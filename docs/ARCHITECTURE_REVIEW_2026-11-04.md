# 组合运行路径的接口审视

审视基线：`5fa85d3ab7c4f643550ecaa2223a65231d7f7a86`。本次关注真实 MLE 启动涉及的模块和后续 C1/C3 缺口，不将局部审视记为 RUBRIC A7 全库通过。v69 的 39 项本地验收证明相应行为回归通过，不证明每个模块均满足接口数/内部机制数 ≤ 1:3。

## 方法与范围

接口包括调用者必须知道的配置、调用顺序、错误处理和恢复条件，不只是公开方法数量。下表的方法数量来自 AST 盘点，作为导航线索；内部机制按真实行为讨论，不以代码行数或私有方法数量充当机制数量。删除检验关注：移除模块后，其复杂性是否会重新分散到调用者。

| 模块与接口 | 实现承担的复杂性 | 本次判断与维护约束 |
| --- | --- | --- |
| `core.loop.Framework`：`from_profile` 构造，`evolve/inspect/replay` 三个运行入口 | 选择旧 M0 或组合路径，冻结配置、组装运行依赖，承接检查与回放 | 应继续保留统一入口；构造入口不能隐藏另一条不受预算和证据约束的执行路径。公开方法存在不等于两种运行路径覆盖相同治理条款 |
| `composition.registry.Registry`：`register/preflight/build` | 名称和选项验证、依赖注入、实例构建；配置只允许注册名，不执行动态表达式 | 是实际替换位置，已有多种 policy/domain/operator。新增行为应优先装回已有位置，不为一个实现增加新顶层入口 |
| `composition.runtime.ComposedRuntime`：`run/inspect/replay` | 调用顺序、运行身份、主循环、费用结算、上下文权限、准入、checkpoint 与回放协调 | 外部接口提供较多能力，但内部耦合需控制：继承的 `HierarchicalRuntime/PopulationRuntime/ProxyRuntime` 读取共享属性并回调驱动私有方法。它们不是可独立替换的注册模块；不能把拆成多个文件视为已经获得独立接口 |
| `composition.budget.HierarchicalBudget`：14 个非下划线方法，含状态和恢复方法 | 同一物理操作的全局/方向/候选投影，整篮预留、开始、结算、释放、未知费用、配额与恢复 | 删除后会把账务与恢复复杂性分散到驱动，具有明确价值。但调用者要理解预留→开始→结算/未知的状态顺序；新增对照账户时应在该模块维护一份权威费用记录，避免在驱动平行记账 |
| `zoo.mle_bench_lite.cny_budget.CampaignBudget`：`create/manifest_binding/reserve/settle/snapshot` | 唯一授权身份、SQLite 原子预留、严格用量计价、崩溃持久性、哈希链校验、未知费用阻断 | 货币和服务商政策保留在任务适配目录；不能挪进六概念内核。调用者必须显式建账一次、复用已有账本，并理解费用上界与供应商账单的区别 |
| `zoo.mle_bench_lite.provider.BenchmarkProvider`：构造、可调用接口、`manifest_binding` | 请求格式、实际 HTTP、无重试/重定向、调用证据、用量和响应身份校验、货币结算 | 在实际请求位置控制费用，避免调用方漏记。DeepSeek 兼容性属于该适配器；不能为了缩短接口把独立审计也变成完全信任 provider 自报 |

独立审计和 provider 会核对部分相同事实，但信任角色不同：`usage_audit.py` 必须从持久账本反向发现本地缺失调用。不能将这种交叉校验当作一般重复代码而删除。相反，纯格式转换可以共享；共享函数不能成为唯一的完整性判断来源。

## 已确认的治理覆盖差异

旧路径在 `core/loop.py` 的 `gen % baseline_every == 0` 分支中创建 `iid-rs` intent，使用 `control` 账户，执行独立 draft，记录 `baseline`；对照候选不进入研究 frontier。最终 `_self_attestation` 使用独立样本并保留证据不足结论。这些源码和旧路径测试不能替代组合路径的执行证据。

组合路径 `ComposedRuntime._run` 当前仅调度主搜索 `_cycle`、三层终裁及上下文收尾。`HierarchicalBudget.OPERATIONS` 包含 `planning/operator/dev/dev_baseline/anchor/admission/final`；其中 `dev_baseline` 是主搜索 incumbent 的开发集基准评估，不是独立随机搜索。当前没有常驻 IID-RS 的生成、评估、保留预算与恢复链路，结果也没有相应控制样本集合。因此 C3 仍不达标。七账户与 intent 的全覆盖也不能由全局/方向/候选三层物理投影直接推定。

当前六次 MLE pilot 的 `baseline` 是相同任务上的 greedy 搜索方案，`full` 是组合治理方案；这里的 baseline 不等于 IID-RS，也不是 OpenEvolve 宿主。该试跑不能关闭 B1、B2 或 C3。其源码与配置已经冻结，不在中途追加对照调用。

## 下一阶段的结构决策依据

独立的第二个 Framework run 比较容易启动，但会带来两份预算、两套恢复状态和难以保证常驻的调度条件，不能直接实现 C3。把 IID-RS 作为普通可选 policy 又会让它替换主搜索，而不是与主搜索共存。这两种方案可用于实验对照，均不足以作为正式运行的治理实现。

建议将控制通道作为组合驱动内的受预算约束职责：主搜索与对照共享物理费用权威来源，使用可区分的账户/intent；对照使用冻结的任务起点和独立随机状态，不读取搜索谱系、记忆或隐藏评分；候选和证据保留以供复核，但不进入主搜索供亲、准入或记忆。实现必须覆盖实际 provider/executor 及恢复位置，不能只增加 `baseline_enabled` 配置或终端报告。

实施前应形成单独的设计和计划，并明确：控制预算如何受保护、调度频率、主搜索提前停止时如何完成对照、缺少对照如何阻止正式认证、对照失败和未知费用如何处理，以及每个恢复窗口的零重复调用证据。静态纯函数或离线 HTTP fixture 用于行为回归；未来真实正式 campaign 仍需独立预算和实测证明。

本次不进行目录重排或继承关系重写。先让真实试跑暴露的使用问题进入所属模块，再用上述结构约束指导控制通道设计。A7 全库审视、A6 新人冷启动和 A/B/C 发布门槛继续保留为未完成项。
