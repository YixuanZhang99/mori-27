# M1-UNIFIED-v1.md — 统一策略（亲本选择/相位/分配意图）模块设计文档

> 依据：`../research/m1/m1_axes_final.md`（18 轴定稿 G1–G18）、`../research/m1/m1_deepdive_part1/2/3.md`（逐轴深挖）、`../research/m1/m1_分歧_公理.md`（八分歧裁决 + 公理 H1–H12 + 根因对账 + 自我证成公约建议 + I-可逆第四投影验证）、`../research/m1/groupA_policy_design.md` / `groupB_policy_failures.md` / `groupC_policy_new.md`（原始调研）。结构与风格对齐 `M4-UNIFIED-v1.md` / `M2-UNIFIED-v1.md` / `M8M9-UNIFIED-v1.md`。所有数字引自上述底稿，不确定处标【推断】；AIDE² 数字一律标【厂商博客级，非同行评审，关键数字未见独立复核】。
> 定位：M1 Policy 的最终形态设计。回答一个问题——**FunSearch 的贪心+岛均匀 / ShinkaEvolve 的加权+UCB / DGM 的分数×子代幂律 / RelayEvolve 的两相位移交 / EvoX 的策略种群进化 / AIDE² 的外环爬山这些策略层设计能否被同一个实现兼容？答案：能。它们之间的差异全部是"亲本公式形态 + 相位模型 + 分配机制"的配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 ParentFormula/AllocationIntent/IntentReceipt/PhaseSignal/PolicyLineage/StopAction 数据模型与 CI-vs-噪声底门槛协议、双重注入禁令、可逆性类型层绑定记账规则（内核，不可换）+ 退化基线永驻自检与策略健康仪表盘（内核，永驻）+ 策略注入点一等接口（公式可热替换，对照可执行）+ 十八轴编译成的 profile（配置）+ 双速调度（sync 禁 LLM，运行时）**。
> 模块定位公理（B 组根因 4）：**M1 的价值不在其复杂度而在其已举证的净增量**——退化基线（IID-RS/SCS）是策略层永远的默认对照组；M1 只输出意图（亲本分布参数, 相位动作, 分配意图流），不执行、不记账、不做统计检验；默认值选择以"限制策略层单点失效（塌缩/误停/饿死/噪声过拟合）的传播半径"为准绳。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条既有框架级不变量 + 两个候选 + 一项新增框架级公约建议

> **修订注记（v1.1）**：本版按 M3 对账（`../research/m3/m3_分歧_公理.md` 契约修订建议）完成 R1/R2 契约扩展——R1（MUST）：AllocationIntent 增 `budget_unit` 必填字段（多币种 reserve 前提，§2）；R2（MUST）：IntentKind/cost_account 扩七科目封闭枚举 + control 类意图签发路径（§2，公约 (f) 执行前提）；R3（SHOULD）仅在 §9-9 登记；R4 ttl 续约冲突交叉引用 M3-UNIFIED-v1 §9-3（§9-9）。
> **修订注记（v1.2，用户裁决）**：①默认亲本公式由 weighted_sigmoid 改为 **greedy（argmax 供亲）**——工程亲和力与使用者熟悉度优先于失效防护默认值；weighted_sigmoid/three_way 降为永驻对照臂。该裁决与证据强度排序（§7 第 1 条"贪心禁止方向最强"）存在张力，补偿控制=H2 有效亲本数监控与结构多样性承载（岛隔离/新颖性闸）升级为默认档的**强制伴随**（缺失=构建期拒绝），塌缩报警率超阈为默认值回退触发器（§9-10）。②ScoreTerm 增 `none` 占位（纯新颖性搜索流派在类型层可表达，防锁死）。

以下四条不变量横跨 M5/M8/M9/M2 四模块独立出现（与 M2-UNIFIED §0.0、M4-UNIFIED §0.0 逐字一致）；第五候选 I-披露由 M2 提出；第六候选 I-可逆由 M4 提出，**M1 经根因对账完成其第四投影验证**：

1. **不变量 I-α（锚点存在性）**：框架内任何被优化压力触及的积累物必须配一个物理上不可被该压力修改的锚点组件。→ M1 侧投影：G14 非 frozen 档的策略接受判据消费 held-out 锚点集（G15 better-only+held-out 档）；G12 退化基线族（IID-RS/SCS）是策略层的常驻锚点——策略的"进步"只能在不被策略压力修改的基线上度量。
2. **不变量 I-β（质量指标一等化）**：任何裁决/积累机制必须暴露其判别质量指标；"机制动作次数"不得作为健康证据。→ M1 侧投影：**M1 策略健康仪表盘（有效亲本数跨代时序 H2、预算分配洛伦兹曲线与零预算幸存者清单 H7、探索转化率 H3、边际改进 CI 读数）是 M1 版的 gate_quality_probe**——"策略健康从未被独立测量"与 M9 闸门判别质量、M2 算子产率、M4 档案健康是同一抽象失效的**第四个投影**；M1 的增量是把 I-β 适用域闭合到**纯意图生产者**（M1 不执行、不记账，其失效甚至不在自己的日志里可见，只在下游 M3/M4 的账上显形）。另：G17"决策用分 vs 报告用分"类型层分离与 M4-E10 双资格分离同构——I-β 的质量指标必须**按用途分离**物化——物化形态贡献，不上收新原则。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：→ M1 侧投影：M1 消费 M9 枚举 Verdict 做相位动作（查表映射），不复算统计量、不旁路 mSPRT/ASHA/noise_floor_zero 判定；LLM 生成的策略代码（G14 outer_loop/population 档）须经 G15 better-only 门控+G12 对照才可部署，LLM 判断不做接受终裁。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：→ M1 侧投影：G15 策略谱系四元组 {policy_id, parent_policy_ids[], deploy_context, acceptance_evidence} 与候选谱系同库异类型入 X1；拒绝回流（IntentReceipt）与 handoff 否决回流为一等谱系事件——"没发生的意图"与"被否决的意图"是两类记录；版本变更、接受/拒绝、回滚事件全部留痕。
5. **候选不变量 I-披露（信号通道最小披露）【候选，M2 提出，待框架级确认】**：→ M1 侧投影：M1→M3 之间只允许 G13 intent_queue 唯一信道（旁路意图=构建期拒绝）；M1 消费 M4 侧仅限 ParentPool 契约字段与 P19 探针读数，不私开信道读档案内部状态。
6. **候选不变量 I-可逆（不可逆操作滞后于证据成熟度）【候选，M4 提出，M1 完成第四投影验证】**：→ **M1 侧投影（调度层，第四投影确认成立）**：相位切换=状态覆盖、停止=过程终止、饿死=预算归零（渐近不可逆）——"不可逆操作"在策略层的三个形态。一手失效证据链（与 M9 过滤/M4 驱逐替换/M2 算子治理形态各异）：hal-00519579 Adaptive Pursuit 无 pmin 压零永不恢复【原文明确】、FunSearch 重置最差半岛=饿死制度化（正确性依赖"最差岛没有未来"这一欺骗性景观上不成立的前提）、AIDE² ~90% 拒绝率下误停烧掉全部已付探索成本【厂商博客级】；生产级反悔先例：EvolveNet 回滚恒指向上一共享 harness。物化：hard 类动作合法性=G17 门槛协议输出"可裁决且支持"；不可逆性档位与证据成熟度在类型层绑定（G13 schema 的 `snapshot_ref` 强制字段）。M1 因此满足 I-可逆上收判据（跨模块投影+各自一手失效证据）的第四投影——**上收与否仍由框架定稿阶段裁决**【推断】。

> 根因对账备注：M1 根因 1（点估计 vs 统计量）→ I-β 覆盖 + 物化形态贡献（门槛前移：从裁决层 M9 前移到决策动作发生处 M1；分用途消费）；根因 2（跨期复合失效+默认值重合）→ I-β 完全覆盖（四模块同型链第四环）；根因 3（不可逆跑在延迟证据前）→ I-可逆第四投影确认；根因 4（自我证成闭环缺失）→ 上收为框架级公约（非不变量，见下）。M1 不贡献新候选不变量。

### 0.1 新增建议：框架级"自我证成公约"（非不变量，建议稿，待框架定稿裁决）【推断】

M2-C10（剃算子复杂度）/ M4-P15（剃档案结构复杂度）/ M1-G12（剃策略复杂度）是同一制度在三个模块的独立物化。三份私有表述的存在本身即漂移风险（预算份额、比对周期、显著性判据、降级触发若各自定义，跨模块对照不可比），建议统一为框架级公约：

- **统一表述**：框架内任何携带可选复杂度的模块，其每个非默认组件必须持续续证"我比关闭我更好"——(a) 退化基线族（IID-RS/SCS/单链投影）为框架级**共享组件**（同一投影组件服务三处自检），永驻对照，被移除=构建失败；(b) 举证门槛统一为"同预算对照 + 增量超 M8 噪声底（带信噪比条件句）"；(c) 环境/模型/噪声底变更后对照自动重跑，增量不显著的组件进入统一**降级流程**（简化或移除）；(d) 多组件增量强制**组件级归因**（加法消融为最低形态，交互分解为 SHOULD；无归因的聚合增量按最低组件可信度计，ShinkaEvolve 三消融为模板）；(e) 全部对照记录（谁 vs 谁、预算、噪声底、结论、降级动作）进 X1 一等谱系条目。
- **对照预算份额为 M3 保留科目**：建议显式占比 5–10%【推断，无文献定值】，由 M3 记账为保留科目，在预算表可见（防塌缩保险费，不可见则第一个被砍）。
- **显著性口径单源**：消费 M8 noise_floor/ReliabilityMeta，单一来源，禁止各模块各自维护阈值。
- **管辖边界**：对照基线族的定义与共享实现、降级流程的触发与出口、归因协议写为框架级横切规范；各模块只声明"对照对象"（算子集表达力 / 档案结构复杂性 / 策略复杂度），台账不合并记账。
- **不上收为不变量的理由**：它不改变设计空间的形状（非"什么合法"的约束），而是全部不变量与公理的**元执行制度**；上收层级是"公约/横切规范"，与 I-α～I-谱系不同层（与 M4 对根因 4 的处置同型）。

### 0.2 公理 H1–H12（失效证据 → 内核物化）

