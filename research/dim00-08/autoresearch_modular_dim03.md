# Dim-03 调研报告：MARS + 成本敏感/预算感知的 AutoResearch 搜索

> 调研单元：MARS (arXiv:2602.02660) 机制级深读 + 成本敏感搜索经典机制（multi-fidelity / SH / Hyperband / early stopping）+ 预算分配策略（方向级 vs 候选级）。
> 调研方法：arXiv HTML（ar5iv）全文精读 + 官方仓库（jfc43/MARS、karpathy/autoresearch、autoresearch-speedrun、NanoGPT-Bench）+ 一手论文 12+ 次独立检索/阅读。

---

## 0. TL;DR

- **MARS 的成本建模非常"轻"**：成本（执行时间）只以一个乘法惩罚项进入 MCTS 的 reward：`R(v) = G(v)·[t(v)/L(v)]^w`（w = −0.07），不做显式预算分账、不做 multi-fidelity；预算约束仅以"总墙钟时间 T"作为硬停止条件 + UCT 探索项隐式调节。[^2^]
- **MARS 的真正创新在 credit assignment**：Comparative Reflective Memory 用 "candidate vs previous best" 的差分分析产出结构化 lesson（因果变更 / 影响对比 / 泛化规则），63% 被使用的 lesson 来自跨分支迁移。[^2^]
- **MARS 自己承认 cost-aware 还不彻底**：论文 Future Work 明确说要补 "advanced context caching and early stopping mechanisms"；其树管理规则（`n_s` 次无改进则重启 root draft）是最原始的 plateau 检测。[^2^]
- **经典机制在 agentic 场景正在以"接口化"形式回归**：Hyperband/SH 被用于 prompt/配置选择（fidelity = 验证实例数）[^10^]；paired-seed 两段式验收漏斗（screen 3 seeds → robust 10 seeds）把"评估器返回不确定性"做成了明确接口[^7^]；BATS 的 Budget Tracker 证明"把预算状态显式注入决策回路"即可显著改善 cost–performance Pareto 前沿[^9^]。
- **对统一框架的核心启示**：`Evaluator` 必须返回 `(metric, cost, uncertainty, fidelity, logs)` 五元组而非标量；`BudgetController` 应是独立一等组件，同时服务"方向级预算"（哪条分支值得继续投入）和"候选级预算"（该候选用哪档 fidelity 评估）。

---

## 1. MARS 核心机制

### 1.1 问题形式化

MARS 把长程 agentic 问题求解形式化为约束优化：问题实例 `𝒫 = (ℐ, ℰ, 𝒪)`（指令、环境、目标函数），目标是

```
s* = argmax_s 𝒪(s, ℰ)   s.t.  Cost(s) ≤ B
```

在 MLE 实例化为 `Q = (I, D, M)`：数据集 `D = {D_dev, D_test}`（D_test 严格隐藏），agent 自建 `D_val`（默认 80:20 stratified/group split）做代理评估，约束 `C(s) ≤ T` 是**总墙钟时间预算**。[^2^]

### 1.2 主循环（伪代码级，来自论文 Algorithm 1 + Algorithm 2 合并）

```
# ---- Task Preparation（一次性） ----
d        ← MetricParsing(I)            # 提取主指标 M 与优化方向 d ∈ {maximize, minimize}
C_meta   ← Preprocess(D)               # 元数据 + stratified split，泄漏检查
C_eda    ← Analyze(I, D, C_meta)       # EDA 报告
C_model  ← SearchArchitectures(I)      # web 检索 K_a 个候选架构族
v_root ← InitializeTree(); v* ← None
L_solution ← ∅   # Solution Lesson Pool（改进经验）
L_debug    ← ∅   # Debug Lesson Pool（排错经验）
𝒴 ← ∅            # 已探索 idea 集合

# ---- MARS Loop（Budget-Aware MCTS） ----
while TimeUsed < T:                                # 唯一硬预算约束
    v ← SelectNode(v_root)                         # UCT 递归下行至未 fully-expanded 节点
    if v is v_root:                                # ---- Drafting（根扩展） ----
        Y ← ProposeIdea(I, 𝒴, C, L_solution)       # curriculum：从轻量 baseline → 复杂集成
        Z ← ProposeModules(I, Y)                   # Modular Agent 分解为功能模块
        {M_j} ← ImplementModules(I, Y, Z)          # Coding Agent 逐模块实现
        {M_j} ← DebugModules(I, {M_j})             # 逐模块单元测试
        π_main ← ImplementMainScript(I, Y, {M_j})  # 编排脚本
        v_new ← DraftNode({M_j}, π_main); 𝒴 ∪= {Y}
    else:                                          # ---- Improvement ----
        v_new ← ImproveNode(v, L_solution)         # ablation 式局部修改 + diff 编辑
    k ← 0
    while IsBuggy(v_new) and k < N_d:              # ---- Debugging loop ----
        v_new ← DebugNode(v_new, L_debug); k += 1  # 最多 N_d = 10 次
    r_e ← ExecuteAndReview(v_new)                  # 执行 + 评审（得到 M(v), t(v)）
    ExtractLesson(v_new, r_e, L_solution)          # 对比反思 → lesson pool
    Backpropagate(v_new, R(v_new))                 # R = G(v)·[t/L]^w，沿路径更新 Q、N
    if v* is None or IsImprovedMetric(r_e, v*, d):
        v* ← v_new                                 # best 按纯验证指标更新（不含成本惩罚！）
return GetRepoCode(v*)
```

