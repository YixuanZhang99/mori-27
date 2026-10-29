# M2-UNIFIED-v1.md — 统一算子（变异/进化生产侧）模块设计文档

> 依据：`../research/m2/m2_axes_final.md`（19 轴定稿 O1–O20，O18 并入 O5）、`../research/m2/m2_deepdive_part1/2/3.md`（逐轴深挖）、`../research/m2/m2_分歧_公理.md`（七分歧裁决 + 公理 C1–C12 + 根因对账 + I-披露候选不变量）、`../research/m2/groupA_operator_design.md` / `groupB_operator_failures.md` / `groupC_frontier.md`（原始调研）。结构与风格对齐 `M8M9-UNIFIED-v1.md` / `M5-UNIFIED-v1.md`。所有数字引自上述底稿，不确定处标【推断】或降级措辞。
> 定位：M2 Operator 的最终形态设计。回答一个问题——**OpenEvolve 的 diff 工程 / GEPA 的反思变异 / DGM 的单算子自进化 / OpenRSI 的统一动作空间 / FunSearch 的岛隔离这些经典设计能否被同一个实现兼容？答案：能。它们之间的差异全部是配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 OperatorSpec/ContextRecipe/VariationProposal/FunnelRecord 数据模型与四段漏斗记账规则（内核，不可换）+ 带宽闸与退化基线自检（内核）+ 四算子集可替换算子（插件，各分确定性/LLM/可学习三档）+ 十九轴编译成的 profile（配置）+ 双速调度与 op tax 经济学协议（运行时）**。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条框架级不变量 + 第五候选（建议上收 CLAUDE.md）

以下四条不变量横跨 M5/M8/M9 三模块独立出现（与 M8M9-UNIFIED §0.0 逐字一致，M2 侧的对账见 `m2_分歧_公理.md` 任务三）；M2 经根因对账后贡献第五条**候选**不变量：

1. **不变量 I-α（锚点存在性）**：框架内任何被优化压力触及的积累物必须配一个物理上不可被该压力修改的锚点组件。→ M2 侧投影：退化基线自检（IID-RS/SCS 永驻）与冻结边界声明（O17①）。
2. **不变量 I-β（质量指标一等化）**：任何裁决/积累机制必须暴露其判别质量指标；"机制动作次数"不得作为健康证据。→ M2 侧投影：**O20 四段漏斗是 M2 版的 gate_quality_probe**——"算子产率从未被独立测量，只有循环总收益被报告"与 M9 侧 E7 根因是同一抽象失效的两个投影。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：→ M2 侧投影：apply 落地由确定性 patcher 完成（O3）；失败判定只来自环境事实（compile/run），LLM 判断只做优先级排序、不做准入硬过滤（C11，AIDE is_buggy 误杀教训）。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：→ M2 侧投影：算子版本/prompt 版本/权重版本/WHERE×WHY 坐标/相似度核算记录全部入 X1（O13/O14/O17④/O20）。
5. **候选不变量 I-披露（信号通道最小披露）【候选，待框架级确认】**：框架内任何进入优化循环消费侧的信号通道（评估反馈、记忆检索、元数据、谱系信息），默认实行最小披露——每个字段必须回答"接收方能拿它讨好谁/过拟合谁"；对接收方为可优化对象的通道，披露单位降档（数值→分档→方向→1bit），完整信息仅对不可被该优化压力触及的接收方（人、外部审计、锚点组件）开放。上收判据满足性论证：M2 侧双投影且机制各异（O7 反馈通道 SEAL 35.1→12.7 + self-bias 0→+11；O5 记忆通道全局拼接零增益 38.18 vs 39.77）；M5 侧投影（A6 两阶段读取）；M8M9 侧已事实物化一半（其分歧 3 与 B2）。与 I-α 的边界：I-α 管供给侧完整性（锚），I-披露管需求侧最小化（闸）【推断：措辞为建议稿，上收与否由框架定稿阶段裁决】。

> 根因对账备注：M2 第三根因"复杂度挣得存在"（C10）经裁决**不上收**为不变量——其判定程序锚定各模块自身的噪声底，框架级措辞会退化为空泛奥卡姆口号，保持模块级 MUST 更诚实【推断】。

### 0.1 公理 C1–C12（失效证据 → 内核物化）

