# C02 FunSearch Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 按 C02 交付保留有效岛屿成员的程序搜索、冻结留出评分、三 seed 真实结果及可重算报告。
**Architecture:** 继续公共 Framework 与 M7/CNY。用 PopulationFrontier 保留有效候选，FunSearchCoordinator 的已有抽样凭证负责岛屿选择；任务文件和双 split 评分位于 zoo，终选复用 metric_final。
**Tech Stack:** Python >=3.11，锁定 uv 环境，NumPy，现有 Linux Bubblewrap/seccomp，pytest。
**Spec:** docs/specs/classic/FUNSEARCH.md，继承 COMMON.md。本计划承接用户已批准的逐方法集成目标。

## Global Constraints

- codex/classic-funsearch 本地先从 GEPA 最终候选开发；GEPA 合入后，将未发布提交衔接到新 main，才推送唯一方法分支；不导入 4df353f 的 supervisor/authority/price/owner 栈。
- 九模块和公共 API 不变；不得另造主循环或借放宽原始证据校验通过测试。
- 两岛、prompt_size=2、temperature=1、temperature_period=10、reset_interval=5，seeds 0/1/2，各初始构造加最多10提案。reset 按成功登记的搜索 cycle 触发（现有实现），失败不增加该计数；不是墙钟重置。
- 固定 priority(item, bins) 模板；np 在隔离 worker 提供。生成代码只能看到当前 item 和可容纳它的 bins 容量。
- dev/held_out 各10实例，冻结官方 notebook 与两 split hash；平均负 bin 数越大越好。总体 incumbent 取 dev mean；FunSearch 簇采样保持现有参考 signature 聚合（最后一个排序 case 的值），两者明确分别报告。
- Linux 实际沙箱验收；新增依赖沙箱的测试明确加入平台清单。离线默认无外部请求，live 明确启用。
- 原累计 ¥200 campaign；供应商上限、模型别名、全部失败与费用保留。初始独立 control 是 sanity check，不是等预算对照。

## Review Focus

1. 同分/较差但有效候选被全局 promotion 门禁永久排除，导致岛屿搜索退化。任务1用反例断言供亲资格独立。
2. 伪造岛屿抽样或 eligible 集合通过 population 恢复。任务1核对原始凭证、预算可用集与持久化候选血缘。
3. 持久数据或 held-out 内容进入选亲与 prompt。任务2用两份合法留出数据对照及运行中修改拒绝。
4. 最终评分与 baseline 对不同代码/数据/评分协议计分。任务2/3固定同一隔离评分器，先冻结 winner，不依据 held-out 重选。
5. 首次构造失败、最终超时或输出费用未决使 runner 无法保留失败报告。任务3保留 terminal failure、现有费用语义与零调用记录 replay。

### Task 1: 保留有效供亲成员并绑定岛屿抽样

**Files:** m0/core/composition/population_runtime.py、funsearch_coordinator.py；必要时提取窄历史校验辅助模块；m0/tests/test_funsearch_population_runtime.py。
**Interfaces:** 复用 FunSearchPolicy.pending_selection()、FunSearchCoordinator 原始 funsearch_selection 事件、core.funsearch_selection.verify_selection；PopulationFrontier 只拥有有效成员/血缘及 promotion 状态，不负责重新抽岛屿。

- [x] 写 `test_tied_and_worse_valid_programs_remain_eligible_for_island_selection`：公共 Framework 中有效非提升成员应为 done、仍出现在后续 eligible，最终 incumbent 保持 dev 最优；capacity=max(2,max_proposals+1)。当前树分支反例是3个有效候选只有初始 merged，另外2个 pruned。
- [x] 写 `test_population_funsearch_resume_and_replay_verify_original_draw`：新 frontier 当前报 selected parents differ from the final sampling receipt；修复后完成、恢复及 replay 不重发 provider。篡改 receipt ancestry/eligible 或没有原始事件时拒绝。
- [x] 最小增加 FunSearch 抽样授权与恢复接缝：commit 时核对已审计的 pending receipt 与当前预算允许集合；restore 时从原事件重算 draw 和 genealogy，不采用 checkpoint 的自证哈希。允许类似 GEPA 的专用抽样授权分支，不调用仅接受内置 sampler 凭证的 PopulationFrontier.commit_selection；不得跳过等价的原始抽样校验或伪造 tournament 凭证。
- [x] 恢复顺序明确：frontier 校验早于 policy.restore_state，故从冻结配置独立重建 FunSearchPopulation，顺序应用原始 registration/selection/abandonment/reset 并核对全部 before/after；policy restore 后再次比较最终状态，不能读取尚未恢复的 pending_selection 来充当权威。新增 checkpoint RNG/岛屿状态被改但候选证据仍合法、以及自洽重哈希但 eligible 含不可用父代的反例。
- [x] 跑上述文件与现有 FunSearch policy/coordinator/framework、population/GEPA 回归；预期全通过；提交。

