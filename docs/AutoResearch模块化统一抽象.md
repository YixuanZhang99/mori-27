# AutoResearch 模块化统一抽象：面向可配置 AutoOptimization 框架的设计空间与接口契约

> **文档定位**：为自研"可配置 AutoResearch 框架"（类比 vLLM/SGLang 之于推理 infra、VeRL 之于 RLHF）提供
> ① 领域代表系统的机制级理解；② 一套带接口契约的模块化抽象；③ 参考架构与配置化组合示例。
>
> **证据基础**：8 个机制单元深读（dim01-08，~2700 行，100+ 一手引用，存于 `../research/dim00-08/autoresearch_modular_dim*.md`）
> + Arbor 开源仓库代码级分析（dim00）+ Arbor 论文全文 + 两份独立总结（Codex/ChatGPT）。
> 交叉验证与冲突区见 `../research/dim00-08/autoresearch_modular_cross_verification.md`。
>
> 生成日期：2026-08-05

---

## 1. 核心结论（TL;DR）

1. **搜索算法的军备竞赛已经结束，状态表示的军备竞赛刚开始。** 五个独立系统的消融证据一致表明：拓扑（tree/MCTS/evo）在算子与记忆到位前几乎不产生差异；增益主体来自**结构化语义记忆**与**准入纪律**。框架护城河在数据面表达力，不在 policy 数量——greedy/MCTS/进化都应是一行配置。
2. **最终节点选择/准入是被全领域低估的最大杠杆。** AIRA 的 oracle 实验给出上界：仅把终选换成 test 分就值 9~13 个奖牌点；Arbor 的 held-out merge gate 显著缓解了 dev 过拟合（但见 M9 关于自适应过拟合的争议）。Admission 必须是一等模块，不是工程附属。
3. **所有成熟系统收敛到同一两层骨架**：控制器（外化持久状态 + Observe→Plan→Select→Dispatch→Absorb→Admit 算子链）+ 执行器（有界工作区 + 结构化证据返回）。系统间差异可完备地分解为 **9 个模块 × 2 个横切层**的取值组合。
4. **"角色分工"与"假设分工"是同一 Executor 接口的两个旋钮**；**"时间尺度记忆"与"拓扑作用域记忆"是同一 Memory 后端的两个索引轴**；**"树/DAG/种群"是同一 Frontier 接口的三种路由**。看似对立的架构派系在接口层统一。
5. **开源生态位确实空缺**：进化框架（OpenEvolve/ShinkaEvolve）工程模块化程度高但无语义记忆与准入纪律；agentic 框架（Arbor）有记忆与准入但拓扑/策略/多保真写死；AIRA-dojo 有形式化但无持久记忆。三者交集无人占据——这就是目标生态位。

---

## 2. 证据地图与强度说明

| 单元 | 系统 | 调研深度 | 文件 |
|---|---|---|---|
| dim00 | Arbor 开源仓库 | 代码级（src/ + docs/ + skills/） | ../research/dim00-08/autoresearch_modular_dim00_arbor_repo.md |
| dim01 | AIDE + AIRA-dojo | arXiv 全文 + 两仓库源码级 | dim01 |
| dim02 | ML-Master 1.0/2.0 + Reflexion/ACE/GA | 全文 + prompt 附录 | dim02 |
| dim03 | MARS + 成本敏感谱系 | 全文 + 10+ 对照工作 | dim03 |
| dim04 | R&D-Agent + AIBuildAI | 全文 + 仓库模块结构 | dim04 |
| dim05 | LoongFlow + FM Agent | 全文 + 进化记忆模块源码 | dim05 |
| dim06 | FunSearch/AlphaEvolve + OpenEvolve/ShinkaEvolve/GEPA | 三仓库类源码 + 配置 | dim06 |
| dim07 | KAPSO + AiScientist-2026 | 全文 + 仓库 schema | dim07 |
| dim08 | MCGS/InternAgent/DataMaster + 评测协议谱系 | 全文 + 争议一手来源 | dim08 |

**证据强度分层**（沿用此前共识，不重复展开）：① 同条件受控对照（Arbor vs Codex/Claude Code，48h 同预算）——强；② 各系统自报消融——中（注意 AIRA 环境固定实验是其中方法论最严的；Arbor 的关键消融在 22 任务、无多种子报告下进行，insight/tree 排序差对应 2-4 个任务，方向可信、精确差值需谨慎）；③ MLE-Bench 异构榜单——仅用于设计路线定位，不用于架构优劣断言；④ 闭源系统（AIBuildAI、FM Agent 核心引擎）——接口细节置信度中低。

---

## 3. 统一抽象总览

### 3.1 语义内核：一切系统都是这个循环的实例

```
候选生成 x' = Ω( parents ⊆ Frontier;  h, Retrieve(Memory, Knowledge), budget )
执行     a  = Executor.execute( spec(x'), workspace, budget )          # M7：候选 → artifact
证据     r  = Evaluator.evaluate( a, EvalRequest{fidelity, limits} )   # M8：artifact → 证据
状态更新     (Frontier, Memory, Best, Budget) ← Update( · , x', r )
准入         if AdmissionGate( x', r, Best ): Best ← x'                # M9
```

其中 r 不是标量，而是类型化证据记录（见 M8）。模块间传递的核心数据类型闭包：
`Candidate（x'，M2 产出）→ ExecutorSpec+Workspace（M7 消费）→ EvidenceRecord = EvalResult + {branch_ref, executor_status, attempt}（M8 产出，M1/M3/M4/M9 共同消费）→ StateMutation 白名单（M1 产出，M4/M5 消费）`。

