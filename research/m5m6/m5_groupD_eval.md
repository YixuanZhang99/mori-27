# M5 Memory 定稿依据：记忆系统的评估方法与失效模式

调研日期：2026-08-25 · 负责：agent-eval 方向调研
范围：PAST-Bench 源码深挖 / 记忆失效模式文献梳理 / 记忆 benchmark 对比 / 对 AutoResearch M5 的设计建议
标注约定：**【原文】**=源码或论文可直接核验；**【推断】**=调研者基于证据的推论。

---

## 1. PAST-Bench 深挖（Gen-Verse/PAST-Bench, arXiv:2608.04003）

### 1.1 总体设计

**【原文】**（arXiv:2608.04003v1, §1/§3）：PAST-Bench 把"跨会话自我改进"建模为**性能归因问题**——后续会话的提升可能来自保留的经验，也可能来自基座模型、运行时、prompt、检索捷径、任务难度或评分噪声。评测单元不是单任务而是**任务家族（family）内的有序轨迹**：26 个 scenario、204 个 episode，覆盖四类能力——Memory（5 family/41 episode）、Procedural Reuse（8/64）、Proactive Information Gathering（6/48）、Update（7/51）。每个 family 的结构为：learn episode（Update 族另有 update episode）把目标（条款/流程/纠正）写入持久化基质；evaluation episode 在**全新会话、触发词被移除**的条件下探测复用；control episode 检验增益不能被 prompt 捷径、表面记忆、陈旧复用或写错基质解释。

**【原文】**（README.md）：配套 Hermes+ 框架，在 agent loop 上加了五个机制——Plan、Render、Route、Gate、Close（plan-time 检查、经验呈现、路由、检索门控、收尾更新），作为诊断驱动的参照基线。

### 1.2 family.yaml 协议（源码：`self-evolve-tasks-v2/<ability>/<FAMILY>/family.yaml`，schema 校验：`src/past_bench/self_evolve_v2/schema.py`）

**【原文】**（schema.py:30–100）关键字段体系：
- `primary_ability`（memory_ability / procedural_ability / proactive_information_gathering / update_ability），`expected_substrate`（memory / skill / session_search / planner_policy / prompt_rule / tool_policy / …），`primary_trigger` + `trigger_category`（17 类：direct_explicit_save_instruction、explicit_correction、conflict_update、embedded_durable_instruction、repeated_cases_induction、failure_reflection、passive_document_exposure、delayed_outcome_feedback、mixed_signal_arbitration 等）。
- **trigger 强度分级**：`TRIGGER_STRENGTHS = {"T0","T1","T2","T3"}`（schema.py:55）。语义未在论文正文定义，从家族文件可还原（见 1.4）。
- `benchmark_role ∈ {canonical_anchor, diagnostic_sibling}`；**canonical_anchor 强制 `trigger_strength ∈ {T2,T3}` 且 compatibility_gate=strict**（schema.py:470–478）——即"正式计分锚点必须用强触发"，弱触发家族只做诊断。
- `transfer_distance ∈ {none, near, far, near_far}`、`overwrite_mode`、`noise_profile`、`family_length_tier`。
- `episode_order` 与 `history_plan`：把 episode 分为 cold / learn / update_or_stabilize / reflection / eval_near / eval_far / control 桶，用 `anchors`（save_after 快照）+ `branches`（fresh / continue / from_anchor）实现"跨会话但同一份持久化状态"的受控编排。
- 归因合同字段：`what_is_learned` / `what_persists` / `what_counts_as_reuse` / `false_positive_pattern` / `must_demonstrate` / `control_design` / `expected_control_result`。authored 状态的家族**强制**填写 cold_design、control_design、expected_control_result（schema.py:495–505）。

### 1.3 三类配对控制（paired controls）

