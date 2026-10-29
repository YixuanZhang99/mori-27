# 九模块分析卡片：Group B —— 自我修改 / 递归自我改进 / 代码进化基线批判

> 分析框架：M1 Policy/Coordinator · M2 Operator · M3 BudgetController · M4 Frontier/State · M5 Memory(L1原始/L2洞见/L3方法知识) · M6 Knowledge · M7 Executor(role 同质/异质 × hypothesis 冻结/自由) · M8 Evaluator(标量→多指标+工件→+文本反馈→完整轨迹) · M9 AdmissionGate · X1 溯源审计 · X2 人在环
> 标注约定：**【原文明确】** = 一手材料直接写明；**【推断】** = 分析者基于材料的映射判断。

---

## 0. 出处核查（先行结论）

- **"Simple Baselines are Competitive with Code Evolution" 不是 weco.ai 博客**。真实出处是 arXiv 论文 **arXiv:2602.16805**（v1 提交于 2026-02-18），作者 Yonatan Gideoni 等（牛津，致谢中提到 Sakana AI 团队、Robert Lange 帮助跑 ShinkaEvolve）；其前身是 NeurIPS 2025 Fourth Workshop on Deep Learning for Code 的 "Random Baselines for Simple Code Problems are Competitive with Code Evolution"（OpenReview）。该论文的 MLE-bench 实验以 Weco 的 AIDE 为对照对象（"We compare the baselines to AIDE, a code evolution pipeline designed specifically for Kaggle competitions (Jiang et al., 2025)"），这大概率为混淆来源。
- **AIDE²** 确为 Weco AI 博客：<https://www.weco.ai/blog/first-evidence-of-recursive-self-improvement>，标题 "AIDE²: First Evidence of Recursive Self-Improvement"，发布日期 **2026-07-14**，署名 Weco Team。有配套博客 "4 Levels of Recursive Self-Improvement"。
- **DGM**：arXiv:2505.22954（v2 2025-09-26，Zhang/Hu/Lu/Lange/Clune，UBC+Vector+Sakana AI），代码 <https://github.com/jennyzzt/dgm>（注：GitHub 页面本次抓取被工具拦截 "audit rejected"，以下 DGM 卡片以论文 HTML 版为准，属一手材料）。

---

## 1. DGM（Darwin-Gödel Machine）

**一句话定位**：单个自指 coding agent 在"自我修改 ↔ 基准评测"交替循环中开放式进化出一个 agent 档案库（archive tree），被进化的对象就是 agent 自己的代码库。
**出处/时间**：arXiv:2505.22954（2025-05 首版，v2 2025-09）；github.com/jennyzzt/dgm。

