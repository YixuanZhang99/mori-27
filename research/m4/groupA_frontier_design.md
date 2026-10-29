# M4 Frontier 调研 · A 组：设计空间（档案/前沿/岛拓扑/亲本供给/治理）

> 范围：候选群体的结构化组织与探索状态——档案表示、前沿定义、岛屿/种群拓扑、亲本池供给（供 M2/M1 消费）、多样性结构的物理承载、档案治理与 M5 衔接。
> 下游硬契约（必须供给，源自 M2-UNIFIED-v1 §2/§4）：亲本池字段 = `rarity / children_count / per-instance 最优表 / island_id`；多样性探针 O9 的物理承载；准入后归 M9、沉淀归 M5。
> 数字约定：一手来源（论文 arXiv 编号 / 官方仓库源码）为准；本地既有卡片（dim05/dim06/newworks15/m2 系列）内的数字均已回溯到一手出处，本文沿用并标注；外推处标【推断】。

---

## 1. 分系统卡片

### 1.1 FunSearch（Nature 2023/2024；官方仓库 google-deepmind/funsearch）

- **档案结构**：三级嵌套 `islands → clusters → programs`。signature = 逐测试得分向量排序元组，同 signature 的程序进同一 cluster（等价类聚簇）；cluster 内可有多个实现。全局配置：`num_islands=10`、`functions_per_prompt=2`、`cluster_sampling_temperature_init=0.1`、`cluster_sampling_temperature_period=30000`（softmax 温度随已注册程序数线性退火）。部署规模：15 samplers + 140 evaluators，每 prompt 采 4 个 continuation（官方 implementation/config.py）【一手：官方仓库源码】。
- **前沿定义**：无显式"前沿"；选择压力完全编码在 cluster-softmax 里（`p(cluster) ∝ softmax(cluster_score / T)`）。best-per-signature 聚类本身即隐式 per-test 前沿【推断】。
- **岛拓扑与迁移**：无迁移，代之以**周期性岛重置**：`reset_period=4h`，到点按各岛 best score 排序，**重置最差的一半岛**，用存活岛随机选出的 best program 作 founder 重播种（源码 `reset_islands`）【一手】。
- **亲本供给**：随机选岛 → 岛内按 cluster-softmax 抽 k=2 个 cluster → cluster 内均匀取 1 实现 → 按分数升序重命名 f_v0/f_v1 拼 prompt（best-shot prompting，无自然语言指令）。
- **治理**：无容量上限字段；失败程序直接丢弃（不计分即不入库）；谱系只以版本序列形式隐含。异步副作用已知：prompt 生成后岛被重置的"陈旧注册"问题，代码注释明确提及并刻意忽略。

### 1.2 AlphaEvolve（DeepMind 白皮书，arXiv:2506.13131）

- **档案结构**：`MAP-Elites × 岛屿` 组合数据库（FunSearch 骨架的升级）；prompt 抽样=历史程序+系统指令+随机化模板格式+渲染的评估结果；**meta prompt evolution**：提示词本身在独立数据库协同进化。
- **前沿定义**：MAP-Elites 胞格精英（每特征胞格存最优）；支持**多目标分数**——一手结论："即使只关心单指标，多指标进化反而更好"（不同指标下优解结构多样，注入 prompt 后刺激多样性）【一手：白皮书 §2】。
- **岛拓扑**：岛模型与网格叠加；具体岛数/迁移参数白皮书未披露（OpenEvolve 复现为其默认值来源）。
- **亲本供给**：数据库抽样历史程序（exploit 倾向 + 多样性结构），细节未全披露。
- **治理**：级联评估（hypothesis-testing cascade，测试用例按难度分级早淘汰）；asyncio 异步流水线，DB 为唯一同步点，吞吐优先。

### 1.3 OpenEvolve（AlphaEvolve 开源复现；codelion/openevolve → algorithmicsuperintelligence）

