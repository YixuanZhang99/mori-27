# A7 深模块审计：resident governance at bedc5b3

对象：干净提交 `bedc5b31fe737dfd207fa8466f68fecb58c5c294` 的常驻治理新增模块及其直接接缝。只读代码/调用点/测试结构与 AST 清点；未更改源码、未执行完整测试或付费请求。原始报告先保存在本地证据目录；本文为同一只读审计的仓库归档。这不是新的代码正确性审查或强制重审要求。

使用的设计依据：`autoresearch-fw/RUBRIC.md` A7（每模块接口数/内部机制数 ≤1:3，无透传型浅模块）及 深模块设计审查方法（Interface、Depth、Locality）。后者将 **Interface** 定义为调用者必须知道的全部事实，包括顺序、约束、错误和配置；**Depth** 是这些学习成本所换取的行为能力，不是实现代码行数。本文分别报告质性 Depth 和字面比例，避免用一种替代另一种。

**审计结论：质性上“有明显 Depth，局部 Locality 需要改善”；A7 字面比例目前不能认证 PASS。** 在下文公开的保守计数规则下，多数内部类的可见入口/独立机制组比值不达 1:3；该结果是可复核的代理指标，不等于证明整体架构浅，也不能包装成正式 A7 PASS。RUBRIC 未预先定义模块粒度和机制计数单位，因此正式字面验收为 **UNCERTAIN / 未关闭**，不是自动豁免。整个仓库 A7 更不能由本次仅治理新增范围的审计关闭。

远端状态更正：协调者本次已确认 push 权限为 true，bedc5b3 已成功推送；当前尚无该 SHA hosted CI 成功证据。早前 readiness 报告引用的 push=false 是旧快照，不应再当作当前阻碍。此变化不影响本次架构判断。

## 1. Module 粒度及计数方法

本次先按实际独立调用接缝而非文件大小划定 Module：不可变配置、冻结计划、受限存储视图、能力校验、物理预算及其私有投影、provider 证据、control 终态审计、运行编排、continuation/replay、注册构造、CNY authority。

- **入口数 I**：列出的构造入口、公开可调用方法、可读属性，每项算 1；实际跨文件使用的下划线函数也算入口。一个方法有多个参数不乘算；但参数/状态顺序另列为 Interface 负担。dataclass 自动生成的直接构造器没有作为受支持 factory 列入，若将其也视为支持面，应相应加 1，而不能降低分母。
- **机制组数 M**：下节显式编号的独立行为职责。把同一规则的多种输入校验或十个 if 语句归为一个机制，不按断言、测试案例、代码行数膨胀。该粒度是本审计声明的人工分组规则，不是仓库已批准的计数规范。
- **比例**：展示 I/M，A7 要求 ≤1/3。该简化量遗漏了 Interface 的语义学习成本，属于**代理值**。不因某行只有一个函数就推定它是 deep；也不因六个小辅助函数就要求无意义地添加十八个机制。
- **禁止的捷径**：把全部文件合成一个名为 Framework 的 Module 然后只数三个入口；或者把每个验证条件算一项机制，都能人为“过关”，本文不这样计算。

AST 读取定位如下（行号绑定 bedc5b3）：`GovernanceConfig` 四入口；`ControlPlan` 三；`LaneStoreView` 六；`ControlProtection` 九；`GovernedInvocation` 六；provider evidence 三；terminal audit 一。实际属性/类型/顺序仍需以下说明。

## 2. 新增 Module：具体 Interface / Implementation 清单

