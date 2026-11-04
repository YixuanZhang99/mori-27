# DeepSeek V4.1-Flash 与人民币 200 元 pilot：接入核验

核验日期：2026-11-04。范围：官方公开文档与本地 provider/pilot 源码；未读取秘密文件、未调用模型或账户 API、未改产品代码。研究开始时 HEAD 为 `dfe29cb4265fd939a203d587a57b523efbe52c36`，工作区有并行改动，以下源码观察对应读取时的工作文件，不能全归属该提交。

**实施结论：** 给当前 provider 增加明确 DeepSeek 协议配置，发送 `max_tokens`；人民币控制必须在每个 HTTP 请求前经过一个跨 run 的持久总账本。返回的 `deepseek-flash` 只能证明 API 返回标识一致，不能认证不可变模型权重版本。当前 token 上限和事后超额检查不足以兑现累计 200 元承诺。

## 官方事实

| 项目 | 当前官方约定 | 来源 |
| --- | --- | --- |
| 模型与端点 | `deepseek-flash`；OpenAI 格式 base URL `https://api.deepseek.com`；价格页当前映射为 `DeepSeek-V4.1-Flash-1017` | [模型与价格][price] |
| 请求限制 | `POST /chat/completions` 使用 `max_tokens`，允许 1–393216；未列出 `max_completion_tokens`，不可假设后者会生效 | [Chat Completions][chat] |
| 默认模式 | thinking 默认启用、effort 默认 high；建议明确发送 `thinking:{type:enabled}` 与 `reasoning_effort:high`，不依赖服务默认值 | [思考模式][thinking] |
| 采样 | thinking 下 temperature 不生效；保留 `temperature:0` 不能声称确定性 | [思考模式][thinking] |
| 输入/输出容量 | `/models` 文档示例给 Flash `context_window=1048576`、`max_output_tokens=393216`；context 定义包含输入与输出 | [Models][models] |
| 身份 | Chat 响应示例 `model=deepseek-flash`；`system_fingerprint` 描述后端配置，未承诺是不可变模型权重 ID | [Chat Completions][chat] |
| 高峰价 | 每百万 token：缓存命中输入 ¥0.04、未命中输入 ¥2、输出 ¥8；空闲价格减半，官方保留改价权 | [模型与价格][price] |

`thinking` 在手写 HTTP JSON 中是顶层字段；官方 SDK 示例使用 `extra_body` 是 SDK 的传参方式，不要把 `extra_body` 原样放入 HTTP body。现有纯文本、单消息、无 tools 路径不必回传 reasoning_content。输出上限包含 completion；usage 将 reasoning_tokens 放在 completion_tokens_details 中，应按 completion 的组成部分处理，不再额外叠加一次。[thinking][chat]

建议冻结明确的请求配置，例如 `model=deepseek-flash, stream=false, thinking=enabled, reasoning_effort=high, max_tokens=4096`。4096 是当前 pilot 的限制，不是已验证最优值；思考可能耗尽该额度导致回答被截断。若后续选 16384，应同时改变所有比较臂的冻结配置与预扣，不可只给失败的一臂临时加量。无需使用官方最大值来完成小额 pilot。

## usage 与金额

官方字段关系为：`total_tokens = prompt_tokens + completion_tokens`，`prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`；`prompt_tokens_details.cached_tokens` 是 cache-hit 的同义字段；`completion_tokens_details.reasoning_tokens` 是 completion 明细。只存总 token 会丢失差异定价与 reasoning 诊断信息。[chat]

**建议校验并持久化**原始 usage 中这些计数字段（非负整数，bool 不算整数），验证等式及 `reasoning_tokens <= completion_tokens`；按有明确依据的计量口径归档，不将缺失字段补成“实测零”。金额统一使用 Decimal 或整数微元，保留定价版本与计价单位。

按高峰价计算的费用上界：

```text
peak_bound_cny = (cache_hit * 0.04 + cache_miss * 2 + completion * 8) / 1_000_000
```

