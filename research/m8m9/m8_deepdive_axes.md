# M8 Evaluator 设计轴逐格深挖（Stage 2）

> 依据：`m8m9_groupA_eval_design.md`（14 条候选轴 A1–A14 + 轴间交互）、`m8m9_groupD_frontier.md`（7 条候选新轴）。所有量化数字均出自上述两份卡片并注明 arXiv/出处；卡片外不引入新数字，合理外推标【推断】。格式对标 M5《deepdive_axes_A-E.md》与《deepdive_axes_F-I_分歧.md》。

---

## 第〇部分：轴系合并方案（A 组 14 轴 × D 组 7 候选新轴 → M8 最终轴系）

**D 组新轴处置表**：

| D 组候选新轴 | 处置 | 理由 |
|---|---|---|
| D1 评估器可观测性与漂移归因（卡 1/9） | **独立成新轴 E1**（吸收卡 9 校准维护周期） | 归因对象是"评估信号本身的来源（system vs judge）"，与 A7（被评对象内部通路归因）正交，A11 只管部署前校准，管不了运行时漂移归因（卡 1 明示"评估器不再是测量工具而是被监控对象"） |
| D2 分数谱系与失效（卡 2） | **独立成新轴 E2** | "换裁判时历史分数作废/保留/重估"是时效性维度，A2 统计可靠性与 A13 元数据都不覆盖 |
| D3 标准级自进化 + 变更准入门（卡 3） | **独立成新轴 E3** | 与 A12 正交（A12 问验证器在哪，E3 问验证器是否可变、谁批准变更）；且引入"门的递归"（评估器变更需 M9 实例），A 组无对应 |
| D4 评估器作为一等制品（卡 4） | **拆分**：per-row judge provenance → 并入 A13 取值；"judge 与 benchmark 捆绑发布/可审计" → 并入 E5；裁判间 35%–95% 方差作为 E1/E5 的动机证据 | D 组已声明"judge 选型不是新轴"，卡 4 的可复现性内核是治理问题 |
| D5 评估预算经济学（卡 7） | **并入 A14**（升级为"预算打包与评估经济学"） | A14 原本就是【推断】轴，卡 7 的 eval tax（35×）正是它缺失的一手证据；采样率/judge 档/级联深度被预算反噬的关系写入 A14 隐藏结构 |
| D6 门的拓扑与渐进信任（卡 5/10） | **主体归 M9，不列 M8 轴**；M8 侧的对应物（"门消费的信号形态须支持连续流量份额下的并排打分"）作为约束写入 A4 | gate placement 是发布控制面，属 AdmissionGate 设计域；D 组声明"3% 阈值/interleaving 不是新轴" |
| D7 评估治理与审计（卡 8） | **独立成新轴 E5**（吸收卡 4 的捆绑发布） | "谁有权改评估器、评估记录是否构成审计证据"在 A 组全部 14 轴的隐含假设（研究者全权控制评估器）之外 |

**最终轴系**：经典段 A1–A14（14 轴，A13/A14 吸收 D 组拆分内容），新轴段 E1–E5（5 轴）。D 组声明的五个"看似新实则旧"项（在线评估/级联定价/3% 阈值/judge 选型/interleaving）不作为轴，分别以取值身份出现在 A1/A2/A3/A11/A14 中。

---
---

# 第一部分：经典轴 A1–A14

## 轴 A1：评估带宽档（一次评估返回多少信息）

**轴定义**：评估器单次产出的信息量档位——scalar → multi-metric+artifacts → +text_feedback → full_trace/replay（A 组第三部分轴表，卡片 5）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| scalar 标量分 | 只回 combined_score | 零成本零泄露面；但 Simple Baselines（arXiv:2602.16805 Appendix L）承认 "textual feedback is evidently important for functional code evolution"——纯标量在代码进化中证据不足 | 级联前几级的淘汰筛选（配 A3） |
| multi-metric + artifacts | 多指标 + 工件侧信道，工件带**字节上限与安全过滤**（OpenEvolve 实践） | OpenEvolve 定位："低成本拿大部分反馈收益"（卡片 5） | 默认主选；反馈收益/成本比最高的一档 |
| +text_feedback | ShinkaEvolve 契约的 `text_feedback: str` 字段，对变异器可见 | 与 public/private 可见性契约捆绑实现（卡片 2） | 需要 LLM 变异器消化失败原因时 |
| full_trace / replay | MOSS：trial worker 重放 failure batch（行为级 replay）+ build smoke test + 90s 健康探针，产出可审计 scoring matrices | MOSS 三档 depth tier（shallow/standard/deep）联动 5 旋钮：max_iter(3/5/8)、max_plan_rounds(1/2/3)、max_code_retries(0/1/2)、n_trials_per_task(2/3/5)、plateau(1/2/3)（卡片 5） | 级联末级、深度诊断、审计场景 |

**隐藏结构**：带宽档不是"越多越好"的线性轴，而是**两个正交带宽的乘积**：评估带宽（harness 看见多少）× 反馈带宽（agent/变异器看见多少）。A 组轴间交互 1 明示：SEAL 证明对 agent 的反馈带宽应**独立于且低于**评估带宽——full_trace 给审计器，1 bit 给 agent，两者可以共存于同一 EvalResult。第二个隐藏结构是带宽档与预算的硬耦合：MOSS 把 n_trials 等 5 旋钮**打包进 depth tier** 而非散落配置，这预示了 A14 的"预算打包"取值；带宽档位本质是价格表（A14 卡 7：deterministic 免费 <1ms → LLM judge ~$0.01–0.03/call → 多 judge $0.05–0.10/probe）。

**反直觉结论**：(1) 给变异器更多信息未必更好——SEAL leaky-anchor 实验证明泄露数值审计分反而显著变差（Doubao 35.1→12.7），所以"带宽档"的正确问法不是"能给多少"而是"每一接收方最少需要多少"。(2) 最贵的 full_trace 档的价值不在帮助当前候选，而在**可审计性**（MOSS scoring matrices）——它是治理资产而非优化信号【推断】。

---

## 轴 A2：统计可靠性（分数带多大的误差棒）

**轴定义**：与带宽正交的可靠性轴——single_run → num_runs=k（mean/median/majority/pass@k）→ +CI95 → +方差分解 → +power 定 N（A 组轴表，卡片 3/8）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| single_run | 单次 pass@1 | 单次 pass@1 随所选 run 波动 2.2–6.0pp；temperature=0 时 SD 仍 >1.5pp（arXiv:2602.07150）——单跑分数在进化选择中基本是掷骰子 | 仅作级联第一级的粗筛 |
| num_runs=k + 聚合 | k 次重复取 mean/median/pass@k | **8–16 trials 够结构化任务收敛，复杂推理需 ≥32**（arXiv:2512.06710）；第三方综述建议最少 5–10 次；Artificial Analysis 实践 3–10 次重复达 ±1% CI | 任何要做候选间比较的场合 |
| +CI95 报告 | 每次评估输出 score ± CI95 与 trials 数 | ~100 题小验证集使 scaffold 选择主要是噪声；重评 10 次后 P(Shinka>IID RS)=0.49——即无显著差异（2602.16805 §5）；建议 ≥300 有效测试题、报 PoI/probability of dominance | 比较两个系统/scaffold 时必选 |
| +方差分解 | ICC 分解 between-query（题目难度）vs within-query（agent 不一致）；三源分解 item-sampling/stochastic/protocol | FRAMES ICC=0.4955–0.7118、GAIA ICC=0.304–0.774（GPT-4o Level3 仅 0.304，arXiv:2512.06710）；聚类题目的 cluster-adjusted SE 可超 naive **3×**（arXiv:2411.00640） | 任务间相关性高（同族题目）时；分配级联末级重复数时 |
| +power 定 N | 用 power analysis 反推所需 N | Miller：每题多重采样比加新题**更便宜地降方差**（2411.00640） | 准入判定这种"错判代价高"的终端环节 |

