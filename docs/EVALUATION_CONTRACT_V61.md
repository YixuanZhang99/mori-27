# S2 统一评估契约：v61 使用与兼容边界

本阶段将严格评估契约接入 `Framework.from_profile(...)` 的配置运行路径，运行与检查点版本为 `composed-v2`。实现保留 `core.executor.types.EvalResult` / `EvidenceRecord` 作为规范结果，不另建第二个完整评估结果类；新增 `EvalResult.contract` 保存身份、计量覆盖、公开/私有数据和逐项结果。旧 M0 路径及小型 `core.eval.types.EvalResult` 保留，通过 `legacy_prompt` 显式适配。

本页保留 S2/v61 阶段说明；S3 新增作用域运行身份和上下文回流，见 [S3 指南](CONTEXT_FEEDBACK_V62.md)。当前 S5/v64 为 `composed-v5`，最新配置与迁移限制见 [S5 指南](HIERARCHICAL_BUDGET_V64.md)；下文范围按 S2 当时状态阅读。

本阶段范围是配置路径的评估传输、身份绑定、可见性和恢复，不等于所有旧执行器已经迁移。当前仍为 dev 单层、token 账本、串行、tree 和 inprocess。S3 检索/知识回流、S4 三层准入、S5 分层预算，以及 [清单](ABSTRACTION_ALIGNMENT.md) 中尚未接通的 S1 子条款继续保留。Mac/Linux 是否通过须以当前提交的实际记录为准。

## 规范结果与身份

纯数据契约在 [`executor/evaluation_contract.py`](../m0/core/executor/evaluation_contract.py)，校验、codec 与受限视图在 [`composition/evaluation.py`](../m0/core/composition/evaluation.py)，基础执行类型在 [`executor/types.py`](../m0/core/executor/types.py)。

| 数据 | 字段与约束 |
| --- | --- |
| `EvalRequest` | fidelity、split_id，以及可选 time_limit、budget_token、seed_set、resume_from；拒绝空身份、布尔伪整数、非法限额、重复或负 seed |
| `EvaluationBinding` | candidate_id、artifact_sha256、request_sha256、evaluator_version、evaluation_context、split_id、fidelity、seed_set |
| `EvalResult` | status、公开 metrics、CostVec、fidelity、uncertainty、反馈、曲线/轨迹/产物引用，以及必需的 contract |
| `EvaluationContract` | binding、measured_cost_units、token_accounting、typed public/private、items、binding_source、visibility |
| `ItemOutcome` | item_id、可选二元 verdict、metrics、seed 和 public/private 可见性；同一 item/seed 不可重复 |
| `EvidenceRecord` | candidate_id、EvalResult、branch_ref、executor_status、attempt、insight、result_text；执行状态必须与评估状态一致 |

domain 必须返回自己的 binding，driver 根据冻结 manifest、实际产物和请求独立计算期望值再比对。不能在收到结果后，把请求中的候选、数据集或评估器身份填入缺失的 producer binding，从而把错绑结果变成成功证据。成功结果必须声明 `binding_source="producer"`；在已知调用失败、没有成功返回结果时，失败证据可以标记 `invocation`，不会因此获准晋升。

结果写入和恢复都经过严格 codec。`encode_evidence()` 输出 `schema_version=1` 的 envelope，`decode_evidence()` 拒绝未知/缺失字段、非法类型、非有限数、状态矛盾和绑定不一致。公开/私有数据、逐项结果、费用和曲线/轨迹/产物引用均保留在完整持久证据中。`allow_legacy=True` 仅用于显式读取缺契约的旧数据，不能认证期望身份，也不使其成为配置运行时的有效新证据。

## 接入原生 domain

保持同一公共入口，仅把 domain 配置改为 `native`，通过 `evaluator` 参数传入对象：

```python
from core.composition.defaults import composed_profile

profile = composed_profile(name="native-task")
profile["domain"] = {"name": "native"}
framework = Framework.from_profile(profile, llm, native_domain, config, workdir)
result = framework.evolve(task)
```

`native_domain` 需声明非空 `evaluator_version`、内容摘要格式的 `evaluation_context`，实现纯校验 `validate_request(request)` 和异步 `evaluate(proposal, request)`。如输入可变，还应提供 `validate_context()` 在调用前检查其内容是否仍与声明相符。仅声明一个 digest 不等于运行时能证明任意外部数据未变化；domain 应将实际数据、规则及相关配置纳入摘要并校验。

`evaluate()` 应使用实际执行的 proposal/request 和自身版本、内容身份构建 `binding_for(...)`，返回带 `EvaluationContract` 的 canonical `EvalResult`。`validate_request()` 必须拒绝无法真正消费的 seed、时限、预算或续跑参数，不能接受后静默忽略。运行时在启动和每轮付费调用前执行该校验；当前调度请求固定为 `EvalRequest("dev")`，字段传输和能力拒绝并不意味着 S5 已按预算动态分配 fidelity。