关键观察：**最终 best solution 的选择只用验证指标，不用 efficiency reward**；成本惩罚只影响"接下来扩展谁"（搜索方向），不影响"最后提交谁"。这是一个干净的职责分离。[^2^]

### 1.3 三个支柱模块的接口

#### (A) Budget-Aware Planning（成本约束 MCTS）

- **动作空间**（Expansion 算子）：`{Drafting（根节点从头起草）, Improvement（对可执行节点做 ablation 式局部改进）, Debugging（对失败节点修错，自动循环 ≤ N_d 次）}`。
- **选择**：标准 UCT，`a* = argmax (Q(s,a) + c_uct·sqrt(ln N(s)/N(s,a)))`，省略 rollout，叶节点值直接取 efficiency-guided reward。
- **树管理（plateau/重启规则）**：
  - buggy 节点永远 fully-expanded（只能走 Debug 算子）；
  - valid 节点有 ≥ N_i = 2 个 improvement 子节点即 fully-expanded；
  - root 除非"连续 n_s 个 valid 节点未改进 best"否则视为 fully-expanded——**这就是 MARS 唯一的收敛/停滞检测**；leaf 全展开后 root 重新激活开新 draft。[^2^]
- **Efficiency-Guided Reward**（见 §2）。

#### (B) Modular Construction（Design–Decompose–Implement）

节点解是**仓库级元组**而非单文件脚本：`s_n = ⟨{ℳ_j}_{j=1..l}, π_main⟩`。三段流水线：

| 阶段 | Agent | 输入 → 输出 |
|---|---|---|
| Idea Generation | Idea Generation Agent | (I, 𝒴, C, L_solution) → 自然语言方案 Y |
| Module Decomposition | Modular Agent | (I, Y) → 模块划分 Z |
| Component Implementation | Coding Agent | (I, Y, Z) → 逐模块实现 {ℳ_j} + 单测 + π_main |

配套 **Diff-Based Editing**：修改以"目标文件 + 待替换块 + 新代码"的标准 diff 格式下发，支持单步原子化多文件更新，避免整仓重生成。动机有四：绕过输出 token 上限、聚焦小逻辑单元提高精度、已验证模块可缓存复用、debug 定位到文件级。[^2^]

#### (C) Comparative Reflective Memory（Lesson Learning）

四类子 agent 构成的记忆子系统：

1. **Empirical Analysis Agent**：从执行日志提取客观发现（指标趋势）。
2. **Lesson Distillation Agent**：**对当前解与 previous best-known 解做差分比较**，隔离驱动性能变化的具体算法变更，产出结构化 lesson 三元组：① 被隔离的因果变更（如"Adam → AdamW"）；② 对比影响分析（如"val acc +2%，训练时间 +5%"）；③ 可泛化规则。[^2^][^3^]
3. **Review Agent**：新 lesson 与池中已有 lesson 做 LLM 推理比对，过滤冗余/低质，保持高信号密度。
4. **使用端**：Improve/Debug 动作检索对应类别 lesson；agent 显式**引用**所使用 lesson（可审计）；只保留最近 K_m = 30 条防上下文溢出。

失败利用：Debug lesson 由专门 agent 分析 buggy 代码 + 错误日志 + 修复 diff，产出"修复有效性确认 + 失败逻辑解释 + 预防指南"。

---

## 2. 成本建模的接口分析（本单元最重要部分）

