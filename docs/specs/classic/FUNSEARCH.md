# C02 — FunSearch 程序进化

状态：规格、工程、三 seed 小规模实测和最终 CI 完成，PR #6 已于 2026-11-05 合入 main `da4e06c`；继承 [COMMON](COMMON.md)。目标：现有 OR3 开发集接入真实程序搜索和一次冻结留出评估。

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
current：`PYTHONPATH=m0 python -m zoo.funsearch_binpacking.runner --mode fixture --output <new-dir>`；live 接受冻结 manifest。
针对性复用 `test_funsearch_framework.py`、`test_funsearch_population.py`、`test_funsearch_governed_or3.py`，新增 `test_funsearch_holdout.py` 验证 F3–F5。

## 进入施工前的最小差距核对（2026-11-05）

固定 notebook 的 SHA256 为 `eec45846a8661722addbb856179327cf2ede0bc502e32be4ad58a6ac54e0aca6`，已用现有 preparation 命令重新核对。dev/held_out 各 10 个实例，文件 SHA256 分别为 `a99be58e4e5cf25986edcffd55f03928f47e82f2db00397eab72b9c1d73c19c3`、`4c18523528ff1c9c5bf235f105478a731c312a92d2924c27c2253ac729918045`。

GEPA 已提供可复用的 `metric_final`：只按 dev 选定并冻结，再进行 reporting-only final_audit。C02 应在 zoo 内增加 opt-in 双 split adapter，保留原 OR3DevDomain 的 dev-only 契约；复用该准入插件、现有 M7、CNY bridge 和 SandboxedPriority，不改第二套核心循环。dev 的 policy binding 与反馈只依赖开发集；整份运行 manifest 另外固定 held-out hash。

已审阅本机 `4df353f` WIP：额外 supervisor、authority broker、价格门禁、owner seal 和源码镜像栈不属于 C02 的必要增量，不整体导入。可复用的是留出泄漏、数据变更和函数边界的测试思路。当前固定模板及既有构造器负责只允许改写 `priority(item, bins)`。

拟用两个岛、prompt_size=2、temperature=1.0、temperature_period=10、每五个搜索 cycle 重置弱岛；按代数重置、独立 RNG、保留历史及治理资格过滤均显式标 adapted。初始独立 control 只作 sanity check；固定 best-fit 在 dev/held-out 的分数单独作为任务参考，不宣称同预算搜索对照。正式冻结前，用公开 fixture 确认这些现有接口和重置参数，然后按 F1–F5 开发；此核对不是实现完成声明。


## 施工前反例与确定的数据流

2026-11-05 对 GEPA 最终候选 `5fed770` 的离线复查发现：现有树 frontier 将没有超过全局 incumbent 的有效候选标为 pruned；三次同分构造中只有初始候选可继续供亲。直接配置 population frontier 又因岛屿抽样不属于其内置采样器而拒绝。因此先前 11-cycle best-fit fixture 仅证明入口和重置可执行，不证明完整岛屿搜索语义。

C02 必须使用 capacity=max(2, max_proposals+1) 的 PopulationFrontier 保留所有可能的有效候选。全局 dev mean 只决定最终 incumbent；岛屿成员/簇及下一次供亲不以是否提升 incumbent 为条件。预算耗尽、无效评价仍排除供亲，弱岛 reset 仍按方法替换活动成员，历史不删除。

唯一必要的 core 增量是把现有 FunSearchCoordinator 的 `funsearch_selection` 和 `verify_selection` 接到 population 抽样授权与恢复校验：在当时有效成员及剩余预算集合上验证有序样本、重复样本、去重血缘和状态转移；恢复时从原始事件重算。不得跳过采样验证、把岛屿抽样改成 tournament，或让 checkpoint 的自证 hash 代替原始事件。

一次迭代：域固定 dev IDs/模板 → policy 按岛屿/簇/长度抽程序 → M7 仅修改 priority 函数 → 独立 worker 接收逐个 item 与可容纳 bins → 可信 scorer 记录完整 dev 分数向量 → 有效候选登记到抽中的岛屿、单独比较 dev mean 更新 incumbent → 每五个成功登记（含初始候选）触发弱岛 reset，失败不增加重置计数。最后冻结 dev incumbent → 用相同沙箱和 scorer 评一次 held_out → reporting-only 结果，不更新岛屿、记忆或最终选择。

保持现有参考簇目标为分数向量最后一个排序 case 的值，最终 incumbent 为 dev mean；这两个目标不可混称。保留独立 RNG、以成功登记计数替代墙钟调度的 adapted 差异。模板固定为 `def priority(item, bins): return -(bins - item)` 的两行 Python 定义，worker 提供 np；固定 best-fit 是外部任务参考，模型的初始程序仍由 M7 构造。

## 运行与证据冻结

