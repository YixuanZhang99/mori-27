# 维度06：FunSearch / AlphaEvolve 谱系与开源进化式程序搜索框架 —— 机制深读与模块化工程分析

> 调研单元：进化式程序搜索（Evolutionary Program Search）的工程架构
> 一手来源：FunSearch 官方仓库实现代码、AlphaEvolve 白皮书（arXiv:2506.13131）全文、OpenEvolve / ShinkaEvolve / GEPA 仓库 README + 目录结构 + 核心类源码、GEPA 论文（arXiv:2507.19457）、DEEVO 论文（arXiv:2506.00178）、DSPy GEPA 官方文档。共 14+ 次独立检索/阅读。

---

## 1. 各系统核心机制（伪代码级）

### 1.1 FunSearch（Romera-Paredes et al., Nature 2023/2024）

**问题设定**：用户提供一个 *specification* 文件，其中用装饰器标记两类函数——`@funsearch.evolve`（待进化的函数，如 `priority()`）和 `@funsearch.run`（评估入口）。LLM 只进化单个函数的**函数体**，骨架（skeleton）与评估逻辑冻结[^1^][^3^]。

**架构**：三角色异步流水线（论文部署规模：15 samplers + 140 evaluators）[^3^]：

```
ProgramsDatabase.get_prompt()          # 随机选一个岛
  -> Island.get_prompt():
       clusters = {signature: Cluster} # signature = tuple(sorted(scores_per_test))，即按逐测试得分向量聚类
       p(cluster) = softmax(cluster_score / T)，T 随已注册程序数线性退火 (T0=0.1, period=30000)
       按 p 抽 k≤functions_per_prompt(=2) 个 cluster，每个 cluster 内均匀抽 1 个实现
       按得分升序排列，重命名为 f_v0, f_v1...，拼成 prompt，末尾留出 f_v{k} 的函数头
Sampler: while True:                    # 15 个并行
  prompt = db.get_prompt()
  samples = LLM.draw_samples(prompt.code)   # 每 prompt 采 4 个 continuation (samples_per_prompt=4)
  for s in samples: random.choice(evaluators).analyse(s, prompt.island_id, version_generated)
Evaluator.analyse(sample, island_id, version_generated):
  body = _trim_function_body(sample)        # AST 截断：从尾部删行直到 ast.parse 成功 —— 对幻觉输出鲁棒
  body = rename(f_v{k} -> f)                # 禁止调用祖先版本 f_v*（防作弊/循环）
  for input in inputs:
      out, ok = sandbox.run(program, run_fn, input, timeout=30s)
      if ok and not calls_ancestor and out is not None: scores_per_test[input] = score(out)
  db.register_program(new_fn, island_id, scores_per_test)
```

**Islands + 周期性重置**（防早熟收敛的核心机制）：`reset_period=4h` 到点时，按各岛 best score 排序，**重置最差的一半岛**，每岛用从存活岛随机选的 founder（该岛 best program）重新播种[^2^]。

**关键配置**（`ProgramsDatabaseConfig`）[^3^]：`functions_per_prompt=2, num_islands=10, reset_period=4*60*60, cluster_sampling_temperature_init=0.1, cluster_sampling_temperature_period=30000`；全局 `num_samplers=15, num_evaluators=140, samples_per_prompt=4`。

**Evaluator 契约**：极度简单——`Sandbox.run(program, function_to_run, test_input, timeout) -> (output, runs_ok)`，得分即 `function_to_run(test_input)` 的返回值。官方开源实现明确**不包含** LLM、sandbox、分布式基建，三者都是留给使用者的 extension point[^1^]。

**要点**：FunSearch 的 "database 即进化算法"——选择压力完全编码在 cluster-softmax + 岛重置里；prompt 是"按分数升序的版本化函数序列"（best-shot prompting），没有任何自然语言指令。

### 1.2 AlphaEvolve（Novikov et al., 2025, DeepMind 白皮书）

在 FunSearch 骨架上做了六项工程升级[^4^]：

1. **进化对象**：从单函数体扩展到**跨文件多个代码块**。用户在代码里用 `# EVOLVE-BLOCK-START/END` 注释标记可变区，其余为骨架；`evaluate(eval_inputs) -> dict[str, float]` 是固定的评估入口签名。可进化：(a) 解的原始表示；(b) 构造解的函数（FunSearch 式）；(c) 搜索算法本身；(d) 解+搜索算法协同进化。
2. **Diff-based mutation**：LLM 输出 `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` 块序列做定向修改；短代码或需要重写时可配置为整段输出。
3. **LLM ensemble**：Gemini 2.0 Flash（低延迟、走量）+ Gemini 2.0 Pro（低频、提供突破性建议），在吞吐量与质量间权衡。
4. **Prompt sampling 升级**：prompt = 数据库中抽样的历史程序 + 系统指令 + 可选的 (a) 显式上下文（方程、文献 PDF）；(b) **随机化模板格式**（占位符按配置概率分布实例化，增加多样性）；(c) 渲染的评估结果（程序+执行输出+分数）；(d) **meta prompt evolution**——提示词本身由 LLM 生成、在独立数据库中协同进化。
5. **Evaluation cascade**（假设检验式级联）：测试用例按难度分级，只有前级达标才进入后级；小规模冒烟先行，早淘汰坏程序；支持 **LLM-generated feedback**（对难以写进 h 的性质如"简洁性"用额外 LLM 打分并入 metrics 或直接丢弃）；支持并行评估（单个候选可花 ~100 计算小时，评估可 embarrassment-parallel 地分发到评估集群）。支持**多目标分数**，且发现即使只关心单指标，多指标进化反而更好（不同指标下的优解结构多样，注入 prompt 后刺激多样性）。
6. **Database = MAP-Elites × island 模型的组合**；整体为 **asyncio 异步流水线**（controller + LLM samplers + evaluation nodes），全局为吞吐量（而非单任务延迟）优化[^4^]。

