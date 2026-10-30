# S8：配置种群、选择与双亲交叉

`Framework.from_profile("population_prompt", ...)` 将种群作为同一配置运行时的 frontier，沿用规范证据、预算、准入、记忆和 S7 command/worktree 恢复。种群成员是完整研究 DAG 的有界视图，M9 仍独立决定晋升。当前实现的是确定性 elite 保留和四种父代采样；没有把这称作 novelty、MAP-Elites 或通用种群算法全部完成。阶段范围见 [逐项清单](ABSTRACTION_ALIGNMENT.md)，执行门槛见 [v67](../m0/verifier/v67/README.md)。

## 配置

已有兼容 prompt evaluator 时可以直接选择命名 profile：

```python
from core.loop import Framework, LoopConfig

fw = Framework.from_profile(
    "population_prompt", provider, evaluator,
    LoopConfig(max_generations=4, total_budget=100_000,
               intent_cost=2_000, reeval_floor=0),
    "/absolute/path/new-population-run",
)
result = fw.evolve("Combine complementary candidates under the declared evaluation")
print(result["population"])
```

该 profile 使用 legacy_prompt、inprocess、dev-only metric 准入和 token 预算；它不自动打开三层评估或 worktree。默认 `capacity=8`、`selection="tournament"`、`sample_seed=0`，policy 为 `population`，operators 严格依次为 `draft`、`crossover`。provider/evaluator 仍须满足原 [评估契约](EVALUATION_CONTRACT_V61.md)与计量接口。

修改配置可使用工厂：

```python
from core.composition.defaults import population_profile

assembly = population_profile(capacity=8, selection="softmax", sample_seed=17)
assembly["frontier"]["options"].update(temperature=0.5, retention="elite")
# 再按 S4/S5/S7 指南显式替换 native domain、layered、hierarchical 或 command/worktree。
```

frontier 支持 `metric`、`direction`、`sample_seed`、`capacity`、`retention`、`selection`、`tournament_size`、`temperature`。默认指标为 `dev/score`、方向 maximize；capacity 与 tournament_size 为正整数，seed 为非负整数，temperature 必须有限且大于零。population policy 要求 capacity 至少 2；只接受 `retention="elite"`。错误组合或未知选项在 provider/评估之前拒绝。

运行时仍为 `composed-v6`，frontier checkpoint 标识 population 并保存其配置。不能把 tree 的原运行直接改成 population 后恢复，也不自动升级 v1–v5 检查点。现有 tree profile 保持原路径。

## 成员、父代与 M9

前两次可用父代不足时使用 draft 建立独立根；之后从可用成员中抽取两个不同父代，交给文本 crossover。成员需要成功、有限的公开 dev 指标及完整 canonical evidence。无效或失败候选不会成为父代，已知生成/评估费用仍记账。

M9 拒绝但 dev 有效的候选可以作为探索父代，并不因此获得晋升。driver 已选定的 M9 incumbent 受到容量内保护，其余位置按配置 dev 指标排序；同分依次按创建周期和候选 ID 排序。capacity 包含受保护 incumbent，不是再额外加一个位置。成员淘汰只移出成员视图，保留节点、两条骨架父边、后代、证据和回执。显式安全排除也不级联删掉其它候选。

`result["population"]` 报告 members、protected_id、capacity、retention、selection、rng_state 和 nodes；nodes 是完整 DAG 节点数，可大于 capacity。best_candidate_id/gate_selected 继续由 M9 决定；不能把成员内 dev 排名直接当作准入结果。

## 采样压力与可复算记录

| selection | 实际行为 |
| --- | --- |
| greedy | 按当前 dev 排名取最优可用父代 |
| uniform | 在当前可用成员中均匀无放回抽样 |
| tournament | 每次抽取最多 tournament_size 个成员，按 dev 排名选胜者，再移出已选父代 |
| softmax | 按方向校正后的 dev 分数和 temperature 形成权重，无放回抽样；较低温度加强对高分的偏好 |

采样使用固定 seed 与持久 counter/calls，产生包含配置摘要、完整 eligible 列表、分数/attempt、前后 RNG 状态和所选父代的 receipt。policy 只操作分离的 frontier 视图；driver 以权威成员和预算资格重新计算整个 receipt 后才提交 RNG。返回父代必须等于最后一份抽样记录，不能隐藏额外抽样、选择被淘汰/无资格候选或伪造分数后直接接管该视图。未接受的抽样不推进权威 RNG。

抽样资格还受方向预算限制；耗尽方向从本轮选择视图排除，不改写历史 DAG。双亲候选的费用按有序父列表第一父的根方向记一次，depth 为两亲最大深度加一；不会把一次物理执行重复扣到两个方向。

