# M5-UNIFIED-v1.md — 统一记忆子系统设计文档

> 依据：`../docs/M5记忆设计空间深度展开_A-I轴_分歧点_失效模式.md`（A–I 轴 × 五分歧 × F1–F8 失效模式逐格深挖，2026-08-26）。
> 定位：M5 模块的最终形态设计。回答一个问题——**ACE / MemRL / DGM / IBM TSM / prime-agent / Dreaming 系这些经典设计能否被同一个实现兼容？答案：能。它们之间的差异全部是配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 固定的条目模型与生命周期状态机（内核，不可换）+ 五个可替换算子（插件）+ 九轴编译成的 profile（配置）+ 双速调度（运行时）**。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

| # | 公理 | 依据 |
|---|---|---|
| A1 | **provenance 与 time 是强制字段**，任何条目必须携带来源与时间的一等建模 | F4（异常污染）伪装成 F7（陈旧复用）、F6（虚假信念自我强化）的共同根因 = 条目无 ttl/scope/confidence/provenance |
| A2 | **正常衰退路径只有降级归档，没有删除**；delete 仅对卫生事件（投毒确认/合规）开放且必须写证据日志 | 分歧 4 裁决：研究场景阴性结果与被反驳假设是高价值记忆；MemRL "FAILED EXPERIENCES" 块有变分最优性证明；FIFO 内容无关会误删高价值旧记忆 |
| A3 | **确定性信号做最终裁决，LLM 只做建议**（度量与裁决解耦） | arXiv:2607.07436：评审器有偏使退休机制静默失效（装着在跑、实际空转）；AI-Scientist 新颖性闸门误杀 9/10 人类已接收论文 |
| A4 | **sync 关键路径禁止 LLM 算子**，只允许廉价标量更新 | MemDelta（2606.29914）：记忆操作可占执行时间 >80%，500 会话抽取耗 1.6 亿 token |
| A5 | **append-only 证据日志是内核，不是插件**；先于一切治理阈值存在 | 轴 F 反直觉结论：贡献分的真正消费者是评估；归因数据丢了补不回，退休阈值可后调 |
| A6 | **两阶段读取（召回 + 效用重排）不可关闭** | 分歧 4 技术前提：降级 + 无权重读取 = 没降级；IBM TSM：检索不足比不检索更糟（−2.9pp） |
| A7 | **无治理不是默认值，是需要显式声明的例外** | SkillsBench（2602.12670）：LLM 自创技能 +0.0pp vs 人工策划 +16.2pp；Library Drift（2605.19576）：无界积累→检索退化、静默崩溃 |
| A8 | **M5 声明象限：about=工作 × for=性能**；对话满意度类信号显式排除出效用函数 | 轴 I：象限声明决定 utility 定义，utility 决定贡献分/慢循环奖励/巩固触发各自优化什么 |

---

## 1. 四层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 4  调度器（轴H/分歧3：双速，sync 禁 LLM）                │
├─────────────────────────────────────────────────────────────┤
│ Layer 3  算子接口（encode/admit/retrieve/consolidate/retire） │
│          每算子三类实现：确定性 | LLM | 可学习（轴G挂点）        │
├─────────────────────────────────────────────────────────────┤
│ Layer 2  生命周期状态机 + append-only 证据日志（内核，冻结）     │
├─────────────────────────────────────────────────────────────┤
│ Layer 1  MemoryEntry 条目模型（内核，冻结）                    │
└─────────────────────────────────────────────────────────────┘
         ↑ 以上两层标注 evolvability: kernel_fixed
         ↑ Layer 3 标注 evolvability: operators_only
         ↑ 经典系统 = profile = Layer 3 算子选择 + Layer 4 配置
```

---

## 2. Layer 1：MemoryEntry 条目模型（冻结）

```python
# core/memory/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any
import time

# ---- 轴A：payload 是类型化 union，消化分歧1 ----
# 基因型（DGM）不是另一种记忆系统，而是 payload=ExecutableRef 的条目
PayloadKind = Literal["text", "structured", "executable", "genotype_ref"]

@dataclass
class Payload:
    kind: PayloadKind
    body: Any                      # text: str; structured: dict(按schema); 
                                   # executable: 可执行引用(脚本/断言/检查器);
                                   # genotype_ref: 指向 Candidate/代码制品的引用
    schema_id: Optional[str] = None  # structured 必填（如 "ibm_tsm_tip_v13"）

# ---- 轴E：作用域（分歧2的权限阶梯）----
Scope = Literal["run", "task", "domain", "global"]

