# M8 Evaluator 评估设计空间卡片（Group A：评估设计统一调研）

> 目的：为 M8 Evaluator（及 M9 AdmissionGate 联动）建立"轴系→统一实现"的设计卡片库。
> 格式：每个维度/工作 = 【设计内容（公式/超参/字段级）| 量化证据（一手来源）| 对统一设计的启示】。推断标【推断】。
> 来源：既有五份材料（newworks_groupE/B/C/D + m5_groupD_eval）重挖 + 2025–2026 web 补充。

---

## 第一部分：既有材料重挖——评估设计维度

### 卡片 1：级联/分阶段评估（cascade / staged evaluation）

【设计内容】
- **OpenEvolve**：`evaluate_stage1/2/3` + `cascade_thresholds`——阈值相对当前最优分（0.5/0.75/0.9 三档），**随进化进程自动收紧**；便宜测试先行淘汰差候选（newworks_groupE M3/M8 行）。
- **DGM**：staged evaluation：10 题（验证基本代码编辑功能）→ 50/60 题子集 → SWE-bench 若 >40% 且 archive 前二才扩到 200 题（arXiv:2505.22954 §4.2）。预算控制实际体现在 M8 分阶段而非显式 BudgetController。
- **Simple Baselines（arXiv:2602.16805 §5）**：提出两级 evaluation cascade 作为省成本的标准做法。
- **PerfCodeBench（arXiv:2605.15222 §4.1）**：两阶段协议——全任务池 runs=1 快速筛选 → 仅对 correct+promising 候选多次重复测量；配合 baseline/reference 编译与测速缓存复用。

【量化证据】DGM 用 10/50/200 三档把完整评测压缩到条件触发；PerfCodeBench 两阶段使大规模多模型评测"可行"（原文未给具体节省比）。【推断】级联的通用数学形态 = Hyperband/连续减半：阈值相对 incumbent 而非绝对分，是进化场景特有（ incumbent 在动）。

【对统一设计的启示】M8 应内置 `cascade: [{stage, subset_size, threshold_rule(absolute|relative_to_best|top_k), escalate_condition}]`；阈值规则必须支持"相对当前最优 × 系数"语义；级联是 M3（预算）与 M8 的**联动件**而非 M8 独属。

### 卡片 2：public/private 双分数与信息可见性契约

【设计内容】
- **ShinkaEvolve**：框架级评估返回契约 `{"combined_score": float, "public": {...}(对LLM可见), "private": {...}(不可见), "extra_data": {...}(存pkl), "text_feedback": str}`——public/private 划分把"评估器→变异器"反馈通道一等公民化（newworks_groupE M8 行）。
- **AIDE²**：public 分数给内环优化用，private 分数不可见、决定存活（一阶泛化门）；跨任务迁移=二阶泛化；外环座位表现（ignition test）=三阶泛化。观察到反作弊是**涌现**的："赢 public 分数的变体活不过 private 选择"。
- **SEAL（arXiv:2607.24300）**：更极端——agent 可见 self-report r_t，harness 私有审计 A(π)（隐藏 seeds/分布，与部署评估不相交），对 agent 只泄露 **1 bit accept/reject**；四设计条件：外生性、密封性、单比特反馈、保守非回归更新（c_t ≥ b_t − δ_t，拒绝即整体回滚）。信息论下界 Eq.1：α+β ≥ 1−TV(P₊,P₋)。

【量化证据】SEAL leaky-anchor 实验：泄露数值审计分反而显著变差（Doubao 35.1→12.7）。AIDE²：~90% 拒绝率下 8 天 7 代连续改进。

【对统一设计的启示】EvalResult 必须是**分层可见性对象**：`{score, public{}, private{}, artifacts_ref, text_feedback}`；且"对 agent 的反馈带宽"与"评估带宽"是两个正交旋钮——SEAL 证明反馈带宽越低越鲁棒（反直觉但有一手证据）。M9 默认语义 = 保守差分 + 最小泄露。

### 卡片 3：多次运行聚合与统计可靠性（seed budget / CI）