**隐藏结构**：可靠性预算是**三个可互换旋钮的分配问题**：题目数 × 每题重复数 × 聚合函数。Miller 证明"每题多重采样"与"加新题"在降方差上是替代品且前者更便宜；2512.06710 的 ICC 正是裁决"该把预算花在哪一头"的统计量——ICC 低（GAIA 0.304）说明 within-query 方差大，应加重复；ICC 高说明 between-query 主导，应加题。第二个隐藏结构：聚类题目使 naive SE 低估 3×，意味着**任务族结构（A9 的 family）直接污染 A2 的误差棒**，两轴不可独立配置。级联末级的 trials 数应由 ICC 收敛准则自动给定（A 组轴间交互 2）。

**反直觉结论**：(1) temperature=0 不消灭随机性（SD 仍 >1.5pp）——"确定性解码 = 确定性分数"是错的，harness/基础设施噪声独立于采样噪声（旁证：Anthropic 测得基础设施配置动 Terminal-Bench ~6 点）。(2) 重复 10 次后两个系统的差异可以是纯噪声（P=0.49）——**没有 CI 的"提升了 X 点"在 ~100 题规模上不可报道**。(3) 加题不如加采样，在预算固定时成立（2411.00640）。

---

## 轴 A3：级联结构（便宜测试先行，贵评估条件触发）

**轴定义**：评估管线的分阶段淘汰结构——none → staged（绝对阈值）→ cascade（相对 incumbent 阈值，自动收紧）→ 双阈值中间带升级（A 组轴表，卡片 1/9）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| none 单层全量 | 所有候选跑完整评估 | GEPA 自承"验证集评估占 rollout 预算大头"，并把"缩小/动态子采样验证集"列为未来方向（arXiv:2507.19457）——单层全量在进化场景被一手承认为瓶颈 | 候选极少或评估本身免费（deterministic）时 |
| staged 绝对阈值 | DGM：10 题（验证基本编辑功能）→ 50/60 题子集 → SWE-bench 若 >40% 且 archive 前二才扩 200 题（arXiv:2505.22954 §4.2） | 三档把完整评测压缩到条件触发；预算控制实际体现在 M8 分阶段而非显式 BudgetController | 有自然难度阶梯的 benchmark |
| cascade 相对 incumbent | OpenEvolve `cascade_thresholds`：阈值 = 当前最优分 × (0.5/0.75/0.9)，**随进化进程自动收紧** | 【推断】进化场景特有：incumbent 在动，绝对阈值会失效——早期太严、后期太松 | 自进化主循环的默认形态 |
| 双阈值中间带升级 | τ₁ 下判 safe、τ₂ 上判 harmful、中间带升级到贵分类器 | Constitutional Classifiers++：仅 **5.5%** 流量升级 → **5.4×** 成本降；Google probes：~8% 升级、~1/50 推理成本（卡片 9） | 判定边界密集、绝大多数样本易判时 |
| bandit 早停 | DarwinX（arXiv:2608.07545）引用 Hoeffding races + Hyperband 作评估早停 | 【推断】把 successive halving 引入 harness 进化评估 | 候选多、单候选评估贵时 |

**隐藏结构**：级联的真正自由度不在层数而在**阈值语义三选一**：相对 incumbent（OpenEvolve，适配 incumbent 移动的进化场景）、绝对分数门（DGM 40%，适配有固定能力定义的场景）、双阈值中间带（Anthropic，适配易判样本占绝大多数的场景）。统一实现 = `cascade: [{stage, subset_size, threshold_rule(absolute|relative_to_best|top_k), escalate_condition}]`（卡片 1）。A3 是 A14 的执行手段而非独立选择（轴间交互 2）；且 A5 每上移一层，A3 从"可选"变"必需"（轴间交互 3：DGM 的 10/50/200 正是被评对象=整个 agent 代码库时的必然产物）。

**反直觉结论**：(1) 级联节省的不只是钱——GEPA 用 35× 更少 rollout 反超 GRPO 19%，说明把预算从"平均撒"改为"集中给幸存者"本身是性能增益来源，不只是成本措施。(2) 相对 incumbent 的阈值意味着**同一个分数在不同代际含义不同**——这与 E2（分数谱系）联动：级联阈值的历史也是谱系的一部分【推断】。

---

## 轴 A4：可见性与反馈泄露（评估结果对谁暴露多少）

**轴定义**：EvalResult 的信息可见性契约——full_visible → public/private 双分数 → private-only 存活信号 → 1-bit accept/reject（A 组轴表，卡片 2）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| full_visible | 评估细节全量对 agent 可见 | 被 hack 面最大；无一手系统在高自主场景采用 | 调试期、无自改进压力时 |
| public/private 双分数 | ShinkaEvolve 契约：`{"combined_score", "public":{}(对LLM可见), "private":{}(不可见), "extra_data":{}(存pkl), "text_feedback"}` | public/private 划分把"评估器→变异器"反馈通道一等公民化 | 进化框架默认 |
| private 决定存活 | AIDE²：public 分给内环优化，private 分不可见、决定存活（一阶泛化门） | 反作弊是**涌现**的："赢 public 分数的变体活不过 private 选择"；~90% 拒绝率下 8 天 7 代连续改进 | 有 held-out 数据时 |
| 1-bit accept/reject | SEAL（arXiv:2607.24300）：agent 可见 self-report r_t，harness 私有审计 A(π)（隐藏 seeds/分布），只泄露 1 bit；四设计条件：外生性、密封性、单比特反馈、保守非回归更新（c_t ≥ b_t − δ_t，拒绝即整体回滚） | 信息论下界 α+β ≥ 1−TV(P₊,P₋)；leaky-anchor 实验：泄露数值审计分反而显著变差（**Doubao 35.1→12.7**） | 高自主、强 reward hacking 压力的自进化回路 |

**隐藏结构**：A4 与 A1 正交（轴间交互 1）：评估带宽决定 harness 能算多少，A4 决定其中多少流向 agent。SEAL 把反馈带宽压到理论极限（1 bit）并给出下界公式，说明反馈带宽是一个**有信息论刻度的连续旋钮**而非定性选择。第二个隐藏结构：保守非回归（c_t ≥ b_t − δ_t）+ 整体回滚意味着 A4 的最低档天然绑定 M9 的准入语义——"M9 默认语义 = 保守差分 + 最小泄露"（卡片 2）。D6（门的渐进信任/canary 并排打分）对本轴的约束是：若门的状态是连续流量份额而非布尔，评估信号必须支持 canary vs baseline 的**实时并排可比**，即 public/private 契约要扩展出 third channel（部署侧遥测）【推断】。

**反直觉结论**：(1) **泄露越多，进化越差**——35.1→12.7 是一手实证：数值反馈给了变异器可优化的目标，1-bit 只给方向不给梯度，反而鲁棒。这直接推翻"透明评估帮助 agent 学习"的直觉。(2) 反作弊不需要显式检测器——AIDE² 的双分数结构让作弊变体被选择压力自动淘汰，结构性防御（A12）优于监测性防御。

---

