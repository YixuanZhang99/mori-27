# M2 Operator（算子模块）统一设计空间卡片

> 任务：为 AutoResearch/自进化 agent 框架的 M2（从既有候选产生新候选的机制——变异/交叉/重写/反思等）重挖设计维度，产出设计空间卡片，供后续建立"轴系→统一实现"。
> 卡片格式：【设计内容（公式/字段/伪代码级）| 量化证据（一手来源）| 对统一设计的启示】。推断标【推断】。
> 一手来源：`dim01`(AIDE/AIRA-dojo, arXiv:2502.13138 / 2507.02554)、`dim02`(ML-Master/Reflexion/ACE)、`dim03`(MARS, arXiv:2602.02660)、`newworks_groupB`(DGM 2505.22954 / AIDE² / Simple Baselines 2602.16805)、`newworks_groupE`(OpenEvolve/ShinkaEvolve)、`newworks_groupA`(OpenRSI/prime-agent)、`CODE-BORROWING.md`；Web 补：GEPA(2507.19457)、EvoPrompt(2309.08532)、PromptBreeder(2309.16797)、ShinkaEvolve 论文(2509.19349)。

---

## A. 算子集构成（类型化的最小完备集）

### 卡 A1. 四算子基准集 {Draft, Improve, Debug, Crossover}

【设计内容】
- **Draft**（0 元）：从头生成候选，输入=(task_desc, 记忆摘要, data_preview)；
- **Improve**（1 元）：对父候选做"恰好一个原子改动"（AIDE D2 的 prompt 约束：每条边性能变化可归因）；
- **Debug**（1 元）：修复 buggy 候选，保持原思路，消费错误日志/traceback；
- **Crossover**（2 元）：重组两个父候选。
OpenRSI 论文称之为 "a unified action space for code evolution"，且**训练（SFT/RL）与推理搜索共享同一动作空间**。AIRA-dojo 中统一签名：`op(llm, cfg, memory_op, task_desc, journal, *input_nodes, step_count, remaining_time) -> completion`，0/1/2 元对应 `o: 2^𝒮→𝒮`；所有算子共享 `execute_op_plan_code` 包装器（生成→抽取 plan/code→失败重试 `max_operator_tries` 次→剥离 thinking tags）。

【量化证据】
- OpenRSI/Frontis-MA1（newworks_groupA §4）：四算子在 OpenMLE-Evo 搜索中驱动 MLE-Bench 结果，并支撑 35B meta-evolution 模型的 RL 训练。
- AIRA 控制实验（arXiv:2507.02554, E3/E4/E5）：固定 𝒪_AIDE（无 crossover）时 MCTS/evo 相对 greedy 无增益（36.4–39.6% 持平）；升级到 𝒪_AIRA 后 greedy 45.45% vs 39.77%（+14% 相对），且 MCTS 在 19h 后才拉开差距——**算子质量是瓶颈，搜索拓扑不是**。
- Simple Baselines（arXiv:2602.16805）：单算子 generate（整文件生成）+ SCS（条件上一代 3 程序）即在三个域匹配/超过 ShinkaEvolve/AIDE——类型化算子库的收益必须在固定预算、固定领域知识下证明增量。

【对统一设计的启示】
1. M2 的最小完备默认集 = 四算子（0/1/2 元齐备，已获 OpenRSI 与 AIRA 独立印证）；算子接口 = 纯函数 + 依赖注入（LLM、memory_op、预算信息），arity 可变。
2. "每边一个原子改动"应作为 improve 的默认语义约束（可归因性），但做成可关配置。
3. 内置"退化投影"自检：任何花哨算子配置必须跑赢 IID-RS/SCS 式单算子基线，否则默认裁掉（奥卡姆剃刀）。

### 卡 A2. 变异表示：diff（SEARCH/REPLACE）vs 全文重写 vs EVOLVE-BLOCK