**框架的不变量**：软决策（想什么、选哪个、怎么解读）交给 LLM policy；硬保证（预算、dev/test 纪律、串行写、作用域隔离、防篡改）留在机制层。

### 3.2 九模块 + 两横切层

```
┌────────────────────────── 控制面（决策） ──────────────────────────┐
│  M1 Policy/Coordinator   M2 Operator 算子库    M3 BudgetController  │
├────────────────────────── 数据面（状态） ──────────────────────────┤
│  M4 Frontier/ResearchState   M5 Memory   M6 Knowledge               │
├────────────────────────── 执行面（落地） ──────────────────────────┤
│  M7 Executor   M8 Evaluator   M9 AdmissionGate                      │
├────────────────────────── 横切层 ──────────────────────────────────┤
│  X1 Provenance & Audit（git lineage/checkpoint/事件总线/防篡改）     │
│  X2 HITL（interaction modes / 人工 gate / steering）                 │
└────────────────────────────────────────────────────────────────────┘
```

三条正交的外部配置轴（借鉴 Arbor 实现并推广）：
**Provider**（用哪个 LLM）× **DomainPlugin**（优化什么：eval 契约 + 保护路径 + 预算包）× **Skill**（单步推理怎么提质）。框架内模块决定"搜索怎么组织"，这三轴决定"在哪个领域、用谁、以什么质量"运行。

---

## 4. 模块详章

> 每模块固定四小节：**职责与接口契约 / 设计选项谱系 / 证据与权衡 / 默认建议**。

### M1 Policy / Coordinator（全局策略）

**职责**：观察状态 → 生成研究方向 → 选择下一个/批候选 → 解读证据 → 决定扩展/剪枝/停止。

**接口契约**：
```python
class Policy(Protocol):
    def observe(self, state: StateView) -> StrategyContext: ...
    def ideate(self, ctx: StrategyContext, parent: NodeRef, k: int) -> list[Hypothesis]: ...
    def select(self, frontier: FrontierView, budget: BudgetState) -> list[NodeRef]: ...
    # 职责切分：select 是决策入口，默认委托给 M4.sample（带权采样原语）；
    # LLM 策略下 select 自行裁决，规则策略下 = sample 的薄封装
    def absorb(self, evidence: EvidenceRecord) -> list[StateMutation]: ...  # 受控 mutation，白名单字段
```

**Policy 运行时上下文**（易被遗漏的子职责，Arbor `context_prune` 实证）：长跑场景下 coordinator 自身的对话上下文需要独立治理（window/compact_threshold/keep_recent），它与 M5 经验记忆是两条写路径——前者管"policy 的工作记忆不爆"，后者管"跨实验的经验沉淀"，不可合并。

**设计选项谱系**：

| 选项 | 代表 | 要点 |
|---|---|---|
| LLM 自由策略（六步循环） | Arbor coordinator | 表达力最强，可解释；选择理由不限于分数（"消除歧义""验证关键假设"） |
| best-first / greedy | AIDE | 简单基线；弱算子下与高级策略无差异 |
| MCTS/UCT | ML-Master、MARS、AIRA 可配 | 算子升级后长时段（>19h）才显优势；credit assignment 稳定 |
| 进化调度（Boltzmann/softmax） | LoongFlow、R&D-Agent（可插拔调度器 RoundRobin/softmax/MCTS-PUCT） | 实现位置 = M4 压力控制器 + trivial policy（见 M4 旋钮 3），此处仅作策略语义列出 |
| Bandit（成本感知 UCB） | ShinkaEvolve（LLM 选择可注入 BanditBase） | 状态可持久化；适合模型/算子选择 |

**证据与权衡**：AIRA 控制实验是分水岭——弱算子下换拓扑零增益、对 UCT 常数不敏感；算子升级后拓扑才分化。R&D-Agent 消融：搜索结构（DAG vs 链）−28% 是最大单一跌幅。**策略不应硬编码，应注册表化（registry + 配置组装），但策略数量不是护城河。**

**默认建议**：默认 LLM 自由策略 + 受控 mutation 白名单（Arbor 模式）；把 UCT/Boltzmann 实现为同接口备选，用于可量化效用且假设空间规整的场景。

### M2 Operator（候选生成算子）

**职责**：从父候选 + 上下文产生新候选。与 M1 解耦：**算子选择策略 π_op 与算子集 O 是两个独立配置**（AIRA 五元组的核心教训）。

**接口契约**：
```python
# 纯函数签名（AIRA-dojo 风格），支持 0/1/2 父节点
def op(llm, cfg, memory, task_desc, journal, *parents, budget) -> Candidate: ...
# 算子可以是单调用，也可以是嵌套 agent（AIBuildAI 闭源自报子 agent 化为其关键因子，代价是 token）
```

**设计选项谱系**：

