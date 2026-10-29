# M4 Frontier 定稿轴系（Stage 2 · 轴系建立）

> 依据：`groupA_frontier_design.md`（候选轴 F1–F15 + 12 张系统卡片）、`groupB_frontier_failures.md`（失效 M4-1～M4-8 + 候选公理 F-B1～F-B16 + 四个共同根因）、`groupC_frontier_new.md`（6 条候选新轴 + 阴性发现）。格式对标 `m2/m2_axes_final.md`。所有数字均引自上述三份产物，不新搜；推断标【推断】。M4 轴用 P 前缀（避免与 M2 的 O、M6 的 K 混淆）。

## 轴系设计原则（与 M2/M5 轴系的风格一致性约定）

1. **轴 = 决策维度，不是组件列表**。每条轴回答一个"实现 M4 时必须做的、可不同答的选择"；"用不用 SQLite"这类组件问题不成轴，"档案状态的可恢复性档位"才成轴。
2. **取值 = 可互斥、可组合的配置点**。同一轴取值互斥（选一档），不同轴自由组合（耦合处以"×"标注）。每轴给默认值；默认值 = 在"评估噪声中等、预算有限、单主体单 run"的标准自进化场景下证据最强的档。
3. **每条轴必须被证据锚定**：至少一条 Group B 失效（反推）或 Group A/C 一手实证（正推）。纯概念轴剔除（C5 档案经济学因此降为横切约束）。
4. **职责边界显式化（刚性）**：M4 管"探索状态的物理承载"（档案结构、前沿表示、岛拓扑、亲本池字段供给、治理原语、健康探针）；**选择公式/权重归 M1**（M4 只暴露策略可注入点与字段）；**准入/准出裁决规则归 M9**（M4 只执行存储侧后果）；**语义沉淀归 M5**（P14 只到"衔接协议"为止）；**亲本池字段契约写死对齐 M2-O11**（`island_id / children_count / rarity / per-instance 最优表`）。
5. **模块定位公理（B 组根因 4）**：M4 的设计目标不是"保管最好的"，而是**限制任何单点失效（塌缩/hacking/噪声）的传播半径**——默认值选择以此为准绳。
6. **接口依赖标注**：每条轴标注它供给谁（M1 选择 / M2 算子 / M5 沉淀 / M9 准入 / X1 谱系）、消费谁（M8 EvalResult 噪声底 / M3 预算）。

---

## 第〇部分：合并与裁决

### Group C 六条候选新轴处置表

| C 组候选 | 处置 | 理由 |
|---|---|---|
| C1 分布与合并（EvolveNet 联邦 / Red Queen champion 交换） | **独立成新轴 P16** | 一手量化强（BIRD held-out 70.7% vs 等预算集中式 67.3%、配对 14 胜 9 负、合并协议消融各自证明贡献）；跨 run 合并恰是 B 组 M4-7/F-B14 的盲区——分布拓扑与合并语义在 2023 前 QD 文献不存在。**但跨组织产权/联邦部署归框架层**（与 M2 对 C4 的裁决一致），M4 轴只到"合并协议与重标定义务" |
| C2 移交/估值（RelayEvolve relay bank + Relay Gain） | **独立成新轴 P17** | 档案整体被打包、估值、移交是"档案作为状态耦合资产"的独有属性，不能并入父代采样轴；11/12 设置均值最高 + "call 级 bandit 近视"一手对照 |
| C3 内容表示（SeaEvo 双空间 / IDEAgent 阴性库 / meta-notepad） | **独立成新轴 P18** | LLM 使"档案存语义层"零成本化；SeaEvo +21% 一手证据；2023 前行为描述子是人工低维向量，不存在"LLM 生成+LLM 消费的档案元表示" |
| C4 记忆分层/多存储（IDEAgent A/Q/H/R 四存储） | **并入 P18 作子结构取值** | 单点证据、增益量化弱（原文标注观察项）；"阴性知识一等表示"作为 P18 取值之一保留 |
| C5 档案经济学（token/美元成本） | **判非轴，降为横切约束** | 无专文基准（C 组阴性发现 2），证据散落三系统实现细节；成本意识写入 P10/P13/P17 的耦合说明 |
| C6 证据制度（TTHE test-time 无标签代理信号） | **并入 P16 取值 + M9 接口标注** | 准入规则归 M9 职责（与 M2 对 C6 的裁决一致，M2 侧已并入 O7）；M4 侧仅剩"档案生命周期短至一次评估"的分布形态，作 P16 取值 |

