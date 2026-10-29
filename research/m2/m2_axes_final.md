# M2 Operator 定稿轴系（Stage 2 · 轴系建立）

> 依据：`groupA_operator_design.md`（候选轴 O1–O18）、`groupB_operator_failures.md`（失效 O1–O8 + 候选公理 B1–B16）、`groupC_frontier.md`（6 条候选新轴）。格式对标 `m8m9/m8_deepdive_axes.md`。所有数字均引自上述三份产物，不新搜；推断标【推断】。

## 轴系设计原则（与 M5/M8M9 轴系的风格一致性约定）

1. **轴 = 决策维度，不是组件列表**。每条轴回答一个"实现 M2 时必须做的、可不同答的选择"；"用不用 bandit 库"这类组件问题不成轴，"选择策略的复杂度档位"才成轴。
2. **取值 = 可互斥、可组合的配置点**。同一轴的取值互斥（选一档），不同轴的取值自由组合（耦合处以"×"标注强相关）。每轴给默认值；默认值 = 在"评估噪声中等、预算有限、无特殊安全需求"的标准自进化场景下证据最强的档。
3. **每条轴必须被证据锚定**：至少一条 Group B 失效（反推）或 Group A/C 一手实证（正推）。纯概念轴剔除。
4. **职责边界显式化**：M2 管"如何产生新候选"（算子集、表示、上下文、选择、安全）；亲本选择的**公式参数**进 M2 配置但**选择算法归 M1**；评估语义归 M8；准入裁决归 M9；预算总额归 M3。跨界处只留接口不留轴。
5. **接口依赖标注**：每条轴标注它消费谁（M5 MemoryEntry / M8 EvalResult / M3 预算）、向谁登记（X1 谱系）。

---

## 第〇部分：合并与裁决

### Group C 六条候选新轴处置表

| C 组候选 | 处置 | 理由 |
|---|---|---|
| C1 算子可学习性（Harness-R1 / MetaSkill-Evolve） | **独立成新轴 O14** | "算子的产出分布是可学习权重"超出 A 组全部 18 轴的隐含假设（算子=固定 prompt 程序）；一手证据强（+9.3pp 击败 frontier 算子；meta-skill 双时间尺度 +23.54） |
| C2 算子治理与谱系（HarnessBank 四道统计门 + WHERE×WHY 基因库） | **拆分**：准入统计门 → 归 M9 职责（不立 M2 轴，作为 O20 漏斗"准入数"一段的消费方）；谱系坐标/版本登记 → 并入 O13/O17 的 X1 接口 | 门控语义是 AdmissionGate 设计域；M2 侧义务仅为"产出携带可登记、可重组的版本与病理坐标" |
| C3 算子经济学（propose/apply 两级、1.5–2× token 效率、相位 handoff） | **独立成新轴 O19** | "预算在时间/模型档位上的结构"是 M2 内部决策（RelayEvolve 证明它不是逐 call 路由问题），与 M3 总额预算正交 |
| C4 分布与合并（EvolveNet 联邦） | **部分收编**：merge 作为算子进 O1 取值（GEPA Merge 已有 +8.16% 证据）；联邦多主体拓扑 → **判为非 M2 职责**，归框架层/部署层（单一进化主体是本轴系的合法默认假设） | EvolveNet 的增益（70.7 vs 67.3）证明 merge 元算子有价值，但"跨组织产权与回传协议"不是算子设计问题 |
| C5 算子作用域宽度（prompt+代码+配置+拓扑联合编辑，HarnessBank 𝒲 坐标） | **独立成新轴 O4** | A 组 O6 管算子"读什么"，作用域管算子"一次写几个层级"，正交；有跨坐标重组 +13.9%（BrowseComp+）一手证据 |
| C6 算子证据体制（TTHE：test-time 无标签代理信号下运行） | **并入 O7**（反馈带宽轴增加"代理信号/无标签"取值）；运行时机约束写入 O7 耦合说明 | 证据单薄（数值未复核），独立成轴不达标；其本质仍是"变异器能消费什么样的评估信号" |

