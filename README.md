# AutoResearch Framework

一个带预算账本、准入凭据和常驻随机对照的自动研究／进化运行时。

本仓库由 `AutoResearch-接续开发完整包.zip` 导入，当前源码基线为 **M0 / verifier v57**。它是开发中的 Python 框架原型：已实现较丰富的治理、恢复与互操作机制，真实外部 benchmark 和产品级验收仍未完成。

本仓库使用化名 `mori-27`，按交接包独立导入；公开内容仍可能被搜索引擎索引。

## 先读这里

- [2026-10-29 代码包详细梳理与审查](docs/CODEBASE_REVIEW_2026-10-29.md)：架构、模块支持矩阵、运行验证、可复现问题及后续优先级。
- [原始接续开发说明](接续开发说明.md)：交接时的状态声明和环境说明。
- [M0 代码文档](m0/README.md)与[术语及契约](m0/CONTEXT.md)。
- [导入完整性记录](docs/review/import-audit.json)及[第三方来源](THIRD_PARTY_NOTICES.md)。
- [原始总索引](docs/review/README.original.md)：完整保留原字节，内部相对路径以原仓库根目录为参照。

## 已有能力

- 通过 `Framework.evolve()`、`inspect()`、`replay()` 驱动和审查搜索。
- 预算意图、七账户预扣与结算、常驻 IID 随机采样对照。
- 基于逐样本输赢的 M9 准入门，以及只追加的 Receipt／证据记录。
- GEPA 反射、FunSearch 岛屿、MAP-Elites 网格三种 profile；均有明确子集边界。
- 批次调度、检查点、多个指定进程崩溃窗口的接管与恢复。
- Git worktree 执行、可选／按适配器默认启用的 Bubblewrap、人工审批接口。
- OpenEvolve 数据库、artifact、谱系和 embedding 状态互操作。
- MLE-Bench Lite／RE-Bench 的任务与评分契约适配。

**完成度不能由测试数量代替。** 原包 v57 历史记录为 490 项通过，但证书同时明确真实外部 API 与 benchmark campaign 未执行。本次独立复核还发现样本身份校验、单币账本、成本口径及 seccomp ABI 覆盖等问题，详见审查报告；源码保持原包基线，尚未修复这些问题。

## 目录

```text
m0/                 Python 内核、配置、59 个测试文件、v1–v57 验收历史
  core/             调度、预算、准入、执行、恢复、记忆与知识等
  config/profiles/  三种 profile
  examples/         三个不需要模型 API key 的示例
  zoo/              MLE-Bench Lite 与 RE-Bench 适配器
  vendor/           OpenEvolve 普通源码快照
autoresearch-fw/    规格、愿景、RUBRIC、各模块统一设计
docs/               综合设计与本次独立审查
research/           调研证据和模块分析
plans/              历史计划
papers/             原始研究材料
scripts/            导入完整性核验
MANIFEST.json       原始压缩包清单，保留不改
```

## 本地启动

完整沙箱验收的参考环境为 **Linux x86_64 + Python 3.12 + Bubblewrap**。源码元数据声明 Python ≥3.11；本次实际验证使用 Python 3.12。macOS/ARM 可运行部分离线逻辑与示例，但不能据此认证 Linux 沙箱及完整恢复套件。

在仓库根目录建立独立环境，安装原包列出的测试与宿主依赖：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install pytest dacite openai pyyaml numpy
python scripts/verify_import.py
cd m0
python ci/check_axioms.py
python examples/toy_gepa.py
python examples/gsm8k_offline.py
python examples/funsearch_offline.py
```

上述例子的模型响应为离线脚本，示例得分不代表真实 GEPA／GSM8K／FunSearch benchmark 成绩。

在准备好 Bubblewrap 和相应 namespace 支持的 Linux x86_64 环境中，可运行完整测试：

```bash
# Debian/Ubuntu 环境准备
sudo apt-get update
sudo apt-get install -y bubblewrap
# 以下命令从 m0/ 执行
python -m pytest -q -p no:cacheprovider
```

`python verifier/v57/verify.py` 是原始版本化验收入口，会更新 `LAST_RUN.json` 并追加 journal；复核历史基线时宜在独立工作副本中运行并另存结果。本次没有覆盖原历史证书。原包的 workflow 位于 `m0/.github/workflows/`，在此仓库根目录布局下不会自动成为 GitHub Actions 工作流；本次未宣称 hosted CI 已验证。

当前 `pyproject.toml` 尚未定义完整安装依赖和打包配置，因此以上采用从 `m0/` 源码目录运行的方式。

## 导入与许可

原包共 1,048 个文件；其中清单覆盖的 1,047 个负载文件全部核验通过。仓库保留 1,020 个负载文件，排除 27 个嵌套 Git 元数据文件；原 README 另存于 `docs/review/README.original.md`。全部生产代码、原测试、配置和历史验收证据字节保持不变。

```bash
python scripts/verify_import.py
```

新增文档和审查证据不在原 `MANIFEST.json` 的覆盖范围内。第三方许可证保持原样；项目整体授权待明确，参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
