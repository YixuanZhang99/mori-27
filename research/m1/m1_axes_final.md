# M1 Policy 定稿轴系（Stage 2 · 轴系建立）

> 依据：`groupA_policy_design.md`（候选轴 S1–S14 + 11 张系统卡片）、`groupB_policy_failures.md`（失效 S-1～S-8 + 候选公理 S-B1～S-B17 + 四个共同根因）、`groupC_policy_new.md`（6 条候选新轴 + 5 条阴性发现）。格式对标 `m4/m4_axes_final.md`。所有数字均引自上述三份产物，不新搜；推断标【推断】。M1 轴用 G 前缀（避免与 M2 的 O、M4 的 P、M6 的 K 混淆）。

## 轴系设计原则（与 M2/M4 轴系的风格一致性约定）

1. **轴 = 决策维度，不是组件列表**。每条轴回答一个"实现 M1 时必须做的、可不同答的选择"；"用不用 UCB"这类算法选型不成轴，"分配决策的最小粒度"才成轴。
2. **M1 只输出意图，不执行、不记账**。M1 的一等输出是（亲本分布参数, 相位动作, 分配意图流），每条轴的取值都是意图层的配置点；执行与资源核算的耦合处以"×"标注并指认责任模块。
3. **取值互斥、轴间可组合**；每轴给默认值——默认值 = 在"评估噪声中等、预算有限、单主体单 run"标准场景下证据最强的档；非默认取值以"跑赢退化投影（IID-RS/SCS）且增量超 M8 噪声底"为启用前提（S-B4/S-B15）。
4. **每条轴必须被证据锚定**：至少一条 Group B 失效（反推）或 Group A/C 一手实证（正推）；纯概念轴剔除（C5 策略迁移、C6 成本感知因此降为横切项）。
5. **职责边界刚性**：预算记账/配额执行归 **M3**（S13 intent_queue 是 M1→M3 的唯一通道）；算子选择归 **M2-O2**（M1 定"在哪个子种群施加哪个方向的压力"，不定用哪个变异算子）；准入/收敛裁决归 **M9**（M1 只消费 Verdict 枚举与 mSPRT/ASHA 门信号，不实现统计检验）；档案结构与字段归 **M4**（M1 只消费 ParentPool 契约字段与 P19 健康探针信号）；语义沉淀归 M5；谱系存证归 X1。
6. **模块定位公理（B 组根因 4）**：M1 的价值不在其复杂度而在其**已举证的净增量**——退化基线（IID-RS/SCS）是策略层永远的默认对照组；默认值选择以"限制策略层单点失效（塌缩/误停/饿死/噪声过拟合）的传播半径"为准绳。
7. **接口依赖标注**：每条轴标注它供给谁（M2 压力方向 / M3 意图 / X1 谱系）、消费谁（M4 字段与探针 / M8 噪声底 / M9 Verdict）。

---

## 第〇部分：合并与裁决

### Group C 六条候选处置表

| C 组候选 | 处置 | 理由 |
|---|---|---|
| C1 策略可学习性（EvoX/AIDE²/Harness-R1 五档梯度） | **并入 S14 扩取值（→G14）** | S14 已有 frozen/meta_evolvable/self_modifiable 骨架；C1 提供的是同一轴上更细的更新机制梯度（bandit 调统计量→外层爬山→LLM 进化+谱系库→RL 梯度训练）。阴性发现 1 明确"RL 训练 M1 策略本身"无一手命中，Harness-R1 是边界案例（策略对象是 harness 非进化循环），故不构成独立轴而扩展取值 |
| C2 策略谱系与版本治理 | **独立成新轴 G15** | 一旦 G14 取非 fixed 值，治理即成必需；EvoX (S,J,ϕ) 记录、AIDE² 版本链+better-only 接受、EvolveNet 门控回滚三家独立收敛；2023 前参数自适应文献无版本语义；阴性发现 3（无通用格式）恰说明是待建的轴 |
| C3 相位触发的状态依赖机制 | **并入 S9（→G9）** | S9 取值已含 marginal_gain_saturated/verdict_driven；C3 的贡献（AdaEvolve G_t 停滞触发、Fixed-switch 全败对照）是该轴的加细取值与加强证据，触发信号语义写进轴定义 |
| C4 多主体策略分工 | **独立成新轴 G16** | LLM 先验致并行分支同质化是 2023 前不存在的问题；EvolveNet 70.7% vs 67.3% + 角色指派消融为一手证据；与 M4-P16（档案分布与合并）互为镜像——P16 管存储侧合并，G16 管策略侧角色编排 |
| C5 策略-任务适配/迁移 | **判非轴，降为横切评估协议** | C 组自评"单独立轴证据不足"；阴性发现 2（迁移基准不存在）佐证；写入 G12/G14 的耦合说明：任何学习/进化得到的策略须报跨任务迁移证据 |
| C6 成本感知策略 | **判非轴，降为横切约束**（与 M4 对 C5 裁决一致） | 阴性发现 4：成本消融专文不存在，证据散落实现细节；成本意识写入 G6/G7/G13 的耦合说明（意图须带成本可归因标签，记账归 M3） |

