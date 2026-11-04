# 2026-11-04 RSI 主源码比较与可验证差异化

## 范围与结论

这是一份固定源码版本的实现比较，不是排行榜，也不是完整安全审计。于 2026-11-04 读取四个公开仓库的默认分支，浅克隆到本仓库外的 `work/references/`；浏览 GitHub 页面作交叉定位，以克隆的源码为主要证据。FlashRSI 的网页抓取失败，但 Git 克隆和源码读取成功。本次没有安装或运行这些参考项目、没有调用付费模型、没有复现其论文数字。下文“存在”只指所链接版本中可以定位到的实现；“建议/假设”不是已完成能力或已验证优势。

**最值得做的下一步，是把本仓库已有机制变成可独立启动、检查、恢复和解释的真实任务流程，并用同预算实验验证其价值。** 不应把模块化、三层评估、版本谱系、恢复或 scope 本身当成独有卖点：RSIHub 已有固定评估器、train/gate/sealed 和执行认证；FlashRSI 已有文件角色权限和内容寻址 Snapshot；RSI-Anything 已有计划/源码身份与完成阶段产物 hash 恢复；Penguin 有可重连的事件读取协议。证据分别见下文 F、H、P、A 组。

本仓库更具体、但仍待外部实验确认的方向是：**物理费用预扣与未知用量状态、独立准入、代理失效后的行为改变、受限负反馈以及进程接管，在同一个公开入口组成可复算闭环**。是否比其它方案更省钱、更可靠或更易用，必须测，不能从代码结构推导。当前 README 自述为开发中原型，真实外部 benchmark/product 验收未完成；S8 记录仍保留串行、HITL、事件订阅、网络知识和真实 campaign 等边界。[M1][M2]

## 版本冻结

| 项目 | 本次读取 commit SHA | 证据入口 |
| --- | --- | --- |
| mori-27 | `49be71ec079f1412a4a8e74086064c4db121c363` | [README][M1]、[抽象对照与阶段记录][M2] |
| RUC-NLPIR/FlashRSI | `4c7f6327fdec7ce09150a1b2958f8051a9653e4a` | [Snapshot][F1]、[Algorithm][F2]、[runner][F3] |
| simple-agent-lab/RSIHub | `d6554299c58bf0fe2db04ddda0277f9db67ea680` | [候选快照][H1]、[评估执行][H2]、[driver][H3] |
| Prism-Shadow/penguin-harness | `2cd01baafd4ee6d59e87b9f41e6a40f65462cf37` | [AMSP reader][P1]、[sandbox 协议][P2]、[默认优化技能][P3] |
| Gen-Verse/RSI-Anything | `8ba44cd73ec6f57b151ec06e2f71a0726adfb687` | [workflow runner][A1]、[代码修复评估][A2]、[反应选择器][A3] |

本地基线是研究开始时的 HEAD。其它并行开发不自动进入本报告；后续比较应重新冻结 SHA，而不是把这里的链接改成浮动 `main`。

## 1. FlashRSI：可编辑资源、执行资源与结果归档

**源码观察。** `SnapshotFile` 保存字节、component 和 executable 位；`Snapshot` 的 SHA-256 包含文件、component rules 和谱系元数据。`_export(full=False)` 按 `none/r/rw` 生成可见编辑视图，`commit()` 保留隐藏基线文件并检查实际修改，`_validate_candidate()` 也验证直接加载的候选。`Algorithm` 分开声明 `evolve_scope` 和 `observation_scope` 并转换为目标 agent 权限；worker 调用由 observer 记录。[F1][F2]

`runner._run()` 先执行 `algorithm.evolve()`，再对返回 Snapshot 运行 `benchmark.test`，生成结果；失败写 `error.json`，`finally` 生成结束摘要。`_startup._preflight()` 将依赖、角色、路径及容器准备检查放到实验前。[F3][F4]

**值得吸收。** 本仓库未来补 M7-01 的 role/frozen hypothesis/context projection 时，可以借鉴“完整执行产物 + 最小编辑视图”，让每次候选明确声明允许改哪些资源、实际改了哪些资源。先做 `check → run → inspect/resume → report` 的统一使用路径，报告实际配置、停止原因、候选和费用证据，降低用户必须自行写 Python glue 的负担。应沿用 Framework，而不是新增绕开预算/准入的实验 runner。[M2][M3]

