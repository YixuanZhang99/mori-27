# Group D：三篇 arXiv 新论文的九模块分析卡片

> 分析框架：M1 Policy/Coordinator（选点控制）、M2 Operator（类型化研究动作）、M3 BudgetController、M4 Frontier/State（树/DAG/population）、M5 Memory（L1 原始记录 / L2 洞见 / L3 方法知识）、M6 Knowledge（外部知识）、M7 Executor（role 同质/异质 × hypothesis 冻结/自由）、M8 Evaluator（评估带宽四档：标量 → 多指标+工件 → +文本反馈 → 完整轨迹）、M9 AdmissionGate（准入/最终选择）、X1 溯源审计、X2 人在环。
>
> 三篇均为真实存在的 arXiv 论文（2026 年 7–8 月），全文已阅读（arXiv HTML 版）。以下明确标注【论文明确】与【推断】。

---

## 论文 1：SEAL — Self-Authored Verification Is Unreliable in Heuristic Self-Improving Agents

- **出处**：arXiv:2607.24300v1，2026-07-27。作者 Diandian Guo, Cong Cao（通讯）等。未见代码链接。
- **一句话定位**：研究自改进智能体"自己写测试验证自己改的策略"这一内生验证失效问题（verifier–deployment gap），并提出一个 agent 看不见、改不了、只回 1 bit 的密封外部验收门（Sealed Exogenous Acceptance Loop）。
- **任务域**：程序化策略自改进（Atari ALE 上 policy.py + tests.py 共同进化），属于"启发式学习（Heuristic Learning）/代码级自改进"，非科研全流程。

### 九模块映射

| 模块 | 对应实现 |
|---|---|
| M1 Policy/Coordinator | 【论文明确】无显式选点控制器；单条 incumbent 轨迹，每轮由同一个 LLM agent 顺序提交候选（§Problem Setup）。退化为单链爬山。 |
| M2 Operator | 【论文明确】单一算子"edit"：agent 每轮同时改写 policy.py 和 tests.py，提交候选状态 x′=(π′,T′)。无 draft/crossover 等类型化动作区分。 |
| M3 BudgetController | 【论文明确】固定 10 轮 outer rounds；无自适应预算。slack 参数 ρ、δ_min 是验收阈值而非预算（§SEAL, Eq.3）。 |
| M4 Frontier/State | 【论文明确】单点 incumbent 状态 x_t=(π_t,T_t)，拒绝即整体回滚（whole-state rollback, Algorithm 1）。拓扑=单链。 |
| M5 Memory | 【论文明确】agent 可见 transcript H_t（当前 policy、自写 tests、历史 accept/reject、self-test 输出）——接近 **L1 原始记录**；无 L2 洞见/L3 方法知识分层。tests.py 本身是一种可执行"记忆"，但它是被优化对象而非记忆系统。 |
| M6 Knowledge | 无/默认。无外部知识源。 |
| M7 Executor | 【论文明确】**role=同质**（单个 LLM 同时做编辑+写测试）；**hypothesis=自由**（policy 和 tests 都可任意改写，没有冻结假设）。任务假设分布甚至由 agent 自己定义（tests.py），这正是失效根源。 |
| M8 Evaluator | 【论文明确】双通道：agent 可见 self-report r_t（标量 pass rate，**第一档：标量**）；harness 私有审计 A(π)（隐藏实例 rollout 的标量分），对 agent 只泄露 **1 bit accept/reject**——刻意把评估带宽压到最低档以下（§Information Limit, Algorithm 1 line 23-24）。 |
| M9 AdmissionGate | 【论文明确】**这是全文核心**。SEAL = 密封外部验收门：固定 harness 侧审计 A（隐藏 seeds/分布，与最终部署评估不相交），保守非回归规则 c_t ≥ b_t − δ_t，拒绝则整体回滚，只回 1 bit。四个设计条件：外生性、密封性、单比特反馈、保守更新（Table 2）。 |
| X1 溯源审计 | 【论文明确】部分：离线记录 deployment truth、self-report、test 编辑结构分类用于事后分析（§Metrics）；但不给 agent 用。 |
| X2 人在环 | 无/默认。审计是"executable, task-native scoring procedure"，明确不是人也不是监督模型（§SEAL）。 |