| # | 公理 | 强制级别 | 失效证据指认（关键数字） | 违反检测 |
|---|---|---|---|---|
| C1 | **多样性是一等受控变量**：>5 代的进化循环必配表型多样性探针（跨代时间序列+报警阈值，标准化模板+精确串匹配/行为级代理，禁用嵌入指标）；无探针的循环默认视为已塌缩 | MUST | 对齐后生成多样性 45.4%→10.8%（−76%，arXiv:2510.01171）；纯贪心父代 3 代内塌缩（arXiv:2604.07872）；稠密拓扑加速塌缩（arXiv:2604.18005） | 谱系审计检查探针时间序列存在且被消费（报警→父代/算子切换记录）；探针缺失=构建期报错 |
| C2 | **变异器先验上限声明**：配置须报告所用 LLM 在该任务族的原生采样多样性实测值，算子设计不得假设更高变异供给 | SHOULD | 同 C1；verbalized sampling 恢复至基座 66.8%（+182.6%）证明上限可部分修复 | 配置评审 checklist 项；探针实测持续低于声明上限→配置重审 |
| C3 | **变异产出强制去重核算，plateau 必须被归因**：候选携带与档案库的相似度核算记录；plateau 须二分"重复率饱和"（切探索算子/父代）与"够新但无提升"（才可谈收敛），两者触发不同响应 | MUST | AI-Scientist 复评迭代改动仅 +8%/0–0.3% 字符（arXiv:2502.14297）；ShinkaEvolve 无拒绝时 near-duplicate 增殖（Fig.9 消融收益最大单项）；AIDE² 外环 ~90% 拒绝 | 候选 schema 缺 similarity_records=拒绝入库；plateau 期重复率台账缺失=审计不通过 |
| C4 | **变异表示是显式配置且有失败率台账**：per-(模型, 表示, 任务族) 的 apply 失败率与 diff 膨胀率常驻记账；apply 失败在重试**之前**计数；换供应商=台账重置 | MUST | aider：o1-preview diff 合规 84.2%、Qwen2.5-Coder-32B 71.6%、同模型换供应商 98.7%→84.0%；Morph 结构化 diff 25%+ vs lazy diff+apply <1% | 台账字段缺失或断点设在 LLM 自判上=构建期报错；膨胀率超阈值报警 |
| C5 | **小改声明须由机制担保**：局部变异的作用域由结构机制约束（EVOLVE-BLOCK 块边界、diff 行数上限硬门）；prompt 措辞请求"只做小改"不构成担保 | MUST | aider issue #2563（imports 塞进函数、重复方法而非替换）；HarnessBank 激活门同根 | 无块边界/行数硬门的 improve 类算子注册=构建期拒绝 |
| C6 | **算子产率四段漏斗记账**（proposed→applicable→runnable→admitted）+ 成本段（admitted_per_usd）；**无漏斗数据的算子不得参与自适应选择**；嵌套算子必须上报 sub_funnels | MUST | LMX 父序波动 >50%、无签名约束 100% 无效（arXiv:2302.12170）；AIDE² 净采纳 ~10%；SB P(Shinka>IID RS)=0.49 证明总收益不构成算子在工作的证据 | O2/O10/O14 消费无漏斗算子=运行期拒绝；任一段比率接近 100% 报"判别器失效"（双向报警） |
| C7 | **多亲本算子须提供结构化可组合性契约**：签名约束、接口对齐、亲本角色标注；亲本排列随机化/枚举并计入方差；裸 prompt 拼接式交叉默认低信任 | SHOULD | 同 C6 的 LMX 数字（2023 数据，现代证据薄） | crossover_validity 段缺失或方差超阈=该算子降级为手工触发 |
| C8 | **变异器反馈通道最小信息披露**：默认 public 标量+结构化错误定位；judge 自由文本经表面特征剥离（版本化）后才可喂入；full trace 与漏斗台账元数据永不进变异器 prompt | MUST | SEAL leaky-anchor 35.1→12.7；self-refine bias 0→+11 三代内（人评不变）；rubric 词汇偏置 100% 被利用、~116 步 onset（转引） | op_context 构造器类型层黑名单（编译期）；带宽快照入 X1 供事后审计 |
| C9 | **同源即共谋风险声明**：变异器与评估器同模型/同家族时，准入裁决前必须引入跨家族校验或外部锚定信号；self-bias 放大系数（自评分增量−外部评分增量）常驻监控，>0 且随代数增长即报警 | MUST | k=4→32 时 bias 显著增大（arXiv:2402.11436）；CommonGen 第 5 代后真实 coverage 饱和而自评续升 | op_context 登记变异器/评估器模型家族字段；同源且无跨家族复评计划=构建期警告→运行期阻断 |
| C10 | **复杂度必须挣得存在**：自适应/学习化机制默认从最简单配置起步，仅当消融证明增量超 M8 噪声底才升级；退化基线（IID-RS/SCS）永驻对照；投入优先序硬编码 新颖性去重 > 父代选择 > LLM/算子 bandit（有结果接地训练信号时 O14 训练档排在 bandit 之前） | MUST | SB P=0.49 vs EoH 引导 2k>纯采样 10k（0.66% vs 2.44% gap）；ShinkaEvolve 消融梯度 去重>父代>bandit；Inria AOS 各方案 ECDF 重叠（hal-00519579）；DGM 去 archive 显著退化 | 构建中退化基线被移除=构建失败；自适应机制无配套消融记录=配置评审拒绝 |
| C11 | **可自修改位声明；防护组件默认不可自进化**：每算子携带显式 self_mutable 位（元位本身冻结）；算子依赖的过滤/防护组件（buggy 判定、新颖性闸 prompt、带宽闸、反作弊层）默认 self_mutable=false，代码版本入 X1；失败判定只来自环境事实，LLM 判断不做准入硬过滤（保留复活通道） | MUST | AIDE² 反作弊统计层被突变改坏而不自知（weco.ai 2026-07）；AIDE is_buggy 自判永久误杀；OpenEvolve"换策略需改源码"锁定 | X1 谱系比对 gate/防护代码版本漂移；is_buggy 式布尔硬过滤出现=构建期拒绝 |
| C12 | **上下文是配方式资源**：全量历史拼接禁止默认；每算子声明记忆视图（scope/kind/ttl/抽象度）；注入条目必须带 ttl/provenance 且过 near/far 抽象度抽检（防护责任在 M2 入口，边界双方共管）；配方变更按实验对待（记录、对照、可回滚） | MUST | AIRA 全局 memory on/off 无差（38.18 vs 39.77）而作用域记忆是 +14% 三件套之一；AIDE₀ 全量拼接被 AIDE₈₅ 自主进化淘汰（16× prompt 压缩）；ACE 塌缩 18,282→122 token | 配方版本 hash 与 lesson 引用列表入 X1，缺失=评审拒绝；过期 ttl 条目进 prompt=运行期拦截 |

> 合并/降级记录（与 `m2_分歧_公理.md` 一致）：B3+B4→C3；B11+B12+B14→C10；B15+B16→C12；C2/C7 降为 SHOULD（证据厚度不足 MUST）；无降级为实现建议的条目。

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（双速调度 sync 禁 LLM / op tax 定价 / handoff 相位）│
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  算子接口：draft / improve / debug / crossover (+merge/select)│
│          每算子三类实现：确定性 | LLM | 可学习                        │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：统一算子签名 + 带宽闸（类型层白/黑名单）+ 新颖性闸   │
│          + 退化基线自检（IID-RS/SCS 永驻）+ 自修改四件套 + 证据日志(X1) │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：OperatorSpec / ContextRecipe /               │
│          VariationProposal / FunnelRecord / DiversityProbe          │
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（C11：防护组件 self_mutable=false）
         ↑ Layer 3 标注 evolvability: operators_only（prompt 可进化须逐 prompt 声明）
         ↑ 经典系统 = profile = Layer 3 算子选择 + Layer 4 配置
```

**M2 的模块分工**（轴系原则 4）：M2 管"如何产生新候选"（算子集、表示、上下文、安全、记账）；亲本选择**算法归 M1**（公式参数进 M2 配置）；评估语义归 M8；准入裁决归 M9；预算总额归 M3。跨界处只留接口不留轴。

---

## 2. Layer 1：冻结数据模型

五个新类型。与既有类型的挂接：ContextRecipe 消费 M5 MemoryEntry 视图声明；VariationProposal/FunnelRecord 消费 M8 EvalResult/Verdict 并写入 X1 谱系坐标。

```python
# core/operator/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

OpKind = Literal["draft", "improve", "debug", "crossover", "merge", "self_modify"]
Representation = Literal["diff_block", "evolve_block", "full_rewrite", "lazy_diff_apply"]
CandidateLevel = Literal["task_solution", "executor_spec", "operator_prompt"]  # O15

