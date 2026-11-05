# C08 — R&D-Agent 角色协作与 Trace DAG

状态：后续范围规格；继承 [COMMON](COMMON.md)。依据：统一抽象 §5、`research/dim00-08/autoresearch_modular_dim04.md`、CODE-BORROWING；参考目标 [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)，实施前固定 revision 和一个场景，不承诺金融/医学等全部应用。

| 模块 | 本方法要求 |
| --- | --- |
| policy | hypothesis planning + 显式可换调度 |
| operator | HypothesisGen / ExperimentGen，角色输入输出分开 |
| budget | 时间触发和实际研究/开发/评估支出 |
| frontier | Trace DAG，骨架负责谱系，引用边只带信息 |
| memory | 跨分支受作用域约束的协同经验 |
| knowledge | benchmark 关闭；文献 research profile 后续单独验证 |
| execution | Researcher/Developer 角色，复用 M7，不拿两段相同 prompt 冒充角色 |
| evaluation | 一个明确任务的 dev 评估与冻结最终评估 |
| admission | 有证据的分支 merge，时间触发本身不能证明质量 |

依赖 C04 的假设与记忆、C05 的可组合拓扑。新增 `m0/config/profiles/rd_agent_mle.json`、`m0/core/composition/rd_agent_policy.py`、`m0/tests/test_rd_agent_recipe.py`，首任务 spooky 复用既有 MLE adapter。
验收 D1：角色输出为对方输入且来源可追踪；D2：添加 reference edge 改变可用 context 但不重复信用；D3：多条分支并存，merge 保留真实来源；D4：失败与拒绝经验可被后续合法分支消费；D5：时间/预算停止不丢费用或已产出的最佳提交。
这是 benchmark 角色/DAG 接入规格；联网文献、完整 R&D-Agent 应用和学习调度另立增量，不纳入首个通过结论。当前未冻结上游细节与可执行命令。
