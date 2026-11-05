# C04 — Arbor 假设驱动研究

状态：施工规格冻结（2026-11-05），细化设计见 [实施设计](../../superpowers/specs/2026-11-05-arbor-design.md)，任务见 [实施计划](../../superpowers/plans/2026-11-05-arbor-delivery.md)。离线实现已完成独立审查和修复，并从 AIDE 实际合入后的 main `9d5967d` 接续到 `codex/classic-arbor`；v1 smoke 已失败并完整保留，v2 修正父身份提示后须单独冻结矩阵。继承 [COMMON](COMMON.md)。依据：REPLICATION §3、统一抽象 M1/M5/M7/M9、CODE-BORROWING 的 Arbor 文件清单。
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

复用 `ContextMemory`、M7 configured construction、`LayeredAdmissionController`；`ArborPolicy` 与 driver coordinator 已连接六步轨迹、待选假设、主干构造和源绑定经验回传。当前证据来自合成数据与机制测试，首组真实 smoke 在第二轮提案父身份错误时停止；[完整失败记录](../../../research/experiments/2026-11-05-arbor-mle/parent-identity-v1/README.md)保留，未完成真实矩阵。
新增 `m0/config/profiles/arbor_mle.json`、`m0/tests/test_arbor_recipe.py`；按需新增 `m0/core/composition/arbor_policy.py`，只补六步规划和 insight 消费，记忆写入沿用串行 mutation。
首个任务复用 spooky；pilot 5 cycles、tree depth 2、margin 0、gate 上限 3；完整默认配置保留 REPLICATION 的 20/2，并分开标注。

验收 R1：六步事件有候选/假设身份；R2：冻结假设在修复中不可被替换；R3：提供高 dev 低 admission 候选，拒绝 merge、原 trunk 不变；R4：叶负面 insight 上溯且下一次 ideation 输入实际包含来源；R5：禁用 insight 的 fixture 会改变输入，不能只比存储是否存在；R6：final 不进入 policy/memory。
真实报告展示至少一次完整 gate 决策，若自然 run 未出现拒绝，保留实际情况并另附机制反例，不伪造实测轨迹。性能采用 MLE 三任务诊断口径，不声称论文奖牌复现。
运行入口已实现（需要 Linux 的 bubblewrap/seccomp 沙箱；默认仅用合成 CSV，不调用外部模型）：

```bash
PYTHONPATH=m0 uv run --project m0 python -m zoo.mle_bench_lite.arbor_runner --output work/arbor-fixture --max-cycles 3
PYTHONPATH=m0 uv run --project m0 python -m zoo.mle_bench_lite.arbor_runner --output work/arbor-fixture --max-cycles 3 --resume
```

恢复要求源码、数据、配置和原匿名化 key 保持不变。入口默认 pilot 5 cycles；`build_profile` 与打包 profile 的完整默认值为 20 cycles。`search_seed` 标记重复运行和独立 control 调度；规划器没有本地随机选亲器，也不声称供应商应用了远端 seed。

本地验证已包含：实际 Linux 沙箱训练与跨 split 冻结预测、开发集赢家被准入集拒绝、经验消融、篡改恢复拒绝，以及本机 HTTP 下 planning/constructor/synthesis 的真实费用结算和零调用回放。独立 `arbor_grading` 入口只接受原始冻结 trunk 及原始预测重建的提交，评分单次执行并与搜索隔离。

独立 [导出与重算工具](../../../research/experiments/2026-11-05-arbor-mle/README.md) 已实现，分别核对开发集最优、准入 trunk、最终冻结评估、费用和经验来源；未完成尝试与未运行 cell 保留在分母中。v1 的 1 组失败、8 组未运行和费用已导出重算，尚无官方成绩。

**交付边界：** 完整分支审查及三项重要修复、本地完整检查和干净 CLI/resume 已完成；当前仍缺真实三任务矩阵、最终 CI 和合入。fixture 的分数不是 benchmark 表现；性能结论与论文复现均未成立。

v2 规划输入显式列出 `eligible_parent_ids`，来源是同一严格父节点校验；所有新假设的 parent_id 只能引用该集合或为 null。待选 hypothesis ID 仅用于 selection.pending_id，不允许成为未执行的父节点。任一新假设无效时仍拒绝整批，不丢弃失败项、不自动重试。

v2 完成五轮但因独立审计错误停止交付；v3 修复按阶段的原始调用覆盖核对。构造器仅在本 profile 中设置 `explicit_json_output=true`，明确 artifact/hypothesis JSON 外层格式，主搜索及独立控制均适用；规划与共享 task 不接收这条构造格式指令。旧方法默认请求保持不变，解析器仍严格、两次构造尝试上限不变。v1/v2 的失败矩阵和费用分别保留，v3 必须另行预声明。