# ---- 算子规格（O1/O13/O17 的登记形态）----
@dataclass
class OperatorSpec:
    op_id: str
    kind: OpKind
    arity: Literal[0, 1, 2]                    # draft=0, improve/debug=1, crossover/merge=2
    representation: Representation = "diff_block"   # O3；概率混合见 Layer 4 配置
    prompt_version: str = ""                   # O13：版本强制，进 X1；空=拒绝注册
    weight_version: Optional[str] = None       # O14：训练版算子的 checkpoint id + 数据批指纹
    self_mutable: bool = False                 # C11：默认冻结；元位本身不可自改
    atomic_change: bool = True                 # O1：improve"每边一个原子改动"默认开（可归因性）
    writable_scopes: list[str] = field(default_factory=lambda: ["code"])  # O4：默认单面
    structural_guards: list[str] = field(default_factory=list)
    # 例：["evolve_block_boundary", "diff_line_cap:200"]——C5：无硬门的 improve 注册被拒

# ---- 上下文配方（O5：消费 M5 视图声明；C12 的物化）----
@dataclass
class ContextRecipe:
    recipe_id: str                             # 版本化；hash 入 X1（配方即实验）
    memory_scope: Literal["sibling", "ancestral", "global", "none"] = "sibling"
    # draft/improve→sibling，debug→ancestral（AIRA 作用域路由）；global=禁止默认（C12）
    lesson_pool: dict = field(default_factory=lambda: {"kind_filter": None, "k": 30})
    # MARS 形态：solution/debug 分池 K_m=30，显式引用可审计
    ttl_max_age: Optional[float] = None        # 新鲜度门；过期条目运行期拦截（C12）
    abstraction_probe: dict = field(default_factory=dict)  # near/far 抽检比（M2 入口职责）
    field_whitelist: list[str] = field(default_factory=list)
    # 例：["raw_tail", "plateau_signal", "complexity_hint"]；complexity_hint = f(node_children_count)
    full_history_concat: bool = False          # 硬编码：True=构建期拒绝（AIDE₀ 已证伪）

# ---- 变异提案（算子产出物；C3/C4/C7 的记账起点）----
@dataclass
class VariationProposal:
    proposal_id: str
    op: OperatorSpec
    parent_ids: list[str]                      # arity 决定长度；crossover 多父谱系边单独标注
    patch_text: str                            # 原文（diff/全文），谱系存档
    patch_type: Representation
    apply_result: Literal["ok", "retry_ok", "failed"] = "failed"
    apply_attempts: int = 0                    # ★ 失败在重试之前计数（C4）
    similarity_records: list[dict] = field(default_factory=list)
    # ★ C3 强制：与档案库的相似度核算记录；缺失=拒绝入库
    claimed_lines: int = 0                     # diff 膨胀率分子（声称行数）
    where_why: dict = field(default_factory=dict)
    # ★ WHERE（写入坐标面）× WHY（目标病理）语义坐标——schema 强制字段（分歧 3）
    crossover_meta: Optional[dict] = None
    # 仅 crossover：{n_parents, signature_constraint: bool, role_labels, perm_seed}（C7）

# ---- 四段漏斗（O20/C6 的核心 schema；算子×代×任务族一条）----
@dataclass
class FunnelRecord:
    operator: str
    model: dict                                # {name, provider}——供应商是独立变量（98.7%→84.0%）
    representation: Representation
    task_family: str
    generation: int
    # 漏斗四段计数（断点必须架在确定性组件上：patcher/编译器/门，C11）
    proposed: int = 0                          # LLM 产出数
    applicable: int = 0                        # patcher 应用成功数 → apply_rate
    runnable: int = 0                          # compile+冒烟通过数（消费 M8 可运行性信号）
    admitted: int = 0                          # 过 M9 准入门数 → net_rate
    # 质量探针字段（防"率正常但语义坏"）
    diff_inflation: dict = field(default_factory=dict)   # {claimed_lines, actual_diff_lines}
    near_dup_rate: float = 0.0                 # O8 相似度>0.95 占比（C3）
    crossover_validity: Optional[float] = None # 仅 crossover：有效后代比例（LMX 指标；分歧 6 硬编码）
    # 成本段（O19 挂接点）
    cost: dict = field(default_factory=dict)   # {propose_tokens, apply_tokens, eval_cost_usd, admitted_per_usd}
    # 谱系与审计（X1 挂接点）
    lineage: dict = field(default_factory=dict)
    # {parent_ids, similarity_records, gate_versions, op_prompt_version}
    sub_funnels: list["FunnelRecord"] = field(default_factory=list)
    # ★ O16 递归字段：嵌套算子的内层漏斗；缺省空——不上报=成本段全错（实现陷阱 ii）

# ---- 多样性探针（O9/C1 的物化；跨代时间序列）----
@dataclass
class DiversityProbe:
    generation: int
    metric: Literal["exact_match_template", "behavioral_proxy"]  # 嵌入指标禁用（混淆 dynamic/static）
    value: float
    alarm: bool = False                        # 超报警阈值；报警→父代/算子切换记录须入 X1
    prior_ceiling: Optional[float] = None      # C2：所用 LLM 原生采样多样性实测声明
```

**与 M5/M8/X1 的类型级挂接（写死，参照 M8M9-UNIFIED §6 白/黑名单风格）**：

```python
# core/operator/consume.py —— op_context 构造器的类型层强制，不可配置关闭（C8）
M2_CONSUME_M8_WHITELIST = {
    "public",               # 标量分+结构化错误定位（给方向不给梯度，分歧 5 默认）
    "items 的错误定位信息",   # debug 算子的合法输入（traceback/失败类别）
    "card.scorer_version",  # 评估器谱系：receipt 失效须级联降权依赖候选的 lesson（O7 接口）
    "reliability",          # CI/噪声底：低于噪声底的 Δscore 不得触发反思/庆祝性记忆写入
    "verdict.rationale_ref",# M9 否决的结构化可证伪理由——debug 的合法输入
}
M2_CONSUME_M8_BLACKLIST = {
    "text_feedback 未剥离版",  # 须先经表面特征剥离（去 rubric 关键词/格式线索），剥离规则版本化
    "private",                 # 决定存活的通道，对变异器类型层不可达
    "combined_score",          # display-only，永不进变异 prompt（M8M9 分歧 2 的消费侧镜像）
    # 一切 signal_provenance == "endogenous" 的字段；full trace 与 FunnelRecord 元数据
    # 永不进变异器 prompt（不是配置项而是流向禁令，C8）
}
# M2 → X1 写死字段：算子类型+版本、prompt_version/weight_version、父指针（crossover 多父边）、
# similarity_records、where_why、带宽快照+剥离规则版本、gate/防护代码版本（O17④）
# M2 → M5 写死约束：full_rewrite 禁用于记忆/知识对象（ACE 18,282→122 token 反例）；
# 知识/记忆面写入必须走 M5 写入门禁，M2 不直连记忆库（分歧 3 前置条件）
```

**设计决定说明**：
- `apply_attempts` 与 `apply_result` 分离是 C4 的物化——"重试到能跑"把失败转成延迟成本在报表上消失，失败必须在重试**之前**计数。
- `FunnelRecord` 四段各有专属消费方：applicable→O3/O19；runnable→O12/M8；admitted→O2 bandit 奖励与 O14 训练信号；near_dup_rate→O8 阈值校准。没有消费方的字段不进 schema【推断】。
- `where_why` 是分歧 3 的硬编码落地：跨坐标重组 +13.9% 的价值由可索引可重组的存档创造，坐标缺失即无米下锅。
- `DiversityProbe.metric` 枚举不含 embedding——arXiv:2508.13333 证明嵌入指标混淆 dynamic/static，探针要保守防漏（与 O8 闸的保守误杀方向相反）。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 统一算子签名与算子集（O1，分歧 1 落地）

对齐 AIRA-dojo 统一签名的**纯函数**形态——依赖全入参（llm/memory_op/budget），OpenEvolve 把选择策略硬编码进 ProgramDatabase（"换策略需改源码"）为反例：

```python
# core/operator/ops.py
def op(llm, cfg: OperatorSpec, memory_op, task_desc, journal,
       *input_nodes, step_count: int, remaining_time: float) -> VariationProposal:
    """arity = len(input_nodes) ∈ {0,1,2}，由 cfg.kind 决定；
       统一 execute_op_plan_code 包装器：生成→抽取→max_operator_tries 重试→剥离 thinking tags；
       apply 由确定性 patcher 完成（I-LLM：LLM 产提案，落地与判定是代码）"""