### Group B 盲区 → 两条新轴

- **P19 档案健康探针**（B 组根因 2：档案健康不可从内部观测，供给熵/跨岛距离/实例判别力/重评存活率等二阶指标在 FunSearch/AlphaEvolve/OpenEvolve/ShinkaEvolve 中**全部缺失**——M4-1/M4-4/M4-5/M4-8 四失效的共同根因）。
- **P20 双资格分离**（B 组根因 1：**进档靠分数，供亲与交付靠证据**——F-B4 分数与亲本权重解耦、F-B15 置信度一等字段+保守晋升的制度化承载轴；M4-2 hacking 放大与 M4-8 噪声滞留的共同对策）。

### Group A 轴处置

- 15 条全部保留（均被证据锚定）；F5（等价类聚簇）与 F1 相近但证据独立（FunSearch signature 聚簇一手源码），保持独立。
- **特别裁决①（新颖性阈值口径）**：M2-O8 定 0.95 起步、系统惯例 0.99（OpenEvolve/ShinkaEvolve 两系统一致）。裁决：M4 侧该机制属 **P9 多样性物理承载**（取值 `novelty_gate`）；口径**以 M2 的 0.95+台账校准为准**，P9 默认值写 0.95 起步并注明"两系统 0.99 为嵌入模型×去重目标差异所致，框架级以 M2 口径对齐、由 P19 重复率台账动态校准"【推断：0.99 对应"近似克隆拦截"、0.95 对应"近重复拦截"，目标不同】。
- **特别裁决②（F15 退化自检基线是否保留）**：**保留为轴（P15）**。M2 侧 O1 的内置 IID-RS/SCS 自检针对"算子集表达力"，P15 针对"档案结构复杂性"（奥卡姆剃刀对象不同：SCS/单链表投影是档案结构的对照组）；SB P=0.49 与 AIDE² 单链达 RSI L1 是档案特有的边界证据，M2 同型约定不覆盖。

**最终轴系：20 轴**（P1–P20；P1–P15 对应 A 组 F1–F15，P16–P18 来自 C 组，P19–P20 来自 B 组盲区）。

---

## P1 档案拓扑结构（原 F1）

**一句话定义**：候选群体的一等组织形态——单池/岛/树/网格/实例矩阵及其组合。

| 取值 | 描述 |
|---|---|
| single_pool | 单池（DEEVO 式锦标赛/单链表为其极端） |
| islands(K) | 隔离子种群，FunSearch 谱系 |
| grid(MAP-Elites) | 行为胞格精英 |
| matrix(per-instance) | GEPA 逐实例最优表 |
| tree | DGM 档案树，全体存活节点即前沿 |
| grid×islands（组合） | AlphaEvolve/OpenEvolve/LoongFlow 三系统收敛形态 |

**关键证据锚点**：OpenEvolve `ProgramDatabase` = MAP-Elites×islands×archive（database.py 一手）；DGM 去 archive 消融显著退化（arXiv:2505.22954 §4.3）；GEPA per-instance Pareto 消融 +6.4%（arXiv:2507.19457）。
**默认值**：`grid×islands`（OpenEvolve/LoongFlow 双系统收敛）。
**耦合**：×P9（拓扑即多样性承载）；×P15（任何非单链拓扑须跑赢单链投影）。

## P2 前沿定义（原 F2）

**一句话定义**："当前最优集合"的计算方式。

| 取值 | 描述 |
|---|---|
| best_so_far | 单点指针——禁止作默认（M4-6 单峰锁定失效） |
| cell_elite | 胞格最优（MAP-Elites 同格替换取优） |
| pareto_per_instance | 至少一个验证实例上最优的候选集合（GEPA） |
| tree_leaves | 全体保留（DGM/ADAS 无压缩） |
| none（全档案即前沿） | ADAS：发现即入档，排序只在 meta 阅读视野隐式发生 |

**关键证据锚点**：GEPA Pareto 消融 +6.4%、整体超 GRPO 平均 ~6%、样本效率 35×（arXiv:2507.19457）；DGM 树消融显著（§4.3）；AIDE² 单链无档案仍达 RSI L1（weco.ai 2026-07，博客级降档）。
**默认值**：逐实例评估场景 `pareto_per_instance`；否则 `cell_elite`。前沿粒度应与评估严格度匹配【推断】。
**耦合**：×P8（Pareto 前沿决定覆盖比例采样）；×P10（前沿表示精度与维护预算联立，F-B9）。

