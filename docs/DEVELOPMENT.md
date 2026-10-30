# Mac 开发与 Linux 自动验收

本文是当前开发入口。开发以 [统一抽象](AutoResearch模块化统一抽象.md)和 [逐项对照清单](ABSTRACTION_ALIGNMENT.md)为基准，当前 v66 保留 S1–S6 组与完整离线 research 示例，并增加 S7 worktree 与公开 Framework 接管组；S8 按阶段独立推进。[S1 使用与边界指南](COMPOSED_RUNTIME.md)说明 `Framework.from_profile("composed_prompt", ...)` 配置入口；[v66 验收说明](../m0/verifier/v66/README.md)限定本阶段认证范围，是否通过仍以同一提交的新证据为准。

[S2 指南](EVALUATION_CONTRACT_V61.md)说明 native domain、producer 身份、计量覆盖、公开/私有字段和受限准入视图；[S3 指南](CONTEXT_FEEDBACK_V62.md)说明实际 ContextPack、显式跨 run 回流与 local_files 双车道。[S4 指南](LAYERED_ADMISSION_V63.md)说明 native 三层 opt-in、调用硬顶、实际记录复算与不回流终审。[S5 指南](HIERARCHICAL_BUDGET_V64.md)说明实际物理预算和 fidelity 边界。[S6 指南](PROXY_VALIDITY_V65.md)说明周期校准、代理有效性和负反馈边界。[S7 指南](WORKTREE_RECOVERY_V66.md)说明命令、worktree、进程身份和恢复边界。S7 沿用 `composed-v6`，新增 executor/domain manifest 自然区分任务；各版 checkpoint 严格按运行时版本和完整 manifest 校验；不要补造旧证据以通过新认证。

`CODEBASE_REVIEW_2026-10-29.md` 保留导入时的独立审查结论；v58 修复准入、成本、账本与 seccomp 问题，v59 继续修复数据内容绑定、进程身份写入、配置校验、回执身份及 replay。变更与兼容边界见 [v58 修复说明](SAFETY_FIXES_V58.md)和 [v59 修复说明](EVALUATION_FIXES_V59.md)。旧 M0 路径与经典 profile 的行为保留；S1 配置路径的 dev 准入、token 预算和串行恢复范围应独立阅读，不能沿用旧路径的全部能力声明。

## Mac 上开始开发

安装 Git、make 和 uv。本次本机与 CI 使用 uv **0.6.8**；Python 开发版本由根 `.python-version` 固定为 **3.12**。已有较新 uv 时可使用现有版本，但提交前必须确认 `--locked` 检查通过。uv 可以在缺少 Python 3.12 时安装对应解释器。

```bash
git clone https://github.com/YixuanZhang99/mori-27.git
cd mori-27
make setup
make check
```

`make setup` 执行 `uv sync --project m0 --locked --python 3.12`，在 `m0/.venv` 创建独立环境。`m0/uv.lock` 锁定直接和传递依赖，`--locked` 会在项目元数据与 lock 不一致时失败，避免运行时悄悄改锁。

IDE 解释器选择 `m0/.venv/bin/python`。命令通过 `uv run` 进入环境，不要求手动激活。测试和四个示例使用离线模型或本地协议 fixture，不需要真实模型 API key。

| 命令 | 用途 |
|---|---|
| `make setup` | 安装锁定开发环境 |
| `make test` | 可移植测试，明确排除 `linux` 项；任何 skip/xfail 均失败 |
| `make axioms` | 11 条静态架构公理 |
| `make examples` | Toy GEPA、GSM8K-style、FunSearch-shaped 与完整 composed research 四个离线示例 |
| `make tooling` | 验收包装器的成功、失败及超时回归 |
| `make check` | 上述 Mac 日常检查组合 |
| `make build` | 构建 sdist 及 wheel 到 `artifacts/dist/` |
| `make test-linux` | Linux 前置检查后执行完整测试，拒绝任何 skip |
| `make accept-linux` | Linux 前置检查后，在副本中执行完整 v66 版本化验收 |
| `make verify-import` | 校验不可修改的初始 Git 导入快照 |

单文件或单个测试可直接运行，例如：

```bash
cd m0
uv run --locked python -m pytest tests/test_eval_governance.py -q
uv run --locked python -m pytest -m 'not linux' --fail-on-skip -q
```

## 测试分层的含义