【设计内容】
- **diff 变异**：LLM 输出 `{目标块, 新代码}` 对，由确定性 patcher 应用；OpenEvolve 配 `max_patch_resamples` 重试与 marker 校验。
- **全文重写**：整文件重生成（Simple Baselines 唯一算子；AIDE² 外环 rewrite 整个内环 agent 代码）。
- **EVOLVE-BLOCK 标记**：在存量代码库中圈出可进化区域，块外代码冻结——把已有 repo 纳入进化的最低侵入方案。
- **概率混合**：ShinkaEvolve `patch_types` + `patch_type_probs=[0.6, 0.3, 0.1]`（diff/full/其他），实战配比可直接借（CODE-BORROWING M2 行）。

【量化证据】
- MARS（arXiv:2602.02660 §3，Modular Construction）：仓库级解（LOC 474.8→1103.9、文件数 1.0→6.7）下 diff 编辑的四个动机——绕过输出 token 上限、聚焦小逻辑单元提精度、已验证模块可缓存复用、debug 定位到文件级；消融去掉模块化后性能显著下降（Fig.3）。代价：多文件 → 输入 token 成本 2.2×（$60.5/task vs AIRA $39.0）。
- AIDE²（weco.ai 博客）：外环用"整体 rewrite"在 100 步中迭代 7 代有效 agent（接受率 ~1/10）；内环用类型化算子——**同一系统两个层级用不同表示粒度**。
- ShinkaEvolve 消融（arXiv:2509.19349 §5/Fig.9）：embedding 新颖性拒绝采样（阈值 0.95）强烈优于无拒绝；LLM-as-novelty-judge 只带来边际提升（不值得额外一次 LLM 调用）。

【对统一设计的启示】
1. 变异表示是独立轴：`edit_granularity ∈ {diff_block, evolve_block, full_rewrite}`，配概率混合（默认 [0.6,0.3,0.1] 量级【推断：具体配比应随任务/代码长度自适应】）。
2. diff 通道必须配确定性 patcher + 校验 + 重试（而非让 LLM 直接改状态）；全文重写是长程重构/元层级改写的保留档位。
3. ACE 的 context-collapse 反例（18,282→122 tokens、66.7→57.1，arXiv:2510.04618）警示：**任何"整篇重写式"算子用于记忆/知识对象时禁用**；重写只作用于代码候选。

### 卡 A3. 反思驱动变异（Reflective Mutation）——消费轨迹的变异器

【设计内容】GEPA reflective prompt mutation：选中候选→按 round-robin 选目标模块→在 minibatch 上 rollout 记录轨迹→LLM 阅读"模块输入/输出/推理轨迹"，把成败归因到 prompt 的具体元素（或缺失）→提出新指令→新候选=旧候选+目标模块替换。配套 **Pareto 候选选择**（维护每个 problem instance 上最优的 prompt 前沿而非全局最优）与 **Merge 算子**（组合两个 Pareto 候选的互补 lesson，即跨候选交叉的反思版）。MARS 的 Comparative Reflective Memory 是同构物：Lesson Distillation Agent 对"当前解 vs previous best"做差分，产出三元组 lesson={因果变更, 对比影响分析, 可泛化规则}。

【量化证据】
- GEPA（arXiv:2507.19457）：4 任务上超 GRPO（24k LoRA rollouts）平均 +10%（最高 +19%），rollouts 少至 35×；匹配 GRPO 最优验证分只需 102/32/6/179 个训练 rollouts（78× 样本效率）；超 MIPROv2 +14%（AIME-2025 +12%）。GEPA+Merge 再扩大到 +21%。
- MARS：lesson-utilization 65.8%，其中**跨分支迁移 63.0%**——反思 lesson 的价值在泛化而非回忆。
- Reflexion 消融（arXiv:2303.11366）：精炼反思 vs 原始轨迹回放 +8%——变异器消费"归因后的文本"优于消费原始失败。

