# M8 Evaluator + M9 AdmissionGate 前沿扫描（Group D）
扫描窗口：2025-08 ~ 2026-08。任务：找既有轴系（评估带宽 / 统计可靠性 / 归因正确性 / public-private 可见性 / 内生-外生验证器 / 级联评估 / 门限保守度）**之外**的新维度。
标注规则：数字均为一手来源原文；推测处标【推断】。

---

## (1) 新发现卡片

### 卡 1｜评估器漂移的"归因二义性"：漂移报警无法区分"系统变差"还是"裁判换了"
- **发现**：持续评估管线把 judge 当 ground truth，但 judge 本身是 API 背后的模型——silent version bump 或评分 prompt 更新会改变打分，导致每次漂移报警在"产品退化"与"裁判变化"之间歧义。论文用固定人工标注 anchor 集 + 第二条 betting e-process + guard-window 规则给出 {none, system, judge} 三方裁决，并证明 anytime-validity 和"anchor 必须跑得比被守护的主过程快"的设计定律。
- **来源**：arXiv 2606.15474《Who Drifted: the System or the Judge? Anytime-Valid Attribution in LLM Evaluation Pipelines》（2026-06-13，S 级）。
- **量化证据**：对真实 judge 变更，silent version bump 在 60/60 次运行中被判定为 judge drift、零误判为系统问题；污染性 strict-prompt 变更在 guard width=300 下 110/120 次正确归因；而业界默认的滚动 z-test 在无漂移流上误报率 75%。
- **为何在轴系外**：现有"归因正确性"轴（PAST-Bench 通路归因）归因的是**被评估对象内部**的因果通路；这里归因的是**评估信号本身**的来源（system vs judge）。评估器不再是测量工具而是被监控对象——这是"评估器可观测性"轴。

### 卡 2｜评估器更换时的"历史分数作废"（selective erasure）与谱系绑定
- **发现**：RQGM（Red Queen Gödel Machine）在 epoch 边界更换评估器时，**删除所有由旧评估器产生的效用记录**，强制档案在新标准下重新排序，防止被旧标准"hack"过的陈旧分数残留；而 ground-truth anchor（人工标注、单元测试）数据永久保留。评估器晋升用 ϵ-best-belief 下界（inverse regularized incomplete Beta）在 anchor 上保守筛选。
- **来源**：arXiv 2606.26294《The Red Queen Gödel Machine: Co-Evolving Agents and Their Evaluators》（2026-06-24，Cambridge/NVIDIA，S 级）。
- **量化证据**：编码任务 71.7% vs 69.9% 通过率且 token 用量 1.35×–1.72× 更少；论文写作 co-evolved writer 接受率 1.78×–1.86×（40.5% vs 21.8%）；co-evolved grader ground-truth 准确率 +9%；对抗目标把 reviewer 对 AI 论文的 1.91× 过度接受率校正到与人文一致。
- **为何在轴系外**：分数携带"评估器版本"谱系，换裁判即换度量衡，历史可比性需要显式失效机制。这既不是统计可靠性也不是保守度——是**评估结果的时效性与谱系（score lineage / validity window）**轴。