**代表性方法创新（数学问题）**：不直接进化构造，而是进化**带固定时间预算（如 1000s）的启发式搜索程序**，并把上一代最优构造作为起点传给新程序——进化出"早期大幅改进型 + 后期精细调优型"的多阶段专用启发式序列。4×4 复矩阵乘法 48 次标量乘法（56 年来首次超越 Strassen）即由此得到[^4^]。

### 1.3 GEPA（Agrawal et al., arXiv:2507.19457，ICLR 2026 Oral）

反思式进化（reflective evolution）的代表：优化对象是**任意文本组件的 dict**（`Candidate = dict[component_name -> text]`，可以是多模块 pipeline 里每个模块的 prompt，也可以是代码/配置）。核心主张：自然语言 trace 比 scalar reward 是更富的学习介质[^12^][^13^]。

**算法**（论文 Algorithm + DSPy 文档交叉确认）[^12^][^14^]：

```
pool = {seed_candidate}; 对 seed 在 valset 全量评估，记录逐实例分数
loop until max_metric_calls:
  1. candidate = sample(Pareto_frontier)      # frontier = 在至少一个验证实例上取得最优的候选集合
                                              # 按实例覆盖数比例随机采样（非贪心取最优）
  2. minibatch = sample(trainset, size=3)     # reflection_minibatch_size 默认 3
  3. out = adapter.evaluate(batch, candidate, capture_traces=True)
     # 返回 EvaluationBatch(outputs, scores, trajectories)——trace 含推理、工具调用、报错
  4. module = module_selector(candidate)      # round_robin / all / 自定义 ReflectionComponentSelector
  5. refl_ds = adapter.make_reflective_dataset(candidate, out, [module])
     # 把 trace 转成该组件的 JSON 反思数据集（输入、输出、失败原因、文本反馈）
  6. new_texts = propose(candidate, refl_ds, [module])   # reflection_lm 读反思数据集写新 prompt
  7. 新候选先在 minibatch 上评估；sum(scores) 不降才接受（minibatch acceptance test）
  8. 接受后在 valset 全量评估，更新逐实例分数矩阵与 Pareto frontier
  9. [可选] merge proposer：合并两条 lineage 上各自最强的模块（system-aware crossover），
     要求父代在 val 上有 ≥merge_val_overlap_floor=5 个共同已评实例
return 聚合验证分最高的候选
```

**结果**：6 任务上平均超 GRPO ~6%（最高 +20%），rollout 少至 35×；超 MIPROv2 >10%（AIME 2025 +12%）；Pareto 选择策略消融 +6.4%；反思成本仅占总优化成本 5–10% 但**反思模型必须是前沿 LLM**[^12^]。

### 1.4 DEEVO（Amazon，arXiv:2506.00178）

无 ground-truth、无手工 fitness 的 prompt 进化：**多智能体辩论（MAD）作为成对评估器 + 改良 Elo 作为选择压力**[^15^]：

```
for gen in 1..G:
  随机配对 (p_a, p_b)                    # 并行
  对每对: 抽任务 t，分别生成响应 r_a, r_b
    d 轮结构化辩论判定胜者 -> 更新 Elo（新生候选初始 1000）
    Crossover agent 读辩论 trace，智能融合两 prompt 的优点（而非任意拼接）
    以概率 m 做 task-driven 定向 Mutation
  全群体"老化"；按 newcomer 配额 n_new + veteran Elo 配额选下一代  # 解决 Elo 对新/老选手的校准问题
return Elo 最高 prompt
```

意义：把 evaluator 契约从"标量函数"推广到"相对评判 + 文本判词"，适合主观质量任务；辩论 trace 同时充当变异算子的"反思材料"（与 GEPA 的 reflective dataset 同构）。

---

## 2. 开源框架的模块化工程分析（重点）

### 2.1 OpenEvolve（codelion/openevolve → algorithmicsuperintelligence/openevolve）

AlphaEvolve 的开源复现，五组件控制器编排架构[^5^][^6^][^7^]：

