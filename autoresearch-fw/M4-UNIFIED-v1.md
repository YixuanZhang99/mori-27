# M4-UNIFIED-v1.md — 统一前沿/档案（探索状态物理承载）模块设计文档

> 依据：`../research/m4/m4_axes_final.md`（20 轴定稿 P1–P20）、`../research/m4/m4_deepdive_part1/2/3.md`（逐轴深挖）、`../research/m4/m4_分歧_公理.md`（七分歧裁决 + 公理 E1–E12 + 根因对账 + I-可逆候选不变量）、`../research/m4/groupA_frontier_design.md` / `groupB_frontier_failures.md` / `groupC_frontier_new.md`（原始调研）。结构与风格对齐 `M2-UNIFIED-v1.md` / `M8M9-UNIFIED-v1.md` / `M5-UNIFIED-v1.md`。所有数字引自上述底稿，不确定处标【推断】或降级措辞。
> 定位：M4 Frontier 的最终形态设计。回答一个问题——**FunSearch 的岛隔离 / OpenEvolve 的 MAP-Elites×岛 / GEPA 的 per-instance Pareto / DGM 的档案树 / EvoDiverse 的多池交换 / EvolveNet 的联邦合并这些经典设计能否被同一个实现兼容？答案：能。它们之间的差异全部是配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 ArchiveEntry/FrontierView/ParentPool/ArchiveHealthProbe/MergeEvidence 数据模型与双资格位/驱逐三字段/谱系四元组记账规则（内核，不可换）+ 健康探针仪表盘与退化基线自检（内核，永驻）+ 策略注入点一等接口（"Database 即算法"但结构-策略禁焊死）+ 二十轴编译成的 profile（配置）+ 双速调度与档案经济学协议（运行时）**。
> 模块定位公理（B 组根因 4）：**M4 的设计目标不是"保管最好的"，而是限制任何单点失效（塌缩/hacking/噪声）的传播半径**——M4 不产生新失效，但决定上游失效是孤立事件还是种群级事故。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条既有框架级不变量 + 两个候选（建议上收 CLAUDE.md）

以下四条不变量横跨 M5/M8/M9/M2 四模块独立出现（与 M2-UNIFIED §0.0 逐字一致）；第五候选 I-披露由 M2 提出；M4 经根因对账后贡献第六条**候选**不变量 I-可逆：

1. **不变量 I-α（锚点存在性）**：框架内任何被优化压力触及的积累物必须配一个物理上不可被该压力修改的锚点组件。→ M4 侧投影：跨 run 合并的共享锚点集重标定（P16/F-B14，呼应 M8 系 A16）；P15 退化基线投影（SCS/单链）永驻。
2. **不变量 I-β（质量指标一等化）**：任何裁决/积累机制必须暴露其判别质量指标；"机制动作次数"不得作为健康证据。→ M4 侧投影：**P19 档案健康探针族是 M4 版的 gate_quality_probe**——"档案健康从未被独立测量"与 M9 侧 E7 根因、M2 侧 O20 根因是同一抽象失效的第三个投影；M4 把 I-β 的适用域从"裁决/生产机制"闭合到**纯存储结构**（档案连"动作"都没有，只有状态，仍须健康指标）。另：E10 资格位分离证明 I-β 的质量指标必须**按用途分资格位**物化（进档证据 vs 供亲权重的质量要求不同，供亲权重的错误按谱系复利）——物化形态贡献，不上收新原则。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：→ M4 侧投影：失败/驱逐判定只来自环境事实（compile/run），LLM 判断只做优先级排序、不做入库硬过滤（E5，AIDE is_buggy 误杀教训，与 M2-C11 逐字对齐）。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：→ M4 侧投影：谱系四元组 {祖先链, 变异算子与 diff, 上下文配方, 评估环境版本} 强制入 X1（E8）；跨 run 谱系边标"异源"（新增谱系类型）；驱逐/资格剥夺留可恢复路径而非删除。
5. **候选不变量 I-披露（信号通道最小披露）【候选，M2 提出，待框架级确认】**：→ M4 侧投影：亲本池字段最小供给（P7 契约之外的数据须经契约变更，不私开信道）；档案台账元数据（驱逐记录、探针读数）永不进变异 prompt（与 M2-C8 消费侧镜像）。
6. **候选不变量 I-可逆（不可逆操作滞后于证据成熟度）【候选，M4 提出，待框架级确认】**：框架内任何不可逆或高恢复成本的状态变更操作（驱逐、覆盖、合并、删除、硬过滤），其执行门槛不得低于支撑证据的成熟度——证据未成熟（CI 未收敛、重评未完成、审计未跑）时，操作必须降级为可逆形态（软删除/quarantine/标记）或延迟执行；操作的不可逆性档位与所消费证据的 CI/重评状态在类型层绑定。**三投影论证**（上收判据=跨模块投影+各自一手失效证据）：(a) **M9 侧已物化一半**——Receipt 失效引擎（三绑 head_sha/base_sha/gate_graph_version + 失效条件①–⑤）与 B11"软证据作废、硬证据永存"是同一原则在**裁决层**的投影（一手证据：selective erasure 后 71.7% vs 69.9%）；(b) **M4 侧存储层独立证据链**——AIDE is_buggy 永久误杀（LLM 判断做不可逆硬过滤）、Justesen 2019 重评后空格（按不成熟证据做不可逆驱逐）、CMA-MAE archive threshold dynamics（瞬间替换杀 stepping stone），三个独立来源、失效形态各异（过滤/驱逐/替换）；(c) **M2 侧投影**——C11"失败判定只来自环境事实、保留复活通道"是该原则在算子治理层的措辞。与既有不变量的边界：I-谱系管记录层（写了什么、能不能作废），I-可逆管状态层（改了什么、能不能回来）；I-LLM 管判定来源，I-可逆管执行时机——AIDE is_buggy 案例需要 I-LLM 与 I-可逆同时在位才能完整解释【推断：措辞为建议稿，上收与否由框架定稿阶段裁决】。

> 根因对账备注：M4 根因 1（幸存者偏差制度化）→ E10 资格位分离，物化形态贡献不上收（单模块强证据不满足跨模块判据）；根因 2（健康不可内观测）→ 被 I-β 完全覆盖；根因 4（O/E 系汇流放大层）→ 模块定位公理而非候选不变量（详见 `m4_分歧_公理.md` 任务三）。

### 0.1 公理 E1–E12（失效证据 → 内核物化）

> 合并规则：F-B1+F-B6→E1；F-B11+F-B12→E7；F-B13+F-B14→E8。**E4/E9 降为 SHOULD**（岛参数零消融、易实例主导定量测量缺位）。16 条候选全部保留，无降级为实现建议的条目。