### 卡 3｜"标准级自进化"（criterion-level self-evolution）已成独立层级，特征失效模式是 criterion drift
- **发现**：自进化 agent 综述生态（Awesome-Reliable-Self-Evolving-Agents）把进化对象分为 L1–L4，**L4 = Criterion-Level Self-Evolution**（评估标准本身进化），并明确其特征失效为 **criterion drift**。2026 年该目录下已有一整批工作：DR-Tulu/RLER（ICML 2026，正负规则在线共进化防 reward hacking）、EvoRubric（对抗训练 rubric 生成器）、SERPO（测试时 RL 中 query 局部标准随策略滚动进化）、RubricBench（ACL 2026，对齐模型生成 rubric 与人类标准）、"Who grades the grader?"（评估指标与技能共进化）、iRULER、OnlineRubrics、CoReflect 等。SkillCoach 只是其中之一（其硬门/软目标验证门控：新 rubric 只有在 held-out 集上不回退一致性/准确率才被接受）。
- **来源**：github.com/wkqdzkd/Awesome-Reliable-Self-Evolving-Agents（2026 持续更新，S 级）；arXiv 2607.26873 SERPO（2026-07-29）；arXiv 2607.01874 SkillCoach（2026-07-02）。
- **量化证据**：SERPO 框架在冻结评估器角色下仅由 query 局部标准进化驱动 test-time RL；DR-Tulu 同时生成正/负规则以"鼓励探索同时抑制 reward hacking"（机制描述，论文内数字未取）。
- **为何在轴系外**：元操作可学习轴的评估版——评估器/标准成为**被优化、被进化的对象**，且进化本身需要准入机制（rubric 更新的 validation gate）。这与"内生 vs 外生验证器"正交：内外生问的是验证器在哪，这里问的是验证器**是否可变、谁来批准变更**。

### 卡 4｜评估器作为一等制品（artifact）：judge 与 benchmark 捆绑发布、可复现
- **发现**：JudgeArena 指出"调优后的开源 judge 很少随 benchmark 捆绑发布"，把 meta-evaluation 例程与竞争性 benchmark 集成在同一框架，让 judge 像模型一样有版本、有竞技场排名。工业侧 SkillVetBench 的做法是**逐行记录 evaluator 身份**（per-row judge provenance）并推荐 ensemble 评分。
- **来源**：arXiv 2608.02620 JudgeArena（2026-07，S 级）；arXiv 2606.15899 SkillVetBench（2026-06-14）。
- **量化证据**：SkillVetBench 报告不同 judge 的检测率在 35%–95% 之间波动；一次模型升级可以**移动整个 leaderboard**（model drift）；低温采样降低但不消除 run-to-run 不确定性。
- **为何在轴系外**：judge 的版本谱系/可复现性/可审计性——**评估器治理**维度。35%–95% 的裁判间方差说明"judge 选型"本身是一个需要管理的决策变量，不属于既有任何一轴。

### 卡 5｜评估→合并阻断（merge gating）成为 CI/CD 原生能力
- **发现**：Braintrust 的原生 GitHub Action 在每个 PR 上跑评估套件、把结果贴到 PR、质量分下降时**自动阻断合并**；Langfuse 无此能力（需人工评审）。业界实践模板："PR 上跑 unit evals，合并到 main 跑 golden dataset（50–200 traces）并对比上次成功部署基线，回归 >3% 阻断部署；生产侧 5–10% 采样在线评估"。
- **来源**：braintrust.dev/articles/langfuse-alternatives-2026（2026-06-21，B 级）；kunalganglani.com/blog/evaluate-ai-agents-production（2026-07-12，B 级）。
- **量化证据**：推荐起始回归阈值 3%（随数据集成熟收紧）；Level 2 评估开销每次部署 3–8 分钟；Langfuse 19/50 的财富 50 强采用、23k+ GitHub stars，2026-01 被 ClickHouse 收购。
- **为何在轴系外**：门控不再是一个"保守度参数"，而是**嵌入软件工程管线的发布控制面**（release control plane），有明确的 gate placement（pre-merge / pre-deploy / post-deploy 三层）与失效→数据回流闭环。门的"位置拓扑"是轴系外维度。

