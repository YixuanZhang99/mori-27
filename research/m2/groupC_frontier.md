# M2 Operator 模块 · 2026 前沿扫描（Group C：轴系外维度）

扫描窗口 2025-08 → 2026-08，优先 2026。背景轴系：算子类型 / 算子选择策略 / 算子上下文输入 / 自修改安全模式。以下只列轴系**之外**的候选维度。数字均引自一手来源（arXiv 论文、官方 repo、官方博客）；外推处标【推断】。

---

## (1) 逐项新发现卡片

### 卡片 1：算子本身成为可训练参数——"编辑策略"被 RL 后训练（Harness-R1）
- **发现**：不再用固定 prompt 让 frontier 模型当变异器，而是把"失败轨迹 → 可执行 harness patch"的编辑策略本身做成一个 9B 专用 engineer 模型，SFT 冷启动 + 在线 GRPO，奖励 = patch 应用后冻结目标 agent 的真实任务成功率。
- **来源+日期**：arXiv:2608.02276《Harness-R1: Learning to Edit Executable Runtime Harnesses from Agent Failure Trajectories》，2026-08-03（SJTU/小红书）。
- **量化证据**：冻结 Qwen3.5-9B 目标在 WebShop/ALFWorld/DBBench 均值 44.3%→53.6%（+9.3pp）；比监督版 engineer 高 7.1pp；最强 frontier engineer（GLM-5.2，48.8%）被 9B 训练版超过 4.8pp；目标 agent 经 SFT 变强后再训练专属 engineer 仍 +5.0pp（59.2→64.2）；20 个未见目标 agent 上平均 +7.06pp，63 个组合中 56 个改善；稀疏失败证据（10 条失败）下 held-out +8.9±1.5pp，而 frontier engineer 平均为负。
- **为何在既有轴系之外**：轴系里"算子类型"假定算子是预设离散类别、"选择策略"假定算子集合固定。这里**算子的产出分布本身是可学习权重**，随编辑结果持续更新——是"operator-as-trained-policy"，不是"operator selection"。

### 卡片 2：改进算子被同一管线递归进化——meta-skill 双时间尺度（MetaSkill-Evolve）
- **发现**：改进过程本身被提升为一等进化对象。每条分支携带 meta-skill m=(ψ 诊断, σ 跨分支检索, α 子代预算, π 编辑提案, ε 应用+校验)，任务 skill 每代进化，meta-skill 每 H 代按"最近 H 个子代的改进量"进化——即"变异器的产出率"成为 meta 适应度。
- **来源+日期**：arXiv:2607.05297，2026-07-06。
- **量化证据**：五个 pipeline agent 共享单一冻结 backbone；相对 raw backbone 的 held-out 提升 OfficeQA +23.54、SealQA +16.09、ALFWorld +1.92 分，超过 no-skill / static-skill / 单层进化基线。
- **为何在既有轴系之外**：这是**算子谱系的时间结构**（快/慢双时间尺度 + "算子的适应度=其子代的改进量"），既有轴系没有"算子自身的评估信号与进化节奏"这一维。

### 卡片 3：算子的联邦化与合并语义——进化产物作为可组合 artifact 跨组织流动（EvolveNet）
- **发现**：多部署点各自本地进化同一广播 harness，只回传 program delta + 行为证据，server 做 scope-typed（全局/域条件化）、证据门控的程序合并。问题从"选哪个算子"变成"**如何合并多个独立算子序列的产出**"——程序不可像参数一样平均。
- **来源+日期**：arXiv:2608.04968《Collaborative Harness Evolution for Agent Self-Improvement》，2026-08-05。
- **量化证据**：BIRD held-out 70.7% vs 等总预算集中式 population 67.3%（配对 14 胜 9 负）vs 等串行深度集中式 68.7%（无门控链式版本直接崩溃回滚）；DS-1000 上合并 harness 比最强单 client 高 9.0 分；与"保留 K 个 specialist 按域路由"（Delegation）和"只允许全局机制"（GLOBAL-only）的消融证明组合与域条件化各自贡献真实收益。
- **为何在既有轴系之外**：算子的**分布、产权边界与合并算子**（merge 本身成为元算子）——既有轴系全部隐含"单一进化主体"。

