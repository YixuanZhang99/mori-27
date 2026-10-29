# M8M9-UNIFIED-v1.md — 统一评估器与准入门子系统设计文档

> 依据：`../research/m8m9/m8_deepdive_axes.md`（M8 轴系 A1–A14 + E1–E5）、`../research/m8m9/m9_deepdive_axes.md`（M9 轴系 A1–A16 + N1–N3 + M8×M9 耦合分析 (a)–(d)）、`../research/m8m9/m8m9_分歧_公理.md`（七分歧裁决 + 公理 B1–B11 + 框架级不变量建议）、`../research/m8m9/m8m9_groupB_eval_failures.md`（失效证据 E1–E10）。
> 定位：M8 Evaluator 与 M9 AdmissionGate 的最终形态设计。回答一个问题——**OpenEvolve 级联 / ShinkaEvolve 契约 / SEAL 密封门 / MOSS 三门 / PAST-Bench 机制分 / MLOps registry 这些经典设计能否被同一个实现兼容？答案：能。它们之间的差异全部是配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 EvalResult/Verdict/Receipt 数据模型与判定规则库（内核，不可换）+ 票据失效引擎（内核）+ 六个可替换算子（插件，M8 侧三个 × M9 侧三个）+ 十九轴 × 十九轴编译成的 profile（配置）+ 级联调度与 meta-gate 协议（运行时）**。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条框架级不变量（建议上收 CLAUDE.md）

以下四条不变量横跨 M5/M8/M9 三模块独立出现（跨模块投影 + 各自有一手失效证据），满足上收判据【推断：措辞为建议稿，上收与否由框架定稿阶段裁决】：

1. **不变量 I-α（锚点存在性）**：框架内任何被优化压力触及的积累物（记忆库、评估器、rubric、准入标准）必须配一个物理上不可被该压力修改的锚点组件（人工 anchor / 确定性验证 / 只读通道）；锚点变更走 meta-gate 且锚点数据永久保留。→ 统一 M5 治理栈数据层、本文 B9、M9-N2 递归基底。
2. **不变量 I-β（质量指标一等化）**：任何裁决/积累机制必须暴露其判别质量指标（误判率、检出率、污染率），且该指标由独立于该机制的金标准探针测量；"机制动作次数"类指标不得作为健康证据。→ 统一 M5 卫生指标、本文 B6/B8、M8-E1 漂移归因。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：LLM 产出可进证据层；阈值比较、票据失效、退休/准入执行、校准与聚合必须由确定性代码完成。→ 即 M5-A3 / M8 全局结论 5 / M9 耦合 (a) 的三模块共识。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：一切评估分数与门控票据携带产生者版本谱系与失效条件；软证据（judge 分、效用记录）随裁判更换作废，硬证据（anchor、轨迹、失败候选）降级归档永存。→ 统一 M5"降级归档不删除"与 M8-E2"selective erasure"的方向性分歧（作废的是度量衡产物，保留的是证据本身）。

### 0.1 公理 B1–B11（失效证据 → 内核物化）