## P3 岛数量 K（原 F3）

**一句话定义**：隔离子种群个数——静态常数或可生长结构。

| 取值 | 描述 |
|---|---|
| K=2 | ShinkaEvolve 默认（+动态繁殖） |
| K=3 | LoongFlow 默认 |
| K=5 | OpenEvolve 默认 |
| K=10 | FunSearch 生产配置 |
| 动态繁殖 | stagnation_threshold=100 触发 island spawn（initial/best/archive_random） |

**关键证据锚点**：岛数谱系 10→5→3→2（四系统一手配置）；ShinkaEvolve `enable_dynamic_islands`（config.py 一手）；**无一手同预算消融——证据空缺明确标注**。
**默认值**：K=5（多系统惯例中位数【推断】）。
**耦合**：×P4（迁移/重置参数与 K 共成三维超参面）；×P19（K 的健康判据在跨岛距离而非岛内指标）。

## P4 岛间交换机制（原 F4）

**一句话定义**：跨岛信息流动的形式与时机。

| 取值 | 描述 |
|---|---|
| reset（周期杀半岛重播种） | FunSearch reset_period=4h 重置最差一半岛 |
| ring_migration | 环形复制迁移：OpenEvolve rate=0.1/interval=50；LoongFlow rate=0.2/interval=10，复制非移动+migrated 标记+逐字查重 |
| dynamic_spawn | 停滞触发繁殖（ShinkaEvolve） |
| none | 纯隔离 |

**关键证据锚点**：各系统一手配置；dim06 §3.7"迁移替代重置"（重置太粗暴）；M4-4：稠密通信拓扑加速早熟收敛（arXiv:2604.18005，多智能体域，迁移性标【推断】）。
**默认值**：`ring_migration(rate=0.1, interval=10~50)`；迁移/重置周期须带阶段感知（F-B8），固定周期为待证默认。
**耦合**：×P12（异步下迁移的陈旧注册问题，FunSearch 刻意忽略的先例）；×P19（跨岛距离单调下降触发迁移率下调，F-B7）。

## P5 等价类聚簇（原 F5）

**一句话定义**：档案内去重/归并的等价关系。

| 取值 | 描述 |
|---|---|
| signature（逐测试得分向量） | FunSearch：同 signature 进同一 cluster，簇内均匀采样 |
| embedding_bin | 嵌入分桶（与 P9 新颖性闸共用嵌入通道） |
| none | 网格在位时冗余 |

**关键证据锚点**：FunSearch 官方源码（signature=得分向量排序元组，cluster_sampling_temperature T0=0.1/period=30000）【一手】。
**默认值**：`none`；per-test 评估场景用 `signature`。
**耦合**：×P6（signature 是"评估指标直接当 descriptor"的极端形态）。

## P6 MAP-Elites 特征维度来源（原 F6）

**一句话定义**：网格 descriptor 怎么来。

| 取值 | 描述 |
|---|---|
| evaluator_metric | OpenEvolve：任意评估指标直接充当维度——"低成本高价值"，binning 由框架内部做 |
| handcrafted | 手工复杂度/行为描述子（2023 前 QD 主流） |
| semantic | plan 嵌入/假设类别（LoongFlow 升级空间【推断】） |

**关键证据锚点**：OpenEvolve config.py 一手；LoongFlow descriptor 退化为代码长度/字符差异浅层代理的教训（dim05 卡片）。
**默认值**：`evaluator_metric`。
**耦合**：×P18（semantic descriptor 与档案语义表示共用 plan/假设类别）；×P19（descriptor 退化由健康探针暴露）。

## P7 亲本池字段集（原 F7，对齐 M2-O11 写死）★供给 M1/M2

**一句话定义**：M4→M2/M1 的亲本采样字段供给契约。

| 取值 | 描述 |
|---|---|
| 四固定字段 | `island_id / children_count / rarity / per_instance_best 表`——类型层写死，对齐 M2-O11 |
| +可选字段 | `sample_weight`（LoongFlow，rarity 的物化先例）/ `score_vector` / `migrated 标记` |

