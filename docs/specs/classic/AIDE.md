# C03 — AIDE 代码树搜索

状态：规格草案；继承 [COMMON](COMMON.md)。依据：统一抽象 §5/§6.2(c)、REPLICATION §2、CODE-BORROWING。
首个源码核对对象：[WecoAI/aideml / ad73d227](https://github.com/WecoAI/aideml/tree/ad73d227af481bea3de06f884f41b2993dd6453a)，2026-11-05 取得 commit 身份；具体选择概率/默认值仍需逐函数核对后冻结，不冒称本轮已完成源码对照。

| 模块 | 本方法要求 |
| --- | --- |
| policy | 初始 draft 配额，buggy 节点按 debug 规则处理，其余 best-first improve |
| operator | draft/debug/improve 各自语义，不把 debug 当普通改进 |
| budget | 总步数、执行时间、debug 深度与所有调用成本 |
| frontier | 代码树，保留 buggy 节点并允许有限深度修复 |
| memory | Journal/Σ(T) 摘要，L1；不默认添加 Arbor insight 或 L3 |
| knowledge | 关闭 |
| execution | M7 隔离构造和执行；失败产生可用于 debug 的公开错误 |
| evaluation | 复用 MLE 本地 validation、submission 及官方终评 |
| admission | validation best 终选；不默加 held-out 优胜 gate 改写 AIDE |

已有树、MLE 数据/评分与 debug 组件不代表完整 AIDE recipe。
最小增量：新增 `m0/core/composition/aide_policy.py`、`m0/config/profiles/aide_mle.json`、`m0/tests/test_aide_recipe.py`；接线 `construction_recipes.py` 的 debug 输入与 MLE 现有 runner。复用预算/provider/沙箱；不新写 MLE 评测器。
首个 smoke 用已授权的 spooky；机制通过后冻结 spooky/leaf/nomad × seeds 0/1/2。pilot 建议 3 初始 drafts、debug 深度 2、最多 10 个节点，均标注为小试跑参数，非上游默认值。

验收 A1：三 draft 形成扇出，后续 improve 指向当前有效最优；A2：注入语法错误触发 debug 支链，超过深度不再修复；A3：验证较差但可修复候选未被统一 PRUNE 抹掉；A4：全部失败时报告 no_valid_submission，不伪造 best；A5：最终按 validation 选择，官方分数仅终评。
public fixture 必须从 `Framework.from_profile` 运行，不直接调用 policy 私有方法代替端到端。
报告 valid/total、每任务分数、费用、树轨迹和缺失项；只有完整官方任务矩阵和匹配条件才能套用旧 REPLICATION 的奖牌区间。
proposed 实现后在本页补完整运行命令；当前不存在 `aide_mle` 可运行入口，不能向用户推荐尚未实现的命令。
