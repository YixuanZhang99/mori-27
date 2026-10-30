# 统一抽象逐项对照与分阶段验收清单

开发基准为 [AutoResearch 模块化统一抽象](AutoResearch模块化统一抽象.md)，尤其 §3 的数据类型闭包、§4 的接口契约、§6 的配置组装、§7 的约束和 §8 的路线图。原文中的论文数字、系统效果和示例参数属于设计依据，不因本仓库测试通过而成为本仓库的实测结果。

本次盘点冻结于 `b45654fe22a2db87f64e12f0142ba39bbd603216`（v59）。表中源码位置与状态描述该基线；后续实施必须保留此盘点，在“阶段执行记录”追加实际实现、测试和提交证据。不得用新增目录、类型定义、单模块测试或历史 CI 成功替代主循环接入证据。

## 状态、阶段与完成规则

状态只使用以下四种：

- **已接通**：基线主路径已实际调用该能力；仅表示表内精确子条款，不扩展为整个模块完成。
- **组件已有未接通**：相关组件存在，但通用运行路径、配置组装或反馈闭环尚未接通。
- **待实现**：完整接口或所列行为尚无可核实实现。
- **后置**：原文明确允许后置，或属于本轮五阶段以外的研究/外部集成能力；必须保持可见，不能计入完成项。

阶段编号及提交门槛：

| 阶段 | 最低交付 | 阶段端到端验收重点 |
| --- | --- | --- |
| S0 | 本清单、设计冲突决议、冻结基线 | 每个条款都有实现证据或明确缺口，不把“有组件”写成“已接通” |
| S1 模块组装 | 明确模块协议、注册/注入、Provider × DomainPlugin × Modules × Skills 配置入口 | 仅替换配置/注册对象即可改变策略与算子，真实走同一公开运行入口；未知组件、冲突配置在执行前失败 |
| S2 统一评估契约 | 一个规范的 EvalRequest/EvalResult/EvidenceRecord 通道及显式旧接口适配 | 连续指标、逐项判定、失败、成本、fidelity、来源和恢复往返均不丢字段；不伪造缺失成本 |
| S3 记忆与知识回流 | 有作用域、有预算、有来源的 ContextPack 进入 policy/operator；M5/M6 独立存储与双车道 | 第一轮经验/已打开知识确实改变后续候选输入；跨作用域、未打开来源、audit 内容泄漏被拒绝；benchmark 模式关闭知识 |
| S4 三层准入 | dev/admission/final_audit 独立配置、调用硬顶、三元组报告、可复算准入 | dev 改进但 admission 退化不晋升；final_audit 不回流搜索；调用上限、数据身份、恢复幂等成立 |
| S5 分层预算 | 全局/方向/候选预算、物理成本、fidelity/种子/时限分配、收敛与方向耗尽 | 多层预留和结算一致；任一硬顶在调用前阻断；失败和重试计量不丢失；低样本停止规则可复算 |

每个阶段必须先通过 Mac `make check`，再将阶段候选提交推到验证分支，以**同一提交 SHA**通过 Linux 全量自动验收后更新 `mori-27/main`。记录测试名称、执行结果、CI URL、提交 SHA 及尚未覆盖的条款。阶段间保留旧功能回归；历史 verifier 源码和历史失败记录不得改写。真实 provider、benchmark、10h 评估和断电恢复需要各自实测证据，不由离线 fixture 推定。

## 逐项契约对照

“原文”列的行号来自本基线设计文档；“源码”列均相对仓库根目录。验收条件是后续工作的完成标准，并非已经运行通过的声明。

### 总体闭包与配置三轴

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| A-01 | §3.1 L47–55 | `m0/core/executor/types.py` 有 Candidate/EvidenceRecord；`m0/core/loop.py:158` 把 M0 小结果转为规范证据，尚非单一通道 | 组件已有未接通 | S1→S2 | 同一候选身份贯穿生成、执行、评估、吸收、准入、检查点；不靠平行的同名结果类维持两个事实源 |
| A-02 | §3.1 L57 | `m0/core/state.py:34` 白名单写入、`budget/ledger.py`、`eval/gate.py` 有机制约束；policy 仍固定规则 | 已接通 | S1→S5 持续保持 | 恶意/错误 policy 输出不能绕过预算、作用域、评估权限、串行写和准入；换 policy 不改变硬保证 |
| A-03 | §3.2 L74–75；§6.1 L371 | `m0/core/llm.py` 有 provider；`tasks/adapter.py` 有任务适配；`profiles.py:12` 只组装少量 operator/archive/extensions，没有完整三轴入口 | 组件已有未接通 | S1→S2 | 固定 domain/skill 换 provider、固定 provider 换 domain/skill 均走公开入口；未知注册名/不兼容协议在模型调用前拒绝 |
| A-04 | §4/M6 L250；§6.2 L388–463 | profile 只有少数 M0 配置；研究模式与 benchmark 模式没有完整 DomainPlugin 组装 | 待实现 | S1→S4 | 同一运行时能按配置组装至少两种任务；benchmark 模式不得初始化或调用外部知识，研究模式显式开启并记录配置身份 |

### M1 Policy / Coordinator 与 M2 Operator

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M1-01 | §4/M1 L89–95、L110 | `m0/core/policy/absorb.py:12` 仅有 select/absorb；`loop.py:315` 固定 BestFirstPolicy，缺 observe/ideate 和统一 registry | 组件已有未接通 | S1 | spy policy 的 observe/ideate/select/absorb 按契约被实际调用；替换策略无需编辑 loop；选择结果必须来自允许的 Frontier |
| M1-02 | §4/M1 L93–94、L104–112 | `frontier/research.py:206` 有采样；`policy/absorb.py:19` 委托 greedy；没有 LLM cycles 实现 | 组件已有未接通 | S1 | 规则策略能委托 sample，注入的软决策策略可提出不同选择；机制层校验非法节点及未经授权的状态变化 |
| M1-03 | §4/M1 L98 | checkpoint 保存 messages，但没有独立 coordinator 对话窗口/compact/keep_recent 管理 | 待实现 | S1 | 超过配置窗口时裁剪/压缩工作上下文；M5 持久经验不被删改；恢复后工作上下文策略保持一致 |
| M1-04 | §4/M1 L95；§7.1 L474 | `state.py:34` StateApplier、`policy/types.py` StateMutation、`loop.py:639` absorb 写入已接通 | 已接通 | S1→S5 持续保持 | 允许 mutation 留下原因和来源；未知操作/越权字段拒绝；检查点后的重放不追加重复写入 |
| M2-01 | §4/M2 L116–122 | `operator/ops.py` 有 draft/reflective/diff 等函数，`executor/types.py:17` 支持至多两个父节点；loop 固定 draft/improve 且未传 ContextPack | 组件已有未接通 | S1→S3 | 0/1/2 父节点算子使用同一调用契约；上下文、预算和父节点身份实际到达算子；多父 lineage 不丢失 |
| M2-02 | §4/M2 L116、L139 | `profiles.py:20` 仅允许两种 improve 实现；选择策略与算子集合尚未独立注册 | 待实现 | S1 | 同一算子集合可换选择策略；同一策略可增删算子；非法选择和未知算子在执行前失败 |
| M2-03 | §4/M2 L129–139；§7.2 L483 | 已有 draft、反思 improve、diff/crossover 相关组件与测试；完整六算子及 comparative-reflect 的研究闭环未完成 | 组件已有未接通 | S1→S3 | 注册的算子走同一执行链；差分反思能读取候选/前基准的受限证据并形成有来源的经验；不声称已复刻论文效果 |
| M2-04 | §4/M2 L137；§7.1 L473 | `executor/types.py:42` 分类失败，`executor/m0.py` 与恢复测试保存失败和成本 | 已接通 | S2→S5 持续保持 | 单候选执行失败成为类型化证据；已发生费用仍结算；其他可运行候选继续；完整性错误仍失败关闭 |

### M3 BudgetController

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M3-01 | §4/M3 L143–151 | `budget/ledger.py` 有真实预留/结算，`loop.py:305` 固定账本；没有完整 allocate/should_continue/converged 控制器 | 组件已有未接通 | S5 | 每次 dispatch 由控制器分配 EvalRequest；全局、方向、候选三层限额同时成立，任何层耗尽均在调用前阻断 |
| M3-02 | §4/M3 L143、L158；§6.2 L425–428、L451 | `executor/types.py:50` CostVec、`budget/currency.py:21` 多币种账本存在；M0 主路径仍按 token 结算 | 组件已有未接通 | S2→S5 | time/token/GPU·h 等分别限额和计量，禁止直接混加；并发预留原子、失败计费、超额及恢复结算覆盖所有配置单位 |
| M3-03 | §4/M3 L150、L160；§6.2 L434–441 | `eval/cascade.py:12` 有 shallow/full 包装器；主路径固定 `EvalRequest("dev")`，未由层级控制器驱动 | 组件已有未接通 | S5 | 配置的 fidelity/seed/time_limit/resume_from 真实传到评估器；晋升、停止和续跑均有证据；低 fidelity 结果不能冒充终审 |
| M3-04 | §4/M3 L151、L166–168；§7.2 L481 | `budget/probe.py` 报告健康情况；主循环主要按轮数/余额退出，未形成方向耗尽和低样本收敛控制 | 待实现 | S5 | 连续无改进阈值与方向耗尽可复算，阈值前继续、到阈值停止；不同方向互不误停；不把规则信号称为统计显著性 |
| M3-05 | §4/M3 L162；§7.2 L484 | 算子输入未统一包含层级预算状态 | 待实现 | S3→S5 | proposer 收到本次调用前真实 used/remaining 与允许 fidelity；不能由模型提供的预算文字决定硬限额 |
| M3-06 | §4/M3 L164；§6.2 L442–444 | 级联已有，周期 anchor、proxy-true 秩相关与负反馈回流未贯通 | 待实现 | S5 | 配置周期触发真实 anchor；异质代理偏离触发告警/降级并写入 M5；样本不足明确报告，不套用同指标阈值 |

### M4 Frontier / ResearchState

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M4-01 | §4/M4 L176–182、L191–197 | `frontier/research.py:80` 实现 add/sample/get_best/prune/view/checkpoint，主循环和 StateApplier 已使用 | 已接通 | S1→S2 持续保持 | 可配置 Frontier 实现通过同一协议；类型化证据、身份、成本、状态与分层分数完整恢复 |
| M4-02 | §4/M4 L183、L187、L200–202 | ResearchFrontier 有 skeleton/reference，另有 island、MAP-Elites 和互操作；`loop.py` 仍按 archive 类别分支 | 组件已有未接通 | S1 | 至少树与种群实例可通过配置替换；引用边只影响上下文，不污染骨架 credit/深度；配置往返和恢复保留拓扑 |
| M4-03 | §4/M4 L188 | 作用域检索在 M5 组件中存在，但 Frontier 描述符→M5→Executor 投影路径未贯通 | 组件已有未接通 | S3 | 父、兄弟、祖先、允许的引用节点按描述符检索；执行器只能投影已有 ContextPack，不能另起无权限检索入口 |
| M4-04 | §4/M4 L189 | `frontier/research.py:206` 有 greedy/round-robin 类采样，island/MAP-Elites 有各自选择；缺统一压力配置入口 | 组件已有未接通 | S1 | 采样策略配置确实改变父节点序列，同时不绕过准入资格；相同种子/配置可复现 |