> 合并规则：S-B3+S-B4→H3；S-B7+S-B8→H6；S-B9+S-B10→H7；S-B13+S-B14→H10；S-B16+S-B17→H12。降级：**H7 的难实例加权部分为 SHOULD**（实例级预算流量直接测量缺位）、**H9 为 SHOULD**（分相位×信噪比阈值表无实现先例）。17 条候选全部保留，无降级为实现建议的条目。

| # | 公理 | 强制级别 | 失效证据指认（关键数字） | 违反检测 |
|---|---|---|---|---|
| H1 | **选择压力是一等超参；贪心供亲为默认档但强制伴随监控与结构承载**——M1 暴露"选择温度/供亲分布"为显式配置；默认档 argmax 供亲（v1.2 用户裁决：工程亲和力优先）**以 H2 有效亲本数监控 + 结构多样性承载（岛隔离 M4-P3 或新颖性闸 M2-O8）为强制伴随**，缺失=构建期拒绝；加权/分层采样为非默认公式，启用须过 G12 对照（同预算跑赢贪心默认且增量超 M8 噪声底） | MUST | ShinkaEvolve Fig.9 三档消融：hill climbing 初期最强快速 plateau、weighted 持续改进（arXiv:2509.19349）；VRP 纯 top 层供亲第 3 代窄化（arXiv:2604.07872）；EoH 评估精确域 2,000 查询胜纯采样 10,000 次（arXiv:2401.02051）——失效边界是信噪比的条件句。**反向证据：FunSearch 岛内贪心 15+ 代不退化（结构承载条件下贪心无害）** | 选择压力参数不可配置=构建期报错；贪心默认下 H2 监控或结构承载缺失=构建期报错；非默认公式无 G12 对照记录=审计不通过 |
| H2 | **选择压力跨代复合效应须被监控：有效亲本数常驻**——常驻报告供亲分布有效熵/基尼系数（与 M4-E1 供给熵/供给浓度术语对齐）跨代时序；单调收缩即触发降温或注入均匀采样份额，而非等 best 曲线 plateau | MUST | ShinkaEvolve 加权 vs hill climbing 曲线形状对照（2509.19349）；FunSearch 跨岛均匀 15+ 代不退化（Nature 2024） | 有效亲本数时序缺失=构建期报错；收缩触发后无治理动作记录=审计不通过 |
| H3 | **探索份额上限 + 机会成本记账 + 噪声条件句声明**——每代预算分配表（探索/利用/重评三账户）为一等配置与一等日志（落点=G13 意图条目 cost_account）；探索账户超阈须附"近期探索转化率"证据；任何探索/利用配比的功效声明必须带评估信噪比条件句，低信噪比设置下策略复杂度预算默认降级 | MUST | SB P(Shinka>IID RS)=0.49、重评 10 次后无差异（arXiv:2602.16805）；GEPA ~85–90% rollout 花在验证表维护（arXiv:2507.19457）；AIDE² 外环 ~90% 拒绝率【厂商博客级】 | 意图条目缺成本账户标签=M3 拒绝入账；功效声明无信噪比条件=评审退回 |
| H4 | **相位切换必须闭环，固定时刻表默认禁止**——切换判据以观测量（Relay Gain 边际改进、有效亲本数、探索转化率）为输入；固定代际/固定时刻切换为待证配置须附对照臂消融；日历量只允许作为估值信号缺位时的兜底档且须在 G12 对照下运行 | MUST | RelayEvolve Fixed-switch 对照臂全败、阶段自适应 11/12 最优（arXiv:2608.05651【按既有卡片口径，未独立核对】）；FunSearch 4h 重置无论证被 PDE-SHARP 继承（arXiv:2511.00183） | wall_clock/budget_fraction 单独作为切换触发源=配置评审拒绝；兜底档运行无 G12 对照记录=审计不通过 |
| H5 | **切换决策可回滚，handoff 带反悔路径**——相位切换与 handoff 保留前一相位种群快照与恢复原语（快照载体复用 M4-P13 双快照，M1 不建第二套）；handoff 被下游否决的候选携带否决原因回流入谱系；策略状态（bandit 统计量、相位、温度）随快照一并回滚 | MUST | EvolveNet 回滚恒指向上一共享 harness（arXiv:2608.04968）——生产级反悔路径先例；M4 侧 E5/E7 同构 | 不可逆类意图（handoff/spawn/停止类）未挂 snapshot_ref=运行期拦截（G13 类型层绑定）；回滚事件无 X1 记录=审计不通过 |
| H6 | **停止不得低于噪声底裁决 + 停止须归因且可逆**——停止决策输入为"边际改进 CI vs 噪声底"统计量而非点估计 plateau 计数；CI 下界高于噪声底时禁止以 plateau 为由停止；软停止（保留档案可续跑）为默认，硬终止须附归因报告（收敛/打转/预算耗尽/噪声底四类），plateau 归因失败默认续跑；剩余预算意图交还 M3 | MUST | Justesen 2019 噪声域档案质量随时间退化——"继续运行=继续变差"；AIDE² ~90% 拒绝率下长平台+阶跃形态（固定 K 判据系统性误停）【厂商博客级】；FunSearch cap set 突破在数千代尺度；SB 重评 10 次后无差异 | 停止事件无归因报告或无 CI 依据=审计不通过；M1 自行实现统计检验=架构评审拒绝 |
| H7 | **分配保底份额 + 饿死审计；难实例按信息量加权**——任何按回报加权的分配保留显式最小份额（岛级/实例级/谱系级 pmin），pmin 为可证配置（继承 H10 举证义务）；常驻报告预算分配洛伦兹曲线/基尼系数与"零预算幸存者清单"，长期零预算触发审计而非静默消失；难实例方向保留专项探索份额、进展信号按稀缺性放大 | MUST（保底+审计）/ **SHOULD**（难实例加权） | hal-00519579：Adaptive Pursuit 无 pmin 则算子压零后永不恢复【原文明确】；FunSearch"重置最差半岛"=饿死制度化；GEPA 难实例须动态子集补救（作者自承，arXiv:2507.19457） | 自适应分配无 pmin 字段=构建期拒绝；零预算清单连续超阈值块数无审计记录=报警；难实例席位置信度字段缺失=降级警告 |
| H8 | **选择压力随信噪比自适应，低信噪比强制降压**——M1 消费 M8 噪声底测量为一等输入；观测信噪比低于阈值时选择温度自动上调、重评预算占比自动上调（预算从"选"挪到"重评"）；"加强选择压力"从 plateau 的默认响应降级为待证响应 | MUST | SB P=0.49（低信噪比极）vs EoH 5 倍预算效率（高信噪比极）——策略价值=f(信噪比) 两极一手证据对；M8 噪声分解：预测噪声>数据噪声（arXiv:2512.21326）；Archive-Sampling 显著优于固定采样（arXiv:2302.00463）——同预算花重评优于更精细选择 | M1 决策路径无 noise_floor 输入=构建期报错；低信噪比读数下出现加压动作且无 G12 举证=运行期拦截 |
| H9 | **策略功效按相位×信噪比分解报告**——任何策略（选择公式/分配规则）的消融证据分相位、分信噪比报告；聚合增量在低信噪比相位不显著时标注适用域边界而非全局声明（降 SHOULD：分解阈值表无实现先例，报告格式先记账后定参） | **SHOULD** | SB 与 EoH 的同公理两个举证面；GEPA 85–90% 预算进验证表——无分解报告时精度静默吃掉选择预算的反面教材 | 功效声明无相位×信噪比分解且无豁免记录=降级警告 |
| H10 | **元超参继承全部举证义务 + 元决策预算按已测增量排序**——任何自适应机制引入元超参时声明敏感区间、失效模式（卡死/迟滞/方差爆炸）与对照基线，"自适应"不构成免于消融的理由；M1 元决策（选算子/选亲本/选 LLM/调探索率）按已测增量排序分配优化预算，ShinkaEvolve 实测序（新颖性拒绝 > 父代加权 > bandit 仅 slight）为默认先验，bandit 类机制在证明增量前不享预算优先权 | MUST | hal-00519579 四失效清单（AP 卡 pmin、Sliding MAB 窗口敏感、朴素 MAB 反应慢、Dynamic MAB 调阈值）+ Royal Road ECDF 重叠；ShinkaEvolve 消融序（2509.19349）——bandit 档是证据-声誉倒挂最严重的一档 | 自适应组件无敏感区间声明=评审拒绝；元决策预算分配与已测增量序倒挂且无豁免=审计不通过 |
| H11 | **退化基线是策略层一等公民 + 策略可热替换**——M1 任何策略配置上线须附与至少一个退化基线（IID-RS/SCS 级）的同预算对照，对照带信噪比条件句声明（H3）；SCS/均匀采样投影永驻对照，定期比对；策略不可热替换的架构视为不合规——对照不可执行的架构即不合规架构 | MUST | SB IID-RS/SCS 三域打平复杂系统（arXiv:2602.16805）；hal-00519579"自适应难稳赢朴素"负结果传统；OpenEvolve 策略硬编码"换策略需改源码"——自检缺失被架构固化的反例（呼应 M4-E2） | 策略切换需改 M1 之外代码=架构评审拒绝；永驻对照臂被移除=构建失败（与 M2-C10/M4-P15 同型） |
| H12 | **周期性重验与自动降级 + 组件级归因强制**——环境版本/模型/噪声底任一变更后退化对照自动重跑；增量不显著的组件进入降级流程（简化或移除）；多组件策略的增量声明分解到组件粒度，无归因的聚合增量在裁决中按最低组件可信度计 | MUST | ShinkaEvolve 三消融（2509.19349）为稀有的组件级归因正面案例；SB 是一次性实验设计——"常驻进程"版为制度补全 | 环境变更事件后对照未重跑且无豁免=审计不通过；多组件增量声明无分解=按最低组件可信度计并报警 |

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（双速调度 sync 禁 LLM / 意图通道协议 / 退化对照调度）│
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  操作面接口：parent_sample / pressure_control /              │
│          island_select / allocate / phase_switch / inject /          │
│          stop / learn_govern                                         │
│          每操作面三类实现：确定性 | LLM 辅助 | 自适应                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：greedy 默认公式（强制伴随 H2 监控+结构承载，v1.2）
│          + weighted_sigmoid/three_way 永驻对照臂（可热替换）           │
│          + 闭环恒温器与双重注入禁令（单通道仲裁+deadband）             │
│          + 岛选择采样内 uniform + 跨期 bandit（pmin 类型层+窗口清洗）  │
│          + CI-vs-噪声底门槛协议（G17）+ 不可裁决一等输出               │
│          + 动作可逆性（快照复用 M4-P13）+ 退化基线自检（G12 永驻）     │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：ParentFormula / AllocationIntent /            │
│          IntentReceipt / PhaseSignal / PolicyLineage / StopAction    │
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（门槛协议/禁令/可逆性绑定 self_mutable=false）
         ↑ Layer 3 标注 evolvability: strategies_only（公式/分配机制可热替换，H11）
         ↑ 经典系统 = profile = Layer 3 策略选择 + Layer 4 配置