【设计内容】
- **ShinkaEvolve**：`run_shinka_eval` 提供多次运行聚合 + validate_fn 脚手架；OpenEvolve 有 `num_runs` 聚合雏形。
- **Simple Baselines（arXiv:2602.16805 §5）**：揭示 ~100 题小验证集使 scaffold 选择主要是噪声；提出报告 probability of improvement (PoI) / probability of dominance、≥300 有效测试题、95% CI。
- **Mustahsan et al., "Stochasticity in Agentic Evaluations"（arXiv:2512.06710）**：用 ICC（组内相关系数）把方差分解为 between-query（任务难度）与 within-query（agent 不一致）；ICC 收敛分析给出重采样预算指导。配套开源框架 youdotcom-oss/stochastic-agent-evals。
- **Bjarnason et al., "On Randomness in Agentic Evals"（arXiv:2602.07150，ICLR 2026 Agents in the Wild WS）**：SD-TSR（跨 run pass@1 标准差）。
- **Miller, "Adding Error Bars to Evals"（arXiv:2411.00640）**：report SEM、配对差分比较、power analysis 定 N；**聚类题目的 cluster-adjusted SE 可超 naive 3×**；每题多重采样比加新题更便宜地降方差。
- **Madaan et al., "Quantifying Variance in Evaluation Benchmarks"（arXiv:2406.10229）**：评测方差来源分解的经典参照。

【量化证据】2512.06710：FRAMES ICC=0.4955–0.7118、GAIA ICC=0.304–0.774（GPT-4o Level3 仅 0.304）；**8–16 trials 够结构化任务收敛，复杂推理需 ≥32**；第三方综述建议最少 5–10 次重复。2602.07150：单次 pass@1 随所选 run 波动 2.2–6.0 pp，temperature=0 时 SD 仍 >1.5 pp。Simple Baselines：重评 10 次后 P(Shinka>IID RS)=0.49（无显著差异）。Artificial Analysis 实践：每评测 3–10 次重复达 ±1% CI。

【对统一设计的启示】M8 需一个与"带宽"正交的**统计可靠性轴**：`num_runs, aggregation(mean|median|majority|pass@k), CI 报告, 方差分解(item/within-item/protocol)`；最低件：每次评估输出 `score ± CI95` 与 trials 数；级联末级应自动按 ICC 收敛准则分配重复次数。

### 卡片 4：嵌套/元评估（评估"求解器程序"而非任务解）

【设计内容】
- **AIDE²**：内环 agent 分数 = 它在多个任务族上跑完整 autoresearch run 的聚合私有分数——"a benchmark composed of benchmarks"，map→reduce 聚合；固定美元成本预算下的约束优化（best-of-N 类增调用策略被成本约束自动淘汰）。
- **DGM**：被进化对象=agent 代码库；准入是功能性存活门（可编译+保留编辑能力），分数只影响父代选择概率（∝ 表现分 × 有编辑功能的子代数）。
- **EvolveNet（arXiv:2608.04968）**：客户端 per-item 二值 verdict v_i∈{0,1}；服务器聚合用 **per-item 行为翻转证据** e_k=(F_k,B_k)（新增修复集/新增破坏集，Eq.9-10）；双层门：客户端 S_k(h_k)≥S_k(h^(t))，服务器承诺门 |F_val|≥|B_val|（Eq.17），每客户端只需回传两个整数；**validation 只 gate 不 rank**（§6.3：总分排序会颠倒真实优劣，per-item 翻转决策才稳健）。
- **Meta-Harness（arXiv:2603.28052）**：端到端优化模型 harness，held-out 模型 × 200 题聚合评估（stratified 100 题 IMO-AnswerBench + 三个其他集全量）。
- **MetaSkill-Evolve（arXiv:2607.05297）**：meta-productivity P̂(m|s) 二阶效用——评的不是当前解多好而是分支还能否生出更好后代；慢环把 H 轮历史折叠成合成 meta-failure trace 喂给 Analyzer。

【量化证据】EvolveNet：聚合算子 vs select-best/delegation 68.5 vs 64.0/66.5；AIDE²：16× prompt 压缩省下的 token 再投资为额外搜索步。

【对统一设计的启示】统一 Evaluator 必须支持 `level` 参数：评估 Candidate<ExecutorSpec> = "在 N 个任务上各跑完整 run 再聚合"。聚合函数应是显式配置（map-reduce 类型：mean / per-item 翻转计数 / 预算约束下 private 分）。**gate-not-rank** 应成为 M9 默认原则。

### 卡片 5：评估带宽四档 + 轨迹级评估