### M5 Memory 与 M6 Knowledge

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M5-01 | §4/M5 L210、L213–214、L222、L226 | `policy/absorb.py:36` L1 写入/L2 增量晋升，`memory/store.py:128` 增量逻辑，loop checkpoint 已保存 memory | 已接通 | S3 持续保持 | 节点扩展/阶段边界/结束触发明确写入；晋升追加 delta 不覆盖旧经验；Frontier insight 能追溯 M5 来源 |
| M5-02 | §4/M5 L211、L215、L220 | `memory/store.py:199` 有 scope 检索；`loop.py:1619` 算子只用父 prompt/feedback/score，没有 retrieve 调用 | 组件已有未接通 | S3 | 第一次失败产生经验，后续生成输入确实包含可用经验；无关 run/task/branch 被过滤；ContextPack 有明确长度/预算上限 |
| M5-03 | §4/M5 L223–224 | `memory/types.py` 来源、效用、时间/作用域，store 有 invalidation/expiry/utility 更新；完整来源链未覆盖全部 M0 适配转换 | 组件已有未接通 | S2→S3 | 检索条目带源证据引用与状态；过期、失效、未准入或负面项按显式规则处理；伪造来源无法进入候选输入 |
| M5-04 | §4/M5 L210、L226；§6.2 L458–460；§8 L509 | store 支持层级/作用域晋升及 checkpoint；没有完整跨 run 持久后端与假设索引组装 | 组件已有未接通 | S3 | 关闭首个 Framework 后，新 run 仅能检索显式授权晋升的共享经验；原 run 私有记忆不泄漏；保留 provenance 与晋升依据 |
| M6-01 | §4/M6 L234–238、L245、L250 | `knowledge/service.py:21` 双 backend/namespace、`:70` 过滤未打开来源、query/audit 已实现，Framework 未注入调用 | 组件已有未接通 | S3 | ground 与 audit 独立访问和缓存；只把实际打开的 ground 来源送入 ideation；audit 文本不能混入生成上下文 |
| M6-02 | §4/M6 L236–238、L247 | `knowledge/types.py` 有 digest/source/ref；与 M5 的统一 ContextPack、分级 retrieve 和 run 后 ingest 未贯通 | 组件已有未接通 | S3 | 知识包保留 query_used/source_pages/tier；无法支持的 tier/workflow 明确标记；ingest 写入独立知识存储并可复查 |
| M6-03 | §4/M6 L250 | `ci/check_axioms.py` D10 当前靠禁止 loop/profiles 导入 knowledge 隔离；未提供 DomainPlugin 模式开关 | 待实现 | S1→S3 | benchmark 运行时禁止知识调用及注入，research 显式开启；仅改变模式配置能证明两者行为差异；不以删除 D10 达成“接入” |

### M7 Executor 与 M8 Evaluator

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M7-01 | §4/M7 L258–265、L272 | `executor/types.py:33` ExecutorSpec，`executor/service.py` GitWorktreeExecutor 支持固定假设；M0 适配主路径另行编排 | 组件已有未接通 | S1→S2 | 通过配置选择实际 executor；role/hypothesis/context projection 传入；执行器中途改冻结假设会拒绝且记录失败 |
| M7-02 | §4/M7 L268、L272 | workspace、sandbox、resource、seccomp、durable process recovery 已有真实 Linux 测试；M0 prompt 路径是非 Git 工作目录 | 组件已有未接通 | S1→S2 | worktree/external 执行配置从统一入口运行；候选产物引用可追溯；保护路径及 Linux PID/starttime/恢复约束继续有效 |
| M7-03 | §4/M7 L270、L272 | ExecutorPool、BatchScheduler 和失败 EvidenceRecord 已进入 batch 路径，存在并发/崩溃测试 | 已接通 | S2→S5 持续保持 | 并发不超过评估资源上限；失败分类、attempt、branch_ref、cost 保存；部分失败不丢其它结果/费用，恢复不重付已完成操作 |
| M8-01 | §4/M8 L276、L280–296 | `executor/types.py:80` 规范大结果与 `eval/types.py:23` M0 小结果并存；转换不等于统一契约 | 组件已有未接通 | S2 | status/metrics/cost/fidelity 必选且验证；public/private、uncertainty、曲线/轨迹/产物引用及逐项证据可往返；旧适配明确标识缺失字段 |
| M8-02 | §4/M8 L291 | `executor/types.py:61` EvalRequest 有字段；主循环的分配主要固定 dev，完整请求语义未贯通 | 组件已有未接通 | S2→S5 | fidelity、time_limit、budget_token、seed_set、resume_from 被真正消费；不支持的能力前置拒绝，不能静默忽略 |
| M8-03 | §4/M8 L298；X1 L327 | v59 GSM 数据/solver 摘要、evaluation_context、cascade 与恢复绑定已经加入 | 已接通 | S2→S4 持续保持 | 数据、规则、模型或 split 改变即不可混比；配置漂移前置失败；外部/恢复路径不能以空上下文降级已声明绑定 |
| M8-04 | §4/M8 L296、L298 | TaskAdapter/benchmark 组件有指标与选择协议；缺通用 DomainPlugin eval 注册、metric_direction/eval_cmd 编译入口 | 组件已有未接通 | S1→S2 | 两个领域通过同一规范证据通道运行；min/max 方向可配置；域协议缺必需字段、未知命令适配或权限不兼容时拒绝 |

### M9 AdmissionGate

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| M9-01 | §4/M9 L302、L307–308、L314、L316 | `loop.py:307` 创建一个 gate；`:1639` 对同一评估结果准入；没有主循环三层 split 与三元组报告 | 待实现 | S4 | dev_best、gate_selected、final_audit 分开报告；dev 胜但 admission 败不能晋升；只有冻结候选可进入独立终审 |
| M9-02 | §4/M9 L309–313 | `eval/gate.py:98` 可复算逐项 flip/noise 判定，profile 不能切换通用 trigger/margin/selection | 组件已有未接通 | S4 | 用领域声明的可复算证据规则判定，覆盖连续指标及二元证据；trigger、margin、单调晋升、best/top_k 的配置有实际效果 |
| M9-03 | §4/M9 L310、L319 | 主账本有成本预留，尚无 admission 调用独立硬顶与 global budget 联动 | 待实现 | S4→S5 | 第 N 次允许、第 N+1 次在调用前阻断；每次准入评估仍扣全局/方向/候选成本；恢复不重扣计数或重复放行 |
| M9-04 | §4/M9 L315、L321 | `gate.py` 没有 LLM 单独放行；v59 decision_context/receipt_id 可重算；未有完整三层读权限和泄漏防线 | 组件已有未接通 | S4 | final 数据/反馈不可进入搜索 policy、operator、memory 或 knowledge；伪造/孤立回执拒绝；语义一致性检查和权限检查同时通过 |

### X1 Provenance & Audit 与 X2 HITL

| ID | 原文 | 基线实现证据与缺口 | 状态 | 阶段 | 端到端验收条件 |
| --- | --- | --- | --- | --- | --- |
| X1-01 | §4/X1 L325 | GitWorktreeExecutor、Frontier.code_ref、OpenEvolve 互操作有 lineage；M0 prompt loop 明确标识 non_git，不能冒称 git 产物 | 组件已有未接通 | S1→S2 | 配置 Git domain 后候选到 commit/branch/artifact 可追溯；非 Git domain 明确标识，不生成伪造 GitState |
| X1-02 | §4/X1 L326；§7.1 L477 | `x1/checkpoint.py`、loop 恢复、durable executor、v59 唯一目录 replay 已接通 | 已接通 | S1→S5 持续保持 | 新增模块状态、配置身份、未完成执行和预算均纳入检查点；恢复无重复副作用；重复 replay 各自隔离；不把 rerun 称为断电 exactly-once |
| X1-03 | §4/X1 L327 | workspace protected manifest、运行前后校验及 v59 数据绑定存在；各 domain 统一完整性钩子未组装 | 组件已有未接通 | S1→S4 | 运行期间保护文件/数据/harness 改变导致可审计失败；新 domain 必须显式声明受保护输入和摘要 |
| X1-04 | §4/X1 L328 | 尚无贯通主循环的 test-hash 去重、URL blocklist、canary 泄漏策略 | 待实现 | S4 | 配置的 canary/禁止来源在候选、上下文或输出中出现时按策略阻断；误用 final 数据有负例；不以哈希相同代替权限隔离 |
| X1-05 | §4/X1 L329–330 | AppendOnlyStore 和 audit 已有；不是可订阅的事件总线，独立 dashboard/export 订阅未贯通 | 组件已有未接通 | S1→S5 | 事件有版本/身份/来源，订阅者不写核心状态；移除展示订阅者不影响结果；导出覆盖全部决策和拒绝原因 |
| X1-06 | §4/X1 L331 | 有本地 Python 公开 API；无本仓库框架 MCP server 接入证据 | 后置 | 后续外部集成 | 能力对外暴露时保持权限/预算/身份边界；MCP 不是本轮五阶段完成的必要声明 |
| X2-01 | §4/X2 L335 | `hitl/controller.py:25` 只接受 auto/review，direction/collaborative 未实现 | 组件已有未接通 | S1 留接口；完整交互后续 | 运行配置可注入统一控制层；未实现模式拒绝而不降级；实现后对四模式分别验证请求与决策行为 |
| X2-02 | §4/X2 L336、L338 | HITLController 的哈希绑定/一次消费存在，executor 服务有独立用例；M0 主循环未普遍接钩子 | 组件已有未接通 | S1→S4 | 配置的 gate/保护路径/API 钩子统一走 X2；批准只对精确载荷有效且只消费一次，模块不得各自另造审批通道 |
| X2-03 | §4/X2 L337 | HITLController 有 pause/resume，尚无公开 /tree /evidence /pause /resume 交互通道 | 组件已有未接通 | S1 留接口；交互 UI 后续 | pause 后不再调度新副作用，已运行任务按明确策略处理；resume 与证据查询具有授权和持久状态 |

## §7 设计决策与反模式覆盖

下表不新增“已经完成”的结论；状态和端到端条件由所列稳定 ID 继承。

| 原文级别/行号 | 对应条款 | 验收解释 |
| --- | --- | --- |
| 必须 L471：结构化语义记忆 | M5-01～04、M4-03 | 必须证明经验进入后续生成，只有 memory JSONL 不算完成 |
| 必须 L472：独立准入与三元组 | M9-01～04 | 可复算 gate 与三层协议分别验证 |
| 必须 L473：失败一等状态 | M2-04、M7-03、M8-01 | 内容失败保留状态/费用；协议完整性失败仍拒绝继续 |
| 必须 L474：受控 mutation | A-02、M1-04 | policy 的权限不能随可配置性扩大 |
| 必须 L475：评估分层返回 | A-01、M8-01～04 | 统一规范证据往返并进入 M1/M3/M4/M9 |
| 必须 L476：provenance | M5-03、M6-01～02、X1-01～03 | 证据和经验来源可追溯、失效可传播 |
| 必须 L477：checkpoint/resume/事件 | X1-02、X1-05 | 新模块状态必须随恢复协议演进，事件不能只是打印 |
| 应该 L480：级联与 paired-seed | M3-03、M8-02、M9-01 | 同 seed 比较可核验；异质代理不套用同指标统计保证 |
| 应该 L481：收敛/耗尽 | M3-04 | 低样本用预先定义的规则，不宣称显著性 |
| 应该 L482：双层图与检索 | M4-02～03 | 引用边影响 context，不影响骨架信用 |
| 应该 L483：comparative-reflect | M2-03、M5-02 | 差分证据确实到达算子并保留来源 |
| 应该 L484：预算注入 | M3-05 | 注入真实预算视图，机制层仍独立校验 |
| 应该 L485：双车道知识 | M6-01～03 | 两个 backend、缓存、输出注入权限均隔离 |
| 可后置 L488：高级 MCTS/evo | M1-02、M4-04 | **后置**算法扩展；S1 必须先有可插拔接口，不必虚构多种成熟算法 |
| 可后置 L489：学习型 π_op | M2-02 | **后置**学习策略；算子集合与选择策略独立配置先完成 |
| 可后置 L490：容器规模化 | M7-02～03 | **后置**分布式/规模化容器；现有 worktree、进程沙箱和资源限制必须保留 |
| 可后置 L491：LLM judge | M9-04 | **后置**辅助 judge；任何阶段都不得单独凭其意见准入 |
| 反模式 L494：无作用域平铺 | M5-02、M4-03 | 外来作用域负例必须失败 |
| 反模式 L495：记忆整篇重写 | M5-01 | 晋升前内容被保留，增量可追溯 |
| 反模式 L496：test 无限反馈 | M9-01、M9-03～04 | 固定 split 权限、call_budget 与 final 不回流同时成立 |
| 反模式 L497：judge 单独放行 | M9-02、M9-04 | 有可复算判定信号，保留拒绝/未验证状态 |
| 反模式 L498：缺实现保真度 | A-01～04、所有阶段记录 | 配置必须改变可观察行为，阶段报告不以测试数量代替条款覆盖 |
| 反模式 L499：中途改假设 | M7-01 | 冻结假设及身份由机制检查，修复重试也不能越界 |

## §8 路线图对应关系

