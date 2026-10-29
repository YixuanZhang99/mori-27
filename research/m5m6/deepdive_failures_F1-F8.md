# 八个记忆失效模式（F1–F8）深度展开分析

> 2026-08-25。基于主文档 §4 失效模式总表（`M5记忆与M6知识设计深度分析.md`），一手证据来自 `research/m5_groupD_eval.md`（PAST-Bench 源码级）、`m5_groupB_general.md`（ACE 等）、`m5_groupA_selfevol.md`（自进化系统）、`m5m6_groupE_frontier.md`（2026 前沿）。事实均标注来源；外推标【推断】。

---

## F1 Context Collapse（上下文塌缩）

**1. 机制解剖**
因果链：记忆更新采用"LLM 整篇重写"→ 每次重写等价于把"旧知识+新观察"重新过一次有损压缩器（LLM 生成）→ LLM 的 brevity bias（生成简洁答案的先验）在重写任务中被放大 → 细节（领域启发式、失败模式、证据清单）逐级被抹除 → 误差随步数**复利累积**。ACE（arXiv:2510.04618）AppWorld 案例研究（Figure 2）给出教科书级数字：第 60 步 playbook 18,282 token、准确率 66.7；第 61 步一步整篇重写后塌缩为 **122 token**，准确率 57.1——**低于无适配基线 63.7**。机制本质是压缩器在更新路径上，且上下文越大压缩越狠。

**2. 真实案例**
ACE 作者明确强调这不是 Dynamic Cheatsheet 的 bug，而是"一切 end-to-end LLM 重写式记忆更新的根本风险"（原文）。同谱系受害者：Reflexion 的全量重写式反思、ExpeL 的 insight 平铺文件（2026 共识：会引入检索冲突的过时结构，见 groupE §4）、A-MEM 的卡片就地演化（局部重写，有小规模 brevity 风险，groupB §1.6）。

**3. 为什么难防**
塌缩是**渐进的、每步看起来都合理**：单次重写只损失一点细节，任何单步 diff 审查都难以定罪；且塌缩后 token 数骤降反而显得"更精炼高效"。只有跨步纵向监控总量与准确率才能发现。它还把"记忆变多"偷换成"记忆变短"，逃过膨胀类监控。

**4. 防护机制分层**
- **事前（设计约束）**：禁止 LLM 整篇重写，改为条目级 delta（ADD/更新计数/微调）+ **确定性非 LLM 合并**——把压缩器从更新路径移除，LLM 只在抽取新教训时介入，新信息天然小、压缩损失有界（ACE 核心设计）。我们框架中 CLAUDE.md 的"delta-merge 记忆晋升"不变量已升级为最高优先级不变量。
- **事中（监控）**：跟踪 playbook/记忆库总 token 数与条数的时间序列，单步缩水超阈值报警；同步记录每步任务分。
- **事后（检测与恢复）**：快照回滚（prime-agent 的事务性设计）；MemRL 的归一化+相似度门把遗忘率从 0.073 压回 0.041（§5.4.2），可作读取侧补救。

**5. AutoResearch 场景形态**
研究记忆恰恰是**最不能承受细节压缩**的场景：18282→122 的等价物是"证据清单（哪个假设、哪次实验、什么 metric、为什么被反驳）塌缩成一句'有些方法有效'"【推断】。对长时程、假设驱动、证据密集的研究 agent，一旦 collapse，阴性结果与被反驳假设首先丢失，直接导致重复试错。故 M5 任何更新路径都不得让 LLM 整篇重写已有记忆。

---

## F2 记忆投毒（Memory Poisoning）

**1. 机制解剖**
写入通道无来源校验 → 攻击者（或被污染的工具输出/网页）经由四写入通道 C1–C4 之一注入恶意条目 → 后续检索把毒条目当合法先验注入决策。系统化研究 arXiv:2606.04329 形式化为 M=(S,W,R)（存储×写入×检索），并列出七个漏洞类：指令-数据边界盲（V-M1）、来源归因失败（V-M2）、写入策略欠规约（V-P1）、压缩无来源过滤（V-P2）、写路径无验证（V-S1）、技能创建无校验（V-S4）、**自我改进放大（V-S5：投毒技能每次执行"无误"即被视为验证通过，演化为优化良好的对抗程序）**。关键数字：MINJA（NeurIPS'25, 2503.03704）query-only 注入成功率 **>95%**、ASR>70%——攻击者只需通过正常查询即可植入。