### 核心创新落点与对框架的冲击
- **核心创新落在 M9（AdmissionGate）+ M8（评估带宽的刻意收窄）**。SEAL 与常见直觉相反：不是提高评估带宽，而是证明内生证据有信息论下界（Eq.1：α+β ≥ 1−TV(P₊,P₋)），必须引入一个 agent 不可观察的外部门，且**反馈只能是 1 bit**——leaky-anchor 实验证明泄露数值审计分反而显著变差（Doubao 35.1→12.7，§Audit leakage）。
- **对 Candidate 类型定义的冲击：有，且值得记录**。本文 Candidate 不是"任务解工件"π，而是**联合状态 x=(π, T)**：解 + 它自己的验证器。验证器成为可进化对象（"the verifier itself becomes part of the evolving system"，§Introduction）。这冲击"Candidate=任务解工件"的定义：当系统允许 agent 自写验收标准时，Candidate 类型必须包含验证器组件，且 M8/M9 必须区分"内生验证器"与"外生验证器"。
- 与 OpenAI 的 SEAL（Self-Adapting Language Models, 自适应权重）**不是同一篇**——本文不涉及参数更新，Candidate 是代码策略。【论文明确：updated object 是 software 而非 model weights】

### 【装不下的机制】
1. **验证器-被验证物共同进化的利益冲突结构**：九模块把 M8 Evaluator 当作系统固定组件，本文恰恰研究 Evaluator 被拖进 Candidate 后的失效模式。框架缺少"Evaluator 是否内生/可进化"这一维度——这是最重要的缺口信号。
2. **信息密封边界（sealed information boundary）**：九模块默认各模块信息共享，SEAL 的核心是刻意制造信息不对称（audit 实例、分数、slack 全部隐藏，Algorithm 1 line 24）。框架没有"哪些模块对 Executor 不可见"的表达能力。
3. **单比特反馈作为一种设计选择**：M8 档位是"带宽越高越好"的序，本文证明对 agent 的反馈带宽应独立于评估带宽，且越低越鲁棒。

### 启发
1. 框架应增加 **M8/M9 的"内生 vs 外生"轴**：凡允许 agent 写测试/指标的 AutoResearch 系统，都暴露 verifier–deployment gap；九模块卡片应强制标注"验收信号是否 agent 可影响"。
2. M9 的最小可信核可以很小（一轮几次隐藏 rollout + 1 bit），SEAL 证明"少量外部信任即可"——准入门不必昂贵。
3. 区分两类自改进失效：**failure to discover**（没找到）与 **failure to retain**（找到了又改掉）；M4 单链状态 + 无外部回滚锚点时后者必然发生。

---

## 论文 2：MetaSkill-Evolve — Recursive Self-Improvement of LLM Agents via Two-Timescale Meta-Skill Evolution

- **出处**：arXiv:2607.05297v1，2026-07-06。LMU Munich / CUHK / MCML / MemAgents Lab（Zefeng Wang*, Minxi Yan* 等）。
- **一句话定位**：把 skill 自进化流水线本身的"改进策略"也变成可进化对象——每分支携带元技能 m=(ψ,σ,α,π,ε) 参数化五个流水线 agent，任务技能走快环、元技能走慢环，用同一条流水线递归改进自身。
- **任务域**：agentic benchmarks（OfficeQA、SealQA、ALFWorld）上的 skill 文件（Markdown 程序）进化；冻结 Gemma-4 31B backbone。

### 九模块映射

