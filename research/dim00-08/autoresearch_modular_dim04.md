# AutoResearch 模块化调研 · 维度04：R&D-Agent + AIBuildAI（角色分工与战略-执行分层）

> 调研目标：为"可配置 AutoResearch/AutoOptimization 框架"提炼角色/层级抽象。覆盖三个代表系统：
> **R&D-Agent**（微软，arXiv:2505.14738）、**AIBuildAI / AIBuildAI-2**（UCSD，arXiv:2604.14455 / 2605.27873）、
> **Arbor**（RUC + MSR，arXiv:2606.11926，对照组）。
> 方法：arXiv 全文（R&D-Agent v1/v2 PDF、AIBuildAI/AIBuildAI-2/Arbor HTML）+ 官方 GitHub 仓库代码级阅读（microsoft/RD-Agent、aibuildai/AI-Build-AI、RUC-NLPIR/Arbor），共 17 次独立检索/阅读。

---

## 1. 各系统核心机制

### 1.1 R&D-Agent：两阶段六组件 + Researcher-Developer 主循环 + 多 trace 并行/合并

#### 1.1.1 框架分解：两阶段、六个可替换组件

R&D-Agent v2 将 MLE（机器学习工程）流程形式化为 **Research 阶段（4 组件）+ Development 阶段（2 组件）**，每个组件给出"LLM-first 简单基线"，已有系统（AIDE、ML-Master、MLE-STAR、KompeteAI）均可被定位为该框架某单一组件上的部分优化 [^1^]：

| # | 组件（Framework Concept） | 职责 | SOTA 配置（Module Design） |
|---|---|---|---|
| ❶ | FC-Planning | 探索算力/策略随时间的分配，探索-利用权衡 | 动态规划：早期（~1h）限制算力禁用集成/CV，后期（~4h）放开；早期鼓励新颖性，后期聚焦打磨已验证方案 [^1^] |
| ❷ | FC-Exploration Path Structuring | 解的组织结构与历史引用关系（链/树/DAG） | 自适应 DAG：第一层最大化多样性建立不同方向，分支内贪心利用、剪枝次优路径，最后阶段合并 [^1^] |
| ❸ | FC-Reasoning Pipeline | 记忆→具体想法的转换（问题识别→假设→可实现 idea） | 科学多步推理：分析当前解与数据特性→定位关键问题→提出假设→输出可实现 idea；**虚拟评估**（一次生成多个 idea，LLM 打分只送最优者进开发） [^1^] |
| ❹ | FC-Memory Context | 历史解、评估结果、洞见的存取与复用 | 协同记忆：分支独立探索，假设生成后注入"全分支最优 idea + 按主题相似度/分数/新近度概率采样的他人 idea"，LLM 再筛选 [^1^] |
| ❺ | FC-Coding Workflow | 概念→无 bug 代码 | 采样数据上快速原型迭代调试，通过后才在全量数据运行 [^1^] |
| ❻ | FC-Evaluation Strategy | 可靠、可比的性能评估 | 运行前固定 train/val/test 切分（test 不可见）；跨分支取 top 解在统一验证集/统一指标下聚合评估再选提交 [^1^] |

#### 1.1.2 代码级模块结构（microsoft/RD-Agent）

仓库分层非常清晰：`rdagent/core`（框架抽象）/ `rdagent/components`（可复用组件，如 CoSTEER coder、workflow）/ `rdagent/scenarios`（场景实现：qlib、data_science、kaggle 等）/ `rdagent/app`（入口配置）/ `rdagent/oai`（LLM 后端）/ `rdagent/log`、`rdagent/utils` [^3^]。

**core 层的关键抽象类** [^4^][^5^][^10^]：

- `Hypothesis`（hypothesis/reason/concise_* 字段）、`ExperimentFeedback(decision, reason, exception)` / `HypothesisFeedback(observations, hypothesis_evaluation, new_hypothesis)` —— R→D→R 的消息载体；
- `Trace`：**全局搜索状态**。`hist: list[(Experiment, ExperimentFeedback)]` + `dag_parent: list[tuple[int,...]]`（DAG 父指针；`NEW_ROOT=()` 表示开新子 trace；`SEL_LATEST_SOTA=(-1,)` 语法糖）+ `current_selection` + 可选 `KnowledgeBase`；
- 角色接口（均为 ABC）：`ExpPlanner.plan(trace)`、`HypothesisGen.gen(trace, plan)`、`Hypothesis2Experiment.convert(hypothesis, trace)`、`ExpGen.gen(trace)`（≈ 前两者的复合）、`Experiment2Feedback.generate_feedback(exp, trace)`；选择器接口 `CheckpointSelector.get_selection(trace)` / `SOTAexpSelector.get_sota_exp_to_submit(trace)` [^4^]；
- D 侧演化内核：`EvolvingStrategy.evolve_iter(evo, queried_knowledge, evolving_trace)`（生成器，逐步产出部分解）、`IterEvaluator.evaluate_iter()`（与演化步交错的生成器式部分评估）、`RAGStrategy.query/generate_knowledge/dump`（知识自演化，文件锁支持多 coder 共享知识库）；`RAGEvoAgent.multistep_evolve()` 把"RAG 查询→演化→评估→追加 `EvoStep` 到 evolving_trace→知识自生成→finished 判定"串成 CoSTEER 开发循环 [^5^][^10^]。

**data_science 场景主循环**：`DataScienceRDLoop`（继承 `RDLoop`/`LoopBase`）的步骤序列由 `LoopMeta` 元类自动收集为 [^7^]：

```
steps = [direct_exp_gen, coding, running, feedback, record]
```

