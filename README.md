# AutoResearch Framework

一个带预算账本、准入凭据和常驻随机对照的自动研究／进化运行时。

本仓库由 `AutoResearch-接续开发完整包.zip` 导入，原始基线为 **M0 / verifier v57**，当前 Linux 验收入口为 **v76**。各提交的实际检查状态以对应 CI 为准。项目仍在开发：部分真实任务已有成绩，完整 benchmark 与产品级验收尚未完成。

## 真实任务结果：三任务、两个批次、三个 seed

以下是 `a6b5826` 上的 M7 真实模型试跑，使用官方 MLE-bench grader；表中是三个本地 seed 的描述性平均，所有指标越低越好。baseline 与 full 的搜索方法不同，**不能作为治理收益的单变量对比**。

| 任务 / 指标 | baseline | full |
| --- | ---: | ---: |
| Spooky Author Identification / log loss | 0.40732 | 0.42306 |
| Leaf Classification / log loss | 0.84945 | 0.45621 |
| NOMAD / 两个 RMSLE 的平均值 | 0.06393 | 0.06320 |

全部 18 份提交有效。seed 1 和 seed 2/3 分为两个冻结批次，第二批在看到第一批结果后启动；模型标识为可变别名 `deepseek-flash`，尚未验证不可变模型快照。这里只覆盖三个任务，不代表完整 MLE-Bench Lite 或统计显著结果。逐 seed 成绩、批次差异、费用、审计与失败记录见[试跑报告](research/experiments/2026-11-05-m7-real-mle-three-seeds/README.md)。

## 经典工作的真实小规模结果

以下为已合入 main 的适配方法，均使用真实模型运行；具体规模、失败和证据见各报告。它们不是等预算方法对照，也不表示完整论文复现。

| 方法与任务 | 真实终评结果 | 解释与证据 |
| --- | --- | --- |
| GEPA / GSM8K | 1/3 次完成终评：127/128；另 2 次因模型输出截断失败 | 只进行一次反思提案，最终选中初始 prompt，不能将成绩归因于优化。[结果与失败](research/experiments/2026-11-05-gepa-gsm8k/README.md) |
| FunSearch / OR3 装箱 | 3/3 个 seed 的 held-out 均为 210.1 箱，越少越好 | 三次均与固定 best-fit 持平，未显示留出集收益；31/33 候选有效。[结果与失败](research/experiments/2026-11-05-funsearch-or3/README.md) |
| AIDE / MLE 三任务 | 官方 score 均值：spooky 0.369990、leaf 0.080923、nomad 0.062363，越低越好 | 每任务 3/3 份提交有效；nomad 的历史阈值映射为铜／银／银。[九组结果](research/experiments/2026-11-05-aide-mle/README.md) |
| Arbor / MLE 三任务 | 官方 score 均值：spooky 0.453330、leaf 0.172093、nomad 0.061257，越低越好 | 每任务 3/3 份提交有效；nomad 三组达到历史银牌阈值。[九组结果](research/experiments/2026-11-05-arbor-mle/README.md) |

MLE 历史阈值由固定评分器映射，不是新的 Kaggle 在线排名或实际获奖；两个方法的预算与搜索设置不同，不应仅凭表格比较方法优劣。GEPA 各 seed 的输出上限并不完全一致，也不计算三 seed 均值。OpenEvolve 正在开发，尚无真实配对 benchmark 成绩；AIRA、LoongFlow 和 R&D-Agent 仍在后续计划中。

GEPA 新入口（默认离线、不访问模型）：

```sh
uv run --project m0 --locked python -m zoo.gepa_gsm8k.runner \
  --mode fixture --max-proposals 2 --output /tmp/gepa-fixture
```

FunSearch 新入口（默认离线；需要 Linux x86_64 和 Bubblewrap）：

```sh
uv run --project m0 --locked python -m zoo.funsearch_binpacking.runner \
  --mode fixture --max-proposals 2 --output /tmp/funsearch-fixture
```

### 方法和证据范围