### Group B 盲区 → 新轴裁决（三根因候选）

- **根因 1（策略决策消费点估计，正确输入是统计量）→ 新轴 G17 策略输入统计量与信噪比自适应**。选择（S-1）/切换（S-3）/停止（S-4）/分配（S-5）四类决策的失效边界全部由信噪比决定（S-6 总投影）；"边际改进 CI vs 噪声底"在全部经典系统默认路径缺席——这是装不进 S1–S14 任一单轴的横切输入维度，S-B7/S-B11/S-B12 的承载轴。
- **根因 3（不可逆策略动作跑在延迟证据前）→ 新轴 G18 策略动作可逆性与恢复路径**。S-B6/S-B8/S-B9/S-B16 的共同指向（切换快照、软停止、保底份额、降级流程）是独立的结构维度：它不是"何时切换/何时停"（G9/G10），而是"动作做出后能否反悔"。
- **根因 4（自我证成闭环缺失）→ 并入 S12（→G12）扩取值**。S12 退化自检已覆盖核心；S-B15/S-B16/S-B17 把它从"触发时机"扩展为完整制度（周期重验/自动降级/组件级归因/热替换合规），作为 G12 的取值梯度，不另立轴。

### Group A 轴处置

- S1–S14 全部保留（均被证据锚定），编号平移为 G1–G14。
- **特别裁决①（S5×S7 重叠）**：S5 岛选择分布与 S7 跨轨迹分配机制相邻但切分不同对象（S5=单个亲本采样动作内的岛级先验；S7=块级预算在轨迹/岛间的跨期分配），AdaEvolve Level 2（跨岛 bandit）属 S7、ShinkaEvolve 岛均匀采样属 S5，保持独立。
- **特别裁决②（S3×S11 信号共享）**：闭环调温与 restlessness 共用档案熵/停滞信号，裁决为同一信号源（消费 M4-P19 探针读数）、两个动作通道（连续旋钮 vs 离散注入），耦合说明中禁止双重注入。

**最终轴系：18 轴**（G1–G14 对应 A 组 S1–S14；G15、G16 来自 C 组；G17、G18 来自 B 组盲区）。

---

## G1 亲本选择公式形态（原 S1）★M1 核心输出

**一句话定义**：parent 采样概率的函数族——M1 契约的中心件。

| 取值 | 描述 |
|---|---|
| three_way | exploit 0.7 / explore 0.2 / random 三路混合（OpenEvolve，最大存量约定） |
| weighted_sigmoid | σ(λ·ΔF)·h(children)，先减中位数再 sigmoid，分数尺度鲁棒（ShinkaEvolve） |
| power_law | 排名幂律 r^{−α}，α=1.0（ShinkaEvolve） |
| boltzmann | exp(ΔF/τ)·sample_weight^p（LoongFlow/FM Agent） |
| coverage_proportional | Pareto 覆盖实例数比例（GEPA，对标定不可比的多实例分数天然免疫） |
| fitness_times_children | 分数×(1+子代数)（DGM 永久树档案） |

**关键证据锚点**：ShinkaEvolve Fig.9 三档消融 weighted > hill climbing > random（arXiv:2509.19349）；GEPA Pareto 采样 vs 贪心 +6.4%/最高 +8.17%（arXiv:2507.19457）；FM Agent adaptive sampling 比 top-k 高 10.99%、比 random 高 58.26%（arXiv:2510.26144）；四系统收敛形态 `p_i ∝ f(score−ref)·g(children, rarity)`。
**默认值**：`weighted_sigmoid` + 保留 `three_way` 作兼容投影。空缺标注：公式族间无同预算横向消融，默认值置信中等。
**耦合**：×G2（公式形态决定拥挤项接口）；×M4-P7（字段供给契约写死对齐 M2-O11）；×G12（任何非默认公式须过退化对照）。

## G2 新颖/拥挤项的方向与形式（原 S2）

**一句话定义**：乘积公式中 g(children_count, rarity) 的符号与参数化。

