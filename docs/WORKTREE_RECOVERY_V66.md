# S7：配置 worktree 命令与进程接管

本指南对应 v66 的配置执行路径，沿用 `Framework.from_profile(...)` 入口、S2 canonical evidence、S4 三层准入、S5 物理预算和 S6 proxy 校准。默认 `composed_prompt` 仍是 inprocess；选择 `domain=command` 与 `executor=git_worktree` 才启用本文协议。实现子范围和实际检查结果见 [逐项清单](ABSTRACTION_ALIGNMENT.md)，Linux 验收定义见 [v66](../m0/verifier/v66/README.md)。

本阶段是可选 executor 接入，保留 `composed-v6` 检查点结构；新 manifest 显式绑定 `command_domain` 和 `executor`，不能把原 inprocess 任务直接改配置后接管。v1–v5 检查点仍不自动升级。

## 配置入口

下面是配置片段。调用前需准备已有提交的 Git 仓库、受保护的 `evaluate.py`、候选文件，以及位于仓库之外的真实评估数据；`provider` 必须提供可核对的 token 用量。这里不把任意脚本当作已经实现的评估器。

```python
import sys
from core.composition.defaults import composed_profile
from core.loop import Framework, LoopConfig

assembly = composed_profile(name="local-command-research")
assembly["domain"] = {
    "name": "command",
    "options": {
        "command": [sys.executable, "evaluate.py"],
        "evaluator_version": "my-evaluator-v1",
        "data_dir": "/absolute/path/evaluation-data",
        "split_paths": {
            "dev": "dev.json",
            "admission": "admission.json",
            "final_audit": "final.json",
        },
        "fidelities": ["dev", "admission", "final_audit"],
        "measured_cost_units": ["token", "eval_count", "node"],
        "time_limit": 120,
    },
}
assembly["executor"] = {
    "name": "git_worktree",
    "options": {
        "base_repo": "/absolute/path/candidate-repository",
        "base_ref": "HEAD",
        "artifact_path": "candidate.py",
        "protected_paths": ["evaluate.py"],
        "sandbox": "none",  # Mac 可信本地开发；Linux 使用 bubblewrap。
    },
}
assembly["budget"] = {
    "name": "hierarchical",
    "options": {
        "limits": {
            "global": {"token": 100_000, "eval_count": 30, "node": 20},
            "direction": {"token": 60_000, "eval_count": 20, "node": 10},
            "candidate": {"token": 15_000, "eval_count": 6, "node": 1},
        },
        "reservation": {"token": 4_000, "eval_count": 1, "node": 0},
        "operation_reservations": {
            "planning": {"token": 2_000, "eval_count": 0, "node": 0},
            "operator": {"token": 4_000, "eval_count": 0, "node": 1},
        },
        "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev", "seed_set": [11]}],
    },
}
# layered 准入可按 S4 指南显式配置；默认仍是 dev-only metric。
fw = Framework.from_profile(
    assembly, provider, None,
    LoopConfig(max_generations=1, total_budget=100_000,
               intent_cost=2_000, reeval_floor=0, checkpoint_enabled=True),
    "/absolute/path/new-run",
)
result = fw.evolve("Improve the candidate against the declared evaluator")
```

`run_root` 默认是本次运行目录中的 `worktrees/`。`base_ref` 启动时冻结为 commit；候选文本只写到声明的 `artifact_path`。相对脚本或输入文件须在 `protected_paths` 中，或就是本次绑定的候选文件。候选、保护文件和内部 `.autoresearch-command` 路径不得重叠。数据 split 必须位于候选仓库之外；相同内容只改文件名不会得到不同的数据身份。可执行文件通过绝对路径或 PATH 名解析后冻结其文件 hash，内容变化会拒绝后续执行。