| # | 公理 | 强制级别 | 失效证据指认（关键数字） | 违反检测 |
|---|---|---|---|---|
| E1 | **亲本供给函数是一等配置：供给熵与供给浓度双指标常驻**——top-k 贪心供给为待证配置，须消融证明优于加权/分层采样后方可启用；浓度超阈触发档案压缩或供给函数切换而非继续烧评估预算 | MUST | ShinkaEvolve 消融 hill climbing 快速 plateau、新颖性拒绝为收益最大单项（arXiv:2509.19349 Fig.9）；VRP 纯 top 层供给 3 代窄化（arXiv:2604.07872）；EvoDiverse 结构缓冲无性能税（arXiv:2606.10587） | 供给函数不可配置或供给熵时序缺失=构建期报错；探针存在但超阈无治理动作记录=审计不通过 |
| E2 | **塌缩的开关归属档案侧：供给函数可热替换**——在不改动 M2 算子的前提下仅切换供给函数即可做因果对照实验；策略注入点为一等接口 | MUST | 同 E1（三个缓冲器全部住在档案层）；OpenEvolve 选择策略硬编码进 ProgramDatabase"换策略需改源码"为反例 | 供给函数切换需改 M2 代码=架构评审拒绝；P15 对照实验因耦合无法执行=构建失败 |
| E3 | **污染祖源可召回：祖源级谱系枚举**——任一档案成员被事后判定污染时，其全部后代谱系可枚举、可降级/标记/quarantine，而非仅删单点；跨 run 合入的污染以整批 quarantine 实现（召回粒度=run id） | MUST | RHB RL 模型 13.9% hacking 率（arXiv:2605.02964）；Countdown-Code 1% 污染祖源点燃灾难性作弊（转引 arXiv:2605.21384）；AIDE² 靠事后人工谱系审计才发现自毁（weco.ai 2026-07） | 谱系指针断裂的候选不得供亲（留档不供亲）；召回操作无 X1 记录=审计不通过 |
| E4 | **岛健康在岛间：跨岛距离时序 + 阶段感知迁移**——跨岛距离单调下降触发迁移率下调/岛重启；岛隔离维度（行为/策略/随机）显式声明，随机分桶不得冒充行为隔离；固定周期为待证默认 | **SHOULD** | 稠密通信拓扑加速早熟收敛（arXiv:2604.18005，多智能体域，迁移性【推断】）；FunSearch 岛数/周期无消融却被 PDE-SHARP 原样继承；MDPI 2026-05 需 5 种多样性机制才防住塌缩 | 岛划分维度未声明=配置评审拒绝；探针就位后仍以固定周期为唯一触发=降级警告 |
| E5 | **驱逐可证伪：容量治理原语 + 软删除 + 失败判定环境事实化**——禁止无界只进不出为默认；每次驱逐记录 {理由, 双方 CI, 可恢复路径}；硬删除默认禁止；失败/驱逐判定只来自环境事实，LLM 判断不做硬过滤 | MUST | CMA-MAE archive threshold dynamics 致早熟（arXiv:2205.10752）；Justesen 2019 朴素基线档案质量随时间退化、矫正重评后空格；AIDE is_buggy 生产级永久误杀 | 出现不可逆删除 API=构建期拒绝；驱逐记录三字段缺失=运行期拦截 |
| E6 | **前沿粒度与维护预算联立声明**——任何 per-instance/per-niche 前沿表示同时声明全量维护成本占评估预算的比例与上限；超阈自动降粒度（动态子集/分层抽样）；精度不得静默吃掉选择预算 | MUST | GEPA ~85–90% rollout 花在 per-instance 验证表维护，作者自承须动态子集（arXiv:2507.19457，原文明确） | 前沿维护成本无按代记账=审计不通过；超阈未降粒度且无豁免记录=报警 |
| E7 | **档案最小合法形态是多峰 + 回退一等操作**——best-so-far 单点档案禁止作默认；最小档案保留 ≥k 个表型可区分候选及其谱系；回退目标选择不被当前 best 分数否决 | MUST | DGM 去 archive 消融显著退化（arXiv:2505.22954 §4.3）；SB P(Shinka>IID RS)=0.49（arXiv:2602.16805）；hill climbing 早衰曲线（2509.19349） | frontier 配置退化为单指针=构建期拒绝；回退操作无谱系记录=审计不通过 |
| E8 | **谱系四元组不可缺省 + 跨 run 合并须重标定**——{祖先链, 变异算子与 diff, 上下文配方, 评估环境版本} 缺任一字段留档不供亲；不同 run/评估版本的分数不可直接比较，合并前过共享锚点集重标定，每候选标来源 run id、跨 run 谱系边标"异源" | MUST | AIDE² provenance 审计案例（weco.ai 2026-07）；OpenEvolve"恢复档案 ≠ 恢复生成档案的策略环境"；生态无跨 run 合并原语（阴性发现）；EvolveNet 无门控链式版本直接崩溃（arXiv:2608.04968） | checkpoint 恢复后四元组校验失败=拒绝供亲；未重标定的跨 run 分数进入同一排序=运行期阻断 |
| E9 | **实例按信息量加权，非均匀**——per-instance 前沿的实例按判别力（难/易、方差、覆盖度）加权；被单一噪声实现占据的席位带置信度标记，低置信席位不供亲 | **SHOULD** | GEPA 覆盖数比例加权规则的机制推论【推断成分中等】；易/难实例 Pareto 席位分布的定量测量在文献中缺位（GB 不确定性 2） | 席位置信度字段缺失=降级警告 |
| E10 | **双资格分离：进档靠分数，供亲与交付靠证据**——被污染探针/低置信标记的候选留档但剥夺供亲资格；供亲位写进 P7 亲本池契约（布尔位）；准入判定逻辑归 M9，M4 只存资格位并执行 | MUST | RHB 13.9%；1% 污染点燃作弊；Grillotti & Cully 2023 档案精英重测显著低于记录值——"最假的分数坐最重的亲本席位" | P7 契约缺供亲位=构建期拒绝；被标记候选进入亲本采样=运行期拦截 |
| E11 | **置信度一等字段 + 保守晋升 + 定期重评**——每档案成员携带 {评估次数, 分数 CI, 最后重评时间}（直接复用 M8 ReliabilityMeta 形态）；进入亲本池头部或最终交付须 CI 下界高于被替代者点估计；"一次评估终身有效"为禁止配置 | MUST | Justesen 2019 重评后空格；UQD Archive-Sampling 显著优于固定采样（arXiv:2302.00463）；Grillotti & Cully 2023 | CI 字段缺失=拒绝入档；重评预算为零且档案运行超阈值代数=报警 |
| E12 | **噪声底下不裁决：驱逐/保留不得低于联合噪声底**——分数差小于 M8 联合噪声底的决策视为不可裁决，触发重评或随机化，禁止按点估计静默执行；序贯检验的提前停止记录写入谱系 | MUST | SB P=0.49（噪声底下档案治理是无效劳动）；mSPRT×驱逐规则交互无公开测量（结构风险外推） | 驱逐记录中分数差 < 噪声底且无重评/随机化标记=审计不通过 |

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（双速调度 sync 禁 LLM / 档案经济学 / handoff 协议）│
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  操作面接口：insert / frontier_update / parent_supply /      │
│          evict / probe / merge / handoff / sediment                  │
│          每操作面三类实现：确定性 | LLM 辅助 | 自适应                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：grid×islands 默认拓扑 + 策略注入点（可热替换）      │
│          + 驱逐协议（CI 下界+软删除，硬删除 API 不存在）+ 资格位执行   │
│          + 健康探针仪表盘（P19 永驻）+ 退化基线自检（P15 永驻）+ X1    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：ArchiveEntry / FrontierView / ParentPool /    │
│          ArchiveHealthProbe / MergeEvidence                         │
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（驱逐协议/资格位/探针 self_mutable=false）
         ↑ Layer 3 标注 evolvability: strategies_only（供给函数可热替换，E2）
         ↑ 经典系统 = profile = Layer 3 策略选择 + Layer 4 配置
```

**M4 的模块分工**（轴系原则 4，刚性边界）：M4 管"探索状态的物理承载"（档案结构、前沿表示、岛拓扑、亲本池字段供给、治理原语、健康探针）；**选择公式/权重归 M1**（M4 只暴露策略注入点与字段）；**准入/准出裁决归 M9**（M4 只存资格位并执行存储侧后果）；**语义沉淀归 M5**（P14 只到衔接协议）；**亲本池字段契约写死对齐 M2-O11**。跨界处只留接口不留轴。

---

## 2. Layer 1：冻结数据模型

五个新类型。与既有类型的挂接：ArchiveEntry 消费 M8 EvalResult/ReliabilityMeta 与 M9 Receipt；ParentPool 供给 M1/M2；ArchiveHealthProbe 与 M2 DiversityProbe 字段级对齐；MergeEvidence 消费 M8 锚点机制与 M9 逐 item 准入门。

```python
# core/frontier/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

ArchiveTopology = Literal["single_pool", "islands", "grid", "matrix", "tree", "grid_x_islands"]  # P1
FrontierKind = Literal["cell_elite", "pareto_per_instance", "tree_leaves"]  # P2；best_so_far/none 不在合法取值集（E7）
FailureProvenance = Literal["env_fact", "llm_judgment"]   # 分歧 7 硬编码：llm_judgment 不得触发物理排除

# ---- 档案条目（P13/P20/P11 的核心 schema）----
@dataclass
class QualificationBits:
    """E10 双资格分离的类型层物化；判定逻辑归 M9，M4 只存位并执行（刚性边界）"""
    archived: bool = True                    # 进档位：分数门槛（宽门，对齐 M9"入库宽"档）
    parent_eligible: bool = False            # 供亲位：须持有效 M9 Receipt（未触发失效条件①-⑤）
    deliver_eligible: bool = False           # 交付位：保守晋升（CI 下界 > 被替代者点估计，E11）
    disqualify_reason: Optional[str] = None  # 剥夺理由（结构化可证伪，对齐 M9 rationale_ref/B8）
    # ★ 资格位=Receipt 状态的档案侧投影：evaluator_version epoch 边界 ⇒ parent_eligible 批量复位待重估