```

**M1 的模块分工**（轴系原则 5，刚性边界）：M1 管"搜索压力与预算方向的意图生产"（亲本分布参数、相位动作、分配意图流）；**预算记账/配额执行归 M3**（G13 intent_queue 是 M1→M3 唯一通道）；**算子选择归 M2-O2**（M1 定"在哪个子种群施加哪个方向的压力"，不定用哪个变异算子）；**准入/收敛裁决归 M9**（M1 只消费 Verdict 枚举与门信号，不实现统计检验）；**档案结构与字段归 M4**（M1 只消费 ParentPool 契约字段与 P19 探针读数；handoff 打包归 M4-P17，时机归 M1）；**语义沉淀归 M5；谱系存证归 X1**。跨界处只留接口不留轴。

---

## 2. Layer 1：冻结数据模型

六个新类型。与既有类型的挂接：ParentFormula 消费 M4-ParentPool 五字段契约（写死对齐 M2-O11）；AllocationIntent/IntentReceipt 是 M1→M3 唯一通道的条目/回流类型；PhaseSignal 消费 M4-P17 Relay Gain 与 M9 Verdict；PolicyLineage 与候选谱系同库异类型入 X1；StopAction 消费 M8 ReliabilityMeta 与 M9 Verdict 枚举。

```python
# core/policy/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

ScoreTerm = Literal["sigmoid", "exp_tau", "rank_power", "coverage_count", "none"]  # f：分数项参数化；
#   none=纯新颖性搜索占位（v1.2 补充：该流派在类型层可表达，防锁死；greedy=True 时 f 不参与决策）
CrowdingTerm = Literal["penalty_inverse", "bonus_linear", "soft_weight", "none"]  # g：拥挤项（G2）
# crowding_sign 无独立默认值——schema 层强制由 M4-P10 archive_eviction_policy 派生（硬编码派生表）：
#   eviction_policy ∈ {capacity+ci_evict(淘汰制)} → penalty_inverse
#   eviction_policy ∈ {tree_permanent(永久制)}     → bonus_linear
#   eviction_policy ∈ {structural_only(FunSearch 形态)} → none 合法
# 手工覆盖须附 G12 对照证据；M4-P10 驱逐策略变更事件 → G2 重配置事件，二者同入 X1（分歧 2）

# ---- 亲本公式（G1/G2/G4：M1 契约中心件 = f×g 二元接口 + 两路实例化）----
@dataclass
class ParentFormula:
    formula_id: str
    version: str                             # 公式版本，采样事件快照入 X1（跨 run 选择压力可比）
    score_term: ScoreTerm = "sigmoid"        # 非默认公式的首选替代：σ(λ·(F−median(F)))，λ=10.0 先例值；
                                             #   默认档为 greedy=True（argmax 供亲，v1.2 用户裁决）
    score_params: dict = field(default_factory=lambda: {"lam": 10.0, "ref": "median"})
    crowding_term: CrowdingTerm = "penalty_inverse"   # 由 archive_eviction_policy 派生，见上
    role: Literal["parent", "inspiration"] = "parent" # ★ G4 split：两路各自实例化、参数成对声明
    # 约束：role=inspiration 路偏 explore+topK（elite/top-k/archive+crowding 混合）；
    # 两路若消费同一拥挤项字段，符号配置须一致声明（防静默抵消）
    greedy: bool = True                      # ★ v1.2 用户裁决：默认档=贪心供亲（工程亲和力优先）。
                                             #   强制伴随（缺失=构建期拒绝）：H2 有效亲本数监控
                                             #   + 结构多样性承载（岛隔离/新颖性闸）；
                                             #   greedy=False（weighted_sigmoid/three_way）为非默认公式，
                                             #   启用须过 G12 对照（跑赢贪心默认且增量超噪声底）

# ---- 分配意图（G13 ★M1→M3 唯一通道；schema 四关键字段硬编码）----
IntentKind = Literal["explore", "exploit", "reeval", "handoff", "spawn_island",
                     "control", "repair", "overhead"]  # 封闭枚举
# 【v1.1 修订·R2】IntentKind 与 cost_account 同步扩为七科目封闭枚举（对齐 M3-N7 决策因果链投影）；
# control 类意图（退化基线重跑/组件消融臂/锚点重评）签发路径：由 G12 永驻对照调度（§5 idle 槽
# degenerate_baseline）与 H12 周期重验（scheduled 槽 periodic_revalidation）签发，kind=control、
# cost_account=control，是公约 (f) 对照预算保留科目的执行前提；repair/overhead 类意图由 M2-O12
# debug 兜底与固定开销摊销路径触发，M1 不主动签发仅透传归科标签

@dataclass
class AllocationIntent:
    intent_id: str
    block_id: str                            # 块级粒度标识（×G6，h 代一块，h~10 代量级【推断】）
    kind: IntentKind
    target: str                              # island_id / trajectory_id / phase
    budget_estimate: float                   # 成本可归因标签（C6 横切落点）
    budget_unit: str = "token"               # 【v1.1 修订·R1】预算币种必填字段（unit ∈
                                             #   {token, usd, eval_count, node, wallclock}，M3-N1 五单位
                                             #   枚举）——reserve 分币种预扣的执行前提；单币种 run 由
                                             #   M3 配置层填充默认值保持向后兼容
    cost_account: str                        # 归属账户：七科目封闭枚举 explore/exploit/reeval/control/
                                             #   handoff/repair/overhead（H3 三账户物化点，v1.1·R2 扩七科目）
    priority: float                          # 队列内排序；M3 可按预算重排
    rationale: str                           # 触发信号摘要（如 "relay_gain_saturated"）
    expected_gain: Optional[tuple[float, float]] = None  # ★关键字段②：(点估计, ci95)；可空，
                                             #   非空强制 CI 形态（对齐 M8 B7"无 CI 不报数"）
    policy_version: str = ""                 # ★关键字段③：必填，签发策略版本（×G14/G15 归因；
                                             #   EvoX J 信号按版本切片的唯一数据源）
    ttl_blocks: int = 1                      # ★关键字段①：意图是易腐品，旧意图自动失效
    snapshot_ref: str = ""                   # ★关键字段④：不可逆类意图（handoff/spawn_island/
                                             #   停止类相位动作）强制挂快照（I-可逆类型层绑定，H5）
    # 设计要点：可拒绝性（rejectability）是本轴相对 ratio_table 的本质升级——
    # ratio_table 无条目粒度，M3 只能整体接受或违约，拒绝回流在类型层不存在

@dataclass
class IntentReceipt:                         # M3→M1 回流（拒绝回路，一等谱系事件）
    intent_id: str
    verdict: Literal["accepted", "rejected_budget", "rejected_quota", "deferred"]
    reason: str                              # 拒绝原因（回流 M1 与 X1：{intent_id, 拒绝原因, 预算余量}）
    executed_cost: float = 0.0
    # G14 版本变更时在途意图须显式处置（失效/重估/继承），否则策略谱系无法归因

# ---- 相位信号（G9/G10：判据层级——状态主判据+日历兜底+Verdict 恒叠加）----
@dataclass
class PhaseSignal:
    phase_model: Literal["single_phase", "two_phase_relay", "three_phase", "cyclic_restart"]
    relay_gain_ci: Optional[tuple[float, float]] = None   # Relay Gain 边际改进 (点估计, ci95)，
                                             # 消费 M4-P17 relay bank 估值曲线；缺位→退化 budget_fraction
    budget_fraction_spent: float = 0.0       # 兜底判据读数（H4：日历量只允许作估值缺位的降级形态）
    verdict: Optional[Any] = None            # ★恒叠加层：M9 VerdictKind（CONVERGED/FUNDAMENTAL_LIMIT_* 等）
                                             #   + Scope；M1 只消费 kind+scope 两字段，不复算统计量
    noise_floor: float = 0.0                 # M8 联合噪声底（门槛协议比较常数，按相位×信噪比分解）
    adjudicable: Optional[bool] = None       # ★不可裁决为一等输出：CI 跨度覆盖噪声底 → None
    # 判据层级硬编码：wall_clock 单独作为触发源不在合法取值集；
    # 切换动作强制挂 snapshot_ref（类型层绑定 G18）

# ---- 策略谱系（G15：通用四元组 = EvoX (S,J,ϕ)/AIDE² 版本链/EvolveNet 门控的最小公共上界）----
@dataclass
class PolicyLineage:
    policy_id: str                           # 策略本体引用（← EvoX S）
    parent_policy_ids: list[str] = field(default_factory=list)  # 版本链（← AIDE² AIDE0→47→85）
    deploy_context: dict = field(default_factory=dict)   # 部署时种群描述子 ϕ(𝒟_t)
    acceptance_evidence: dict = field(default_factory=dict)
    # {acceptance_rule: better_only|gate, held_out_ci: (est, ci95),  # J 信号强制 CI 口径（×G17）
    #  rollback_target: last_shared_stable}   # 回滚恒指向上一共享稳定版而非历史最优（反 winner's curse）
    # 与候选谱系同库异类型入 X1；接受用 J（带 CI），回滚用"共享时长×最近重评存活"——双排序键不可合并