| 取值 | 描述 |
|---|---|
| penalty_inverse | 1/(1+N)，容量淘汰档案下"已榨取者让位"（ShinkaEvolve） |
| bonus_linear | (1+N)，永久树档案下"子代多=stepping stone 价值高"（DGM §C.2） |
| soft_weight | sample_weight^p 软惩罚（LoongFlow/dim05） |
| none | 无拥挤项 |

**关键证据锚点**：DGM §C.2 vs ShinkaEvolve §3.1 的同字段异号对照【方向由档案淘汰策略决定：永久制→正、淘汰制→负，推断】；OpenRSI reward×子代方差×rarity 三系统收敛。
**默认值**：随 M4 档案淘汰策略联动——淘汰制→`penalty_inverse`；永久制→`bonus_linear`。
**耦合**：×M4-P10（容量与驱逐策略决定符号）；×M4-P7（children_count/rarity 字段供给）。

## G3 探索/利用调节旋钮（原 S3）

**一句话定义**：选择压力如何随时间/状态变化。

| 取值 | 描述 |
|---|---|
| fixed_ratio | 固定配比（OpenEvolve 0.7/0.2，开环无反馈） |
| open_loop_anneal | 温度日程退火（FunSearch T0=0.1、period=30000，开环） |
| closed_loop_thermostat | 种群熵→τ 闭环（LoongFlow τ=τ_base(1+αe^{−βH})） |
| structural | 岛隔离+迁移承载，旋钮只微调；温度池 β 梯连续分层（EvoDiverse +12%/+19% Top-10 AUC 为其变体） |

**关键证据锚点**：LoongFlow 熵闭环（arXiv:2512.24077 §3.4）；FM Agent 第 40 代超 random 峰值（random 需 900 代）；VRP 纯 exploit 3 代塌缩（arXiv:2604.07872）；Verbalized Sampling 对齐后多样性 −76%（arXiv:2510.01171，供给端上限封顶本轴效能）。
**默认值**：`closed_loop_thermostat`；α/β 常数仅 LoongFlow 单系统先例，跨域稳健性未验证【推断】。
**耦合**：×G11（共用熵信号，禁止双重注入）；消费 M4-P19 供给熵探针；×G17（信噪比低时强制升温降压，S-B11）。

## G4 double selection 亲本/灵感分采（原 S4）

**一句话定义**：parent 与 inspirations 是否用两个不同采样分布。

| 取值 | 描述 |
|---|---|
| shared | 同一分布采 parent 与 inspirations |
| split | parent 偏 exploit、inspirations 偏 explore+topK（OpenEvolve/ShinkaEvolve 双系统收敛） |

**关键证据锚点**：OpenEvolve default_config.yaml/database.py 一手；ShinkaEvolve inspirations=elite/top-k/archive+crowding 一手配置。
**默认值**：`split`（零成本多样性增益，双系统收敛）；M1 默认契约 = (parent 分布, inspiration 分布) 两路参数化输出。
**耦合**：×G1（两个分布各自取 G1 形态）；×M4-P8（M4 只暴露注入点，公式归 M1——刚性边界）。

## G5 岛选择分布（原 S5）

**一句话定义**：单次亲本采样动作内"先选岛"的岛级概率。

| 取值 | 描述 |
|---|---|
| uniform | 岛均匀（FunSearch 15+ 代不退化的核心设计；ShinkaEvolve） |
| proportional | 按岛 best/大小加权 |
| weighted_recent_gain | 按岛近期收益（AdaEvolve 全局归一化 r=(f′−f*)/f*_global 消"差岛偏好"） |

**关键证据锚点**：FunSearch 跨岛均匀（Nature 2024，B 组 S-1 正面对照）；AdaEvolve 185 问题统一超参（arXiv:2602.20133）。
**默认值**：`uniform`；bandit 化岛选择归 G7（跨期分配），不在本轴。
**耦合**：×M4-P3（岛数 K）；×G7（本轴是采样内先验，G7 是预算跨期分配，对象不同——裁决①）。

## G6 分配决策粒度（原 S6）

**一句话定义**：M1 分配决策的最小单位。

| 取值 | 描述 |
|---|---|
| per_call | 逐调用路由——**反例，禁默认**（RelayEvolve 一手证明近视失效） |
| per_block | h 代一块（RelayEvolve Grow–Deepen；h 默认 ~10 代量级【推断】） |
| per_phase | 相位级一次性分配 |

