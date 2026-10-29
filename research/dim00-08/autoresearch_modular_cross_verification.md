# 交叉验证与跨单元 Insight（Phase 4 + Phase 6）

> 输入：dim00（Arbor 仓库实读）+ dim01-08（八个机制单元深读），共 ~2700 行一手调研。
> 验证方式：跨单元独立证据的收敛/冲突比对。

## 一、高置信收敛结论（≥3 个独立单元证据支持）

| # | 结论 | 独立证据来源 |
|---|---|---|
| C1 | **语义记忆/反馈信号的价值 > 搜索拓扑**。拓扑是容器，记忆与准入才是增益主体 | Arbor 消融（w/o insight 54.5 < w/o tree 63.6 < full 81.8）；AIRA（弱算子下 MCTS/进化相对 greedy 零增益，升级算子 +14% 后拓扑才分化）；AiScientist（移除 File-as-Bus Any Medal −31.82）；DataMaster（去 Global Memory overcome rate 69.96%→28.57%）；R&D-Agent（DAG→链 −28%） |
| C2 | **最终节点选择/准入是被低估的最大杠杆** | AIRA oracle 实验：仅终选换 test 分即 +9~13pp，top-3 多提交 +10%；Arbor held-out merge gate 的 dev/test 反差证据（Claude Code dev 75.0/test 71.7 vs Arbor 72.2/77.4）；KAPSO 因 test 评分方式引社区争议（MLE-bench issue #138） |
| C3 | **所有成熟系统收敛到同一两层骨架**：控制器（外化持久状态 + Observe→Plan→Select→Dispatch→Absorb→Admit）+ 执行器（有界工作区 + 结构化证据返回）；差异仅在状态拓扑、Executor spec、调度与准入三个配置点 | dim01（AIRA 四层）、dim04（三系统统一）、dim06（进化四组件同构）、dim00（Arbor 实现） |
| C4 | **记忆系统 = 生命周期治理（活多久/何时压缩）× 作用域寻址（与哪个搜索状态相关）双轴**；晋升算子必须增量合并而非重写 | dim02（HCC L1/L2/L3 消融各自不可替代；ACE context collapse 18,282→122 tokens 实证；Reflexion 精炼>回放 +8pp）；dim05（LoongFlow Plan/Summary 消融）；dim04（三方消融一致支持"蒸馏洞见为最小数据单元"） |
| C5 | **评估反馈带宽是核心权衡轴**：scalar → metrics+artifacts → +text_feedback → 完整 trajectory；带宽越高样本效率越高、实现成本越高 | dim06（GEPA 35× 样本效率 vs GRPO，反思成本仅 5-10%）；dim03（MARS evaluator 缺口分析）；dim07（KAPSO R(c) 四元组是最完整一般化） |
| C6 | **状态 = 物化层（workspace/git DAG）+ 索引层（tree/graph 视图）**；credit assignment 只认骨架边 | dim07（KAPSO branch 即产物引用、File-as-Bus 产物协议）；dim08（MCGS 骨架边 E_T + 引用边 E_ref 双层图）；dim00（Arbor code_ref=git branch） |
| C7 | **评估纪律必须机制化，不能依赖 LLM judge 单独放行** | dim08（Gasteiger/Anthropic：zero-shot 监视器失效、judge 易被操纵；PostTrainBench 观测到真实 reward hacking）；dim03（paired-seed 统计验收，假阳性 ~0.1%）；dim00（Arbor protected_paths SHA-256 运行时防篡改） |
| C8 | **成本敏感需要 BudgetController 一等组件 + fidelity 晋升策略**；方向级与候选级预算两层叠加 | dim03（MARS cost-aware UCT w=−0.07；paired-seed funnel；BATS 预算状态注入；PostTrainBench 20h→10h 反例）；dim06（ShinkaEvolve 成本感知 UCB bandit）；dim05（FM Agent 异步双池） |

## 二、冲突区（如实记录，不抹平）

| # | 冲突 | 双方证据 | 调和解释 |
|---|---|---|---|
| K1 | **全局记忆是否有效**：AIRA 消融显示全局 memory 算子几乎无差（38.2% vs 39.8%）| 矛盾于 | DataMaster（去 Global Memory −41pp）、Arbor（w/o insight −27pp）、HCC（三层各自消融失效） | 关键区分：AIRA 的全局记忆是**平铺文本注入**；有效的记忆都是**结构化（树绑定/分层/蒸馏）**的。结论：平铺记忆 ≈ 无效，结构化记忆 = 关键。这为框架的记忆接口设计提供了负例约束 |
| K2 | **Arbor merge gate 是否引入 adaptive overfitting**：搜索期反复调 E_test（≤20 次）决定 merge，test 不再纯 held-out（每次泄漏 ≤1 bit，winner's curse）| vs | 论文辩护：阈值门控+单调决策+终评独立+跨任务迁移验证 | 结构性风险真实存在；更严方案是三层协议（dev/admission-val/final-audit）或 gate 调用硬预算。框架必须把 gate 评估器/调用上限/触发阈值/终评隔离做成显式配置（dim08 已给配置对象定义） |
| K3 | **LoongFlow 论文宣称 vs 源码实现**：population entropy 在源码中实为浅层代码差异度 + sigmoid 温度；迁移宣称阈值触发实为间隔触发 | dim05 源码实读 | 教训：descriptor/机制的"宣称-实现保真度"应作为框架的可观测指标 |
| K4 | **预算是否越多越好**：直觉上更多预算=更好结果 | vs | PostTrainBench：20h 时 agent 自行提前停止，降到 10h 反而合理 | 预算存在边际收益拐点，收敛检测比固定预算更重要（dim00 Arbor ConvergenceDetector 提供了实现参照） |