**2. 真实案例**
AgentPoison（NeurIPS'24, 2407.12784）、MINJA、MemoryGraft（模仿历史成功轨迹造成持续行为漂移）、Zombie Agents（自我强化注入持久控制）、Sleeper Memory Poisoning（arXiv:2605.15338，休眠投毒）；MemRL 论文自承"maliciously injected sample could rapidly diffuse pollution... causing agent collapse"（App. G.4）。OWASP Agentic Top10 已收录为 ASI06。

**3. 为什么难防**
写入时刻毒条目往往**语法正常、语义合理**，与真实经验不可区分；毒效在**检索时刻**才发作，写入与受害时空分离；最阴险的是 V-S5——自我改进循环本身成为放大器，每次"成功执行"都给毒技能加信用。共享记忆库（EvolveNet 的共享 harness、MemRL 全局 bank）意味着单点污染全域。

**4. 防护机制分层**
- **事前**：写入门控——每条写入强制携带 {来源可信度, 作用域, TTL, 置信度, 证据计数} 元数据；不信任内容（网页/工具输出）默认低信任、隔离，不可直接入持久记忆（V-S2 对策）；Truth-Maintained Memory Agent（NeurIPS'25）式写路径验证；技能创建必须过执行校验（V-S4 对策）。
- **事中**：投毒回归探针常驻评测集（MINJA 式弱信号注入 + C1–C4 通道用例），报 ASR/RSR 双指标（2606.04329）；A-MemGuard 主动防御（2510.02373）。
- **事后**：MemAudit 事后因果归因审计（2605.23723）、SMSR 密码学溯源（2606.12703）、快照回滚（MemRL 自承可清除性是污染后唯一补救）。

**5. AutoResearch 场景形态**
研究 agent 大量消费不可信外部内容（arXiv 论文、博客、代码仓库、检索结果）——这是天然投毒面【推断】：一篇含隐藏指令的网页被 RAG 读入后经"经验总结"写入 M5，即在所有后续实验中持久生效；被污染的"可执行 skill"（如数据预处理脚本）在共享 harness 中是单点故障（EvolveNet 教训）。M6 两车道零共享文本、引用必须实际打开过的设计部分对冲，但 M5 写入侧仍需独立来源门。

---

## F3 经验过拟合与负迁移

**1. 机制解剖**
从少数 learn episode 归纳出**表面规则**（与触发词、关键词重叠绑定，而非底层机制）→ 近迁移（near，同域换面）表现好 → 远迁移（far，去关键词重叠/换结构）表现差甚至为负 → 净效应：经验库"记住"了答案的形状而非解法。PAST-Bench 把此量化为 `overfit_penalty = max(0,(near−far)/near)` 与 `transfer_without_keyword_overlap = far/near`、`induction_quality = far−baseline`。SM06 的 `false_positive_pattern` 即："remembers both the durable rule and the one-week exception, causing negative transfer"。

**2. 真实案例**
PAST-Bench procedural 能力的 layer-2 指标直接为此设计（`v2_layer2.py`）；MemoryGraft 的"模仿历史成功轨迹→持续行为漂移"是同一现象的攻击面版本；MemRL 在 HLE 上跨任务无增益（Table 3）——任务相似度低时经验迁移退化为单任务反思；CODESKILL 的管理策略过拟合风险（训练分布上学到的保留偏好系统性排斥新颖低频经验）是元层版本。

**3. 为什么难防**
near 迁移提升是**真实可见的**，far 退化需要专门构造的去关键词评测才暴露——常规 benchmark 只测 near 时该失效完全隐形，且表现为"记忆有效"。规则在写入时无法自证其抽象度：表面规则与真抽象在文本上往往只差几个实体名。

**4. 防护机制分层**
- **事前**：规则抽象度检查——写入时要求条目做实体抽象/动作归一/上下文剥离（IBM TSM Phase 2 的泛化管线）；强制生成 domain-specific 与 generic 两级（IBM TSM 双层 tip）。
- **事中**：near/far 双距离评测常驻；far 集必须清掉触发词与关键词重叠（PAST-Bench evaluation episode"触发词被移除"的设计）。
- **事后**：overfit_penalty 超阈值时对近邻规则做降级/重写；negative transfer 必须显式报告而非当噪声丢弃。