```
openevolve/
├── controller.py        # class OpenEvolve: 编排、checkpoint/resume、early stopping、信号处理
├── database.py          # class Program + class ProgramDatabase: MAP-Elites + 岛屿 + 迁移
├── evaluator.py         # class Evaluator: 级联评估、重试、artifacts、LLM feedback
├── iteration.py         # run_iteration_with_shared_db(): 单次迭代的 worker 逻辑
├── process_parallel.py  # class ProcessParallelController: 进程池、DB 快照、批量提交
├── config.py            # LLMModelConfig/LLMConfig/PromptConfig/DatabaseConfig/EvaluatorConfig/Config
├── prompt/sampler.py    # class PromptSampler: 模板渲染、历史/灵感/artifact 组装
├── llm/ensemble.py      # class LLMEnsemble: 加权采样模型、fallback
├── llm/base.py          # LLMInterface（provider 抽象）
├── embedding.py / novelty_judge.py   # 嵌入相似度 + LLM 新颖性裁判
└── evaluation_result.py # EvaluationResult(metrics + artifacts 侧信道)
```

**核心抽象与契约**[^8^][^9^]：

| 组件 | 类/接口 | 关键方法与契约 |
|---|---|---|
| 个体 | `Program` (dataclass) | `id, code, language, metrics: Dict[str,float], parent_id, generation, island_id, artifacts, iteration_found`；`to_dict/from_dict` 序列化 |
| 变异器 | `LLMInterface` / `LLMEnsemble` | `generate_with_context(prompt, ...)`；ensemble 按 `weight` 加权采样模型，失败自动 fallback；provider 支持 openai 兼容 API / claude_code CLI / `init_client` 自定义回调 |
| 提示构造 | `PromptSampler` | `build_prompt(parent, inspirations, artifacts, ...) -> {system, user}`；模板目录可替换，`use_template_stochasticity` 随机化措辞，`num_top_programs/num_diverse_programs` 控制证据集 |
| 评估器 | `Evaluator` | 用户**单文件契约**：`evaluate(program_path) -> dict[str, float] | EvaluationResult`；级联契约：可选定义 `evaluate_stage1/2/3(program_path)`，逐级过 `cascade_thresholds=[0.5,0.75,0.9]`（相对岛最优的阈值）；`use_llm_feedback` 时用第二个 LLM ensemble 打分并入 metrics（权重 `llm_feedback_weight=0.1`）；超时/重试/临时文件隔离；artifacts（stderr、traceback、文件）作为**侧信道**存入 DB，供下一轮 prompt 渲染（带安全过滤 `artifact_security_filter`） |
| 数据库 | `ProgramDatabase` | `add(program)` / `sample(num_inspirations) -> (parent, inspirations)` / `get_best_program(metric)`；MAP-Elites：`feature_dimensions`（内置 complexity/diversity/score + 任意 evaluator metric，**必须返回原始连续值，binning 由框架内部做**）× `feature_bins`；岛屿：`num_islands=5`、`migration_interval=50`（按岛 generation 计数，lazy migration）、`migration_rate=0.1`、环形迁移拓扑；父母采样三路混合：exploitation 0.7 / exploration 0.2 / random；**double selection**——展示给 LLM 的 parent 与 inspirations 分别采样；嵌入 + LLM judge 双重新颖性检查（`similarity_threshold=0.99`）；`_enforce_population_limit` 人口上限淘汰 |
| 控制器 | `OpenEvolve` | `__init__(initial_program, evaluation_file, config, output_dir)` → `run(iterations, target_score)`；初始化顺序 Config→LLMEnsemble→PromptSampler→ProgramDatabase→Evaluator→ProcessParallelController；`_save_checkpoint/_load_checkpoint`（完整 DB 状态 + best program + 岛状态）；early stopping（patience/convergence_threshold/metric）；SIGINT 优雅停机 |
| 并行 | `ProcessParallelController` | 每次迭代 = 独立进程 + **数据库快照**（`_create_database_snapshot`），worker 内 `sample→build_prompt→generate→evaluate→add`，结果批量回传合并；`max_tasks_per_child` 防内存泄漏 |

**配置长什么样**（`configs/default_config.yaml`，全部 YAML + `${ENV_VAR}` 环境变量插值）[^8^]：
- 顶层：`max_iterations, checkpoint_interval, random_seed=42, diff_based_evolution, max_code_length, diff_pattern(可改 regex!), early_stopping_*`
- `llm:`：`models: [{name, weight}], evaluator_models: [...], api_base, api_key, temperature, max_tokens, timeout, retries, reasoning_effort, manual_mode(人在回路)`
- `prompt:`：`template_dir, system_message, num_top_programs=3, num_diverse_programs=2, use_template_stochasticity, template_variations{...}, include_artifacts, max_artifact_bytes`
- `database:`：`population_size=1000, archive_size=100, num_islands=5, migration_interval/rate, elite_selection_ratio=0.1, exploration_ratio=0.2, exploitation_ratio=0.7, feature_dimensions, feature_bins`
- `evaluator:`：`timeout=300, max_retries=3, cascade_evaluation=true, cascade_thresholds, parallel_evaluations, use_llm_feedback, enable_artifacts`