**边界。** 文件角色权限是资源编辑边界；单凭该类不能证明任意执行环境的 OS 隔离。runner 的结束 test 证明有最终评估调用；Algorithm 本身持有 benchmark 对象，因此本次未把这条调用顺序认定为所有算法都具有不可绕过的 held-out 信息隔离。没有运行具体 harness/benchmark，不能以 README 支持数量推定任意组合都可用。[F1][F2][F3]

## 2. RSIHub：固定评估与可组合策略已经是共同基线

**源码观察。** `build_candidate_snapshot()` 用实际 Git diff 检查 mutable surface，再用独立 index/commit-tree 构造快照；提交时验证 tree 与已审查快照一致。`evaluate()` 从候选 commit 建干净 worktree，拒绝 evaluator tree 偏离 `gen/0`，严格模式使用可信 evaluator 配置并验证 candidate runtime receipt。[H1][H2]

`EvaluationRunPlan` 记录候选 commit、任务列表、每任务尝试数、并发数、预期 trial 数、evaluator/task/runtime 指纹，并校验预期 trial 数。driver 有中断后的 pending gate/record 接续；`_maybe_final_anchor()` 对选中候选做 sealed anchor，并标明不进入 mutate feedback。`doctor` 将依赖、身份配置、执行环境与显式可选的模型 probe 区分开。[H3][H4][H5]

**值得吸收。** 真实 campaign 应先生成机器可读的执行计划：模型/任务/seed/评估器身份、预算和预期调用矩阵，执行后逐项对账。引入“不启动模型即可说明为什么现在不能运行”的 preflight；昂贵 probe 必须显式区分。CLI/报告应清楚区分候选质量失败、基础设施失败、未知费用与尚未终审，避免一个笼统失败状态。[H2][H4][H5]

**边界与定位修正。** 固定 evaluator、候选谱系、受限变更、sealed split 不是 mori-27 的独有创新。这里确认的是具体函数和配置分支，不代表本次已验证 RSIHub 所有 recipe 的 held-out 隔离或收费恢复性质，也不据此断言它缺少多层预算、代理监控或任意其它能力。实际差异应在相同任务与威胁/故障模型下比较，而不是用关键词有无判分。

## 3. PenguinHarness：产品流程与事件消费值得单独对标

**源码观察。** AMSP 的 `SessionReader` 先订阅流，再读取历史快照，按 cursor 处理重叠片段；重连带 `Last-Event-ID`，遇到 `409 resync_required` 重新同步。transport 实际写该请求头。这使实时观察与历史读取有明确一致性语义。[P1][P4]

sandbox 插件接口按 `fs-write/network/network-local/mask-paths/closed-temp` 声明能力，并区分 enforcement 的 full/partial；这是适配器契约设计的参考，不是“配置了 sandbox 就一定完整隔离”的模糊布尔量。[P2]

默认 agent-optimization 技能要求冻结 benchmark、版本化 reference、可证伪假设、候选评估、接受/回滚及拒绝尝试的分析。这属于 agent 执行的工作流指令，不能和 Python/TypeScript 机制强制保证混为一谈。它还允许 formal baseline 与候选 run 数不同，按存储的平均分直接比较；若借鉴，应保留 mori-27 对比较口径和准入证据的要求，而不是照搬整个统计协议。[P3]

**值得吸收。** 优先做可读的运行摘要与只读事件浏览，再考虑实时订阅；明确事件 cursor、重复消费、落后读者和重同步语义。用户需要知道“正在做什么、为什么停止、哪个候选被保留、下一步如何恢复”。M0 已有 AppendOnlyStore，但 S8 记录明确尚无通用订阅协议。沙箱能力应在运行前可见，不将 Mac 可信本地执行描述为 Linux 同等隔离。[M2][M7]