| 模块 | 对应实现 |
|---|---|
| **M1 Policy/Coordinator** | 开放式档案搜索循环：每次迭代从 archive 选父代（"Parent selection is roughly proportional to each agent's performance score and the number of its children with codebase-editing functionality"，§3, §C.2）【原文明确】。关键声明：exploration 过程本身（archive 维护、父代选择）**是固定的、不可被 DGM 自我修改**，留作 future work（§3 末）【原文明确】 |
| **M2 Operator** | 单一算子 = self-modify-implement：父 agent 先分析自己的 benchmark 评测日志、提出下一个要实现的 feature（self-proposal 作为 problem statement），再把该 feature 实现进自己的代码库产出子 agent（§C.3）【原文明确】。无 draft/debug/crossover 的类型化区分——只有"自我提案→自我实现"一种动作 |
| **M3 BudgetController** | 弱：固定 80 次迭代（SWE-bench 2 路并行、Polyglot 4 路并行，§4.1）【原文明确】。真正的"预算控制"体现在 M8 的分阶段评测（省下评测算力）而非显式 BudgetController |
| **M4 Frontier/State** | **档案树（tree archive）**：从单一初始 agent 生长，所有成功 agent 永久保留为 stepping stones（"archived solutions can serve as stepping stones that result in improvements much later than their original discovery"，§3）；消融显示去掉 archive（只保留最新版本 = hill-climbing）性能显著变差（DGM w/o open-ended exploration 基线，§4.3）【原文明确】 |
| **M5 Memory** | **L1 为主**：父 agent 读取"自己的 benchmark evaluation logs"作为自我诊断材料【原文明确】；archive 本身是 L1 工件库。无显式 L2 洞见层/L3 方法知识层——跨代"方法知识"只以子 agent 代码（工具、workflow）形式实体化传承，没有外置的可读知识库。【推断】DGM 的"记忆=基因型"，知识沉淀在代码而非文本记忆里 |
| **M6 Knowledge** | 无外部知识注入（无文献检索/RAG）；仅 FM 预训练知识 + 评测日志 |
| **M7 Executor** | **role = 同质**：自我修改者与任务执行者是同一个 agent（同一代码库，frozen FM：自我修改用 Claude 3.5 Sonnet；下游评测 SWE-bench 用 Claude 3.5 Sonnet / Polyglot 用 o3-mini，§4.1）【原文明确】。**hypothesis = 自由**：agent 自主提出下一个 feature（无人工冻结的研究假设）。两旋钮取值：**同质 × 自由** |
| **M8 Evaluator** | **标量 + 部分文本反馈，且为分阶段级联**：基准 solve-rate 标量（SWE-bench Verified / Polyglot pass@1）【原文明确】；**staged evaluation**：先在 10 题上验证基本代码编辑功能→50/60 题子集→（SWE-bench 若 >40% 且 archive 前二）扩到 200 题（§4.2）【原文明确】。评测带宽档位：**标量分数 + 工件（代码 diff），文本反馈仅用于自我诊断日志，不到完整轨迹评审**。级联评测是显著的"评估经济学"设计 |
| **M9 AdmissionGate** | 硬门："Only agents that compile successfully and retain the ability to edit a given codebase are added to the DGM archive"（§3）【原文明确】——功能性准入（可编译+保留编辑能力），非分数门槛；分数只影响后续父代选择概率 |
| **X1 溯源审计** | archive tree 自带完整谱系（边=哪个 agent 自改产生了后代，Figure 3 左）【原文明确】；论文 §5 讨论安全：sandboxing、human oversight、self-modification 可追溯性【原文明确】 |
| **X2 人在环** | 循环内无人；安全层面 human oversight（§5）【原文明确】 |

**M7 两旋钮**：同质 × 自由　**M8 档位**：标量+工件（分阶段级联）　**M5 层级**：L1（日志+代码档案即记忆）

### DGM"自我修改"对 Candidate/ExecutorSpec 类型定义的冲击（特别关注）
- **被进化对象 = agent 自身代码库，不是任务解**。在我们的抽象里，Candidate 通常是"任务空间中的解"，ExecutorSpec 是"产生解的执行体配置"。DGM 把二者折叠：Candidate = 一份 agent 代码库 = 一个 ExecutorSpec（且是可执行、可继续变异的 ExecutorSpec）。【推断】这不是冲击而是**推广**：框架需要承认"ExecutorSpec 本身可以是一阶 Candidate"（harness-as-candidate），即候选空间存在**层级**（任务解 vs. 研究体），DGM/AIDE² 都在第二层搜索。类型上可建模为 `Candidate<T>` 其中 `T = TaskSolution | ExecutorSpec`，AdmissionGate/Evaluator 对 `T=ExecutorSpec` 的评测语义变为"该 ExecutorSpec 跑若干任务后的聚合分数"（元评测）。
- DGM 另一个反直觉点：M1（搜索策略）**刻意不被进化**【原文明确】——自我修改只作用于 agent 代码，不作用于进化循环本身。这划清了"可变基因"与"固定物理定律"的边界，是我们框架需要的同类声明。

### 【装不下的机制】
1. **元对象层级切换**（候选=执行体）：九模块默认 Candidate 与 Executor 分离，缺一个显式的"层"（level）维度来表达在解空间/执行体空间/搜索策略空间之间选择被进化对象。这是最重要缺口。
2. **"功能性存活门"**：准入判据不是分数而是"是否仍保有编辑代码的能力"——一种关于 Candidate 元能力（而非任务表现）的门，M9 语义需扩展。
3. **冻结边界声明**：哪些模块可被系统自身改写、哪些固定（DGM 的 exploration 固定），九模块没有这个元属性位。