每步职责：`direct_exp_gen`（CheckpointSelector 选父节点 → `exp_gen.async_gen(trace, loop)` 产出 DSExperiment）；`coding`（按 hypothesis.component 分派给 6 个 CoSTEER coder 之一：DataLoader / Feature / Model / Ensemble / Workflow / Pipeline）；`running`（`DSCoSTEERRunner` 全量执行）；`feedback`（LLM 总结成败 decision）；`record`（`trace.sync_dag_parent_and_hist()` 写回 DAG、选提交 SOTA、知识库 dump、连续失败重置 trace）[^7^]。

#### 1.1.3 主循环伪代码（依据 loop.py / evolving_agent.py 重建）

```python
# ===== R&D-Agent 单进程异步主循环（LoopBase.run）=====
trace = DSTrace(scen, knowledge_base)          # 全局状态：DAG + 知识库
while not timer.is_timeout():
    # --- R 侧：提议 ---
    selection = ckp_selector.get_selection(trace)      # 或 TraceScheduler.next(trace)
    exp  = await exp_gen.async_gen(trace, loop)        # Planner→科学推理(问题→假设→idea)
                                                       # →虚拟评估选 1 个→Hypothesis2Experiment
    # --- D 侧：实现与执行 ---
    exp  = coder.develop(exp)        # CoSTEER: 采样数据上 evolve_iter/evaluate_iter 迭代调试
    exp  = runner.develop(exp)       # 全量数据运行，得到 result
    fb   = summarizer.generate_feedback(exp, trace)    # decision=True/False + 原因
    # --- 写回（串行化）---
    trace.sync_dag_parent_and_hist((exp, fb), loop_id) # record 步，semaphore=1
    kb.dump()                                          # 知识自演化
sota = sota_exp_selector.get_sota_exp_to_submit(trace) # 聚合评估选提交
```

并行模型：`LoopBase` 用 asyncio 实现 **kickoff_loop + N 个 execute_loop 协程**；每步有独立信号量，且 `record`/`feedback` 强制 `limit=1`（"record 步负责修改全局环境"，避免并行写 DAG 的不一致）；ExpGen 内部用 `loop.get_unfinished_loop_cnt() < max_parallel` 控制yield节奏；每个实验携带 `local_selection` 实现多 trace 交错扩展 [^6^][^7^]。

#### 1.1.4 多并行 exploration trace 与合并

- **多 trace 调度**（`trace_scheduler.py`）：`TraceScheduler` 抽象 + 多种实现——`RoundRobinScheduler`、`ProbabilisticScheduler`（softmax 势函数）、`TraceLengthScheduler`、`SOTABasedScheduler`、`RandomScheduler`、`MCTSScheduler`（PUCT 打分，`observe_feedback` 沿祖先路径回传 value）。所有调度器统一规则：子 trace 数不足 `max_trace_num` 时返回 `NEW_ROOT` 开新 trace，否则选一个"未被扩展中"的 leaf 作为父节点 [^9^]。
- **合并**（`merge.py`）：时间触发型——剩余时间 < `merge_hours` 后进入合并阶段（同时禁用连续失败重置）。`MergeExpGen` 取两条 trace 叶子的 SOTA 实验，构造 `PipelineTask` 让 LLM 把"被合并解"的成功改动融入最优解工作区（`inject_code_from_file_dict` 注入 SOTA 代码作为起点），合并后继续沿用最后一条 trace 打磨；`ExpGen2Hypothesis`（V3）则先从各分支成功实验中**生成合并假设**再实现 [^8^]。
- v1 报告的多 trace 实验协议：两条独立 trace（不同 prompt/知识库/工具链）各跑 11h，第二条启动时可读第一条的失败历史以避免重复；最后 2h 融合代码模块、idea 与双 trace 反馈，最终用"验证性能+鲁棒性+过拟合风险"的复合评分选提交 [^2^]。RD-Agent(Q) 场景还用 **multi-armed bandit 调度器**做因子/模型方向的自适应选择 [^16^]。

#### 1.1.5 消息流

```
Scenario ──► Researcher(ExpGen): Trace(DAG+KB) → Hypothesis → DSExperiment(pending_tasks)
Researcher ──► Developer(CoSTEER coder): idea 文本 + 工作区
Developer 内部: EvolvingStrategy ⇄ IterEvaluator（采样数据上的步进式代码/反馈对）
Developer ──► Runner: runnable solution → 全量运行 → result
Runner ──► Summarizer(Experiment2Feedback): exp+trace → ExperimentFeedback(decision, reason)
Feedback ──► Trace.record: 写 DAG；─► KnowledgeBase: 蒸馏新知识（下一轮 RAG query 可用）
```

---

### 1.2 AIBuildAI：Manager + Designer/Coder/Tuner 的层级分工与 multi-start

#### 1.2.1 总体结构

AIBuildAI 把"自动构建 AI 模型"显式建模为 **multi-start local search**：初始化 n=7 个相互隔离的 solution repository（`repo_i = {data_i, plan_i, code_i, config_i, result_i}`，各自含数据副本），每个 repo 是一条根本不同的建模路线，迭代做增量改进，结束时选择/集成最强者 [^11^]。

Agent 抽象：agent = (prompt, tool set)，控制循环为"LLM 输出含工具调用→环境执行→observation 追加进上下文"直到无工具调用 [^11^]。层级化方式：**子 agent 作为 manager 工具集里的工具**（`designer_i, coder_i, tuner_i, read_i`），manager 通过长上下文推理全量执行历史来决定"对哪个 repo 调用哪个子 agent" [^11^]。

