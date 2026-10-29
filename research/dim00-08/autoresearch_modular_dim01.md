# Dim-01 调研报告：AIDE × AIRA-dojo —— 搜索策略与算子解耦

> 调研单元：AIDE（arXiv:2502.13138，Weco AI）与 AIRA-dojo（arXiv:2507.02554，Meta FAIR）。
> 视角：**模块边界与可插拔设计**——两个系统各自把什么做成了可替换组件，接口/契约长什么样，哪些设计被实验证明重要/不重要。
> 一手来源：arXiv HTML 全文 + 两个官方 GitHub 仓库的源码与文档（检索/阅读次数 >20 次）。所有访问日期为 2026-08-05。

---

## 1. 系统概览与核心循环

### 1.1 AIDE：ML 工程 = 代码空间上的树搜索

AIDE 把 ML 工程形式化为一个**无状态优化问题**：给定解空间 𝒮（Python 脚本）与无状态目标函数 h: 𝒮→ℝ（验证指标），求 s\* = argmax h(s)。与 ReAct 式 agent 把全部历史追加进上下文不同，AIDE 把所有历史解组织成一棵**解树 T**，每次 LLM 调用只聚焦单个节点的局部问题（起草/修 bug/改进），由硬编码的树搜索算法积累增量改进[^1^]。

五个核心组件（论文 §3.1 的形式化）：

| 组件 | 符号 | 作用 |
|---|---|---|
| 评估器 | h: 𝒮→ℝ | 执行脚本、给出标量分数 |
| 解树 | T | 节点=脚本，边=一次改进尝试 |
| 搜索策略 | π(T) | 选择下一个作为改进基座的节点 |
| 摘要算子 | Σ(T) | 从树中提取相关信息，控制 prompt 长度 |
| 编码算子 | f(s, Σ(T)) | 生成新脚本（draft / debug / improve 三入口） |

**伪代码级主循环**（论文 Algorithm 1，与开源实现 `aide/run.py` + `aide/agent.py` 一致[^1^][^6^][^3^]）：

```python
T ← ∅; s ← s0                       # 空根解
for n in 1..N:                      # N = cfg.agent.steps（默认 20）
    s_n ← f(s, Σ(T))                # 编码算子：draft / debug / improve
    v_n ← h(s_n)                    # 执行 + LLM 评审（is_bug / metric / summary）
    T ← T ∪ {node(s_n, v_n), edge(s → s_n)}
    s  ← π(T)                       # 搜索策略选下一个基座
return argmax_{s' ∈ T} h(s')        # 返回验证指标最优节点
```

开源实现中，`Agent.step()` 的一次迭代精确对应上述循环体：`search_policy()` 选父节点 → `_draft()`/`_debug()`/`_improve()` 生成代码 → `exec_callback`（Interpreter 子进程执行）→ `parse_exec_result()`（用 function-calling 结构化评审输出，判定 is_buggy 并写回 MetricValue）→ `journal.append()`[^3^]。

**搜索策略 π 是硬编码的优先级规则**（`Agent.search_policy()`）[^3^]：
1. 若 draft 节点数 < `num_drafts`（默认 5）→ 返回 None（触发 draft）；
2. 否则以概率 `debug_prob`（默认 0.5）从「buggy 且为叶子且 debug_depth ≤ `max_debug_depth`（默认 3）」的节点中随机选一个去 debug；
3. 若没有 good 节点 → 继续 draft；
4. 否则贪心选 `journal.get_best_node()`（验证指标最高的非 buggy 节点）去 improve。

**评估 h 的实现**：代码在子进程执行后，由一次独立的 LLM 调用（`review_func_spec`，function calling）输出 `{is_bug, summary, metric, lower_is_better}`；metric 非 float、执行异常或 LLM 判 bug 均记为 buggy，metric 置为 `WorstMetricValue()`[^3^]。

### 1.2 AIRA-dojo：把 research agent 统一形式化为图搜索算法

AIRA（AI Research Agents）论文把 AIDE 推广为**图搜索五元组**[^10^]：

> 一个基于图的搜索算法由 tuple **(ℱ, π_sel, 𝒪, π_op, τ)** 完全指定：
> - **ℱ: 𝒮→[0,1]**：fitness 函数（代理指标，如 5-fold CV 分数）；实例化中 ℱ 由生成该节点的算子定义（非全局）；
> - **π_sel: 2^V→2^V**：节点选择策略，通常由启发式 h（如 UCT）引导；
> - **𝒪 = {o_l: 2^𝒮→𝒮}**：算子集，从一个或多个已有 artifact 生成新 artifact；
> - **π_op: 𝒪×U→𝒪**：算子选择策略；
> - **τ**：终止规则（wall-clock 或节点数上限）。

在此记号下，**AIDE = greedy 搜索（π_sel 贪心 + ε_bug 回访）+ 固定规则 π_op + 算子集 {Draft, Debug, Improve, Memory}**[^10^]。AIRA 论文的系统贡献是：(a) 把算子集与搜索策略解耦做控制实验；(b) 提出改进算子集 𝒪_AIRA（新增 Crossover，重做 Memory，prompt 自适应复杂度，think tokens）；(c) 配套开源框架 AIRA-dojo。

**伪代码级主循环**（论文 Fig.2 + `src/dojo/solvers/*` 实现[^10^][^16^][^24^][^23^]）：

