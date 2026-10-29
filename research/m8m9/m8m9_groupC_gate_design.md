# M9 AdmissionGate 统一设计调研（Group C：门设计轴系）

> 范围：AutoResearch/自进化 agent 框架的 M9（准入/晋升门）——决定一个候选（解/策略/记忆条目/技能/模型版本）是否进入主线、库或生产路径。
> 材料：既有研究文档（newworks_groupA/C/D/E + ADAPT-v1.1）精读 + 2025–2026 web 补充（sequential testing / AutoML 早停 / 进化计算选择机制 / model registry promotion / canary & shadow）。
> 卡片格式：【设计内容 | 量化证据（出处）| 对统一设计的启示】。标注【推断】处为分析者判断。

---

## 第一部分：既有材料中的门设计精读

### C1. MOSS 三阶段门（自动收敛 → 人授权 → 运行时健康探针）

- **设计内容**：三重串联门，作用于"源码级自我重写"的 apply 事件。(1) 自动门：七阶段流水线 Verdict 必须返回 `CONVERGED`（其余取值 `NEED_MORE_WORK / FUNDAMENTAL_LIMIT_MODEL / FUNDAMENTAL_LIMIT_ARCHITECTURE` 均不放行）；plateau guard（plateau_no_improvement_iters 1/2/3 随 depth tier 缩放）防停滞。(2) 人在环硬门：swap 必须用户显式授权（操作规则第 1 条："Do not invoke `moss evo apply` without the user's explicit go-ahead"）。(3) 运行时门：apply = compose recreate + 90s 健康探针，失败自动 rollback；状态机 `pending_evolution → running → converged/applied/failed`，fresh-start-only，拒绝整体回滚。
- **量化证据**：depth tier 三档（shallow/standard/deep）联动 max_iter 3/5/8、n_trials_per_task 2/3/5（evolution.md 表格）。【原文：newworks_groupC_moss_past.md §1】
- **启示**：① 门可以按"决策时点"分层串联——**自动证据门 → 授权门 → 部署后健康门**，每层证据类型不同（轨迹重放分 / 人判断 / 运行时探针），任何一层否决即回滚；② Verdict 的多值分类（含"根本性限制"）比二元 accept/reject 更有信息——门输出应该是**枚举类型**而非 bool；③ 深度档位即"门的严格度档位"，由人显式选择（"the user owns this trade-off"）。

### C2. SEAL 密封外生验收门（1-bit 反馈）

- **设计内容**：四个必要条件（Table 2）：(1) **外生性**——审计 A(π) 由固定 harness 侧执行（隐藏 seeds/分布，与最终部署评估不相交）；(2) **密封性**——audit 实例、分数、slack 参数 ρ/δ 全部对 agent 不可见（Algorithm 1 line 24）；(3) **最小反馈**——只回 1 bit accept/reject，刻意把反馈带宽压到 M8 评估带宽之下；(4) **保守更新**——非回归规则 c_t ≥ b_t − δ_t（允许退化容差 δ_t），拒绝则 whole-state rollback（单点 incumbent 单链）。
- **量化证据**：内生验证失效有信息论下界 Eq.1：α+β ≥ 1−TV(P₊,P₋)；leaky-anchor 实验：泄露数值审计分反而显著变差（Doubao 35.1→12.7）——证明"反馈给多了反而更差"。【原文：newworks_groupD_arxiv3.md §论文1】
- **启示**：① **评估带宽与反馈带宽必须解耦**——门可以消费高带宽证据，但只把 1 bit 透给被门控的 agent；② 当 Candidate 联合包含验证器 (π,T) 时，外生门是唯一已知可靠的准入机制；③ 门的最小可信核可以很小（几次隐藏 rollout + 1 bit），准入门不必昂贵。

### C3. EvolveNet scope-typed 承诺门（per-item 翻转证据）