通过自定义 registry 注入的 domain 也必须满足相同契约。默认组件的指标名和方向应一致配置；`legacy_prompt`、frontier、prompt operators、metric admission 的目标不一致会在付费调用前拒绝。

## 显式计量与失败

CostVec 的零默认值不能证明发生了真实零用量。producer 必须在 `measured_cost_units` 中列出实际测量的单位；当前配置路径至少要求 `token` 和 `eval_count`。可声明的其他单位为 `wallclock`、`gpu_hours`、`usd`、`node`；非零值也必须有对应测量覆盖。声明只保留计量事实，不把这些维度自动变成 S5 的硬限额。

token/count 必须是非负整数，其他数值必须有限且非负；不能用 `True`、NaN 或负数结算。`token_accounting="split"` 表示输入/输出分别测量；`"total_only"` 表示只有总 token，此时约定总量存于 `tokens_in`、`tokens_out=0`。这不是声称所有 token 都是输入 token，消费者必须保留该标记。

先确认费用是否已知，再验证业务身份和结果。若结果错绑而费用完整，运行中止且结算已知实际费用，不形成准入或状态 mutation；若用量或覆盖缺失，则保留未结预扣并失败关闭，不能填零或自动重试。已知 operator/domain 内容失败保留类型化失败证据及费用；未知异常若没有完整成本证据，也不能认证免费执行。

## 兼容旧 prompt evaluator

`legacy_prompt` 仍接收 `evaluator(candidate_id, head_sha, prompt)` 返回的小型 EvalResult，先执行原身份校验，再投影为规范结果。逐项判定、public/private payload 与文本反馈保留；原 reliability 写入独立的 `contract.public.metadata`，不覆盖 producer 的 public data，也不自动解释为规范 uncertainty。legacy token usage 标记为 `total_only`。默认 evaluator 版本延续原 `det-v1`，原空 evaluation_context 保持为空，不能伪造 dataset 内容摘要。

此适配器只接受不附加约束的 `fidelity="dev"`、`split_id="dev"` 请求。time_limit、budget_token、seed_set、resume_from 或其他层请求会在调用前拒绝。需要这些能力时应实现原生 domain，并证明参数确实被消费。

旧 evaluator 的空内容上下文只能说明旧的不透明身份边界；它不能获得原生内容绑定级别的保证。旧 M0 gate 和 v59 回执按原契约保留，不因配置路径新增 codec 而变更历史记录。

## 公开视图、私有证据与准入

完整证据保存在 journal/checkpoint，用于审计与恢复。发往 policy 的 absorb、operator 父证据和 frontier 的数据经 `public_projection()` 投影：剔除 private payload、private metrics 和 private items，保留明确公开的信息。默认记忆吸收因此不会把这些私有字段写入生成上下文。

准入组件只收到 `ComparisonEvidence`，包含身份、成功状态、公开指标、fidelity 和 uncertainty；不提供 CostVec、私有 payload 或可任意遍历的完整 contract。这使成本不能通过标准准入输入混入分数规则。默认 `metric` 仍执行确定性的同 fidelity 指标比较。

这些视图是当前 dev 评估结果的字段权限边界。它们不替代 S4 的独立 admission/final_audit 调用、固定 split 权限或终审不回流规则，也不会自动清洗错误放入 public 文本的秘密。domain 必须正确区分公开反馈与私有数据；信任边界之外的插件仍需专门的隔离机制。

## 检查点与 replay 升级

S2 使用 `composed-v2`；S1 的 `composed-v1` 检查点缺少严格评估契约，恢复会在新的付费工作前明确拒绝。不要修改版本字段或补造身份来强行恢复。保留旧目录，需要新认证时使用新 workdir 重新评估；旧 M0 运行仍按自己的兼容规则处理。

v2 恢复核对 proposal/evidence 键集合、候选身份、产物、请求与冻结评估上下文，并通过 codec 恢复完整结果。cycle 边界、模块状态恢复和 fresh-factory 规则仍与 [组装指南](COMPOSED_RUNTIME.md#恢复与-replay)一致。未完成付费 cycle 仍不自动重调。replay 是再次执行，保留独立账本及证据，会再次发生真实模型/评估调用；确定性匹配不是免费回放或远端 exactly-once 保证。

## 验收入口

Mac 使用 `make check`；定向回归为：

```bash
cd m0
uv run --locked python -m pytest \
  tests/test_evaluation_contract.py \
  tests/test_composed_evaluation.py -q --fail-on-skip --strict-markers
```

S2 对应 [v61](../m0/verifier/v61/README.md)；当前 Linux `make accept-linux` 使用 v62，保留 S2 全部命令组及全量 pytest。执行记录追加在 [对照清单](ABSTRACTION_ALIGNMENT.md)，包括尚未覆盖的条款、Mac 结果和同一 SHA 的 Linux CI 链接。历史证据必须从真实成功 artifact 归档，不能以预期结果或新环境重跑替代。