# ---- 停止动作查表（G10：枚举→动作查表，M1 不复算统计量）----
STOP_ACTION_TABLE = {                        # M9 Verdict.kind × scope → M1 相位动作（硬编码映射）
    ("CONVERGED", "global"):   "soft_stop_finalize",   # 冻结探索分量，剩余预算意图重标记为 reeval 交还 M3
    ("NEED_MORE_WORK", "*"):   "continue_log_stagnation",  # 不做相位动作，记入停滞统计（喂 G9/G11）
    ("FUNDAMENTAL_LIMIT_MODEL", "*"):  "stop_lineage_reallocate",  # 该谱系/岛族系意图清零走 G7 重分配；
                                             #   禁止原方向重试；模型档切换为唯一合法例外
    ("FUNDAMENTAL_LIMIT_ARCHITECTURE", "global"): "soft_stop_with_attribution",  # 全 run 软停+归因报告
    ("FUNDAMENTAL_LIMIT_ARCHITECTURE", "home|cell"): "stop_subtree",
}
@dataclass
class StopAction:
    action: str                              # 上表取值；软停为默认
    attribution: Optional[Literal["converged", "spinning", "budget", "noise_floor"]] = None
    # ★ 硬终止强制归因报告四类；plateau 归因失败默认续跑（H6）
    marginal_gain_ci: Optional[tuple[float, float]] = None  # 决策用分：CI 形态（非点估计 plateau 计数）
    budget_return_intent: bool = False       # 软停后剩余预算意图交还 M3（不截留）
    snapshot_ref: str = ""                   # 不可逆档位挂快照（×G18）
    # 刚性边界：检测归 M9/M8；M1 只消费 Verdict+ReliabilityMeta，不实现/复算/旁路统计检验