**5. AutoResearch 场景形态**
在 MLE-Bench 类场景：从少数几个 Kaggle 任务归纳出"调大 dropout 有效""XGBoost 先跑 baseline"等表面规则 → 同族任务（near）提升，跨模态/跨问题类型（far）任务因盲目套用过时先验而退化【推断】。这恰是 AutoResearch 最可能自欺的失效：报告 near 增益即宣称"自我改进有效"。故 M5 消融必须报 overfit_penalty，far 分低于 baseline 的规则进 quarantine。

---

## F4 例外规则污染（Exception Pollution）

**1. 机制解剖**
临时性、有作用域的例外（"仅本周客户 Maya 免审"）在写入时**不带 TTL/作用域元数据**→ 被当作持久 durable 规则入库 → 例外过期后不消退 → 后续检索把它与正式规则并列注入 → 行为被永久扭曲。PAST-Bench SM06_temporary_exception_pollution 的实测结果：`expected_control_result` 显示污染时 with_persistence **差于** no_persistence——记忆不仅无效，而且是净负债。

**2. 真实案例**
PAST-Bench SM06（临时 Maya 例外过期后仍污染 durable RISK-CANON 默认）与 SM07 scoped_rule_migration；机制分中的 `noise_resistance_score` 用 `forbidden_rule_keywords`（不应被持久化的一次性/陈旧规则）线性扣分，直接量化该失效（`self_evolve_helpers.py:362`）。

**3. 为什么难防**
**例外在写入时看起来完全合理**：它确实是当下正确的指令，且 agent 没有先验理由拒绝记录"刚刚被明确告知的事"。污染的发作延迟到例外过期之后——写入与危害之间隔着时间维，常规正确性检查全部失效。且例外与规则文本相似，去重/冲突检测难以识别"这是同一规则的临时变体"。

**4. 防护机制分层**
- **事前**：写入分流——durable default vs temporary exception 是两个不同条目类型；exception 类型强制带 TTL 与 scope 字段（SM06 协议可直接移植）；写入时记录"过期后的回退默认值"。
- **事中**：TTL 到期自动失效 + 周期清理（Close 机制）；over_storage 监控中单独统计无 TTL 的 exception 类条目数。
- **事后**：stale 控制家族常驻回归（暴露过期例外的 distractor/stale 控制）；noise_resistance 分下降即触发审计。

**5. AutoResearch 场景形态**
研究中的"例外"极多：本次实验用的随机种子、临时数据集子采样、为赶 deadline 跳过的显著性检验、某个被 debug 覆盖的 metric 定义【推断】。它们被无 TTL 地写入 M5 后，会在下个季度的新项目里作为"既定协议"被检索出来——例如"数据集 X 用 10% 子采样"这条例外变成默认流程，系统性破坏后续实验统计功效。schema 必须有 ttl/scope/confidence/provenance 四字段（已列入 ADAPT-v1.1 增量）才有防的制度前提。

---

## F5 记忆膨胀与检索噪声

**1. 机制解剖**
无条件写入 → 库单调膨胀 → 两个问题：(a) 检索精度退化——top-k 中噪声淹没信号，且 top-k 过严的"修复"反而跌破基线；(b) 成本爆炸。关键数字：MemDelta（2606.29914）实测记忆操作可占 agent 执行时间 **>80%**、500 会话事实抽取耗 **1.6 亿 token**；Library Drift（2605.19576）实测无界积累下技能库检索退化、假阳性注入、性能停滞。IBM TSM 的负结果是另一面：top-3 过严限制使总分跌破基线 **−2.9pp**——**检索不足比不检索更糟**；ConvoMem 发现 ~150 会话以下全上下文反而优于检索记忆（短程 benchmark 压缩了要测的差异）。

**2. 真实案例**
Library Drift（AWS GenAI + HSBC）：修复配方 Ratchet（outcome 驱动退休 + 活跃库有界上限 + per-skill 贡献分归因）使 MBPP+ hard-100 100 轮 pass@1 从 **0.258 → 0.584**；SkillsBench：LLM 自创技能 **+0.0pp** vs 人工策划 **+16.2pp**——无治理积累零增益的直接证据；DGM/AIDE 的 append-only archive 在长程进化后"检索退化为纯标量打分，丢失为什么有效"。