【对统一设计的启示】
1. 反思不是独立模块，而是**变异器的上下文构造器**：`reflect(traces, score_diff) -> 归因文本` 作为 improve/debug 的前置 pipeline 阶段。
2. 变异器消费 M8 的 text_feedback 通道时，带宽需受控：SEAL leaky-anchor 实验证明泄露数值审计分反而显著变差（Doubao 35.1→12.7，m8_deepdive_axes §A4）——"给变异器最少需要的信息"，text_feedback 给方向不给梯度。
3. Pareto-frontier 父选择（按 instance 最优而非全局最优）应列为 M2 可选的亲本选择策略（与 M1 的边界：亲本选择公式归 M1，但 Pareto 结构是算子侧需求【推断】）。

### 卡 A4. 程序交叉（Crossover）的实现形态与有效性

【设计内容】三种形态：
- **LLM 语义交叉**（OpenRSI Crossover 算子、AIRA-dojo `crossover_op(input_node, input_node2)`）：prompt 给出两个父程序+分数，LLM 产出融合体；
- **差分进化式**（EvoPrompt-DE）：找两 prompt 的差异部分→只变异差异→并入当前最优→再与基 prompt 交叉（保留共享成分）；
- **反思合并**（GEPA Merge）：从 Pareto 前沿两候选抽取互补 lesson 合并。
Node 需支持**多父节点**（AIRA-dojo 已改 Node 支持 multi-parent；谱系图上 crossover 边单独标注——OpenRSI 用双线边样式）。

【量化证据】
- 正面：EvoPrompt（arXiv:2309.08532）DE 实例化在 BBH/分类任务上超人工 prompt；GEPA+Merge 比纯 GEPA 再 +8.16%（IFBench, GPT-4.1 mini）。
- 警示：AIRA E3——在旧算子集下 evo（含 crossover）≈ greedy（39.61 vs 39.77），交叉只有在算子整体升级后才参与拉开差距（E5）；Simple Baselines 的 SCS（无显式 fitness 选择的条件采样）即可匹配复杂进化系统。
- 结构性风险【推断】：LLM 交叉的高失败率来自"语义融合破坏可运行性"——未见任何系统报告 crossover 子代的 compile/pass 率高于 improve；所有成功系统都给 crossover 子代接 debug 循环兜底（AIRA：buggy 子节点自动进 debug，上限 10 节点或 12h）。

【对统一设计的启示】
1. crossover 是可选算子而非必备：默认算子集含之，但配置项允许关闭；启用时强制 (a) 父节点多指针谱系、(b) 子代自动接 debug 兜底、(c) 父选择按互补性（Pareto/差异大）而非双高分【推断：双高分父代往往同构，交叉退化为重写】。
2. 差分式交叉（EvoPrompt-DE 的"保留共享、变异差异"）是比自由融合更有原则的默认实现。

### 卡 A5. 提示词变异与算子的自进化（meta 层）

【设计内容】
- **EvoPrompt**：LLM 即进化算子，GA（轮盘选择→交叉→变异）与 DE（差分变异）两套算子由自然语言指令实现，用 one-shot 算法执行示例约束 LLM。
- **PromptBreeder**：自指二阶进化——变异算子 P′=LLM(M+P) 的 mutation-prompt M 自身也被进化 M′=LLM(H+M)；5 类变异算子 + 多样性维护（随机串前缀、BERT fitness sharing、温度 1.0–2.0 随进化自适应变异 ±0.2）。
- **ShinkaEvolve meta 层**：`SystemPromptEvolver` + `MetaSummarizer`——变异用 system prompt 自身有独立 archive + 独立 bandit；MetaSummarizer 周期性生成 meta-recommendations（程序摘要+全局洞察+实现建议，附加进 mutation prompt）。

【量化证据】
- PromptBreeder（arXiv:2309.16797）：消融显示去 meta-mutation（Hyper）多数数据集 fitness 下降；ETHOS 89% vs 人工 80%；Instruction-Induction 24 任务中 21 个匹配/超 APE。
- ShinkaEvolve（arXiv:2509.19349）：circle packing 用 150 次评估即超 AlphaEvolve（原需数千次）；三创新（加权父采样、新颖性拒绝、bandit LLM 选择）消融各自有贡献。