- **设计内容**：双层门。客户端门：S_k(h_k) ≥ S_k(h^(t))（Eq.5，本地不许更差）。服务器承诺门：**|F_val| ≥ |B_val|**（Eq.17，修复的 item 数 ≥ 破坏的 item 数才 commit），失败允许一次 revise，再失败回滚 h^(t)。证据格式 = delta + per-item 翻转集合 e_k=(F_k,B_k)（Eq.9-10）；作用域分类 global / home(d_k) / reject（Eq.14）——门不只决定 accept/reject，还决定**在哪里生效**。隐私结构：每客户端只需回传两个整数即可计算门。关键原则："validation 只 gate 不 rank"（§6.3）。
- **量化证据**：消融：merge 算子 68.5 vs select-best 64.0 / delegation 66.5；验证集总分排序会颠倒真实优劣而 per-item 翻转决策稳健（§6.3/§6.4）。【原文：newworks_groupD_arxiv3.md §论文3】
- **启示**：① **gate ≠ rank**——准入证据应是最小单位的差分证据（per-item 翻转），不是聚合分数差；② 门的输出可带**作用域**（scope-typed adoption），把冲突从 winner-take-all 变成条件共存；③ 门可以在不见原始数据的情况下计算（|F|,|B| 两个整数）——证据压缩是门设计的显式目标。

### C4. MetaSkill-Evolve 严格改进门

- **设计内容**：archive 准入 = ΔU_v > 0 严格正改进（§3.3）；最终选择 = 验证集 best-skill，held-out test 只在循环外评一次（§4.1）防自适应过拟合。
- **量化证据**：+6.38/+8.05（OfficeQA/SealQA，单层进化之上）。【原文：newworks_groupD §论文2】
- **启示**：最简形式"严格正差分 + 训练/测试隔离（test 只评一次）"是研究型门的默认基线；失败节点不删、持久化供检索（ΔU≤0 也入 DAG）说明"拒绝 ≠ 销毁"，被拒证据仍有记忆价值。

### C5. prime-agent `/refine` 证据门 + 快照回滚

- **设计内容**：对 harness 自身变更的准入门（对内自改，非对外候选）："small, evidence-backed updates"；**immutable base system prompt 不可改写**（写保护锚点）；recorded snapshots 支持 rollback。quality gates 语义："A passed gate checks only what that gate verifies"（门只担保其验证过的性质）。
- **量化证据**：repo README 明确。【原文：newworks_groupA_github5.md §2】
- **启示**：① M9 需要区分**对外候选准入**与**对内自改准入**两种形态；② "immutable 基座 + 可精化层 + 快照"是安全的自我改进分层；③ 门应声明自己的**担保范围**（gate coverage），过门 ≠ 全域正确。

### C6. Argus 独立权威评审门（Reviewer 判决即准入）

- **设计内容**：执行-评审制度性分离：固定四角色管线 Manager→Planner→Engineer⇄Reviewer，"normal rounds end with a Reviewer judgment"；只有通过验证的进度才成为新的 resume 位置（"continues from its latest verified position"）——**门与 M4 状态绑定**（未过门的状态不可恢复续跑）。Vertical 机制允许领域自定义 "evidence requirements and completion standards" = 领域化的门配置。Planner 为每个任务预先声明"必须产出的证据"。
- **量化证据**：repo README + arXiv:2608.05144。【原文：newworks_groupA §3】
- **启示**：① 门应是有**独立权威**的角色而非流水线末尾的函数；② "verified progress 才能 resume"把门语义嵌入状态机，可直接移植到我们的 checkpoint 设计；③ EvalRequest 与证据要求绑定（先声明证据再执行）值得进框架。

### C7. ShinkaEvolve public/private 评估契约

- **设计内容**：评估返回契约为框架级约定：`{"combined_score": float, "public": {...}(对LLM可见), "private": {...}(不可见), "extra_data": {...}, "text_feedback": str}`——**可见性划分是一等公民**；`run_shinka_eval` 多次运行聚合 + validate_fn 脚手架。准入本身朴素（岛 best 更新 + 新颖性拒绝）。
- **量化证据**：ICLR 2026；BanditBase 状态可持久化（select_llm/update/posterior）。【原文：newworks_groupE_evol2.md】
- **启示**：public/private 应成为 EvalResult 分层标准（ADAPT G2.1 已采纳 `{split}.{visibility}.{name}` key 规范）；门的输入契约应显式区分"对门可见"与"对被门控者可见"。

### C8. ADAPT-v1.1 G4.3 既定立场

- **设计内容**：M9 准入门规则补充："准入决策基于**保守差分证据 + 回滚**为默认"；merge 算子（输入 = delta + per-item 翻转证据）排入 M3；M8/M9 增加"内生 vs 外生"标注（endogenous 时强制外部审计门）；Simple Baselines 教训（~100 题小验证集使 scaffold 选择退化为噪声，P(Shinka>IID RS)=0.49）→ 最小基线 recipe 列为强制对照组。
- **量化证据**：【原文：autoresearch-fw/ADAPT-v1.1.md §4】
- **启示**：本次调研的 web 补充应为"保守差分证据+回滚"提供**具体的统计机制**（差分到什么程度才够格？多重比较如何校正？）——这正是 sequential testing 传统回答的问题。