### 对框架的启发
1. Candidate 类型参数化（解 vs. ExecutorSpec），并允许 AdmissionGate 接收"元能力检查"。
2. 档案树 + 功能性存活门 + 按分数/子代数加权的父代选择，是低成本可复用的开放式搜索默认配置。
3. 明确声明每个模块的"可自修改位"，防止自我改进系统改写自己的评估器（reward hacking 的结构性防线）。

---

## 2. AIDE²（Weco AI, 递归自我改进）

**一句话定位**：双层优化——外环用手调研究 agent（AIDE_human）改写内环研究 agent（AIDE_k）的 harness 代码，以"同成本预算下的跨任务私有分数"为选择信号，8 天无人值守跑出 7 代连续改进、且超过人类两年手调版本。
**出处/时间**：weco.ai 博客，2026-07-14。

| 模块 | 对应实现 |
|---|---|
| **M1 Policy/Coordinator** | 外环：贪心爬山——"proposes a rewrite of the inner-loop agent's code, evaluates the proposed agent, and keeps it only if better than the previous best"（§1）【原文明确】。注意与 DGM 相反：**无 archive、无多样性维护，单链 accept/reject**（100 步中约 9/10 被拒，§2.1）。内环 AIDE₀ 的搜索策略：先写 5 个各不相同的 draft，之后每步"debug 随机 buggy 叶 或 improve 全树最优解"，greedy 选父（§2.4）【原文明确】 |
| **M2 Operator** | 外环算子 = rewrite（整体改写内环 agent 代码）【原文明确】。内环算子是**类型化的**：draft / debug / improve（"operators for different scenarios, e.g., drafting, debugging and improving a particular solution"，§2.4）【原文明确】——与九模块 M2 几乎一一对应。AIDE₈₅ 还自主发现了"为每个 operator 定制最小上下文"的 matrix mechanics（bug rate>15% 才挂某组件、debug 读 raw tail、improve 读 plateau 信号等，§2.4）【原文明确】 |
| **M3 BudgetController** | **核心设计**：评估框架为约束优化——固定每次评估的美元成本预算，增益必须是效率增益；"Strategies that greatly increase the number of LLM calls (e.g., best-of-N) … will not pass this cost constraint"（§The inner-loop evaluation）【原文明确】。AIDE₈₅ 发现的 16× prompt 压缩正是把省下的 token "reinvested as additional search steps"（§2.4）【原文明确】——预算从"上下文"再配置到"搜索步数"，是 M3 的教科书案例 |
| **M4 Frontier/State** | 外环：**单链表**（incumbent + challenger），无 archive（推断：与 DGM 的 archive tree 形成鲜明对照；这正是 AIDE²≈"DGM w/o open-ended exploration"基线配置却仍然有效，可能因为外环评估更严）。内环：AIDE 经典**解树**（solution tree，§2.4）【原文明确】 |
| **M5 Memory** | 内环 AIDE₀：naive 全历史拼接（"prompts carry the full history of every earlier attempt, each attempt's complete source code and everything its execution printed"）= 纯 L1【原文明确】。AIDE₈₅ 自主进化出**压缩轨迹摘要 + 每算子定制上下文 + 12 条 one-liner + 1 份完整解**（§2.4 matrix mechanics）【原文明确】≈ 自建 L1→L2 摘要层。**记忆层级：AIDE₀ = L1；AIDE₈₅ ≈ L1+L2（自动发现的）**。无 L3 方法知识库 |
| **M6 Knowledge** | 无外部知识；任务异质性（ML 工程/启发式算法/harness 工程三族）充当"环境知识"来源【原文明确】 |
| **M7 Executor** | **外环 vs 内环是异质的**：不同 agent（AIDE_human vs AIDE₀ 谱系）、甚至不同模型（claude-opus-4.7 vs gemini-3-flash），经济性论证（外环 token 占总成本小头，故用最强模型）（§1）【原文明确】。**hypothesis = 自由**（外环自主提出 rewrite）。内环 executor 自身同质。两旋钮取值：**异质（跨层）× 自由**；ignition test（§3.1）把 AIDE₄₇ 放到外环座位，检验"被发现的改进者是否也是更好的改进者"——即在测试 role 同质化的可行性，结果：收敛更快（20 vs 40 步）但渐近相同，"not strong enough evidence of ignition"【原文明确】 |
| **M8 Evaluator** | **多层嵌套评估**：内环 agent 的分数 = 它在多个任务族上跑完整 autoresearch run 的聚合私有分数（"a benchmark composed of benchmarks"，map→reduce 聚合）【原文明确】。**public/private split**：public 分数给内环优化用，private 分数不可见、决定存活（一阶泛化门）【原文明确】；跨任务迁移=二阶泛化；外环座位表现=三阶泛化（§3.1）【原文明确】。带宽档位：**标量聚合分 + 完整内环优化曲线（分数随步数的曲线被作为工件审视）**，介于"多指标+工件"与"+文本反馈"之间 |
| **M9 AdmissionGate** | "keeps it only if better than the previous best"且以 private 分数判定 + 固定成本约束（§1）【原文明确】；~90% 拒绝率（§2.1）【原文明确】 |
| **X1 溯源审计** | 谱系记录（AIDE₀→…→AIDE₉₉，接受步 47/85；"Provenance: summary and gate from steps 2 and 6; the output guard from step 63"§2.4）【原文明确】；人工事后审计发现：eval repair 的 monkey patch 是修复评测 bug 而非作弊【原文明确】；反作弊统计层在后续突变中被改坏、实际无作用【原文明确】——谱系审计发现"机制失效"，是 X1 价值的活例 |
| **X2 人在环** | 循环内 100 步零干预【原文明确】；循环外人工读代码/判定 RSI 等级/部署决策（§3.2 "Living with code you didn't write"：进化产物难懂、难部署）【原文明确】 |

