# AutoResearch 代码包验证记录（2026-10-29）

本记录验证原始 `AutoResearch-handoff/m0`，未修改其源文件与历史证书。最终重新核验 `MANIFEST.json`：1047 个原始文件全部 SHA256 一致。

## 本次实测结论

| 项目 | 结果 |
| --- | --- |
| 完整 pytest | 490 项：337 passed、138 failed、15 skipped；71.55 秒；退出码 1 |
| 静态架构公理 | 11/11 通过，无依赖循环 |
| Toy GEPA 离线示例 | best_score=1.0；IID-RS 维持 1/3；治理审计通过 |
| GSM8K-style 离线示例 | best_score=1.0；主轨迹 [0,1,1,1,1]，baseline [0,0]；治理审计通过 |
| FunSearch-shaped 离线示例 | best_score=0.8333333333333334；治理审计通过；2 个岛屿，6 次迁移 |
| 标准源码安装 | 失败：setuptools 默认包发现遇到多个顶级目录 |
| v57 完整 verifier | 未运行其 main，避免覆盖原历史 LAST_RUN.json / 追加原 journal；本机也不满足其 Linux 门禁 |

三个离线示例使用确定性 mock/script LLM，证明机制可运行，不能代表真实 provider 或真实 benchmark 效果。

## 环境

- macOS 26.4.1，arm64，无 bwrap、Docker、Podman。
- 完整测试使用独立 `/tmp/autoresearch-audit-venv`，Python 3.12.9。
- pytest 9.2.0、numpy 2.5.4、PyYAML 6.0.3、dacite 1.9.2、openai 3.41.0。
- 依赖来自当前索引的未锁版本；不能据此声称复原历史验收环境。
- 完整 pytest 子进程移除了名称含 API_KEY 或以 _TOKEN 结尾的继承环境变量；测试内部本地 HTTP fixture 自行设测试值。

## 138 个失败的核对结果

| 根因 | 数量 | 证据 |
| --- | ---: | --- |
| Bubblewrap 缺失 | 97 | 96 个失败栈直接含 `requires an installed bwrap executable`；1 个 benchmark CLI 间接断言失败，其 host/governed 两个 stderr 都是该错误 |
| seccomp 仅支持 x86_64 | 24 | 全部直接报 `seccomp policy v1 requires x86_64; got arm64` |
| Linux /proc 进程身份不可得 | 17 | 5 个直接错误；11 个间接 executor/recovery/settlement 断言在对应 JSONL evidence 中记录稳定身份错误；1 个 PID 测试因 start_ticks 返回 None 后 +1 而失败 |

对应代码：

- `core/executor/sandbox.py:21-24`：检查 bwrap 可执行文件。
- `core/executor/seccomp.py:88-93`：架构白名单只有 x86_64。
- `core/executor/proposal.py:53,71`：ExternalCommandLLM 默认启用 seccomp。
- `core/executor/process.py:17-33`：通过 `/proc/<pid>/stat` 读取稳定进程身份；`91-94` 在无法取得身份时拒绝启动。

13 个间接失败额外检查了完整测试产生的 pytest-24 临时证据，并非仅凭失败名称推断：benchmark 双臂 `stderr.log`；其余 executor 的 `evidence.jsonl` / `executor-evidence.jsonl`；PID 测试本身的 `start_ticks` 表达式。

15 个跳过项：8 项需要 x86_64+bubblewrap；4 项需要 Linux x86_64 direct-prctl；3 项需要 bubblewrap。没有把 skip 算作通过。

这些结果表明：平台无关内核可运行，外部执行与恢复层当前按 Linux x86_64 设计；本次结果不能替代 Linux 全量通过证书。

## 历史证据与本次结果分离

包内 `verifier/v57/LAST_RUN.json` 保存的历史结果是 21 checks passed，完整回归 490 passed / 230.43 秒。本次未重新认证这一历史结果。

历史文件同时明确：真实外部 API 未运行；RE-Bench/MLE-Bench Lite campaign 未运行；host parity、RUBRIC B2/B3 未完成。local OpenAI-compatible HTTP worker 运行过，只能证明本地协议机制。

