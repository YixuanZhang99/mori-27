# 经典工作接入：当前路线与文档导航

日期：2026-11-05。状态：**用户已批准执行，逐项验收；不是全部实现完成声明**。
规划时源码核对基线：`18400ad5e6b671beb82b19763c5b4ea52793519e`；已执行的分支收敛见第 6 节。
用户已批准分支收敛及从 GEPA 起逐项施工；当前执行目标及应用 Goal 状态见 [CURRENT_GOAL](CURRENT_GOAL.md)。

## 1. 本轮结论

以九模块承载经典方法，以一个方法的完整运行闭环作为交付单位。
不先把九模块各自所有设计轴实现完，也不重写已经工作的运行时。
建议顺序：**GEPA → FunSearch → AIDE → Arbor → OpenEvolve → AIRA → LoongFlow → R&D-Agent**。
前两项来自较新的 ADR-0/RUBRIC，并已有组件；AIDE/Arbor 来自早期复刻规格；后四项补足原统一抽象的主要组合。
此顺序已获用户批准；每个方法仍须冻结自己的 spec，不能承诺全部论文成绩。

每次只推进一个方法：冻结 spec → 补最小差距 → 公共入口验收 → 真实小试跑 → 合入 → 下一项。
长时实验可以与已冻结方法的下一项 spec 阅读并行；不同时修改多个方法的共享运行时。
外部数据或硬件确实不可用时，将该项标为“机制接通、实测等待”，记录原因后推进下一项；不无限扩建基础设施。

## 2. 文档梳理：哪些决定现在的开发

| 文档 | 实际角色 | 本次处理 |
| --- | --- | --- |
| [VISION](../autoresearch-fw/VISION.md)、[RUBRIC](../autoresearch-fw/RUBRIC.md) | 项目定位、完整发布验收 | 保留；接入一个方法不等于全部 A/B/C 达标 |
| [初版范围 v2 / ADR-0](../autoresearch-fw/初版范围-v2.md) | 明确取代 v1：六概念内核、GEPA 首发、机制按需装回 | 用于解释首发次序；UNIFIED 不是全部待办 |
| [统一抽象](AutoResearch模块化统一抽象.md) §4–6 | 九模块职责、经典系统组合 | 本轮模块与方法映射依据 |
| [SPEC](../autoresearch-fw/SPEC.md) | v0.1 接口底稿 | 与现行接口有差异；不直接照旧签名另建一套框架 |
| [M1/M2/M3/M4/M5/M6/M8M9-UNIFIED](../autoresearch-fw/README.md) | 模块设计银行及 profile | 按当前方法需要取用；区分完整方法、局部机制、反例 |
| [REPLICATION](../autoresearch-fw/REPLICATION.md) | AIDE/Arbor/OpenEvolve 机制与复刻边界 | 继承机制要求；历史榜单数字须重新锁定来源后才作验收锚点 |
| [ZOO](../autoresearch-fw/ZOO.md) | 任务、数据、评分接入契约 | 方法 recipe 与 benchmark adapter 分开 |
| [CODE-BORROWING](../autoresearch-fw/CODE-BORROWING.md)、[REFERENCES](../autoresearch-fw/REFERENCES.md) | 文件级借鉴清单 | 实现前读取对应来源，不重做全领域调研；其中“已复刻”须由当前证据复核 |
| [ABSTRACTION_ALIGNMENT](ABSTRACTION_ALIGNMENT.md) | S1–S9 条款、阶段历史和合入门槛 | 保留稳定条款 ID 和历史证据，不把基线表当最新完成状态 |
| [新增工作映射](新增工作九模块映射表.md) | 15 项设计压力测试 | “能映射”不等于“已接通”；登记于扩展目录 |
| [早期开发计划](AutoResearch框架开发计划.md)、`plans/` | 早期先 AIDE/Arbor 的路线与研究计划 | 保留历史，不与 ADR-0 的首发路线同时执行 |
| 旧 [实证交付计划](superpowers/plans/2026-11-04-evidence-delivery.md) | 三份实证交付的执行历史 | 已有成果保留；本轮后续排期以本页评审结果为准 |