### 卡片 4：算子产出的准入机制工业化——四道序贯统计门 + 语义基因库（HarnessBank）
- **发现**：算子产物的准入不是单次打分，而是序贯门：有效性门（排除基建失败污染的评估）→ 激活门（修改真的被执行了）→ 配对显著性门（z 检验区分任务噪声）→ 增益门（必须超父代）。谱系侧用 WHERE（prompt/knowledge/runtime/config）× WHY（失败病理）语义坐标的基因库存档，支持跨 cell 机制重组。关键对照：无显著性门的 DGM 在 Omni-MATH 上把**比 vanilla 差 −1.1%** 的 harness 部署上线。
- **来源+日期**：arXiv:2607.13683，2026-07-30（EverMind）。
- **量化证据**：7 个 benchmark 上 +5.1%~+15.4%，6 项 held-out 增益全部 z≥1.96 credited；GEPA 47 代在 LiveCode 找不到超种子变体（0 项 credited），DGM 仅 1/5；门是双向的——TB2 上拦下一个显著为负的候选（−6.4%）；跨模型呈"病理→补丁匹配律"：错配补丁近零增益（+0.2/+1.2），匹配补丁 +13.5%（z=4.15）。
- **为何在既有轴系之外**：既有"自修改安全模式"轴管的是**改之前**的约束；这里是**改之后**的统计学准入与谱系索引（病理坐标、recombination 许可）——算子治理/谱系学，独立于安全模式。

### 卡片 5：编辑/变异成为专用模型能力——apply 模型的经济性证据（Morph 等）
- **发现**："编辑"从通用生成中剥离成专门能力：强模型自然输出"lazy diff"，由专用 apply 模型负责合并落地。理由：通用模型输出结构化 diff 非自然、错误率高。
- **来源+日期**：Morph/Continue 官方博客，2025-05-28（窗口边缘，2026 该方向未见一手新基准，标【证据陈旧风险】）。
- **量化证据**：结构化 diff 格式失败率 25%+ vs lazy diff + apply 模型 <1%；额外 1.5–2× token 效率。
- **为何在既有轴系之外**：这是**算子与载具（模型）的绑定/分工**维——"变异步骤内部再拆分为 propose-model / apply-model 两级"。【推断】对 M2 的推论：算子实现可拆为"语义决策（贵模型）+ 机械落地（便宜专用模型）"，与卡片 6 的预算分配正交。

### 卡片 6：变异预算的跨阶段分配——population handoff 而非逐 call 路由（RelayEvolve 等）
- **发现**：LLM 驱动进化中，模型调用是状态耦合的（每次提议改变后续 population），所以"下次调用用哪个模型"是错的问题；对的问题是"便宜模型何时把 population 移交给强模型"。实证三规律：适应度改进强烈前置；早期轨迹质量是有用但嘈杂的信号；便宜模型以远低成本捕获早期大部分进展。同簇工作：ShinkaEvolve（bandit 选 LLM 集成）、AdaptEvolve（按生成置信度逐级升级）、LEVI（按变异角色路由到不同模型级）、AdaEvolve（跨 population 分配算力）。
- **来源+日期**：arXiv:2608.05651《Adaptive Population Handoff for Cost-Efficient LLM-Driven Evolution》，2026-02-15。
- **量化证据**：上文三条轨迹统计规律为一手观察；相对收益见原文（本扫描未摘取具体百分比，标【未复核】）。
- **为何在既有轴系之外**："算子选择策略"轴选的是**哪个算子**；这里分配的是**预算在时间/模型档位上的结构**（探索期 vs 精炼期、集合级移交）。变异经济学是独立一维。