```python
G ← {v0}                            # 搜索图，v0 为空根 artifact
while not τ:                        # τ = wall-clock 24h 或 step_limit
    U ← π_sel(G)                    # 选择策略：greedy 取 argmax ℱ / MCTS 按 UCT 下行 / evo 按 ℱ 比例采样
    o ← π_op(𝒪, U)                  # 算子策略：draft 若种子不足；debug 若 buggy；否则 improve/crossover
    v_new ← o(U)                    # 应用算子（LLM 生成 plan+code）
    ℱ(v_new) ← execute & evaluate   # Jupyter/Apptainer 执行 + analyze 算子解析验证指标
    G ← G ∪ {v_new}                 # 更新图（MCTS 回传 (N,Q)；evo 替换最劣个体）
return argmax_{v ∈ G} ℱ_val(v)      # 按验证分数返回最终节点
```

三种实例化搜索策略的关键差异[^10^]：
- **Greedy**：π_sel 取 ℱ 最大者（概率 ε_bug 回访 buggy 节点）；
- **MCTS**：标准 selection/expansion/evaluation/backup，但**不做模拟 rollout**——叶节点值直接取 ℱ；UCT 中 h(v|u)=Q(v)+c·√(ln N(u)/(N(v)+ε))，c=0.25，每次 expansion 生成 num_children=5 个子节点，buggy 子节点进入自动 debug 循环[^10^]；
- **Evolutionary**：固定大小种群（每代 5 个候选），按 ℱ 比例采样父代，以固定概率 improve 或 crossover，子代替换最劣个体；实现上还引入了**岛模型**（`Island`/`SolutionsDatabase` 类，支持迁移）[^23^]。

---

## 2. 模块边界与可插拔点（核心）

### 2.1 AIDE 的模块划分（代码级）

仓库 `WecoAI/aideml` 的核心代码仅 ~8 个文件，模块边界非常清晰[^2^]：

```
aide/
├── agent.py          # Agent: π + f（draft/debug/improve）+ 反馈解析
├── journal.py        # Journal/Node: 解树持久状态
├── interpreter.py    # Interpreter: 子进程代码执行
├── backend/          # LLM 路由层（openai/anthropic/gemini/openrouter）
├── utils/config.yaml # 全部可调超参
├── utils/metric.py   # MetricValue: 带优化方向的可比较指标
└── run.py            # 主循环 + CLI 入口
```

**① 持久状态抽象：`Journal` / `Node`**（aide/journal.py）[^4^]
`Node` 是搜索的基本数据单元，dataclass 字段构成「节点契约」：

```python
@dataclass
class Node:
    code: str                      # 单文件 Python 脚本
    plan: str                      # 自然语言方案（3-5 句）
    parent / children              # 树结构（单父节点）
    _term_out, exec_time, exc_type, exc_info, exc_stack   # 执行信息
    analysis: str                  # LLM 评审的实验结论
    metric: MetricValue            # 验证指标（带方向）
    is_buggy: bool                 # 是否失败节点
    # 派生属性：stage_name ∈ {draft, debug, improve}、debug_depth、is_leaf
```

`Journal` 是节点容器 + 查询接口：`draft_nodes` / `buggy_nodes` / `good_nodes` / `get_best_node(only_good=True)` / `generate_summary(include_code=False)`——**Σ(T) 摘要算子就是 `generate_summary`**：仅对 good 节点拼接 "Design/Results/Validation Metric"，即 memory 只保留成功解的设计与结果[^4^]。

**② 搜索策略与算子：`Agent`**（aide/agent.py）[^3^]
- `search_policy() -> Node | None`：上文 1.1 的硬编码规则；返回 None 表示 draft。
- 三个算子入口 `_draft()` / `_improve(parent)` / `_debug(parent)`：**输入 = (task_desc, journal 摘要, 父节点代码/执行输出, data_preview)，输出 = Node(plan, code)**；内部统一走 `plan_and_code_query()`（要求 LLM 输出「3-5 句 plan + 单个 markdown 代码块」，解析失败重试 3 次）。
- `parse_exec_result()`：反馈解析器，用 `review_func_spec`（FunctionSpec / JSON schema：`{is_bug: bool, summary: str, metric: number, lower_is_better: bool}`）做结构化输出评审；is_buggy 的判定 = LLM 判 bug **或** 有异常类型 **或** 无合法 metric[^3^]。

**③ 执行环境：`Interpreter`**（aide/interpreter.py）[^8^]
接口为 `run(code: str, reset_session=True) -> ExecutionResult`，其中 `ExecutionResult = {term_out, exec_time, exc_type, exc_info, exc_stack}`。实现上用子进程 + Queue 重定向 stdout，支持超时（`exec.timeout` 默认 3600s）与会话复用。**注意：AIDE 默认不做容器级隔离**，仅工作目录隔离 + 超时。

**④ LLM 后端路由：`backend`**（aide/backend/__init__.py）[^7^]
统一入口 `query(system_message, user_message, model, temperature, func_spec=None) -> OutputType`；`determine_provider()` 按模型名正则路由到 openai/anthropic/gemini/openrouter 四个 backend；传 `func_spec` 时返回结构化 dict，否则返回字符串。prompt 以 dict/list 嵌套结构描述，由 `compile_prompt_to_md` 编译成 markdown——**prompt 即配置数据而非模板文件**。