- **档案结构**：`ProgramDatabase` = MAP-Elites feature_map + 岛屿 + archive + artifacts。`Program` 字段：`id, code, language, metrics: dict, parent_id, generation, island_id, artifacts, iteration_found`。特征维度可插拔——evaluator 任意 metric 可直接充当 MAP-Elites 维度（**低成本高价值**：无需手工选特征，binning 由框架内部做）【一手：database.py / config.py】。
- **前沿定义**：MAP-Elites 胞格竞争（同格替换取优）+ 岛 best 更新；`get_best_program(metric)`。
- **岛拓扑**：`num_islands=5`、`migration_interval=50`（按岛 generation 计数，lazy migration）、`migration_rate=0.1`、**环形迁移拓扑**【一手：default_config.yaml】。
- **亲本供给**：三路混合采样 exploitation 0.7 / exploration 0.2 / random；**double selection**——展示给 LLM 的 parent 与 inspirations 分别采样。`population_size=1000, archive_size=100`。
- **治理**：`_enforce_population_limit` 人口上限淘汰；嵌入 + LLM judge 双重新颖性检查（`similarity_threshold=0.99`）；checkpoint 存完整 DB 状态+岛状态（全组件 seed=42、hash 隔离）。【反例】选择策略硬编码进 ProgramDatabase，"换策略需改源码"——M4 内部可替换性锁定的反面教材。

### 1.4 ShinkaEvolve（SakanaAI，ICLR 2026，arXiv:2509.19349）

- **档案结构**：SQLite 持久化 ProgramDatabase + **独立 prompt archive**（SystemPromptEvolver，二阶优化有独立档案）+ bandit state。样本效率：circle packing 150 样本达 SOTA【一手】。
- **前沿定义**：岛 best 更新 + 新颖性拒绝；无 MAP-Elites 网格默认（`database=island_large` 等 preset 可配）。
- **岛拓扑**：`num_islands=2`、`migration_interval=10`、`island_elitism`、`enforce_island_separation`；**stagnation 触发的动态岛屿繁殖**（`enable_dynamic_islands, stagnation_threshold=100, island_spawn_strategy ∈ {initial, best, archive_random}`）——岛拓扑不是静态常数而是可生长结构【一手：config.py】。
- **亲本供给**：`parents.py` 策略族 weighted / power_law / beam_search；`inspirations.py` elite/top-k/archive + crowding；岛选择 uniform/equal/proportional/weighted。
- **治理**：新颖性拒绝采样（嵌入 `code_embed_sim_threshold=0.99` + 可选 LLM judge，`max_novelty_attempts=3`）；Fig.9 消融显示新颖性拒绝是**收益最大单项**【一手，图内数值未读】。MetaSummarizer 每 `meta_rec_interval=10` 代产 meta-recommendations——档案→语义摘要的雏形（归 M5 雏形但在档案侧有物理载体）。

### 1.5 GEPA（arXiv:2507.19457，ICLR 2026 Oral；gepa-ai/gepa）

- **档案结构**：候选池（`Candidate = dict[组件名 -> 文本]`）+ **逐实例分数矩阵** + frontier；run_dir checkpoint 可恢复。
- **前沿定义**：**per-instance Pareto frontier**——"在至少一个验证实例上取得最优的候选集合"；亲本采样按**实例覆盖数比例随机采样**（非贪心取最优）。消融：Pareto 选择策略 **+6.4%**；整体超 GRPO 平均 ~6%、样本效率 35×【一手：论文】。
- **岛拓扑**：无岛；单池+前沿。merge proposer = 谱系合并（合并两条 lineage 各自最强模块），要求父代在 val 上有 ≥`merge_val_overlap_floor=5` 个共同已评实例。
- **亲本供给**：`candidate_selection_strategy` 可注入（默认 "pareto"，可 "current_best"）；minibatch 接受测试（sum(scores) 不降才接受新候选）。
- **治理**：预算即一等约束（`max_metric_calls` / auto 三档）；adapter state 鸭子类型快照。per-instance 矩阵 = M2 契约 O11 里"per-instance 最优表"字段的直接物化。