```

**设计决定说明**：
- `ParentFormula` 的 `crowding_term` 派生表是**全 18 轴唯一条件句默认值**的类型层物化：children_count 的语义由档案承诺决定（淘汰制=已榨取度取负、永久制=已验证度取正），派生表硬编码并随 M4-P10 联动——换驱逐策略不换 g 符号=在公式层伪造档案层不成立的语义。该联动规则是双系统对照+机制外推的归纳【推断，本模块推论负载最重的一条】，列 G12 首验最高优先级。
- `AllocationIntent` 的四关键字段（ttl/expected_gain CI/policy_version/snapshot_ref）把 G13/G17/G14/G18 四个轴的纪律前移到意图生成处；**可拒绝性是本质升级**——没有拒绝回流的分配接口等价于假设 M1 永远不犯错（AIDE² ~90% 外环拒绝率【厂商博客级】证明打回回路必须存在）。
- `PhaseSignal.adjudicable=None` 与 `StopAction.marginal_gain_ci` 是 G17"决策用分 vs 报告用分"类型层分离的落点：报告用分（点估计，进日志）与决策用分（CI 形态，进门槛协议）在类型层分离，禁止用报告分做决策——与 M4-P20 双资格分离同构【推断】。
- `PolicyLineage` 四元组抽象显式暴露三家各自的空缺：EvoX 缺回滚原语、AIDE² 缺部署上下文标注、EvolveNet 缺进步率信号——全契约是框架的设计空位【推断】；术语（scope 分类/门控/回滚）从 M4-P16/MergeEvidence 直接复用。
- `STOP_ACTION_TABLE` 硬编码保证 M1 侧消费协议是"枚举→动作"查表而非"统计量→判断"推理——FUNDAMENTAL_LIMIT 当 NEED_MORE_WORK 消费（再烧一块试试）是本轴的静默失效形态，类型层不可表达。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 亲本公式：greedy 默认（强制伴随监控）+ weighted_sigmoid/three_way 对照臂（G1/G2，分歧 1/2 落地，v1.2 修订）

- **默认 `greedy`（argmax 供亲）**【v1.2 用户裁决：工程亲和力与使用者熟悉度优先，推翻此前"贪心=待证配置"的裁决】。**该默认的全部安全性来自三个强制伴随**（缺失=构建期拒绝）：①H2 有效亲本数跨代监控在线；②结构多样性承载在位（岛隔离 M4-P3 或新颖性闸 M2-O8——FunSearch 岛内贪心 15+ 代不退化证明：结构承载条件下贪心无害）；③塌缩报警路径可用（有效亲本数收缩→报警→人工或自动升温）。证据张力诚实登记于 §9-10：无结构承载的纯贪心 3 代塌缩（VRP）与 plateau 伪装（ShinkaEvolve hill climbing）是一手失效，默认档的本质是"贪心语义+监控护栏"。
- **非默认公式**：`weighted_sigmoid`（σ(λ·(F−median(F)))·h(children)，λ=10.0 先例值）为首选替代档与**永驻对照臂**；`three_way`（0.7/0.2）保留为兼容投影档（最大存量约定，明确标注未消融）；逐实例评估场景用 `coverage_proportional`（f 输入非分数信号的合法逃逸口）；`none`（纯新颖性搜索）为占位取值。非默认公式启用须过 G12 对照（同预算跑赢贪心默认且增量超 M8 噪声底）。
- **乘积骨架是契约中心件**：四系统独立收敛 `p_i ∝ f(score−ref)·g(children, rarity)`——M1 声明 f×g 二元接口而非单一公式（greedy 档=f 退化为 argmax 的特例形态，接口不变）；ref 取法（median/max）是 f 内部第三决策点【推断】。一阶差异是"贪心 vs 非贪心"与信噪比，f 参数化是二阶。
- **G2 符号联动硬编码**：`crowding_sign` 由 M4-P10 `archive_eviction_policy` 派生（派生表写死，见 Layer 1）；错配（淘汰制配正号/永久制配负号）为失效配置；`none` 档合法仅当 G3=structural 或作对照臂。
- **公式可热替换为一等架构要求**（H11）：OpenEvolve 把策略硬编码进 ProgramDatabase（"换策略需改源码"）为反例——对照不可执行的架构即不合规架构。亲本采样事件携带公式版本+参数快照进 X1；非默认公式启用以 G12 对照（跑赢贪心默认与 IID-RS/SCS 且增量超 M8 噪声底）为前提。

### 3.2 探索/利用闭环恒温器 + 双重注入禁令（G3×G11，分歧 3 落地）

- **默认 `closed_loop_thermostat`**（LoongFlow τ=τ_base(1+αe^{−βH}) 形态；α/β 常数仅单系统先例、跨域稳健性未验证【推断】，按"先记账后定参"处理）；**探针缺位强制降级 `fixed_ratio` + G12 对照常开**；`structural`（岛隔离承载）为叠加层而非替代档（归 M4-P3/P4 配置）。闭环的深层价值不在更准而在**失效时可归因**——闭环失败留下"信号→响应"记录，开环失败只留下 plateau。
- **双重注入禁令硬编码**（轴系裁决②）：G3 连续旋钮与 G11 离散注入共用 M4-P19 熵/停滞信号源——**同一信号在一个决策周期内只驱动一个通道**：连续通道（调 τ）先行（成本低、可逆），τ 到上限仍无改善才移交离散通道（spawn/危机档，须走 G18 快照）；两通道触发阈值显式分离留 **deadband**；τ 单写者归 G3（G11 只发"危机档"声明）。按近期回报调配比的朴素闭环不在合法取值集（系统性偏向利用侧，S-2）。
- 信号分工（×G9）：同一停滞信号由 G17 信噪比档位裁决走哪个通道——高信噪比停滞→G9 相位动作；低信噪比停滞→G11 注入（低信噪比下"停滞"可能是噪声伪影，切相位是不可逆的过重响应）【推断】。
- 供给端上限封顶本轴效能：对齐后生成多样性 −76%（arXiv:2510.01171）——升温无响应时诊断路径指向 M2 供给端而非继续加压。

### 3.3 岛选择：采样内 uniform + 跨期 bandit（G5×G7，分歧 6 落地）

- **采样内先验=`uniform`**（与"贪心禁止"绑得最死的一档：FunSearch 15+ 代不退化、ShinkaEvolve <150 评估极致样本效率仍坚持岛均匀）：岛级均匀把选择压力限制在岛内，全局 greedy 被结构性禁止，塌缩半径限在单岛；**proportional/weighted 在采样内层无一例成功先例，仅作对照臂**。有效性依赖岛真实隔离（随机分桶时全取值等价，×M4-P3）。
- **跨期分配=块级 bandit**：单轨迹 `fixed`；多轨迹默认 `grow_deepen_bandit`（recent-window UCB，Grow=开新轨迹 meta-arm、Deepen(i)=轨迹延块，奖励=Relay Gain），**三个组成件不可分割**：①块级粒度（×G6，call 级近视失效为禁例——RelayEvolve"逐 call 路由是错的问题"）；②**pmin 保底份额进类型层**（含 pmin 与不含是两个取值，后者为失效配置——hal-00519579：AP 无 pmin 压零永不恢复【原文明确】）；③**统计窗口清洗规则**（RelayEvolve 一手教训：初始 Grow 收益受入档顺序污染须剔除统计；冷启动期、相位切换点两侧分布不连续同须处理）。
- **先结构后自适应**：bandit 类机制在证明增量前不享预算优先权（H10，ShinkaEvolve 实测序：新颖性拒绝 > 父代加权 > bandit 仅 slight 为默认先验）；非 fixed 取值启用前须跑赢 fixed 均匀投影且增量超噪声底（×G12）。arm 级回报统计与清洗规则版本入 X1；AdaEvolve 全局归一化 r=(f′−f*)/f*_global 消"差岛偏好"为 weighted_recent_gain 档的必要修正。
- **粒度-机制-输出三位一体**：G6 块级 × G7 块级 bandit × G13 块级意图流刚性同粒度——per_block 决策配 ratio_table 输出=自适应被静态表抹平；per_call 意图流=M3 被淹没且路由器学噪声。

### 3.4 相位切换判据层级（G8/G9，分歧 4/5 落地）

- **相位模型**：多模型档默认 `two_phase_relay`（便宜探索→强模型精化；强模型预算占比 0.85 为先例起点、非通用常数；便宜模型前 20 代捕获强模型 0.82–1.01× 进展）；单模型档默认 `single_phase + closed_loop`（连续调节不硬切成离散段）；`three_phase` 注册为预算紧+显式收尾义务场景取值（POCAII 为 HPO 域证据，迁移性【推断】）；`cyclic_restart` 不作生产取值（仅 G11/G12 组成件）。相位的收益来自**档位分化**而非时间本身；相位数 N 无消融，2 段默认地位靠成本结构反推。
- **切换判据层级**：默认 `marginal_gain_saturated` 为主判据（Relay Gain 持续低=当前相位能贡献的候选类型已被档案吸干——档案边际收益曲线先于成本曲线宣告相位终结）+ `budget_fraction` 兜底（日历量只允许作估值信号缺位时的降级形态，且须在 G12 对照下运行）+ **`verdict_driven` 恒叠加层**（M9 Verdict 到，相位动作必须响应：CONVERGED→收尾；FUNDAMENTAL_LIMIT_*→换方向而非再试）。`stagnation_meta` 管"何时重开"与主判据叠加，但同一停滞信号不得同拍触发切换与注入（×G11）。**wall_clock 单独作为触发源不在合法取值集**（FunSearch 4h 被 PDE-SHARP 生态原样继承是失效超参扩散标本）。
- **跨模块共管**：P17 缺位时退化 budget_fraction 兜底——切换判据的上限被档案模块估值能力封顶；Relay Gain 饱和阈值无通用常数（方向性结论，各系统自校准）；切换输入须为"边际改进 CI vs 噪声底"统计量（×G17）；切换动作强制挂 G18 快照（类型层绑定）。

### 3.5 CI-vs-噪声底门槛协议与不可裁决一等输出（G17 ★横切门槛，B 组根因 1 落点）

- **默认 `ci_gated`（最低档必配）**：四类决策的动作门槛=`ci95_lower(Δscore) vs noise_floor` 比较（消费 M8 `ReliabilityMeta{n_trials, ci95, icc, noise_floor}`，与 M9 规则 5 `noise_floor_zero` 共享同一字段，禁止各自维护）：
  | 决策 | ci_gated 形态 | 不可裁决时默认动作 |
  |---|---|---|
  | 加强选择压力（G1/G3） | 近期边际改进 CI 下界>noise_floor 且有效亲本数未收缩才允许加压；"加强选择"从默认响应降级为待证响应 | 维持现温+申请重评头部候选 |
  | 相位切换（G9） | Relay Gain CI 上界<noise_floor（饱和判据）才触发 handoff | 不切+继续当前相位+预算意图转重评账户 |
  | 停止（G10） | CI 下界>噪声底时禁止以 plateau 为由停止 | 归因失败默认续跑 |
  | 分配倾斜（G7） | arm 间差异 CI 下界>噪声底才允许份额倾斜超 pmin 范围 | 均匀分配+pmin 保底 |
- **"不可裁决"是一等输出而非失败态**：SB P=0.49 的正确消费方式是"报告当前配置下策略不可裁决"——该输出触发**预算向重评转移**（snr_adaptive 档动作②：预算从"选"挪到"重评"，Archive-Sampling 优于固定采样 arXiv:2302.00463 为机制层直接证据）或评估集扩容请求（向 M8/M3 上报），形成负反馈：信噪比越低，策略越安静，预算越流向信噪比本身。
- **`+snr_adaptive_pressure` 档**：观测信噪比低→①选择温度自动上调②重评预算占比自动上调③策略功效按相位×信噪比分解报告（H9）；前置=ci_gated 运行且分解读数积累校准后启用；自适应响应本身继承 H10 举证义务。噪声底按相位×信噪比分解维护（噪声底随相位移动，全局单一噪声底在利用相位系统性低估噪声【推断】）。
- **决策用分/报告用分类型层分离**：报告用分可为点估计（进日志），决策用分必须 CI 形态（进门槛协议）——把 G17 门槛前移到决策动作发生处而非事后审计处（与 M4-P20 双资格分离同构【推断】）。

### 3.6 策略动作可逆性（G18，I-可逆调度层投影）

- **默认 `snapshot_rollback + soft_stop`**；存在自适应分配（G7 非 fixed）时强制叠加 `starvation_floor`。
- **快照复用 M4-P13 双快照**（档案+策略环境 full_db_snapshot；M1 不建第二套）：策略侧增量只有两项——①不可逆类意图挂 `snapshot_ref`（类型层绑定）；②**策略状态（bandit 统计量、相位、温度）随快照一并回滚**——但注意窗口清洗纪律：回滚后 bandit 统计量**不复位为空白**，而是随快照恢复到切换点状态（RelayEvolve 入档顺序污染教训：回滚后的分配若建立在被污染/错配的历史上即重建失效【推断，本轴最易踩的实现陷阱】）。
- **hard 类动作合法性=G17 门槛协议输出"可裁决且支持"**；不可裁决时动作自动降级为软形态（软停止/快照+延迟/pmin 保底）——不可逆性档位与证据成熟度类型层绑定。
- **软停止归因**：硬终止须附归因报告（收敛/打转/预算耗尽/噪声底四类），plateau 归因失败默认续跑；剩余预算意图交还 M3（"早停省下的预算去哪"有唯一记账答案）。
- **starvation_floor**：pmin 为岛级/实例级/谱系级可证配置（继承 H10 举证义务——pmin 是难超参，高则浪费低则虚设，无标定数据，先记账后定参）；零预算幸存者清单常驻审计，长期零预算触发审计而非静默消失（被饿死者不产生任何日志信号）；保底份额是"防塌缩保险费"，为 M3 一等预算科目须在预算表可见。
- 回滚目标="上一共享稳定版"而非"历史最优"（反 winner's curse，与 G15 双排序键联动）。

### 3.7 退化自检永驻对照（G12 ★横切激活器，自我证成公约 M1 侧物化）

- **默认 `resident_probe + periodic_revalidation`**：SCS/均匀采样投影**永驻对照**（被移除=构建失败，与 M2-C10/M4-P15 同型；基线族共享实现、台账不合并记账）；非默认取值启用前须跑赢 IID-RS/SCS 且增量超 M8 噪声底（`pre_activation` 为最低合规线）；环境/模型/噪声底任一变更后对照自动重跑；增量不显著的组件进入降级流程（简化或移除）；多组件增量强制组件级归因（ShinkaEvolve 三消融为模板），无归因的聚合增量按最低组件可信度计。
- **激活器语义**：G1–G11、G13–G18 的任何非默认取值以本轴对照为启用前提——G12 是轴系的免疫系统：缺自检的系统丧失的是发现其他全部失效的能力（none 档=不合规架构，OpenEvolve 策略硬编码为反例）。
- **预算份额**：永驻对照预算为 M1 意图流中的保留科目（建议显式占比 5–10%【推断，无文献定值】，M3 记账）；对照结果（谁 vs 谁、预算、噪声底、结论、降级动作）进 X1 一等谱系条目。
- G12 的独特增量（vs M2-C10/M4-P15）：策略层的对照对象含**元决策层**（bandit/自适应机制本身也须过对照——S-7"自适应换超参"失效只有组件级归因能戳穿）。
- 三方同构公约（M2-C10/M4-P15/G12 统一为框架级规范）见 §0.1——目前是建议稿待办【推断】。

---

## 4. Layer 3：操作面×实现类矩阵

八操作面（M1 的全部对外能力面）× 三实现类：

| 操作面 | 确定性实现（默认与兜底） | LLM 辅助实现 | 自适应实现（opt-in） | 默认实现类 |
|---|---|---|---|---|
| parent_sample（亲本采样） | greedy argmax（默认，强制伴随 H2 监控+结构承载）；weighted_sigmoid×派生拥挤项与 three_way 为对照臂；G4 split 两路各采 | —（LLM 不参与亲本打分，M2-C9 镜像） | 探针驱动公式切换（默认关，须过 G12） | 确定性 |
| pressure_control（压力调节） | 闭环恒温器 τ=τ_base(1+αe^{−βH})；探针缺位降级 fixed_ratio | — | snr_adaptive 信噪比自适应调压（校准后启用） | 确定性（闭环） |
| island_select（岛选择） | 采样内 uniform（两级采样：先岛后个） | — | 跨期 grow_deepen_bandit（pmin+窗口清洗不可分割） | 确定性 + 自适应（跨期） |
| allocate（跨期分配） | fixed 均匀（单轨迹默认；多轨迹对照臂） | — | recent-window UCB（块级；启用前提=跑赢 fixed 投影超噪声底） | 确定性默认；自适应待证 |
| phase_switch（相位切换） | Relay Gain 饱和主判据+budget 兜底+Verdict 恒叠加查表 | — | —（切换判据自适应学习无先例） | 确定性 |
| inject（多样性注入） | stagnation_spawn（停滞→新岛，archive_random 播种默认【推断】）+diversity_floor 危机档声明 | 新方向种子生成（spawn 内容侧，idle 槽） | — | 确定性触发 + LLM 内容 |
| stop（停止消费） | STOP_ACTION_TABLE 查表（Verdict×scope→动作）；marginal_utility 软停 | 归因报告撰写辅助（不判定） | — | 确定性 |
| learn_govern（策略学习与治理） | frozen 默认；G15 谱系库记录/better-only 接受/回滚到上一共享稳定版 | outer_loop_evolved/population_evolved 的策略代码生成与变异（离线/meta 层专用） | bandit_online（选 LLM/选算子统计量；继承 H10 举证义务，不享预算优先） | 确定性（frozen）+ 离线 LLM 进化 |

**策略可学习性五档**（G14，`policy_learnability` 配置）：`frozen`（运行期默认，参数只按调度表/闭环规则变化——默认值的真正理由不是保守是**可归因性**：运行期自变使 G12 对照的归因对象不恒定）/ `bandit_online`（在线调统计量不改策略表示，证据-声誉倒挂最严重档）/ `outer_loop_evolved`（AIDE² 形态：better-only 爬山，100 步 8 天【厂商博客级】，离线/meta 层专用）/ `population_evolved`（EvoX 形态：策略种群 LLM 进化+谱系库，前置=G15 全档+G12 对照+C5 迁移证据报告，缺 CI 按 M8 B7 计零）/ `rl_trained`（**边界占位端点**：类型槽现在留出避免 OpenEvolve 式锁死未来，槽内默认填 frozen；启用入口当前不存在——RL 训练 M1 策略本身零一手命中，2027 空位）。**硬编码约束：G14≠frozen 时 G15 谱系库未就位=构建期拒绝**（非 frozen 强制 PolicyLineage）；策略版本变更进 X1；版本变更时在途意图显式处置（失效/重估/继承）；AIDE² 引用强制三重降档标注（厂商博客出处+非同行评审+关键数字未见独立复核），幅度数字不作设计参数依据。

**硬编码约束汇总**：parent_sample/phase_switch/stop 无 LLM 终裁路径（I-LLM）；双重注入单通道仲裁器；wall_clock 禁独用；不可逆类意图未挂 snapshot_ref=运行期拦截；自适应分配无 pmin 字段=构建期拒绝；策略切换需改 M1 之外代码=架构评审拒绝。

---

## 5. Layer 4：双速调度 YAML

```yaml
# policy/schedule.yaml
schedules:
  sync:                        # 关键路径，每次采样/切换/停止决策前后；硬约束：禁 LLM（对齐 M5 A4/M2/M4 Layer 4）
    - op: parent_sample        # G1 公式采样 + G5 岛均匀先验；parent_eligible=false 候选类型层不可见（消费 M4）
      constraint: no_llm
    - op: threshold_gate       # G17 门槛协议：ci95_lower(Δ) vs noise_floor；不可裁决为一等输出
    - op: double_inject_arbiter# 双重注入禁令：单信号单通道仲裁 + deadband（τ 单写者归 G3）
    - op: intent_emit          # G13 意图入队（四关键字段校验：ttl/expected_gain CI/policy_version/snapshot_ref）
    - op: receipt_consume      # IntentReceipt 拒绝回流消费（M3→M1，回流进 X1）
  idle:                        # 默认档：块边界/空闲窗
    - op: block_allocation     # G7 块级 bandit 更新（窗口清洗规则版本快照入 X1）
    - op: health_dashboard     # H2/H3/H7 策略健康仪表盘：有效亲本数/探索转化率/预算洛伦兹曲线+零预算清单
    - op: degenerate_baseline  # G12：IID-RS/SCS 永驻对照（不可移除；与 M2/M4 共享实现不合并记账）
    - op: starvation_audit     # 零预算幸存者清单周期性审计输出（一等 X1 事件）
  scheduled:                   # 可选：长程维护
    - op: periodic_revalidation# H12：环境/模型/噪声底变更后对照自动重跑 + 降级流程执行
      cron: "on_env_change"
    - op: policy_governance    # G15：策略版本接受/拒绝/回滚事件处理；held-out 判据消费 M8（≥300 有效题口径）
    - op: inject_llm_seed      # G11 spawn 的 LLM 种子生成（LLM 调用只许在此槽）