# 默认四算子集（arity 覆盖=表达力下限：0 元冷启动 / 1 元归因改进 / 2 元组合）：
OPERATOR_REGISTRY = {
    "draft":     ...,   # 0 元：从头生成（task_desc, 记忆摘要, data_preview）
    "improve":   ...,   # 1 元：每边一个原子改动（atomic_change=True 默认开）
    "debug":     ...,   # 1 元：消费结构化错误定位修复 buggy 候选
    "crossover": ...,   # 2 元：受三件套约束（见 §3.3）
    # "merge": 注册为可选、默认关（分歧 7）；前置=Pareto-per-instance 亲本结构+lesson 池在位
    # "self_modify": 仅 T≥ExecutorSpec 且 O17 四件套就位后可注册
}
```

**硬编码不变量**：
1. **退化基线自检永驻**（C10/分歧 1）：IID-RS（独立同分布随机采样）与 SCS（单算子整文件生成+条件上一代，Simple Baselines 形态）作为内置退化投影**不可从构建中移除**；任何新算子/新组合必须跑赢退化基线且增量超 M8 噪声底才允许进默认集（SB：P(Shinka>IID RS)=0.49）。
2. **算子集注册表版本化**：算子上下线=谱系事件（入 X1）；improve 的"每边一个原子改动"为默认开的可归因性约束（可关配置，关闭须记录理由）。
3. **π_op 默认规则优先级表**（分歧 2）：声明式 触发条件→算子（种子不足 num_drafts=5→draft；以 debug_prob 回访 buggy 叶、限 debug_depth；否则贪心 improve）；bandit/RL 仅当 (a) O20 漏斗数据就位（**奖励的唯一合法来源=漏斗产率**，写入 M2×M1 接口契约）、(b) 消融证明增量超噪声底 同时满足时作插件启用；bandit 状态 get/set_state 入 checkpoint 契约；读 bandit 后验前先看漏斗（risk-aversion 偏置）。
4. **投入优先序硬编码**（C10）：新颖性去重 > 父代选择 > LLM/算子 bandit；有结果接地训练信号时 O14 训练档排在 bandit 之前。

### 3.2 变异表示与带宽闸（O3/O7，分歧 5 落地）

- **表示默认**：diff_block + 确定性 patcher（校验 + max_patch_resamples 重试）；**概率混合默认起点 `patch_type_probs=[0.6, 0.3, 0.1]`**（diff/full/其他，ShinkaEvolve 实战配比；配比本身应随 O20 失败率台账自适应【推断】）。evolve_block 为存量 repo/安全敏感档；full_rewrite 保留给长程重构与元层级改写，**禁用于记忆/知识对象**。
- **失败率是 (模型, 格式, 供应商) 联合分布**：台账按三元组记账，换供应商=台账重置（C4）；"更聪明的模型可能是更差的编辑器"（QwQ whole 42.1%）——(模型, 表示) 联合选择由 O20 台账驱动，不由推理能力直觉驱动。
- **带宽闸**（C8，类型层强制见 §2 consume.py）：默认 public 标量+结构化错误定位；text_feedback 经剥离后按任务需要开启；剥离规则版本化、每步带宽快照入 X1。带宽闸代码默认 self_mutable=false。
- **同源校验**（C9）：op_context 登记变异器/评估器模型家族字段；同源时准入裁决前引入跨家族校验或外部锚定；self-bias 放大系数常驻监控。

### 3.3 新颖性闸与 crossover 三件套（O8/O6 交叉，分歧 6 落地）

- **新颖性闸默认开**：embedding 相似度拒绝，阈值 **0.95 起步**，配 O20 重复率台账动态校准（拒绝率 <5% 或 >50% 均触发算子/父代切换而非调阈值【推断】）；+LLM novelty judge 默认关（边际提升不值一次调用）。闸拒绝率飙升=多样性塌缩先行指标（×O9）。
- **plateau 归因二分**（C3 硬编码）：fitness plateau 不得直接解释为收敛——重复率饱和→切探索算子/父代；候选够新但无提升→才可谈收敛。两者触发不同响应，诊断曲线来自闸的拒绝率时间序列。
- **crossover 合法形态=三件套绑定**（缺一即降级为手工触发，C7）：(a) 多父谱系+父选按互补性（差异大/Pareto）而非双高分；(b) 子代强制接 debug 兜底（无任何系统报告 crossover 子代 pass 率高于 improve——交叉的真实形态是"融合+修复"复合管线【推断，A 组卡 A4 归纳】）；(c) 签名约束/亲本角色标注的可组合性契约，亲本排列随机化并计入方差。O20 的 `crossover_validity` 段强制记录；无该段的 crossover 不得参与自适应选择。

### 3.4 失败子代处理与自修改四件套（O12/O17）

- **debug 兜底默认**（O12）：失败子代自动进 debug，上限可配（AIRA 参照值 10 节点或 12h，单系统经验值）；失败判定只来自环境事实（compile/run），LLM 判断只做优先级排序、不做准入硬过滤——is_buggy 式布尔硬过滤构建期拒绝，失败标记保留复活通道（C11）。
- **自修改四件套**（O17，组合而非互斥；T=TaskSolution 时仅①必配，T≥ExecutorSpec 时全配）：
  ① **冻结边界声明**：每模块标 self_mutable 位（元位冻结）；评估器/门代码/反作弊层/exploration 机制默认不可自改（DGM 刻意冻结 archive/父选择为正面先例）。
  ② **功能性存活门**：compile+元能力检查优先于任何分数比较（DGM §3）——存活门归 M2 自修改通道，统计准入门归 M9，两问两个机制（DGM −1.1% 反例）。
  ③ **小步证据化+快照回滚**：small, evidence-backed updates，写入前快照，退化整体回退；回滚触发走外部信号或确定性规则，不得由被进化系统自判。
  ④ **谱系覆盖 gate/evaluator 代码**：X1 记每次准入裁决时的 gate/evaluator 代码版本，gate 代码变更=一等谱系事件。**第④件优先实施**——它是四件套中唯一被实证"抓到过真失效"的件（AIDE² 反作弊层自毁靠人工谱系审计才发现）；防护层的数量不是安全度量，防护层版本的可审计性才是。

### 3.5 op tax 经济学（O19，消费 M3）

对齐 M8M9-UNIFIED 的 eval tax 范式（显式定价 + 档位打包 + 禁散置参数 + 上报 M3 共享一条预算曲线）：
- **决策单位是相位/代，不是单次调用**：RelayEvolve 证明"逐 call 路由是错的问题"（LLM 调用状态耦合）——正确问题是"population 何时整代移交"（handoff），handoff 时机是 M1 搜索相位决策的输入，M2 只提供成本结构。
- **定价表**：每档算子调用显式定价（op kind × 模型档位），打包为显式档位注册进 M3；propose/apply 两级拆分（贵模型产 lazy diff + 便宜专用 apply 模型落地，失败率 25%+→<1%，1.5–2× token 效率【证据陈旧风险：Morph 2025-05 博客】）在 O20 台账显示 apply 失败率是落地瓶颈时启用。
- **目标函数**：固定总预算下的有效搜索深度（AIDE² 16× 压缩省下的 token 再投资为搜索步数），核算单位=admitted_per_usd 而非每调用成本【推断】。
- **嵌套算子成本必须拆成内部调用序列上报**（sub_funnels），否则预算失控不可诊断（O16×O20 结构性耦合）。

### 3.6 证据日志（复用 X1，append-only）

与 M5/M8M9 共用同一 X1 存储。每个候选携带：算子类型+版本、prompt_version/weight_version、父指针（crossover 多父边单独标注）、similarity_records、where_why、带宽快照+剥离规则版本、gate/防护代码版本；每条 FunnelRecord 的 lineage 子树并入谱系事件流。**先建日志，后调策略**（对照 M5-A5 / M8M9 §3.3）：所有算子产出从第一天就过漏斗记账。

---

## 4. Layer 3：算子×实现类矩阵

六操作面（含 select=亲本池构造与信号供给，O11 的 M2 侧义务；选择算法本身归 M1）× 三实现类：

| 操作面 | 确定性实现（默认与兜底） | LLM 实现（主力生成） | 可学习实现（opt-in） | 默认实现类 |
|---|---|---|---|---|
| draft（0 元） | 种子库/模板实例化 | 条件生成（task_desc+兄弟记忆） | RL 训练的生成策略（O14 档） | LLM |
| improve（1 元） | 确定性变换库（常量扰动/重构规则） | diff_block 提案 + 确定性 patcher 落地；每边一个原子改动 | SFT/RL 编辑策略（Harness-R1 形态）；meta 双时间尺度（MetaSkill 形态） | LLM + 确定性 patcher |
| debug（1 元） | 编译器/linter 定位 + 规则修复 | 消费结构化错误定位修复；上限 N_d/时限 | —（修复质量由漏斗 runnable 段测量，不单列学习档） | LLM |
| crossover（2 元） | AST/块级确定性拼接（受签名契约约束） | 双父+分数 prompt 融合；子代强制接 debug 兜底 | —（C7 契约未就位前禁学习化） | LLM |
| merge（2 元，可选） | 配置面确定性合并 | GEPA reflective merge：合并 Pareto 前沿两候选的互补 lesson | — | LLM（默认关） |
| select（亲本池供给） | 加权采样字段供给（rarity/children_count/per-instance 最优表/岛标签） | —（选择执行归 M1，LLM 不参与亲本打分，C9） | bandit 加权公式参数（插件，C10 约束） | 确定性 |

**实现类升级前置（硬编码，C10/分歧 4）**：任何操作面升级为 learnable 档须三前置同时就位——**(1) O20 漏斗数据**（训练信号的唯一起源：算子适应度=最近 H 个子代的改进量均值，与 O2 bandit 奖励共享同一台账，禁止两套不一致适应度）；**(2) 可重跑的确定性评估环境**（M8 噪声底已知且低于预期训练信号）；**(3) RL 基础设施**（训练预算是 M3 独立科目）。三缺一时开训练档=用噪声训练噪声。升级顺序硬编码：prompt 可进化（O13 轻量档）→ meta 双时间尺度 → 权重训练。

---

## 5. Layer 4：调度 YAML（双速，对齐 M5/M8M9 先例）

```yaml
# operator/schedule.yaml
schedules:
  sync:                        # 关键路径，每步算子调用前后；硬约束：禁 LLM（对齐 M5 A4）
    - op: funnel_count         # 四段计数器递增（确定性断点：patcher/编译器/门）
      constraint: no_llm       # LLM 算子注册到 sync 直接报错
    - op: novelty_gate_embed   # embedding 相似度拒绝（编码器调用计为确定性档位成本）
    - op: diff_inflation_check # 声称行数 vs 实际 diff 规模比对报警
    - op: bandwidth_snapshot   # 带宽快照+剥离规则版本写 X1
  idle:                        # 默认档：空闲窗/代际边界
    - op: funnel_report        # 段间比率时间序列诊断（双向报警：过低=算子失效，过高=判别器失效）
    - op: diversity_probe      # C1：跨代表型多样性时间序列+报警（>5 代循环强制）
    - op: novelty_threshold_recal  # 重复率台账→O8 阈值校准
    - op: recipe_experiment    # 配方变更按实验对待：记录、对照、可回滚（C12）
    - op: degenerate_baseline  # C10：IID-RS/SCS 退化基线周期性对照（永驻，不可移除）
  scheduled:                   # 可选：长程维护
    - op: cross_family_audit   # C9：跨家族模型对外部锚点集复评，self-bias 放大系数更新
      cron: "per_epoch"
    - op: ledger_reset_on_provider_change  # C4：换供应商=失败率台账重置