原始测试场景继续保留；当前测试覆盖准入、计量、账本、seccomp，以及数据内容、进程身份写入、配置前置校验、回执上下文、replay 隔离和验收流程回归。S1 增加 `test_composition_registry.py`、`test_composition_defaults.py`、`test_composed_runtime.py`，覆盖组装预检、组件契约、策略/skill 的实际效果、计量、记忆写入、恢复与独立 replay。具体数量以当前提交的 pytest 收集和 Actions 日志为准，包装器的 unittest 单独计数。

S2 的独立验收组运行 `test_evaluation_contract.py` 与 `test_composed_evaluation.py`，验证 canonical 传输与身份/成本契约以及公开运行入口的组合行为；完整 pytest 组仍运行全部旧测试。S2 不等于所有旧 M0 接口已经迁移，也不关闭清单中 S1 尚未接通的 population、worktree、HITL 和事件总线条款。

S3 的 `test_composed_context.py`、`test_composition_context.py`、`test_composition_knowledge.py` 验证经验和已打开 ground 来源真正改变后续候选、显式跨 run/M5→M6 回流、audit 隔离、失效、hash 与作用域拒绝、v3 恢复/replay，以及原地篡改 context 被阻断。本地词项检索测试不证明语义检索质量，也没有调用外部网络知识服务。

S4/S5/S6 继续分别保留三层准入、分层预算和 proxy 校准的显式组。S7 新增 `test_composed_worktree_executor.py`、`test_process_identity_writer.py`、`test_composed_worktree_framework.py`、`test_composed_recovery.py` 组合组：既测真实命令和进程协议，也从公开 Framework 杀死 coordinator 后核对 provider/评估不重付费和账本续接；Linux 专用用例另验证真实 bubblewrap/seccomp 及 split 访问边界。Mac 的 `sandbox="none"` 是明确的可信本地模式，不能代替这些 Linux 安全结果。

`m0/tests/conftest.py` 以显式模块/函数清单标记 `linux`，原因是依赖 Bubblewrap、x86_64 seccomp 或 Linux `/proc` 稳定进程身份。混合模块中的纯协议测试仍在 Mac 运行。清单中的文件/函数不存在时，测试收集直接失败。

Mac 使用 `-m 'not linux'`，输出明确的 Linux deselected 数量；这不是 skip，也不证明被排除的测试已通过。Linux 完整验收不使用该选择条件，保留全部测试。`--fail-on-skip` 拒绝运行时跳过、模块收集跳过和 xfail；其行为有 5 个独立子进程回归用例保护。

新增测试默认进入可移植集合。只有确实依赖 Linux 执行机制的测试才应显式标记或加入清单，并同时在 Linux 验收；不要用平台标记掩盖业务断言失败。

五阶段分别是 S1 模块组装、S2 统一评估契约、S3 记忆与知识回流、S4 三层准入、S5 分层预算。每阶段都要补充通过公共 API 的端到端场景，先通过 `make check`，再取得同一阶段提交的 Linux Actions 全量成功证据，才能记录该阶段验收完成。S1 验收不会把 S2–S5 标为完成；后续 verifier 保留旧命令组与历史证据，新增阶段测试，避免用替换旧测试缩小验收范围。

## GitHub Actions 实际运行路径

根目录 `.github/workflows/ci.yml` 在 push、pull_request 和手动触发时运行，使用 `ubuntu-24.04` x86_64：

1. 安装固定版本 uv、系统 Python 3.12、Bubblewrap 与 AppArmor 工具。
2. 验证 user namespace 可用；必要时只给一份 root-owned CI 专用 bwrap 加允许 userns 的 AppArmor profile，保留全局限制。
3. 用 lock 安装环境，检查原始导入快照，构建安装包，运行包装器回归及离线示例。
4. 对当前解释器执行真实沙箱预检，随后在临时 `m0` 副本里运行 v66；所有内部 pytest 调用都强制 `--fail-on-skip --strict-markers`。
5. 无论成功失败都保存本次结果和构建产物，保留 14 天；检查原仓库的历史 verifier 文件没有变化。

Actions 使用完整 commit SHA 固定版本，权限为 `contents: read`，checkout 不持久化访问令牌。同一 ref 的新运行会取消旧运行。

### Linux 的 Python 安装路径为什么特殊

当前生产沙箱只只读挂载 `/usr`、`/bin`、`/lib` 等系统路径及候选工作区。解释器若位于 `/opt/hostedtoolcache` 或仓库 `.venv`，即使外部可以运行，进入沙箱后仍可能不可见。

因此 CI 使用：