| 模块 | 对应实现 |
|---|---|
| M1 Policy/Coordinator | 【论文明确】frontier selection（§3.3, Eq.4）：v* = argmax η₁U_v + η₂P̂_v + η₃N_v，三项=效用/元生产力/访问冷却（novelty N_v=1/(1+times_selected)）。且 frontier 的"选择策略"本身受元技能慢环影响（推断：m 参数化 pipeline，故 M1 部分被进化）。 |
| M2 Operator | 【论文明确】类型化五阶段：Analyzer(诊断ψ)→Retriever(检索σ)→Allocator(预算α)→Proposer(提议π)→Evolver(执行ε)，对应 diagnose/retrieve/allocate/propose/execute 算子；K 个 children 并行，K>1 时 diversity hint 迫使不同干预角度（§3.4）。 |
| M3 BudgetController | 【论文明确】**Allocator agent（α）**：自适应决定每步 child 数 K∈[1,K_max]，停滞（P̂≈0）时放宽、 productive 后收缩（§3.4）。预算本身是进化对象。慢环频率 H 固定。 |
| M4 Frontier/State | 【论文明确】**持久化 DAG**（SQLite），节点存 (s_v,m_v,U_v,ΔU_v,φ_v)+分支路径+选择计数；双类型边：lineage（父子）与 inspiration（跨分支检索）。top-K frontier 每轮刷新；archive 只收 ΔU>0 的 child，但失败节点也持久化供检索（§3.3）。 |
| M5 Memory | 【论文明确】分支历史 h（**L1**）；inspiration 检索机制让失败/中性编辑成为后续提议的材料（近似 **L2 洞见**）；元技能 m 本身是"如何改进"的程序化知识——**明确命中 L3 方法知识**，且分文件、分支局部。三级齐全，L3 是核心创新载体。 |
| M6 Knowledge | 【论文明确】跨分支 inspiration（系统内部经验），无外部文献/知识库。 |
| M7 Executor | 【论文明确】**role=异质**：五个专家 agent（Analyzer/Retriever/Allocator/Proposer/Evolver）分工，共享一个冻结 backbone；**hypothesis=自由**：skill 全文可改，慢环连"改进流程"本身也可改（递归）。慢环还做 whole-m rewrite：五个元技能文件一次性共同改写保持跨组件一致性（§3.5）。 |
| M8 Evaluator | 【论文明确】U(s)=验证集 accuracy（**第一档：标量**）；但诊断输入是训练集最差样本的失败 trace（Analyzer 消费 failure trace，含完整执行失败信息，介于第三档文本反馈与第四档轨迹之间——推断：评语为"评分标量 + 轨迹级诊断输入"）。慢环把 H 轮历史折叠成合成 meta-failure trace（§3.5）。 |
| M9 AdmissionGate | 【论文明确】archive 准入 = ΔU_v > 0 严格改进门（§3.3）；最终选择 = 验证集 best-skill，held-out test 只在循环外评一次（§4.1）。 |
| X1 溯源审计 | 【论文明确】强：全搜索历史持久化 SQLite DAG，"preserves full provenance for any final node"（§3.3），lineage+inspiration 双边可追溯每个编辑来源。 |
| X2 人在环 | 无/默认。 |

### 核心创新落点与对框架的冲击
- **核心创新落在 M2/M3/M5-L3：把"算子本身"升格为 Candidate**。元技能 m=(ψ,σ,α,π,ε) 就是 M2（诊断/提议/执行算子策略）、M3（预算分配）、M4 检索策略的参数化——这些在九模块里本来是系统固定组件，本文把它们全部变成被进化对象，用"同一条流水线"递归改写（bounded, one-level recursion，§1）。
- **对 Candidate=任务解工件 的冲击：明确存在**。Candidate 是 (s, m) 二元组，m 是"研究动作的策略"。这意味着框架的 Candidate 类型需要区分 L0（任务解）、L1（如何改进任务解的元策略）。meta-productivity P(m|s)（Eq.3）是一个"二阶效用"：评的不是当前解多好，而是这个分支还能不能生出更好的后代——M1 选点函数因此包含未来生产力项，这在九模块的 M1 定义中没有对应。
- 不冲击权重层面：backbone 冻结，一切在 Markdown 文件层面。【论文明确】

### 【装不下的机制】
1. **双时间尺度（two-timescale）**：快环每步、慢环每 H 步，M3 BudgetController 没有"环频率分层"的表达。
2. **递归自应用的自指结构**：同一条五 agent 流水线被应用于其自身的参数文件（meta-failure trace 把改进历史伪装成一个失败样本喂给 Analyzer，§3.5）——九模块可以逐模块标注，但"流水线=自身的优化对象"这一自指性无法表达。
3. **元技能的分支局部性（branch-local m）+ 元级检索传播**：不同谱系有不同改进策略，唯一的跨谱系通道是 meta-level retrieval（§3.5）；框架的 M2 默认全局共享算子集。
4. P̂ 作为 quality-diversity 描述子保留"改进策略多样性"（§2 末），这是 QD 思想进入 M1，九模块无对应槽位。

### 启发
1. 九模块可显式增加 **"M1–M4 策略是否可进化"的元标注**；MetaSkill-Evolve 证明把 M2/M3 做成可进化的 Markdown 对象（与 Candidate 同构）无需新模型新目标即可收益 +6.38/+8.05（OfficeQA/SealQA 上单层进化之上，§4.2）。
2. **meta-productivity P̂** 值得引入 M1：选父节点不只看当前分，还看"该分支近期产生改进的速率"，防止锁死在停滞高点。
3. 失败节点不删、持久化供检索（ΔU≤0 也入 DAG 作 inspiration）是低成本提升 M5 利用率的做法。

---

## 论文 3：EvolveNet — Collaborative Harness Evolution for Agent Self-Improvement

