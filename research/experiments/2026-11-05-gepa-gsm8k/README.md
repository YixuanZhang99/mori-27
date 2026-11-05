# GEPA / GSM8K：真实小规模运行记录

日期：2026-11-05。方法：**adapted、单组件 GEPA**。公共 Framework 已在真实模型上完成反思、同批父子比较、冻结终评及记录回放。本批预声明 seeds 0/1/2 的尝试全部保留：**1 次完整终评、2 次终评失败**。这证明存在可运行的完整路径，尚不足以声称稳定 benchmark 交付、优化增益或论文成绩复现。

## 配置与结果

源代码固定为 `d950a4f76d5316a26e4619100ee59bd879266af5`。后续 `b558143` 只修复离线 fixture 在无 `.git` 的验收副本中的启动问题；本批实际运行代码未中途改动。方法规格、参考 revision 与允许差异见 [C01](../../../docs/specs/classic/GEPA.md) 和 [provenance](../../../m0/zoo/gepa_gsm8k/PROVENANCE.md)。

数据使用固定版本 GSM8K：train 64、validation 64、test 128，原始行 ID 在切分前确定，完整内容 hash 见 [data-manifest.json](data-manifest.json)。每个 seed 为一个初始 prompt 加 **一次**反思提案，minibatch=8；不是标准 pilot 的十次提案搜索。模型为可变别名 `deepseek-flash`，thinking enabled / reasoning_effort high；未验证不可变模型快照。seed 控制框架抽样，不控制供应商随机性。

| Seed | 输出 token 上限 | 选中 prompt 的 validation | 冻结 test | 独立初始 control 的 validation | API 费用上界（元） |
| --- | ---: | ---: | --- | --- | ---: |
| 0 | 4096 | 62/64（96.88%） | 失败；完成 100 题后下一请求截断 | 61/64（95.31%） | 1.135556 |
| 1 | 16384 | 61/64（95.31%） | **127/128（99.22%）** | 构造失败，无成绩 | 0.605784 |
| 2 | 16384 | 61/64（95.31%） | 失败；完成 119 题后下一请求截断 | 61/64（95.31%） | 0.909070 |

全部三次记录回放通过，没有为回放发送模型请求。三次训练配对分别为 8/8 对 7/8、8/8 对 8/8、8/8 对 8/8；严格改进规则全部拒绝，故最终选中的均是各自初始 prompt。**不能把 99.22% 归因于 GEPA 优化。** 初始 control 仅作 validation sanity check，并非等预算搜索或 final-test baseline。

## 失败与费用

- Seed 0 的失败响应为 `finish_reason=length`，4096 completion tokens 全为 reasoning tokens，没有最终答案。费用已知并结算；不报告部分题目准确率作为完整 test 成绩。
- 观察到该 smoke 失败后，明确把后两次输出上限改为 16384。Seed 2 仍发生同类截断，16384 completion tokens 全用于推理。两种配置分开保留，不计算“三 seed 均值/标准差”，不继续提高上限挑选成功结果。
- Seed 1 的 control 返回纯文本而非构造器要求的 JSON，单次构造失败；该成本保留，没有用主搜索或其他 seed 的成绩填补对照。
- 共 **726 次**模型调用（248 / 211 / 267），本批费用上界 **¥2.650410**。包含此前试验后，同一 ¥200 campaign 的累计上界为 **¥17.724090**，剩余 **¥182.275910**；无未决调用、未释放预留或保护违约。见 [campaign-after.json](campaign-after.json)。这些是冻结上界价格计算的 API 费用，未核对供应商发票，不是本机计算费用。

当前冻结评分协议遇到不完整模型输出会使该次评价失败，不自动重试。后续若要将可确定的“未答”作为逐题 0 分继续，必须另行明确评分策略、区分已结算输出失败与未知费用/身份错误，并用新 evaluator 版本验证；不得回改本批分数。提高有效终评率、更充分的多提案搜索、同配置多 seed 和等预算对照仍是未完成项。

## 历史计量标记勘误与交付修复

本批 `d950a4f` 的领域评价将 provider 返回的总 token 数存入 `CostVec.tokens_in`，但契约错误地沿用 `split` 标记。当前实现已改为 `total_only`，明确该数值不能解释成输入 token 数；历史压缩证据保持原样。费用凭证中的输入/输出用量来自 provider 的独立详细 usage，报告费用由这些凭证重算，因此本项元数据修正不改变本批费用或成绩。

当前交付还修复了两处边界：同一运行在响应已保存、费用尚未结算时可恢复结算，新运行仍拒绝未决费用；批次 token 预留使用 provider 声明的实际单次上界，覆盖支持的 65,536 输出上限。新增回归覆盖终评冻结、费用结算和终评完成后的中断恢复，检查不重复调用或计费。这些修复没有重新运行或重新解释上述冻结尝试。

## 重算与运行

无需密钥即可从已保存的逐题证据、调用记录和费用凭证重算结果：

```sh
python3 research/experiments/2026-11-05-gepa-gsm8k/recalculate.py
```

每个 `seed-N/` 保存原始 `method-report.json.gz`、调用前冻结的 `run-manifest.json`、profile、压缩的逐项 evaluation、该运行的费用凭证与原始 journal；`summary.json` 为摘要。脚本核对 journal hash、调用/费用覆盖、固定上界单价及完整终评的 128 项成绩。它重算报告，不冒充重新运行模型或独立执行全部 Framework replay。

工程本地完整检查、关键机制与故障恢复验证、独立审查均已执行；一次 Linux CI 暴露的无 Git fixture 启动问题已复现并以回归测试修复，16 项 GEPA 相关测试通过。最终候选 CI 和合入状态以 [PR #5](https://github.com/YixuanZhang99/mori-27/pull/5) 为准，不用旧提交的成功替代当前检查。

从公开入口开始离线运行，或准备固定数据后使用自己的凭据与原累计账本，见 [运行说明](../../../m0/zoo/gepa_gsm8k/PROVENANCE.md)。本批原始私有运行目录及原 campaign 留在本机；未复制凭据文件。数据来源为 [openai/grade-school-math@3101c7d](https://github.com/openai/grade-school-math/tree/3101c7d5072418e28b9008a6636bde82a006892c)，MIT license。