# ---- 生命周期状态（Layer 2 状态机的状态集）----
LifecycleState = Literal[
    "candidate",   # 已写入未准入
    "active",      # 在活跃库，可被检索
    "demoted",     # 效用低于阈值/被取代，降权但可读
    "archived",    # 归档层：带 provenance 与退役理由，仅显式查询可达
    "deleted",     # 仅卫生事件；物理删除前必须已写证据日志
]

@dataclass
class UtilitySignals:
    """多信号并存：不同 profile 用不同信号，字段可空"""
    q_value: Optional[float] = None          # MemRL 式 Q←Q+α(r−Q)
    helpful_count: int = 0                   # ACE 式
    harmful_count: int = 0                   # ACE 式（负面课程的载体）
    contribution: Optional[float] = None     # per-entry 贡献分（通路归因）
    hit_count: int = 0                       # hit-count 巩固触发的输入

@dataclass
class Provenance:                            # 公理A1：强制
    source_run_id: str
    source_branch: Optional[str]
    evidence_refs: list[str] = field(default_factory=list)  # 指向 EvidenceRecord
    trust_tier: Literal["verified", "gated", "ungated", "human"] = "ungated"

@dataclass
class TimeMeta:                              # 公理A1：强制
    created_at: float = field(default_factory=time.time)
    last_hit_at: Optional[float] = None
    ttl: Optional[float] = None              # None = 不过期；过期走降级不删除
    superseded_by: Optional[str] = None      # F7 的一等公民：废止语义

@dataclass
class MemoryEntry:
    id: str
    payload: Payload
    scope: Scope = "task"                    # 默认 task；升 global 需前置清单（§7.2）
    level: Literal["L1", "L2", "L3"] = "L2"  # 对接 G1 候选层级
    state: LifecycleState = "candidate"
    utility: UtilitySignals = field(default_factory=UtilitySignals)
    provenance: Provenance = None            # 强制，无默认
    time: TimeMeta = field(default_factory=TimeMeta)
```

**设计决定说明**：
- `Payload.kind` 四个取值即轴 A 表示轴的全部取值（raw trace 归入 text + provenance 指向原始轨迹；结构化 schema 用 `schema_id` 注册管理，IBM TSM 13-field 即一个 schema 实例）
- `UtilitySignals` 允许多信号并存而非选一个：分歧 4 要求降级操作有信号可用，而不同 profile 用不同信号；成本递增顺序 helpful/harmful < q_value < contribution
- `state` 字段是状态机的物化——任何迁移必须经 Layer 2 的迁移函数，禁止直接赋值

---

## 3. Layer 2：生命周期状态机 + 证据日志（冻结，不可学习、不可绕过）

### 3.1 状态机

```
                    ┌─────────────┐
   observe ──► [WRITE_GATE] ──► candidate ──► [ADMIT] ──► active
                                                             │
              效用低于阈值 / 被supersede / TTL过期             ▼
                                                           demoted ──► archived
                                                             │              │
                                                             └── 重新激活 ──┘ (效用回升/显式恢复)
   任何状态 ──► [卫生事件: 投毒确认/合规] ──► deleted（先写证据日志，后物理删除）
```

| 迁移边 | 裁决器（挂点） | 默认实现 | 经典对应 |
|---|---|---|---|
| WRITE_GATE | `admit_precheck` | 无门（全部进 candidate） | Reflexion=无门；prime-agent=evidence gate；宽进严读=只标 trust_tier 不拦截 |
| ADMIT | `admit` 算子 | 确定性校验（schema 合法 + provenance 完整） | IBM TSM=LLM 冲突合并（成功>失败、recovery>预防） |
| active→demoted | `retire` 算子 | 确定性阈值（q_value/贡献分 + last_hit 时间） | Ratchet 配方 |
| demoted→archived | 定时/容量触发 | 活跃库有界上限溢出时按效用序降级 | Ratchet 有界上限 |
| →deleted | 人工/卫生审计 | 人工确认 | MINJA 投毒响应 |
| 任何迁移 | — | **全部写证据日志** | append-only 证据日志 |

**硬编码不变量**（写进 CLAUDE.md）：
1. 状态迁移只能由 Layer 2 迁移函数执行，且每个迁移产生一条证据日志记录
2. `deleted` 的唯一入口是卫生事件
3. 算子（Layer 3）可以**提议**迁移，不能**执行**迁移——公理 A3 的物化：LLM 建议、状态机执行

### 3.2 证据日志（Evidence Log）

```python
@dataclass
class EvidenceRecord:
    seq: int                     # 单调递增，append-only
    ts: float
    entry_id: str
    transition: str              # "candidate->active" 等
    actor: str                   # 算子id / "scheduler" / "human"
    rationale_ref: Optional[str] # LLM 建议的原文引用（如有）
    signals_snapshot: dict       # 迁移时刻的 UtilitySignals 快照
    run_context: dict            # run_id / branch / task