**⑤ 指标类型：`MetricValue`**（aide/utils/metric.py）[^9^]
把「优化方向」内化进类型：`MetricValue(value, maximize=bool)`，比较运算符按「更好」而非「更大」定义；`WorstMetricValue`（value=None）永远比任何合法值差， buggy 节点统一置此值。这使得 `get_best_node` 无需关心 metric 方向。

**⑥ 配置项**（aide/utils/config.yaml，OmegaConf CLI 覆盖）[^5^]：

```yaml
exec:      {timeout: 3600, agent_file_name: runfile.py, format_tb_ipython: False}
agent:
  steps: 20                       # 搜索步数（终止条件）
  k_fold_validation: 5            # 是否指示 agent 用 CV
  expose_prediction: False        # 是否要求生成 predict() 函数
  data_preview: True              # 是否在 prompt 中注入数据预览
  code:     {model: o4-mini, temp: 0.5}        # 编码 LLM
  feedback: {model: gpt-4.1-mini, temp: 0.5}   # 评审 LLM（与编码 LLM 解耦！）
  search:   {max_debug_depth: 3, debug_prob: 0.5, num_drafts: 5}   # 搜索策略超参
report:    {model: gpt-4.1, temp: 1.0}         # 最终报告生成
```

任务契约是**纯自然语言**：CLI 传入 `data_dir` + `goal` + `eval`（如 `aide data_dir=... goal="预测房价" eval="RMSE"`），或 `desc_file`；agent 被要求输出 `submission.csv` 作为对外交付物[^5^][^11^]。

**AIDE 的可插拔点小结**：LLM provider/模型、编码与评审模型分离、搜索三超参（num_drafts/debug_prob/max_debug_depth）、执行超时、任务描述。**硬编码不可替换**：搜索策略规则本身、三算子的 prompt 工程、节点类型（单文件脚本）、串行单节点步进。换言之，**AIDE 的「策略 vs 算子」在代码里是同一个 Agent 类内的方法，并未接口化**——这正是 AIRA-dojo 要拆的东西。

### 2.2 AIRA-dojo 的模块划分（代码级）

AIRA-dojo 是一个完整的框架（Hydra 配置 + registry + ABC 分层），README 明确给出术语：**Task**（环境+动作空间+评估函数）、**Solver = Operators + Search Policy**、**Run**（一个 solver 解一个 task）、**Runner**（并行编排多个 run）[^12^]。

```
src/dojo/
├── core/
│   ├── tasks/base.py         # Task(ABC): prepare/step_task/evaluate_fitness/close
│   ├── solvers/base.py       # Solver(ABC): __call__(task, state) + checkpoint
│   ├── solvers/operators/    # draft/improve/debug/analyze/crossover/memory（算子即函数）
│   ├── solvers/llm_helpers/  # GenericLLM + 多后端 client + Jinja prompt
│   ├── solvers/utils/journal.py  # Journal/Node（含多父节点支持）
│   ├── interpreters/         # python / jupyter（Apptainer 沙箱）
│   └── runners/              # Slurm/submitit 并行
├── solvers/{greedy, mcts, evo}/   # 三个搜索策略实现
├── tasks/mlebench/           # MLE-bench 任务实例
├── configs/                  # Hydra YAML（task/solver/operators/memory/client/...）
└── config_dataclasses/       # YAML 反序列化的 dataclass + *_MAP registry
```

**① Task 抽象**（core/tasks/base.py）[^15^]——四类方法构成环境契约：

```python
class Task(ABC):
    def prepare(**task_args) -> (state, task_info)          # 准备工作区，返回初始状态与任务信息
    def step_task(state, action) -> (state, eval_result)    # 执行一个动作（这里是“跑一份代码”）
    def evaluate_fitness(solution, state, interpreter, aux_info)  # 最终解的 fitness
    def close(state)                                        # 清理
```

`task_info` 与 `eval_result` 的 key 由 `core/tasks/constants.py` 统一约定：`TASK_DESCRIPTION / EXECUTION_OUTPUT / VALIDATION_FITNESS / TEST_FITNESS / VALID_SOLUTION / VALID_SOLUTION_FEEDBACK / AUX_EVAL_INFO`[^25^]。**solver 与 task 之间只通过这些字符串 key 的 dict 通信，完全解耦**。

**② Solver 抽象**（core/solvers/base.py）[^14^]：

```python
class Solver(ABC):
    def __call__(self, task, state)     # 主搜索循环（子类实现）
    def save_checkpoint() / load_checkpoint()   # 断点续跑（一等公民）
```

三个具体 solver（Greedy/MCTS/Evolutionary）共享同一套算子函数，差异只在 `search_policy()` / `step()` 的控制逻辑与节点统计量（如 `MCTSNode` 增加 visit count N 与均值 Q；evo 增加 Island 种群管理）[^16^][^24^][^23^]。

**③ 算子即函数 + 依赖注入**（core/solvers/operators/）
以 `improve_op` 为例的签名[^18^]：

```python
def improve_op(
    improve_llm: GenericLLM, cfg: DictConfig,
    memory_op: Optional[Callable[[Journal, Optional[Node]], str]],
    task_description: str, journal: Journal, input_node: Node,
    step_count: int, remaining_time: int,
    complexity: Optional[Complexity] = None, data_preview: Optional[str] = None,
) -> str     # 返回 LLM 文本（plan+code），由 execute_op_plan_code 统一抽取
```

