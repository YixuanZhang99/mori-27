# M1 Policy 调研 · A 组：设计空间（亲本公式/探索利用/相位调度/停止/分配意图）

> 范围：AutoResearch/AutoOptimization 框架的 M1（全局搜索策略模块）——探索/利用权衡、亲本选择公式（M4 供信号、M1 出公式）、相位调度（何时切阶段/何时停）、跨岛/跨任务/跨相位的分配意图、退化自检触发。
> 边界切分（沿用 M2-UNIFIED-v1 / M4 裁决）：**预算记账归 M3**（M1 只输出"分配意图"，不记账）；**算子选择归 M2-O2**（M1 决定"在哪个子种群上施加哪个方向的压力"，不决定用哪个变异算子）；**准入归 M9**（M1 消费 M9 的 Verdict.CONVERGED 等信号作相位/停止输入）；**档案结构与字段归 M4**（M1 消费 F7 契约字段：`island_id / children_count / rarity / per-instance 最优表 / sample_weight / score_vector`）。
> 数字约定：一手来源（论文 arXiv 编号 / 官方仓库）为准；本地既有卡片（m4 groupA、m2 groupA、dim05、dim06、newworks15）内数字已回溯到一手出处，本文沿用并标注；【推断】为分析者判断。

---

## 1. 分系统卡片

### 1.1 OpenEvolve：三路混合 + double selection（M1 最大契约的来源）

- **公式**：父代采样 = 三路混合 `exploitation 0.7 / exploration 0.2 / random`；**double selection**——展示给 LLM 的 parent 与 inspirations **分别采样**（parent 偏 exploit，inspirations 偏 explore），即一次生成消费两个不同的采样分布。【一手：openevolve default_config.yaml / database.py，经 m4 groupA 回溯】
- **机制归属**：该 0.7/0.2 配比硬编码在 ProgramDatabase 内（"换策略需改源码"，m4 groupA §1.3 反例）——正是"公式归 M1、字段归 M4"切分要解决的结构问题。
- **启示**：M1 的默认契约 = **(parent 分布, inspiration 分布) 两个采样器的参数化输出**，而非单一选择概率。

### 1.2 LoongFlow：熵调温 Boltzmann + 反重复 sample_weight

- **公式**（arXiv:2512.24077 §3.4/§4 + 仓库 base_memory.py）：`P(s_i) ∝ exp(R(s_i)/τ)`，**温度由种群熵动态调制**：`τ = τ_base·(1 + α·e^{−β·H_k})`（H_k = 岛 k 的档案熵）；dim05 一手实现补充：`p ∝ exp((score−max_score)/τ)·sample_weight^power`——**sample_weight 把"被采样次数"作为反重复压力项**。另有 ε=0.2 随机探索 + elite:non-elite=3:2 候选构造。
- **证据**：adaptive sampling 最终得分 0.7182，**比 top-k 高 10.99%、比 random 高 58.26%**；第 40 代即超 random 峰值（random 需 900 代）【一手：FM Agent arXiv:2510.26144 §6 消融，经 dim05 回溯】。
- **启示**：① 多样性不直接进选择概率项，而通过**温度这个全局旋钮**间接注入（"压力→温度→分布锐度"的三段式，是本调研里最干净的探索/利用解耦）；② sample_weight 是 children_count 的软惩罚版，与 DGM 硬项互补。

### 1.3 ShinkaEvolve：加权采样（分数 sigmoid × 子代倒数）+ 幂律 + beam

- **公式族**（arXiv:2509.19349 §3.1，ICLR 2026）：
  - **power_law**：`p_i = r_i^{−α} / Σ r_j^{−α}`（r=排名，α=0 即均匀，α→∞ 即 hill-climbing）；默认 `exploitation_alpha=1.0`。
  - **weighted**：`s_i = σ(λ·(F(P_i) − median(F)))`（sigmoid 压分，λ=10.0 控制选择压力），`h_i = 1/(1+N(P_i))`（子代数倒数作新颖项），`p_i ∝ s_i·h_i`。
  - **beam_search**：`num_beams=5`。
  - 配套 `exploitation_ratio=0.2`（以 0.2 概率从 archive 而非 population 采 parent）；**岛先均匀采样**，再岛内采 parent/inspirations（top-K + random archive）。
