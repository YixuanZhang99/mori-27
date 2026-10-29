# Dim-07 调研报告：KAPSO + AiScientist-2026 —— 知识平面、Provenance 与持久工作区

> 调研范围：KAPSO（arXiv:2601.21526，MLE-Bench 排行榜名 Leeroo，Leeroo Team）与 AiScientist（arXiv:2604.13018，"Toward Autonomous Long-Horizon Engineering for ML Research"，人大高瓴/RUC AI Box + 阶跃星辰 Kai Jia 团队，非 2024 Sakana 的 The AI Scientist）。一手来源：arXiv HTML 全文（KAPSO v1/v2、AiScientist v2）+ 两个官方仓库（Leeroo-AI/kapso、AweAI-Team/AiScientist）源码与文档。独立检索/阅读 ≥17 次。

---

## 1. 各系统核心机制（伪代码级）

### 1.1 KAPSO：知识接地的评测器驱动程序优化框架

**顶层契约与四操作 API。** KAPSO 围绕一个简单契约：给定自然语言目标 g、预算 B、评测器契约 ℰ，产出可运行软件产物并以"测量驱动的迭代"持续改进。用户面 API 只有四个操作：`evolve`（评测器接地的优化循环）、`deploy`（把选中方案适配为目标运行时，返回统一 `Software.run()` 句柄）、`learn`（把仓库/playbook/论文等摄入统一知识库）、`research`（发现外部材料，返回结构化 findings，可作 evolve 上下文或 learn 种子）[^2^]。

**两平面分离。** 知识平面（knowledge plane）聚合仓库、文档、论文、web 材料、benchmark 产物、内部 playbook，托管在 MediaWiki 供人审阅/策展，同时索引进可插拔检索后端（默认 Neo4j 图索引 + Weaviate 向量索引）供机器检索；执行平面（execution plane）由显式评测器边界锚定：ProblemHandler/Evaluator 定义"如何执行、产出什么、如何度量质量"，编排逻辑与评测器解耦，换评测器即可跨域复用同一 evolve 循环[^2^]。

**Evaluator contract 的一般化（本维度最重要的形式化之一）。** 评测器契约 ℰ = (P, Run, Stop, Select, Agg)：

- `P(β)`：预算进度 β∈[0,1] 处呈现给系统的问题上下文（可预算感知）；
- `Run(c; θ)`：在评测器配置 θ 下执行产物 c，返回**测量记录** `R(c) = (status, M(c), F(c), A(c))`——status（success/error，即可行性）、M 定量指标（标量或向量）、F 定性反馈（自由文本/结构化诊断/评委理由）、A 附属产物（日志、trace、产出文件）；
- 选择规则二选一：标量效用 `U(R(c))∈ℝ` **或** 测量记录上的**偏好关系 ≻**（可由自动指标、测试套件、规则比较器、LLM judge 或人在环策略实现）；
- **随机 rollout 聚合**：评测器跑 K 次 rollout，聚合算子 `R̂_K(c)=Agg^R_K(R⁽¹⁾,…,R⁽ᴷ⁾)` 与 `Ĵ_K(c)=Agg^J_K(U(R⁽¹⁾),…)`，概念优化目标定义为 `J*(c)=𝔼[U(R(c))]`（显式区分 U(𝔼[R]) 与 𝔼[U(R)]）；
- 不可行处理：error 对应不可行产物，U 赋哨兵值（如 −∞）或 ≻ 恒偏好可行记录；
- `Stop(β, H)`：按预算进度与实验历史提前终止[^2^]。

**Git-native 实验引擎（provenance 的物理实现）。** 每个实验 = ExperimentWorkspace 中的一个独立 git branch。ExperimentSession 从父 branch 创建新 branch b，CodingAgent 施加编辑，ProblemHandler 执行评测，然后把产物状态与运行输出**提交到该 branch**；`close_session()` 总是 `git push origin <branch>`——origin 通常不是网络远端，而是从 `file://<base_repo>` 克隆的本地工作区仓库，push 的作用是把 branch 发布回本地 ExperimentWorkspace，使其立即可作为树状探索中子实验的父节点。每个实验提交的可复现 bundle 包括：相对父 branch 的 diff 与 commit id、评测器配置（含随机聚合的 rollout 数 K）、运行日志与结构化诊断、评测器产物（输出文件/trace）[^2^][^6^]。形式化地，实验历史 H_i = {e_1..e_{i-1}}，其中 `e_j = (b_j, u_j, β_j, c_j, K_j, R̂_K(c_j), Ĵ_K(c_j))`，`c_j := RepoState(b_j)`——**branch 是产物的规范引用，评测记录挂在 branch 上**[^2^]。