**M7 两旋钮**：异质（跨层）× 自由　**M8 档位**：多指标+工件（嵌套评估 + public/private 分数对）　**M5 层级**：L1→L2（L2 是进化出来的）

### 递归自我改进对框架的冲击（特别关注）
- 与 DGM 同构：Candidate = inner-loop ExecutorSpec。但 AIDE² 比 DGM 多走一步：**双层 executor 刻意异质**（模型/角色都不同），并用 ignition test 把"层间角色可替换性"变成可测量问题。对框架含义：ExecutorSpec 需要带 **level 属性**（哪一环的 executor），M7 的 role 旋钮应允许"跨层异质"取值，且 Evaluator 要支持"以另一层运行结果为输入"的嵌套评估。
- AIDE₈₅ 自主构建了**三层反 reward-hacking 防线**（prompt 指令 / 硬编码 guard 重生成可疑输出 / 统计剔除极端成功）【原文明确】——这本质是 agent 给自己的 M9/M8 写的补丁。自我改进会**改写自己的评估与准入模块**，框架必须把 M8/M9 纳入"可自修改位"的审计范围（X1 必须覆盖 gate 代码的谱系，Weco 正是靠此发现统计层已失效）。

### 【装不下的机制】
1. **嵌套/元评估**（benchmark of benchmarks、score 回流外环）：M8 单点评估语义装不下"评估一个 ExecutorSpec = 跑 N 个完整 autoresearch run 再 map-reduce 聚合"。最大缺口。
2. **public/private 双分数制**：同一解有两个分数，一个对 agent 可见（优化信号）一个不可见（选择信号），作为结构性防 reward-hacking——九模块里 M8/M9 都没有"信息可见性"维度。
3. **泛化阶数（一阶=held-out 数据、二阶=held-out 任务、三阶=换座位当 outer agent）**：这是一种跨层级的 AdmissionGate 梯度，九模块无对应。
4. **RSI 等级（L0-L3 ladder）与 ignition test**：元层级能力认证协议，框架外的新对象。