**【原文】**（SM06_temporary_exception_pollution/family.yaml 的 `control_set: [no_persistence, shortcut, wrong_mechanism]` 与 `control_design`）：
- **no_persistence**：删除先前沉积的状态（"removes the stored default"），给出无记忆对照基线；
- **shortcut**：把当前规则直接暴露在 episode 局部上下文里（"exposes the current durable rule locally"）——若 agent 在 shortcut 控制下也能做对，说明评测任务本身可被当轮信息解出，Δ 不构成记忆证据；
- **wrong_mechanism**：把规则放在错误的基质里（"places the active rule and expired-exception notice inside the current note instead of memory"）——区分"真走了记忆通路"与"走了别的通道恰好也对"。
论文层面（§3.2）另有第四类表述：stale controls（暴露过时记忆）与 distractor controls（注入相似但无关信息）。**【原文】**（§3.2）：家族级 Δ_f 只有在**超过全部控制条件给出的上界**时才被接受为自我改进证据。

### 1.4 trigger 强度 T0–T3

**【推断】**（依据 memory_ability/SM05_weak_trigger_preference_adoption/family.yaml，论文无定义）：T3=显式"请保存"指令（direct explicit save instruction，最强）；T2=直接指令但无显式 save 措辞；T1=嵌入便签/文档中的被动暴露（最弱）；T0 推测为无触发/纯观察。SM05 有意把 T3/T2/T1 映射到三个互不冲突的规则槽（TSV 结构 / 优先级归一化 / 日期归一化），使评测能**按触发强度逐槽归因**哪一档获取失败。canonical anchor 必须 T2/T3（schema 强制），弱触发族（T1）定位为 diagnostic_sibling。

### 1.5 Task score vs Mechanism score 解耦

**【原文】**（论文 §4.1）：Task score s_e∈[0,1] 为 episode 级任务分；Δ = S^{w/ evolve} − S^{w/o-evolve}（家族内均值差，能力级为家族宏观平均）；Mechanism score 单独报告，"so that higher accuracy is not confused with evidence-aligned self-evidence"。实证发现同 Δ 不同机制分：Hermes vs. nanobot 在 Δ=+0.13 相同时 mechanism evidence 0.64 vs 0.57（§1贡献点(2)、图 10 attribution frontier）。

**机制分计算细节【原文】**（`src/past_bench/graders/self_evolve_helpers.py:362` `compute_self_evolve_mechanism_scores`）：
- **artifact_quality_score** = （规则关键词命中率 `rule_keyword_hits.hit_rate` 与 写入计数阈值分 `min(actual/required,…)` 的均值，按 artifact_contract 配置组装）；写入计数按 expected artifact 类型取 memory_entry_delta 或 skill_count_delta 与内部工具计数（memory_write_count / skill_create+update_count）的最大值——**防止 agent 绕过被观测通道**。
- **retrieval_score** = 各 retrieval_contract 阈值分（min_memory_reads / min_memory_injections / min_skill_reads / min_session_search_calls / min_retrieval_signals / min_memory_writes / min_skill_updates）的均值；无显式契约时退化为 used_expected_signal 的 0/1。
- **mechanism_confidence** = (artifact_quality + retrieval_score + artifact_presence)/3（session_search 基质例外，=retrieval_score）。
- **noise_resistance_score**：若持久化产物中出现 forbidden_rule_keywords（不应被持久化的一次性/陈旧规则），按命中率线性扣减——**直接量化"例外/噪声污染"**。
- **stale_memory_resistance_score**：有 updated_rules/changed_skill_names/added_rules 记 1 否则 0；shortcut_resistance = (noise + max(stale,0.5))/2。
- **transfer_quality**：retrieval_before_first_update（先检索后写入）记 1.0，仅用了预期信号记 0.5，否则 0——奖励"先查后写"的正确顺序。