### Group A 轴合并与 Group B 盲区补轴

- A 组 O2（arity）并入 **O1**（算子集的属性，非独立决策）；A 组 O4（patch 应用器）并入 **O3**（变异表示与落地是同一决策的两半）；A 组 O18（复杂度课程）并入 **O5**（复杂度提示是上下文配方的一个字段，AIDE₈₅ 证据同根）。
- Group B 盲区 → 两条新轴：**O9 多样性维护**（B1/B2：塌缩在 fitness 曲线上隐形，A 组轴系无任何"探针/维护"维度）；**O20 算子产出漏斗记账**（B3/B5/B7 三失效的共同根因：算子质量从未被独立测量）。
- 剔除：无（A 组 18 轴全部被证据锚定，经合并后保留）。

**最终轴系：20 轴**（O1–O20，编号重排，与 A 组原编号的映射见各轴条目首行）。

---

## O1 算子集构成（原 A-O1，吸收 A-O2 arity）

**一句话定义**：M2 向搜索循环暴露的类型化算子集合及其 arity 签名（`o: 2^𝒮→𝒮`）。

| 取值 | 描述 |
|---|---|
| 三算子基集 {draft, improve, debug} | 0/1 元齐备的最小完备集，AIDE/AIRA 主流 |
| 四算子集 +crossover | OpenRSI "unified action space"，训练与推理共享同一动作空间 |
| +merge（聚合/反思合并） | GEPA Merge：组合 Pareto 前沿两候选的互补 lesson，再 +8.16%（IFBench） |
| 单算子 generate（退化自检基线） | Simple Baselines：整文件生成 + SCS 即匹配复杂系统——任何花哨配置的及格线 |

**关键证据锚点**：AIRA 控制实验（arXiv:2507.02554）：固定旧算子集时 MCTS/evo 相对 greedy 无增益（36.4–39.6% 持平），升级算子集后 +14% 相对——**算子质量是瓶颈，搜索拓扑不是**；Simple Baselines（arXiv:2602.16805）P(复杂系统>IID RS)=0.49。
**默认值**：四算子集 {draft, improve, debug, crossover}，merge 注册为可选；内置 IID-RS/SCS 退化自检（B14：表达力须外部对照）。
**耦合**：×O15（crossover 子代强制接 debug 兜底）；×O20（无漏斗数据的算子不得参与自适应选择）。

## O2 算子选择策略 π_op（原 A-O9）

**一句话定义**：每一步触发哪个算子的元决策机制。

| 取值 | 描述 |
|---|---|
| 规则优先级表（YAML 可配） | AIDE 式：种子不足→draft；以 debug_prob 回访 buggy 叶；否则贪心 improve |
| bandit（有状态、可持久化） | cost-aware UCB，get/set_state 入 checkpoint 契约 |
| RL policy | OpenRSI：Sample Operator 作为可训练输出 |

**关键证据锚点**：AIRA E3/E4 规则式 π_op 未成为瓶颈；Inria AOS 经典分析（hal-00519579）：每种自适应方案把难超参换成难超参；EoH 正例（arXiv:2401.02051）：确定性适应度下引导式 2k 查询 > 纯采样 10k（0.66% vs 2.44% gap）。
**默认值**：规则优先级表；升级 bandit 须消融证明增量超评估噪声底（B11 复杂度须挣得存在）。
**耦合**：×O20（bandit 的奖励=漏斗产率，否则在优化黑箱）；×M1（π_op 与亲本选择分离）。

## O3 变异表示与 patch 落地（原 A-O3 + A-O4）

**一句话定义**：算子改动的文本表示（diff/块标记/全文重写）及其确定性应用机制。

| 取值 | 描述 |
|---|---|
| diff_block（SEARCH/REPLACE）+ 确定性 patcher | 校验 + max_resamples 重试；OpenEvolve 生产形态 |
| evolve_block（标记区域进化） | 存量 repo 最低侵入方案，块外冻结 |
| full_rewrite | 长程重构/元层级改写的保留档位（Simple Baselines 唯一算子） |
| 概率混合 | ShinkaEvolve `patch_type_probs=[0.6,0.3,0.1]` 对冲单一表示失败 |

