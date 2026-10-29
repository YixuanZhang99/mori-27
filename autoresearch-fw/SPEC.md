# SPEC.md — AutoResearch 框架技术规格书

> **本文档是实现的宪法。** 所有模块必须实现本文档定义的 Protocol；模块间只允许传递 §1 定义的六个数据类型；
> 任何偏离必须先在 ADR 中记录再改代码。
> 证据指针格式：`[抽象文档 §X]` = ../docs/AutoResearch模块化统一抽象.md；`[dimNN]` = ../research/dim00-08/autoresearch_modular_dimNN.md。
> 版本：v0.1（2026-08-05，M0 冻结底稿）

---

## 0. 设计原则（不可协商）

1. **超集接口，最小实现**：接口按经典系统的并集设计，一期只实现最小子集。
2. **软决策 LLM 化，硬保证机制化**：想什么/选哪个/怎么解读 → policy 自由；预算、dev/test 纪律、串行写、作用域隔离、防篡改 → 代码强制。
3. **失败是一等状态**：任何评估/执行失败不抛异常穿越主循环，而是编码进状态字段。
4. **一切可复现**：checkpoint/resume、事件总线、决策留痕是内置能力而非后补功能。
5. **复刻即验证**：框架正确性 = 用配置复刻经典系统的报告行为（见 REPLICATION.md）。

---

## 1. 六大数据类型（`core/types.py`）

模块边界上只允许出现这些类型（及语言原生类型）。禁止自定义跨模块数据结构。

```python
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

NodeRef = str        # 层级 id，如 "ROOT", "1", "1.2"
ArtifactRef = str    # git branch 或 commit sha，artifact 的唯一合法引用方式

# ---------- 候选与假设 ----------

class Candidate(BaseModel):
    """M2 算子的产出：一个待执行的候选。0/1/2 父（draft/improve/crossover）。"""
    id: NodeRef
    parents: list[NodeRef]                    # len ∈ {0,1,2}；>2 需用多分支聚合算子显式声明
    hypothesis: str | None = None             # 语义假设；纯代码搜索系统可为 None
    operator: str                             # 产生它的算子名（registry key）
    context_pack_ref: str | None = None       # 生成时所用 ContextPack 的引用（审计用）
    created_cycle: int = 0

class ExecutorSpec(BaseModel):
    """角色分工与假设分工的统一（[抽象文档 M7]，证据 [dim04]）。"""
    role: str = "general"                     # 职能轴：general/designer/coder/tuner/analyst...
    hypothesis_frozen: bool = True            # 假设轴：True=Arbor 模式（归因完整）；False=自由
    hypothesis: str | None = None
    context_projection: list[str] = Field(default_factory=lambda: ["summary"])
    # 对 ContextPack 的投影选择，如 ["summary","insights","constraints","raw_excerpt"]

# ---------- 评估 ----------

class EvalStatus(str, Enum):
    OK = "ok"
    FAILED_TO_RUN = "failed_to_run"
    TIMEOUT = "timeout"
    INVALID = "invalid"                       # 跑完但不满足 required_outputs

class CostVec(BaseModel):
    wall_seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    gpu_hours: float = 0.0

class EvalRequest(BaseModel):
    fidelity: str                             # 保真度档位名，由 EvalContract 声明
    time_limit: int | None = None
    budget_token: int | None = None
    seed_set: list[int] | None = None         # paired-seed 验收的关键
    resume_from: ArtifactRef | None = None    # 高成本评估必备：从检查点续跑

class EvalResult(BaseModel):
    """分层带宽超集（证据 [dim03][dim06][dim07]）。前四项必选，其余按带宽档位。"""
    status: EvalStatus
    metrics: dict[str, float] = Field(default_factory=dict)   # key 带 split 前缀: "dev/acc", "private/loss"
    cost: CostVec = Field(default_factory=CostVec)
    fidelity: str = "dev"
    uncertainty: float | None = None          # 种子方差等；多 seed 评估时必填
    text_feedback: str | None = None
    partial_curves_ref: str | None = None     # 训练曲线等（若评估过程可得）
    trajectory_ref: str | None = None
    artifacts_ref: str | None = None

# ---------- 证据与状态变更 ----------

class EvidenceRecord(BaseModel):
    """= EvalResult + 执行归属。M8 产出；M1/M3/M4/M9 共同消费。"""
    candidate_id: NodeRef
    eval_result: EvalResult
    branch_ref: ArtifactRef | None = None
    executor_status: str = "scored"           # scored | skipped | failed_to_run
    attempt: int = 1
    insight: str | None = None                # executor 蒸馏（M5 的写入源）
    result_text: str | None = None            # 事实性结果描述

class MutationOp(str, Enum):
    ADD_NODE = "add_node"
    UPDATE_NODE = "update_node"
    PRUNE = "prune"
    MERGE = "merge"
    WRITE_MEMORY = "write_memory"
    PROMOTE_MEMORY = "promote_memory"

class StateMutation(BaseModel):
    """M1.absorb 的唯一输出形式。fields 受目标对象的白名单校验（Arbor MUTABLE_FIELDS 模式 [dim00]）。"""
    op: MutationOp
    target: NodeRef | str
    fields: dict = Field(default_factory=dict)
    rationale: str = ""                       # 决策留痕：为什么做这个变更
```