## 三、跨单元 Insight（不重复已有发现，只写组合后才可见的模式）

**I1. "搜索算法的军备竞赛已经结束，状态表示的军备竞赛刚开始"**
- 来源：C1 + K1 + dim01（拓扑在算子升级前无差异）+ dim08（MCGS 的增益来自引用边信息流而非更强 credit assignment）
- 推论：框架的护城河不在实现更多 search policy（greedy/MCTS/evo 都应是一行配置），而在**状态 schema 与记忆/准入机制**的表达力。设计资源应 7:3 分配给数据面 vs 控制面策略。

**I2. 存在一条统一的"反馈带宽 × 评估成本"帕累托前沿，且每家的选择都可解释**
- 来源：C5 + dim03（EvalResult 五元组）+ dim07（KAPSO 四元组）+ dim06（四档带宽谱系）
- 推论：Evaluator 返回类型应设计为**可分层的超集**（status / metric±uncertainty / cost vector / text feedback / trajectory-ref），框架按任务评估成本选择带宽档位：10h 级场景用 scalar+uncertainty+partial_curves，秒级场景可用全 trajectory。

**I3. "角色分工"与"假设分工"不是两种架构，而是 Executor spec 的两个旋钮**
- 来源：dim04（三系统统一为 Executor(spec=(role, hypothesis, context_scope), workspace, budget)→Evidence）
- 推论：职能异质+假设自由（AIBuildAI）、职能同质+假设冻结（Arbor）、两者之积（R&D-Agent）是同一接口的三个配置点。框架只需一个 Executor 抽象 + spec 配置。

**I4. 多样性机制与语义假设管理可以统一：假设即 behavior descriptor**
- 来源：dim05（GSME/ACES/QD-LLM 先例；LoongFlow Solution 已绑定 plan/summary）+ dim08（DataMaster 树+Global Memory 混合）
- 推论：Archive 接口三个正交旋钮（准入结构 elite-pool/MAP-Elites/hypothesis-tree、岛拓扑与迁移、压力控制器）；假设嵌入作为 QD descriptor 维度有外部先例但无人与假设树结合——空白组合。

**I5. 持久状态的两种正交治理——时间尺度与拓扑作用域——可以统一为单一记忆后端**
- 来源：dim02（统一后端 = 存储按时间尺度分层 + 索引按假设拓扑与语义双键）+ C4
- 推论：Memory 模块接口 = write(checkpoint 钩子) / promote(增量 delta 算子) / retrieve(scope×recency×relevance)；主循环暴露 checkpoint 钩子供记忆后端订阅。1.0 scoped memory、HCC、ACE、Arbor insight 均为配置投影。

**I6. 评估纪律正在从"工程惯例"变为"对抗环境下的安全需求"**
- 来源：C7 + dim08（RE-Bench 作者自陈 test 直给 agent 计划改隐藏；MLE-bench validation server+transcript 审计+Dolos）
- 推论：框架的 Admission/Audit 层要按"对手是会 reward hacking 的强 agent"设计：不可变 harness、泄漏防线（hash 去重/URL blocklist/canary）、高风险调用人工批准、强制报告 (dev_best, gate_selected, final_audit) 三元组。

**I7. 开源生态位确实空缺**
- 来源：dim06（OpenEvolve/ShinkaEvolve 模块化高但无语义记忆与准入纪律）+ dim00（Arbor 有记忆与准入但拓扑/策略/多保真写死）+ dim01（AIRA 五元组但无持久记忆与准入）
- 推论："进化框架的工程模块化" × "agentic 框架的语义状态" × "评估协议的一等公民化" 三者没有交集产品。这正是目标生态位。

## 四、证据强度备注
- Arbor 论文为 living technical report（v1, 2026-06），数字可能更新。
- AIBuildAI 闭源（仅论文+README）；FM Agent 核心进化引擎未开源——两者接口细节置信度中等。
- MLE-Bench 榜单数字为异构条件快照，仅用于设计路线比较，不用于架构优劣断言。