**关键证据锚点**：aider 排行榜一手失败率（B-O3）：o1-preview diff 合规率仅 84.2%、Qwen2.5-Coder-32B 71.6%、同模型换供应商 98.7%→84.0%——失败率是 模型×格式×供应商 的联合函数；Morph：结构化 diff 失败率 25%+ vs lazy diff + apply 模型 <1%。
**默认值**：diff_block + 确定性 patcher + 概率混合起点 [0.6,0.3,0.1]。
**耦合**：×O19（propose/apply 两级拆分的经济性）；×O18（嵌套 agent 算子常用 full_rewrite）；约束：full_rewrite 禁用于记忆/知识对象（ACE 塌缩 18,282→122 tokens 反例，B-O8）。

## O4 算子作用域宽度（新，C5）

**一句话定义**：单次算子调用可同时写入的坐标面数——单点 prompt/代码，或 prompt+知识+工具规格+运行时配置+拓扑的联合编辑。

| 取值 | 描述 |
|---|---|
| 单面编辑 | 一次只改代码或只改 prompt（2024–25 默认） |
| 多面联合编辑 | HarnessBank 𝒲 坐标（prompt/knowledge/runtime/config）联合可变 |
| 条件化作用域 | 域条件化写入（EvolveNet scope-typed delta：全局 vs 域限定） |

**关键证据锚点**：HarnessBank 跨坐标重组案例：runtime 修复 + verify-finalize 栈叠，BrowseComp+ +13.9%（arXiv:2607.13683）；ADAS 综述（2026-06）指 co-evolution 为 2026 第一趋势。
**默认值**：单面编辑（代码）；多面联合仅在 O17 安全四件套就位后开启。
**耦合**：×O16（作用域越宽越接近 harness-as-candidate）；×O17（每多一个可写面多一面冻结边界声明）。

## O5 变异上下文构造（上下文配方轴，原 A-O6，吸收 A-O18）★消费 M5

**一句话定义**：每个算子消费的记忆视图与上下文字段白名单——读什么、什么作用域、什么新鲜度/抽象度。

| 取值 | 描述 |
|---|---|
| 固定模板（全量历史拼接） | AIDE₀ naive 形态——已被证伪的失效配置 |
| 作用域记忆按算子类型切换 | AIRA 𝒪_AIRA：draft/improve 看兄弟记忆，debug 看祖先链 |
| lesson pool 引用制 | MARS：solution/debug 分池 K_m=30，变异器显式引用可审计 |
| 每算子字段白名单（可进化） | AIDE₈₅ matrix：bug rate>15% 才挂 debug 组件、debug 读 raw tail、improve 读 plateau 信号 |

**关键证据锚点**：AIRA E2/E4：全局 memory on/off 无差（38.18 vs 39.77），作用域记忆是 +14% 三件套之一——记忆是"作用域×算子类型"匹配问题；AIDE₀→AIDE₈₅ 代际对比 + 16× prompt 压缩（weco.ai 2026-07 §2.4）；B-O8：F1 塌缩记忆喂变异、F3 表面规则负迁移、F7 陈旧策略再注入三重失效。
**默认值**：作用域记忆按算子类型切换 + lesson pool；全量历史拼接为禁止默认（B15）。上下文配方变更按实验对待（记录、对照、可回滚）。
**耦合**：**直接消费 M5 MemoryEntry**（ttl/provenance/抽象度门，B16）；×O12（作用域记忆与亲本选择共同决定多样性）；复杂度提示（按节点子代数注入 minimal→advanced 线索）作为配方的一个字段。

## O6 反思驱动度（原 A-O7）

**一句话定义**：变异器在生成前消费"归因文本"的深度——从纯生成到轨迹级归因。

