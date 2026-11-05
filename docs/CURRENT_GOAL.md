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

C02 FunSearch 已通过 [PR #6](https://github.com/YixuanZhang99/mori-27/pull/6) 合入 main `da4e06c`。最终候选 `5196db9` 的 push/PR 两组 Mac/Linux/MLE 均通过，合并树与候选相同；方法分支已归档为 `archive/classic-funsearch-20261105` 并退役。本地完整检查、11-cycle 离线试跑和记录回放通过。真实 v1 seed 0 暴露函数输出要求与 JSON 外层格式的冲突：11次构造均失败（7格式错误、4输出截断），无有效程序或留出成绩；费用上界 ¥0.971870 已全部结算，原 campaign 累计 ¥18.695960。其余两个 v1 seed 在调用前停止，完整记录保留于 [失败档案](../research/experiments/2026-11-05-funsearch-or3/format-conflict-v1/README.md)。

v2 已修正格式，但真实seed0的10次改进均在high推理下达到16384输出上限；初始程序dev213.9/held-out210.1箱，与best-fit持平。此批费用上界¥1.373084全部结算，原campaign累计¥20.069044。其余v2 seed在调用前停止，[完整记录](../research/experiments/2026-11-05-funsearch-or3/high-effort-v2/README.md)保留。

v3 的三个 seed 已全部完成：有效候选 10/11、11/11、10/11；三组冻结 held-out 都为 210.1 箱，与 best-fit 持平。Seed 0 的 dev 改善至 213.8 箱，但没有体现留出收益。三组回放与独立重算通过，真实轨迹包含非最优父代选亲与弱岛重置。[完整结果及失败](../research/experiments/2026-11-05-funsearch-or3/README.md)已归档；本批费用上界 ¥1.098926，原 campaign 累计 ¥21.167970，剩余 ¥178.832030，无未决调用或预留。

C03 AIDE 的完整分支审查与修复、本地完整检查、三任务 × 三 seed 真实矩阵、冻结提交的官方评分均已完成。九组提交全部有效，主候选 70/90 有效、20 个失败、0 个未完成。nomad 的三个 seed 达到固定 MLE-Bench 评分器的铜/银/银历史阈值；另两个任务均高于历史中位数但未达奖牌阈值，不外推完整 benchmark 奖牌率。[完整证据和可重算报告](../research/experiments/2026-11-05-aide-mle/README.md)已归档；最终 `bbea24b` 的 push/PR 两组 Mac/Linux/MLE 均通过，已通过 [PR #7](https://github.com/YixuanZhang99/mori-27/pull/7) 合入 main `9d5967d`；合并树一致，推送 Linux 产物独立核验 56 项检查、1,206 个源码与验收文件一致。方法分支已归档为 `archive/classic-aide-20261105` 并退役。

AIDE 本批费用上界 ¥9.723236；原累计 campaign 已使用 ¥30.891206，剩余 ¥169.108794，无未决调用或保护违约。之后继续 Arbor → OpenEvolve → AIRA → LoongFlow → R&D-Agent。保持 main 加一条活跃方法分支；Arbor 已无冲突衔接实际 main，当前唯一方法分支为 `codex/classic-arbor`。Goal 保持 active，单项完成不代表八项总目标完成。

C04 Arbor 已实现六步假设循环、当前 trunk 构造、来源绑定 insight 上溯/消费、独立准入与冻结终评，以及专用 MLE 入口和导出重算。独立审查的三项重要问题均经 RED→GREEN 修复；完整本地检查 2,408 portable、126 tooling 通过，另有 14 项含 Linux 沙箱的 runner/currency 用例通过。干净默认 CLI、终态 resume 和零调用 replay 通过；接续 AIDE 后 134 项 tooling 全部通过。下一步是预声明九组真实 MLE 矩阵、官方评分、证据归档及最终 CI/合入；合成结果不作为 benchmark 成绩。

Arbor v1 首组真实 smoke 在第二轮规划停止：1 个主候选完成、1 轮未完成，另外 8 组未运行；模型把待选假设 ID 当作父候选，整批提案被正确拒绝。[失败证据与费用](../research/experiments/2026-11-05-arbor-mle/parent-identity-v1/README.md)已独立重算并保留，未重跑覆盖。v2 明确提供可用父候选 ID，仍严格校验全部提案；修复正在完成验证，随后单独声明新矩阵。v1 费用上界 ¥0.183060，原 campaign 累计 ¥31.074266，剩余 ¥168.925734，零未决调用。

Arbor v2 已跑完五轮但交付核验失败：1 个有效候选、4 次构造格式失败，另外 8 组未运行。原始 replay 通过且账本平衡；审计错误是将 operator-only 构造次数与含 planning 的全部调用数比较。v3 已按阶段核对全部原始回执，并仅为 Arbor 构造启用明确 JSON 输出指令；112 项相关回归（含完整 HTTP live 入口/物理核验/终态恢复）通过，完整检查通过：2,414 项 portable、134 项 tooling，架构与离线示例通过。[v2 原始失败及只读诊断](../research/experiments/2026-11-05-arbor-mle/audit-coverage-v2/README.md)保留。v2 费用上界 ¥0.686746，原 campaign 累计 ¥31.761012，剩余 ¥168.238988，零未决调用。下一步单独声明 v3，不重跑覆盖 v1/v2。

Arbor v3 首组在第 4 轮规划停止：3 个有效候选、1 轮未完成、8 组未运行；构造格式已正常，模型把合法父候选写成来源引用形式 `candidate:<ID>`，裸 ID 解析器拒绝。原始响应离线复现，v4 明确等价表示解码后继续严格检查资格/深度；[v3 原始失败档案](../research/experiments/2026-11-05-arbor-mle/parent-reference-v3/README.md)已独立重算。费用上界 ¥0.532886，原 campaign 累计 ¥32.293898，剩余 ¥167.706102，无未决调用。修复通过 46 项相关回归及完整检查（2,422 项 portable、134 项 tooling，含架构与离线示例）；即将从干净发布版本单独声明 v4，尚无完整 Arbor 实测交付。