### 卡 6｜生产失败→评估集的一键补给线（trace-to-eval loop）与评估集自动生长
- **发现**：Braintrust"production failures convert into eval cases in one click"；Latitude 用 GEPA 从真实失败自动生成评估、失败模式自动聚类（Topics/Signals），并把 issue→修复→开 PR 的闭环接到编码 agent（MCP）。评估套件从"人工策划的静态集"变成"从生产持续补给的生命体"。
- **来源**：braintrust.dev/articles/agent-observability-complete-guide-2026（2026-06-21）；latitude.so/blog/agent-first-comparison-guide-vs-braintrust（2026-03-26）。
- **量化证据**：Notion 用该闭环把问题分诊从 3 个/天提到 30 个/天（10×）。
- **为何在轴系外**：评估集的**来源与更新动力学**（dataset supply chain）——评估器吃什么、多久更新一次、谁决定新失败进入回归集。这是评估的"新陈代谢"轴，既有轴系全部假定评估集外生给定。

### 卡 7｜评估成本经济学：judge 成本可达生成成本的 35×
- **发现**：逐 token 算账：2026 年中快照，生成模型（GPT-5 mini 级）约 $0.75/M input tokens，judge（前沿模型）约 $5.00/M（7×），且评估 prompt 含全量历史+rubric 约 2500 tokens vs 生成 500 tokens（5×）——单次评估成本 ≈ 35× 被评估的生成；judge 与 agent 配对更近时降到 5–10×，廉价 agent 配前沿 judge 可超 100×。"每条用户消息都触发前沿评估时，评估从舍入误差变成推理账单的主导项"。
- **来源**：brizz.ai/blog/llm-as-a-judge-cost（2026-08-12）。
- **量化证据（工业界另一侧）**：100-prompt 夜间套件 + GPT-4o-mini judge ≈ $2/晚、$60/月；3% 在线采样（10 万日请求）≈ $90/月；中型生产 agent 全套评估 <$300/月（hireagentic.dev，2026-04-27）。级联评估分层定价：deterministic 免费 <1ms、启发式免费 <5ms、LLM judge ~$0.01–0.03/call、多 judge 高stakes $0.05–0.10/probe，内置 $50 预算熔断（aatmf-toolkit，2026-02）。
- **为何在轴系外**：**评估预算占比**（eval tax）作为一等设计约束，决定采样率、judge 选型、级联深度——是经济学轴，不属于带宽或级联结构本身。【推断】对自进化框架，M8 的 token 预算应与 M9 门控频率联合优化。

### 卡 8｜评估的治理/合规格式化：EU AI Act、ISO 42001 证据生成
- **发现**：Kosmoy 类平台把评估接入治理面：每个 AI 系统风险分级、gateway 强制策略、红队测试映射 OWASP LLM Top 10、自动生成 EU AI Act / ISO 42001 / NIST AI RMF 的审计证据；意大利央行已在生产使用。Braintrust 等评估平台则无红队、无强制、无合规证据生成（截至 2026-07）。
- **来源**：kosmoy.com/resources/blog/kosmoy-vs-braintrust（2026-07-31）。
- **量化证据**：产品对比中 Braintrust eval 能力 9/10 vs Kosmoy 7/10，但治理维度 Kosmoy 独有。
- **为何在轴系外**：**谁有权改评估器、评估记录是否构成审计证据**——治理轴。学术界评估器默认由研究者自己全权控制；工业界评估器变更已进入 RBAC、审计线索（Label Studio audit trails、Langfuse prompt 版本与 trace 绑定）的监管视野。

### 卡 9｜judge 校准的"维护周期"成为显式运维项
- **发现**：生产漂移监控指南把"季度评估 prompt 评审：LLM-as-judge 标准是否仍校准"列入季度 SLO 评审清单；judge 漂移检测的操作化是"按固定节奏（每周/每版本）重打分校准集，盯 judge-versus-human 一致率，下降即信号"。judge 选型上，自评（GPT-4o 评 GPT-4o）无 rubric 时分数虚高 10–15%，带 rubric 后与人工一致率约 85%。
- **来源**：valuestreamai.com/blog/ai-monitoring-in-production-guide-2026（2026-05-07）；scorable.ai/post/multi-turn-llm-evaluation-techniques-2026（2026-03-16）；hireagentic.dev（2026-04-27）。
- **量化证据**：校准集规模建议"每维度几百条对话"；虚高 10–15% / 一致率 ~85%。
- **为何在轴系外**：评估器有**维护周期与折旧**（calibration cadence / shelf life）——评估器像设备一样需要定期计量校准，这是计量学概念，不在任何现有轴上。