```
SetupAgent(一次) → Manager ┬─ designer_i: read_i, write_i, search(web)   → 产出/修订 plan_i
                           ├─ coder_i:    read_i, write_i, execute_i    → plan→code，短跑验证+调试到无 bug
                           ├─ tuner_i:    read_i, write_i(config), execute_i → 训练、读日志、调超参（短时预跑→全程训练）
                           └─ read_i (i=1..n)：跨 repo 只读比较
                       → AggregatorAgent(一次, repo_{n+1}): 选最优或加权集成（rank blending / 概率图加权 / 加权平均），不重训、不改中间产物
```

关键机制 [^11^]：

- **异步并发调度**：manager 的工具调用是异步的，可跨 repo 并行发出多个调用，设计/实现/训练在不同 repo 上交叠执行；
- **repo 作用域工具**：`read_i/write_i/execute_i` 绑定到单个 repo，coder/tuner **无权访问其他 repo**——隔离是强制的，跨候选比较只发生在 manager（只读）与 aggregator（只读 + 写 repo_{n+1}）；
- **上下文经济学**：子 agent 各自维护专注的工作上下文（coder 记录历史尝试避免重蹈，tuner 只拿 coder 的最终正确代码），manager 保持紧凑上下文以维持全局控制流——用层级分解对抗"context explosion" [^11^]；
- **局部搜索语义**：repo 一旦初始化，改进是增量式而非重设计（manager 通过 designer 修订 plan 实现"方向修正"）；表现差/相似的 repo 通过"不再对其发出动作"被隐式淘汰 [^11^]；
- **tuner 的时间预算**：manager 给 tuner 最大调参时间，先用短跑获取早期信号，停滞即换配置，后期把有前途的配置跑满 [^11^]。

实际运行样例（alaska2-image-steganalysis）：manager 调 designer 提出 6 个候选方案 → 审阅后选 4 个 → coder/tuner 实现训练 → 依据结果让 designer 修订候选 2（去掉 stride surgery 回到 vanilla EfficientNet-B4）→ 再过 coder/tuner → aggregator 构造 4 模型 rank-based 集成 [^11^]。

#### 1.2.2 主循环伪代码（依据 Methods §4.2–4.7 重建）

```python
# ===== AIBuildAI 主循环 =====
setup_agent(task_desc)                       # conda 环境
repos = [Repo(data=copy(D)) for _ in range(n)]        # n=7 multi-start
manager = Agent(prompt=p_manager,
                tools={read_i} ∪ {designer_i, coder_i, tuner_i})
while not budget_exhausted:                  # manager 单控制循环
    obs = [read_i(repos[i]) for i in focused]          # 读各 repo artifacts
    actions = manager.decide(obs)            # 异步、可并行：{(repo_j, subagent_j, instructions)}
    for (j, sub, instr) in actions:          # 子 agent 是 manager 的工具
        dispatch_async(sub, repos[j], instr) # 子 agent 内部多轮 LLM+工具，写回本 repo
aggregator({result_i}) → repo_{n+1}          # 选最优 or 加权集成 → submit
```

官方 README 的架构图进一步给出**消息协议细节**：manager 每步输入"competition context + workflow state + 决策规则（setup/designer/coder/tuner/reviser/judge/stop）"，输出"单个 action call（含 reason 与 instructions）"；每个子 agent 以 **report JSON** 汇报（designer report：候选 plan 选项；coder report：quick test 结果与产物清单；tuner report：改动、与历史结果对比；aggregator report：集成后验证分数）；并行轨迹记为 `D₁→C₁→T₁→…✓ / D₂→C₂→T₂→…✗`；输出目录为 `candidate_1..N/ + checkpoint.pth + inference.py + submission.csv` [^13^]。注意：AIBuildAI **二进制发布、代码闭源**（仓库仅含 tasks/ 示例与发行包），接口细节以论文 + README 为准 [^13^]。

#### 1.2.3 AIBuildAI-2：~1000 文档的分层演进知识库

2.0 在相同骨架上加入**两级知识系统**（agentic RAG 风格动态加载）[^12^]：

- **L1（顶层，人工撰写）**：~30 个主题类目（按任务/模态：vision、NLP、时序、表格、分子；按通用策略：集成技术等），每个类目一条 high-level knowledge instruction + 指向 L2 的指针索引；**L1 索引默认进入每次 agent 调用**，agent 按当前任务与 repo 状态条件性检索相关类目的 L1 值；
- **L2（底层，专家查阅库）**：~1000 篇 low-level 知识文档（如某类数据的特征提取配方、某类模型的调优技巧），仅当 agent 判定需要更细粒度知识时才取；
- **初始化**：爬取/去重/清洗 web 来源（技术博客、库文档、精选开源仓库），蒸馏进 L2，再从 L2 综合出各类目 L1 指令；
- **持续演进（双 builder agent）**：每次 run 结束后，**L2 builder** 分析完整执行轨迹（设计决策、尝试过的实验、失败、最优策略）产出结构化 takeaway 追加到相关类目 L2；**L1 builder** 用 takeaway 增量更新 L1 指令。同样流程用于吸收新竞赛 write-up/博客/库更新 [^12^]。

效果：MLE-Bench 奖牌率 63.1%（v1，Claude Opus 4.6，n=7，24h/A100）→ **70.7%（v2）**；心脏病预测竞赛 4370 队中 top 6.6%；OpenADMET 盲测 103 队第 40（MA-RAE 0.6300，v1 为 0.7000 排 61，MLEvolve 0.6735 排 53）——v1↔v2 的同骨干对比构成"知识系统"的准消融证据 [^11^][^12^]。v2.5 又加跨 run 记忆（`aibuildai memorize`）、run replay、MCP 研究工具 [^13^]。