@dataclass
class ArchiveEntry:
    entry_id: str
    artifact_ref: str                        # 候选实体（代码/配置/harness）
    scores: dict = field(default_factory=dict)  # 评估分数（带 EvaluationCard 谱系，B11）
    reliability: Any = None                  # ★ E11：ReliabilityMeta{n_trials, ci95, noise_floor}
                                             #    + last_reeval_at 一等字段；CI 缺失=拒绝入档
    qualifications: QualificationBits = field(default_factory=QualificationBits)  # 三资格位
    # ---- 谱系四元组（E8/F-B13：缺任一字段可留档不供亲）----
    lineage: dict = field(default_factory=dict)
    # {ancestor_chain, operator_and_diff, context_recipe, eval_env_version}
    # ---- 拓扑坐标（P1/P3：双记账）----
    island_id: Optional[str] = None
    cell_coords: Optional[dict] = None       # MAP-Elites 胞格坐标（descriptor 值）
    tree_depth: Optional[int] = None
    # ---- 语义层（P18 默认档：artifact + plan/summary，LoongFlow Listing 1 先例）----
    plan: str = ""
    summary: str = ""
    strategy_embedding_ref: Optional[str] = None  # 语义嵌入（生成模型版本入谱系）
    # ---- 失败与软删除（P11/P10）----
    failure_provenance: Optional[FailureProvenance] = None  # 失败判定来源；env_fact 才可驱逐
    buggy_leaf: bool = False                 # 标记保留、不参选、可作 debug 亲本（×M2-O12）
    soft_delete: Optional[dict] = None       # {reason, both_sides_ci, recovery_path, depth_buffer_slot}
                                             # ★ E5 驱逐三字段强制；hard_delete API 不存在
    # ---- 跨 run 合并（P16）----
    source_run_id: Optional[str] = None      # 合并产物强制；缺失=拒绝入库（"异源"谱系边）

# ---- 前沿视图（P2：前沿是时变集合，不是属性）----
@dataclass
class FrontierView:
    kind: FrontierKind
    members: list[str]                       # entry_id 列表；入/出前沿事件留痕入 X1
    budget_share: float = 0.0                # ★ E6：全量维护成本占评估预算比例（按代记账）
    budget_cap: float = 1.0                  # frontier_budget_cap 一等字段；超阈自动降粒度
    granularity: dict = field(default_factory=dict)
    # pareto_per_instance 档：{n_instances, weighting: "uniform"|"info_weighted"(E9),
    #   seat_confidence: 低置信席位标记（低置信不供亲）}
    # cell_elite 档：{n_cells, descriptor_source: P6 取值}

# ---- 亲本池契约（P7 ★刚性：四固定字段写死对齐 M2-O11 + 第五过滤位）----
@dataclass
class ParentPoolEntry:
    entry_id: str
    island_id: Optional[str]                 # 固定字段①：支撑跨岛均匀/加权岛选择
    children_count: int = 0                  # 固定字段②：DGM §C.2 反精英加权（∝分数×(1+子代数)）
    rarity: float = 0.0                      # 固定字段③：新颖性加权供亲（ShinkaEvolve）
    per_instance_best: dict = field(default_factory=dict)  # 固定字段④：GEPA 覆盖比例采样
    parent_eligible: bool = False            # ★ 第五字段=过滤位（E10×P7）：类型层过滤，
                                             #   M1 采样公式永远看不到 False 的候选（不是权重归零）
    # 可选字段：sample_weight（LoongFlow）/ score_vector（P5 signature 素材）/ migrated 标记（P4）

# ---- 档案健康探针（P19 ★一等输出；与 M2 DiversityProbe 字段级对齐）----
@dataclass
class ArchiveHealthProbe:
    probe_kind: Literal["supply_entropy",            # ①供给熵+供给浓度（F-B1/F-B6）：看管 M4-1
                        "cross_island_distance",     # ②跨岛表型距离时序（F-B7）：看管 M4-4
                        "instance_discriminability", # ③实例判别力分布（F-B10）：看管 M4-5
                        "reeval_survival"]           # ④重评存活率（F-B15）：看管 M4-8
    generation: int                          # 异步下用注册计数代理（P12：无代边界）
    value: Any                               # float 或分布摘要（探针③为分布）
    alarm: bool = False                      # 超阈值；报警→治理动作/配置切换记录须入 X1（同 O9 契约）
    consumes: str = ""                       # 数据来源声明（亲本采样日志/岛标签/per-instance 表/重评记录）
    # 对齐要点：跨岛距离继承 DiversityProbe 嵌入禁令（默认 exact_match/behavioral proxy 口径）；
    # 探针③④判定合法性消费 M8 ReliabilityMeta.noise_floor；探针③④重评预算显式定价注册 M3

# ---- 跨 run 合并证据包（P16：合并是有失败模式的算法操作）----
@dataclass
class MergeEvidence:
    merge_id: str
    source_run_ids: list[str]                # 合并双方 run id（召回粒度=run id，E3）
    anchor_set_version: str                  # ★ 双前置(a)：共享锚点集重标定记录（F-B14，呼应 M8 锚点）
    recalibration_report: dict = field(default_factory=dict)  # 分数映射到公共尺度的校准报告
    item_gate_results: list[dict] = field(default_factory=list)
    # ★ 逐 item 准入门结果（判定归 M9，消费 per-item ItemResult.verdict 形态；无门控禁止合并）
    rollback_snapshot: str = ""              # ★ 双前置(b)：合并失败整体回滚依赖的可恢复快照（E5 就位）
    scope_typing: dict = field(default_factory=dict)  # scope-typed 合并语义：全局/域条件化（EvolveNet）
    # 全部合并事件为一等谱系事件入 X1；跨 run 谱系边标"异源"
