# Mac 开发与 Linux 自动验收

本文是当前开发入口。`CODEBASE_REVIEW_2026-10-29.md` 保留导入时的独立审查结论；当前 v58 在开发环境基础上修复准入、成本、账本与 seccomp 问题；变更及兼容边界见 [修复说明](SAFETY_FIXES_V58.md)。

## Mac 上开始开发

安装 Git、make 和 uv。本次本机与 CI 使用 uv **0.6.8**；Python 开发版本由根 `.python-version` 固定为 **3.12**。已有较新 uv 时可使用现有版本，但提交前必须确认 `--locked` 检查通过。uv 可以在缺少 Python 3.12 时安装对应解释器。

```bash
git clone https://github.com/YixuanZhang99/mori-27.git
cd mori-27
make setup
make check
```

`make setup` 执行 `uv sync --project m0 --locked --python 3.12`，在 `m0/.venv` 创建独立环境。`m0/uv.lock` 锁定直接和传递依赖，`--locked` 会在项目元数据与 lock 不一致时失败，避免运行时悄悄改锁。

IDE 解释器选择 `m0/.venv/bin/python`。命令通过 `uv run` 进入环境，不要求手动激活。测试和三个示例使用离线模型或本地协议 fixture，不需要真实模型 API key。

| 命令 | 用途 |
|---|---|
| `make setup` | 安装锁定开发环境 |
| `make test` | 可移植测试，明确排除 `linux` 项；任何 skip/xfail 均失败 |
| `make axioms` | 11 条静态架构公理 |
| `make examples` | Toy GEPA、GSM8K-style、FunSearch-shaped 三个离线示例 |
| `make tooling` | 验收包装器的成功、失败及超时回归 |
| `make check` | 上述 Mac 日常检查组合 |
| `make build` | 构建 sdist 及 wheel 到 `artifacts/dist/` |
| `make test-linux` | Linux 前置检查后执行完整测试，拒绝任何 skip |
| `make accept-linux` | Linux 前置检查后，在副本中执行完整 v58 版本化验收 |
| `make verify-import` | 校验不可修改的初始 Git 导入快照 |

单文件或单个测试可直接运行，例如：

```bash
cd m0
uv run --locked python -m pytest tests/test_eval_governance.py -q
uv run --locked python -m pytest -m 'not linux' --fail-on-skip -q
```

## 测试分层的含义

原始测试场景继续保留；当前测试新增准入、计量、账本、seccomp 及验收流程回归。具体数量以当前提交的 pytest 收集和 Actions 日志为准，包装器的 unittest 单独计数。

`m0/tests/conftest.py` 以显式模块/函数清单标记 `linux`，原因是依赖 Bubblewrap、x86_64 seccomp 或 Linux `/proc` 稳定进程身份。混合模块中的纯协议测试仍在 Mac 运行。清单中的文件/函数不存在时，测试收集直接失败。

Mac 使用 `-m 'not linux'`，输出明确的 Linux deselected 数量；这不是 skip，也不证明被排除的测试已通过。Linux 完整验收不使用该选择条件，保留全部测试。`--fail-on-skip` 拒绝运行时跳过、模块收集跳过和 xfail；其行为有 5 个独立子进程回归用例保护。

新增测试默认进入可移植集合。只有确实依赖 Linux 执行机制的测试才应显式标记或加入清单，并同时在 Linux 验收；不要用平台标记掩盖业务断言失败。

## GitHub Actions 实际运行路径

根目录 `.github/workflows/ci.yml` 在 push、pull_request 和手动触发时运行，使用 `ubuntu-24.04` x86_64：

1. 安装固定版本 uv、系统 Python 3.12、Bubblewrap 与 AppArmor 工具。
2. 验证 user namespace 可用；必要时只给一份 root-owned CI 专用 bwrap 加允许 userns 的 AppArmor profile，保留全局限制。
3. 用 lock 安装环境，检查原始导入快照，构建安装包，运行包装器回归及离线示例。
4. 对当前解释器执行真实沙箱预检，随后在临时 `m0` 副本里运行 v58；所有内部 pytest 调用都强制 `--fail-on-skip --strict-markers`。
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

v58 verifier 会创建或更新 `LAST_RUN.json` 并追加 journal，因此 `scripts/run_acceptance.py` 复制当前 `m0` 后才运行。原包里的 v1–v57 历史成功/失败记录保持原样；历史 `m0/.github/workflows/axioms.yml` 也保留，作为历史证据。v58 检查根 workflow、Makefile 与包装器的实际调用链。当前真正触发 Actions 的是仓库根级 workflow。

每次新结果写入独立目录 `artifacts/linux-acceptance/<UTC-run-id>/`，包含控制台日志、新证书、journal 和结构化摘要；不会把上一轮成功当成本轮结果。包装器要求本次进程退出成功、有效新证书与本次 journal 检查成立，并确认源历史未被改动。CI 的临时 VM 负责最终清理隔离环境；指定进程崩溃恢复测试仍不等价于机器断电或真实远端服务 exactly-once 保证。

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

同时提交 pyproject 与 lock；不要手改 lock。完整 Linux CI 通过说明当前定义的测试与 v58 验收成立，不证明尚未执行的真实模型/benchmark campaign 已完成，其修复覆盖范围与尚未实现的能力见修复说明。

相关一手文档：[uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)、[uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)、[Ubuntu user namespace 限制](https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions)。