**汇总层【原文】**（`src/past_bench/metrics/v2_layer1.py`）：家族级
`FamilyEvolveScore = max(0, AblationLift) × MechanismConfidence × AutonomousReuseRate × TransferRobustness`；
AblationLift = (eval−baseline)^{with} − (eval−baseline)^{without}（双重差分，剥离练习效应）；TransferRobustness = clip01(eval_far/eval_near)；ShortcutResistance = clip01(1 − shortcut_score/eval_score)；AutonomousReuseRate 以 evaluation 桶 retrieval_before_success_rate 为代理。每个指标带 `basis` 标签区分 measured / proxy / needs_runner_collection——**测量来源透明化**，缺失信号退化到中性默认并显式标记。

**能力特异的 Layer-2 指标【原文】**（`v2_layer2.py`）值得 M5 直接借用：
- memory：`write_precision` / `recall_accuracy` / `retention_horizon` / `memory_pollution_rate`（runner 信号）；`over_storage_penalty` = learn 阶段 memory 写入占总写入比（**过度存储惩罚**）。
- procedural：`skill_creation_rate`（learn 期每 episode 建技能数）、`transfer_gain` = eval_far − eval_near、`overfit_penalty` = max(0,(near−far)/near)（**近迁移好而远迁移差 = 经验过拟合**）。
- update：`overwrite_correctness`、`memory_pollution_rate`、`stale_leak_penalty`。
- Layer-3（`v2_layer3.py`）按 trigger 给诊断：explicit_instruction→first_use_correctness；explicit_correction→correction_retention / repeat_violation_rate；conflict_update→overwrite_completeness / stale_leak；repeated_cases_induction→sample_efficiency / transfer_without_keyword_overlap（far/near）/ induction_quality（far−baseline）；failure_reflection→reflection_to_behavior_conversion。
- trace 级取证（`v2_trace_parse.py`）：`first_use_turn`（规则首次出现在工具输入/回答的轮次）、`repeat_violation_count`（被纠正后再次使用禁用措辞的次数）、`stale_leak_events`（终答仍含应被覆盖的旧短语）。

**【原文】**（论文 §4.2 + 附录 D.2）：机制消融显示 E3/E4/E5 分别对 Procedural/Info/Update 贡献最大单机制 Δ；E2（Render）在 PC03 案例中反而**降低** Procedural gap（+0.085→+0.108 去掉 E2 后）——机制间存在负交互，全量堆机制不单调。

---

## 2. 记忆失效模式分类表