**关键证据锚点**：RelayEvolve"call 级 bandit 是错的问题"（arXiv:2608.05651）；ShinkaEvolve proposal/eval/db 三池配额同向佐证。
**默认值**：`per_block`。
**耦合**：×G7×G13（粒度-机制-输出形式三者必须同块级）；成本横切约束：块级意图须带 token/美元可归因标签（C6 落点，记账归 M3）。

## G7 跨轨迹/跨岛分配机制（原 S7）

**一句话定义**：多条搜索线间块级预算意图的跨期分配规则。

| 取值 | 描述 |
|---|---|
| fixed | 固定分配（单轨迹场景退化形态） |
| grow_deepen_bandit | recent-window UCB，奖励=边际改进；初始 Grow 收益受入档顺序污染须剔除统计（RelayEvolve 一手细节） |
| unified_signal | 单一累积改进信号 G_t 驱动多级分配+停滞触发（AdaEvolve 三级同信号） |
| restart_cycle | SCS 周期重启（退化基线兼简相位循环） |

**关键证据锚点**：RelayEvolve 4 benchmark×3 预算 11/12 均值最高（arXiv:2608.05651）；AdaEvolve 圆打包 2.636 超人类 SOTA（arXiv:2602.20133）；hal-00519579：乘性权重更新必产饿死尾部，Adaptive Pursuit 无 pmin 则算子压零后永不恢复——任何自适应分配须带显式保底份额（S-B9）。
**默认值**：多轨迹场景 `grow_deepen_bandit`（含 pmin 保底份额）；单轨迹退化为 `fixed`。
**耦合**：×G18（保底份额=不可逆饿死的预防结构）；×M4-P17（移交估值信号是本轴输入）；空缺：跨任务课程式调度无一手先例（A 组空缺标注 2）。

## G8 相位模型（原 S8）

**一句话定义**：搜索过程是否分显式阶段。

| 取值 | 描述 |
|---|---|
| single_phase | 无相位，全由温度/配比连续调节（FunSearch） |
| two_phase_relay | 便宜探索→强模型精化，handoff 一次（RelayEvolve；强模型预算占比默认 0.85 消融最优） |
| three_phase | 构想→利用→收尾（POCAII"前探后收"在 HPO 域的独立证据：低预算超 SMAC/BOHB/DEHB 且方差更低） |
| cyclic_restart | 周期重启循环（SCS/SB） |

**关键证据锚点**：RelayEvolve（arXiv:2608.05651）；POCAII（arXiv:2505.11745）；GEPA 固定验证预算分配须"动态选择验证子集"补救（作者自承，arXiv:2507.19457）。
**默认值**：多模型档位场景 `two_phase_relay`；单模型 `single_phase + closed_loop`（G3）。
**耦合**：×G9×G10（相位模型决定切换判据与停止消费的可选值）；×M4-P17（handoff 打包归 M4，时机归 M1）。

## G9 相位切换判据（原 S9，吸收 C3）

**一句话定义**：何时切相位/handoff——触发信号的语义（日历 vs 搜索状态观测量）。

| 取值 | 描述 |
|---|---|
| budget_fraction | 预算比例——**反例**（RelayEvolve Fixed-switch 对照臂全败） |
| wall_clock | 固定时刻表——**反例**（FunSearch 4h 重置无论证被生态继承，arXiv:2511.00183） |
| marginal_gain_saturated | Relay Gain 持续低触发 handoff（档案估值曲线比预算曲线更早更准宣告相位终结） |
| stagnation_meta | 停滞信号触发 meta 干预/新岛（AdaEvolve G_t≤0.02 全岛停滞 spawn；Level 3 System 2 战术重定向） |
| verdict_driven | 消费 M9 枚举 Verdict（CONVERGED→收尾；FUNDAMENTAL_LIMIT→换方向而非再试） |

**关键证据锚点**：RelayEvolve Fixed-switch 全败 + 11/12 最优（arXiv:2608.05651）；AdaEvolve（arXiv:2602.20133）；MOSS plateau guard 1/2/3 随 depth tier 缩放。
**默认值**：`marginal_gain_saturated` 为主 + `budget_fraction` 兜底（S-B5：固定时刻表默认禁止；Relay Gain 饱和阈值论文未给通用常数，默认值为方向性结论）。
**耦合**：消费 M4-P17 Relay Gain 估值曲线与 M9 Verdict；×G17（切换输入须为边际改进 CI 而非点估计，S-B12）；×G18（切换须带快照与反悔路径）。

## G10 停止判据消费（原 S10）★接口 M9/M3

**一句话定义**：M1 如何响应停止信号并主动早停——M1 只做相位动作，统计检验不做。