**新增一个策略要实现什么**：
- **新任务**：只需 3 个文件——`initial_program.py`（含 EVOLVE-BLOCK 标记）、`evaluator.py`（实现 `evaluate(path)->dict`）、`config.yaml`。这是最低接入成本。
- **新 LLM provider**：实现 `LLMInterface`（或传 `init_client` 回调），注册进 ensemble。
- **新特征维度**：不改框架代码——evaluator 多返回一个 metric，在 `feature_dimensions` 里列名即可。
- **新 prompt 策略**：替换 `prompt.template_dir` 下模板文件，或子类化 `PromptSampler`。
- **新选择/迁移策略**：目前**需要改 `ProgramDatabase` 源码**（`_sample_parent`、`_sample_inspirations`、`migrate_programs` 非注册式插件）——这是 OpenEvolve 模块化最明显的短板。
- **级联评估**：在 evaluator 文件里加 `evaluate_stage1/2/3`，无需改框架。
- 也支持纯库用法：`run_evolution(initial_program=..., evaluator=lambda path: {...}, iterations=...)`，零文件接入[^5^]。

### 2.2 ShinkaEvolve（SakanaAI/ShinkaEvolve，ICLR 2026）

定位：样本效率优先的 AlphaEvolve 复现（circle packing 仅用 150 样本达 SOTA）。三大算法创新：**自适应父母采样（explore/exploit 平衡）、代码新颖性拒绝采样、bandit-based LLM ensemble 选择**[^10^]。

```
shinka/
├── core/
│   ├── config.py          # EvolutionConfig（dataclass）
│   ├── async_runner.py    # ShinkaEvolveRunner（统一入口，替代旧 EvolutionRunner/AsyncEvolutionRunner）
│   ├── sampler.py         # PromptSampler: patch 类型采样 + meta 推荐注入 + 灵感上下文
│   ├── novelty_judge.py / async_novelty_judge.py   # 嵌入 + LLM 新颖性裁判
│   ├── summarizer.py / async_summarizer.py         # MetaSummarizer：周期性元推荐（meta-recommendations）
│   ├── prompt_evolver.py  # SystemPromptEvolver：系统提示词本身的协同进化（prompt archive + UCB）
│   └── wrap_eval.py       # run_shinka_eval：用户评估脚手架（多次运行聚合、validate_fn）
├── database/
│   ├── dbase.py           # ProgramDatabase（SQLite 持久化！）+ DatabaseConfig
│   ├── islands.py / island_sampler.py   # 岛屿逻辑；island_selection_strategy: uniform/equal/proportional/weighted
│   ├── parents.py         # 父母选择策略: weighted / power_law / beam_search
│   ├── inspirations.py    # 灵感程序选择: elite/top-k/archive + crowding
│   ├── prompt_dbase.py    # prompt 进化的独立 archive
│   └── complexity.py
├── edit/                  # apply_diff.py / apply_full.py / async_apply.py / marker_validation.py（EVOLVE-BLOCK 校验）
├── llm/                   # LLMClient/AsyncLLMClient + prioritization.py: BanditBase(ABC) + UCB 等
├── launch/                # local.py / slurm.py / scheduler.py  → LocalJobConfig/SlurmCondaJobConfig/SlurmDockerJobConfig
├── configs/               # Hydra presets（task=/database=/evolution=/cluster= 组）
└── webui/                 # 实时可视化（谱系树、指标）
```

**核心契约**[^10^][^11^]：
- **Runner 组装式注入**：`ShinkaEvolveRunner(evo_config, job_config, db_config, max_evaluation_jobs=2, max_proposal_jobs=3, max_db_workers=4)`——proposal 生成与 evaluation 是两条**独立配额的异步流水线**（oversubscription 可调），DB 用独立 worker 写。这与 OpenEvolve 的"每迭代一进程"不同，是更彻底的生产者-消费者解耦。
- **评估契约**：用户提供 `evaluate.py`（CLI 入口，`main(program_path, results_dir)`），内部可复用 `run_shinka_eval(program_path, results_dir, experiment_fn_name, num_runs, aggregate_metrics_fn, validate_fn)`；**返回结构是框架级约定**：`{"combined_score": float, "public": {...}(对 LLM 可见), "private": {...}(不可见), "extra_data": {...}(存 pkl), "text_feedback": str}`——`public/private` 划分和 `text_feedback` 是把"评估器→变异器"反馈通道一等公民化的优秀设计。
- **变异算子即配置**：`patch_types=["diff","full","cross"], patch_type_probs=[0.6,0.3,0.1]`（diff/full/crossover 三种 patch 类型按概率采样；无灵感程序时自动屏蔽 cross 并归一化）；`max_patch_resamples/attempts` 控制非法 patch 重采。
- **LLM 选择是可插拔 bandit**：`llm_dynamic_selection: Union[str, BanditBase]`，`BanditBase(ABC)` 暴露 `select_llm / update / update_cost / posterior / get_state / set_state`，cost-aware UCB 默认——**选择策略本身成为可注入对象**（OpenEvolve 只是权重）。
- **meta 层**：`MetaSummarizer` 每 `meta_rec_interval=10` 代总结进化历史产出 meta-recommendations 注入系统提示；`SystemPromptEvolver` 把系统提示词放进独立 archive 用 UCB/ε-greedy 协同进化（对应 AlphaEvolve 的 meta prompt evolution）。
- **岛屿**：`num_islands=2`，`migration_interval=10`，`island_elitism`，`enforce_island_separation`，**stagnation 触发的动态岛屿繁殖**（`enable_dynamic_islands, stagnation_threshold=100, island_spawn_strategy: initial/best/archive_random`）。
- **新颖性拒绝采样**：嵌入相似度 `code_embed_sim_threshold=0.99` + 可选 LLM judge，`max_novelty_attempts=3`。
- **配置体系双轨**：Hydra YAML presets（`shinka_launch task=circle_packing database=island_large evolution=small_budget`）+ 无 Hydra 的 agent CLI（`shinka_run --task-dir ... --set db.num_islands=2`）；task-dir 约定 = `evaluate.py` + `initial.<ext>` 两个文件。

