# 配置组装运行时：S1 使用与边界

开发基准是 [AutoResearch 模块化统一抽象](AutoResearch模块化统一抽象.md)，逐项状态及后续验收条件在 [对照清单](ABSTRACTION_ALIGNMENT.md)。五个阶段依次为：S1 模块组装、S2 统一评估契约、S3 记忆与知识回流、S4 三层准入、S5 分层预算。本页保留 S1（v60）的组装说明；后续评估契约见 [S2 指南](EVALUATION_CONTRACT_V61.md)，S3 的 ContextPack 变化见 [S3 指南](CONTEXT_FEEDBACK_V62.md)。后续 S5/v64 运行版本与完整离线入口见 [S5 指南](HIERARCHICAL_BUDGET_V64.md)；下文 S1 边界按历史阶段阅读。是否通过以对应提交的 Mac 检查和 Linux Actions 新证据为准。

`Framework.from_profile("composed_prompt", ...)` 是新的配置开发入口，继续使用同一组 `evolve()`、`inspect()`、`replay()` 公共方法。旧 `Framework(...)` 默认 M0 路径与 GEPA、FunSearch、MAP-Elites profile 仍保留，其二元准入、IID 对照、批次调度及恢复能力有各自的历史契约；这些能力不能直接视为 S1 组装路径已经具备。

## 运行一个离线闭环

先在仓库根执行 `make setup`，再运行：

```bash
cd m0
uv run --locked python - <<'PY'
import tempfile

from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

workdir = tempfile.mkdtemp(prefix="composed-prompt-")
framework = Framework.from_profile(
    "composed_prompt",
    llm=MockLLM(),
    evaluator=toy_evaluator,
    config=LoopConfig(
        total_budget=30_000,
        reeval_floor=0,
        intent_cost=2_000,
        max_generations=3,
        batch_size=1,
        max_inflight=1,
    ),
    workdir=workdir,
)
result = framework.evolve("Toy arithmetic prompt optimization")
inspection = framework.inspect()
print({"workdir": workdir, "best_score": result["best_score"],
       "cycles": result["cycles"], "memory_entries": inspection["memory_entries"],
       "ledger": result["ledger"]})
PY
```

这个例子使用脚本模型和本地评分器，模型每次调用显式计入 1,000 个模拟 token，评分器显式报告零 token。分数只验证优化链路，不是外部 benchmark 成绩。cycle 从 0 开始，`max_generations=3` 最多执行 4 个 cycle；`intent_cost` 是每轮预扣估计，最终按报告的实际 token 用量结算。

一次 cycle 顺序执行预算预扣、policy 的 `observe/select/ideate`、skills、operator、executor/domain 评估、policy 的 `absorb`、admission、预算结算和状态写入。driver 负责候选身份、谱系与状态写入顺序；policy 只能提出允许的状态变更，不能直接添加、合并或剪除候选来绕过准入。

`inspect()` 返回运行结果、实际 assembly、记忆条目数和最近的 replay 证书。`x1.jsonl` 保留 manifest、预算事件、候选与评估证据、判定及检查点事件；配置路径的事件名包含 `composed_evidence`、`composed_decision`、`composed_checkpoint`。S1 判定摘要使用内容摘要作为 `receipt_id`，尚不等于 S2/S4 完整评估身份与分层准入认证。

## 配置、注册表与默认组件

内置配置位于 [`m0/config/profiles/composed_prompt.json`](../m0/config/profiles/composed_prompt.json)。`schema_version=1` 配置采用 `{ "name": "注册名", "options": {...} }` 选择组件。provider、domain 与 skills 分别配置；配置不能指定任意 import 路径或可执行表达式。

| 槽位 | 默认注册名 | S1 行为和选项 |
|---|---|---|
| provider | `provided` | 使用传入的 `llm`，由 `MeteredProvider` 按调用计量；无 options |
| domain | `legacy_prompt` | 显式适配旧 prompt evaluator；`metric` 默认 `dev/score` |
| policy | `greedy` | 确定性四钩子策略；`context_window` 默认 8 |
| policy（可选） | `llm_cycles` | 同一 provider 生成受约束的 JSON 计划；`context_window` 默认 8 |
| operators | `draft`、`reflective` | 无父候选起草、基于一个父候选及反馈改进；可设 `prompt_version`、`metric` |
| frontier | `tree` | `ResearchFrontier`；可设 `metric`、`direction` |
| memory | `scoped` | `ScopedMemory` 写入、提升与检查点；无 options |
| executor | `inprocess` | 进程内调用 domain；无 options |
| admission | `metric` | 比较同一 fidelity 的成功评估指标；可设 `metric`、`direction`、非负 `margin` |
| budget | `tokens` | 使用现有 token 账本；可覆盖 `total_budget`、`control_share`、`reeval_floor` |
| skills | 默认空列表；可选 `instruction` | 将 `options.text` 注入 operator 上下文 |