### 1.6 DGM（Darwin-Gödel Machine，arXiv:2505.22954）

- **档案结构**：**档案树（tree archive）**——从单一初始 agent 生长，所有成功 agent 永久保留为 stepping stones（"archived solutions can serve as stepping stones that result in improvements much later than their original discovery"，§3）。80 次迭代（SWE-bench 2 路并行 / Polyglot 4 路）。结果：SWE-bench 20%→50%、Polyglot 14.2%→30.7%；**去 archive 消融（hill-climbing）显著退化**（DGM w/o open-ended exploration，§4.3）【一手】。
- **前沿定义**：无压缩前沿——树本身就是前沿（全体存活节点）；最优 agent = 树上最高分。
- **亲本供给**：父代选择概率 **∝ 分数 × (1 + 拥有代码编辑能力的子代数)** 的近似权重（§C.2），保证档案中所有 agent 被选概率非零——`children_count` 字段的直接先例【一手】。
- **治理**：无驱逐（永久保留）；准入门=功能性（compile + 保留编辑能力，归 M9）；archive/父选择机制**刻意冻结不可自修改**（§3，留作 future work）——冻结边界声明的正面先例。

### 1.7 ADAS / Meta Agent Search（arXiv:2408.08435，ICLR 2025）

- **档案结构**：**ever-growing archive**（无限增长的 agent 档案，初始化为手工基线），每轮评估后追加；档案作为 meta agent prompt 中的 `[Discovered Agent Archive]` 部分整体注入。
- **前沿定义**：无——档案不筛选不压缩，"发现即入档"；性能排序只在 meta agent 的阅读视野里隐式发生。
- **亲本供给**：无显式采样——meta agent 读整个档案自由生成下一代（"use the knowledge from the archive… to propose the next interesting agentic system design"）。
- **治理**：无容量管理（档案增长的代价是 meta prompt 变长，属于隐性治理负债【推断】）。结果：DROP F1 +13.6、MGSM +14.4%，跨域迁移 GSM8K +25.9%【一手】。Simple Baselines（arXiv:2602.16805）指出 ~100 题小验证集下 ADAS 与 IID RS 无显著差异（P=0.49）——档案结构的价值以评估可靠性为前提。

### 1.8 AIDE²（Weco AI 博客，2026-07-14；博客级证据，置信降档）

- **档案结构**：外环**无 archive、无多样性维护**——incumbent + challenger 单链表，"keeps it only if better than the previous best"，100 步中约 9/10 被拒（~90% 拒绝率）。内环 AIDE 经典**解树**（solution tree）。
- **意义**：AIDE² ≈ "DGM w/o open-ended exploration" 配置却仍然达到 Level-1 RSI（8 天 7 代，超人调版本）——**档案结构不是自我改进的必要条件**；它与 DGM 的对照提示：档案收益依赖评估严格度（AIDE² 外环评估为固定美元预算 + private 分数）。【证据降档：厂商博客无评审】

### 1.9 LoongFlow（dim05 一手卡片；论文+仓库 base_memory.py）