**核心循环（Orchestrator + SearchStrategy）。** 论文 Algorithm 1/2：

```
# Algorithm 1: solve loop (OrchestratorAgent.solve, 由 Kapso.evolve 调用)
H_0 = ∅; i = 0
while i < N:
    β_i = budget_progress(B, i)                # 时间/迭代/成本三通道取最大
    if Stop(β_i, H_i) or β_i ≥ 1: break
    x_i = M.get_context(β_i)                   # P(β)+知识包+episodic memory+H_i
    new_experiments = S.run(x_i, β_i)          # SearchStrategy: linear 或 tree
    H_{i+1} = H_i ∪ new_experiments
return best artifact in H under U or ≻

# Algorithm 2: implement-and-debug (branch 级内循环；debug 只修可行性,不做目标优化)
session = create_experiment_session(branch=b, parent=p)
r = implement_solution(u, x, session)          # codegen + Run
for k in 1..D:
    if r.has_error_or_contract_violation: r = debug_solution(u, x, r, session)
    else: break
finalize_session(session)                      # commits + push + cleanup
```

树搜索实例化（§3.7）：每轮 LLM 对叶节点做 Prune（基于 P(β_i)、K_i、H_i）→ Expand（探索/利用权衡，LLM ensemble 生成子 solution spec）→ Select（top-k 叶节点送评测）。可视为"solution spec 上的学习型提议分布 + Run(·) 黑盒评测 + U/≻ 选择"[^2^]。仓库代码与论文一致：OrchestratorAgent 组合四个可插拔子系统 SearchStrategy / ContextManager / KnowledgeSearch / CodingAgent[^2^][^17^]。

**认知控制器（cognitive memory，Algorithm 3）。** 控制器状态 C_i = (g, 当前知识包 K_i, 最新实验 e_{i-1}, 检索到的 episodic insight Z_i, 元统计如连续失败数)。每实验后：

```
if e.has_error_or_contract_violation:
    E.add(ExtractIssue(g, e))                  # 失败泛化为可复用 fix pattern
    K = ERA(g, e, K)                           # 错误恢复增强, 附 provenance
elif e.feedback 非空:
    E.add(ExtractInsight(g, e.feedback))       # 成功/改进 → best-practice insight
Z = RetrieveEpisodic(E, g, e)
a = DecideAction(g, K, e, Z)                   # RETRY / PIVOT / COMPLETE
if a == PIVOT: K = RetrieveCascade(g, s=None)  # 排除当前 workflow/种子仓库, 鼓励换起点
```

检索为级联策略：**WSR 主检索 + PFR 回退 + ERA 错误增强**[^2^]。仓库代码（archive/memory/knowledge_retriever.py）揭示其三层实现：TIER1 精确 Workflow 匹配（page_type=Workflow、score≥0.7 阈值、LLM 生成多个 workflow 查询）→ 图遍历展开 Workflow→Steps→Principles→Implementations→Heuristics 全嵌套知识；TIER2 无 workflow 命中时退回相关 Principle 页（"不伪造 workflow"）；TIER3 出错时向现有知识追加错误针对性 heuristics[^5^]。（据此推断 WSR≈Workflow-Seeded Retrieval、PFR≈Page-Focused Retrieval，与代码的 Tier1/Tier2 对应；论文未展开缩写，此为推断。）

### 1.2 AiScientist-2026：thin control over thick state 的层级研究团队

**问题化。** 把 long-horizon ML research engineering 定义为"累积项目状态问题"：agent 调用是瞬态的，研究进展必须累积且持久。由此提出两个连续性需求——**role continuity**（专家再次被调用时能从角色级既有工作恢复：试过什么、假设什么、哪些失败、遗留什么问题）与 **project continuity**（不同角色围绕全项目共享证据协作，而不是靠有损对话交接）[^12^]。