| 取值 | 描述 |
|---|---|
| budget_only | M3 耗尽硬停（兜底，不可单独使用） |
| +verdict | 消费 M9 枚举 Verdict 做相位动作（停岛/切档/重分配） |
| +marginal_utility | 边际收益 CI 低于噪声底主动软停，剩余预算意图交还 M3 |

**关键证据锚点**：Justesen 2019——噪声域档案质量随时间退化，"继续运行=继续变差"，停止判据承担止损职能；AIDE² ~90% 外环拒绝率致长平台+阶跃形态，固定 K 代无改进判据系统性误停；FunSearch cap set 突破在数千代尺度（任何固定 K 都会在突破前截断）。
**默认值**：`+verdict + marginal_utility`（S-B7：CI 下界高于噪声底时禁止以 plateau 为由停止）。
**耦合**：**收敛统计机制归 M9/M8（刚性边界）**；×G17（停止输入是"边际改进 CI vs 噪声底"统计量）；×G18（软停止为默认，硬终止须附归因报告，S-B8）。

## G11 restlessness 主动多样性注入（原 S11）

**一句话定义**：何时主动打破当前搜索重心。

| 取值 | 描述 |
|---|---|
| never | 不主动注入 |
| stagnation_spawn | 停滞→新岛/新轨迹（ShinkaEvolve threshold=100 代；initial/best/archive_random 三播种策略） |
| diversity_floor | 档案熵/嵌入覆盖低于阈值→升 τ/升 explore 比/注入随机亲本（MDPI 15(5):98 危机档变异率 0.45–0.50 的完整控制逻辑先例） |
| periodic_reset | FunSearch 4h 杀半岛——**弃用**（dim06 §3.7"重置太粗暴"；演化后期可能砍掉正突破的岛） |

**关键证据锚点**：ShinkaEvolve 动态岛繁殖（arXiv:2509.19349）；MDPI Robotics 15(5):98 需 5 种多样性机制并用才防住塌缩；Verbalized Sampling −76%（注入效能被 M2 变异供给端先验封顶）。
**默认值**：`stagnation_spawn + diversity_floor`。
**耦合**：×G3（共用 M4-P19 熵探针信号，禁止双重注入——裁决②）；spawn 动作的结构执行归 M4-P3/P4。

## G12 退化自检与自我证成（原 S12，吸收 B 根因 4）★横切激活器

**一句话定义**：策略层持续续证"我比关闭我更好"的制度——退化基线是策略层一等公民。

| 取值 | 描述 |
|---|---|
| none | 无对照——策略复杂性不可证伪（OpenEvolve 策略硬编码致对照不可执行=不合规架构，S-B15） |
| pre_activation | 非默认取值启用前须跑赢 IID-RS/SCS 且增量超 M8 噪声底 |
| resident_probe | SCS/均匀采样投影永驻对照，定期比对 |
| +periodic_revalidation | 环境/模型/噪声底变更后自动重跑对照；增量不显著的组件进入降级流程（S-B16）；多组件增量强制组件级归因（S-B17，ShinkaEvolve 三消融为模板） |

**关键证据锚点**：SB P(Shinka>IID RS)=0.49、重评 10 次后无差异（arXiv:2602.16805）——退化基线证伪策略价值的教科书案例；hal-00519579"最优自适应难稳赢朴素"的负结果传统；OpenEvolve ProgramDatabase 策略硬编码=自检缺失被架构固化的反例（策略可热替换为一等架构要求，呼应 F-B2）。
**默认值**：`resident_probe + periodic_revalidation`。
**耦合**：×全体（其他全部轴的非默认取值以本轴对照为启用前提——"自检是其他全部公理的激活器"）；消费 M8 噪声底；对照结果进 X1 谱系（可审计）。

## G13 分配意图输出形式（原 S13）★M1→M3 唯一通道（刚性）

**一句话定义**：M1→M3 的接口形态——**M1 只产出意图，记账、拒绝与配额执行全部归 M3**。

| 取值 | 描述 |
|---|---|
| ratio_table | 固定比例表（最简，不可响应状态） |
| intent_queue | 带优先级的块级分配意图流（与 G6 块粒度对齐；M3 负责记账与拒绝） |
| budget_split_curve | 按相位/轨迹的预算曲线函数（RelayEvolve 0.85 强模型占比；POCAII 相位化预算形状） |