**关键证据锚点**：LoongFlow Listing 1（Solution dataclass：parent_id/plan/summary/island_id/score/sample_cnt/sample_weight）；DGM §C.2（父代选择概率 ∝ 分数×(1+子代数)——children_count 直接先例）；OpenEvolve Program dataclass。
**默认值**：四固定字段全供给（不可裁剪）。
**耦合**：**刚性契约，写死对齐 M2-O11**；×P20（供亲资格标记是本契约的新增布尔位，被污染探针标记者字段在位但供亲位关闭）。

## P8 亲本采样结构（原 F8，公式归 M1）★接口 M1

**一句话定义**：M4 暴露给 M1 的采样分布骨架与可注入点——**选择公式/权重归 M1，结构与字段供给归 M4**。

| 取值 | 描述 |
|---|---|
| three_way（exploit/explore/random） | OpenEvolve 0.7/0.2 三路 + double selection（parent 与 inspirations 分采） |
| cluster_softmax（温度退火） | FunSearch T0=0.1、period=30000 线性退火 |
| coverage_proportional | GEPA：按 Pareto 覆盖实例数比例随机采样 |
| weighted（分数×子代数×rarity） | ShinkaEvolve/DGM 式持续改进档 |

**关键证据锚点**：ShinkaEvolve 父代消融三档排序 weighted > hill climbing > random（Fig.9）；VRP 纯贪心 3 代塌缩（arXiv:2604.07872）；OpenEvolve 选择策略硬编码进 ProgramDatabase 是**反例**（F-B2 要求供给函数可热替换）。
**默认值**：`three_way` + double selection；策略注入点必须为一等接口。
**耦合**：**选择算法归 M1，M4 只暴露注入点**（刚性边界）；×P2（前沿定义决定可用骨架）；×P19（供给熵是骨架的健康指标）。

## P9 多样性物理承载（原 F9，含裁决①）

**一句话定义**：多样性由什么结构机制保证。

| 取值 | 描述 |
|---|---|
| topology（岛隔离） | FunSearch 谱系 |
| grid（胞格竞争） | MAP-Elites |
| novelty_gate（嵌入拒绝） | ShinkaEvolve 消融收益最大单项；OpenEvolve 双系统惯例阈值 0.99 |
| controlled_exchange（系统交换/温度池） | EvoDiverse：交换后多样性↑且 best 不降；PT 池间 MH 交换 |
| template_stochasticity | AlphaEvolve 随机化 prompt 模板 |

**关键证据锚点**：ShinkaEvolve Fig.9 新颖性拒绝=收益最大单项（arXiv:2509.19349）；EvoDiverse 同 prompt 消融仍 +12%/+19% Top-10 AUC（arXiv:2606.10587）；VRP 3 代塌缩（arXiv:2604.07872）；Verbalized Sampling：对齐后多样性 −76%（arXiv:2510.01171，变异供给先验上限）。
**默认值**：`topology + novelty_gate` 双保险。**裁决①**：新颖性阈值口径以 M2-O8 的 **0.95 起步 + 台账校准**为准（0.99 为两系统嵌入去重惯例，目标口径不同；框架级统一走 P19 重复率台账动态校准）。
**耦合**：×P1（拓扑即承载）；×P19（多样性探针监控是本轴的传感层）；×M2-O8（新颖性闸的执行在 M2 侧，档案侧提供嵌入索引）。

## P10 容量与驱逐策略（原 F10）

**一句话定义**：档案上限与出档规则——禁止无界只进不出为默认（F-B5）。

| 取值 | 描述 |
|---|---|
| population_limit（淘汰最差） | OpenEvolve `_enforce_population_limit`（pop=1000/archive=100） |
| elite_replace（优于最差精英才替换） | LoongFlow elite_archive_size=50 |
| cell_competition（同格竞争天然限容） | MAP-Elites 自带 |
| unbounded（永久保留） | DGM/ADAS——stepping stone 论据成立但须配 P19 浓度监控 |
| 软删除+深度缓冲 | CMA-MAE archive learning rate / UQD depth d=8/32：抑制边际替换防 stepping stone 丢失 |

**关键证据锚点**：CMA-MAE（arXiv:2205.10752）archive threshold dynamics 致早熟；Justesen 2019（GECCO）朴素基线档案质量随时间退化、矫正重评后"sometimes leaves cells empty"；AIDE `is_buggy` 硬过滤永久误杀（驱逐误杀生产级案例）。
**默认值**：`population_limit + cell_competition`；每次驱逐记录"理由+可恢复路径"，硬删除默认禁止（F-B5）。
**耦合**：×P16（跨 run 合并前须先过驱逐可证伪性）；×P20（驱逐/保留决策不得低于噪声底裁决，F-B16）；成本约束：档案大小按 token/注意力预算核算（C5 横切约束落点）。

