# S5 分层物理预算与 fidelity（v64）

本页保留 S5/v64 的契约和边界。当前 S6/v65 的 `composed-v6` 与新增校准功能见 [S6 指南](PROXY_VALIDITY_V65.md)。S5 引入的配置运行时版本为 `composed-v5`；旧 v1/v2/v3/v4 检查点缺少新的物理操作状态，明确拒绝自动升级。默认 tokens 配置和 hierarchical 配置均使用该运行版本。

S5 在同一 `Framework.from_profile()` 入口增加 `budget=hierarchical`，按全局、方向、候选三个视图约束真实物理用量，保留 [S4 三层准入](LAYERED_ADMISSION_V63.md)和 [S3 经验回流](CONTEXT_FEEDBACK_V62.md)。计量、限制与准入仍各司其职：预算决定是否能调用，公开评估证据决定是否晋升，费用不能成为准入分数。

本页与 [逐项清单](ABSTRACTION_ALIGNMENT.md)记录实际实现范围。五阶段增量不等于统一抽象全部条款完成；worktree 组装、HITL、种群、事件总线及真实外部 campaign 等缺口继续保留。GPU·h 和 USD 的账本契约回归不代表已经运行真实 GPU 或完成提供方账单对账。

## 完整离线 research 示例

在仓库根目录运行：

```bash
uv run --project m0 --locked python m0/examples/composed_research_offline.py
```

也可传 `--workdir /absolute/path/to/new-directory` 保留可审查文件，指定目录必须尚不存在；省略时使用新临时目录。示例源文件是 [composed_research_offline.py](../m0/examples/composed_research_offline.py)。

示例组合 native ChecklistDomain、tree/反射算子、scoped memory、实际打开的 local_files ground/audit、三层准入与 hierarchical budget，最后显式导出经验并 ingest 到独立知识记录，执行独立 replay。输出包括 dev_best、gate_selected、final_audit、三层预算、memory_export 的内容摘要和 replay 结果。

三组离线案例各有真实内容摘要；ground 中的检查建议会改变候选，audit/held-out 反馈不进入生成。proposer 的 token 用量是明示的合成 fixture 数量，domain 的 eval_count 是实际本地调用数，node 是候选数量；没有声称测量 GPU、货币或 wallclock。示例固定一个 dev rung，变化 fidelity 的行为由独立回归测试覆盖。

本地执行的可核对输出为 3 个候选、6 次本地评估、60 个合成 token，三单位预扣均归零；final 调用 1 次，导出 3 条 L2 经验，`replay_passed=True`。分数 1 只表示该合成检查表满足条件，不能解释为外部任务成绩。

## 选择预算配置

保留默认 `budget=tokens` 可继续使用旧配置语义。新的 native research 配置显式选择 `hierarchical`，例如：

```python
profile["budget"] = {
    "name": "hierarchical",
    "options": {
        "limits": {
            "global": {"token": 100_000, "eval_count": 30},
            "direction": {"token": 60_000, "eval_count": 20},
            "candidate": {"token": 15_000, "eval_count": 6},
        },
        "reservation": {"token": 4_000, "eval_count": 1},
        "operation_reservations": {
            "planning": {"token": 2_000, "eval_count": 0},
            "operator": {"token": 4_000, "eval_count": 0},
        },
        "fidelity_rungs": [
            {"fidelity": "shallow", "split_id": "dev", "seed_set": [11]},
            {"fidelity": "full", "split_id": "dev", "seed_set": [11, 29]},
        ],
        "rung_by": "direction_calls",
        "rung_every": 2,
        "convergence": {
            "patience": 3,
            "min_samples": 4,
            "min_improvement": 0.01,
            "metric": "dev/score",
            "direction": "maximize",
        },
    },
}
```

这段数值只展示结构，需要按实际调用上界与 domain 能力调整；不是推荐的资源规模。domain 必须支持每一个请求，不能仅改 fidelity 标签却沿用不符合契约的返回值。