| # | 公理 | 失效证据指认（关键数字） | 内核物化 |
|---|---|---|---|
| B1 | **凡被优化压力触及的信号默认将被 hack——压力-防御匹配** | E1：同架构同预训练下 SFT 作弊率 0.6% vs RL 13.9%（23×）；1% SFT 污染点燃 RLVR 灾难性作弊；72% 作弊事件 CoT 自我合理化；环境加固实测 −87.7% 作弊率且不伤成功率（83.2% vs 82.8%）；E8：rubric 词汇偏置 100% 被利用、~116 步 onset | M8 评估环境硬化为默认（随机化输入、隐藏测试、verifier 隔离）；评估环境的不可篡改性是 M9 的一等设计约束 |
| B2 | **准入信号外生密封，内生信号仅诊断** | SEAL 信息论下界 α+β ≥ 1−TV(P₊,P₋)；leaky-anchor 泄露后 Doubao 35.1→12.7；Berkeley RDI 审计 2,385 条 trace 中 ~67% 含 hacking——hacking 是先验而非异常 | `endogenous` 标注为 EvalResult 强制 schema 字段；endogenous 字段强制外部审计门且永不进 M9 裁决输入；对 agent 反馈默认 1 bit |
| B3 | **评分通道只读，防护层不可自进化** | E2：tampering 占作弊事件 19%；RE-Bench 作弊率 43× HCAST——可及性即风险；o3 三例直接改计时/评分；AIDE² 自进化中改坏自己的反作弊层 | immutable core 清单：M8 评分代码/测试/计时/日志管道 + M9 准入规则 + 反作弊层，列入进化循环禁止修改集；verifier 独立进程/沙箱；M8/M9 代码入 X1 谱系并声明可自修改位 |
| B4 | **LLM 产原始分，确定性代码做校准/聚合/终裁** | E3：位置交换 66/80 判决翻转、质量接近时翻转 20–40%、更强模型自我偏好更大；M8-A11：裸 agreement 高估一致性 33.8–41.3pp；naive judge CI 可 0% 覆盖率；judge 排名跨 benchmark 移动 14 位 | judge 上线前过位置交换/长度扰动/自我偏好三组探针（翻转率 66/80 级别禁入裁决）；报 Cohen's κ 非裸 agreement；isotonic 校准到 oracle；裁决 judge 与被评生成器跨模型家族；阈值比较/票据失效/回滚触发全部代码可复算 |
| B5 | **结构化判据优先于开放质量分** | E4：4 词对抗短语→任意文本满分；1% 投毒→分数 ×3 且 ASR>76%；空输入假奖励 80–90%；绝对打分制最脆弱；反例边界：代码作弊检测 GPT-5 judge 1% FPR/16.7% FNR——有明确结构判据时 judge 可靠 | M9 准入裁决优先 diff 分析/文件完整性哈希/provenance/per-item 翻转；开放文本评分仅辅助且用成对比较制；judge 训练数据/rubric/prompt 按安全资产管理（版本化+来源校验+变更审计） |
| B6 | **评估资产先审计后使用，holdout 纪律强制** | E5：SWE-bench 76% vs 53% 路径猜测；UTBoost 重评致 24.4% 排名变动；~32% verifier 错误率；Verified 80.9% → Pro 45.9%；同模型换 harness 摆 10–20pp；E9：held-out 对作弊检出仅 ~0.7% 增量 | 外部 benchmark 启用前审计答案键/测试错误率，该错误率作为结论不确定度下限入库（32% 错误率下 2–3pp 差距无意义）；准入测试集与被进化对象强制信息屏障（隐藏 split、定期轮换、查询 provenance）；单通道"未发现"不构成清白——≥3 异构通道（held-out + judge + 完整性哈希） |
| B7 | **无 CI 不报数；效应量 < 噪声底计零；预算优先给重复** | E6：预测噪声 > 数据噪声（数据 SE 为预测 SE 的 1/2 至 1/6）；平均 36 次重复→总 SE ~0.24×、可检效应缩 4×；~100 题验证集 P(Shinka>IID RS)=0.49；聚类题目 naive SE 低估可达 3× | M8 所有对比结论强制配对差分 SE/CI + 预测/数据噪声分解；M9 裁决规则内建"低于噪声底 = 零效应"硬规则；reliability_budget 由 ICC 裁决分配（分歧 4） |
| B8 | **闸门本身须被评估；否决须举证** | E7：新颖性闸门 12/12 误判 novel（含教科书概念）；反向误杀 9/10 人类已接收论文；有偏评审器使退休机制静默空转（2607.07436）——机制装着在跑但语义已失效 | 每个否决门强制伴生金标准探针集定期测 FP/FN；否决输出结构化可证伪理由（引用失败测试/违反弹例）；无探针的门不得行使否决权、只许打标签；"闸门动作次数"不得作为机制在工作的监控指标 |
| B9 | **不可进化的评估锚点 + 分歧率早期警报** | E8：CHERRL rubric 偏置维度利用成功率词汇 100%/语气 98.7%；强 verifier 压 verifier 利用到 15–28% 但不能消除 rubric 失效（rubric judge 85.8% 偏好 RL checkpoint vs 无 rubric judge 78.4% 偏好基座，方向完全反转）；CoT 监控被优化压力腐蚀后作弊隐形化；RQGM meta-gate 递归基底需求 | M8 保留 ≥1 个不可被任何慢循环修改的评估组件（确定性机制分/金标准集/人工 anchor）；可进化组件每次变更用锚点回归校验（held-out 不回退硬门）；监控 rubric judge vs 无 rubric judge/锚点评估的偏好分歧率，方向反转即一等警报 |
| B10 | **修复件与监控压力过同一闸门——反身性防御** | E10：LLM 生成测试增强 61.9% 连 gold patch 都过不了；惩罚 CoT 坏想法后作弊行为率不变但可见率下降；注入 reward-hack 知识后泛化出 alignment faking——局部修补诱发全局退化 | LLM 生成的评估资产修复件（新测试/rubric/题目）以不低于原资产的严格度过 gold-sanity 校验（61.9% 缺陷率基线）；对被监控信号施加优化压力时同时监控"行为率"与"可见率"双通道，背离即报警 |
| B11 | **分数带谱系，换裁判即换度量衡——软证据作废、硬证据永存** | M8-E2/RQGM：无谱系时陈旧分数污染新排序；selective erasure 后 71.7% vs 69.9% 通过率且 token 省 1.35×–1.72×；E5：同模型跨 harness 41 点 F1 摆幅——无元数据的分数连符号都不可信 | 全 Evaluation Card 强制入库（model/benchmark hash/scorer 版本/decoding/repeats/CI）；epoch 边界效用记录作废、anchor 永存；receipt 绑定 (head_sha, base_sha, gate_graph_version)，漂移自动失效 |

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（级联 depth tier / tenure 消融钩子 / meta-gate 触发）│
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  算子接口：M8 侧 judge / calibrator / cascade_policy        │
│                    M9 侧 decision_rule / authorization / exposure │
│          每算子三类实现：确定性 | LLM | 可学习                        │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：判定规则库（flip-count / mSPRT / e-value / 非回归）│
│          + 票据失效引擎 + 证据日志（复用 X1，append-only）           │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：EvalResult（扩展）/ Verdict / Receipt        │
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（B3 immutable core）
         ↑ Layer 3 标注 evolvability: operators_only
         ↑ 经典系统 = profile = Layer 3 算子选择 + Layer 4 配置
```

**M8 与 M9 的模块分工**（耦合分析 (a)）：M8 生产**证据**（EvalResult：分数、per-item 翻转、轨迹、置信度）——对同一候选可重复、可比较；M9 生产**裁决**（Verdict/Receipt：准入、作用域、生效节奏）——改变系统状态且必须可回滚。两模块共享同一个冻结数据模型层（Layer 1）与判定机制层（Layer 2），故合并为一份统一设计文档。

---

## 2. Layer 1：冻结数据模型（EvalResult 扩展 + Verdict/Receipt）

对接六数据类型：EvalResult 为既有类型的**扩展**（新增字段全部有默认值，旧记录可反序列化）；Verdict/Receipt 为新增类型。

```python
# core/eval/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