### 卡片 7：测试时进化——算子在评估内运行、judge 只见代理信号（TTHE）
- **发现**：harness 优化从"评估前用开发集"移入"评估内部"：task gold 对 proposer 和 judge 都隐藏，候选只能靠当前无标签 batch 上的执行代理信号打分，且必须在任意代码编辑 + 不完全证据下提交。
- **来源+日期**：arXiv:2607.08124《TTHE: Test-Time Harness Evolution》，2026-07-09。
- **量化证据**：核心发现是代理可靠性（proxy 是否跟踪真实正确性）成为中心研究对象（具体数值未摘取，标【未复核】）。
- **为何在既有轴系之外**：算子的**运行时机/证据制度**（offline-dev vs in-evaluation、有标签 vs 无标签代理）——不是类型、不是选择策略、不是输入内容，而是"算子在什么证据体制下被允许产出并提交"。

### 卡片 8：工业界 harness 进化的平台化——harness 成为平台级优化目标
- **发现**：Claude Code / Codex 类产品的 plan mode、`/loop`、工具 schema、恢复逻辑迭代，本质是**平台方用聚合失败信号做的集中式 harness 进化**，所有用户继承。失败归因框架：同一步骤大量失败 → 改 prompt/router/工具契约/重试策略/验证循环，而非换模型。
- **来源+日期**：Xinming Tu 博客《The What & When of Self-Evolving Agents》，2026-06-08；Lilian Weng《Harness Engineering for Self-Improvement》，2026-07-04（DGM 以 Claude 3.5 Sonnet 为基座：SWE-bench Verified 20%→50%，Polyglot 14.2%→30.7%）。
- **量化证据**：DGM 数字如上（Weng 引自 DGM 原文）。
- **为何在既有轴系之外**：算子的**所有权与受益范围**（平台级集中进化 vs 用户级本地进化），及"失败聚合信号从哪来"——治理/拓扑维度，非技术策略维度。

### 卡片 9：算子组合的生态化萌芽——prompt 优化库 vs 算子库
- **发现**：promptolution 等库把 CAPO/EvoPromptGA/OPRO 等优化器做成统一模块框架（1M token、<$0.15 预算约束下评测，GSM8K 上 CAPO 93.7 vs 未优化 78.1）；但 2026 仍未出现"**共享变异算子库**"式的生态——共享的是被进化产物（EvolveNet 的 harness delta、HarnessBank 的基因库、GEA 的经验共享），不是算子本身。【推断】算子组合子/DSL 仍是空白：SAMMO 的 function-graph prompt 表示最接近"算子 DSL"，但已沉寂。
- **来源+日期**：arXiv:2512.02840（promptolution，2026-02 更新）；EvoAgentX（arXiv:2507.03616）被工业项目（templar/forge issue #238，2026-02）引用为优化器设计模板。
- **量化证据**：promptolution 基准数字如上（gemma-3-27B，GSM8K/SST-5）。
- **为何在既有轴系之外**：**算子的可共享性/可组合性**（产物可共享已证实，算子本身尚不可）——是一个"存在性为负但有边界证据"的新轴候选。

### 卡片 10：联合变异 prompt+代码+配置成为 2026 默认假设
- **发现**：harness 的定义在 2026 文献中已稳定为 prompt + 知识注入 + 工具规格 + 运行时控制逻辑 + 恢复机制 + 配置的**联合可变面**（HarnessBank 的 𝒲 坐标；EvolveNet、TTHE 同）。ADAS 综述（2026-06）指出 2026 区别于 2024-25 的第一趋势就是 co-evolution：prompt 与拓扑联合优化（MASPOB、TPGO，后者还 meta-优化自己的优化器）。
- **来源+日期**：arXiv:2607.13683；preprints.org 202606.0238《Automated Design of Agentic Systems: A Survey》，2026-06-02。
- **量化证据**：HarnessBank 的跨坐标重组案例（runtime 修复 + verify-finalize 栈叠，BrowseComp+ +13.9%）是联合变异收益的一手证据。
- **为何在既有轴系之外**："算子上下文输入"轴管算子**读什么**；这里算子**同时写多个层级**（编辑的作用域宽度）是独立维度。

