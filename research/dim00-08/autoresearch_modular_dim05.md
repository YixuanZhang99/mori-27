# Dim 05 · LoongFlow + FM Agent：Population 进化与多样性保持机制深读

> 调研单元：LoongFlow (arXiv:2512.24077) 与 FM Agent (arXiv:2510.26144)，重点为 population 进化、多样性量化/维护/选择压力注入，以及与"语义假设管理"（Arbor hypothesis tree）的兼容性。
> 一手来源：两篇 arXiv HTML/PDF 全文、两个官方仓库（含 LoongFlow 进化记忆模块源码级精读）、FM Agent 官方技术报告 PDF、MLE-bench 官方 leaderboard 记录。

---

## 1. 各系统核心机制（伪代码级主循环）

### 1.1 LoongFlow：PES 认知范式 + 混合进化记忆

LoongFlow 把进化搜索形式化为离散代码空间上的 MDP ⟨𝒞, 𝒜, R, π_θ⟩，LLM 作为**可组合的语义算子**（composite transition kernel），一次"变异"被分解为三个潜变量步骤：先由 Planner 生成自然语言蓝图 b ~ π_θ(b | s_t, ℳ_t)，再由 Executor 生成代码 s' ~ π_θ(s' | b, s_t)，最后 Summarizer 依据评估反馈 r = R(s') 生成反思 insight z 并写回记忆 ℳ_{t+1} ← ℳ_t ∪ {z} [^1^]。即"变异"= 假设提出（Plan）→ 受控实验（Execute）→ 因果归因（Summarize），把随机变异升级为定向假设检验。

主循环（论文 Algorithm 1 的忠实转写）[^1^]：

```
输入: 任务 T, 初始解 s0, 最大迭代 N_max, 岛数 K
ℳ ← {s0}; 初始化 K 个岛, 每岛一个 MAP-Elites archive 𝒜_k
for iteration = 1 .. N_max:
    for k = 1 .. K:                        # 岛间并行
        # (1) 自适应选择
        H_k ← CalculateEntropy(𝒜_k)        # 种群熵
        τ   ← τ_base · (1 + α·e^{-β·H_k})  # 动态温度
        s_parent ← BoltzmannSelect(𝒜_k, τ)
        # (2) 谱系规划 (lineage-based planning)
        chain   ← GetLineage(s_parent.id)  # 沿 parent_id 回溯祖先链
        context ← {p.plan, p.summary | p ∈ chain}   # 意图追踪 + 教训
        plan    ← Planner(s_parent, context, T)
        # (3) 执行与评估
        code ← Executor(plan, s_parent)
        if not Verify(code): continue      # 本地 fast-fail（语法/导入错误）
        score, logs ← Evaluator(code)
        # (4) 反思与入库
        summary ← Summarizer(plan, code, logs)
        s_new ← Solution(code, score, summary, parent=s_parent.id)
        UpdateMAPElites(𝒜_k, s_new)
    # (5) 周期性迁移
    if iteration mod M == 0: MigrateElites(𝒜_1..𝒜_K)
return argmax_{s ∈ ∪𝒜_k} s.score
```

三个关键的结构性设计 [^1^]：

- **Lineage-based memory**：每个 Solution 携带 `parent_id / generate_plan / summary / island_id / score / sample_cnt / sample_weight / generation` 等完整谱系元数据（论文 Listing 1，与仓库 `base_memory.py` 中的 `Solution` dataclass 完全一致 [^4^]）。Planner 不靠 RAG 式模糊语义检索，而是沿 parent_id 链回溯，读取祖先的"原始意图（plan）"与"事后教训（summary）"——意图追踪（了解研究轨迹）+ 航向修正（避开已验证的坑）。
- **Hybrid Evolutionary Memory** = Multi-Island（环形拓扑）× 岛内 MAP-Elites（行为网格）× 熵正则化 Boltzmann 选择，三层分别对应空间隔离、利基保持、探索-利用自调节 [^1^]。
- **Executor 的 Polymorphic Execution + 本地 fast-fail**：执行策略可插拔（单轮 Chat / 多轮 ReAct / 自适应 Fuse），提交全局评估前先做预检查，挡住低质候选，节省昂贵评估 [^1^]。

### 1.2 FM Agent：Cold Start + Island Evolve 两阶段 + Ray 异步基础设施

FM Agent 是"通用研究 agent"定位的两阶段框架 [^7^][^9^]：

```
阶段 A: Cold Start（冷启动）
  并行启动多种异构生成 agent（差异化配置/不同优化方向），
  可选 expert-in-the-loop 指导，快速产出 高多样性 + 高质量 的初始解池;
  主动引导各 agent 探索目标空间的不同区域（proactive solution space expansion）。

阶段 A→B: 初始种群划分
  对冷启动解池按解间相似度聚类，簇数 = 岛数，
  以"岛间相似度最大化"为目标把簇分配给各岛（保证岛间算法族差异最大）。

阶段 B: Evolve（岛模型进化）
  loop:
    每岛独立进化（mutation + crossover，岛内核内大部分时间隔离）;
    岛内: Adaptive Diversity-Driven Sampling
      - 语义 + 结构度量实时监控种群多样性;
      - cluster-based sampling 按当前多样性动态调节选择压力;
      - elite pool 保留历代最优解指导后续生成;
    岛间: 周期性交互/迁移，交叉授粉防停滞;
  评估器: 正确性 + 有效性 + LLM judge 反馈的多面评分（domain-specific）。

基础设施: Ray 编排; 生成池与评估池分离的异步流水线
  （synthesis 与 evaluation 互不阻塞，支持数千并发进化进程）。

可选: Human-Interactive Feedback（实时监控 fitness/多样性曲线,
  自然语言或代码级干预; RAG 知识库检索增强 mutation/crossover）。
```

值得注意的工程事实：FM-Agent 开源仓库只包含科学工作流示例与 agent 配置，**未公开核心进化引擎源码**；进化机制细节只能以论文/技术报告为准，论文对 cluster-based sampling 的具体公式、岛数、迁移周期均刻意保持高层描述 [^8^][^9^]。

---

## 2. 多样性机制的接口分析（重点）

### 2.1 Archive/种群的数据结构

**LoongFlow**（源码级证据 [^3^][^4^][^5^][^6^]）：

```python
@dataclass
class Solution:                # base_memory.py
    solution: str              # 代码本体
    solution_id / parent_id    # 谱系链（显式系谱指针）
    generate_plan: str         # 产生该解的蓝图（语义假设！）
    summary: str               # 评估后的反思 insight
    score / evaluation         # 标量适应度 + 原始评估文本
    island_id / generation / iteration
    sample_cnt / sample_weight # 采样统计（反重复采样压力）
    metadata: Dict             # 开放扩展槽（如 migrated 标记）
```

存储层是 `EvolveMemory` 抽象基类（`add_solution / get_solutions / list_solutions / get_best_solutions / sample / save_checkpoint / load_checkpoint / memory_status / update_solution`），有 `InMemory` 与 `Redis` 两种实现，配置项 `num_islands=3, population_size=100, elite_archive_size=50, migration_interval=10` [^6^]。每个岛内部维护三类结构：**islands**（solution_id 集合）、**island_feature_maps**（MAP-Elites 网格：feature_key → solution_id，每格只留最优）、**elites**（按 score 维护的 elite archive，容量 elite_archive_size，新解须优于最差精英才替换）[^5^]。feature map 与 elite archive 联动：格子内 incumbent 被更优者替换时，若 incumbent 在 elites 中则同步替换 [^5^]。

**FM Agent**：论文未给出数据结构级定义，可确认的概念实体为：初始解池（cold start 产出）、按相似度聚类的簇→岛映射、岛内 population、**curated elite pool**（保留 top 解指导后续生成）、以及支撑它们的分布式 database（case study 提到 "sampling and database management"）[^7^]。

### 2.2 距离/行为度量

**LoongFlow 的 behavior descriptor**（论文 vs 实现有出入，均需记录）：

- 论文：Φ: 𝒞→ℱ⊆ℝᵏ 把代码映射到可解释特征向量，示例为 v =（圈复杂度， 代码长度）或（代码复杂度 × 内存占用）；MAP-Elites 在 ℱ 上离散成网格，每格保留该行为下最优解 [^1^]。
- 实现：默认 `feature_dimensions = ["complexity", "diversity", "score"]`——complexity = 代码字符长度；diversity = 该解与一个**贪心构造的最大多样性参考集**（默认 20 个参考解）之间的平均"代码差异度"；score = 归一化适应度本身也作为一维 descriptor。每个维度用在线 min-max（或 percentile）统计缩放到 [0,1] 后分桶，`feature_bins ≈ elite_archive_size^(1/dims)` [^4^][^5^]。
- **距离函数是浅层文本启发式**而非语义嵌入：`_fast_code_diversity = 0.1·|Δlen| + 10·|Δlines| + 0.5·|独有字符数|`；种群多样性（供温度调节用）为抽样解对的 `0.4·len_diff + 0.3·line_diff + 0.3·char_set_diff` 均值 [^3^][^4^]。这是重要的机制级发现：**LoongFlow 论文宣称的"population entropy"在实现中实为代码文本代理多样性**，且论文公式 τ ∝ exp(−λ·H) 与实现 `τ = clip(base·(1+2·diversity−1), 0.5, 2.0)`（再与当前温度 0.8/0.2 混合）方向一致但形式不同 [^1^][^3^]。

**FM Agent**：明确使用**语义 + 结构（semantic and structural）双路度量**做多样性保持；冷启动后的分岛按"岛间最大相似度"聚类划分（即最小化岛间相似、保持算法族分离）。具体嵌入模型/公式未公开 [^7^]。

### 2.3 选择算子的契约

**LoongFlow `sample()` 的实际契约**（boltzmann.py [^3^]）：

```
select_parents_with_dynamic_temperature(
    solutions, elites, initial_temp,
    min_temp=0.5, max_temp=2.0,
    use_sampling_weight=True, sampling_weight_power=1.0,
    exploration_rate=0.2) -> Solution
```

1. 以 `exploration_rate`（默认 0.2）概率纯随机返回一个解（ε-greedy 兜底探索）；
2. 否则构造 5 个候选：3 个来自 elites + 2 个来自非精英（60/40 精英偏向）；
3. 候选上计算 `p ∝ exp((score − max_score)/τ) · sample_weight^power`，归一化后轮盘赌；
4. τ 由当前种群多样性自适应（多样性低→τ 升→趋均匀探索；多样性高→τ 降→趋贪心利用），并有 min/max 截断与惯性混合保证平稳；
5. `sample_weight` 把"被采样次数"纳入选择压力（反重复利用同一亲本）。

即选择算子的输入契约是 **(score, sample_weight, diversity→τ, elite 标签)**，输出单个亲本；多样性不直接作为个体被选择的概率项，而是通过**温度这个全局旋钮**间接注入压力。

**FM Agent**：cluster-based sampling 按实时种群多样性**动态调节选择压力**（多样性低→偏向跨簇探索，高→偏向簇内利用），elite pool 作为稳定的优质亲本来源；论文给出的对照基线是 random sampling（纯探索）与 top-k sampling（纯利用），其 adaptive 方法在两者间自适应 [^7^]。与 LoongFlow 的"温度旋钮"相比，FM Agent 的旋钮作用在**簇级配额**上——多样性以簇为单位显式进入采样分布。

### 2.4 迁移触发条件

**LoongFlow**（论文 vs 实现再次有差异）：

- 论文：环形拓扑；**当相邻岛间多样性差 ΔD 超过阈值时**触发迁移，top k% 精英复制到邻岛充当"入侵物种" [^1^]。
- 实现：触发器是**间隔式**——`max(island_capacity) − last_migration_generation ≥ migration_interval`（默认 10 代）；每岛按 score 排序取前 `migration_rate=0.2` 的解，复制（非移动）到环形邻居 `(i±1) mod N`，带 `migrated` 元数据标记防重复迁移、带代码逐字查重防重复注入；迁移副本保留原 plan/summary/sample_weight [^5^]。注释自承"Adapted from OpenEvolve database.py"。
- 另有 OpenEvolve 式岛重置机制的痕迹（论文图 2 出现 "reset island"），论文正文未展开 [^1^]。

**FM Agent**：仅描述为"周期性岛间交互/交叉授粉"，触发条件、迁移配额未公开 [^7^]。其独特性在于**岛的形成本身**就是多样性优化的结果——冷启动解池按最大岛间相似度聚类划分，岛在初始化时刻就对应不同的算法族 [^7^]。

---

## 3. 关键设计决策与权衡（含消融证据）

### 3.1 LoongFlow

| 决策 | 权衡 | 消融/实验证据 |
|---|---|---|
| PES 三段式替代单步变异 | 每次迭代 3 次 LLM 调用（更贵/次），换方向性与可归因性 | Planner 消融：最高分停滞在 0.96 以下，达到 Top-1 时间从 9.67h→14.67h；Summary 消融：出现"循环错误"，一次试验 35h 未破 0.95；完整模式达 0.998 [^1^] |
| Executor Fuse 模式（Chat vs ReAct 自适应切换） | Chat 轻量但不稳；ReAct 稳但低效；Fuse 动态分配算力 | Fuse 模式取得最高渐近分 0.998 与最优样本效率 [^1^] |
| Lineage 检索替代 RAG 语义检索 | 只能沿谱系回溯（局部上下文），换检索精确性与零嵌入成本 | 论文动机性论证：记忆从"高分榜"升级为"结构化知识图谱"，支持因果查询 [^1^] |
| MAP-Elites 利基保持 | 网格内存与维护成本；descriptor 需人工/启发式设计 | 论文层面：防 Top-K 采样丢失"垫脚石"解；实现层面 descriptor 退化为代码长度/文本差异/score 三维，语义性弱 [^1^][^4^] |
| 熵/多样性自适应 Boltzmann | 引入 min/max_temp、混合系数等超参；多样性度量本身粗糙 | 无独立消融（多样性机制整体未单独消融，是论文弱点） |
| 效率主张 | 258 次评估达 0.99 vs OpenEvolve 783 次（>60% 效率提升）；3/3 vs 1/3 成功率；Gemini-3-Pro 100 迭代内 3/3 突破理论壁垒（基线 0/3） [^1^] | MLE-bench 官方 leaderboard：LoongFlow 62.66%（Famou-Agent 2.0 为 64.44%），test-set feedback 标注为 "Hill Climbing" [^10^] |

### 3.2 FM Agent

| 决策 | 权衡 | 消融/实验证据 |
|---|---|---|
| 专家指导冷启动 | 引入人先验/专家成本，换初始种群质量与多样性 | 消融（ahc016，5 次平均）：cold start 提供显著初始优势、加速早期收敛；三组件（cold start + adaptive sampling + island）有协同效应，Full Method 最优 [^7^] |
| 相似度聚类分岛 | 需计算全对相似度；簇数=岛数是硬绑定 | island model 消融：通过促进多样性，中期即达到基线峰值水平 [^7^] |
| cluster-based adaptive sampling | 实现复杂、需维护簇结构；比 top-k 慢收敛于单点但更抗早熟 | adaptive 最终得分 0.7182，**比 top-k 高 10.99%、比 random 高 58.26%**；且第 40 代即超过 random 的峰值（random 需 900 代）[^7^] |
| elite pool | 保留最优解指导生成，代价是精英偏向/潜在早熟 | 与 adaptive sampling 组合使用，无单独消融 |
| Ray 异步生成-评估双池 | 基础设施复杂度高，换吞吐（数千并发） | 论文定性主张；case study 显示前 25 代 best score 快速跃升、个体分数方差先大后小（探索→利用转换的定性证据）[^7^] |
| 领域专用多面评估器（正确性+有效性+LLM judge） | 评估成本；反馈信号更稠密 | ALE-Bench 1976.3（+5.2% vs ALE-Agent；+64.6% vs iterative refinement）；MLE-bench 43.56%（当时榜首）；KernelBench 最高 20.77× [^7^][^8^] |

### 3.3 两系统对照：多样性如何被"量化—维护—注入压力"

| 环节 | LoongFlow | FM Agent |
|---|---|---|
| 量化 | 代码文本启发式差异度（长度/行数/字符集），逐解对参考集计算；种群级聚合为"多样性/熵"代理 | 语义 + 结构度量；簇间相似度（具体度量未公开） |
| 维护 | MAP-Elites 网格（每格一精英）+ 岛隔离 + elite archive；种群超限时淘汰最低分 | 岛=相似度聚类的算法族；cluster 结构持续维护；elite pool 保底 |
| 注入选择压力 | 间接：多样性→温度 τ→Boltzmann 分布锐度；另有 ε=0.2 随机探索 + elite:non-elite=3:2 候选构造 + sample_weight | 直接：cluster-based 采样按实时多样性调簇级选择压力；elite pool 引导 |
| 初始多样性 | 单初始解 s0，靠进化过程展开 | 专门的 cold start 阶段，多异构 agent 并行+主动空间扩展 |
| 跨域迁移 | 间隔触发（实现）/ΔD 阈值（论文），环形邻岛，top 20% 复制 | 周期性交互（未公开细节） |

---

## 4. 八轴卡

| 轴 | LoongFlow | FM Agent |
|---|---|---|
| **优化对象** | 代码解（算法发现 / ML pipeline），标量 fitness R:𝒞→ℝ | 通用"程序/算法"（OR、ML pipeline、CUDA kernel、数学构造），多维 domain-specific fitness |
| **基本搜索单元** | `Solution`：代码 + 谱系元数据（plan/summary/parent_id），即"解 + 产生它的假设 + 它的教训" | 程序 + 评估记录；单元级元数据未公开 |
| **算子** | LLM 复合语义算子 PES：Plan（定向假设）→ Execute（可插拔实现 + fast-fail）→ Summarize（溯因反思）；无显式 crossover（靠迁移副本做跨岛授粉） | LLM mutation + crossover（岛种群内）；人类/RAG 知识可增强算子 |
| **拓扑** | K 岛 × 岛内 MAP-Elites 网格 × 环形迁移 | K 岛（由相似度聚类生成）× 簇结构 × 周期交互 |
| **持久状态** | 进化记忆 ℳ：Solution 图谱（谱系链 + insight）+ 每岛 feature map + elite archive + checkpoint（InMemory/Redis 双实现） | 分布式 database：解池/岛/elite pool + 外部知识库（RAG） |
| **反馈权限** | 评估分数 + logs 全部回流 Summarizer→Planner（闭环反思）；本地预检查拦截无效评估 | 评估器多维反馈（正确性/有效性/LLM judge）；可选人类实时干预（NL 指令/代码级） |
| **失败利用** | 显式：Summarizer 把"意图 vs 结果"差异归因为 insight，沿谱系传给后代 Planner，消除循环错误（消融证实） | 隐式：低分个体经采样压力自然淘汰；LLM judge 定性反馈指导 refinement；无专门的失败归因记忆 |
| **并行与选择** | 岛级并行；Boltzmann(τ(diversity)) + ε-随机 + 精英偏向候选 + sample_weight | Ray 大规模异步（生成池/评估池分离，数千并发）；cluster-based adaptive sampling + elite pool |

---

## 5. 对统一框架的接口启示

### 5.1 两个系统事实上收敛到同一个模块分解

LoongFlow 的 `EvolveMemory` ABC 已经是一个准标准接口：`add_solution / sample / get_best_solutions / memory_status / checkpoint` [^4^][^6^]；FM Agent 的概念架构（解池-岛-elite pool-sampler-database）与之同构 [^7^]。统一框架可把"Archive/Population"定义为如下契约（前沿管理器 FrontierManager）：

```python
class Individual(Protocol):
    id: str; parent_id: str | None
    artifact: str                    # 代码/配置/pipeline
    fitness: float | dict            # 标量或多维
    descriptor: BehaviorDescriptor   # ← 关键扩展点
    provenance: dict                 # plan/summary/hypothesis/operator trace
    sampling_stats: dict             # sample_cnt, sample_weight...

class FrontierManager(Protocol):
    def add(ind: Individual) -> AddOutcome: ...      # 准入策略：MAP-Elites 格替换 / elite 替换 / 树节点挂载
    def sample(context: SampleContext) -> Individual: ...  # 亲本选择：Boltzmann / cluster-adaptive / UCB-on-tree
    def frontier() -> list[Individual]: ...          # 当前前沿（elites/格子/树叶）
    def diversity() -> DiversityReport: ...          # 多样性观测量（供控制器与监控）
    def migrate(other: "FrontierManager") -> None: ...     # 迁移/合并（岛间、树间）
    def checkpoint() / restore(): ...
```

配置维度自然浮现为三个正交旋钮：

1. **准入结构（niche 组织）**：`flat-elite-pool`（FM Agent）| `map-elites-grid(descriptor, bins)`（LoongFlow）| `tree(hypothesis)`（Arbor 式）——三者只是 `add()` 的不同路由策略；
2. **拓扑（空间隔离）**：`single` | `islands(K, topology=ring, migration=interval|ΔD-threshold, rate)` —— 迁移触发器应支持 interval（LoongFlow 实现）、阈值（LoongFlow 论文）、periodic（FM Agent）三种策略，迁移内容=elite 副本+provenance；
3. **选择压力控制器**：`boltzmann(τ=f(diversity))` | `cluster-adaptive(pressure=g(diversity))` | `top-k/random` —— 两系统的消融一致表明 adaptive 显著优于两端基线（FM Agent：+10.99% vs top-k，+58.26% vs random [^7^]），因此"多样性→压力"的反馈回路应是框架一等公民，而非算子内部细节。

### 5.2 语义假设能否作为 behavior descriptor？

**可以，且两系统已各走了一半路；证据链如下：**

- LoongFlow 的 Solution 已经把**语义产物**（generate_plan = 产生该解的假设/意图，summary = 反思）与代码绑定存储，并用谱系链做检索——但其 MAP-Elites descriptor 仍退化为代码长度/文本字符差异这类浅层代理 [^4^]。这是明显的升级空间：把 `plan` 的嵌入或假设类别直接作为 descriptor 维度，archive 就从"行为网格"变成"假设网格"。
- FM Agent 宣称用语义+结构度量做多样性 [^7^]，说明工业级系统已经在用（未公开的）语义距离。
- 外部先例支持可行性：GSME 用**诊断模型从失败轨迹指派的"病理类型"（pathology）作为 categorical descriptor** 构建 MAP-Elites，每格一个 gated elite，并证明语义标签只 steering 探索、不参与 credit 时对标签噪声优雅降级 [^11^]；ACES 用 LLM 打分的语义特征向量作为 archive 维度，语义空间的多样性优化同时提升嵌入空间多样性 [^12^]；QD-LLM 用 SBERT 嵌入+显式特征的混合 descriptor，并给出覆盖数的理论界 [^13^]。
- 与 Arbor hypothesis tree 的兼容性：Arbor 的 hypothesis tree 本质是一个**按语义假设组织的准入结构**（节点=假设+证据+失败归因，coordinator 决定扩展/剪枝/合并）[^14^]。在 FrontierManager 视角下，它只是 `add()` 的第三种路由：新个体按其 hypothesis 挂到树节点，而非落入网格 cell。统一接口的关键在于 **descriptor 抽象要同时容纳"连续向量（嵌入）、结构化特征（复杂度等）、范畴标签（假设/病理类型）"三种形态**，且 `diversity()` 与选择压力控制器只对 descriptor 空间操作、不关心其语义来源。

**需要注意的陷阱**（供框架设计参考）：(i) 语义 descriptor 由 LLM 指派时存在标签噪声——GSME 的对策是"标签只影响探索、准入门槛只看门控质量" [^11^]；(ii) LoongFlow 论文与实现之间的落差（entropy→文本代理、ΔD 阈值→间隔触发）提醒我们：声明的语义机制在工程实现中常被浅层代理替代，框架应把 descriptor 的可解释性/保真度作为可观测指标暴露；(iii) 多样性度量若基于 plan/hypothesis 文本，可防止"代码表面不同但策略相同"的伪多样性——这正是 LoongFlow 浅层度量和 FM Agent 语义度量之间的本质差别。

---

## 参考来源

- [^1^] LoongFlow: Directed Evolutionary Search via a Cognitive Plan-Execute-Summarize Paradigm, arXiv:2512.24077, https://arxiv.org/html/2512.24077v1 （全文：问题形式化 §3、Algorithm 1、PES §4.1、混合进化记忆 §4.2、实验与消融 §5）
- [^2^] LoongFlow 官方仓库 README, https://github.com/baidu-baige/LoongFlow
- [^3^] LoongFlow 源码 `src/loongflow/agentsdk/memory/evolution/boltzmann.py`（多样性计算、自适应温度、带权 Boltzmann 选择）
- [^4^] LoongFlow 源码 `src/loongflow/agentsdk/memory/evolution/base_memory.py`（Solution dataclass、EvolveMemory ABC、MAP-Elites 特征坐标/分桶、参考集多样性）
- [^5^] LoongFlow 源码 `src/loongflow/agentsdk/memory/evolution/in_memory.py`（岛/elite archive/MAP-Elites 更新、迁移触发与复制逻辑、sample 契约）
- [^6^] LoongFlow 文档 `docs/en/components/memory/evolution.md`（默认配置 num_islands=3, population_size=100, elite_archive_size=50, migration_interval=10）
- [^7^] The FM Agent, arXiv:2510.26144, https://arxiv.org/html/2510.26144v1 （§3 Framework：Cold Start/Evolve/Infra/Human-Interactive；§4 实验；§5 Case Study；§6 Ablation：adaptive sampling 0.7182、+10.99%/+58.26%；三组件消融）
- [^8^] FM Agent 官方仓库 README, https://github.com/baidubce/FM-Agent
- [^9^] FM Agent 技术报告 PDF（仓库 docs/FMAgent_TechReport.pdf，与 arXiv 版内容一致；仓库未含核心进化引擎源码，已核实文件树）
- [^10^] openai/mle-bench Issue #138 leaderboard 表（LoongFlow 62.66%、Famou-Agent 2.0 64.44%、Famou-Agent 43.56%；LoongFlow test-set feedback 标注 "Hill Climbing"）, https://github.com/openai/mle-bench/issues/138
- [^11^] Self-Evolving Agent Harnesses via Gated Semantic Quality-Diversity (GSME), arXiv:2607.13683, https://arxiv.org/html/2607.13683v1 （pathology 作为 categorical semantic descriptor；gated elite；quality-biased 选择 + 跨格重组）
- [^12^] ACES: Generating Diverse Programming Puzzles with Autotelic Language Models and Semantic Descriptors, OpenReview, https://openreview.net/pdf/26a6b00bacff76bfcb91a6f75bc718517ccc44b3.pdf
- [^13^] Parameter-Efficient Neuroevolution for Diverse LLM Generation (QD-LLM), arXiv:2605.09781, https://arxiv.org/html/2605.09781v2
- [^14^] Toward Generalist Autonomous Research via Hypothesis-Tree Refinement (Arbor), arXiv:2606.11926, https://arxiv.org/html/2606.11926v1 （persistent hypothesis tree：假设/证据/失败归因/insight 传播；coordinator-executor 架构）