`crossover_op` 多一个 `input_node2`（二元算子）[^23^]；`analyze_op` 用 JSON schema 结构化输出 `{is_bug, summary, metric}`（fetch_metric 可关）[^26^]。所有算子通过 `execute_op_plan_code(operator_fn, *args, max_operator_tries, requires_plan)` 统一做「生成→抽取 plan/code→失败重试」，并剥离 thinking tags（think tokens 对其他算子不可见）[^19^]。Solver 在 `setup_operators()` 里用 `functools.partial` 把 LLM 与 memory 注入算子——**算子集通过配置组装，而非写死在 solver 里**[^16^]。

**④ Memory 算子：工厂 + 注册表**（core/solvers/operators/memory.py）[^17^]
这是全仓库最能体现「可插拔」的设计：

```python
MEM_OPS = {"simple_memory": ..., "no_memory": ..., 
           "sibling_memory": ..., "ancestral_memory": ...}
def create_memory_op(cfg: MemoryOpConfig) -> Callable[[Journal, Optional[Node]], str]
```

四种作用域：全局摘要（simple，等价 AIDE 的 Σ）、无记忆、**兄弟记忆**（draft/improve 只看同一父节点的子节点 → 促进多样性）、**祖先记忆**（debug 看整条 debug 链 → 避免 undo-redo 振荡）。YAML 里一行切换：`override memory: sibling_memory`，且主 memory 与 debug memory 可分别配置[^21^]。

**⑤ LLM 封装：GenericLLM + Jinja 模板**[^27^][^22^]
每个算子的 LLM 由 YAML 完整声明：client（litellm_4o/o3/r1/gdm…）、generation_kwargs、system/user prompt 的 **Jinja 模板**（变量如 `{{task_desc}} {{memory}} {{data_overview}} {{packages}} {{execution_timeout}}`，条件块如 `{% if draft_complexity == 'simple' %}`——这就是「prompt 自适应复杂度」的实现位置）。prompt 从代码中解放为配置文件，是 AIRA-dojo 与 AIDE 的重要工程差异。

**⑥ 执行环境与任务实例：MLEBenchTask**（tasks/mlebench/task.py）[^20^]
`step_task(state, action)`：抽取代码 → `interpreter.run()`（Apptainer 容器内 Jupyter 执行）→ 取回 `submission.csv` → 校验合法性 → 用 mlebench 官方评分器算 **test fitness**。**关键防泄漏设计：test fitness 只写入 eval_result 供事后分析，agent 在搜索中只能看到 analyze 算子从 stdout 解析出的 validation fitness**[^20^]。环境约束（运行时限、GPU/CPU/内存/存储）由 Apptainer 容器强制；Superimage 预装 CUDA/PyTorch/TF，agent 在容器内有 root 权限可 apt-get/pip 安装但不影响宿主与其他 agent[^10^]。

**⑦ 配置组装与 registry**（main_run.py + configs/）[^19^][^13^]
执行流：`build(cfg.task, TASK_MAP)` → `build(cfg.interpreter, INTERPRETER_MAP)` → `task.prepare()` → `build(cfg.solver, SOLVER_MAP, task_info=task_info)` → `solver.load_checkpoint()` → `solver(task, state)` → `task.close()`。组件选择完全由 Hydra YAML 组合驱动，例如 mlebench/greedy.yaml[^21^]：

```yaml
defaults:
  - greedy
  - /solver/operators/mlebench@operators: [aira_operators/debug, aira_operators/draft,
                                           aira_operators/improve, aide_operators/analyze]
  - override memory: simple_memory
  - override memory@debug_memory: debug_memory
improvement_steps: 5
max_debug_depth: 20      # dojo 版比 AIDE 的 3 大得多
debug_prob: 1.0
num_drafts: 5
```

注意 **operator 配置可以在 aide_operators 与 aira_operators 两套之间混搭**——控制实验（固定搜索策略换算子集）就是这样做的[^21^]。

**⑧ 并行与规模化**[^10^][^12^]
单 run 内部仍是串行节点步进；并行在 **Runner 层**：`main_runner_job_array.py` + Slurm job array，支撑了 1000 个 agent 并行、最长 120 小时的实验。工程教训（论文 §14）：自托管 LLM（外部 API 限速是规模上限）、容器隔离（agent 会 pip install 污染环境）、checkpointing（1000 agent × 24h ≈ 24000 机时 vs 节点 MTBF ~1000h，故障是常态）[^10^]。

---

## 3. 关键设计决策与权衡（含实验证据链）

### 3.1 AIDE 侧的设计决策

**D1：树搜索 + 无状态优化，而非 ReAct 式单体长程决策。**
依据：POMDP 视角需要把全部历史塞进上下文，prompt 会爆；而每个候选解可被独立评估，天然适配树搜索。证据（MLE-bench，OpenAI 官方评测）：AIDE+o1-preview 奖牌率 16.9%，约为线性 agent OpenHands（4.4%）的 4 倍；MLE-bench Lite 上套了 AIDE 外壳后 o1-preview 的有效提交率从 63.6%→92.4%，above-median 从 13.6%→59.1%，金牌率 6.1%→21.2%（p<0.01）[^1^]。结论：**把 agentic 循环外化为「搜索算法 × 单节点 LLM 调用」，比依赖 LLM 消化长历史更可靠**。

**D2：每次 improve 只做「一个原子改动」。**
改进算子被 prompt 约束为恰好一个可测变更（换优化器、加正则等），保证每条边的性能变化可归因、树结构语义清晰[^1^]。这是「算子粒度」设计，后被 AIRA 继承。