---

## 2. 主循环（语义内核）

```python
async def main_loop(task: TaskAdapter, cfg: RunConfig):
    frontier, memory, budget = init_state(task, cfg)
    best: EvidenceRecord | None = None
    while budget.should_continue_run():
        ctx      = policy.observe(frontier.view("compact"), memory, best)          # M1
        parents  = policy.select(frontier, budget.state())                         # M1（默认委托 frontier.sample）
        for parent in parents:
            for cand in operators[cfg.operator_set].propose(parent, ctx):          # M2
                spec    = ExecutorSpec(hypothesis=cand.hypothesis, **cfg.executor_spec)
                request = budget.allocate(cand)                                    # M3 → EvalRequest（含 fidelity/seed）
                ev      = await executor_pool.run(spec, cand, task, request)       # M7 → EvidenceRecord
                for mut in policy.absorb(ev):                                      # M1 → [StateMutation]
                    state.apply(mut)                                               # 白名单校验后落 M4/M5
                decision = admission.consider(cand, ev, best)                      # M9
                if decision.admit:
                    best = ev
                    state.apply(decision.mutations)
        events.emit("cycle_end", frontier.view("json"))
    return FinalReport(best, admission.report_triple())   # (dev_best, gate_selected, final_audit)
```

**并发纪律**：executor 并行度由 evaluator 资源反压；frontier/memory 的写必须串行（R&D-Agent 用 semaphore=1 保证 DAG 写一致 [dim04]）；读可并发。

---

## 3. M1 Policy / Coordinator

**职责**：观察状态 → 生成方向 → 选择候选 → 吸收证据。软决策的唯一合法位置。

```python
class Policy(Protocol):
    async def observe(self, state_view: str, memory: Memory, best: EvidenceRecord | None) -> StrategyContext: ...
    async def ideate(self, ctx: StrategyContext, parent: NodeRef, k: int) -> list[Candidate]: ...
    async def select(self, frontier: Frontier, budget: BudgetState) -> list[NodeRef]:
        """决策入口。规则策略 = frontier.sample 的薄封装；LLM 策略自行裁决。"""
    async def absorb(self, evidence: EvidenceRecord) -> list[StateMutation]: ...
```

**一期实现**：`best_first`（AIDE 复刻用）、`llm_cycles`（六步循环：observe→ideate→select→dispatch→absorb→admit，Arbor 复刻用）。
**二期**：`mcts`、`round_robin`。

**必备子职责——policy 运行时上下文治理**（`context_prune`，易被遗漏 [dim00]）：
policy 的对话上下文按 `window / compact_threshold / keep_recent` 压缩；它与 M5 经验记忆是两条独立写路径，禁止合并。

**证据指针**：LLM 策略表达力 [抽象文档 M1]；算子升级前高级策略无差异 [dim01]，故 MCTS 置二期。

---

## 4. M2 Operator（算子库）