```

- **先建日志，后调阈值**（公理 A5）：所有迁移从第一天就记录，即使 retire 算子最初是 no-op
- 与 X1 溯源层复用同一存储，不另起炉灶
- PAST-Bench 通路归因、MemRL credit assignment 缺陷（多记忆共注时含糊）、反事实轨迹审计（2605.11946）都以此日志为原始数据

---

## 4. Layer 3：五个算子接口（插件层）

```python
# core/memory/operators.py
from typing import Protocol

class MemoryOperators(Protocol):
    def encode(self, obs: Observation, ctx: Context) -> MemoryEntry:
        """轴A实例化：从观察构造条目。写算子是轴G'记忆写算子'取值的挂点（MemSkill位置）"""

    def admit(self, entry: MemoryEntry, store: Store) -> TransitionProposal:
        """轴B/D：准入 + 冲突合并 + 去重。返回提议，不执行（Layer 2执行）"""

    def retrieve(self, query: Query, store: Store, k: int) -> list[MemoryEntry]:
        """轴C：两阶段 = 召回 + 效用重排。公理A6：不可关闭重排"""

    def consolidate(self, store: Store, budget: Budget) -> list[TransitionProposal]:
        """轴D/H：摘要/蒸馏/解矛盾/supersession。重型操作，禁sync"""

    def retire(self, store: Store) -> list[TransitionProposal]:
        """轴F：降级归档裁决。LLM实现只产出建议+理由，阈值裁决用确定性信号"""
```

### 4.1 每个算子的三类实现与轴 G 的映射

| 实现类 | 特征 | 何时用 | 例子 |
|---|---|---|---|
| **确定性** | 无 LLM、可复现、可单测 | **默认与最终裁决** | EMA Q 更新（α=0.3）、时间戳比较、阈值、schema 校验 |
| **LLM** | 灵活但不可复现、可被讨好 | 建议生成、冲突合并草稿、蒸馏 | IBM TSM 冲突合并、Dreaming 摘要 |
| **可学习** | RL 训练的策略 | 有可靠训练信号时 | CODESKILL 管理策略（+4.01 over 最强记忆基线）、MemSkill controller |

**轴 G 元层递进 = 允许慢循环替换哪个算子的实现**：

| 慢循环对象 | 框架含义 | 默认开放？ |
|---|---|---|
| 任务技能 | 不动 M5，走 M2/Candidate L3 | ✅ 本就是框架主循环 |
| 记忆写算子 | 换 `encode`/`admit` 实现（MemSkill 双库解耦+快照回退模式） | ✅ 开放 |
| 巩固策略 | 换 `consolidate` 实现（CODESKILL 位置） | ✅ 开放 |
| 评审 rubric | 换 admit/retire 的评审器 | ⚠️ 需配评审器审计（rubric 自进化 = 裁判改规则，偏置自固化风险） |
| 记忆架构 | 换 profile（MemEvolve 教训：无唯一最优架构，按任务搜索） | ⚠️ 设计期实验，非在线进化 |

**跨层稳定化要求**：任何慢循环替换算子实现时，必须保留 MemSkill 式"快照回退"——旧实现快照可恢复，新实现经 StateMutation + X1 记录。

### 4.2 retrieve 的固定骨架（公理 A6）

```python
def retrieve(self, query, store, k):
    # 阶段1：召回（可配置：语义相似度 / 结构位置 / 全量小库）
    candidates = self.recall(query, store, k_recall=3*k)
    # 阶段2：效用重排（不可关闭；权重公式可配置）
    ranked = self.rerank(candidates, utility_weight=self.cfg.utility_weight)
    # 阶段3：状态与可见性过滤（不可关闭）
    return [e for e in ranked
            if e.state in ("active", "demoted")        # archived 仅显式查询
            and e.time.superseded_by is None           # F7：被废止条目不注入
            and within_scope(e, query.scope)           # X3 可见性
            and passes_trust(e, query.trust_floor)][:k]