**3. 为什么难防**
膨胀的每一步写入都"便宜且似乎有用"；危害是检索层的**统计性退化**而非单条错误，无法归罪任何单条记忆；且有偏评审器会**静默使退休机制失效**（2607.07436）——治理机制本身有评估器依赖。遗忘还有反直觉陷阱：Tenure Crossover（2607.21962）表明记忆架构排名随使用时长反转，短期最优长期最差。

**4. 防护机制分层**
- **事前**：写入预算与准入（write gate、Adaptive admission control 2603.04549）；活跃库有界上限；宽进严读（写入宽松、读取侧用 Q 值/效用惩罚，MemRL 有收敛定理）。
- **事中**：over_storage_penalty（learn 期写入占比）、memory_pollution_rate、检索 precision 单独计分、写路径 token/时延成本常驻报告（embedding 模型必须披露）。
- **事后**：outcome 驱动退休 + 贡献分归因裁决 + append-only 证据日志（Ratchet 配方）；研究场景用**降级归档而非删除**（阴性结果与被反驳假设是高价值记忆）；快照回滚。

**5. AutoResearch 场景形态**
数周的研究项目产生数千条实验记录、教训、假设【推断】：若无界写入，半年后检索"学习率策略"会召回几十条互相矛盾的条目，注入 top-k 后 LLM 在噪声中平均化，产出平庸折中方案；同时 embedding+读写的 token 成本超过实验本身。M5 的治理轴（退役评审、贡献分）因此是必选项而非增强项。

---

## F6 自我强化错误信念

**1. 机制解剖**
反思/总结**不经外部校验**直接入库 → 后续检索把它当先验知识 → 按此先验产生的行为若未立即失败，又被反思为"验证通过"并回写 → 置信度循环加固。V-S5 "Self-Improvement as Amplification"：投毒/错误技能每次执行无误即被视为验证，演化为"优化良好的对抗程序"。Misevolution（2509.26354）实测：记忆积累后**安全对齐退化**；TAME（2602.03224）首次把 misevolution 作为一等风险目标。

**2. 真实案例**
Zombie Agents 的自我强化记忆注入；OpenAI Dreaming V3 的 ZDNET 实测——会**自信地产生错误的合成记忆**（虚构 HomeAssistant 迁移），产品端真实复现；AIDE 的 `is_buggy` 由 LLM 自判，误判的好方案被 good_nodes 硬过滤**永久排除**出摘要（写入侧自评偏差不可逆）；IBM TSM 在无 ground truth 时由自反思推断结果，"错误归因被写入并带 provenance 背书"。

**3. 为什么难防**
闭环内**没有外部锚点**：错误信念与正确信念在库内不可区分，且自我引用使证据计数虚增（"验证"次数多恰恰因为信念驱动了更多尝试）。ACE 作者自陈"反馈信号质量是命门"——无 GT 标签也无执行信号时 ACE 与 DC 双双退化。prime-agent 的证据门是反例的另一面：证据本身被 reward hacking 污染时，证据门反而给假经验背书。

**4. 防护机制分层**
- **事前**：反思结论须落地验证（执行反馈/外部证据）后才升置信度；条目强制带置信度与证据计数；无 GT 场景标注 provenance 为"self-reported"。
- **事中**：置信度分布漂移监控（大量条目无外部证据却高置信=警报）；Misevolution/TAME 式安全对齐定期回归。
- **事后**：STALE（2605.06527）探针测"agent 是否知道记忆已失效"；MemAudit 因果归因审计定位加固链起点；快照回滚。

**5. AutoResearch 场景形态**
研究 agent 反思"方法 X 无效因为假设 Y 错误"并入库 → 后续所有实验按此先验设计，从不复测假设 Y → 若最初的实验 X 其实是实现 bug，整条研究线被永久锁死在错误方向【推断】，且"证据"随每次回避而显得越来越充分。防护的具体形态：置信度升级必须有可执行验证（重跑实验），"结论是否正确"没有 ground truth 的条目永不升满置信，并保留人工/自动复核通道。