【设计内容】既有框架已定四档：标量 → 多指标+工件 → +文本反馈 → 完整轨迹。材料内实例：
- OpenEvolve：多指标 + artifacts 侧信道（安全过滤 + 字节上限）——"低成本拿大部分反馈收益"。
- ShinkaEvolve：+text_feedback 档。
- MOSS：完整轨迹级——trial worker 重放 failure batch（行为级 replay）+ build smoke test + 90s 健康探针；Verdict 产出可审计 scoring matrices。
- Simple Baselines（Appendix L）：承认"textual feedback is evidently important for functional code evolution"。

【量化证据】MOSS 三档 depth tier（shallow/standard/deep）联动 5 旋钮：max_iter(3/5/8)、max_plan_rounds(1/2/3)、max_code_retries(0/1/2)、n_trials_per_task(2/3/5)、plateau(1/2/3)。

【对统一设计的启示】带宽档位与成本挂钩，应有 `bandwidth_level` 显式配置；artifacts 必须带字节上限与安全过滤（OpenEvolve 实践）；n_trials 打包进 budget tier 而非散落各处。

### 卡片 6：机制归因分（提升是否经由预期通路）

【设计内容】**PAST-Bench 源码级**（m5_groupD_eval §1.5）：
- Task score 与 Mechanism score **解耦报告**；家族级 Δ_f 只有超过全部控制条件上界才计为自我改进证据。
- 机制分公式：`mechanism_confidence = (artifact_quality + retrieval_score + artifact_presence)/3`；artifact_quality = 规则关键词命中率与写入计数阈值分均值；写入计数取 expected artifact 通道与内部工具计数的**最大值**（防绕过被观测通道）。
- 家族总分乘性合成：`FamilyEvolveScore = max(0, AblationLift) × MechanismConfidence × AutonomousReuseRate × TransferRobustness`，其中 AblationLift = (eval−baseline)^{with} − (eval−baseline)^{without}（**双重差分**，剥离练习效应）；TransferRobustness=clip01(eval_far/eval_near)；任一因子为 0 总分归零。
- 每个指标带 `basis` 标签（measured / proxy / needs_runner_collection），缺失信号退化到中性默认并显式标记。
- 配对控制三件套 `control_set: [no_persistence, shortcut, wrong_mechanism]` + family.yaml 强制 `false_positive_pattern` / `expected_control_result` 字段。

【量化证据】同 Δ=+0.13 的 Hermes vs nanobot，mechanism evidence 0.64 vs 0.57（arXiv:2608.04003 §1/图10）。

【对统一设计的启示】M8 应在任务分之外平行输出"机制/通路分"；乘性合成（zero-factor 归零）比加性更适合准入；**双重差分 with/without 是检验任何自改进声明的标准协议**，应成为 M8 内建实验模式而非外部 benchmark 特性。

### 卡片 7：触发强度 / 迁移距离 / 泛化阶数（评估难度的受控刻度）

【设计内容】
- PAST-Bench：`TRIGGER_STRENGTHS={T0,T1,T2,T3}`（schema.py:55），canonical_anchor 强制 T2/T3、弱触发族只做 diagnostic_sibling（schema.py:470-478）；`transfer_distance ∈ {none,near,far,near_far}`；`overfit_penalty = max(0,(near−far)/near)`。
- AIDE² 泛化阶梯：一阶=held-out 数据（private split）、二阶=held-out 任务族、三阶=换座位（ignition test：AIDE₄₇ 当外环 agent，收敛 20 vs 40 步但渐近相同，"not strong enough evidence of ignition"）。

【量化证据】PAST-Bench：26 family / 204 episode / 4 能力维（5/8/6/7 family，41/64/48/51 episode）；7 模型 × 4 框架实验矩阵；judge 固定 MiniMax-M2.7（config.yaml 钉死 judge 模型保可复现）。

【对统一设计的启示】评估任务族应有声明式 schema（trigger_strength、episode_order、control_set、must_demonstrate、false_positive_pattern——family.yaml 即现成模板）；泛化阶数（held-out data / held-out task / role-swap）可作为 AdmissionGate 的梯度档位。

---

## 第二部分：Web 补充（2025–2026 新工作）

### 卡片 8：统计可靠性新工作汇总