---

### 1.3 Arbor（对照）：coordinator-executor 与假设树精修（HTR）

Arbor 把自治研究形式化为 **Autonomous Optimization (AO)**：`P=(M₀, O, E_dev, E_test)`，目标是在不以 E_test 为探索 oracle 的约束下返回 `argmax S_test(M')` [^14^]。

**核心机制**：

- **假设树 = 持久研究状态**：节点 `n = ⟨h_n（假设）, ι_n（洞见）, μ_n（元数据：状态/dev 分数/结果记录/git 分支引用）⟩`；内部节点是抽象方向，叶子是可执行干预；artifact 本体不进树（只存引用），树同时充当搜索前沿、长期记忆与审计轨迹 [^14^]；
- **Coordinator（长寿命）六步循环**：Observe（读树的结构化投影重新接地）→ Ideate（选父节点提 k 个子假设，以已验证洞见为正面约束、被剪节点为负面约束）→ Select（前沿控制，不只是分数最大化）→ Dispatch（并行派给独立 executor）→ Backpropagate（叶→根抽象传播：分数+因果归因+适用条件）→ Decide（继续/剪枝/停止/合并）[^14^]；
- **Executor（短寿命、假设绑定契约）**：输入 `(h_n, 祖先洞见, M_best, E_dev)`，在全新 git worktree 中实现该假设、跑 dev 评估、自修复实现（**h_n 固定不可改**），返回四元组 `(dev score, 事实结果, 蒸馏洞见, 分支引用)`。契约的意义：若允许 executor 中途改假设，返回分数就不再是"该节点"的证据，祖先洞见将不可解释 [^14^]；
- **held-out merge gate**：候选只有在 E_test 上超过当前最优才 merge 进 M_best——把"dev 上的探索性改进"与"可迁移的验证性改进"分开（Terminal-Bench 上 Claude Code dev 75.0 但 test 掉到 71.7，Arbor dev 72.2/test 77.4，证明该 gate 的必要性）[^14^]。

**HTR 主循环（论文 Algorithm 1，照录）**：

```
init Tree=({n0},∅), b_n0←M0, M_best←M0
while budget B left ∧ pending leaves exist:
    V ← Observe(Tree, M_best)                     # 形状/根洞见/已剪教训
    p ← choose parent under V; attach k pending children ← Ideate(p, V)
    L ← pending leaves under Select(V)            # 前沿控制
    {(s_n,r_n,ι_n,b_n)} ← parallel Executor(h_n, ι_anc(n), M_best)   # 隔离 worktree
    for n∈L, a∈path(n0→n): write back (s_n,r_n,ι_n,b_n); ι_a ← Abstract({ι_c})  # 回传
    n† ← argmax s_n
    if O(E_test(b_n†)) > O(E_test(M_best)): M_best ← merge(b_n†)   # held-out 门
    prune falsified subtrees; persist Tree
Executor(h_n, ι_anc, M_best):
    W ← fresh worktree(M_best)
    repeat: Δ ← Implement(h_n, ι_anc, W); (s,r) ← E_dev(apply(Δ,W))  # 只修 Δ，h_n 固定
    until run ok ∧ h_n-path exercised (or cap)
    return (s, r, Distill(h_n,Δ,r), commit(W))
```

**代码结构**（RUC-NLPIR/Arbor）：`src/coordinator/`（`orchestrator.py` ~55KB、`idea_tree.py`、`checkpoint.py`、`convergence.py`、`context_prune.py`、`contamination.py`、`hitl.py`、`prompts.py`、`tools/`）、`src/executor/`（executor agent + CLI）、`src/core/`（共享 ReAct loop、工具、LLM provider、上下文管理）、`src/events/`（类型化事件总线）、`src/plugins/`（领域插件如 `mle_kaggle.yaml`）、`src/skills/`（按需 markdown playbook）、`src/report/`、`src/webui/` [^15^]。默认 20 个 coordinator cycle、树深 2、执行并行度受评估资源约束 [^14^]。

**消融（MLE-Bench Lite，Claude Opus 4.6）**：Full Arbor 81.82% any-medal；**w/o tree（拍平为根下实验队列）→ 63.64%**；**w/o insight feedback（保树但关闭洞见上溯）→ 54.54%**。结论：树结构本身不够，洞见传播才是最大驱动；两者互补——树定义竞争假设的存放与比较位置，洞见反馈决定可复用信息的携带 [^14^]。GPT-5.5 下 MLE-Bench Lite 达 86.36% any-medal / 77.27% gold，为对照中最强；六个 AO 任务全部取得最佳 held-out 结果，平均相对增益 >2.5× Codex/Claude Code；BrowseComp 上演化出的 harness 冻结后迁移到 HLE（25.5→31.5）与 DeepSearchQA（61→69）仍有效 [^14^]。

---

## 2. 角色/层级接口分析（控制面抽象的关键证据）

### 2.1 输入输出契约与状态所有权总表