**File-as-Bus：schema 治理的产物协议。** File-as-Bus 不是共享存储，而是"产物中介的协调协议"：agent 通过发布/消费持久产物来协调，workspace 即项目进展的 **system of record**。设 σ 为 File-as-Bus schema，规定每个产物的**用途、更新模式、写者集合、读者集合**；W_t 为 t 步的持久工作区状态；**workspace map** 是产物状态+schema 元数据的紧凑运行时视图 `m_t = ℳ(W_t; σ)`，agent 先从 m_t 定位相关产物，再按需深读 W_t 的特定部分[^12^]。σ 区分三种更新模式：

- **append-only logs**：保存时序证据，不可改写（实现日志、实验诊断）；
- **versioned artifacts**：维护规范当前版本、保留历史修订（计划、分析、报告）；
- **mutable state**：短生命周期控制信息/可直接编辑的项目状态（源码、setup 脚本、入口），其决策史由 append-only log 承载而非对每个文件做版本[^12^]。

论文 Table 3 给出完整产物 schema（paper 轨）：`paper_analysis/{summary,structured,algorithm,baseline}.md`（versioned，写者=Paper Comprehension）、`agent/prioritized_task.md`（versioned，写者=Prioritization）、`submission/`（mutable runnable，写者=Implementation）、`agent/impl_log.md`（append-only，写者=Implementation）、`agent/exp_log.md`（append-only，写者=Experimentation）；读者集合显式列出（如 impl_log 的读者含 Orchestrator/Paper Comprehension/Prioritization/Experimentation）[^12^]。

**层级研究团队 + Agent-as-Tool。** Tier-0 Orchestrator 维持紧凑控制上下文 c_t，输出 stage 级指令而非过程脚本；关键抽象是 **Agent-as-Tool**：`a_t = π_0(c_t, m_t), a_t ∈ 𝒯_0 ∪ 𝒜_1`——专家调用与普通工具调用同属一个动作空间，委派是选择性的。Tier-1 专家：Paper Comprehension（内部用 DAG-based subagent 协调器并行做 Algorithm/Experiments/Baseline 抽取再 Synthesis）、Prioritization、Implementation（full mode 建仓 / fix mode 打补丁）、Experimentation（执行+对照+诊断）、Generic Helper（General/Explore/Plan 子代理）。专家被调用时收到指令 d_t 与 workspace map，读 W_t 中任务相关产物，写回**简洁摘要 s_t 与工作区增量 ΔW_t**：`(s_t, ΔW_t) = π_j(d_t, m_t; W_t)`，`W_{t+1} = 𝒰(W_t, ΔW_t)`——摘要更新 Orchestrator 的薄控制视图，ΔW 把详细进展留进厚状态。Tier-2 subagent 只做有界子任务，默认只读，层级不递归[^12^]。

**MLE 轨的工程实现（仓库证据）。** 每个角色有定制 workspace reference 表（Orchestrator 2 列全知视图；专家 3 列带 Availability）；`FILE_AS_BUS` 环境变量是消融开关（默认 true，`0/false/no/off` 关闭，关闭后 workspace reference 移除 impl_log/exp_log 共享总线）；`/home/code` 是 git 仓库；`submission_registry.jsonl` 为 append-only 候选注册表（`candidate_detail`/`champion_selected` 行：方法、指标、eval protocol、 rationale）；`/home/submission/candidates/` 存不可变候选快照；orchestrator 在子代理间做"上下文注入"（impl_log→experiment、exp_log→implement），并要求专家"先 `git log --oneline -15` + 读对方日志 + 对照实际代码验证"再行动——防止重复修已修问题[^14^][^15^]。

---

## 2. 类型化知识/证据 Schema 分析（本维度核心）

### 2.1 KAPSO 的类型化知识图

**节点类型（4+1）。** 论文形式化：`𝒦=(𝒱,ℰ_K)`，每个节点 = 一页类型化 wiki page，含 ID、标题、类型 ∈ {**Principle, Implementation, Environment, Heuristic**}、正文（可含代码片段）[^2^]。仓库代码（archive/memory/kg_types.py）显示实现层还有第五个根类型 **Workflow**，图骨架为：

```
Workflow ──uses_heuristic──▶ Heuristic (workflow 级)
   └──step──▶ Principle ──implemented_by──▶ Implementation (强制≥1, "可执行约束")
                │                               ├──requires_env──▶ Environment
                │                               └──uses_heuristic──▶ Heuristic
                └──uses_heuristic──▶ Heuristic (principle 级)
```