**关键证据锚点**：RelayEvolve 预算占比消融（arXiv:2608.05651）；POCAII 相位预算形状（arXiv:2505.11745）；AIDE² 外环 ~90% 拒绝率——意图被下游打回的回路必须存在。
**默认值**：`intent_queue`（块级）。
**耦合**：**预算记账/配额执行归 M3（刚性边界）——本通道是 M1→M3 唯一接口**；×G6（粒度必须同为块级）；意图条目须携带成本可归因标签（C6 横切约束落点）。

## G14 策略可学习性与可进化性（原 S14，吸收 C1）

**一句话定义**：M1 公式/参数在运行期是否可被学习/进化更新，更新机制是什么。

| 取值 | 描述 |
|---|---|
| frozen | 公式结构冻结，参数按调度表/闭环规则变化（AlphaEvolve/AIDE0；DGM §3 刻意冻结；AVO 综述"Sample 仍是固定算法过程"） |
| bandit_online | bandit 在线调选择统计量，不更新策略表示（ShinkaEvolve UCB1 选 LLM；AdaEvolve） |
| outer_loop_evolved | 策略代码被外层循环 better-only 爬山重写（AIDE²：100 步 8 天，MLE-Bench Lite 0.673→0.739，hacking 率 63%→34%【厂商博客级证据】） |
| population_evolved | 策略作为种群对象被 LLM 变异进化+谱系库（EvoX：近 200 任务多数占优；单 run 内自发经历 random→greedy→分层多目标→UCB 相位序列） |
| rl_trained | 策略参数化+SFT/GRPO 梯度训练——**边界取值**：Harness-R1 +9.3、20/20 未见模型正迁移，但其策略对象是 agent harness 而非进化循环；阴性发现 1：RL 训练 M1 策略本身无一手命中，2027 空位 |

**关键证据锚点**：EvoX（arXiv:2602.23413）；AIDE²（weco.ai 2026-07，非同行评审，引用须注明）；Harness-R1（arXiv:2608.02276）；DGM 冻结声明+AVO 判断（安全与可归因性论据）。
**默认值**：`frozen`（运行期）+ 离线 `meta_evolvable`（运行期只许参数级调节，不许结构自改）。
**耦合**：取非 frozen 值时 G15（谱系治理）强制启用；×G12（进化/学习得到的策略同样须过退化对照与迁移证据报告——C5 横切协议落点）；策略版本变更进 X1。

## G15 策略谱系与版本治理（新，C2）★接口 X1

**一句话定义**：策略版本如何记录、评估、接受/回滚、跨循环层引用。

| 取值 | 描述 |
|---|---|
| 无版本（单策略） | 经典默认 |
| 谱系库带部署状态标注 | EvoX (S, J, ϕ) 记录：策略×进步率信号×部署时种群描述子 |
| better-only 接受+held-out 判据 | AIDE² 版本链 AIDE0→AIDE47→AIDE85，held-out 聚合分接受 |
| 门控+回滚协议 | EvolveNet 行为门控，回滚恒指向上一共享 harness 而非最优 client |

**关键证据锚点**：三家独立收敛（arXiv:2602.23413 / weco.ai 2026-07 / arXiv:2608.04968）；阴性发现 3：策略谱系通用表示不存在，各家私有——本轴是待建规范。
**默认值**：无版本（G14=frozen 时）；G14 非 frozen 时强制 `谱系库 + better-only 接受`。
**耦合**：谱系记录进 X1；×G14（本轴是 G14 非默认取值的治理前提）；×M4-P16（策略合并/回滚与档案合并协议同构术语对齐）。

## G16 多主体策略分工（新，C4）★与 M4-P16 镜像

**一句话定义**：探索/利用权衡在多个并行进化主体间的配置——从单主体内采样分布升格为多主体间角色编排。

| 取值 | 描述 |
|---|---|
| 单主体 | 经典默认（无分工） |
| 同质并行分支 | 不干预——**失效取值**（LLM 先验使独立分支坍缩到同类编辑） |
| 异质角色指派 | conservative repair / independent exploration / adversarial audit 按 client index 分配（EvolveNet）；对抗角色（分布式 Red Queen 2605.27130） |
| 成本档分工 | 便宜模型探索/贵模型精化的角色分化（RelayEvolve/Squeeze Evolve，路由粒度到重组组级） |

**关键证据锚点**：EvolveNet BIRD held-out 70.7% vs 等预算集中式 67.3%（配对 14 胜 9 负）；DS-1000 合并 harness 超最强单 client +9.0；集中式无门控链式进化直接崩溃回滚（arXiv:2608.04968）。
**默认值**：单主体；多主体场景 `异质角色指派`。
**耦合**：**跨组织产权/联邦部署归框架层（刚性边界，与 M4-P16 一致），M1 只到角色意图编排**；合并门控与存储归 M4-P16/M9；×G7（角色分工与预算分配联合决策）。