## P11 失败候选的档案地位（原 F11）

**一句话定义**：失败个体是否入库、可否复活。

| 取值 | 描述 |
|---|---|
| discard | FunSearch：不计分即不入库 |
| artifacts_only | OpenEvolve artifacts 侧信道（存而不入主库） |
| buggy_leaf（标记保留+复活通道） | 不参选但可作 debug 亲本；保留谱系留痕 |
| 阴性聚合库（只存聚合失败模式） | IDEAgent R：不存个体而存聚合模式供生成回避 |

**关键证据锚点**：OpenEvolve artifacts 字段一手；AIDE `is_buggy` 自判误杀——LLM 自判 buggy 的节点被永久过滤出亲本池（M2-O12 / M4-3 双重记录在案）；IDEAgent 四存储设计（arXiv:2607.22375，增益【未复核】）。
**默认值**：`buggy_leaf`（标记保留，不参选、可复活）。
**耦合**：×M2-O12（debug 兜底消费失败标记）；×P18（阴性聚合是内容表示的取值之一）。

## P12 同步模型（原 F12）

**一句话定义**：档案与生成/评估流水线的同步点。

| 取值 | 描述 |
|---|---|
| async_db_sole_sync | DB 为唯一同步点、无代边界——FunSearch/AlphaEvolve/OpenEvolve 全异步 |
| generation_sync | 代际边界同步 |
| snapshot_merge | 进程快照批量合并 |

**关键证据锚点**：AlphaEvolve asyncio 流水线、DB 唯一同步点（白皮书一手）；ShinkaEvolve proposal/eval/db 三池配额；FunSearch 陈旧注册问题（prompt 生成后岛被重置）被代码注释明确提及并刻意忽略【一手】。
**默认值**：`async_db_sole_sync` + checkpoint 快照。
**耦合**：×P4（异步下迁移/重置的陈旧注册）；×P13（快照是一等配套）。

## P13 持久化与 checkpoint（原 F13）

**一句话定义**：档案状态的可恢复性——**含谱系与策略环境的可恢复**。

| 取值 | 描述 |
|---|---|
| full_db_snapshot | OpenEvolve：完整 DB+岛状态，全组件 seed=42、hash 隔离 |
| sqlite 持久化 | ShinkaEvolve：ProgramDatabase+bandit state+prompt archive |
| run_dir | GEPA：checkpoint 可恢复 + adapter state 鸭子快照 |
| redis/外存 | LoongFlow 双实现 |

**关键证据锚点**：各系统一手配置；dim06 §3.10"无 checkpoint 的进化框架无法用于生产"；M4-7：恢复档案 ≠ 恢复生成档案的策略环境（OpenEvolve 选择策略硬编码致版本漂移）。
**默认值**：`full_db_snapshot`（含岛状态+bandit 状态+策略版本）。
**耦合**：**谱系四元组 {祖先链, 变异算子与 diff, 上下文配方, 评估环境版本} 进 X1**（F-B13，缺任一字段的候选可留档不供亲）；×P17（移交集须可快照）。

## P14 归档→长期记忆衔接（原 F14，M5 边界）★接口 M5

**一句话定义**：什么从档案沉淀进 M5——**本轴只到衔接协议为止，语义沉淀归 M5**（刚性边界）。

| 取值 | 描述 |
|---|---|
| none（档案即 L1 终点） | 进化系普遍现状（阴性发现：跨代语义抽象普遍缺失） |
| meta_summary（周期摘要，L2 雏形） | ShinkaEvolve MetaSummarizer，interval=10 |
| lineage_digest | LoongFlow：plan/summary 随解绑定，planner 沿 parent_id 链回溯 |

**关键证据锚点**：ShinkaEvolve MetaSummarizer（config.py 一手，唯一 L2 雏形）；LoongFlow Listing 1；"归档什么进长期记忆仍是开放问题"（A 组阴性发现）。
**默认值**：`none` + `meta_summary` 可选（挂 M5 写入门禁）；M4 侧义务仅为"档案条目携带可供沉淀的结构化字段（plan/summary/谱系链）"。
**耦合**：**沉淀语义归 M5（刚性边界）**；×P18（语义表示是沉淀的素材层）。

## P15 退化自检基线（原 F15，裁决②：保留）