各类型语义：Principle=库无关的理论/概念（what & why，必须挂至少一个 Implementation）；Implementation=具体代码/API 用法（含全部代码示例）；Environment=软硬件要求（CUDA 版本、RAM 等）；Heuristic=技巧/优化/调试建议（叶子节点，可被 Workflow/Principle/Implementation 引用）[^4^]。

**边类型。** IMPLEMENTED_BY、USES_HEURISTIC、REQUIRES_ENV、交叉引用边；另有仓库关联：SOURCE_REPO 元数据与 RELATED_REPO 链接（支持 repo 条件检索）[^2^]。

**写入接口（learn / KnowledgePipeline）。** 两阶段：Stage-1 Ingestor（Source.Repo/Idea/Implementation/ResearchReport/Solution → 类型化 WikiPage；RepoIngestor 识别入口点、依赖/环境要求、高信号实现模式，抽取 P/I/E/H 四类页，另做确定性文件挖掘把 README 未强调但可复用的脚本/配置/评测工具 triage 成页）；Stage-2 Merger（层级、子图感知的合并进既有 KG）[^10^]。**每个抽取项都附 provenance：链回仓库路径与 commit**[^2^]。

**查询接口。** 两级检索：(1) `RepoRetrieve(g) → (r̂, ρ)`：混合信号（README/文件树 embedding + 元数据过滤）选种子仓库，置信度 ρ≥τ 则以 `RepoState(r̂)` 初始化，否则从 scaffold 起步；(2) `KnowledgeRetrieve`：从类型化索引取 P/I/E/H，可以种子仓库为条件。后端可插拔：`kg_graph_search`（Weaviate 语义检索 → LLM rerank → Neo4j 图扩充邻居页）或 `kg_llm_navigation`（LLM 导航器直接走图）[^2^][^7^]。

**返回类型 = 知识包（KGKnowledge）。** 含：(i) 可选种子仓库引用+置信度 ρ；(ii) 按类型分组的检索页集合；(iii) 置信分数与 **provenance 元数据（`query_used`、`source_pages`）**；(iv) ERA 触发时的恢复附件（失败条件 heuristics、诊断、替代实现，同样带 provenance）[^2^]。代码中 KGKnowledge 还携带 tier 标记（TIER1_EXACT/TIER2_RELEVANT/TIER3_ERROR）[^4^][^5^]。

**Episodic memory（自知识）。** 条目 schema：紧凑 trigger 描述 + 泛化 lesson + 推荐动作 + **provenance 链回源实验 branch 及其产物（日志、diff、评测反馈）**；存 Weaviate（JSON 回退），按目标与失败信号语义检索；成功时抽 best-practice insight（含 LLM 评委理由），失败时把错误泛化为可复用 fix pattern[^2^]。

**实验记录（代码层 schema）。** `ExperimentRecord(node_id, solution, score, feedback, branch_name, had_error, error_message, timestamp, technical_difficulties, metrics: Dict[str,float], primary_metric, external_evaluation_metadata, evaluation_valid, evaluation_provenance, evaluation_integrity_error)`——注意 **evaluation_provenance 是一等字段**（默认 "agent_generated"），且有专门的评测完整性错误字段；双写存储（JSON + Weaviate 语义检索），同时供 orchestrator 进程内写入与 MCP server 进程外查询[^9^]。

**RepoMemory（证据接地的仓库理解）。** schema v2：每个 claim = `{kind, statement, evidence: [{path, quote}]}`——**所有断言必须挂文件级证据**；分节（architecture/entrypoints/where_to_edit/invariants/testing/gotchas/dependencies）；子实验继承父实验 memory；prompt 侧用 summary+TOC 有界渲染、分节按需深读[^8^]。这是 AiScientist workspace map 的 KAPSO 对应物，但证据粒度更细（到 quote 级）。

### 2.2 AiScientist 的产物 Schema（File-as-Bus σ）