| 算子族 | 代表 | 备注 |
|---|---|---|
| draft / debug / improve | AIDE | 最小完备集 |
| crossover | AIRA、FM Agent | 需要 2 父签名 |
| hypothesis-refine（语义细化） | Arbor ideate | 证据条件化：validated insight 作正约束、pruned 节点作负约束 |
| LLM diff 变异（EVOLVE-BLOCK / SEARCH-REPLACE） | AlphaEvolve | 必须配 max_patch_resamples 重试 + marker 校验 |
| Plan-Execute-Summarize 三段式 | LoongFlow | 消融证明 Planner/Summary 缺一不可（去 Planner Top-1 时间 9.67h→14.67h） |
| comparative-reflect（差分反思） | MARS | candidate vs previous best 做近似因果归因；lesson 跨分支迁移率 63% |
| analyze/review（独立评审） | AIRA | 与编码模型解耦的结构化输出算子 |

**证据与权衡**：**算子质量先于搜索拓扑成为瓶颈**（AIRA：仅升级算子集 +14% 相对提升）。算子"agent 化"（多轮推理）vs"单调用"是质量/成本主轴。失败处理契约：单例失败不抛异常、错误写进 trajectory（GEPA 契约）——失败是数据不是异常。

**默认建议**：内置 draft/debug/improve/crossover/hypothesis-refine/comparative-reflect 六算子；π_op 默认规则式（学习型 π_op 从未被证明是瓶颈，可后置）。

### M3 BudgetController（预算与收敛）

**职责**：分配与回收三类预算——轮数/时间/token（全局）、方向级、候选级（fidelity）；检测收敛与方向耗尽。

**接口契约**：
```python
class BudgetController(Protocol):
    def state(self) -> BudgetState: ...                        # used/remaining per 层级
    def should_continue(self, branch: NodeRef, evidence: EvidenceRecord) -> bool: ...
    def allocate(self, candidate: Candidate) -> EvalRequest: ...  # 决定 fidelity/时限/种子数
    def converged(self, evidence: FrontierView) -> ConvergenceSignal | None: ...
```

**设计选项谱系**：

| 机制 | 代表 | 要点 |
|---|---|---|
| 硬上限（轮数/墙钟） | Arbor max_cycles、PostTrainBench | 必要但朴素；PostTrainBench 发现 20h 时 agent 自行早停 → 更多预算≠更好 |
| 成本感知价值函数 | MARS：reward = G(v)·[t(v)/L(v)]^w，w=−0.07 | w=0 退化、w=−0.15 偏向琐碎快解；"w 随 elapsed_frac 调度"是未验证提案（dim03 建议，无实验） |
| fidelity 级联 | paired-seed funnel（3 seeds 筛选 → 10 seeds 验收，假阳性 ~0.1%）、SH/Hyperband（HBBO）、固定 5min 档 | **高成本场景的核心机制**；"便宜 dev→昂贵真实评估"统一为 fidelity 晋升策略插件 |
| 收敛/耗尽检测 | Arbor ConvergenceDetector（velocity + exhausted parents + 建议） | 统计显著的 convergence detector 全领域无人做——空白 |
| 预算状态注入 | BATS：prompt 注入 `<budget>used/remaining</budget>` 即推 Pareto 前沿 | 零成本增强 |

**代理有效性验证**（异质代理级联的必备子机制，高成本工业场景的最大失败模式）：当 proxy 指标与真实指标不同质时，需要 ① 定期 anchor 全评估校准代理；② proxy-true 秩相关监控与代理漂移告警；③ "代理通过、真实倒退"的负反馈记入 Memory。注意两个常被直接挪用的数字的适用前提：Arbor 的 5% 触发阈值是**同指标 dev 域**的；paired-seed funnel 的 ~0.1% 假阳性率前提是**同一指标、仅种子噪声**——对异质代理均不成立。

**样本规模 regime**：velocity 收敛检测、成本惩罚 value 的证据均来自单 run 数百上千次评估的系统；若一周仅 ~10-30 次真实评估（10h 级场景），velocity 在个位数样本下无统计意义——应降级为规则式信号（连续 N 次无改进 + 方向耗尽），fidelity 级联的 rung 数也应收敛到 2-3 档。

**默认建议**：两层叠加——方向级用成本惩罚 value 或 LLM pivot 判断，候选级用 fidelity 级联 + 尝试上限；收敛检测默认 velocity + 方向耗尽双信号（低样本 regime 按上文降级）。

### M4 Frontier / ResearchState（搜索状态）

**职责**：组织候选集合与搜索拓扑；提供状态的多投影（程序态/LLM 态/人读态/约束态）。

**接口契约**（综合 Arbor IdeaTree、LoongFlow EvolveMemory ABC、MCGS 双层图）：
```python
class Frontier(Protocol):
    def add(self, node: Node) -> None: ...            # 路由由"准入结构"配置决定
    def sample(self, k: int, ctx: StrategyContext) -> list[Node]: ...  # 压力控制器
    def get_best(self, scope: Scope) -> Node | None: ...
    def prune(self, node: NodeRef, reason: str) -> None: ...
    def view(self, projection: Projection) -> str: ...  # json / compact-md / constraints-block
    def checkpoint(self) -> bytes: ...
# 不变量：credit assignment 只认骨架边；引用边仅承载信息流（MCGS 教训）
```

**三个正交配置旋钮**（dim05 结论）：
1. **准入结构**：链 / 树 / DAG(骨架边+引用边) / elite-pool / MAP-Elites / island
2. **上下文检索策略**（与拓扑解耦！）：仅父 / 父+兄弟（ML-Master scoped memory）/ 同分支近 k / 全局 top-N（MCGS 引用边）/ 多分支聚合。**职责切分**：本旋钮只声明"作用域描述符"，唯一检索入口是 M5.retrieve（消费该描述符）；M7 的 context_scope 进一步降级为对返回 ContextPack 的投影选择——三条路径一个入口
3. **多样性压力控制器**：温度 Boltzmann / 簇级选择压力 / niche 保留（这是 sample 原语的实现位置；M1 规则策略只是它的薄封装）