**一句话定义**：档案复杂性的奥卡姆剃刀——任何结构变更须跑赢退化投影且增量超 M8 噪声底。

| 取值 | 描述 |
|---|---|
| resident（SCS/单链表投影永驻对照） | 档案结构按单链/SCS 配置的投影常驻跑对照 |
| none | 无对照——档案复杂性不可证伪 |

**关键证据锚点**：Simple Baselines：P(Shinka>IID RS)=0.49（arXiv:2602.16805）——**档案/前沿结构的全部复杂性以评估统计可靠性为先决条件**；AIDE² 单链表达 RSI L1（博客级，方向被 DGM 消融独立佐证）。
**默认值**：`resident`。**裁决②**：保留为轴——M2-O1 的自检对象是"算子集表达力"，P15 对象是"档案结构复杂性"，奥卡姆剃刀的施加面不同，M2 同型约定不覆盖本轴。
**耦合**：×全体（评估噪声底是任何非默认取值的启用前提）；消费 M8 噪声底测量。

## P16 档案分布与合并协议（新，C1 + F-B14 + C6）★接口 X1

**一句话定义**：档案存在于单进程还是跨 run/跨主体分布；合并协议与重标定义务是什么。

| 取值 | 描述 |
|---|---|
| 单主体集中式 | 全部经典系统默认 |
| 跨 run 事后合并（共享锚点重标定） | F-B14：不同评估版本分数不可直接比较，合并前过共享锚点集，谱系边标"异源" |
| 联邦式 delta+证据门控合并 | EvolveNet：scope-typed（全局/域条件化）合并，无门控链式版本直接崩溃回滚 |
| 对抗式 champion 交换 | 分布式 Red Queen QD：跨节点 gossip 传对手而非解 |
| test-time 瞬时档案 | TTHE：档案生命周期短至一次评估，无标签代理信号准入（准入语义归 M9） |

**关键证据锚点**：EvolveNet（arXiv:2608.04968）：BIRD held-out 70.7% vs 等总预算集中式 67.3%（配对 14 胜 9 负）vs 等串行深度 68.7%；合并协议消融各自证明贡献；跨 run 合并通用协议/标准格式不存在（C 组阴性发现 1——EvolveNet 是唯一一手系统）。
**默认值**：单主体集中式；开启跨 run 合并须先满足重标定（F-B14）与驱逐可证伪（F-B5）。
**耦合**：**跨组织产权/联邦部署归框架层（刚性边界），M4 只到合并协议**；合并事件与来源 run id 进 X1；×P13（合并前的快照对齐）；×M9（合并时的逐 item 准入门）。

## P17 档案移交与估值（新，C2）★接口 M1/M3

**一句话定义**：档案（或其子集）作为跨相位、跨模型档位移交对象时如何估值与压缩。

| 取值 | 描述 |
|---|---|
| 无移交（单模型单相位） | 经典默认 |
| 固定切换 | 到点整体移交 |
| 子模目标估值+自适应 handoff | RelayEvolve：relay bank |S|≤k，top-r 质量+多样性覆盖的单调子模目标（(1−1/e) 保证），Relay Gain 反向驱动调度 |

**关键证据锚点**：RelayEvolve（arXiv:2608.05651）：4 benchmark×3 预算中 11/12 设置均值最高；一手规律"进展强前置、便宜模型前 20 代捕获强模型 0.82–1.01× 的进展"；call 级 bandit 被证明近视。
**默认值**：无移交；启用相位 handoff 时采用子模估值档。
**耦合**：**handoff 时机是搜索相位决策，归 M1 消费**；移交预算归 M3；×P13（移交集可快照）；×M2-O19（RelayEvolve 证据在 M2 侧已入算子经济学轴，本轴管档案侧的打包与估值）。

## P18 档案内容表示（新，C3，吸收 C4）

**一句话定义**：档案条目除 artifact+fitness 外还持久化什么语义层。

| 取值 | 描述 |
|---|---|
| 纯 artifact | (program, fitness) 经典形态 |
| +行为描述子 | MAP-Elites descriptor（2023 前主流，见 P6） |
| +NL 策略描述/嵌入 | SeaEvo 双空间档案（代码+策略），SLN 周期总结策略家族 |
| +失败模式聚合（阴性知识） | IDEAgent R 存储：聚合失败模式供生成回避（C4 收编点） |
| +meta-notepad 提炼 | ShinkaEvolve：从成功个体提炼高层策略附进变异 prompt |