**职责**：从父候选产生新候选。算子与算子选择策略 π_op 解耦（AIRA 五元组教训 [dim01]）。

```python
class Operator(Protocol):
    name: str
    arity: int                                 # 0=draft, 1=improve/debug, 2=crossover
    async def propose(self, parents: list[NodeRef], ctx: StrategyContext,
                      llm: LLM, memory_view: ContextPack) -> Candidate: ...
```

**一期实现**（4+2）：
| 算子 | arity | 语义来源 | 备注 |
|---|---|---|---|
| `draft` | 0 | AIDE | 从任务描述起新解 |
| `debug` | 1 | AIDE | 修复 buggy 节点 |
| `improve` | 1 | AIDE | 改进有效节点 |
| `hypothesis_refine` | 1 | Arbor | 证据条件化：validated insight 作正约束、pruned 作负约束 |
| `comparative_reflect` | 1 | MARS | 与 current best 差分归因，产三元组 lesson（变更/影响/泛化规则） |
| `crossover` | 2 | AIRA | 二期前可 stub |

**约束**：算子内部失败不得抛异常，返回 `Candidate` 且标注 `meta.partial_failure`；LLM diff 变异必须配 `max_patch_resamples` 重试 + marker 校验（[dim06] 工程教训）。π_op 一期为规则式（按 frontier 状态路由），禁止一期做学习型 π_op（从未被证明是瓶颈 [dim01]）。

---

## 5. M3 BudgetController

**职责**：三级预算（全局/方向/候选-fidelity）+ 收敛与方向耗尽检测。

```python
class BudgetController(Protocol):
    def state(self) -> BudgetState: ...                     # 各层 used/remaining
    def should_continue_run(self) -> bool: ...
    def allocate(self, cand: Candidate) -> EvalRequest: ... # 决定 fidelity/seed/时限/resume
    def converged(self, frontier: Frontier) -> ConvergenceSignal | None: ...
```

**一期实现**：硬上限（cycles/wall_clock/gpu_hours）；规则式收敛（连续 N 次无改进 + exhausted_parents）。
**二期**：fidelity 级联（SH/Hyperband 风格 + paired-seed funnel）、成本感知 value（MARS w，默认 −0.07 [dim03]）。

**低样本 regime 强制规则**：若 `evaluations_per_run < 50`，velocity 类统计信号必须降级为规则式（[抽象文档 M3]）。

---

## 6. M4 Frontier / ResearchState

**职责**：候选集合与搜索拓扑的组织；状态多投影；sample 原语的唯一实现位置。

```python
class Frontier(Protocol):
    def add(self, cand: Candidate, evidence: EvidenceRecord | None) -> None: ...   # 路由由准入结构配置
    def sample(self, k: int, strategy: SamplingStrategy) -> list[NodeRef]: ...    # 压力控制器在此
    def get_best(self, scope: Scope | None = None) -> NodeRef | None: ...
    def prune(self, node: NodeRef, reason: str) -> None: ...                      # 级联，留痕
    def view(self, projection: Literal["json","compact","constraints","markdown"]) -> str: ...
    def checkpoint(self) -> bytes: ...
```

**框架不变量**：credit assignment 只认骨架边；引用边仅承载信息流（MCGS 教训 [dim08]）。数据结构实现为 `edges: {skeleton: [...], reference: [...]}` 两类。

**节点 schema**（以 Arbor Node 为底 [dim00]，加 uncertainty/cost/ref_edges）：
```
id, parent_ids, children_ids, depth, hypothesis, status(pending/running/done/merged/pruned),
insight(M5 L2 的物化视图), result, score, score_split(dev|admission|test), test_score,
code_ref, grounding, related_work, eval_status, attempt, cost, uncertainty
MUTABLE_FIELDS 白名单 = 上述除 id/parent_ids/children_ids 外全部
```

**三个正交旋钮**（配置项）：`structure: chain|tree|dag|map_elites|island`；`scope_descriptor: parent|parent_siblings|branch_k|global_topk|aggregate`（只声明作用域，检索走 M5）；`pressure: none|boltzmann|cluster|niche`。

