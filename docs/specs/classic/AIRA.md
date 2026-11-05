# C06 — AIRA-dojo 可控搜索组合

状态：后续范围规格，尚未冻结上游源码版本；继承 [COMMON](COMMON.md)。依据：统一抽象 §5/§6.2(c)、M2/M3 与 `research/dim00-08/autoresearch_modular_dim01.md`。

| 模块 | 本方法要求 |
| --- | --- |
| policy | greedy 首项，MCTS/evo 各自作为有独立验收的配置 |
| operator | O 与 π_op 解耦；draft/debug/improve/crossover 的 arity 0/1/1/2 |
| budget | 剩余时间进入算子输入，机制仍独立硬限额 |
| frontier | 代码树；策略变更不改算子内容 |
| memory | none/simple/sibling/ancestral 各自作用域 |
| knowledge | 关闭 |
| execution | 复用隔离单调用；参考容器差异记录，后端兼容单列 |
| evaluation | 同一 MLE 任务/数据/评分，防 test 回流 |
| admission | final selector 独立可配，不将其塞进 policy |

依赖：C03 AIDE 先关闭；新增 `m0/config/profiles/aira_mle.json` 和 `m0/tests/test_aira_recipe.py`，最小差距是算子策略、作用域与终选接线，不重做 MLE。
验收 I1：只换 π_op 改变算子分配而非实现；I2：sibling/ancestral 负例不跨作用域；I3：固定候选池只换合法 selector 能得到预期终选，test 分数不可作 selector 输入；I4：同预算同任务输出逐组结果。
首版只承诺 greedy 配置，MCTS/evo 在子规格与行为测试齐全后点亮；不能以一个 greedy run 宣称整个 AIRA 设计空间已复现。
冻结前任务：从原论文定位官方仓库、锁定 revision/许可、提取选择规则，选定与 AIDE 相同三任务及 seed。当前不提供不存在的运行命令。
