# C03 — AIDE 代码树搜索

状态：施工规格冻结，2026-11-05。本地基于 C02 最终候选 1af2dc0 开始；仅在 C02 合入后衔接实际 main 并发布 AIDE 分支。继承 [COMMON](COMMON.md)。目标是让公开 Framework 完整执行 draft/debug/improve 和真实 MLE 评估，并保留可核对的失败、费用与树轨迹。

## 来源和一致性边界

参考固定为 [WecoAI/aideml@ad73d227af481bea3de06f884f41b2993dd6453a](https://github.com/WecoAI/aideml/tree/ad73d227af481bea3de06f884f41b2993dd6453a)。已核对 `aide/agent.py` 的 search_policy、`aide/journal.py` 的 Node/Journal 和 `aide/utils/config.yaml`。

参考决策顺序：先满足独立 draft 配额；随后按 debug 概率抽取可修复的 buggy 叶节点；没有选中 debug 时，若没有有效程序则继续 draft，否则 improve 当前 validation best。失败根节点也计入 draft 配额。debug 深度统计连续 buggy 父代链，根深度为 0；不是树的绝对深度。

上游默认五个 drafts、debug 概率 0.5、最大 debug 深度三、二十步、五折 CV。本次 adapted pilot 使用三个 drafts、概率 0.5、深度二、十个主搜索节点和已有 MLE 固定切分。独立 seeded RNG、可信执行/CSV 评分替代模型自报有效性/分数；公开失败反馈和独立 control 的治理约束均明确保留。源代码构造失败且没有 artifact 的节点不能充当修复父代；它仍是一次计费失败和一次根尝试。

## 九模块配置

| 模块 | 本项必须实现的行为 |
| --- | --- |
| policy | 三个独立根 draft；按上述顺序选择 debug/improve/draft；同时明确父代和算子；不访问网络、时钟或最终分数 |
| operator | draft 无父代；debug 接收失败程序及该父代的真实公开错误，不要求伪造分数；improve 接收有效程序及 dev 结果；保持 M7 JSON artifact/hypothesis 外层 |
| budget | 最多十个主节点，失败也计数；每节点至多一次构造调用；一次独立初始 control 单列；沿用原累计 ¥200 campaign，无新费用权限 |
| frontier | 保留完整代码树与非最优历史；buggy 叶可在深度/预算允许时修复；只有有效分数可更新 incumbent，严格同分保留先出现者 |
| memory | 仅 run-scoped L1 Journal；记录源绑定的生成计划、规则意图、公开结果/错误和 dev 分数；实际进入后续构造；不自动提升 L2、不跨 run 导入 |
| knowledge | 关闭 |
| execution | 复用 M7、PublicTrainDomain、SandboxRunner；120 秒执行上限；公开 dev 反馈含有界真实 stderr；密钥、私有标签和终评分数不进入 worker 或记忆 |
| evaluation | 复用 PublicTrainBundle、可信评分、预测 hash 和 submission materialize；先冻结 dev winner，再报告本地 final；官方 grader 只对冻结提交终评 |
| admission | validation best；不沿用 full MLE 的 layered/calibration 门禁；无有效程序时报告 no_valid_submission，最终成绩为 null |

## 一次运行的数据流

固定 task、数据切分、参数和源码 → 建立隔离 control → 为主节点预留预算 → policy 根据当前树和可用预算同时选父代/算子 → M5 提供源绑定 Journal → M7 构造完整 Python 程序 → 隔离训练与预测校验 → 可信 dev 评分或失败反馈 → 保留节点、写入并激活 L1 摘要 → 只按有效 dev 分数更新 incumbent。

结束时冻结唯一 winner，复用其原始训练输出做本地终评与提交；不重新训练、挑选其他候选或把最终分数反馈给搜索。无有效 winner 时保留全部尝试和费用，明确缺失成绩。

## 当前源码差距及最小接缝

1. `Policy.select` 目前只返回父代列表。AIDE 需要父代与算子的一次明确选择；允许增加一个内部结构化选择结果，同时保留旧列表调用者。不能先在 observe 固定 debug，再在预算过滤后改选父代而仍使用旧算子。Framework 的 evolve/inspect/replay 接口不变。
2. runtime 只授权 OK/scored 父代，树 admission 会 prune 所有非赢家。需要显式的调试父代能力与 opt-in 保留语义：授权必须同时核对终态、artifact、叶节点、连续 debug 深度和预算；普通方法保持成功父代限制。树恢复必须保留并验证该配置，不引入现有 restore 不支持的隐式子类。
3. 构造 recipe 目前没有 debug/improve 种类。增加真实语义；debug 不制造 numeric comparison。原始错误通过 M5 的授权上下文传入，不能借 strategy 或 private evaluation metadata 绕过投影。
4. L1 candidate 状态不会被检索，默认 BestFirst 会把成功记录升到 L2。增加当前证据绑定的 L1 激活路径；AIDE 不继承该 L2 晋升。M5 从 authoritative proposal 和公开 dev evidence 形成摘要。复用 M7 已有 hypothesis_frozen=False：初始 hypothesis 记录规则意图，构造器输出的 effective hypothesis 记录实际生成计划；原始 materialization 同时保留两者。无需从代码 docstring 提取计划，不额外调用模型编造摘要。
5. 当前 MLE 入口将一个 seed 同时用于数据与搜索。专用 builder 必须分离 split_seed/search_seed：bundle 和全部 dev/control/final EvalRequest.seed_set 使用固定 split_seed，策略/控制抽样使用 search_seed。

复用现有预算/provider/数据/沙箱/提交/回放路径。新增方法代码集中在 composition 的策略与配方、现有 M5 接缝和 zoo runner。禁止另建优化主循环、supervisor、费用账本或模型评分器。

## 冻结的小规模配置

- main 节点数 10（含初始）；draft 配额 3；debug_probability=0.5；max_debug_depth=2。
- main/control 模型均取原 campaign 的 alias；reasoning_effort=low、max_completion_tokens=16384；不声称不可变模型快照或供应商 seed 可控。
- 搜索 seeds 0/1/2；每个任务固定同一个数据切分 seed。三个任务为 spooky-author-identification、leaf-classification、nomad2018-predict-transparent-conductors。
- 先运行 spooky 单 seed smoke 验证完整提交链，再执行预声明矩阵。smoke 的来源/配置/费用单列；若与矩阵完全一致且在首次调用前已声明属于矩阵，可作为该单元格，不能重复付费挑选较好结果。
- 每个 run 一份 manifest、原始树/构造/评分记录、method-report、冻结提交及费用凭证。context 必须容纳十个有界 L1 摘要，调试父代反馈缺失时在调用前拒绝；不默默降为普通改进。
- 全部费用继续原累计 campaign。截至 C02 v3 结束为 ¥21.167970，实际开跑前重新读取原账本。不得复制或打印凭据内容。

## 验收

- A1：从 Framework.from_profile 运行，前三个主节点是独立 roots；后续 improve 选择有效 validation best，同分不换 incumbent。
- A2：注入可识别语法错误，debug_probability=1 的 fixture 真实执行失败→debug 子节点→修复成功；debug 请求含原 artifact 和原公开错误。
- A3：buggy 非叶、深度到限、无 artifact 或预算不足的父代排除；非最优有效历史保留。普通方法不能选择失败父代；伪造父代/配置/RNG 的恢复在再次调用前被拒绝。
- A4：全失败返回 no_valid_submission 与 null final；尝试/失败/未完成计数和费用完整，没有用 baseline 填缺失分数。
- A5：改变合法最终数据不改变搜索输入、树选择或 winner；跨 search seeds 保持同一数据切分和 dev/control/final 请求身份。官方 grader 只在冻结提交后调用。
- A6：实际生成计划标记、dev 分数和选中失败父代错误被后续构造消费，均能追溯原 artifact/evidence；较早失败父代也不能被 top_k/字符预算丢失。无私有标签/预测元数据、L2 或跨 run 信息。
- A7：完成候选后的恢复复用原训练输出，不重发 provider；记录 replay 不调用模型、训练或官方 grader。改变来源/数据/参数拒绝。
- A8：真实 smoke/矩阵按预声明报告所有任务和 seeds，包括失败。公布逐任务成绩、valid/total、树轨迹、耗时、费用、模型身份限制和差异，不由小矩阵推断奖牌率或论文区间复现。

验收必须经过公共 Framework 和真实数据流，不能用孤立 policy 私有方法测试代替。默认入口离线；live 显式启用。入口尚未实现，当前不提供可运行 AIDE 命令。实现后补命令、来源提交、关键证据路径和最终 CI/合入状态。
