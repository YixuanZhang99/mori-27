# DeepSeek MLE pilot：第一次真实尝试

2026-11-04 在固定源码 `5fa85d3ab7c4f643550ecaa2223a65231d7f7a86` 上执行。此前该 SHA 已通过本机完整 v69（39 检查），生产预检无缺失项。实验是三个任务、两个方案、seed 1 的诊断性试跑；不是完整 MLE-Bench Lite 或 OpenEvolve 宿主比较。

完整白名单报告见 [summary.json](summary.json)，逐 run 独立用量核验和失败归因见 [analysis.json](analysis.json)。原始数据、候选、匿名化密钥、模型凭据、完整账本和私有日志没有复制到这个目录。

| 任务 | 方案 | 官方评分 | token | 费用保守上界（元） | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| spooky-author-identification | baseline | 0.42599 | 40,105 | 0.281048 | 有效提交、已评分 |
| spooky-author-identification | full | 0.42352 | 27,698 | 0.201802 | 有效提交、已评分 |
| leaf-classification | full | — | 13,394 | 0.088012 | 首个候选评估前停止 |
| leaf-classification | baseline | — | 13,313 | 0.087832 | 首个候选评估前停止 |
| nomad2018-predict-transparent-conductors | baseline | — | 17,974 | 0.134252 | 首个候选评估前停止 |
| nomad2018-predict-transparent-conductors | full | — | 18,017 | 0.134338 | 首个候选评估前停止 |

合计 9 次真实模型请求、130,501 token；按冻结高峰费率折算的累计费用上界为 0.927284 元。六个 run 的本地回执与共享账本双向核对通过，无未结调用或预留；这不是供应商实际账单。原授权 200 元累计账本剩余 199.072716 元，后续尝试不得另开预算或清零。

## 发现与解释

所有六次运行都触发了相同的物理 token 预留超额停止。配置把 60,000-token 总预算除以五个候选位置，每个 operator 固定预留 12,000；推理模型的一次输入加输出可以超过这一数值。框架如实结算了已知用量并停止，而不是把多出的费用抹掉。leaf/full 的首条回执为 3,190 输入 + 10,204 输出 = 13,394 token，可直接在本地 HTTP 回归中复现。

spooky 两组在停止前已有候选，因此仍能冻结有效提交并完成官方评分；其余四组停止于 cycle 0，没有候选可提交。即使两条 spooky 官方评分有效，也不能把这次实验描述为完整运行了所有预定迭代或所有 full 算子。所有提交均先冻结，再进入官方隐藏评分。

spooky 的指标越小越好，full 相比 baseline 少 0.00247；单 seed、提前停止和其它任务失败均限制解释，不作统计显著、普遍优势或模块归因声明。这里的 baseline 是 greedy 搜索，既不是 IID-RS，也不是 OpenEvolve 宿主；B1/B2/C3 仍未达标。

nomad 两条回执的输出均达到 16,384-token 上限，但本版本没有保存响应 finish reason，不能仅凭计数断言具体结束原因。修复预留后仍须观察输出是否完整，不把“解决一个配置问题”当作保证全部任务成功。

后续按 [预留修复设计](../../../docs/superpowers/specs/2026-11-04-mle-reservation-design.md) 增加显式剩余额度预留，保留固定预留、真实超额停机和未知费用阻断。修复需通过独立审查、完整回归及新版本验收后再尝试；本目录的失败矩阵和原始结果不可被后续成功覆盖。