| # | 失效模式 | 成因 | 已观测案例（一手来源） | 防护机制 |
|---|---------|------|----------------------|---------|
| F1 | **Context collapse / brevity bias** | 迭代式整体重写上下文，LLM 压缩倾向逐级侵蚀细节 | **【原文】**ACE（arXiv:2510.04618）："iterative rewriting erodes details over time"，brevity bias 丢弃领域启发式与失败模式 | 结构化增量更新（itemized delta，不重写全文）；条级追加+策展（Curator）替代 monolithic rewrite |
| F2 | **记忆投毒（memory poisoning）** | 写入通道无来源校验：指令-数据边界盲（V-M1）、来源归因失败（V-M2）、写入策略欠规约（V-P1）、压缩无来源过滤（V-P2）、写路径无验证（V-S1）、技能创建无校验（V-S4）、自我改进放大（V-S5） | **【原文】**AgentPoison（NeurIPS'24, 2407.12784）；MINJA（NeurIPS'25, 2503.03704，query-only 注入成功率>95%、ASR>70%）；MemoryGraft（模仿历史成功轨迹导致持续行为漂移）；Zombie Agents（自我强化注入持久控制）；系统化研究 arXiv:2606.04329 定义 M=(S,W,R)、四写入通道 C1–C4、ASR/RSR 双指标；OWASP Agentic Top10 ASI06 | 写入门控（来源/意图/范围校验）；write-path 验证（Truth-Maintained Memory Agent, NeurIPS'25）；A-MemGuard 主动防御（2510.02373）；SMSR 密码学溯源（2606.12703）；MemAudit 事后因果归因审计（2605.23723）；不信任内容隔离（V-S2 对策） |
| F3 | **经验过拟合 / 负迁移** | 从少数 learn 案例归纳出表面规则；近迁移（关键词重叠）好、远迁移差 | **【原文】**PAST-Bench `overfit_penalty=(near−far)/near`、`transfer_without_keyword_overlap=far/near`；SM06 `false_positive_pattern`："remembers both the durable rule and the one-week exception, causing negative transfer"；MemoryGraft 的行为漂移亦属此类 | near/far 双距离评测；远迁移分必须清掉触发词与关键词重叠；规则抽象度检查（induction_quality=far−baseline） |
| F4 | **Exception pollution（例外规则污染）** | 临时/有作用域的例外被当作持久规则写入；过期后不消退 | **【原文】**PAST-Bench SM06_temporary_exception_pollution（临时 Maya 例外过期后仍污染 durable RISK-CANON 默认；`expected_control_result`：污染时 with_persistence 可**差于** no_persistence）；SM07 scoped_rule_migration；noise_resistance 用 forbidden_rule_keywords 检测一次性规则入库 | 记忆条目带 TTL/作用域元数据；过期清理（Close 机制）；写入时区分 durable default vs temporary exception；stale 控制家族常驻回归 |
| F5 | **记忆膨胀与检索噪声** | 无条件写入导致库膨胀；检索 top-k 噪声淹没信号；存储成本爆炸 | **【原文】**PAST-Bench `over_storage_penalty`（learn 期写入占比）、`memory_pollution_rate`；MemDelta（2606.29914）：记忆操作可占 agent 执行时间 >80%，500 会话事实抽取耗 1.6 亿 token；ConvoMem：~150 会话以下全上下文反而优于检索记忆——短程 benchmark 压缩了要测的差异 | 写入预算与准入（write gate）；检索精度单独计分（retrieval_precision）；成本与延迟纳入报告轴；容量压力测试 |
| F6 | **写入门缺失 → 自我强化的错误信念** | 反思/总结不经外部校验直接入库；后续检索把它当先验知识，循环加固 | **【原文】**arXiv:2606.04329 V-S5 "Self-Improvement as Amplification"：投毒技能每次执行无误即被视为验证通过，演化为"优化良好的对抗程序"；Zombie Agents 自我强化记忆注入；Misevolution（2509.26354）：记忆积累后安全对齐退化 | 反思结论须落地验证（执行反馈/外部证据）后才提升置信度；记忆条目带置信度与证据计数；冲突更新协议（PAST-Bench update_ability 的 overwrite_correctness + stale_leak_penalty）；STALE（2605.06527）测"agent 是否知道记忆已失效" |
| F7 | **陈旧状态泄漏（stale reuse）** | 事实被更新后旧值仍可被检索/复述 | **【原文】**PAST-Bench conflict_update trigger 的 `overwrite_speed/completeness/stale_leak_penalty`；v2_trace_parse.stale_leak_events；LongMemEval Knowledge-Update 题型 | supersession 语义（新条目逻辑废止旧条目而非共存）；检索按时间戳+有效性过滤；终答前 stale 短语扫描 |
| F8 | **评估假象：无配对控制下的假增益** | 增益来自模型/练习效应/当轮泄漏而非记忆；LoCoMo 答案键 6.4% 错误、LLM judge 接受 62.81% 故意错答；真实实体泄漏进预训练 | **【原文】**MemDelta（2606.29914）：主流评测骨架仍是"对比 no-memory 基线"，embedding 模型不披露、写路径成本不报；Ground-Truth-First（2607.21962）：LoCoMo 审计 99/1540 分损坏；MemGym：无虚构化时前沿模型 0.70–0.85（污染） | 配对控制 + 双重差分（PAST-Bench）；虚构实体防污染；judge 对抗性校验；公开 embedding/写路径成本 |

---

