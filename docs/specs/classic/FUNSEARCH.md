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

## 进入施工前的最小差距核对（2026-11-05）

固定 notebook 的 SHA256 为 `eec45846a8661722addbb856179327cf2ede0bc502e32be4ad58a6ac54e0aca6`，已用现有 preparation 命令重新核对。dev/held_out 各 10 个实例，文件 SHA256 分别为 `a99be58e4e5cf25986edcffd55f03928f47e82f2db00397eab72b9c1d73c19c3`、`4c18523528ff1c9c5bf235f105478a731c312a92d2924c27c2253ac729918045`。

GEPA 已提供可复用的 `metric_final`：只按 dev 选定并冻结，再进行 reporting-only final_audit。C02 应在 zoo 内增加 opt-in 双 split adapter，保留原 OR3DevDomain 的 dev-only 契约；复用该准入插件、现有 M7、CNY bridge 和 SandboxedPriority，不改第二套核心循环。dev 的 policy binding 与反馈只依赖开发集；整份运行 manifest 另外固定 held-out hash。

已审阅本机 `4df353f` WIP：额外 supervisor、authority broker、价格门禁、owner seal 和源码镜像栈不属于 C02 的必要增量，不整体导入。可复用的是留出泄漏、数据变更和函数边界的测试思路。当前固定模板及既有构造器负责只允许改写 `priority(item, bins)`。

拟用两个岛、prompt_size=2、temperature=1.0、temperature_period=10、每五个搜索 cycle 重置弱岛；按代数重置、独立 RNG、保留历史及治理资格过滤均显式标 adapted。初始独立 control 只作 sanity check；固定 best-fit 在 dev/held-out 的分数单独作为任务参考，不宣称同预算搜索对照。正式冻结前，用公开 fixture 确认这些现有接口和重置参数，然后按 F1–F5 开发；此核对不是实现完成声明。