- **证据**：Fig.9 消融——加权父采样优于随机搜索与爬山；新颖性拒绝是收益最大单项，加权父采样次之【一手】。
- **启示**：**"分数项×新颖项"的乘积公式**是 DGM/OpenRSI/ShinkaEvolve 三系统收敛的公式形态（见 §2）；排名幂律 vs sigmoid 加权是"压力参数化"的两种等价路线，sigmoid 版对分数尺度更鲁棒（先减中位数再 sigmoid）【推断】。

### 1.4 DGM：分数 × (1+子代数) 的开放档案采样

- **公式**（arXiv:2505.22954 §C.2）：父代选择概率 **∝ 分数 × (1 + 拥有代码编辑能力的子代数)** 的近似权重，保证档案中所有 agent 被选概率非零。
- **注意方向差异**：DGM 的子代数项是**奖励**（子代多=该节点已被证明可拓展=stepping stone 价值高），ShinkaEvolve 的 h_i 是**惩罚**（子代多=已榨取=让位给少子代者）——同一字段两种符号，背后是"树档案永久保留"vs"固定容量档案"的结构差异【推断：永久档案下子代数=价值信号；淘汰档案下子代数=拥挤信号】。
- **证据**：去 archive 消融（hill-climbing）显著退化（§4.3）。

### 1.5 GEPA：per-instance Pareto + 覆盖数比例采样

- **公式**（arXiv:2507.19457 §3.3，ICLR 2026 Oral）：frontier = 在至少一个验证实例上取得最优的候选集合；亲本采样**按实例覆盖数（赢得的实例数）比例**随机采样，非贪心取最优。
- **证据**：Pareto 采样 vs SelectBestCandidate **+6.4%**（最高 +8.17%）；贪心基线"立即改进一次后停滞，耗尽预算反复锤同一候选"（Fig.6a）——纯 exploit 失效路径的直接一手证据【一手】。
- **启示**：覆盖数比例采样 = "利用强度由覆盖广度自动调节"（赢得多→被采多，但 frontier 上所有非支配候选概率非零）；与分数加权不同，它对**标定不可比的多实例分数**天然免疫【推断】。

### 1.6 FunSearch：cluster-softmax 温度退火 + 周期性重置

- **公式**：`p(cluster) ∝ softmax(cluster_score/T)`，`T_init=0.1`，随已注册程序数线性退火（`period=30000`）【一手：官方仓库 config.py】。
- **相位行为**：无显式相位；探索/利用的时间结构完全编码在**温度退火日程**里。多样性维护靠 `reset_period=4h` 杀最半岛+founder 重播种（重置即"定期强注入多样性"的粗粒度实现）。
- **启示**：温度退火 = 把相位调度**压缩进单个标量日程**（无需离散相位状态机）；代价是不可响应搜索状态（日程是开环的，LoongFlow 的熵调温是闭环版）【推断】。

### 1.7 RelayEvolve：Grow–Deepen bandit + Relay Gain 三重消费

- **公式/机制**（arXiv:2608.05651）：便宜模型多轨迹探索，按 h 代一块；**Grow–Deepen bandit**（Grow=共享 meta-arm 开新轨迹，Deepen(i)=轨迹 i 延一块；recent-window UCB，窗口 w，初始 Grow 收益不计入统计因受入档顺序污染）；奖励 = **Relay Gain** g_t = F(S_{t+1}) − F(S_t)，即在线 relay bank（|S|≤k，top-r 质量+多样性覆盖的单调子模目标，贪心+局部交换 (1−1/e) 保证）的边际改进；handoff 触发 = **Relay Gain 持续低** 或便宜预算耗尽。
- **证据**：4 benchmark × 3 预算 11/12 设置均值最高；便宜模型前 20 代捕获强模型 0.82–1.01× 进展；强模型预算占比默认 0.85 最优（过多过少都降分）；**call 级 bandit 被证明近视**（"逐 call 路由是错的问题"）【一手】。
- **M1 侧归属裁决**（与 M4-P17 一致）：relay bank 的**结构与估值归 M4**；**Grow/Deepen 决策、handoff 时机判据归 M1**；移交预算记账归 M3。本系统给出最重要的相位调度先例：**handoff 的最优信号源是档案估值曲线（Relay Gain），不是预算比例或 wall-clock**。

### 1.8 相位/收敛消费方：MOSS Verdict 与 M9 门信号