### 2.1 成本如何进入 reward / 选择 / 剪枝

MARS 的成本建模数据流：

```
执行器返回: M(v)  性能标量（float，验证集指标）
            t(v)  执行墙钟时间（float 秒）
            L(v)  该节点时间上限（float 秒，常量配置）
历史归一化: G(v) = (M(v) − M_min)/(M_max − M_min)  （对全部已探索节点 V 做 min-max；
                  M_max = M_min 时 G = 0.5）
Reward:     R(v) = G(v) · [t(v)/L(v)]^w           （w = −0.07，沿 MnasNet (tan2019) 的做法）
```

- **进入 reward**：乘法惩罚。性能可比时，更快候选获得更高 R（论文 Fig. 5 的 reward modulation 示意）。[^2^]
- **进入选择**：R 经 backprop 进入 Q 值，再经 UCT 影响后续扩展方向 → 慢的轨迹被"软剪枝"（不是硬删除，而是被选中的概率下降）。
- **进入剪枝**：没有显式剪枝算子；"剪枝"完全通过 UCT 注意力分配实现。作者将其定义为 effective solution rate 的提升：19.5%±1.5% vs Vanilla MCTS 16.1%±1.3%。[^2^]
- **不进入最终提交**：v* 只按验证指标更新（Algorithm 2 第 34 行 `IsImprovedMetric(r_e, v*, d)`），成本不影响提交决策。
- **w 的权衡（附录 E.2 敏感性分析）**：w = 0 退化为 Vanilla MCTS，性能下降；w = −0.07 最优；w = −0.15 过强，搜索偏向"琐碎但快"的节点而牺牲性能。→ 单参数、静态、全局的 cost–performance 汇率。[^2^]

### 2.2 Evaluator 返回什么：成本与不确定性

MARS 的 evaluator（`ExecuteAndReview`）接口实际返回：

| 字段 | 类型 | 用途 |
|---|---|---|
| 有效/失败标志 | bool（IsBuggy） | 路由到 Debug 算子；buggy 节点锁死改进 |
| M(v) | float（单值） | reward + best 更新 |
| t(v) | float（秒） | reward 惩罚项 |
| 执行日志 | 文本 | Empirical Analysis Agent 提取发现 → lesson |
| ~~不确定性~~ | **无** | 单次运行、无 seed 方差、无置信区间 |

**这是 MARS 接口上最明显的缺口**（也是对工业 10h 级评估场景最危险的简化）：

1. **无不确定性建模**：M(v) 是单次验证集评估的点估计。对照 evidence——AIRA 论文发现 validation/test generalization gap 导致系统性过拟合，用 oracle test 分数选节点可再涨 9–13 个百分点的 medal rate[^4^]；autoresearch-speedrun 证明单次运行的种子方差可达 ~0.005 val_loss 量级，必须用 paired-seed 漏斗才能防止 baseline 被噪声"静默污染"[^7^]。
2. **成本只有时间一个维度**：无 token/API 成本、无 GPU 时成本。而 MARS 自己的成本分析（附录 E.3）显示其 LLM 开销结构畸形：输入 token 是 AIRA-dojo 的 2.2×（长上下文 lesson 记忆 + Gemini-2.5-Pro >200k 上下文溢价），$60.5/task vs AIRA $39.0 vs AIDE $10.6——成本大头在**搜索侧 LLM 推理**而非**候选执行**。[^2^]
3. **无 fidelity 维度**：每个候选都全量执行。没有"先 10% 数据/短训练 dev 评估，再全量评估"的级联。

### 2.3 对比：其他系统的 evaluator 接口