`command` 域必须使用 `git_worktree`，不能交给 inprocess 绕过该协议。该执行器要求 hierarchical 预算和启用 checkpoint；默认 token-only 预算不能直接接管。当前仅接受内置 Greedy/LLMCycles policy、PromptOperator 和 InstructionSkill，避免在恢复中重放未声明副作用的任意插件。示例预算只展示结构，需按真实调用上界调整，评估器指标也必须匹配 frontier 的默认 `dev/score`。配置运行仍要求 `batch_size=max_inflight=1`；本阶段没有通用并发池或分布式调度。

## 命令与回执契约

执行器在独立 worktree 中运行 `command + [request_json_path, response_json_path]`。请求包含完整 `EvalRequest`、候选和产物文本、当前 split 的真实路径、预期 producer binding、operation key 和 execution token。评估器必须读取本次请求，按真实执行填写 canonical `EvidenceRecord`；请求中的身份是需要验证并回传的绑定，不能替代实际内容和成本测量。

响应是严格 JSON envelope，字段为 `schema_version=1`、`operation_key`、`execution_token`、`request_sha256` 和 canonical codec 输出的 `evidence`。`request_sha256` 是收到的请求原始字节的 `sha256:` 摘要。重复 JSON key、非有限数、缺字段、错绑候选/产物/请求/数据/版本均拒绝。可参考 [真实命令回归中的 PROGRAM](../m0/tests/test_composed_worktree_executor.py)，该脚本的固定 token 数只是离线测试数据。

命令至少显式计量 `token` 和 `eval_count`；`CostVec` 字段及 `EvaluationContract.measured_cost_units` 必须完整且一致。执行器先保留原始响应并提取可验证的物理计量，再核对业务身份和受保护内容。因此，完整计量已知但回执错绑或保护文件被修改，会带着真实费用拒绝晋升；缺失、篡改或不完整的计量保留未结预扣，不能当作零费用，也不能自动发起替代命令。命令退出失败或超时不得提交 `EvalStatus.OK`；合法失败回执仍可以保留状态和已知成本。

启用 wallclock 预算时，worktree 评估结算取 producer 计量与持久 worker 运行时间的较大值；producer 自报零或更短不会抹掉真实进程成本。原始评估回执仍保留原值与声明，执行边界的下限单独用于物理账本。恢复使用同一 worker 计时，不使用新 coordinator 的等待时间。

每个成功解码并验证的终态保留 `branch_ref` 指向真实 artifact commit；基础仓库工作区不因评估而被替换。快照通过原始 Git object 写入，避免运行仓库配置的 clean filter 或提交 hook。内部请求/响应目录不进入公开 artifact commit，原始响应和进程证据保留在运行目录的 `worktree-operations/`。这不等于任意评估器输出的自动脱敏；评估器仍应按公开/私有契约保存业务内容。

## Mac 与 Linux 的边界

| 模式 | 实际保证 | 不应据此推断 |
| --- | --- | --- |
| `sandbox="none"` | 显式可信本地命令、独立 Git worktree、进程身份、内容校验、预算和恢复协议 | 不隔离主机文件、网络、环境变量或其它数据 split；不能运行不可信候选并声称沙箱安全 |
| 默认 `sandbox="bubblewrap"` | Linux bubblewrap 和原 seccomp 策略；受保护文件和当前 split 只读；只挂载当前请求 split；真实 Linux 用例检查主机环境/文件和其它 split 不可见 | 不等于任意容器/集群部署、GPU 隔离或生产系统安全认证 |

Mac 使用 Darwin `libproc` 的进程出生时间，Linux 使用 `/proc/<pid>/stat` 的 starttime；两者都检查 PID 与出生身份，僵尸进程不被当作活进程。无法获取稳定身份会拒绝接管，不能只凭 PID 杀进程或认领旧任务。检查点绑定平台、Python/worker/identity 实现和安全策略；不是跨平台迁移运行中进程的格式。

`resource_limits` 可显式设置正整数 `memory_bytes`、`file_bytes`、`process_count`，映射到系统 rlimit；不配置时不宣称这些额外限额已启用。wall timeout 采用请求的 `time_limit`，没有时使用 domain 默认值；这和 S5 的累计物理 wallclock 预算是两个不同边界。Bubblewrap 环境仍需满足 [Linux 开发环境](DEVELOPMENT.md) 的挂载和可执行文件条件。