## 3. 记忆 benchmark 评估协议对比

| Benchmark | 评测对象 | 协议要点 | 与 PAST-Bench 的关键差异 |
|---|---|---|---|
| **LoCoMo**（ACL'24） | 长对话记忆 QA | 10 段 18–30 会话对话，1540 QA（单跳/多跳/时序/开放域/对抗），LLM-as-judge | 静态 QA、无 agent 行为、无持久化开关控制；答案键质量被审计质疑（6.4% 错） |
| **LongMemEval**（ICLR'25, 2410.10813） | 聊天助手长期记忆 | 500 问嵌入可扩展聊天史（128K–1.5M token），5 能力：信息抽取/多会话推理/时序/知识更新/拒答；index-retrieve-read 三阶段分解 | 读路径为中心；不测写入决策与复用行为；无机制归因 |
| **MemoryBench**（2510.17281, THUIR） | 记忆+持续学习 | LLM-as-user 模拟显式/隐式反馈，20k 案例，声明式+程序性记忆，off-policy 反馈日志 | 有反馈学习维度但无配对持久化消融；结论：现有系统"不能有效利用程序性反馈" |
| **MemoryAgentBench**（ICLR'26, 2507.05257） | 增量多轮交互 | 4 能力：Accurate Retrieval / Test-Time Learning / Long-Range Understanding / **Selective Forgetting**（FactConsolidation） | 选择性遗忘是 PAST-Bench update 能力的近亲，但仍无捷径/错误机制控制 |
| **MemoryArena**（2602.16313） | 多会话 agentic 任务 | 每任务 ~6.9 个显式相互依赖子任务、~57 动作；购物/旅行/渐进搜索/形式推理；SR+PS | 任务完成导向、有跨会话依赖；发现 LoCoMo 上近饱和的 agent 在此惨败、外部记忆有时**有害**；但无机制证据轴 |
| **MemDelta**（2606.29914） | 评测方法论 | 受控基线+隐藏混杂审计；主张披露 embedding、报告写路径成本 | 是对上述 benchmark 的元批评，与 PAST-Bench 的 paired-control 思路同源 |
| **BEAM**（ICLR'26） | 超长程（10M+ token）记忆 | 规模压力 | 不测跨会话改进归因 |
| **AMemGym**（ICLR'26） | 交互式动态记忆更新 | LLM 模拟用户 | 交互性类似，无控制家族 |
| **STALE**（2605.06527）/ **HaluMem**（2511.03506） | 记忆失效/记忆幻觉 | "agent 何时知道记忆已过期" / 记忆系统幻觉评测 | 单点失效模式专项，可作 M5 的补充探针 |
| **LoCoMo-Plus**（2602.10715） | 认知记忆（Level-2） | cue-trigger 语义断裂下的隐式约束一致性评测；证明字符串匹配与任务明示 prompt 系统性误导 | 对应 PAST-Bench 的"评测时移除触发词"思想（T1 弱触发/embedded） |
| **PAST-Bench**（2608.04003） | 跨会话自我改进归因 | 有序 family 轨迹 + with/without 双重差分 + 三类配对控制 + 机制证据分 + T0–T3 触发强度 + near/far 迁移 | 唯一把"任务分"与"机制分"解耦并要求 Δ 超过控制上界的协议 |

**【推断】**对比结论：QA 系 benchmark（LoCoMo/LongMemEval）回答"检索得准不准"；agentic 系（MemoryArena/MemoryBench）回答"任务做得好不好"；只有 PAST-Bench 回答"提升是否来自预期记忆通路"。三者互补，M5 评估应分层复用而非二选一。

---

## 4. 记忆评估协议设计空间（轴向分解）