| 系统 | Evaluator 返回值 | 成本处理 | 不确定性处理 |
|---|---|---|---|
| AIDE / AIRA-dojo | 5-fold CV 均值 fitness F(v)[^4^] | 无（仅总时限 τ） | CV fold 方差隐式存在但未用于选择 |
| Karpathy autoresearch | `val_bpb, training_seconds, peak_vram_mb, mfu, …` 结构化摘要行；**固定 5min 墙钟/实验**，>10min 强杀记失败[^6^] | 成本被"固定时间预算"常数化——所有候选在相同资源点比较，reward 无需成本项 | 无（单次 run），但固定预算 + val_bpb（tokenizer 无关指标）消除了两类作弊维度[^6^] |
| autoresearch-speedrun | paired-seed val_loss 序列 | 两段式 funnel：SCREEN(3 seeds, ~6min/candidate) → ROBUST(+7 seeds)；拒绝即早停，约 24 次 honest discard vs 6 次 accept[^7^] | **显式统计门槛**：候选须在全部 10 个配对种子上 ≤ best（≥1 个严格胜），等效 p<0.01，对齐上游 speedrun 规则[^7^] |
| PostTrainBench | 最终 checkpoint 的 benchmark 分数 + LLM judge 作弊审计 | 10h/1×H100 硬预算；**20h 时 agent 普遍提前停止 → 降到 10h**（需求侧证据：agent 自身缺乏收敛后继续产出的能力）[^5^] | 3 次重复跑估方差（仅 frontier agent） |
| NanoGPT-Bench | `submit` 命令：LLM judge 规则审查 + **跨 10 次重计时确认统计显著加速**[^12^] | 512 H100-hour 总预算 | 重计时显著性检验内建于提交接口 |
| AutoResearch-RL | 标量 reward（val-bpb 导出）+ termination oracle（收敛或资源耗尽信号）[^8^] | 固定 300s/实验 | termination oracle 是显式的"收敛检测器"接口 |

**接口结论**：工业界最强实践（speedrun 系）已经把 evaluator 定义为"**可请求多次测量、返回显著性判断**"的服务，而非一次性打分器；MARS 系（MCTS 树搜索）则把 evaluator 当黑盒点估计器，靠搜索结构（UCT）吸收噪声。10h 级单次评估成本下，两者必须融合。

---

## 3. 关键设计决策与权衡（含消融证据）

| 决策 | 证据 | 权衡 |
|---|---|---|
| **w = −0.07 的乘法时间惩罚** | Budget-Aware MCTS > Vanilla (w=0) > Greedy（Fig. 4）；effective solution rate 19.5% vs 16.1%；w=−0.15 会偏向 trivial-fast 节点[^2^] | 单一静态汇率无法表达"早期重探索、晚期重利用"；乘法形式在 G(v)≈0（差解）时成本惩罚失效（差的快解 ≈ 差的慢解 reward 都≈0，无区分度） |
| **成本只影响搜索、不影响提交** | Algorithm 2 line 34[^2^] | 干净但放弃了"性能可比时选便宜的"这一最终决策收益（工业场景部署成本敏感时尤其可惜） |
| **模块化仓库 vs 单文件** | LOC 474.8 → 1103.9，文件数 1.0 → 6.7；消融去掉 modular 后性能显著下降（Fig. 3）；模块清单显示 config/engine/loss 等专业划分[^2^] | 更多文件 = 更长上下文 = 输入 token 成本 2.2×；diff 编辑是把成本压回去的关键配套 |
| **Lesson pool K_m = 30，Review Agent 去冗** | lesson-utilization 65.8%，lesson-transfer（跨分支）63.0%[^2^] | 记忆是双刃剑：输入 token 成本主因（$60.5/task）；"63% 跨分支迁移"证明记忆的价值在**泛化**而非回忆 |
| **buggy 节点永远 fully-expanded + N_d = 10 debug 上限** | Hyper-param 选择[^2^] | 防止在死分支上无限制烧钱；N_d 是候选级预算的一种朴素形式 |
| **n_s 次无改进重启 root draft** | §4.4.2[^2^] | 最简 plateau 检测；无统计显著性，n_s 是拍脑袋常数 |
| **MARS+：2 棵并发树 + 2×H100** | Any Medal 56.0% → 62.7%，Above Median 65.8% → 74.2%[^2^] | 并行化以"多棵独立树"为粒度，树间无显式预算协调（共享 lesson pool 是唯一的知识耦合） |
| **记忆维护贵但值** | $39.0(AIRA)→$60.5(MARS) 换来 Any Medal 24.4%→43.1%[^2^] | 成本效益核算要在"美元/奖牌"层面做，而非 token 层面 |

补充消融证据（AIRA 系，解释为什么 MARS 的 reward 设计比搜索拓扑更重要）：AIRA 论文证明在 AIDE 旧算子下，MCTS/进化相对 greedy 几乎无增益——**算子质量是瓶颈，搜索算法不是**；换 O_AIR 算子后 AIRAmcts 才达 SOTA（medal 39.6%→47.7%）[^4^]。这提示：成本敏感改造的优先级应高于搜索拓扑改造。AIRA2 进一步把瓶颈归到同步单 GPU 执行（→异步 worker pool，8 GPU ≈ 8× 实验吞吐）与 validation/test gap（→Hidden Consistent Evaluation）[^14^]。