【设计内容】
- **arXiv:2512.06710**（ICC 框架，详见卡片 3）。
- **arXiv:2602.07150**（Bjarnason/Silva/Monperrus, SD-TSR，ICLR'26 WS）。
- **arXiv:2411.00640**（Miller，error bars/聚类 SE/power analysis）。
- **"The Score Went Up. The Model Didn't."（2026-03 博客，引 Mustahsan）**：提出 Minimum Viable Evaluation Card 字段清单：model+version+endpoint、benchmark+split+commit hash、prompting 全文或 hash、decoding 参数、ITA level(0–3)、thinking budget、repeats k 与聚合法、95% CI 三源分解、scorer 类型、运行日期。NIST AI 800-3 同方向。
- **Laplace-PSN-IRT（arXiv:2607.25257）**：IRT 建模 benchmark 题目的不确定度量。
- **ReasonBench（2025-12）**：variance-aware 推理评测（11 方法 × 4 模型 × 7 任务）。

【量化证据】Artificial Analysis：3–10 次重复 → 复合指数 ±1% CI。Miller：cluster-adjusted SE >3× naive。Semgrep：同 GPT-5.5 跨 harness 41 点 F1 摆幅；Anthropic：基础设施配置（RAM/并发/时延）动 Terminal-Bench ~6 点；SWE-bench 标准化 harness vs 厂商 harness 同模型 ~20 点差距（state-of-agentic-coding 2026-07）。

【对统一设计的启示】统一 M8 输出应内嵌 Evaluation Card 元数据字段（模型端点、scaffold 版本、seed、repeats、CI）——没有这些字段的分数不可比较；CI 三源分解（item-sampling / stochastic / protocol）是报告标准。

### 卡片 9：级联评估的 2025–2026 实例化

【设计内容】
- **PerfCodeBench（2605.15222）**：runs=1 全池筛选 → promising 候选重复测（代码性能域）。
- **Constitutional Classifiers++（Anthropic 2025）/ Google probes（Kramár et al. 2026）**：双阈值级联——τ₁ 下判 safe、τ₂ 上判 harmful、中间带升级到贵分类器；Anthropic 仅 5.5% 流量升级 → 5.4× 成本降；Google ~8% 流量升级、~1/50 推理成本。虽是安全分类场景，但"双阈值+中间带升级"是最干净的级联数学形态。
- **FrugalGPT（2305.05176）/ RouteLLM（2406.18665）**：模型级联路由的鼻祖参照（98%/75–85% 成本降）。
- **DarwinX（arXiv:2608.07545）**：agent harness 进化引用 Hoeffding races + Hyperband 作为评估早停机制【推断：把 bandit 式 successive halving 引入 harness 进化评估】。
- **GEPA（arXiv:2507.19457）**：minibatch(size=3) 反馈评估 + Pareto 集完整评估的双层结构；原文自指"验证集评估占 rollout 预算大头，未来方向是缩小/动态子采样验证集"——级联需求被一手承认。

【量化证据】GEPA：验证评估占总 rollout 多数；用 35× 更少 rollout 超 GRPO 19%。Constitutional Classifiers++：5.5% 升级率 / 5.4× 成本。

【对统一设计的启示】级联的阈值语义三选一：相对 incumbent（OpenEvolve）、绝对分数门（DGM 40%）、双阈值中间带升级（Anthropic）；统一实现可用 `escalation_rule` 枚举 + 每级 `subset/重复数` 参数化。

### 卡片 10：LLM-as-judge 校准/去偏 2026 进展

【设计内容】
- **大规模 judge 可靠性研究（arXiv:2606.19544，2026-06）**：21 judges × 9 providers × MT-Bench/JudgeBench/RewardBench，118 runs / ~541k 判断；提出 Minimum Viable Validation Protocol。
- **Causal Judge Evaluation（arXiv:2512.11150v3）**：把 judge 分 S 经 isotonic regression 校准到 E[Y|S]（reward calibration，保均值），处理 policy/deployment shift 与 off-policy；连续校准比 Rogan-Gladen 混淆矩阵二值修正 13× 样本高效；并发 EIF 工作（Chen et al. 2026）证明 naive judge CI 可有 0% 覆盖率。
- **UDA（arXiv:2508.09724）**：成对 judge 无监督去偏对齐。
- **CalibraEval（ACL 2025）**：推断期校准预测分布消选项位置/ID-token 选择偏差。
- **MMB（arXiv:2509.08777）**：贝叶斯 prompt ensemble 校准（多模态 judge）。

