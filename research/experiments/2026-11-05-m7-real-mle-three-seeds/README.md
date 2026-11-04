# M7 真实 MLE 三任务：两个批次、三个本地 seed

2026-11-05，源码提交 `a6b58267b7447fbb1c40e47875d0d2ca5534e37d` 在
三个 MLE-bench 任务上完成 18 次真实模型运行。官方 grader 接受了全部 18
份提交。官方任务和 leaderboard 快照固定在 [MLE-bench `507f92e`](https://github.com/openai/mle-bench/tree/507f92e1138bb6e40dac5c6ee7a6758e6424bf97)。

指标均为**越低越好**；差值为 full 减 baseline。

| 任务 / 指标 | 本地 seed | baseline | full | 差值 |
| --- | ---: | ---: | ---: | ---: |
| Spooky / log loss | 1 | 0.40538 | 0.42521 | +0.01983 |
| Spooky / log loss | 2 | 0.41634 | 0.42550 | +0.00916 |
| Spooky / log loss | 3 | 0.40024 | 0.41847 | +0.01823 |
| Leaf / log loss | 1 | 1.06263 | 0.26220 | −0.80043 |
| Leaf / log loss | 2 | 0.81291 | 0.09109 | −0.72182 |
| Leaf / log loss | 3 | 0.67282 | 1.01535 | +0.34253 |
| NOMAD / 两个 RMSLE 的平均值 | 1 | 0.06501 | 0.06403 | −0.00098 |
| NOMAD / 两个 RMSLE 的平均值 | 2 | 0.06232 | 0.06290 | +0.00058 |
| NOMAD / 两个 RMSLE 的平均值 | 3 | 0.06446 | 0.06268 | −0.00178 |

这是一份三任务诊断结果，不是完整 MLE-Bench Lite 成绩，也不建立统计显著性。
full 在 Leaf 和 NOMAD 各有两个 seed 更好、一个更差；在 Spooky 三个 seed
均更差。baseline 使用 greedy 与 draft/reflective，full 使用 population 与
draft/crossover；两者均启用治理，因此这些结果**不能单独证明治理收益**。

## 批次、可比性和限制

seed 1 是先完成的六次试跑；seed 2 和 3 是看到 seed 1 结果后另行冻结的
十二次扩展。项目交付计划在 seed 1 之前已列出扩展到三个 seed 的方向，
但这不是一个在任何结果出现前一次性冻结的 18 次实验。两个批次的源码、
任务、官方版本、模型别名、预算、迭代数和评分方法一致；批次内的 arm
顺序按各自 seed 列表交替，因此不等同于一次性运行 `[1, 2, 3]` 的完整
顺序。逐次顺序和结果可从 [`results.json`](results.json) 与原始记录追溯。

请求及返回的模型标识均为可变别名 `deepseek-flash`，未验证不可变模型
快照；本地 seed 用于数据与搜索，未发送给模型提供方。每次运行限 3 次搜索
迭代、300 万 token、600 秒墙钟时间和 120 秒单候选时间。扩展批次与部分
本地工程验证并行，逐次墙钟时间不宜用于严格的性能或成本因果比较。
所有候选均在各自批次的官方评分前冻结；未用隐藏评分选择候选。

18 次运行记录 **1,257,687 tokens**；共享账本对这 18 次的结算上界合计
**8.681424 元**。加上此前失败尝试，原 campaign 累计结算上界为
**12.709140 元**，总限额 200 元；核验时预留和未决调用均为零。这是按
保守价格计算的上界，不是供应商账单。先前失败尝试继续保留在
[attempt 1](../2026-11-05-m7-real-mle-attempt-1/) 和
[attempt 2](../2026-11-05-m7-real-mle-attempt-2/)。

两个批次均在运行后独立检查了原始费用凭据、物理结算、所选预测、冻结
提交哈希、记录回放和官方评分报告哈希；这些核验未发出新的模型请求，
也未修改共享账本。逐次费用、耗时、成绩、提交和评分报告哈希见
[`results.json`](results.json)。原始数据、运行目录和提供方凭据保留在本机。

## 复现入口

需要固定版本的官方 MLE-bench、已授权并准备的数据、同一提供方别名以及
经授权的现有 CNY 账本。以下命令只做无付费预检；去掉 `--preflight-only`
才会启动付费运行，且结果可能变化：

```sh
PYTHONPATH=m0 python -m zoo.mle_bench_lite.pilot \
  --runtime m7 --official-root /path/to/mle-bench --data-root /path/to/data \
  --model deepseek-flash --token-budget 3000000 --time-limit 600 \
  --solution-timeout 120 --iterations 3 --seeds 2 3 \
  --spending-ledger /path/to/existing-campaign.db \
  --output-root /path/to/new-preflight --preflight-only
```

需要按仓库的 MLE 配置准备本地 provider 环境；不要把密钥放入命令行或报告。