**边界。** Penguin 的比较维度是 agent 产品运行时、可用性和观察协议；不能直接与研究搜索策略做总分排名。浏览/桌面体验、插件数量不是预算治理或独立终审有效性的证据；本次没有启动 UI 或 sandbox 后端。[P1][P2]

## 4. RSI-Anything：预测选择器与统一实验管理应分开学习

**源码观察。** shared workflow runner 把配置、源码身份、stage 计划和渲染文件组成 identity；持有排他文件锁；恢复前验证完成 stage 的产物 hash；完成阶段跳过，未完成阶段增加 attempt 并按声明保留旧输出。`Stage` 明确 command/cwd/env/expected/retry_outputs。[A1][A4]

代码修复评估实现让四个修复候选与 keep-current 一起预测：`choose()` 仅在候选 utility 严格高于 incumbent 时换候选；predictor 过滤到 public tests 和 public observations；封存 public 轨迹后才进入 hidden judge。该公开评估路径中的 `optimizer_steps=0`，不应把它描述成每轮在线更新世界模型。[A2]

Suzuki 选择器使用固定、校准后的 prior，通过 Gaussian expected improvement 推荐未观测条件；观测只更新当前最好收益和排除集合，预测表在整个实验保持冻结。这是清晰可复算的策略例子，不能泛化成所有领域都在线训练同一种世界模型。[A3]

**值得吸收。** 先借鉴 manifest/plan/status/report 与任务适配器的使用流程；把预测选择器当作可替换 policy 的实验性插件，保留真实评估、独立准入和物理预算。mori-27 的 S6 已能做 proxy/anchor 配对、失效后每候选校准和 true-best 附加约束，因此值得测试“预测器失效时的退化成本”，而不只是加入模型后看最好分数。[M5][M6]

**边界。** shared runner 的恢复语义是 stage 级重试/跳过，不能仅凭 resume 参数认定它接管仍在运行的原 worker 或对外部付费调用 exactly-once。mori-27 自己也明确不保证断电丢写恢复，缺 provider completion 时拒绝重调；这属于可比较的行为契约，不是竞品能力否定。[A1][M7]

## 5. 按既有抽象推进的优先级建议

下面是研究建议，不替代既有阶段门槛或授权新的付费实验。

| 优先级 | 具体交付与现有条款关系 | 可审查的完成标准 |
| --- | --- | --- |
| P0 可用流程 | 在 Framework 上提供一条小型真实任务的配置启动、前置检查、状态/报告路径；对应 A-03/A-04、M8-04、X1-05 | 新目录仅凭配置能启动；缺 key/数据/不兼容计量在首个收费调用前报出；完成/失败/恢复都给出同一报告结构 |
| P0 真实实验清单 | 将 S8 组合能力放到有限预算、固定数据身份的外部任务；保留 dev/admission/final_audit/calibration 各自权限 | 报告 provider 和 evaluator 的真实用量、未结预扣、所有失败及 final 状态；离线脚本模型、合成 token 和真实模型数据分列 |
| P1 观察链 | M3/M9/恢复已有 journal 生成可复算摘要；随后再实现 X1-05 订阅 | 报告不能把被淘汰种群成员当准入失败；dev-best、gate-selected、final-audited 分列；读报告不触发模型/replay |
| P1 执行角色 | M7-01 的冻结假设/允许资源/上下文投影，借鉴 FlashRSI scope | 越界改动、隐私内容注入、假设在付费重试时漂移均有公开入口负例；完整执行产物仍保留 |
| P2 新策略 | world-model/EI 或其它预测 policy，和现有 greedy/population 比较 | 先完成同预算消融和失效实验；算法接入不绕过 M3/M9，性能提升以独立 final 数据确认 |

本仓库已有多单位分层账本、严格 usage 读取、proxy 降级和 continuation 源码；“补使用流程”不意味着重写这些机制。S8 的测试组合和阶段记录能证明具体接线，不能代替外部质量与用户操作成本的测量。[M2][M3][M4][M5][M6][M7][M8]

## 6. 可证伪的差异化假设与实验