```

**设计决定说明**：
- `QualificationBits` 三资格位对应 M9 的严格度三元组（入库宽/谱系相对/合并部署严，M8M9 分歧 5）——双资格分离不是发明新结构，而是把 M9 已有的严格度漏斗钉进 M4 的数据结构。`parent_eligible` 是**类型层过滤位而非权重**——权重归零仍可被调参复活，类型层过滤不可【推断：对齐 M2/M9"类型层白/黑名单不可配置关闭"先例】。
- `ParentPoolEntry` 四固定字段过度供给严格占优：每个字段对应一个已被消融验证的选择机制（DGM 反精英加权/ShinkaEvolve 新颖性/GEPA 覆盖比例/岛模型分层），字段缺位=该机制在 M1 侧永久不可启用，而边际存储成本≈0。`per_instance_best` 是唯一有预算语义的字段（GEPA 85–90% 预算税），字段供给与维护强度解耦【推断】。
- `failure_provenance` 与 `soft_delete` 是 I-可逆候选不变量的类型层绑定：`llm_judgment` 来源的失败标记不得触发物理排除；驱逐三字段 {理由， 双方 CI, 可恢复路径} 缺一则运行期拦截；`hard_delete` 方法在类型层**不存在**（只有 deprecate/quarantine）。
- `ArchiveHealthProbe` 与 M2 `DiversityProbe` 共享 generation/value/alarm 骨架并加 probe_kind/consumes；O20 重复率台账看管变异器**输出端**，P19 探针①看管档案**供给端**——同一塌缩过程的两端读数，双读数交叉验证避免单端误判【推断】。
- `MergeEvidence` 的双前置硬门（锚点重标定 × 驱逐可证伪）是分歧 6 的物化——EvolveNet 证明分布化的价值几乎全部住在合并环节（DS-1000 合并 harness 比最强单 client +9.0 分；无门控链式合并直接崩溃回滚）。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 默认拓扑与策略注入点（P1/P8，分歧 1/5 落地）

- **默认拓扑 `grid×islands`**（AlphaEvolve/OpenEvolve/LoongFlow 三系统收敛形态）：每岛一张 MAP-Elites 网格，岛内胞格竞争 + 岛间隔离双缓冲——其本质是"双缓冲器冗余"而非"双机制叠加增益"。树形态（DGM）作为"免驱逐"特例保留为合法取值；`single_pool` 仅在 K=1 退化配置下合法；`best_so_far` 单点档案禁止作默认（E7）。
- **"Database 即算法"但结构-策略禁焊死**（E2）：拓扑选择=选择压力分布的选择，换拓扑≈换算法；OpenEvolve 把选择策略硬编码进 ProgramDatabase（"换策略需改源码"）为**反例**——它把"Database 即算法"从口号变成锁定，使"不动 M2 只切供给函数做因果对照"在该实现上不可能。内核硬编码：**供给函数可热替换为一等接口**（ShinkaEvolve `parents.py`/`inspirations.py` 策略族为正面先例）；拓扑切换、K/迁移参数变更=谱系事件入 X1。
- **P15 常驻退化自检**（分歧 1 前置，与 M2-O1 同构不同面）：档案结构按 SCS（每代随机 3 个前代程序拼 prompt、无 fitness 选择，Simple Baselines 形态）/单链表（incumbent+challenger，AIDE² 外环形态）投影**常驻对照，不可从构建中移除**；任何非单链拓扑/前沿/驱逐结构变更须跑赢投影且**增量超 M8 噪声底**才允许进默认配置（SB：P(Shinka>IID RS)=0.49）。剃刀砍错方向的防护：SCS 投影"赢"时正确响应是先质疑评估集规模（M8 侧）而非砍档案结构【推断】。与 M2-O1 共享退化基线实现与调度槽，但对照对象（档案结构复杂性 vs 算子集表达力）与报告通道独立，两模块退化台账不合并记账。

### 3.2 亲本三路采样骨架（P8，公式归 M1）

- **默认 `three_way(0.7/0.2)` + double selection**（OpenEvolve 生产验证配置）：档案维护三路采样所需的结构分区——exploit 路从 elite/岛 best 池取、explore 路从全库取、random 路均匀取；**parent 与 inspirations 分别采样**（供变异模板与供上下文多样性是两个不同采样目标，单路采样把 exploit 压力耦合进上下文【推断】）。0.7/0.2 为工程惯例值、**明确标注未消融**（整个 P8 超参层是暗超参）。
- **配比是结构分区的参数而非公式**（刚性边界）：选择公式/权重归 M1，M4 只供给三路分区与 `parent_sampler`/`inspiration_sampler` 两个独立注入点；M1 注入的策略只消费 P7 契约字段。
- **骨架×前沿绑定**：coverage_proportional 要求 pareto_per_instance 前沿在位（×P2）；cluster_softmax 要求 signature 聚簇在位（×P5）；三者是联合配置点而非三个独立旋钮。换前沿定义不换采样骨架=结构错配（GEPA +6.4% 是"前沿+采样"联合体的消融，不可全归给前沿【推断】）。
- 探针驱动的供给切换（供给熵超阈→切供给函数）为一等升级路径，默认关；切换必须按 C10 同型规则跑赢退化对照。每代供给函数版本+配比快照入 X1。

### 3.3 驱逐协议（P10×P20，分歧 4 落地；根因 3 最集中落点）

- **噪声底下不裁决**（E12）：驱逐/保留双方的分数差小于 M8 联合噪声底时，该决策视为不可裁决，触发重评或随机化，**禁止按点估计静默执行**；资格位冻结不变并触发重评请求（走 M8 级联）。
- **驱逐规则默认 `ci_lower_bound`**（CI 下界裁决）；点估计档仅在本代重评预算耗尽时降级使用并报警。
- **一切驱逐走软删除+深度缓冲**（CMA-MAE archive learning rate / UQD depth d=8/32 形态：抑制边际替换防 stepping stone 丢失）：标记、留谱系、留可恢复路径；**`hard_delete` API 不存在**（只有 deprecate/quarantine）；驱逐三字段 {理由， 双方 CI, 可恢复路径} 强制。容量默认 `population_limit + cell_competition`；无界只进不出禁止作裸默认（E5）。
- **定期重评预算为一等配置**，"一次评估终身有效"为禁止配置（E11）——"不重评"是被实验证明的失效配置（UQD：Archive-Sampling 显著优于固定采样）；档案内分数是虚高的系统性偏置而非无偏估计（Justesen 2019 重评后空格；Grillotti & Cully 2023 重测显著低于记录值）。

### 3.4 新颖性双阈值口径（P9，裁决①）

- **框架级以 M2-O8 的 0.95 起步 + 台账校准为准**：0.99（OpenEvolve/ShinkaEvolve 两系统惯例）拦的是**近似克隆**（变量重命名级重复），0.95 拦的是**近重复**（同思路小改）——两个闸在拦不同的东西【推断：0.99 为嵌入模型×去重目标差异的历史配置，不作框架默认】；M4-1 的失效形态（对当前最优做小改）只有 0.95 口径能拦。
- **闸的执行在 M2-O8 侧，M4 侧义务=维护档案嵌入索引**（增量更新、支持余弦近邻查询）+ 供给重复率台账的档案侧读数；台账校准归 P19（拒绝率 <5% 说明太松或变异器塌缩、>50% 说明变异器无新供给，两种情况触发算子/父代切换而非调阈值本身【推断】）。
- **承载冗余原则**：默认 `topology + novelty_gate` 双保险（行为树进化需 5 种多样性机制才防住塌缩，MDPI 2026-05——单一承载机制不足）；EvoDiverse 受控交换（+12%/+19% Top-10 AUC 且 best 不降）为可选档。先验层塌缩（对齐后多样性 −76%，arXiv:2510.01171）封顶任何承载机制能保护的多样性上限。

### 3.5 失败候选：环境事实判定 + 复活通道（P11，分歧 7 落地）

- **默认 `buggy_leaf`**：失败个体带标记入库——不参选（供亲位关闭）但可作 debug 亲本、留谱系可平反；**失败判定只能来自环境事实**（compile/run），LLM 判断只做优先级排序（先修谁）、不做入库硬过滤——is_buggy 式布尔硬过滤构建期拒绝（与 I-LLM、M2-C11 逐字对齐；AIDE is_buggy 永久误杀双重记录在案 M2-O12/M4-3）。
- `discard` 仅对环境事实失败且超深度缓冲上限的候选合法；阴性聚合库（IDEAgent R：不存个体存聚合失败模式）注册为 P18 取值，证据级别降级标注、默认关（增益【未复核】+ LLM judge 可信度警示）。
- buggy 标记与 P20 供亲位统一为同一资格位的两种触发源（环境失败 vs 污染嫌疑）【推断】；debug 复活通道上限可配（AIRA 参照值 10 节点或 12h，单系统经验值），消费接口归 M2-O12。

### 3.6 持久化：档案+策略环境双快照（P13）

- **默认 `full_db_snapshot`**：完整 DB + 岛状态 + bandit 状态 + **策略/prompt 版本**——恢复档案 ≠ 恢复生成档案的策略环境（M4-7：OpenEvolve 选择策略硬编码致版本漂移，恢复后的 run 与中断前不可比）。
- **谱系四元组是 checkpoint 的最小合法载荷**（E8）：{祖先链, 变异算子与 diff, 上下文配方, 评估环境版本} 写进类型层（缺任一字段的候选可留档不供亲）——靠纪律维系的持久化必然漂移（LoongFlow 把 `save_checkpoint` 写进抽象基类是同思路先例）。
- 异步档（P12 默认 `async_db_sole_sync`）下 checkpoint 是唯一一致状态切分点；快照间隔=最大可丢失进展量，为 M3 预算科目。陈旧注册（FunSearch 刻意忽略的先例）的容忍机制=migrated 标记+逐字查重。回归测试建议：断点续跑后前 N 个候选的分布应与原 run 统计不可区分【推断】。

### 3.7 M5 沉淀通道（P14 ★刚性边界：语义沉淀归 M5）

- **P14 协议本质 = 把 P13 已强制收集的字段再导出一份给 M5**：M4 侧产出"沉淀观察"（周期摘要 MetaSummarizer 形态 interval=10 / 谱系链摘要 lineage_digest 形态）→ 经 M5 `encode` 构造 MemoryEntry（**level=L2**——档案沉淀天然是跨实例模式层；state=candidate）→ 走 M5 默认 `admit: no_llm_gate`（只校验 schema+provenance 完整）。
- **provenance 强制无默认**：沉淀条目回填 {来源 run_id, 谱系链, 评估环境版本}，恰是 P13 四元组的字段复用——无 P13 四元组则沉淀过不了 M5 admit 校验（不可归因的记忆污染）。
- **沉淀资格=交付资格**：只有 `deliver_eligible=true` 的候选才允许产出沉淀【推断，由 F-B4/F-B15 推广】——否则被污染探索经验当 verified 记忆扩散到后续所有 run（M4-2 的跨 run 版）。
- 反向通道：变异 prompt 中的策略记忆经 M5 `retrieve` 供给（效用重排+状态过滤不可关闭），M4 不直连记忆库；meta_summary 的 LLM 调用入 idle/scheduled 槽，禁 sync 槽。默认 `none` + `meta_summary` 可选。正确启用序：**P13 → P20 → P14**。

### 3.8 跨 run 合并：双前置硬门（P16，分歧 6 落地）

- **默认单主体集中式**；合并档注册、默认关。开启跨 run 合并须先满足双前置硬门：**(a) 共享锚点集重标定**（分数跨 run 可比性由锚点建立而非假设；跨评估版本的候选分数默认作废、锚点重评分默认保留，呼应 M8 系 A16 锚点与 Receipt 失效条件④）；**(b) 目标档案驱逐可证伪**（软删除就位，合入错误可回滚）。
- 合并档案每候选标 `source_run_id`、跨 run 谱系边标"异源"（新增谱系类型，类型层强制）；逐 item 准入判定归 M9（刚性边界）；被污染 run 的跨 run 召回只允许以整批 quarantine 形态实现（召回粒度=run id，E3 联动）。
- **联邦式 delta+证据门控合并**（EvolveNet 形态：diff→机制分解→scope 分类→条件化组合→逐 item 证据准入门→失败整体回滚）为注册档：BIRD held-out 70.7% vs 等总预算集中式 67.3%（配对 14 胜 9 负）vs 等串行深度 68.7%——分布化的净收益（+2.0）小于合并协议的净收益（+9.0），无协议合并的收益是负无穷（崩溃回滚）。设计优先级：**先建合并门与重标定，再谈分布拓扑**。跨组织产权/联邦部署归框架层（刚性边界），M4 只到合并协议与 scope 语义。

### 3.9 移交估值（P17：Relay Gain）

- **默认无移交**；启用相位 handoff 时采用**子模目标估值档**（RelayEvolve 形态）：维护在线 relay bank（|S|≤k），以 top-r 质量+多样性覆盖的单调子模目标选移交子集（贪心+局部交换，(1−1/e) 保证）；**Relay Gain=bank 的边际改进**，同时反哺 bandit 调度、handoff 时机与种子集选择。
- **决策粒度=移交集级**：call 级 bandit 路由被证明近视（"逐 call 路由是错的问题"，LLM 调用状态耦合）——所有"便宜模型先试、贵了再升级"机制的硬性约束。定量锚：便宜模型前 20 代捕获强模型 0.82–1.01× 的进展（进展强前置）。
- handoff 时机归 M1 消费（M4 只暴露 Relay Gain 时序与移交集构造器）；移交预算归 M3；移交集须可快照（×P13）且成员须持交付资格（×P20——移交=交付的预备态，无交付位的移交集会把噪声高分快递给下一阶段【推断】）。与 M2-O19 共享 Relay Gain 信号但分别记账（M2 侧管算子经济学，本轴管档案侧打包与估值）。

### 3.10 证据日志（复用 X1，append-only）

与 M2/M5/M8M9 共用同一 X1 存储。每个候选携带：谱系四元组、拓扑坐标（island_id/胞格坐标/树深度）、资格位翻转事件与剥夺理由、驱逐三字段、前沿入/出事件、岛创建/繁殖/重置事件、供给函数版本+配比快照、合并事件与"异源"谱系边、探针读数跨代时序与触发的治理动作。**先建日志，后调策略**：所有档案操作从第一天就过台账记账（对照 M5-A5/M8M9 §3.3/M2 §3.6）。P19 是 M4 对 X1 的最大写入方之一；祖源级召回（E3）依赖谱系四元组完备。

---

## 4. Layer 3：操作面×实现类矩阵

八操作面（选择算法本身归 M1，M4 侧为结构供给与执行）× 三实现类：

| 操作面 | 确定性实现（默认与兜底） | LLM 辅助实现 | 自适应实现（opt-in） | 默认实现类 |
|---|---|---|---|---|
| insert（入档） | 分数门槛+CI 字段校验+嵌入去重索引写入 | LLM novelty judge（默认关，边际提升不值一次调用） | — | 确定性 |
| frontier_update（前沿维护） | cell_elite 同格替换 / per-instance 最优表增量更新 | — | 动态子集降粒度（E6 超阈触发） | 确定性 |
| parent_supply（亲本供给） | three_way 分区供给 + 资格位类型层过滤 | —（LLM 不参与亲本打分，M2-C9 镜像） | 探针驱动供给函数切换（E1，默认关） | 确定性 |
| evict（驱逐执行） | CI 下界裁决 + 软删除+深度缓冲；hard_delete 不存在 | LLM 只做重评优先级排序，不做驱逐判定（I-LLM） | — | 确定性 |
| probe（健康探针） | 供给熵/跨岛距离日志重放（近零成本）；重评存活率走 M8 级联 | — | 探针反馈治理（超阈自动动作；前置=误报率已校准） | 确定性 |
| merge（跨 run 合并） | 锚点重标定 + 逐 item 门执行 + 快照回滚 | LLM-merger（机制分解→scope 分类→条件化组合，EvolveNet 形态） | — | 确定性门 + LLM merger |
| handoff（移交打包） | relay bank 子模贪心+局部交换 | 移交集语义字段生成（plan/summary 补齐） | Relay Gain 驱动的自适应 handoff 时机（信号归 M1 消费） | 确定性 |
| sediment（M5 沉淀导出） | 谱系四元组字段复用导出 | meta_summary/lineage_digest 摘要生成（idle 槽） | — | LLM 辅助 + 确定性校验 |

**硬编码约束**：evict/insert 的资格判定无 LLM 终裁路径（I-LLM）；probe 反馈治理档继承 M9 同型纪律——**无校准数据的探针不得自动触发治理动作，只许报警**（治理档启用前置=仪表盘档误报率先被测量）【推断】；治理动作必须可回滚（对齐 M8M9"改变系统状态且必须可回滚"判据）。

---

## 5. Layer 4：双速调度 YAML

```yaml
# frontier/schedule.yaml
schedules:
  sync:                        # 关键路径，每次入档/驱逐/供给前后；硬约束：禁 LLM（对齐 M5 A4/M2 Layer 4）
    - op: qualification_filter # 资格位类型层过滤（parent_eligible=false 对 M1 不可见）
      constraint: no_llm
    - op: eviction_record      # 驱逐三字段强制记录 {理由, 双方 CI, 可恢复路径}；缺失=运行期拦截
    - op: noise_floor_check    # E12：分数差 < 联合噪声底 ⇒ 冻结资格位+触发重评请求（消费 M8）
    - op: novelty_index_update # 档案嵌入索引增量更新（供 M2-O8 闸消费）
  idle:                        # 默认档：空闲窗/代际边界（异步档以注册计数为"代"代理）
    - op: health_probe         # P19 四探针常驻报告（①②近零成本日志重放；③④按预算档位）
    - op: degenerate_baseline  # P15：SCS/单链投影周期性对照（永驻，不可移除；与 M2 共享实现不合并记账）
    - op: novelty_threshold_recal  # 重复率台账→阈值校准信号（0.95 起步，P19 消费）
    - op: frontier_budget_audit    # E6：前沿维护成本按代记账，超阈自动降粒度事件入谱系
    - op: sediment_export      # P14：meta_summary/lineage_digest 生成（LLM 调用只许在此槽）
  scheduled:                   # 可选：长程维护
    - op: archive_reeval       # E11：档案精英周期重评（Archive-Sampling 式；预算注册 M3）
      cron: "per_epoch"
    - op: lineage_recall       # E3：污染判定后的祖源级谱系枚举/降级/quarantine
    - op: merge_gate_audit     # P16：合并事件审计（锚点版本、逐 item 门结果、异源谱系边）