【对统一设计的启示】
1. "算子的 prompt 自身是可进化对象"应建模为**配置项而非新模块**：`Operator.evolvable_prompt: bool`，开时挂独立 archive+bandit（ShinkaEvolve 模式）。
2. 温度/多样性参数可作为"被进化的超参"（PBT 式，PromptBreeder 的 Redescriber 温度自进化）——M2 与 M3 的边界上留钩子【推断】。

## B. 算子选择策略（π_op）

### 卡 B1. 规则式 π_op（当前主流且够用）

【设计内容】AIDE/AIRA 的硬编码优先级：draft 若种子不足（num_drafts=5）→ 以 debug_prob 概率回访 buggy 叶（限 debug_depth）→ 否则贪心 improve 最优节点。ML-Master 1.0/MARS 同为"按节点状态规则化动作选择"。

【量化证据】AIRA E3/E4：规则式 π_op 未成为瓶颈（瓶颈在算子质量）；MLE-bench Lite 奖牌率 AIDE_greedy 39.77%、AIRA_greedy 45.45%（dim01）。

【启示】统一实现默认规则式 π_op（声明式优先级表，YAML 可配：触发条件→算子）；学习型 π_op 做成插件，不承诺收益。

### 卡 B2. Bandit / 自适应算子与模型选择

【设计内容】
- **LLM 选择 bandit**（ShinkaEvolve `BanditBase`）：ABC 暴露 `select_llm / update / update_cost / posterior / get_state / set_state`——cost-aware UCB，状态可持久化（get/set_state 支持断点续跑）。
- **算子概率自适应**：ShinkaEvolve `patch_type_probs`（静态起点）；PromptBreeder 的算子有效性统计（Table J.4：每种变异算子产生改进子代的比例被记录并反馈进化）；OpenRSI 把"Sample Operator"做成 RL policy 的可训练输出。
- **父采样加权**（ShinkaEvolve/OpenRSI）：`F(p) ∝ performance × (1 + α·children_count 或 children_variance) × rarity`——平衡探索/利用。

【量化证据】
- ShinkaEvolve Fig.9 消融：bandit LLM ensembling 略优于固定均匀 ensemble（增益小但稳定）；加权父采样优于随机搜索与爬山；新颖性拒绝采样收益最大。
- OpenRSI（newworks_groupA）：F(p) 用"reward × 子代方差 × 稀少度"，子代方差作为内在动机。

【对统一设计的启示】
1. 三个可插拔选择点分离：**算子选择 π_op**（规则/bandit/RL）、**算子内 LLM 选择**（BanditBase 式有状态对象，注入 ExecutorSpec.llm_policy）、**父/亲本选择**（加权公式，归 M1 但公式参数进 M2 配置）。
2. Bandit 选择对象必须可持久化（get_state/set_state 入 checkpoint 契约）。
3. 实证排序：新颖性拒绝 > 加权父采样 > LLM bandit——预算紧张时按此顺序投入【推断：该排序来自单任务（circle packing）消融，跨域稳健性未验证】。

## C. 算子消费什么（与 M5/M6/M8 的接口）

### 卡 C1. 变异器的上下文契约

【设计内容】各系统给变异器的输入束：
- AIDE：`(task_desc, Σ(T)=good 节点的 plan/analysis/metric 摘要(无代码), 父代码, 父执行输出, data_preview)`；
- AIRA 𝒪_AIRA：**作用域 memory 按算子类型切换**——draft/improve 看兄弟记忆（促多样性），debug 看祖先链（防 undo-redo 振荡）；prompt 自适应复杂度（按节点子代数 nc 注入 minimal/moderate/advanced 线索）；think tokens 对其他算子不可见；
- MARS：lesson pool（solution/debug 分池，K_m=30，Review Agent 去冗，变异器**显式引用**所消费 lesson 可审计）；
- ShinkaEvolve：meta-scratchpad（程序摘要+全局洞察+实现建议）+ text_feedback 字段；
- GEPA：目标模块的 rollout 轨迹（输入/输出/推理链）minibatch。