| Module / 代码定位 | Interface（I） | 隐藏的独立机制组（M） | I/M 代理结果 | 质性判断 |
| --- | --- | --- | --- | --- |
| `contracts.py:74` GovernanceConfig | `__init__`、`controls`、`from_dict`、`to_dict`（4） | ①有限 JSON/版本/精确字段；②schedule/seed；③工厂规格与固定 dev request；④物理维度/阶段最低费用；⑤规范不可变存储；⑥序列化往返（6） | 4/6 >1/3 | 有效值对象。四入口含两种构造/一个读视图，薄但不是透传模块。调用者仍需知道 controls 的七个字段及 hard-unit 语义 |
| `governance.py:22` ControlPlan | `freeze`、`plan_ref`、`to_dict`（3） | ①按 max_generations 校验 schedule；②单位集合一致；③确定 slot/seed 派生；④task/context/plan 内容身份；⑤冻结规范表示与 detached 读取（5） | 3/5 >1/3 | 局部职责清晰，删除会把身份与冻结规则散回 runtime/budget。输入配置已验证的规则不重复算新机制 |
| `governance.py:71` LaneStoreView | 构造、lane、slot_id、component、append、read（6） | ①lane/slot 合法性；②authority kind 访问拒绝；③按 lane/slot/module 封装写入；④精确过滤读取；⑤JSON detached 值、无 path 的受限视图（5） | 6/5 >1/3 | 质性 **deep Adapter**：保留 append/read 使用方式却实际执行隔离。三个只读属性增加代理入口数，但不能据此判定它只是代理转发。非恶意 Python sandbox |
| `governance.py:130` capability validator | `validate_factory_governance`（1） | ①各角色精确 schema；②fresh/state-independent 声明；③applied sampling 合约；④唯一可计量 token hard bound 与 reservation 匹配；⑤拒绝未接通 external currency（5） | 1/5 ≤1/3 | 低入口、可直接测试、明确失败的深值校验 Module；不以能力声明证明供应商统计真实性 |
| `budget_governance.py:16` ControlProtection | 构造、validate_plan、protect、protected、slot、bind、convert、cancel、audit（9） | ①plan/config/作用域语义验证；②保护总容量；③剩余义务投影；④main/account 归属；⑤control phase/candidate/request 约束；⑥义务转为 operation；⑦失败取消状态机；⑧七账户/slot/保护状态审计（8） | 9/8 >1/3 | **作为独立公开 Module 偏浅且 Interface 宽；作为 HierarchicalBudget 的私有 Implementation 合理。** 不拥有第二把锁或第二本 journal，是保留单一权威的重要选择 |
| `budget_contracts.py:14` 共用值规则 | `_canonical/_hash/_text/_quantity/_basket/_request`，两常量（6 个函数入口，常量另记） | ①规范编码/内容身份；②文本标识；③finite count/物理 basket；④仅 dev fidelity 请求（4） | 6/4 >1/3 | 小型纯规则库，不是适配层；消除真实依赖环并去重有收益。不能为了 A7 扩写或包一层对象。`_canonical` 的跨文件导入还需区分遗留导出与真实调用 |
| `provider_evidence.py:13` provider receipt validation | invocation_records、evidence_reference、audit_provider_receipts（3） | ①start/completed 配对；②精确字段/终态/成本；③每 intent ordinal；④request+invocation hash；⑤run/lane/slot/fingerprint/adapter cross-link；⑥settlement evidence digest；⑦provider token 不高于实际结算（7） | 3/7 >1/3 | 行为密度高，质性 deep；三入口分别供解析、结算封口、整体审计。不是三个重复的转发入口 |
| `governance_audit.py:58` terminal audit | audit_terminals（1） | ①plan 与预算；②run 派生 candidate；③checkpoint/main stop 顺序；④slot schedule/初始与 drain；⑤唯一/有序 start-terminal；⑥operator identity/lineage/failure；⑦measurement-settlement 实际成本；⑧evaluation request/domain binding；⑨证据失败/成功状态；⑩与物理 slot 状态一致（10） | 1/10 ≤1/3 | 清晰的只读复算 Module，Depth 强；不是只看缓存布尔值。其 runtime/session 依赖和输入字典 schema 仍是 Interface 成本 |
| `governed.py:27` GovernedInvocation | 构造、meter、check_integrity、operator、due、audit（6）；plan/main_binding/sessions 是被使用的状态面 | ①main/controls capability+可比性预检；②plan/fresh session 组装；③每调用绑定/ordinal；④累计调用 envelope；⑤实际 bound/drift 检测；⑥终态→结算/unknown 分流；⑦control 身份/上下文/失败终态；⑧resident schedule/drain；⑨live audit 聚合（9） | 6/9 >1/3，未把三个状态属性计入 I；加上后更高 | 提供大量真实行为，非透传。**Depth 中等，Locality 风险最大**：名称像统一 invocation，但 planning/evaluation 生命周期仍分散在 HierarchicalRuntime/ContinuationStore |