| 取值 | 描述 |
|---|---|
| 无（纯生成） | 直接条件生成 |
| 事后归因 lesson | MARS：差分三元组 {因果变更, 对比影响, 可泛化规则} |
| 轨迹级归因 | GEPA reflective：读模块输入/输出/推理轨迹，归因到 prompt 具体元素 |

**关键证据锚点**：GEPA（arXiv:2507.19457）：超 GRPO 平均 +10%，rollouts 少至 35×，匹配 GRPO 最优只需 78× 样本效率；MARS lesson-utilization 65.8%，跨分支迁移 63.0%；Reflexion 消融：精炼反思 vs 原始轨迹回放 +8%（arXiv:2303.11366）。
**默认值**：事后归因 lesson（成本/收益最平衡档）；轨迹级归因在评估便宜时升级。
**耦合**：消费 M5（lesson 池）+ 间接消费 M8（score_diff 触发归因）；×O7（归因文本的质量上限由反馈带宽决定）。

## O7 消费反馈带宽与证据体制（原 A-O8，吸收 C6）★消费 M8

**一句话定义**：M2 从 M8 EvalResult 获得什么形态的信号、在什么证据体制下被允许产出。

| 取值 | 描述 |
|---|---|
| public 标量 + 结构化错误定位 | 最小披露默认（B9）：给方向不给梯度 |
| +text_feedback（表面特征剥离后） | 去 rubric 关键词、去格式线索后才可喂变异器 |
| 无标签代理信号（test-time 体制） | TTHE：task gold 隐藏，仅靠执行代理信号打分（arXiv:2607.08124） |
| full trace | 仅审计/X1，永不进变异器 prompt |

**关键证据锚点**：SEAL leaky-anchor 实验：泄露数值审计分反而显著变差（Doubao 35.1→12.7）；Pride and Prejudice（arXiv:2402.11436）：GPT-4 三代 self-refine 自评 bias 0→+11 而人评不变——反馈带宽越高，可讨好面越大；CHERRL：rubric 词汇偏置 ~116 步即被 hack（转引，置信中等）。
**默认值**：public 标量 + 结构化错误定位；text_feedback 经剥离后开启。
**耦合**：**直接消费 M8 EvalResult/Verdict**（public/private 契约）；×O17（带宽闸是反 reward-hacking 结构件）；×O10（同源声明：变异器与评估器同家族时 bias 放大系数常驻监控，B10）。

## O8 新颖性闸与重复核算（原 A-O12）

**一句话定义**：子代进入评估前的近重复拦截机制。

| 取值 | 描述 |
|---|---|
| 无 | 近重复候选直接烧评估预算 |
| embedding 相似度拒绝（阈值 ~0.95） | ShinkaEvolve 消融中收益最大的单项 |
| +LLM novelty judge | 边际提升，默认关（不值额外一次 LLM 调用） |

**关键证据锚点**：ShinkaEvolve Fig.9 消融（arXiv:2509.19349）：无拒绝时 "near-duplicate programs proliferate"；AI-Scientist 复评（arXiv:2502.14297）：迭代间修改平均 +8% 字符、另一复现仅 0–0.3%——无闸系统实质原地打转。
**默认值**：embedding 拒绝（阈值 0.95 起步，配 O20 重复率台账动态校准）。
**耦合**：×O20（重复率超阈值触发算子/父代切换，B3）；×O2（新颖性>父代>bandit 的投入优先序，B12）。

## O9 多样性维护（新，B-O1 盲区补轴）

**一句话定义**：种群的表型/基因型多样性是否被显式测量、报警与主动维护。

| 取值 | 描述 |
|---|---|
| 无探针 | 塌缩在 fitness 曲线上完全隐形（plateau 误读为收敛） |
| 探针监控（跨代时间序列 + 报警阈值） | 标准化模板 + 精确串匹配代理指标（避免嵌入指标混淆 dynamic/static，arXiv:2508.13333） |
| 主动维护 | 系统交换（EvoDiverse）、niche protection/行为复活（机器人行为树 5 机制 + 8 档变异率表） |