- **档案结构**：`EvolveMemory` 抽象基类（`add/get/sample/save_checkpoint`，InMemory/Redis 双实现）；每岛三类结构：**islands（解集合）+ island_feature_maps（MAP-Elites 网格，每格只留最优）+ elites（elite archive，新解须优于最差精英才替换）**；feature map 与 elite archive 联动替换。默认 `num_islands=3, population_size=100, elite_archive_size=50, migration_interval=10`。
- **谱系字段**：`Solution` 携带 `parent_id / generate_plan / summary / island_id / score / sample_cnt / sample_weight / generation`（Listing 1，与仓库 dataclass 一致）——**谱系元数据=档案条目的标准字段**，planner 沿 parent_id 链回溯（lineage-based memory 替代 RAG）。
- **岛迁移**：间隔式触发（`max(island_capacity) − last_migration_generation ≥ migration_interval`，默认 10 代）；每岛取 score 前 `migration_rate=0.2` 复制（非移动）到环形邻居 `(i±1) mod N`；带 `migrated` 元数据防重复迁移、带代码逐字查重防重复注入；迁移副本保留原 plan/summary/sample_weight。注释自承 "Adapted from OpenEvolve database.py"。
- **消融**：island model 通过促进多样性，中期即达到基线峰值；cold start + adaptive sampling + island 三组件有协同效应（ahc016，5 次平均）【一手】。
- **治理升级空间【推断】**：其 MAP-Elites descriptor 退化为代码长度/文本字符差异浅层代理；把 `plan` 的嵌入/假设类别作 descriptor 维度，archive 即从"行为网格"升级为"假设网格"。

### 1.10 EvoDiverse（arXiv:2606.10587，科学假设搜索）

- **档案/多样性**：单池调温基线"often suffers from premature collapse"，基线种群在嵌入空间 "cluster tightly"；加入**系统性交换机制**后多样性显著更高**且 best-score 不降**——"多样性维护不是性能税"的一手证据【一手，经 m2 groupB/part2 卡片回溯】。
- **意义**：多样性的物理承载可用"受控通信"（交换）赎回，与岛隔离是同一旋钮的两端——岛模型=用拓扑买多样性，交换机制=用受控迁移赎回多样性【推断】。

### 1.11 EvolveNet（arXiv:2608.04968，联邦 harness 进化）

- **档案结构**：多部署点各自本地档案，server 端做 scope-typed（全局/域条件化）、证据门控的程序合并——**档案是分布式的，合并本身成为元算子**。
- **结果**：BIRD held-out 70.7% vs 等总预算集中式 population 67.3%（配对 14 胜 9 负）vs 等串行深度 68.7%（无门控链式版本直接崩溃回滚）【一手】。
- **意义**：对 M4 是"多档案联邦"拓扑取值；本地裁决已把联邦多主体判归框架层/部署层，但"档案合并语义（全局 vs 域条件化）"作为档案条目属性可留在 M4【推断】。

### 1.12 退化/对照组（档案结构价值的边界证据）

- **Simple Baselines（arXiv:2602.16805）**：IID RS 无状态；SCS 只保留上一代随机 3 个程序进 prompt、无适应度选择、可周期性 restart——"no explicit fitness-based selection or a memory of all past programs"。~100 题验证集下与 ShinkaEvolve/ADAS 无显著差异（P(Shinka>IID RS)=0.49）。**档案/前沿结构的全部复杂性以评估统计可靠性为先决条件**。
- **VRP 进化失败案例（arXiv:2604.07872）**：纯适应度贪心父代选择 **3 代内**种群塌缩（LLM 自诊断 "selecting exclusively from the top cost stratum… converge to a narrow region"）——无结构档案的最短失效路径。
- **DEEVO（arXiv:2506.00178）**：单池 + Elo 表 + newcomer/veteran 配额——无网格无岛的锦标赛式档案，适合相对评判任务。
- **机器人行为树进化（MDPI Robotics 15(5):98）**：内置 5 种多样性保护机制 + 8 档变异率表（危机档 0.45–0.50）才防住塌缩——防御成本本身即失效严重度度量。
- **Verbalized Sampling（arXiv:2510.01171）**：对齐后生成多样性 45.4%→10.8%（−76%）——档案多样性维护的上限由变异供给端先验决定（C2 prior_ceiling 的依据）。

---

## 2. 跨系统综合：M4 切分假设的验证/修正