### 对框架的启发
1. 引入 "budget-constrained private score" 作为 AdmissionGate 标准件：固定美元预算 + 不可见私有分数，同时充当效率压力与防作弊压力（Weco 观察到反作弊是涌现的，因为"赢 public 分数的变体活不过 private 选择"）。
2. ExecutorSpec 增加 level 字段，支持双层 loop；把 ignition-test 式的"换座实验"作为评估自我改进系统的标准诊断。
3. X1 谱系必须覆盖 M8/M9 自身的代码版本——自我改进系统会把反作弊机制改坏而不自知。

---

## 3. "Simple Baselines are Competitive with Code Evolution"（arXiv:2602.16805）

**一句话定位**：方法论批判论文——两个极简基线（IID 随机采样 IID RS、序贯条件采样 SCS）在数学界、agentic scaffold、MLE-bench 三个域上匹配或超过 ShinkaEvolve/ADAS/AIDE 等复杂代码进化系统，论证复杂 pipeline 的许多组件未被消融、收益常被 prompt 领域知识/评估噪声所混淆。
**出处/时间**：arXiv:2602.16805，v1 2026-02-18；Yonatan Gideoni 等（牛津；致谢 Sakana AI）。**非 Weco 出品**（尽管以 AIDE 为主要对照）。

| 模块 | 对应实现 |
|---|---|
| **M1 Policy/Coordinator** | 刻意极小：IID RS = 无策略（每次独立采样）；SCS = 每代从上一代**成功运行**的程序中随机取 3 个拼进 prompt（"no explicit fitness-based selection"，§3）【原文明确】。MLE-bench 版加一个"生成后迭代 debug 直到能跑"步骤（Appendix L）【原文明确】 |
| **M2 Operator** | 单算子 = generate（整文件生成，非 diff 变异）；SCS 多一个 condition-on-previous；MLE-bench 有 debug-until-runs。无 crossover、无类型化算子库 |
| **M3 BudgetController** | **论文的核心关注变量**：三个域分别以不同资源为主约束——$20 API 预算 / scaffold 评估次数（50 次）/ 24 小时 wall-clock + 单 GPU（§1, §4-6）【原文明确】。"明确问题的主约束是 API 成本、函数评估数、wall-clock 还是别的"被列为未来工作准则第一条（§7）【原文明确】 |
| **M4 Frontier/State** | 无：IID RS 无状态；SCS 只保留上一代随机子集，且可周期性 restart from scratch（§3）【原文明确】。MLE-bench 基线"do not include explicit fitness-based selection or a memory of all past programs and their performance"（Appendix L）【原文明确】 |
| **M5 Memory** | **L0/L1 之间**：SCS 的"记忆"= 上一代 3 个程序原文+bound，无摘要、无洞见层。记忆层级：**L1（且是有意最小化）** |
| **M6 Knowledge** | 恰好是本文的控制变量："the domain knowledge used and a problem's formulation affect the search's efficiency and performance ceiling much more than the pipeline"（§7）【原文明确】；公平比较要求各方法 prompt 领域知识一致（§3.1）【原文明确】。结论：搜索空间设计/verifier 设计（由领域专家完成）比搜索方法更决定上限（§4.1：改 uncertainty inequality 的 formulation，所有方法同预算下都找到更好界）【原文明确】 |
| **M7 Executor** | **同质 × 半冻结**：单一 LLM 生成器，无分工；问题陈述固定（hypothesis 由 prompt 冻结），但生成内容自由。两旋钮：**同质 × 冻结（prompt 固定）** |
| **M8 Evaluator** | 标量（bound/validation accuracy），**但论文主要贡献在评估方法论**：揭示 ~100 题小验证集导致 scaffold 选择主要是噪声（重评 10 次后 ADAS/Shinka 与 IID RS 无显著差异，P(Shinka>IID RS)=0.49，§5）【原文明确】；提出 evaluation cascade（两级级联省成本）、probability of improvement / dominance、≥300 有效测试题、95% CI（§5）【原文明确】。带宽档位：**标量**；MLE-bench 场景承认"textual feedback is evidently important for functional code evolution"（Appendix L）【原文明确】 |
| **M9 AdmissionGate** | best-of-N（按 bound 或 validation accuracy 取最优）【原文明确】 |
| **X1 溯源审计** | 无（基线无需）；但论文要求社区做贡献拆分审计："It is important to be clear when proposing search methods and when exhibiting a discovery"（§7）【原文明确】——方法贡献 vs 发现贡献的解耦 |
| **X2 人在环** | 领域专家设计搜索空间/verifier 被证明是性能上限的主要来源（§4.1, §7）【原文明确】——人在环不是辅助而是关键因素 |