**关键证据锚点**：Verbalized Sampling（arXiv:2510.01171）：对齐后生成多样性 45.4%→10.8%（-76%，变异供给的先验上限）；VRP 进化失败反思（arXiv:2604.07872）：纯贪心父代选择 3 代内塌缩；EvoDiverse（arXiv:2606.10587）：多样性维护不是性能税。
**默认值**：探针监控（最低档必配，B1：无多样性探针的进化循环默认视为已塌缩）。
**耦合**：×O12（贪心父代是塌缩的制度化来源）；×O2（塌缩报警应触发算子/父代切换）。注意 B2：须声明所用 LLM 的原生采样多样性上限，算子设计不得假设高于此上限的变异供给。

## O10 算子内 LLM/参数选择（原 A-O10）

**一句话定义**：算子调用内部用哪个模型、什么温度等超参的决策机制。

| 取值 | 描述 |
|---|---|
| 固定模型 + 固定超参 | 零开销基线 |
| BanditBase 式 cost-aware UCB | 状态可持久化；ShinkaEvolve 消融增益 "slight" |
| 超参可自进化（PBT 式） | PromptBreeder 温度 1.0–2.0 随进化 ±0.2 自适应 |

**关键证据锚点**：ShinkaEvolve Fig.9：bandit LLM ensemble 仅 slight 增益（投入优先序末位，B12）。
**默认值**：固定模型；bandit 为插件。
**耦合**：×O19（模型档位即成本档位，RelayEvolve handoff 的粒度）；×O13（prompt 可进化时 bandit 作用域须含 prompt 版本）。

## O11 亲本选择（原 A-O11，与 M1 交界）

**一句话定义**：算子输入亲本的采样公式——选择算法归 M1，公式参数与结构需求归 M2。

| 取值 | 描述 |
|---|---|
| 贪心 best | hill climbing：Shinka 消融中 "plateaus quickly" |
| 加权 F(p) ∝ reward×(1+子代数/方差)×rarity | ShinkaEvolve/OpenRSI：持续改进档 |
| Pareto-per-instance | GEPA：每 instance 最优前沿而非全局最优 |
| 岛比例采样 + 迁移 | FunSearch/AlphaEvolve 式隔离 |

**关键证据锚点**：ShinkaEvolve 父代消融三档排序（weighted > hill climbing > random）；VRP 案例：纯贪心 3 代塌缩（arXiv:2604.07872）。
**默认值**：加权采样；【推断】crossover 父选按互补性（差异大/Pareto）而非双高分。
**耦合**：×O9（父代选择是多样性第一调节阀）；×O5（作用域记忆与亲本共同决定多样性）。

## O12 失败子代处理（原 A-O14）

**一句话定义**：算子产出不可运行/校验失败后的处置策略。

| 取值 | 描述 |
|---|---|
| 丢弃 | 最简单；浪费生成成本 |
| debug 兜底循环（上限 N_d / 时限） | AIRA：buggy 子节点自动进 debug，上限 10 节点或 12h |
| buggy 节点冻结只许修 | 防 undo-redo 振荡 |

**关键证据锚点**：【推断，A 组卡 A4】所有成功系统都给 crossover 子代接 debug 兜底——无任何系统报告 crossover 子代 compile/pass 率高于 improve；AIDE `is_buggy` 自判误杀（B-O7）：LLM 自判 buggy 的节点被永久过滤出亲本池，不可逆误杀。
**默认值**：debug 兜底（上限可配）；is_buggy 判定不得作为永久硬过滤（保留复活通道）。
**耦合**：×O20（debug 兜底的修复成功率是漏斗的一段）；消费 M8 错误定位信号。

## O13 算子 prompt 管理与可进化性（原 A-O13）★进入 X1

**一句话定义**：算子的 prompt 是代码内嵌、配置即数据、还是自身可进化对象。