【量化证据】
- AIRA E2/E4：全局 memory on/off 几乎无差（38.18 vs 39.77），但**作用域 memory 作为算子升级三件套之一贡献了 +14% 相对提升**——记忆不是"有无"问题，是"作用域×算子类型"匹配问题。
- AIDE² §2.4：AIDE₈₅ 自主进化出"每算子定制最小上下文"矩阵（bug rate>15% 才挂某组件、debug 读 raw tail、improve 读 plateau 信号）+ 16× prompt 压缩，省下的 token 再投资为搜索步数——**变异器上下文最小化是被进化发现的**，非人工先验。
- SEAL/m8 证据：反馈带宽给变异器应独立且低于评估带宽（35.1→12.7 反例）。

【对统一设计的启示】统一算子上下文签名：
```python
op_context = {
  task_desc, parent_code(s), parent_exec_output(tail?),
  memory: retrieve(scope=per_operator_default),   # draft/improve→sibling, debug→ancestral
  lessons: lesson_pool.filter(kind=op_type, k=30),
  text_feedback: EvalResult.text_feedback,         # 受带宽闸控
  budget: {remaining_time, step_count},
  complexity_hint: f(node_children_count),
}
```
每算子的上下文字段做成白名单配置（AIDE₈₅ 矩阵是可学习/可进化的目标）。

## D. 自修改算子与安全模式

### 卡 D1. 自修改循环的算子形态与安全门

【设计内容】
- **DGM**：单算子 self-modify-implement——父 agent 读自己的 benchmark 评测日志→self-proposal 提出下一个 feature→实现进自身代码库产子代。准入=**功能性存活门**（"Only agents that compile successfully and retain the ability to edit a given codebase are added"，§3），非分数门。exploration 机制（archive/父选择）**刻意冻结不可自改**（§3 末）。
- **AIDE²**：双层——外环 rewrite 内环 agent 代码；固定美元预算约束（best-of-N 类烧 token 策略过不了门）；~90% 拒绝率。AIDE₈₅ 自建三层反 reward-hacking 防线（prompt 指令/硬编码 guard 重生成可疑输出/统计剔除极端成功），且后续突变把统计层改坏而不自知——被人工谱系审计发现。
- **prime-agent /refine**：对 harness 自身变更的准入门——"small, evidence-backed updates"，immutable base system prompt 不可改 + 快照回滚。

【量化证据】DGM：SWE-bench Verified 20%→50%、Polyglot 14.2%→30.7%（arXiv:2505.22954）；去 archive 退化（hill-climbing 基线显著变差）。AIDE²：8 天 100 步 7 代连续改进，超人类两年手调版本（博客，无同行评审）。

【对统一设计的启示】
1. 自修改算子的安全模式四件套：**(a) 冻结边界声明**（每个模块标注 self_mutable: bool，评估器/门代码默认不可自改）；**(b) 功能性存活门**（compile+元能力检查优先于分数）；**(c) 小步证据化写入+快照回滚**（/refine 范式）；**(d) X1 谱系必须覆盖 gate/evaluator 自身代码版本**（AIDE² 反作弊层失效实证）。
2. 元对象层级：`Candidate<T>, T ∈ {TaskSolution, ExecutorSpec}`；T=ExecutorSpec 时算子=rewrite/self-modify，评估=元评测（跑 N 个任务聚合），选择信号用 public/private 双分数（private 不可见做存活判定）。

## E. 交叉轴证据：算子质量 > 算子数量 > 选择策略

- **算子质量是瓶颈**（AIRA E3–E5）：先投资算子（上下文工程、作用域记忆、think tokens），再投资拓扑，最后才轮到 π_op 学习化。
- **评估噪声会让一切算子设计退化**（Simple Baselines）：~100 题验证集下 ADAS/Shinka 与 IID RS 无显著差异（P=0.49）；M8 统计可靠性是 M2 发挥作用的先决条件。
- **领域知识/搜索空间设计 > 搜索方法**（Simple Baselines §4.1/§7）：prompt 里的领域知识必须作为受控变量声明，否则算子增益不可归因。

---

## M2 算子设计轴系候选（轴 + 取值）