发现的具体矛盾：旧 SPEC 允许 LLM policy，ADR-0 禁止 M1 同步路径网络；旧 SPEC 强调六类型，现行 composition 有显式 Proposal/OperatorRequest；旧复刻目标允许 val-best，治理默认准入又可能改变供亲资格。解决方式是**在方法 spec 明示配置、边界和差异**，不靠同时“满足”不相容文字来不断加层。
本页不改写 VISION/RUBRIC 或原始材料。涉及硬不变量冲突时，先写一个针对该方法的决策，不用新名称冒充忠实复现。

## 3. 九模块的接入责任

下表是现有代码落点，不要求物理目录立即改名。M7 对应 executor；M8/M9 在 executor/eval/composition 中分布，逻辑职责仍独立。

| 模块 | 必须回答 | 已有主要落点（仓库根相对路径） | 新方法允许的最小变化 |
| --- | --- | --- | --- |
| policy | 何时 draft/debug/improve，选谁、何时停 | `m0/core/policy/`、`m0/core/composition/strategies.py`、`gepa_policy.py`、`funsearch_policy.py` | 方法策略插件；不直接扣账或自判最终准入 |
| operator | 父代与何种反馈如何形成提案 | `m0/core/operator/`、`m0/core/composition/construction_recipes.py` | 配方、patcher 或算子插件 |
| budget | 生成、评估、反思各消耗多少 | `m0/core/budget/`、`m0/core/composition/budget*.py` | 复用既有 reserve/settle；方法参数与计量接线 |
| frontier | 历史、供亲、最终交付分别有哪些候选 | `m0/core/frontier/`、`m0/core/funsearch_population.py` | 方法所需选择与保留语义；不把三种资格混为一谈 |
| memory | 哪些过去证据进入下一步 | `m0/core/memory/`、`m0/core/composition/context.py` | 有作用域的反思集、树摘要或 insight |
| knowledge | 是否需要外部资料 | `m0/core/knowledge/`、`m0/core/composition/knowledge.py` | 首批 benchmark 关闭；research 单列扩展 |
| execution | 如何构造、运行、修复候选 | `m0/core/executor/`、`m0/core/composition/construction.py`、`configured_execution.py` | 复用 M7 provider/构造/沙箱，不另建 paid runner |
| evaluation | 数据、反馈、分数与最终留出 | `m0/core/composition/evaluation.py`、`m0/zoo/` | 任务适配器；参考数据与评分固定 |
| admission | 方法接纳与最终交付如何裁决 | `m0/core/eval/`、`m0/core/composition/admission.py` | 显式方法规则；治理改变规则时标注 adapted |

共享接入规则见 [COMMON](specs/classic/COMMON.md)。**不用每个方法重写九个模块；只实现矩阵里与已有行为不同的格子。**

## 4. 一项一项交付

| 顺序 | 工作 spec | 当前确认证据 | 必须补的闭环 |
| --- | --- | --- | --- |
| 1 | [GEPA](specs/classic/GEPA.md) | 同批父子反思、validation 实例赢家、冻结 test、计量回放已接通；[真实 GSM8K 记录](../research/experiments/2026-11-05-gepa-gsm8k/README.md)单列成功与失败 | 更充分的多提案搜索、等预算对照与公开区间复现 |
| 2 | [FunSearch](specs/classic/FUNSEARCH.md) | [三 seed 实测](../research/experiments/2026-11-05-funsearch-or3/README.md)完成，31/33 有效，held-out 均210.1箱；选亲/重置/计量回放接通 | 最终候选 CI 与合入；尚无留出收益或论文复现结论 |
| 3 | [AIDE](specs/classic/AIDE.md) | 通用树/算子/MLE 任务组件；未找到完整命名 recipe 的验收包 | draft 扇出、buggy debug 路由、best-first、validation best |
| 4 | [Arbor](specs/classic/ARBOR.md) | llm_cycles、假设/上下文、记忆、layered gate 组件 | 六步循环、insight 上溯与实际消费、gate 接纳/拒绝轨迹 |
| 5 | [OpenEvolve](specs/classic/OPENEVOLVE.md) | vendored 宿主、数据库往返、grid/island/cascade 组件 | 同一运行中的 diff→grid×island→cascade→选择；与宿主对照 |
| 6 | [AIRA](specs/classic/AIRA.md) | 算子、策略和作用域组件 | 独立终选、可换 operator set/π_op/memory 的受控配置 |
| 7 | [LoongFlow](specs/classic/LOONGFLOW.md) | 种群、lineage、参考源码材料 | Plan→Execute→Summarize 真正串联，温度供亲；并发单列 |
| 8 | [R&D-Agent](specs/classic/RD_AGENT.md) | DAG/引用边、角色、记忆组件 | Researcher/Developer、Trace DAG、调度/merge 闭环 |

