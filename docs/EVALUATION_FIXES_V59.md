# v59 数据内容、进程身份、配置、回执与 replay 修复

本轮在 v58 基础上修复五个运行边界。Mac 使用 `make check`，Linux 使用 `make accept-linux`；当前提交的验收结果以其实际日志和新证书为准。本说明不将历史成功记录视为本轮验收，也不宣称完成真实外部模型调用、外部 benchmark campaign、host parity 或产品级认证。

## 数据集内容与评估上下文

仅比较 `gsm8k-0` 等样本 ID，无法区分题目或标准答案已经改变的数据集。`GSM8KEvaluator` 现在在构造时复制题目及数值标准答案，内部使用不可变记录和元组；`items` 返回独立视图，修改原输入或返回值不会改变评估数据。

`evaluation_context` 是带版本的规范 JSON 的完整 SHA-256，绑定有序 question/gold 列表、评分规则、评估器版本、反馈配置和已声明的 solver 配置。数据顺序属于摘要的一部分；判定回执内的逐项证据则按 item ID 排序。solver 身份包含适配器类型及公开的模型、版本、采样等设置；自定义影响输出的配置应通过 JSON `evaluation_identity` 映射或纯零参数方法声明。凭据和调用用量不作为模型配置记录；自定义声明也不应包含秘密。

框架在首次调用和证据写入前检查已绑定的评估配置，GSM8K 评估期间也检查配置是否改变。原对象的模型、版本或评估配置发生变化后应构造新评估器，不允许继续沿用原摘要。摘要随 `EvalResult`、cascade、执行结果和检查点保存；恢复时重新验证，候选与基准的最终比较必须使用同一评估上下文。

兼容的 opaque 评估器可以继续使用空字符串上下文，但空值不认证任何数据内容或未声明配置。空上下文与非空上下文不能作为可比结果混用；类名相同也不能证明 solver 的隐藏配置相同。外部评估适配器声明非空摘要时，返回结果必须匹配该声明；外部调用方仍负责证明其摘要对应实际执行的数据和配置。

## 进程身份写入与恢复读取

Linux `/proc/<pid>/stat` 的进程名可能含空格、换行及括号，直接按空格拆整行会把 starttime 位置读错。新 `core/executor/process_identity.py` 从最终右括号之后解析字段，并核对 PID；主进程的身份读取和 detached wrapper 的 target 身份写入共用该实现。

wrapper 只有取得有效的 `(pid, start_ticks)` 后才发布身份文件。无法读取或持久化稳定身份时，它清理自己尚未回收的直接子进程并失败，不发布缺少 starttime 的可接管记录。恢复仍检查 starttime 与非僵尸状态，避免把复用的数值 PID 当成原进程。这是 Linux 进程身份边界；Mac 的解析与协议检查不替代 Linux 的真实 `/proc`、owner crash 和进程接管测试。

## 配置前置校验

`LoopConfig.validate()` 在每次 `evolve()` 最前执行，因此创建框架后再篡改配置也会被检查。无效配置在预算预留、LLM／评估器调用及证据记录之前失败。

预算、预留估算、基准间隔、代数与批次参数需要符合各自范围的整数，拒绝 bool、字符串、小数和非有限数；`control_share` 必须处于 `(0, 1)`，`noise_floor` 必须有限且非负。checkpoint 标志需要真正的 bool，resume 要求开启 checkpoint，reeval 预留不得超过总预算。`max_generations=0`、`reeval_floor=0` 和 `stop_after_generation=0` 是合法边界；最后一项仍表示按原有语义在相应边界提前停止。

## v2 判定上下文与回执身份

旧回执只使用候选 ID、head、评估器版本和规则生成短摘要。同一候选对不同基准得出 ACCEPT 与 REJECT 时可能共享身份。现在回执 ID 是完整 `sha256:<64 hex>`，绑定 `schema_version=2` 的判定上下文：候选与 incumbent 的身份、head、评估版本和评估上下文，排序后的逐项二元证据，cascade 状态、noise floor、forced-reject 原因、规则及最终 verdict。

