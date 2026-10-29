# 深度展开：2026 新轴 F–I 与五个经典分歧点

> 依据材料：主文档《M5记忆与M6知识设计深度分析.md》§1/§3；research/m5_groupA_selfevol.md、m5_groupB_general.md、m5m6_groupE_frontier.md、m5_groupD_eval.md。所有数字均出自上述卡片并注明 arXiv 编号或来源；机制细节推断处标【推断】。

---

# 第一部分：四个 2026 新轴

## 轴 F：治理与退役（Governance & Retirement）

**轴定义**（主文档 §1）：outcome 驱动退休、有界活跃上限、per-entry 贡献分归因、append-only 证据日志。Group E 的判定：这是 ACE（只增不退）与 MetaSkill（进化但无退役语义）都没有的轴，且 2026 年证据表明"它不是可选项而是必要条件"。

### 取值表

| 取值 | 机制展开（含细节数字） | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **无治理（只增不减）** | 库单调增长，无退休、无上限、无归因。代表：DGM archive（"unbounded, per the paper"，遗忘靠选择压力而非删除）、Voyager skill library（只增，靠描述去重）、AI-Scientist-v2（无跨 run 记忆，等于回避了问题） | Library Drift（arXiv:2605.19576，AWS GenAI + HSBC）：技能库无界积累 → 检索退化、假阳性注入、性能停滞。SkillsBench（2602.12670）给出动机级证据：**LLM 自创技能 +0.0pp vs 人工策划技能 +16.2pp**——无治理的自产积累增益为零。DGM 教训粒度=整个 agent，同类 bug 跨分支反复犯（Group A §1.1） | 库极小且生命周期短（单 run 树搜索）；或把"无治理"当对照基线（MOSS 式：低信噪比环境下坏记忆不如无记忆） |
| **outcome 驱动退休 + 有界活跃上限（Ratchet 配方）** | Ratchet 三件套（2605.19576）：①按真实 outcome 退休技能；②活跃库有界上限；③元技能创作先验。配套 append-only 证据日志 + 每技能贡献分 + 归因裁决。MBPP+ hard-100 上 100 轮 **pass@1 从 0.258 → 0.584** | Library Drift 现象本身即失败案例：静默退化——库还在"增长"但检索质量已崩。Group E：Voyager 谱系重心 2026 已从"发现"转向"治理"，15+ 篇技能库论文（SkillRouter/SkillOpt/CoEvoSkills 等）是排列组合，治理才是新轴 | 库跨 run 持续累积、且条目由 LLM 自产的任何系统——SkillsBench +0.0pp 说明自产技能默认无增益，必须有退休阀把噪声压出去 |
| **有偏评审器下的退休（治理失效模式）** | 退休决策依赖评审器打分；若评审器有偏，退休机制被**静默**失效（arXiv:2607.07436 "How a Biased Judge Silently Disables Skill Retirement"）——不是报错而是机制空转 | 这是治理机制的**评估器依赖**问题：治理回路里每个 LLM 判官都是单点。旁证：AI-Scientist 的 LLM-as-judge 新颖性闸门误杀 9/10 人类已接收论文（误报）+ 漏报已知技术（主文档 M6 §2）；CODESKILL 的 rubric 评审是 LLM，存在被 skill 文本"讨好"的空间（Group A §2.5） | 任何用 LLM 做退休/准入裁决的设计都必须假设此失效存在：评审器本身要可审计、可换、最好有确定性兜底【推断】 |
| **per-entry 贡献分 + 证据日志（归因型治理）** | 每条技能/记忆记贡献分数，append-only 证据日志供事后归因裁决；与 PAST-Bench 通路归因天然互补——"Library Drift 的 per-skill contribution score 正是通路归因在技能库上的实例化"（Group E §6） | MemRL 的 Q 值是轻量版（后置效用门，Q←Q+α(r−Q)，α=0.3，Thm A.1 收敛保证），但自承多记忆共注时 credit assignment 含糊（2601.03192 §6）。反事实轨迹审计（2605.11946）是更严格的归因工具 | 需要回答"这条记忆到底帮没帮上忙"的场景；M5 做消融/卫生监控（memory_pollution_rate 等）时，贡献分是原始数据 |
| **人审批准型治理（工业取值）** | Anthropic Dreaming：每条记忆人类可读、**可审查/批准/拒绝/编辑后才上线**，纯文本 playbooks；OpenAI V3：memory summary 页 + sources 溯源 + legacy 回退 | Harvey 报告任务完成率 6x（一方数据，Group E §7 注明工业数字证据力弱）；反面：ZDNET 实测 OpenAI V3 会自信地合成错误记忆（虚构 HomeAssistant 迁移）——学术担忧（TAME misevolution、Library Drift）在产品端真实存在 | 人机协作/高风险域；"只改可读记忆层、不改权重"已成 2026 工业界安全基线共识 |