parent_sampling:               # 分歧 5：默认固定三路；公式归 M1
  scheme: three_way
  ratios: [0.7, 0.2, 0.1]      # 工程惯例值，明确标注未消融
  double_selection: true       # parent 与 inspirations 分采
  adaptive: false              # 探针驱动供给切换默认关；开启须跑赢退化对照

topology:                      # 分歧 1/3
  archive_topology: grid_x_islands
  island_count: 5              # 惯例中位数（10→5→3→2 谱系），明示非被验证最优点
  migration: {rate: 0.1, interval: [10, 50], trigger: periodic}  # 探针就位后切 probe_gated
  island_partition_dim: required  # E4：隔离维度（行为/策略/随机）显式声明，随机分桶不得冒充行为隔离

eviction:                      # 分歧 4
  rule: ci_lower_bound         # point_estimate 档仅在重评预算耗尽时降级并报警
  soft_delete: {depth_buffer: 8}   # UQD d=8/32 量级；hard_delete API 不存在
  reeval_budget: required      # "一次评估终身有效"为禁止配置（E11）

distribution:                  # 分歧 6：默认 centralized；cross_run_gated/federated_delta 注册默认关
  mode: centralized
  preconditions: [anchor_recalibration, eviction_falsifiable]  # 双前置硬门

