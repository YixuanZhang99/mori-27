# Classic Work Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 结束串联开发分支，按九模块规格逐项交付经典工作，先 GEPA/FunSearch 的可运行闭环。

**Architecture:** 复用当前 Framework、composition registry、M7 和预算/证据通道。方法是 profile + 必要插件；任务差异归 zoo。一次一个方法，后续方法只在其 spec 冻结后细化实现任务。

**Tech Stack:** Python >=3.11；现有锁定依赖、JSON profiles、pytest、GitHub Actions。

**Spec:** [CLASSIC_WORKS_PLAN](../../CLASSIC_WORKS_PLAN.md)、[COMMON](../../specs/classic/COMMON.md)、[C01](../../specs/classic/GEPA.md)、[C02](../../specs/classic/FUNSEARCH.md)。

## Global Constraints

- 用户已于 2026-11-05 批准按本计划执行、整合 main 并逐方法交付；控件限制与当前执行目标见 `docs/CURRENT_GOAL.md`。
- 不修改原 VISION/RUBRIC 完成阈值；遵守现有 Mac `make check` + 同 SHA Linux 验收的主线门槛。
- 保留既有公开 `Framework.from_profile/evolve/inspect/replay`；不另造方法主循环。
- 每个正式试跑使用同一累计 ¥200 账本；密钥不打印、不复制到产物。
- 旧数据、失败记录、verifier、bundle 不删除；未推的 FunSearch WIP 不整体合入。

## Review Focus

1. 方法需要的训练配对/validation 表在现 runtime 中无法表达：Task 2 先确认通用接缝，不能用标签伪装。
2. 未击败全局 best 的有效个体被治理删掉：Task 3 的实例赢家/供亲反例必须覆盖。
3. solver 或反思费用漏算：Task 3 所有 provider 调用核对同一账本。
4. 三任务旧成绩被误标成新方法成绩：Task 4/5 的 report 绑定 recipe/source，旧结果只作为历史。
5. 重定向 PR 后 CI 或 Mac 未通过：Task 1 不凭旧 base 的绿灯合并。

---

### Task 1：一次性收敛整合基线

**Files:** `.github/workflows/ci.yml`、`docs/FRAMEWORK_STATUS.md`、`docs/DEVELOPMENT.md`、PR #4 元数据。
**Interfaces:** 输入为 `origin/main` 和现 m7 分支的冻结 SHA；输出为含既有成果、可核对 Linux/Mac 证据的新 main SHA，保留原提交历史。

- [x] 保存 main/候选回滚引用；核对 `git merge-base --is-ancestor origin/main origin/codex/m7-construction`。
- [x] 补 macOS `make check` job，保留现 Linux job 与测试；验证 portable 测试明确排除 Linux、无 skip/xfail 偷过。
- [x] 更新 #4 为唯一面向 main 的整合 PR；正文写真实范围和剩余缺口，移除过期“final acceptance pending”描述。
- [x] 最终候选 Mac + Linux 检查通过，并审查 main 到候选完整差异，再保留历史合并；main 检查通过后处理 #1–#3 和祖先分支。
- [x] 更新状态页，明确唯一稳定 main 与下一条 `codex/classic-gepa`；提交/推送并保留回滚点。

### Task 2：冻结 GEPA 的最小协议差距

**Files:** `docs/specs/classic/GEPA.md`；读取 `m0/core/composition/contracts.py`、`gepa_policy.py`、`runtime.py`、`evaluation.py` 与固定 upstream。
**Interfaces:** 保留现行 `Policy.observe/select/ideate/absorb`、`Operator.propose`、`Domain.evaluate`；产物为配对评估与 validation 请求的具体数据流决策，不新建 public Framework API。

- [x] 从 pinned reference 提取 acceptance/tie、minibatch、reflection/validation 更新顺序，与 C01 G1–G5 对照。
- [x] 画一轮具体 item IDs 的数据流，先按原始数据行固定身份再切 minibatch，确认 train/validation/test 权限和所有调用的计费归属。
- [x] 若通用请求无法承载配对结果，写明最小扩展字段/类型/调用位置及拒绝条件；否则明确复用现有接口。此决策必须先于实现，不能把未知签名写成已定。
- [x] 锁定数据 revision/hash、任务参数及允许差异，提交 C01 spec；此时才标“规格冻结”。

### Task 3：GEPA 公开入口机制闭环

**Files:** C01 列出的 `zoo/gepa_gsm8k/`、profile、policy/recipe 与 `test_gepa_recipe.py`。
**Interfaces:** 输入为已冻结配置、provider、domain；输出继续为 Framework result、inspect 证据和记录 replay，附方法元数据。

- [x] 为 G1–G5 编写五组决定性测试：实例互补、同批父子与 tie、拒绝不更新 validation、两份合法冻结 test 标签不影响搜索（运行中篡改另测拒绝）、反思来源与零调用回放；同时断言重排/抽批不重编号，确认当前代码失败在所述缺口。
- [x] 最小实现配对反思和验证表更新，复用已有 frontier/M7/预算，只增加 Task 2 冻结的接缝。
- [x] 额外断言 proposer/solver/validation 调用均有成本记录，失败同样保留，control 不进入主候选池。
- [x] 运行 `PYTHONPATH=m0 python -m pytest -q m0/tests/test_gepa_recipe.py m0/tests/test_gepa_instance_frontier.py m0/tests/test_gepa_instance_policy.py`；预期全通过。
- [x] 从 profile 跑一次 fixture 和一次记录回放，核对决策/账本，提交推送；不为每个小修复追加 verifier 版本。

### Task 4：GEPA 小规模真实交付

**Files:** C01 runner、`research/experiments/<date>-gepa-gsm8k/`、README 方法矩阵。
**Interfaces:** 输入为冻结 manifest 和已有凭据位置；输出逐 seed 原始结果、方法身份与可重算 summary，不含密钥。

- [x] 先验证 fixture/live 模式显式切换和成本预检；确认原累计账本剩余额度，不重置。
- [x] 一个 smoke 后按预声明三 seed 执行，包含失败；模型别名与版本未知如实记录。
- [x] 冻结候选后一次 test 评分，输出 accuracy/成本/对照/差异，不把新结果拼接到旧 MLE 报告。
- [ ] 在方法结果上审查 C01、一次现有合入检查，通过后合并；若结果不提升仍可交付“无提升”报告，公开区间复现状态保持未通过。

### Task 5：FunSearch、其余方法顺序推进

**Files:** C02 指定文件；随后各 C03–C08 spec 的文件清单。
**Interfaces:** 方法输入继续 profile/provider/domain；任务数据沿用 zoo 契约，控制预算/证据通道不复制。

- [ ] 对照 C02 F1–F5 审阅本地 WIP，仅取真实运行与冻结留出需要的最小代码；列出不采用项和原因。
- [ ] 先写留出泄漏/冻结后选择反例，再实现缺口，使用已有 FunSearch 公共入口回归和一个三 seed 小试跑。
- [ ] 交付 C02 独立结果并合并；检查切换 GEPA/FunSearch 是否只需 profile/plugin，不能修改核心循环。
- [ ] 依序把 C03、C04、C05 提升为冻结 spec；每次复制“关键行为→最小实现→公开入口→真实结果”四步，禁止一次同时开三套实现。
- [ ] C06–C08 和扩展目录保持排队；仅在进入施工前为该方法补来源锁定和细粒度任务，避免提前写大量失效计划。

本计划刻意不为后续未冻结协议伪造函数签名。Task 2 是明确的冻结关口；后续每个方法也必须先具备可执行验收，再进入实现。