---

## 第二部分：2025–2026 web 补充

### W1. mSPRT / always-valid p-values：持续监控下的合法早停（A/B 传统）

- **设计内容**：mSPRT（Johari/Pekelis/Walsh, KDD 2017；Optimizely Stats Engine 产品化）：维护混合似然比 Λₙ=∫∏ f_θ(x_i)/f_θ₀(x_i) π(θ)dθ，always-valid p 值 pₙ=1/Λₙ；**首次 pₙ≤α 即停，Type I 错误仍 ≤ α**（Ville 不等式保证，对非负超鞅）。"test of power 1"：真效应存在时以概率 1 有限时间终止。Truncated mSPRT（2025-09 arXiv:2509.07892）把 H0 截断到实际等价区 (|θ|<δ, ROPE)，只声明"有实际意义的改进"。Optimizely 展示层刻意保守：significance = 100 个序贯区间中最小值、CI = 运行交集。工程规则：统计准则（阈值达标）与业务准则（≥1 完整业务周期、CI 稳定 3–5 天）双重要求——"always-valid 消除偷看惩罚，不消除对数据量的需求"。
- **量化证据**：Optimizely 宣称早停识别胜者 ~2.5× 快于固定期（ai-cmo.net/tools/optimizely）；Stats Engine 同时控制 FDR（多重变体/指标时校正阈值）。【出处：arXiv:2509.07892；optipilot.com/data/optimizely-stats-engine；atticusli.com】
- **启示**：① **agent 持续改进门 ≡ 持续偷看的 A/B 测试**：每次循环都问"要不要晋升 incumbent？"正是 always-valid 推理的用武之地；② ROPE/截断零假设直接给出"最小值得晋升的改进量 δ"（等价于 SEAL 的 δ_t 的统计学依据）；③ 门的展示/记录应保守化（历史最劣区间而非当前值）。

### W2. E-values 与多重性：e-BH、任意依赖下的合并

- **设计内容**：e-value 框架（Ramdas/Vovk/Wang 系）为自适应/序贯决策提供 any-time 有效推断；关键代数性质：**同一零假设下 e-value 的算术平均在任意依赖下仍有效**，独立 e-value 的乘积有效——支持 e-BH 程序控制 FDR。2026-02 arXiv:2602.06379 给出自适应临床试验的完整 e-value 实现（含 hybrid_monitor 联合 e-process 与 group-sequential 监控），并指出 2026 FDA draft Bayesian guidance 要求操作特征文档化。
- **量化证据**：【出处：arXiv:2602.06379 §6.4/§9】
- **启示**：① 当框架同时门控**多个候选/多个指标/多个分支**时，多重性校正不是奢侈品而是默认；e-value 的"任意依赖下平均有效"特别适合 agent 系统（候选间依赖关系不可控【推断】）；② 门决策可以维护一个**e-process 轨迹**作为一等审计工件（比单次 p 值更适合 append-only 日志）。

### W3. BH/FDR 校正在在线实验的工程实践

- **设计内容**：BH 程序：p 值升序排列，第 i 个与 (i/m)·Q 比较（m=总检验数，Q=目标 FDR）；FWER（Bonferroni）用于"任何假阳性都是大事"，FDR 用于探索性高通量。Statsig 指南明确：检验相关时改用 Benjamini-Yekutieli。
- **量化证据**：Microsoft 等在线实验平台已采用 BH 校正评估网站变更（statsig.com guide, 2025-01）。【出处：statsig.com/perspectives/controlling-false-discoveries-guide】
- **启示**：agent 进化一次批量评估 N 个候选时，晋升判定应对 N 做 BH 校正；分支间高度相关（共享祖先）时提示 BY 或 e-BH。【推断】

### W4. ASHA / Hyperband：早停即门（AutoML 传统）