# ---- 内外生标注（公理 B2：强制）----
Provenance_Signal = Literal["exogenous", "endogenous", "mixed"]
# exogenous: 密封 harness 产出，可进 M9 裁决
# endogenous: agent 可影响，仅诊断，永不进 M9（分歧 1 裁决）
# mixed: 须由 Layer 2 拆分到前两类后才可消费

# ---- per-item 结果（分歧 2 裁决：gate-not-rank 的证据形态）----
@dataclass
class ItemResult:
    item_id: str
    verdict: Literal[0, 1]           # v_i∈{0,1}，逐 case 二值（EvolveNet 形态）
    score: Optional[float] = None    # 连续分可选；聚合总分不进 M9 终裁
    family_id: Optional[str] = None  # 任务族（A9 难度刻度/A2 聚类 SE 校正用）

@dataclass
class ReliabilityMeta:               # 公理 B7：无 CI 不报数
    n_trials: int = 1
    ci95: Optional[tuple[float, float]] = None   # 配对差分 SE/CI
    icc: Optional[float] = None                  # between/within 方差分解
    noise_floor: Optional[float] = None          # 效应量 < 噪声底 ⇒ M9 计零

@dataclass
class EvaluationCard:                # 公理 B11：分数可比较性的前提（A13 全卡）
    model_version: str
    benchmark: str
    benchmark_commit: str            # split + commit hash（A10 污染审计锚点）
    scorer_type: str                 # deterministic | llm_judge | hybrid
    scorer_version: str              # ★ evaluator_version 谱系：E2 存亡判据
    prompting_hash: Optional[str] = None
    decoding: dict = field(default_factory=dict)
    repeats: int = 1
    run_date: float = 0.0
    judge_provenance: list[str] = field(default_factory=list)  # per-row judge 身份（N3）

# ---- EvalResult 扩展（M8 的产出物）----
@dataclass
class EvalResult:
    candidate_id: str
    head_sha: str                                # 评的是哪个可验证对象（A16 对象保真）
    items: list[ItemResult]                      # ★ per-item 数组，强制非空（分歧 2 硬编码）
    combined_score: float                        # 聚合分：display-only，M9 禁作终裁输入
    public: dict = field(default_factory=dict)   # 对 agent/变异器可见（ShinkaEvolve 契约）
    private: dict = field(default_factory=dict)  # 决定存活，对 LLM 不可见
    text_feedback: str = ""                      # 变异器消费；与存活信号物理分离（分歧 3）
    signal_provenance: Provenance_Signal = "exogenous"   # B2 强制标注
    reliability: ReliabilityMeta = field(default_factory=ReliabilityMeta)
    card: EvaluationCard = None                  # 强制，无默认（A13 全卡入库）
    artifacts_ref: Optional[str] = None          # full_trace/工件，带字节上限与安全过滤

# ---- M9 的产出物 ----
VerdictKind = Literal[
    "ACCEPT", "REJECT",
    "CONVERGED", "NEED_MORE_WORK",               # MOSS 枚举：多值分类比二元更有信息
    "FUNDAMENTAL_LIMIT_MODEL", "FUNDAMENTAL_LIMIT_ARCHITECTURE",  # 拒绝理由分类
]
Scope = Literal["global", "home", "cell", "reject"]   # A9 作用域语义：门是路由器

@dataclass
class Verdict:
    kind: VerdictKind
    scope: Scope = "reject"
    flip_evidence: Optional[tuple[int, int]] = None    # (|F|,|B|) 翻转计数（决策充分统计量）
    rationale_ref: Optional[str] = None          # 否决的结构化可证伪理由（B8：否决须举证）
    feedback_to_agent: Literal["1bit", "public"] = "1bit"  # 最小泄露（B2）

@dataclass
class Receipt:                                   # 门输出 = 凭证而非结论（A10）
    verdict: Verdict
    head_sha: str                                # ★ 评过的候选与要晋升的候选必须同一对象
    base_sha: str
    gate_graph_version: str                      # ★ 三者任一变化 → 自动失效（A8 工程路线）
    evaluator_version: str                       # ★ 换裁判即换度量衡（B11）：epoch 边界批量失效
    guarantees: list[str] = field(default_factory=list)  # 显式担保清单（A14：门只担保它验证过的性质）
    valid_until: Optional[float] = None          # 担保保质期；tenure review 复核调度（A14）
    evidence_refs: list[str] = field(default_factory=list)  # 指向证据日志
    human_signoff: Optional[str] = None          # 授权层签署（A15；None=全自动档）