---

## F7 陈旧状态泄漏（Stale Reuse）

**1. 机制解剖**
事实被更新后，**旧值在存储层仍与新值共存**且仍可被检索 → 检索召回旧值 → 终答/行为复述过期状态。根因是更新语义错误：多数系统"追加新条目"而非"逻辑废止旧条目"。PAST-Bench conflict_update trigger 专测此项：`overwrite_speed/completeness/stale_leak_penalty`；trace 级取证 `stale_leak_events`（终答仍含应被覆盖的旧短语，`v2_trace_parse.py`）。LongMemEval 的 Knowledge-Update 题型、Supersede（2606.27472，memory-update gap）、ShinkaEvolve 的滞后摘要（适应度景观快变时持续推荐过时策略）均属此族。

**2. 真实案例**
PAST-Bench update 能力族（7 family/51 episode）将其设为核心测量；OpenAI Dreaming V3 的 Synthesis 层专门处理"计划中的旅行→已完成的旅行"这类时序更新（官方指标时序正确性 9%→75%）——说明头部产品也把陈旧更新当一等难题；"Don't ask the LLM to track freshness"（2606.01435）证明 LLM 自主追踪新鲜度不可靠，须确定性冲突解决。

**3. 为什么难防**
共存是**默认且实现最简单**的更新语义；新旧值文本相似度高，语义检索无法区分"current"与"superseded"；且陈旧泄漏是**间歇性**的——检索排序稍有波动就召回旧值，复现困难。让 LLM 自己判断"哪条新"已被 2606.01435 证伪。

**4. 防护机制分层**
- **事前**：supersession 语义——新条目**逻辑废止**旧条目而非共存（存储层指针，非 append）；更新走"先检索后写入"硬顺序（retrieval_before_first_update 作硬遥测，防冲突写入）。
- **事中**：检索默认按有效性+时间戳过滤已废止条目；stale_leak_events 常驻 trace 解析。
- **事后**：终答前 stale 短语扫描；conflict_update 家族回归（overwrite_completeness 必须为 1）；确定性冲突解决规则（2606.01435）。

**5. AutoResearch 场景形态**
研究事实高频更新：baseline 数字、数据集版本、API 行为、"当前最优配置"【推断】。若 M5 中"最佳结果是 0.83（实验 42）"与两周后的"最佳结果是 0.87（实验 91）"共存，agent 写 related work 或设计下一实验时可能引用旧 SOTA，导致错误的增量声明与错误的起点选择。supersession + provenance（来源实验 ID）是此处 schema 设计的直接动因。

---

## F8 评估假象（Evaluation Illusion）

**1. 机制解剖**
观测到的"记忆增益"实际来自**练习效应、当轮信息泄漏、基座能力或评分噪声**而非记忆通路。三条具体路径：(a) 只对比 no-memory 基线，任务重复本身带来提升；(b) 评测可被当轮上下文解出（shortcut）或经验走了错误通道（wrong_mechanism）也得分；(c) benchmark 本身被污染——LoCoMo 答案键 **6.4% 错误**（99/1540 分损坏，2607.21962 审计）、LLM judge 接受 **62.81% 故意错答**、MemGym 无虚构化时前沿模型得分 0.70–0.85（纯污染记忆）。MemDelta（2606.29914）元批评：主流评测不披露 embedding 模型、不报写路径成本。

**2. 真实案例**
PAST-Bench（2608.04003）是唯一把 Task score 与 Mechanism score 解耦的协议：实证 Hermes vs nanobot 在 Δ=+0.13 相同时 mechanism evidence 0.64 vs 0.57——同增益不同机制；其判据"写了不读、或经错误基质成功的，不得仅凭 Δ 得分"。家族级 Δ 只有超过**全部控制条件上界**才计为自我改进证据（§3.2）。

**3. 为什么难防**
假增益在**单基线对照下无法识别**——所有数字都真实，只是归因错误；且 F8 有制度性共谋：论文需要正结果，审计基准（Penfield Labs 对 LoCoMo）是非同行评议的边缘劳动。Tenure Crossover 进一步说明**单点评测结论不可信**：架构排名随使用时长反转。