- **出处**：arXiv:2608.04968v1，2026-08-05。HKBU / USTC / HKUST（Jun Nie 等）。代码：https://github.com/junnie00/EvolveNet
- **一句话定位**：联邦式 harness 进化——把"先聚合数据再进化"反转为"本地进化再聚合程序"：共享 harness 广播到数据不出域的客户端，各自进化为专家 harness，服务器用 scope-typed、证据引导的程序聚合把多个代码 delta 合成下一个共享 harness。
- **任务域**：五设置——text-to-SQL（BIRD）、数据科学编程（DS-1000）、竞赛编程（LiveCodeBench）、软件工程（SWE-bench Verified）、agentic 工作流（ClawEval）。冻结 deepseek-v4-flash solver。

### 九模块映射

| 模块 | 对应实现 |
|---|---|
| M1 Policy/Coordinator | 【论文明确】双层：客户端本地进化用 TTHE 的 trace-driven proposer（Nie et al. 2026）；服务器端聚合器 𝒜 决定采纳哪些 mechanism 及其作用域（§4.3）。"选点"分散为 K 个并行本地搜索 + 1 个聚合决策。 |
| M2 Operator | 【论文明确】本地：trace→edit 单一编辑算子（每客户端每轮一个 proposer 分支，E=G=1，§5）；服务器：**类型化聚合算子**——diff、mechanism 分解、scope 分类（global / home(d_k) / reject，Eq.14）、compose（verbatim 复制进 guard 分支）、revise（一次修订）。客户端还被赋予三种 search role：conservative repair / independent exploration / adversarial audit（§5）。 |
| M3 BudgetController | 【论文明确】固定 T=3 轮、每轮 1 代（E=G=1）；聚合端有 harness 行数增长预算（§4.3 末，§7 Artifact growth：BIRD 14→253 行）；串行深度分析 C=max_k C_k + C_𝒜 + C_val（Eq.7）是预算的并行化论证。 |
| M4 Frontier/State | 【论文明确】**星型 population**：每轮从单一共享状态 h^(t) 分叉出 K 个本地专家，聚合回单一共享 h^(t+1)；非持久 DAG，每轮重构（客户端间轮内不通信）。拓扑 = 重复 broadcast→fork→merge 的"联邦平均"式结构。 |
| M5 Memory | 【论文明确】本地执行 traces（**L1**，不出域）；行为证据 e_k=(F_k,B_k)（新增修复/新增破坏的 item 集合，Eq.9-10，近似 **L2 结构化洞见**，随程序 delta 跨界传输）；共享 harness 本身即累积的跨客户端经验载体（"experience found by one becomes available to the others only through the redistributed harness"，§1）——harness = 可执行的 **L3 方法知识**。**关键：原始数据（L1）严格本地，跨界的只有 L2/L3**。 |
| M6 Knowledge | 无/默认外部知识；但客户端的本地 workload 本身就是不可共享的"私有知识源"，机制设计上等价于 M6 分布式化（推断）。 |
| M7 Executor | 【论文明确】**role=异质**（双层）：K 个客户端按 workload 分片专业化（specialist instruction 明确要求"成为 THIS slice 的专家"，Appendix C），且按 client index 分配三种搜索角色；服务器端 LLM merger + 静态 auditor 又是另一类角色。**hypothesis=冻结与自由混合**：模型权重/endpoint/gold label 读取被静态 auditor 冻结（§5 不变量）；harness 源码自由改。 |
| M8 Evaluator | 【论文明确】客户端：本地 per-item 二值 verdict v_i∈{0,1}（标量，第一档）；但聚合器的输入是 **per-item 行为翻转证据 + 执行 traces**（"Every adoption decision cites either a graded per-item verdict or a trace"，§6.9）——聚合器侧达到 **第三/四档（工件+轨迹级）**。服务器 gate 用 per-item 翻转比较而非总分差（§4.4，§6.3：validation 只 gate 不 rank）。 |
| M9 AdmissionGate | 【论文明确】双层门：客户端门 S_k(h_k) ≥ S_k(h^(t))（Eq.5，本地不许更差）；服务器承诺门 \|F_val\| ≥ \|B_val\|（Eq.17，修复数≥破坏数才 commit），失败允许一次修订，再失败回滚到 h^(t)。门可在不集中验证数据的情况下计算（每客户端回两个整数，§4.4）。 |
| X1 溯源审计 | 【论文明确】强：所有 delta 相对共同基线 diff（Eq.8），mechanism 级归因（attribution 列为程序聚合三大难题之首，§4.2）；merge 报告逐条引用 verdict/trace（§6.9）；静态 auditor 拒绝改模型/读 gold 的候选（§5）。 |
| X2 人在环 | 无/默认（LLM merger 替代人做聚合判断）。 |