## 轴 A5：被评对象层级（评估的是解、求解器、还是改进策略）

**轴定义**：评估对象在元层级阶梯上的位置——L0 任务解 → L1 求解程序（harness/skill/policy）→ L2 改进策略（meta-skill/验证器）（A 组轴表，卡片 4）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| L0 任务解 | 经典 benchmark 评估 | 所有既有 benchmark 的默认 | 不解进化只选模型时 |
| L1 求解程序 | 评估 harness/skill/整个 agent 代码库。DGM：被进化对象=agent 代码库，准入是**功能性存活门**（可编译+保留编辑能力），分数只影响父代选择概率（∝ 表现分 × 有编辑功能的子代数）。Meta-Harness（arXiv:2603.28052）：端到端优化 harness，held-out 模型 × 200 题聚合 | DGM 把"准入"与"打分"分离：存活是二值的，分数是软选择压力 | 优化对象是 scaffolding/技能库时 |
| L2 改进策略 | 评估"能否生出更好后代"而非当前表现。AIDE²：内环 agent 分数 = 它在多个任务族上跑完整 autoresearch run 的聚合私有分（"a benchmark composed of benchmarks"，map→reduce）。MetaSkill-Evolve（arXiv:2607.05297）：meta-productivity P̂(m|s) 二阶效用；慢环把 H 轮历史折叠成合成 meta-failure trace 喂 Analyzer | AIDE²：16× prompt 压缩省下的 token 再投资为额外搜索步；固定美元预算下 best-of-N 类增调用策略被成本约束自动淘汰 | 自进化框架的外环 |

**隐藏结构**：L0→L1→L2 不是抽象层级而是**成本阶梯与必要性阶梯的复合**：A 组轴间交互 3 明示，每上移一层，A6 聚合成本指数上升，A3 级联从可选变必需（DGM 10/50/200 是 L1 评估的必然形态）。第二个隐藏结构：层级越高，"分数"的语义越从"表现"转向"潜力"——MetaSkill 的 P̂(m|s) 评的是分支的生殖力，这与 L0 的任务分不可比，说明 **A5 决定了 A6 聚合函数的合法语义域**。第三个隐藏结构：L2 评估天然嵌套（评一个 agent 要跑 N 个完整 run），所以统一 Evaluator 必须支持 `level` 参数与 `Candidate<ExecutorSpec>` 类型（卡片 4）。

**反直觉结论**：(1) 在 L1/L2，**分数可以不作准入**——DGM 中准入只是功能性存活门，表现分只调父代采样概率；"高分=存活"的直觉在进化框架里被解耦。(2) 美元预算约束会自动淘汰看似聪明的策略（best-of-N 增调用），说明 L2 评估的优化压力首先作用于**成本结构**而非质量【推断：AIDE² 卡片】。

---

## 轴 A6：聚合语义（嵌套评估怎么汇总成一个判定）

**轴定义**：多任务/多次运行结果的汇总算子——单任务分 → map-reduce 多任务聚合 → per-item 翻转计数（gate-not-rank）→ 预算约束下 private 聚合（A 组轴表，卡片 4）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 单任务分 | 不做聚合 | 只在 A5=L0 且任务单一时合法 | 单点诊断 |
| map-reduce 聚合 | 多任务族各跑完整 run 再 mean/加权聚合。AIDE²："a benchmark composed of benchmarks" | 固定美元成本预算下的约束优化是聚合函数的一部分 | A5=L1/L2 默认 |
| per-item 翻转计数（gate-not-rank） | EvolveNet（arXiv:2608.04968）：客户端 per-item 二值 verdict v_i∈{0,1}；服务器聚合**行为翻转证据** e_k=(F_k,B_k)（新增修复集/新增破坏集，Eq.9-10）；双层门：客户端 S_k(h_k)≥S_k(h^(t))，服务器承诺门 \|F_val\|≥\|B_val\|（Eq.17）；每客户端只需回传两个整数 | **validation 只 gate 不 rank**：§6.3 明示总分排序会颠倒真实优劣，per-item 翻转决策才稳健；聚合算子 vs select-best/delegation = 68.5 vs 64.0/66.5 | 分布式/多客户端评估；模型更新准入 |
| 预算约束下 private 聚合 | 聚合函数含成本项，淘汰超预算策略（AIDE²） | best-of-N 类增调用策略被成本约束自动淘汰 | 有硬预算的进化外环 |

**隐藏结构**：聚合算子选择本质是**"分数该用来排序还是用来放行"**的元决策。EvolveNet 的 gate-not-rank 是全书眼：总分排序颠倒真实优劣的原因是总分掩盖了 per-item 翻转的方向性——一个候选可以总分更高却破坏了更多原本正确的行为。这使 A6 与 M9 产生硬绑定：**gate-not-rank 应成为 M9 默认原则**（卡片 4 原文）。第二个隐藏结构：翻转计数 (F,B) 把聚合压缩成两个整数，说明聚合函数的输出带宽可以极低而不损失准入语义——与 A4 的最小泄露原则同构【推断】。

**反直觉结论**：(1) **排序比放行更危险**——用同一批评估数据，rank 会颠倒真实优劣、gate 却稳健（EvolveNet §6.3），推翻"排名是评估的自然产出"的直觉。(2) 聚合信息可以压缩到两个整数（新增修复数/新增破坏数）而不损失决策质量——评估的产出物不是分数而是**翻转证据**。

---

## 轴 A7：机制归因（提升是否经由预期通路）

**轴定义**：在任务分之外平行输出"机制/通路分"，取值递进：仅结果分 → +工件证据 → +时序遥测 → 任务分 × 机制分乘性合成（zero-factor）（A 组轴表，卡片 6，PAST-Bench 源码级）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 仅结果分 | 只有 task score | 无法区分"真自我改进"与"碰巧/作弊" | 对照基线 |
| +工件证据 | 检查 expected artifact 是否产生 | PAST-Bench：写入计数取 expected artifact 通道与内部工具计数的**最大值**——防绕过被观测通道 | 有声明式预期产物时 |
| +时序遥测 | 检查行为发生的顺序与通路 | mechanism_confidence = (artifact_quality + retrieval_score + artifact_presence)/3；artifact_quality = 规则关键词命中率与写入计数阈值分均值 | 需审计"怎么做到的"时 |
| 乘性合成 | `FamilyEvolveScore = max(0, AblationLift) × MechanismConfidence × AutonomousReuseRate × TransferRobustness`，任一因子为 0 总分归零；每指标带 `basis` 标签（measured/proxy/needs_runner_collection），缺失信号退化到中性默认并显式标记 | 同 Δ=+0.13 的 Hermes vs nanobot，mechanism evidence 0.64 vs 0.57（arXiv:2608.04003 §1/图10）——任务分相同、机制分可分辨 | 自改进声明的准入判定 |

**隐藏结构**：(1) **乘性 vs 加性是准入语义的岔路口**：乘性合成的 zero-factor 性质（任一因子 0 则总分 0）使"机制缺失"不可被任务分补偿——这比加性更适合准入（卡片 6 启示原文）。(2) A7 与 A8 是"自改进声明"的最低举证标准（轴间交互 4）：机制分回答"经由预期通路"，双重差分回答"确实由该机制造成"，缺一即可被 shortcut 解释。(3) basis 标签体系是 E1（评估器可观测性）的先驱思想：每个信号标注 measured/proxy/needs_collection，缺失时显式降级而非静默假设——**不可观测不等于零**【推断】。(4) "写入计数取最大值防绕过"揭示了机制归因与 A12 的耦合：被评 agent 越自主，机制观测通道本身越可能被规避。