parent_formula:                # 分歧 1/2（v1.2 修订）
  scheme: greedy               # v1.2 用户裁决：默认=argmax 供亲（工程亲和力优先）
  required_companions: [h2_monitoring, structural_diversity]  # 强制伴随，缺失=构建期拒绝
  resident_baselines: [weighted_sigmoid, three_way]  # 永驻对照臂（λ=10.0 先例值 / 0.7/0.2 未消融标注）
  crowding_term: derived_from_m4_p10  # 派生表硬编码：淘汰制→penalty_inverse；永久制→bonus_linear
  double_selection: split      # G4：parent/inspiration 两路参数成对声明

pressure:                      # 分歧 3
  control: closed_loop_thermostat   # 探针缺位强制降级 fixed_ratio
  structural_layer: true       # 岛隔离承载常开（归 M4 配置）
  double_injection: forbidden  # 单通道仲裁+deadband 硬编码

island_selection: {sampling_prior: uniform}   # 采样内贪心禁止；倾斜通道只走 G7

allocation:                    # 分歧 6：G6×G7×G13 三位一体同块级
  granularity: per_block       # h~10 代量级【推断】；per_call 禁默认
  mechanism: grow_deepen_bandit  # 多轨迹默认；单轨迹 fixed
  pmin: required               # 类型层字段；取值待标定（先记账后定参）
  window_cleaning: required    # 入档顺序污染/冷启动/相位切换点剔除规则

phase:                         # 分歧 4/5
  model: two_phase_relay       # 多模型档；单模型 single_phase+closed_loop
  strong_model_budget_share: 0.85  # RelayEvolve 先例起点、非通用常数
  switch_criterion: {primary: marginal_gain_saturated, fallback: budget_fraction, verdict_overlay: always}
  # wall_clock 单独触发不在合法取值集；切换强制挂快照

stop: {mode: soft_stop_default, attribution: required_on_hard, table: STOP_ACTION_TABLE}

intent_output:                 # 分歧 8
  form: intent_queue           # 块级；M1→M3 唯一通道（旁路意图=构建期拒绝）
  ratio_table: resident_baseline  # 永驻对照投影位
  ttl_blocks: 1

learnability:                  # 分歧 7
  online: frozen               # 运行期冻结；变化放逐离线层（离线 meta_evolvable）
  lineage_governance: required_if_not_frozen  # G15 强制联动；rl_trained 仅占位槽
```

**与其他模块的协议钩子**：
- **M3**：G13 intent_queue 唯一通道（记账/拒绝/配额执行归 M3）；意图条目带成本可归因标签；永驻对照预算份额、pmin 保底份额、快照预算均为一等科目；软停剩余预算意图交还 M3。
- **M4**：消费 ParentPool 五字段契约（写死对齐 M2-O11）与 P19 探针读数；P10 驱逐策略变更触发 G2 重配置（同入 X1）；快照载体复用 P13；handoff 打包归 P17、时机归 M1；spawn 结构执行归 P3/P4。
- **M8**：noise_floor/ReliabilityMeta 是 G17 门槛协议唯一合法输入源（跨模块共管，M1 不能独立自救）；决策用分继承"≥300 有效题"口径，不足时门槛协议输出恒"不可裁决"。
- **M9**：Verdict 枚举+Scope 为停止/相位动作的法定输入；M1 不复算统计量、不旁路判定；策略接受门控逻辑归 M9（M1 执行存储后果）。
- **M2**：M1 定压力方向，算子选择归 M2-O2（刚性边界）；注入疗效报告须连带 M2 供给端多样性读数（−76% 上限）。
- **X1**：意图条目、拒绝回流、公式版本快照、arm 统计与清洗规则、切换/回滚/饿死审计/归因报告、策略谱系四元组全部为一等谱系事件。

---

## 6. 八分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | 亲本公式形态（G1） | 分数可比性 × 淘汰策略 × 信噪比 × 工程亲和力 | **greedy 默认（v1.2 用户裁决）**+ 强制伴随 H2 监控与结构承载；weighted_sigmoid/three_way 永驻对照臂 | `parent_formula` 枚举 | 贪心默认的强制伴随缺失=构建期拒绝；非默认公式须过 G12 对照 | 采样事件带公式版本+参数快照入 X1；塌缩报警率超阈触发默认值复核（§9-10） |
| 2 | 拥挤项符号（G2，唯一条件句默认） | M4 淘汰策略 | 淘汰制→penalty_inverse；永久制→bonus_linear | `crowding_term` 无独立默认值 | 派生表写死；手工覆盖须附 G12 证据 | M4-P10 变更→G2 重配置，同入 X1（可审计联动） |
| 3 | 闭环 vs 结构承载（G3） | P19 探针是否在位 | closed_loop_thermostat + 结构承载常开 | `pressure_control` | 双重注入禁令（单通道仲裁+deadband）；τ 单写者归 G3 | 探针缺位强制降级 fixed_ratio+G12 对照常开 |
| 4 | 相位模型档位（G8） | 模型档位分化 × 收尾义务 | 多模型 two_phase_relay（0.85 先例起点）；单模型 single_phase+闭环 | `phase_model` + 相位参数档表 | cyclic_restart 不作生产取值 | 相位定义与 budget_split_curve 一致；切换走 G18 快照 |
| 5 | 切换信号源（G9） | M4-P17 估值信号是否在位 | Relay Gain 饱和主判据+预算比例兜底+Verdict 恒叠加 | `switch_criterion` 层级 | wall_clock 禁独用；切换强制挂快照 | P17 缺位退化兜底档且须在 G12 对照下运行 |
| 6 | bandit vs fixed（G7） | 多轨迹存在 × 信噪比 × 窗口清洗 | 多轨迹 grow_deepen_bandit（pmin+清洗不可分割）；单轨迹 fixed | `allocation_mechanism`；pmin/window 一等字段 | pmin 进类型层；per_call 禁默认 | arm 统计+清洗规则版本入 X1；倾斜超 pmin 须挂 G17 门槛输出 |
| 7 | 策略可学习档位（G14） | G15 就位 × 可归因性 × 证据等级 | 运行期 frozen+离线 meta_evolvable；rl_trained 占位 | `policy_learnability`+online/offline 作用域 | 非 frozen 无 G15=构建拒绝；rl_trained 启用入口不存在 | AIDE² 三重降档标注；版本变更在途意图显式处置 |
| 8 | intent_queue vs ratio_table（G13） | 状态响应 × 拒绝回流必要性 | intent_queue（块级）；ratio_table 永驻对照位 | `intent_output.form` | schema 四关键字段；M1→M3 唯一通道 | 拒绝回流 {intent_id, 原因, 预算余量} 进 X1；成本标签强制 |

---

## 7. 证据强度与投资优先序

**证据强度排序**（合并 Group A/B/C 结论与三批深挖，强→弱）：

1. **贪心禁止与非贪心供给**（ShinkaEvolve Fig.9 三档消融 2509.19349；GEPA Pareto 采样 vs 贪心 +6.4%/最高 +8.17% 2507.19457；VRP 3 代塌缩 2604.07872；FunSearch 15+ 代不退化）——方向最强；边界由 SB P=0.49 划定：**全部增量以评估统计可靠性为前提**。
2. **统计门槛与信噪比条件句**（SB P=0.49 vs EoH 5 倍预算效率两极一手证据对；Archive-Sampling 优于固定采样 2302.00463；Justesen 2019；Grillotti & Cully 2023）——机制方向有证据，中间段与相位分解无测量。
3. **块级分配与相位 relay**（RelayEvolve 11/12、0.85 消融、Fixed-switch 全败、0.82–1.01× 前期捕获）——单系统依赖面过宽（G6/G7/G8/G9 四轴锚同一系统，Fixed-switch 全败按卡片口径未独立核对）。
4. **退化自检制度**（SB 三域打平；hal-00519579 负结果传统；ShinkaEvolve 三消融归因模板）——负结果证据强，常驻进程版工程形态待建。
5. **多主体角色分工**（EvolveNet 70.7 vs 67.3、+9.0、无门控崩溃）——单系统，价值兑现路径穿过 M4-P16。
6. **策略学习高档位**（EvoX 近 200 任务；AIDE² 0.673→0.739【厂商博客级】；Harness-R1 +9.3 在 harness 域）——方向收敛、幅度降档、RL 端点空位。
7. **double selection split / 双重注入禁令 / h 块长**——零消融/控制论外推/无出处，最弱（G12 首验候选）。

**投资顺序表**：

| 顺位 | 投资方向 | 依据 |
|---|---|---|
| **0（最高优先，显式置顶）** | **G2 符号联动规则的框架内首验 + f(信噪比) 中间段标定** | 符号派生表是全 18 轴唯一条件句默认值的全部依据（双系统对照+机制外推，无固定档案策略下的符号扫描）——列 G12 首验最高优先级；SB 与 EoH 各测一个端点，信噪比中等的常态区间无任何功效-信噪比曲线，G17 全部门槛常数与 snr_adaptive 函数形状锁死在该标定上（**核心依赖**） |
| 1 | G17 门槛协议 + 决策/报告用分分离（消费 M8） | 四轴决策的共同门槛；噪声底下一切策略增量不可证伪（P=0.49） |
| 2 | intent_queue 通道 + 四关键字段（G13） | 六轴契约交汇点（policy_version/snapshot_ref/expected_gain CI 的载体），先建 schema 后谈机制 |
| 3 | G12 永驻对照与策略健康仪表盘（H2/H3/H7） | 其他全部非默认取值的激活器；失效在策略层不可内观测 |
| 4 | G18 可逆性绑定（快照复用 M4-P13+pmin+软停） | I-可逆第四投影落点；防塌缩保险费 |
| 5 | 相位 relay 与块级 bandit（G6–G9） | 单系统证据强但需第二系统复现 |
| 6 | G14/G15/G16 治理三件套 | 增量档；前置依赖重 |

---

## 8. Profile 兼容性验证（统一性的证明）

六个经典系统全部编译为 profile（Layer 3 策略选择 + Layer 4 配置），**无一处需要改内核**；每个 profile 诚实标注该系统实际违反的公理。

### 8.1 funsearch_greedy_uniform（亲本贪心 + 岛均匀 + 周期重置）

```yaml
profile:
  name: funsearch_greedy_uniform
  axes: {G1: 簇级 softmax(岛内 best 供亲≈贪心通道), G2: none(结构承载), G3: open_loop_anneal(T0=0.1, period=30000),
         G5: uniform(跨岛均匀), G7: fixed, G8: single_phase, G9: wall_clock(4h 杀半岛),
         G11: periodic_reset, G14: frozen}
  parent_formula: {scheme: cluster_softmax, crowding_term: none}   # none 合法：G3=structural 档联动
  island_selection: {sampling_prior: uniform}   # 15+ 代不退化的核心设计
  pressure: {control: open_loop_anneal}
  phase: {model: single_phase, switch: wall_clock(4h)}   # 违反 H4，见标注