handoff:                       # P17：默认无移交
  mode: none                   # fixed | submodular_relay（Relay Gain 驱动）
  eligibility: deliver_eligible_only

sedimentation:                 # P14：默认 none；沉淀资格=交付资格
  mode: none                   # meta_summary | lineage_digest（挂 M5 写入门禁，level=L2）
```

**与其他模块的协议钩子**：
- **M1**：P8 注入点（parent_sampler/inspiration_sampler）+ P7 字段供给；探针报警是 M1 切换父代公式/相位的触发信号；handoff 时机归 M1 消费；M1 的结构切换决策须附最近一次 P15 对照结果。
- **M2**：O11 亲本池四字段+供亲位契约写死对齐；嵌入索引供 O8 闸消费；buggy_leaf 供 O12 debug 消费；共享退化基线实现不合并台账。
- **M8**：噪声底/CI/ReliabilityMeta 是 E11/E12/P19③④的判定合法性来源；重评请求走 M8 级联调度；锚点机制供 P16 重标定。
- **M9**：资格判定、逐 item 合并门、保守晋升裁决全部归 M9；M4 只存位、执行过滤、上报事件；资格位=Receipt 状态的投影（epoch 边界批量复位）。
- **M3**：容量上限、重评预算、软删除缓冲深度、前沿维护成本、探针③④重评预算、快照频率均为显式定价的一等预算科目（档案经济学横切约束落点：档案大小按 token/注意力预算核算，不按内存核算）。
- **M5**：沉淀通道见 §3.7；M4 不直连记忆库。

---

## 6. 七分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | grid×islands vs 树/单池（P1） | 噪声底已知 × 需回退/对照能力 | grid×islands + 单链投影常驻自检 | `archive_topology` 枚举；拓扑切换=谱系事件 | P15 退化投影对照不可从构建中移除 | 非单链拓扑条件合法：增量须超 M8 噪声底 |
| 2 | Pareto-per-instance vs cell_elite vs 单链（P2） | 逐实例评估结构 × 维护预算占比 | 逐实例场景 pareto_per_instance，否则 cell_elite；best_so_far 禁默认 | `frontier_definition` + `frontier_budget_cap` 一等字段 | best_so_far/none 不在合法取值集（E7） | 前沿维护成本按代记账入 X1（与 M3 对账）；超阈自动降粒度 |
| 3 | K 与迁移：惯例 vs 待证（P3×P4） | 跨岛距离探针是否在位 | K=5（惯例中位数，明示非最优）+ ring(0.1, 10~50)；探针就位后切 probe_gated | `island_count` / `migration.trigger ∈ {periodic, probe_gated}` | 驱逐式 reset（杀半岛）让位于迁移+软重启；固定周期标注待证默认 | K/迁移参数变更与探针读数快照同时入 X1（治理可归因） |
| 4 | 驱逐：点估计 vs CI 下界+软删除（P10×P20） | 分数差 vs 联合噪声底 | CI 下界裁决 + 软删除+深度缓冲 + 重评预算 | `eviction_rule ∈ {point_estimate, ci_lower_bound}` | 驱逐三字段强制；hard_delete API 不存在；噪声底下资格位冻结 | 驱逐的消费方是资格位而非物理删除；序贯检验提前停止写入谱系 |
| 5 | 三路配比：固定 vs 自适应（P8） | 供给熵探针 × 增量超噪声底 | 固定 0.7/0.2 + double selection；自适应默认关 | `parent_sampling = {scheme, ratios, adaptive}` | 策略注入点一等接口（E2）；供给函数版本+配比快照入 X1 | 公式归 M1；M1 策略只消费 P7 契约字段 |
| 6 | 跨 run 合并门控（P16） | 锚点重标定 × 驱逐可证伪双前置 | 单主体集中式；合并默认关 | `distribution ∈ {centralized, cross_run_gated, federated_delta}` | 缺 source_run_id 的合并产物拒绝入库；跨 run 谱系边标"异源" | 合并事件 {run id, 锚点集版本, 逐 item 门结果} 进 X1；逐 item 判定归 M9 |
| 7 | 失败候选：保留 vs 硬删 vs 聚合（P11×P18） | 失败判定来源（环境事实 vs LLM 自判） | buggy_leaf；阴性聚合库默认关 | `failure_policy ∈ {discard, artifacts_only, buggy_leaf, negative_aggregate}` | `failure_provenance` 字段强制；llm_judgment 不得触发物理排除 | 复活通道（debug 消费）归 M2-O12；阴性聚合规则归 M5 |

---

## 7. 证据强度与投资优先序

**证据强度排序**（合并 Group A/B/C 结论与三批深挖，强→弱）：

1. **档案存在的价值本身**（DGM 去 archive 消融显著退化 arXiv:2505.22954 §4.3；GEPA Pareto 消融 +6.4% arXiv:2507.19457）——方向最强；但 SB P=0.49 划定边界：**全部增量以评估统计可靠性为前提**。
2. **驱逐/重评治理**（UQD Archive-Sampling 显著优于固定采样 arXiv:2302.00463；Justesen 2019 重评后空格；CMA-MAE threshold dynamics）——QD 域一手，LLM 代码进化域零实现先例。
3. **合并协议**（EvolveNet 70.7/67.3/68.7/+9.0，五 benchmark 全显著，换模型栈定性复现）——单系统但消融齐全；跨 run 通用协议零先例。
4. **移交估值**（RelayEvolve 11/12 设置均值最高；0.82–1.01× 前置规律；call 级 bandit 近视对照）——单系统。
5. **语义层**（SeaEvo +21%、跳出平台 26–30→42.94）——单系统单域，成分未分离。
6. **岛参数/迁移参数**（谱系 10→5→3→2、rate 0.1/0.2）——全线零消融，惯例继承。
7. **阴性知识档**（IDEAgent R）——【未复核】+LLM judge 可信度警示，最弱。

**投资顺序表**：

| 顺位 | 投资方向 | 依据 |
|---|---|---|
| **0（最高优先依赖，显式置顶）** | **P19 探针度量实现与标定** | B 组根因 2：四失效（M4-1/4/5/8）的共同根因是二阶指标全部缺失；四探针无一度量实现先例、阈值全线无标定——**探针缺失视同塌缩已发生**；且 P3/P4/P8/P10 的全部动态档触发器、E1/E4/E6/E11 的治理动作都锁死在 P19 就位上 |
| 1 | 资格位+CI 字段+驱逐协议（P20/E10–E12） | 幸存者偏差制度化的最小充分手术；RHB 13.9%、重评空格 |
| 2 | 谱系四元组+双快照（P13/E8） | 唯一使自毁类失效可发现的结构（AIDE² 审计）；P14/P16 的前置 |
| 3 | 亲本供给结构与字段契约（P7/P8） | ShinkaEvolve 父代消融三档排序；字段过度供给零成本 |
| 4 | 前沿粒度×预算联立（P2/E6） | GEPA 85–90% 预算税的一手教训 |
| 5 | 合并协议与重标定（P16） | 先建合并门再谈分布拓扑；阴性发现=设计机会 |
| 6 | 移交估值与语义层（P17/P18） | 单系统证据，增量档 |

---

## 8. Profile 兼容性验证（统一性的证明）

六个经典系统全部编译为 profile（Layer 3 策略选择 + Layer 4 配置），**无一处需要改内核**；每个 profile 诚实标注该系统实际违反的公理。

### 8.1 funsearch_island（岛隔离 + signature 聚簇）

```yaml
profile:
  name: funsearch_island
  axes: {P1: islands(10), P2: 无显式前沿(cluster-softmax 内编码), P3: K=10,
         P4: reset(4h 杀半岛), P5: signature(T0=0.1, period=30000), P8: cluster_softmax 两级,
         P11: discard, P12: async_db_sole_sync}
  topology: {island_count: 10, migration: {type: reset, period: 4h}, partition_dim: random}
  clustering: {signature: {T0: 0.1, period: 30000}}   # 逐测试得分向量排序元组；簇内均匀采样
  parent_sampling: {scheme: cluster_softmax, levels: [island_uniform, cluster_softmax, intra_cluster_uniform]}
  frontier: {kind: cell_elite}     # best-per-signature 即隐式 per-test 前沿，编译为 cell_elite