| 原文路线 | 本轮位置与基线状态 | 后续证据门槛 |
| --- | --- | --- |
| L507 语义记忆 × 进化框架（P0） | S3；组件已有未接通，M5-02/M4-02 | 改变 archive 拓扑仍能消费有作用域经验；不只保存历史候选 |
| L508 统计显著收敛（P1） | S5 先完成低样本规则；统计研究**后置** | 需要独立实验设计/样本和误判率验证；规则停止不改称显著收敛 |
| L509 跨 run 假设记忆（P0） | S3；组件已有未接通，M5-04 | 独立 run 可控共享、假设/来源索引与负例权限检查 |
| L510 三层默认协议（P0） | S4；待实现，M9-01～04 | 通用研究配置默认三层；兼容旧 M0 的单层模式需明确标识 |
| L511 语义 behavior descriptor（P2） | 基础 MAP-Elites 已有；语义 descriptor **后置** | 实际嵌入/描述符质量与确定性实验，不能由 JSON 字段存在推定 |
| L512 晋升忠实度/负面智慧/并发（P2） | S3 保持作用域/失效/串行写；完整研究机制**后置** | 晋升忠实度评测、负面经验独立策略、跨进程并发一致性需专项证据 |
| L513 实现保真度可观测（P2） | S1～S5；待实现完整观察链 | 配置、调用事件、返回证据和模块状态都能用于复算实际执行路径 |
| L516 MVP：LLM cycles/树/L1-L2/worktree/分层评估/gate/X1 | S1～S4 的组合验收；尚不能宣称整体完成 | 一份配置从公开入口贯通全部模块，实际执行与恢复；离线 LLM fixture 仅验证契约 |
| L517 差异化：L3/三层/fidelity | S3～S5 的组合验收；待贯通 | 跨 run 共享、独立终审、物理预算与昂贵评估续跑共同成立 |
| L518 生态位：frontier/语义 descriptor/Bandit | S1 提供插件接口，已有 archive 可复用；高级策略与语义 QD **后置** | 实际插件组合及独立性能评测后才能宣称覆盖相应系统 |

## 设计基准与旧 M0 约束的衔接决议

以下冲突必须显式处理；不能通过删除安全断言、静默降级新契约或继续扩大专用 loop 来隐藏。

| 冲突 ID | 旧实现/静态检查 | 本轮设计要求与处理标准 |
| --- | --- | --- |
| C-01 | `core/eval/types.py` 小 EvalResult 与 `core/executor/types.py` 大 EvalResult；`loop.py:158` 转换 | S2 以类型化 EvidenceRecord 为唯一新运行契约；旧二元结果通过有名、有验证的兼容适配器进入，不把缺失 cost 当成真实零成本，不丢失逐项/数据上下文 |
| C-02 | `ci/check_axioms.py` 的 `T_gate_not_rank` 禁止旧 gate 访问 combined_score/cost；旧 gate 固定 flip | 保留旧二元 gate 的限制；统一抽象允许领域声明的可复算 metric/margin/selection。新规则必须注册、绑定来源/split/方向并可审计；不能把“指标准入”与“成本混入准入”混为一谈 |
| C-03 | `T_no_clock_network_llm` 将整个 policy 包视为纯同步逻辑 | 文档要求软决策可由 LLM policy 完成。将外部调用放到明确的异步适配边界，预算/准入/状态校验继续纯机制化；用行为测试证明 policy 无权绕过硬保证，不直接删禁令来放开网络 |
| C-04 | `D10_benchmark_isolated` 静态禁止 loop/profiles 导入 knowledge | 研究模式需要 M6 接入，benchmark 仍须隔离。以显式 DomainPlugin 模式、依赖注入和“benchmark 零知识调用/零注入”端到端负例补强隔离；不把全局禁用 M6 当作完整实现 |
| C-05 | `A1_public_api` 固定 Framework 的 evolve/inspect/replay；profile 只有少数专用字段 | 保留公开入口兼容，组装通过构造配置/工厂或协议注入完成；不绕开 Framework 另造无人使用的演示入口来计完成 |
| C-06 | M0 主路径预算是 token，固定 intent_cost/dev；CostVec/多币种账本有零默认值 | S5 必须声明实际计量维度和单位，逐层执行硬顶；缺失测量保持未知/失败，不能仅因 dataclass 默认为 0 而认证免费执行 |
| C-07 | v59 replay 是重新执行，存在 provider 费用；历史 checkpoint 没有未来模块状态 | 新模块需明确 checkpoint/replay 状态契约、配置版本和兼容拒绝；工厂重建资源；高成本评估应优先采用受支持的 resume_from，不把 rerun 宣称为免费回放 |
| C-08 | 旧 gate/receipt、静态公理与历史 verifier 绑定 M0 行为 | 原始设计文档和 v1～v59 历史证据不重写；新阶段新增版本化验收与兼容说明。需要改变当前检查时，应保留旧路径回归并新增覆盖新契约的更强检查 |

## 阶段执行记录

以下初始表保留冻结基线与阶段计划；实际实现和验收结果在其后追加，不用局部通过覆盖未完成条款。