**关键证据锚点**：SeaEvo（arXiv:2604.24372）：系统优化任务平均 +21%；Prism 上策略档案使 run 跳出平台（26–30→42.94）；IDEAgent 四存储（量化【未复核】，置信降档）。
**默认值**：纯 artifact + plan/summary 字段（LoongFlow 先例，零成本档）；NL 策略层在档案规模超检索预算时启用。
**耦合**：×P6（semantic descriptor 同根）；×P14（语义层是 M5 沉淀素材）；×M2-O5（meta-notepad 被变异器消费的通道在 M2 侧）。

## P19 档案健康探针（新，B 组根因 2 盲区补轴）★一等输出

**一句话定义**：档案健康的二阶治理指标（跨代/跨岛/跨实例）作为一等常驻输出——档案健康不可从档案内部单点观测。

| 取值 | 描述 |
|---|---|
| 无探针 | FunSearch/AlphaEvolve/OpenEvolve/ShinkaEvolve 全部现状——塌缩在 fitness 曲线上隐形 |
| 计数仪表盘 | 供给熵（亲本有效熵/基尼系数，F-B1/F-B6）、跨岛表型距离时序（F-B7）、实例判别力分布（F-B10）、重评存活率（F-B15）常驻报告 |
| 探针反馈治理 | 超阈值自动触发：迁移率下调/岛重启/供给函数切换/档案压缩/前沿降粒度 |

**关键证据锚点**：B 组根因 2：四类失效（M4-1 塌缩/M4-4 岛间趋同/M4-5 易实例主导/M4-8 噪声滞留）的共同根因是二阶指标全部缺失；ShinkaEvolve Fig.9 三缓冲器全部住档案层；GEPA ~85–90% 预算花在 per-instance 验证表维护（arXiv:2507.19457，原文明确）——无探针则精度静默吃掉选择预算。
**默认值**：计数仪表盘（最低档必配）；无健康探针的档案默认视为不可治理（与 M2-O9/O20 同构的制度件）。
**耦合**：×P3/P4/P8/P10（探针是这四轴治理动作的触发器）；消费 M8 噪声底；探针读数进 X1 谱系（跨代时序可审计）。

## P20 双资格分离（新，B 组根因 1 盲区补轴）★接口 M9

**一句话定义**：**进档资格靠分数，供亲资格与交付资格靠证据**——两套资格在数据结构层分离。

| 取值 | 描述 |
|---|---|
| 合一（分数即一切资格） | 经典默认——M4-2/M4-8 的失效配置：最假的分数坐最重的亲本席位 |
| 供亲位分离 | 被污染探针/低置信标记的候选可留档（保留信息）但剥夺供亲资格（F-B4） |
| +交付位分离 | 最终交付候选须 CI 下界高于被替代者点估计（保守晋升，F-B15）；驱逐/保留不得低于联合噪声底裁决（F-B16） |

**关键证据锚点**：RHB：RL 模型 13.9% hacking 率（arXiv:2605.02964）——档案侧感染率上限；Countdown-Code：1% 污染祖源点燃灾难性作弊（转引 arXiv:2605.21384）；Justesen 2019：档案精英经不起重评（矫正后空格）；Grillotti & Cully 2023：档案精英重测显著低于记录值。
**默认值**：供亲位分离（最低档必配）；交付位分离在存在下游部署时开启。
**耦合**：**准入侵规则归 M9（刚性边界）——本轴只管档案侧的资格位存储与执行，判定逻辑在 M9**；置信度字段 {评估次数, 分数 CI, 最后重评时间} 为一等字段；×P7（供亲位写进亲本池契约）；×F-B3 祖源级召回（污染判定后谱系枚举/降级，依赖 X1 谱系）。

---

## 总览表