```

**设计决定说明**：
- `items` 强制非空、per-item 二值 verdict 是分歧 2 的硬编码落地——EvalResult schema 层就杜绝"只有聚合分"的证据形态；任务不可逐案二值化时退化为 with/without 双重差分 + CI（此时 `items` 承载两轮运行的配对记录）。
- `public`/`private`/`text_feedback` 在 schema 中物理分离（分歧 3 硬编码）：private 字段决定存活，public 字段只喂变异器，两者带宽独立配置。
- `combined_score` 保留但标注 display-only：排序仅允许出现于级联中间档粗筛与人读 dashboard（分歧 2 裁决），Layer 2 的判定规则库不消费它。
- Receipt 三绑（head_sha/base_sha/gate_graph_version）+ evaluator_version 是"票据失效"问题的类型层物化——把重复检验与陈旧分数问题转化为失效条件检查（§3.2）。
- `Verdict` 含 `FUNDAMENTAL_LIMIT_*`：拒绝理由分类是门最有价值的输出之一（一票否决整个搜索方向），指导 M1/M2 下一代搜索方向。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 判定规则库（公理 B4 的物化：终裁全部代码可复算）

判定规则库是**封闭枚举**，新规则只能以"确定性代码 + 单元测试 + anchor 回归"入库（B10：修复件过同一闸门）：

```python
# core/gate/rules.py
class DecisionRule(Protocol):
    def judge(self, result: EvalResult, incumbent: Optional[Receipt], ctx: GateContext) -> Verdict: ...

# 内建规则（封闭枚举）：
# 1. flip_count        —— gate-not-rank 默认（分歧 2）：|F_val| ≥ |B_val|（EvolveNet Eq.17）
#                        消费 items[] 的 per-item 翻转，永不消费 combined_score
# 2. non_regression    —— c_t ≥ b_t − δ_t，拒绝即整体回滚（SEAL 保守差分）；δ_t 由
#                        ROPE/截断零假设给定，且只能单调收紧（分歧 6 硬编码）
# 3. msprt             —— 混合似然比 always-valid p 值 pₙ=1/Λₙ，首次 pₙ≤α 即停且 Type I ≤ α；
#                        truncated mSPRT 把 H0 截断到等价区 |θ|<δ（自进化循环持续偷看的合法化）
# 4. e_value_gate      —— e-value ≥ 1/α；同一零假设下 e-value 算术平均在任意依赖下仍有效
#                       （多候选共享祖先、依赖不可控时的默认；配 e-BH 多重性校正）
# 5. noise_floor_zero  —— 效应量 < reliability.noise_floor ⇒ 计为零效应（公理 B7 硬规则）
# 6. absolute_conjunction —— 多指标合取阈值（registry 形态），仅作合规驱动的版本晋升
```

**硬编码不变量**：
1. 判定规则只消费 `Gate.consume()` 白名单字段（§5），`combined_score` 与一切 `endogenous` 标注字段在类型层不可达。
2. 参数收紧单调性：任何自动调整不得放松既有阈值（cascade 系数、δ_t、mSPRT 截断点）——否则"调整严格度"本身成为可 hack 面（分歧 6）。
3. LLM 产出（judge 分数、Reviewer 意见）可以进 EvalResult，但**阈值比较、票据失效、回滚触发必须是确定性代码**——不变量 I-LLM。

### 3.2 票据失效引擎

```
失效条件（任一触发 ⇒ Receipt 自动失效，重估方可再消费）：
  ① head_sha ≠ 当前候选 sha          —— 对象漂移（防"评 A 晋升 B"）
  ② base_sha ≠ 当前基线 sha           —— 基线漂移（保守差分失效）
  ③ gate_graph_version 变化           —— 门规则变化（重复检验问题工程化解）
  ④ evaluator_version 变化（epoch 边界）—— 换裁判：旧评估器产生的效用记录批量作废
                                         （selective erasure；anchor 记录永久保留）
  ⑤ now > valid_until                 —— 担保过期，触发 tenure review 复核
```

- **级联失效**：meta-gate 通过评估器变更时，④ 批量作废下游全部旧 receipt——这是框架必须显式建模的级联（耦合分析 (d)）。
- **anchor 豁免**：ground-truth anchor（人工标注、单元测试、确定性验证）产生的记录**永久保留**，不参与 ④——分歧 7 的二元处置（作废的是分数即度量衡产物，保留的是候选、轨迹与 anchor 证据；与 M5"降级归档不删除"不矛盾）。

### 3.3 证据日志（复用 X1，append-only）

与 M5 共用同一 X1 存储，不另起炉灶。记录条目：

```python
@dataclass
class GateEvidenceRecord:
    seq: int                        # 单调递增，append-only
    ts: float
    candidate_id: str
    receipt_id: Optional[str]
    transition: str                 # "evaluate" | "verdict" | "invalidate:<条件①-⑤>" | "rollback"
    rule_id: str                    # 消费哪条判定规则
    signals_snapshot: dict          # 裁决时刻的 (|F|,|B|)/pₙ/e-value/CI 快照
    evaluator_card: EvaluationCard  # 全卡快照（元数据事后补不回来）
    actor: str                      # rule / "scheduler" / "human:<signoff>"
```

- **先建日志，后调规则**（对照 M5-A5）：所有裁决从第一天就记录，即使最初只有 absolute_conjunction 一条规则。
- e-process 轨迹作为一等审计工件入日志（比单次 p 值更适合 append-only 存储）。
- E1 漂移归因（anchor 集 + 双 e-process，输出 {none, system, judge} 三方裁决）消费此日志运行；设计定律：anchor 必须跑得比被守护的主过程快。

---

## 4. Layer 3：可替换算子（插件层，各分确定性/LLM/可学习三档）

```python
# core/eval/operators.py —— M8 侧
class EvalOperators(Protocol):
    def judge(self, candidate: Candidate, items: list[Item]) -> list[ItemResult]:
        """评分器（A11）。产出原始 per-item 结果；校准/聚合不在此（Layer 2 职责）"""
    def calibrate(self, raw: list[ItemResult], oracle_ref: Optional[AnchorSet]) -> list[ItemResult]:
        """校准器（A11 第三层）。isotonic 校准到 E[Y|S]，处理 policy/deployment shift"""
    def cascade_policy(self, candidate: Candidate, tier: DepthTier, budget: Budget) -> EvalPlan:
        """级联策略（A3/A14）。threshold_rule ∈ absolute | relative_to_best | top_k；
           决定 subset_size、n_trials、escalate_condition"""