### 隐藏结构

治理轴不是单选而是**分层栈**：【推断】
1. **数据层**：append-only 证据日志（不可变、可追溯）——一切治理的原料；prime-agent 快照回滚是同层的"撤销原语"。
2. **度量层**：per-entry 贡献分 / MemRL Q 值 / ACE helpful-harmful 计数器——三者是同构的效用信号，精度递增、成本递增。
3. **裁决层**：退休判决。可由确定性规则（阈值/上限）、LLM 评审器、或人（Anthropic 批准流）执行——2607.07436 证明裁决层的评审器偏置会让整层失效，故裁决层必须与度量层解耦（度量用确定性信号，LLM 只做建议）。
4. **执行层**：退休≠删除——与分歧点 4 联动，退役条目应降级归档（保留阴性结果价值）。

### 反直觉结论

1. **退休机制可以"装着在跑"而实际空转**：有偏评审器让退休静默失效（2607.07436），监控指标（活跃库大小）看起来一切正常。治理必须被治理——评审器要纳入卫生指标。
2. **无治理的积累增益恰好为零**：SkillsBench +0.0pp 意味着 Voyager 式"验证过就入库"在规模化后等于没做记忆——治理不是防腐剂而是增益本身的来源（Ratchet 0.258→0.584 的 2.3 倍提升来自"做减法"）。
3. **贡献分的真正消费者不是退休，而是评估**：per-entry 归因与 PAST-Bench 的 mechanism score 是同构物，先把证据日志建好，退休阈值可以后调，归因数据丢了补不回来【推断】。

---

## 轴 G：元操作可学习（Learnable Memory Meta-operations）

**轴定义**（主文档 §1）：慢循环作用对象 ∈ {任务技能， 记忆写算子， 巩固策略， 评审 rubric, 记忆架构本身}。Group E：这是 MetaSkill 双时间尺度结构的泛化——巩固循环的对象从"任务知识"上移到"记忆管理操作本身"。

### 取值表