- **设计内容**：异步逐次减半：rung k 中 top-1/η（默认 η=4）晋升到下一资源档 r·η^k，其余杀掉；异步版本"有晋升即晋升，否则新开随机配置"，消除 straggler。晋升判据是**同一 rung 内的相对排名**而非绝对阈值。OpenEvolve 的级联评估是同构思想：cascade_thresholds 相对当前最优 0.5/0.75/0.9，**随进化自动收紧**——便宜测试先淘汰。
- **量化证据**：ASHA 作者给出通用默认 s=0, η=4（Li et al., MLSys 2020；CERN OPL 2024/2025 讲义）。【出处：CERN indico 讲义；newworks_groupE】
- **启示**：① 门可以是**多档级联**的（便宜关 → 贵关），每档只淘汰不录取，最终录取只在最贵的证据上发生——这与 M8 评估带宽分档天然对齐；② "相对当前最优自动收紧的阈值"应成为 M3/M9 的一等配置（OpenEvolve 已验证）；③ rung 内相对排名 = 对评估噪声稳健的门判据【推断：排名比绝对分差更抗噪声漂移】。

### W5. 进化计算的晋升语义：tournament / lexicase / MAP-Elites

- **设计内容**：(a) **Tournament**：k 个体竞争，最优者获得繁殖权——压力由 k 控制，纯相对、无阈值。(b) **Lexicase**：把每个 training case 当作一次"门事件"——随机洗序 case 序列，逐 case 过滤候选池（只保留该 case 上最优者，ε-lexicase 放宽到最优的 ε 邻域内），直到池收敛。理论结果：lexicase 选中的个体必在 case 定义的 **Pareto front** 上，ε-lexicase 选中 ε-Pareto 最优点（La Cava et al. 2019）——lexicase 本质是"**逐维生存门**"，天然奖励专家（specialists）。(c) **MAP-Elites**：胞格内竞争（新个体优于胞内现任即替换），准入=局部改进 + 行为特征归档；噪声域的 UQD/Extract-QD（Flageat & Cully 2024–2025）增加 buffered evaluation + **周期性重评估 archive 精英**——准入后仍有复核门。
- **量化证据**：ε-lexicase 选中个体恰为 ε-Pareto 最优（La Cava et al., Evolutionary Computation 2019）；down-sampled ε-lexicase 相对标准版解质量提升最高 85%（2023）；Extract-MAP-Elites 在噪声域一致优于朴素重评估基线（Flageat et al. 2025）。【出处：cavalab.org lexicase 讲义；arXiv:2605.09781 引述】
- **启示**：① **per-item 生存门（lexicase）与 EvolveNet 的 per-item 翻转证据同构**——把聚合分数拆成逐 case 决策既保多样性又抗聚合噪声；② MAP-Elites 胞格准入 = scope-typed adoption 的进化计算版本（"在所属胞格内生效"）；③ **周期性重评估已入库成员**（Extract-QD）对应"入库不等于永久豁免"——门应支持在职复核（tenure review），这与 M5-UNIFIED 的 tenure 消融协议挂钩。

### W6. Model registry promotion（MLOps 传统）

- **设计内容**：阶段化生命周期 `None → Staging → Production → Archived`（MLflow 经典三态，2026 年起转向别名 `champion/challenger` 指针）；晋升门要求证据四件套：eval 结果、model card、偏差审计、人工签署；示例阈值 `accuracy ≥ 0.92 ∧ p95 latency ≤ 120ms ∧ demographic_parity_diff ≤ 0.10`。关键制度：① **promotion 与 deployment 分离**——registry 只"祝福"版本，流量切换是另一条管线；② 单一 Production 不变量（晋升新版时旧版必须 Archived）；③ Archived = 退役不删除，保留完整谱系供事后审计；④ 回滚 = 指针重指（registry 操作，不是重部署）。每次晋升记录 who/when/metrics，直接对接 EU AI Act Art.9/14/15、ISO 42001、SOC 2 变更管理。
- **量化证据**：【出处：datarekha.com/mlops/model-registry（2026-06）；theja.org MLflow 教学（含阈值示例）；vigilens.ai MLflow+Datadog（2026-04）；bestaiweb.ai 2026 指南】
- **启示**：① **晋升决策与生效动作分离**——M9 输出应是"给候选盖章 + 记录证据"，生效（进入主线/被检索/被部署）由下游消费印章；这自然支持回滚=改指针；② 多指标合取阈值门（acc ∧ latency ∧ fairness）是简单稳健的门形态；③ "别名指针"模型使回滚 O(1)，应成为 M4/M9 状态设计默认。

### W7. Coding agent PR 合并门（2026 实证）