---

## 4. 八轴卡（MARS）

| 轴 | MARS 的取值 |
|---|---|
| **优化对象** | 仓库级 ML pipeline 代码（模块集合 + 编排脚本），代理目标为验证集指标 M，终极目标为隐藏测试集指标；硬约束为总墙钟 T |
| **基本搜索单元** | 节点 = 完整可执行解 `s_n = ⟨{ℳ_j}, π_main⟩`（整个 repo 快照），边 = 一次算子调用（Draft/Improve/Debug） |
| **算子** | Drafting（根扩展，curriculum 从简到繁）、Improvement（ablation 式局部 diff 修改，配 solution lessons）、Debugging（错误修复，配 debug lessons，≤N_d 次循环）；Diff-Based Editing 为统一修改协议 |
| **拓扑** | 单棵树（MARS+ 为 2 棵并发树）；UCT 选择 + fully-expanded 规则 + root 停滞重启；树内路径 = 一条研究方向的血统 |
| **持久状态** | ① 搜索树（Q/N 统计）；② 双 lesson pool（solution/debug，K_m=30，Review Agent 治理，可跨分支迁移）；③ 已探索 idea 集 𝒴；④ best 节点 v*；⑤ 任务上下文 C（metadata/EDA/架构候选） |
| **反馈权限** | 只读验证集指标 + 执行日志 + 执行时间；无测试集访问；无不确定性估计；无中间 checkpoint 读取（无早停钩子） |
| **失败利用** | Debug 算子 + 专用 debug lesson pool（错误模式库）；buggy 节点永久标记、只许修不许改进；crash 也进 lesson 提取 |
| **并行与选择** | 默认非并行顺序执行；MARS+ 树级并行（2 树 × 各自 GPU）；选择 = UCT(exploitation Q 来自 efficiency reward + exploration 访问计数) |

---

## 5. 成本敏感搜索的经典机制补充（接口视角）

### 5.1 Multi-fidelity / SH / Hyperband 在 agentic search 中的应用

经典定义：fidelity 参数 r（训练轮数、数据子集大小、验证实例数），低成本低保真评估用于早期淘汰。

- **Successive Halving (SH)**：初始给全部 N 个候选各 b = B/(N·log₂N) 预算，每轮淘汰后半、幸存者预算翻倍，直至剩 1 个[^10^][^13^]。
- **Hyperband (HB)**：对 SH 的"n vs B/n 两难"做对冲——多个 bracket 分别以不同初始候选数/初始预算跑 SH，无需先知最优资源分配；在 LLM prompt 选择中（fidelity = 验证实例数），HB 比全保真评估显著省 query 且比裸 SH 鲁棒[^10^]。
- **Agentic 场景的三点适配**：
  1. fidelity 轴必须由 evaluator 暴露为**可请求参数**（`evaluate(config, fidelity) → partial result`），而非固定协议。Karpathy autoresearch 实质上把 fidelity 固定成单一档（5min）——简单可靠但放弃了级联节省[^6^]。
  2. SH/HB 的"rung 晋升"天然是**方向级预算分配器**：autoresearch-speedrun 的 SCREEN(3 seeds)→ROBUST(10 seeds) 就是手工版 SH（η≈淘汰率由统计门槛决定），约 80% 候选在便宜档被拦掉[^7^]。
  3. 与 LLM 生成式搜索结合时，候选不是随机采样而是条件生成，SH 的均匀初始分配不再最优——预算应向高 Q 分支倾斜（MARS 的 UCT 做的正是这件事，只是没有 fidelity 维度）。

### 5.2 Early stopping / convergence detector 的近期实现谱系

| 机制 | 系统 | 形式 |
|---|---|---|
| 硬墙钟/预算耗尽 | 几乎所有（MLE-Bench 24h、PostTrainBench 10h、autoresearch 5min/exp）[^2^][^5^][^6^] | 唯一普适机制 |
| 停滞计数（plateau） | MARS root 重启（n_s 个 valid 节点无改进）[^2^]；"Greedy is a strong default"（连续 2 次拒绝即 early stop，3 次独立运行均在 Phase 3 触发）[^13^] | 拍脑袋常数，无统计依据 |
| 反思驱动终止 | OR-Agent：reflection 指示方向停滞/不可约瓶颈时，削减预算、提前终止并向上层返回摘要；方向改善快时追加预算/加大采样/换更强 LLM[^11^] | 把 convergence detection 交给 LLM 语义判断 |
| 目标达成即停 | Leeroo/KAPSO：一旦按官方评分库达到任意奖牌即提前停止[^2^ 附录D] | 目标导向停止，省剩余预算 |
| 统计显著性门槛 | speedrun 系 p<0.01 / paired-seed funnel[^7^][^12^] | 防止"假改进"而非"真收敛" |
| 需求侧证据 | PostTrainBench：给 20h 时 agent 普遍提前自行停止 → 官方降到 10h[^5^] | 当前 agent 在预算利用率上存在系统性短板，预算不是越多越好 |