**M7 两旋钮**：同质 × 冻结　**M8 档位**：标量（但附评估统计学方法论）　**M5 层级**：L1（刻意最小）

### 【装不下的机制】
本文本身是"装不下机制"的报警器，而非新机制来源：
1. **评估统计噪声作为一阶对象**：九模块里 M8 是"带宽"维度（信号丰富度），本文指出还有正交的**可靠性维度**（样本数/CI/级联），低带宽+高噪声的评估会让 M1-M4 的所有复杂设计退化为随机搜索。
2. **问题表述/verifier 设计（search-space engineering）**：位于九模块之外——它决定性能上限，而 M1-M9 全在"给定问题后怎么搜"。框架若做 AutoResearch，需要把"任务 formulation 本身可作为被优化对象"表达出来（本文 §7 也呼吁"设计能改变自己问题表述的系统"）。
3. **贡献归因协议**（搜索方法贡献 vs 领域知识贡献 vs 发现贡献）：一种审计规范，X1 装得下但需显式化。

### 对框架的启发
1. 九模块应内置"最小基线投影"：任何复杂配置（M1/M4/M5 的花哨设计）必须证明相对 IID RS / SCS 式退化配置的增量，否则默认裁掉——该论文是框架的奥卡姆剃刀。
2. M8 增加与带宽正交的"统计可靠性"旋钮（评估次数、级联、PoI/PoD 报告），并把 evaluation cascade 列为 BudgetController 的标准联动件。
3. 把 M6（领域知识/prompt 内容）列为公平比较的受控变量——实验报告中 M6 差异必须显式声明，否则搜索方法的增益不可归因。

---

## 4. 跨工作综合（对九模块框架的整体信号）

1. **候选层级化是最一致的结构缺口**：DGM 与 AIDE² 都进化 ExecutorSpec 而非任务解，九模块需 `Candidate<level>` 分层 + 元评估（Evaluator 的输入可以是另一层的完整运行）。
2. **自我改进系统会改写自己的评估/准入**：AIDE² 的反作弊三层防线及其失效、eval-bug 修复，说明 M8/M9 的代码必须在 X1 谱系覆盖范围内，且需要"可自修改位"声明（DGM 冻结 exploration 的做法是正面先例）。
3. **复杂搜索未必优于简单基线**：Simple Baselines 论文 + AIDE² 外环用无 archive 的贪心也达到 Level-1 RSI，共同提示：九模块中 M4（档案拓扑）的收益依赖评估质量与任务结构，应以评估统计可靠性（M8 新旋钮）为先决条件。
4. **评估经济学是三者共同主线**：DGM 分阶段评测、AIDE² 固定美元预算+16×上下文压缩、Simple Baselines 的 evaluation cascade——M3 与 M8 的联动（级联/分阶段/预算内再配置）是这三个系统最可移植的设计。

### 材料与置信度
- DGM：arXiv HTML v2 全文（一手），GitHub 仓库本次未能抓取（工具拦截），置信度高。
- AIDE²：博客全文滚动阅读（一手，仅 2.5 节部分段落跳过），置信度高；注意其为厂商博客、无论文级同行评审，RSI "first evidence" 为作者主张。
- Simple Baselines：arXiv HTML v1 全文含附录（一手），置信度高。出处混淆已澄清（非 weco.ai 博客，为牛津/Sakana 相关论文）。