## G17 策略输入统计量与信噪比自适应（新，B 根因 1）★消费 M8

**一句话定义**：M1 核心决策消费的输入是分数点估计还是"边际改进 CI vs 噪声底"统计量——策略强度是信噪比的函数。

| 取值 | 描述 |
|---|---|
| point_estimate | 点估计驱动——**全部经典系统默认，失效配置**（S-1/S-3/S-4/S-5 的共同根因） |
| ci_gated | 决策输入为 CI/噪声底比值；CI 下界高于噪声底才允许"加强选择/停止/切换"类动作（S-B7/S-B11） |
| +snr_adaptive_pressure | 观测信噪比低→选择温度自动上调+重评预算占比自动上调（预算从"选"挪到"重评"）；策略功效按相位×信噪比分解报告（S-B12） |

**关键证据锚点**：SB P=0.49 vs EoH 5 倍预算效率（arXiv:2401.02051，2,000 查询 0.66% gap 胜纯采样 10,000 次 2.44%）——策略价值=f(信噪比) 的两极一手证据；M8 噪声分解：预测噪声>数据噪声，换评估采样比重收数据更能移动噪声底（arXiv:2512.21326）；Flageat & Cully 2023 Archive-Sampling 显著优于固定采样（arXiv:2302.00463）——同预算花重评优于更精细选择；Grillotti & Cully 2023 精英重测显著低于记录值。
**默认值**：`ci_gated`（最低档必配）。
**耦合**：消费 M8 噪声底测量（跨模块共管，M1 不能独立自救）；×G1/G3/G9/G10（四轴动作的统计门槛）；×M4-P20（双资格分离的档案侧镜像）。

## G18 策略动作可逆性与恢复路径（新，B 根因 3）

**一句话定义**：不可逆策略动作（相位切换/停止/饿死/降级）须附带可恢复路径或延迟执行——"软"不是工程奢侈而是防塌缩结构件。

| 取值 | 描述 |
|---|---|
| hard_irreversible | 单向门——**失效配置**（切换即弃前相位、硬终止、零预算静默消失） |
| snapshot_rollback | 相位切换/handoff 保留前相位种群快照与恢复原语；handoff 被下游否决的候选携带否决原因回流入谱系（S-B6，呼应 F-B12/F-B13） |
| +soft_stop | 软停止默认（保留档案可续跑）；硬终止须附归因报告（收敛/打转/预算/噪声底）；plateau 归因失败默认续跑（S-B8） |
| +starvation_floor | 任何按回报加权分配保留显式最小份额（岛级/实例级/谱系级 pmin），零预算幸存者清单常驻审计（S-B9/S-B10；难实例方向专项保护） |

**关键证据锚点**：hal-00519579——Adaptive Pursuit 无 pmin 则算子压零后永不恢复，非平稳环境下不可逆损失【原文明确】；FunSearch"重置最差半岛"=饿死制度化，其正确性依赖"最差岛没有未来"这一欺骗性景观上不成立的前提；AIDE² ~90% 拒绝率下误停烧掉全部已付探索成本；EvolveNet 回滚恒指向上一共享 harness（生产级反悔路径先例）。
**默认值**：`snapshot_rollback + soft_stop`；存在自适应分配（G7 非 fixed）时叠加 `starvation_floor`。
**耦合**：×G9/G10（切换/停止动作的结构配套）；×G7（保底份额是分配的组成部分）；快照载体归 M4-P13，谱系留痕进 X1。

---

## 总览表