这是高峰费率折算上界，空闲时会高于实际账单；报告应叫“按冻结高峰价折算”，不能叫实际支付金额。若 prompt/completion 完整而 cache 明细缺失，可将全部 prompt 按未命中计价，明确 `cache_breakdown=unknown`；若仅有合法 total，可保守以 `total*8/1e6` 计上界，但不能伪造输入/输出明细。字段互相矛盾则停止并保留证据/预扣。后两种是实施建议，不是官方声称返回字段可省略。

不得按最终 `content` 字数计费：看不到的思考 token 也属于 completion；缓存命中 token 也属于 prompt。官方字符比例只是估计，文档明确实际以 usage 为准；离线 tokenizer 可辅助估算，不能未经匹配验证就当完整 HTTP message 的硬计量器。[tokens]

## 200 元累计控制的可执行方案

建立一个与本次授权绑定、放在单个 run/output_root 之外的 **campaign 人民币账本**。全部任务、seed、baseline/full、重启、手动重试和模型 smoke 都引用同一账本；新输出目录不得隐式创建新的 200 元额度。候选进程不可写该账本，也不可自行拿 key 绕过 provider。

每次真正 HTTP 请求前，在排他锁下核对旧记录、分配唯一 operation_id、核验余额并持久化 reservation，再允许发请求；接收有效 usage 后用绑定 request/response hash 的 receipt 结算。check-reserve 必须原子；只有“检查余额后稍后写文件”存在并发超售窗口。持久文件需要明确崩溃协议（文件与目录 fsync/原子替换或等价事务），不能承诺无限制断电恢复。

无需用字符估计获得较紧输入上界，可以采用极保守的**完整 context 输入预扣**：

```text
C = 1048576
O = 实际请求中的 max_tokens
R = (C * 2 + O * 8) / 1_000_000 CNY
已结费用上界 + 所有未结预扣 + R <= 200.000000
```

按官方文档的 context/output 限制和冻结高峰价，此式故意没有减去输出占用的 context，因而是松上界。[models][price] 计算例：O=4096 时 R=¥2.129920；O=16384 时 R=¥2.228224。正常完成后按 usage 缩小到费用上界并释放差额，临近总额边界时宁可拒绝新请求。若想在接入验证前不依赖较小 `max_tokens` 是否正确传到 API，可暂按官方最大输出预扣 ¥5.242880；这仍依赖官方容量约定，不是独立于服务端行为的绝对保证。

预算与恢复规则：

- HTTP 已开始但缺响应/usage，包括超时、连接断开、进程终止，保留全部预扣，标为 unresolved，禁止自动重发，并在 campaign 层阻断后续付费；不能以“没有收到文本”确认免费。
- 本地预扣已落盘但尚无可确认 dispatch 的崩溃窗口，也先保留预扣；只有可靠证明未发送才能释放。手动补偿必须有审计记录。
- 有效 usage 先结算，之后再验证模型身份、content、finish_reason；截断、内容过滤、空内容、错误模型等失败也已产生费用。`length` 不应被当成完整成功回答；重试是新的收费 operation。
- 恢复读取同一总账本并验证旧回执，不因启动新的 provider/新任务清零。账本缺失、损坏或引用不一致时拒绝启动，而不是当新实验从零算。
- 账本金额守恒与每 run 的 token 限额是两套约束。当前 token 限额允许单次输入使实际超额、事后停止；不能用它替代 HTTP 前人民币预扣。

**保证边界：** 这是“全部受控调用共用账本，API 遵守冻结的 token/价格约定，账本未被越权改写”前提下的本地准入保证；不是供应商账单的无条件封顶。官方可能改价，同账户其它程序可能消费，网络中断后实际账单可能暂不可知。定价/模型映射漂移应在下一批调用前复核；本地预算不覆盖未经过该 provider 的调用、付费数据/云计算或其它服务。Search/Fetch 另按请求收费，本 pilot 的纯文本 Chat 请求不要隐式接入它们。[price]

`GET /user/balance` 只返回账户当前充值/赠送余额及币种，不是某 campaign 的累计花费证明；共享账户的余额差不能直接归因给本实验。可作为额外对账信息，不能代替预扣账本。本次未调用该接口。[balance]