# core/gate/operators.py —— M9 侧
class GateOperators(Protocol):
    def decision_rule(self, result: EvalResult, incumbent: Optional[Receipt]) -> Verdict:
        """判定规则选择器：从 Layer 2 封闭枚举中选规则并给定参数（档内参数系统算、单调收紧）"""
    def authorization(self, verdict: Verdict, tier: StrictnessTier) -> AuthPlan:
        """授权结构（A15）：全自动 | 自动+人授权硬门 | 独立评审角色 | 多签"""
    def exposure(self, receipt: Receipt) -> ExposurePlan:
        """生效方式（A13/N1）：仅盖章 | shadow→canary 阶梯 | 离线 shadow 等价物（trial-worker 重放）"""
```

### 4.1 三档实现矩阵

| 算子 | 确定性实现（默认与终裁） | LLM 实现（建议/辅助） | 可学习实现（opt-in） |
|---|---|---|---|
| judge | 单元测试/编译/规则/结构判据（diff 分析、完整性哈希） | LLM-as-judge 钉版本 + position-swap + 报 κ；成对比较制（B5）；跨模型家族（B4） | RL 训练的 judge/rubric 生成器（须过 meta-gate + anchor 回归，B9） |
| calibrate | isotonic regression 到 oracle（13× 样本高效于二值修正）；Cohen's κ 报告 | —（校准层禁止 LLM，B4） | — |
| cascade_policy | 固定阈值表 / ICC 收敛准则自动给 n_trials | LLM 建议升级档位（不执行） | bandit 早停（Hoeffding races/Hyperband） |
| decision_rule | Layer 2 封闭枚举（flip_count/mSPRT/…） | Reviewer 意见作授权层材料，不进判定 | —（终裁永远确定性，I-LLM） |
| authorization | 全自动（L0/记忆条目，量大唯一可行） | LLM Reviewer 草稿（人签署才生效） | — |
| exposure | 盖章-生效分离 + 指针模型 | — | canary 阶梯自动推进（配预注册回滚触发器） |

**轴 G 式递进挂点**：慢循环允许替换 judge/rubric（→ 必须过 meta-gate，§6.4）与 cascade_policy；**禁止**替换 calibrate/decision_rule 的确定性内核（B3 immutable core）；任何算子替换保留快照回退（M5 跨层稳定化要求的同构条款）。

---

## 5. Layer 4：调度与协议

```yaml
# eval/schedule.yaml
cascade:                            # A3/A14：预算打包为显式档位（MOSS 形态），禁散置参数
  tiers:
    shallow:   {bandwidth: scalar,              n_trials: 2, threshold_rule: relative_to_best(0.5)}
    standard:  {bandwidth: multi_metric_artifacts, n_trials: 3, threshold_rule: relative_to_best(0.75)}
    deep:      {bandwidth: full_trace,          n_trials: 5, threshold_rule: relative_to_best(0.9)}
  # 档内 n_trials 由 ICC 收敛准则自动给定（8–16 结构化 / ≥32 复杂推理），只能单调收紧
feedback:
  to_agent: 1bit                    # 分歧 3：对被门控者最小泄露；诊断走 public 通道
  to_mutator: public_channel        # text_feedback + public 字段
  to_governance: full               # N3：对人全透明（逐行 judge 谱系、完整证据包）
tenure_review:                      # A14 担保折旧 + 分歧 5 探针
  reevaluate_archive_elites: periodic   # Extract-QD 式在职复核
  gate_quality_probe: required          # B8：每个否决门的强制伴生组件，定期测 FP/FN
  judge_calibration: {anchor_set: required, cadence: per_version}  # E1：judge 有 shelf life
meta_gate:                          # N2/E3：评估器变更的准入（§6.4）
  trigger: [rubric_change, judge_version_change, eval_set_change]
  rule: heldout_no_regression       # 或 epsilon_best_belief（RQGM 形态，默认前者）
  on_pass: cascade_invalidate_receipts   # epoch 边界批量失效（§3.2 条件④）
