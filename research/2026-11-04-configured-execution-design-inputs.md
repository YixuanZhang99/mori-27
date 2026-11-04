# 下一阶段执行接通：基于9afc1d2的只读调查

这是后续设计输入，未实现并行、未关闭M7-01/M7-03，不改变原目标或验收条件。

## 原要求与已存在的机制

统一抽象M7要求职能role、冻结/自由hypothesis和ContextPack投影成为实际执行输入。`core/executor/types.py::ExecutorSpec`已有role、hypothesis_frozen、hypothesis、context_projection、execution_ref；不应再造第二个同名概念。`executor/service.py::GitWorktreeExecutor.execute`检查冻结假设，并保留artifact/worktree与执行状态。该旧路径的存在不等于composition已经接通。

`executor/pool.py::ExecutorPool`已提供有界线程、排队/运行/终裁状态、输入顺序回调和结束前drain。`orchestration.py::BatchScheduler`已提供冻结cohort、全部预留后启动、结算后串行终裁与恢复记录。但是它消费旧AllocationIntent/ledger接口；composition使用带物理维度、方向/候选约束和常驻对照保护的HierarchicalBudget。不能用薄包装把两本authority并行维护。

当前`composition/runtime.py::_run`明确拒绝batch_size或max_inflight不为1。移除拒绝本身不构成并行实现。

## 必须先设计的实际接缝

1. **执行输入必须改变行为。** role/冻结假设/上下文投影要进入实际候选执行过程，而非只写manifest。目前composition的M2已产出Proposal.artifact、executor主要调domain评估；需要明确角色化artifact构建和评估的职责，保持M5为唯一检索入口。
2. **provider和domain的会话所有权。** MeteredProvider的累计计量、last_usage和临时治理钩子不能被并行候选共享。现有control工厂只能证明main/control隔离，不能自动推定每个并行main候选都有独立会话。需声明支持能力并在dispatch前创建与绑定实际独立对象。
3. **记录/恢复按调用身份关联。** ContinuationStore目前消费线性有序transcript与checkpoint后缀。不能把同一恢复游标发给多个线程；需要单一记录所有者及按intent关联的执行结果，终裁仍确定性排序，不能用线程完成次序决定选择。
4. **一份物理authority。** 冻结整批请求，启动前完成每项的实际预留与保护容量检查；部分启动只释放可证明未开始者。已知费用保存、未知费用保持预扣，排空已开始工作后处理停止。
5. **多资源与货币约束。** evaluator配额决定执行并发上限；不能以线程数量代替CPU/GPU/工作区资源合同。付费provider并行还需核对现有CNY authority的pending-call规则，不能因执行池允许并行而绕过货币准入。

## 可交付顺序与证据

先接通真实ExecutorSpec及受限ContextPack投影，并通过相同Framework入口验证角色、冻结假设和投影影响实际执行；再接通cohort与并行池，保留常驻控制保护与恢复。分阶段可以交付，但M7并行条款在所有对应能力接通前保持未完成。

最终需要：native与真实worktree两个Adapter；实际重叠执行屏障和max_inflight峰值；整批拒绝零dispatch；不同完成顺序下相同终裁；部分启动/SIGKILL后零重复调用；已知/未知费用混合结果；暂停、继续、记录回放；控制样本不进入主搜索；原全部测试与同SHA验收。生命周期收拢只是前置工程，不代替这些证据。

## 已核实的并发阻碍

`ContinuationStore`的rows/cursor/boundary与provider_call/evaluation_call是共享线性恢复状态，当前append消费下一个精确记录。线程安全的底层文件追加不等于这个恢复游标可以并发共享。并行方案须显式处理关联结果和恢复顺序。

CNY冻结policy明确包含`concurrency: one_unresolved_operation`，`_reduce_governance`在governed_reserve时只要pending非空就拒绝新请求。因此“已有SQLite事务”不能外推为并行付费调用已支持。若并行provider是目标，必须单独版本化currency policy/事件和既有费用保护语义，保留所有未知用量停止条件；不能修改原冻结policy或清空旧pending来放行。工作区纯本地评估的并行与付费请求的并行必须分别给证据，最终M7支持范围如实列明。

## 固定参考源码补充

以下是本地固定提交的机制，不代表远端最新版本。

- [FlashRSI Agent.rollout / _execute](https://github.com/RUC-NLPIR/FlashRSI/blob/4c7f6327fdec7ce09150a1b2958f8051a9653e4a/flashrsi/core/agent.py#L206) 在运行前固定snapshot并深拷贝config，用执行上下文保存，finally恢复；rollout本身逐任务await，是顺序循环。可借鉴配置冻结与作用域清理，不能据此声称它已提供通用并发调度。_docker_harness.py中的gather用于容器清理，也不是候选并发证据。
- [RSIHub EvaluationRunPlan](https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/evaluation/run_plan.py#L9) 用不可变数据类记录candidate commit、任务/尝试数、期望trial数、concurrency和多个runtime指纹；read校验计数一致，write使用临时文件替换。[调用位置](https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/evaluation/execution.py#L130) 在后续preflight之前写入run-plan。可借鉴启动前的执行契约，不能从这一结构单独推断预算预留、实际并发或崩溃恢复保证。

对mori的设计含义：复用已有ExecutorSpec，将规范化配置和上下文投影绑定到实际dispatch与恢复指纹；并发能力必须额外以可重叠执行、独立会话和确定性终裁测试证明。差异化应通过跨物理账本/货币保护、控制隔离、恢复与回放的组合证据展示，不声称其他仓库无法实现。