- **设计内容**：大规模实证（arXiv:2602.19441, MSR 2026）：33,596 个 agent 撰写 PR、2,807 repo、5 个 agent。**评审者参与度（reviewer engagement）是合并成功的最强预测因子，force push 是最强负向预测因子；功能正确性必要但不充分**。自治度分级 L1(comment)–L5(ship with approval gates)；L5 实践（Codex/Devin）强制人审门后才 auto-merge。工程实例（perl-lsp-swarm）：merge-ready **receipt** 绑定 (head_sha, base_sha, gate_graph_version)，required_checks 全绿 + 四个评审 sign-off + blocker 标签缺席，且 receipt 在 head_sha/base_sha/门图版本任一变化时**自动失效**——"门票据有失效条件"是一等设计。
- **量化证据**：总体合并率 71.5%（95%CI [0.710,0.720]）；按 agent：Codex 82.6%、Devin 53.8%、Copilot 43.0%（arXiv:2602.19441）；Devin 18 个月 PR 合并率 34%→67%（Cognition 2025-12 年报）。【出处：agentpatterns-ai/website；github EffortlessMetrics/perl-lsp-swarm#2799】
- **启示**：① 门证据应绑定**精确状态哈希**并在状态漂移时失效——agent 系统里"评过的那个候选"和"要晋升的候选"必须是同一个可验证对象；② 人类/独立评审者参与度本身是最强质量信号——门的社交/制度层与统计层同样重要；③ 合并率是 agent 能力的可操作度量，可作为我们评估 M9 配置的外部效标【推断】。

### W8. Shadow / canary / 回滚（LLM/agent 部署实践 2025–2026）

- **设计内容**：四策略风险谱：direct(100%立即) → shadow(0%用户暴露，仅内部比对) → canary(1–5%→10%→25%→50%→100% 阶梯) → A/B(50/50)。推荐晋升链：**shadow 先行验证安全性，canary 其次量真实影响，禁止直接 100%**。量化协议示例：shadow 期最少 1,000 次比对或 5 天、>5% 分歧人工复核；canary 每档 24–72h，监控 grounding −5pts / P95 +500ms / cost +25% 等阈值，**超阈值持续 ≥N 分钟自动回滚**；稳定用户路由（同用户恒同版本）；晋升后 shadow 再跑 24h 作为 sanity check。Shadow 模式下 agent 决策被记录但不执行，与人类实际决策比对，达到预定义阈值才晋升；典型回滚触发器：一致性 <80% 连续两天 / 关键错误 / SLA 违约。Anneal（arXiv:2605.16309, 2026）：符号补丁学习系统，accepted patch 须过 value check + causal check + **canary testing**，全治理运行中零回滚；版本化 commit 构成"structural ratchet"（特定失效模式一旦修复即难以复发）。
- **量化证据**：canary 阶梯 5%/24h → 10%/48h → 25%/72h → 50%→100%（channel.tel 2026-05）；auto-rollback 阈值示例 grounding −5pts/P95 +500ms/cost +25%（digitaloneagency 2025-08）。【出处：channel.tel/blog/ai-agent-shadow-mode-deployment；brightlume.ai；arXiv:2605.16309】
- **启示**：① 对研究框架，MOSS 的"健康探针回滚"只是该谱系的最右端；**shadow = 让候选在真实输入上跑但不生效**这一中间档，我们的 trial-worker 重放本质上是 shadow 的离线版【推断】；② **分级暴露（graduated exposure）**概念可移植为"候选记忆条目先在小流量/低风险任务上生效再全域生效"；③ 回滚触发器必须**事先声明**（pre-registered rollback criteria），与 ADAPT G4.3 的保守默认一致。

---

## 第三部分：门设计轴系候选（轴 + 取值）

