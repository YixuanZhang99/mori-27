# AIDE / MLE：三任务真实小规模交付记录

预声明的三个任务 × seeds 0/1/2 共九组搜索和独立官方评分全部完成。90 个主候选中 70 个有效、20 个失败、0 个未完成；失败没有重跑替换，完整树、生成程序、冻结提交和费用凭证均保留。方法为 adapted AIDE，规格见 [C03](../../../docs/specs/classic/AIDE.md)。

## 配置与评分口径

运行源码固定为 `40b1e88272c401397617b03f88792108e0ae43d4`，搜索期间源码和依赖保持不变。官方 MLE-Bench 固定为 `507f92e1138bb6e40dac5c6ee7a6758e6424bf97`。来源、公共数据、评分器、依赖与模型配置的身份见 [预声明矩阵](pilot-v1/matrix-manifest.json) 和 [准备数据身份](pilot-v1/official-prepared-identity.json)。

每组最多 10 个主节点（含初始节点），三个 draft、p_debug=0.5、最大 debug depth=2；每个程序最多训练 120 秒。固定 split_seed=7；search_seed 控制框架选亲 RNG，不保证供应商使用远端随机种子。每组另设一个新会话的独立初始 control，仅用于开发集 sanity check，并非等预算 baseline。

模型是可变别名 `deepseek-flash`，reasoning_effort=low，输出上限 16384；未验证不可变模型快照，因此不把用户所说的版本名当成已验证供应商身份。全部调用共用原 ¥200 campaign。

下表所有 loss 均越低越好。dev 只用于选定候选；本地 final 使用已冻结的预测和独立切分；全部搜索结束后，官方评分器对同一冻结提交单次评分。分类任务为 log loss，nomad 为目标 RMSLE 的平均值。三个评分列的样本范围不同，不能相互替代。

| 任务 / seed | 有效/尝试 | dev loss | 本地 final loss | 官方 score | API 费用上界（元） | 搜索秒数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| spooky / 0 | 9/10 | 0.374249 | 0.372388 | 0.37105 | 0.820256 | 816.0 |
| spooky / 1 | 9/10 | 0.368906 | 0.360914 | 0.35603 | 0.907644 | 819.5 |
| spooky / 2 | 8/10 | 0.389344 | 0.384664 | 0.38289 | 0.794072 | 604.9 |
| leaf / 0 | 6/10 | 0.078518 | 0.036465 | 0.08681 | 1.177482 | 932.1 |
| leaf / 1 | 8/10 | 0.035596 | 0.011733 | 0.05811 | 1.155326 | 767.1 |
| leaf / 2 | 7/10 | 0.065295 | 0.037264 | 0.09785 | 1.136916 | 734.5 |
| nomad / 0 | 8/10 | 0.070153 | 0.061657 | 0.06282 | 1.188600 | 1179.7 |
| nomad / 1 | 7/10 | 0.069764 | 0.061236 | 0.06221 | 1.271694 | 974.8 |
| nomad / 2 | 8/10 | 0.067547 | 0.058287 | 0.06206 | 1.271246 | 1042.0 |

同配置三次官方 score 的描述统计：

| 任务 | 均值 | 样本标准差 | 固定评分器阈值判断 |
| --- | ---: | ---: | --- |
| spooky | 0.369990 | 0.013461 | 三组均高于历史中位数，未达奖牌阈值 |
| leaf | 0.080923 | 0.020514 | 三组均高于历史中位数，未达奖牌阈值 |
| nomad | 0.062363 | 0.000403 | 铜 / 银 / 银（seeds 0 / 1 / 2） |

这些奖牌标记是固定 MLE-Bench 评分器对历史阈值的映射，不是新的 Kaggle 在线提交或实际获奖。九组提交均被评分器判定有效。本结果只覆盖三个预选任务，不能外推完整 MLE-Bench 奖牌率，也没有等预算搜索对照来证明优化增益或论文区间复现。

## 机制、失败与费用

真实树包含 draft 27 次、improve 57 次、debug 6 次；debug 中 4 次成功。状态统计为 {'ok': 70, 'timeout': 4, 'failed_to_run': 16}。每个失败的候选、父代、算子与原始反馈可在各 cell 的 journal/programs 中核查。另有两个独立 control 失败（spooky seed 2、leaf seed 2），未从控制组记录中删除。

本批费用上界 ¥9.723236（含 control），原 campaign 累计 ¥30.891206，剩余 ¥169.108794；无未决调用、预留或保护违约，见 [账本快照](pilot-v1/campaign-after.json)。上界按原冻结输入/输出 token 单价 2/8 micro-CNY 独立重算，不是供应商发票，也不含本机计算费用。

原始 AIDE 的完整工作负载、默认大预算与模型配置并未复现。当前适配限制为 CSV 特征、固定 public-training 切分、十节点搜索、受限 Python 沙箱、按任务指标选优、隔离官方终评；L1 Journal 使用实际公开开发集错误和已生成计划，knowledge/cross-run imports 关闭。每个 method report 记录 reference_revision、recipe_revision、fidelity 与 deviations。

## 重算与验收

九组记录回放、独立物理提交审计、费用审计均通过；官方评分全部完成后，另一个纯 JSON reducer 从原始日志重算候选选择、失败分母、费用，并绑定原始 grader report 核对官方 score。它不重新计算私有标签上的 loss，也不把哈希当作外部数字签名。数据 CSV、密钥和匿名化映射不随证据包发布。

```bash
python research/experiments/2026-11-05-aide-mle/recalculate.py \
  research/experiments/2026-11-05-aide-mle/pilot-v1
```

证据入口：[完整九组汇总](pilot-v1/summary.json)。每组目录包含 run manifest、原始 journal、method report、费用凭证、所有程序、选中程序、实际 submission.csv、独立评分 audit 与 raw report。最终候选检查与合入状态见 [PR #7](https://github.com/YixuanZhang99/mori-27/pull/7)。
