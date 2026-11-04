# 框架交付范围与后续开发顺序

## 最新实证进展（2026-11-05）

`e4aa87e` 将受限的 GEPA 实例级选择和 FunSearch 种群、构造及 OR3
开发集适配合入本开发分支。离线示例和参考程序可运行，但真实模型结果、
独立留出集评分和完整方法复现均未完成。合入代码树通过 2406 项 Linux 测试、
84 项工具测试及构建检查；同提交本机 v74 的 55 项检查和源码绑定已通过独立
核验。同提交的 GitHub Actions 推送验收也已通过，下载的证据经独立核对，
同样绑定 1158 个源码文件和 55 项检查。

后续仅改文档的 `ec25543` 在一次远端验收中，完整回归达到单项 600 秒
时限而失败；其源码摘要与 `e4aa87e` 相同。这次失败记录保留，当前分支的
最新 CI 状态应以 GitHub Actions 为准，不能由前一提交的通过结果代替。
为缩短验收临时文件的 I/O，后续 CI 优先使用可执行且剩余至少 1 GiB 的
`/dev/shm`，不可用时回退到 runner 临时目录；测试内容和原时限不变。
`586dd1f` 本机 v74 的 55 项检查及源码绑定通过；其 [GitHub Actions 推送验收](https://github.com/YixuanZhang99/mori-27/actions/runs/41911091797)
再次因完整回归的单项 600 秒时限失败，快速临时目录未消除这一远端计时问题。
失败证据已保留；尚不能将该提交标记为远端验收通过。
同一开发提交对应的 [PR 合并检查](https://github.com/YixuanZhang99/mori-27/actions/runs/41911103180)
则通过 55 项检查：实际验收对象是 GitHub 合并提交 `c7b11cb`，其 Git 树与
`586dd1f` 完全相同，1159 个源码与验收文件也已独立核验。这支持相同源码在
另一远端运行中通过，但不抹去推送验收的超时失败，也不能保证下一次不会超时。
后续文档提交 `a75164d` 的[推送验收](https://github.com/YixuanZhang99/mori-27/actions/runs/41915628876)
已通过 55 项检查；下载的证据经独立核验，绑定该提交的 1159 个源码与验收
文件。此前超时记录仍保留，最新提交的状态须单独查看。
后续文档提交 `8e665f5` 的[推送验收](https://github.com/YixuanZhang99/mori-27/actions/runs/41919153806)
再次在完整回归的 600 秒内层时限失败；上一成功运行的完整回归耗时约 522 秒。
日志没有给出具体失败断言，也不能据此确定耗时波动的根因；CI 稳定性仍待解决。

开发分支 `codex/m7-construction` 的 `a6b5826` 已完成本机完整项目检查、
本机 v74 验收以及同提交 GitHub Actions 验收，并完成三项真实 MLE 任务的
baseline/full 三个本地 seed 试跑：两个冻结批次的 18 份提交均通过官方评分
和独立核验。具体分数、批次差异、费用及限制见[已完成试跑报告](../research/experiments/2026-11-05-m7-real-mle-three-seeds/)。
这不是完整 MLE-Bench Lite 成绩，也不能据此宣称治理带来提升；模型标识是
可变的 `deepseek-flash` 别名，未验证不可变模型快照。前两次未完成的尝试
仍保留在相邻实验目录中。

经典方法复现、同搜索治理对比及完整 Goal 的其余验收仍未完成。下文是
2026-11-04 的架构和分支历史快照，不代表最新试跑状态或当前远端分支数量。

## 当前交付优先级（2026-11-04 用户确认）

后续按[实证交付计划](superpowers/plans/2026-11-04-evidence-delivery.md)推进：①三任务真实 MLE 报告；②有明确方法一致性边界的 GEPA、FunSearch 复现包；③同一搜索方法下的治理收益与开销对照。原完整 Goal 和 A/B/C 验收要求保留。工程测试、方法风格示例、真实诊断试跑和完整 benchmark 分开报告；旧 greedy/full 结果不能直接证明治理增益。

批量进程内评估恢复依赖原始持久化日志：已结算候选的结果费用会与其账本结算核对；尚未结算的候选没有独立费用凭据，恢复会使用其日志中的已记录用量完成结算。因此不能把该路径描述为能独立识别所有结算前的日志篡改。外部费用治理的独立收据和不同的审计边界另见 [GOVERNED_CURRENCY.md](GOVERNED_CURRENCY.md)。

历史记录：用户暂停时中止的 v74 运行不算通过；后续已对上述 `a6b5826` 重新完成本机和远端验收。下文分支表仍是已推送 ec47899 阶段的快照。

本文是当前开发状态的统一入口，区分代码位置、实现范围和验收结果。设计依据仍是 [统一抽象对照表](ABSTRACTION_ALIGNMENT.md) 与 [RUBRIC](../autoresearch-fw/RUBRIC.md)，不以本页替换原验收门槛。以下分支快照于 2026-11-04 核对；本页随 M7 Task 5 功能提交同步，精确源码哈希和验证结果见[本阶段记录](../research/experiments/2026-11-04-m7-currency-construction-local/summary.json)。

## 当前应该看哪个分支

- **已合入主线：** `main`，`49be71e`，停在 S8 / v67 的配置种群与双亲 crossover。
- **最近完成独立版本验收的工程节点：** `f7ab273`，v73，包含常驻对照、外部费用桥接及调用生命周期收拢；其本地和同 SHA Linux CI 均通过。它尚未合入 main，也不是正式发布。
- **当前唯一继续开发的分支：** `codex/m7-construction`，包含上述所有工作，并新增 M7 原生构造、Git 产物发布、命令恢复及 v9 外部费用接入。当前不再按每个子任务新增开发分支。

本阶段提交后比 main 多 **24 个提交**（含设计和状态文档），没有与 main 分叉。远端 16 个分支并非 16 份互不相容的实现：所有分支头都在当前开发分支的祖先链上。回滚以精确 SHA 和已验证 bundle 为依据，无需长期保留每一个阶段分支名。

| 远端分支 / 分组 | 相对 main 的状态 | 用途与 PR |
| --- | --- | --- |
| `main` | `49be71e` | 当前默认分支；没有下面的新功能 |
| `codex/abstraction-stage-1` 至 `-8`、`codex/evaluation-context-and-replay`、`codex/governance-safety-fixes`（10 个） | 全部已经包含在 main，独有提交为 0 | 历史分支名，可在保留回滚引用后清理；没有待合入代码 |
| `codex/mle-composed-pilot` | 领先 main 1 个提交；已包含于下列所有开发分支 | 早期 MLE 接入节点，独有工作已在 PR #1 范围内 |
| `codex/resident-governance` | 领先 main 13 个提交 | [PR #1 → main](https://github.com/YixuanZhang99/mori-27/pull/1)，Draft |
| `codex/governed-currency-bridge` | 领先 main 14 个提交 | [PR #2 → resident-governance](https://github.com/YixuanZhang99/mori-27/pull/2)，Draft；比前者多 1 个 |
| `codex/invocation-lifecycle` | 领先 main 17 个提交 | [PR #3 → governed-currency-bridge](https://github.com/YixuanZhang99/mori-27/pull/3)，Draft；比前者多 3 个 |
| `codex/m7-construction` | 本阶段提交后领先 main 24 个提交 | [PR #4 → invocation-lifecycle](https://github.com/YixuanZhang99/mori-27/pull/4)，Draft；本轮已完成 5/6 项，尚未完成整体交付 |

这是一条累积提交链：`main → MLE → resident-governance → currency-bridge → invocation-lifecycle → M7`。目前有四个按上述依赖顺序排列的 Draft PR；Git 可合并不等于满足仓库验收要求。

## 实际开发到哪里

| 工作块 | 当前实际完成范围 | 验证与未完成范围 |
| --- | --- | --- |
| 主线 S1–S8 | 配置组装、统一评估、记忆回流、分层准入/预算、proxy 校准、命令 worktree 恢复、种群与 crossover | 已在 main；具体限制见原阶段记录，不能理解为原设计全部实现 |
| MLE 接入与费用保护 | 三任务适配、官方评分接入、隔离、请求容量检查、跨运行费用账本 | 三任务 × baseline/full × 三个本地 seed 均已获得官方评分；批次和可比性限制见上方报告 |
| 常驻治理 / v72 | 独立对照会话、未来容量保护、七账户投影、原始结果接管及记录回放 | `ff5c441` [同 SHA CI 通过](https://github.com/YixuanZhang99/mori-27/actions/runs/41816499445)，46 项版本验收；尚未合入 main |
| 外部费用桥 / v73 | 物理与人民币双重准入、独立费用审计、已知结果恢复、回放不新增请求 | `75f397e` [同 SHA CI 通过](https://github.com/YixuanZhang99/mori-27/actions/runs/41820454246)，50 项版本验收；新路径使用 loopback 验证，未迁移真实账本 |
| 调用生命周期收拢 | planning/operator/evaluation 共用调用与结算顺序，保留真实计费权威 | `f7ab273`：2,132 Linux tests、76 tooling、本地 v73 50 项和[同 SHA CI](https://github.com/YixuanZhang99/mori-27/actions/runs/41827376262)通过；不等于 A7 全仓关闭 |
| M7 构造、Git 执行与费用保护（当前） | 角色/假设/投影参与生成；不可变原生/Git artifact；命令评估复用原提交；独立对照、SIGKILL 恢复；v9 物理/人民币双重准入及原始请求/产物审计 | Task 5：2,257 Linux tests、76 tooling、11 公理、示例/构建/导入通过；新建安装环境的 v8/v9 仓库外示例均通过；M7 总计划 6 项完成 5 项。当前增量同 SHA CI 待验证，不能继承前序绿色结果 |

**M7 下一步：** Task 6 整体独立审查、v74 验收及同 SHA 安装/远端证据。旧 v8 与新 v9 外部费用路径分别有本地验证；尚不能据此宣称 M7 整体或完整框架交付。见 [实施计划](superpowers/plans/2026-11-04-m7-execution.md)和[当前原生接口](CONFIGURED_CONSTRUCTION.md)。

**框架整体仍开放：** composed 并发池、完整算子与比较反思、部分准入组装、HITL、事件订阅、网络知识、A7 全仓指标，以及 RUBRIC B1–B5 等真实研究/产品证据。不能用“当前计划完成 5/6”推导框架整体完成比例，也不能用单测数量推导发布完成度。

## 为什么还没合入，以及收敛顺序

原对照表规定：每阶段先通过 Mac `make check`，再通过同一 SHA 的 Linux 全量自动验收，之后更新 main。目前新开发节点具备 Linux 证据，但缺少对应提交的 Mac 实机检查；M7 还缺整体审查与自身验收。这是当前未推进 main 的具体原因，不是分支冲突或 GitHub 写权限问题。

维护顺序为：在现有 M7 分支继续开发；补齐已完成节点的合入门槛，按 #1、#2、#3 的依赖顺序集成；M7 在自身交付门槛通过后再集成。合并后清理被包含的历史分支，保留精确提交与回滚备份。当前状态核对没有执行分支删除或主线合并。主线门槛若需要调整，应作为明确的项目决策记录，不能把 Linux 测试冒充 Mac 证据。

## 下文历史记录的阅读方式

以下保留 v72 起的阶段记录。当它们写“待 CI”“桥接未完成”时，仅描述当时的基线；当前事实以上面的提交/能力表为准。

当前可交付的是**可安装、可运行、可恢复、可离线回放的治理工程预览**。不能称 v1.0 或完整设计全部完成。原 RUBRIC 要求 A1–A7、B1–B5、C1–C4 全部达标；测试通过不能替代这些条款。

## v72 基线已接通的使用路径

从 [开发指南](DEVELOPMENT.md) 安装框架，用 [治理示例](GOVERNED_CONTROLS.md) 运行同一 `Framework.evolve/inspect/replay` 入口：

- 可选 `composed-v7-governed` 固定对照计划，创建独立 session，在初始和指定周期执行对照；对照不进入主搜索的父节点、记忆或最终选择。
- 单一物理账本预留未来对照容量，冻结主搜索可用份额；七账户由实际结算投影，不重复收费。
- 主流程与对照的 provider 调用绑定精确身份、请求、ordinal 和适配器声明；失败保留已知成本，未知费用或完整性问题停止新调用。
- native 与真实 worktree 均支持已有终态接管、暂停与恢复；不明的原生执行不会自动重试。
- governed replay 消费已记录结果，校验预算与回执链，不发起新模型请求。旧 ungoverned replay 保留原来的重新执行语义。
- CNY authority 的版本迁移、未来义务及语义审计已在临时账本验证；**该基线的外部 provider 桥接尚未接通**，不能据此启动正式受保护的付费对照。

省略 governance 保留既有 composed-v6 行为。支持边界和配置拒绝条件见治理指南。

## 可核对的证据

| 证据 | 已知结果与边界 |
| --- | --- |
| [实现验证记录](../research/experiments/2026-11-04-resident-governance-local/README.md) | 2,000 Linux tests、64 tooling tests、公理、示例、构建及初始导入完整性检查通过；是工程证据 |
| 同目录的 `summary.json` | 独立环境安装 wheel，复制示例到 checkout 外：暂停、恢复、记录回放通过；不是第三方任意插件认证 |
| [v71 原始归档来源](../m0/verifier/v72/v71-provenance.json) | 干净 bedc5b3 完整验收 42 checks，717.642 秒，前后源码不变，零外部模型请求；旧失败运行仍保留为失败 |
| [v72 验收定义](../m0/verifier/v72/README.md) | 保留全部 33 个 v71 命令及超时，新增四组，预期 46 checks；定义存在不等于本提交已通过 |
| [远端开发分支](https://github.com/YixuanZhang99/mori-27/tree/codex/resident-governance) | bedc5b3 已推送；当前候选的同 SHA CI 状态以 Actions 为准，不能用历史绿色结果代替 |
| [bedc5b3 CI](https://github.com/YixuanZhang99/mori-27/actions/runs/41815641612) | 编写本页时已启动；完成状态由该记录给出 |
| [架构审计](review/2026-11-04-governance-depth.md) | 新增模块承担实际规则；invocation 生命周期分散与动态属性协议仍需收敛，A7 全仓比例未关闭 |
| [四个参考仓库比较](../research/2026-11-04-framework-development-priorities.md) | 固定源码来源的机制比较与取舍；不宣称其他系统无法实现相同能力 |

## 基线审查时的开发顺序（桥接进展见文末）

| 优先级 / 对应条款 | 待交付能力 | 最低关闭证据 |
| --- | --- | --- |
| P0 / C1、C3、C4 | 外部 provider 与既有 CNY authority 桥接 | 所有调用先获得两边准入；固定 main/control 货币份额；逐崩溃切点验证恢复；记录回放不改真实账本、不重复请求 |
| P0 / A7 | 收敛 invocation 生命周期 | 调用者不再分别维护 meter、settle、integrity-check 顺序；保留主/对照、native/worktree 及全部故障边界行为；不能只加一层透传类 |
| P1 / M7-01、M7-03 | 通用 ExecutorSpec 与 composed 并行池 | 冻结角色/假设/上下文投影；资源反压、整批预留、串行终裁、部分启动及恢复均从公开入口验证 |
| P1 / M9-02 | layered top_k 与旧二元规则组装 | 配置真实改变选择和回执；成本、准入数据和最终审计权限继续隔离 |
| P1 / X1-05 | 只读事件订阅与完整导出 | 覆盖决策和拒绝来源；订阅者不能写核心状态，去掉订阅者不改变结果；日志文件本身不计事件总线完成 |
| P1 / X2 | composed 控制层注入 | 精确动作授权、一次消费、暂停/恢复持久化；现有 stop_after_generation 不等于全部 HITL |
| P1 / M2-03、M4-03、M5 | 完整算子、比较反思和通用检索投影 | 来源受限的比较证据实际改变后续提案；失败、预算和恢复闭环；不能仅注册新名字 |
| P1 / M9-01、设计 §8 | 通用研究配置默认三层 | 默认配置贯通 dev/admission/final；旧兼容单层保持明确标识 |

每个工作块先完成实现和有意义的回归，再记录精确提交、更新模块地图、推送可回滚分支。主分支仍遵守原有平台与同 SHA 自动验收门槛。MCP、统计显著收敛、语义 QD 等原文后置项保持后置；表中的未完成项不能擅自改为后置来宣布全部完成。

## 真实研究证据仍开放

已保留两轮小规模 MLE 诊断。第二轮有三份有效提交，但三个任务均没有同轮完整有效的 baseline/full 配对；baseline 是 greedy，不是 OpenEvolve 或 IID-RS。因此不能报告框架优势或模块归因。两轮历史合计 33 次请求、477,858 token、保守费用上界 3.242064 元，未结调用为 0；这不是供应商账单。用户将本轮重点转向框架开发，第三轮付费试跑暂缓。

B1–B5 需要真实的独立对照、固定数据/模型/预算、足够任务与种子、官方评分及全成本记录。工程可以保证实验记录和拒绝条件，不能保证效果超过其他框架。正式 IID-RS、供应商统计独立性、任意外部副作用 exactly-once 和整机断电恢复均不由当前离线结果推出。


## 后续工程增量：外部费用桥接

在上述 bedc5b3/v72 基线之后，独立分支增加了 [v8 外部费用桥接](GOVERNED_CURRENCY.md)：固定 main/control 货币容量、逐调用双重准入、私有结果与 provider 状态持久化、独立账本审计及记录回放。native、真实 worktree 和实际 SIGKILL 路径已用临时账本与 loopback HTTP 验证。P0 桥接的工程实现因此已接入；完整版本验收、同 SHA CI 和真实供应商实验仍须分别报告实际结果。本增量不改写上面的历史证据，也不宣称原设计全部完成。

新增[本地桥接验证记录](../research/experiments/2026-11-04-governed-currency-local/README.md)：2,116 Linux tests、76项当前 tooling 检查通过；安装后的 wheel 在仓库外完成独立示例。v72 基线 ff5c441 的[同提交 GitHub CI](https://github.com/YixuanZhang99/mori-27/actions/runs/41816499445)两项 job 已成功，草稿 [PR #1](https://github.com/YixuanZhang99/mori-27/pull/1) 已创建。v73 候选的验收状态须单独查看，不能继承该绿色结果。

## 调用生命周期收拢（当前开发增量）

planning、operator、evaluation 的物理调用现在由私有 `InvocationLifecycle` 负责开始、计量、失败分类、结算和完整性检查顺序，主流程／对照以及旧的 hierarchical 路径使用同一实现。`GovernedInvocation` 保留固定计划、会话、逐请求准入和控制调度；`HierarchicalRuntime._settle_physical` 保留真实单位覆盖与持久化测量政策。flat 非层级账务路径仍保留原语义。

已通过92项相关回归及11项静态公理；上一版75f397e安装包产生的暂停状态由新代码恢复完成，主流程4次与对照3次provider调用均只有一组原始开始／完成记录，记录回放零新调用。完整项目检查现已通过2,132项Linux tests、76项tooling、公理、六个例子、构建及导入完整性；同提交验收仍须单独核对。本增量降低调用者需要维护的顺序约束，不据此关闭A7全仓比例或完整设计。

独立审查发现并修复一项 Important 计费边界问题：持久化时长读取异常不能冒充执行器的测量账单；直接回归与公开 Framework 入口均先重现失败，再验证修复。最终完整检查和新 wheel 仓库外示例均通过，详见[审查记录](review/2026-11-04-invocation-lifecycle.md)。前序桥接提交75f397e的[同 SHA CI](https://github.com/YixuanZhang99/mori-27/actions/runs/41820454246)已全部通过，v73共50项检查；生命周期新提交的CI仍需独立报告。