- **MOSS**（newworks_groupC）：Verdict ∈ {CONVERGED, NEED_MORE_WORK, FUNDAMENTAL_LIMIT_MODEL, FUNDAMENTAL_LIMIT_ARCHITECTURE} 枚举 + plateau guard（plateau_no_improvement_iters 1/2/3 随 depth tier 缩放）；depth tier 联动 max_iter 3/5/8、n_trials 2/3/5。**门输出枚举而非 bool**——"根本性限制"类 verdict 对 M1 是"停止并换方向"信号而非"再试一次"信号。
- **M9 轴 A4**（m8m9 groupC）：判定规则含 mSPRT 序贯统计门（always-valid，pₙ≤α 即停仍控 Type I）、ROPE 最小有意义改进 δ、ASHA 相对排名门（top-1/η，η=4 默认）——这些机制产出 M1 消费的**停止/降级信号**，机制本身归 M9。
- **边界确认**：收敛检测的**统计机制归 M9/M8**；M1 负责**消费 verdict 后的相位动作**（切阶段/停岛/重分配）。

### 1.9 多保真与探针驱动分配（AutoML/HPO 传统）

- **ASHA/Hyperband**（Li et al., MLSys 2020）：rung 内相对排名 top-1/η 晋升（η=4），"有晋升即晋升否则开新配置"；OpenEvolve 级联评估 thresholds 0.5/0.75/0.9 相对当前最优自动收紧（经 m8m9 groupC W4）——**分配决策的证据形式是 rung 内排名而非绝对分数**，对评估噪声更稳健。
- **POCAII**（arXiv:2505.11745）：显式分离搜索相位与评估相位，"前期重搜索、后期重评估"，低预算下超 SMAC/BOHB/DEHB 且方差更低——相位式预算形状（前探后收）在 HPO 传统里有独立证据。
- **Diffuse AI Control**（arXiv:2606.08892）：MO-ASHA 用于多目标 prompt 优化，滑窗排名晋升（rung0 最近 640 次评估中 top160）——滑窗相对排名在 LLM 评估噪声下的一手用法。
- **KernelBrain**（arXiv:2608.02611）：coarse-to-fine，scheduler 排名晋升 + "ranking 与 mutation 分离"——晋升决策 budget-aware、代码编辑 diagnosis-guided，与 M1（调度）/M2（变异）切分同构。

### 1.10 退化/对照与主动多样性注入

- **Simple Baselines**（arXiv:2602.16805）：SCS 无适应度选择、周期性 restart，~100 题验证集下与 ShinkaEvolve/ADAS 无显著差异（P=0.49）——**M1 策略的全部复杂性以评估统计可靠性为前提**；restart 本身就是最简相位循环。
- **VRP 塌缩**（arXiv:2604.07872）：纯适应度贪心父选 **3 代内**种群塌缩——exploit 全开的失效下界。
- **机器人 BT 进化**（MDPI Robotics 15(5):98）：监督策略按种群状态动态切换——缺优质个体时提变异率+注入专才 BT；多行为能力出现后转向整合；**停滞/多样性塌缩时升变异率+偏向稀有行为原型注入**——restlessness（主动注入多样性）的完整控制逻辑先例（8 档变异率表，危机档 0.45–0.50，经 m4 groupA §1.12 回溯）。
- **ShinkaEvolve 动态岛繁殖**：stagnation_threshold=100 代无改进→新岛 spawn（initial/best/archive_random 三种播种策略）——**停滞信号→结构级探索注入**的离散实现。
- **Verbalized Sampling**（arXiv:2510.01171）：对齐后生成多样性 −76%——M1 注入多样性策略的上限被 M2 变异供给端先验封顶（多样性压力开再大，生成端给不出差异也无效）【推断】。

### 1.11 AVO 阴性定位：Sample 仍是固定算法过程

- **AVO**（Agentic Variation Operators，2026-03）明确指出：AlphaEvolve/LoongFlow 等系统的 **Sample（亲本选择）仍是固定算法过程**，LLM 只参与 Generate——没有任何系统把亲本选择公式本身交给 LLM/学习层动态改写【一手综述判断】。即：M1 公式是"被配置/被调度"的对象，不是"被生成"的对象——这与 DGM"archive/父选择机制刻意冻结不可自修改"（§3）互为印证。

---

## 2. 跨系统综合：M1 切分假设的验证/修正