| 工作 | 任务与运行时 | 本仓库证据 | 尚未完成 |
| --- | --- | --- | --- |
| MLE 搜索（baseline / full） | 三个公开任务；M7 | [真实模型、三个 seed 的官方评分](research/experiments/2026-11-05-m7-real-mle-three-seeds/README.md) | 完整 MLE-Bench Lite；两种搜索方法不同，不能隔离治理效果 |
| 同搜索治理强度对照 | 三个公开任务、单 seed；M7 | [真实模型官方评分和总费用上界](research/experiments/2026-11-05-m7-governance-intensity/README.md) | 更大样本、候选接纳数与单独控制开销；不能直接视为有无治理的因果比较 |
| GEPA 单组件 prompt 优化 | GSM8K train/validation/test；M7 | [真实试跑、逐题成绩与失败](research/experiments/2026-11-05-gepa-gsm8k/README.md)；[运行命令](m0/zoo/gepa_gsm8k/PROVENANCE.md) | 更充分的多提案搜索、同配置多 seed 等预算对照与公开区间复现 |
| FunSearch 程序进化 | OR3 dev/held-out；M7 隔离执行 | [三 seed 真实搜索、全部失败与留出成绩](research/experiments/2026-11-05-funsearch-or3/README.md)；[运行命令](m0/zoo/funsearch_binpacking/PROVENANCE.md) | 更大规模、等预算对照与论文区间复现；本批无留出收益 |
| AIDE 代码树搜索 | 三个 MLE 任务 × 三 seed；M7 | [九组官方评分、代码树、失败与费用](research/experiments/2026-11-05-aide-mle/README.md)；70/90 主候选有效，九组提交均有效 | 完整 MLE-Bench、等预算方法对照与论文区间复现；历史奖牌阈值不等于实际获奖 |
| Arbor 假设驱动研究 | 三个 MLE 任务 × 三 seed；M7 | [九组官方成绩、准入拒绝、经验来源与费用](research/experiments/2026-11-05-arbor-mle/README.md)；38/44 主候选有效；[运行命令](m0/zoo/mle_bench_lite/README.md#c04-arbor-adapted-recipe) | 完整 benchmark、等预算对照与论文区间复现 |

本仓库使用化名 `mori-27`，按交接包独立导入；公开内容仍可能被搜索引擎索引。

## 先读这里

- **[经典工作接入路线与分支决定](docs/CLASSIC_WORKS_PLAN.md)**：2026-11-05 本轮规划入口，包含文档优先级、九模块职责、八项工作规格、扩展目录和 main 整合顺序。已获准按路线施工；各方法状态单列，当前进度与 Goal 状态见[当前执行目标](docs/CURRENT_GOAL.md)。
- [持续开发接续记录](docs/CONTINUATION_2026-11-04.md)：当前分支、已验证基线、真实试跑前置条件、提交与复审节奏。
- [四个 RSI 项目源码比较](research/2026-11-04-rsi-comparison.md)：固定 SHA 的机制证据与可验证差异化实验。

- [统一抽象](docs/AutoResearch模块化统一抽象.md)是当前开发基准；[逐项对照清单](docs/ABSTRACTION_ALIGNMENT.md)记录实现证据、各阶段边界和验收条件。
- [S1 配置组装使用指南](docs/COMPOSED_RUNTIME.md)：推荐入口 `Framework.from_profile("composed_prompt", ...)`、组件替换、恢复与 replay 契约。
- [S2 统一评估契约](docs/EVALUATION_CONTRACT_V61.md)：原生 domain、严格身份和计量覆盖、公开/私有视图、v2 检查点兼容边界。
- [S3 上下文与本地知识回流](docs/CONTEXT_FEEDBACK_V62.md)：有作用域的 ContextPack、显式跨 run 导出/导入、ground/audit 隔离和 v3 运行身份。
- [S4 三层准入与独立终审](docs/LAYERED_ADMISSION_V63.md)：显式 native 三层配置、调用硬顶、可复算回执和冻结候选终审。
- [S5 分层物理预算与 fidelity](docs/HIERARCHICAL_BUDGET_V64.md)：全局/方向/候选独立限额、实际请求、预算输入和低样本停止规则。
- [S6 周期 anchor 与代理有效性](docs/PROXY_VALIDITY_V65.md)：独立 calibration 配对、秩相关规则和仅当前 run 的负反馈。
- [S7 worktree 与进程接管](docs/WORKTREE_RECOVERY_V66.md)：真实命令执行、保护输入、持久进程身份和主循环恢复边界。
- [S8 种群与双亲交叉](docs/POPULATION_RUNTIME_V67.md)：有界成员、可复算父代抽样、独立 M9 晋升和恢复。
- [S9 MLE 配置评估与试跑](docs/MLE_COMPOSED_V68.md)：公开训练数据的独立校准、负反馈、种群搜索和同模型同预算子集对照；真实试跑证据与机制验收分开。
- [M7 配置构造与费用保护](docs/CONFIGURED_CONSTRUCTION.md)：角色、假设与上下文参与生成，原生/Git 产物复用，恢复及费用关联审计。
- [配置式常驻对照与七账户治理](docs/GOVERNED_CONTROLS.md)：可运行的离线示例、固定对照计划、保护额度、隔离会话及零新调用的证据回放。
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

v59 继续修复数据集内容绑定、进程身份写入、配置前置校验、完整判定回执与 replay 隔离。旧回执兼容边界、适配器契约及验证范围见 [v59 修复说明](docs/EVALUATION_FIXES_V59.md)。旧模式的 `replay()` 会重新执行适配器，可能再次产生提供方费用；新的 `composed-v7-governed` 模式只采用已记录结果，缺失证据时拒绝回放。

## 配置组装入口

新开发使用 `Framework.from_profile("composed_prompt", llm, evaluator, config, workdir)`，继续通过 `evolve()`、`inspect()`、`replay()` 操作。S1 将 provider、domain、policy、operators、frontier、memory、executor、admission、budget 和 skills 接入显式注册表；默认 greedy 策略和可选 `llm_cycles` 都使用默认 8 条的有界工作历史。

五阶段顺序为模块组装、统一评估契约、记忆与知识回流、三层准入、分层预算。S1 交付配置组装，S2 补齐配置路径的评估契约，S3 接入作用域经验和本地知识回流，S4 增加显式启用的三层准入，S5 增加显式分层物理预算。默认兼容配置仍只做 dev 指标准入和 token 预算；新能力需要选择相应模块。五阶段覆盖范围与剩余条款以清单记录为准。旧 M0 的 IID 对照、二元 gate、批次与中断接管能力保留在原路径，不能视为组装路径的完成项。

S1 只接受 `batch_size=max_inflight=1`，支持 cycle 边界恢复；未完成的付费 cycle 会拒绝自动重调。replay 需要独立适配器和新组件实例，并对再次执行的用量记账。可直接运行的离线例子、配置选项及准确边界见 [S1 使用指南](docs/COMPOSED_RUNTIME.md)。

S2 在配置路径使用带身份和计量契约的规范评估结果，保存完整私有证据，向搜索投影公开字段，向准入提供不含费用的比较视图。原生 domain 与 legacy dev-only 适配器的接入和限制见 [S2 指南](docs/EVALUATION_CONTRACT_V61.md)。

S3 引入 `composed-v3`，每个新 run 有独立记忆身份，恢复和 replay 保留该逻辑身份。经验与已打开的本地 ground 来源真正进入后续候选输入，audit 单独记录；跨 run 分享需显式导出及内容 hash 授权。当前检索按词项相关度排序，未联网或宣称向量检索质量。旧 v1/v2 检查点不自动升级，具体配置和限制见 [S3 指南](docs/CONTEXT_FEEDBACK_V62.md)。

S4 引入 `composed-v4`，原生 domain 可选 `admission=layered`；dev、admission、final_audit 使用不同内容身份，准入次数有硬顶，每次额外评估独立预扣费用。冻结后的 final 只出报告，不回流搜索或经验；不支持的 top-k/HITL 明确拒绝。旧 v1/v2/v3 检查点不自动升级，详见 [S4 指南](docs/LAYERED_ADMISSION_V63.md)。

S5 引入 `composed-v5`，不自动接收旧 v1–v4 检查点。`budget=hierarchical` 让 global、direction、candidate 成为同一物理操作账本的三个视图，按单位分别预扣/结算，实际超额如实记录后停止新调用。fidelity 由配置生成真实请求，低样本停止规则不宣称统计显著。详见 [S5 指南](docs/HIERARCHICAL_BUDGET_V64.md)；完整离线 research 示例纳入 Mac 与 Linux 验收。

S6 周期 anchor/代理有效性回流已按同 SHA CI 封板。S7 新增 `command` domain 与 `git_worktree` executor 的配置组合，使用 hierarchical 预算和 checkpoint 进行真实命令执行与进程接管；Mac 必须显式选择可信本地 `sandbox="none"`，Linux 默认使用 bubblewrap。S8 新增 `population_prompt`：elite 成员保留、四种可复算父代采样和双亲文本 crossover，详见 [S8 指南](docs/POPULATION_RUNTIME_V67.md)。逐项范围和阶段门槛见 [对照清单](docs/ABSTRACTION_ALIGNMENT.md)，配置和平台限制见 [S7 指南](docs/WORKTREE_RECOVERY_V66.md)。实现与验收范围以阶段记录和同 SHA CI 证据为准。

S9 新增 MLE-Bench Lite 的 `composed_agent` 和显式 `pilot` 入口，把最新 anchor、负反馈与种群接到三个公开 CSV 任务。旧 M0 benchmark 入口保留；新试跑的 baseline/full 使用同一模型、数据和资源上限，每批次所有提交冻结后才调用官方 grader。[三任务三个 seed 的试跑](research/experiments/2026-11-05-m7-real-mle-three-seeds/README.md)已完成，分为两个分别冻结的批次；完整 Lite 实验仍未完成。具体接口见 [S9 指南](docs/MLE_COMPOSED_V68.md)。

显式配置 `governance` 可启用 `composed-v7-governed`：主搜索和独立对照共用物理结算权威，七账户是同一实际费用的投影；未来对照额度预先保护，主搜索可见预算固定，避免从对照花费推断结果。调用回执绑定 run、lane、slot、intent、ordinal 和适配器参数，恢复及回放核验原始结果而不重新调用。Native 和真实 worktree 路径均有例子与测试；[使用指南](docs/GOVERNED_CONTROLS.md)说明当前支持范围。该 v7 路径不接收外部货币 provider；后续 v8 桥接已实现，见下一段。两者均不能据此宣称真实付费 IID-RS 已达标。

新增 [外部费用治理桥接](docs/GOVERNED_CURRENCY.md) 提供独立的 loopback HTTP 示例、双重准入和记录恢复；真实付费三任务试跑已使用该桥接，但尚未完成同搜索治理收益对照。

**当前代码位置：** `main` 已包含 GEPA、FunSearch、AIDE 和 Arbor 的适配及小规模真实结果；Arbor 已通过 [PR #8](https://github.com/YixuanZhang99/mori-27/pull/8) 合入。当前开发分支为 `codex/classic-openevolve`：离线工程验证正在推进，真实配对试跑及合入尚未完成。后续顺序和详细状态见[当前执行目标](docs/CURRENT_GOAL.md)。

## 目录

```text
m0/                 Python 内核、配置、回归测试、v1–v72 历史及 v73 验收入口
  core/             调度、预算、准入、执行、恢复、记忆与知识等
  config/profiles/  三种经典 profile、composed_prompt 与 population_prompt
  examples/         不需要模型 API key 的示例与常驻治理入门流程
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

根 `.github/workflows/ci.yml` 在 push/PR 时运行 macOS 可移植检查、Linux v76 完整验收及 MLE 合成数据检查。Linux 验收在临时副本中运行，结果作为 Actions artifacts 保存；具体通过状态以对应提交的工作流为准。

```bash
make test          # Mac 可移植测试
make build         # 生成 wheel 和 sdist
make accept-linux  # Linux x86_64：全量版本化验收
make verify-import # 核验初始导入 Git 快照
```

详见 [开发与测试指南](docs/DEVELOPMENT.md)。原 [代码审查报告](docs/CODEBASE_REVIEW_2026-10-29.md)记录导入时状态；开发环境、打包与 CI 已配置，v58 与 v59 的修复范围和兼容行为见各版本修复说明。v60、v61 分别新增 S1 组装和 S2 评估契约组；v62 增加 S3 经验与知识回流端到端组；v63 增加 S4 三层准入与终审组；v64 增加 S5 分层预算组及完整离线 research 示例；v65 增加 S6 proxy 有效性回流组；v66 增加 S7 worktree 与公开 Framework 接管组；v67 增加 S8 种群组；[v68](m0/verifier/v68/README.md)保留全部旧组并增加 S9 MLE 配置评估与试跑组。[v69](m0/verifier/v69/README.md) 保留全部 v68 检查，增加私有匿名顺序、沙箱前置探针及[跨运行人民币预算](docs/DEEPSEEK_CAMPAIGN_BUDGET.md)。[v70](m0/verifier/v70/README.md) 保留全部 v69 检查，新增剩余物理预算预留与跨进程日志快照检查。[v71](m0/verifier/v71/README.md) 继续保留全部旧组，增加请求输入容量、预算拒绝结算和已知拒绝恢复检查。[v72](m0/verifier/v72/README.md) 保留全部 v71 命令和超时，增加常驻对照、受保护的七账户物理预算、隔离 session、恢复与记录回放、人民币 authority 显式迁移及语义审计。v72 的认证范围不包含外部 provider/currency bridge。[v73](m0/verifier/v73/README.md) 保留全部历史命令和超时，新增外部费用桥接的身份、双重准入、崩溃恢复、独立审计及 native/worktree loopback 验证，成功时共50项检查；不宣称真实供应商运行、IID、账单核验或正式发布。当前提交是否通过验收，以其 Actions 日志和新证书为准。离线示例使用脚本模型，得分不代表真实外部 benchmark 成绩。

## 导入与许可

原包共 1,048 个文件；其中清单覆盖的 1,047 个负载文件全部核验通过。仓库保留 1,020 个负载文件，排除 27 个嵌套 Git 元数据文件；原 README 另存于 `docs/review/README.original.md`。初始导入时，全部生产代码、原测试、配置和历史验收证据字节保持不变；后续开发通过独立 Git 提交记录。

```bash
make verify-import
```

新增文档和审查证据不在原 `MANIFEST.json` 的覆盖范围内。第三方许可证保持原样；项目整体授权待明确，参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