```
内核复用：signature 聚簇=P5 原生取值（评估确定场景的合法档）；物理岛+逻辑簇双分层=P1×P5 联合配置。
**公理违反标注**：原系统**违反 E1/E2（无供给熵探针且供给函数不可热替换）**、**违反 E5（discard 硬删+4h 杀半岛为不可逆驱逐无恢复路径）**、**违反 E11（无 CI 字段无重评）**；岛数/重置周期无消融论证却被 PDE-SHARP 生态原样继承（E4 失效超参继承案例）；陈旧注册被代码注释刻意忽略（P12 已知竞态）。【诚实标注】

### 8.2 openevolve_mapelites（grid×islands + 三路采样）

```yaml
profile:
  name: openevolve_mapelites
  axes: {P1: grid×islands, P2: cell_elite, P3: K=5, P4: ring_migration(0.1, 50),
         P6: evaluator_metric, P8: three_way(0.7/0.2)+double_selection,
         P9: novelty_gate, P10: population_limit(1000/100), P11: artifacts_only,
         P13: full_db_snapshot(seed=42, hash 隔离)}
  topology: {archive_topology: grid_x_islands, island_count: 5,
             migration: {rate: 0.1, interval: 50, type: ring}}
  parent_sampling: {scheme: three_way, ratios: [0.7, 0.2, 0.1], double_selection: true}
  novelty_gate: {embedding: 0.99}    # 原系统口径=近似克隆拦截；框架级编译为 0.95 起步+台账校准
  eviction: {rule: point_estimate, population_limit: [1000, 100]}   # 硬编码反例见下
```
内核复用：grid×islands、evaluator_metric descriptor、三路+double selection、full snapshot 全部是默认形态——**本 profile 与框架默认值重合度最高**。
**公理违反标注**：原系统**选择策略硬编码进 ProgramDatabase（违反 E2，"换策略需改源码"——本框架将其编译为策略注入点配置正是对此反例的修复）**；**违反 E12/E5**（`_enforce_population_limit` 按点估计静默驱逐，无 CI 无软删除）；**违反 E1/E4**（无供给熵/跨岛距离探针）；**违反 E8 精神**（恢复档案 ≠ 恢复策略环境，M4-7 案例 2）。【诚实标注】

### 8.3 gepa_pareto（per-instance 前沿 + 覆盖比例采样）

```yaml
profile:
  name: gepa_pareto
  axes: {P1: matrix(per-instance), P2: pareto_per_instance, P7: per_instance_best 表,
         P8: coverage_proportional, P13: run_dir+adapter 鸭子快照}
  frontier: {kind: pareto_per_instance,
             budget_cap: required,          # E6：85–90% 预算税教训——联立声明为一等字段
             granularity: {weighting: info_weighted, seat_confidence: true}}  # E9
  parent_sampling: {scheme: coverage_proportional}   # 按 Pareto 覆盖实例数比例随机采样
  persistence: {mode: run_dir, adapter_state: duck_snapshot}
```
内核复用：per-instance 最优表=P7 固定字段④的直接物化；覆盖比例采样=P8 原生骨架（×P2 绑定关系原生）。
**公理违反标注**：原系统**违反 E6 精神（per-instance 表全量维护吃掉 ~85–90% rollout 预算且无占比上限声明，作者自承须动态子集）**；**违反 E9（实例均匀未按判别力加权——易实例主导，M4-5）**、**违反 E11（单评噪声实例席位无置信度标记）**。【诚实标注】

### 8.4 dgm_archive（档案树 + 自改进档案）

```yaml
profile:
  name: dgm_archive
  axes: {P1: tree, P2: tree_leaves(全体保留), P8: weighted(分数×(1+子代数)),
         P10: unbounded, P13: 按(benchmark commit, agent version)隐式绑定}
  topology: {archive_topology: tree}     # 免驱逐特例（驱逐需求由 P10 裁决豁免）
  parent_sampling: {scheme: weighted, fields: [score, children_count]}   # DGM §C.2 反精英加权
  eviction: {rule: none}                 # 永久保留；须配 P19 供给浓度监控（E5 的 tree 特例条款）
  frontier: {kind: tree_leaves}
```
内核复用：tree/tree_leaves 为合法取值（免驱逐特例）；children_count 加权=P7 固定字段②的消费先例；archive/父选择机制刻意冻结=冻结边界声明正面先例（与 M2-O17① 同源）。
**公理违反标注**：原系统**违反 E1（无供给熵监控，unbounded 档案的采样稀释无读数，M4-3a）**、**违反 E8 精神（换 benchmark 版本旧分失效但记录不自动作废，M4-7 案例 4）**、**违反 E11（无重评机制）**；去 archive 消融显著退化是 E7 的正面证据。【诚实标注】

### 8.5 evodiverse（多池 + 受控交换）

```yaml
profile:
  name: evodiverse
  axes: {P1: single_pool(多温度池变体), P9: controlled_exchange(PT 池间 MH 交换),
         P8: weighted(Boltzmann 权重)}
  topology: {archive_topology: single_pool, pools: temperature_ladder}  # 温度梯非地理隔离
  diversity: {carrier: controlled_exchange, exchange: metropolis_hastings}  # P9 受控交换档
  parent_sampling: {scheme: weighted, weight: boltzmann(beta)}   # 档案语义=从 Boltzmann 分布采样
```
内核复用：controlled_exchange 为 P9 原生取值；"隔离 vs 交换"两端各防一种失效的联合配置空间由 P1×P4×P9 覆盖。
**公理违反标注**：原系统基线（无交换单池）即 M4-1 塌缩实例（premature collapse、嵌入空间 cluster tightly），**profile 本身合规但依赖 P19 探针缺失时不可治理（违反 E1/E4 的传感层义务——无跨池/跨代多样性时序读数）**；+12%/+19% 证据在科学假设搜索域，代码域未复现（迁移性【推断】）。【诚实标注】

### 8.6 evolenet_federated（可选第六：联邦分布合并）

```yaml
profile:
  name: evolenet_federated
  axes: {P16: federated_delta(scope-typed+证据门控), P12: snapshot_merge,
         P1: 多部署点本地档案+server 合并}
  distribution: {mode: federated_delta,
                 preconditions: [anchor_recalibration, eviction_falsifiable],  # 双前置硬门
                 merge: {pipeline: [diff, mechanism_decompose, scope_classify,
                                    conditional_compose, item_gate, rollback_on_fail]}}
  lineage: {cross_run_edge: hetero_source}   # "异源"谱系边；source_run_id 强制