1. **亲本选择公式族收敛为"分数项 × 拥挤/新颖项"乘积式**：ShinkaEvolve `σ(λ·Δscore)·1/(1+N)`、DGM `score·(1+children)`、OpenRSI `reward·子代方差·rarity`、LoongFlow `exp(Δscore/τ)·sample_weight^p`——四个独立系统同构。M1 统一公式的候选形态：**`p_i ∝ f(score_i − ref) · g(children_count_i, rarity_i)`**，ref 取 median/max/当前最优；f ∈ {sigmoid, exp/τ, rank^{-α}, 覆盖数比例}；g 的符号方向由档案淘汰策略决定（永久保留→正，容量淘汰→负）【推断】。
2. **探索/利用的三条独立实现路线**：(a) 混合比例（OpenEvolve 0.7/0.2/random，硬编码配比）；(b) 温度标量（FunSearch 开环退火 / LoongFlow 熵闭环）；(c) 结构（岛隔离 + 迁移/重置/繁殖）。三路可叠加（LoongFlow 同时用 ε=0.2 + Boltzmann + 岛）；温度路线最省状态、结构路线最抗塌缩（VRP 3 代塌缩 vs EvoDiverse 交换后多样性↑且 best 不降）。
3. **相位调度的信号源裁决**：直觉用预算比例/wall-clock 切相位；RelayEvolve 一手证明**档案估值曲线（Relay Gain 边际改进）比成本曲线更早更准地宣告相位终结**——M1 相位判据的默认输入应是档案侧边际收益信号，预算耗尽作兜底触发。
4. **决策粒度下限**：RelayEvolve"call 级 bandit 近视"——分配决策的最小粒度是**块/轨迹级**（h 代一块），不能到逐调用级；ShinkaEvolve 的 proposal/eval/db 三池配额同向佐证。
5. **停止判据的分层**：预算耗尽（M3 记账，硬停）→ 收敛检测（M9 verdict + plateau guard，统计机制归 M8/M9）→ **边际收益停止**（Relay Gain 饱和 / FunSearch 退火到底 / MOSS plateau guard，M1 可主动决策早停并把剩余预算意图交还 M3）。M1 的职责是消费 verdict 做**相位动作**（停岛/切档/重分配），不是自己实现统计检验。
6. **M1 公式本身不可自进化**：AVO 综述判断 + DGM 冻结声明——M1 的策略参数可被调度/配置，但公式结构在运行期冻结（安全与可归因性）；进化 M1 配置是离线/meta 层的事。
7. **评估可靠性前提**（与 M4/M9 共享的最大约束）：SB P=0.49——小验证集下所有选择策略退化为随机；M1 任何非默认取值须以"跑赢退化投影（SCS/纯随机采样）且增量超 M8 噪声底"为启用前提。

---

## 3. M1 候选轴系初稿（S# 编号，14 条）

> 每条：定义 / 候选取值 / 证据锚点 / 暂定默认值。M1 输出**意图**（亲本分布参数、相位动作、分配比例），执行与记账归下游。