```

- 效用重排信号与权重：λ 类参数（MemRL 报告 λ=0.5 最优），暴露为配置
- IBM 教训内建为护栏：top-k 过严（如 top-3）会 −2.9pp 劣于基线 → `k` 与 `k_recall` 是 profile 级超参，框架报 warning 当 k < 5 且库 > 100 条
- 负面课程注入：MemRL "FAILED EXPERIENCES (Avoid these mistakes)" 块 / ACE harmful 计数 / Perplexity "避免此路" 在此统一为 `include_negative: bool = True`

---

## 5. Layer 4：双速调度器（轴 H / 分歧 3 的裁决落地）

```yaml
# memory/schedule.yaml
schedules:
  sync:                      # 关键路径，episode 末
    - op: utility_ema        # Q←Q+α(r−Q)，确定性，α=0.3
      constraint: no_llm     # 公理A4：硬约束，LLM算子注册到sync直接报错
  idle:                      # 默认档：空闲窗
    - op: consolidate_llm    # 摘要/冲突合并/supersession
    - op: retire_sweep       # 降级扫描
  hit_count:                 # 可选（DeltaMem 模式）
    - op: distill_chain
      trigger: {hit_count_gte: 5}   # K_cons，暴露为超参
  scheduled:                 # 可选（Dreaming 模式）：定时全库视角维护
    - op: global_synthesis   # 解矛盾、"计划中→已完成"类时序更新
      cron: "0 3 * * *"
```

**裁决变量（分歧 3 结论）= 景观变化率 × 巩固成本，不是任务长度**：
- sync 槽：零时滞，只放标量更新（MemRL FR=0.041 证明足够）
- idle/scheduled 槽：重型 LLM 巩固异步化（OpenAI 成本降 5 倍的教训：批处理化是成本结构问题）
- hit_count 槽：按"被证明有用"触发，前置条件是检索侧埋点（`UtilitySignals.hit_count` 已在条目模型中）
- 周期摘要产物**必须带 schema 与版本**（ShinkaEvolve 教训：自由文本摘要难冲突检测/回滚，且景观快变时持续推荐过时策略）

---

## 6. Profile 机制：经典系统 = 配置 + 算子组合

### 6.1 Profile schema

```yaml
# memory/profiles/<name>.yaml
profile:
  name: memrl_like
  description: "可靠reward + 任务同构高场景（跨任务干扰−0.004时才允许global）"
  preconditions:                # 分歧裁决规则的前置条件声明（§7.1）
    reward_reliable: true
    task_homogeneity: high
  payload: {kind: structured, schema_id: memrl_zqe}
  scope: task                   # 升global需满足前置清单
  operators:
    encode: deterministic_zqe
    admit: no_llm_gate          # 只校验schema+provenance
    retrieve: two_stage         # λ=0.5
    consolidate: null           # 全靠sync EMA
    retire: q_threshold_demote  # Q压低→降级，不删除
  schedules: [sync]
  utility: {primary: q_value, ema_alpha: 0.3}
  guardrails:
    include_negative: true      # FAILED EXPERIENCES块
    max_active_entries: 500     # 有界上限（轴F）
