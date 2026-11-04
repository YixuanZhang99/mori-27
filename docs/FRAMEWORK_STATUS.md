# 框架交付范围与后续开发顺序

本文区分可用的工程能力、尚未接通的原设计条款和必须实测的研究结果。设计依据仍是 [统一抽象对照表](ABSTRACTION_ALIGNMENT.md) 与 [RUBRIC](../autoresearch-fw/RUBRIC.md)，不以本页替换原验收门槛。时间点：2026-11-04；治理实现提交 `bedc5b31fe737dfd207fa8466f68fecb58c5c294`。

当前可交付的是**可安装、可运行、可恢复、可离线回放的治理工程预览**。不能称 v1.0 或完整设计全部完成。原 RUBRIC 要求 A1–A7、B1–B5、C1–C4 全部达标；测试通过不能替代这些条款。

## 已接通的使用路径

从 [开发指南](DEVELOPMENT.md) 安装框架，用 [治理示例](GOVERNED_CONTROLS.md) 运行同一 `Framework.evolve/inspect/replay` 入口：

- 可选 `composed-v7-governed` 固定对照计划，创建独立 session，在初始和指定周期执行对照；对照不进入主搜索的父节点、记忆或最终选择。
- 单一物理账本预留未来对照容量，冻结主搜索可用份额；七账户由实际结算投影，不重复收费。
- 主流程与对照的 provider 调用绑定精确身份、请求、ordinal 和适配器声明；失败保留已知成本，未知费用或完整性问题停止新调用。
- native 与真实 worktree 均支持已有终态接管、暂停与恢复；不明的原生执行不会自动重试。
- governed replay 消费已记录结果，校验预算与回执链，不发起新模型请求。旧 ungoverned replay 保留原来的重新执行语义。
- CNY authority 的版本迁移、未来义务及语义审计已在临时账本验证；**外部 provider 桥接尚未接通**，不能据此启动正式受保护的付费对照。

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

## 按原设计继续开发

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