**反直觉结论**：(1) 两个系统任务分提升完全相同（+0.13），机制分仍可分辨优劣（0.64 vs 0.57）——**结果分是自改进声明的弱证据，机制分才是强证据**。(2) 乘性归零意味着"99% 确定性 × 一个缺失证据 = 0"，这比任何阈值都激进，但正是它挡住了 shortcut 型假阳性【推断】。

---

## 轴 A8：对照/差分协议（跟谁比、怎么剥离混杂因素）

**轴定义**：提升声明的对照结构——无对照 → 单基线 → with/without 双重差分 → 多控制（no_persistence/shortcut/wrong_mechanism），Δ 须超全部控制条件上界（A 组轴表，卡片 6/7）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 无对照 | 报绝对分 | 练习效应、基线漂移全部混入 | 不可用，仅调试 |
| 单基线 | 与固定 baseline 比较差值 | 仍无法区分"机制起效"与"任何扰动都起效" | 快速筛查 |
| with/without 双重差分 | `AblationLift = (eval−baseline)^{with} − (eval−baseline)^{without}`，剥离练习效应 | PAST-Bench 把双重差分定位为**检验任何自改进声明的标准协议**（卡片 6 启示原文） | 任何机制声明的最低配置 |
| 多控制组 | `control_set: [no_persistence, shortcut, wrong_mechanism]`；family.yaml 强制 `false_positive_pattern` / `expected_control_result` 字段；家族级 Δ_f 只有**超过全部控制条件上界**才计为自我改进证据 | PAST-Bench：26 family / 204 episode / 4 能力维；7 模型 × 4 框架实验矩阵 | 准入判定、论文级声明 |

**隐藏结构**：控制组三件套不是并列的而是**针对三种具体造假/自欺模式的疫苗**：no_persistence 杀"与机制无关的扰动增益"、shortcut 杀"绕过预期通路的投机解"、wrong_mechanism 杀"走错误通路但碰巧得分"。`false_positive_pattern` 字段强制评估设计者在**看到结果之前**声明假阳性长什么样——这是预注册思想在 eval 设计中的实例【推断】。第二个隐藏结构：双重差分应成为 **M8 内建实验模式而非外部 benchmark 特性**（卡片 6 启示原文）——即 Evaluator 自己调度 with/without 两次运行，而不是指望 benchmark 提供。

**反直觉结论**：(1) "比基线好"不构成证据——Δ 必须超过 shortcut 控制组的上界，意味着一个**故意作弊的系统**是你的比较基准而非被排除项。(2) 自改进声明的成本结构是翻倍的（with/without 各跑一遍），但卡片结论是该协议应内建于 M8——正确性开销不可省，只能通过 A3 级联摊销【推断】。

---

## 轴 A9：难度刻度（评估难度的受控调节）

**轴定义**：任务难度的声明式刻度——单点 → trigger 强度分级（T0–T3）→ 迁移距离（none/near/far）→ 泛化阶数（heldout data/task/role-swap）（A 组轴表，卡片 7）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 单点难度 | 固定任务集 | 无法测量泛化，只能测量拟合 | 对照 |
| trigger 强度 T0–T3 | PAST-Bench `TRIGGER_STRENGTHS={T0,T1,T2,T3}`（schema.py:55）；canonical_anchor 强制 T2/T3，弱触发族只做 diagnostic_sibling（schema.py:470-478） | 难度被做成 schema 字段而非任务集的隐含属性 | 测"多弱的提示还能唤起能力" |
| 迁移距离 | `transfer_distance ∈ {none,near,far,near_far}`；`overfit_penalty = max(0,(near−far)/near)` | near/far 差直接转成可扣分的过拟合指标 | 量化记忆/技能的迁移价值 |
| 泛化阶数 | AIDE² 阶梯：一阶=held-out 数据（private split）、二阶=held-out 任务族、三阶=换座位（ignition test：AIDE₄₇ 当外环 agent，收敛 20 vs 40 步但渐近相同） | 三阶 ignition 的结论是 "**not strong enough evidence of ignition**"——换座位收敛更快不等于更强 | 自进化声明的最高举证档 |

**隐藏结构**：A9 的三个取值层是**同一根轴——"评估分布与优化分布的距离"——的三种刻度**：trigger 强度调任务内距离、迁移距离调任务间距离、泛化阶数调评估者/被评者的角色距离。A 组启示明示：泛化阶数可直接作为 **AdmissionGate 的梯度档位**（一阶门放行进内环、三阶门才放行外环），即 A9 是 M9 松紧度的量纲。第二个隐藏结构：难度刻度与 A2 耦合——难度越高信号越稀疏，所需 trials 越多（GAIA Level3 ICC 仅 0.304 恰是高难度端的证据）。

**反直觉结论**：(1) 换座位收敛快一倍（20 vs 40 步）却**不构成** ignition 证据——渐近相同使"加速"与"更强"解耦，泛化阶数越高，直觉性的正面结果越不可信。(2) 过拟合可以被一个公式直接定价（max(0,(near−far)/near)），但前提是评估集显式声明 near/far 划分——没有 A9 刻度的 benchmark 无法测量过拟合，只能被它骗过【推断】。

---

## 轴 A10：防 gaming / 污染控制（评估集的可信度管理）

**轴定义**：任务集的防污染结构——公开固定集 → public/heldout split → 时间门控滚动集 → canary+decontamination+功效声明（A 组轴表，卡片 11）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 公开固定集 | 静态公开 benchmark | 分数膨胀不可信：SWE-bench Verified 70–95% vs SWE-bench Pro ~23%（GPT-5/SWE-Agent 23.3%）；DeepSeek V4-Pro 在 Verified 80.6% vs 自家无污染 DeepSWE **8%** | 仅作历史对照 |
| public/heldout split | SWE-bench Pro：1,865 题 / 41 个活跃维护 repo，public+held-out+commercial 三 split | 防御 = held-out 私有集；与 A4 的 public/private 双分数同构 | 任何需长期迭代的评估 |
| 时间门控滚动集 | LiveCodeBench 按题目发布日期门控（只测训练截止后题目）；K Prize 测试集全部取自提交截止后新 filed issue；SWE-rebench / SWE-bench-Live 滚动新鲜任务 | K Prize 首轮冠军 **7.5%**（对比 Verified 70s）——无污染评估下真实水位 | 模型/agent 训练数据不可审计时 |
| canary + 去污染 + 功效声明 | canary 检测、decontamination 检查入 CI；"未发现污染"需附**功效计算**：可检测性 ∝ 污染比例 × seen/unseen 行为差 × √n（2026-08 形式化） | Berkeley RDI 审计：2,385 条 trace / 15 个 agent benchmark，其中两个上 **~67%** trace 有 reward hacking 或答案暴露；Cursor 受控重跑把 Opus 4.8 Max 87.1→73.0、Composer 2.5 74.7→54.0 | 发布任何排行榜/准入判定时 |

**隐藏结构**：A10 的真正产物不是"干净的题"而是**一个可监控的差分信号**："public 分与 heldout 分的差距本身是 gaming 指标"（卡片 11【推断】）——这把 gaming 从不可观测变为可观测（可作 X1 审计信号）。第二个隐藏结构：污染防御与时间轴纠缠——时间门控（LiveCodeBench/K Prize）是唯一对"训练集不可见"稳健的方案，但它把评估集变成消耗品，天然指向 E4（评估集补给动力学）。第三个隐藏结构：功效声明要求把"未发现污染"从安慰变成统计命题，与 A2 的 power analysis 共用数学工具。

