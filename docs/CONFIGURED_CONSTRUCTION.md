# M7 构造与 Git 产物：schema 2

本页描述 M7 实施计划 Tasks 3–5 的公开接口。它提供 `composed-v9-m7` 和 `composed-v9-m7-governed`，包含原生 artifact 与 Git artifact，以及原生/命令评估接入。显式安装费用桥后使用 `composed-v9-m7-governed-external`，保留物理与人民币双重准入。它不表示 M7 并发调度或整个框架验收完成。原有 schema 1 配置与历史检查点按原契约运行，不自动升级。

## 配置与调用

在已有、可运行的 [hierarchical 配置](HIERARCHICAL_BUDGET_V64.md) 上显式设置：

```python
profile["schema_version"] = 2
profile["executor"] = {"name": "inprocess"}
profile["execution"] = {
    "schema_version": 1,
    "spec": {
        "role": "coder",
        "hypothesis_frozen": True,
        "context_projection": ["memory", "grounding"],
    },
    "constructor": {"name": "prompt", "options": {"max_attempts": 2}},
}
framework = Framework.from_profile(profile, llm, evaluator, config, workdir)
result = framework.evolve(task)
```

这里的 `profile`、`llm`、`evaluator`、`config`、`workdir` 和 `task` 是调用方已有依赖；片段不是独立示例。预算必须选择 `hierarchical`，并覆盖 planning、operator 和评估阶段。默认 `tokens` 配置会在调用前拒绝。内置角色为 general、coder、analyst；角色指令进入真实构造请求。自定义角色必须通过 constructor 注册声明，与工厂实例的版本化角色绑定一致。

`draft`、`reflective`、`crossover` 在此路径产生声明式配方。构造器调用模型，要求返回 JSON 对象，包含非空 `artifact` 和 `hypothesis`。规划仍选择算子、父候选和假设。`spec.hypothesis` 可显式约束初始假设；冻结模式下，模型改变该字符串会产生有费用记录的构造失败，而不会执行评分。自由模式把最终假设归属到实际评分候选。字符串一致不保证生成代码在语义上遵循假设。

## 上下文与策略状态

`context_projection` 只接受不重复的 memory、grounding、query；空列表允许，summary 和 full 不属于该版本契约。一次 M5 检索的原始摘要仍保存用于审计，但规划、动态 skill 和配方只获得投影后的内容。选中的父 artifact、任务文本与显式配置的静态 instruction 是另外授权的输入。

schema 2 将同一策略配置实例化为两个独立会话：一个规划，一个吸收反馈；它们分别保存检查点状态。反馈继续写入记忆，再经 M5 检索和投影供后续规划使用。自定义策略不能再依赖在 absorb 中保存原始反馈、随后由同一个实例直接交给 ideate 的隐式通道。schema 1 行为不变。

显式选择 `gepa_instance` 时，规划选择器还接收一个独立、有限的数值选择通道：仅包括配置中冻结的公开样本 ID 和无 seed 的二值 verdict，附带原证据引用；它不包含原始反馈、私有样本、轨迹或产物文本，也不作为构造器 prompt 的额外上下文。恢复时会对照原始证据与日志重验策略检查点。该通道是选择此策略时明确启用的例外，不改变其他策略或 `context_projection` 的语义；它只提供 GEPA 选择机制，尚不代表独立验证集、配对小批次接受或完整 GEPA 复现。

构造器工厂不接收 live provider 或 evaluator；模型依赖只在计量中的构造调用内提供。生成相关工厂获得组件范围内的 journal 视图。注册的 Python 代码仍属于受信任代码，共享全局变量、外部状态与原生执行不构成安全沙箱。

## 预算、artifact 与恢复

一次候选生产共用一个 operator 预扣、一个连续调用序列和一次结算：一个尝试节点、零次评估。构造、修复和发布失败保留已经测得的费用；未知用量保留整笔未结预扣，不重发替代调用。`max_attempts` 限制修复次数。对没有硬调用上界的原生 provider，用量耗尽预扣后不再修复，但单次调用仍可能超额；超额费用如实记账。受治理 provider 继续使用已有硬调用上界与未来对照保留预算。