策略的 `context_window` 限制工作历史条数；每条保存有限节点摘要，任务文本也被截断。它不是 token 级上下文上限，也不会压缩或删除持久记忆。`llm_cycles` 只决定 operator、父候选和假设；解析结果必须通过约束检查，准入和状态执行仍由确定性机制负责。策略调用与 skill 中通过注入 provider 发起的调用计入同轮费用。离线例子的 `MockLLM` 只模拟 prompt 算子，不实现 `llm_cycles` 的 JSON 计划协议。

可以把配置字典直接传给 `from_profile`，例如配置指令 skill：

```python
from core.composition.defaults import composed_profile

profile = composed_profile(name="my-prompt-run")
profile["policy"] = {"name": "greedy", "options": {"context_window": 8}}
profile["skills"] = [
    {"name": "instruction", "options": {"text": "保留可验证的逐步推理提示。"}}
]
framework = Framework.from_profile(
    profile, llm, evaluator, config, workdir,
)
```

替换模型时可向 `llm` 传入新的 callable；替换领域或策略等组件时，使用 `default_registry()` 后调用 `register(kind, name, factory, validate_options=...)`，再通过 `component_registry=registry` 传入。factory 接收 `BuildContext` 和隔离复制的 options。后续组件获得已计量的 provider，executor 获得所选 domain。注册名在同一槽位内不能重复，组件 options 默认不接受未知字段；自行注册带选项组件时必须提供纯校验函数。

所有名称、JSON 数据和 options 都先校验，再构造组件；串行配置限制也在模型调用前检查。注册表中的 Python factory 属于受信任代码，应只构造组件，不发起模型调用或实验。配置校验不能隔离恶意 factory。默认 `inprocess` 也不提供子进程或 Bubblewrap 安全边界；需要沙箱执行的任务须使用明确实现该契约的 executor。

## 评估、记忆、准入与预算的阶段边界

| 阶段 | S1 已接入的接口 | 后续仍需完成的行为 |
|---|---|---|
| S1 模块组装 | 同一公共 API、显式注册表、可替换组件、完整优化与状态闭环 | 每次变更仍须通过 Mac 和 Linux 验收 |
| S2 统一评估契约 | operator 产出 `Proposal`；domain 产出 `core.executor.types.EvalResult`；executor 产出 `EvidenceRecord` | 严格跨边界 codec、完整 artifact/dataset/evaluator 身份与成本契约 |
| S3 记忆与知识回流 | `absorb` 的记忆写入与提升通过 `StateApplier` 执行，保存到检查点 | 检索结果注入 operator、知识获取与回流、research/benchmark 隔离闭环 |
| S4 三层准入 | 默认只请求 `EvalRequest("dev")`，`metric` 比较 dev 指标 | dev/holdout/test 分层、独立最终准入与完整分层回执 |
| S5 分层预算 | 每轮预扣并结算 token；已知失败费用保留 | CostVec 多资源及分层分支分配、升降级、收敛控制 |

`legacy_prompt` 先调用原 evaluator 的身份校验，再把旧 `core.eval.types.EvalResult` 的分数和文本反馈转换成 canonical 评估结果。这是显式兼容边界；两种 EvalResult 仍存在，不能混用，也不能由 S1 声称全框架评估契约已统一。新 domain 可以直接返回 canonical 类型。

默认 `metric` 仅在成功评估且指标改善超过 `margin` 时准入；最小化目标需把 frontier 和 admission 的 `direction` 都设为 `minimize`，使用其他指标时还要同步 domain 和 operator 的 `metric`。旧 M0 的逐样本二元 gate 继续按原契约运行。