| 取值（慢循环作用对象） | 机制展开 | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **任务技能**（经典取值） | MetaSkill-Evolve：L3 元技能五元组经进化/整合写入；controller 快循环用技能、慢循环进化技能库。Voyager 谱系 2026 爆发（SkillRL 2602.08234、AutoSkill、SkillEvolver 2605.10500 等 15+ 篇）均为该取值的排列组合 | SkillsBench：LLM 自创技能 +0.0pp——慢循环产出的技能质量是命门；MetaSkill 失败模式：低频关键教训永不被检索、五元组 schema 设计错误系统性限制表达 | 任务技能是性能瓶颈且可执行验证（代码域）时——这是最成熟取值 |
| **记忆写算子** | MemSkill（arXiv:2602.02474）：controller（RL 训练，按 span 选 Top-K 技能）→ executor（LLM 一次成型生成 skill-guided 记忆）→ designer（周期性从 hard-case buffer 聚类选代表失败，精炼旧技能/提新技能）。双库解耦：memory bank（trace 特有）vs skill bank（跨 trace 共享）。含 skill bank 快照 + 性能退化回退。LoCoMo/LongMemEval/HotpotQA/ALFWorld 验证 | Group E 明确定性："MetaSkill 双时间尺度在 memory-write 算子上的同构实例"。风险：designer 复盘是 LLM，改进方向可被 hard case 的采样偏差带歪【推断】 | 记忆操作本身是手工启发式、且长历史下低效时（MemSkill 的原话动机）；AutoResearch 的"如何写消融教训"正是可 skill 化的写算子 |
| **巩固策略** | CODESKILL（2605.25430）：把 skill 提取与 skill-bank 维护做成可学习管理策略，RL 训练，hybrid reward = 密集 rubric 式 skill 质量反馈 + 稀疏下游冻结 agent 可验证执行反馈。EnvBench/SWE-Bench Verified/Terminal-Bench 2 平均 **+9.69 over 无 skill、+4.01 over 最强 memory 基线**；skill bank 维持稳定大小（容量控制可学习） | 风险自陈：管理策略过拟合训练分布——学到的保留/淘汰偏好可能系统性排斥新颖但低频有用的经验；rubric 评审是 LLM 可被讨好 | 有可靠 RL 训练信号（可验证执行反馈）时；"写什么/何时更新/何时淘汰"要从启发式升级为可优化对象时 |
| **评审 rubric** | SkillCoach（2607.01874）：评审 rubric 本身自进化 | 与轴 F 联动：评审器有偏会使退休静默失效（2607.07436）——若 rubric 还可自进化，偏置会被慢循环固化放大【推断】；正面证据：AI-Scientist 新颖性评审误杀 9/10 说明静态 rubric 也不可靠 | 评审标准随任务域漂移、人工维护 rubric 跟不上时；必须与评审器审计配套 |
| **记忆架构本身** | MemEvolve（2512.18746）：在 encode/store/retrieve/manage 四元设计空间内联合进化经验知识与架构；EvolveLab 蒸馏 12 个记忆系统为统一模块库；SmolAgent/Flash-Searcher 提升最高 17.06%，跨任务、跨 LLM 迁移 | 核心警示："没有唯一最优记忆架构，应按任务搜索"（Group B §3.3）；风险：搜索成本高（Group B 字段表） | 框架级设计期——含义是 M5 应暴露可配置轴而非锁死单点，而非在线进化架构 |

### 隐藏结构

五个取值构成**元层递进阶梯**：任务技能（对象层）→ 写算子（操作对象的手段）→ 巩固策略（操作的时机与保留规则）→ rubric（评判操作好坏的标准）→ 架构（操作存在的空间）。【推断】每上移一层：(a) 改进的杠杆变大（改 rubric 同时改变所有条目的命运）；(b) 验证信号变稀疏（架构级只有 17.06% 这种整体指标）；(c) 自指风险变大（rubric 自进化 = 裁判改规则）。MemSkill 的"双库解耦 + 快照回退"是跨层通用的稳定化模式：慢循环产物必须与快循环数据分离存储，且带可回退点。DeltaMem 的 K_cons 命中阈值巩固是"巩固策略"取值的启发式实例（无需 RL）。

### 反直觉结论

1. **最值钱的慢循环对象不是任务技能**：CODESKILL +4.01 的增益来自学"怎么管理 skill"而非"造更好的 skill"——管理策略是被长期低估的一等优化对象。
2. **慢循环越强，越需要不可学习的锚点**：rubric 可进化 + 评审器有偏 = 偏置自我固化（2607.07436 与 2607.01874 的组合风险）；MemSkill 的快照回滚、PAST-Bench 的确定性机制分是"不可被慢循环修改"的锚。【推断】
3. **MemEvolve 的真正教训不是"去进化架构"，而是"把轴做成配置项"**：无唯一最优架构意味着定稿配置只是先验，必须为框架自我实验留接口（Group B §7.6b）。

---

## 轴 H：巩固时机（Consolidation Cadence）

**轴定义**（主文档 §1）：sync / idle-time batch / hit-count 阈值 / scheduled。2026 年 5–6 月 OpenAI、Anthropic、Perplexity 三家几乎同期产品化"空闲时回顾→提炼→写回"。

### 取值表