所有实验先冻结协议和预算；两组用同一任务内容、候选起点、provider/model 配置、评估器版本与成对 seed。至少报告每个 seed 的原始结果，不只报均值/最佳值；小样本先称 pilot，不宣称统计显著。外部系统适配失败记作集成结果，不能随意折算成任务零分或搜索质量差。以下阈值是建议的操作验收标准，不是已测结果。

### H1：运行时治理是否减少昂贵异常的浪费

- **假设：** 同一任务中启用层级预算和持久调用记录，可以降低故障后的重复收费及未解释费用，同时保持停止原因可审查。不是“账本存在所以一定省钱”。
- **设计：** 先用可计数的本地计费模拟服务注入：已完成未结算、中断后缺 completion、超额真实用量、缺失 meter、provider 响应错误但 usage 已知；随后用授权的小额真实调用验证一条正常路径。与既有最简串行 runner 或可适配参考 runner 对照，明确不同恢复语义。
- **指标：** 真实请求数、重复 operation 数、used/reserved/unresolved、故障后人工操作数、恢复耗时、未结费用解释完整率。恢复失败关闭且没有新收费是正确结果，不能当作恢复成功伪报。
- **证伪：** 出现同身份重复付费、已知费用丢失、未知量变成 0、拒绝恢复后仍发新请求，均推翻该路径的保证；若维护成本远高于节省费用，产品价值假设也应下调。源码基础：[M4][M7][M8]；参考恢复对照：[H3][A1]。

### H2：proxy 失效保护是否换来更好的最终收益/成本

- **假设：** 当 proxy 与真实质量关系退化，S6 的 anchor/降级/来源受限负反馈比持续按 proxy 排序更少保留坏候选，并在明确额外费用下改善 final 结果。
- **设计：** 第一阶段用已知 ground truth 的任务注入 rank 反转/常量/噪声；第二阶段选有真实廉价 proxy 的任务。对比“无 anchor”“周期 anchor 但无负反馈”“完整 S6”，固定同一总物理预算；另给出相同候选数下成本曲线。final 数据不作校准或选择。
- **指标：** 坏候选准入率、失效检出延迟、anchor 费用比例、final 得分、每预算单位 final 增益、有效经验实际进入后续输入的次数。预算耗尽导致 final 未运行应单列，不能填 0 或拿 dev 顶替。
- **证伪：** 完整配置在同预算下没有可重复改善，或频繁误报增加费用而无质量收益，则只保留可靠性价值，不能宣传性能优势。源码基础：[M5][M6]；预测策略参考：[A2][A3]。

### H3：更完整证据是否真正降低首次使用与排障成本

- **假设：** 明确的 preflight + 无副作用 inspect/report 能让未参与开发的人更快完成首次有效运行、识别缺失依赖和恢复路径。
- **设计：** 用统一步骤表分别走全新目录、缺凭据、数据 identity 漂移、运行中断、已完成恢复五个案例；记录首次 setup 到可审查结果的耗时、命令数、人工改配置次数和错误诊断是否正确。跨项目比较只选择共同支持的任务/运行模式；安装环境不同单独记录。
- **指标：** 首次有效运行成功率、首个付费调用前发现错误比例、异常诊断正确率、报告与原始 journal 对账率。真实新用户样本优于开发者自测。
- **证伪：** 只是新 CLI 包装，仍要求用户读内部模块/手写适配代码，或报告遮蔽未知成本，不能称易用性改善。参考：[F4][H5][P1][A1]；本地入口与边界：[M1][M2]。

### H4：治理层是否能容纳不同搜索策略而不改变硬契约

- **假设：** 更换 tree/population/预测 policy 后，同一 domain 的预算、独立准入、身份和恢复检查继续成立，且整合工作量可控。
- **设计：** 对同一真实任务切换 greedy、现有 population 和一个固定预测 prior；记录适配代码行数、改动的机制文件数、同预算 final 质量与异常用例结果。先对比本仓库内部策略，避免因目标 harness 不同产生虚假横向胜负。
- **证伪：** 新策略必须修改预算/准入内核，或恢复后采样、身份、成本改变，说明抽象尚未稳定；更好的接口不自动证明搜索更好。基础与对照：[M3][M2][F2][H4][A3]。

