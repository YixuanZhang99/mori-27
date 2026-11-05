# C07 — LoongFlow Plan–Execute–Summarize

状态：后续范围规格；继承 [COMMON](COMMON.md)。依据：统一抽象 §5、`research/dim00-08/autoresearch_modular_dim05.md`、`papers/lfsrc/`。本地材料未锁定完整上游与许可，不直接 vendor。

| 模块 | 本方法要求 |
| --- | --- |
| policy | 显式温度的 Boltzmann 供亲，随机状态持久化 |
| operator | Plan→Execute→Summarize 三段独立输入输出 |
| budget | 按代预算且三阶段调用都计费 |
| frontier | island×MAP-Elites；复用 C05 能力 |
| memory | lineage 绑定 summary，后续 Plan 真正读取 |
| knowledge | 关闭 |
| execution | 先有界串行 adapted 版本；并行需要 composed pool 实证后另点亮 |
| evaluation | 冻结 dev 目标，最终评测独立 |
| admission | elite 更新，与档案历史分离 |

新增目标：`m0/config/profiles/loongflow_program.json`、`m0/core/composition/loongflow_operator.py`、`m0/tests/test_loongflow_recipe.py`；首负载复用 C05 的 circle packing task，避免另开 zoo。
验收 L1：三段不是同一输出改标签，Summary 含具体执行结果且下一代消费；L2：温度变化使固定分数的采样概率按公式变化，恢复序列一致；L3：禁用 Plan/Summary 的 fixture 有预期输入差异；L4：失败 Execute 仍结算并供 Summary 分析，不当作有效 elite。
冻结前核对上游 PES、温度与 topology 的真实实现（原研究已指出论文/源码可能不同），明确选择哪个版本；未接并行前不声称完整吞吐复现。