### 5.3 预算分配：方向级 vs 候选级

- **方向级（branch/direction-level）**：决定"哪条研究方向还值得继续投"。实现：MARS 的 UCT（Q 值含效率惩罚）[^2^]；OR-Agent 的 reflection-guided 资源分配（语义化步长控制）[^11^]；BATS 的 dig-deeper/pivot 验证模块（按剩余预算决定深挖还是转向）[^9^]；SH/HB 的 rung 淘汰[^10^]。
- **候选级（candidate-level）**：决定"这个候选给多少评估资源"。实现：paired-seed funnel 的 N₁=3/N₂=7[^7^]；MARS 的 N_d=10 debug 上限、N_i=2 分支因子[^2^]；固定时间预算（autoresearch 5min）[^6^]。
- **预算感知注入**：BATS 证明仅把 `<budget>used/remaining</budget>` 状态块注入每步上下文（Budget Tracker 插件），就能推动 cost–performance Pareto 前沿——**预算状态必须是决策回路的一等输入，而非循环外的 if 条件**[^9^]。
- **实践结论**：方向级与候选级不是二选一。成熟系统两层都有：方向级用带成本惩罚的 value/统计淘汰，候选级用 fidelity 级联 + 尝试上限；且两层都应消费同一个 BudgetController 的剩余预算信号。

---

## 6. 对统一框架的接口启示

针对"单次完整评估 10h 级"的工业场景，MARS 暴露了三个必须修复的接口缺口：① evaluator 无不确定性/无 fidelity；② 成本维度单一且只有静态汇率；③ 预算逻辑散落（硬编码 w、N_d、N_i、n_s、T）。建议如下。

### 6.1 Evaluator 接口

```python
class Evaluator(Protocol):
    def evaluate(self, candidate: Candidate,
                 request: EvalRequest) -> EvalResult: ...

@dataclass
class EvalRequest:
    fidelity: Fidelity            # 例如 {"data_frac": 0.1, "train_steps": 500} 或 {"seeds": 3}
                                  # None = 全保真（昂贵真实评估）
    time_limit_s: float           # 硬超时（autoresearch 式强杀）
    budget_token: BudgetToken     # 由 BudgetController 签发的本次评估额度
    resume_from: CheckpointRef | None   # 支持从低保真结果续训/增量评估

@dataclass
class EvalResult:
    status: Literal["ok", "crash", "timeout", "budget_exceeded"]
    metric: float | None
    uncertainty: Uncertainty | None     # seeds 方差 / CV 区间 / bootstrap CI；单点评估时显式标 None
    cost: CostVec                        # {wall_s, gpu_s, llm_tokens_in, llm_tokens_out, usd}
    fidelity: Fidelity                   # 回显实际执行的保真度
    partial_curves: dict | None          # 训练曲线等中间信号，供 convergence detector 使用
    logs_ref: LogRef                     # 供 lesson/credit-assignment 模块消费
```

设计要点：

1. **五元组返回值**（metric, cost, uncertainty, fidelity, logs）是 multi-fidelity 级联与统计验收的最小充分接口。MARS 只有 (metric, t, logs)；speedrun funnel 手工实现了 (metric×seeds, cost)；统一框架应把两者合并。
2. **fidelity 是可组合的**：数据子集 × 训练步数 × 种子数 × 模型规模，各自独立成轴；便宜 dev 评估 = 低 fidelity 组合，昂贵真实评估 = 全保真 + 多 seed。
3. **成本必须是向量**：MARS 的教训是 LLM 输入 token（搜索侧开销）可以超过候选执行开销（E.3：$60.5 vs $39.0，主因在 >200k 上下文溢价）[^2^]；CostVec 同时记 GPU·s 与 token/美元。
4. **crash/timeout 是一等公民**：状态枚举而非隐式 0 分（AIDE 的 F=0 约定会污染 reward 统计[^4^]；autoresearch 记 0.000000 + status=crash[^6^]）。

