# C04 — Arbor 假设驱动研究

状态：规格草案；继承 [COMMON](COMMON.md)。依据：REPLICATION §3、统一抽象 M1/M5/M7/M9、CODE-BORROWING 的 Arbor 文件清单。
源码核对对象：[RUC-NLPIR/Arbor / a633f56f](https://github.com/RUC-NLPIR/Arbor/tree/a633f56f2601387402194481e846e3375e822afa)；本轮锁定身份，执行前核对六步语义和 insight 写读路径。

| 模块 | 本方法要求 |
| --- | --- |
| policy | Observe→Ideate→Select→Dispatch→Backpropagate→Decide；规划调用通过现有计量通道 |
| operator | 证据条件化 hypothesis_refine；已验证/被否决 insight 分别作正/负约束 |
| budget | max_cycles/max_tree_depth，低样本规则收敛，gate 调用独立上限 |
| frontier | 假设树、骨架/引用边分离、merge 状态与 trunk |
| memory | 叶 insight 增量上溯至祖先/全局 prior，并实际进入下一次 ideation |
| knowledge | benchmark 双车道关闭；联网 research 另项，不能阻塞本 recipe |
| execution | hypothesis_frozen=True；worktree 产物，修复只改实现 |
| evaluation | dev/admission/final 各自身份；同一固定 artifact 跨 split 评分 |
| admission | dev trigger→held-out 严格 margin 改进→merge，失败保留旧 trunk |

复用 `LLMCyclesPolicy`、`ContextMemory`、M7 configured construction、`LayeredAdmissionController`；目前这些只是组件，不是完整 Arbor 轨迹。
新增 `m0/config/profiles/arbor_mle.json`、`m0/tests/test_arbor_recipe.py`；按需新增 `m0/core/composition/arbor_policy.py`，只补六步规划和 insight 消费，记忆写入沿用串行 mutation。
首个任务复用 spooky；pilot 5 cycles、tree depth 2、margin 0、gate 上限 3；完整默认配置保留 REPLICATION 的 20/2，并分开标注。

验收 R1：六步事件有候选/假设身份；R2：冻结假设在修复中不可被替换；R3：提供高 dev 低 admission 候选，拒绝 merge、原 trunk 不变；R4：叶负面 insight 上溯且下一次 ideation 输入实际包含来源；R5：禁用 insight 的 fixture 会改变输入，不能只比存储是否存在；R6：final 不进入 policy/memory。
真实报告展示至少一次完整 gate 决策，若自然 run 未出现拒绝，保留实际情况并另附机制反例，不伪造实测轨迹。性能采用 MLE 三任务诊断口径，不声称论文奖牌复现。
当前没有完整 `arbor_mle` 入口；实现完成时将可复制命令和三元组报告补到此页。