1. **"Database 即算法"是收敛共识**：FunSearch cluster-softmax、AlphaEvolve/OpenEvolve MAP-Elites×岛、GEPA per-instance Pareto——选择压力全部编码在结构化状态库里。M4 不是被动存储，而是**探索状态的物理承载**；选择公式归 M1、字段供给归 M4 的切分成立，但 M4 必须暴露"策略可注入点"（OpenEvolve 硬编码选择进 ProgramDatabase 是反例，ShinkaEvolve BanditBase 是正面先例）。
2. **前沿定义四分**：best-so-far 单链表（AIDE²）/ 网格精英（MAP-Elites）/ per-instance Pareto（GEPA）/ 全体保留树（DGM）/ 等价类聚簇（FunSearch signature）。实测增量证据：Pareto-per-instance +6.4%（GEPA 消融）；树 vs 无树显著（DGM 消融）；单链无档案仍可达 RSI L1（AIDE²，评估严格前提下）——**前沿粒度应与评估严格度匹配**【推断】。
3. **岛数谱系**：FunSearch 10 岛 → OpenEvolve 5 岛 → LoongFlow 3 岛 → ShinkaEvolve 2 岛+动态繁殖。无一手同预算消融比较岛数；迁移率取值 0.1（OpenEvolve）/0.2（LoongFlow）；迁移周期 10（LoongFlow/Shinka）/50（OpenEvolve）；重置（FunSearch 4h 杀半岛）在开源复现中普遍被迁移替代（"重置太粗暴，迁移更平滑"，dim06 §3.7）。
4. **亲本供给字段已收敛**：`island_id / generation / parent_id / children_count / score / (plan, summary)`（LoongFlow Listing 1、OpenEvolve Program、DGM §C.2）——M2 O11 契约四字段（rarity/children_count/per-instance 最优表/岛标签）全部有先例；`sample_weight`（LoongFlow）是 rarity 的物化先例。
5. **治理三段式浮现**：容量驱逐（OpenEvolve `_enforce_population_limit`、LoongFlow elite 替换）/ 新颖性闸（0.99 嵌入阈值两系统一致）/ 永久保留（DGM/ADAS）。三者互斥性未有一手比较；与 M5 衔接：进化系档案=L1 实例仓库，跨代语义抽象普遍缺失，ShinkaEvolve MetaSummarizer 是唯一 L2 雏形——**归档什么进长期记忆仍是开放问题**（本调研阴性发现）。
6. **评估可靠性是档案复杂性的前提**：SB P=0.49 + VRP 3 代塌缩共同界定：噪声评估下复杂档案退化为随机搜索；纯贪心档案快速塌缩。M4 默认值必须落在"有结构但可退化自检"的中间带。

---

## 3. M4 候选轴系初稿（F# 编号，15 条）

> 每条：定义 / 候选取值 / 证据锚点 / 暂定默认值。选择公式归 M1、准入归 M9——F 轴只描述**状态结构与物理承载**。