pi_op:                         # 分歧 2：默认规则表
  mode: rules                  # rules | bandit | rl；bandit/rl 须 C10 双前置
  rules:                       # YAML 可配，AIRA/AIDE 形态
    - {if: "seed_count < num_drafts(5)", use: draft}
    - {if: "buggy_leaf and depth < debug_depth", use: debug, prob: debug_prob}
    - {else: improve_best}
  bandit: {reward_source: funnel_yield_only,  # 协议：奖励唯一合法来源=O20 产率
           state_contract: [get_state, set_state]}   # checkpoint 契约

op_tax:                        # O19：显式定价+档位打包，注册进 M3
  tiers:
    propose_premium_apply_cheap: {enabled: false}   # O20 台账显示 apply 瓶颈时启用
    phase_handoff: {enabled: false}                 # 整代移交，不逐 call 路由
  accounting_unit: admitted_per_usd
  report_to: M3

self_modify:                   # O17：T=task_solution 时仅冻结声明；executor_spec 时四件套全配
  suite: [freeze_boundary]     # executor_spec → [freeze_boundary, survival_gate, snapshot_rollback, lineage_covers_gate]
```

**与其他模块的协议钩子**：
- **预算上报（→ M3）**：每档 op tax 注册预算消耗；嵌套算子上报 sub_funnels；相位 handoff 报告预算重分配。
- **tenure 消融钩子（→ M8 消费侧协议镜像）**：任何算子/profile 对比消融在 ≥3 个 tenure 点重复，排名反转作为一等发现报告；算子产率曲线按 tenure 呈现。
- **M1 接口**：π_op 与亲本选择分离；M2 供给亲本池 schema（rarity/children_count/per-instance 最优表/岛标签）与互补配对需求，公式参数进 M2 配置，选择在 M1 执行；O9 报警是 M1 切换父代公式的触发信号。

---

## 6. 七分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | 四算子集 vs 单算子 | 是否跑赢 IID-RS 退化基线且超噪声底 | 四算子集 + 退化自检常开 | `operator_set` 注册表（版本化，上下线=谱系事件） | IID-RS/SCS 退化自检不可移除；improve 原子改动默认开 | 算子数量投资优先级排在算子质量之后 |
| 2 | 规则表 vs bandit/RL | 评估噪声底 × 适应度确定性 | 规则优先级表 | `pi_op ∈ {rules, bandit, rl}`；每步记录所选算子与依据入 X1 | bandit 状态 get/set_state 入 checkpoint 契约 | 奖励唯一合法来源=O20 漏斗产率（M2×M1 接口契约）；读后验前先看漏斗 |
| 3 | 联合编辑 vs 窄作用域 | 可写面数 × 治理强度匹配 | 单面（代码） | `writable_scopes ⊆ {code,prompt,knowledge,runtime,config}` 默认 {code} | WHERE×WHY 坐标为候选 schema 强制字段（进 X1）；多面产物准入走 M9 统计门 | 每多一个可写面配一面冻结边界声明；知识/记忆面写入走 M5 门禁 |
| 4 | 可学习算子 vs 固定 prompt | 结果接地训练信号是否存在 | 固定 prompt | `operator_learnability ∈ {fixed, prompt_evolvable, meta_evolving, rl_trained}` | 权重版本+训练数据批指纹进 X1；升级顺序 prompt→meta→权重 | 算子适应度唯一定义=最近 H 子代改进量均值（与 O2 bandit 共享 O20 台账）；三前置（漏斗/可重跑评估/RL 设施） |
| 5 | 反馈带宽 | 消费方是否可优化对象 | public 标量+错误定位；剥离后 text 按需开启 | `feedback_bandwidth ∈ {scalar_loc, scrubbed_text, proxy_signal}`（full trace 是流向禁令非可选档） | op_context 构造器类型层黑名单；剥离规则版本化；带宽闸 self_mutable=false | 每步带宽快照入 X1；对人/审计全透明 |
| 6 | crossover 标配与否 | 是否带结构化契约三件套 | 标配但受约束（互补父选+debug 兜底+签名契约） | crossover 启用位（默认开，受契约约束） | `crossover_validity` 漏斗段与亲本数/签名约束记录强制；crossover 边谱系单独标注 | 无该段的 crossover 不得参与自适应选择；契约缺失降级为手工触发 |
| 7 | merge 收编与否 | Pareto 结构 + lesson 池是否在位 | 注册为可选、默认关 | `operators.optional = [merge]` | merge 谱系边=多父 + lesson 引用列表双记录 | 开启后按普通算子接受 O20 漏斗考核与 C10 退化基线对照；联邦拓扑判归框架层 |

---

## 7. 证据强度与投资优先序

**证据强度排序**（合并 Group A 结论与三批深挖，强→弱）：

1. **AIRA 算子集+作用域记忆 +14% 相对**（greedy 45.45% vs 39.77%，arXiv:2507.02554，受控实验）——**但含归因裂缝警告**：+14% 是三件套打包（算子集+作用域记忆+复杂度提示），各成分独立贡献从未分离；且 SB P=0.49 证明噪声评估下增量可与零不可区分。
2. **新颖性闸**（ShinkaEvolve Fig.9 消融收益最大单项；AI-Scientist 复评 +8%/0–0.3% 字符反证无闸打转）——方向强、精确数值缺（图内数值未读）。
3. **反思 lesson**（GEPA 超 GRPO 平均 +10%、35× 样本效率；MARS utilization 65.8%/跨分支 63.0%；Reflexion 精炼反思 +8%）——prompt 优化域为主，代码域迁移【推断】。
4. **diff 工程**（aider 合规率序列 71.6%–98.7%、供应商效应 14.7pp；Morph 25%+→<1%【证据陈旧风险】）——编辑通道证据硬，但 2026 模型代次无同口径基准。
5. **bandit（算子内 LLM 选择）**（ShinkaEvolve 消融仅 "slight"；Inria AOS 二十年 ECDF 重叠）——投入优先序末位。
6. **learned π_op / 可学习算子**（Harness-R1 +9.3pp/稀疏证据 +8.9±1.5pp 但限于交互 benchmark，代码进化域未验证；MetaSkill +23.54 基线较弱）——方向最有潜力、证据外推度最大。

**投资顺序表（硬编码进 C10 + O19 目标函数）**：

| 顺位 | 投资方向 | 依据 |
|---|---|---|
| 1 | 上下文工程/记忆配方（O5/O6 流水线） | AIRA +14% 三件套之二；AIDE₈₅ 16× 压缩 |
| 2 | 新颖性去重（O8） | ShinkaEvolve 消融梯度首位 |
| 3 | 父代选择结构（O11，执行归 M1） | 消融梯度次位；VRP 3 代塌缩反证 |
| 4 | diff/表示工程与 propose-apply 拆分（O3/O19） | 失败率 25%→<1% 的可靠性收益 |
| 5 | 结果接地的算子训练信号（O14，三前置就位后） | Harness-R1：信号来源>模型规模；排在 bandit 之前 |
| 6 | LLM/算子 bandit（O2/O10） | 消融梯度末位，"slight" |

---

## 8. Profile 兼容性验证（统一性的证明）

五个经典系统全部编译为 profile（Layer 3 算子选择 + Layer 4 配置），**无一处需要改内核**；每个 profile 诚实标注该系统实际违反的公理。

### 8.1 openevolve_diff（diff 工程 + 概率混合 + MAP-Elites 亲本）

```yaml
profile:
  name: openevolve_diff
  axes: {O1: 三算子基集+debug, O3: diff_block+概率混合[0.6,0.3,0.1], O5: 固定模板(受控),
         O11: MAP-Elites 岛式亲本池, O12: debug 兜底, O13: 配置即数据, O20: 计数台账}
  operators: {draft: llm, improve: llm_diff_block, debug: llm, crossover: null}
  representation: {patch_type_probs: [0.6, 0.3, 0.1], patcher: deterministic, max_resamples: 3}
  parent_pool: {structure: map_elites, fields: [island_id, feature_coords]}  # M2 供字段，选择在 M1
  novelty_gate: {embedding: 0.95}
  schedule: [sync, idle]