**D3：失败节点不丢弃，而是作为可修复资产保留在树中。**
buggy 节点以 `debug_prob` 概率被回访，但 `max_debug_depth` 限制修复链长度（默认 3），防止在死胡同上耗尽预算[^3^][^5^]。RE-Bench 数据显示 AIDE 在 2 小时内超过人类专家（更快的迭代周期），但 8 小时后被追上——作者归因于**贪心策略陷入局部最优**（如 Rust CodeContests 任务上重复局部补丁而非发现新策略）[^1^]。这预示了「搜索策略可能需要升级」，但 AIRA 的控制实验给出了更精细的答案（见 D6）。

**D4：摘要算子 Σ(T) 只保留 good 节点的 plan/analysis/metric，不带代码。**
用极小的上下文换取跨分支知识复用；data preview 作为静态 prompt 段补充数据基本信息[^1^][^4^]。

### 3.2 AIRA 侧的证据链（控制实验）

AIRA 论文的方法论价值在于：**把环境、算子、搜索策略、评估四个因子逐一隔离**。以下按因果链排列（所有数字为 MLE-bench Lite 奖牌率，R1 模型 20 seeds/task，o3 为 10 seeds）[^10^]：

**E1（环境先行）：基础设施本身就是性能因子。**
同一个 AIDE_greedy + o1-preview，搬进 AIRA-dojo 环境后从 35.2%（OpenAI 报告值）提升到 45.9%（+10.7 绝对点，+30% 相对）。归因：执行隔离、4h→更短的单步执行上限换来更多有效节点、防泄漏评估等[^10^]。**启示：比较 agent 算法前必须先固定环境。**

**E2（memory 消融）：全局记忆不是 AIDE 性能的驱动因素。**
[DOJO] AIDE_greedy 无 memory 38.18% vs 有 memory 39.77%，均值几乎相同[^10^]。**这直接推翻了一个流行的直觉（跨节点记忆是关键），memory 算子在框架中应该可插拔而非必备。**

**E3（核心结论）：在 AIDE 算子集下，更高级的搜索拓扑无增益 → 算子是瓶颈。**
固定 𝒪_AIDE，换搜索策略：MCTS c_UCT∈{0, 0.25, 0.5, 0.75} → 36.36 / 35.45 / 35.00 / 34.55（对探索常数不敏感且整体不优于 greedy 39.77）；Evolutionary → 39.61 ≈ greedy[^10^]。即：**搜索层面的探索被「算子×策略的交互」所约束——算子产出的多样性/质量不足时，拓扑再聪明也没用**。论文 Fig.7 给出层级化「扩展前提」：环境 → 评估信号 → 算子能力 → 搜索策略，任何一层瓶颈都会吞掉额外算力[^10^]。

**E4（算子升级）：只换算子集，greedy 策略不变，+14% 相对提升。**
AIRA_greedy 45.45% vs AIDE_greedy 39.77%。𝒪_AIRA 的三个改动：(i) **prompt 自适应复杂度**（按节点的子节点数 nc 注入 minimal/moderate/advanced 复杂度线索，防止过早过度工程）；(ii) **作用域 memory**（draft/improve 看兄弟记忆促多样性，debug 看祖先记忆防振荡）；(iii) **think tokens**（显式鼓励推理模型思考，思考内容对其他算子不可见，completion tokens 平均 2×）[^10^]。

**E5（交互效应）：算子升级后，搜索拓扑才开始产生分化。**
配上 𝒪_AIRA 后：AIRA_mcts (R1) 47.05、AIRA_greedy (o3) 47.73、AIRA_mcts (o3) 47.27，全部超过 AIDE_greedy；且 any-time 曲线显示排名随时间变化——3h 时 greedy 领先，10h 收敛，**19h 后 MCTS 才拉开**[^10^]。结论：搜索拓扑的价值依赖于算子质量，且需要长时间尺度才显现。

**E6（泛化差距/反馈权限）：验证分数驱动的搜索存在系统性过拟合。**
- anytime 曲线：验证奖牌率持续上升，测试奖牌率平台期甚至下降[^10^]；
- oracle 实验：最终节点选择改用 test 分数（Val/Test）→ 所有 agent +9~13 绝对点；全程用 test（Test/Test）→ AIRA_mcts +9.4、AIRA_evo +12.4、AIRA_greedy +15、AIDE_greedy +16.6；Val/Test 相对 Test/Test 已消除大部分差距（greedy 也闭合 >60%）[^10^]；
- 实用缓解：top-k（k=3）按验证分筛选后取 test 最优 → +10%；非贪心 agent 的 top-k 与 random-k 差距更大，说明其搜索图多样性更高[^10^]；
- 长时间尺度（90h）：AIRA_greedy 峰值 ~53% 后随过拟合下降；AIRA_mcts 50h 后开始过拟合[^10^]。
**启示：最终节点选择策略（final-node selection）是一个独立的、高杠杆的模块；多次提交/集成选择比升级搜索拓扑便宜且有效。**

**E7（评测方法论）：种子数不足会颠倒排名。**
方差分解显示任务间与任务内方差都大；作者建议每任务 ≥10 seeds（20 更好）、stratified bootstrap 置信区间、宁可选子集多种子也不要全集少种子[^10^]。