σ 不是图，而是**类型化文件产物注册表**：每个产物声明 {路径, 用途, 更新模式, 写者, 读者}。三种更新模式（append-only / versioned / mutable）匹配不同证据生命周期："有些证据永不应被覆盖，有些需要稳定当前版+可恢复历史，有些应保持轻量"[^12^]。角色作用域访问策略：Tier-1 专家主要写自己负责的产物，所有角色可读上游证据；Tier-2 默认只读。每次专家调用后 workspace map 从当前产物状态+schema 元数据刷新，给 Orchestrator 一份"不装入全工作区"的紧凑证据索引[^12^]。MLE 轨的 `submission_registry.jsonl` 实际上是一个**轻量 provenance 图**：候选产物（不可变快照）→ 评测协议 → 指标 → champion 选择及其 rationale，全部 append-only[^14^]。

### 2.3 Provenance 追踪方式对比

| 维度 | KAPSO | AiScientist-2026 |
|---|---|---|
| 实验→产物 | branch id 即产物引用（c=RepoState(b)），实验记录 7 元组挂 branch | 文件路径即引用；候选快照不可变 + registry JSONL |
| 知识→来源 | query_used / source_pages / SOURCE_REPO / RELATED_REPO（页级+仓库 commit 级） | paper_analysis 产物即"论文→实现决策"的中间证据层；写者/读者集合记录角色来源 |
| 经验→实验 | episodic 条目链回 branch+logs+diffs+反馈 | impl_log/exp_log append-only，时间序即 provenance |
| 评测完整性 | ExperimentRecord.evaluation_provenance / evaluation_integrity_error 字段[^9^] | 评测在干净环境 fresh execution；validation_report.json |
| 人可审性 | MediaWiki 人工策展 + Docker 一键复现全栈（wiki dump + Neo4j/Weaviate 快照 + 仓库清单）[^2^] | workspace 落盘可 diff/audit/resume，无需从记忆重建[^13^] |

---

## 3. 关键设计决策与权衡（含消融证据）

**KAPSO：**

1. **"程序合成是算子而非终点"**：synthesis 内嵌在长程优化循环里，进展由评测器结果定义。权衡：完全依赖评测器质量——MLE-Bench 场景 KAPSO 每次提交都跑完整 test 集评分并以"获得任意奖牌"为早停条件（论文 §5.1 明确披露），社区 issue 指出这构成 test-set 反馈，与主榜规则存在争议[^2^][^16^]。
2. **Git-native 分支隔离 vs 单工作区**：换取可复现性、provenance 与"子实验可继承任意父实验"的树状探索能力；代价是每实验一次 clone+branch 的存储/IO 开销，且默认本地执行（容器化仅在评测器要求时引入）[^2^][^6^]。
3. **知识平面双表示（人读 MediaWiki / 机读图+向量索引）**：换取 human-in-the-loop 策展与审计能力；代价是摄入-索引-同步管线重（wiki→Neo4j/Weaviate 同步服务）[^2^]。
4. **级联检索 + ERA**：TIER1 找不到 workflow 时"不伪造 workflow"（TIER2 只返回相关页），失败时才触发 TIER3 错误定向增强——把"什么时候注入什么知识"做成显式状态机而非一次性 RAG[^5^]。
5. **结果**：MLE-Bench 开源系统第一——Low 68.18%（与 R&D-Agent 持平）、Medium 44.74%（vs 21.05%）、Hard 40.00%（vs 22.22%），难度越高优势越大；ALE-Bench ELO 1909.4 / RP 6.1%（vs ALE-Agent 1879.3 / 6.8%），且成本更低（$914.8 vs $1003.3）[^2^]。注意论文没有给出移除知识系统/episodic memory 的消融表（仅贡献声明提及 ablations，正文只有基准对比），其组件级归因证据弱于 AiScientist。

**AiScientist-2026：**