`limits` 必须明确包含 global、direction、candidate。global 定义本次使用的单位；direction/candidate 可对其中的单位设限。默认 reservation 和每一个 operation override 必须完整覆盖 global 的所有单位，未知单位/选项和缺失覆盖前置拒绝。

支持的物理单位为 token、eval_count、node、wallclock（秒）、gpu_hours（GPU·h）和 usd；前三者为整数计数，其余为有限非负数量。它们分别记账，不能相加成一个通用“成本”。显式零表示已经确认该操作不消耗该单位，不能用缺失计量或 dataclass 默认零冒充。

`Proposal.measured_cost_units=None` 是旧接口未知覆盖，不能直接用于多单位结算。默认 PromptOperator（包括已知失败）声明 token/node/eval_count：一个候选节点、零次评估；LegacyPromptDomain 声明相同三单位：零个候选节点、一次评估。内置实现没有因此获得 GPU/USD 计量能力，其他单位需要真实测量来源。新候选 node 数由 driver 权威计为 1；没有 node 声明时可按已执行的候选生成补记，若显式声明却报非 1，仍计 1 后拒绝该结果。它不会据此补造 token/GPU/USD 等未知测量。

operation 可为 planning、operator、dev、dev_baseline、admission、final。admission/final 请求由准入协议决定，不能通过 dev fidelity 配置降低终审要求；这些调用仍共享同一物理账本。没有 override 的操作使用默认 reservation。

## 三层视图与原子预扣

每次操作写一条完整单位篮子的 reserve/settle 记录。global、direction、candidate 是同一记录的三个投影，不是重复收费三次。任一层任一单位不足，整条预扣失败，其他层不留下部分扣款；并发组件调用由同一控制器内的锁序列化。配置运行时仍串行，不据此声明多进程数据库事务。

每条 reservation 绑定固定 intent、候选、方向、操作类型、请求、depth 和数量，指纹与身份不能重复使用。已开始操作不能按未执行释放；仅尚未调用的预扣可以释放。结算要求实际用量完整覆盖全部配置单位；负数、NaN、缺测量或错绑不形成部分结算。

实际用量超过预扣时仍如实记账，随后进入只读结算状态，阻止后续付费调用。预算机制不能撤销已经消耗的外部资源，也不提供 cgroup/GPU/time 的操作系统限额。执行器必须使用可靠估计或外部硬限制来保证单次操作不越界。

未知用量保留 reservation 并阻断新调用；不能推断免费失败。开放预扣只接受同一指纹下的完整真实用量，重复结算或更改费用来源会被拒绝。公开预算视图包含各单位的 used、reserved、committed、remaining，超额不会被截断为零来隐藏。

## 配置运行时的计量边界

方向身份由候选骨架确定：无父候选以自己的 ID 为方向根，后代沿主父链继承根；深度使用真实父关系。planning/absorb 另用 `coordination` 方向，并计入对应候选预算，不能把协调开销遗漏在全局账本之外。结果 `ledger` 在 hierarchical 模式下是上述三层 schema，不能继续按旧 token 账本的 `spent` 字段读取。

operator 收到 `OperatorRequest.context["budget"]`，包含 `state`、`allocated_request`、`direction_id`、`depth`；state 在本次 operator 预扣并开始后刷新，包含当前 reservation。这些只提供可读的预算信息；真正授予/拒绝仍由控制器完成。policy 的 observe/select 获得账本摘要，不能自行修改预算事件。

operator/evaluation 声明的 token 不得低于同一共享 MeteredProvider 在该调用内的实际增量；低报会留下已知小计与差异记录，保持 unresolved 预扣并阻止后续付费调用。这个下限不代替 domain 自身额外调用的完整计量。

每次实际 domain 调用至少消耗一次 eval_count；显式报零时先按实际一次记账再拒绝结果。domain 若执行批量实验并实测报告大于一的数量，保留完整数量，不会压成一次来少算费用。

