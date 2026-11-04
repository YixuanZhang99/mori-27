# DeepSeek MLE pilot：第二次真实尝试

固定源码 `aedede3c2b78a5c2b57074c70d510af710f5af4e`，已通过独立 v70 本地验收。六个运行均已终止，三个有效提交完成官方评分，另三个因实际总 token 超额失败。该矩阵不构成完整有效的 baseline/full 对照实验。

| 任务 | 分支 | 官方分数（越小越好） | token | 费用上界（元） | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| spooky-author-identification | baseline | — | 62,830 | 0.405614 | 总 token 超额，失败 |
| spooky-author-identification | full | 0.4546 | 48,227 | 0.339802 | 有效提交，已评分 |
| leaf-classification | full | — | 62,856 | 0.365544 | 总 token 超额，失败 |
| leaf-classification | baseline | 0.88233 | 58,643 | 0.389644 | 有效提交，已评分 |
| nomad2018-predict-transparent-conductors | baseline | — | 63,502 | 0.437720 | 总 token 超额，失败 |
| nomad2018-predict-transparent-conductors | full | 0.06369 | 51,299 | 0.376456 | 有效提交，已评分 |

本次 24 个真实请求、347,357 token，费用上界为 2.314780 元。两轮共 33 个请求，累计 3.242064 元，原 200 元共享账本余量为 196.757936 元；无未结调用或预留。金额来自冻结高峰单价的保守核算，不是供应商实际账单。

## 核对范围与解释

独立审计重新核对六个 run 与汇总、每次请求的本地回执及共享货币账本、三份冻结提交的摘要、三份官方原始评分报告的摘要，并重新验证运行源码清单的全部 1,206 个文件。审计只导出明确白名单字段到本目录，不包含密钥、原始提示、数据表或模型生成程序。所有运行停止并冻结选中提交后，原执行器才进入官方评分循环。

三个失败的总量分别为 62,830、62,856、63,502，均超过 60,000-token 限额。运行器最终以 `provider receipts do not establish an in-budget single-backbone run` 拒绝它们。原因是请求仅用剩余总额度限制输出，未计入输入。剩余物理预留修复已消除了每次固定 12,000 的人为限制，但不能替代请求前的输入容量判断。`summary.json` 保留按已核验账本顺序排列的各次输入、输出与剩余额度。

例如 spooky/baseline 的最后一次调用前剩余 14,213；请求允许输出 14,213，实际输入 4,480、输出 12,563，共 17,043，累计超额 2,830。成本未截断、未删除，也未通过增加预算重新解释失败。

nomad/full 的官方离线报告标记 above_median 与 any_medal；这只是该冻结 MLE 任务的历史阈值比较，不代表已向 Kaggle 提交或获得实时排行榜奖牌。三对任务都缺少同一轮的有效完整配对，因此不计算 full 对 baseline 的效果提升，也不作统计显著性、跨任务优势或模块归因声明。baseline 仍是 greedy 搜索，并非 IID-RS 或 OpenEvolve 宿主。

新修复见 [请求容量计划](../../../docs/superpowers/plans/2026-11-04-provider-token-admission.md) 与 [输入上限研究](../../2026-11-04-provider-token-bounds.md)。输入估算会明确标为 estimate-only，正常预算拒绝需要保留已有候选；正式上限模式必须具备能覆盖输入与输出的服务契约。该修改未参与本次已冻结试跑，不能把后续本地回归成功写成本轮真实成功。