**节点 schema**（以 Arbor Node 为底，推广）：
```
id, parent_ids[], children_ids[], depth,
hypothesis(语义假设，可空=纯代码节点), status,
insight(蒸馏), result(事实), score, score_split(dev|admission|test), test_score,
code_ref(git branch/commit), grounding(ideation 引用), related_work(novelty audit),
eval_status(scored|skipped|failed_to_run), attempt, cost, uncertainty
```

**证据与权衡**：拓扑选择影响的是**信息流宽度**（纯树只允许父-子传递 → node isolation；引用边允许任意节点进入新 context）。R&D-Agent：DAG→链 −28%。DataMaster 取中间值（父+兄弟默认 + 可查询 Global Memory）。**树/DAG/种群是同一接口的退化/组合形态，不应写死。**

**默认建议**：默认树 + 可开引用边；MAP-Elites/island 作为 frontier 插件；descriptor 支持"假设嵌入"（语义假设即 behavior descriptor，外部先例：GSME 范畴标签、ACES/QD-LLM 语义嵌入）。

### M5 Memory（内生经验）

**职责**：把执行轨迹转化为可复用经验；治理经验的生命周期与作用域。

**统一后端定义**（dim02 核心结论）：
```
存储按时间尺度分层：L1 工作记忆(原始) → L2 阶段蒸馏(知识单元) → L3 跨任务(键值对, embedding 检索)
索引按双键：拓扑作用域(与哪个搜索状态相关) × 语义(embedding/标签)
接口：
  write(checkpoint_hook, trace)           # 主循环暴露钩子，记忆后端订阅
  promote(level, delta_op)                # 必须增量合并，禁止整篇重写（ACE context collapse 教训）
  retrieve(scope, query, budget) -> ContextPack
```

**关键设计约束（全部有实证）**：
- **精炼 > 回放**：Reflexion 消融压缩反思比原始轨迹高 8 个绝对点；蒸馏洞见是最小数据单元（dim04 三方消融一致）。
- **平铺记忆 ≈ 无效**：AIRA 全局 memory 算子消融无差异 vs DataMaster 去 Global Memory −41pp、Arbor 去 insight −27pp——区别在于结构化（树绑定/分层/作用域）。**这是接口设计的负例约束：无作用域的记忆注入等于没有记忆。**（注：Arbor 消融在 MLE-Bench Lite 22 任务上进行，无多种子报告，insight 排序差对应 2-4 个任务——方向性结论可信，精确差值需谨慎。）
- **晋升必须增量**：被 ACE 针对的"整篇重写"范式导致 context collapse（ACE 论文实证 18,282→122 tokens）；ACE 的增量 delta 合并正是解法。
- **所有权约定**：M4 节点 schema 中的 insight 字段是 M5 L2 蒸馏层的物化视图（source of truth 在 M5，写路径经 M1.absorb 的受控 mutation）。
- **provenance 必选字段**：来源指针 + 置信计数（helpful/harmful），否则防污染无从谈起。
- 未解决问题（框架可超越）：晋升忠实度校验、负面智慧隔离、并发写一致性。

**默认建议**：L1/L2 默认开启，L3 跨任务层作为可选后端；写入绑定 checkpoint 钩子（节点扩展/相边界/任务终止）。

### M6 Knowledge（外部知识）

**职责**：文献/web/repo/playbook 的获取、组织、注入与审计。

**接口契约**：与 M5 共享 retrieve 语义但独立存储：
```python
class Knowledge(Protocol):
    def search(self, query: Query, lane: Lane) -> Digest: ...   # lane = grounded_ideation | novelty_audit，两车道互不共享抓取文本
    def retrieve(self, scope: Scope, query: Query) -> KnowledgePack: ...  # 返回分级知识包（TIER1 精确/TIER2 相关/TIER3 纠偏），含 query_used/source_pages
    def ingest(self, source: ArtifactRef, schema: GraphSchema) -> None: ...  # run 后蒸馏回写
# 约束：来源未实际打开则丢弃（引用诚实）；检索策略显式编码进返回类型（不伪造 workflow）
```

**设计选项谱系**：

| 机制 | 代表 | 要点 |
|---|---|---|
| 两车道检索 | Arbor：grounded ideation（落 node.grounding）+ novelty audit（落 node.related_work），**独立检索、互不共享抓取文本**，默认关闭 | 保 benchmark 公平；未实际打开的来源丢弃（引用诚实） |
| 分层 agentic RAG | AIBuildAI-2：L1 ~30 人工类目常驻 + L2 ~1000 文档条件加载；run 后蒸馏回写知识库 | 知识稀疏领域收益最大（ADMET 61→40 反超） |
| 类型化知识图 | KAPSO：Principle/Implementation/Environment/Heuristic + Workflow 根；Principle 强制挂 ≥1 Implementation（可执行约束）；检索返回分级知识包（TIER1 精确/TIER2 相关/TIER3 纠偏） | 检索策略显式编码进返回类型——"不伪造 workflow" |
| prior wisdom 预热 | ML-Master 2.0：407 个 Kaggle 任务预填 L3 | 跨任务知识的冷启动方案 |