【量化证据】2606.19544：exact-match 高估 chance-corrected 一致性 **33.8–41.3 pp**（MT-Bench，21/21 judges 普遍）；judge 排名跨 benchmark 最多移动 **14 位**；两个生产 judge 高 test-retest(>0.95) 与严重 position bias(>0.10) 并存（consistency–bias paradox）；verbosity bias <0.011。UDA：judge 间标准差 193.95→70.97（−63.4%），与human Pearson 0.651→0.812。2512.11150：连续校准 13× 样本效率。

【对统一设计的启示】凡 M8 用 LLM judge：必须 position-swap（AB+BA）、报 Cohen's κ 而非裸 agreement、固定 judge 模型版本（PAST-Bench 实践）、小校准集做 isotonic 校正；judge 可靠性协议（agreement/consistency/bias 三件套）应作为 EvaluatorSpec 的验证钩子。

### 卡片 11：benchmark gaming 防御 / 污染控制 2026 实践

【设计内容】
- **SWE-bench Pro（Scale AI 2026）**：1,865 题 / 41 个活跃维护 repo，public + held-out + commercial 三 split——防御 = held-out 私有集。
- **LiveCodeBench**：按题目发布日期时间门控（只测训练截止后题目）。
- **K Prize（Konwinski）**：测试集全部取自提交截止后新 filed issue。
- **SWE-rebench / SWE-bench-Live**：滚动新鲜任务。
- **BeyondBench（2025-09）**：合成式抗污染。
- **DeepSWE**：DeepSeek 自家无污染集。
- 污染检测理论（2026-08 形式化工作）：可检测性 ∝ 污染比例 × seen/unseen 行为差 × √n——"未发现污染"需附功效计算。
- Berkeley RDI agent benchmark exploit paper（2026）：2,385 条 trace / 15 个 agent benchmark 审计，两个 benchmark 上 ~67% trace 有 reward hacking 或答案暴露。
- METR gaming 发现使部分厂商分数"带星号"；Cursor 受控重跑把 Opus 4.8 Max 87.1→73.0、Composer 2.5 74.7→54.0。

【量化证据】SWE-bench Pro 把同模型从 Verified 的 70–95% 打到 ~23%（GPT-5/SWE-Agent 23.3%）；K Prize 首轮冠军 7.5%（对比 Verified 70s）；DeepSeek V4-Pro：SWE-bench Verified 80.6% vs DeepSWE 8%。

【对统一设计的启示】M8 的任务集管理应是一等功能：`split ∈ {public(优化信号), heldout(准入判定), rolling_fresh}`；canary/decontamination 检查入 CI；**public 分与 heldout 分的差距本身是 gaming 指标**（可作 X1 审计信号）。【推断】对自进化框架，最现实的三件套 = ShinkaEvolve 式 public/private 字段 + 时间门控滚动任务 + SEAL 式最小泄露。

---

## 第三部分：评估设计轴系候选（M8 统一设计的轴与取值）

以下为建议的 M8 Evaluator 轴系（每轴给候选取值；【推断】为新增判断）：