### 6.2 BudgetController 接口

```python
class BudgetController(Protocol):
    # ---- 查询：预算状态是一等决策输入（BATS 证据[^9^]） ----
    def state(self) -> BudgetState:
        """返回 {remaining: CostVec, used: CostVec, elapsed_frac, per_direction: {...}}"""

    # ---- 方向级：值不值得继续投这条分支 ----
    def should_continue(self, branch: BranchRef,
                        evidence: BranchEvidence) -> ContinueDecision:
        """BranchEvidence = 该分支历史 EvalResult 序列 + lesson/反思摘要。
        实现可插拔：UCT 隐含式（MARS）、plateau 计数、统计显著性、
        LLM 反思式（OR-Agent[^11^]）、SH rung 淘汰[^10^]。"""

    # ---- 候选级：这个候选给多少评估资源 ----
    def allocate(self, candidate: Candidate,
                 context: SearchContext) -> EvalRequest:
        """输出 fidelity + time_limit + budget_token。
        实现可插拔：固定档（autoresearch）、两段漏斗（screen→robust[^7^]）、
        Hyperband bracket[^10^]、UCT 价值加权。"""

    # ---- 记账与终止 ----
    def charge(self, result: EvalResult) -> None: ...
    def converged(self, evidence: BranchEvidence) -> bool:
        """收敛检测器：plateau 计数 / 统计无显著改进 / 目标达成即停（Leeroo[^2^]）/
        termination oracle（AutoResearch-RL[^8^]）。"""
```

三条接口原则（全部由调研证据支撑）：

1. **奖励塑形与提交决策分离**：cost-aware reward（如 MARS 的 `G·[t/L]^w`）只进 `should_continue`/搜索值函数；最终 best/submit 用带不确定性的性能比较（paired-seed、显著性检验），可叠加成本 tie-break。MARS 做对了前半、缺了后半。[^2^][^7^]
2. **成本惩罚参数化但可调度**：静态 w 的消融（0 / −0.07 / −0.15）证明存在甜区且过强会崩溃[^2^]；统一框架应允许 w 随 `elapsed_frac` 调度（早期宽、晚期严），并支持把乘法惩罚换成约束式（budget_exceeded 直接拒评）。
3. **multi-fidelity 级联作为 allocate() 的一种策略注册**：`Fixed`（autoresearch）、`ScreenRobust`（speedrun funnel）、`Hyperband`、`AsymmetricUCB` 共存为策略插件；级联的每一档产出独立 EvalResult，由 BudgetController 决定是否晋升下一档——这样"便宜 dev 评估 → 昂贵真实评估"与"3 seeds → 10 seeds"是同一抽象的两个实例。[^7^][^10^]

### 6.3 针对 10h 级单次评估的额外建议

- **partial_curves + resume_from 必备**：10h 评估无法承受"从头重跑"，fidelity 晋升必须支持 checkpoint 续训；训练曲线中间信号可喂给学习型 convergence detector（PostTrainBench 的 trace 显示 agent 已在手工做"看 ETA 决定砍配置"[^5^]）。
- **uncertainty 不可省略**：AIRA 的 9–13pp oracle 差距[^4^]与 speedrun 的 ~0.1% 假阳性率设计[^7^]共同说明：单次点估计 + 贪心接受会在 10h 尺度上以极高代价累积假改进。最低成本做法：配对种子 +  Wilcoxon/符号检验。
- **记忆成本进 CostVec**：MARS 证明反思记忆的 LLM 推理开销可与执行开销同量级[^2^]；lesson 提炼/审查的 token 消耗必须记账，否则"成本敏感"只优化了半边。

---

## 参考来源