### Task 2: 冻结双 split 数据与终评

**Files:** 新增 m0/zoo/funsearch_binpacking/data.py；修改 domain.py；新增 runner.py 配置部分、m0/config/profiles/funsearch_or3.json、m0/tests/test_funsearch_holdout.py；修改 tests/conftest.py Linux清单。
**Interfaces:** `FrozenOR3.from_manifest(path)` 提供 identity、split_hashes、ids(split)、validate() 及只读固定文件；`OR3Domain(data, *, template, timeout)` 提供 dev/final_audit evaluation_contexts；原 OR3DevDomain dev-only 契约保留。`build_profile(data, *, seed, max_proposals, call_token_bound)` 组装已有插件，registry_for(data) 绑定域。

- [x] 先写反例：两份合法 held-out 内容产生不同 final 分数，但搜索 prompt、dev证据、选亲与最终选择一致；公开 final item IDs 不进入 funsearch_public_candidate。
- [x] 测文件/manifest变更、重叠ID、错误hash/count/无效items在付费调用前拒绝；控制读取时再次校验hash，不能校验一份再评分另一份。
- [x] 实现双 split adapter，共用可信 scorer + SandboxedPriority；请求严格限制 unseeded dev 或 final_audit，相应 fidelity 一致。final 只经 metric_final 冻结选择后运行；最终失败不伪造完整分数。
- [x] 测失败/无效/超时程序无供亲资格，成本eval_count保留；final freeze 后恢复不重复已完成评分，replay 禁止 provider 和沙箱调用。
- [x] 运行新增 holdout 与原 OR3 domain/governed tests；实际 Linux执行，全通过；提交。

### Task 3: 可复制 runner、真实运行与交付

**Files:** 完成 runner.py；PROVENANCE.md；m0/tests/test_funsearch_delivery.py；research/experiments/2026-11-05-funsearch-or3/；状态/方法矩阵。
**Interfaces:** CLI `--mode fixture|live --manifest PATH --spending-ledger PATH --seed N --max-proposals N --max-completion-tokens N --timeout SECONDS --output PATH [--resume] [--final-only]`。默认fixture；live复用 GovernedCNYProvider 和 CNYInvocationBridge，不新建费用权威。

- [x] runner 的 fixture 使用真实隔离执行的小数据；测试无Git副本可跑fixture，live要求clean source、原账本、冻结数据和沙箱可用。manifest 在首次调用前保存；resume配置漂移拒绝。
- [x] 独立终评命令 `--resume --final-only` 必须读取已有 metric_final_frozen 并核对 candidate/binding；没有冻结记录立即拒绝，不能补跑搜索。复用 public Framework 的现有 final 恢复路径，仅执行未完成的冻结终评，已完成时返回原报告；测试禁止所有模型请求、禁止重新选择，改变max_proposals/data/source拒绝。
- [x] 独立初始 control 复用M7构造/OR3 dev domain，只有operator需要provider调用，evaluation计0模型token。调用预留取provider声明。主候选池不得混入control。
- [x] 基准 best-fit 使用同一 frozen template/可信 scorer/沙箱，独立报告dev和held_out逐实例bin数，不作为模型发现。主程序先冻结再评held_out；基准结果不反馈生成器。
- [x] loopback验证费用、控制隔离、失败报告、恢复不重复调用；随后离线端到端命令完成并记录replay。完成一次全分支审查和必要修复。
- [x] 提交干净source后，固定16384输出上限、timeout30秒/partition、官方OR3切分，按0/1/2各最多10提案真实运行；原累计campaign。保留全部生成/评分/终评失败，不为挑成功重跑。
- [ ] 导出原始证据、源/配置/数据hash、程序和逐case bin数、控制状态、费用、失败率、所有差异；脚本从冻结记录重算，不需要密钥。执行macOS portable/Linux完整CI并合入main，才推进AIDE。
