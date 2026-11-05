# DeepSeek 小规模试跑与累计人民币预算

实现位于 `m0/zoo/mle_bench_lite/`，不向六概念内核加入服务商或货币特例。测试、环境预检和预算验证不代表真实外部模型成绩。

## 一次授权，一个总账本

用户本轮累计上限为人民币 200 元。三个任务、baseline/full、重启、新输出目录和任何补跑必须使用同一个已有 `CampaignBudget` 文件。运行时不会自动建账、清零或在文件丢失后重建。

仅授权执行者可以在已有的可信私有目录中显式初始化一次：

```python
from zoo.mle_bench_lite.cny_budget import CampaignBudget
CampaignBudget.create("/trusted/private/campaign.db", limit_micro_cny=200_000_000)
```

文件权限为 0600；路径已存在时拒绝创建，包括上次初始化中断留下的文件。账本必须在所有 pilot 输出目录之外，不能位于候选可见的系统目录、workspace 或 agent_artifacts 下。它不是 API key；凭据继续由可信父进程从仓库外私有配置载入。候选的 Bubblewrap/seccomp 环境清空凭据并禁止网络。

## 请求前预留与结算

金额使用整数微元，1 元 = 1,000,000 微元。按 2026-11-04 核验的 Flash 高峰价格冻结输入 2 微元/token、输出 8 微元/token。保守上界不扣缓存折扣；合法缓存和 reasoning 明细仍保存在回执中，reasoning 不重复计费。

每次请求先预留 `1,048,576 × 2 + output_allowance × 8` 微元。实际 output allowance 是冻结输出上限和该 run 剩余 token 预算的较小值；16384 输出时预留 2.228224 元。余额检查与预留在同一 SQLite 事务中提交，之后才允许 HTTP。同一 campaign 有一个未结请求就拒绝新请求；这适用于串行 pilot，不是通用并行池认证。

有效 prompt/completion 计数及其总数、明细关系和计价模型都核验后，按实际用量缩小为费用上界并释放剩余预留。空代码、截断或非 `stop` 结束仍先结算已知用量再拒绝结果。网络中断、缺失/矛盾用量或返回错误模型时，保留预留并阻断后续调用；已知 token 不抹为零。没有自动重试或自动释放未知费用的路径。

`settled_upper_bound_micro_cny` 是按冻结费率折算的上界，`invoice_verified=false`，不能描述成供应商实际账单。保证依赖 API 遵守冻结价格和容量约定；账户中其他程序消费、服务端违反约定和恶意拥有者整体回滚账本不在保证范围内。下一批试跑前重新核验官方价格，不静默修改旧 policy。

## 请求与身份

官方 `https://api.deepseek.com` 端点必须配置已有账本。模型请求为 `deepseek-flash`，使用 `max_tokens`、`thinking={"type":"enabled"}`、`reasoning_effort="high"`、`stream=false`。两个比较方案都冻结输出上限 16384，不发送 thinking 模式下无效的 temperature 参数，也不声称确定性。

请求 alias、响应模型、可用的 response id/created/system_fingerprint，以及附来源和核验日期的官方版本映射分别记录。alias 一致只能证明返回标识一致，不能证明权重固定；`immutable_snapshot_verified=false`。历史兼容字段 `backbone_evidence_complete` 也只表示响应标识证据完整，新的明确字段为 `response_identifier_evidence_complete`。

## 入口与独立审计

可信父进程准备好凭据和锁定运行环境后，先运行零模型预检：

```bash
python -m zoo.mle_bench_lite.pilot \
  --official-root /trusted/mle-official --data-root /trusted/mle-data \
  --model deepseek-flash --token-budget 60000 --seeds 1 \
  --iterations 4 --time-limit 600 --solution-timeout 120 \
  --spending-ledger /trusted/private/campaign.db \
  --output-root /trusted/preflight-evidence --preflight-only
```

实际运行移除 `--preflight-only`、换一个空输出目录，保留同一 `--spending-ledger`。CLI 和 `run_mle_cloud.py` 也接受可信父进程设置的 `MLE_CNY_LEDGER_PATH`。普通 GitHub-hosted 临时 runner 没有持久账本时，DeepSeek 预检拒绝执行；仅有 GitHub Secrets 不等于配置了跨运行累计预算。

每个 agent contract、请求 started 记录和回执绑定 campaign/policy 身份。预留同时保存可信 token_usage 目录规范绝对路径的 SHA-256 作为 run_id，不保存原路径或秘密；它不会因本地回执丢失而消失。迁移目录恢复不在当前协议范围中。

`audit_usage(..., spending_ledger=ledger)` 双向核对该 run 的账本调用集合与本地记录，再核对请求/响应 hash、输出预留、用量明细和结算。重算本地 hash 或删除整组回执均不能把证据变完整。预留后、写 started 前崩溃仍被归入原 run；已结费用从账本保留。未知费用阻断剩余运行和新输出目录。所有提交仍在官方隐藏评分前冻结。

公开 summary 只导出允许的金额和完整性字段，不导出完整操作账本、候选源码、原始数据或私有日志。既有 token 限额仍可能因输入导致单次超额，不能替代请求前货币预留。

验证状态见 [实施计划](superpowers/plans/2026-11-04-deepseek-budget.md)，服务事实来源见 [接入研究](../research/2026-11-04-deepseek-pilot.md)。完成软件验收前不启动本轮付费试跑。