| 取值 | 机制展开（含细节数字） | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **sync-per-episode（同步巩固）** | 每条轨迹/episode 结束即在主循环内巩固。代表：MemRL（episode 结束写 (z,e,Q_init=0) 并即时 Q 更新）；prime-agent `/refine`（同步触发，证据门+快照）；Reflexion（失败后立即反思注入下轮） | 利：零滞后，即时教训立即可用。弊：占用在线预算——MemDelta（2606.29914）测得**记忆操作可占 agent 执行时间 >80%**，500 会话事实抽取耗 1.6 亿 token；ShinkaEvolve 卡片指出周期/同步摘要成本随历史增长 | 反馈即时可得且单 episode 短；教训必须下轮就生效（调试循环） |
| **idle-time batch（空闲批处理）** | Anthropic Dreaming（2026-05-06）：空闲时后台进程回顾**最多 100 个过往会话** + 现有记忆库，抽取模式（反复错误、高效流程、团队偏好、工具怪癖），写入纯文本笔记与结构化 playbooks；每条人审后才上线；Harvey 报告任务完成率 6x（一方数据） | OpenAI 的成本证据：V3 成本降 5 倍才得以推向免费层——**批处理化的本质动机之一是成本结构**（Group E §5.3）。弊：巩固产物滞后于产生它的会话；人审批准流不适用于全自主 agent【推断】 | 会话密集且有空闲窗；记忆对象相对稳定（偏好/流程类） |
| **hit-count 阈值（命中触发巩固）** | DeltaMem（2606.03083）：成功命中计数 **≥K_cons** 触发 LLM 把链蒸馏为新根节点（神经科学启发的自主巩固）；双残差树 Task-Tree（程序性 ⟨α,π,ω⟩）与 Env-Tree（陈述性 ⟨α,κ⟩）解耦 | ALFWorld/ScienceWorld/WebShop 优于 Synapse/AWM/ReasoningBank。含义：巩固不是按时间而是按"被证明有用"触发——冷知识不被浪费算力巩固【推断】。K_cons 是手调超参 | 在线系统、巩固成本高（LLM 蒸馏）、希望巩固频率自适应于记忆实际使用强度 |
| **scheduled（定时）** | Perplexity Brain（2026-06-18）：**夜间定时综合**，输入四源——完成会话、connector 结果、源文档变更、用户纠正（编码为"避免此路"负面课程）；产出可溯源 context graph。报告重复任务正确率 +25%、recall +16%、成本 -13%（一方数据） | OpenAI V3 Synthesis 层（会话间巩固、解矛盾、更新过时事实如"计划中的旅行→已完成"）也是定时/异步取值；官方指标：事实回忆 41.5→68(V0)→83(V3)，时序正确性 9%→75%，偏好遵循 31%→71%。反面：ZDNET 实测 V3 会自信合成错误记忆 | 有明确昼夜/班次节奏的服务型系统；需要全局一致性维护（解矛盾）的库 |
| **周期摘要（学术版折中）** | ShinkaEvolve MetaSummarizer：周期触发（非每步），把跨代经验压成策略文本注入后续采样；配合 SystemPromptEvolver | 失败案例明确定性：**适应度景观快速变化时，滞后摘要持续推荐过时策略（staleness）**；meta-recommendations 自由文本无 schema，难做冲突检测与回滚（Group A §1.5） | 进化类框架的跨代知识传递；周期长度是关键超参 |

### 隐藏结构

时机轴与两个变量纠缠：【推断】
1. **巩固时滞 vs 巩固成本**：sync 零时滞高成本（>80% 执行时间警告）、idle/scheduled 低成本高时滞、hit-count 用"效用证据"换两全——但 hit-count 需要检索侧埋点（命中计数）作为前置。
2. **巩固时滞 × 环境变化率 = staleness 风险**：ShinkaEvolve 的失败不是"周期"本身而是"周期 × 快变景观"。裁决变量是适应度/知识景观的变化率，不是任务长度。
3. 与轴 D（更新/遗忘）的复合：定时巩固天然适合做"解矛盾/废止"（OpenAI Synthesis、2606.01435 确定性冲突解决）这类需要全库视角的操作；sync 只适合局部增量。

### 反直觉结论