**默认建议**：Knowledge 与 Memory 共享 retrieve 契约但独立存储；两车道默认关闭（benchmark 模式）/ 开启（真实研究模式）由 DomainPlugin 切换。

### M7 Executor（执行器）

**职责**：在隔离工作区中把候选变为可评估 artifact，返回结构化证据。

**统一签名**（dim04 结论——角色分工与假设分工的统一）：
```python
def execute(spec: ExecutorSpec, workspace: Workspace, budget: Budget) -> EvidenceRecord: ...

ExecutorSpec = (role,        # 职能轴：designer/coder/tuner/analyst... 同质=单一通用 role
                hypothesis,  # 假设轴：冻结(Arbor) / 自由(Codex/AIBuildAI)
                context_scope)  # 可见上下文：repo 作用域(AIBuildAI 强制隔离) / 祖先 insight(Arbor)
# AIBuildAI = role 异质 + hypothesis 自由 + 对象级 multi-start
# Arbor     = role 同质 + hypothesis 冻结（归因完整性：返回分数必须归因于该假设）
# R&D-Agent = 两者之积
```

**执行隔离谱系**：共享工作区串行（Codex）→ 容器（AIRA，小规模非必需、规模化刚需）→ git worktree（Arbor/KAPSO，branch 即产物引用）→ 异步双池（FM Agent，Ray 数千并发）。

**返回契约**（恰好四元组，Arbor）：`{score, result, insight, branch_ref}` + eval_status(scored/skipped/failed_to_run)——**失败是一等状态**。

**默认建议**：worktree 隔离为默认（成本低于容器、provenance 免费）；并行度由 Evaluator 资源反压决定；executor 内部修复循环绑定 hypothesis 不变。

### M8 Evaluator（评估器）

**职责**：把 artifact 变成类型化证据。这是**框架与被优化领域之间的唯一契约**，其返回类型决定整条反馈带宽轴。

**返回类型（分层超集，综合 dim03 五元组 + dim07 KAPSO 四元组 + dim06 带宽谱系）**：
```python
EvalResult = {
    status:       ok | failed_to_run | timeout | invalid,      # 可执行性（必选）
    metrics:      dict[str, float],                            # 定量向量（必选；public/private 分离）
    uncertainty:  float | None,                                # 种子方差等（高成本场景必选）
    cost:         CostVec,                                     # time/tokens/gpu_hours（必选）
    fidelity:     str,                                         # 本次评估的保真度档位（必选）
    text_feedback: str | None,                                 # 定性反馈（中带宽）
    partial_curves: Any | None,                                # 训练曲线等（支持早停决策）
    trajectory_ref: str | None,                                # 完整轨迹引用（高带宽，GEPA 档）
    artifacts_ref: str | None,                                 # 附属产物（OpenEvolve 侧信道，性价比折中）
}
EvalRequest = { fidelity, time_limit, budget_token, seed_set, resume_from }
```

**谱系与权衡**：scalar（FunSearch）→ +artifacts（OpenEvolve）→ +public/private/text_feedback（ShinkaEvolve）→ 完整 trajectory+reflective dataset（GEPA，prompt 优化场景下 rollout 少至 35× vs GRPO——跨域对照、"up to" 量级，仅作方向性锚点；反思成本仅 5-10%）。**带宽越高样本效率越高、实现成本越高；按任务评估成本选档**——10h 级工业场景建议 scalar+uncertainty+partial_curves（若评估过程可产生中间曲线）档。

**默认建议**：status/metrics/cost/fidelity 四字段设为必选，其余按带宽档位可选；评估器实现注册表化（DomainPlugin 的 eval_contract 即注册入口）。

**配套机制**：metric_direction + eval_cmd（Arbor eval_contract）；paired-seed 统计验收；评估器自身不可变（见 X1）；KAPSO 概念目标 J*=𝔼[U(R)] 显式定义以消除 U(𝔼R) 歧义。

### M9 AdmissionGate（准入）

**职责**：裁决什么算"真正的进步"。**一等模块，独立可配**（AIRA oracle 实验：终选模块化值 9-13pp）。

**配置对象**（dim08 定义）：
```yaml
admission:
  layers: [dev, admission, final_audit]   # 三层协议；两层=Arbor 模式
  gate_evaluator: admission_split         # gate 用哪个评估器/数据划分
  trigger: { min_dev_gain: 0.05 }         # 限流阈值（Arbor：dev 改进≥5% 才触发 gate）
  call_budget: 20                         # gate 调用硬上限（防 adaptive overfitting）
  margin: 0.0                             # 改进幅度门槛（Arbor 支持 margin）
  monotonicity: true                      # current-best ratchet
  selection: best | top_k                 # top-3 多提交值 +10%（AIRA）
  final_audit: { isolation: true, runs: 1 }
  integrity_hooks: [hash_check, canary_scan, human_approval]
reporting: [dev_best, gate_selected, final_audit]  # 强制三元组报告
```

**调用契约**：gate 复用 M8 Evaluator 接口（gate_evaluator 即一个带权限标记的 Evaluator 实例）；call_budget 与准入评估消耗计入 M3 全局预算，同时受 M9 独立硬顶约束——双预算权属：M3 管"花了多少"，M9 管"最多能花几次"。