**反直觉结论**：(1) 同一模型在污染集与干净集上的差距可以是**数量级**（80.6% vs 8%；70s vs 7.5%）——高分的绝对值几乎不携带能力信息，只有分差不携带污染信息的比较才有意义。(2) ~67% 的 trace 含 hacking 意味着在 agentic 评估中 **reward hacking 是先验而非异常**——评估设计应从"假设会被 hack"出发（SEAL 四条件正是如此）。(3) "我们没发现污染"在没有功效计算时是零信息陈述【推断：卡片 11 形式化结果的直接含义】。

---

## 轴 A11：评分器类型与校准（谁来打分、分可不可信）

**轴定义**：评分器的类型与计量保障——deterministic → LLM-judge（钉版本）→ +position-swap/κ 验证 → +isotonic 校准到 oracle（A 组轴表，卡片 10）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| deterministic | 单元测试/编译/规则 | 零方差零偏置；表达力限于可验证域 | 有自动 oracle 时永远首选 |
| LLM-judge 钉版本 | judge 模型版本入配置钉死 | PAST-Bench 实践：config.yaml 钉死 judge=MiniMax-M2.7 保可复现；SkillVetBench：不同 judge 检测率在 **35%–95%** 间波动，一次模型升级可移动整个 leaderboard（arXiv:2606.15899） | 必须用 judge 时的底线 |
| +position-swap/κ 验证 | AB+BA 双序消除位置偏置；报 Cohen's κ 而非裸 agreement | 大规模研究（arXiv:2606.19544，21 judges × 9 providers，~541k 判断）：exact-match 高估 chance-corrected 一致性 **33.8–41.3pp**；judge 排名跨 benchmark 最多移动 **14 位**；两生产 judge 高 test-retest(>0.95) 与严重 position bias(>0.10) 并存（consistency–bias paradox）；verbosity bias <0.011 | judge 上线前的验证钩子 |
| +isotonic 校准 | judge 分 S 经 isotonic regression 校准到 E[Y\|S]（reward calibration，保均值），处理 policy/deployment shift | Causal Judge Evaluation（arXiv:2512.11150v3）：连续校准比 Rogan-Gladen 二值修正 **13×** 样本高效；并发 EIF 工作证明 naive judge CI 可有 **0% 覆盖率**。UDA（2508.09724）：judge 间 SD 193.95→70.97（−63.4%），与人工 Pearson 0.651→0.812 | judge 分要跨 policy/跨时间比较时 |

**隐藏结构**：A11 是**三层栈**：选型（deterministic vs LLM）→ 计量验证（agreement/consistency/bias 三件套作 EvaluatorSpec 验证钩子）→ 统计校准（isotonic）。三层的失效模式互不相同：选型层是表达力问题、计量层是偏置问题、校准层是**跨分布可比性**问题（off-policy shift）。第二个隐藏结构：consistency–bias paradox 证明"稳定"与"正确"解耦——一个 judge 可以 test-retest 完美而自一致地偏心，所以 A2（可靠性）通过不能替代 A11 通过。第三个隐藏结构：judge 选型本身被 D 组声明为"非新轴"——它是本轴与 A14 成本轴的交点取值（自评虚高 10–15%、带 rubric 后与人工一致率 ~85%，D 组卡 9）。

**反直觉结论**：(1) 裸 agreement 是系统性谎言——高估真实一致性 33.8–41.3pp 且 21/21 judges 普遍存在。(2) **judge 的置信区间可以是 0% 覆盖率**——naive CI 不仅偏窄而是完全不含真值，未校准 judge 的"显著差异"可以是纯幻觉。(3) judge 排名不稳定到跨 benchmark 移动 14 位——"最好的 judge"这个问题本身没有稳定答案，只有"校准过的 judge"有。

---

## 轴 A12：内生 vs 外生（验收信号是否可被 agent 影响）

**轴定义**：验收信号的因果位置——endogenous（agent 自写测试）→ exogenous（密封 harness）→ 混合（self-report 仅诊断用）（A 组轴表，卡片 2；SEAL）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| endogenous | agent 自己产出/影响验收信号 | 结构性 reward hacking 敞口；Berkeley 审计 ~67% trace 含 hacking（卡片 11）为背景威胁模型 | 仅作诊断信号，永不作准入 |
| exogenous 密封 | SEAL：harness 私有审计 A(π)，隐藏 seeds/分布，与部署评估不相交；四条件——外生性、密封性、单比特反馈、保守非回归更新（c_t ≥ b_t − δ_t，拒绝即整体回滚） | 信息论下界 α+β ≥ 1−TV(P₊,P₋)；leaky-anchor 泄露后 Doubao 35.1→12.7 | 自进化主循环的准入判定 |
| 混合 | agent 可见 self-report r_t 但只作诊断；存活由密封信号决定 | AIDE² 反作弊涌现："赢 public 分数的变体活不过 private 选择"——混合结构下作弊被选择压力自动淘汰 | 工程上无法完全密封时的折中 |

**隐藏结构**：A12 是**结构性防御**而非监测性防御——它不检测 hacking，而是让 hacking 在因果上不可能影响准入（信号不在 agent 的动作可达集内）。这决定了它与其他轴的关系：A4（泄露带宽）是 A12 被部分击穿时的减压阀；A 组轴间交互 5 明示"M8/M9 代码须入 X1 谱系，且声明'可自修改位'"——**评估器自身的代码也必须声明内外生属性**，否则自进化 agent 修改评估器即绕过整个轴。第二个隐藏结构：SEAL 的"保守非回归 + 整体回滚"把外生信号的消费方式也规格化了——外生不只管信号来源，还管信号如何转化为状态变更。

**反直觉结论**：(1) 密封性的反面不是"全部泄露"而是"泄露一点"——leaky-anchor 实验中数值泄露比完全不泄露更糟（35.1→12.7），因为部分信息给了优化靶子却不给完整图景。(2) self-report 不必废除——降级为纯诊断用后它仍有价值；错误的是让它参与存活判定，而不是收集它【推断：SEAL 混合取值】。

---

## 轴 A13：报告元数据（Evaluation Card：分数的可比较性前提）

**轴定义**：评估产出附带的元数据完整度——裸分数 → +repeats/CI → 全卡（A 组轴表，卡片 8；"The Score Went Up. The Model Didn't." 2026-03；吸收 D 组卡 4 的 per-row judge provenance）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 裸分数 | 只报 score | 跨 run/跨系统不可比较；Semgrep：同 GPT-5.5 跨 harness 41 点 F1 摆幅；SWE-bench 标准化 harness vs 厂商 harness 同模型 ~20 点差距（state-of-agentic-coding 2026-07，中置信） | 不可用 |
| +repeats/CI | 附 trials 数与 95% CI 三源分解（item-sampling/stochastic/protocol） | 见 A2 | 最低报道标准 |
| 全 Evaluation Card | Minimum Viable Evaluation Card 字段：model+version+endpoint、benchmark+split+commit hash、prompting 全文或 hash、decoding 参数、ITA level(0–3)、thinking budget、repeats k 与聚合法、95% CI 三源分解、**scorer 类型与版本**、运行日期 | NIST AI 800-3 同方向；SkillVetBench 的 per-row judge provenance 是 scorer 字段的行级强化——不同 judge 检测率 35%–95%，漏记 judge 身份=分数失去解释 | 任何入库/入谱系的评估记录 |

