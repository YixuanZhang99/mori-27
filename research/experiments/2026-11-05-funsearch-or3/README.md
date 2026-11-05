# FunSearch / OR3：真实小规模运行记录

方法为 adapted FunSearch。三次运行均完成冻结终评与记录回放，33 个候选中 31 个有效。此页报告独立 v3 批次的预声明 seeds 0/1/2，所有失败均保留。此前 v1 格式冲突与 v2 高推理强度截断记录分别保存在 [format-conflict-v1](format-conflict-v1/README.md) 和 [high-effort-v2](high-effort-v2/README.md)，不与 v3 混算均值。

## 配置与成绩

实际运行源代码固定为 `1462fb373b4630504c82c9d5f1fcf9b2c9fb7078`；运行中未修改源码。参考方法、九模块职责和差异见 [C02](../../../docs/specs/classic/FUNSEARCH.md)，运行命令见 [provenance](../../../m0/zoo/funsearch_binpacking/PROVENANCE.md)。

官方固定 OR3 notebook 按排序 ID 分为 dev/held-out 各 10 个实例，完整 hash 在每个 manifest 中。两个岛、每个 seed 一个初始程序加最多 10 个提案，输出上限 16384、reasoning_effort=low、每 partition 执行限时 30 秒。模型为可变别名 `deepseek-flash`，未验证不可变快照；seed 控制框架抽样，不控制供应商随机性。每个 seed 的主搜索和独立初始 control 使用相同模型配置。

分数以平均使用箱数呈现，越低越好。固定 best-fit 的 dev/held-out 为 213.9/210.1；主程序由 dev 冻结选定后才评 held-out，不能根据最终分数重新选择。

| Seed | 有效/尝试候选 | 选中程序 dev | 冻结 held-out | 初始 control dev | 回放 | API 费用上界（元） |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| 0 | 10/11 | 213.8 | 210.1 | 213.9 | 通过 | 0.485782 |
| 1 | 11/11 | 213.9 | 210.1 | 213.9 | 通过 | 0.329914 |
| 2 | 10/11 | 213.9 | 210.1 | 213.9 | 通过 | 0.283230 |

Seed 0 在第 9 次提案得到 dev 213.8 箱，其余两组保留初始程序。三组 held-out 都与固定 best-fit 持平：开发集的小幅改善没有在本次留出数据上体现，尚无泛化收益证据。

相同 v3 配置的三次完整 held-out 均值为 210.100000 箱，样本标准差为 0.000000 箱。该统计仅描述本次小规模运行，不代表论文区间复现。

## 失败、费用与方法边界

- Seed 0：状态 completed，已完成失败 1、未完成 0，候选失败率 9.09%；供应商响应 finish_reason=length / incomplete_output，16384 completion tokens 全用于推理；已结算并保留该失败，不重试。
- Seed 1：状态 completed，已完成失败 0、未完成 0，候选失败率 0.00%；供应商不完整响应 0 次。
- Seed 2：状态 completed，已完成失败 1、未完成 0，候选失败率 9.09%；供应商响应完整；第 5 次提案在隔离评分中记录 ValueError。该程序含正无穷输出分支，不满足有限优先级向量契约；失败未进入供亲或终选。

本批费用上界 ¥1.098926，其中 control ¥0.007276。加上此前原 campaign 的 ¥20.069044，批次结束累计 ¥21.167970，剩余 ¥178.832030。费用按原冻结上界单价重算，未核对供应商发票，也不含本机计算费用。

三批 v1/v2/v3 的全部费用上界合计 ¥3.443880，历史失败未从项目累计中扣除。批次结束无未决调用、预留或保护违约，见 [账本快照](low-effort-v3/campaign-after.json)。

独立初始 control 只作 dev sanity check，不是等预算搜索对照。模型生成初始程序、两岛、十提案、独立 Python RNG、每五次成功登记重置弱岛，均是明确的适配。采样簇目标为最后一个排序 case 的分数；最终 incumbent 使用 dev mean，两者不混称。程序只可修改 priority(item, bins)，隔离 worker 不接收整份数据或最终标签。

## 重算与验收

真实选亲轨迹中，seeds 0/1/2 分别有 3/4/4 次选择使用非 incumbent 程序；前两组各有一次实际选择较差但有效的父代。每组发生两次弱岛重置，这些真实轨迹覆盖了岛屿搜索的关键步骤。

原始 journal、manifest、report、所有生成程序、选中程序、逐 case 分数、费用凭证和供应商结果元数据保存在 [low-effort-v3](low-effort-v3/summary.json) 的 seed-N 子目录。供应商结果通过 response digest 与原费用凭证对应。以下命令只核对已保存证据，不读取密钥、不调用模型、不执行生成程序：

```sh
python3 research/experiments/2026-11-05-funsearch-or3/recalculate.py \
  research/experiments/2026-11-05-funsearch-or3/low-effort-v3
```

F1 岛屿簇/长度采样及重置由 population/selection/coordinator 行为测试覆盖；F2 目标函数边界与失败费用由 validator/sandbox/framework 测试覆盖；F3/F5 由本批三个真实 seed 的原始证据与费用重算支持；F4 由冻结终评记录及 holdout 泄漏/恢复测试支持；F6 由 population runtime 的非最优候选保留/历史篡改测试和真实选亲轨迹支持。记录回放与离线重算分别报告，后者不替代前者。

最终候选检查及合入状态以 [PR #6](https://github.com/YixuanZhang99/mori-27/pull/6) 为准。工程验收、小规模实测、性能提升和论文复现是不同结论。