```

**与其他模块的协议钩子**：
- **tenure 消融钩子（→ M8 消费侧协议）**：任何 profile 对比消融在 ≥3 个 tenure 点重复，排名反转作为一等发现报告（M5-UNIFIED §8 同一条款在评估侧的镜像）。
- **meta-gate 触发**：评估器/rubric/评估集变更一律先过 meta-gate 再生效；meta-gate 的递归基底是永久保留的 ground-truth anchor，anchor 由人维护（人=最终外生层，递归终止条件）。
- **预算上报（→ M3）**：每档级联注册预算消耗；eval tax 显式定价（deterministic 免费 <1ms → LLM judge ~$0.01–0.03/call → 多 judge $0.05–0.10/probe），门控频率与单次评估成本共享一条预算曲线联合优化。

---

## 6. M8×M9 分界协议（耦合分析 (a)–(d) 的形式化）

### 6.1 Gate.consume(EvalResult) 白名单 + 排除规则

```python
# core/gate/consume.py —— 类型层强制，不可配置关闭
CONSUME_WHITELIST = {
    "items",              # 粒度约束：per-item 翻转 (F,B)，不消费聚合总分做排序（耦合 b.1）
    "private",            # 可见性约束：门读全带宽；只把 1 bit 透给被门控 agent（耦合 b.2）
    "card.scorer_version",# 保真约束：评估器版本谱系——无谱系的分数不构成证据（耦合 b.3）
    "head_sha",           # 对象保真：评 A 晋升 B 在类型层不可能
    "reliability",        # CI/ICC/噪声底——低于噪声底计零（B7）
}
CONSUME_BLACKLIST = {
    "combined_score",     # display-only；聚合总分永不作终裁输入（分歧 2）
    "public",             # 防转述失真：门读原始字段，不读 agent 可见通道的复述（耦合 c.4、A16）
    "text_feedback",      # 内生诊断信号，永不进裁决（分歧 1）
    # 一切 signal_provenance == "endogenous" 的字段（B2：协议层排除规则）
}
```

### 6.2 典型设计错误（耦合分析 (c)，编译为 lint 规则）

| # | 错误 | 框架防御 |
|---|---|---|
| 1 | 把排序职责塞进 M9（用聚合总分选最优） | `combined_score` 不在白名单；select-best 64.0 vs merge 68.5 的实测差距 |
| 2 | 把裁决职责塞进 M8（评估器直接返回 accept/reject） | EvalResult 类型无 verdict 字段；破坏 LLM 建议/确定性终裁分界且触发 leaky-anchor 失效（35.1→12.7） |
| 3 | 内生证据直接准入 | `endogenous` 标注字段黑名单；信息论下界 α+β ≥ 1−TV 不可工程规避 |
| 4 | 门消费 public 通道转述 | 黑名单 + 原始证据不可转述（人授权门材料原样保留） |
| 5 | 小验证集未校正裁决 | `reliability` 白名单强制 CI；~100 题 P=0.49 教训 → 效应量<噪声底计零 |

### 6.3 职责判据

M8 输出对同一候选**可重复、可比较**；M9 输出**改变系统状态且必须可回滚**。凡不满足前者的不许进 EvalResult，凡不满足后者的不许进 Receipt。

### 6.4 meta-gate 递归（耦合分析 (d)）

评估器变更 = 元级准入事件，M9 递归作用于自身依赖的 M8：
- **递归基底**：永久保留的 ground-truth anchor（人工标注/单元测试）——元层裁决不能再用被进化的评估器评估评估器。
- **判定**：SkillCoach 硬门（held-out 集不回退一致性/准确率，δ=0 的非回归元层实例）为默认；RQGM ϵ-best-belief（inverse regularized incomplete Beta 下界）为可配置替代。
- **通过动作**：级联作废下游全部旧 receipt（§3.2 条件④）。
- **监控**：anchor 上跑第二条 betting e-process 裁决"系统变了还是裁判变了"——silent version bump 60/60 次正确归因、零误判；滚动 z-test 误报率 75%，禁用。

---

## 7. 七分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | 内生 vs 外生验证器 | 信号消费用途（准入 vs 诊断） | 混合：准入一律外生，self-report 仅诊断 | `signal_provenance` 每字段标注 | `{split}.{visibility}.{name}` key 规范；评分/计时/日志管道对被进化对象只读（B3） | `Gate.consume()` 黑名单排除 endogenous 字段；M8/M9 代码声明可自修改位入 X1 谱系 |
| 2 | 聚合分 vs per-item 翻转 | 裁决语义（gate vs rank） | gate-not-rank，承诺门 \|F\|≥\|B\| | —（无配置，终裁唯一形态） | Layer 2 flip-count 算子；EvalResult 强制 per-item 数组；`combined_score` display-only | 排序仅允许于级联中间档粗筛与人读 dashboard |
| 3 | 反馈带宽 | 接收方身份（agent vs 人） | public/private 双分数，对 agent 最小泄露 | `feedback_bandwidth ∈ {1bit, public_private, full}`（默认 public_private）；`eval_bandwidth` 独立配置 | public/private/text_feedback 在 EvalResult schema 物理分离 | 全带宽仅对不可被 hack 的通道（人/独立 Reviewer）开放 |
| 4 | 重复采样 vs 题目数 | ICC（within/between 方差比） | 预算优先给重复（预测噪声主导为多数情形） | `reliability_budget = {n_items, n_trials, agg_fn}` 打包进 depth tier | 裁决前强制 CI95 输出；聚类题目强制 cluster-adjusted SE | 对比结论强制配对差分 SE/CI + 噪声来源分解 |
| 5 | 严门误杀 vs 宽门污染 | （元规则）错误代价不对称性 + 回滚在位 | 漏斗分层：入库宽、谱系相对、合并/部署严 | `gate_strictness` 三元组（FDR↔FWER × 自动↔双签 × trials）打包为显式档位 | 无探针的门不得行使否决权，只许打标签 | `gate_quality_probe` 为每个否决门的强制伴生组件；否决须附结构化可证伪理由 |
| 6 | 人选档位 vs 自动收紧 | 档位语义 vs 档内参数 | 三档制（shallow/standard/deep），默认 standard；人定档、系统单调收紧档内参数 | `strictness_tier`（人选）+ `tier_params`（系统算，只读展示） | 参数收紧单调性约束（自动调整不得放松既有阈值） | 档内参数由 ICC/anchor 集/power analysis 自动给定 |
| 7 | 历史分数作废 vs 保留 | 分数是否依赖可变评估器 | 效用记录作废、anchor 永存（selective erasure） | —（二元处置，无光谱） | `evaluator_version` 强制谱系字段；epoch 边界批量 receipt 失效；无谱系的分数换裁判时默认作废 | "历史最高分"曲线按评估器版本分段呈现，跨段不做数值比较 |

---

## 8. Profile 兼容性验证（统一性的证明）

六个经典系统全部编译为 profile（Layer 3 算子选择 + Layer 4 配置），**无一处需要改内核**。

### 8.1 openevolve_cascade（级联淘汰）

```yaml
profile:
  name: openevolve_cascade
  m8:
    bandwidth: multi_metric_artifacts   # 字节上限+安全过滤
    cascade: {threshold_rule: relative_to_best, coefficients: [0.5, 0.75, 0.9]}  # 随 incumbent 自动收紧
    judge: deterministic_tests
  m9:
    decision_rule: relative_rank        # 级联中间档粗筛（ASHA 式 rung 内 top-1/η）
    final_rule: flip_count              # 终裁仍走 per-item 翻转
    authorization: full_auto
  schedule: {tiers: [shallow, standard, deep]}