1. **File-as-Bus 消融（本维度最有力的证据）**：移除 File-as-Bus（`FILE_AS_BUS=false`，去掉 impl_log/exp_log 共享总线）→ PaperBench 均分 **−6.41**、MLE-Bench Lite Any Medal **−31.82**（81.82→50.00）。分解极具诊断性：Valid Submission 与 Bronze 基本不降，Above Median/Silver/Gold 大幅劣化——**持久状态对"做出最小可跑起点"不关键，对"后期诊断与改进轮次"关键**[^12^][^14^]。
2. **行为分析**：有 File-as-Bus 时高分轨迹把后期精力花在 validation 与 closure 上、实验步数反而更少；无 File-as-Bus 时高分轨迹需要显著更多 implementation/experimentation 步——证据复用效率低。说明成功轨迹不是"试更多变体"，而是"更早得到可用实现 + 后期闭环验证"[^12^]。
3. **层级组织与总线正交**：去掉 File-as-Bus 后层级架构本身仍比简单非层级基线强（PaperBench +4.74；MLE-Bench Lite Above Median +22.73、Any Medal +9.09）——durable state 与控制结构是两个独立增益源[^12^]。
4. **Thin control 的成本收益**：比 IterativeAgent 交互更少却更强（PaperBench $15.67 vs $27.44/task、$12.20 vs $54.90/task），证明"更多轮次"不解释长程性能，轮次必须围绕累积证据组织[^12^]。
5. **时间动力学**：AiScientist 早期慢（预算花在理解/规划/脚手架），AIDE/Codex 早期快但 6–12h 后 plateau，AiScientist 持续改善至 24h——前期投资 durable scaffold 的回报在后期[^12^]。
6. **权衡/局限**：schema 治理的产物协议需要预定义写者/读者契约，泛化到新阶段要改 σ；workspace map 是"索引"不是"保证"，专家仍需自觉"先读日志+对照代码验证"（prompt 工程弥补而非机制保证）；PaperBench 全套评测约 $832，重复大规模消融受限[^12^][^15^]。

---

## 4. 八轴卡

| 轴 | KAPSO (Leeroo) | AiScientist-2026 |
|---|---|---|
| **优化对象** | 可执行仓库状态 c（代码产物）；J*(c)=𝔼[U(R(c))]，可为标量/多指标/偏好 | runnable ML system（submission/ 仓库）；PaperBench 复现 rubric 分 / MLE 竞赛指标 |
| **基本搜索单元** | 实验 e=(branch, solution spec u, β, K, R̂, Ĵ)；一实验一 git branch | 一次专家调用 π_j(d_t, m_t; W_t) → (s_t, ΔW_t)；产物增量 ΔW |
| **算子** | ideation(LLM ensemble 生成 spec)、代码合成/编辑、implement-debug(D 次)、ERA 恢复、PIVOT 换种子、lesson 抽取 | paper 理解→优先级→实现→实验的角色委派；full-build/patch、EnvSetup/ResDownload 子代理、diagnose |
| **拓扑** | 线性搜索 或 LLM-steered 树搜索（prune/expand/select，git 分支树承载） | 星型层级：Tier-0 Orchestrator → Tier-1 专家 →（非递归）Tier-2 子代理；研究流程为自适应环而非树 |
| **持久状态** | git branch 树（实验）+ MediaWiki/Neo4j/Weaviate 知识平面 + Weaviate episodic store + RepoMemory | File-as-Bus 工作区（append-only/versioned/mutable 三类产物）+ workspace map + 候选注册表 |
| **反馈权限** | 评测器契约 ℰ=(P,Run,Stop,Select,Agg)：自动指标/测试/judge/人、随机 K rollout 聚合；MLE 场景用 test 集评分+奖牌早停（有争议）[^16^] | 干净环境 fresh execution；CV/validation 作 medal 代理；提交格式硬校验+软警告 |
| **失败利用** | 失败→episodic fix pattern（trigger/lesson/action/provenance）；ERA 注入错误条件 heuristics；状态机 RETRY/PIVOT/COMPLETE | 失败写入 append-only exp_log（失败+诊断+证据），后续调用重接地；"对照代码验证日志"防重复修复 |
| **并行与选择** | 多 ExperimentSession 并发；top-k 叶节点送测；U 或 ≻ 选择（可行>不可行哨兵） | 主要串行委派（并行训练作业在 runs/ 下允许，但 submission.csv 唯一写者）；champion 选择经 registry 显式记录 rationale |

---

## 5. 对统一框架的接口启示

### 5.1 "研究状态存储"的统一 schema 建议

两个系统给出了互补答案：KAPSO 证明**类型化知识图 + branch 级实验 provenance** 可行且高回报（Hard 任务优势最大）；AiScientist 用消融证明**durable、schema 治理的厚状态**本身就是 31.82 分级别的增益来源。统一框架的研究状态存储建议采用**四类子图 + 一等 provenance 边**：