[^1^]: MARS arXiv abstract page. https://arxiv.org/abs/2602.02660
[^2^]: Chen, J., Dalvi Mishra, B., Nam, J., Meng, R., Pfister, T., Yoon, J. *MARS: Modular Agent with Reflective Search for Automated AI Research*. arXiv:2602.02660v3 全文（ar5iv HTML：§3–5, Appendix A–F：Algorithm 1/2、Eq. 3/4、Table 2/4/6/10、Fig. 3/4/5/7）. https://ar5iv.labs.arxiv.org/html/2602.02660
[^3^]: MARS 官方仓库（README + prompts + 轨迹）. https://github.com/jfc43/MARS
[^4^]: Toledo, E. et al. *AI Research Agents for Machine Learning: Search, Exploration, and Generalization in MLE-bench*. arXiv:2507.02554（AIDE greedy 形式化、O_AIR 算子、AIRAmcts 47.7%、val/test gap 9–13pp、top-k 提交策略）. https://arxiv.org/html/2507.02554v1
[^5^]: Rank, B. et al. *PostTrainBench: Can LLM Agents Automate LLM Post-Training?* arXiv:2603.08640（10h/1×H100；"agents given 20 hours often stopped early, so we use 10"；trace 中 agent 手工时间管理；reward hacking 审计）. https://arxiv.org/html/2603.08640v1 ; https://openreview.net/pdf?id=FJKOIxkUxo ; https://posttrainbench.com
[^6^]: Karpathy, A. *autoresearch* 仓库 program.md/README（单文件可变、prepare.py 只读、固定 5min/实验、>10min 强杀、val_bpb 指标、keep/discard/crash TSV 协议、LOOP FOREVER）. https://github.com/karpathy/autoresearch
[^7^]: Dolgirev, P. *autoresearch-speedrun* README（两段式 paired-seed 验收漏斗：SCREEN 3 seeds ~12.5% 假阳性 → ROBUST 10 seeds ~0.1% 对齐 p<0.01；~6min/candidate 便宜过滤；6 accept / 24 honest discards）. https://github.com/PashaDolgirev/autoresearch-speedrun
[^8^]: *AutoResearch-RL: Perpetual Self-Evaluating Research Agents*. arXiv:2603.07300（frozen environment / mutable target / meta-learner 三分离；termination oracle 信号 convergence 或 resource exhaustion；K=32 历史 + top-5 best buffer）. https://arxiv.org/html/2603.07300v1
[^9^]: Liu, T., Wang, Z., … Pfister, T., Lee, C.-Y. *Budget-Aware Tool-Use Enables Effective Agent Scaling*. arXiv:2511.17006（Budget Tracker 插件每步注入 `<budget>used/remaining</budget>`；BATS 的 dig-deeper/pivot 验证模块；统一 token+tool 成本度量；推 Pareto 前沿）. https://arxiv.org/html/2511.17006v1
[^10^]: *Hyperband-based Bayesian Optimization for Black-box Prompt Selection*. arXiv:2412.07820（fidelity = 验证实例数；SH 公式 b = B/(N·log₂N) 逐轮淘汰后半、预算翻倍；HB 多 bracket 对冲 n vs B/n 两难；对比 TRIPLE）. https://arxiv.org/html/2412.07820
[^11^]: *OR-Agent: Bridging Evolutionary Search and Structured Research for Automated Algorithm Discovery*. arXiv:2602.13769（§2.6 Reflection-Guided Resource Allocation：方向改善快→追加预算/加采样/换强模型；停滞→削减预算提前终止并返回摘要）. https://arxiv.org/html/2602.13769v1
[^12^]: Intology AI. *NanoGPT-Bench*（submit 接口 = LLM judge 规则审查 + 跨 10 次重计时确认统计显著加速；512 H100-hour 预算下 agent 仅恢复 <10% 人类进展；agent 算力大头花在超参调优 vs 人类 77% 为算法变更）. https://github.com/IntologyAI/NanoGPT-Bench ; https://www.intology.ai/blog/nanogpt-bench
[^13^]: *Greedy Is a Strong Default: Agents as Iterative Optimizers*. arXiv:2603.27415（连续 2 次拒绝触发 early stopping；LoRA SST-2 三次独立运行两阶段模式复现）. https://arxiv.org/html/2603.27415v1
[^14^]: *Overcoming Bottlenecks in AI Research Agents (AIRA2)*. arXiv:2603.26499（同步单 GPU 吞吐瓶颈→异步 worker pool 8 GPU ≈ 8×；generalization gap→Hidden Consistent Evaluation）. https://arxiv.org/html/2603.26499v2
[^15^]: MLE-Bench leaderboard PR #121 / issue #138（MARS/MARS+ 上榜结果与各系统资源配置对比）. https://github.com/openai/mle-bench/pull/121 ; https://github.com/openai/mle-bench/issues/138

*注：arXiv 官方 HTML（arxiv.org/html/2602.02660v3）在调研时返回 "HTML not available"，正文取自 ar5iv 镜像（同一 v3 源文件渲染）；数值均与 abstract/仓库/leaderboard 交叉一致。*