原生 artifact 按内容摘要持久化。dev、baseline、calibration、admission、final 只评估同一个已构造 artifact，不重新生成。材料化记录同时绑定原始构造终态、计划、角色、上下文摘要、实际费用和 artifact 字节；只修改一组自洽摘要不能替换原始产物。

恢复复用已完成结果，只执行可证明未启动的剩余部分。无法确认完成的原生调用保持未结状态。`inspect()` 和恢复会重新验证 artifact；删除或修改 artifact 会拒绝复用。此路径的 `replay()` 使用 recorded outcomes，不再次调用模型或领域评估器；第三方 factory 本身仍必须遵守无外部调用的构造约定。

每个对照槽位有独立 provider、constructor、domain、executor 和 artifact 空间，使用冻结的初始任务、空 memory/grounding 和无父候选配方。主线耗尽可用预算后，已保留的对照容量仍受保护。对照候选不进入主线选择和准入。

实现与验证范围见 [M7 计划](superpowers/plans/2026-11-04-m7-execution.md)。Git/SIGKILL 与安装包示例是工程验证的一部分；整体独立审查与新版本验收仍未完成，不应把此增量当作完整发布证书。


## 推荐的 Git 产物配置

新代码可以从 `core.composition.defaults.execution_profile()` 获取显式 schema-2 配置：原生 domain、`git_artifact` executor、hierarchical budget、三层准入和 prompt constructor。它与旧 `composed_profile()` 的兼容语义分开；没有改变旧 profile 的默认路径。预算数值是可修改的起始配置，不是模型调用硬上界或对真实任务的费用建议。

省略 `base_repo` 时，在本次运行的 artifact 空间创建受管理的空 Git 仓库，绝不自动快照调用方当前目录。有基础代码与受信评分器时可显式配置：

```python
from core.composition.defaults import execution_profile

profile = execution_profile()
profile["execution"]["spec"]["role"] = "coder"
profile["executor"] = {
    "name": "git_artifact",
    "options": {
        "base_repo": "/absolute/path/to/base-repository",
        "base_ref": "HEAD",  # 启动时解析并绑定到确切 commit
        "artifact_path": "candidate.py",
        "protected_paths": ["evaluate.py"],
        "sandbox": "bubblewrap",
    },
}
```

`base_repo` 必须已经提交需要的文件；工作目录中的未提交改动不会成为构造基线。运行空间必须在该仓库外。当前只支持一个 artifact 文件，基础树中的符号链接、子模块和特殊文件会拒绝；artifact 不能覆盖受保护路径、目录或执行器控制路径。原生评估仍为受信任进程内执行；Git 发布本身不是 OS 沙箱。选择已有 `command` domain 后，命令评估默认使用 Linux bubblewrap，或显式 `sandbox="none"` 的可信本地模式。`resource_limits` 沿用原命令执行器的 memory_bytes/file_bytes/process_count 契约。

构造器只生成一次。发布使用基础提交的精确 blob、独立 Git index、冻结 tree 和 commit 内容，绕开用户 hooks/filters，不修改调用方工作树和 index。提交计划先持久化，再发布提交及引用；恢复验证原 journal、计划、提交和字节，采用同一个原始提交。Git 对象可能有不同候选共享的 blob，但每次候选生产的提交身份绑定到自身操作。

命令评估使用现有 WorktreeCommandExecutor，从原始 artifact 提交创建自己的评估工作区；分配好的 `EvalRequest`（包括 resume_from）不改写。评分日志与结果提交属于评估工作，不重新定义构造 artifact。调用记录将原始 artifact commit 保存在执行器基础提交绑定中。真正的 supervisor 时长继续作为墙钟费用下限，评分器申报零时间不会让命令免费。

不完整的命令调用仅通过原进程身份协议接续；没有可验证进程/结果的启动意图仍拒绝替代。原生调用保持不明终态不重试。recorded replay 使用原 terminal evidence，不再创建评分进程。公开入口已有真实 SIGKILL 测试覆盖 provider 完成、产物计划/提交，以及评分进程开始/完成和结果发布；它们不证明整机断电丢写恢复。