**隐藏结构**：A13 是**所有跨时间比较的基础设施**：A2 的 CI 是卡内字段、E2 的分数谱系（评估器版本）是卡的 scorer 字段、A10 的污染审计靠 benchmark hash 字段。没有卡，历史分数无法与当前分数放在同一坐标系——这在自进化框架里是致命的，因为整个档案库（archive）的价值建立在跨代可比性上。第二个隐藏结构：harness 本身是最大的未声明变量——同模型跨 harness 摆幅 20–41 点，超过绝大多数"改进"声明的幅度，意味着 **scaffold 版本字段缺失的分数连符号都不可信**【推断】。

**反直觉结论**：(1) 分数的可比性不由分数本身决定而由元数据决定——两个 75 分之间可能隔着 41 点的 harness 噪声。(2) 元数据是**事后补不回来**的（对照 M5 轴 F 结论 3：归因数据丢了补不回来）——运行时不记 endpoint/decoding，事后任何审计都无法重建。【推断】

---

## 轴 A14：预算打包与评估经济学（eval tax 作为一等约束）

**轴定义**：评估开销的封装与经济学定位——散置参数 → depth tier 打包 → 成本（$）为硬约束的约束优化（A 组轴表【推断】轴，卡片 5/4；并入 D 组卡 7 评估预算经济学）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 散置参数 | trials/rounds/plateau 等散落各处 | 无法做预算推理；无法回答"这次评估多少钱" | 反模式 |
| depth tier 打包 | MOSS 三档打包 5 旋钮：max_iter(3/5/8)、max_plan_rounds(1/2/3)、max_code_retries(0/1/2)、n_trials_per_task(2/3/5)、plateau(1/2/3) | 预算成为单个可声明档位，与 A1 带宽档对齐 | 多档服务水平的框架默认 |
| 成本硬约束 | AIDE²：固定美元预算下的约束优化，best-of-N 增调用策略被成本约束自动淘汰 | 预算不只是上限而是**选择压力的一部分** | 自进化外环 |
| eval tax 显式定价（D 组并入） | 逐 token 算账：生成 ~$0.75/M input vs judge（前沿）~$5.00/M（7×），评估 prompt ~2500 tokens vs 生成 500（5×）——**单次评估成本 ≈ 35× 被评估生成**；配对近时 5–10×；廉价 agent 配前沿 judge 可超 100×（brizz.ai 2026-08，NA 级单源） | 工业对照：100-prompt 夜间套件 + GPT-4o-mini judge ≈ $2/晚（$60/月）；3% 在线采样（10 万日请求）≈ $90/月；中型 agent 全套 <$300/月。分层定价：deterministic 免费 <1ms / 启发式免费 <5ms / LLM judge ~$0.01–0.03/call / 多 judge $0.05–0.10/probe，内置 $50 预算熔断（aatmf-toolkit） | 决定采样率、judge 档、级联深度的联合优化 |

**隐藏结构**：本轴的关键洞察是**因果方向会反转**：预算不只是评估的输出约束，反过来决定 A1（带宽档）、A2（重复次数）、A3（级联深度）、A11（judge 选型）的合法取值域——"评估预算占比决定采样率、judge 选型、级联深度"（D 组卡 7）。第二个隐藏结构：A3 级联的经济学本质在本轴显形——级联分层定价（deterministic 免费 → LLM judge $0.01–0.03）说明级联的每一级价差约两个数量级，**级联深度 = 价格曲线的分段数**。第三个隐藏结构：D 组【推断】"M8 的 token 预算应与 M9 门控频率联合优化"——门越频繁，单次评估必须越便宜，两模块共享一条预算曲线。

**反直觉结论**：(1) 评估可以从舍入误差变成账单主导项——逐条前沿 judge 达生成成本 35×（甚至 >100×），"每条消息都评估"在经济上不可行，采样/级联不是优化而是生存条件。(2) 预算约束会**自动执行科学纪律**——AIDE² 中美元约束淘汰了 best-of-N 刷分策略，硬预算是最便宜的反 gaming 机制【推断】。(3) 夜间批量套件可以把月成本压到 $60——评估经济学的主要杠杆是**调度**（何时评）而非精度（评多准）【推断：对照 D 组卡 5/7 的夜间/采样制实践】。

---

---

# 第二部分：2026 新轴 E1–E5

## 轴 E1：评估器可观测性与漂移归因（系统变了，还是裁判变了）

**轴定义**：持续评估管线中，漂移报警必须在"被评系统退化"与"评估器自身变化"之间做出归因；评估器本身成为被监控对象（D 组卡 1/4/9；arXiv:2606.15474《Who Drifted: the System or the Judge?》）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 无可观测性 | judge 当 ground truth，漂移报警直接解读为系统退化 | 业界默认滚动 z-test 在无漂移流上误报率 **75%**（2606.15474）——默认方案基本在报假警 | 反模式 |
| anchor 集 + 双 e-process 归因 | 固定人工标注 anchor 集 + 第二条 betting e-process 监控 judge + guard-window 规则，输出 {none, system, judge} 三方裁决；anytime-valid | 真实 judge 变更：silent version bump 在 **60/60** 次运行中判为 judge drift、零误判；污染性 strict-prompt 变更在 guard width=300 下 **110/120** 正确归因（2606.15474） | 任何持续运行的评估管线 |
| 定期计量校准（维护周期） | judge 像设备一样有 shelf life：按固定节奏（每周/每版本）重打分校准集，盯 judge-versus-human 一致率，下降即信号；季度 SLO 评审含"LLM-as-judge 标准是否仍校准" | 校准集规模建议"每维度几百条对话"；自评（GPT-4o 评 GPT-4o）无 rubric 时虚高 10–15%，带 rubric 后与人工一致率 ~85%（D 组卡 9，B 级） | judge 依赖外部 API、无法钉版本时 |

**隐藏结构**：(1) **anchor 速度定律**：anchor 集评估必须跑得比被守护的主过程快（2606.15474 的设计定律）——监控者必须比被监控者便宜且快，这使 E1 与 A14 反向耦合：可观测性预算必须压在生产评估预算之下。(2) E1 与 A11 的分工是**部署前 vs 运行时**：A11 的 isotonic 校准假设 judge 固定，E1 处理的正是这个假设在生产中被 silent version bump 打破的情形；PAST-Bench 钉死 judge 版本是把 E1 问题转化为 A11 问题的工程规避。(3) 归因对象是三方 {none, system, judge}，这使 E1 与 A7 形成镜像：A7 归因被评对象内部的因果通路，E1 归因评估信号本身的来源——**评估器是被观测系统的第 N+1 个组件**。

**反直觉结论**：(1) 漂移报警的默认解释大概率是错的——z-test 75% 误报率意味着大多数"系统退化"警报其实是噪声或裁判变化；没有归因机制的监控是负资产（制造假维护工作）。(2) 裁判变化可以零误判地检测（60/60），但前提是**预存人工 anchor**——治理数据又是丢了补不回来的。(3) judge 的折旧是确定性的（版本 bump、prompt 更新），所以"校准"不是一次性动作而是有维护周期的计量学实践【推断：卡 9】。

---

## 轴 E2：分数谱系与失效机制（换裁判时，历史分数怎么办）