**一期实现**：`tree`（含可选引用边）。`map_elites/island` 三期（M3 里程碑）。

---

## 7. M5 Memory（内生经验）

**职责**：轨迹 → 经验的转化；生命周期（L1/L2/L3）× 作用域双轴治理。结构化记忆已被多系统消融证明是增益主体，平铺记忆被证明无效（[交叉验证 C1/K1]）。

```python
class Memory(Protocol):
    async def write(self, hook: CheckpointHook, trace: TraceRef) -> None: ...
    # hook 由事件总线触发：experiment_end / phase_end / run_end
    async def promote(self, level: int, delta_op: PromoteOp) -> None: ...
    # 必须增量合并，禁止整篇重写（ACE context collapse 教训 [dim02]）
    def retrieve(self, scope: ScopeDescriptor, query: str | None,
                 budget_tokens: int) -> ContextPack: ...
```

**ContextPack**（retrieve 的唯一返回类型）：`{summary, insights[], constraints[], factual_results[], provenance[]}`，每项带 provenance（来源 NodeRef + 置信计数）。

**层级语义**：L1 工作记忆（原始，当前 run/phase）；L2 阶段蒸馏（知识单元，晋升即逐出原件）；L3 跨 run（kv_graph：`(embedding, wisdom)`，cos>δ 预取；一期 stub，M3 里程碑实现）。
**所有权**：node.insight 是 L2 的物化视图，source of truth 在 M5；写路径只能经 M1.absorb → WRITE_MEMORY/PROMOTE_MEMORY。
**一期实现**：L1 + L2（delta merge），scope=parent_siblings。

---

## 8. M6 Knowledge（外部知识）

**一期为 stub**（接口先行，M3 里程碑后实现）。接口：

```python
class Knowledge(Protocol):
    async def search(self, query: Query, lane: Literal["grounded_ideation","novelty_audit"]) -> Digest: ...
    # 两车道独立检索、互不共享抓取文本；benchmark 模式默认双关闭（Arbor 先例 [dim00]）
    def retrieve(self, scope: Scope, query: Query) -> KnowledgePack: ...
    # 返回分级包：TIER1 精确 / TIER2 相关 / TIER3 纠偏；含 query_used/source_pages；未打开的来源丢弃
    async def ingest(self, source: ArtifactRef) -> None: ...   # run 后蒸馏回写
```

---

## 9. M7 Executor（执行器）

**职责**：隔离工作区中把 Candidate 变为可评估 artifact；返回恰好一个 EvidenceRecord。

```python
class Executor(Protocol):
    async def execute(self, spec: ExecutorSpec, cand: Candidate,
                      workspace: Workspace, request: EvalRequest) -> EvidenceRecord: ...

class Workspace(Protocol):                       # 隔离后端抽象
    def fork(self, base: ArtifactRef) -> ArtifactRef: ...
    def destroy(self, ref: ArtifactRef) -> None: ...
```

**一期后端**：`git_worktree`（默认；成本最低、provenance 免费 [dim00][dim07]）。二期：`container`。
**假设绑定契约**：`hypothesis_frozen=True` 时，executor 的修复循环只许改实现不许改假设——否则返回的分数失去归因意义（Arbor 最精巧约束 [抽象文档 M7]）。
**返回纪律**：恰好 `{eval_result, branch_ref, insight, result_text, executor_status, attempt}`；执行失败 → `executor_status=failed_to_run`，不抛异常。
**并行**：ExecutorPool 配额调度；二期支持异步双池（FM Agent 模式）。

---

## 10. M8 Evaluator（评估器）

**职责**：框架与被优化领域之间的唯一契约。

```python
class Evaluator(Protocol):
    def contract(self) -> EvalContract: ...
    async def evaluate(self, artifact: ArtifactRef, request: EvalRequest) -> EvalResult: ...

class EvalContract(BaseModel):                    # DomainPlugin/zoo 适配器声明（Arbor 插件模式 [dim00]）
    metric_direction: Literal["maximize","minimize"]
    eval_cmd: str                                 # 支持 {cwd} 插值
    fidelity_levels: list[FidelityLevel]          # 名称/成本/种子数/用途(exploration|admission|audit)
    required_outputs: list[str] = []
    protected_paths: list[str] = []               # 运行时 SHA-256 校验
```