```
内核复用：diff+patcher+概率混合=O3 默认形态；EVOLVE-BLOCK 边界=C5 原生担保。
**公理违反标注**：原系统**违反 C12/C5 的精神而非条文**——OpenEvolve 选择策略硬编码于 ProgramDatabase（"换策略需改源码"），对应违反 C11 的不可替换性锁定条款；原系统无失败率台账（违反 C4/C6）。【诚实标注】

### 8.2 gepa_reflective（反思变异 + Merge + Pareto）

```yaml
profile:
  name: gepa_reflective
  axes: {O1: +merge 开启, O5: lesson 池引用制, O6: 轨迹级归因, O7: public 标量+minibatch 轨迹,
         O11: pareto_per_instance, O20: 计数台账}
  operators: {improve: llm_reflective, merge: llm_reflective_merge, crossover: null, debug: null}
  reflection: {depth: trajectory_level, attribute_to: prompt_module_element,  # GEPA 形态
               trigger: score_diff}
  parent_pool: {structure: pareto_per_instance}
  merge: {enabled: true, parent_select: complementary_lessons,  # 分歧 7 前置两结构就位
          lineage: [multi_parent_edge, lesson_refs]}
```
内核复用：O6 轨迹级归因档、merge 双记录谱系边、Pareto 亲本结构全部原生。
**公理违反标注**：原系统**无四段漏斗记账（违反 C6）**、无新颖性闸（违反 C3）；merge 仅单系统单域（IFBench +8.16%）证据，跨域为【推断】。【诚实标注】

### 8.3 dgm_selfmodify（单算子自进化 + 四件套）

```yaml
profile:
  name: dgm_selfmodify
  axes: {O1: 单算子 generate/self_modify, O3: full_rewrite(代码面), O15: executor_spec,
         O17: 四件套全配, O20: 计数台账}
  operators: {self_modify: llm_full_rewrite}   # arity=1（父=自身前一版本）
  self_modify:
    suite: [freeze_boundary,        # ① exploration 机制(archive/父选择)刻意冻结——DGM 原生
            survival_gate,          # ② compile+保留编辑能力——DGM §3 原生
            snapshot_rollback,      # ③ 补齐（DGM 原生缺）
            lineage_covers_gate]    # ④ 补齐（DGM 原生缺）
  evaluation: meta_eval_N_tasks     # 元评测；统计显著性门归 M9（DGM −1.1% 教训）
  degenerate_baseline: resident     # C10：单算子配置必须周期性对照 IID-RS/SCS
