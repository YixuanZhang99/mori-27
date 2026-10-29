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

### S3 作用域经验与本地知识回流：实现记录，阶段验收待完成

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
| Linux v62 | pending：待同一 S3 提交的新证书、journal 与 summary，v61 历史成功不替代本阶段结果 |
| 提交与 main 更新 | pending：待阶段候选 SHA 与对应 CI URL |

S3 不关闭 S1 尚未实现的种群/采样压力/worktree/HITL/事件总线条款，也未实现 S4 三层准入或 S5 分层预算。C-04 已在本地知识配置路径落实 research/benchmark 的实际行为差异；C-07 升级作用域检查点并保留付费 replay 语义；C-08 继续保持旧 verifier 源码及历史失败证据。
