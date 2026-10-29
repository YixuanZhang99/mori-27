# v58 准入、计量、预算与 seccomp 修复

本说明对应 2026-10-29 导入审查中的四类问题。原审查报告、复现输出及 v1–v57 的验收证书和 journal 保持历史原样；当前行为以源码、回归测试和当前提交的 v58 Actions 结果为准。

## 准入证据

原实现将 incumbent 样本转为字典，重复 ID 会被覆盖，候选重复 ID 又可能重复计票。现在准入和执行边界都验证：候选 ID、head SHA、评估器版本非空，样本非空且 ID 唯一，评分只能为整数 0/1（拒绝 bool、浮点数和字符串）。最终比较必须使用相同样本集合和评估器版本；乱序不影响比较。明确的浅层 cascade 或扩展否决可以拒绝不完整结果，不能借此通过准入。

同步执行、批次执行、检查点与原生结果恢复均重新绑定预期候选/head/评估器身份。评估器升级通过固定 anchor 的 meta-gate 单独校验，合法的版本升级仍可发生。

## 成本计量

`last_usage` 是调用适配器的明确契约：每次调用必须提供 `{"total_tokens": 非负整数}`，不允许 bool、字符串、负数、NaN 或无穷值。真实 0 可结算为 0；没有 usage 不是 0。若同时提供 prompt/completion 两项，其和必须等于 total。

框架在调用前清空旧值，在调用后消费一次。预留金额仅用于预算报价，不能替代实际用量。缺失或非法用量抛出 `UsageError`，停止准入及结算；已经提交执行的批次预留不会在异常清理中被退还，检查点也不能将其伪装为已完成。并发执行会等待已派发工作结束后再传播异常，避免关闭线程池时掩盖成本错误。

已知成本的失败仍计费，包括内容格式错误、显式报告用量的外部失败，以及 GSM8K/cascade 多次调用中带有效用量的失败。未知成本保持未决，需核实提供方或外部适配器的用量证据后再处理，不能直接重试或删掉 journal 释放预算。这不提供跨远端服务的 exactly-once 保证。

自定义本地确定性评估器应在每次调用中显式设置零用量。离线 Toy proposer 每次报告 **1,000 模拟 token**，不是提供方账单；其他离线示例也使用显式模拟用量。

账本 stamp 不再固定写入 `mock/mock-v1/t1/p1/2026-10-26`。默认读取 proposer 的 supplier/model，未知 tokenizer、价格表和日期标为 `unavailable`。需要完整计价上下文时，可给 `Framework(...)` 或 `Framework.from_profile(...)` 传入 `accounting_stamp=AccountingStamp(...)`；该上下文写入 run_start，在恢复和 replay 中保留，冲突声明被拒绝。token 账本不会自行推算美元账单，多模型实际价格仍需调用方明确提供计价数据。

## 预算账本

重复的未结束 intent 不能再次预留。请求、实际消耗及币种数值在状态修改前验证；负数、非有限数值、bool 和字符串被拒绝。单币账本会在预留之前拒绝多币篮子或不一致的 token 数量。

新预留记录绑定原账户及完整 intent 的 SHA-256；同名 intent 改账户、金额或身份，不能结算或释放原预留。多币结算先验证整个成本向量，再修改任何币种。恢复在临时状态中完成全量校验，失败不会留下部分恢复状态；部分结算、release、reconcile 和重复接管都有回归覆盖。

旧 journal 没有完整 intent 指纹时，只能检查其实际保留的账户、金额和币种字段；不会补造历史指纹。旧的不正确计量记录不会被 v58 自动更正或重写。

## seccomp v2

Linux x86_64 的 seccomp v1 只比较 audit architecture 和原生 syscall 号。x32 共享同一 audit architecture，原规则会漏掉带 `0x40000000` 标记的编号。v2 在原生 denylist 之前拒绝全部 x32 标记编号及旧内核的原始 512–547 区间；错误 audit architecture 仍终止进程。

两条交付路径（直接 prctl 和 Bubblewrap memfd）均有真实 Linux syscall 回归，Mac 则执行 BPF 指令边界测试。旧版本、重算 hash 或重新标号的旧过滤器不能作为 v2 启动。尚未完成的旧策略进程在恢复时被停止并拒绝接管；已完成的历史结果保留原版本证据，不改写为 v2。

这仍是危险 syscall denylist。外部 proposer 本身仍是受信任适配器，保留网络及环境访问；此次变更不构成文件系统、凭据隔离、完整 allowlist 或 cgroup 限额。技术依据见 [Linux seccomp(2) Filters](https://man7.org/linux/man-pages/man2/seccomp.2.html)。

## 验证与证据

Mac 使用 `make check`，Linux 使用 `make accept-linux`。v58 保留原有完整测试、崩溃恢复与安全执行场景，另加入上述负向回归；任何 skip/xfail 均失败。

验收包装器在临时副本运行，首次 v58 可以没有证书/journal。它要求本次产生新的成功证书及恰好一条匹配的 journal，并确认全部源历史记录未变。日志、证书和摘要保存在 `artifacts/linux-acceptance/`，由 Actions 上传。通过标准是实际运行结果，不以测试数量代替安全或真实 benchmark 成绩。