## 恢复、付费调用和 replay

同一运行目录只有一个 coordinator 可持有非阻塞文件锁；每个 worktree operation 也有独立 lease。持久 operation 绑定 logical run、周期/调用身份、候选、完整请求、内容与配置。请求、启动意图、supervisor/target 身份及授权、进程终态和 artifact commit 均按原身份核对。恢复会等待原进程或读取其已完成结果，不能用“再跑一次”代替接管。

启动意图在 `Popen` 前持久化。若 coordinator 恰好在该窄窗口崩溃，且无法证明是否已启动，协议保留未知状态并拒绝替代执行。若 supervisor 消失且没有持久结果，只清理匹配已记录身份的 target，费用继续未知；安全策略或身份被改写时同样不能猜测成功或重付费。这是进程崩溃和已经持久化边界的恢复协议，不承诺磁盘丢写或机器断电下的 exactly-once。

检查点提交先完整写入并 fsync `checkpoint.pending.json`，再持久追加对应 journal boundary，最后原子替换 `checkpoint.json` 指针。恢复只在 pending 的内容摘要和 `next_cycle` 与最新持久 boundary 严格一致时完成指针切换；没有已提交 boundary 的 pending 不自动成为恢复基线，而使用原 checkpoint 续接纯决策后缀。这避免进程死在“文件已保存、边界尚未追加”之间时误把未提交状态当成已完成周期。

公开 Framework 恢复以最近 checkpoint 为纯决策状态基线，按相同顺序消费之后的持久 journal；事件内容必须逐项相等，不允许删掉既有预算、准入或来源记录来继续。外部 worktree 事件由 operation 协议独立核验。provider 成功结果、实际 token 和可恢复内部状态会缓存到持久 completion，恢复重用该完成记录，不再付费调用 provider；只有 started、没有 completed 的 provider 调用拒绝自动重试。组件需要恢复内部状态时仍须成对提供 `checkpoint_state/restore_state`。若本地 planning/operator 配置了 wallclock 且在计量持久化之前中断，旧调用的墙钟无法还原，恢复保留预扣并拒绝继续；已持久化 worker 的真实运行时间可以复用，不把 coordinator 离线等待时间算成执行费用。

`resume_from_checkpoint=True` 使用原运行目录和同一冻结配置。完整完成后的恢复应是零新调用、零新增费用；周期边界暂停后只执行剩余周期和一次最终审计。真正的 dev/admission/final 中途接管需要四文件 S7 组中的公开 Framework SIGKILL 用例证明，执行器组件单测不能替代该证据。

`Framework.replay()` 仍是独立重执行，会产生新的真实 provider/命令费用，不能当作恢复或免费缓存。严格结果/快照比较保留实际执行来源和 wallclock；新的进程身份、worktree 路径、commit 或测量值可能导致不匹配。不能通过抹平这些证据来宣称精确 replay 成功。若 domain 显式支持 `resume_from`，它只能是不可变 Git commit；这表示评估请求的基础产物，不是 coordinator 的进程恢复开关。

## 阶段验收

`make check` 执行 Mac portable tests、静态公理、工具测试和四个离线示例；Linux 专用测试明确排除。`make accept-linux` 在 Linux x86_64 上执行完整、无过滤且不允许 skip 的 v66，包括新四文件组及全部历史组。精确数量和同 SHA CI 结果记录在 [阶段清单](ABSTRACTION_ALIGNMENT.md)，不能用已归档 v65 成功替代本阶段结果。

本阶段继续保留 ExecutorSpec 的通用 role/frozen hypothesis/context projection、通用事件订阅、HITL、分布式执行和外部 campaign 等未完成项；S8 种群组装另行验收。串行 command/worktree 接通不意味着 M7 全部抽象和旧 batch 路径已统一。
