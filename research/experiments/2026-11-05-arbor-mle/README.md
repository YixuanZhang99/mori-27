# Arbor / MLE：三任务真实小规模交付记录

预声明的三任务 × seeds 0/1/2 共九组搜索及官方评分全部完成，九份提交均有效。规格冻结、机制接通和小规模实测已完成；等预算方法对照、完整 benchmark 与论文公开区间复现未完成。规格见 [C04](../../../docs/specs/classic/ARBOR.md)，命令见 [任务入口](../../../m0/zoo/mle_bench_lite/README.md#c04-arbor-adapted-recipe)。最终证据提交的 CI 与合入状态见 [PR #8](https://github.com/YixuanZhang99/mori-27/pull/8)，本报告不把运行源码的检查当成后来提交已通过的证明。

## 协议与来源

运行源码固定为 `aeeb6fd471d9b1532d8dcd495e6479983b367efc`；搜索至官方评分完成期间源码和依赖不变。方法参考为 RUC-NLPIR/Arbor `a633f56f2601387402194481e846e3375e822afa`，recipe 为 `arbor-mle-v4`，fidelity 为 `adapted`。官方 MLE-Bench 固定为 `507f92e1138bb6e40dac5c6ee7a6758e6424bf97`。逐项身份见 [预声明矩阵](pilot-v4/matrix-manifest.json) 和 [准备数据身份](pilot-v4/official-prepared-identity.json)。

每组最多 5 个主候选、树深 2、每轮最多 3 个新假设；同一冻结假设最多 2 次构造尝试，单程序训练上限 120 秒。准入严格要求 margin=0 的改善，最多 3 次准入调用。开发集收敛规则 min_samples=4、patience=3；leaf seed 1 在 4 个有效样本后因连续三次未改善停止，因此实际分母为 44 次尝试，而非强补第 45 次。每组另有一个新会话独立初始 control，九个均有效，但它们不是等预算搜索 baseline。

split_seed=7 固定。search_seed 标记独立重复与 control 调度；规划器没有本地随机选亲器，也未向模型施加远端 seed。模型使用可变别名 `deepseek-flash`、reasoning_effort=low、输出上限 16384；不可变模型快照未验证。全部调用继续使用原累计 ¥200 campaign。

所有 loss/score 越低越好。dev 用于开发和触发准入，admission 决定主干；本地 final 在选择冻结后评分；全部搜索结束后，官方 grader 对同一冻结提交单次评分。分类为 log loss，nomad 为两个目标 RMSLE 的均值。各列样本范围不同，不能相互替代。

## 全部预声明结果

主候选：38/44 有效，6 失败，0 未完成。
全部失败保留；dev 最优与最终准入 trunk 分开列出。官方 score 来自搜索结束后的独立评分。

| 任务 / seed | 有效/尝试 | 最优 dev loss | 准入 trunk dev loss | 本地 final loss | 官方 score | API 费用上界（元） | 搜索秒数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| spooky-author-identification / 0 | 3/5 | 0.451215 | 0.451215 | 0.465294 | 0.469540 | 0.587382 | 423.4 |
| spooky-author-identification / 1 | 4/5 | 0.417121 | 0.417121 | 0.421689 | 0.416170 | 0.739256 | 656.3 |
| spooky-author-identification / 2 | 5/5 | 0.453980 | 0.453980 | 0.470874 | 0.474280 | 0.693364 | 512.0 |
| leaf-classification / 0 | 5/5 | 0.064618 | 0.064618 | 0.077967 | 0.126020 | 0.792522 | 477.1 |
| leaf-classification / 1 | 4/4 | 0.108261 | 0.108261 | 0.094212 | 0.167530 | 0.559858 | 356.2 |
| leaf-classification / 2 | 3/5 | 0.152081 | 0.152081 | 0.130533 | 0.222730 | 0.665944 | 408.1 |
| nomad2018-predict-transparent-conductors / 0 | 5/5 | 0.069238 | 0.072892 | 0.063565 | 0.062170 | 0.744916 | 474.1 |
| nomad2018-predict-transparent-conductors / 1 | 4/5 | 0.066740 | 0.066740 | 0.058143 | 0.060450 | 0.792158 | 503.5 |
| nomad2018-predict-transparent-conductors / 2 | 5/5 | 0.070027 | 0.070027 | 0.061569 | 0.061150 | 0.742272 | 523.9 |

| 任务 | 官方评分数/预声明数 | 官方 score 均值 | 样本标准差 |
| --- | ---: | ---: | ---: |
| spooky-author-identification | 3/3 | 0.453330 | 0.032269 |
| leaf-classification | 3/3 | 0.172093 | 0.048516 |
| nomad2018-predict-transparent-conductors | 3/3 | 0.061257 | 0.000865 |

独立 admission 调用：21；全部候选裁决：{'not_admitted': 25, 'admitted': 19}。
实际执行 admission 规则的裁决：21；其中拒绝：2。
未准入不等于在 admission 集上落败：可能未通过 dev trigger 或受到调用上限限制。
原始六步事件计数：{'observe': 44, 'ideate': 44, 'select': 44, 'dispatch': 44, 'backpropagate': 44, 'admission': 44}。
来源绑定经验汇总：125 次。

本批 API 费用上界：¥6.317672（含独立 control）。
主候选状态：{'failed_to_run': 5, 'ok': 38, 'timeout': 1}。独立 control 状态：{'ok': 9}。
费用按冻结的输入/输出 token 单价 2/8 micro-CNY 重算，非供应商发票。
这是三个预选任务的小规模 adapted Arbor 实测；control 不是等预算 baseline，不能据此宣称优化收益、论文区间复现或完整 benchmark 奖牌率。

固定官方评分器判定：nomad 三组均达到历史银牌阈值；spooky 只有 seed 1 高于历史中位数，三组均未达奖牌阈值；leaf 三组均未高于历史中位数。这些是本地固定评分器映射的历史阈值，不是新的 Kaggle 在线排名或实际获奖。负结果与失败均保留，不把三任务结果外推完整 MLE-Bench 奖牌率。

## 真实机制证据与差异

六步轨迹每阶段各 44 次，125 次来源绑定 L2 经验汇总实际进入运行；L2 文本是模型解释，不是科学事实证明。21 次实际准入规则评估中有 2 次拒绝。nomad seed 0 的一个候选将 dev loss 从旧主干的 0.0807198513 降至 0.0777568288，但 admission loss 从 0.0646768596 变差到 0.0733924087，原始回执拒绝替换旧主干。该组最终 dev 最优与准入主干也不同，表格单独列出；原始凭据见该 cell 的 journal 与 summary。

适配差异包括：有界假设树；增量新证据加旧摘要，而非完整子节点文本重汇总；仅本轮有效的 global prior；固定 public-training dev/admission/final 切分；三次独立严格准入；受限 Python 沙箱和 CSV 特征；knowledge 导入及跨 run memory 关闭。完整 deviations 随每组 method report 保存。insight 消融、冻结假设修复、最终评分不进入 policy/memory 等反例由公开行为测试覆盖，不把 fixture 分数当成实测成绩。

v1 [父身份失败](parent-identity-v1/README.md)、v2 [审计阶段覆盖失败](audit-coverage-v2/README.md)、v3 [父引用语法失败](parent-reference-v3/README.md)均原样保留，没有重跑覆盖或替换失败 seed。三批失败费用上界合计 ¥1.402692；加本批 ¥6.317672，Arbor 累计 ¥7.720364。

原 campaign 总累计费用上界 ¥38.611570，剩余 ¥161.388430，零未决调用、零预留、零保护违约，见 [账本快照](pilot-v4/campaign-after.json)。不含本机计算费用，也不是供应商发票。

## 重算与工程验收

九组记录回放均为零外部调用，独立物理提交与费用审计通过。纯 JSON reducer 从原始记录核对选择、准入、失败分母、来源绑定与费用，并绑定原始 grader audit 核对官方 score；不重新计算私有标签上的 loss。哈希用于检出变动，不是外部数字签名。数据 CSV、匿名化 key 和模型密钥不随证据包发布。

```bash
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  research/experiments/2026-11-05-arbor-mle/pilot-v4
```

[完整汇总](pilot-v4/summary.json)包含全部九组；每组保留 manifest、journal、method report、费用回执、所有生成程序、冻结程序和 submission.csv、官方 audit 与原始 grader report。无需模型或 Kaggle 凭据即可重算。

运行源码本地完整检查通过：2,422 portable、134 tooling，另有真实 Linux 入口/费用回归；其 PR 与 push 的 Mac/Linux/MLE 最终均通过。push Linux 首次因完整测试集超过 900 秒上限失败，原失败保留；同源码重跑的 2,633 项测试在 884.41 秒通过，PR 那次为 680.79 秒。两次通过的 Linux 产物均独立核验 56 项检查和 1,220 个源码/验收文件。此耗时波动仍是工程限制，未靠放宽阈值或删除测试解决；真实数据矩阵未重跑。