**E8（最新结果）：完整 MLE-bench 上 AIRA_greedy+o3 总奖牌率 31.6%，Lite 上经 infra 再优化（文件系统、模型缓存）达 55.0%**[^10^]。

### 3.3 两系统共同的权衡点

| 权衡 | AIDE 的选择 | AIRA-dojo 的选择 | 证据倾向 |
|---|---|---|---|
| 上下文长度 vs 历史复用 | Σ 摘要（good 节点、无代码） | 作用域 memory 注册表（simple/sibling/ancestral/no） | 全局 memory 可有可无（E2）；作用域 memory 是算子升级的一部分（E4） |
| 修复 vs 放弃失败节点 | debug_prob=0.5, max_debug_depth=3 | debug cycle 上限 10 节点或 12h | 都需要预算约束；深度阈值差异大（3 vs 10-20）未单独消融 |
| 贪心利用 vs 搜索探索 | 纯贪心 + ε_bug | greedy/MCTS/evo 三策略 | 算子弱时探索无用（E3），算子强后 MCTS 长时段占优（E5） |
| 验证信号 vs 真实信号 | 仅验证分 | 仅验证分（test 防泄漏，仅事后分析） | 系统性过拟合 9-16.6 点（E6），是下一级瓶颈 |
| 单步算力 vs 迭代次数 | 1h/步，20 步 | 4h/步（从 9h 降下），24h wall-clock | 更短单步 → 更多有效节点，性能不降（AIRA §3.4）[^10^] |

---

## 4. 八轴卡

### 4.1 AIDE

| 轴 | 内容 |
|---|---|
| **优化对象** | 单文件 Python ML pipeline 脚本（code-as-solution），任务以自然语言 goal+eval 描述；对外交付 submission.csv |
| **基本搜索单元** | `Node` = (code, plan, parent/children, exec 输出, LLM 评审 analysis, MetricValue, is_buggy)；`stage_name ∈ {draft, debug, improve}` |
| **算子** | f 的三入口：draft（从头起草）/ debug（修 bug，保持思路）/ improve（恰好一个原子改动）；外加 Σ 摘要算子与 LLM 评审（function calling 结构化输出） |
| **搜索拓扑** | 树；硬编码优先级策略：先凑齐 num_drafts → ε(debug_prob) 回访 buggy 叶（限 debug_depth≤3）→ 贪心 improve 最优节点 |
| **持久状态** | `Journal`（全解树 JSON 序列化）；Σ(T) 摘要（仅 good 节点的 plan/analysis/metric）；workspace 中的 data preview |
| **反馈权限** | 执行 stdout/traceback + 独立评审 LLM 判 is_bug/metric/方向；仅验证指标，无 test 访问；反馈模型与编码模型可不同 |
| **失败利用** | buggy 节点留树、以 debug_prob=0.5 回访，debug_depth≤3 限制沉没；评审 LLM 的 summary 作为修复提示 |
| **并行与选择** | 单 agent 串行（每步 1 节点，默认 20 步/1h 超时）；选择=每步选 1 个基座节点；最终返回验证分最高节点 |

### 4.2 AIRA-dojo / AIRA

| 轴 | 内容 |
|---|---|
| **优化对象** | 任意 artifact（实例化为 Python 脚本/codebase）；Task 抽象把「问题」定义为环境+动作空间+fitness 函数 |
| **基本搜索单元** | 搜索图节点 v ∈ 𝒮（dojo 版 Node 支持多父节点，以容纳 crossover）；MCTS 节点附 (N, Q) 统计 |
| **算子** | 𝒪 = {draft, debug, improve, crossover, memory, analyze}；算子=纯函数 + 依赖注入（LLM, memory_op, cfg）；memory 有注册表（simple/no/sibling/ancestral）；analyze 用 JSON schema 结构化输出 |
| **搜索拓扑** | 可插拔三策略：greedy（ε_bug）/ MCTS（UCT, c=0.25, 无 rollout, 叶值=ℱ, expansion=5 子节点）/ evolutionary（比例选择+improve/crossover+劣者替换+岛模型）；π_op 仍为规则式（种子数够→debug 若 buggy→否则 improve） |
| **持久状态** | Journal（搜索图）+ 作用域 memory（兄弟/祖先）+ **checkpointing**（state.json + journal.jsonl，支持 Slurm 断点续跑） |
| **反馈权限** | Jupyter 执行的 status/stdout/traceback/耗时；analyze 算子解析验证 fitness；**test fitness 在 run 内计算但对 agent 不可见**（防泄漏，仅供事后分析）；评审用 GPT-4o Structured Outputs 与编码 LLM 解耦 |
| **失败利用** | buggy 子节点进入自动 debug 循环（上限 10 节点或 12h）；debug 用祖先记忆避免 undo-redo 振荡；无效 submission 被显式删除防作弊 |
| **并行与选择** | 单 run 串行；Runner 层 Slurm job array 并行 1000 agents；evo 每代 5 候选、MCTS 每次 expansion 5 子节点；最终按验证分选节点（oracle 实验显示该环节有 9-13 点提升空间） |

---

## 5. 对统一框架的接口启示

### 5.1 应借鉴的模块划分

1. **以五元组 (ℱ, π_sel, 𝒪, π_op, τ) 作为框架的语义内核**[^10^]。AIDE 证明最小可行形态（π 与 f 硬编码进一个 Agent 类）也能 SOTA，但 AIRA 证明只有五元组显式化后才能做「固定其他因子、单变量消融」的科学研究，这正是「可配置框架」的存在意义。