```
内核复用：G2=none×结构承载的合法联动档；采样内岛均匀=G5 默认值的正面先例；岛内 best 供亲=v1.2 后贪心默认档的一手原型（结构承载条件下无害的正面证据）。
**公理违反标注**：原系统**违反 H4/G18（4h wall_clock 重置最差半岛=日历触发+不可逆饿死制度化，无快照无恢复路径——其正确性依赖"最差岛没有未来"这一欺骗性景观上不成立的前提）**、**违反 H11（无退化对照，periodic_reset 已被 dim06 明判"太粗暴"）**；（v1.2 前曾标注违反 H1 贪心通道，v1.2 贪心成为默认档后该条撤销——其岛内贪心+跨岛均匀恰是默认档强制伴随的正面先例）；4h 超参无论证被 PDE-SHARP 生态原样继承（arXiv:2511.00183）为失效扩散标本。【诚实标注】

### 8.2 shinkaevolve_bandit（父代加权 + bandit ensemble）

```yaml
profile:
  name: shinkaevolve_bandit
  axes: {G1: weighted_sigmoid(λ=10.0), G2: penalty_inverse, G4: split(inspirations=elite/top-k/archive+crowding),
         G5: uniform, G6: per_block(三池配额), G11: stagnation_spawn(threshold=100, 三播种),
         G14: bandit_online(UCB1 选 LLM), G17: point_estimate(原系统)}
  parent_formula: {scheme: weighted_sigmoid, score_params: {lam: 10.0, ref: median},
                   crowding_term: penalty_inverse}   # 淘汰制档案→负号派生一致
  double_selection: {mode: split, inspiration: [elite, top_k, archive_crowding]}
  inject: {stagnation_spawn: {threshold: 100, seeding: archive_random}}
  learnability: {online: bandit_online}   # UCB1 选 LLM ensemble
```
内核复用：weighted_sigmoid×penalty_inverse=本框架默认公式的一手原型；split 双路=G4 默认值先例；动态岛 spawn=G11 默认组成件先例。
**公理违反标注**：原系统**违反 G17/H8（决策消费点估计，无 CI/噪声底门槛）**、**部分违反 H10（bandit ensemble 上线先于其消融举证——实测仅 slight 增益，恰是 H10 预算序的教训来源，本框架将其降为非优先档）**；threshold=100 为单系统常数无消融（先记账后定参）。Fig.9 三消融（新颖性拒绝>父代加权>bandit）是 H12 组件级归因的正面模板。【诚实标注】

### 8.3 dgm_powerlaw（∝分数×子代数 + 永久档案）

```yaml
profile:
  name: dgm_powerlaw
  axes: {G1: fitness_times_children, G2: bonus_linear, G5: uniform(树节点≈单池),
         G7: fixed, G8: single_phase, G14: frozen(刻意冻结声明)}
  parent_formula: {scheme: fitness_times_children, crowding_term: bonus_linear}   # 永久制→正号派生一致
  # 须配供给浓度监控（永久树无驱逐，采样稀释无读数风险，M4-3a）
  learnability: {online: frozen}   # DGM §3 刻意冻结=可归因性论据的正面先例
```
内核复用：bonus_linear=G2 联动规则的永久制端点一手锚；冻结声明=frozen 默认值的论据来源（去 archive 消融显著退化 arXiv:2505.22954 §4.3 佐证回采价值）。
**公理违反标注**：原系统**违反 H2（无有效亲本数/供给浓度监控，unbounded 档案的采样稀释不可内观测）**、**违反 G17/H8（点估计驱动、无重评机制——记录值高估风险无对冲）**；换 benchmark 版本旧分失效但记录不自动作废（M4-7 案例 4，跨模块失效）。【诚实标注】

### 8.4 relayevolve_twophase（Relay Gain 切换）

```yaml
profile:
  name: relayevolve_twophase
  axes: {G6: per_block, G7: grow_deepen_bandit(recent-window UCB, 初始 Grow 收益剔除),
         G8: two_phase_relay(0.85), G9: marginal_gain_saturated, G16: 成本档分工, G17: point_estimate(原系统)}
  phase: {model: two_phase_relay, strong_model_budget_share: 0.85,
          switch_criterion: {primary: marginal_gain_saturated}}
  allocation: {granularity: per_block, mechanism: grow_deepen_bandit,
               window_cleaning: [drop_initial_grow]}
```
内核复用：G6/G7/G8/G9 四轴默认值的一手原型（11/12 均值最高；Fixed-switch 全败；0.82–1.01× 前期捕获）。
**公理违反标注**：原系统**未执行 H7（pmin 保底份额未声明——recent-window UCB 乘性倾斜的饿死防护缺位）**、**违反 G17（Relay Gain 饱和判据按点估计消费，无 CI-vs-噪声底门槛——本框架将其升级为 ci_gated 饱和判据）**；单系统四轴锚定本身已落边界声明。【诚实标注】

### 8.5 evox_policy_population（策略种群进化）

```yaml
profile:
  name: evox_policy_population
  axes: {G14: population_evolved, G15: 谱系库带部署状态标注((S,J,ϕ)), G8: 相位结构涌现(非人工),
         G9: stagnation_meta(停滞触发策略变异), G17: 部分(J 信号无 CI 口径)}
  learnability: {online: offline_meta, mode: population_evolved}
  policy_lineage: {schema: [policy_id, parent_policy_ids, deploy_context, acceptance_evidence],
                   acceptance: {rule: better_only, held_out_ci: required}}   # 本框架补齐：J 强制 CI 口径
```
内核复用：G14 population_evolved 档与 G15 (S,J,ϕ) 谱系库的一手原型（近 200 任务多数占优；单 run 内策略自发经历 random→greedy→分层多目标→UCB 相位序列——G8 的存在性反证与再证）。
**公理违反标注**：原系统**违反 G17/H8（J=Δ·log(1+s_start)/√W 无 CI 口径、窗口 W 无消融——谱系库排序键可能建在噪声上，winner's curse 风险；本框架强制 J 带 CI）**、**违反 H5/G18（谱系库无回滚原语——通用四元组抽象显式暴露的空缺）**；跨任务迁移证据仅单系统内（阴性发现 2）。【诚实标注】

### 8.6 aide2_outer_loop（外环爬山，博客级证据降档标注）

```yaml
profile:
  name: aide2_outer_loop
  axes: {G14: outer_loop_evolved(better-only 爬山), G15: better-only+held-out(版本链 AIDE0→47→85),
         G10: 外环 ~90% 拒绝率下长平台形态, G12: 缺常驻对照(一次性设计)}
  learnability: {online: frozen, offline: outer_loop_evolved}   # 外层循环离线/meta 层专用
  policy_lineage: {acceptance: {rule: better_only, held_out: aggregate}}
  # ★ 证据等级：厂商博客（weco.ai 2026-07），非同行评审，关键数字未见独立复核——
  #   100 步 8 天、MLE-Bench Lite 0.673→0.739、hacking 率 63%→34% 均不作设计参数依据