## 安装包独立示例

先构建并安装 wheel，把 [configured_execution_offline.py](../m0/examples/configured_execution_offline.py) 复制到仓库外，再用安装环境运行：

```bash
python -I /path/outside/checkout/configured_execution_offline.py --workdir /new/empty/run-directory
```

也可在开发环境执行 `uv run --project m0 --locked python m0/examples/configured_execution_offline.py`，或运行 `make examples`。示例实际执行 2 次合成模型生成、5 次本地评估；暂停恢复后仍是原始 Git 产物，并使用会直接报错的 provider/domain 验证回放零新调用。10 个生成 token 是合成 fixture 用量；分数不是 benchmark 成绩。


## 外部费用保护与修复

在既有 [CNY 治理配置](GOVERNED_CURRENCY.md) 上启用上述 schema 2 和 execution，即进入显式 v9 外部运行。它不是旧 v8 检查点的自动升级。主线和各对照的构造器、角色完整定义、artifact backend、execution 配置及运行 manifest 都会冻结到费用桥计划中。该 manifest 摘要只排除随后生成的 external_governance 字段，避免循环摘要；最终完整 manifest 仍绑定每个构造操作。价格政策本身没有改写。

`max_attempts` 是构造器的尝试上限；provider 的 `phase_call_limits.operator` 和原始物理预扣共同决定实际可调用次数。允许两次调用时，主线 operator 预扣和每个对照 operator 保护都必须覆盖两个完整的 provider 硬调用上界。修复沿用同一个 intent 和连续 ordinal，不会建立额外节点；一次失败也不会重置额度。主线耗尽后仍可执行已保护的对照。第一笔费用已知、第二笔未知时，人民币账本保留首笔结算和第二笔 pending，物理账本保留整个生产操作的未结预扣。

`inspect()["governance"]["external_currency"]["construction"]` 提供构造费用审计：每份 artifact 关联原 materialization、candidate、lane/slot 和 provider context 引用。审计核对原始 run manifest、角色定义、构造终态、实际发送的 prompt、原始返回及计费回执；对内置 prompt constructor，还重建计划摘要，拒绝只修改产物、上下文投影或初始假设再重算哈希的替换。自定义 constructor 的内部输出算法仍属于受信任插件，其版本化绑定、费用和产物出处会核对，但不能借内置构造器的验证宣称任意插件已被独立证明。

安装后的本机示例无需 API Key 或真实账户：

```bash
python -I /path/outside/checkout/governed_cny_offline.py --construction --workdir /new/empty/cny-run
```

复制的脚本来自 [governed_cny_offline.py](../m0/examples/governed_cny_offline.py)。它以本机 HTTP 和新的临时账本演示 4 个 Git 产物、每个产物一次修复、共 8 次请求，暂停/恢复后记录回放不增加请求或账本事件。304 微元完全来自合成 fixture 用量，不是实际供应商消费。省略 `--construction` 仍演示旧 v8 路径。


## 实现职责与验收入口

| 模块 | 所有权 |
| --- | --- |
| `construction.py`、`construction_recipes.py` | 冻结角色/假设/投影、声明式配方与实际构造/修复 |
| `configured_execution.py`、`execution.py` | 公开配置接入、候选生产生命周期及原始材料化结果复用 |
| `artifacts.py`、`git_artifacts.py`、`construction_workspace.py` | 原生/Git 产物发布、字节/提交身份和评估工作区 |
| `invocation.py`、`governed.py`、`recovery.py` | 调用开始/计量/结算顺序、独立对照、原结果接管 |
| `external_provider.py`、`construction_audit.py` | v9 冻结费用上下文、原请求/返回/产物的独立关联审计 |
| `zoo/mle_bench_lite/governed_currency.py` | 既有人民币账本的双重准入、私有证据与费用核对 |

[v74](../m0/verifier/v74/README.md) 在保留全部 v73 命令的基础上增加五组验收。`make accept-linux` 要求干净提交的实际源码身份成立；`make check` 仍是原有 Mac 门槛。版本定义、单项测试、本机全量、独立审查和同 SHA 远端结果分别记录，不互相替代。