1. **Hypothesis 子图（提议层）**：节点=SolutionSpec/Hypothesis（KAPSO 的 u、AiScientist 的 prioritized_task 条目），边=DERIVED_FROM（树搜索父子）、REFUTES/SUPPORTS、PIVOTED_FROM。对应 KAPSO 树节点与 AiScientist 的 versioned plan。
2. **Artifact 子图（产物层）**：节点=不可变产物引用（git branch/commit、文件快照、种子仓库），边=PARENT_BRANCH（KAPSO 的 c=RepoState(b)）、ADAPTED_TO（deploy 策略适配）、SNAPSHOT_OF（AiScientist candidates/）。**产物只存引用+摘要，实体交给 git/文件系统**——两个系统都不约而同地让 git 做版本化的重活。
3. **Evidence 子图（证据层）**：节点=测量记录与诊断，边=MEASURED_ON(→Artifact)、GENERATED_BY(→Hypothesis/Evaluator config)。KAPSO 的 R(c)=(status,M,F,A) 与 AiScientist 的 exp_log/registry 行是同构的。必须保留：K 次 rollout 原始记录 + 聚合记录两级；评测器配置（含 K、eval protocol）作为 evidence 的一部分；**evaluation_provenance/integrity 字段**（KAPSO 代码已实践）[^9^]。
4. **Knowledge 子图（知识层）**：节点=类型化知识页（P/I/E/H + Workflow 根），边=IMPLEMENTED_BY/USES_HEURISTIC/REQUIRES_ENV/SOURCE_REPO；另有 episodic lesson 节点（trigger/lesson/action），边=DISTILLED_FROM(→Evidence)。查询接口统一为"知识包"：分组内容+置信度+`query_used`/`source_pages` provenance，并区分 tier（精确命中/相关回退/错误定向）——这等价于把检索策略显式编码进返回类型，便于下游审计"这条建议从何而来"。

**横切机制（比节点类型更重要）：**

- **更新模式类型化**：每个状态条目声明 append-only / versioned / mutable。AiScientist 的消融说明这不是工程洁癖而是性能来源；append-only 用于证据（不可改写），versioned 用于计划/分析（当前版+历史），mutable 用于代码（历史交给 git 与日志）。
- **写者/读者契约**：schema 级声明哪个角色/算子可写、谁消费，使工作区成为"协作契约"而非 scratchpad；Tier-2/临时代理默认只读。
- **紧凑索引（workspace map / summary+TOC）**：控制面只消费索引 m_t=ℳ(W_t;σ)，按需深读——这是"thin control over thick state"的接口形态，统一框架的控制器不应把全状态塞进上下文。
- **持久工作区 vs 树状研究状态的关系**：两者是**物化层与索引层**的关系。持久工作区（git 仓库/文件总线）是厚状态的物化载体，保存当前可执行前沿与全部原始证据；树状研究状态是挂在工作区之上的**版本化索引**——每个树节点=(hypothesis 引用, parent 引用, artifact 引用(branch/commit), evidence 引用, 聚合效用)。KAPSO 让 git 分支树直接承载研究树（push 回本地 origin 使新 branch 立即可做父节点）；AiScientist 基本不建树（best-so-far 线性前沿 + registry），其消融显示无树也能强，但 KAPSO 的树搜索表明在目标明确可评测时树状索引带来系统性探索。建议统一框架：**工作区为必需基底，树/图索引为可选视图**，索引节点一律存轻引用而非状态拷贝。

### 5.2 Evaluator 返回值的类型建议

直接采纳并推广 KAPSO 的测量记录（两系统实践 + 其形式化最完整）：

```
EvaluationRecord = {
  status: SUCCESS | ERROR | CONTRACT_VIOLATION,   # 可行性一等化（不可行≠低分）
  metrics: Dict[str, float],                       # 多指标向量, 标量是特例
  feedback: Text | StructuredDiagnostics,          # 定性反馈/评委理由/诊断
  artifacts: List[ArtifactRef],                    # 日志/trace/产出文件(引用)
  rollouts: Optional[List[EvaluationRecord]],      # K 次随机 rollout 原始记录
  config: EvaluatorConfig,                         # 含 K、eval protocol、环境
  provenance: {source: agent|external, integrity_flags...}
}
```

配套契约：(a) 选择规则与记录解耦——框架接受 `U: Record→ℝ` **或** `≻: Record×Record→Bool`（标量/多指标/偏好/LLM judge/人均可插拔）；(b) 聚合算子 `Agg^R_K`、`Agg^J_K` 作为评测器配置的一部分并随记录持久化，概念目标统一定义为 J*(c)=𝔼[U(R(c))]，避免 U(𝔼R) 与 𝔼U(R) 歧义；(c) 不可行处理规约化（哨兵效用或偏好规则恒序）；(d) debug 循环只修 `status≠SUCCESS`，目标优化交给搜索层——KAPSO 把"修可行性"与"优化目标"分成两个预算是值得保留的边界[^2^]。