**证据与陷阱**：① dev 过拟合实证（Claude Code Terminal-Bench dev 75.0/test 71.7）；② Arbor 两层模式的 adaptive overfitting 争议（搜索期 ≤20 次自适应 test 查询，winner's curse）——更严方案是三层划分或 call_budget 硬顶；③ **不能用 LLM judge 单独放行**（Gasteiger/Anthropic：zero-shot 监视器失效、judge 易被"贬低强方案"的 justification 操纵）——准入必须以可执行/可复算信号为准；④ KAPSO 每提交用完整 test 集评分引发社区争议（MLE-bench issue #138）——**评估器能看到什么必须做成显式权限配置**。

### X1 Provenance & Audit（横切）

- **git 即 lineage**：branch 即 artifact 引用（Arbor code_ref、KAPSO repo-state-as-candidate）；研究树挂在 git DAG 上，无需另建状态库。
- **checkpoint/resume/replay**：版本化 Checkpoint（GitState + InflightExecutor + CacheAnchor + messages）。
- **防篡改**：protected_paths 运行时 SHA-256 manifest（不止 merge 时检查）；数据与 harness 不可变。
- **泄漏防线**：test-hash 去重、URL blocklist、canary 扫描（DataMaster 三层；Arbor ContaminationProbe + membership probe）。
- **事件总线**：events + subscribers 解耦 dashboard/日志/UI；全决策留痕（为什么扩展/剪枝/合并）。
- **审计报表**：轨迹导出、违规审计（MLE-bench transcript audit + Dolos 查重 >60% 取消资格）。
- **外部互操作面**：MCP server 等"框架能力对外暴露"归本层（Arbor 实现先例），与控制面解耦。

### X2 HITL（横切）

- interaction modes 谱系：auto / direction（问去哪）/ review（批想法）/ collaborative（Arbor 四档）。
- 高风险操作人工批准钩子（gate 调用、保护路径写、外部 API）。
- 会话内 steering：slash 命令（/tree /evidence /pause /resume）。
- 原则：HITL 是决策包装层——各模块配置中可声明人工钩子（如 M9 的 human_approval），但钩子的实现统一走 X2 的交互通道，不在模块接口内生长。

---

## 5. 系统 = 模块配置组合（总映射表）

| 系统 | M1 策略 | M2 算子 | M3 预算 | M4 拓扑/前沿 | M5 记忆 | M6 知识 | M7 执行器 | M8 评估 | M9 准入 |
|---|---|---|---|---|---|---|---|---|---|
| Codex/Claude Code | LLM 自由(隐式) | 自由编辑 | 墙钟 | 单链 | 对话历史(无显式记忆层) | 无 | 共享工作区,假设自由 | dev 直读 | 无 |
| AIDE | best-first | draft/debug/improve | 轮数 | 代码树 | Σ(T) 摘要(L1) | 无 | 隔离,单调用 | val 分数 | val best |
| AIRA-dojo | greedy/MCTS/evo 可配 | 算子集+π_op 解耦 | 轮数 | 树 | memory 工厂(simple/sibling/ancestral/none) | 无 | 容器,单调用 | 防泄漏设计 | 终选独立模块 |
| ML-Master 2.0 | MCTS | 算子+检索 | 轮数 | 树 | **L1/L2/L3 HCC** | L3 wisdom 预热 | 隔离 | val | val best |
| R&D-Agent | LLM 规划+可插拔调度 | ExpGen/HypothesisGen | 时间触发 merge | **DAG(Trace)** | 协同记忆(弱贡献) | 文献 | Researcher/Developer 分工 | dev | 分支 merge |
| AIBuildAI | manager LLM | 子 agent 化算子 | 异步调度 | multi-start repo 集 | 会话历史 | **分层 RAG 知识库** | role 异质+假设自由 | dev | aggregator/ensemble |
| LoongFlow | Boltzmann 温度 | Plan-Execute-Summarize | 代际 | island+MAP-Elites | lineage 记忆 | 无 | 并行 | dev | elite pool |
| FM Agent | 簇级压力 | 变异+crossover | 代际+配额 | island | evolution memory | expert cold start | Ray 异步双池分布式 | domain evaluator | elite pool |
| OpenEvolve | controller 规则 | diff 变异 | 配额 | MAP-Elites+岛 | 实例仓库 | 无 | 异步 | cascade 评估+artifacts | 胞格竞争 |
| ShinkaEvolve | **Bandit(UCB)** | diff 变异 | 三池配额 | MAP-Elites+岛 | MetaSummarizer(雏形) | 无 | 异步 | **public/private+text_feedback** | 胞格竞争 |
| GEPA | 规则+反思 | reflective mutation | Stopper 注入 | Pareto 前沿 | reflective dataset | 无 | 依赖注入 | **trajectory 全带宽** | AcceptanceCriterion 注入 |
| KAPSO | 树搜索 | 算子+知识包 | 达奖牌即停 | git DAG | episodic memory | **类型化知识图** | branch 即产物 | **R(c) 四元组,随机 K rollout** | 偏好/效用二选一(有争议) |
| AiScientist-2026 | 层级编排 | 专家 agent | 预算 | best-so-far 前沿+registry | **File-as-Bus 产物协议** | 文献 | 专家分工 | dev | ratchet |
| **Arbor** | LLM 六步循环 | 证据条件化 ideate | max_cycles+收敛检测 | **假设树** | **insight 上溯(假设绑定)** | 两车道(默认关) | worktree+假设冻结 | dev/test 双评估器 | **held-out margin gate** |

读法：任何两行之间的差异都能定位到具体模块的具体取值——这就是"可配置"的含义。

---