这些表格没有把 `digest()` 单列成新治理抽象：它是内容身份的 Implementation helper，单独函数的“1/若干行”没有 A7 意义。同理 `_terminals()` 是内部别名，不是新 Module。

## 3. 已有 Module 被扩展后的实际接缝

### 3.1 HierarchicalBudget 与 ControlProtection 应作为一个权威 Module 看待

`budget.py:287–327` 的 protect/reserve-control/cancel/audit 入口不是简单转发：它们持锁，检查既有历史/幂等条件，派生 control operation identity，或从 journal 重建并验证 head。`reserve_operation` 在同一锁内验证转换后的 admission state，reducer 执行同一转换；全局/方向/候选、固定 main allocation、七账户是同一 settlement 的投影。

新增外部行为入口为 protect_controls、reserve_control_operation、cancel_control_slot、audit_governance、invalidate_protection、main_state/main_account_summary，既有 reserve/settle/checkpoint 也新增治理语义。调用者必须知道“先保护→预留→开始→终态证据→实际结算→完整性停止/取消”的顺序；不能只数方法而忽略这部分 Interface。

`ControlProtection` 反向依赖 owner 的 `_decimal/_numeric/_totals/options/units` 五项，且修改 owner 管理的 state 字典。**它是私有 reducer/projection 的分文件组织，不是可独立替换的 Adapter。** 删除该文件不会消除规则，只会把约 200 行规则移回 budget；其存在不是假抽象，但不宜再公开为第三方可替换协议。

`budget_contracts.py` 提取共享纯值规则后消除了 budget↔protection 的真实依赖环，具有 Locality 收益。没有理由为“类更统一”把它合并回去再制造循环。

### 3.2 ContinuationStore / RecordedOutcomeStore 是有真实差异的 Seam

`recovery.py:53` 的 ContinuationStore 有 9 个可见定义入口（含构造与 external）；其 Implementation 隐藏 prefix/suffix 游标、诊断/外部事件策略、逐记录一致性、durable flush、measurement、provider terminal adoption、nested provider adoption、native domain state 恢复和 unknown fail-closed。

`RecordedOutcomeStore` 有三个定义入口（构造、provider_call、evaluation_call），但继承了完整父类 Interface。**不能用“只覆写两个方法”制造超低比例。** 它的实际差异是 transcript-only 模式禁止 live dispatch，且任何缺失/额外证据失败。与可续执行的 ContinuationStore 是真实的两种 Adapter；小覆写不是无价值透传。删去这些覆写会丢掉零新调用保证，故通过 deletion test。

结构风险是一个 store 同时承担 generic append/read 与模型/评估恢复协议；调用方需知道 cursor/restoring、checkpoint boundary、provider/domain restore 能力。当前复杂性确有业务来源，建议先保持一个恢复权威，不为拆文件新增抽象或第二套事件格式。

### 3.3 MeteredProvider 的表面很小，内部 Interface 却是隐式状态协议

`provider.py:14` 保留 callable 语义、raw_provider、usage_total、known_usage_total；其未公开的协作面还包括 `_governed_store`、admission_guard、governance_measurement、invocation_binding、invocation_ordinal、current_invocation_binding、last_usage 等属性。`GovernedInvocation.meter` 安装/清理这些属性，`MeteredProvider` 调用它们，`ContinuationStore` 读取/恢复它们。

这不是无行为 wrapper：它集中未知用量污染、每次真实成本累加、guard、ordinal 和 durable route，删除后会把计量散到所有调用者。但当前 **跨三个 Module 的动态属性协议** 不在类型层表达；新增一种调用路径容易漏掉计量/完整性检查，是最值得降低 Interface 成本的区域。

### 3.4 Registry.build_control 隐藏真实构造和隔离复杂性