“组件已有”只表示可复用线索，不表示组件已被上述方法完整消费。后面三份是范围规格，实施前需锁定对应上游和运行任务，不虚构已确定的源码接口。
其它原文系统及模块 profile 全部登记在 [扩展目录](specs/classic/EXTENSIONS.md)，明确哪些是后续整方法、模块能力、benchmark 或禁止取值。

## 5. 统一完成标准：不再用测试数量作进度

每个方法分别记录四个状态：

1. **规格冻结**：来源版本、九模块配置、算法决策、允许差异、首个任务和验收例子齐全。
2. **机制接通**：从 `Framework.from_profile` 经 `evolve/inspect/replay` 完成真实数据流；脚本模型仅证明机制。
3. **小规模实测**：真实模型 + 固定数据，报告所有预先声明 seed，包括失败，保存逐项成绩和实际成本。>=3 seeds 才报告均值与标准差；单 seed 只叫 smoke。
4. **公开区间复现**：匹配参考任务/模型/预算或解释偏差，独立达到公开区间；不能由第 3 步自动升级。

首批验收目标是 GEPA/FunSearch 达到 2、3，其他按序闭环；完整 v1.0 仍须原 RUBRIC。真实预算继续沿用用户授权的累计 ¥200，共享账本不重置。真实调用继续记入同一原始账本；不另开预算。
对照必须与方法共用相同总资源口径，报告治理占用，不能给主方法和 control 各算一份“同预算”。

## 6. 分支决定与已执行结果

稳定入口统一为 **main**。2026-11-05，[PR #4](https://github.com/YixuanZhang99/mori-27/pull/4) 已用 merge commit `9648aa3` 整合既有开发链，保留原提交历史；候选两轮检查及 [合并后 main 检查](https://github.com/YixuanZhang99/mori-27/actions/runs/41964500311) 的 macOS、Linux v75、MLE jobs 全部通过。

- PR #1 随完整提交链进入 main 后被 GitHub 标为 merged；被取代的 PR #2、#3 已关闭。
- 15 条已被 main 包含的历史开发分支已按精确 SHA 核对后清理；历史 `pr-4-merge` 引用也不再出现在远端。
- GEPA [PR #5](https://github.com/YixuanZhang99/mori-27/pull/5) 已在两组最终候选检查通过后合入 `main=b16b4c6`，合并树与 `5fed770` 相同；方法分支退役，回滚 tag 为 `archive/classic-gepa-20261105`。下一条唯一发布方法分支为 `codex/classic-funsearch`，本地在 CI 期间准备的提交须先衔接新 main。
- 回滚标签 `archive/pre-classic-main-20261105`、`archive/pre-classic-development-20261105` 与已验证本地 bundle 保留。保留有未提交文件的本地工作区，不用远端分支清理覆盖用户文件。
- 未推的 `/tmp/mori27-classic-integrate@4df353f` FunSearch WIP 保留备份。已核对其额外 supervisor、价格门禁等不属 C02 最小缺口，不能整包导入。

以后固定为：一个方法 spec → 一个短期分支/PR → 公共入口与真实结果 → 检查通过合入 → 下一项。最多 main 加一条活跃方法分支，不再叠串联 PR。

## 7. 执行节奏

第一批时间盒（估计，不是完成承诺）：分支/入口收敛 1 个检查周期；GEPA 的最小缺口施工先给 2 小时。到时交付可运行增量或明确的失败验收条款，不以“还需更多审计”延长未知范围。
后续只按方法关闭情况排期；不承诺两小时完成所有系统与论文 benchmark。

每项只产生：一份 spec、一份配置/入口、一组关键行为测试、一份结果报告。
必要的共享接口变更随第一个使用它的方法提交；第二个方法验收时必须只换配置/插件，验证可复用性。
不新造逐版本 verifier 链、不为每个小修复新增长计划、不重复付费跑同一已冻结候选。
外部仓库回顾放在方法开始/完成时，引用其对应文件与决策；不再把全量调研变成每次开发的前置。

详细执行拆分见 [首批实施计划](superpowers/plans/2026-11-05-classic-spec-delivery.md)。