| 系统 | 角色 | 输入契约 | 输出契约 | 全局状态归属 | 写权限 |
|---|---|---|---|---|---|
| R&D-Agent | Researcher（ExpGen = Planner+HypothesisGen+Hypothesis2Exp） | `Trace`（DAG hist+反馈）、知识库查询结果、scenario 描述 | `Hypothesis` → `DSExperiment`（pending_tasks + local_selection） | **Trace 由 loop 进程持有**，R 只读 | 不可写 trace；提议经 `record` 步（semaphore=1）统一落盘 [^4^][^6^][^7^] |
| R&D-Agent | Developer（CoSTEER coder/runner） | idea 文本 + 实验工作区 + evolving_trace + queried knowledge | 可运行解 + 部分评估反馈（生成器交错） | 自己的 `evolving_trace` | 写实验工作区；知识库经文件锁共享 [^5^][^10^] |
| R&D-Agent | Summarizer（Experiment2Feedback） | exp（含 result）+ trace | `ExperimentFeedback(decision, reason)` | — | 无（record 步代写） |
| R&D-Agent | TraceScheduler / CheckpointSelector / SOTAexpSelector | trace | 父节点选择 / 提交选择 | 读 trace | 仅返回选择，不直接改 [^9^] |
| AIBuildAI | Manager | 任务描述 + 工具描述 + `read_i` 读到的全 repo artifacts | 单个/并行 action call：`subagent_i(instructions)` + reason | **全量 workflow state 在 manager 上下文**；产物在 repos | 仅通过调用子 agent 间接写；自身只读 [^11^][^13^] |
| AIBuildAI | Designer_i | `read_i`（本 repo）+ web search + 知识系统 | 新/修订 `plan_i`（report JSON） | 本 repo | `write_i` 仅本 repo [^11^][^12^] |
| AIBuildAI | Coder_i | 本 repo（尤其 plan_i） | `code_i + config_i`，短跑验证无 bug（report JSON） | 本 repo | `write_i/execute_i` 仅本 repo [^11^] |
| AIBuildAI | Tuner_i | 本 repo（code_i, result_i）+ 时间预算 | 新 `config_i` + `result_i`（report JSON） | 本 repo | `write_i`(config)/`execute_i` 仅本 repo [^11^] |
| AIBuildAI | Setup / Aggregator | 任务描述 / 全 repos 只读 | conda 环境 / repo_{n+1} 最终提交（可集成，不重训） | — | 一次性、确定性 [^11^] |
| AIBuildAI-2 | L1/L2 builder agents | 完成 run 的全执行轨迹 | L2 takeaway 文档 / L1 指令增量更新 | **跨 run 知识系统**（唯一跨任务持久状态） | 写知识系统，不动 run 产物 [^12^] |
| Arbor | Coordinator | 树的结构化投影（前沿+近期证据+祖先洞见+M_best） | 树受控变异：加节点/派发/写证据/传播/剪枝/合并 | **独占假设树** | 唯一可写树；不碰 executor 工作区 [^14^] |
| Arbor | Executor | `(h_n, 祖先洞见, M_best, E_dev)` | `(dev_score, 事实结果, 蒸馏洞见, 分支引用)` | 无（短寿命） | 仅自己的 git worktree；**不可改假设、不可写树** [^14^] |

### 2.2 通信协议对比（这决定"控制面"如何抽象）

1. **R&D-Agent：共享可变状态 + 串行化写回**。R↔D 不直接发消息，而是读写同一个 `Trace`（DAG）。并行安全靠"每步信号量 + record/feedback 强制串行 + local_selection 附着在实验对象上"。知识交换通过知识库的"先 load 他人 dump 再更新"协议。**协议本质：黑板（blackboard）模型** [^6^][^7^][^10^]。
2. **AIBuildAI：工具即子 agent 的 RPC 模型**。子 agent 被包装成 manager 工具集中的 repository-scoped 工具；manager 只看到工具描述（"designer 生成/修订策略"），调用是异步的、可并行；返回物是 artifacts（repo 文件）+ report JSON。**跨候选信息交换只有两个合法通道：manager 的只读 `read_i` 和 aggregator 的只读汇总**——执行层之间零通信 [^11^][^13^]。
3. **Arbor：显式证据契约 + 状态变异窄接口**。coordinator 对树只有六类受控变异；executor 返回恰好四个字段（score/result/insight/branch-ref），多一个不要。"executor 假设绑定"是用契约保证**返回证据对节点可归属（attributable）**，这是树上做抽象传播和剪枝决策正确性的前提 [^14^]。

### 2.3 职能分工 vs 假设分工：三系统谱系

- **纯职能分工（AIBuildAI）**：executor 层按"操作类型"特化（designer/coder/tuner），假设多样性靠 multi-start（n=7 repo）在"对象维度"表达，而非 executor 维度。分工理由是**上下文经济学**：每类操作的中间推理互不相关，拆开可避免 context explosion，且每步修改的复杂度不再受"单次 LLM 调用"限制（子 agent 内部可多轮）[^11^]。
- **纯假设分工（Arbor）**：executor 同质（同一 ReAct agent），按"一个假设一个 executor"分工；分工理由是**证据可归属性**——分数必须能唯一归因到树节点，洞见才能沿树抽象成可复用约束 [^14^]。
- **混合（R&D-Agent）**：R/D 大阶段是职能分工（对应两类反馈：性能反馈→想法、错误反馈→代码 [^2^]），D 内部再按 pipeline 组件职能分工（6 个 CoSTEER coder）；而 R 侧的 DAG 多 trace 是假设分工，trace 间靠协同记忆与定时合并交换信息 [^1^][^7^][^8^]。

---

## 3. 关键设计决策与权衡（含消融证据）

### 3.1 R&D-Agent 消融（40 竞赛子集，GPT-5；Any Medal 全系统 35.1%）[^1^]