| # | 轴 | 取值 | 主要证据来源 |
|---|---|---|---|
| A1 | **门的对象层级**（Candidate level） | L0 任务解 / L1 求解程序(skill/harness) / L2 改进策略 / 记忆条目 / 模型版本 | G1；W6 |
| A2 | **门的位置/时点** | 入库门（archive） / 谱系门（成为父代资格） / 主线合并门 / 部署门 / 部署后健康门（在职复核） | C1, C6, W4, W8 |
| A3 | **证据类型** | 聚合分数差 / per-item 翻转集合(F,B) / 逐 case 生存(lexicase) / 轨迹+工件 / 运行时探针 / 人判断 | C2, C3, W5 |
| A4 | **判定规则** | 绝对阈值（acc≥0.92） / 非回归（c≥b−δ） / 严格改进（ΔU>0） / 序贯统计门（mSPRT pₙ≤α / e-value ≥1/α） / 相对排名（rung top-1/η） / 多指标合取 | W1, W4, C2, W6 |
| A5 | **保守度/严格度档位** | 探索档（FDR, BH） ↔ 确认档（FWER, Bonferroni） ↔ 高风险双人/双签 | W3, W7 |
| A6 | **内生 vs 外生** | endogenous（agent 可影响评估，须强制外生审计） / exogenous（agent 不可见不可改） | C2；ADAPT 2.4 |
| A7 | **反馈泄露带宽** | 1 bit accept/reject / 分数区间 / 完整证据包；原则：反馈带宽 ≤ 评估带宽，可刻意收窄 | C2（leaky 35.1→12.7）, C7 |
| A8 | **多重性校正** | 无 / BH / BY / e-BH / gate-graph 版本绑定失效 | W2, W3, W7 |
| A9 | **作用域语义** | global / home(scope 条件化) / reject；胞格局部（MAP-Elites） | C3, W5 |
| A10 | **输出类型** | bool / 枚举（CONVERGED/NEED_MORE_WORK/FUNDAMENTAL_LIMIT_*） / 带 scope 的采纳 / receipt（绑定哈希+失效条件） | C1, W7 |
| A11 | **拒绝的处置** | 销毁 / 持久化供检索（inspiration） / 归档供 post-mortem | C4, C1 |
| A12 | **回滚机制** | whole-state rollback / 快照恢复 / 别名指针重指（O(1)） / 健康探针自动触发 / 预注册回滚触发器 | C1, C5, W6, W8 |
| A13 | **生效方式（promotion↔deployment 分离）** | 立即全域 / 分级暴露（shadow→canary 阶梯） / 仅盖章不生效 | W6, W8 |
| A14 | **担保范围声明** | 门声明其验证过的性质清单（"passed gate checks only what that gate verifies"）；入库后在职复核（周期重评估） | C5, W5(Extract-QD) |
| A15 | **授权结构** | 全自动 / 自动门+人授权硬门 / 独立权威评审角色 / 多签 | C1, C6, W6, W7 |
| A16 | **证据保真约束** | 原始证据不可转述（MOSS 用户投诉原样保留） / 状态哈希绑定 / decontamination（评估卫生） | C1 装不下机制, W7, groupA §5 |

**轴系与既有结论的汇聚点**【推断】：五个独立来源（SEAL、EvolveNet、MOSS、MLOps registry、sequential testing）在以下默认配置上收敛——**外生或独立权威的判定者（A6/A15）+ 保守差分证据（A3/A4）+ 最小泄露反馈（A7）+ 回滚为默认（A12）+ 盖章与生效分离（A13）**。这与 ADAPT-v1.1 G4.3 既定立场一致，web 补充的新增量是：差分判据的**统计合法化**（mSPRT/e-value 给出"δ 该多大、看多少次不罚"的形式答案，A4/A5/A8）与**分级暴露**作为生效方式（A13）。

---

## 附：主要来源清单

既有材料：newworks_groupC_moss_past.md（MOSS/PAST-Bench）、newworks_groupD_arxiv3.md（SEAL arXiv:2607.24300 / MetaSkill-Evolve arXiv:2607.05297 / EvolveNet arXiv:2608.04968）、newworks_groupA_github5.md（prime-agent/Argus/OpenRSI）、newworks_groupE_evol2.md（ShinkaEvolve）、autoresearch-fw/ADAPT-v1.1.md。

Web：arXiv:2509.07892（truncated mSPRT）、Johari et al. KDD 2017（mSPRT，经 Optimizely 文档引述）、arXiv:2602.06379（e-values 自适应试验）、statsig.com FDR/BH 指南、Li et al. MLSys 2020（ASHA）、La Cava et al. 2019（ε-lexicase Pareto 性）、Flageat et al. 2025（Extract-QD）、datarekha.com & theja.org（model registry promotion）、arXiv:2602.19441（agent PR 合并 33,596 PR）、github.com/EffortlessMetrics/perl-lsp-swarm#2799（merge-ready receipt）、channel.tel & brightlume.ai & digitaloneagency（shadow/canary 协议）、arXiv:2605.16309（Anneal 治理门）、arXiv:2305.16291（Voyager 自验证入库）。