**配套机制（一期实现）**：cascade（便宜档位先跑，失败即短路）；paired-seed 评估（同 seed 集比较候选与 best）。
**二期**：multi-fidelity 晋升策略插件、uncertainty 上报规范。
**权限**：评估器实例带 `visibility` 标记（dev/admission/audit），M9 只能调用 admission 档以上实例——"评估器能看到什么"是显式配置（KAPSO 争议教训 [dim08]）。

---

## 11. M9 AdmissionGate（准入）

**职责**：裁决什么算真正的进步。一等模块，独立可配（终选模块化价值 9-13pp 上界 [dim01]）。

```python
class AdmissionGate(Protocol):
    def consider(self, cand: Candidate, ev: EvidenceRecord,
                 best: EvidenceRecord | None) -> AdmissionDecision: ...

class AdmissionDecision(BaseModel):
    admit: bool
    mutations: list[StateMutation] = []           # 通过时产生的 merge/状态变更
    reason: str = ""
```

**配置对象**（yaml）：
```yaml
admission:
  layers: [dev, admission, final_audit]   # 一期可配 [dev] 或 [dev, admission]
  trigger: { min_gain: 0.05 }             # 触发 gate 的 dev 改进阈值（限流）
  call_budget: 20                         # gate 调用硬顶（防 adaptive overfitting，双预算权属见下）
  margin: 0.0                             # 改进幅度门槛
  monotonicity: true                      # current-best ratchet
  selection: best                         # best | top_k（top-3 多提交值 +10% [dim01]）
  integrity_hooks: [hash_check, canary_scan]
```

**双预算权属**：准入评估消耗计入 M3 全局预算（"花了多少"），同时受 M9 call_budget 硬顶（"最多几次"）。
**强制报告**：每次 run 输出 `(dev_best, gate_selected, final_audit)` 三元组 [dim08]。
**红线**：准入信号必须可执行/可复算；LLM judge 最多做排序建议，永远不得单独放行（Gasteiger 教训 [dim08]）。

---

## 12. X1 Provenance & Audit（横切）

- **git 即 lineage**：artifact 只允许以 branch/commit 引用；研究树挂在 git DAG 上，不另建状态库。
- **Checkpoint**：版本化（schema_version + GitState + InflightExecutor + messages），每次 cycle 末写盘；支持 resume/replay。
- **事件总线**：`events.emit/subscribe`；日志、dashboard、记忆钩子、审计全部以 subscriber 接入。
- **防篡改**：protected_paths 运行时 SHA-256 manifest（executor 启动时 + merge 前双检查）。
- **泄漏防线**：canary 扫描、test-hash 去重（二期）；外部互操作面（MCP 类）归本层。

## 13. X2 HITL（横切）

- interaction modes：`auto | direction | review | collaborative`；一期实现 `auto` + `review`。
- 各模块配置可声明人工钩子（如 M9 human_approval），实现统一走 X2 交互通道，不得在模块接口内生长。

---

## 14. 配置与 Recipe 系统

- pydantic schema 定义全部配置；YAML 组合（defaults 组 + 覆盖链：全局 < 项目 < CLI < 会话内）。
- **recipe = 命名预设**（`recipes/*.yaml`），是框架的一等公民与验收标准（见 REPLICATION.md）。
- 每个 recipe 必须能通过 `framework run --recipe aide --task mle_bench_lite` 直接执行。

---

## 15. 测试与验收

| 层 | 内容 | 通过标准 |
|---|---|---|
| 单元 | 六类型序列化、白名单校验、frontier 路由、cascade 短路 | 100% 覆盖 types/frontier/admission |
| 契约 | mock Evaluator + mock LLM 跑全循环 | 主循环 100 cycle 无异常、状态可 resume |
| 复刻 | recipes/aide.yaml、recipes/arbor.yaml | 见 REPLICATION.md 验收区间 |
| 审计 | 随机抽 run 检查三元组报告、决策留痕、protected hash | 全通过 |