| 消融 | 结果 | 解读 |
|---|---|---|
| w/o Planning（动态→无时变基线） | 26.7%（-24%）；First-Medal 1.7h 反而更快 | 无时间维资源编排会早陷局部最优；"先便宜后昂贵"的算力课程是免费午餐 |
| **w/o Exploration Path（DAG→链）** | **25.3%（-28%，最大跌幅）**；平均 loop 数 45.9→19.4 | 树/DAG 结构是最关键优势；链式（MLE-STAR 式）搜索量与多样性双输 |
| w/o Reasoning Pipeline（多步科学推理→一步） | 26.7%（-24%）；Improve Rate 41.1%→23.0%（loop 数 55.3 最高） | 堆量不如提质：结构化"问题→假设→idea"推理 + 虚拟评估把每次 loop 的命中率翻倍 |
| w/o Memory Context（协同记忆→简单记忆） | 32.0%（-9%，最小跌幅） | 跨分支记忆是增强而非地基；验证了"基础组件 vs 增强组件"的分层 |
| w/o Coding Workflow（采样调试→全量调试） | 24.0% 且全程持续落后（时序曲线） | 采样数据快速原型是 D 侧最大杠杆；全量调试的算力开销直接压缩探索量 |
| w/o Evaluation Strategy（聚合评估→基线） | 30.7%，2h 后才分化 | 解变复杂后，统一切分+跨分支聚合评估才成为瓶颈（防"评估噪声当进步"） |
| 参照：Perfect Selection oracle | 37.3%；全系统 34.7% ≈ oracle 的 93% | 解池上限与选择机制的差距仅 ~7%，提交选择接近打满 |

另：MLE-Bench 主结果 35.1%（GPT-5）/ 29.7%（o3(R)+GPT-4.1(D) 异构分工），ML-Master 同环境 GPT-5 复评仅 16.9%——框架设计而非模型选择构成主要差距 [^1^]。**异构模型分工**（推理强的模型做 R、指令遵循强的做 D）以更低成本达到接近最强配置 [^1^][^2^]。

### 3.2 AIBuildAI 的设计决策与权衡

- **子 agent 化 vs 单调用算子**：AIRA/MLEvolve 的 Draft/Debug/Improve 是单次 LLM 调用，每步修改复杂度受单调用上限约束；AIBuildAI 把每类操作实例化为可多轮推理+工具的子 agent——作者明确指出这是跨任务高质量解的关键因子 [^11^]。
- **代价**：多子 agent 层级显著增加 token 消耗（每子 agent 多轮调用 + 层级间反复通信）；作者提出 dynamic LLM routing（简单操作给小模型）作为降本方向 [^11^]。
- **知识系统准消融**（v1→v2，同骨架同骨干）：MLE-Bench 63.1%→70.7%（+7.6pt）；ADMET 盲测 MA-RAE 0.7000→0.6300（排名 61→40/103）；且相对"web-search 检索"（v1）与"静态知识库"（MLEvolve）两种知识方案均优——**分层索引 + 动态加载 + run 后蒸馏回写**三者构成的知识系统，在分子等 LLM 参数知识稀疏的领域收益最大 [^11^][^12^]。
- **multi-start n=7 + 隐式淘汰**：无显式早停算子，靠 manager"不再派发动作"回收预算——把剪枝委托给 manager 的长上下文判断，省了机制但依赖模型能力 [^11^]。

### 3.3 Arbor 的设计决策与权衡 [^14^]

- **树 + 洞见反馈缺一不可**：w/o tree 63.64%、w/o insight 54.54%（full 81.82%）——层级只是语法，上溯的洞见才是语义记忆；"证据能在树上累积"是树有用的前提。
- **held-out merge gate 防过拟合**：dev/test 分离的入场机制使 Arbor 在 dev 分数不占优时仍拿到最佳 held-out（Terminal-Bench 例）；高 dev 低 test 候选被当作"该方向在利用反馈信号"的证据而非成功。
- **executor 假设绑定 vs 自由度**：牺牲 executor 的临场改方向自由，换取分数-假设的可归因性与祖先洞见的可解释性。
- **成本**：与单 agent 基线相比 token 预算未显著增加（§5.8），增益来自搜索过程组织而非算力堆叠；框架层 model-agnostic，但经验上限取决于任务-骨干匹配（BrowseComp 上 Opus 4.6 最佳，MLE-Bench Lite 上 GPT-5.5 最佳）。

### 3.4 跨系统权衡小结

1. **全局状态放哪**：黑板（RD-Agent Trace/DAG）vs 控制器上下文（AIBuildAI manager）vs 显式外部树（Arbor）。前两者把状态塞进 LLM 上下文或共享内存，Arbor 显式把状态外化为 LLM 可读写的持久结构——长程可审计性最强，且 coordinator 上下文压缩后仍能以树为权威状态重新接地 [^14^]。
2. **剪枝/合并的触发**：规则+时间触发（RD-Agent merge_hours、连续失败重置）vs LLM 自由裁量（AIBuildAI manager）vs LLM 裁量 + held-out 硬门（Arbor）。趋势是"软决策交给 LLM，硬保证（预算、dev/test 纪律、串行写）留给机制"。
3. **失败利用**：RD-Agent 把失败写进 DAG 并供下一条 trace 读取（失败历史避免重复）[^2^]；AIBuildAI 失败只留在本 repo 上下文 + v2 蒸馏进知识库 [^12^]；Arbor 把失败蒸馏为"负面约束"沿树上溯，是三类中最结构化的失败利用 [^14^]。

---

## 4. 八轴卡