| 取值 | 描述 |
|---|---|
| 代码内嵌 | 不可审计、不可对照（OpenEvolve "换策略需改源码" 式锁定，B-O7） |
| Jinja/YAML 配置即数据 | 版本化、可 A/B、可回滚 |
| 可进化（独立 archive+bandit） | ShinkaEvolve SystemPromptEvolver meta 层；PromptBreeder 二阶进化 M′=LLM(H+M) |

**关键证据锚点**：PromptBreeder 消融：去 meta-mutation 多数数据集 fitness 下降（arXiv:2309.16797）；ShinkaEvolve 150 次评估超 AlphaEvolve（arXiv:2509.19349）。
**默认值**：配置即数据；可进化档开启时挂独立 archive。
**耦合**：**算子 prompt 版本必须进 X1 谱系**（每次变异记录 prompt 版本号）；×O14（prompt 可进化是算子可学习性的轻量档）。

## O14 算子可学习性（新，C1）★部分进入 X1

**一句话定义**：算子的产出分布是固定 prompt 程序，还是可训练的权重/可被同一管线递归进化的 meta 对象。

| 取值 | 描述 |
|---|---|
| 固定 prompt 算子 | 全部经典系统默认 |
| SFT/RL 训练的编辑策略 | Harness-R1：9B engineer 模型，奖励=patch 后冻结目标的真实任务成功率 |
| meta 算子双时间尺度进化 | MetaSkill-Evolve：meta-skill 每 H 代按"最近 H 子代改进量"进化——算子的适应度=其子代的改进量 |

**关键证据锚点**：Harness-R1（arXiv:2608.02276）：冻结目标 +9.3pp，9B 训练版超最强 frontier engineer（GLM-5.2）4.8pp，稀疏失败证据下 held-out +8.9±1.5pp 而 frontier 为负；MetaSkill-Evolve（arXiv:2607.05297）：OfficeQA +23.54。
**默认值**：固定 prompt（训练算子是高投入高回报档，须先有 O20 漏斗数据作为训练信号）。
**耦合**：×O20（算子适应度=子代改进量，正是漏斗指标的消费）；训练版算子的权重版本进 X1；×M3（训练预算是独立科目）。

## O15 被进化对象层级（原 A-O15）

**一句话定义**：算子作用的候选对象在元层级阶梯上的位置——`Candidate<T>`，T ∈ {TaskSolution, ExecutorSpec, 算子 prompt}。

| 取值 | 描述 |
|---|---|
| TaskSolution | 经典代码/解进化 |
| ExecutorSpec（harness-as-candidate） | DGM/AIDE²：评估=元评测（N 任务聚合），存活门优先于分数 |
| 算子 prompt / meta 层 | 与 O13/O14 联动 |

**关键证据锚点**：DGM：SWE-bench Verified 20%→50%、Polyglot 14.2%→30.7%（arXiv:2505.22954）；AIDE²：8 天 100 步 7 代超人类两年手调版本（博客，无同行评审，置信中等）。
**默认值**：TaskSolution；升层须先就位 O17。
**耦合**：×O4（层级越高作用域越宽）；×O17（L1+ 必须安全四件套）。

## O16 算子嵌套度（原 A-O17）

**一句话定义**：算子内部是单次 LLM 调用还是嵌套的完整子搜索/agent run。

| 取值 | 描述 |
|---|---|
| 单次 LLM 调用 | 接口 `o: 2^𝒮→𝒮` 不变，成本可控 |
| 算子内嵌子搜索（agentic 算子） | SWE-Agent 式；AIRA 展望 |

**关键证据锚点**：【推断，A 组】接口不变性使嵌套对上层透明；无直接消融证据（弱证据轴，保留因 O3 耦合明确）。
**默认值**：单次调用。
**耦合**：×O3（嵌套算子通常配 full_rewrite）；×O19（嵌套算子的成本必须进漏斗核算，否则预算失控）。

## O17 自修改安全模式（原 A-O16）★进入 X1

**一句话定义**：算子修改系统自身（含防护层）时的结构约束四件套。