| # | 轴 | 定义 | 候选取值 | 证据锚点 | 暂定默认值 |
|---|---|---|---|---|---|
| F1 | **档案拓扑结构** | 候选群体的一等组织形态 | `single_pool` / `islands(K)` / `tree` / `grid(MAP-Elites)` / `matrix(per-instance)` / 组合（grid×islands） | FunSearch 10 岛；OpenEvolve grid×5 岛；DGM 树；GEPA matrix；AIDE² 单链（博客级） | `grid×islands`（OpenEvolve/LoongFlow 双系统收敛） |
| F2 | **前沿定义** | "当前最优集合"的计算方式 | `best_so_far` / `cell_elite`（胞格最优） / `pareto_per_instance` / `tree_leaves` / `none`（全档案即前沿） | GEPA Pareto 消融 +6.4%（arXiv:2507.19457）；DGM 树消融显著（arXiv:2505.22954） | `pareto_per_instance`（逐实例评估场景）；否则 `cell_elite` |
| F3 | **岛数量 K** | 隔离子种群个数 | 2 / 3 / 5 / 10 / 动态繁殖 | 谱系 10→5→3→2；ShinkaEvolve stagnation_threshold=100 动态繁殖（arXiv:2509.19349）；无同预算消融（证据空缺） | `K=5`（OpenEvolve 默认；居中取值【推断】） |
| F4 | **岛间交换机制** | 跨岛信息流动的形式 | `reset`（周期杀半岛重播种） / `ring_migration`（环形复制迁移） / `dynamic_spawn`（停滞触发繁殖） / `none` | FunSearch reset_period=4h 杀半岛；OpenEvolve ring rate=0.1 interval=50；LoongFlow rate=0.2 interval=10 复制非移动+migrated 标记；dim06 §3.7"迁移替代重置" | `ring_migration(rate=0.1, interval=10~50)` |
| F5 | **等价类聚簇** | 档案内去重/归并的等价关系 | `signature`（逐测试得分向量） / `embedding_bin` / `none` | FunSearch signature=得分向量聚簇、簇内均匀采样（官方源码） | `none`（网格在位时冗余）；per-test 评估可用 `signature` |
| F6 | **MAP-Elites 特征维度来源** | 网格 descriptor 怎么来 | `evaluator_metric`（直接拿评估指标） / `handcrafted`（复杂度/行为） / `semantic`（plan 嵌入/假设类别） | OpenEvolve"evaluator metric 直接当维度=低成本高价值"；LoongFlow 浅层 descriptor 退化教训（dim05） | `evaluator_metric` |
| F7 | **亲本池字段集** | M4→M2/M1 的亲本采样字段供给（O11 契约） | 固定字段 `island_id / children_count / rarity / per_instance_best 表` + 可选 `sample_weight / score_vector / migrated 标记` | LoongFlow Listing 1；DGM §C.2（∝分数×子代数）；OpenEvolve Program dataclass | 四固定字段全供给（写死进类型层） |
| F8 | **亲本采样结构** | 供给的采样分布骨架（公式归 M1） | `three_way`（exploit 0.7/explore 0.2/random） / `cluster_softmax`（温度退火） / `coverage_proportional`（Pareto 覆盖数比例） / `weighted`（分数×子代数×rarity） | OpenEvolve 0.7/0.2 三路+double selection；FunSearch T0=0.1 period=30000；GEPA 覆盖比例 | `three_way` + double selection（parent 与 inspirations 分采） |
| F9 | **多样性物理承载** | 多样性由什么结构保证 | `topology`（岛隔离） / `grid`（胞格竞争） / `novelty_gate`（嵌入拒绝 0.99） / `controlled_exchange`（系统交换） / `template_stochasticity` | EvoDiverse：交换后多样性↑且 best 不降（arXiv:2606.10587）；VRP 纯贪心 3 代塌缩（arXiv:2604.07872）；ShinkaEvolve 新颖性消融收益最大单项 | `topology + novelty_gate(0.95~0.99)` 双保险 |
| F10 | **容量与驱逐策略** | 档案上限与出档规则 | `unbounded`（永久保留） / `population_limit`（淘汰最差） / `elite_replace`（优于最差精英才替换） / `cell_competition`（同格竞争天然限容） | OpenEvolve pop=1000/archive=100；LoongFlow elite=50；DGM/ADAS 无界 | `population_limit + cell_competition` |
| F11 | **失败候选的档案地位** | 失败个体是否入库/可复活 | `discard`（FunSearch） / `artifacts_only`（存侧信道不入主库） / `buggy_leaf`（标记保留+debug 复活通道） | OpenEvolve artifacts 侧信道；M2 O12 debug 兜底（失败标记保留复活通道，C11） | `buggy_leaf`（标记保留，不参选可作 debug 亲本） |
| F12 | **同步模型** | 档案与生成/评估流水线的同步点 | `async_db_sole_sync`（DB 唯一同步点，无代边界） / `generation_sync`（代际边界） / `snapshot_merge`（进程快照批量合并） | FunSearch/AlphaEvolve/OpenEvolve 全异步；ShinkaEvolve proposal/eval/db 三池配额；陈旧注册问题被 FunSearch 刻意忽略 | `async_db_sole_sync` + checkpoint 快照 |
| F13 | **持久化与 checkpoint** | 档案状态的可恢复性 | `full_db_snapshot`（OpenEvolve，seed 隔离） / `sqlite`（ShinkaEvolve+W&B） / `run_dir`（GEPA+adapter state 鸭子快照） / `redis`（LoongFlow） | 各系统一手配置；dim06 §3.10"无 checkpoint 的进化框架无法用于生产" | `full_db_snapshot`（含岛状态+bandit 状态） |
| F14 | **归档→长期记忆衔接（M5 边界）** | 什么从档案沉淀进 M5 | `none`（档案即 L1 终点） / `meta_summary`（周期摘要，L2 雏形） / `lineage_digest`（谱系链+plan/summary 结构化沉淀） | ShinkaEvolve MetaSummarizer interval=10（唯一 L2 雏形）；LoongFlow plan/summary 随解绑定；进化系普遍缺语义记忆（dim06 §5.2 阴性发现） | `none` 默认 + `meta_summary` 可选（挂 M5 写入门禁） |
| F15 | **退化自检基线** | 档案复杂性的奥卡姆剃刀 | `resident`（SCS/单链表投影永驻对照） / `none` | SB：P(Shinka>IID RS)=0.49（arXiv:2602.16805）；AIDE² 单链达 RSI L1（博客级） | `resident`——任何档案结构变更须跑赢单链/SCS 投影且增量超 M8 噪声底 |