2. **四层分离的架构骨架**（来自 AIRA-dojo）[^13^][^15^][^14^]：
   - `Task`（环境+fitness）：`prepare() / step_task(state, action) / evaluate_fitness() / close()`；
   - `Solver`（= 算子集 + 搜索策略）：`__call__(task, state)` + checkpoint；
   - `Interpreter`（执行沙箱）：`run(code) -> ExecutionResult{term_out, exec_time, exc_type, ...}`；
   - `Runner`（并行编排，与单机搜索逻辑解耦）。
   各层通过 registry（TASK_MAP/SOLVER_MAP/INTERPRETER_MAP）+ 组合式配置（Hydra）装配[^19^]。

3. **算子接口标准化**：`op(llm, cfg, memory_op, task_desc, journal, *input_nodes, budget_info...) -> completion`；输入节点数可变（draft=0、improve/debug=1、crossover=2）对应 `o: 2^𝒮→𝒮`；所有算子共享「生成→抽取 plan/code→重试」的包装器；**memory 作为一等可注入算子**（注册表 + 作用域：global/sibling/ancestral/none）[^17^][^18^]。

4. **节点数据类型**：AIDE 的 `Node`（code/plan/exec 结果/analysis/MetricValue/is_buggy）是优良起点，但需两处扩展——(a) 支持**多父节点**（crossover/合并类算子需要，dojo 已改）；(b) 预留策略私有统计字段（MCTS 的 N/Q、evo 的 island id），可用 mixin/子类（dojo 的 `MCTSNode(Node)`）[^4^][^24^]。`MetricValue` 把优化方向内化进可比较类型、用 WorstMetricValue 统一表示失败，值得直接照搬[^9^]。

5. **反馈/评审独立成算子**：analyze/review 用结构化输出（JSON schema: is_bug, summary, metric），且**评审模型与生成模型解耦配置**（AIDE: o4-mini 写码 + gpt-4.1-mini 评审；AIRA: R1/o3 写码 + GPT-4o 评审）[^3^][^26^][^10^]。

6. **防泄漏的评估契约**：搜索内只暴露 proxy/validation fitness；test fitness 可在 run 内计算但仅写入结果 dict 供事后分析；无效产物（submission.csv）显式删除防止错误结果污染后续步骤[^20^]。

7. **checkpointing 与日志是一等公民**：长时运行（24-120h）下硬/软故障必然发生；solver state + journal 的可序列化应在接口层强制（dojo 的 `save_checkpoint/load_checkpoint` 抽象方法）[^14^][^10^]。

8. **prompt 即配置**：算子 prompt 用模板文件（Jinja）+ YAML 声明，而不是嵌在代码里（AIDE 的 dict-prompt 方式难以做算子级 A/B）；预算信息（剩余时间/剩余步数/执行超时）作为模板变量注入[^22^]。

9. **最终节点选择独立成模块**：E6 显示该环节值 9-13 个绝对点；框架应暴露 final-selection 接口（top-k 验证分 + 重评估/集成/多提交），而非默认 argmax(validation)[^10^]。

### 5.2 被证明不重要（或优先级低）的设计

- **全局记忆算子**：memory on/off 几乎无差（38.18% vs 39.77%）——框架应支持 `no_memory`，不要把记忆做成必选件[^10^]。
- **在弱算子下升级搜索拓扑**：MCTS 探索常数 c∈{0..0.75} 不敏感、evo/MCTS 相对 greedy 无增益——**先投资算子质量，再投资拓扑**；框架的默认策略用 greedy 即可，把拓扑做成可选插件[^10^]。
- **复杂的 operator policy π_op**：两个系统都用规则式 π_op（种子数→buggy→改进），未成为瓶颈；可暂缓做成学习型组件。
- **AIDE 的容器隔离**：AIDE 仅用子进程+目录隔离即可跑出 SOTA；但 AIRA §14 说明规模化后隔离是刚需（环境被 pip 污染、agent 间干扰）——隔离属于「规模扩展前提」而非「算法正确性前提」[^10^]。

### 5.3 需要超越这两个系统的设计空白

- **agentic 算子**：两系统的算子都是单次 LLM 调用；AIRA 展望把 SWE-Agent、ideation agent 作为算子——框架的算子接口应允许算子本身是嵌套搜索/agent[^10^]。
- **算子级并行**：两系统单 run 内都是串行；MCTS expansion/evo 每代多个子节点天然可并行，框架应在 Runner 之下再提供节点级并行原语。
- **过拟合控制/正则化**：长时搜索下过拟合是共同瓶颈（E6、90h 实验）；框架可在 ℱ 接口上内建 holdout 轮换、early-stop、复杂度惩罚等正则钩子[^10^]。
- **跨任务记忆**：两系统都按任务独立（Agent K 式跨竞赛记忆被显式排除）——持久状态接口可预留跨 run 的知识库[^10^]。

---

## 参考来源