**新增策略成本**：换选择策略 = 实现 `BanditBase` 或改 `parent_selection_strategy` 配置值；换 patch 算子 = 改 `patch_types` 配置 + 对应 `edit/` 应用器；换评估后端 = 换 `job_config`（local/Slurm/Docker 三实现）。模块化程度**高于 OpenEvolve**（策略注入点更多），代价是概念更多（proposal/eval/db 三池、bandit、meta 层）。

### 2.3 GEPA（gepa-ai/gepa）

GEPA 把"适配用户系统"收敛为**单一 Protocol**——这是全部四个框架中最干净的扩展面设计[^13^]：

```python
class GEPAAdapter(Protocol[DataInst, Trajectory, RolloutOutput]):
    def evaluate(batch, candidate: dict[str,str], capture_traces=False) -> EvaluationBatch
        # EvaluationBatch = (outputs, scores, trajectories?, objective_scores?)
        # 契约细节：单例失败不得抛异常——返回 score=0 + 把错误写进 trajectory（失败即反思材料）
    def make_reflective_dataset(candidate, eval_batch, components_to_update) -> Mapping[str, Sequence[Mapping]]
        # 把 trace 转成喂给 reflection LM 的 JSON 数据集
    # 可选：propose_new_texts(...)（自定义 ProposalFn 替代默认指令提案器）
    # 可选：get_adapter_state/set_adapter_state（checkpoint 恢复，鸭子类型探测）
```

**引擎对策略的全面依赖注入**（`gepa.optimize(...)` 的参数表即扩展点清单）[^13^][^14^]：
- `candidate_selection_strategy: CandidateSelector`（默认 `"pareto"`，per-instance Pareto frontier，按覆盖数随机采样；可 `"current_best"`）
- `batch_sampler: BatchSampler | "epoch_shuffled"`；`module_selector: ReflectionComponentSelector`（`"round_robin"/"all"`/自定义，可用 LLM 按状态选模块）
- `custom_candidate_proposer: ProposalFn`（自定义反思提案）；`reflection_prompt_template`（改反思元提示）
- `use_merge / max_merge_invocations / merge_val_overlap_floor`（谱系合并 = 交叉算子）
- `stop_callbacks: StopperProtocol`（FileStopper/TimeoutStopper/NoImprovementStopper…）；`acceptance_criterion: AcceptanceCriterion`（minibatch 接受准则可换）
- `val_evaluation_policy: EvaluationPolicy`（每轮对哪些 val 实例打分，默认全量）
- 预算即一等约束：`max_metric_calls` / `max_full_evals` / `auto∈{light,medium,heavy}` 三选一
- 持久化：`run_dir` checkpoint 可恢复；adapter state 鸭子类型快照

仓库内 adapters/ 目录给出 10 个参考实现（default、dspy、langchain、mcp、terminal_bench、generic_rag、optimize_anything……），证明 Protocol 的表达力[^13^]。另有 `optimize_anything(seed_candidate, evaluator, objective, config)` 顶层 API：evaluator 是普通 Python 函数，内部用 `oa.log(...)` 输出"actionable side information"喂回反思通道——把 GEPA 的 trace-feedback 契约压缩成单个函数 + 日志调用。

---

## 3. 关键设计决策与权衡