- 官方 notebook 和双 split hash 见上文。live 要求来源干净、原累计账本和可用 Linux 沙箱；在模型请求前核对整份 manifest、10/10 count、disjoint IDs、实例字段及当前文件内容。
- 双 split adapter 保留旧 OR3DevDomain 的 dev-only 接口。dev 的 evaluation_context、FunSearch binding 和生成输入不包含 held-out 内容；整份运行 manifest 单独固定两份数据。
- 固定 seeds 0/1/2，每 seed 一个初始候选及最多10提案，输出上限16384，partition timeout30秒。现有初始独立 control 只测 dev。所有费用继续原累计 ¥200；候选评价/终评无模型调用，以现有 eval_count 和实际墙钟记录。
- 当前任务参考在相同真实沙箱上验证：best-fit dev 平均213.9 bins，held_out 平均210.1 bins（对应负分-213.9/-210.1）。这不是模型搜索结果，也不参与模型挑选；交付报告保留逐实例 bin 数并重算。
- `--resume` 不得改变源代码、数据、方法参数、provider/预算身份。已完成 final 的恢复与记录 replay 不执行模型或程序。生成失败、超时和无可用 winner 均作为失败/跳过结果保留，不改分母或用 baseline 填补。

新增验收 F6：公共 Framework 中同分及较差但有效程序仍可参与岛屿选择；population 恢复必须拒绝篡改的原始选亲凭证或不满足当时预算的 eligible 集合。F1–F6 全部满足并报告真实三 seed 后才称 C02 已接入；论文区间复现仍单列。


独立终评入口明确为同一 runner 的 `--resume --final-only`：只接受已存在的 `metric_final_frozen`，读取并验证原候选及绑定后执行未完成的终评；已完成则返回原报告。尚未冻结时立即拒绝，不能借终评命令生成候选、继续搜索、重新选择或调用模型。它复用 Framework 的持久化 final 恢复路径，不复制终选权威。

恢复必须从冻结初始配置重建 FunSearch 岛屿状态并逐事件校验，不能仅验证每张凭证自带的 before/after；policy 完成恢复后还须核对最终 RNG/成员/reset/pending 状态。平台原有 generic population sampler 不变，FunSearch 的抽样通过独立等价验证接入。

## 实测发现与格式修正（v2）

v1 `f151dba` 的 seed 0 完成 11 次搜索，均未通过构造；无有效程序或留出分数。其中7次因外层格式错误、4次因供应商输出截断而失败；“只返回函数”的任务指令与 M7 JSON 外层格式冲突是已定位的实现缺陷。后两个 v1 seed 在调用前停止，原始记录与费用保留于 [格式冲突记录](../../../research/experiments/2026-11-05-funsearch-or3/format-conflict-v1/README.md)。

`funsearch-or3-v2` 将函数限制明确限定为 JSON `artifact` 的内容，并用 version=2 的 FunSearch 专用角色指令要求 `artifact`/`hypothesis` JSON 外层；主搜索与独立 control 同步修正。不放宽解析器、不从裸代码补造成功、不改变算法/数据/提案数/输出上限/时间限额/原费用账本。新版本独立预声明 seeds 0/1/2，各初始加最多10提案，16384输出、30秒/partition；不得把两版样本混合报均值。

## 有界生成参数修正（v3）

v2 seed0 的初始程序与control可评分，但10次mutation均将16384 completion tokens全部用于reasoning后截断；dev213.9/held-out210.1箱与best-fit持平。其余v2 seed未启动，全部记录/费用在[high-effort-v2](../../../research/experiments/2026-11-05-funsearch-or3/high-effort-v2/README.md)。

依据[官方参数说明](https://api-docs.deepseek.com/guides/thinking_mode/)，给既有受治理provider增加显式reasoning_effort（low/high/max），默认high保持原调用者行为；构造、冻结manifest、实际wire、计费桥独立重算均绑定此值。C02 `funsearch-or3-v3` 明确选择low；不改变模型、16384输出上限、10提案、30秒、官方数据或原预算。预声明新批seeds0/1/2，main与control同配置；不混合v1/v2/v3做均值，不把旧失败删除，不声称参数调节证明方法优越。

## v3 交付证据

`1462fb3` 的 seeds 0/1/2 已完整运行：有效候选 10/11、11/11、10/11；三组冻结 held-out 均为 210.1 箱，记录回放和原始证据重算通过。Seed 0 的 dev 改善至 213.8 箱，但未体现留出收益。真实轨迹包含非 incumbent/较差有效父代选亲以及每组两次弱岛重置；F1–F6 对应测试与原始记录见[结果报告](../../../research/experiments/2026-11-05-funsearch-or3/README.md)。本批费用上界 ¥1.098926，原 campaign 累计 ¥21.167970，无未决费用。最终检查与合入仍以 PR #6 为准；不声称论文区间复现。

最终集成证据：候选 `5196db9` 的 [push 检查](https://github.com/YixuanZhang99/mori-27/actions/runs/41988128650) 与 [PR 检查](https://github.com/YixuanZhang99/mori-27/actions/runs/41988135259) 均通过 Mac/Linux/MLE；合并树与候选相同。回滚标签为 `archive/classic-funsearch-20261105`。