## 7. 周期比较的记录方法

建议每个功能阶段封板后或准备外部 campaign 前做一次增量对照；这是研究节奏建议，本次未创建定时自动任务。

1. 固定四仓库新 SHA；用相对上次 SHA 的 diff 找到与当前条款有关的变更，不重复抄 README。
2. 保留“源码已见 / 本地运行通过 / 外部任务实测 / 未覆盖”四类证据，性能数字必须有环境、数据、模型、预算、seed 和输出文件。
3. 每轮最多选一个待吸收机制和一个待验证差异；标明对应 ABSTRACTION_ALIGNMENT 条款，避免被新术语带离计划。
4. 对“不支持/没有/不能”的判断要求专门检索和可运行负例；只读若干文件时写“本次未验证”，不把沉默当否定证据。
5. 不将 mock、单位测试数量或外部 README 结果当本项目成绩；新增实验与 Mac/同 SHA Linux 阶段门槛分别记账。[M2]

## 源码永久链接

[F1]: https://github.com/RUC-NLPIR/FlashRSI/blob/4c7f6327fdec7ce09150a1b2958f8051a9653e4a/flashrsi/core/snapshot.py
[F2]: https://github.com/RUC-NLPIR/FlashRSI/blob/4c7f6327fdec7ce09150a1b2958f8051a9653e4a/flashrsi/core/algorithm.py
[F3]: https://github.com/RUC-NLPIR/FlashRSI/blob/4c7f6327fdec7ce09150a1b2958f8051a9653e4a/flashrsi/runner.py
[F4]: https://github.com/RUC-NLPIR/FlashRSI/blob/4c7f6327fdec7ce09150a1b2958f8051a9653e4a/flashrsi/_startup.py
[H1]: https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/candidate/snapshot.py
[H2]: https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/evaluation/execution.py
[H3]: https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/driver.py
[H4]: https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/evaluation/run_plan.py
[H5]: https://github.com/simple-agent-lab/RSIHub/blob/d6554299c58bf0fe2db04ddda0277f9db67ea680/src/evolve/doctor.py
[P1]: https://github.com/Prism-Shadow/penguin-harness/blob/2cd01baafd4ee6d59e87b9f41e6a40f65462cf37/packages/amsp/src/reader.ts
[P2]: https://github.com/Prism-Shadow/penguin-harness/blob/2cd01baafd4ee6d59e87b9f41e6a40f65462cf37/packages/core/src/plugin/sandbox.ts
[P3]: https://github.com/Prism-Shadow/penguin-harness/blob/2cd01baafd4ee6d59e87b9f41e6a40f65462cf37/plugins/default-rsi-toolkit/skills/agent-optimization/SKILL.md
[P4]: https://github.com/Prism-Shadow/penguin-harness/blob/2cd01baafd4ee6d59e87b9f41e6a40f65462cf37/packages/amsp/src/transport.ts
[A1]: https://github.com/Gen-Verse/RSI-Anything/blob/8ba44cd73ec6f57b151ec06e2f71a0726adfb687/src/rsi_anything/workflow/runner.py
[A2]: https://github.com/Gen-Verse/RSI-Anything/blob/8ba44cd73ec6f57b151ec06e2f71a0726adfb687/tasks/code_repair/src/evaluation.py
[A3]: https://github.com/Gen-Verse/RSI-Anything/blob/8ba44cd73ec6f57b151ec06e2f71a0726adfb687/tasks/reaction_optimization/src/suzuki_inference/selector.py
[A4]: https://github.com/Gen-Verse/RSI-Anything/blob/8ba44cd73ec6f57b151ec06e2f71a0726adfb687/src/rsi_anything/workflow/types.py
[M1]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/README.md
[M2]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/docs/ABSTRACTION_ALIGNMENT.md
[M3]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/contracts.py
[M4]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/budget.py
[M5]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/proxy.py
[M6]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/proxy_runtime.py
[M7]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/recovery.py
[M8]: https://github.com/YixuanZhang99/mori-27/blob/49be71ec079f1412a4a8e74086064c4db121c363/m0/core/composition/provider.py