1. **配对控制轴**：无控制（LoCoMo 式）→ 单一 no-memory 基线（主流）→ 双重差分 with/without（PAST-Bench Δ）→ 多控制家族（no_persistence / shortcut / wrong_mechanism / stale / distractor），Δ 须清过控制上界才计为证据。
2. **归因证据轴**：纯结果分 → 检索日志 → 产物 diff（写入计数、关键词命中、forbidden 词检测）→ 时序证据（retrieval_before_first_update、first_use_turn、repeat_violation_count）→ 任务分×机制分的乘性合成（FamilyEvolveScore）。
3. **触发强度轴**：T3 显式保存指令 → T2 直接指令无 save 措辞 → T1 嵌入文档被动暴露 → T0 无信号。canonical 计分用 T2/T3，T1/T0 作诊断探针（schema 强制的角色-强度绑定值得借鉴）。
4. **迁移距离轴**：同分布 replay → near（同域换面）→ far（去关键词重叠/换结构）；用 overfit_penalty=(near−far)/near 与 induction_quality=far−baseline 把"真抽象"与"表面记忆"分开。
5. **污染与卫生轴**（PAST-Bench 有部分、文献补充）：forbidden_rule_keywords 命中、over_storage_penalty、memory_pollution_rate、stale_leak、写路径成本（MemDelta）。
6. **时间轴**：retention_horizon、TTL 失效后复测（SM06 的 expiry 协议）、多轮纠正保持（correction_retention）。

---

## 5. 对 AutoResearch M5 的建议

### 5.1 M5 需内置的"记忆卫生"机制

1. **写入门（Write Gate）**：每条写入带 `{来源可信度, 作用域(scope), TTL, 置信度, 证据计数}` 元数据。对应失效 F2/F4/F6：来源不可信内容（网页/工具输出）默认低信任、不可直接进入持久记忆（V-M1/V-S1 对策）；临时例外必须带过期时间（F4，SM06 协议直接可移植）；反思性结论需"落地验证"后才升置信（V-S5 对策）。
2. **增量策展而非整体重写**：ACE 式 itemized delta 更新，禁止 monolithic rewrite（F1）。
3. **Supersession 而非共存**：事实更新在存储层废止旧值；检索默认过滤已废止条目（F7）。
4. **写入预算 + 污染率监控**：跟踪 over_storage_penalty（learn 期写入占比）与 memory_pollution_rate，超阈值触发清理（F5）。
5. **先检索后写入的顺序约束**：retrieval_before_first_update 作为硬遥测（防重复写入与冲突写入）。
6. **投毒回归探针**：在评测集中常驻 MINJA 式弱信号注入与"伪指令注入"用例（C1–C4 四通道），报 ASR/RSR。

### 5.2 记忆贡献的消融协议（把"记忆增益"与"搜索/算子增益"解耦）

核心难点：AutoResearch 的提升可能来自 M5 记忆，也可能来自检索算子、搜索策略或基座能力。建议四层归因设计（基于 PAST-Bench 协议改造）：

1. **双重差分主指标**：对每个任务家族，报告
   `AblationLift = (eval−baseline)^{persistence-on} − (eval−baseline)^{persistence-off}`，
   其中 baseline 为家族内冷启动 episode。这剥离了练习效应与任务难度漂移（PAST-Bench v2_layer1 的既有实现可直接移植）。
2. **算子混淆的三类控制**：
   - **no_persistence**：同 agent 同算子、仅关记忆 → 隔离记忆贡献；
   - **shortcut**：当轮上下文直接给出结论 → 上界检测"根本不需要记忆"的任务（防假阳性）；
   - **wrong_mechanism / wrong_substrate**：把经验放到错误通道（如把该进记忆库的结论写进当轮 note）→ 检验增益是否真走 M5 通路而非通用检索增强。若 wrong_mechanism 也能拿到同等增益，说明增益来自"有检索"而非"有记忆"，应归到搜索/算子侧。【推断】这是对 AutoResearch 最关键的一条：M5 的 Δ 必须显著超过"等价 RAG/搜索增强"控制，否则记忆设计没有被证成。