**轴间耦合备忘**：F1×F9（拓扑即多样性承载）；F2×F8（Pareto 前沿决定覆盖比例采样）；F6×F14（语义 descriptor 与 M5 沉淀共用 plan/假设类别）；F12×F4（异步下迁移/重置的陈旧注册问题）；F15×全体（评估噪声底是任何非默认取值的启用前提）。

**空缺标注（诚实边界）**：
1. 岛数 K、迁移周期/比例无一手同预算消融——F3/F4 默认值为多系统惯例中位数【推断】。
2. 档案→M5 的沉淀协议无任何系统完整实现（仅 MetaSummarizer 雏形）——F14 是设计外推。
3. AIDE² 全部数字为厂商博客级证据，置信降档；但作为"无档案对照组"的方向性结论被 DGM 消融独立佐证。
4. 新颖性阈值两系统一致 0.99（OpenEvolve/ShinkaEvolve），M2 侧已定 0.95 起步——口径需在框架级对齐（建议以 M2 的 0.95+台账校准为准）。

---

## 参考来源（一手）

- FunSearch：Nature 2023/2024；官方仓库 google-deepmind/funsearch（implementation/programs_database.py、config.py 源码）
- AlphaEvolve：arXiv:2506.13131（DeepMind 白皮书）
- OpenEvolve：github.com/algorithmicsuperintelligence/openevolve（database.py / default_config.yaml 源码）
- ShinkaEvolve：arXiv:2509.19349；github.com/SakanaAI/ShinkaEvolve（config.py / dbase.py 源码）
- GEPA：arXiv:2507.19457（ICLR 2026 Oral）；gepa-ai/gepa（adapter.py / engine.py）
- DGM：arXiv:2505.22954（§3, §C.2, §4.3）
- ADAS：arXiv:2408.08435（ICLR 2025）
- AIDE²：weco.ai 博客 2026-07-14【博客级，置信降档】
- LoongFlow：论文 + 仓库 base_memory.py（Listing 1）
- EvoDiverse：arXiv:2606.10587；EvolveNet：arXiv:2608.04968；DEEVO：arXiv:2506.00178
- Simple Baselines：arXiv:2602.16805；VRP 塌缩案例：arXiv:2604.07872；Verbalized Sampling：arXiv:2510.01171
- 本地素材：research/dim00-08/dim05、dim06；newworks15/groupB、groupE；m2/groupA、groupB、deepdive_part2、groupC；autoresearch-fw/M2-UNIFIED-v1.md §2/§4