1. **三家产品化"Dreaming"的共同卖点不是质量而是成本**：OpenAI 明说"成本降 5 倍才得以推向免费层"——异步巩固的第一性收益是把 LLM 巩固算力移出关键路径，质量提升（41.5→83）是第二位的。
2. **按"有用性"触发巩固优于按时间触发**：DeltaMem 的 K_cons 把巩固预算只花在已被检索命中的链上——定时巩固会巩固没人用的记忆【推断】。
3. **同步巩固在 agentic 负载下可能是预算灾难**：>80% 执行时间花记忆操作意味着"每 episode 后巩固"在长任务里不可承受；sync 取值应限定给廉价操作（MemRL 的标量 Q 更新），重型巩固（蒸馏/解矛盾）必须异步。

---

## 轴 I：记忆目的 × 对象（Purpose × Object）

**轴定义**（主文档 §1）：记忆 about {用户 vs agent 工作} × for {参与度 vs 性能}。Perplexity Brain 显式提出此两轴框架。

### 取值表（象限）

| 象限 | 机制展开 | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **about=用户 × for=参与度** | OpenAI V3 Capture 层：会话中被动识别值得记的事实/偏好，用户画像 + 进行中的项目 | 参与度象限的真实风险：ZDNET 实测 V3 自信地产生错误合成记忆（虚构 HomeAssistant 迁移）——错配的记忆直接损害信任；用户侧控制（summary 页/溯源/legacy 回退/Temporary Chats）是该象限的必备治理 | 消费级助手产品；AutoResearch 不涉及 |
| **about=用户 × for=性能** | Google Memory Bank / Memory Profiles：身份域隔离的低延迟高精度回忆，"身份作用域数据库原语" | 工业定位对比：Anthropic=文件系统、OpenAI=向量库检索工具、Google=身份域 DB（Group E §3.5） | 多租户企业场景，按身份隔离记忆 |
| **about=agent 工作 × for=参与度** | （基本为空象限）【推断：无卡片证据，主文档与 Group E 均未给出实例】 | — | — |
| **about=agent 工作 × for=性能** | Perplexity Brain 的显式选择：work-memory × performance。构建可溯源 context graph（每条记忆回溯到产生它的会话/文件/connector）；四输入源含用户纠正→负面课程；+25% 重复任务正确率、+16% recall、-13% 成本。Anthropic Dreaming 同象限：playbooks 记"反复错误、高效流程、工具怪癖" | 我们全部调研的学术系统（ACE/MemRL/IBM TSM/MemSkill…）都隐式位于此象限（Group E §5.4："我们的调研隐含全在 (work, performance) 象限"） | **研究 agent 应显式声明此象限** |

### 隐藏结构

象限声明不是文档工作，它决定下游三件事：【推断】
1. **utility 的定义**：for=性能 → 效用=任务分/Q 值/贡献分（可接 MemRL、Ratchet）；for=参与度 → 效用=留存/交互指标——两者用错会优化错目标（OpenAI V3 争议=象限错配的产品风险，Group E §5.4）。
2. **治理界面的必要性**：about=用户 → 人审/编辑/删除是合规底线（Anthropic 批准流、OpenAI summary 页）；about=工作 → 治理可以是纯自动的（贡献分+退役阈值）。
3. **负面课程的位置**：Brain 把用户纠正编码为"避免此路"，这只在 about=工作象限有意义——对应学术侧 ACE 的 harmful 计数、MemRL 的 FAILED EXPERIENCES 块、DeltaMem 的 failure-node penalty。

### 反直觉结论

1. **研究 agent 的默认象限声明能防住一整类设计污染**：一旦声明 for=性能，"用户喜欢的答案"类信号（对话满意度）就显式不属于 M5 效用函数——否则参与度信号会悄悄污染贡献分【推断】。
2. **2026 工业界三家实际上收敛到了同一象限分歧**：OpenAI 守在用户象限（画像/偏好），Anthropic 与 Perplexity 移到工作象限（playbooks/context graph）——消费级与企业级记忆产品正在沿 I 轴分裂，而非沿技术分裂。
3. **空象限（about=工作 × for=参与度）不是疏漏**：它提示"为了参与度去记 agent 工作"没有自然需求，两轴不是均匀张成设计空间【推断】。