### 核心创新落点与对框架的冲击
- **核心创新落在 M2 的一个新算子类型 + M4 的新拓扑**："程序聚合"（evidence-guided scope-typed program aggregation）。它既非 crossover（不是两个解重组）也非 select（明确消融证明优于 select-best 和 delegation 路由，§6.4：68.5 vs 64.0/66.5），而是一种**带证据与作用域类型的多方合并算子**。九模块的 M2 算子清单（draft/debug/improve/crossover）没有"aggregate/merge"这一类型。
- **对 Candidate=任务解工件 的冲击：轻微但重要**。Candidate 是 harness（控制程序），不是任务解本身——与 MetaSkill-Evolve 一样，被进化对象是"做研究的程序"而非"研究产出"。三篇论文一致：2026 年这条线（harness/skill/policy 进化）都把 Candidate 上移了一层。框架的类型定义需要容纳"解工件 / 求解器程序 / 改进策略"三层 Candidate。
- scope-typed 机制（global vs home(d_k)）本质是**条件化准入**：M9 不只决定 accept/reject，还决定"在哪里生效"。Proposition 1/2（scope isolation / conflicts under disjoint scopes）给出形式保证。

### 【装不下的机制】
1. **数据本地性约束（data locality）作为一等设计约束**：九模块假设所有执行经验可被任何模块访问；EvolveNet 的整个范式来自"经验不能集中"。框架缺少"信息驻留/通信边界"维度（与 SEAL 的密封边界遥相呼应，但方向不同：SEAL 对 agent 隐藏评估，EvolveNet 对服务器隐藏数据）。
2. **多方/联邦拓扑**：M4 的树/DAG/population 都是单系统视图；EvolveNet 的 broadcast→parallel specialize→aggregate→redistribute 循环是跨信任域的多系统拓扑，客户端轮内零通信、只通过共享工件耦合。
3. **程序空间的非算术聚合问题**："聚合空间本身是一门编程语言，两个贡献能否组合是执行层面的事实"（§2）——九模块没有任何模块表达"Candidate 空间的可组合性结构"。
4. **并行化作为收益维度**：串行深度 max_k C_k vs Σ_k C_k（Eq.7）、1.9–5.4× 加速（§6.8）——M3 只管预算不管"搜索的串行结构"。

### 启发
1. M2 应增加 **merge/aggregate 算子类型**，且其输入是"delta + 行为证据"而非完整 Candidate；per-item 翻转（F/B 集合）是比标量分更好的聚合证据格式。
2. **scope-typed adoption**（证据跨域→global，单域→home 条件化，单 item→reject）可直接移植为九模块系统从多分支合并经验的规则；它把"冲突"从 winner-take-all 变成条件共存。
3. M9 门的正确用法是 **gate 而不 rank**（§6.3：验证集总分排序会颠倒真实优劣，per-item 翻转决策才稳健）——与 SEAL 的"1 bit 反馈"精神一致：准入决策应基于最稳健的差分证据。

---

## 跨论文综合观察（给框架的顶层信号）

1. **Candidate 上移是共同趋势**：三篇分别把 (policy+verifier)、(skill+meta-skill)、harness 作为 Candidate，都不是"任务解工件"。九模块框架的 Candidate 类型定义必须扩展为分层：L0 任务解 / L1 求解程序（harness/skill/policy）/ L2 改进策略（meta-skill/验证器）。这是三篇论文对框架最集中的冲击。
2. **三篇各自把框架的一个"固定组件"变成了优化对象**：SEAL→Evaluator 内生化的风险；MetaSkill-Evolve→M2/M3/M5-L3 的可进化；EvolveNet→M2 新增聚合算子+M4 联邦拓扑。九模块作为"描述工具"够用，但需要为每个模块增加"固定 vs 可进化 / 内生 vs 外生"两个正交标注轴。
3. **共同缺口：信息边界**。SEAL 的密封审计、EvolveNet 的数据本地性，都说明"哪个模块能看见什么"是一等设计变量，九模块（含 X1/X2）目前没有该维度。建议新增横切维度 **X3: Visibility/Trust Boundary（信息密封与信任边界）**。
4. M9 在三篇中都是关键且设计趋同：保守非回归 + 回滚 + 最小泄露（SEAL 1 bit；EvolveNet per-item 翻转 gate；MetaSkill-Evolve ΔU>0 严格门）。"准入门=保守差分证据+回滚"可作为框架 M9 的默认最佳实践。
