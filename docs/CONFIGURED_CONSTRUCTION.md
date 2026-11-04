# M7 原生构造接入：schema 2

本页描述 M7 实施计划 Task 3 的公开接口。它提供 `composed-v9-m7` 和 `composed-v9-m7-governed` 原生路径；Git artifact 发布、命令评估接入和 v9 外部货币桥仍待后续任务。它不表示 M7 并发调度或整个框架验收完成。原有 schema 1 配置与历史检查点按原契约运行，不自动升级。

## 配置与调用

在已有、可运行的 [hierarchical 配置](HIERARCHICAL_BUDGET_V64.md) 上显式设置：

```python
profile["schema_version"] = 2
profile["executor"] = {"name": "inprocess"}
profile["execution"] = {
    "schema_version": 1,
    "spec": {
        "role": "coder",
        "hypothesis_frozen": True,
        "context_projection": ["memory", "grounding"],
    },
    "constructor": {"name": "prompt", "options": {"max_attempts": 2}},
}
framework = Framework.from_profile(profile, llm, evaluator, config, workdir)
result = framework.evolve(task)
```

这里的 `profile`、`llm`、`evaluator`、`config`、`workdir` 和 `task` 是调用方已有依赖；片段不是独立示例。预算必须选择 `hierarchical`，并覆盖 planning、operator 和评估阶段。默认 `tokens` 配置会在调用前拒绝。内置角色为 general、coder、analyst；角色指令进入真实构造请求。自定义角色必须通过 constructor 注册声明，与工厂实例的版本化角色绑定一致。

`draft`、`reflective`、`crossover` 在此路径产生声明式配方。构造器调用模型，要求返回 JSON 对象，包含非空 `artifact` 和 `hypothesis`。规划仍选择算子、父候选和假设。`spec.hypothesis` 可显式约束初始假设；冻结模式下，模型改变该字符串会产生有费用记录的构造失败，而不会执行评分。自由模式把最终假设归属到实际评分候选。字符串一致不保证生成代码在语义上遵循假设。

## 上下文与策略状态

`context_projection` 只接受不重复的 memory、grounding、query；空列表允许，summary 和 full 不属于该版本契约。一次 M5 检索的原始摘要仍保存用于审计，但规划、动态 skill 和配方只获得投影后的内容。选中的父 artifact、任务文本与显式配置的静态 instruction 是另外授权的输入。

schema 2 将同一策略配置实例化为两个独立会话：一个规划，一个吸收反馈；它们分别保存检查点状态。反馈继续写入记忆，再经 M5 检索和投影供后续规划使用。自定义策略不能再依赖在 absorb 中保存原始反馈、随后由同一个实例直接交给 ideate 的隐式通道。schema 1 行为不变。

构造器工厂不接收 live provider 或 evaluator；模型依赖只在计量中的构造调用内提供。生成相关工厂获得组件范围内的 journal 视图。注册的 Python 代码仍属于受信任代码，共享全局变量、外部状态与原生执行不构成安全沙箱。

## 预算、artifact 与恢复

一次候选生产共用一个 operator 预扣、一个连续调用序列和一次结算：一个尝试节点、零次评估。构造、修复和发布失败保留已经测得的费用；未知用量保留整笔未结预扣，不重发替代调用。`max_attempts` 限制修复次数。对没有硬调用上界的原生 provider，用量耗尽预扣后不再修复，但单次调用仍可能超额；超额费用如实记账。受治理 provider 继续使用已有硬调用上界与未来对照保留预算。

原生 artifact 按内容摘要持久化。dev、baseline、calibration、admission、final 只评估同一个已构造 artifact，不重新生成。材料化记录同时绑定原始构造终态、计划、角色、上下文摘要、实际费用和 artifact 字节；只修改一组自洽摘要不能替换原始产物。

恢复复用已完成结果，只执行可证明未启动的剩余部分。无法确认完成的原生调用保持未结状态。`inspect()` 和恢复会重新验证 artifact；删除或修改 artifact 会拒绝复用。此路径的 `replay()` 使用 recorded outcomes，不再次调用模型或领域评估器；第三方 factory 本身仍必须遵守无外部调用的构造约定。

每个对照槽位有独立 provider、constructor、domain、executor 和 artifact 空间，使用冻结的初始任务、空 memory/grounding 和无父候选配方。主线耗尽可用预算后，已保留的对照容量仍受保护。对照候选不进入主线选择和准入。

实现与验证范围见 [M7 计划](superpowers/plans/2026-11-04-m7-execution.md)。完整 Git/SIGKILL、安装包示例、v9 外部货币审计及新版本验收通过之前，不应把此增量当作完整发布证书。