1. **进化单元：函数体（FunSearch）→ EVOLVE-BLOCK 块（AlphaEvolve 系）→ 具名文本组件 dict（GEPA）**。粒度越粗，评估契约越重（FunSearch 只需 `Sandbox.run`，GEPA 需要 trace 采集），但适用面越宽。EVOLVE-BLOCK 标记法（AlphaEvolve/OpenEvolve/ShinkaEvolve 三家一致）是"把存量代码库纳入进化"的最低侵入方案[^4^][^5^][^10^]。
2. **变异表示：diff vs full rewrite**。diff（SEARCH/REPLACE）支持大代码库定向修改但引入 patch 应用失败率（需要 `max_patch_resamples` 重试 + marker 校验）；full rewrite 简单可靠但浪费 token、难做大文件。工程结论：两者共存 + 概率配置（ShinkaEvolve `patch_type_probs=[0.6,0.3,0.1]`）[^11^]。
3. **Database 即算法**：FunSearch 的 cluster-softmax、AlphaEvolve/OpenEvolve 的 MAP-Elites×岛屿、GEPA 的 per-instance Pareto frontier，本质都是"**用一个带结构的状态库把'重新浮现旧思想'的策略编码进去**"。MAP-Elites 的特征维度可插拔（OpenEvolve 直接把 evaluator metric 当维度）是低成本高价值的设计；Pareto-per-instance（GEPA）不需要人工选特征维度，但要求评估天然逐实例[^9^][^14^]。
4. **Evaluator 契约的反馈带宽递增**：scalar → dict[str,float] → +artifacts 侧信道（OpenEvolve）→ +public/private/text_feedback 划分（ShinkaEvolve）→ +完整 trajectory + reflective dataset（GEPA）。带宽越高样本效率越高（GEPA 35× vs GRPO），但评估器实现成本和对 LLM 的依赖同步上升。OpenEvolve 的 artifacts（含安全过滤 + 字节上限）是"低成本拿到大部分收益"的折中[^9^][^11^][^13^]。
5. **级联评估（cascade）是进化特有的早停**：AlphaEvolve hypothesis-testing cascade、OpenEvolve `evaluate_stage1/2/3` + `cascade_thresholds`——用便宜测试先淘汰，把昂贵评估留给有希望的候选。阈值是"相对当前最优"的（OpenEvolve 默认 0.5/0.75/0.9），随进化自动收紧[^6^][^9^]。
6. **异步流水线 vs 世代同步**：FunSearch/AlphaEvolve/OpenEvolve 全部放弃"代"的硬边界，sampler/evaluator 各自无限循环、DB 为唯一同步点，吞吐优先；副作用是"prompt 生成后岛被重置/迁移"的陈旧注册问题（FunSearch 代码注释明确提及并刻意忽略[^2^]）。OpenEvolve 用 DB 快照 + 批量合并换取进程级并行；ShinkaEvolve 用 proposal/eval/db 三池配额进一步解耦[^7^][^11^]。
7. **多样性维护的四种机制可组合**：岛屿+迁移（全部）、MAP-Elites 特征网格（AlphaEvolve 系）、新颖性拒绝（嵌入+LLM judge，ShinkaEvolve/OpenEvolve）、模板随机化（AlphaEvolve/OpenEvolve `use_template_stochasticity`）。岛重置（FunSearch 每 4h 杀一半岛）在开源复现中被迁移机制替代——重置太粗暴，迁移更平滑[^2^][^9^]。
8. **LLM ensemble 的选择策略演化**：固定权重（OpenEvolve）→ 成本感知 UCB bandit（ShinkaEvolve `BanditBase`）→ Flash/Pro 人工配比（AlphaEvolve）。bandit 方案把"哪个模型擅长当前进化阶段"变成在线学习问题，且状态可持久化（`get_state/set_state`）[^11^]。
9. **meta 层（提示词自身的进化）**：AlphaEvolve meta prompt evolution、ShinkaEvolve `SystemPromptEvolver` + `MetaSummarizer`、GEPA 无（其 prompt 就是优化对象本身）。meta 层 = 二阶优化，收益真实但工程复杂度陡增，ShinkaEvolve 把它做成了独立 archive + 独立 bandit，值得借鉴[^4^][^11^]。
10. **可复现性作为一等设计**：OpenEvolve 全组件 seed（默认 42）、hash 隔离；GEPA checkpoint/resume + adapter state 快照；ShinkaEvolve SQLite + W&B。进化搜索本质是长尾随机的，无 checkpoint 的框架无法用于生产[^5^][^13^]。

---

## 4. 八轴卡

