# 当前获准执行目标

用户批准日期：2026-11-05。此页是仓库接续依据，不冒充应用 Goal 控件状态。

按 [经典工作接入计划](CLASSIC_WORKS_PLAN.md) 收敛分支并逐项交付可运行方法：

1. 补齐最终候选的 macOS portable 与 Linux 验收；整合 PR #4 到 main，关闭被包含的串联 PR，保存回滚点后清理历史远端分支。
2. 从新 main 开始 GEPA：冻结来源/数据/配对接纳规格，公共 Framework 跑通反思、同批父子比较、独立 validation、冻结 test 与计量/回放，交付真实小规模结果。
3. 依次推进 FunSearch、AIDE、Arbor、OpenEvolve、AIRA、LoongFlow、R&D-Agent；一次一个方法分支，完成即合入。
4. 每项报告规格、机制、实测和公开区间复现的独立状态；不以工程测试或示例替代真实成绩，不无限扩建外围设施。

继续遵守九模块职责与原 VISION/RUBRIC；保留历史成果和失败证据。所有真实调用共用此前累计 ¥200 上限和原账本，密钥不得复制或打印。用户已授权按此计划实现、推送及将通过检查的成果合入 main。

应用 Goal 控件：用户已于 2026-11-05 将目标更新为“按 docs/CURRENT_GOAL.md 收敛分支，并从 GEPA 开始逐项完成 spec、实现、实测和合入”，并点击继续；工具查询已确认状态为 active。此前 paused 和无法由工具恢复的限制已由此次用户操作解除。后续按本页顺序持续推进，单个方法交付不代表整个 Goal 完成。

执行进度：分支收敛已完成，GEPA 的 [PR #5](https://github.com/YixuanZhang99/mori-27/pull/5) 已于 2026-11-05 合入 main `b16b4c6`，两组最终候选 Mac/Linux/MLE 检查全部通过，合并树与候选相同。GEPA 远端方法分支已归档退役；真实结果及失败见 [GSM8K 交付记录](../research/experiments/2026-11-05-gepa-gsm8k/README.md)，尚无优化收益或论文复现结论。

当前施工为 C02 FunSearch，唯一方法分支 `codex/classic-funsearch` 已衔接 main 并发布 [PR #6](https://github.com/YixuanZhang99/mori-27/pull/6)。本地完整检查、11-cycle 离线试跑和记录回放通过。真实 v1 seed 0 暴露函数输出要求与 JSON 外层格式的冲突：11次构造均失败（7格式错误、4输出截断），无有效程序或留出成绩；费用上界 ¥0.971870 已全部结算，原 campaign 累计 ¥18.695960。其余两个 v1 seed 在调用前停止，完整记录保留于 [失败档案](../research/experiments/2026-11-05-funsearch-or3/format-conflict-v1/README.md)。

v2 已修正格式，但真实seed0的10次改进均在high推理下达到16384输出上限；初始程序dev213.9/held-out210.1箱，与best-fit持平。此批费用上界¥1.373084全部结算，原campaign累计¥20.069044。其余v2 seed在调用前停止，[完整记录](../research/experiments/2026-11-05-funsearch-or3/high-effort-v2/README.md)保留。

v3 的三个 seed 已全部完成：有效候选 10/11、11/11、10/11；三组冻结 held-out 都为 210.1 箱，与 best-fit 持平。Seed 0 的 dev 改善至 213.8 箱，但没有体现留出收益。三组回放与独立重算通过，真实轨迹包含非最优父代选亲与弱岛重置。[完整结果及失败](../research/experiments/2026-11-05-funsearch-or3/README.md)已归档；本批费用上界 ¥1.098926，原 campaign 累计 ¥21.167970，剩余 ¥178.832030，无未决调用或预留。

下一步完成 PR #6 最终候选检查并合入，再从 main 开始 AIDE，依次打通 draft/debug/improve、真实 L1 摘要消费和 MLE 试跑。当前仅发布一个方法分支；AIDE 仍是规格准备，不冒称实现完成。Goal 保持 active。GEPA 合并后 Mac 故障注入修复已由 PR #6 的 fd02b5c、1462fb3 Mac 检查通过验证。