**轴定义**：分数携带"评估器版本"谱系；评估器更换时历史分数的处置策略——作废、保留、重估（D 组卡 2；arXiv:2606.26294 RQGM）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 无谱系（分数永存） | 历史分数默认可比 | 被旧标准"hack"过的陈旧分数残留档案，污染新评估器下的排序（RQGM 动机） | 反模式 |
| selective erasure（选择性作废） | RQGM：epoch 边界更换评估器时**删除所有由旧评估器产生的效用记录**，强制档案在新标准下重新排序；ground-truth anchor（人工标注、单元测试）数据**永久保留**。评估器晋升用 ϵ-best-belief 下界（inverse regularized incomplete Beta）在 anchor 上保守筛选 | 编码任务 71.7% vs 69.9% 通过率且 token 用量 **1.35×–1.72× 更少**；论文写作 co-evolved writer 接受率 1.78×–1.86×（40.5% vs 21.8%）；co-evolved grader ground-truth 准确率 +9%；对抗目标把 reviewer 对 AI 论文的 1.91× 过度接受率校正到与人文一致 | 评估器可进化的自进化框架 |
| 全量重估 | 新评估器回刷全部历史 | 成本 = 全档案重评，A14 下通常不可行【推断】 | 档案小或 anchor 域 |

**隐藏结构**：(1) 处置策略是**二元的而非光谱**：效用记录（judge 产出）作废、anchor 记录（ground truth）永存——区分的标准是"该分数的产生是否依赖可变的评估器"。这把 A13 的 scorer 版本字段从元数据提升为**存亡判据**：没带谱系的分数在换裁判时无法归类，只能默认作废。(2) E2 与 E3 是同一枚硬币的两面：E3 管评估器怎么变（晋升门），E2 管变了之后历史怎么办（失效机制）；ϵ-best-belief 下界晋升 + selective erasure 是 RQGM 的成套设计。(3) 与 M5 的"遗忘"轴同构但方向相反：记忆侧的教训是"降级归档不删除"，评估侧的教训是"作废但不删除 anchor"——**软证据作废、硬证据永存**【推断】。(4) 不确定性声明：RQGM 作者自述结果尚属 preliminary，长搜索视野下的尺度行为未知（D 组结论）。

**反直觉结论**：(1) 换裁判时最安全的动作是**删除历史分数而非保留**——保留看似保守，实则让被旧标准 hack 过的分数在新排序里继续套利。(2) 作废旧分数后系统反而更强且更省（71.7% vs 69.9%、token 1.35–1.72× 更少）——谱系卫生不是合规开销而是性能来源。(3) "换裁判即换度量衡"意味着跨 epoch 的分数比较在数学上无意义，自进化框架的"历史最高分"曲线需要按评估器版本分段【推断】。

---

## 轴 E3：标准级自进化与变更准入门（评估标准本身可进化，但进化需要门）

**轴定义**：评估标准（rubric/criteria）作为被进化对象（L4 Criterion-Level Self-Evolution），且每次变更需要自己的 admission gate——门的递归（D 组卡 2/3；Awesome-Reliable-Self-Evolving-Agents 的 L1–L4 分层）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 静态标准 | rubric 人工定义、冻结 | 特征失效：标准随任务域漂移而失配；AI-Scientist 新颖性评审误杀 9/10 人类已接收论文（M5 材料旁证） | 任务域稳定、合规要求高时 |
| 标准进化 + 硬门/软目标验证 | SkillCoach（arXiv:2607.01874）：新 rubric 只有在 **held-out 集上不回退一致性/准确率**才被接受 | rubric 更新的 validation gate 是准入门的递归实例——M9 需要"评估器变更"这一新准入类型（D 组结论 3） | rubric 需随域演化时 |
| 标准共进化（agent×evaluator） | RQGM：评估器与被评 agent 共进化；DR-Tulu/RLER（ICML 2026）：正/负规则在线共进化防 reward hacking；EvoRubric 对抗训练 rubric 生成器 | RQGM 数字见 E2；"Who grades the grader?"：评估指标与技能共进化 | 长期自主进化框架 |
| query 局部标准滚动进化 | SERPO（arXiv:2607.26873）：冻结评估器角色，仅 query 局部标准随策略滚动进化驱动 test-time RL | 把标准进化的作用域收窄到单 query，降低 criterion drift 半径 | 测试时计算场景 |

**隐藏结构**：(1) E3 与 A12 正交（D 组卡 3 明示）：A12 问验证器在哪（内/外生），E3 问验证器**是否可变、谁批准变更**——一个外生密封的评估器仍然可以进化，只是进化通道必须有自己的密封门。(2) **门的递归**是本轴的核心结构：M9 对候选的准入判定本身依赖评估器，评估器的变更因此是元级准入事件——SkillCoach 的 held-out 不回退门、RQGM 的 ϵ-best-belief 晋升，都是 M9 作用在"评估器变更"这一新对象类型上的实例。(3) 特征失效模式从 reward hacking 变为 **criterion drift**（L4 的定义性失效）：标准可变后，agent 不再需要 hack 固定标准，偏置可被慢循环固化放大（对照 M5 轴 G 反直觉结论 2：rubric 可进化 + 评审器有偏 = 偏置自我固化）。(4) SERPO 的 query 局部取值提示 drift 半径可用**作用域**控制——标准进化的粒度越细，漂移的爆炸半径越小【推断】。

**反直觉结论**：(1) 静态标准不是安全取值而是另一种失效模式——rubric 冻结的代价是标准与现实漂移失配（9/10 误杀），所以问题不是"要不要进化"而是"进化的门多严"。(2) 让标准可变反而可以**抑制** reward hacking（DR-Tulu 正负规则共进化的设计动机）——固定标准才是可被定向套利的靶子。(3) 评估器变更门是被评对象准入门的**前置条件**：门后的裁判若可无门变更，前门再严也形同虚设【推断】。

---

## 轴 E4：评估集补给动力学（评估器吃什么、多久更新一次）

**轴定义**：评估集的来源与更新动力学——从人工策划的静态集变为从生产失败持续补给的"生命体"（D 组卡 6；Braintrust/Latitude 实践）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 静态人工策划集 | 评估集外生给定、冻结 | 既有轴系全部隐含此假设（D 组卡 6 明示）；随分布漂移与污染而贬值（联动 A10） | 发布 benchmark 时 |
| trace-to-eval 一键补给 | Braintrust："production failures convert into eval cases in one click"——生产失败一键转入回归集 | Notion 用该闭环把问题分诊从 3 个/天提到 **30 个/天（10×）**（B 级一方数据） | 有生产流量的部署系统 |
| 自动生成 + 失败聚类 | Latitude：用 GEPA 从真实失败自动生成评估、失败模式自动聚类（Topics/Signals），issue→修复→开 PR 闭环接编码 agent | 与 A10 的时间门控滚动集（LiveCodeBench/SWE-rebench）在学术侧的对应物【推断】 | 失败样本量大、人工策划跟不上时 |

**隐藏结构**：(1) E4 是评估系统的**新陈代谢轴**：评估集是消耗品（A10 的时间门控使其不断过期、A2 的 ≥300 题要求使其不断需要增量），补给线因此不是运维杂事而是维持评估有效性的核心机制。(2) "谁决定新失败进入回归集"是治理问题——补给通道同时是**注入通道**，无门的 trace-to-eval 会把生产噪声（甚至对抗样本）直接写进准入标准，故 E4 与 E5（治理）、E3（变更门）硬性耦合：评估集变更应与 rubric 变更走同类准入门【推断】。(3) 补给方向是单向的（生产→评估集），反向（评估集→生产金丝雀）属于 D6 门拓扑，归 M9。(4) 失败聚类（Topics/Signals）使补给不只是加题而是加**结构**——聚类标签可直接映射为 A9 的任务族 schema【推断】。

