# 九模块卡片：OpenEvolve / ShinkaEvolve（基于 dim06 一手调研整理）

## OpenEvolve（algorithmicsuperintelligence/openevolve，原 codelion/openevolve）

**定位**：AlphaEvolve 的开源复现，面向代码进化的生产级异步进化框架。

| 模块 | 实现 |
|---|---|
| M1 Policy | `OpenEvolve` controller：编排循环 + checkpoint/resume + early stopping（patience/convergence_threshold）；选择策略（`_sample_parent`、岛迁移）硬编码在 `ProgramDatabase` 内——**换策略需改源码，是其模块化最大短板** |
| M2 Operator | EVOLVE-BLOCK 块级变异；diff(SEARCH/REPLACE) 与 full rewrite 两种变异表示共存；LLM ensemble 固定权重 |
| M3 Budget | `run(iterations, target_score)`；级联评估 `evaluate_stage1/2/3` + `cascade_thresholds`（相对当前最优 0.5/0.75/0.9，随进化自动收紧）= 进化特有的"便宜测试先淘汰"早停 |
| M4 Frontier | ProgramDatabase = MAP-Elites × 岛屿模型；特征维度可直接拿 evaluator metric 充当（低成本高价值）；异步无"代"边界，DB 为唯一同步点 |
| M5 Memory | **只有实例仓库**（程序+分数+岛屿），无跨代语义抽象层 = L1 only |
| M6 Knowledge | 无外部知识接入 |
| M7 Executor | role=general（同质 LLM ensemble）、hypothesis=free（无冻结假设概念） |
| M8 Evaluator | 带宽档位：**多指标 + artifacts 侧信道**（含安全过滤 + 字节上限）——"低成本拿到大部分反馈收益"的折中；`num_runs` 聚合雏形 |
| M9 Admission | 朴素：MAP-Elites 胞格竞争 + 岛 best 更新；新颖性拒绝（嵌入+LLM judge）；无"假设-验证-定论"研究纪律 |
| X1 溯源 | 全组件 seed（默认 42）+ hash 隔离 + checkpoint 完整 DB 状态——可复现性一等设计 |
| X2 HITL | `manual_mode`（人在回路变异队列）——进化框架中唯一触及者 |

**装不下的机制**：级联评估阈值"相对当前最优自动收紧"这一早停语义，我们的 M3 预算模型可以容纳，但值得作为 M3 的一等配置显式建模。
**启发**：① EVOLVE-BLOCK 标记法是把存量代码库纳入进化的最低侵入方案；② 选择策略应是可注入对象而非配置枚举；③ 无 checkpoint 的进化框架无法用于生产。

## ShinkaEvolve（SakanaAI/ShinkaEvolve，ICLR 2026）

**定位**：SakanaAI 出品的下一代代码进化框架，样本效率与工程解耦程度均超 OpenEvolve。

| 模块 | 实现 |
|---|---|
| M1 Policy | `ShinkaEvolveRunner(evo_config, job_config, db_config, max_evaluation_jobs=2, max_proposal_jobs=3, max_db_workers=4)`——**proposal/eval/db 三条独立配额的异步流水线**（生产者-消费者彻底解耦） |
| M2 Operator | `patch_types` 配置化（diff/full/...）+ `patch_type_probs=[0.6,0.3,0.1]` 概率混合；**meta 层**：`SystemPromptEvolver` + `MetaSummarizer`（提示词自身的进化 = 二阶优化，独立 archive + 独立 bandit） |
| M3 Budget | proposal/eval 各自配额 + oversubscription 可调；Hydra preset `evolution=small_budget` |
| M4 Frontier | 岛屿模型 + 新颖性拒绝；`db.num_islands` 等 Hydra/CLI 双轨配置 |
| M5 Memory | 实例仓库（L1）+ **MetaSummarizer 周期性生成 meta-recommendations（L2 雏形）**——进化系中最接近语义记忆者 |
| M6 Knowledge | 无 |
| M7 Executor | role=general、hypothesis=free；**LLM 选择 = 可插拔 cost-aware UCB bandit**：`BanditBase(ABC)` 暴露 `select_llm/update/update_cost/posterior/get_state/set_state`，状态可持久化 |
| M8 Evaluator | 带宽档位：**+text_feedback 档**。评估契约是框架级约定：`{"combined_score": float, "public": {...}(对LLM可见), "private": {...}(不可见), "extra_data": {...}(存pkl), "text_feedback": str}`——**public/private 划分把"评估器→变异器"反馈通道一等公民化**；`run_shinka_eval` 提供多次运行聚合 + validate_fn 脚手架 |
| M9 Admission | 岛 best 更新 + 新颖性拒绝；无研究纪律式准入 |
| X1 溯源 | SQLite 持久化 + W&B 集成 |
| X2 HITL | 无 |

**装不下的机制**：① **meta 层（提示词进化）**——在我们抽象中它落在 M2 内部还是 M1？它是"对 operator 的 operator"，我们的模块化应明确支持"operator 自身作为可进化对象"（配置项而非新模块）；② LLM bandit 选择（M1/M7 交叉处）——我们 SPEC 中需确认其归属（建议：M7 ExecutorSpec 的 llm_policy 字段，策略对象注入）。
**启发**：① public/private/text_feedback 评估返回契约应成为我们 EvalResult 的分层标准（我们已有 text_feedback/artifacts_ref，**建议补 public/private 可见性划分**）；② BanditBase 证明选择策略须是有状态、可持久化的注入对象；③ task-dir 约定（evaluate.py + initial.<ext> 两文件）与我们 ZOO.md 的 TaskAdapter 契约高度同构。