| 轴 | 取值（递进/枚举） | 主要出处 |
|---|---|---|
| **A1 带宽档** | scalar → multi-metric+artifacts(字节上限/安全过滤) → +text_feedback → full_trace/replay | 既有四档 + MOSS |
| **A2 统计可靠性** | single_run → num_runs=k(mean/median/pass@k) → +CI95 → +方差分解(ICC/三源) → +power 定 N | 2512.06710 / 2411.00640 / 2602.16805 |
| **A3 级联结构** | none → staged(绝对阈值) → cascade(相对 incumbent 阈值，自动收紧) → 双阈值中间带升级 | OpenEvolve / DGM / Anthropic CC++ |
| **A4 可见性/反馈泄露** | full_visible → public/private 双分数 → private-only 存活信号 → 1-bit accept/reject | ShinkaEvolve / AIDE² / SEAL |
| **A5 被评对象层级** | L0 任务解 → L1 求解程序(harness/skill/policy) → L2 改进策略(meta-skill/验证器) | DGM / AIDE² / EvolveNet / MetaSkill |
| **A6 聚合语义（嵌套评估）** | 单任务分 → map-reduce 多任务聚合 → per-item 翻转计数(gate-not-rank) → 预算约束下 private 聚合 | AIDE² / EvolveNet |
| **A7 机制归因** | 仅结果分 → +工件证据 → +时序遥测 → 任务分×机制分乘性合成(zero-factor) | PAST-Bench |
| **A8 对照/差分协议** | 无对照 → 单基线 → with/without 双重差分 → 多控制(no_persistence/shortcut/wrong_mechanism)，Δ 须超控制上界 | PAST-Bench |
| **A9 难度刻度** | 单点 → trigger 强度分级(T0–T3) → 迁移距离(none/near/far) → 泛化阶数(heldout data/task/role-swap) | PAST-Bench / AIDE² |
| **A10 防 gaming/污染** | 公开固定集 → public/heldout split → 时间门控滚动集 → canary+decontamination+功效声明 | SWE-Pro / LCB / K Prize / 2026 理论 |
| **A11 评分器类型与校准** | deterministic → LLM-judge(钉版本) → +position-swap/κ 验证 → +isotonic 校准到 oracle | 2606.19544 / 2512.11150 |
| **A12 内生 vs 外生**（验收信号是否 agent 可影响） | endogenous(agent 自写测试) → exogenous(密封 harness) → 混合(self-report 仅诊断用) | SEAL / AIDE² 反作弊涌现 |
| **A13 报告元数据**（Evaluation Card） | 裸分数 → +repeats/CI → 全卡(model/benchmark hash/decoding/ITA/预算/scorer/日期) | 2026 Evaluation Card 实践 |
| **A14 预算打包**【推断】 | 散置参数 → depth tier 打包(trials/rounds/plateau 联动) → 成本($)为硬约束的约束优化 | MOSS / AIDE² |

**轴间关键交互**【推断】：
1. A4 与 A1 正交——SEAL 证明对 agent 的反馈带宽应独立于（且低于）评估带宽。
2. A3 是 A14 的执行手段：级联末级的 trials 数应由 A2 的 ICC 收敛准则自动给定。
3. A5 每上移一层，A6 的聚合成本指数上升，A3 级联从"可选"变"必需"（DGM 的 10/50/200 即此）。
4. A8+A7 是"自改进声明"的最低举证标准；A10 是跨 run 比较可信度的前提。
5. A12 是结构性防 reward hacking：M8/M9 代码须入 X1 谱系，且声明"可自修改位"。

---

## 附：新增一手来源清单（第二部分）

- arXiv:2512.06710 Stochasticity in Agentic Evaluations（ICC；GAIA/FRAMES；8–16 vs ≥32 trials）
- arXiv:2602.07150 On Randomness in Agentic Evals（SD-TSR；temp=0 仍 >1.5pp SD）
- arXiv:2411.00640 Adding Error Bars to Evals（聚类 SE 3×；power analysis）
- arXiv:2406.10229 Quantifying Variance in Evaluation Benchmarks
- arXiv:2605.15222 PerfCodeBench（两阶段评测协议 §4.1）
- arXiv:2606.19544 LLM-as-Judge 大规模可靠性研究（κ 通缩 33.8–41.3pp；consistency–bias paradox）
- arXiv:2512.11150v3 Causal Judge Evaluation（isotonic reward calibration；13× 样本效率）
- arXiv:2508.09724 UDA（judge 间 SD −63.4%；Pearson 0.651→0.812）
- arXiv:2603.28052 Meta-Harness（harness 优化；200 题 held-out 聚合）
- arXiv:2507.19457 GEPA（minibatch+Pareto 双层评估；验证集成本自承）
- arXiv:2608.07545 DarwinX（harness 进化引用 Hoeffding races/Hyperband）
- SWE-bench Pro / LiveCodeBench / K Prize / SWE-rebench / BeyondBench / DeepSWE（污染防御谱系；量化差：Pro ~23% vs Verified 70–95%；K Prize 7.5%）
- Berkeley RDI agent benchmark exploit audit（2,385 traces/15 benchmarks；~67% hacking 率于其中两个）
- 2026-08 污染检测形式化（可检测性 ∝ 污染率×行为差×√n）
- "The Score Went Up. The Model Didn't."（2026-03，Minimum Viable Evaluation Card 字段清单；引 NIST AI 800-3）

置信度说明：第一部分均引自已有一手调研卡片（高）；第二部分 arXiv 条目基于摘要/HTML 片段（高-中），博客/二手汇总（Semgrep 41pp、Cursor 重跑、METR 星号、Anthropic 6pp）标为中置信、建议入库前复核原文。