```
内核复用：双前置、逐 item 门（归 M9）、scope-typed 语义、异源谱系边、快照回滚全部是 P16/MergeEvidence 原生结构——**本 profile 是 P16 设计的一手原型**。
**公理违反标注**：其**无门控链式版本（直接崩溃回滚）违反 E8/分歧 6 双前置**，是框架硬门的正面反证；EvolveNet 本体合规。域条件化收益与联邦拓扑混杂未分离（边界声明 7）；跨组织产权/部署归框架层（不留接口）。【诚实标注】

**兼容性结论**：六个 profile 覆盖调研中全部经典系统设计空间（含分布合并与多池交换两个 2026 新形态），差异 = 拓扑/前沿/聚簇/供给骨架/驱逐档/合并协议的选择，全部在配置层。表达不了的进 §9 边界声明。

---

## 9. 诚实边界声明（统一不了的东西，合并后 8 条）

1. **P19 四个健康探针全线"先记账后定参"**：供给熵的有效熵口径（基因型/表型）、跨岛表型距离的度量选择、实例判别力量化式、重评存活率的周期与样本量——无一度量实现先例，阈值全部是公理推导的占位符。探针缺失视同塌缩已发生（默认档强制逻辑不依赖阈值），但"探针反馈治理"档的全部触发线只能先记账待标定。
2. **P3/P4 岛参数零消融**：岛数谱系 10→5→3→2 是时间线而非剂量-反应曲线（混杂部署规模/任务转向/迁移成熟/新颖性闸替代四共变因子）；动态繁殖 threshold=100 零消融、量纲敏感性未知；K=5 的法律地位是"惯例中位数"不是"被验证最优点"——E4 因此降 SHOULD，只保证可配、可记账、可被探针接管。
3. **P10 软删除+深度缓冲跨域外推**：CMA-MAE archive learning rate 与 UQD depth d=8/32 全部在机器人/函数优化 QD 域验证，LLM 代码进化域零实现先例；mSPRT 提前停止×驱逐规则的交互无公开直接测量——E5/E12 的机制方向有证据、参数形态是设计外推。
4. **P16 重标定档零先例**：跨 run 合并通用协议不存在（阴性发现 1，EvolveNet 是唯一一手系统且其合并是任务特定 LLM-merger）；共享锚点集大小/重评预算占比/标定漂移容忍度全部无标定；被污染 run 的跨 run 召回无任何文献触及，纯设计外推——只允许以整批 quarantine 形态实现。
5. **正面叙事证据等级分层**：AIDE² 数字为博客级（方向被 DGM 消融独立佐证）；IDEAgent 阴性聚合库增益【未复核】+LLM judge 可信度警示；Red Queen/TTHE 为单系统/单点【未复核】——这些取值全部注册但默认关，不以弱证据进默认路径。
6. **跨模块接口的三角待定**：P20 资格位契约同时对齐 M9（判定）× P7（字段）× X1（召回）三方，E12 消费 M8 联合噪声底——三方接口在 M4 侧只定义了存储与执行义务，判定逻辑的全部细节依赖 M8M9 定稿；P17 移交集"可读性"（接收方是否消费语义字段）零测量。
7. **核心归因裂缝**：SeaEvo +21% 是双空间档案整体增益（语义 descriptor/NL 策略层独立贡献未分离）；EvolveNet 70.7% 混杂联邦拓扑与合并协议；GEPA +6.4% 的 Pareto 消融与覆盖比例采样/反思算子同论文打包——轴系默认值是"打包采纳最强证据组合"而非逐成分验证（与 M2 边界声明 7 同型）。
8. **保守晋升的反向代价无测量**：CI 下界>点估计的交付假阴率（真精英被拒的代价）无任何一手对照；"1% 污染点燃"的档案侧剂量-效应曲线无量化模型；资格位 epoch 边界批量复位的级联成本（一次复位多少亲本池、恢复多慢）无运行数据【推断】。

---

## 10. 分阶段落地（M4a–M4d，对接 ADAPT-v1.1）

| 期 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|
| **M4a（类型层，P0）** | ArchiveEntry（三资格位+ReliabilityMeta 快照+谱系四元组+failure_provenance）/FrontierView/ParentPool（五字段）/ArchiveHealthProbe/MergeEvidence 落 core/frontier/types.py；全部字段有默认值；hard_delete 不存在的类型层证明 | 缺 CI 字段的候选被拒绝入档、缺谱系四元组的候选留档不供亲、缺 source_run_id 的合并产物拒绝入库的单测通过 | 无，与 G1/M2a/M5a/E9a 类型层改动同批；并入 Step 0 |
| **M4b（最小可用档案，P1）** | grid×islands 默认拓扑 + cell_elite 前沿 + three_way+double selection 供给骨架（策略注入点一等接口）+ 驱逐协议（CI 下界+软删除+三字段）+ buggy_leaf + full_db_snapshot 双快照 + P15 退化投影常驻；openevolve_mapelites / funsearch_island 两 profile | 真实运行中产出台账；退化对照跑通；供给函数热替换不改 M2 代码的集成测试通过；sync 槽注册 LLM 算子直接报错 | M4a + M8 ReliabilityMeta（噪声底）；并入 Step 1 |
| **M4c（健康探针与资格位，P2）** | **P19 四探针仪表盘（最高优先依赖，显式置顶）**+ 资格位与 M9 Receipt 绑定（epoch 边界批量复位）+ 前沿预算联立声明（E6）+ 重评预算通道（E11）+ M5 沉淀通道（level=L2，provenance 复用四元组）；gepa_pareto / dgm_archive profile | 四探针跨代时序入 X1 且报警触发记录可审计；资格位复位/平反路径演练通过；沉淀条目过 M5 admit 校验 | M4b + M8M9 准入门就位 + M5b 条目模型；并入 Step 2 |
| **M4d（合并/移交/治理档，P3）** | 跨 run 合并双前置门（锚点重标定+快照回滚）+ 异源谱系边 + relay bank 子模估值（Relay Gain 上报 M1）+ 探针反馈治理档（误报率校准后启用）+ 祖源级召回演练；evodiverse / evolenet_federated profile | 合并失败整体回滚演练通过；污染 run 整批 quarantine 演练通过；治理动作全量可回滚 | M4c + 锚点机制（M8）+ 探针台账积累（≥数十代）；并入 Step 3 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做硬删除 API（只有 deprecate/quarantine；出现不可逆删除=构建期拒绝）
- 不做无退化对照的档案结构变更（P15 永驻，移除=构建失败）
- 不做 best-so-far 单点档案默认档（E7；仅作为退化对照投影存在）
- 不做跨组织产权/联邦部署拓扑（判归框架层，M4 不留轴不留接口）
- 不做 LLM 失败/驱逐判定硬过滤（is_buggy 式布尔过滤构建期拒绝，E5/I-LLM）
- 不做逐 call 级模型路由（决策粒度=移交集级，P17）
- 不做无重标定的跨 run 分数同序（运行期阻断，E8）

---

## 11. 一句话规格

> **M4 = 冻结的 ArchiveEntry/FrontierView/ParentPool/ArchiveHealthProbe/MergeEvidence 数据模型与双资格位（进档靠分数、供亲/交付靠证据，parent_eligible 为类型层过滤位）/驱逐三字段/谱系四元组记账规则（内核）+ grid×islands 默认拓扑与策略注入点一等接口（"Database 即算法"但结构-策略禁焊死，供给函数可热替换）+ 驱逐协议（噪声底下不裁决、CI 下界+软删除+深度缓冲、hard_delete API 不存在）与新颖性双阈值口径（0.95 近重复起步、0.99 克隆口径记录、P19 台账校准）+ 失败候选环境事实判定与复活通道（buggy_leaf）+ 档案+策略环境双快照 + M5 沉淀通道（level=L2、provenance 复用四元组、沉淀资格=交付资格）+ 跨 run 合并双前置硬门（锚点重标定×驱逐可证伪，异源谱系边）与移交估值（Relay Gain，决策粒度=移交集级）+ P19 四族健康探针仪表盘（供给熵/跨岛距离/实例判别力/重评存活率，最高优先依赖，探针缺失视同塌缩）与 P15 常驻退化自检（SCS/单链投影，增量须超 M8 噪声底）+ 八操作面×三实现类矩阵 + 二十轴编译成的 profile（FunSearch/OpenEvolve/GEPA/DGM/EvoDiverse/EvolveNet 全部是 profile 实例）+ 双速调度（sync 禁 LLM）+ E1–E12 公理内核化与四条既有不变量承接（I-披露、I-可逆双候选待框架级确认，I-可逆由 M4 以三投影论证提出）。**
