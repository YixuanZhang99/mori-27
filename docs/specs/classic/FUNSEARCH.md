# C02 — FunSearch 程序进化

状态：规格草案；继承 [COMMON](COMMON.md)。目标：现有 OR3 开发集接入真实程序搜索和一次冻结留出评估。

## 来源与现状

依据：M1-UNIFIED §8.1、M2 §8.5、M3 §8.1、M4 §8.1；[官方固定实现](https://github.com/google-deepmind/funsearch/tree/cc53f274237d7ab05c19df939edbc1f9616a7c19) 和 [当前证据](../../../research/experiments/2026-11-05-funsearch-population/README.md)。
已有 `FunSearchPopulation`、选择/版本化 prompt、受限构造、`OR3DevDomain`、隔离 priority 执行。已有 OR3 -213.9 是固定 best-fit 在十个开发实例的分数，不是模型发现。
本机 `4df353f` WIP 不属于此基线；先逐条对 spec 挑选可复用最小增量，不因投入多而整体接收。

| 模块 | 本方法要求 |
| --- | --- |
| policy | 岛屿选择、signature 簇温度采样、簇内长度偏好、弱岛重置 |
| operator | 版本化示例程序形成 prompt；只生成目标函数，冻结程序骨架 |
| budget | 生成/执行/终评分别计量；墙钟重置与代数重置差异显式登记 |
| frontier | per-test signature、簇、岛、成员及 reset founder；历史保留，供亲资格单列 |
| memory | 选中程序与开发分数，不加未在参考中的全局语义记忆 |
| knowledge | 关闭 |
| execution | 复用 M7 构造及已存在的隔离 priority 子进程 |
| evaluation | trusted scorer 计算负 bin 数；只有当前 item/容量进入候选进程 |
| admission | 原方法成员/簇更新与最终 best 选择；治理排除供亲时明确 adapted |

## 首个负载与交付

沿用 `prepare_or3.py` 已定义的 sorted IDs 10/10 dev/held-out split，内容 hash 固定；相同 seed 程序和 baseline 评估。search seeds=0/1/2，各最多 10 提案，预算先到先停；与上游默认/论文规模的差异公开。开发集是已看过的，不能重新称为 unseen。
复用 `m0/zoo/funsearch_binpacking/domain.py`，新增 `runner.py`、`PROVENANCE.md` 和 `m0/config/profiles/funsearch_or3.json`；补独立终评入口，只读冻结候选。不得为了此任务重建 provider、货币账本、通用 supervisor。

## 验收

- F1：固定分数向量与参考 signature/簇概率/长度概率一致，已声明 RNG 和调度差异保留；重置确实更换弱岛 founders。
- F2：只修改目标函数；越界修改、无效输出和超时不进入供亲或终选，已花成本保留。
- F3：三 seed 可真实生成并评分候选；未发现更优程序也交付完整失败/无提升结果。
- F4：从 dev 选定并冻结一个程序，另进程评 held-out；不得从 held-out 重新挑 winner。
- F5：报告 seed、搜索预算、baseline/final bin 数、失败率、控制占用和适配差异。OR3 pilot 不声称原论文完整复现。

current：`PYTHONPATH=m0 python research/experiments/2026-11-05-funsearch-population/check_or3_framework.py <dev/data.json>`。
proposed：`PYTHONPATH=m0 python -m zoo.funsearch_binpacking.runner --mode fixture --output <new-dir>`；live 接受冻结 manifest。
针对性复用 `test_funsearch_framework.py`、`test_funsearch_population.py`、`test_funsearch_governed_or3.py`，新增 `test_funsearch_holdout.py` 验证 F3–F5。