| 轴 | FunSearch | AlphaEvolve | OpenEvolve | ShinkaEvolve | GEPA | DEEVO |
|---|---|---|---|---|---|---|
| **优化对象** | 单 Python 函数体 | EVOLVE-BLOCK 标记的多代码块（程序/搜索算法/二者协同） | 整文件代码（多语言）中的标记块 | 同左 + 系统提示词（meta） | 具名文本组件 dict（prompt/代码/配置） | 单 prompt 文本 |
| **基本搜索单元** | 版本化函数（cluster 内等价类） | 程序 + (分数, 输出) 记录 | `Program`(code+metrics+谱系+island) | `Program`(SQLite 行+谱系) | candidate（组件文本映射） | prompt + Elo rating |
| **算子** | LLM best-shot 续写（k=2 示例） | LLM diff/全文变异 + meta prompt 进化 | diff/full 变异（无原生 crossover） | diff/full/cross 按概率 + meta 推荐注入 + prompt 共进化 | reflective mutation（trace 驱动）+ merge（谱系合并） | 辩论引导智能 crossover + 定向 mutation |
| **拓扑** | 10 岛 + 周期重置后半岛（founder 重播种） | 岛 × MAP-Elites 组合 | 5 岛环形迁移（lazy，按岛代计数） | 2+ 岛，可 stagnation 动态繁殖 | 无岛；单池 + per-instance Pareto frontier | 单池锦标赛 |
| **持久状态** | islands→clusters(signature=得分向量)→programs | 进化数据库（程序+分数+输出） | MAP-Elites feature_map + archive + islands + artifacts + checkpoint | SQLite DB + prompt archive + bandit state + W&B | 候选池 + 逐实例分数矩阵 + frontier + run_dir checkpoint | 群体 + Elo 表 |
| **反馈权限** | 仅标量分（逐测试） | 多指标 dict + LLM feedback + 渲染进 prompt 的执行结果 | metrics dict + artifacts 侧信道（stderr/traceback）+ 可选 LLM feedback | combined_score + public/private metrics + text_feedback | 完整 trajectory + reflective dataset（最高带宽） | 辩论判词文本 + 相对胜负 |
| **失败利用** | 直接丢弃（不计分即不入库） | 级联早淘汰；失败程序可留档 | artifacts 把失败原因喂回下一轮 prompt | text_feedback + 新颖性拒绝；patch 失败重采 | **失败即反思材料**（契约强制错误写入 trajectory） | 辩论 trace 暴露弱点供 crossover 规避 |
| **并行与选择** | 15 sampler/140 evaluator 异步；cluster-softmax 退火 | asyncio 流水线，吞吐优先；MAP-Elites 胞格竞争 | 进程池 + DB 快照；exploit/explore/random 三路 + double selection | proposal/eval/db 三池异步；bandit 选模型、power-law/beam 选父母 | minibatch 接受测试（sum 不降）+ frontier 随机采样；预算制（metric calls） | 并行配对；Elo + newcomer/veteran 配额 |

---

## 5. 对统一框架的接口启示

### 5.1 可直接吸收的模块接口（来自本维度的最大价值）

进化式框架收敛出的模块分解与 agentic 框架（如 Arbor 的 coordinator-executor）**高度可统一**，映射关系如下：

```
统一抽象                进化框架实例化                          agentic 框架对应
─────────────────────────────────────────────────────────────────────────────
ProposalEngine          LLMEnsemble + PromptSampler              planner/executor 的决策核心
  .propose(context)     diff/full/cross/reflective 算子可配       action 生成
PopulationStore         ProgramDatabase (FunSearch/AlphaEvolve    run/trajectory 存储
  (Archive)             系) / GEPAState + Pareto frontier         ＋经验库
  .add() .sample()      选择策略注入点（bandit/weighted/pareto）  检索策略注入点
Evaluator               evaluate(path)->metrics /                 verifier/reward 模块
  .evaluate(candidate)  GEPAAdapter.evaluate->EvaluationBatch     工具执行+校验
  → 分级契约：scalar → metrics+artifacts → traces+text_feedback
Controller              OpenEvolve / ShinkaEvolveRunner /         coordinator（调度、配额、
  .run(budget)          GEPAEngine：预算制 stop、checkpoint、      早停、恢复）
                        stop_callbacks
JobBackend              local/Slurm/Docker (ShinkaEvolve          sandbox/执行环境
                        JobConfig)、OpenEvolve 进程池
```

**具体建议吸收的接口设计**（按价值排序）：

1. **GEPAAdapter 式单 Protocol 适配层**：`evaluate(batch, candidate, capture_traces) -> EvaluationBatch(outputs, scores, trajectories?)` + `make_reflective_dataset(...)`，泛型参数（DataInst/Trajectory/RolloutOutput）不解释、全留给用户。一个 Protocol 同时框住"评估"与"失败利用"两轴，是四框架中最优雅的扩展面[^13^]。
2. **分层的评估返回契约**：`{score, public_metrics(对变异器可见), private_metrics(不可见), text_feedback, artifacts/extra_data}`（ShinkaEvolve/OpenEvolve 融合版）。`public/private` 划分直接回应"反馈权限"轴的配置化需求[^11^]。
3. **EVOLVE-BLOCK 区域标记**：把"优化对象"声明为宿主代码内的注释标记，骨架与可变区分离——统一框架支持"优化存量系统"的最小侵入协议[^4^]。
4. **选择策略的可注入对象化**：ShinkaEvolve `BanditBase`（select/update/get_state/set_state）证明"父母/模型选择"应是有状态、可持久化的策略对象，而非配置枚举；GEPA 的 `CandidateSelector/BatchSampler/StopperProtocol/AcceptanceCriterion` 全家桶展示了把引擎每个决策点都做成 Protocol 的彻底 DI 风格[^11^][^13^]。
5. **cascade 评估协议**：`evaluate_stage1/2/3` + 相对阈值，是评估预算的标准件[^6^]。
6. **预算作为一等公民**：GEPA `max_metric_calls` 三选一强制、AlphaEvolve 吞吐导向异步流水线——controller 应以"预算-消耗"记账为中心，而非"迭代次数"[^4^][^14^]。
7. **checkpoint/resume + adapter state 鸭子类型快照**：长跑搜索的生产必需[^5^][^13^]。