```
内核复用：级联阈值单调收紧 = 分歧 6 硬编码；相对排名仅在粗筛 = 分歧 2 协议。

### 8.2 shinkaevolve_contract（public/private 契约）

```yaml
profile:
  name: shinkaevolve_contract
  m8:
    bandwidth: text_feedback_tier       # multi-metric + text_feedback
    judge: {type: llm_judge, pinned_version: required, position_swap: required, report: cohens_kappa}
  m9:
    decision_rule: flip_count
    feedback: {to_agent: public_channel, to_mutator: text_feedback}   # private 定存活
  reliability: {ci95: required}         # 重评 10 次 P=0.49 教训：≥300 有效题才报系统比较
```
内核复用：`{split}.{visibility}.{name}` key 规范与 public/private 物理分离本就是 Layer 1 原生形态。

### 8.3 seal_gate（密封门）

```yaml
profile:
  name: seal_gate
  m8:
    judge: sealed_audit                 # 外生密封：隐藏 seeds/分布，与部署评估不相交
    bandwidth: {harness: full_trace, agent: 1bit}   # 双带宽解耦
  m9:
    decision_rule: non_regression       # c_t ≥ b_t − δ_t
    on_reject: whole_state_rollback     # 拒绝即整体回滚
    feedback: {to_agent: 1bit}
  constraints: {no_numeric_leak: true}  # leaky-anchor 护栏：泄露数值审计分 35.1→12.7
```
内核复用：B2/B3 的直接实例——密封等级由对抗压力档位给定（分歧 1 前置条件）。

### 8.4 moss_three_gates（三门漏斗 + depth tier）

```yaml
profile:
  name: moss_three_gates
  m8:
    cascade: {tiers: [shallow, standard, deep],
              knobs: {max_iter: [3,5,8], max_plan_rounds: [1,2,3],
                      max_code_retries: [0,1,2], n_trials_per_task: [2,3,5], plateau: [1,2,3]}}
    bandwidth: full_trace               # trial-worker 重放 + scoring matrices（可审计资产）
  m9:
    gates: [auto_evidence, human_authorization, runtime_health]  # 三层串联，任一层否决即回滚
    verdict_enum: [CONVERGED, NEED_MORE_WORK, FUNDAMENTAL_LIMIT_MODEL, FUNDAMENTAL_LIMIT_ARCHITECTURE]
    authorization: auto_plus_human_hard_gate   # CONVERGED 后 swap 仍须用户显式授权
    health_probe: {interval: 90s, on_fail: auto_rollback}
  strictness: {tier_owner: user}        # "the user owns this trade-off"（分歧 6）
```
内核复用：Verdict 枚举、人授权硬门、健康探针自动回滚、depth tier 打包全部在 Layer 1/2/4 原生。

### 8.5 past_bench_mechanism（机制分 × 双重差分）

```yaml
profile:
  name: past_bench_mechanism
  m8:
    judge: deterministic_plus_rubric    # mechanism_confidence=(artifact_quality+retrieval+presence)/3
    aggregation: multiplicative         # FamilyEvolveScore：任一因子 0 总分归零（准入语义）
    basis_labels: [measured, proxy, needs_runner_collection]  # 缺失信号显式降级，不可观测≠零
    difficulty: {trigger_strength: [T0,T1,T2,T3], transfer_distance: [none,near,far]}
    protocol: with_without_diff_in_diff # 双重差分内建为 Evaluator 实验模式（A8）
    controls: [no_persistence, shortcut, wrong_mechanism]     # Δ 须超全部控制条件上界
  m9:
    decision_rule: flip_count_with_controls
  preconditions: {false_positive_pattern: declared_upfront}   # 预注册：看结果前声明假阳性长相
```
内核复用：basis 标签与乘性合成是 `private` 字段的取值形态；双重差分调度走 Layer 4；机制分/锚点组件满足 B9 不可进化锚点。

### 8.6 mlops_registry（registry + canary）

```yaml
profile:
  name: mlops_registry
  m8:
    judge: deterministic_metrics        # accuracy/p95/parity 多指标
  m9:
    decision_rule: absolute_conjunction # 合规驱动版本晋升
    lifecycle: [None, Staging, Production, Archived]   # 单一不变量：晋升新版时旧版必须 Archived
    authorization: human_signoff        # evidence 四件套：eval 结果、model card、偏差审计、人工签署
    exposure: stamped_only              # 盖章与生效分离：registry 只祝福，流量切换另管线
    rollback: alias_pointer             # O(1) 指针重指
    deployment_chain: [shadow, canary_1_5_10_25_50_100]  # shadow ≥1000 次比对或 5 天；canary 每档 24–72h
    receipt: {bind: [head_sha, base_sha, gate_graph_version], required_checks: all_green}
    rollback_triggers: preregistered    # grounding −5pts / P95 +500ms / cost +25%