`verifier/v57/verify.py:10` 通过相对脚本位置取得 ROOT，没有 /workspace 硬编码。`71` 行会把任何包含 skipped 的结果判失败，因此 macOS 即便手工跳过不兼容测试也不满足当前验收。`467-471` 行会写 LAST_RUN 与 append journal，所以保留原件时应在工作副本运行。

## 安装与 CI 问题

`m0/pyproject.toml` 仅含项目名、版本、Python>=3.11 和 pytest testpaths，没有依赖、build backend 或显式包发现配置。实测标准构建报：

```text
Multiple top-level packages discovered in a flat-layout:
['zoo', 'core', 'config', 'vendor', 'verifier']
```

因此当前可按源码目录运行，但尚不能把 `pip install ./m0` 当作可用安装方式。未锁依赖也让历史环境难以重建。

原 CI 位于 `m0/.github/workflows/axioms.yml`；完整包作为仓库根时 GitHub 不会自动识别该嵌套位置。需要仓库根的 workflow，并设置 `working-directory: m0`。原配置要求 Ubuntu、Python3.12、bubblewrap，执行静态公理与 v57；尚未证明 hosted runner 能完成该门禁。

## 可复核命令与输出文件

以下测试命令均在 `m0` 目录执行；`PYTHONDONTWRITEBYTECODE=1`、pytest 禁用 cacheprovider，输出写入仓库之外。

```bash
uv venv /tmp/autoresearch-audit-venv --python python3
uv pip install --python /tmp/autoresearch-audit-venv/bin/python pytest PyYAML numpy
uv pip install --python /tmp/autoresearch-audit-venv/bin/python dacite openai

PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python ci/check_axioms.py
PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python examples/toy_gepa.py
PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python examples/gsm8k_offline.py
PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python examples/funsearch_offline.py

PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python -m pytest -q -p no:cacheprovider --tb=short --junitxml=/tmp/autoresearch-audit-full.xml
```

完整测试实际由一个 subprocess 包装器运行，timeout=600 秒，stdout/stderr 合并到 `/tmp/autoresearch-audit-full.log`；包装器记录版本、退出码和用时到 `/tmp/autoresearch-audit-full.json`。后者已补充失败分类。

先前分两组验证的 181 passed 是完整 337 passed 的子集，不得相加成另一通过总数：

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_axioms.py tests/test_archive_health.py tests/test_eval_governance.py tests/test_memory.py tests/test_knowledge.py tests/test_loop_checkpoint.py tests/test_loop_batch.py tests/test_loop_governed_state.py tests/test_governance_audit.py tests/test_formal_governance.py tests/test_map_elites_archive.py tests/test_pareto_archive.py tests/test_multi_currency.py tests/test_operator_extensions.py tests/test_real_load.py tests/test_research_frontier.py tests/test_state_mutation.py tests/test_self_attestation.py
# 128 passed in 2.41s；/tmp/autoresearch-audit-portable.log

PYTHONDONTWRITEBYTECODE=1 /tmp/autoresearch-audit-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_batch_scheduler.py tests/test_batch_multicurrency.py tests/test_batch_recovery.py tests/test_benchmark_adapters.py tests/test_benchmark_selection_contract.py tests/test_benchmark_selection_receipt.py tests/test_run_evidence_isolation.py
# 53 passed in 0.98s；/tmp/autoresearch-audit-portable-extra.log
```

安装复现命令在完整包根目录运行：

```bash
uv venv /tmp/autoresearch-audit-install --python /opt/homebrew/bin/python3
uv pip install --python /tmp/autoresearch-audit-install/bin/python --no-deps ./m0
# Python3.13.2；标准隔离构建；日志 /tmp/autoresearch-audit-install.log
```

另有一次未隔离构建因空环境没有 setuptools 失败，该次只说明环境缺 backend，不作为项目打包缺陷证据。标准隔离构建的 multiple-top-level-packages 才是上述结论依据。