| # | 轴 | 定义 | 候选取值 | 证据锚点 | 暂定默认值 |
|---|---|---|---|---|---|
| S1 | **亲本选择公式形态** | M1 的核心输出：parent 采样概率的函数族 | `three_way`（exploit0.7/explore0.2/random） / `weighted_sigmoid`（σ(λΔF)·h(children)） / `power_law`（r^{−α}） / `boltzmann`（exp(ΔF/τ)·sample_weight^p） / `coverage_proportional`（Pareto 覆盖数比例） / `fitness_times_children`（DGM） | ShinkaEvolve 消融（arXiv:2509.19349 Fig.9）；GEPA +6.4%（arXiv:2507.19457）；LoongFlow +10.99% vs top-k（arXiv:2510.26144） | `weighted_sigmoid` + 保留 `three_way` 作兼容投影（OpenEvolve 契约为最大存量约定） |
| S2 | **新颖/拥挤项的方向与形式** | 乘积公式中 g(children_count, rarity) 的符号与参数化 | `penalty_inverse`（1/(1+N)，容量档案） / `bonus_linear`（1+N，永久树档案） / `soft_weight`（sample_weight^p） / `none` | DGM §C.2 vs ShinkaEvolve §3.1 的方向对照；OpenRSI reward×子代方差×rarity | 由 M4 档案淘汰策略联动：淘汰制→`penalty_inverse`；永久制→`bonus_linear` |
| S3 | **探索/利用调节旋钮** | 压力如何随时间/状态变化 | `fixed_ratio`（固定配比） / `open_loop_anneal`（温度日程退火） / `closed_loop_thermostat`（种群熵→τ 闭环） / `structural`（岛隔离+迁移承载，旋钮只微调） | FunSearch T0=0.1 period=30000 开环；LoongFlow τ=τ_base(1+αe^{−βH}) 闭环 | `closed_loop_thermostat`（闭环严格优于开环且成本低【推断】，LoongFlow 消融支持） |
| S4 | **double selection（亲本/灵感分采）** | parent 与 inspirations 是否用不同分布 | `shared`（同分布） / `split`（parent 偏 exploit，inspirations 偏 explore+topK） | OpenEvolve double selection（一手配置）；ShinkaEvolve inspirations=elite/top-k/archive+crowding | `split`（零成本多样性增益，双系统收敛） |
| S5 | **岛选择分布** | 先选岛再选个体内，岛级概率 | `uniform` / `proportional`（按岛 best/大小） / `weighted`（按岛近期收益） / `bandit`（岛=arm） | ShinkaEvolve 岛 uniform；RelayEvolve 轨迹=bandit arm（Grow/Deepen） | `uniform` 默认 + `bandit` 可选（轨迹/岛数量多时启用） |
| S6 | **分配决策粒度** | M1 做分配决策的最小单位 | `per_call`（逐调用，反例） / `per_block`（h 代一块） / `per_phase`（相位级） | RelayEvolve"call 级 bandit 近视"（arXiv:2608.05651）；块级 Grow–Deepen 为正面 | `per_block`（h 可配，默认 ~10 代量级【推断】） |
| S7 | **跨轨迹/跨岛分配机制** | 多条搜索线间的预算意图怎么分 | `fixed` / `grow_deepen_bandit`（recent-window UCB，奖励=边际改进） / `proportional_to_gain` / `restart_cycle`（SCS 周期重启） | RelayEvolve 11/12 最优；初始 Grow 收益受入档顺序污染须剔除统计（一手细节） | `grow_deepen_bandit`（多轨迹场景）；单轨迹退化为 `fixed` |
| S8 | **相位模型** | 搜索过程是否分显式阶段 | `single_phase`（无相位，全由温度/配比连续调节） / `two_phase_relay`（便宜探索→强模型精化，handoff 一次） / `three_phase`（构想→利用→收尾） / `cyclic_restart`（周期重启循环） | RelayEvolve 两相位+handoff；POCAII 前探后收（arXiv:2505.11745）；FunSearch 单相位+退火 | `two_phase_relay`（多模型档位场景）；单模型时 `single_phase+closed_loop` |
| S9 | **相位切换判据** | 何时切相位/何时 handoff | `budget_fraction`（预算比例，反例） / `wall_clock`（反例） / `marginal_gain_saturated`（Relay Gain 持续低） / `verdict_driven`（消费 M9 CONVERGED/plateau） | RelayEvolve：档案估值曲线比预算曲线更早更准；MOSS plateau guard 1/2/3 随 tier 缩放 | `marginal_gain_saturated` 为主 + `budget_fraction` 兜底（强模型预算占比默认 0.85 量级【一手：RelayEvolve 消融】） |
| S10 | **停止判据消费** | M1 如何响应停止信号并主动早停 | `budget_only`（M3 耗尽硬停） / `+verdict`（消费 M9 枚举 verdict：CONVERGED→收尾，FUNDAMENTAL_LIMIT→换方向） / `+marginal_utility`（边际收益低于阈值主动停，剩余预算意图交还 M3） | M9 轴 A4（mSPRT/ASHA 排名门机制归 M9）；GEPA `max_metric_calls`；RelayEvolve 饱和停 | `+verdict+marginal_utility`（M1 只做相位动作，统计检验不做） |
| S11 | **restlessness（主动多样性注入）** | 何时主动打破当前搜索重心 | `never` / `stagnation_spawn`（停滞→新岛/新轨迹，threshold~100 代） / `diversity_floor`（档案熵/嵌入覆盖低于阈值→升 τ/升 explore 比/注入随机亲本） / `periodic_reset`（FunSearch 4h 杀半岛） | ShinkaEvolve 动态岛繁殖（arXiv:2509.19349）；MDPI 15(5):98 危机档变异率 0.45–0.50；Verbalized Sampling −76% 供给端上限（arXiv:2510.01171） | `stagnation_spawn + diversity_floor`；`periodic_reset` 弃用（dim06 §3.7"重置太粗暴"） |
| S12 | **退化自检触发** | 何时验证 M1 配置未退化为随机 | `resident_probe`（SCS/均匀采样投影永驻对照，定期比对） / `pre_activation`（非默认取值启用前要求跑赢基线） / `none` | SB P=0.49（arXiv:2602.16805）；VRP 3 代塌缩（arXiv:2604.07872）；与 M4-F15 同构 | `resident_probe`——增量须超 M8 噪声底才允许维持非默认配置 |
| S13 | **分配意图的输出形式** | M1→M3 的接口形态 | `ratio_table`（固定比例表） / `intent_queue`（带优先级的块级分配意图流） / `budget_split_curve`（按相位/轨迹的预算曲线函数） | RelayEvolve 强模型预算占比 0.85 消融；POCAII 相位化预算形状 | `intent_queue`（块级，与 S6 对齐；M3 负责记账与拒绝） |
| S14 | **M1 自身可进化性** | M1 公式/参数在运行期是否可被搜索过程修改 | `frozen`（公式结构冻结，参数按调度表/闭环规则变化） / `meta_evolvable`（离线 meta 层进化配置） / `self_modifiable`（运行期自改，反例） | DGM §3 刻意冻结；AVO 判断"Sample 仍是固定算法过程"；DGM/AIDE² 对自改的谱系审计要求 | `frozen` + 离线 `meta_evolvable`（运行期只许参数级调节，不许结构自改） |