---

## (2) 结论

### 候选新轴清单（按证据强度排序）

1. **算子可学习性轴**（固定 prompt 算子 → SFT/RL 训练的编辑策略 → 被同一管线递归进化的 meta-算子）。一手证据：Harness-R1 (+9.3pp，击败 frontier 模型算子)、MetaSkill-Evolve (+23.54pp)。**最强候选**。
2. **算子治理与谱系轴**（准入：统计门控、显著性门槛；谱系：WHERE×WHY 语义坐标、版本/重组许可、provenance=delta+行为证据）。一手证据：HarnessBank 四门 + DGM 部署回归的反例（−1.1%）。
3. **算子经济学轴**（变异成本结构：propose/apply 两级拆分的 token 效率 1.5–2×；预算分配：探索→移交→精炼的相位结构、集合级 handoff）。一手证据：Morph、RelayEvolve 簇。
4. **算子的分布与合并轴**（单主体 → 联邦多主体；合并本身成为元算子；产物而非数据跨组织流动）。一手证据：EvolveNet（70.7 vs 67.3/68.7）。
5. **算子作用域宽度轴**（单点 prompt 编辑 → prompt+代码+配置+拓扑联合编辑）。一手证据：HarnessBank 𝒲 坐标、ADAS 综述 2026 co-evolution 趋势。
6. **算子证据制度轴**（offline 有标签开发 → test-time 无标签代理信号下提交）。一手证据：TTHE。可与轴 2 合并为"治理"大轴，【推断】建议保留独立——它约束的是算子何时被允许运行，而非产出如何准入。

### 看似新、实则旧轴取值的东西

- **bandit 选 LLM 集成（ShinkaEvolve）、按置信度升级（AdaptEvolve）、按角色路由（LEVI）**：是"算子选择策略"轴上的新取值（自适应/bandit 的具体化），不构成新轴。只有 RelayEvolve 的"跨相位集合移交"越界进入经济学轴。
- **GEPA/反思式变异、E-SPL（进化+RL 联合训 system prompt）**：反思变异是"算子类型"的旧取值（反思）；E-SPL 的"EA 有时超过 RL"是选择策略层的比较结果，非新轴。E-SPL 数字：EA 单独可与 GRPO/CISPO 竞争（arXiv:2602.14697，2026-08）。
- **GEA 经验共享、HarnessBank 基因库的重组**：经验/记忆输入属于"算子上下文输入"轴的旧取值；只有"重组许可+语义坐标索引"部分溢出到治理轴。
- **自愈 harness（Self-Harness、HarnessFix、MOSS 等 2026 大量 harness 进化工作）**：均为"算子类型=重写"在 harness 目标上的实例繁荣，不是新维度；它们贡献的是轴 1/2/4 的证据密度。
- **SPO 的"1–6% 成本达到有竞争力效果"**：单点成本优化结果，属经济学轴的一个数据点，本身不是新轴。

### 空白与风险标注
- 专用编辑/apply 模型方向 2026 缺一手新基准（卡片 5 证据停在 2025-05）——【推断】该方向热度被 harness 进化叙事吸收，但"算子-模型绑定"问题本身未解决。
- 算子 DSL/组合子生态为**阴性发现**：产物共享已发生（EvolveNet），算子共享未发生。
- 未找到工业界对"变异 prompt 变更审批流"的一手披露（治理轴的工业端证据缺），学术端由 HarnessBank/EvolveNet 的门控机制部分代偿。