```
内核复用：G14 outer_loop 档与 G15 better-only 接受判据的（降档）先例；~90% 拒绝率是 G13 拒绝回流回路必要性的存在性证据。
**公理违反标注**：原系统**违反 H11/H12（无常驻退化对照、无组件级归因——外层爬山 100 步的增量无对照臂）**、**违反 H6（~90% 拒绝率下固定形态判据系统性误停风险无 CI 门槛对冲——其长平台+阶跃形态恰是 G10 的反例教具）**；全部数字三重降档标注。【诚实标注】

**兼容性结论**：六个 profile 覆盖策略层全部经典设计空间（贪心/加权/幂律/接力/种群进化/外环爬山六形态），差异=公式形态×拥挤项符号×相位模型×分配机制×可学习档位的选择，全部在配置层。表达不了的进 §9 边界声明。

---

## 9. 诚实边界声明（统一不了的东西，合并后 8 条）

1. **f(信噪比) 中间段完全未测**（本模块最大测量空缺）：SB（P=0.49，极低信噪比极）与 EoH（5 倍预算效率，评估精确极）各测一个端点——信噪比中等的常态区间无任何系统的功效-信噪比曲线；G17 snr_adaptive 档函数形状、G9/G10 的 CI 门槛在各信噪比档位的取值全部无标定依据（默认 ci_gated 而非 snr_adaptive 正因此）。"噪声底随相位移动"为结构外推，相位×信噪比分解阈值表零实现先例。
2. **G2 符号联动规则是全模块推论负载最重的推断**：淘汰制→penalty_inverse、永久制→bonus_linear 的支撑仅为 DGM/ShinkaEvolve 双系统对照+机制外推——无任何系统在固定档案策略下扫描 g 的符号；它是全 18 轴唯一条件句默认值的全部依据，置信中等，列 G12 首验最高优先级。
3. **RelayEvolve 单系统证据依赖面过宽**：G6 块级粒度、G7 grow_deepen_bandit（11/12）、G8 0.85 占比、G9 Relay Gain 饱和与 Fixed-switch 全败四轴锚同一系统；Fixed-switch 全败按既有卡片口径引用、未独立核对原文；饱和阈值无通用常数，"边际收益先于成本曲线"的时序差是 20 代单点测量。需第二系统复现。
4. **intent_queue 零先例**：显式跨模块协议无任何一手系统先例（RelayEvolve/ShinkaEvolve 的块级配额是内部实现），schema 是纯设计外推；拒绝回流回路的消费效果无量化（AIDE² 90% 拒绝率只证明"打回存在"）；ttl_blocks 与意图过期率无标定。
5. **AIDE² 博客级证据四处引用**（G13 拒绝回路/G14 outer_loop/G15 better-only/G18 误停论据）：非同行评审，关键数字（0.739、63%→34%、~90% 拒绝率）未见独立复核——统一三重降档标注；方向性结论靠 EvoX/EvolveNet 机制收敛佐证，幅度数字不作设计参数依据。
6. **G3 双重注入禁令为控制论外推**："同一熵信号驱动连续+离散双通道致过阻尼振荡"在 LLM 进化域零一手测量；closed_loop 的 α/β、τ_base、deadband 仅 LoongFlow 单系统先例、零扫描；closed_loop vs open_loop 无同任务干净对照。
7. **保底与阈值类参数全线"先记账后定参"**：G7 pmin（hal-00519579 只证明"无 pmin 必死"，多少最优无数据）、recent-window w（Sliding MAB 难超参无自动调参）、G9 饱和阈值、G11 threshold=100 与危机档 0.45–0.50（均单系统常数）、G18 饿死审计报警阈值、G12 永驻对照预算份额（建议 5–10% 纯推断）——全部是公理推导的占位符，触发线待运行数据标定。
8. **G14 五档右端空位与策略迁移盲区**：RL 训练 M1 策略本身零一手命中（阴性发现 1，2027 空位）——Harness-R1 证据在 harness 域；跨任务策略迁移基准不存在（阴性发现 2）；EvoX J 公式无消融、噪声底下谱系库排序键假阳性率无测量；五档间升级判据无任何文献触及。
9. **【v1.1·R4】拒绝-重发回路与 ttl_blocks=1 的时延冲突未解**（M1×M3 联合登记，MUST 级问题、方案待定）：rejected_budget→M1 重发低档的往返时延未量化，ttl_blocks=1 下重发意图可能出生即过期（旧 intent 作废、reserve 痕迹须清理，"幽灵预扣"风险）；候选方案为同谱系续约（ttl 重置+intent_id 派生关联）或预发双档意图——**交叉引用 M3-UNIFIED-v1 §9-3**（该冲突若不可解，"M3 只报价不决策"边界原则的执行层可行性受损）。另：**【v1.1·R3，SHOULD】** IntentReceipt.executed_cost 单值无法承载 J9 对账闭环的"承诺 vs 实际 vs 产出差"三件套与分币种结算，建议升级为 Dict[str, float] + settlement_report_ref——本版仅登记、暂不实施（详见 M3 对账文档契约修订建议 R3）。
10. **【v1.2】贪心默认档与证据强度排序的张力登记**：v1.2 用户裁决将默认亲本公式改为 greedy（工程亲和力优先），但 §7 证据强度排序第 1 条（贪心禁止与非贪心供给）仍是全模块方向最强的证据——本默认值是**工程裁决而非证据裁决**。补偿控制：H2 监控+结构多样性承载为强制伴随（构建期拒绝）；FunSearch 岛内贪心 15+ 代不退化证明结构承载下无害。**回退触发器**：运行数据中贪心默认档的塌缩报警率（H2 收缩事件/块）超过 weighted_sigmoid 对照臂 2× 时，默认值应复核回退——该比较由 G12 永驻对照自动产出，无需专门实验。

---

## 10. 分阶段落地（M1a–M1d，对接 ADAPT-v1.1）

| 期 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|
| **M1a（类型层，P0）** | ParentFormula（f×g 二元接口+派生表硬编码）/AllocationIntent/IntentReceipt（四关键字段）/PhaseSignal/PolicyLineage 四元组/STOP_ACTION_TABLE 落 core/policy/types.py；全部字段有默认值；G14≠frozen 无 G15 构建拒绝的类型层证明 | 缺 policy_version 的意图被拒、handoff 意图未挂 snapshot_ref 被运行期拦截、crowding_term 派生表随 M4-P10 联动的单测通过 | 无，与 M4a/M2a 类型层改动同批；并入 Step 0 |
| **M1b（最小可用策略层，P1）** | greedy 默认公式（强制伴随 H2 监控+结构承载校验）+weighted_sigmoid/three_way 对照臂+G4 split 两路+G5 岛均匀+fixed 分配+intent_queue 通道（M3 记账联调）+STOP_ACTION_TABLE 消费 M9 Verdict+G17 ci_gated 门槛（消费 M8 noise_floor）；funsearch_greedy_uniform / shinkaevolve_bandit 两 profile | sync 槽注册 LLM 算子直接报错；不可裁决输出触发重评转移的链路跑通；意图拒绝回流进 X1；真实运行产出台账 | M1a + M8 ReliabilityMeta（噪声底）+ M4 ParentPool 字段；并入 Step 1 |
| **M1c（闭环与可逆性，P2）** | 闭环恒温器+双重注入仲裁器（消费 M4-P19）+grow_deepen_bandit（pmin 类型层+窗口清洗）+G18 快照回滚（复用 M4-P13，策略状态随快照回滚）+软停归因+饿死审计清单+策略健康仪表盘（H2/H3/H7）+G12 永驻对照；dgm_powerlaw / relayevolve_twophase profile | 双重注入仲裁演练通过（同周期单通道）；回滚后 bandit 统计与快照一致的回归测试通过；对照臂产出可审计 | M1b + M4b/c（P19 探针、P13 快照）；并入 Step 2 |
| **M1d（相位接力与治理档，P3）** | two_phase_relay（消费 M4-P17 Relay Gain）+相位切换判据层级（饱和主判据+兜底+Verdict 恒叠加）+G14/G15 治理三件套（谱系库+better-only+回滚上一共享稳定版）+snr_adaptive 档（校准后启用）+G16 角色指派意图；evox_policy_population / aide2_outer_loop profile | handoff 否决回流演练通过；策略版本接受/回滚演练通过（回滚指稳定版非最优版）；对照预算份额 M3 保留科目记账 | M1c + M4d（P17 估值）+ M9 准入门 + 探针台账积累；并入 Step 3 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做 per_call 级路由/分配（RelayEvolve 近视失效一手阴性；决策粒度=块级）
- 不做无 CI 的停止/切换/加压决策（point_estimate 档永不合法，仅作对照臂）
- 不做 wall_clock 单独触发的相位切换（H4；日历量仅作估值缺位兜底且须对照）
- 不做无 pmin 的自适应分配（类型层拒绝；压零永不恢复原文明确）
- 不做无 G15 的非 frozen 策略档位（构建期拒绝）；不做 rl_trained 启用入口（仅占位槽）
- 不做 M1 侧统计检验实现（检测归 M9/M8，M1 只查表消费 Verdict）
- 不做跨组织产权/联邦部署（判归框架层，与 M4-P16 同款）

---

## 11. 一句话规格

> **M1 = 冻结的 ParentFormula（f 分数项×g 拥挤项二元接口；**v1.2 用户裁决：默认=greedy argmax 供亲（工程亲和力优先），强制伴随 H2 有效亲本数监控+结构多样性承载（缺失=构建期拒绝），weighted_sigmoid/three_way 为永驻对照臂，塌缩报警率超阈 2× 触发默认值复核**；crowding_sign 随 M4-P10 派生表硬编码——全轴系唯一条件句默认值；ScoreTerm 含 none 占位）/AllocationIntent+IntentReceipt（intent_queue 为 M1→M3 唯一通道，ttl/expected_gain CI/policy_version/snapshot_ref 四关键字段，可拒绝性为本质升级）/PhaseSignal（Relay Gain 饱和主判据+budget 兜底+Verdict 恒叠加，wall_clock 禁独用）/PolicyLineage 通用四元组（G14 非 frozen 强制）/STOP_ACTION_TABLE 查表（枚举→动作，M1 不复算统计量）数据模型与 CI-vs-噪声底门槛协议（不可裁决为一等输出，触发预算向重评转移；决策用分/报告用分类型层分离）、双重注入禁令（单通道仲裁+deadband、τ 单写者）、岛选择采样内 uniform+跨期 bandit（pmin 类型层+窗口清洗）、动作可逆性（快照复用 M4-P13、策略状态随快照回滚、软停归因、starvation_floor）（内核）+ G12 退化自检永驻对照（激活全体非默认取值；M2-C10/M4-P15/M1-G12 三处物化上收为框架级自我证成公约建议稿）与策略健康仪表盘（有效亲本数/探索转化率/预算洛伦兹曲线）（内核，永驻）+ 策略可热替换一等接口与可学习性五档（frozen 运行期默认/rl_trained 占位）+ 十八轴编译成的 profile（FunSearch/ShinkaEvolve/DGM/RelayEvolve/EvoX/AIDE² 全部是 profile 实例）+ 双速调度（sync 禁 LLM）+ H1–H12 公理内核化（H7 难实例部分/H9 为 SHOULD；H1 经 v1.2 修订为"贪心默认+强制伴随"）与四条既有不变量承接（I-披露候选承接，I-可逆由 M1 完成第四投影验证——调度层：切换=覆盖、停止=终止、饿死=渐近不可逆）。**