| 轴 | R&D-Agent | AIBuildAI (1.0/2.0) | Arbor |
|---|---|---|---|
| **优化对象** | 完整 DS pipeline 代码（数据加载/特征/模型/集成/工作流组件）+ 量化因子/模型 | 完整 solution repo（plan+code+config+checkpoints） | 任意研究 artifact（训练代码、harness、数据合成 pipeline） |
| **基本搜索单元** | (Hypothesis, Experiment, Feedback) 三元组节点，DAG 组织 | solution repository（multi-start 的局部搜索起点） | 假设树节点 ⟨h, ι, μ⟩（假设+洞见+artifact 引用） |
| **算子** | 提议（问题→假设→idea+虚拟评估）、组件级 CoSTEER 编码、运行、反馈、合并、知识蒸馏 | designer 生成/修订 plan、coder 实现/调试、tuner 训练/调参、aggregator 选择/集成、（2.0）知识检索/蒸馏 | Ideate/Select/Dispatch/Backpropagate/Decide + executor Implement-Repair + merge gate |
| **拓扑** | 自适应 DAG：首层多 trace 多样性→分支内贪心→定时合并；调度器可插拔（RR/softmax/MCTS-PUCT） | 星型：manager—(n=7 repo × 3 职能子 agent)；repo 间无边 | 假设树（默认深 2，k 分支）：内部节点=方向、叶子=干预；并行兄弟假设 |
| **持久状态** | Trace DAG + 知识库（idea pool，可跨进程 dump/load） | 各 repo artifacts + manager 上下文；（2.0）跨 run L1/L2 知识系统 | 假设树（分数/结果/洞见/分支引用）+ M_best |
| **反馈权限** | R 吃性能反馈、D 吃错误反馈；feedback/record 串行化保证一致性 | 子 agent 只见本 repo 反馈；跨 repo 比较仅 manager/aggregator 只读 | executor 只用 E_dev；E_test 仅 merge gate；coordinator 独占全部证据 |
| **失败利用** | 失败写 DAG、异常进 feedback、连续失败重置/重分析；新 trace 读旧失败史 | coder 上下文记录失败尝试；2.0 将失败蒸馏为知识文档 | 失败蒸馏为负面约束洞见上溯，剪枝证伪子树 |
| **并行与选择** | asyncio 协程并行 loop；per-step 信号量；CheckpointSelector/TraceScheduler 选父，聚合评估+SOTAexpSelector 选提交 | manager 异步并行工具调用；隐式淘汰（停止派发）；aggregator 选/集成 | 兄弟假设并行 executor；Select 做前沿控制；held-out 门选 M_best |

---

## 5. 对统一框架的接口启示：让"职能分工"与"假设分工"成为同一接口的两种配置

三个系统在工程上收敛到同一个两层骨架：**一个拥有全局状态与决策权的控制器 + 一组在隔离工作区内干活、返回结构化证据的执行器**。差异只在三个配置点上。建议的统一抽象：

### 5.1 控制面（Controller）= 状态持有者 + 决策算子组合

```
Controller 持有: ResearchState S（RD-Agent 的 Trace-DAG ≈ Arbor 的假设树 ≈ AIBuildAI 的 repo 集合+workflow state）
每 cycle 执行可插拔算子链:
  Observe(S) → Plan(t, S) → Select(S) → Dispatch(units) → Absorb(evidence) → Admit(gate) 
对应: Arbor 六步; RD-Agent 的 exp_gen/scheduler/record/sota_select; AIBuildAI manager 的 read→decide→(隐式淘汰/聚合)
```

- **状态 S 必须外化、持久、可投影**：三系统一致教训（Arbor Observe 步骤、RD-Agent session dump/load、AIBuildAI manager 上下文爆炸问题）是控制器上下文不可靠，应把 S 做成"可序列化、可结构化投影进 prompt"的一等对象。DAG/树/repo 集合是同一抽象（节点=假设×artifact×证据）的不同拓扑配置。
- **决策分两层**：软决策（提议、选择、剪枝、合并时机）交给 LLM 策略；硬保证（预算计时、dev/test 隔离、写回串行化、并行上限）做成框架机制。RD-Agent 的 record 信号量、Arbor 的 merge gate、AIBuildAI 的 repo 作用域工具都是"机制层硬保证"的实例，可直接复用。

### 5.2 执行面（Executor）= 有界工作区 + 结构化返回契约

```
Executor(spec, workspace, budget) -> Evidence{score, artifacts_ref, insight, log}
spec = (hypothesis, role, ancestor_context)   # 三元组，两个维度可独立开关
```

- **假设维度开关**：`hypothesis=None` → 执行器自由发挥（AIBuildAI 子 agent 模式）；`hypothesis=h_n` 且冻结 → 证据可归因（Arbor 模式，支撑树上抽象传播/剪枝）。
- **职能维度开关**：`role ∈ {designer, coder, tuner, ...}` 决定工具集与提示词（AIBuildAI 模式；RD-Agent D 侧的 6 个 CoSTEER coder 同样是 role 维度的配置）；`role=general` → 同质执行器（Arbor 模式）。
- **由此，"职能分工"= role 异质 + hypothesis 冻结关闭 + 对象级 multi-start；"假设分工"= role 同质 + hypothesis 冻结开启**。R&D-Agent 是两者的积（R/D 大 role + D 内组件 role + R 侧 DAG 假设维）。统一框架只需把 `spec=(role, hypothesis, context_scope)` 作为执行器签名的三个独立配置轴。
- **返回契约四元组是公约数**：`(可比分数, 事实结果, 蒸馏洞见, artifact 引用)`——Arbor 显式、RD-Agent 的 ExperimentFeedback+EvoStep 隐式同构、AIBuildAI 的 report JSON + result_i 同构。蒸馏洞见字段是跨 run/跨分支知识复用的载体（AIBuildAI-2 的 takeaway、Arbor 的 ι、RD-Agent 的 knowledge_base），消融一致显示它是"增强轴上收益最大"的字段。

### 5.3 并行与合并的两个可配置旋钮