## Crossover、经验和可比较性

Crossover 输入必须恰好有两个不同父代及匹配的成功公开 dev evidence。候选文本另做 artifact hash 核对；prompt 包括两者 ID、产物、指标、分数、公开反馈，以及原 scoped ContextPack。输出记录两个有序骨架父代；引用边仍不能偷改骨架亲缘、预算归属或后代信用。

这是一次由 provider 生成的完整文本交叉，不是代码签名、类型正确性或行为保持证明。产物仍须经正常 domain/evaluator 和 M9。私有结果与 admission/final 原始反馈不能通过 crossover 获得新的权限；普通 memory 的拓扑/trust/层级/长度限制继续有效。两亲祖先都能进入已授权的祖先作用域，成员淘汰不删除该历史。S6 run-only proxy 负反馈仍按独立 driver 权限进入后续 ContextPack，不能因种群分享而导出到别的 run。

elite 保留要求同一个可比较 dev 请求。因此在 hierarchical 模式，所有配置 fidelity rungs 必须规范化为相同完整 `EvalRequest`；变化 fidelity/split/seed/time_limit 等在付费前拒绝。tree 继续支持 S5 的变化 rung，不把异质 dev 分数硬排成一个种群榜。admission、final 和显式 calibration 仍可使用各自独立请求，由原 S4/S6 协议控制，不进入 dev 保留排名。

内置 CrossoverOperator 与 PromptOperator 声明 token/node/eval_count；pure-local PopulationPolicy 不产生额外 GPU/USD 费用，但不能替未计量的生成或评估组件授权额外资源。配置这些单位却没有真实 meter 覆盖会前置拒绝。

## 检查点与 worktree 接管

checkpoint 保存完整节点/边、成员、保护 incumbent、M9 outcome 顺序和 RNG。恢复先将完整 Proposal/Evidence 与 durable composed_evidence 逐字段比对，再按原 StateMutation 和 M9 decision/receipt 从零重建所有节点状态、成员及有序亲缘；每次历史抽样都会先重放当时预算池，再重新计算 receipt、返回父代和 RNG，不只是读取最后一份 RNG 状态。

回归包含：修改非 incumbent 节点状态并重算成员、同时改 checkpoint 与 journal 的末尾 RNG、同时修改节点和 proposal 的父代顺序。以上被拒绝时新增付费调用为零，原 journal 字节不变。合法抽样后预算拒绝的终态 checkpoint 仍可重复恢复；已经提交的抽样记录不会因此被抹除。这里的权威来自保留的原始执行/决策日志，不是 checkpoint 自己的 hash，也不是对任意恶意重写全部证据链的签名保证。

inprocess 路径支持周期边界恢复，独立 replay 仍重新计费且需要独立适配器。选择 S7 的 command/git_worktree、hierarchical 和 checkpoint 组合后，采样完成、原进程执行中或已完成未结算时的 coordinator SIGKILL 使用严格 journal 续接。恢复消费原 sampling receipt、provider completion 和物理 operation，RNG 与费用只提交一次。S7 的未知调用、缺失计量、pending checkpoint 和安全身份边界继续适用；见 [worktree 指南](WORKTREE_RECOVERY_V66.md)。

独立 worktree replay 会创建新物理执行来源，真实路径/commit/进程/墙钟差异仍可能使严格证书不匹配；这不等同于恢复失败，也不能通过删去来源差异来宣称精确 replay。

## 验收范围

v67 显式执行 `test_population_frontier.py`、`test_population_components.py`、`test_composed_population.py`，并保留全部 S1–S7 与旧 M0 回归。真实公开入口场景覆盖 elite 容量/淘汰、四种采样、拒绝者仍可作为探索父代、双亲 ContextPack、已知失败费用、配置/身份拒绝、状态篡改、inprocess replay、worktree SIGKILL，以及种群+proxy+记忆+gate+物理预算组合。

组合离线用例包含 4 次 dev、4 次 calibration、3 次 gate、1 次 final 和 2 次已提交抽样；第 3 个候选 proxy 改善但 true 退步，触发否决和 run-only 负反馈，第 4 次 crossover 接到反馈后产生不同产物并再次通过 gate。这是合成评估与合成 token 的机制验证，不是外部研究成果。最终 Mac/Linux 数量与同 SHA 证据见阶段清单。

当前未实现 novelty/MAP-Elites 成员保留、通用多样性优化器、任意数量父代、代码签名证明、配置种群并行调度、HITL 或真实外部 campaign。完成本阶段不自动关闭这些条款。