| 阶段 | 状态 | 已覆盖 ID / 仍未覆盖 ID | Mac 结果 | Linux 结果与提交 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 基线 v59 | 已接通的子条款见上表 | 五项正确性修复，不等于整份抽象完成 | 863 portable；18 tooling；11 axioms；3 examples | [CI 40879734092](https://github.com/YixuanZhang99/mori-27/actions/runs/40879734092)，`b45654f`：1,021 pytest，28 验收检查通过 | 新阶段以此为回归基线；无真实外部模型/benchmark 完成声明 |
| S0 | 清单建立 | 本文覆盖条款、冲突及阶段验收标准 | 文档核对 | 待随阶段提交 | 不宣称功能新增 |
| S1 | 待实现 | 待实施后列明 | 待运行 | 待运行、待提交 | 模块组装 |
| S2 | 待实现 | 待实施后列明 | 待运行 | 待运行、待提交 | 统一评估契约 |
| S3 | 待实现 | 待实施后列明 | 待运行 | 待运行、待提交 | 记忆与知识回流 |
| S4 | 待实现 | 待实施后列明 | 待运行 | 待运行、待提交 | 三层准入 |
| S5 | 待实现 | 待实施后列明 | 待运行 | 待运行、待提交 | 分层预算与组合验收 |

### S1 首次组装增量：实现与验收记录

本增量通过 `Framework.from_profile("composed_prompt", ...)` 接入配置注册表与优化闭环。**这只证明下列精确子范围，尚未满足所有标注 S1 的条款。** 当前默认实现为 tree、串行、inprocess、draft/reflective；X2 尚无配置注入，X1 尚无订阅事件总线。旧 M0 的批次、worktree、IID 对照和 HITL 独立组件不能计入新路径覆盖。使用方法及恢复限制见 [S1 使用指南](COMPOSED_RUNTIME.md)。

下表逐项覆盖上文全部 25 个涉及 S1 的 ID，并补记提前接入的 M2-04、M5-01 子范围。“已接通行为”是当前代码行为；整条验收条件是否完成仍由“剩余条件”及本次执行证据共同判断。

| ID | 本增量已接通行为与实现证据 | 剩余条件，不计为本次完成 |
| --- | --- | --- |
| A-01 | `composition/contracts.py`、`runtime.py` 以 Proposal→EvidenceRecord 串联候选、吸收和判定；`legacy_prompt` 显式转换旧结果 | S2 严格 codec、完整身份/逐项/来源字段及成本缺失语义；不是全框架单一结果类 |
| A-02 | runtime 先预扣再调用，校验候选/父节点身份和允许 mutation；policy 获得隔离的 frontier/evidence 副本 | S3–S5 的检索权限、分层评估和多层预算硬保证；受信任插件代码仍需遵守契约 |
| A-03 | `Registry` 注册并注入 provider/domain/skills；未知名、非法 JSON/options 在 factory 前拒绝；原生 canonical domain 和 skill 有实际运行负载 | 更完整的 domain 能力协商与协议校验留 S2；不以注册槽存在声称任意插件兼容 |
| A-04 | assembly 固定保存 mode、模块名和选项；legacy prompt 与原生 domain fixture 走同一公开入口 | 尚无两个完整真实任务 DomainPlugin；research 未开启知识管线；非空 knowledge 配置当前直接拒绝 |
| M1-01 | greedy 与 llm_cycles 的 observe/select/ideate/absorb 均由 runtime 调用；替换 policy 改变实际谱系与结果；driver 对所有策略统一检查父 ID、数量、去重和成功/可选状态 | 此次已接通四钩子与选择资格子条款；不扩展为后续评估、检索或预算契约已完成 |
| M1-02 | greedy 委托 frontier.sample；llm_cycles 产生受约束的 JSON 计划，策略费用计入同轮账本；非法计划、选择失败/剪除节点和越权 mutation 有负例 | 高级搜索算法与性能论证后置 |
| M1-03 | `strategies.py` 的 context_window 默认 8，裁剪工作历史并保存/恢复；端到端检查点与 memory 条目数可核对 | 当前是有界摘要条数，不是 token 上限或语义压缩；不宣称 M5 检索完成 |
| M1-04 | absorb 的 UPDATE_NODE/WRITE_MEMORY/PROMOTE_MEMORY 经 `StateApplier`，禁止 policy 自行 ADD/MERGE/PRUNE；更新不能伪造执行状态 | 只验证完整 cycle 边界恢复；中途未完成 cycle 拒绝自动重调，尚无一般 adoption |
| M2-01 | draft 使用 0 父、reflective 使用 1 父；任务、父产物/证据、策略和 skill 上下文传给同一 OperatorRequest | 无双父内置算子端到端、ContextPack 检索或层级预算输入；不能声称完整 0/1/2 父闭环 |
| M2-02 | 算子集合与 policy 分开配置；未知选择拒绝；自定义 operator 和 llm_cycles 的实际选择有端到端用例 | 目前默认策略针对 draft/reflective；任意算子组合必须由相匹配的策略选择并补契约测试 |
| M2-03 | draft/reflective 作为独立注册组件进入统一执行链，反射使用父反馈 | 六算子、差分反思和有来源的比较经验未接通 |
| M4-01 | 默认 ResearchFrontier 由配置工厂创建，接收 canonical 证据并保存/恢复 | selection/restore 仍依赖 ResearchFrontier；S2 的完整证据字段及其他 Frontier 恢复未完成 |
| M4-02 | 默认 tree 可运行；registry 有 frontier 槽 | 种群/island/MAP-Elites 尚不能在此路径按配置替换；统一双层拓扑恢复未验收，整条仍未接通 |
| M4-04 | 换 greedy/自定义 oldest policy 会改变实际父节点序列 | 尚无 frontier 采样压力配置入口及统一带种子采样协议；不能用“可换 policy”代替整条完成 |
| M6-03 | assembly 对非空 knowledge 前置拒绝，因此当前两个 mode 都不调用知识 | research/benchmark 的知识权限差异尚未实现；全局不接入不等于模式隔离已完成 |
| M7-01 | executor 注册槽和 inprocess 实现实际调用所选 domain | ExecutorSpec 的 role/frozen hypothesis/context projection 尚未进入配置执行链 |
| M7-02 | 非 Git prompt 产物在本地证据保存，原 Linux executor 回归继续保留 | 新路径未接 worktree/external executor、sandbox 和进程 adoption；inprocess 不提供沙箱隔离 |
| M8-04 | legacy_prompt 与原生 canonical domain fixture 均可调用；默认组件 metric/direction 可配置并检查一致性 | 完整领域声明、eval_cmd 能力适配和跨领域字段/权限校验待 S2；不是两套真实领域 campaign |
| X1-01 | checkpoint 明确使用 `git_state.kind=configured_artifacts`，候选及父节点写入证据 | 无配置 Git domain 的 commit/branch/artifact 追溯；不生成或宣称真实 GitState |
| X1-02 | 保存 assembly、运行参数、frontier、memory、显式模块状态和账本；完整 cycle 恢复及独立 replay 有端到端用例 | 仅支持 batch_size=max_inflight=1；组件需成对实现 checkpoint_state/restore_state；未完成付费 cycle 拒绝重调；无机器断电保证 |
| X1-03 | legacy domain 调用 validate_context，保存版本及 evaluation_context；数据漂移在调用前/恢复时拒绝 | 新 domain 的保护输入声明、统一运行中完整性钩子待 S2–S4 |
| X1-05 | AppendOnlyStore 保存 manifest、cycle、evidence、decision、ledger 和 checkpoint 事件 | 无可订阅事件总线、展示订阅和完整事件版本/来源契约；本轮仅已有存储接通 |
| X2-01 | 无新接通；旧 HITLController 组件保留 | assembly/registry 无 HITL 控制层注入槽，四模式未组装；S1 留接口要求仍未完成 |
| X2-02 | 无新接通；旧哈希绑定/一次消费回归保留 | 新路径 gate/保护路径/API 钩子尚未统一接入 X2 |
| X2-03 | 无新接通；旧 pause/resume 组件保留 | 新路径无统一控制注入或授权交互；stop_after_generation 仅测试性边界停止，不等于 HITL pause/resume |
| M2-04 | 已知 operator/domain 失败生成失败证据并保留费用；未知 usage 保留未结预扣后终止 | S2 全部失败分类/成本 codec，以及并发下部分失败的完整组合验收未完成 |
| M5-01 | 默认 absorb 写入 scoped L1 并增量提升 L2，检查点保存 memory | 检索、跨 run 晋升、所有阶段边界写入及 Frontier insight 来源链仍待 S3 |

新增回归文件为 `m0/tests/test_composition_registry.py`、`test_composition_defaults.py`、`test_composed_runtime.py`。其中 `test_policy_configuration_changes_actual_lineage_and_optimization_result`、`test_skill_configuration_reaches_provider_and_changes_evaluated_artifact`、`test_llm_cycles_policy_selects_actual_operator_and_persists_bounded_context` 验证配置改变实际行为；`test_boundary_resume_matches_uninterrupted_and_replay_attempts_are_isolated`、`test_unknown_usage_retains_reservation_and_resume_refuses_reexecution` 验证准确的恢复边界。以上测试名说明覆盖位置，不替代执行结果。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终复核通过：973 portable、158 Linux deselected、21 tooling、11 axioms、3 examples，包含父节点资格的新增回归；Linux deselected 不计通过 |
| 打包与导入快照 | `make build` 通过；`make verify-import` 校验 1,020 个保留负载文件通过 |
| Linux v60 | [CI 40889093796](https://github.com/YixuanZhang99/mori-27/actions/runs/40889093796) 通过：1,131 pytest、29 验收检查，613.777 秒；新证书/journal/summary 均已核实，原历史未改动 |
| 提交与 main 更新 | 阶段提交 `06491ce5639dd33f7f89bc8e1288f881b54ecb8c` 已通过同 SHA Linux 验收，main 已更新至该提交。本记录认证上述组装子范围，不宣称 S1 全条款或后续阶段通过 |

v60 成功证据从该 CI artifact 原样归档到 `m0/verifier/v60/LAST_RUN.json` 与 `m0/verifier/runs/v60.jsonl`，来源、摘要和字节保护见 [v61 历史证据说明](../m0/verifier/v61/README.md#archived-v60-evidence-provenance)。归档本身不会把 S1 结果当成 S2 结果。

后续仍需单独关闭本表中 S1 原定但未实现的拓扑、采样、executor、X2 和事件总线条款；不得在 S2–S5 推进时静默移除这些缺口。C-01/C-02/C-06 的严格身份、证据和预算迁移继续按阶段实施；C-03 的 LLM 软决策位于 composition 适配边界，原纯机制静态公理保留；C-04 的模式隔离尚未完成；C-05 的公开 API 已复用；C-07 仅覆盖上述明确恢复范围；C-08 保留 v1–v59 源码与历史记录。

### S2 配置路径评估契约：实现与验收记录

本增量的范围是 `composed-v2` 配置运行时，新增 `composition/evaluation.py`，沿用 canonical EvalResult/EvidenceRecord，并要求其携带严格契约。旧 M0 兼容路径保留；本记录不将“新增 codec”扩展为所有 domain/executor 已完成迁移。具体输入、计量和兼容规则见 [S2 指南](EVALUATION_CONTRACT_V61.md)。

| ID | 本增量已接通行为与实现证据 | 剩余条件，不计为本次完成 |
| --- | --- | --- |
| A-01 | 配置主循环统一验证和持久化 canonical 证据；严格 codec 往返完整评估字段，旧 evaluator 只经有名适配器进入 | 旧 M0/M7 其他运行路径保留原接口；不能声称全框架只剩一个结果定义 |
| A-02 | domain 能力/内容校验在付费调用前执行；完整结果与搜索/准入视图分开，身份错绑不得形成 mutation 或准入 | S3 作用域检索、S4 三层数据权限、S5 多层预算仍需各自硬保证 |
| A-03 | `domain=native` 通过同一个 Framework 入口接收原生 domain；要求版本、内容摘要、validate_request/evaluate | 完整 Provider × Domain × Skills 的生产级兼容矩阵和真实 campaign 未执行 |
| M2-04 | 失败证据保留状态/费用；业务身份无效但费用已知时仍结算，缺计量覆盖时保留预扣并拒绝继续 | 原生 domain 的未知异常不能自动推断费用；并发或中断 adoption 不由本阶段补齐 |
| M3-02 | `measured_cost_units` 明确已测维度，有限非负 CostVec 与 total_only/split token 语义受校验 | 当前账本仍只扣 token；多资源、全局/方向/候选限额与分配待 S5 |
| M4-01 | frontier 接收公开证据投影，完整私有结果独立保存在 journal/checkpoint；恢复校验候选键与产物绑定 | 只有 tree 的 portable restore；种群/拓扑和分层评分仍未接通 |
| M5-03 | 默认 absorb 只收到公开字段；private payload/metrics/items 不进入默认 memory 或父候选生成输入 | 来源有效性传播、跨 run 记忆权限和检索预算待 S3；错误标成 public 的内容不被自动清洗 |
| M7-01 | inprocess executor 保留 producer 的原始评估结果，交由 driver 按费用→身份/状态顺序验证 | ExecutorSpec role/frozen hypothesis/context projection 与 worktree 执行仍未组装 |
| M7-03 | 规范状态/attempt/executor_status 一致性验证，已知失败费用与结果原样持久化 | 新路径仍串行；并发部分失败、已付费中断接管的组合条件未完成 |
| M8-01 | 严格验证/往返 status、metrics、cost、fidelity、uncertainty、引用、typed public/private、逐项证据；legacy reliability 独立保存在 public.metadata；缺测量覆盖不能用零默认值认证 | legacy reliability 不自动解释为规范 uncertainty；旧外部执行器迁移需独立证据 |
| M8-02 | EvalRequest 含 split_id，严格验证限额/seed/续跑引用；domain 显式验证支持能力；legacy 不支持参数调用前拒绝 | 调度仍固定 dev；真实 fidelity/seed/time_limit/resume_from 分配与消费待 S5/相应 domain |
| M8-03 | producer binding 绑定候选、产物、请求、评估器、内容上下文、split、fidelity、seed；运行前及恢复比对冻结身份 | legacy 空上下文仍为不透明边界；任意外部数据的实际完整性由 domain 声明与校验，不能仅凭格式正确的 digest 认证 |
| M8-04 | native 和 legacy_prompt 通过同一规范结果通道；原生 domain 必须声明身份并拒绝不支持请求 | 未接通通用 eval_cmd、受限工作区权限协商和两个真实领域 campaign |
| M9-02 | gate 只接收 ComparisonEvidence 中的公开指标/身份/状态/fidelity/uncertainty，无 cost 或完整私有 contract | 三层、trigger/top_k、独立终审及多领域判定规则仍待 S4；当前仅 dev metric gate |
| M9-04 | 私有字段不发给 policy/operator/default memory，准入获得受限比较视图；完整证据仍可审计 | 这不是独立 final_audit 权限与防泄漏认证；秘密误放 public、恶意插件和终审回流仍需对应边界 |
| X1-02 | `composed-v2` 检查点严格解码并验证所有 proposal/evidence；完整字段可恢复/replay；v1 缺契约检查点在付费前拒绝 | cycle 中断 adoption、独立资源工厂、组件内部状态仍遵循 S1 限制；无自动补造历史身份 |
| X1-03 | domain 元数据与冻结 manifest 对齐，每轮调用 validate_context/validate_request，结果 independently bound | 完整 protected-input/harness 文件契约和所有 external executor 接入仍需后续工作 |

新增验收组为 `test_evaluation_contract.py` 与 `test_composed_evaluation.py`；后者通过公开 Framework 检查原生 domain 的完整结果、错绑失败仍计费、未知计量保留预扣、不支持请求零调用、私有字段隔离及 v1 检查点拒绝。v61 保留全部 v60 命令组和超时，v58→v59→v60→v61 的迁移保护继续保留。历史 v60 证据已从真实成功的 S1 CI 原样归档，不代表 S2 验收结果。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终实现复核通过：1,048 portable、158 Linux deselected、11 axioms、3 examples，包含 reliability 元数据增量；归档 v60 后 `make tooling` 单独复核 24 项全部通过 |
| 历史与 source 检查 | v61 的 9 项历史/source-only 检查通过，未执行 Linux 工作负载或生成 v61 运行证书 |
| 打包与导入快照 | 最终实现的 `make build` 与 `make verify-import`（1,020 文件）通过 |
| Linux v61 | [CI 40891610362](https://github.com/YixuanZhang99/mori-27/actions/runs/40891610362) 通过：1,206 pytest、30 检查、447.362 秒；新证书/journal/summary 已核实，历史未改动 |
| 提交与 main 更新 | 阶段提交 `babe764c7b2bb83d5fdb0151316a8677d21052d7` 已通过同 SHA Linux 验收，main 已更新至该提交 |

v61 成功证据已从真实 CI artifact 原样归档到 `m0/verifier/v61/LAST_RUN.json` 与 `m0/verifier/runs/v61.jsonl`，来源和字节摘要见 [v62 历史证据说明](../m0/verifier/v62/README.md#archived-v61-evidence-provenance)。该归档不代表 S3 验收通过。

S2 没有关闭 S1 的 population、统一采样压力、worktree、HITL 和事件总线缺口，也没有将 S3–S5 标为完成。C-01 通过规范通道与显式旧接口适配推进；C-02 保持旧二元 gate 公理并限制新 gate 输入；C-06 先落实计量覆盖而非宣称多层预算；C-07 通过新运行版本拒绝不完整旧检查点；C-08 保留 v1–v60 verifier 源码与历史记录。

### S3 作用域经验与本地知识回流：实现与验收记录

本阶段新增 `composition/context.py` 与 `composition/knowledge.py`，运行版本为 `composed-v3`。范围是有权威来源的 M5 检索、实际 ContextPack 输入、显式跨 run 分享和本地 M6 双车道回流；不是外部联网搜索、向量检索或语义质量认证。可用配置及生命周期见 [S3 指南](CONTEXT_FEEDBACK_V62.md)。

| ID | 本增量已接通行为与实现证据 | 剩余条件，不计为本次完成 |
| --- | --- | --- |
| A-02 | 权威证据 hash 绑定 memory 来源/作用域；skill/operator 不得原地篡改 context 或替换 context_pack_ref；不支持模式/导入在付费前拒绝 | S4 终审权限、S5 多层物理预算及受信任插件之外的隔离仍需后续机制 |
| A-04 | 同一 assembly 显式切换 research/benchmark；research 可配置 local_files，benchmark 非空 knowledge 在 factory/读文件前拒绝 | 完整两领域生产适配与外部知识集成未认证 |
| M1-01 | 检索后的实际 context 进入 ideate；策略获得隔离副本，状态与记忆写入仍受 driver 约束 | 默认 llm_cycles 的 observe 计划仍有界且不等于语义推理质量证明 |
| M2-01 | OperatorRequest 获得父证据与实际 ContextPack；Candidate 保存内容 hash；测试证明经验改变非父节点 draft 的输入/产物 | 内置双父算子、完整六算子和层级预算输入仍未实现 |
| M2-03 | 反射/起草可消费有来源的经验与 ground 知识 | comparative-reflect 及六算子研究闭环仍未接通 |
| M3-05 | context 带明确字符长度预算，日志记录检索和最终纳入的条目 | 这是上下文长度预算，不是 proposer 的真实全局/方向/候选 used/remaining 视图；后者仍待 S5 |
| M4-03 | frontier 的 parents/ancestors/parent_siblings/run 描述符先缩小可读 ID，M5 再检索；高相关度不能绕过范围 | 当前不沿 reference 边扩张检索；更广双层图能力与工作区 executor 投影仍未接通 |
| M5-01 | 本轮公开 dev 证据产生受约束 L1，成功证据增量晋升 L2；可在结束时导出本 run 合格经验；暂停不执行结束导出 | 完整阶段触发规则、自动 L3 抽象和语义忠实度评测未完成 |
| M5-02 | scoped ContextMemory 实际检索后进入候选输入；topology、scope、状态、trust、levels、negative 与字符上限均影响纳入 | 词项/效用排序不等于向量或语义检索；默认 gated 过滤失败，需显式 ungated 才可读取失败经验 |
| M5-03 | 来源引用改为同时绑定 logical_run_id 和真实证据的 hash；相同评估在不同 run 不复用 receipt；伪造来源/信任提升拒绝，失效后下一包移除而历史保留；非 dev/私有数据不成为经验 | 不自动清洗被错误标为 public 的秘密；跨进程权限与外部签名认证不由内容 hash 提供 |
| M5-04 | 独立新 run 有不同 logical_run_id；export_on_finish→明确 hash imports→include_imported 的 Framework E2E 改变下一 run 首次输入 | 仅授权快照传输；未实现全局共享数据库、自动假设聚类或自动 domain 晋升；legacy 空内容上下文只允许 run 范围 |
| M6-01 | local_files 实际限长打开 UTF-8 内容并记录 URI/hash；ground 与 audit 分离 backend/query/namespace；仅 ground 注入，跨 lane 内容重叠使 audit 失效 | 未调用网络知识 provider；audit 仅 advisory，不独立准入或声称外部新颖性准确率 |
| M6-02 | ingest_on_finish 将显式 M5 导出写入独立 M6 records；下一 run 的 knowledge.memory_imports/retrieve 经内容和作用域验证后进入 ground 包；原 M5 不被混写 | 当前只提供本地 TIER2/词项检索；完整多 tier/workflow、联网知识和高成本 retrieval 预算尚未实现 |
| M6-03 | benchmark 的 knowledge 在读取/构造前拒绝；research 可实际打开文件并查询，公开入口负例证明模式差异；旧静态检查保留 | 任意第三方 backend 的外部资源权限需独立验证，不由 local_files 结果外推 |
| M8-03 | domain 内容身份参与 memory/knowledge scope 与导入验证；知识 manifest 绑定已打开文件内容 | 运行中使用打开时快照；新文件更新不自动刷新，恢复/replay 必须匹配原 manifest |
| M9-04 | audit 文本独立记录，不进入 policy/operator/default memory 或准入；保留 S2 的私有字段与受限比较视图 | 当前仍是 dev 单层；独立 final_audit 数据及其不回流保证待 S4 |
| X1-02 | v3 checkpoint 保存 logical_run_id、memory 权威绑定/import、知识状态和结束导出；恢复/replay 核对导出 hash；完成恢复不重复导出 | v1/v2 缺作用域身份明确拒绝；仍只支持串行 cycle 边界，未完成付费操作不自动重调 |
| X1-03 | 输入知识文件和显式快照的 hash/manifest 在启动及恢复验证；篡改导出拒绝后续付费工作 | 完整 protected-file/worktree executor 与通用 harness 完整性仍未组装 |
| X1-05 | 新增 context_pack、composed_context、memory_receipt_binding、import/export、fetch/audit/ingest/retrieve 等可核对事件 | 仍是 AppendOnlyStore，没有订阅事件总线或独立 dashboard 完整契约 |

S3 显式组为 `test_composed_context.py`、`test_composition_context.py`、`test_composition_knowledge.py`。公开入口用例包括 `test_failed_nonparent_memory_changes_next_draft_input_and_artifact`、`test_ground_sources_change_actual_candidate_but_audit_text_never_reaches_search`、`test_explicit_memory_export_import_changes_next_run_and_completed_resume_is_idempotent`、`test_export_to_knowledge_ingest_then_scoped_retrieval_is_a_separate_store`；同时覆盖错误 hash/task/dataset、benchmark 禁用、来源伪造、原地 context 篡改、导出篡改和恢复/replay。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终实现复核通过：1,094 portable、158 Linux deselected、11 axioms、3 examples，包含 run-bound receipt 与导出完整性新增回归；归档 v61 后 `make tooling` 单独复核 27 项全部通过 |
| 历史与 source 检查 | v62 的 9 项历史/source-only 检查通过，未执行 Linux 工作负载或生成 v62 运行证书 |
| 打包与导入快照 | `make verify-import` 校验 1,020 文件通过；最终 `make build` 通过 |
| Linux v62 | [CI 40894739044](https://github.com/YixuanZhang99/mori-27/actions/runs/40894739044) 通过：1,252 pytest、31 检查、641.858 秒；新证书/journal/summary 已核实，历史未改动 |
| 提交与 main 更新 | 阶段提交 `ccb91c86c4b8dc05d52fb3f09c3fd6cfc13d8891` 已通过同 SHA Linux 验收，main 已更新至该提交 |

v62 成功证据从实际 S3 artifact 原样归档到 `m0/verifier/v62/LAST_RUN.json` 与 `m0/verifier/runs/v62.jsonl`，来源和摘要见 [v63 历史证据说明](../m0/verifier/v63/README.md#archived-v62-evidence-provenance)。该归档不代表 S4 验收通过。

S3 不关闭 S1 尚未实现的种群/采样压力/worktree/HITL/事件总线条款，也未实现 S4 三层准入或 S5 分层预算。C-04 已在本地知识配置路径落实 research/benchmark 的实际行为差异；C-07 升级作用域检查点并保留付费 replay 语义；C-08 继续保持旧 verifier 源码及历史失败证据。

### S4 三层准入与独立终审：实现与验收记录

本增量新增 `composition/admission.py`，在 `composed-v4` 的原生 domain 配置中显式选择 `admission=layered`。默认 `composed_prompt` 继续使用 dev-only metric 兼容路径，因此本阶段不关闭 §8 L510 的“三层默认协议”全部要求。使用方式和非支持配置见 [S4 指南](LAYERED_ADMISSION_V63.md)。

| ID | 本增量已接通行为与实现证据 | 剩余条件，不计为本次完成 |
| --- | --- | --- |
| A-01 | 三层调用都返回 S2 canonical EvidenceRecord，并保留完整费用/私有证据；准入只使用受限公开比较视图 | 旧 M0 兼容路径仍保留自己的结果/二元 gate 类型，不声称已全面替换 |
| A-02 | split 内容、支持能力、选项和完整性在调用前校验；driver 独立控制预扣、回执、冻结与最终报告 | 同进程插件不是安全沙箱；S5 多层物理硬顶和 X2 统一控制尚未接入 |
| A-04 | 同一 Framework 可显式配置两层或三层 native 协议，research/benchmark 原有隔离保留 | 默认 profile 仍 dev-only；真实多领域 campaign 与完整通用研究默认配置未完成 |
| M2-04 | admission 失败不晋升；已开始失败计入调用上限，已知费用仍结算；身份错误不发准入回执 | 未知用量保留预扣，未完成操作不自动重调；外部进程接管未组装 |
| M3-01 | 每个 admission/final 评估经独立预算意图预扣；配对调用在开始前需整组预扣成功 | 当前仍全局 token/reeval 账户，未实现方向/候选限额及 allocate/should_continue 全控制器 |
| M3-02 | 三层已知 token 实际结算，缺计量覆盖不能按零值通过；付费调用数与物理 token 分开计量 | 多资源单位和全局/方向/候选分层硬顶仍待 S5 |
| M3-03 | admission/final 的显式 fidelity/seed_set 真实传入 domain，配对使用相同请求与 seeds | 未实现级联晋升、time_limit/resume_from 分配及周期 anchor |
| M4-01 | frontier 仍存公开 dev 证据；最终选出者必须经过独立 admission，dev_best 与 gate_selected 分开报告 | 仍 tree；种群、骨架/引用图扩展及层级评分未完成 |
| M5-03 | admission/final 的反馈与私有结果不写入默认 memory；已有 dev 来源约束继续生效 | 不会自动发现错误标为 public 的秘密；无通用语义泄漏检测 |
| M6-01 | knowledge 的 ground/audit 仍按 S3 独立车道；final 不进入知识 ingest/retrieve 的反馈来源 | 知识 audit 仅 advisory，不等同于独立评估 final_audit；网络 backend 仍未接入 |
| M8-02 | domain 用完整 EvalRequest 声明三层能力；不支持 split/fidelity/seeds 的 legacy 在付费前拒绝 | 通用 constrained-resource/resume 调度仍未完成 |
| M8-03 | 冻结各 split 的内容身份；dev/admission/final 内容上下文必须不同；缓存与回执绑定产物、版本、请求、数据与种子 | 摘要由 domain 按实际数据生成；不同字符串不能自行认证真实外部数据权限或内容隔离 |
| M9-01 | dev_best、gate_selected、final_audit 三元组实际报告；dev 改善但 admission 退步不能晋升；结束后冻结候选再独立终审 | 默认 profile 尚未切三层，真实领域评估仍需提供数据及实现 |
| M9-02 | 连续公开指标支持 maximize/minimize、dev min_dev_gain、严格 admission margin 与 best 单调晋升；实际记录重算 trigger/判定 | top_k 显式拒绝；旧二元 gate 保留测试但未作为新 layered 规则插件组装，未完成所有领域规则矩阵 |
| M9-03 | 独立 admission call_budget 在调用前硬限制，包含基线及失败；缓存不重复计数；checkpoint 不能抹掉已开始调用；final 最多一次且仍扣全局 token | 尚未同步扣方向/候选层级和多资源限额，这部分依赖 S5 |
| M9-04 | 回执绑定并比对实际 dev/admission 记录，重 hash 篡改拒绝；final 数据不进入 policy/operator/frontier/memory/knowledge，反向 final 分数不能改已冻结选择 | 非恶意组件的协议/读写权限受测；同进程恶意插件、语义一致性模型、LLM 辅助 judge 不在本阶段范围 |
| X1-02 | v4 保存 layered 调用、缓存、实际 dev 记录、回执和冻结状态；边界暂停不终审，完成恢复不重复付费终审；只追加日志阻断回滚遗忘调用 | v1/v2/v3 明确拒绝；仍 serial/tree/inprocess，无中途付费重调或 worktree adoption |
| X1-03 | domain 三层身份在开始、每次调用及恢复核对；hash_check 必需且不能关闭 | 完整 protected-file/harness 声明及外部工作区执行器仍未统一组装 |
| X1-04 | 可选 canary 按字面串扫描任务/上下文/候选，blocked_sources 精确匹配上下文来源；两者在相关付费执行前阻断 | 不是通用 URL 规范化/网络防火墙、语义泄漏或所有输出扫描；没有以哈希代替权限隔离 |
| X1-05 | 持久化 layered 状态、额外评估证据、预算拒绝、比较回执和最终报告，恢复使用真实调用日志 | 仍无订阅事件总线和独立 dashboard 完整事件协议 |
| X2-02 | 无新增统一人工控制；human_approval 等未实现模式前置拒绝 | HITL 的正式注入槽、保护路径/API/gate 授权仍是未关闭缺口 |

v63 显式组是 `test_layered_admission.py` 与 `test_composed_admission.py`。端到端用例检查 dev 过拟合不晋升、final 反向分数不改选择、预算不足零调用、已知失败费用、分层内容碰撞、来源阻断、恢复与两层报告。组件用例补充基线配对成本、缓存身份、实际记录重算、篡改重新 hash、调用日志不能被旧 checkpoint 遗忘与不支持配置拒绝。保留 v62 所有组和超时，不用删除旧安全公理来接入新 gate。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终实现复核通过：1,149 portable、158 Linux deselected、11 axioms、3 examples；归档 v62 后 `make tooling` 单独复核 30 项全部通过；Linux deselected 不计通过 |
| 历史与 source 检查 | v63 的 9 项历史/source-only 检查通过；未执行 Linux 工作负载或生成 v63 运行证书 |
| 打包与导入快照 | 最终实现 `make build` 通过；`make verify-import` 校验 1,020 文件通过 |
| Linux v63 | [CI 40898306157](https://github.com/YixuanZhang99/mori-27/actions/runs/40898306157) 通过：1,307 pytest、32 检查、592.512 秒；新证书/journal/summary 已核实，历史未改动 |
| 提交与 main 更新 | 阶段提交 `41a8dc83340b787fdbfef73dbee2c8759751bbe2` 已通过同 SHA Linux 验收，main 已更新至该提交 |

v63 成功证据从实际 S4 artifact 原样归档到 `m0/verifier/v63/LAST_RUN.json` 与 `m0/verifier/runs/v63.jsonl`，来源和摘要见 [v64 历史证据说明](../m0/verifier/v64/README.md#archived-v63-evidence-provenance)。该归档不代表 S5 验收通过。

S4 推进 §7 必须的独立准入/三元组与 provenance，覆盖 paired-seed 和禁止无限 test 反馈的已实现子范围；不把连续 margin 称为统计显著性。C-02 保留旧 gate 的 cost/rank 公理且新增受限判定，C-06 仍需 S5 层级物理预算，C-07 升级调用状态与付费恢复边界，C-08 保留旧 verifier 源码与真实历史失败记录。S1 的种群、采样压力、worktree、X2 与事件总线缺口继续保留。

### S5 分层物理预算与 fidelity：实现与验收记录

本增量新增 `composition/budget.py` 的 `HierarchicalBudget` 和 `hierarchical_runtime.py` 调用桥接，运行版本为 `composed-v5`，通过 `budget=hierarchical` 显式配置，并为完整离线 research 例子增加独立验收入口。组件契约和配置见 [S5 指南](HIERARCHICAL_BUDGET_V64.md)。以下区分已实现子范围与没有关闭的要求；测试通过本身不把所有条款变为完成。

| ID | 本增量已接通行为与实现证据 | 剩余条件，不计为本次完成 |
| --- | --- | --- |
| A-01 | 三层预算复用规范 EvalRequest/EvidenceRecord/CostVec；Proposal 增加显式 measured_cost_units，未知零值不能作为免费操作证据 | 旧 M0 的兼容类型及外部执行器契约没有全面迁移 |
| A-02 | 预算配置先验证完整单位覆盖；硬预扣由机制层执行，不能由 policy/operator 提供的预算文本覆盖；任一层失败不留下部分扣款 | 同进程插件不构成权限沙箱；外部资源强制限额、X2 控制及全部算子组合未认证 |
| M1-04 | 预算事件独立按固定 intent 指纹写入只追加日志；恢复不能重新解释请求/方向或重复结算 | 仍保留既有 mutation 白名单；没有通用事件总线或多进程事务 |
| M2-01 | operator 预算输入与配置请求来自实际账本/分配器，作用域 ContextPack 和候选身份仍受 driver 校验 | 完整六算子、双父及多样化生产策略未完成 |
| M2-04 | 已开始失败保留实际已知用量；缺测量覆盖保持未结预扣并禁止新付费操作；已开始不能按免费释放 | 自动恢复外部未知用量和付费进程 adoption 未接入配置路径 |
| M3-01 | global/direction/candidate 是同一操作日志的三个视图；完整单位篮子原子预扣/结算；allocate/should_continue/converged 具有明确配置与状态 | controller 内锁不等同于分布式事务；不能保证失控外部调用在预扣估计内结束 |
| M3-02 | token/eval_count/node/wallclock/gpu_hours/usd 按物理单位分别计量，禁止混加；实际超额如实结算后阻断后续调用；未知用量不归零 | GPU/USD 等以合成计量 fixture 覆盖账本契约，未执行真实 GPU/provider 账单 campaign；没有 OS/cgroup 强制资源限制 |
| M3-03 | fidelity_rungs 产生真实 dev EvalRequest，direction_calls/depth 阶梯明确；admission/final 请求独立且共享物理预算；配对 dev_baseline 不推进阶梯 | 固定 rung 计划不是自适应统计级联；真实 time_limit/resume_from 语义依赖 domain，不宣称外部作业续跑已接通 |
| M3-04 | min_samples/patience/min_improvement 按有效 dev 记录和比较口径计算；纯控制器在比较口径变化时重置窗口，configured run 的数据/评估器漂移仍拒绝；方向/全局耗尽有可复算原因；选择视图过滤耗尽方向但保留持久骨架，greedy 可换分支或新 draft | 停止信号是低样本规则且 statistical=False；不证明收敛到最优或有统计显著性 |
| M3-05 | 公开预算视图逐单位给出 used/reserved/committed/remaining，与允许请求共同进入 proposer 输入，state 在当前 operator 预扣/开始后刷新；机制层独立执行硬顶 | 不自动为模型的预算建议提供可执行权限；生产提示质量与真实资源预测误差尚未评估 |
| M3-06 | 本轮 fidelity 请求及同口径基线为后续 anchor 提供可比较证据基础 | 周期 anchor、proxy–true 秩相关告警/降级、负反馈写回 M5 仍未完成；不能以本轮同口径补评代替此条 |
| M4-01 | 不同 fidelity 请求不能直接混比后晋升；需要以当前请求建立可比较基线 | 默认 frontier 仍 tree，种群、统一采样压力和完整多 fidelity 排名策略未完成 |
| M5-03 | 停止规则只使用 dev 公开证据，admission/final 不驱动搜索进展；预算事件不伪装成语义经验 | 自动 anchor 异常写回和更广阶段触发记忆规则仍未完成 |
| M7-03 | 操作 start/reserve/settle/unresolved 身份持久化，已知失败用量保存；历史 Linux 恢复回归继续保留 | 配置运行时仍串行/inprocess，不将组件原子性测试外推为 executor 并发/中断接管已组装 |
| M8-01 | 计量覆盖与 CostVec 数量同时校验；driver 权威记录新候选 node=1，operator/evaluation token 不能低于共享 provider 已知增量，低报留差异记录并 unresolved；业务身份无效不能逃避已知成本 | 信任 domain/provider 如实测量；声明格式不能认证外部账单真实性 |
| M8-02 | 配置 fidelity/seed/时限/token/resume 字段作为完整 EvalRequest 传入 domain，并验证支持能力；不支持字段不静默忽略 | 当前离线示例只使用固定 dev rung；外部资源限制/作业续跑需要相应真实 domain 验收 |
| M8-03 | 预算 intent、比较基线和停止窗口绑定完整请求、split、数据、版本与种子；口径漂移不能继续拼接进展 | 输入真实完整性仍由 domain 提供；没有通用文件工作区权限声明 |
| M9-02 | 成本与预算仅决定能否执行，准入继续由实际公开证据复算；不同 dev fidelity 先对齐基线 | top_k 和二元规则插件组装仍未完成 |
| M9-03 | admission/final 作为独立物理操作扣同一全局/方向/候选预算，同时保留 S4 admission call_budget 与 final 一次硬顶 | 外部执行单次实际超额只能如实记录并停止下一次，不能事后撤销消耗 |
| X1-02 | 预算恢复重放真实追加日志并严格比对配置、stamp、序列、摘要与 checkpoint；未完成付费操作拒绝自动重调 | 不自动修补旧运行版本，仍无机器断电保证或新路径 worktree adoption；严格 replay 的完整状态比较可能因实测 wallclock/非确定性结果失败 |
| X1-05 | 追加完整物理预算事件、公开状态和停止原因；离线例子输出三元评估/三层预算/经验导出/replay 结果 | 没有订阅事件总线或独立 dashboard 的完整协议 |

v64 新增 `test_hierarchical_budget.py`、`test_composed_budget.py` 显式组，并单独执行 `examples/composed_research_offline.py`。Mac `make examples` 同时加入该例子，共四例。组件回归覆盖并发原子预扣、任一层/单位拒绝、真实超额与未知覆盖、不可重复身份、阶梯计数、比较窗口、日志回滚篡改与只读恢复；公开 Framework 用例包括 `test_framework_accounts_each_physical_charge_once_across_three_views_and_replays`、`test_new_rung_pays_for_matching_incumbent_baseline_and_updates_public_frontier_evidence`、`test_exhausted_direction_is_hidden_only_in_selection_view_and_greedy_can_start_new_direction`、`test_operator_budget_context_contains_its_own_started_reservation`，另覆盖 unknown planning、已知失败/错绑费用、真实 node 尝试、wallclock 来源、独立 M9 调用上限和恢复。示例已独立运行并核对 3 个候选、6 次本地评估、60 合成 token、1 次终审、3 条 L2 导出及 replay=True；最终全量结果仍以本表为准。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终实现复核通过：1,240 portable、158 Linux deselected（18.35 秒）、34 tooling、11 axioms、4 个离线示例；Linux deselected 不计通过 |
| 历史与 source 检查 | v64 的 9 项历史/source-only 检查通过，未生成 v64 运行证书 |
| 打包与导入快照 | 最终实现 `make build` 通过；`make verify-import` 校验 1,020 文件通过 |
| Linux v64 | [CI 40904572252](https://github.com/YixuanZhang99/mori-27/actions/runs/40904572252) 通过：1,398 pytest、34 检查、644.819 秒；新证书/journal/summary 与 handoff receipt 已核实，历史未改动 |
| 提交与 main 更新 | 阶段提交 `685fd5fffae41d693cc4f4865bd763cb64dcae15` 已通过同 SHA Linux 验收，main 已更新至该提交；本次后续开发归档其真实证据 |

C-06 通过显式物理计量与三层视图推进，仍不将缺失 measurement 当零，也不把限额账本称为资源沙箱；C-02 继续隔离费用与准入；C-07 保持严格恢复与真实付费 replay；C-08 保留 v1–v63 verifier 源码和全部真实历史证据。S1 的种群/采样/worktree/X2/事件总线，S3 外部网络知识，S4 默认三层/top_k，以及 M3-06 的 anchor 与异质代理校验仍是明确剩余项。


v64 成功证据已原样归档到 `m0/verifier/v64/LAST_RUN.json` 与 `m0/verifier/runs/v64.jsonl`，来源和摘要见 [v65 历史证据说明](../m0/verifier/v65/README.md#archived-v64-evidence-provenance)。这是 S5 的真实结果，不是 S6 的验收结果。

### S6–S8 后续补齐计划

以下计划承接 S1–S5 已验收增量和明确未关闭条款，保留原始清单与历史阶段记录。每阶段先完成该范围的公开入口 E2E 与 Mac 检查，候选提交在同 SHA 完整 Linux 验收通过后再推进 main；阶段封板后才切换下一 verifier，不把下一阶段代码混入当前提交。此表是计划，不是完成声明。

| 阶段 / verifier | 对照 ID 与原文依据 | 计划范围 | 必须可观察的端到端验收条件 | 当前状态 |
| --- | --- | --- | --- | --- |
| S6 / v65 | M3-06（§4/M3 L164、§6.2 L442–444）；关联 M3-02～04、M5-03、M8-03、M9-04、X1-02 | 周期 anchor；proxy 与 true 的配对证据及秩相关有效性规则；失效时告警/降级和负反馈进入 scoped memory | 配置周期实际触发独立开发 calibration anchor 并经三层预算；请求/数据/seed 身份可核对；样本不足与无效相关明确区分；故意反向 proxy 触发预定动作并改变后续输入；admission/final 不进入搜索反馈；恢复/replay 保留调用、有效性与记忆来源 | 已接通子范围见下方 S6 实现记录；最终 Mac/Linux 按阶段证据核对 |
| S7 / v66 | M7-01～03（§4/M7）；X1-01～03（§4/X1）；关联 A-02、M2-04、M8-03 | 将现有 worktree/进程执行与身份写入、保护输入、终态证据和中断接管接入同一配置运行时 | 公开 Framework 实际创建隔离工作区并执行候选；真实 Linux 中断后按进程身份接管，不重复付费、不丢失已知结果；保护文件篡改拒绝；完整证据/成本/来源可恢复；Mac 本地检查明确区分需要 Linux 的用例 | S7 已按同 SHA Linux 验收封板；已接通子范围及保留限制见下方 S7 记录 |
| S8 / v67 | M4-01～04（§4/M4）；M1-02（§4/M1）；关联 M2-03、M5-02、X1-02 | 配置种群 frontier 与选择/生存接口，保留骨架与引用边语义、作用域检索及预算/准入边界 | 同一配置入口选择种群并真实改变保留/选择结果；选择不能引用无资格个体；多样性/生存规则可复算；引用边不能偷改骨架信用；checkpoint/resume/replay 保留种群与来源；已有 tree 和全套安全回归继续通过 | S8 已按同 SHA Linux 验收封板；已接通子范围及保留限制见下方 S8 记录 |

S6 当前验收组为 `test_proxy_validity.py`、`test_composed_proxy.py`；v65 保留 v64 的全部命令、超时与真实历史证据。接线阶段 tooling 37 项、历史/source-only 9 项通过，未生成 v65 运行证书；这些不代替 S6 公开入口功能或 Linux 验收。S7/S8 的测试文件名与精确子范围在实现前确定，不提前认证生产环境隔离、分布式并发或真实外部 benchmark。

### S6 周期 anchor 与 proxy 有效性：实现记录与验收门槛

本增量新增 `composition/proxy.py`、`proxy_runtime.py`，在 hierarchical budget 中显式配置 proxy_validity，运行版本为 `composed-v6`。校准使用独立开发 `calibration` split；既不使用 admission/final 反馈，也不把不同指标的绝对数值当作同量纲改善。配置、触发与限制见 [S6 指南](PROXY_VALIDITY_V65.md)。

| ID | 本增量已接通行为与实现证据 | 仍保留的边界 |
| --- | --- | --- |
| A-02 | 配置和 calibration 内容身份前置校验；driver 掌握预算、配对来源、负反馈写入和晋升否决，policy 无权自报校准结论 | inprocess 仍不是恶意插件沙箱；工作区/进程接管待 S7 |
| M3-02 | anchor 是独立物理操作，candidate/baseline 整组先预扣；每次成本仍计入全局/方向/候选；失败与未开始释放分开 | 不提供外部资源操作系统硬限额；未知用量不能自动推断 |
| M3-03 | anchor_request 的 calibration split、fidelity、seed 等完整请求实际交给 domain；成功缓存要求完整请求/产物/来源匹配 | 本阶段采用显式固定周期与监控规则，未声称通用自适应最优资源分配 |
| M3-04 | rank warmup 需至少 3 个有效候选配对；恒定分数相关未定义；比较 basis 变化重置有效窗口，既有 drift 告警保留 | statistical=False；阈值不是显著性检验或泛化保证 |
| M3-06 | 首次/周期实际校准，平均并列秩 Spearman 监控；低于阈值/未定义/anchor 失败或明确 proxy↑true↓触发 sticky degraded；降级后每候选校准、严格 true-best 附加约束和 M5 负反馈真实接通 | 保留原探索策略和准入规则；未自动替换为独立全保真优化器，也无真实外部任务质量认证 |
| M5-01 | 真实 proxy 改善但同口径 true 退步产生结构化 L1，并显式晋升为带 harmful_count 的 run-only L2 | 其他 rank/失败告警只记监控状态，不捏造配对退步经验；未补齐全框架所有阶段写入规则 |
| M5-02 | driver 授权的 run_feedback 可跨非祖先拓扑进入后续 draft；ContextPack 显式列 run_feedback_ids，仍受 negative/trust/levels/top_k/chars 限制 | 普通记忆的拓扑权限不因此扩大；预算不足时经验可不纳入，不能宣称所有后续 prompt 必然包含 |
| M5-03 | 负反馈须核对 current/baseline 四份真实 proxy/anchor 记录；可检索内容只有指标/方向/分数与来源引用；private 与原始文本不进入 ContextPack | 仍依赖 domain 如实提供实际内容与计量；hash 不是外部身份签名 |
| M5-04 | 校准负反馈限定当前 logical_run_id，导出/import/knowledge 回流均排除该 run-only 权限 | 未将局部 drift 教训自动推广为跨任务或跨 domain 知识 |
| M8-03 | dev 与 calibration 身份非空且不同，calibration 亦不能复用已启用 held-out 内容；pair 绑定候选/产物/请求/版本/seed/run；重复候选不能重复增加 rank 样本 | 真实数据内容与权限仍由 domain 校验，字段格式不能证明外部隔离 |
| M9-02 | layered dev_metric/dev_direction 与 gate metric/direction 可独立，回执复算两套规则；degraded veto 在付费 admission 前执行，通过 true-best 仍需原 gate | top_k 与新的二元规则插件组装未由本阶段补齐；校准不单独授予准入 |
| M9-03 | calibration 不占 admission call_budget，但全数使用物理预算；uncached incumbent anchor 失败时计已知费用、释放 candidate 未开始预扣并 veto | 不以失败/未测 baseline 猜测候选优势；未知付费调用仍无自动重试 |
| M9-04 | anchor 只接收 dev proxy 和 calibration；admission/final 的 raw/private 结果不能进入配对或 M5；bounded monitor 输入不注入整个配对历史 | calibration 是明确可反馈的开发数据，不等于终审；外部 benchmark 划分需领域协议授权 |
| X1-02 | v6 checkpoint 保存 proxy 调用/状态和 memory 权威引用；恢复重算 journal、反馈与固定内容身份，重复 replay 独立计费 | v1–v5 不自动升级；中途付费调用失败关闭，进程身份接管待 S7；实测 wallclock 可能使精确 replay 不匹配 |
| X1-05 | 记录 proxy_validity、composed_anchor、memory_proxy_receipt_binding、预算拒绝与最终监控状态；输入只含摘要与最近 5 条告警 | 仍无可订阅事件总线或完整 dashboard |

v65 显式组 `test_proxy_validity.py` / `test_composed_proxy.py` 覆盖周期切换、distinct metrics/directions、未测 incumbent 基线、反向代理、并列秩/低样本/常量、真实成本、预扣组拒绝、负反馈改变非祖先 draft、可见性/检索预算、禁止跨 run 导出，以及恢复/replay/篡改。完整重 hash 修改负反馈、复合引用和 checkpoint 仍须经 controller 原始回执复核，拒绝时新增付费调用为零且 journal 不变。测试执行结果与阶段门槛如下。

| 验证项 | 本次执行状态与证据 |
| --- | --- |
| Mac `make check` | 最终实现复核通过：1,319 portable、158 Linux deselected（22.37 秒）、37 tooling、11 axioms、4 个离线示例；包含负反馈/引用/检查点同时重 hash 的来源篡改拒绝回归；Linux deselected 不计通过 |
| 历史与 source 检查 | v65 的 9 项历史/source-only 检查通过；tooling 37 项通过；未生成 v65 运行证书 |
| 打包与导入快照 | 最终实现 `make build` 通过；`make verify-import` 校验 1,020 文件通过 |
| Linux v65 | [CI 40911722972](https://github.com/YixuanZhang99/mori-27/actions/runs/40911722972) 通过：1,477 pytest、35 检查、529.923 秒；exact SHA、artifact 摘要及新证书/journal/summary 已独立核实，历史未改动 |
| 提交与 main 更新 | 候选 `62a73631800bdf17eff0e5342fda0212a5303a50` 在同 SHA Linux 通过后，以非 force 快进 main，并重新读取远端确认 |

本轮落实 M3-06 的周期校准、异质指标有效性监控与负反馈子范围；C-02 继续隔离准入与成本，C-06 保留物理计量，C-07 扩展来源与恢复，C-08 保留 v1–v64 verifier 源码。S7 worktree/接管、S8 种群，以及 HITL、通用事件总线、外部知识与真实 campaign 继续按计划单列。

S6 成功证据已原样归档到 `m0/verifier/v65/LAST_RUN.json` 与 `m0/verifier/runs/v65.jsonl`，来源和 SHA-256 见 [v66 历史证据说明](../m0/verifier/v66/README.md#archived-v65-evidence-provenance)。该归档不认证 S7。

### S7 worktree 与进程接管：集成和验收记录

v66 显式执行 `test_composed_worktree_executor.py`、`test_process_identity_writer.py`、`test_composed_worktree_framework.py`、`test_composed_recovery.py`，保留 v65 全部命令、超时和真实历史。执行器组件与公开 Framework 中断接管分别验收；单独执行器通过不能代替实际主循环接管。本阶段已通过 Mac 和同 SHA Linux 验收；精确用法和限制见 [S7 指南](WORKTREE_RECOVERY_V66.md)。本提交完整 CI 必须通过后才推进 main；最终证据见该提交 CI 产物和交付记录。

本阶段保留 `composed-v6` 结构，通过新增 command-domain/executor manifest 区分原任务与新 executor。以下为已落盘实现的子范围；功能测试及最终平台验收按后表核实，不把某一子范围接通等同于整项抽象完成。

| 条款 ID | S7 实现子范围与证据 | 剩余范围或明确限制 |
| --- | --- | --- |
| A-02 | `recovery.register_worktree` 注册 command/git_worktree；配置能力、hierarchical 预算和 checkpoint 前置检查；coordinator/operation 非阻塞 lease；driver 掌握预扣、来源核对与 mutation | 仅内置 Greedy/LLMCycles、PromptOperator、InstructionSkill 的可恢复组合；不允许任意有副作用插件借恢复重执行 |
| M2-04 | `MeasuredCommandError` 保存完整真实计量与原始响应，已知失败/错绑先计费再停止；缺响应或缺 meter 保留未结预扣 | provider started 无正常文本 completion 不自动重试；未知费用不补零，不承诺外部服务支持幂等 |
| M3-02 | worktree dev、校准、admission/final 操作仍逐次使用 S5 原子预扣；恢复使用原物理账本及 worker 的持久执行时间；结算 wallclock 不低于 worker 实测，即使 producer 自报零/更短也不低扣 | 本地 planning/operator 的 wallclock 若未持久化则未知；不把 coordinator 离线等待作为费用，不猜测未测资源 |
| M7-01 | 配置选定 command executor；完整请求、候选、产物、内容/版本和安全 manifest 进入冻结 operation；身份漂移在启动或接管时拒绝 | 通用 ExecutorSpec role/frozen hypothesis/context projection 尚未作为独立模块组装；command 绑定不能替代该抽象全部语义 |
| M7-02 | 真实 Git worktree/命令/branch_ref 接入同一 Framework；Linux bubblewrap/seccomp 与当前 split 只读挂载；Darwin/Linux 稳定出生身份、启动授权和原进程接管 | Mac `none` 是可信本地模式，没有主机/网络/held-out 隔离；未认证其它容器、集群或 GPU 环境 |
| M7-03 | 规范终态、attempt、branch_ref、known cost/unknown reserve 和可选 rlimit、wall timeout 接入；已持久化结果接管不重新付费；提交前后中断保留 commit 计划 | 新配置路径仍串行；未统一旧 ExecutorPool/BatchScheduler，不宣称新路径并发部分失败或分布式 exactly-once |
| M8-02 | command 收到完整 EvalRequest 和 split 路径；fidelity/split 能力先验证；time_limit 真正约束进程；显式支持的 resume_from 为不可变 Git commit | budget_token/seed 的实验含义由受信任评估器消费并在回执绑定；不以传参证明任意外部程序已遵守预算或实验语义 |
| M8-03 | 可执行文件、受保护脚本、真实 split 内容及 evaluator_version 冻结；改名不制造独立数据；原始响应 hash/完整 producer binding 恢复重核 | 摘要不是外部签名；评估器本身仍须可信；跨平台运行中进程迁移不在范围内 |
| X1-01 | 每次 worktree evidence 的真实 commit 写入 branch_ref，driver 投影到 frontier code_ref；原始 Git object 快照不执行 clean filters/hooks，内部请求/响应不进入 artifact commit | checkpoint 顶层仍标 configured_artifacts，真实执行来源另见 manifest/evidence；未生成伪造全局 GitState，也未统一所有域的代码管理接口 |
| X1-02 | `ContinuationStore` 从 checkpoint 边界严格消费持久事件；pending 文件 fsync→持久 boundary→原子替换指针，恢复仅在内容/周期匹配最新边界时前滚；provider 文本/用量/状态 completion 缓存；完成恢复零新调用；进程运行中或完成后的接管按原 operation 身份核对 | 只有 started 或启动意图无稳定身份时失败关闭；磁盘丢写/断电不保证；独立 replay 真计费，执行来源/墙钟不一致仍可判失败 |
| X1-03 | 保护文件、请求、安全策略和数据运行前后校验；Linux 当前 split 单独挂载且拒绝数据放在候选基础仓库内；安全策略改写只清理身份绑定的进程 | `sandbox=none` 没有 OS 保护，只是完整性检查；不认证评估器自行把私有内容写入其它输出的行为 |
| X1-04 | Linux 回归实际尝试读取其他 split 和主机秘密，验证执行边界；原 canary/来源拦截继续保持 | 未扩展语义泄漏检测、所有输出扫描或通用 URL 防火墙 |
| X1-05 | 新增 worktree launch/process/commit/evidence/rejection 和 provider started/completed、operation measurement 事件；持久 suffix 不允许静默删除或改写后续接管 | 仍无可订阅事件总线和完整 dashboard 协议 |

公开 Framework 回归覆盖 dev/admission/final_audit 与 calibration 的运行中和已完成未结算 SIGKILL、第二协调器接管中再次崩溃、StateApplier 实际变更与 journal 前后边界、持久后缀不匹配零新增付费调用，以及 checkpoint pending 写完但 boundary 未写、boundary 已持久化但指针未替换两种窗口。executor 回归另覆盖命令安全规格/身份/结果/commit 的篡改、启动意图无可验证进程时拒绝替代、Git filters/hooks 隔离和受保护输入。Linux 两项真实 bubblewrap/seccomp 与跨 split 文件权限测试必须在 CI 执行，Mac 结果不替代其证据。

| 验证项 | 执行状态与阶段门槛 |
| --- | --- |
| Mac `make check` | 最终实现通过：1,392 portable、160 Linux deselected（104.22 秒）、40 tooling、11 axioms、4 个离线示例；包含检查点双提交间隙及 producer 墙钟低报回归，Linux deselected 不计通过 |
| 工具与历史/source 检查 | 40 tooling、9 历史/source-only 检查通过；v65 原始证据 SHA-256 受保护；未生成 v66 运行证书 |
| 打包与导入快照 | `make build` 通过；`make verify-import` 校验 1,020 文件通过 |
| Linux v66 | [CI 40992561406](https://github.com/YixuanZhang99/mori-27/actions/runs/40992561406) 通过：1,552 pytest、36 检查、815.844 秒；exact SHA、ZIP 摘要及新 summary/certificate/journal 已核实，历史未改动 |
| 提交与 main 更新 | 候选 `fb8a0f7e703c2300b95149536837cd2569e3f1e7` 在同 SHA Linux 成功核验后，非 force 快进 main，重新读取远端确认 |

本阶段对 C-07 增加公开入口进程接管，同时保留未知付费操作失败关闭；C-08 保留 v1–v65 原 verifier 源码。M7-01 的通用执行角色/冻结假设、M7-03 新路径并发、S8 种群、X2 HITL、事件订阅和真实外部 campaign 继续单列。

S7 成功证据已原样归档到 `m0/verifier/v66/LAST_RUN.json` 与 `m0/verifier/runs/v66.jsonl`；来源和摘要见 [v67 历史证据说明](../m0/verifier/v67/README.md#archived-v66-evidence-provenance)。这不代替 S8 验收。

### S8 种群与双亲 crossover：实现记录与验收门槛

新增 `frontier/population.py`、`composition/population.py`、`population_runtime.py` 与命名配置 `population_prompt`，仍通过同一 Framework 入口执行。`composed-v6` 保持不变；frontier checkpoint 自带 population 配置和状态，不把 tree 检查点伪装成种群。配置、机制与边界见 [S8 指南](POPULATION_RUNTIME_V67.md)。下表记录实际子范围，平台验收以随后真实执行记录为准。

| 条款 ID | S8 实现子范围与证据 | 剩余范围或明确限制 |
| --- | --- | --- |
| A-02、M1-04 | driver 重新计算 detached selection view 的采样 receipt；仅原 M9 decision/receipt 经 `POPULATION_FINALIZE` 改成员和 protected incumbent；无资格父代/伪造 mutation 拒绝 | 不把 policy 的整份状态覆盖到权威 frontier；任意外部有副作用策略不由本阶段授权 |
| M1-02 | PopulationPolicy 前两根 draft，之后真实委托 `sample(2)`；四种 selection 实际改变父序列；固定 seed 和接受的 receipt 决定 RNG 推进 | 无 LLM 人口管理或自适应最优选择器质量认证；retention 只支持 elite |
| M2-01、M2-03 | CrossoverOperator 走同一 OperatorRequest，接收两个不同父代、公开 dev evidence、真实 ContextPack/预算；核对父代 artifact hash，输出两个有序骨架父边 | 普通文本交叉不提供代码签名/类型/行为保持证明；未补齐所有六类算子或 comparative-reflect 算法效果 |
| M2-02 | 配置注册 `crossover` 与 population policy，执行域仍可替换 native/inprocess 或 command/worktree | 内置 population policy 明确要求 `[draft,crossover]` 顺序，不宣称任意算子集合都与该策略兼容 |
| M2-04 | 生成/评估失败保存已知成本，失败或无效 dev 不成为成员/父代；未计量费用继续失败关闭 | 不把 M9 拒绝等同于执行失败；未知外部费用仍不自动重试 |
| M3-02、M3-05 | 真实全局/方向/候选成本仍只扣一次；有序双亲以第 1 父根方向归属，depth=max(双亲深度)+1；operator 收到已预扣预算视图 | 纯本地 PopulationPolicy 不给 crossover/Prompt 补造 GPU/USD meter；额外单位缺覆盖前置拒绝 |
| M3-03、M8-03 | population+hierarchical 前置要求全部 dev rung 规范化为同一完整 EvalRequest，防止 elite 混比；三层评估和 calibration 继续独立身份 | 种群不支持变化 fidelity/seed/time_limit 排名；tree 的变化 rung 能力保持，未认证异质种群多保真策略 |
| M4-01、M4-02 | 同一配置可选择 ResearchFrontier 或 PopulationFrontier；一份完整 DAG 与有界成员视图；容量含 M9 incumbent，eviction 保留节点/两亲骨架/后代/证据，不级联删谱系 | 未统一 island/MAP-Elites 成员策略；不是额外平行 archive 或通用生存算法集合 |
| M4-03、M5-02 | 两亲骨架用于原有父/祖先权限，真实公开 evidence 和 scoped memory 到达 crossover；淘汰不删除祖先记忆；S6 run-only 负反馈仍可影响后续候选 | 普通 memory 继续受 trust/level/negative/长度限制；引用边不自动扩大检索，也无通用 ExecutorSpec projection |
| M4-04 | greedy/uniform/tournament/softmax；receipt 绑定配置、eligible、score/attempt、k、strategy、RNG 和最后选择；权威 eligible 含预算资格，driver 复算后才推进 RNG | 不把抽样多样性称为 novelty/MAP-Elites 保留；M9 拒绝但有效 dev 可作探索父代，不代表准入晋升 |
| M5-03、M9-04 | 两亲只能使用公开 dev 字段；合成组合用例证明 private、raw anchor、held-out 不经 crossover 回流，run-only 负反馈有原四回执来源 | 没有跨 run 自动推广 proxy 负反馈或语义泄漏的通用保证 |
| M9-01～03 | 种群 retention 与 gate_selected 分离；M9 selected 受容量内保护；dev-best/gate/final、调用硬顶和物理预算保持；失效 proxy 在 gate 前 veto | top_k/HITL 仍未接入；种群成员不是准入集合 |
| X1-02 | checkpoint 完整 Proposal/Evidence 对原 composed_evidence；从 StateMutation+M9 重建节点/成员/有序双亲，每次抽样按当时预算池重算 receipt/父代/RNG；合法预算拒绝终态可恢复；周期恢复/独立 inprocess replay 与 worktree 三窗口接管保持原调用/RNG | serial 仍必需；worktree 独立 replay 的真实执行来源/墙钟可能不匹配，未知付费操作和断电限制沿用 S7 |
| X1-05 | 持久化 population_sample、sampling_committed、finalized/pruned 等记录，成员变更和随机状态可审查 | 仍不是可订阅事件总线，未完成独立 dashboard |

v67 三文件显式组为 `test_population_frontier.py`、`test_population_components.py`、`test_composed_population.py`，保留全部 v66 命令和超时。公开组合用例同时启用种群、真实 worktree、proxy 校准、记忆、M9 和三层物理预算：4 dev + 4 calibration + 3 gate + 1 final、4 次离线 provider 调用、2 次 committed draw，真实本地调用数 12、候选数 4、明示合成 token 104。第 3 候选 proxy↑true↓被否决，其来源受限的负反馈改变第 4 次 crossover 产物并再次通过 gate；完成 resume 不产生新调用。该用例验证机制，不代表外部模型或 benchmark 成绩。恢复回归还覆盖非 protected 节点状态+成员重算、checkpoint/journal RNG 双改和有序父代在 node/proposal 双改，均要求零新增付费调用且原 journal 字节不变。

| 验证项 | 执行状态与阶段门槛 |
| --- | --- |
| Mac `make check` | 最终实现通过：1,472 portable、160 Linux deselected（135.73 秒）、11 axioms、4 个离线示例；全量时 42 tooling，新增真实归档保护后 43 tooling 单独复核通过；Linux deselected 不计通过 |
| 工具与 source 检查 | v67 接线 43 tooling、9 历史/source-only 检查通过；v66 真实成功证据原字节归档并以 SHA-256 保护，不生成 v67 初始证书 |
| 打包与导入快照 | 最终实现 `make build` 通过；`make verify-import` 校验 1,020 文件通过 |
| Linux v67 | [CI 40994318799](https://github.com/YixuanZhang99/mori-27/actions/runs/40994318799) 通过：1,632 pytest、37 检查、868.971 秒；exact SHA、ZIP 摘要及新 summary/certificate/journal 已核实，历史未改动 |
| 提交与 main 更新 | `49be71ec079f1412a4a8e74086064c4db121c363` 已在同 SHA Linux 验收通过后非 force 推进 main；本地 handoff 和 CI 产物保留独立复核记录 |

S8 接通配置种群、压力抽样和双亲文本交叉的具体闭环；novelty/MAP-Elites、代码签名、通用执行角色、配置并行池、HITL、事件订阅、网络知识和真实外部 campaign 保持明确未完成或后置。原始抽象文档及基线对照不改写为事后“全部完成”。


S8 成功证据已原样归档到 `m0/verifier/v67/LAST_RUN.json` 与 `m0/verifier/runs/v67.jsonl`；来源和摘要见 [v68 历史证据说明](../m0/verifier/v68/README.md#archived-v67-evidence-provenance)。这不代替 S9 验收。

### S9 MLE-Bench Lite 配置评估与同预算试跑：实现记录与验收门槛

本阶段将 S6/S8 能力接到真实任务数据协议，新增 `zoo.mle_bench_lite.composed_agent` 与显式子集 `pilot`；旧 `governed_agent` 的 M0 路径保留。机制验收与外部模型试跑分别记录。精确接口、任务输入范围及评分边界见 [S9 指南](MLE_COMPOSED_V68.md)。

| 条款 ID | S9 接入子范围与验收要求 | 剩余范围或明确限制 |
| --- | --- | --- |
| A-03、A-04、M8-01～04 | 三个公开 CSV 任务经同一配置 Framework/domain 产生规范 Evidence；训练/dev/calibration/admission/final 的实际内容身份绑定；每候选固定生成程序与预测后再分别评分 | 不是完整 22 题或全部任务模态；leaf 图像和 nomad 几何数据未接入；旧 M0 benchmark 入口不自动升级 |
| M3-02、M3-03、M3-06 | full 真实启用层级预算、周期 anchor、秩相关；分类 accuracy 对负 log loss、回归绝对对数误差对负 RMSLE；每个附加操作计入该组资源消耗 | 阈值是预设规则，不宣称显著性；无真实价格表时不推导美元成本，未知费用不补零 |
| M4-01～04、M2-03 | full 的种群抽样与双亲 crossover 进入实际任务候选生成；baseline 使用同一任务实现的 greedy 搜索 | 两组只测整个组合增益，不能直接归因单个模块；elite 不等于 novelty/MAP-Elites |
| M5-02、M5-03、M9-04 | 独立公开开发 calibration 触发的有来源负反馈可以影响后续候选；admission/final 与外部官方 private 分数不反馈 | 实验内反思不代表跨任务知识迁移；fixture 中的确定性负反馈链路不代表真实模型必然出现同样行为 |
| M7-01～03、M8-03 | Linux 使用受限执行环境运行生成程序；受信评分器独占验证标签；冻结后的固定预测供各 split 评分 | Mac 可移植检查不认证 Linux 沙箱；不得由任务执行成功推定未知付费调用可安全重试 |
| X1-01～03、M9-01～03 | pilot 先冻结完整任务/种子/组/预算/model spec，所有组提交冻结后官方评分；独立 token 回执和实际模型复核；失败矩阵保留 | 子集结果明确 `subset_only`，不触发完整 22 题比较/host parity；正式 runner 的完整矩阵要求不放松 |

v68 显式执行 `test_mle_composed.py`、`test_mle_provider.py` 与 `test_mle_pilot.py`，保留全部 v67 命令和超时、完整 pytest、真实 Linux 安全/恢复组与历史证据。新组必须证明原始数据与评估结果确实驱动候选、校准和回流，不能只检查 profile 字段存在。

| 验证项 | 执行状态与阶段门槛 |
| --- | --- |
| Mac `make check` | 最终实现通过：1,577 portable、163 Linux deselected（176.69 秒）、11 axioms、4 个离线示例和 52 tooling；Linux deselected 不计通过 |
| 工具与历史 | 最终 52 tooling 通过；v68 保留全部 v67 命令与超时，v67 原始证据以 SHA-256 保护；不生成 v68 初始证书 |
| 官方 CPU 环境冒烟 | Mac 独立环境安装同一 hash lock，真实官方三任务 registry/preparer/protected snapshot/grade_csv 合成测试通过；Linux 由独立 `mle-cloud-runtime` CI job 验证，不计真实 benchmark 分数 |
| 打包与导入快照 | `make build` 通过；`make verify-import` 核对原始导入快照 1,020 文件通过 |
| Linux v68 | 同一候选提交的全量 CI 必须通过，证书包含 S9 组及全部 38 检查；实际 pytest 数以同 SHA artifact 为准 |
| 提交与 main 更新 | 候选提交→核对同 SHA 新 summary/certificate/journal→非 force 推进 main；不为补自引用 SHA 制造未验收提交 |
| 真实外部试跑 | 未执行；数据、规则授权、模型凭据和资源预算须先完整，实际结果与 fixture 验收分开归档 |

S9 接入真实任务协议不改变其余条款边界：通用执行角色、配置并行池、HITL、事件订阅、外部网络知识、更多模态与全量 benchmark 效果仍须独立实现和验收。原始统一抽象和历史阶段证据保持不变。