---

# 第二部分：五个经典分歧点

## 分歧 1：记忆该不该进 context（DGM 基因型 vs 文本记忆）

### 两方最强论据

**DGM 方（记忆=基因型代码库，不进 context）**：
- 记忆即制品：archive 每条目是完整可分叉 agent（代码+performance.txt+谱系），天然可执行、可回滚（任何祖先可重新分叉）、谱系可审计（2505.22954 + 复现 repo）。
- **零 context collapse 风险**：记忆不进 context，进的是代码本身——ACE 的 18282→122 塌缩机制在此根本不存在（Group A §1.1）。
- 选择压力替代遗忘：parent selection 按 sigmoid(performance)×1/(1+children) 采样，无需维护遗忘机制。

**文本/结构化记忆方（记忆进 context）**：
- 粒度：DGM 教训粒度=整个 agent，**无法表达"局部教训"，同类 bug 在不同分支反复犯**（Group A §1.1 弊 a）。文本条目（IBM 13 字段 tip、ACE bullet）可精确到单一策略。
- 评测独立性：DGM 依赖可自动评分的 benchmark——**评测被 hack 时整个 archive 被污染且无检测机制**；MemRL 式效用记忆至少有 Q 值后置修正与回滚概念。
- 长程可读性：DGM 无压缩，长程进化后检索/选择退化为纯标量打分，丢失"为什么有效"（Group A §1.1 弊 c）。

### 裁决规则

- **评测可自动验证且粒度=整个程序可接受时（代码进化、benchmark 优化）→ DGM 赢**：免 collapse、免维护遗忘、回滚免费。
- **评测信号稀疏/不可验证的开放研究任务 → 文本记忆赢**（主文档 §3 判据原文）：教训粒度必须是条目级，且需要 provenance 支撑不可验证结论的置信管理。
- 混合判据：若教训可以编译为可执行制品（检查脚本、断言），基因型路线的优点可部分移植到条目级【推断：prime-agent L3、EvolveNet harness 即此折中】。

### 对框架的含义

- **默认值：文本/结构化条目进 context**（研究任务评测不可验证是常态）。
- **不做成二选一配置项**：M5 分层已含 L3 可执行方法知识（skill）——"基因型"在框架内降级为 L3 条目的表示格式取值，而非独立记忆系统。配置项应为"L3 条目是否可执行化"，默认对可自动验证的域开启【推断】。

---

## 分歧 2：分支私有 vs 全局共享（MetaSkill vs IBM/MemRL）

### 两方最强论据

**分支私有 + meta 检索传播（MetaSkill）**：
- 隔离性：坏经验不扩散；"默认私有、按需广播"模型天然防全局污染（Group A §1.3）。
- 与 EvolveNet 域隔离同理：多租户/多域场景下唯一明确"什么可以出域"的设计（行为证据级抽象，原始轨迹不出域）。

**全局共享（IBM TSM / MemRL）**：
- 迁移增益的量化证据：MemRL 跨模型迁移 **0.150→0.531（3.5×）**（Gemini-3-pro 训练的 bank 直接给 Qwen3-235B）；跨任务合并几乎无干扰（OS∪DB：**−0.004**）（2601.03192 Table 5/6）。
- IBM subtask 抽象：task-level 与 subtask-level 双粒度共存，subtask tips + LLM 检索 held-out SGC **+14.3pp（难任务 +28.5pp，+149% 相对）**（2603.10600 §4）。
- MetaSkill 的失败模式即私有化的代价：**低频但关键的教训可能永不被检索到**（Group A §1.3 弊）。

### 裁决规则

- 任务间同构性高、reward 可靠 → 全局共享赢（MemRL 跨任务合并 −0.004 说明干扰可忽略）。
- 任务相似度低 → 全局退化为单任务反思（MemRL 在 HLE 上跨任务无增益，Table 3），私有化至少不亏。
- 污染面考量：全局共享=污染面最大（MemRL 自承投毒样本可快速扩散致 collapse，App. G.4）；有对抗/不可信写入源时必须加门或退回私有。

### 对框架的含义