**轴间耦合备忘**：S1×S2（公式形态决定拥挤项接口）×M4-F7（字段供给契约）；S3×S11（闭环调温与 restlessness 共用熵信号，避免双重注入）；S6×S7×S13（粒度-机制-输出形式三者必须同块级）；S8×S9×S10（相位模型决定切换判据与停止消费的可选值）×M4-P17（handoff 打包归 M4）；S12×全体（评估噪声底是任何非默认取值的启用前提，与 M4-F15/M9-A4 三方对齐）。

**空缺标注（诚实边界）**：
1. 各公式族之间**无一手同预算同任务横向消融**（ShinkaEvolve 内部有 weighted vs power_law vs beam 消融但只在 circle packing 等少数任务）——S1 默认值置信中等。
2. 跨任务分配（多任务间调度）一手材料稀少：本调研仅覆盖跨岛/跨轨迹/跨相位，跨任务调度（课程式）未找到 2025–2026 LLM 进化场景的直接一手先例——S7 未含课程式取值，留待 B/C 组或标注为开放问题。
3. Relay Gain 的"饱和"阈值（持续低多少代判 handoff）论文给机制未给通用常数——S9 默认值为方向性结论。
4. 熵闭环调温的 α/β 常数仅 LoongFlow 单系统先例，跨域稳健性未验证【推断】。

---

## 参考来源（一手）

- OpenEvolve：github.com/algorithmicsuperintelligence/openevolve（default_config.yaml / database.py）
- LoongFlow：arXiv:2512.24077 + 仓库 base_memory.py；FM Agent：arXiv:2510.26144
- ShinkaEvolve：arXiv:2509.19349（§3.1, Fig.9）+ SakanaAI/ShinkaEvolve（config.py）
- GEPA：arXiv:2507.19457（§3.3, Table 2, Fig.6）
- DGM：arXiv:2505.22954（§C.2, §4.3）
- FunSearch：Nature 2023/2024 + google-deepmind/funsearch（config.py）
- RelayEvolve：arXiv:2608.05651（§Empirical Motivation, Method, Ablation）
- MOSS/PAST-Bench：本地 newworks_groupC；M9 门机制：m8m9/groupC（mSPRT arXiv:2509.07892、ASHA Li et al. MLSys 2020）
- POCAII：arXiv:2505.11745；Diffuse AI Control（MO-ASHA）：arXiv:2606.08892；KernelBrain：arXiv:2608.02611
- Simple Baselines：arXiv:2602.16805；VRP 塌缩：arXiv:2604.07872；Verbalized Sampling：arXiv:2510.01171；机器人 BT：MDPI Robotics 15(5):98；AVO：papercache 2026-03（Agentic Variation Operators）
- 本地素材：research/m4/groupA、groupC、m4_axes_final（P17）、m4_deepdive_part3；research/m2/groupA（O2/O11）；research/m8m9/groupC；research/dim00-08/dim05、dim06；research/newworks15/groupC