| 轴 | 取值集 | 默认值 | 最强证据 | 接口依赖 |
|---|---|---|---|---|
| P1 档案拓扑 | 单池/岛/树/网格/实例矩阵/组合 | grid×islands | OpenEvolve 三系统收敛；DGM 消融 | — |
| P2 前沿定义 | best_so_far(禁默认)/胞格/per-instance Pareto/树叶/无 | pareto_per_instance（逐实例场景） | GEPA +6.4% 消融 | ×P8/P10 |
| P3 岛数 K | 2/3/5/10/动态繁殖 | K=5 | 谱系 10→5→3→2（无消融，证据空缺） | ×P19 |
| P4 岛间交换 | reset/环形迁移/动态繁殖/无 | ring(0.1, 10~50) | OpenEvolve/LoongFlow 一手配置；迁移替代重置 | ×P12/P19 |
| P5 等价类聚簇 | signature/embedding_bin/无 | none | FunSearch 源码（T0=0.1/period=30000） | ×P6 |
| P6 网格维度来源 | 评估指标/手工/语义 | evaluator_metric | OpenEvolve"低成本高价值"；LoongFlow 退化教训 | ×P18 |
| P7 亲本池字段 | 四固定字段+可选扩展 | 四字段全供给（写死） | LoongFlow Listing 1；DGM §C.2 | **写死对齐 M2-O11；供给 M1/M2** |
| P8 亲本采样结构 | 三路/簇softmax/覆盖比例/加权 | three_way+double selection | Shinka 父代消融三档排序；VRP 3 代塌缩 | **公式归 M1；M4 只暴露注入点** |
| P9 多样性物理承载 | 拓扑/网格/新颖性闸/受控交换/模板随机 | topology+novelty_gate(0.95 起步) | Shinka Fig.9 最大单项；EvoDiverse +12/+19% | ×M2-O8（阈值口径对齐）；×P19 |
| P10 容量与驱逐 | 人口上限/精英替换/胞格竞争/无界/软删除 | population_limit+cell_competition | CMA-MAE threshold dynamics；Justesen 重评空格 | ×P20（噪声底下不裁决） |
| P11 失败候选地位 | 丢弃/artifacts侧信道/buggy_leaf/阴性聚合库 | buggy_leaf | AIDE is_buggy 永久误杀 | ×M2-O12 |
| P12 同步模型 | 异步DB唯一同步/代际/快照合并 | async_db_sole_sync+快照 | FunSearch 陈旧注册先例 | ×P4/P13 |
| P13 持久化 | 全量快照/sqlite/run_dir/redis | full_db_snapshot | dim06"无 checkpoint 无法生产"；策略环境漂移 | **谱系四元组进 X1** |
| P14 M5 衔接协议 | none/meta_summary/lineage_digest | none + meta_summary 可选 | MetaSummarizer 唯一 L2 雏形；阴性发现 | **语义沉淀归 M5（刚性边界）** |
| P15 退化自检基线 | resident(SCS/单链投影)/none | resident | SB P=0.49；AIDE² 单链 RSI L1 | 消费 M8 噪声底 |
| P16 分布与合并 | 集中式/跨run重标定/联邦门控/对抗交换/test-time瞬时 | 单主体集中式 | EvolveNet 70.7 vs 67.3/68.7 | **跨组织归框架层；合并进 X1；×M9** |
| P17 移交与估值 | 无/固定切换/子模估值handoff | 无移交 | RelayEvolve 11/12 最优；0.82–1.01× 前置规律 | **时机归 M1；预算归 M3** |
| P18 内容表示 | 纯artifact/+描述子/+NL策略/+阴性聚合/+meta-notepad | artifact+plan/summary | SeaEvo +21%；跳出平台 26→42.94 | ×P6/P14；×M2-O5 |
| P19 健康探针 | 无/计数仪表盘/探针反馈治理 | 计数仪表盘（必配） | B 根因 2：四失效共同根因；GEPA 85–90% 预算暗耗 | 消费 M8；读数进 X1 |
| P20 双资格分离 | 合一/供亲位分离/+交付位分离 | 供亲位分离 | RHB 13.9%；1% 污染点燃作弊；重评空格 | **准入规则归 M9；×P7；×X1 召回** |

## 逐格深挖优先级提示

预计深挖工作量最大的三条：
1. **P19 档案健康探针**——四个二阶指标（供给熵/跨岛距离/实例判别力/重评存活率）各自缺现成度量实现，且要为每条定阈值与治理动作映射（F-B1/F-B6/F-B7/F-B10/F-B15 五公理落一处），并与 M2-O9/O20 的探针家族做术语对齐。
2. **P16 分布与合并协议**——跨 run 合并无通用协议标准（阴性发现），重标定锚点集设计要呼应 M8 系 A16，scope-typed 合并语义只有 EvolveNet 单点一手，X1"异源谱系边"是新增谱系类型。
3. **P20 双资格分离**——资格位契约要同时对齐 M9（判定）、P7（亲本池字段）、X1（祖源级召回），且 F-B16"噪声底下不裁决"要求消费 M8 的联合噪声底，三方接口待定。