目前 operator 接收的检索上下文为空，只有显式 skill 等输入可补充内容。`knowledge` 非空配置会被前置拒绝；`mode="research"` 不会自动启用知识管线。现有记忆写入和上下文工作窗口不能替代 S3 的检索与知识回流。

token 账本保留七账户结构，但 S1 仅在首轮使用 `explore`、后续使用 `exploit`；`control_share` 等兼容配置不意味着此路径已运行 IID 对照。`baseline_every` 和 `noise_floor` 不驱动 S1 的对照或准入。CostVec 中其他资源可以留在证据里，尚未成为此路径的硬预算。provider/evaluator 必须每次报告有效 usage，明确的零用量才可按零结算；未知 usage 会保留未结预扣并终止运行。

## 恢复与 replay

S1 只支持 `batch_size=1`、`max_inflight=1`，其他值在执行前拒绝。默认开启检查点；正常运行要求新的空证据目录。需要恢复时，复用原 workdir、任务、assembly、预算和其他运行参数，将 `resume_from_checkpoint=True`，并保持 `checkpoint_enabled=True`。`stop_after_generation` 可以用于干净的 cycle 边界暂停，恢复时可清除它；`max_generations` 等其余配置必须与检查点一致。

恢复要求 manifest、domain 的版本及 evaluation_context、账本和检查点一致。目前只有默认 `ResearchFrontier` 具备该路径的 portable restore；自定义 frontier 不能据此宣称可恢复。对有内部状态的注册组件，必须成对实现 `checkpoint_state()` 与 `restore_state(state)` 才能恢复该状态。没有这对方法的状态不会自动保存；恢复 provider/evaluator 的会话或计数器也需要各自的状态契约。默认 greedy/LLM 策略会保存有界工作历史。

若 journal 显示一个 cycle 已开始、却没有对应完整边界检查点，恢复会拒绝自动重调。这包括已发生付费调用、未知 usage 或仅完成部分状态写入的情况。S1 尚无这些窗口的 durable adoption 契约；保留原证据进行核对，不应删除 journal 或重复执行来伪装恢复成功。

`framework.replay()` 在独立的 `replays/replay-*/` 工作目录中重新运行，并比较最终检查点与结果。它会再次调用 provider 和 evaluator，真实调用按实际用量记账并可能再次收费；新账本属于该次 replay，原账本不会变成第二次执行的汇总账本。每次成功或失败都留下独立目录和 replay 证书。随机模型即使正常运行，也可能因为结果不同而无法通过一致性认证。

默认 replay 使用运行前对 `(llm, evaluator)` 一起 `deepcopy` 的种子，保留二者的共享依赖关系。持有不可复制连接、可变闭包状态或外部资源的适配器需提供工厂：

```python
def adapter_factory(workdir, store):
    # 每次调用都创建独立的适配器和所需资源，绑定本次 workdir/store。
    return make_new_llm(), make_new_evaluator()

replayed = framework.replay(adapter_factory=adapter_factory)
assert replayed["replay_certificate"]["passed"]
```

注册表的每个 factory 也必须为 replay 构造新组件，不能返回闭包中缓存的原组件或原 provider 实例；运行时会拒绝复用可变实例。普通函数可共享身份的前提是无业务可变状态（usage 属性除外）；有可变闭包的函数应改用独立 factory。checkpoint 恢复的是已保存状态，replay 则要求从独立初始状态重新执行，两者的生命周期不同。

## S1 验证入口

`make check` 执行 Mac 静态检查、全部可移植回归、离线示例及包装器测试。三组新增测试覆盖配置预检与注册、默认组件和策略、公共 API 的端到端闭环：

```bash
cd m0
uv run --locked python -m pytest \
  tests/test_composition_registry.py \
  tests/test_composition_defaults.py \
  tests/test_composed_runtime.py -q --fail-on-skip --strict-markers
```

S1 的 v60 验收保留 v59 全部命令组并加入上述三文件组；当前 `make accept-linux` 使用 v62，继续继承这些组以及 S2 评估契约组，并新增 S3 上下文组。最终 pytest 全量组仍覆盖所有测试，任何 skip/xfail 都失败。v60 证书只标明 S1 组装证据，不将 S2–S5 声明为完成；后续阶段单独记录。完整环境和证据保存规则见 [开发指南](DEVELOPMENT.md)。