- **默认值：任务局部**（主文档定稿）；跨任务迁移走泛化/抽象层——具体落地为 IBM 式 subtask 双粒度：L2 条目写两份（domain-specific + generic），只有 generic/subtask 级条目可跨任务共享【机制来自 2603.10600 §3】。
- **做成配置项**：`scope ∈ {run, task, domain, global}`，默认 task；升 global 的前置条件写成清单（来源校验 + Q/贡献分后门 + 回滚快照在位）——共享是权限提升，不是默认态【推断】。

---

## 分歧 3：摘要周期（ShinkaEvolve 周期 MetaSummarizer vs MemRL 即时 EMA）

### 两方最强论据

**周期摘要（ShinkaEvolve）**：
- 控制 context 膨胀：把跨代经验压成一段策略文本注入采样上下文；配合 prompt 进化让"记忆使用方式"本身可改进（Group A §1.5）。
- 批处理摊销成本——呼应轴 H 工业证据（OpenAI 成本降 5 倍）。

**即时 EMA（MemRL）**：
- 零 staleness：每条轨迹结束即 Q←Q+α(r−Q)（α=0.3），收敛性与方差界有定理保证（Thm A.1）；遗忘率 FR=0.041 vs MemP 0.051，去掉归一化+门控升至 0.073。
- 失败案例对照：**ShinkaEvolve 在适应度景观快变时，滞后摘要持续推荐过时策略**（Group A §1.5 失败场景）——周期摘要的系统性风险。

### 裁决规则

裁决变量 = **景观变化率 × 摘要成本**（主文档 §3 + 轴 H 分析）：
- 适应度/知识景观稳定 + 摘要用 LLM（贵）→ 周期摘要赢（成本主导）。
- 景观快变 + 更新是廉价标量运算 → 即时 EMA 赢（staleness 主导）。
- 注意 EMA 的前置：**即时更新需可靠 reward**（主文档 §3 原判据）；无可靠 reward 时即时更新 = 即时污染（MemRL no-signal 讨论：Q 估计被噪声主导）。

### 对框架的含义

- **双速默认值**（两者都要，分工而非二选一）【推断：与轴 H 隐藏结构一致】：
  - 即时层：每条目效用标量 EMA 更新（便宜、无 LLM），默认开；
  - 周期层：LLM 摘要/合并/解矛盾，默认 idle-time/定时触发（轴 H 取值），不进关键路径。
- **配置项**：`consolidation_cadence ∈ {sync, idle, hit_count, scheduled}`，默认 idle；周期层超参（周期长度/K_cons）必须暴露，因为 ShinkaEvolve 证明它是 staleness 的旋钮。
- 周期摘要产物必须带 schema 与版本（ShinkaEvolve 自由文本无冲突检测/回滚的教训）。

---

## 分歧 4：遗忘 = 删除 vs 降级（MemoryOS FIFO vs MemRL Q 压低）

### 两方最强论据

**删除（MemoryOS FIFO）**：
- 工程简单、可预期：短→中 FIFO 链式批量转储、中→长分段页聚合；LoCoMo 上 F1 **+49.11%**、BLEU-1 +46.18%（GPT-4o-mini，2506.06326）。
- 直接控制膨胀与检索噪声（F5）；容量有硬保证。

**降级/压低不删除（MemRL Q 值压低）**：
- 坏经验被环境奖励自然压低检索概率而非删除——**保留否定性知识的检索可能性**；写入宽松、读取侧惩罚有理论保证（变分最优性，App. A.4）。
- 主文档 §3 判据原文：**研究场景阴性结果与被反驳假设是高价值记忆**（防止重复试错；MemRL 的失败记忆块 "FAILED EXPERIENCES (Avoid these mistakes)" 正是利用被压低但保留的经验）。
- Group B §7.5 佐证：研究中"被反驳假设"防重复试错，剪枝应改为归档层并记录删除理由。
- 删除的内容无关性缺陷：FIFO 是内容无关启发式，会误删高价值旧记忆（Group B §6 轴 D 对照表）。

### 裁决规则