`registry.py:147` 新增一个主入口，隐藏声明预检、slot 精确比对、fresh scope/workdir、受限 store、provider wrapping、runtime binding 与 registration 一致、domain request validation、raw identity reuse 检查。`_construct` 还检测 factory 篡改 scope/governance。

有实在的 Leverage：原生和 worktree 两个 Adapter 使用同一注册入口，框架使用者无需复制 live adapter。返回字典的固定键与 provider/domain/checkpoint 契约仍是 Interface；对受信任 factory 隐藏全局状态不作保证。该接缝不是仅有一个实现的假想插件点。

### 3.5 CNY authority 是独立任务 Adapter，不应为了“统一”搬进 core

`zoo/mle_bench_lite/cny_budget.py` 的六个新增入口为 enable_governance、quote_call、protect_run、admit_call、cancel_control、audit_run；沿用 reserve/settle/snapshot。它隐藏 SQLite transaction、整条链 reducer、显式迁移锚点、冻结价格计算、跨 run 义务、单 pending、原子义务转换、真实超额保留和 idempotent adoption。

这是真实 monetary authority 的 Depth，且使用了现有账本而不是平行账本。但其 provider bridge 未接通；**接口已存在不能证明整体 paid workflow 的 Leverage 已实测**。后续 bridge 应调用此 Seam，保留货币策略在任务 Adapter；不要把两个 authority 隐藏在一个宣称分布式原子的总账类里。

## 4. 透传检查与 Locality 风险

| 位置 | deletion test / 影响 | 建议与优先级 |
| --- | --- | --- |
| `governed.py:150 _terminals()` | 只有 import+调用 audit_terminals；删去后不减少规则，只消除私有重复调用拼写 | 微小内部 convenience，不单独记 shallow Module，也不值得打断验收去删除 |
| `budget.py:686 main_account_summary()` | 直接返回 main_state。与旧 account_summary 保持相同调用习惯，但仅新增别名 | **低优先 shallow forwarding surface**。后续调用点收敛到一个“main view”名称可减少 Interface；不要为了这个别名声明架构失败 |
| `provider_evidence.py:49 evidence_reference()` | 表面一行，但明确“整组有序 receipt 的规范摘要”政策；被 settlement 用来 seal proof | 保留；删除会让结算方知道分组/摘要语义，降低 Locality |
| `RecordedOutcomeStore.provider_call/evaluation_call` | 替换 invoke 为 forbidden 并验证 transcript 尚未耗尽 | 保留；不是无语义 super 转发，删除会失去无 live dispatch 保证 |
| `governed.py:27` 与 `hierarchical_runtime.py:162/197` | GovernedInvocation 直接知道 runtime 的 16 个属性/方法：`assembly,budget,cfg,manifest,parts,registry,stamp,store,task,workdir,_logical_run_id,_save,_check_provider_floor,_settle_physical,_unresolved_physical,_evaluate_physical`。planning/evaluation 调用者仍须自己配对 meter、settle、check_integrity | **首要深化候选**：减少调用方必须记住的生命周期组合。应在未来真实改动时把 measured invocation 顺序收敛在同一私有 Module；先设计更窄的输入/结果，再替换旧路径，别加一层仍透传 runtime 的 facade |
| `provider.py:41`、`governed.py:66`、`recovery.py:146` | 动态属性连接三个生命周期实现，状态何时存在依赖外部顺序 | **中优先**：明确一个内部 invocation context 的拥有者和生命周期；使 token/binding/outcome 的变更集中。避免把所有属性原样放进 dataclass 就声称已 deepened；必须让调用方少记顺序 |
| `provider_evidence.py:55` | 审计直接调用 budget._rebuild 并读取内部 operations 字典 | **中优先**：未来需要更多独立审计时，可输出一次 immutable authority evidence snapshot；不是现在为一个调用点加空泛公开接口。审计与 authority 保持可独立复算，避免用缓存最终布尔值代替证据 |
| `governed.py:158` / `audit` / `evidence_reference` | 每个 slot 的 due/audit 与每次 settlement 可重扫 journal；正确性简单，但长 run 成本不会被小 Interface 自动消除 | 记录为性能特征/观察项。本次未基准测量，不报告性能 bug。先测实际长 run 再考虑一次快照多投影；不新增第二可变事实源 |