```
内核复用：单算子集是 O1 合法取值（退化自检永驻此时尤其关键）；四件套=O17 原生枚举。
**公理违反标注**：原系统**违反 C6（无漏斗记账，DGM 部署 −1.1% 回归的直接原因——无显著性门亦无产率台账）**、**违反 C11 第④件（gate/防护代码版本未入谱系）**；去 archive 消融显著退化证明其单算子表达力隐性锁定（C10 外部对照缺失）。【诚实标注】

### 8.4 openrsi_unified（统一动作空间 + arity 0/1/2）

```yaml
profile:
  name: openrsi_unified
  axes: {O1: 四算子集(含 crossover), O2: rl_policy(可训练 Sample Operator), O11: 加权采样,
         O13: 配置即数据, O20: 漏斗反馈选择}
  operators: {draft: llm, improve: llm_diff_block, debug: llm, crossover: llm}
  crossover: {contract: {signature_constraint: true, role_labels: true, perm_randomize: true},
              child_debug_fallback: required,    # 分歧 6 三件套
              lineage: multi_parent_edge}
  pi_op: {mode: rl, reward_source: funnel_yield_only,   # 前置：O20 就位+消融超噪声底
          unified_action_space: true}                    # 训练与推理共享同一动作空间
  parent_pool: {structure: weighted, fields: [reward, children_count, children_variance, rarity]}
```
内核复用：arity 0/1/2 齐备=O1 默认集的定义本身；统一动作空间=同一算子签名供训练/推理。
**公理违反标注**：原系统 RL π_op 无"RL vs 规则"分离消融（C10 挣得存在未证明【诚实标注】）；加权公式参数（α、rarity 定义）与 ShinkaEvolve 口径不一致、无横向对照（证据空缺）。profile 层强制补 O20 漏斗后方可启用 rl 档。

### 8.5 funsearch_island（骨架约束 + 岛隔离）

```yaml
profile:
  name: funsearch_island
  axes: {O1: 单算子 improve(骨架内), O3: evolve_block, O5: 无记忆(none), O6: 无反思,
         O9: 探针监控+岛拓扑维护, O11: 岛比例采样+迁移, O20: 计数台账}
  operators: {improve: llm_evolve_block}       # 骨架外冻结=C5 结构担保的极端形态
  representation: {evolve_block: {boundary: skeleton_frozen}}
  parent_pool: {structure: islands, migration: periodic, fields: [island_id]}
  diversity: {probe: required, maintenance: island_isolation}   # 用拓扑买多样性
  novelty_gate: {embedding: 0.95}
