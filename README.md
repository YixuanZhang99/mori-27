# AutoResearch Framework

一个带预算账本、准入凭据和常驻随机对照的自动研究／进化运行时。

本仓库由 `AutoResearch-接续开发完整包.zip` 导入，原始基线为 **M0 / verifier v57**，当前验收入口为 **v61**。它是开发中的 Python 框架原型：已实现较丰富的治理、恢复与互操作机制，真实外部 benchmark 和产品级验收仍未完成。

本仓库使用化名 `mori-27`，按交接包独立导入；公开内容仍可能被搜索引擎索引。

## 先读这里

- [统一抽象](docs/AutoResearch模块化统一抽象.md)是当前开发基准；[逐项对照清单](docs/ABSTRACTION_ALIGNMENT.md)记录实现证据、五阶段边界和验收条件。
- [S1 配置组装使用指南](docs/COMPOSED_RUNTIME.md)：推荐入口 `Framework.from_profile("composed_prompt", ...)`、组件替换、恢复与 replay 契约。
- [S2 统一评估契约](docs/EVALUATION_CONTRACT_V61.md)：原生 domain、严格身份和计量覆盖、公开/私有视图、v2 检查点兼容边界。
- [2026-10-29 代码包详细梳理与审查](docs/CODEBASE_REVIEW_2026-10-29.md)：架构、模块支持矩阵、运行验证、可复现问题及后续优先级。
- [原始接续开发说明](接续开发说明.md)：交接时的状态声明和环境说明。
- [M0 代码文档](m0/README.md)与[术语及契约](m0/CONTEXT.md)。
- [导入完整性记录](docs/review/import-audit.json)及[第三方来源](THIRD_PARTY_NOTICES.md)。
- [原始总索引](docs/review/README.original.md)：完整保留原字节，内部相对路径以原仓库根目录为参照。

## 已有 M0 能力

- 通过 `Framework.evolve()`、`inspect()`、`replay()` 驱动和审查搜索。
- 预算意图、七账户预扣与结算、常驻 IID 随机采样对照。
- 基于逐样本输赢的 M9 准入门，以及只追加的 Receipt／证据记录。
- GEPA 反射、FunSearch 岛屿、MAP-Elites 网格三种 profile；均有明确子集边界。
- 批次调度、检查点、多个指定进程崩溃窗口的接管与恢复。
- Git worktree 执行、可选／按适配器默认启用的 Bubblewrap、人工审批接口。
- OpenEvolve 数据库、artifact、谱系和 embedding 状态互操作。
- MLE-Bench Lite／RE-Bench 的任务与评分契约适配。

**完成度不能由测试数量代替。** 原包 v57 历史记录为 490 项通过，但证书同时明确真实外部 API 与 benchmark campaign 未执行。导入时发现的样本身份、预算账本、成本计量及 seccomp ABI 问题已纳入 v58 修复与回归测试，详见 [修复说明](docs/SAFETY_FIXES_V58.md)。

v59 继续修复数据集内容绑定、进程身份写入、配置前置校验、完整判定回执与 replay 隔离。旧回执兼容边界、适配器契约及验证范围见 [v59 修复说明](docs/EVALUATION_FIXES_V59.md)。`replay()` 会重新执行适配器，可能再次产生提供方费用。

## 配置组装入口

新开发使用 `Framework.from_profile("composed_prompt", llm, evaluator, config, workdir)`，继续通过 `evolve()`、`inspect()`、`replay()` 操作。S1 将 provider、domain、policy、operators、frontier、memory、executor、admission、budget 和 skills 接入显式注册表；默认 greedy 策略和可选 `llm_cycles` 都使用默认 8 条的有界工作历史。

五阶段顺序为模块组装、统一评估契约、记忆与知识回流、三层准入、分层预算。S1 的交付范围是配置组装：旧 evaluator 通过 `legacy_prompt` 显式适配 canonical 类型；记忆写入已接入，检索和知识回流待 S3；默认只做 dev 指标准入和 token 预算，三层准入与多资源分层预算仍待后续阶段。旧 M0 的 IID 对照、二元 gate、批次与中断接管能力保留在原路径，不能视为组装路径的完成项。

S1 只接受 `batch_size=max_inflight=1`，支持 cycle 边界恢复；未完成的付费 cycle 会拒绝自动重调。replay 需要独立适配器和新组件实例，并对再次执行的用量记账。可直接运行的离线例子、配置选项及准确边界见 [S1 使用指南](docs/COMPOSED_RUNTIME.md)。

S2 在配置路径使用带身份和计量契约的规范评估结果，保存完整私有证据，向搜索投影公开字段，向准入提供不含费用的比较视图。新的 `composed-v2` 检查点不会自动接受缺契约的 S1 检查点；原生 domain 与 legacy dev-only 适配器的接入和限制见 [S2 指南](docs/EVALUATION_CONTRACT_V61.md)。

## 目录

```text
m0/                 Python 内核、配置、回归测试、v1–v60 历史及 v61 验收入口
  core/             调度、预算、准入、执行、恢复、记忆与知识等
  config/profiles/  三种经典 profile 与 composed_prompt 组装配置
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

## Mac 开发与 Linux 自动验收

当前开发环境使用 **Python 3.12 + uv lock**。在 Mac 上：

```bash
make setup
make check
```

`make check` 运行静态公理、全部可移植测试、离线示例及验收包装器回归。Linux 集成测试由 GitHub Actions 在 Ubuntu x86_64 上执行；完整验收运行全部 pytest，任何 skip/xfail 都使验收失败。

根 `.github/workflows/ci.yml` 在 push/PR 时自动运行完整 v61，使用系统 Python 和 `/usr/local/share` 虚拟环境以满足现有沙箱挂载范围。验收在临时副本中运行，保留原历史证书，结果与安装包作为 Actions artifacts 保存。

```bash
make test          # Mac 可移植测试
make build         # 生成 wheel 和 sdist
make accept-linux  # Linux x86_64：全量版本化验收
make verify-import # 核验初始导入 Git 快照
```

详见 [开发与测试指南](docs/DEVELOPMENT.md)。原 [代码审查报告](docs/CODEBASE_REVIEW_2026-10-29.md)记录导入时状态；开发环境、打包与 CI 已配置，v58 与 v59 的修复范围和兼容行为见各版本修复说明。v60 新增 S1 注册表、默认组件与端到端测试；[v61](m0/verifier/v61/README.md)保留所有旧组并增加配置运行时的 S2 评估契约与端到端组。当前提交是否通过验收，以其 Actions 日志和新证书为准。离线示例使用脚本模型，得分不代表真实外部 benchmark 成绩。

## 导入与许可

原包共 1,048 个文件；其中清单覆盖的 1,047 个负载文件全部核验通过。仓库保留 1,020 个负载文件，排除 27 个嵌套 Git 元数据文件；原 README 另存于 `docs/review/README.original.md`。初始导入时，全部生产代码、原测试、配置和历史验收证据字节保持不变；后续开发通过独立 Git 提交记录。

```bash
make verify-import
```

新增文档和审查证据不在原 `MANIFEST.json` 的覆盖范围内。第三方许可证保持原样；项目整体授权待明确，参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