1. **并行调度**：固定规则（RD-Agent RoundRobin/MCTS 调度器、merge_hours 定时合并）↔ LLM 裁量（AIBuildAI manager 异步并行、隐式淘汰）。建议接口：`Scheduler.next(state) -> selection`（RD-Agent 已有此 ABC），LLM-as-scheduler 只是其实现之一；写回路径必须串行化或加锁。
2. **合并/准入**：定时触发+LLM 融合（RD-Agent MergeExpGen）↔ 结束时选择/集成（AIBuildAI aggregator）↔ 持续 held-out 门（Arbor）。统一为 `Admit(candidate, incumbent, gate)`：gate 可以是聚合验证集评估（RD-Agent ❻）、验证分数集成（AIBuildAI）、或 E_test 硬门（Arbor），dev/test 纪律应做成 gate 的内置约束而非 prompt 约定。

### 5.4 知识/记忆作为正交的服务层

三系统都把记忆做成了 RAG 式服务（RD-Agent `RAGStrategy.query/generate_knowledge/dump`；AIBuildAI-2 L1 索引常驻+L2 条件加载+builder 回写；Arbor 树上洞见抽象）。统一框架应把 KnowledgeService 独立成层：`query(state)→context` 与 `absorb(trace)→updates` 两个方向都可插拔，且消融证据（RD-Agent -9%、Arbor -27pt、AIBuildAI +7.6pt）表明：**跨单元"蒸馏洞见"的传播比原始历史的堆积更重要**——记忆层的最小接口应以"洞见"而非"日志"为数据单元。

---

## 6. 参考来源

- [^1^] R&D-Agent v2: *R&D-Agent: An LLM-Agent Framework Towards Autonomous Data Science*, arXiv:2505.14738v2（六组件框架、MD 配置、消融表 3、时序消融图 3、MLE-Bench 35.1%）. https://arxiv.org/pdf/2505.14738v2
- [^2^] R&D-Agent v1: arXiv:2505.14738v1（Researcher/Developer 双角色设计原则、多 trace 并行/信息交换/融合协议）. https://arxiv.org/pdf/2505.14738
- [^3^] microsoft/RD-Agent 仓库目录（rdagent/{core,components,scenarios,app,oai,log,utils}）. https://github.com/microsoft/RD-Agent/tree/main/rdagent
- [^4^] rdagent/core/proposal.py（Hypothesis/Trace/ExpPlanner/HypothesisGen/Hypothesis2Experiment/Experiment2Feedback/CheckpointSelector/SOTAexpSelector）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/core/proposal.py
- [^5^] rdagent/core/evolving_agent.py（RAGEvoAgent.multistep_evolve）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/core/evolving_agent.py
- [^6^] rdagent/utils/workflow/loop.py（LoopBase 异步并行、per-step 信号量、record/feedback 串行、session dump/load）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/utils/workflow/loop.py
- [^7^] rdagent/scenarios/data_science/loop.py（DataScienceRDLoop 五步、6 个 CoSTEER coder 分派、record 逻辑）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/scenarios/data_science/loop.py
- [^8^] rdagent/scenarios/data_science/proposal/exp_gen/merge.py（MergeExpGen/ExpGen2Hypothesis/ExpGen2TraceAndMergeV1-V3，merge_hours 触发）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/scenarios/data_science/proposal/exp_gen/merge.py
- [^9^] rdagent/scenarios/data_science/proposal/exp_gen/trace_scheduler.py（TraceScheduler ABC、RoundRobin/Probabilistic/SOTABased/MCTSScheduler PUCT）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/scenarios/data_science/proposal/exp_gen/trace_scheduler.py
- [^10^] rdagent/core/evolving_framework.py（EvolvingStrategy/IterEvaluator/RAGStrategy/EvoStep）. https://raw.githubusercontent.com/microsoft/RD-Agent/main/rdagent/core/evolving_framework.py
- [^11^] AIBuildAI: *An AI Agent for Automatically Building AI Models*, arXiv:2604.14455（manager/designer/coder/tuner/aggregator、n=7 multi-start、异步工具调用、repo 作用域工具、63.1% MLE-Bench、AIRA/MLEvolve 对比）. https://arxiv.org/html/2604.14455v1
- [^12^] AIBuildAI-2: *A Knowledge-Enhanced Agent for Automatically Building AI Models*, arXiv:2605.27873（L1~30 类目/L2~1000 文档、动态上下文加载、L1/L2 builder、70.7%、心脏病 top 6.6%/4370、ADMET 40/103）. https://arxiv.org/html/2605.27873v1
- [^13^] aibuildai/AI-Build-AI GitHub README（架构图与 report JSON 协议、闭源二进制发布、v2.5 cross-run memory/memorize/replay、输出目录结构）. https://github.com/aibuildai/AI-Build-AI
- [^14^] Arbor: *Toward Generalist Autonomous Research via Hypothesis-Tree Refinement*, arXiv:2606.11926（AO 形式化、HTR Algorithm 1、六步循环、executor 契约、merge gate、消融表 4/5、MLE-Bench Lite 86.36%、迁移实验）. https://arxiv.org/html/2606.11926v1
- [^15^] RUC-NLPIR/Arbor GitHub（src/{core,executor,coordinator,events,plugins,skills,report,webui}；coordinator/orchestrator.py、idea_tree.py 等）. https://github.com/RUC-NLPIR/Arbor
- [^16^] R&D-Agent-Quant: arXiv:2505.15155（RD-Agent(Q) 的 Research/Development/Feedback 三段式 + multi-armed bandit 调度器）. https://arxiv.org/pdf/2505.15155
- [^17^] RD-Agent 文档（Co-STEER：scheduling agent + implementation agent 协同演化，arXiv:2407.18690）. https://rdagent.readthedocs.io/