### 5.2 进化框架缺什么（与 agentic 框架互补的缺口）

1. **语义记忆（semantic memory）**：所有进化数据库都是"实例仓库"（程序+分数），**没有跨代的知识抽象**——为什么某类变异有效、什么策略在什么阶段有效，这些经验只隐式存在于"哪些程序存活"里。最接近的是 ShinkaEvolve 的 MetaSummarizer（周期性生成 meta-recommendations）和 GEPA 的 reflective dataset（但只覆盖当次 minibatch，不跨代沉淀）。统一框架应增加"经验→自然语言规则→注入后续 proposal"的持久语义层（类似 Reflexion/Voyager 的 skill library 之于 agentic 框架）。
2. **准入纪律（admission discipline）与目标管理**：进化框架的接受准则很朴素（minibatch 不降 / MAP-Elites 胞格竞争 / 岛 best 更新），没有"假设-验证-定论"的研究纪律：不确定候选该重复实验多少次、分数噪声如何处理（仅 OpenEvolve 支持 `num_runs` 聚合的雏形在 ShinkaEvolve `run_shinka_eval` 里）、结论如何分级。agentic 研究框架（如 AI-Scientist 的 review 环节、Arbor 的 verification gate）的准入纪律正好是补充。
3. **多步/条件化评估计划**：evaluator 契约是"一个候选进、一组分出"，不支持"根据中间结果决定下一步测什么"的主动实验设计（active experimentation）。
4. **跨任务迁移与复用**：island 间迁移只搬运程序，不搬运"做法"；meta prompt evolution（AlphaEvolve/ShinkaEvolve）是雏形但仍限于单 run 内。
5. **人机共治接口**：OpenEvolve `manual_mode`（人在回路变异队列）是唯一触及者；准入、早停、方向调整均无人机协同抽象。

**结论**：进化式框架提供了成熟的"搜索内核"（population store + proposal + evaluator + 预算化 controller + 分布式评估），agentic 框架提供"认知外壳"（语义记忆、验证纪律、规划）。统一抽象可行：把进化的四组件作为 kernel，把 agentic 的记忆/纪律作为挂在 ProposalEngine 上下文装配点（`build_context`）与 PopulationStore 准入钩子（`admit(candidate, evidence) -> bool`）上的策略层——两者的接口冲突点仅在"反馈带宽"（scalar vs traces）与"状态语义"（实例库 vs 知识库），而这两者都可用 GEPA 式 Protocol 泛型参数化解。

---

## 参考来源

[^1^]: google-deepmind/funsearch 官方仓库 README, https://github.com/google-deepmind/funsearch
[^2^]: FunSearch `implementation/programs_database.py` 源码（ProgramsDatabase/Island/Cluster、reset_islands、softmax 退火）
[^3^]: FunSearch `implementation/config.py` / `funsearch.py` / `evaluator.py` / `sampler.py` 源码
[^4^]: Novikov et al., "AlphaEvolve: A coding agent for scientific and algorithmic discovery", arXiv:2506.13131, §2.1–2.6
[^5^]: OpenEvolve README, https://github.com/codelion/openevolve
[^6^]: OpenEvolve CLAUDE.md（架构说明：级联评估、lazy migration、double selection、EVOLVE-BLOCK）
[^7^]: DeepWiki: codelion/openevolve — Controller and Orchestration / System Architecture, https://deepwiki.com/codelion/openevolve
[^8^]: OpenEvolve `openevolve/config.py` 与 `configs/default_config.yaml` 源码
[^9^]: OpenEvolve `openevolve/database.py` / `evaluator.py` / `prompt/sampler.py` / `process_parallel.py` 源码（类与方法签名、MAP-Elites、cascade 校验）
[^10^]: Lange, Imajuku, Cetin, "ShinkaEvolve: Towards Open-Ended and Sample-Efficient Program Evolution", arXiv:2509.19349；仓库 README, https://github.com/SakanaAI/ShinkaEvolve
[^11^]: ShinkaEvolve 源码：`shinka/core/config.py`(EvolutionConfig)、`shinka/database/dbase.py`(DatabaseConfig/ProgramDatabase)、`shinka/core/sampler.py`、`shinka/llm/prioritization.py`(BanditBase)
[^12^]: Agrawal et al., "GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning", arXiv:2507.19457（ICLR 2026 Oral）
[^13^]: gepa-ai/gepa 仓库 README 与 `src/gepa/core/adapter.py`(GEPAAdapter Protocol)、`src/gepa/api.py`(optimize 签名)、`src/gepa/core/engine.py`, https://github.com/gepa-ai/gepa
[^14^]: DSPy 官方文档 dspy.GEPA, https://dspy.ai/api/optimizers/GEPA/overview/
[^15^]: Nair, Banerjee, Mombaerts, "Tournament of Prompts: Evolving LLM Instructions Through Structured Debates and Elo Ratings" (DEEVO), arXiv:2506.00178
[^16^]: OpenEvolve 官方架构博客, https://algorithmicsuperintelligence.ai/blog/openevolve-overview/