没有发现一个新增顶层模块仅靠无语义转发维持存在。主要风险是 **职责分散和隐式 Interface**，不是文件过多或代码不够长。

## 5. 测试 Seam 及可维护性

- `test_governed_runtime.py`、`test_governed_native_recovery.py`、`test_governed_worktree.py` 从公共 Framework 验证真实可见行为；native 和 worktree 是两个实际 Adapter，使该 Seam 不只是设想。
- budget、config、session 测试通过它们自己的入口验证规则，支持分别理解/验证 Implementation。由一个 Interface 能触发预算拒绝、费用保留、失败槽、恢复和 audit，是 Depth 的正面证据。
- 故障注入 monkeypatch `_write` 是为了准确定位 durable 窗口，不因此判定模块形状错误。`test_governed_final_review.py:86` 修改 `registry._entries` 构造 paid-domain fixture 则可将来改为公开 register 路径，减少对内部布局的测试耦合；非当前阻塞。
- 本次不以测试文件数或通过数作为机制数，也不通过新增镜像实现测试提高比例。现有 2,000 全量通过证据证明回归状态，**不能证明 A7 的 1:3**。

## 6. 诚实的 A7 判定及最小后续动作

| 判定维度 | 结果 |
| --- | --- |
| 新增模块是否主要是透传层 | **否**。主要 Module 通过 deletion test，承担真实治理/恢复/审计规则；有两个小别名，不构成独立架构层 |
| 是否在既有 Framework/预算 Interface 后获得显著 Leverage | **是，限定范围质性通过**。同入口、单物理 authority、两执行 Adapter、记录结果回放；未新增第二 Framework 或平行物理账本 |
| Locality 是否理想 | **否，需改善**。runtime 16 项依赖、meter/settle/check 分散、provider 动态属性协议是具体欠账 |
| 按本文声明的入口/机制组代理计数是否每个都 ≤1:3 | **否**。能力校验和 terminal audit 达线，其余若按独立内部类/值模块计多数未达；不通过重新划分模块或细拆 if 来修饰结果 |
| RUBRIC A7 的正式字面条件是否已证明 | **UNCERTAIN / 未关闭**。仓库尚无预先固定的模块粒度和机制计数法，本次仅覆盖治理新增而非全仓；不能宣称 PASS，也不能把代理不达线直接扩大成所有模块不合格 |
| 是否要求现在改源码或再加代码审查才能保留工程候选 | **否**。本报告是读范围/深度盘点；没有新增正确性阻断。保持正在验收的源码冻结，架构欠账明确列入后续即可 |

最小后续次序：

1. 固定 A7 的 Module 列表与计数规则，保存本报告作为初始证据，避免执行后随结果调整单位。可先由维护者按现有 RUBRIC 人工程序裁决“私有 helper 属于同一 Module”如何计数；这不是放宽阈值。
2. 下一次需要扩展 paid provider bridge 或调用类型时，优先深化 invocation 的生命周期拥有关系；目标是调用方不再手动配对 meter/settle/check，而不是增加更多 handler/facade。用已有 main/control、native/worktree 的行为测试替换旧接缝，不保留两套并行路径。
3. 为全仓 A7 补上其余 M1–M9/X1 的同口径 inventory；只在真实 shallow Module 上整改。此项是可执行工程审计，不依赖付费 benchmark，但也不应把“写一份表”自动当成所有比例达标。
4. 在 RC/交接声明中分别列质性结论、代理计数、正式 A7 状态；hosted CI 取得后更新其独立证据状态，不能用 CI 的绿色关闭深模块评审。

最终可使用的结论是：“bedc5b3 治理新增具有实际 Depth，主要机制隐藏在已有运行和账务 Interface 后；内部分工存在明确 Locality 改进点。A7 全仓及字面 1:3 验收尚未关闭。”