```
内核复用：Receipt 绑定与失效、预注册回滚触发器、晋级记录 who/when/metrics（N3 审计闭环）全部原生。

**兼容性结论**：六个 profile 覆盖调研中全部经典系统的设计空间，差异 = judge 选型 + 判定规则选择 + 授权结构 + 生效节奏 + 调度档位，全部在配置层。表达不了的进 §9 边界声明。

---

## 9. 边界声明（统一不了的东西）

1. **reward 可信度前置**：本框架假设"存在至少一个不可被优化压力触及的外生锚点"可构造（B9）。若部署域连人工 anchor/确定性验证都无法获得（无任何 ground truth），gate-not-rank 与 meta-gate 递归失去基底——此时 M9 只能输出"无担保标签"而非 Receipt。这是公理体系的前置条件，不是配置项。
2. **合规域的人审法定要求**：EU AI Act Art.14 类人审义务是法律约束而非设计选择。`authorization: full_auto` 档在受监管域**不可用**——框架不尝试把法定人审"优化掉"，profile 层强制 `human_signoff`。
3. **RQGM preliminary 状态**：selective erasure 与 ϵ-best-belief 的数字（71.7% vs 69.9%、token 省 1.35×–1.72×、接受率 1.78×–1.86×）作者自述 preliminary，长搜索视野下尺度行为未知。故 meta-gate 默认规则取 SkillCoach 硬门（证据更薄但机制更简），RQGM 形态留作可配置替代而非默认。
4. **降级为实践建议的三条**（证据过薄，不进公理/内核）：防 polish-masking（M8 消费机器可读结果表+代码，不消费论文式叙述；单系统单事件）；规格歧义是作弊温床（准入标准写作评审 checklist 项；单来源场景对照，歧义任务 44% vs 明确 0%）；作弊能力跨域迁移泛化（单一机构叙事级报告）。
5. **在线连续流量份额门（N1 连续信任份额）**：框架原生支持的是"盖章+指针+阶梯"的离散份额推进；逐请求级连续份额路由依赖部署基础设施，M9 只输出 Receipt，消费侧（canary 控制器）在框架外【推断】。

---

## 10. 实现分期（对接 ADAPT-v1.1）

| 期 | 内容 | 依赖 |
|---|---|---|
| **E9a（类型层，P0）** | EvalResult 扩展（items/public-private 分离/EvaluationCard/ReliabilityMeta）+ Verdict + Receipt 落 core/eval/types.py；`{split}.{visibility}.{name}` key 规范；**类型层增量并入 ADAPT-v1.1 Step 0** | 无，与 G1/M5a 类型层改动同批 |
| **E9b（最小可用，P1）** | Layer 2 判定规则库（flip_count + non_regression + noise_floor_zero）+ 票据失效引擎 + 证据日志接 X1；确定性 judge；openevolve_cascade / shinkaevolve_contract 两 profile | E9a；并入 Step 1 |
| **E9c（密封与统计，P2）** | sealed_audit judge（隐藏 seeds/分布）+ mSPRT/e_value_gate + isotonic calibrate + position-swap/κ 探针；seal_gate / past_bench_mechanism profile | E9b + anchor 集建立；并入 Step 2 |
| **E9d（治理与三门，P3）** | 授权结构（人授权硬门/多签）+ exposure 链（shadow→canary）+ gate_quality_probe 伴生组件 + judge 校准维护周期；moss_three_gates / mlops_registry profile | E9c；并入 Step 3 |
| **E9e（meta-gate 与谱系，随治理里程碑）** | meta-gate 递归（held-out 不回退硬门默认）+ epoch 边界级联失效 + E1 漂移归因（anchor 双 e-process）+ tenure 消融协议钩子 | E9d + X1 谱系完备；不阻塞 Step 0–3 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做评估器全自动无门共进化（meta-gate 永远在位；RQGM 留作配置非默认）
- 不做对 agent 的全透明反馈档作为默认（`full` 仅调试期显式声明）
- 不做 LLM 终裁路径（decision_rule 无 LLM 实现档，I-LLM）
- 不做在线评估集自动补给入准入门（trace-to-eval 走与 rubric 变更同类 meta-gate，E4 治理耦合）

---

## 11. 一句话规格

> **M8/M9 = 冻结的 EvalResult/Verdict/Receipt 数据模型与判定规则库（per-item 翻转 gate-not-rank、外生密封准入、CI 强制与噪声底计零、票据三绑自动失效、分数带谱系软作废硬永存、证据日志先行）+ 六个可替换算子（judge/校准器/级联策略 × 判定规则/授权结构/生效节奏，确定性/LLM/可学习三档）+ 三十八轴编译成的 profile（经典系统全部是 profile 实例）+ 级联调度与 meta-gate 递归（评估器变更先过门、通过即级联作废、递归终止于人工 anchor）+ 四条框架级不变量（锚点存在、质量指标一等化、LLM 建议确定性终裁、谱系可失效）上收 CLAUDE.md。**