[^1^]: AIDE 论文：Jiang et al., "AIDE: AI-Driven Exploration in the Space of Code", arXiv:2502.13138, https://arxiv.org/html/2502.13138 （访问 2026-08-05）。形式化（Algorithm 1、π/f/Σ）、MLE-bench/RE-Bench/Weco-Kaggle 结果、§3.2 设计细节。
[^2^]: aideml 仓库文件树，https://github.com/WecoAI/aideml （访问 2026-08-05，via GitHub API）。
[^3^]: aide/agent.py 源码（Agent.search_policy/_draft/_improve/_debug/parse_exec_result、review_func_spec），https://github.com/WecoAI/aideml/blob/main/aide/agent.py （访问 2026-08-05）。
[^4^]: aide/journal.py 源码（Node/Journal/generate_summary），https://github.com/WecoAI/aideml/blob/main/aide/journal.py （访问 2026-08-05）。
[^5^]: aide/utils/config.yaml（全部配置项及默认值），https://github.com/WecoAI/aideml/blob/main/aide/utils/config.yaml （访问 2026-08-05）。
[^6^]: aide/run.py（主循环 run()），https://github.com/WecoAI/aideml/blob/main/aide/run.py （访问 2026-08-05）。
[^7^]: aide/backend/__init__.py（query 统一接口、determine_provider 路由），https://github.com/WecoAI/aideml/blob/main/aide/backend/__init__.py （访问 2026-08-05）。
[^8^]: aide/interpreter.py（ExecutionResult、Interpreter.run），https://github.com/WecoAI/aideml/blob/main/aide/interpreter.py （访问 2026-08-05）。
[^9^]: aide/utils/metric.py（MetricValue/WorstMetricValue），https://github.com/WecoAI/aideml/blob/main/aide/utils/metric.py （访问 2026-08-05）。
[^10^]: AIRA 论文：Toledo et al., "AI Research Agents for Machine Learning: Search, Exploration, and Generalization in MLE-bench", arXiv:2507.02554, https://arxiv.org/html/2507.02554 （访问 2026-08-05）。五元组（§2.1）、AIDE 重铸（§2.3/§9）、𝒪_AIRA（§4.1）、三策略（§4.2）、全部控制实验（§5.1-5.3、Fig.3-6）、泛化差距、90h 实验（§10）、完整 MLE-bench（§11）、实现细节与超参（§12）、基础设施教训（§14）、种子方差建议（§16）。
[^11^]: aideml README（CLI 用法、生态位说明、衍生工作表），https://github.com/WecoAI/aideml/blob/main/README.md （访问 2026-08-05）。
[^12^]: aira-dojo README（Task/Solver/Run/Runner 术语、并行规模、示例命令），https://github.com/facebookresearch/aira-dojo （访问 2026-08-05）。
[^13^]: aira-dojo docs/PROJECT_STRUCTURE.md（目录与组件说明、Hydra 配置系统），https://github.com/facebookresearch/aira-dojo/blob/main/docs/PROJECT_STRUCTURE.md （访问 2026-08-05）。
[^14^]: src/dojo/core/solvers/base.py（Solver ABC、checkpoint 接口），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/solvers/base.py （访问 2026-08-05）。
[^15^]: src/dojo/core/tasks/base.py（Task ABC 四方法契约），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/tasks/base.py （访问 2026-08-05）。
[^16^]: src/dojo/solvers/greedy/greedy.py（Greedy solver、setup_operators 依赖注入、search_policy），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/solvers/greedy/greedy.py （访问 2026-08-05）。
[^17^]: src/dojo/core/solvers/operators/memory.py（MEM_OPS 注册表、四种 memory 作用域），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/solvers/operators/memory.py （访问 2026-08-05）。
[^18^]: src/dojo/core/solvers/operators/improve.py（算子函数签名），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/solvers/operators/improve.py （访问 2026-08-05）。
[^19^]: src/dojo/main_run.py（build+registry 装配流程）与 src/dojo/core/solvers/operators/core.py（execute_op_plan_code 包装器），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/main_run.py （访问 2026-08-05）。
[^20^]: src/dojo/tasks/mlebench/task.py（step_task 防泄漏评估、submission 校验与删除），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/tasks/mlebench/task.py （访问 2026-08-05）。
[^21^]: src/dojo/configs/solver/mlebench/greedy.yaml（算子集混搭与搜索超参配置），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/configs/solver/mlebench/greedy.yaml （访问 2026-08-05）。
[^22^]: src/dojo/configs/solver/operators/mlebench/aira_operators/draft.yaml（Jinja prompt 模板、复杂度条件块、预算变量），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/configs/solver/operators/mlebench/aira_operators/draft.yaml （访问 2026-08-05）。
[^23^]: src/dojo/solvers/evo/evo.py（Island/SolutionsDatabase/Evolutionary）与 operators/crossover.py（二元算子签名），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/solvers/evo/evo.py （访问 2026-08-05）。
[^24^]: src/dojo/solvers/mcts/mcts.py（MCTSNode、uct_value、_backprop_step），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/solvers/mcts/mcts.py （访问 2026-08-05）。
[^25^]: src/dojo/core/tasks/constants.py（task-solver 通信 key 契约），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/tasks/constants.py （访问 2026-08-05）。
[^26^]: src/dojo/core/solvers/operators/analyze.py（结构化评审 schema），https://github.com/facebookresearch/aira-dojo/blob/main/src/dojo/core/solvers/operators/analyze.py （访问 2026-08-05）。
[^27^]: src/dojo/core/solvers/llm_helpers/generic_llm.py（GenericLLM 封装）与 docs/SOLVER_DEVELOPMENT.md（算子/求解器开发指南、策略-算子对照表），https://github.com/facebookresearch/aira-dojo/blob/main/docs/SOLVER_DEVELOPMENT.md （访问 2026-08-05）。