| 取值 | 描述（四件套，组合而非互斥） |
|---|---|
| 冻结边界声明 | 每模块标 self_mutable 位；评估器/门代码默认不可自改（DGM 刻意冻结 exploration 机制） |
| 功能性存活门 | compile + 元能力检查优先于分数（DGM §3） |
| 小步证据化 + 快照回滚 | prime-agent /refine 范式；AIDE² ~90% 拒绝率 |
| 谱系覆盖 gate/evaluator 代码 | AIDE² 反作弊统计层被突变改坏而不自知，靠人工谱系审计才发现 |

**关键证据锚点**：AIDE² 反作弊层自毁案例（weco.ai 2026-07，B-O7 教科书案例）；"改尺子与修 bug 在操作层同构"（E2 联动）。
**默认值**：T=TaskSolution 时仅冻结边界声明；T=ExecutorSpec 时四件套全配（B13）。
**耦合**：**可自修改位 + gate/evaluator 代码版本进 X1**；×O7（带宽闸是反 hacking 结构件）；×M9（存活门与准入门分工）。

## O18 复杂度课程（已并入 O5，编号保留说明）

见 O5（复杂度提示字段）。原 A-O18 不独立成轴。

## O19 算子经济学（新，C3+C6 预算部分）★消费 M3

**一句话定义**：变异预算的内部结构——propose/apply 两级拆分、模型档位的相位移交（population handoff）。

| 取值 | 描述 |
|---|---|
| 单级同模型 | 全部调用同一模型档 |
| propose/apply 两级 | 贵模型做语义决策 + 便宜专用 apply 模型落地（Morph：失败率 25%+→<1%，1.5–2× token 效率） |
| 相位 handoff | RelayEvolve：便宜模型捕获早期进展后把 population 移交强模型（适应度改进强烈前置是一手统计规律） |

**关键证据锚点**：Morph/Continue 博客（2025-05，标【证据陈旧风险】）；RelayEvolve（arXiv:2608.05651，三条轨迹统计规律为一手观察，百分比未复核）；AIDE²：16× prompt 压缩省下的 token 再投资为搜索步数。
**默认值**：单级同模型；propose/apply 拆分在 diff 失败率台账（O20）显示落地瓶颈时启用。
**耦合**：消费 M3 预算信息（remaining_time/step_count 进 op_context）；×O10（模型档=成本档）；×M1（handoff 时机是搜索相位决策的输入）。

## O20 算子产出漏斗记账（新，B 盲区补轴）★接口 M8/M9/X1

**一句话定义**：每个算子必须报告"提议数→可应用数→可运行数→准入数"的四段漏斗，作为一等健康指标。

| 取值 | 描述 |
|---|---|
| 无记账 | 算子质量是暗数据（绝大多数论文现状——报告偏倚本身已被 B 记录在案） |
| 计数台账 | per-(模型, 表示, 任务族) 的 apply 失败率、diff 膨胀率、重复率、采纳率常驻报告（B3/B5） |
| 漏斗反馈选择 | 产率作为 O2 bandit 的奖励、O8 阈值的校准信号、O14 算子训练的训练信号 |

**关键证据锚点**：AIDE² 外环 ~90% 拒绝率（净采纳率 ~10%）；LMX（arXiv:2302.12170）：亲本顺序致交叉有效率波动 >50%、单亲无签名约束 100% 无效——无漏斗则这些全部隐形；aider 排行榜提供 per-模型×格式的失败率基准序列。
**默认值**：计数台账（最低档必配，B7：无漏斗数据的算子不得参与自适应选择）。
**耦合**：消费 M8 可运行性信号与 M9 准入裁决；漏斗记录进 X1 谱系（每个候选携带相似度核算记录）；×O2/O8/O14（三家消费方）。

---

## 总览表