**4. 防护机制分层**
- **事前**：评测协议设计——双重差分 `AblationLift = (eval−baseline)^{on} − (eval−baseline)^{off}`；三类配对控制（no_persistence / shortcut / wrong_mechanism）；虚构实体防预训练污染；judge 对抗性校验；多 tenure 点纵向评测。
- **事中**：机制分与任务分双轴报告，乘性合成（任一环节为 0 总分归零）；embedding 模型与写路径成本强制披露。
- **事后**：使用任何基准前先审计答案键；负迁移/反常结果显式报告而非丢弃。

**5. AutoResearch 场景形态**
AutoResearch 的 M5 提升可能来自记忆，也可能来自检索算子（M2/M6）、搜索策略或基座能力【主文档 §5】。最关键的一条控制是 **wrong_mechanism**：若把经验放到错误通道（当轮 note 而非记忆库）也能拿到同等增益，说明增益来自"有检索"而非"有记忆"，M5 设计未被证成【推断：对 AutoResearch 这是证伪自己记忆设计的第一刀】。此外 AutoResearch 用 LLM judge 评实验报告质量时，62.81% 错答接受率意味着 judge 必须先过对抗校验。

---

## 八个失效模式的隐藏结构：因果链与共谋关系

**三条主因果链：**

1. **F1 ↔ F6 互相加剧**：context collapse 把细节压缩掉后，库中只剩笼统结论——笼统结论缺乏可证伪的具体证据，更易被自我强化循环当作"已被多次验证的先验"（F6）；反过来，F6 的错误信念一旦入库，每次重写循环都会优先保留"简洁而自信"的断言、丢弃带条件的细节，加速塌缩。ACE 的 122-token 残骸正是 F6 的温床。【推断】

2. **F4 伪装成 F7，二者共享一根因**：例外污染（F4）与陈旧泄漏（F7）表象相同——过期内容仍可检索；但 F4 的病根在**写入时缺少 TTL/scope 元数据**（类型系统缺失），F7 的病根在**更新语义错误**（共存而非废止）。二者共享的根因是：**记忆条目缺乏时间维的一等建模**（无 ttl、无 supersession 指针、无 provenance 时间戳）。schema 的四字段（ttl/scope/confidence/provenance）同时是 F2/F4/F6/F7 四个失效的前置防线——这是"治理轴"被列为一等新轴的深层理由。

3. **F5 是 F2/F3/F4 的放大器，F8 是所有失效的隐身衣**：库越膨胀，毒条目（F2）、表面规则（F3）、过期例外（F4）被检索命中的概率越高、归因越难；而 Library Drift 证明膨胀本身足以使性能停滞（0.258）。F8 则与所有失效共谋：无配对控制时，F3 的 near 增益、F4 的短期无害、F6 的虚增证据计数、F5 的早期便利**全部显示为正增益**——评估假象让前七个失效在报表上隐形，直到长期纵向测量（Tenure Crossover）才暴露。

**两个共同根因【推断】：**
- **写入侧缺门、读取侧缺闸、更新侧缺语义**：F2/F4/F6 是写入门缺失的三种变体（恶意、临时、错误），F5 是读取闸缺失，F7 是更新语义缺失——七者都源于"记忆被当作 append-only 日志而非有生命周期的受治理工件"。Library Drift/Ratchet 的配方（有界上限+贡献分+退役+证据日志）之所以一举修复 pass@1 0.258→0.584，正因为它补的是根因而非某个症状。
- **LLM 被放到了不该在的位置**：F1（让 LLM 整篇重写）、F7（让 LLM 追踪新鲜度，2606.01435 证伪）、F6（让 LLM 自我验证）的共同教训是——压缩、冲突解决、验证必须是**确定性/外部锚定**的，LLM 只产增量。这与 ACE 的 delta-merge、supersession、执行反馈验证三条具体防护是同一原则的三个实例。

**设计含义**：F1–F8 不是八个独立 bug 清单，而是一张网——单独修补任何一个，其余会通过共谋关系迂回复发（如只治 F5 的膨胀而不治 F4 的 TTL，清理策略会把例外和规则一起留下）。最小完备的防护组合 = delta 写入+确定性合并（F1）× 元数据门（F2/F4/F6）× near/far+双重差分评测（F3/F8）× supersession+治理轴（F5/F7），缺一角则网破。