```

### 6.2 六个经典 profile（兼容性验证）

| Profile | payload | admit | retrieve | consolidate | retire | schedule | 备注 |
|---|---|---|---|---|---|---|---|
| **ace** | structured bullet | deterministic delta-merge（非LLM） | two_stage（helpful−harmful） | idle 去重剪枝 | dedup_demote | sync+idle | 防塌缩：max_active 硬上限（ACE 塌缩 18282→122 token 的教训） |
| **memrl** | structured (z,e,Q) | no_llm_gate | two_stage（Q 重排，λ=0.5） | null | q_demote | sync | scope=global 需同构前置 |
| **dgm** | genotype_ref（整agent代码） | selection_pressure（无显式门） | parent_selection 策略 | null | 无（选择压力替代） | sync | 状态机退化：永远 active；已知代价=同类bug跨分支反复犯 |
| **ibm_tsm** | structured 13-field | llm_conflict_merge（成功>失败、recovery>预防） | llm_guided_select（+7.2pp SGC） | scheduled 离线三段管线 | manual_review | scheduled | 写双份：domain_specific + generic（仅 generic 可跨任务） |
| **prime_agent** | executable（L3检查器/断言） | evidence_gate + 快照回滚 | two_stage | sync /refine | manual | sync | executable payload 是分歧1的折中解 |
| **dreaming** | text playbook | human_approve（trust_tier=human） | two_stage | idle/scheduled 全库synthesis | human_review | idle+scheduled | 人审档位，高风险域用 |
| **no_governance**（例外，非默认） | text | none | similarity_only ⚠️ | null | **noop** | sync | 公理A7：必须显式声明，仅作对照基线/极短生命周期 |

**兼容性结论**：七个 profile 覆盖了调研中全部经典系统的设计空间，没有一处需要改内核。它们之间的差异 = payload kind + 算子选择 + 调度档 + 效用信号选择，全部在配置层。

---

## 7. 分歧裁决规则的编译落地

### 7.1 五个分歧 → 选择器输入

| 分歧 | 裁决规则（深挖文档） | 编译为 |
|---|---|---|
| 1 基因型 vs 文本 | 评测可自动验证且粒度=整程序 → 基因型；稀疏/不可验证 → 文本 | `preconditions.auto_verifiable` → payload kind 选择；不做二选一，L3 条目可选 executable 化 |
| 2 私有 vs 共享 | 同构高+reward可靠 → global（干扰−0.004）；有不可信写入源 → 必须加门或退私有 | scope 阶梯 + §7.2 升级前置清单 |
| 3 周期 vs 即时 | 裁决变量=景观变化率×成本 | 双速调度（§5），不是二选一 |
| 4 删除 vs 降级 | 研究场景 → 降级赢 | 公理 A2 硬编码进状态机 |
| 5 短期 vs 长期 | 单点结论不可外推 | 不在代码，在协议（§8 评测钩子） |

### 7.2 scope 升级前置清单（共享是权限提升，不是默认态）

`scope: task → domain/global` 升级时框架强制检查：
- [ ] 来源校验在位（trust_tier ≠ ungated，或有门）
- [ ] 效用后门在位（降级路径可撤销已共享条目）
- [ ] 回滚快照在位
- [ ] （global）跨任务同构证据 或 人工确认

依据：MemRL App. G.4 自承投毒扩散风险；MINJA >95% query-only 投毒成功率（F2）。

---

## 8. 与九模块的接口 & 评测协议（分歧 5 落地）

| 接口 | 内容 |
|---|---|
| **M5 → X1** | 证据日志复用 X1 存储；所有状态迁移带 run/branch 上下文 |
| **M5 → M1/M2** | retrieve 出口强制执行 X3 可见性过滤（private 指标永不进 Executor 可见上下文） |
| **M5 → M3** | 每个 schedule 槽注册预算消耗；sync 槽上报 token 预算占用率，>20% 触发 warning（MemDelta >80% 教训的安全边际） |
| **M5 → M8/M9** | **tenure 评测协议**：任何 profile 对比消融必须在 ≥3 个 tenure 点重复，报告排名稳定性；排名反转作为一等发现报告，不得取平均掩盖；卫生指标（漂移/污染率）按 tenure 画曲线——漂移早期信号在斜率不在终值 |
| **M5 evolvability 标注** | `kernel_fixed`（Layer 1/2）+ `operators_only`（Layer 3）——对接 G3 |

**配套 M9 机制分检查项**（对接 PAST-Bench 通路归因）：
- 消融组：no_memory / no_rerank（关效用重排）/ no_retire / no_consolidate / flat_scope（全 global）
- FamilyEvolveScore 的 MechanismConfidence 部分直接消费证据日志

---

## 9. 实现分期（对接 ADAPT-v1.1）

| 期 | 内容 | 依赖 |
|---|---|---|
| **M5a（类型层，P0）** | MemoryEntry + LifecycleState + EvidenceRecord 落 core/memory/types.py；状态机迁移函数 + 日志写入；全部字段有默认值 | 无，可与 G1 类型层改动同批 |
| **M5b（最小可用，P1）** | 确定性算子实现全套 + two_stage retrieve + sync 调度 + ace/memrl 两个 profile | M5a |
| **M5c（LLM 算子，P2）** | llm_conflict_merge（IBM schema）+ idle consolidate + dreaming profile（无人审档） | M5b + Arbor 测试完成后 |
| **M5d（可学习算子，M3.5 实践层）** | CODESKILL/MemSkill 式可学习 consolidate；rubric 可换 + 评审器审计 | 有可靠 RL 信号后，**不阻塞现有里程碑** |
| **M5e（tenure 评测协议，随 M8 里程碑）** | ≥3 tenure 点消融 + 排名稳定性报告 | M8 改造 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做在线记忆架构自进化（MemEvolve 留作设计期实验）
- 不做跨模型共享运行时（MemRL 3.5× 迁移是离线合并结论）
- 不做用户象限记忆（about=用户 全部取值，轴 I 已声明不涉及）
- 不把 RL 训练算子放进默认 profile（可学习实现永远是显式 opt-in）

---

## 10. 一句话规格

> **M5 = 冻结的条目模型与生命周期状态机（强制 provenance/time、降级不删除、确定性终裁、证据日志先行）+ 五个可替换算子（确定性/LLM/可学习三档实现）+ 九轴编译成的 profile（经典系统全部是 profile 实例）+ 双速调度（sync 禁 LLM）+ tenure 评测协议（单点结论不可外推）。**