**反直觉结论**：(1) 评估集的主要营养来源不是设计而是**失败**——最有区分度的评估用例是系统实际犯过的错，人工策划集测的是设计者想象到的失败。(2) 补给提速的直接收益是运维指标（分诊 10×）而非评估指标——评估集新鲜度首先是工程敏捷性资产。(3) 静态 benchmark 的贬值是热力学式的必然：冻结即开始过期，所以"好 benchmark"的定义必须包含其补给机制而非仅其内容【推断】。

---

## 轴 E5：评估治理与审计（谁有权改评估器、评估记录是否构成证据）

**轴定义**：评估器的权限与审计结构——谁有权改评估器、变更是否留审计线索、评估记录能否作为合规证据（D 组卡 4/8；吸收卡 4 的 judge 捆绑发布）。

| 取值 | 机制展开 | 关键细节（量化证据） | 什么时候选它 |
|---|---|---|---|
| 研究者全权（无治理） | 评估器由研究者自由修改、无审计 | 学术界默认；在自进化框架下等于把准入标准的钥匙交给系统内部人（含 agent 自身，联动 A12 的"可自修改位"声明） | 单次实验 |
| 版本化 + provenance | judge 像模型一样有版本、有竞技场排名；judge 与 benchmark 捆绑发布（JudgeArena，arXiv:2608.02620）；per-row 记录 evaluator 身份（SkillVetBench） | SkillVetBench：不同 judge 检测率 35%–95% 波动；一次模型升级可**移动整个 leaderboard**（model drift）——没有 provenance 的 leaderboard 不可解释 | 任何被引用的评估结果 |
| RBAC + 审计线索 | 评估器变更入 RBAC；prompt 版本与 trace 绑定（Langfuse 实践）；审计线索（Label Studio audit trails） | 工业界评估器变更已进入监管视野（D 组卡 8） | 多人/多租户系统 |
| 合规证据生成 | 评估接入治理面：风险分级、gateway 强制策略、红队映射 OWASP LLM Top 10、自动生成 EU AI Act / ISO 42001 / NIST AI RMF 审计证据（Kosmoy 类平台；意大利央行已在生产使用） | 产品对比：Braintrust eval 能力 9/10 vs Kosmoy 7/10，但治理维度 Kosmoy 独有（2026-07，B 级利益相关来源） | 受监管域部署 |

**隐藏结构**：(1) E5 的四个取值是**信任半径的递增收窄**：研究者全权 → 版本可审计 → 权限受控 → 证据对外可呈递；每一级把"评估器变更"从私人行为变成越来越公共的行为。(2) E5 是 E1–E4 的**权力层**：E1 的 anchor 集谁来标注、E2 的作废谁来执行、E3 的变更门谁来把守、E4 的补给谁来批准——四个新轴的机制全部预设了一个治理主体，E5 就是把这个隐含主体显式化。(3) 与 M5 轴 F（治理与退役）同构：M5 治理记忆条目、M8 治理评估器本身——两模块共享"治理必须被治理"的结构（M5 有偏评审器使退休静默失效，arXiv:2607.07436；此处 judge 漂移使评估静默失效，2606.15474）。(4) 对自进化框架的特殊性：agent 本身在系统内，"谁有权改评估器"的答案必须显式排除 agent 的非授权路径——即 A12 的可自修改位声明是 E5 的技术落地【推断】。

**反直觉结论**：(1) 评估能力强 ≠ 治理能力强（Braintrust 9/10 vs Kosmoy 7/10 但治理独有）——评估与治理是两个独立成熟度的产品线，选评估基础设施时两者需分别打分。(2) 一次模型升级即可移动整个 leaderboard——**排行榜的稳定性是治理产物而非统计产物**，没有 judge provenance 的排名变化无法区分"模型变了"与"裁判变了"（与 E1 同源）。(3) 合规证据不是事后文档而是评估管线的**输出格式**——EU AI Act/ISO 42001 证据自动生成意味着评估记录的 schema 设计（A13）在受监管域直接是法律工件【推断】。

---
---

## M8 跨轴全局结论

1. **杠杆最大的轴是 A4/A12（可见性 × 内外生）这对连体轴**：SEAL 的 1-bit 反馈 + 密封审计 + 保守非回归是唯一有信息论下界（α+β ≥ 1−TV）和一手实证（泄露后 35.1→12.7、~90% 拒绝率下 8 天 7 代连续改进）同时支撑的防 reward hacking 结构；在 ~67% trace 含 hacking 的先验下（Berkeley 审计），这对轴的配置错误会让其余所有轴的产出不可信——评估先保证不被骗，才谈得上准。

2. **必须联合配置的轴组**：(a) **A2 × A3 × A14**——级联末级的重复数由 ICC 收敛准则给定（8–16 vs ≥32 trials），级联深度由 eval tax 价格曲线（deterministic 免费 → judge $0.01–0.03）决定，三者是同一条预算曲线的三个投影，单独配置任何一个都会失真；(b) **A7 × A8**——机制分与双重差分共同构成自改进声明的最低举证标准，缺一即可被 shortcut 解释（同 Δ=+0.13、机制分 0.64 vs 0.57）；(c) **E2 × E3 × A13**——评估器可进化（E3）则历史分数必须带谱系（A13 scorer 字段）并接受作废机制（E2），三者缺一则换裁判即全库失真。

3. **默认值应为**：A1=multi-metric+artifacts（带字节上限与安全过滤）；A2=每次评估输出 score ± CI95 与 trials 数（最低件）；A3=相对 incumbent 阈值的级联（进化场景）；A4=public/private 双分数、对 agent 最小泄露；A6=gate-not-rank（per-item 翻转计数）作 M9 默认原则；A11=deterministic 优先、LLM-judge 必钉版本 + position-swap + 报 Cohen's κ；A12=准入信号一律外生，self-report 仅诊断；A13=全 Evaluation Card 强制入库。**总原则：M9 默认语义 = 保守差分 + 最小泄露 + gate-not-rank。**

4. **评估器自身的健康管理（E1/E2/E3/E5）是 2026 年新轴段对经典轴系的最大增量**：经典 14 轴全部隐含"评估器是固定且可信的测量工具"，而新轴段的共同主题是评估器是被观测、可折旧、可进化、需治理的第 N+1 个组件。最小落地三件套：judge 版本与 per-row provenance 入 Evaluation Card（A13/E5）、anchor 集 + judge 漂移归因（E1）、评估器变更走 M9 递归门 + 历史分数 selective erasure（E3/E2）。

5. **所有轴的共同反模式与 M5 相同：让 LLM 承担该由确定性机制承担的工作**——裸 agreement 报 judge 一致性（应报 κ，高估 33.8–41.3pp）、naive CI 报 judge 置信（覆盖率可为 0%）、z-test 报漂移（误报 75%）、总分排序做准入（应 per-item 翻转 gate-not-rank）。LLM 评分器只应产原始分，校准（isotonic）、归因（e-process）、聚合（翻转计数）、准入（保守差分）的确定性部分必须交给代码。

---

> 置信度备注：A 组第一部分与 PAST-Bench/SEAL/EvolveNet 数字为既有卡片一手调研（高）；D 组卡 7 的 35× eval tax 为单篇博客估算（方向可信、绝对值依赖定价快照）；卡 5/6/8 的工业对比（Braintrust/Langfuse/Kosmoy）为利益相关来源（B 级）；RQGM 结果作者自述 preliminary。