```
内核复用：evolve_block 块外冻结与 self_mutable 冻结边界共用同一声明机制（O3×O17）；岛结构=O11/O9 原生取值。
**公理违反标注**：原系统**无新颖性闸与漏斗记账（违反 C3/C6）**；岛迁移频率/比例无一手消融（证据空缺，profile 只保证可配可记账）。【诚实标注】

**兼容性结论**：五个 profile 覆盖调研中全部经典系统设计空间，差异 = 算子集选择 + 表示档 + 上下文配方 + 亲本池结构 + 安全套件档位，全部在配置层。表达不了的进 §9 边界声明。

---

## 9. 诚实边界声明（统一不了的东西，合并后 8 条）

1. **AIDE² 博客级证据整体降档警告**：AIDE² 全部数字（16× 压缩、~90% 拒绝、8 天 7 代、反作弊层自毁）来自 weco.ai 博客、无同行评审；ShinkaEvolve 三消融只给方向性结论（图内数值未读）；CHERRL 116 步为转引；Morph 停在 2025-05【证据陈旧风险】；RelayEvolve 百分比未复核。ExecutorSpec 层最强正面叙事恰是证据最弱处——结论方向不降级（反例证据独立存在），数字置信整体降档。
2. **O16（算子嵌套度）双向空白**：无任何一手同预算消融证明嵌套强于单次，也无证明其弱——默认低档是"无证据"而非"有反证"；sub_funnels/成本拆分等全部耦合设计是预防性结构。
3. **交叉/后代有效率的现代量化零报告**：LMX 是 2023 年数据；2025–26 代码进化论文普遍不报告后代有效率/apply 失败率——空白本身是报告偏倚失效（已记录在案），C7 的阈值与三件套参数因此无现代标定，我们只记账不定参。
4. **AIRA +14% 归因裂缝不可消除**：三件套打包（算子集+作用域记忆+复杂度提示）各成分独立贡献从未分离；merge 的 +8.16% 单系统单域；EvolveNet 域条件化收益与联邦拓扑混杂。轴系默认值是"打包采纳最强证据组合"而非逐成分验证。
5. **阈值类参数全线无标定证据**：新颖性阈值 0.95、多样性报警线、self-bias 放大系数报警线、ttl/抽象度抽检比、meta 层 H 窗口、debug 上限（10 节点/12h 单系统经验值）——全部是公理推导的占位符；设计只保证可配、可记账、可回滚，不保证默认值为最优。
6. **可学习算子未在代码进化域验证**：Harness-R1 限于交互 benchmark（WebShop/ALFWorld/DBBench），M2 主战场（程序候选变异）的训练档收益是外推【推断】；same-batch 奖励的多轮共演化动态只验证一轮。
7. **披露防御的有效性侧零量化**：表面剥离的残余可讨好面与绕过率无一手测量；leaky-anchor 剂量-效应曲线只有 Doubao 单点（35.1→12.7）；1bit 档的机会成本无对照——C8 的防泄收益有证据、代价无证据。
8. **"算子生成讨好 judge 工件"在代码进化场景无直接量化**：C8/C9 主证据来自 self-refine 与 rubric-RL 邻域，向代码变异的迁移性标【推断】；跨家族校验的成本与频率无实证依据（进 M3 预算是设计决策而非证据结论）。

---

## 10. 分阶段落地（M2a–M2e，对齐 M5a–M5e / E9a–E9e 粒度，对接 ADAPT-v1.1）

| 期 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|
| **M2a（类型层，P0）** | OperatorSpec/ContextRecipe/VariationProposal/FunnelRecord/DiversityProbe 落 core/operator/types.py；op_context 类型层白/黑名单（consume.py）；全部字段有默认值 | 类型层增量并入 ADAPT-v1.1 Step 0；缺 similarity_records 的候选被拒绝入库的单测通过 | 无，与 G1/M5a/E9a 类型层改动同批 |
| **M2b（最小可用，P1）** | 四算子集 LLM 实现 + 确定性 patcher + 规则表 π_op + 新颖性闸（0.95）+ 四段漏斗计数器（sync 槽）+ 退化基线 IID-RS/SCS 常驻；openevolve_diff / funsearch_island 两 profile | 漏斗四段在真实运行中产出非零台账；退化基线对照实验跑通；sync 槽注册 LLM 算子直接报错的单测通过 | M2a；并入 Step 1 |
| **M2c（上下文与安全，P2）** | ContextRecipe 作用域路由（sibling/ancestral）+ lesson 池引用制（接 M5）+ text_feedback 剥离器（版本化）+ debug 兜底（上限可配）+ O17 第①④件（冻结边界+谱系覆盖 gate 代码）；gepa_reflective profile | 配方版本 hash+lesson 引用列表入 X1；剥离规则版本可回滚；过期 ttl 条目运行期拦截的集成测试通过 | M2b + M5b 条目模型；并入 Step 2 |
| **M2d（merge/自修改/经济学，P3）** | merge 可选算子（Pareto+lesson 前置检查）+ O17 第②③件（存活门+快照回滚）+ op tax 定价表注册 M3 + 多样性探针 idle 槽；dgm_selfmodify profile | 四件套在 ExecutorSpec 沙箱运行中全配；快照回滚演练通过；op tax 档位在 M3 预算曲线可见 | M2c + M8/M9 准入门就位；并入 Step 3 |
| **M2e（学习化档，随治理里程碑）** | prompt 可进化档（独立 archive）→ bandit 插件（漏斗奖励）→ meta 双时间尺度 →（三前置就位后）RL 训练档；openrsi_unified profile 的 rl 档 | 每档升级附消融记录证明增量超 M8 噪声底；C10 三前置检查单全部通过才开放下一档 | M2d + O20 台账积累（每算子≥数十代）+ RL 设施；不阻塞 Step 0–3 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做无退化基线对照的算子集变更（IID-RS/SCS 永驻，移除=构建失败）
- 不做 full trace/台账元数据进变异器 prompt 的任何档位（流向禁令非配置项）
- 不做逐 call 模型路由（O19 决策单位是相位/代；O10 bandit 为插件非默认）
- 不做联邦多主体合并拓扑（判归框架层/部署层，M2 不留轴不留接口）
- 不做 LLM 失败判定硬过滤（is_buggy 式布尔过滤构建期拒绝，C11）

---

## 11. 一句话规格

> **M2 = 冻结的 OperatorSpec/ContextRecipe/VariationProposal/FunnelRecord 数据模型与四段漏斗记账规则（提议→可应用→可运行→准入，无漏斗数据的算子不得参与自适应选择）+ 统一纯函数算子签名与默认四算子集（draft/improve/debug/crossover，退化基线 IID-RS/SCS 永驻自检）+ 带宽闸（public 标量+错误定位最小披露，类型层白/黑名单）与新颖性闸（0.95+plateau 归因二分）+ 自修改四件套（冻结边界/存活门/快照回滚/谱系覆盖 gate 代码，第④件优先）+ 六操作面×三实现类矩阵（learnable 档三前置：漏斗数据/可重跑评估/RL 设施）+ 十九轴编译成的 profile（OpenEvolve/GEPA/DGM/OpenRSI/FunSearch 全部是 profile 实例）+ 双速调度（sync 禁 LLM）与 op tax 经济学（显式定价、整代 handoff、admitted_per_usd 上报 M3）+ C1–C12 公理内核化与四条既有不变量承接（第五候选 I-披露待框架级确认）。**