| # | 轴 | 取值（默认加粗） |
|---|---|---|
| O1 | 算子集构成 | **{draft, improve, debug}** / +crossover / +merge(aggregate) / 单算子 generate（退化自检基线）/ 自定义注册表 |
| O2 | 算子 arity | 0(draft) / 1(improve, debug, rewrite) / 2(crossover) / N(merge, inspiration-set 条件生成) |
| O3 | 变异表示 edit_granularity | diff_block(SEARCH/REPLACE) / evolve_block(标记区域) / full_rewrite；概率混合 probs=[0.6,0.3,0.1] 可调 |
| O4 | patch 应用器 | 确定性 patcher + 校验 + max_resamples 重试（默认）/ LLM 自由编辑（仅 sandbox 任务） |
| O5 | 改动语义约束 | **每边一个原子改动** / 自由改动 / 语义 diff（EvoPrompt-DE 式保留共享变异差异） |
| O6 | 变异上下文构造 | 固定模板 / **作用域记忆按算子类型切换**(sibling/ancestral/global/none) / lesson pool 引用制 / 反思轨迹(GEPA) / 每算子字段白名单（可进化） |
| O7 | 反思驱动度 | 无（纯生成）/ 事后归因 lesson（MARS）/ 轨迹级归因（GEPA reflective）/ 强制假设- reconcilation（The Little Scientist 式） |
| O8 | 消费反馈带宽 | 标量分数 / +text_feedback（受闸控，SEAL 证据）/ +工件 artifacts / full trace（仅审计，不给变异器） |
| O9 | 算子选择 π_op | **规则优先级表**（YAML）/ bandit（有状态可持久化）/ RL policy（OpenRSI 式，可训练）|
| O10 | 算子内 LLM/参数选择 | 固定 / BanditBase 式 cost-aware UCB / ensemble 固定权重；温度等超参可自进化（PBT） |
| O11 | 亲本选择（与 M1 交界） | 贪心 best / 加权 F(p)=reward×(1+子代数)×rarity / Pareto-per-instance（GEPA）/ 岛比例采样+迁移 |
| O12 | 新颖性闸 | 无 / **embedding 相似度拒绝**(阈值~0.95) / +LLM novelty judge（边际收益，默认关）|
| O13 | 算子 prompt 管理 | 代码内嵌 / **Jinja/YAML 配置即数据** / 可进化（独立 archive+bandit，ShinkaEvolve meta 层）|
| O14 | 失败子代处理 | debug 兜底循环（上限 N_d / 时限）/ 丢弃 / buggy 节点冻结只许修 |
| O15 | 被进化对象层级 level | TaskSolution / **ExecutorSpec(harness-as-candidate)** / 算子 prompt（meta）/ 问题表述本身 |
| O16 | 自修改安全 | 冻结边界声明（self_mutable 位）/ 功能性存活门 / 小步证据化+快照回滚 / 谱系覆盖 gate 代码 |
| O17 | 算子=嵌套 agent | 单次 LLM 调用（默认）/ 算子内嵌子搜索（SWE-Agent 式 agentic 算子，AIRA 展望）【推断：接口上 o:2^𝒮→𝒮 不变，内部可以是完整 run】|
| O18 | 复杂度课程 | 无 / prompt 自适应复杂度（按 nc 注入 minimal→advanced 线索，𝒪_AIRA）/ curriculum 从简到繁（MARS drafting） |

**轴间强耦合备忘**：O6×O11（作用域记忆与亲本选择共同决定多样性）；O8×D-安全（反馈带宽闸是反 reward-hacking 结构件）；O3×O17（嵌套 agent 算子通常用 full_rewrite 粒度）；O13×O10（prompt 可进化时 bandit 作用域需含 prompt 版本【推断】）。

**证据强度排序（投入优先级建议）**：算子上下文工程（O6，+14%）> 新颖性闸（O12，Shinka 消融最大单项）> 反思 lesson（O7，GEPA 35× 样本效率）> diff 工程（O3/O4）> bandit 选择（O9/O10，增益小）> 学习型 π_op（暂不投）。