planning 的 token 来自 MeteredProvider 累计真实用量差值；出现未知 usage 时该计数器拒绝作为结算总量，保留 unresolved 预扣。GPU/USD 配置要求 operator/domain 声明并返回真实计量；任意付费 planning 没有相应货币/GPU meter，不能以零结算。额外单位下仅允许已知纯本地 policy/skill 以零消耗运行。

wallclock 在 producer 明确声明测量时采用其值，否则由 runtime 在操作调用边界使用单调时钟测量，单独进入预算结算；不会给 producer 的原始 EvidenceRecord 补造声明。它是所保护操作区间的时间，不是整个 run 的总墙钟，也不提供强制超时。hierarchical 模式只接受内置 LocalKnowledge，确保规划/audit 不会出现未计量的外部知识调用；高成本网络知识 backend 明确不支持。

## Fidelity 与可比较性

`fidelity_rungs` 是非空 EvalRequest 列表，只允许 dev split。可包含 seed_set、time_limit、budget_token、resume_from，但实际 domain 必须明确支持。allocation 本身不收费、不推进阶梯；成功授予的 dev 预扣推进 `direction_calls`，dev_baseline、admission 和 final 不推进该计数。

`rung_by=direction_calls` 按同方向的 dev 调用进展选择阶段；`rung_by=depth` 使用真实骨架深度，不能用循环轮号代替。`rung_every` 为正整数，超出阶梯后停留在最后一个 rung。

比较口径包含请求摘要、fidelity、seed、内容上下文、评估器版本和 split。不能把 shallow 的数值和 full 的数值直接比较后晋升；不同口径的进展也不能拼成连续改善/停滞样本。已有 gate-selected 候选时，变更 dev 请求需用同一新请求实际付费补评 incumbent，再显式推进当前 dev 比较基准；当前 dev_best 随之重建，历史证据/回执仍保留。

## 低样本停止规则

`convergence` 可省略；启用时必须声明正整数 min_samples 与 patience。只有成功且包含指定有限公开指标的 dev 证据才计入有效样本。严格超过 min_improvement 才重置无改善次数；失败可作为无改善尝试，但不能补足有效样本数。

纯收敛控制器在比较口径变化时重置窗口；配置运行允许的请求/fidelity/seed 变化因此不能拼接旧样本。实际 configured run 的数据上下文和 evaluator version 已冻结，漂移会被拒绝，不能通过“重置窗口”透明更换。admission/final 的隐藏证据不得驱动搜索停止。各方向预算独立核算；已耗尽方向只在本次 policy 选择视图中标为不可选，保留骨架并重新验证选择资格，不破坏持久 frontier。greedy 可选其他可用分支或创建新的 draft。全局耗尽或未知用量阻止新的付费工作。输出信号明确为预先定义的规则，`statistical=False`，不声称统计显著或找到全局最优。

周期 anchor、异质 proxy–true 秩相关告警/降级及负反馈写回 M5 尚未实现；当前同请求基线补评不替代这些要求。

## 日志与验收

操作日志保存递增序号、前项摘要、配置摘要、计量 stamp 与事件摘要。恢复从实际只追加日志重建三层视图，再严格比对 checkpoint；旧状态不能抹掉已发生调用或将不同配置的记录重新解释成可用预算。

当前 replay 是独立重执行并要求完整 snapshot/result 精确一致。runtime 实测 wallclock 或非确定性外部结果可能使比较失败，实际费用仍保存在重执行日志中；固定计量离线例子的成功不能外推为任意真实运行都可逐字重现。它也不是恢复未知付费操作的手段。

v64 显式执行 `test_hierarchical_budget.py`、`test_composed_budget.py`，并单独执行 `examples/composed_research_offline.py`。Mac 的 `make examples` 也包含该例子，合计四个离线示例。完整 Linux 验收保留 S1–S4 和全部历史安全回归，不将 fixture 的物理数量当作真实外部 campaign 成绩。当前验收及证据来源见 [v64 verifier 说明](../m0/verifier/v64/README.md)。