- 场景含**高价值阴性结果/被反驳假设**（研究、调试、合规审计）→ 降级赢，删除是永久信息损失。
- 纯消费级对话、存储成本敏感、阴性结果无复用价值 → 删除/FIFO 可接受。
- 技术前提：降级方案要求读取侧有效用重排（λ·Q 项）兜底，否则被压低的条目仍会以纯相似度漏回 context【推断】——降级+无语加权重的读取 = 没降级。

### 对框架的含义

- **默认值：降级归档，不删除**（主文档已定稿"降级归档（不删除）"）。
- 三层落实：活跃库（有界，轴 F 上限）→ 归档层（降级条目，保留 provenance 与退役理由）→ 删除仅限卫生事件（投毒确认、合规要求），且删除动作写入 append-only 证据日志【推断】。
- **配置项**：`forgetting ∈ {fifo, q_demote, ttl_expire}`，默认 q_demote；TTL 过期（F4 例外规则）走降级而非删除，与 SM06 协议兼容。
- 配套硬要求：读取侧必须启两阶段（召回+效用重排），否则降级默认值失效。

---

## 分歧 5：短期最优 vs 长期最优（Tenure Crossover）

### 两方最强论据

**短期评测结论（隐式主流）**：
- 绝大多数记忆系统按单点 benchmark 排名定优劣；ConvoMem 甚至发现 ~150 会话以下全上下文反而优于检索记忆——短程 benchmark 压缩了要测的差异（F5 证据）。

**纵向评测方（Ground Truth First, arXiv:2607.21962）**：
- **任期交叉（Tenure Crossover）：记忆架构排名随使用时长反转——短期最优架构长期可能最差**（2026-07-24）。
- 旁证机制：(a) Library Drift——无治理的库长期静默退化，短期评测看不到；(b) 周期摘要的 staleness 只在长程暴露；(c) ConvoMem 证明短程评测把"检索 vs 全量"的结论做反。评测诚信面：LoCoMo 答案键 6.4% 错误、judge 接受 62.8% 故意错答，单点静态评测结论双重不可信（F8）。

### 裁决规则

此分歧的裁决是元规则：**任何记忆架构对比结论，必须附 tenure 点声明；单 tenure 点结论不可外推**（主文档 §3 原判据："评测必须在多个 tenure 点做纵向测量"）。短 tenure 赢的架构特征：无治理开销、全量注入、无巩固延迟；长 tenure 赢的架构特征：有退役机制、降级归档、异步巩固——恰好是轴 F/H 的取值。【推断】

### 对框架的含义

- **默认值：不为单点指标调参**；M5 配置定稿时，涉及治理开销的取舍（活跃库上限、巩固频率）按长 tenure 假设设默认。
- **做成评测协议而非配置项**：M5 消融协议（主文档 §5 四层归因）增加纵向维度——在 ≥3 个 tenure 点（如 learn 期结束 / 2× / 4× 经验量【推断：具体倍数由基准定】）重复双重差分测量，报告排名是否稳定；排名反转本身作为一等发现报告，不得取平均掩盖。
- 卫生指标（memory_pollution_rate、stale_leak_events、over_storage_penalty）按 tenure 画曲线——漂移的早期信号在曲线斜率里，不在终值里【推断】。

---

## 附：轴 F–I 与分歧点的耦合图（速查）

- F×分歧4：退役执行=降级归档（不是删除）；治理栈的度量层（贡献分/Q）同时是降级的技术前提。
- F×分歧5：治理开销是"长 tenure 才回本"的投资——Tenure Crossover 是轴 F 必配的证据。
- G×F：rubric 可进化（SkillCoach）× 评审器有偏（2607.07436）= 偏置自固化风险；慢循环产物必须可被治理栈退役。
- H×分歧3：摘要周期分歧即 H 轴在学术系统的实例；双速方案=sync 标量更新 + idle/scheduled LLM 巩固。
- I×一切：象限声明决定 utility 定义，utility 定义决定贡献分（F）、慢循环奖励（G）、巩固触发（H）各自优化什么。
- 分歧1×分歧2：基因型方案天然全局共享（archive 即进化），文本方案才有私有/共享之争；框架选文本路线后才需要 scope 配置项。