3. **机制分与任务分双轴报告**：除任务分外，独立报告 mechanism_confidence（写入证据 × 检索证据 × 时序证据，公式见 §1.5）。采纳 PAST-Bench 的判据："写了不读、或经由错误基质成功的，不得仅凭 Δ 得分"。最终家族分用乘性合成 `max(0,Lift)×Mechanism×ReuseRate×TransferRobustness`，使任一环节为 0 时总分归零。
4. **触发强度与迁移距离扫描**：同一规则以 T3/T2/T1 三档触发分别注入（canonical 结论只取 T2/T3，T1 作诊断）；评测分 near/far，报 overfit_penalty=(near−far)/near——防 M5 退化为"关键词复读机"（F3）。
5. **卫生指标常驻**：每次跑评测同步输出 memory_pollution_rate、stale_leak_events、over_storage_penalty、写路径 token/时延成本（MemDelta 教训：embedding 模型与写路径成本必须披露）。
6. **失效容忍判据**：允许 with_persistence 显著差于 no_persistence 的结果被显式报告为负迁移事件（SM06 的 expected_control_result 即此设计），而不是当作噪声丢弃——这是发现 exception pollution 的唯一途径。

### 5.3 可直接复用的资产清单

- 指标实现：`PAST-Bench/src/past_bench/metrics/v2_layer1.py`（FamilyEvolveScore 合成）、`v2_layer2.py`（能力特异指标）、`v2_trace_parse.py`（first_use / repeat_violation / stale_leak 三个纯 trace 解析器，零 runner 改动可用）。
- 任务协议模板：`self-evolve-tasks-v2/**/family.yaml`（特别是 SM05 弱触发分槽设计、SM06 例外污染设计、SM06/SM07 的 control_set 写法）。
- 机制分实现：`src/past_bench/graders/self_evolve_helpers.py:362 compute_self_evolve_mechanism_scores`。

---

## 附：主要一手来源

- PAST-Bench 论文 arXiv:2608.04003v1（§3.2 控制与 Δ 定义、§4.1–4.2、附录 D）；源码 github.com/Gen-Verse/PAST-Bench（commit 见 clone 日期 2026-08-25）：`src/past_bench/metrics/v2_layer{1,2,3}.py`、`v2_trace_parse.py`、`src/past_bench/graders/self_evolve_helpers.py`、`src/past_bench/self_evolve_v2/schema.py`、`self-evolve-tasks-v2/**/family.yaml`。
- ACE / context collapse：arXiv:2510.04618。
- 记忆投毒：AgentPoison（2407.12784, NeurIPS'24）；MINJA（2503.03704, NeurIPS'25）；系统化研究 arXiv:2606.04329（M=(S,W,R)、C1–C4、V-M1…V-S5、ASR/RSR）；MemoryGraft、Zombie Agents（2604.04759 相关工作）；防御 A-MemGuard（2510.02373）、SMSR（2606.12703）、MemAudit（2605.23723）。
- Misevolution：arXiv:2509.26354。
- Benchmark：LoCoMo（ACL'24）；LongMemEval（2410.10813, ICLR'25）；MemoryBench（2510.17281）；MemoryAgentBench（2507.05257, ICLR'26）；MemoryArena（2602.16313）；MemDelta（2606.29914）；BEAM（ICLR'26）；AMemGym（ICLR'26）；LoCoMo-Plus（2602.10715）；STALE（2605.06527）；HaluMem（2511.03506）；ConvoMem（Pakhomov et al. 2025）；LoCoMo 审计（2607.21962 引述 Penfield Labs 2026，非同行评议，注意）。

不确定性说明：T0 的精确定义未在仓库中定位到（schema 只列枚举值），T1/T2/T3 语义系从 SM05/SM06 family.yaml 用法还原，标注为【推断】；PAST-Bench 论文 Eq.1/Eq.2 的完整公式（附录 B）本次未逐字核对，机制分细节以源码为准。