完整上下文作为独立 `decision_context` 快照写入只追加的 gate evidence。审计检查摘要，并从快照重新运行准入判定，核对回执及 F/B/N 投影；只修改摘要不能使不一致的判定获认证。原输入对象后续变化不会改动已保存快照。相同证据乱序保持身份一致，不同基准、证据或阈值生成不同身份。总分、成本、反馈文本不进入准入判定或回执身份；一候选一次准入的冲突检查继续保留。

旧 context-free 回执仍保留原字节并可读取，但新审计会明确拒绝认证；涉及这些回执的中断 resume 也会因恢复计划不一致而拒绝。不会推测或补造旧判定上下文，也不会重新准入来掩盖旧证据。保留旧运行供历史审查，需要新认证时应在新目录重新评估。v1–v58 历史验收文件并不会因为当前审计规则变化而被重写。

## replay 隔离与适配器契约

`Framework.replay(task_desc=None, *, adapter_factory=None)` 在独立运行中重新执行任务，然后比较检查点、Receipt 链、结果及治理审计。它要求已经执行 `evolve()` 并启用 checkpoint。重新执行会再次调用适配器，可能产生模型提供方费用；它不是离线读取 journal 来模拟结果，也不承诺真实远端服务返回确定性响应。

每次进入执行阶段都创建唯一的 `<workdir>/replays/replay-*/` 目录，不删除或复用前一次目录。证书记录 `replay_id`、绝对工作目录和 `mode=independent_rerun`；执行失败及 factory 设置失败也会留下失败证书和本次目录，供后续重试与审计。缺少必要复制能力等前置检查失败时，不启动新的执行。

首次 `evolve()` 在调用适配器之前保存其初始状态。proposer 和 evaluator 一起 deepcopy，以保留 evaluator 引用 proposer 等共享对象关系；每次 replay 再独立复制该初始状态。扩展 registry 也从运行前副本复制，避免使用原运行累积后的扩展状态。外部命令适配器通过 `fork(workdir, store)` 绑定新目录与新 store，外部 proposer 的 fallback 使用隔离后的副本。若调用方显式替换了适配器，replay 会复制替换后的对象，调用方需提供与原运行初态等价的配置和状态。

持有锁、连接等不可 deepcopy 资源的适配器，或 `__deepcopy__` 返回自身的对象，不会被默认共享给 replay。应传入以下 factory：

```python
def adapter_factory(workdir, store):
    # 创建与原运行初态等价、相互关系正确的全新适配器。
    # 外部命令适配器应绑定这里提供的目录与 AppendOnlyStore。
    llm, evaluator = build_fresh_adapters(workdir, store)
    return llm, evaluator

replayed = framework.replay(adapter_factory=adapter_factory)
```

factory 返回顺序必须为 `(llm, evaluator)`，不得返回原运行仍在使用的有状态对象；调用用量仍遵守 `last_usage` 契约。factory 只负责这两个适配器，无法绕过扩展 registry 必须可独立复制的要求。

Python 普通函数的 deepcopy 通常仍返回同一个函数，因此默认支持函数的契约是：除每次覆盖的 `last_usage` 外，不依赖可变调用状态。可变闭包、全局计数器或隐藏资源不能被自动隔离；这类实现需要 factory 创建独立状态。框架检查不会证明任意自定义对象图或远端服务完全独立，适配器作者仍需保证该契约。

## 验收与历史证据

v59 新增对应回归测试，保留原有安全执行、计量、账本及崩溃恢复场景。Mac 执行可移植集合；Linux 完整验收执行真实平台测试，任何 skip/xfail 都不能作为成功结果。离线 fixture 和本地协议服务的测试不构成真实外部模型或 benchmark 成绩。

v1–v58 verifier 源码保留不改。本轮只归档真实 [v58 CI 运行 40870494602](https://github.com/YixuanZhang99/mori-27/actions/runs/40870494602) 产出的 `m0/verifier/v58/LAST_RUN.json` 与 `m0/verifier/runs/v58.jsonl`，供 v59 核验已有历史，不用新代码倒填旧版本证书。v59 自己的证书和 journal 必须由当前提交的独立验收产生，日志与摘要由验收包装器保存到 `artifacts/linux-acceptance/`。