| 轴 | 取值集 | 默认值 | 最强证据 | 接口依赖 |
|---|---|---|---|---|
| O1 算子集构成 | 3算子 / 4算子 / +merge / 单算子自检 | 四算子集 | AIRA +14%；SB P=0.49 | X1（算子版本） |
| O2 算子选择 π_op | 规则 / bandit / RL | 规则优先级表 | AIRA E3/E4；EoH 5× | 消费 O20 漏斗 |
| O3 变异表示与落地 | diff / evolve_block / full_rewrite / 混合 | diff+patcher+[0.6,0.3,0.1] | aider 84.2%/71.6%；Morph 25%→<1% | — |
| O4 作用域宽度 | 单面 / 多面联合 / 域条件化 | 单面（代码） | HarnessBank +13.9% | — |
| O5 上下文配方 | 固定模板 / 作用域切换 / lesson 池 / 可进化白名单 | 作用域切换+lesson 池 | AIRA +14% 三件套；AIDE₈₅ | **消费 M5 MemoryEntry** |
| O6 反思驱动度 | 无 / 事后 lesson / 轨迹级归因 | 事后归因 lesson | GEPA 35× 效率、+10% | 消费 M5；间接受 M8 |
| O7 反馈带宽与证据体制 | 标量+错误定位 / +剥离后 text / 无标签代理 / full trace(仅审计) | public 标量+错误定位 | SEAL 35.1→12.7；self-bias 0→+11 | **消费 M8 EvalResult/Verdict** |
| O8 新颖性闸 | 无 / embedding 拒绝 / +LLM judge | embedding 0.95 | Shinka Fig.9 最大单项；AIS +8% 字符 | — |
| O9 多样性维护 | 无 / 探针监控 / 主动维护 | 探针监控 | 对齐后多样性 −76%；3 代塌缩 | — |
| O10 算子内 LLM 选择 | 固定 / bandit / PBT 自进化 | 固定 | Shinka bandit "slight" | — |
| O11 亲本选择 | 贪心 / 加权 / Pareto / 岛 | 加权采样 | Shinka 父代消融三档排序 | 公式归 M1 |
| O12 失败子代处理 | 丢弃 / debug 兜底 / 冻结只修 | debug 兜底 | AIRA 10节点/12h 上限；is_buggy 误杀 | 消费 M8 错误信号 |
| O13 算子 prompt 管理 | 内嵌 / 配置即数据 / 可进化 | 配置即数据 | PromptBreeder 消融 | **进 X1（prompt 版本）** |
| O14 算子可学习性 | 固定 prompt / SFT-RL 训练 / meta 双时间尺度 | 固定 prompt | Harness-R1 +9.3pp；MetaSkill +23.54 | **进 X1（权重版本）**；消费 O20 |
| O15 被进化对象层级 | TaskSolution / ExecutorSpec / meta | TaskSolution | DGM 20%→50% | — |
| O16 算子嵌套度 | 单次调用 / 内嵌子搜索 | 单次调用 | （弱证据，接口不变性） | — |
| O17 自修改安全 | 冻结声明 / 存活门 / 快照回滚 / 谱系覆盖 | L0 仅冻结声明；L1+ 四件套 | AIDE² 反作弊层自毁 | **进 X1（self_mutable 位、gate 代码版本）**；×M9 |
| O19 算子经济学 | 单级 / propose-apply 两级 / 相位 handoff | 单级同模型 | Morph 1.5–2×；RelayEvolve | **消费 M3 预算** |
| O20 漏斗记账 | 无 / 计数台账 / 漏斗反馈选择 | 计数台账 | AIDE² ~10% 采纳；LMX >50% 波动 | **消费 M8/M9；记录进 X1** |

（编号 O18 已并入 O5，保持空号以维持与 A 组映射可追溯。）

## 逐格深挖优先级提示

证据强度排序（Group A 结论，仍然成立）：O5 上下文工程 > O8 新颖性闸 > O6 反思 > O3 diff 工程 > O9/O20 监控基建 > O2/O10 选择学习化。深挖工作量预期最大的三条：O5（配方空间组合爆炸 + M5 接口双向契约）、O7（与 M8 public/private 契约、SEAL 1-bit 下界、TTHE 证据体制的三方对齐）、O17（四件套与 M9/X1 的职责切分，AIDE² 案例需逐机制拆解）。