## 6. 参考架构与配置示例

### 6.1 分层架构

```
┌─ 配置层 ──────────────────────────────────────────────┐
│  run.yaml = Provider × DomainPlugin × Modules × Skills │
├─ 控制面 ──────────────────────────────────────────────┤
│  Coordinator(M1) ── OperatorRegistry(M2) ── Budget(M3) │
│        │ 受控 mutation（白名单）                        │
├─ 数据面 ──────────────────────────────────────────────┤
│  Frontier(M4: 骨架边+引用边) ─ Memory(M5) ─ Knowledge(M6)│
│        │ 多投影 view()           ▲ checkpoint 钩子      │
├─ 执行面 ──────────────────────────────────────────────┤
│  ExecutorPool(M7) → Evaluator(M8) → AdmissionGate(M9)  │
├─ 横切 ────────────────────────────────────────────────┤
│  X1: git lineage / checkpoint / events / 防篡改 / 审计  │
│  X2: interaction mode / 人工 gate / steering           │
└────────────────────────────────────────────────────────┘
```

### 6.2 配置示例（YAML 风格，示意）

**(a) 复刻 Arbor**：
```yaml
policy: { type: llm_cycles, steps: [observe, ideate, select, dispatch, absorb, admit] }
operators: [hypothesis_refine]
frontier: { structure: tree, ref_edges: false, scope_descriptor: ancestors }
memory: { levels: [l1, l2], l2_op: insight_delta, index: topology }
executor: { isolation: git_worktree, spec: { role: general, hypothesis: frozen } }
evaluator: { contract: { direction: max, cmd: "bash {cwd}/eval.sh" }, bandwidth: scalar_plus }
admission: { layers: [dev, test], trigger: {min_dev_gain: 0.05}, margin: 0.0, monotonicity: true }
budget: { max_cycles: 20, tree_depth: 2, convergence: {velocity: true, exhausted_parents: true} }
```

**(b) 复刻 OpenEvolve/AlphaEvolve**：
```yaml
policy: { type: round_robin }
operators: [llm_diff_mutation, crossover]
frontier: { structure: map_elites_islands, migration: {interval: 10, top_frac: 0.2}, pressure: boltzmann }
memory: { levels: [l1], index: none }     # 实例仓库=无语义记忆（=其已知缺口）
executor: { isolation: process_pool, async: true }
evaluator: { cascade: [stage1, stage2, stage3], bandwidth: metrics_plus_artifacts }
admission: { layers: [dev], selection: cell_competition }
budget: { quotas: {proposal: x, eval: y, db: z} }
```

**(c) 复刻 AIDE/AIRA**：
```yaml
policy: { type: registry, name: greedy }   # 可换 mcts / evolutionary
operators: [draft, debug, improve, memory?]
frontier: { structure: tree }
memory: { levels: [l1, l2], l2_op: summary, index: topology, scope_descriptor: parent_siblings }
executor: { isolation: container, call: single_shot }
evaluator: { bandwidth: scalar }
admission: { layers: [dev], selection: best, final_selector: configurable }  # AIRA 关键：终选独立
```

**(d) 高成本工业场景（10h+ 单次真实评估，本团队场景）**：
```yaml
# 预算数学前提（显式声明，否则配置不可行）：
# 假设 evaluator 并行度 = 4 路；预算以 GPU·h 计而非 wall_clock
# full_eval 10h × 3 seeds = 30 GPU·h/次；call_budget 8 次 → 240 GPU·h
# final_audit 10h × 10 seeds = 100 GPU·h（仅 1 次）；proxy_dev 成本可忽略
policy: { type: llm_cycles }
operators: [hypothesis_refine, comparative_reflect]   # MARS 差分归因补信用分配
frontier: { structure: tree, ref_edges: true, scope_descriptor: parent_siblings_plus_topk }
memory: { levels: [l1, l2], l2_op: delta_merge, index: [topology, semantic], provenance: required }
executor: { isolation: git_worktree, spec: { role: general, hypothesis: frozen } }
evaluator:
  bandwidth: scalar_plus_uncertainty
  partial_curves: if_available            # 10h 评估可能是无中间曲线的黑盒
  resume_from: checkpoint                 # 必备：10h 评估承受不起从头重跑
  fidelity_ladder:                        # 核心：便宜代理 → 昂贵真实
    - { name: proxy_dev,  cost: minutes,  seeds: 3, role: exploration }
    - { name: full_eval,  cost: 10h,      seeds: 3, role: admission, parallel: 4 }
    - { name: final_eval, cost: 10h,      seeds: 10, role: audit, runs: 1 }
  proxy_validity:                         # 异质代理的必备监控（M3）
    anchor_eval: { every_n_cycles: 5 }    # 定期全评估校准代理
    rank_correlation_monitor: true        # 代理漂移告警
admission:
  layers: [dev, admission, final_audit]   # 三层，规避 Arbor 式 adaptive overfitting 争议
  trigger: { min_proxy_gain: 0.05 }       # 注意：0.05 为同指标 dev 域经验值，异质代理需重新标定
  call_budget: 8                           # 10h×3seeds 评估是稀缺资源，硬顶
  integrity_hooks: [hash_check, paired_seed_test]
budget:
  global: { gpu_hours: 400 }
  direction_level: cost_aware_value        # MARS 式 w（w 调度为未验证提案）
  convergence: { rule_based: {max_no_improve: 3}, exhausted_parents: true }  # 低样本 regime 降级（M3）
```