---

## 参考来源

[^1^]: KAPSO arXiv 摘要页, https://arxiv.org/abs/2601.21526
[^2^]: KAPSO arXiv HTML v2 全文（§2–§5、Algorithm 1–3、评测器契约、知识系统、认知记忆、实验引擎、结果表）, https://arxiv.org/html/2601.21526v2
[^3^]: KAPSO arXiv HTML v1, https://arxiv.org/html/2601.21526v1
[^4^]: Leeroo-AI/kapso 仓库 `archive/memory/kg_types.py`（Workflow/Principle/Implementation/Environment/Heuristic 数据结构与图骨架、KGTier）, https://github.com/Leeroo-AI/kapso/blob/main/archive/memory/kg_types.py
[^5^]: Leeroo-AI/kapso 仓库 `archive/memory/knowledge_retriever.py`（TIER1/2/3 级联检索实现）, https://github.com/Leeroo-AI/kapso/blob/main/archive/memory/knowledge_retriever.py
[^6^]: kapso 文档 `docs/evolve/experiment-lifecycle.mdx`（git branch 模型与 ExperimentSession 代码）, https://github.com/Leeroo-AI/kapso/blob/main/docs/evolve/experiment-lifecycle.mdx
[^7^]: kapso 文档 `docs/knowledge/search-backends.mdx`（kg_graph_search / kg_llm_navigation、KGSearchFilters/KGOutput）, https://github.com/Leeroo-AI/kapso/blob/main/docs/knowledge/search-backends.mdx
[^8^]: kapso 文档 `docs/evolve/repo-memory.mdx`（RepoMemory schema v2、claim-evidence 结构、分支继承）, https://github.com/Leeroo-AI/kapso/blob/main/docs/evolve/repo-memory.mdx
[^9^]: Leeroo-AI/kapso 仓库 `src/kapso/execution/memories/experiment_memory/store.py`（ExperimentRecord 字段含 evaluation_provenance）, https://github.com/Leeroo-AI/kapso/blob/main/src/kapso/execution/memories/experiment_memory/store.py
[^10^]: kapso 文档 `docs/knowledge/overview.mdx` 与 `docs/knowledge/learning-pipeline.mdx`（两阶段摄入、Source 类型、Merger）, https://github.com/Leeroo-AI/kapso/tree/main/docs/knowledge
[^11^]: AiScientist arXiv 摘要页, https://arxiv.org/abs/2604.13018
[^12^]: AiScientist arXiv HTML v2 全文（§3 File-as-Bus/层级团队、Table 3 产物 schema、§4.4–4.6 消融与行为分析、Appendix B/C）, https://arxiv.org/html/2604.13018v2
[^13^]: AweAI-Team/AiScientist README（File-as-Bus 运行时模型、双轨、workspace 落盘可审计）, https://github.com/AweAI-Team/AiScientist
[^14^]: AiScientist 仓库 `benchmark/MLE-bench/agents/aisci/constants.py`（FILE_AS_BUS 开关、角色 workspace reference 表、submission_registry/candidates）, https://github.com/AweAI-Team/AiScientist/blob/main/benchmark/MLE-bench/agents/aisci/constants.py
[^15^]: AiScientist 仓库 `agents/aisci/orchestrator.py` 与 `prompts/templates.py`（子代理适配工具、impl_log/exp_log 跨代理注入、"先验证代码状态"规则）, https://github.com/AweAI-Team/AiScientist/tree/main/benchmark/MLE-bench/agents/aisci
[^16^]: openai/mle-bench issue #138（KAPSO 每次提交使用完整 test 集评分+奖牌早停的争议，引用 KAPSO 论文 §5.1 与 handler 源码行号）, https://github.com/openai/mle-bench/issues/138
[^17^]: kapso 文档 `docs/evolve/orchestrator.mdx`（OrchestratorAgent solve 循环、预算进度三通道）, https://github.com/Leeroo-AI/kapso/blob/main/docs/evolve/orchestrator.mdx