## 模型身份：不要把 alias 稳定写成 snapshot 锁定

至少分开记录：`requested_model`、响应 `model`、`system_fingerprint`（若有）、response id/created、官方当前版本映射及核验时间/来源。`/models` 的 name 是展示名；它也未提供权重 hash。更新日志明确同一 `deepseek-flash` 接口可更新到新版本。[models][updates]

因此报告可以声称“请求 deepseek-flash；本批响应标识一致；按 2026-11-04 官方映射为 V4.1-Flash-1017”，但要同时标注 `immutable_snapshot_verified=false`。fingerprint 改变可触发保守停止/分组；不改变也不能独立证明权重不变。不要伪造响应中的版本字段，或改请求 ID 为未经文档支持的 `DeepSeek-V4.1-Flash-1017`。

## 当前代码接缝与优先改动

2026-11-04 实施审查补充：上文“有效 usage 先结算，再验证模型身份”仅适用于返回身份仍受冻结定价 policy 覆盖的情况。不同或缺失的 DeepSeek alias 可能对应不同价格，必须先持久保存已知 token 回执，再拒绝并保留货币预留未结；不能按 Flash 价格结算未知模型。正确模型上的内容/截断失败仍须先结算。这一差异已有本地 HTTP 回归，未调用真实模型。

1. [provider.py](../m0/zoo/mle_bench_lite/provider.py)：`__call__()` 当前发送 `max_completion_tokens`；`manifest_binding()` 也冻结该通用字段。DeepSeek 路径需冻结实际 wire 参数、thinking/effort、人民币账本身份/费率；HTTP 前在此处预扣。现有 started/completed/receipt、无自动重试和未知用量停机值得保留。`validate_usage()` 当前只保留 total/prompt/completion，应在此边界独立补保存 cache/reasoning 明细，避免无关修改通用核心。
2. [pilot.py](../m0/zoo/mle_bench_lite/pilot.py)：`_plan()` 固定 temperature=0、4096 上限，并把 response model 描述为 actual snapshot；应改成真实模式及有限身份声明。`_command()`、`_validate_agent_summary()`、`_validate_provider_settings()` 同步冻结新参数；同一人民币账本传至全部 run。当前 output_root 要求为空，并非整份 pilot 已支持 resume；不要新增 resume 文案而无实现。
3. [composed_agent.py](../m0/zoo/mle_bench_lite/composed_agent.py)：provider 构造、agent contract 和 resume 身份必须绑定同一配置/账本；账本路径是配置引用，不是 API key 或其内容。
4. [usage_audit.py](../m0/zoo/mle_bench_lite/usage_audit.py) 与 [agent_common.py](../m0/zoo/mle_bench_lite/agent_common.py)：报告同时保留 known token、按费率算出的金额上界、未结预扣、未知调用和真实账单未核实标志。失败 evidence 不能消失；完成度不以 alias 相同冒充 snapshot 相同。

建议先用本地 HTTP fixture 验证 wire 参数、cache/reasoning 无重复计费、截断仍计费、人民币拒绝零 HTTP、unknown 跨新 run 仍阻断、并发 reserve 和恢复不重发，再进入已授权的有限真实 pilot。真实首调也走同一总账本；不需要为测试先读取/输出秘密。

读取时源码 SHA-256（工作区可能继续变化）：

```text
provider.py    5279771c903517634728e4450cd69439383bf022c113f437f808c3eb48099ef6
pilot.py       c8f8d4ad49ff0cda1ccfc8d0529abf1a51b4e37195c37d415801d9b24741a8bb
usage_audit.py 3994202d2323e36ff698ff51f5e55e6695ee7c9542d4f54bcbe9dd6495da8275
```

[price]: https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
[chat]: https://api-docs.deepseek.com/api/create-chat-completion/
[thinking]: https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/
[models]: https://api-docs.deepseek.com/api/list-models/
[tokens]: https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/
[balance]: https://api-docs.deepseek.com/api/get-user-balance/
[updates]: https://api-docs.deepseek.com/updates/