**(e) 跨 run 知识积累模式（本团队经验管理方向）**：
```yaml
memory:
  levels: [l1, l2, l3]              # L3 跨 run 持久层
  l3_store: { type: kv_graph, index: [embedding, hypothesis_path], provenance: required }
knowledge:
  lanes: { grounded_ideation: true, novelty_audit: true }   # 真实研究模式
  graph_schema: [principle, implementation, environment, heuristic]
```

---

## 7. 设计决策清单（含证据强度）与反模式

### 7.1 必须有（强证据）
- [ ] **结构化语义记忆**（树绑定/分层/作用域化）——平铺记忆无效（K1 冲突区的调和结论）【强】
- [ ] **独立 Admission 模块 + (dev_best, gate_selected, final_audit) 三元组报告**【强】
- [ ] **失败一等公民**：eval_status 分类 + 错误写进 trajectory【强】
- [ ] **受控 mutation 白名单**：LLM 决策、机制落状态【强】
- [ ] **Evaluator 分层返回类型**（status/metrics/cost/fidelity 必选）【强】
- [ ] **provenance 贯穿**：记忆项、知识项、证据项全部带来源指针【强】
- [ ] **checkpoint/resume + 事件总线**【工程刚需】

### 7.2 应该有（中证据）
- [ ] fidelity 级联 + paired-seed 验收（高成本场景升级为必须）【中-强】
- [ ] 收敛/方向耗尽检测（不止轮数上限）【中】
- [ ] 引用边（骨架边 + 引用边双层图；context 检索策略独立可配）【中】
- [ ] comparative-reflect 差分归因算子（补 credit assignment）【中】
- [ ] 预算状态注入 prompt（零成本增强）【中】
- [ ] 两车道外部知识（grounding 与 novelty audit 隔离）【中】

### 7.3 可后置（弱证据/未成瓶颈）
- [ ] 高级搜索拓扑（MCTS/evo）——算子与记忆到位前无差异【弱】
- [ ] 学习型算子选择 π_op【弱】
- [ ] 容器隔离（规模化前 worktree 足够）【工程权衡】
- [ ] LLM judge 参与准入——**且必须永远可复算信号兜底**【反模式预警】

### 7.4 反模式（有实证教训）
- ❌ 平铺文本记忆全局注入（AIRA 消融无差异）
- ❌ 记忆晋升整篇重写（ACE context collapse）
- ❌ test 反馈无限次参与搜索决策（adaptive overfitting；RE-Bench 作者自陈要改）
- ❌ LLM judge 单独放行准入（可被操纵；zero-shot 监视失效）
- ❌ 宣称的机制不做"实现保真度"观测（LoongFlow entropy 论文-源码落差）
- ❌ executor 可中途改假设（归因完整性崩坏，树上 insight 失去意义）

---

## 8. 空白点与差异化路线图

| # | 空白 | 依据 | 优先级建议 |
|---|---|---|---|
| 1 | **语义记忆 × 进化框架**：OpenEvolve 系全是实例仓库，"为何有效"不跨代沉淀 | dim06 | P0（生态位核心） |
| 2 | **统计显著的收敛检测** | 全领域朴素 early stop（dim03） | P1 |
| 3 | **跨 run 假设级记忆图谱**（L3 层 + 假设路径索引） | dim02 遗留 + 本团队方向 | P0（本团队差异化） |
| 4 | **三层评估协议成为默认**（dev/admission/final-audit + call_budget） | dim08 争议 | P0（高成本场景刚需） |
| 5 | **假设即 behavior descriptor**（语义 QD） | dim05 + GSME/ACES 先例 | P2 |
| 6 | **记忆晋升忠实度校验、负面智慧隔离、并发写一致性** | dim02 遗留 | P2 |
| 7 | **descriptor/机制的实现保真度可观测** | dim05 教训 | P2 |

**落地三步走建议**：
1. **MVP**：M1(LLM cycles) + M2(4 算子) + M4(树) + M5(L1/L2) + M7(worktree) + M8(分层契约) + M9(两层 gate) + X1(git/checkpoint)。对标 Arbor 开源版能力，但 M8/M9 接口按本文超集设计，为后续留位。
2. **差异化**：M5 L3 跨 run 层 + 三层 admission + fidelity 级联（直击本团队 10h 评估约束）。
3. **生态位**：frontier 插件化（MAP-Elites/island）+ 语义 descriptor + Bandit 策略注册表——覆盖进化系用户场景，形成"一个框架复刻所有系统"的叙事（正如 VeRL 之于 RLHF 框架）。

---

## 9. 附录

- 各机制单元完整调研：`../research/dim00-08/autoresearch_modular_dim00-08（9 个文件）`
- 交叉验证与冲突区：`../research/dim00-08/autoresearch_modular_cross_verification.md`
- 前序文档：`AutoResearch设计空间与Baseline统一分析.md`（七维视角，本文为其工程化升级版）
- 外部一手文献索引见各 dim 文件引用列表（AIDE/AIRA-dojo/ML-Master×2/MARS/R&D-Agent/AIBuildAI/LoongFlow/FM Agent/FunSearch/AlphaEvolve/OpenEvolve/ShinkaEvolve/GEPA/KAPSO/AiScientist/AutoMLGen/InternAgent/DataMaster/Arbor/RE-Bench/PostTrainBench/MLE-bench/Gasteiger 等，共 100+ 条）