### 卡 10｜canary/staged rollout 与 judge 实时打分的融合
- **发现**：AI 模型金丝雀发布的 2026 指南：model registry 追踪每个版本的谱系与评估结果，canary 窗口内用 LLM-as-judge 对 canary vs baseline 实时打分并排对比，晋升/回滚是元数据操作。Google Cloud Deploy 支持自动分阶段百分比推进+部署分析。
- **来源**：mlflow.org/articles/what-is-canary-deployment-ai（2026-07-23，B 级）。
- **量化证据**：无硬数字（工具能力描述）。
- **为何在轴系外**：门控从"一次性二元准入"变为**流量分级的渐进信任**（staged trust），门的状态空间是连续的流量份额而非布尔值。阈值保守度轴只描述门的松紧，不描述门的"渐进结构"。

---

## (2) 结论

### 候选新轴清单（按优先级）

1. **评估器可观测性与漂移归因**（evaluator observability / drift attribution）：漂移信号必须裁决"系统变了还是裁判变了"。卡 1、4、9。
2. **分数谱系与失效机制**（score lineage / selective erasure）：分数绑定评估器版本，换裁判时历史分数如何处置（作废、保留、重估）。卡 2、4。
3. **标准级自进化与变更准入门**（criterion-level self-evolution + meta-gate）：评估标准本身是可进化对象，且进化需要自己的 admission gate（SkillCoach 硬门/软目标、RQGM 的 ϵ-best-belief 晋升）——**M9 需要一个"评估器变更"的准入实例**，即门的递归。卡 2、3。
4. **评估集补给动力学**（dataset supply chain / eval 新陈代谢）：评估集从生产失败持续补给、自动生长，评估器的"食谱"是一等设计对象。卡 6。
5. **评估预算经济学**（eval tax / budget share）：评估开销相对生成开销可达 35×（逐条 judge）或 <$300/月（采样制），预算约束反过来决定采样率与级联深度。卡 7。
6. **门的拓扑与渐进性**（gate placement & staged trust）：pre-merge / pre-deploy / post-deploy 三层放置 + canary 式连续流量份额，取代单点二元门。卡 5、10。
7. **评估治理与审计**（eval governance）：谁有权改评估器、评估记录作为合规证据（EU AI Act/ISO 42001）、judge 身份逐行记录。卡 4、8。

### 看似新、实则旧轴取值的项

- **在线/持续评估、shadow eval、5–10% 采样**：只是"评估带宽 × 可见性"在生产流量上的取值扩展，外加统计可靠性轴下的采样率参数。**不构成新轴**（新的是卡 1 的归因二义性，不是在线评估本身）。
- **级联评估分层定价**（deterministic→heuristic→LLM judge 三层）：已知级联轴的成本参数化，属旧轴取值。
- **回归阈值 3% 起步、随数据集成熟收紧**：门限保守度轴上的取值建议。
- **judge 用便宜模型（gpt-4.1-mini）还是前沿模型**：内生/外生验证器轴与成本轴的交点取值。
- **A/B 测试与 interleaving**：传统实验平台概念平移，仍落在统计可靠性 + 带宽轴内。

### 不确定性声明
- 卡 7 的 35× 为单篇博客（NA 级权威）的估算，方向可信、绝对值依赖具体模型定价快照。
- 卡 5 的 "Langfuse 需人工评审" 为 Braintrust 官方对比文（利益相关方），可能有偏【推断】。
- RQGM 作者自述结果尚属初步（preliminary），长搜索视野下的尺度行为未知。