```text
UV_PYTHON=/usr/bin/python3.12
UV_PROJECT_ENVIRONMENT=/usr/local/share/mori27-venv
UV_PYTHON_DOWNLOADS=never
```

`/usr` 内的解释器、标准库、虚拟环境和依赖均在沙箱可见范围中。该配置没有扩大生产沙箱挂载，也没有关闭 seccomp。

自建 Ubuntu 24.04 x86_64 环境可由管理员准备依赖及可写目录，再运行：

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap apparmor python3.12-venv
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /usr/local/share/mori27-venv
export UV_PROJECT_ENVIRONMENT=/usr/local/share/mori27-venv
export UV_PYTHON=/usr/bin/python3.12
export UV_PYTHON_DOWNLOADS=never
make setup PYTHON=/usr/bin/python3.12
make accept-linux
```

若 user namespace 受宿主策略限制，需由管理员配置应用级许可。`scripts/setup_linux_ci.sh` 仅允许在一次性 GitHub-hosted runner 执行，避免在开发机器上修改系统策略。Mac 上 `make test-linux` 会提前给出平台提示，不会自动关闭隔离换取通过。

## 证据和历史文件

v66 verifier 会创建或更新 `LAST_RUN.json` 并追加 journal，因此 `scripts/run_acceptance.py` 复制当前 `m0` 后才运行。v1–v65 verifier 源码保持原样；原包里的 v1–v57 历史成功/失败记录及历史 `m0/.github/workflows/axioms.yml` 也保留。归档的 `m0/verifier/v58/LAST_RUN.json` 与 `m0/verifier/runs/v58.jsonl` 来自真实 [v58 CI 运行 40870494602](https://github.com/YixuanZhang99/mori-27/actions/runs/40870494602)。v59 同名证据文件原样来自提交 `b45654fe22a2db87f64e12f0142ba39bbd603216` 的 [v59 CI 运行 40879734092](https://github.com/YixuanZhang99/mori-27/actions/runs/40879734092)，均不代表 v66 的运行结果。新增历史证据必须来自其真实成功的阶段 CI artifact，归档前核对提交、摘要、证书与 journal；不得在新的接线上重新运行旧 verifier 后把结果当成历史。

v60 成功证据已原样归档自提交 `06491ce5639dd33f7f89bc8e1288f881b54ecb8c` 的 [S1 CI 40889093796](https://github.com/YixuanZhang99/mori-27/actions/runs/40889093796)：1,131 项 pytest、29 个验收检查通过。其 SHA-256 与 artifact 来源见 [v61 归档说明](../m0/verifier/v61/README.md#archived-v60-evidence-provenance)，工具测试固定保护归档字节。

v61 成功证据已原样归档自提交 `babe764c7b2bb83d5fdb0151316a8677d21052d7` 的 [S2 CI 40891610362](https://github.com/YixuanZhang99/mori-27/actions/runs/40891610362)：1,206 项 pytest、30 个验收检查通过。其来源和摘要见 [v62 归档说明](../m0/verifier/v62/README.md#archived-v61-evidence-provenance)。

v62 成功证据已原样归档自提交 `ccb91c86c4b8dc05d52fb3f09c3fd6cfc13d8891` 的 [S3 CI 40894739044](https://github.com/YixuanZhang99/mori-27/actions/runs/40894739044)：1,252 项 pytest、31 个验收检查通过。其来源和摘要见 [v63 归档说明](../m0/verifier/v63/README.md#archived-v62-evidence-provenance)。

v63 成功证据已原样归档自提交 `41a8dc83340b787fdbfef73dbee2c8759751bbe2` 的 [S4 CI 40898306157](https://github.com/YixuanZhang99/mori-27/actions/runs/40898306157)：1,307 项 pytest、32 个验收检查通过。其来源和摘要见 [v64 归档说明](../m0/verifier/v64/README.md#archived-v63-evidence-provenance)。

v64 成功证据已原样归档自提交 `685fd5fffae41d693cc4f4865bd763cb64dcae15` 的 [S5 CI 40904572252](https://github.com/YixuanZhang99/mori-27/actions/runs/40904572252)：1,398 项 pytest、34 个检查通过。其来源和摘要见 [v65 归档说明](../m0/verifier/v65/README.md#archived-v64-evidence-provenance)。

v65 成功证据已原样归档自提交 `62a73631800bdf17eff0e5342fda0212a5303a50` 的 [S6 CI 40911722972](https://github.com/YixuanZhang99/mori-27/actions/runs/40911722972)：1,477 项 pytest、35 个检查通过。其来源和摘要见 [v66 归档说明](../m0/verifier/v66/README.md#archived-v65-evidence-provenance)。

v60 保留 v59 所有命令组并加入 S1 三文件组；v61 加入 S2 两文件组；v62 加入 S3 三文件组；v63 加入 S4 两文件组；v64 加入 S5 两文件组和完整离线 research 示例；v65 加入 S6 两文件组；v66 保留全部旧命令与超时并加入 S7 四文件组，历史验证范围扩展至 v65。包装器回归逐版本保护 v58→v59→v60→v61→v62→v63→v64→v65→v66 的旧命令与超时设置，以及已经核实的历史归档字节来源。当前真正触发 Actions 的是仓库根级 workflow，其与 Makefile、包装器的实际调用链也接受检查。

每次新结果写入独立目录 `artifacts/linux-acceptance/<UTC-run-id>/`，包含控制台日志、新证书、journal 和结构化摘要；不会把上一轮成功当成本轮结果。包装器要求本次进程退出成功、有效新证书与本次 journal 检查成立，并确认源历史未被改动。CI 的临时 VM 负责最终清理隔离环境；指定进程崩溃恢复测试仍不等价于机器断电或真实远端服务 exactly-once 保证。

运行目录同样应保留历史。普通 `evolve()` 要求空证据目录；已有运行需使用有效检查点恢复，或选择新目录。缺少 v2 判定上下文的旧回执仍可读取，但新审计不会认证，涉及旧回执的中断恢复也会拒绝；不要补造上下文或删掉原证据重跑。需要新认证时，在新目录重新评估。

`Framework.replay()` 是独立重新执行，会调用模型或外部命令并可能计费，不是离线 journal 播放。每次执行写入 `<原工作目录>/replays/replay-*/`，保留各次成功和失败证据。旧 M0 路径的普通适配器与扩展从运行前副本恢复；不可独立复制的适配器需显式提供 `adapter_factory(workdir, store) -> (llm, evaluator)`，带可变闭包状态的函数也需使用 factory。详细接口及状态隔离限制见 [v59 replay 契约](EVALUATION_FIXES_V59.md#replay-隔离与适配器契约)。

S1 配置路径同样复制运行前的 provider/evaluator 或使用上述 adapter factory，并要求注册组件的 factory 每次返回新实例。组件内部状态需要 `checkpoint_state()/restore_state()` 才能跨恢复保存。S1 仅支持完整 cycle 边界恢复，未完成的已启动 cycle 会拒绝自动重调；默认 `batch_size=max_inflight=1`，其他值前置拒绝。详见 [S1 恢复与 replay](COMPOSED_RUNTIME.md#恢复与-replay)。

S3 在此基础上保存独立 logical_run_id 与上下文/知识状态。两个独立新 run 的 checkpoint_ref 可以因作用域身份不同而不同；同一逻辑 run 的恢复/replay 才保持该身份。显式结束导出的文件也要在恢复/replay 核对内容 hash，暂停不导出，完成恢复不重复导出。旧 v1/v2 检查点缺少这些字段时明确拒绝。

原 `MANIFEST.json` 是导入快照清单，不会因后续开发而重写：

```bash
make verify-import
# 等价于校验初始提交里的文件
uv run --project m0 --locked python scripts/verify_import.py \
  --ref 9301cebe15c3abd772330beba5bd1898f4d4eb72
```

不带 `--ref` 时仍检查当前工作目录与原包是否相同；开发后该检查可能有预期差异。浅克隆需先取得上述初始提交；CI 使用完整历史。

## 修改依赖和打包

依赖声明在 `m0/pyproject.toml`：运行依赖与 pytest 开发组分开，Hatchling 构建后端固定版本。安装包显式包含 `core`、`zoo`、profile JSON、OpenEvolve 运行源码/模板/许可证及 benchmark 静态资源；不打包研究论文、历史 verifier 或上游完整示例集。

```bash
uv add --project m0 <runtime-package>
uv add --project m0 --dev <test-package>
make setup
make check
make build
```

同时提交 pyproject 与 lock；不要手改 lock。完整 Linux CI 通过说明当前定义的测试与 v66 验收成立，不证明尚未执行的真实模型/benchmark campaign 已完成。修复覆盖范围见版本修复说明，统一抽象的未完成项和阶段验收条件见 [对照清单](ABSTRACTION_ALIGNMENT.md)。

相关一手文档：[uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)、[uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)、[Ubuntu user namespace 限制](https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions)。