| 轴 | 取值集 | 默认值 | 最强证据 | 接口依赖 |
|---|---|---|---|---|
| G1 亲本公式形态 | three_way/weighted_sigmoid/power_law/boltzmann/coverage_prop/fit×children | weighted_sigmoid（three_way 兼容投影） | Shinka Fig.9 三档消融；GEPA +6.4% | ×M4-P7 字段契约；×G12 |
| G2 拥挤项方向 | penalty_inverse/bonus_linear/soft_weight/none | 淘汰制→penalty_inverse | DGM vs Shinka 同字段异号对照 | ×M4-P10/P7 |
| G3 探索利用旋钮 | fixed/open_loop_anneal/closed_loop/structural | closed_loop_thermostat | LoongFlow 熵闭环；FM Agent 40 代超 random 峰值 | 消费 M4-P19；×G11/G17 |
| G4 亲本/灵感分采 | shared/split | split | OpenEvolve+ShinkaEvolve 双系统收敛 | **公式归 M1；M4-P8 只暴露注入点** |
| G5 岛选择分布 | uniform/proportional/weighted_gain | uniform | FunSearch 15+ 代不退化 | ×M4-P3 |
| G6 分配粒度 | per_call(禁)/per_block/per_phase | per_block | RelayEvolve call 级近视一手阴性 | ×G7/G13 |
| G7 跨轨迹分配 | fixed/grow_deepen_bandit/unified_signal/restart | grow_deepen_bandit（含 pmin） | RelayEvolve 11/12；AP 无 pmin 永不恢复 | ×M4-P17；×G18 |
| G8 相位模型 | single/two_phase_relay/three_phase/cyclic | two_phase_relay（多模型档） | RelayEvolve；POCAII 低预算超 BOHB | ×M4-P17 |
| G9 相位切换判据 | budget_frac(反例)/wall_clock(反例)/gain_saturated/stagnation_meta/verdict | marginal_gain_saturated+budget 兜底 | Fixed-switch 全败；AdaEvolve G_t 触发 | 消费 M4-P17/M9 Verdict；×G17/G18 |
| G10 停止判据消费 | budget_only/+verdict/+marginal_utility | +verdict+marginal_utility | Justesen 继续跑=更差；AIDE² 长平台误停 | **统计机制归 M9/M8（刚性）**；×G17/G18 |
| G11 restlessness | never/stagnation_spawn/diversity_floor/periodic_reset(弃) | stagnation_spawn+diversity_floor | Shinka 动态岛；MDPI 5 机制并用 | 消费 M4-P19；×G3 |
| G12 退化自检与自我证成 | none/pre_activation/resident/+periodic_revalidation | resident+periodic | SB P=0.49；hal-00519579 负结果传统 | 消费 M8；对照进 X1；激活全体非默认取值 |
| G13 意图输出形式 | ratio_table/intent_queue/budget_split_curve | intent_queue（块级） | RelayEvolve 0.85 消融；AIDE² 90% 拒绝回路 | **M1→M3 唯一通道（刚性）；记账归 M3** |
| G14 策略可学习性 | frozen/bandit_online/outer_loop_evolved/population_evolved/rl_trained(边界) | frozen+离线 meta_evolvable | EvoX 200 任务；AIDE² 8 天超两年手调 | 非 frozen 强制 G15；版本进 X1 |
| G15 策略谱系治理 | 无版本/谱系库/better-only+held-out/门控回滚 | 随 G14 联动 | 三家独立收敛；通用格式不存在（阴性 3） | 谱系进 X1；×M4-P16 术语对齐 |
| G16 多主体策略分工 | 单主体/同质并行(失效)/异质角色/成本档分工 | 单主体；多主体→异质角色 | EvolveNet 70.7 vs 67.3；无门控链式崩溃 | **跨组织归框架层（刚性）；与 M4-P16 镜像** |
| G17 输入统计量与信噪比 | point_estimate(失效)/ci_gated/+snr_adaptive | ci_gated | SB P=0.49 vs EoH 5×；Archive-Sampling 胜固定采样 | 消费 M8 噪声底；×G1/G3/G9/G10 |
| G18 动作可逆性 | hard(失效)/snapshot_rollback/+soft_stop/+starvation_floor | snapshot+soft_stop（+保底随 G7） | AP pmin 不可逆；EvolveNet 回滚先例 | 快照归 M4-P13；留痕进 X1；×G7/G9/G10 |

## 逐格深挖优先级提示

预计深挖工作量最大的三条：
1. **G17 输入统计量与信噪比自适应**——横跨 G1/G3/G9/G10 四轴的统计门槛设计，须消费 M8 噪声底并定义"CI 下界 vs 噪声底"的具体比较协议、信噪比观测的窗口与相位分解（S-B12 报告格式），与 M4-P20、M9-A4 的术语对齐三方待定。
2. **G14+G15 策略可学习性×谱系治理**——EvoX/AIDE²/EvolveNet 三家私有表示须抽象成通用 (S, J, ϕ) 契约（阴性发现 3：无可移植规范），接受判据、回滚原语、X1 谱系条目格式全部待建；且 AIDE² 证据等级为厂商博客，默认值周边须标注置信。
3. **G18 动作可逆性**——snapshot_rollback 的载体契约要与 M4-P13 写死对齐，starvation_floor 的 pmin 取值是 hal-00519579 明示的难超参（高则浪费、低则虚设），零预算审计的报告格式与 G7 的 bandit 统计污染处理（初始 Grow 收益剔除）纠缠，工程化细节最密。
