# M6 Knowledge：科研 Agent 外部知识接入设计调研

调研日期：2026-08-25。覆盖 Arbor、AI-Scientist v1/v2、KAPSO、R&D-Agent、openresearch-cli，以及 3 个 2026 新工作（Tree-of-Ideas、AI Research Agents Narrow Scientific Exploration、IDEAgent）。文中【原文】= 一手材料明确陈述；【推断】= 调研者归纳。

---

## 1. Arbor（RUC-NLPIR/Arbor，arXiv:2606.11926）：两车道隔离设计

一手来源：`docs/search.md`（"Search & External Knowledge"）、`src/search_agent/`（agent.py / main.py / prompts.py）、README。

**核心设计【原文】**：外部知识分**两条独立车道**：

| 车道 | 时机 | 作用 | 落地字段 | 默认 |
|---|---|---|---|---|
| Grounded ideation | IDEATE 期间 | coordinator 搜索以**启发新想法** | `node.grounding` | off |
| Novelty audit | 实验之后（或 add 时预审） | 独立 SearchAgent 为**已被验证的 idea** 查先验工作 | `node.related_work` | off |

**隔离机制【原文】**："The two lanes run independent searches and never share fetched text — so the same page can't both inspire an idea and certify it as novel."（两条车道独立检索、从不共享抓取文本，避免同一页面既启发想法又为其新颖性背书——自我指涉的循环论证。）两者**默认全关**，理由是保持 benchmark 公平：系统不能从网上抄一个现成想法或结果。

**Grounded ideation 细节【原文】**：
- Coordinator 获得可选的 `ResearchSearch` 工具，带 4 种 intent：`related_work`（评估重叠/缺口）、`survey`（领域格局+取舍）、`lookup`（具体事实）、`explore`（开放扫描）。
- 工具在**隔离上下文**中运行：冗长搜索结果与页面原文不进入 coordinator 主窗口，只返回压缩 digest（summary + findings + 编号来源）。
- 防幻觉：从未实际打开过的来源会被丢弃（"Sources that were never actually opened are dropped, so citations stay honest"）。
- 阅读深度分级：novelty-audit 用 `visit_max_content_tokens`（默认 2048 token，"abstracts are enough to judge prior art"）；grounded ideation 用更大的 `research_visit_tokens`（默认 6000，让方法/结果章节在截断后幸存）。

**Novelty audit 细节【原文】**：
- 审计对象是"already proved out 的 idea"——在 merge 决策前确认"win 是否也是 contribution"。
- `auto_search_on_add: true` 时每个新 idea 入树即触发后台预检，verdict 落在 `related_work` 字段，**advisory——从不阻塞运行**（"it never blocks a run"）。
- 由专门的 SearchAgent 做全新搜索，"so it can't be fooled by whatever grounded ideation read earlier"。
- 独立 CLI：`arbor idea-check "<idea>"`，输出 novel / partial-overlap / prior-art-exists 三档评估 + 最接近论文 + 具体重叠风险。

**后端【原文】**：有序 backend 列表，结果合并去重；`alphaxiv`（论文，免 key）、`jina`（通用 web）、`serper`/`exa`（需 key）、`exa-mcp`、自托管 `endpoint`。缺 key 的后端静默跳过，默认 `[alphaxiv, jina]` 全免 key。页面访问：alphaXiv URL 走 SDK 全文，其余走 Jina reader（r.jina.ai），PDF 也能读。

【推断】Arbor 的设计哲学是"审计后置、建议不阻断"：知识不约束搜索（novelty check 不 veto），只在 merge 时提供 citation context；grounded ideation 则是扩大探索的可选输入。两车道字段分离（grounding vs related_work）使 Idea Tree 中"灵感来源"与"先验审计"可分别溯源。

## 2. AI-Scientist v1 / v2（SakanaAI）

一手来源：Sakana 官方页（sakana.ai/ai-scientist）、v2 摘要（arXiv:2504.08066）；第三方独立评测 arXiv:2502.14297（Beel, Kan, Baumgart）。

**v1【原文】**：idea 生成阶段允许系统搜 Semantic Scholar "to make sure its idea is novel"；写论文阶段也用 Semantic Scholar 自动找引用。评测论文补充实现细节：每次查询检索至多 10 条结果，提取元数据（标题/作者/venue/年份/引用数/摘要），最多迭代 10 轮；无明确匹配则判 `novel=True`。

**v1 的失效证据【原文，来自 2502.14297】**：系统把全部 10 个生成 idea + 2 个种子 idea 都判为 novel，包括 micro-batching for SGD、adaptive learning rates、e-fold cross validation 等**早已确立的概念**。"This misclassification likely results from the AI Scientist's reliance on keyword matching rather than any deeper synthesis." 论文中位数仅 5 条引用且多数过时；57% 手稿含幻觉数值。

**v2【原文，摘要】**：消除对人写代码模板的依赖，引入 dedicated experiment manager agent 管理的渐进式 agentic tree search；评审环节加 VLM 反馈循环。文献检索仍主要用于新颖性过滤而非领域地图（旁证：arXiv:2603.24402 的对比表："v2 integrates literature queries into the idea generation loop but still for novelty filtering rather than field mapping"）。

【推断】v1/v2 的设计是"生成→关键词检索→二元 novel 判定"的浅循环：检索接入时机在构想**之后**、作为 veto 闸门，但判定粒度（10 条关键词匹配 + LLM 一票）决定了高假阴性（漏报非新颖）。这正是不做防污染隔离、且把 audit 当硬门槛的反例。

## 3. KAPSO（arXiv:2601.21526，Leeroo）：类型化知识图 + 分级/条件化检索

一手来源：arXiv HTML v2 全文。

**表示【原文】**：知识图 K=(V,E)，每个节点是类型化 wiki 页，四类主类型 **Principle / Implementation / Environment / Heuristic**，类型化边如 IMPLEMENTED_BY、USES_HEURISTIC、REQUIRES_ENV。宿主在 MediaWiki（人类可审阅/编辑），同时索引进 Neo4j（图）+ Weaviate（向量），发布完整知识包（MediaWiki dump + 快照 + Docker 脚本），语料来自 2000+ 常用数据/ML 仓库。抽取条目带 provenance（SOURCE_REPO、RELATED_REPO、路径与 commit）。

**接入时机与分级检索【原文】**：
- **种子仓库选择**（运行初始化时）：`RepoRetrieve(g)→(r̂,ρ)`，置信度 ρ≥τ 则用检索到的仓库做初始代码库，否则用空 scaffold。即知识决定搜索的**起点**。
- **基础检索 KR**（每轮 evolve 时）：`K_base(g, r̂)` 返回有界的类型化页面集，以种子仓库为条件（浮现依赖、入口、惯用法）。
- **ERA 错误恢复增强**（失败后触发）：`RetrieveKnowledge(g, r̂, s)`，当失败信号 s≠∅ 时追加失败条件化的 heuristics、诊断与替代实现。检索为级联式（WSR 主检索 + PFR 兜底，+ERA 增强）。
- 产出为 **knowledge packet**（KGKnowledge）：按类型分组的页面 + 置信度 + provenance（query_used、source_pages）+ ERA 附件。
- 认知记忆层独立维护 episodic store（从实验 trace 蒸馏的教训），控制器做 RETRY/PIVOT/COMPLETE 决策；PIVOT 时重跑检索并**排除当前种子仓库**。

【推断】KAPSO 是"知识作为可执行经验库"的极端：知识不只启发想法，还直接决定初始代码库、约束环境配置、注入修复模式。接入时机贯穿全程（初始化/每轮/失败后），表示为带类型与来源的 bounded packet 而非原文拼接——防幻觉靠 provenance 链路与 bounded 集合；对搜索方向是**强约束**（seed repo 直接锚定起点），撞车风险靠 PIVOT 时排除当前 seed 缓解。与文献新颖性无关——它优化的是 evaluator 指标，不声称 novelty。

## 4. R&D-Agent（microsoft/RD-Agent，arXiv:2505.14738）

一手来源：arXiv HTML v2。

**R/D 双循环中知识的角色【原文】**：框架分 Research 相（Planning / Exploration Path Structuring / Reasoning Pipeline / Memory Context）与 Development 相（Coding Workflow / Evaluation Strategy）。知识相关组件：
- **FC/MD-Memory Context【原文】**："manages how accumulated knowledge, such as historical solutions, evaluation results, and insights, is stored, retrieved, and reused to inform the reasoning pipeline"。SOTA 配置为 Collaborative Communication：每个分支独立探索后，把**全分支最优 idea + 按主题相似度/分数/新鲜度加权的概率采样子集**注入各分支上下文，由 LLM 从富化池中选候选——"accelerating convergence while maintaining exploration diversity"。
- **MD-Scientific Reasoning Pipeline【原文】**：先识别问题→形成假设（为何该方法能解决）→输出可实现 idea；配 virtual evaluation（先生成多 idea、LLM 评估、只送最优者进开发相）。
- 消融【原文】：w/o Memory Context 仅降 9%（35.1→32.0 Any Medal），w/o Reasoning Pipeline 降 24%、w/o Exploration Path 降 28%。

【推断】R&D-Agent 的知识几乎全是**内部经验**（历史方案+评估反馈），外部文献缺位；其记忆模块本质是跨分支经验路由，用采样核在收敛与多样性间调压。对我们的启示：M5（记忆）与 M6（外部知识）的分界在 R&D-Agent 里根本不存在——知识即记忆。消融显示记忆的边际贡献小于推理管线与路径结构，提示外部知识模块若无好的消费管线也价值有限。

## 5. openresearch-cli / OpenResearch（alphaXiv）

一手来源：github.com/alphaXiv/openresearch-cli README、SYSTEM_PROMPT.md。

**设计【原文】**：文献检索是 CLI **一等命令**：`orx lit`、`orx paper <arxiv-id-or-doi>`——"full-text search across alphaXiv, OpenAlex, bioRxiv — no login required"。`orx install-skills` 把 OpenResearch skill 注入 Claude Code / Codex / OpenCode / Cursor，SYSTEM_PROMPT.md 明确：orx-lit skill "Preferred over web search for academic/research queries — start here"。知识接入不是 agent 内部组件，而是**任何 agent 都可调用的外部工具面**；实验管理（git worktree 树、run evidence）与文献检索正交。

【推断】这是"知识即基础设施"路线：不做接入时机决策，把决策权留给宿主 agent（靠 system prompt 偏好排序）。优点是零耦合、可组合；代价是防污染、审计时机、digest 压缩全部无人负责——agent 自己决定何时查、信多少。

## 6. 2026 新工作（3 个补充）

**(a) Tree-of-Ideas（ToI，arXiv:2608.10740）**【原文】：三阶段——EvoGraph 建主题引文图并选 frontier 论文；EvoTrace 从 frontier 递归回溯，重建**分支化学术演化树**，沿路径记录"方法推进了什么/解决了哪个局限/遗留或新生什么 gap"；EvoAgent 跨轨迹发现两类信号：convergent（≥2 条轨迹共享的 gap/共同 action/frontier race）与 cross-link（一条轨迹的能力桥接另一条的 gap），且**方向必须引用 ≥2 条独立轨迹的证据**，单谱系延续被拒。另有 NON-OBVIOUSNESS GATE：拒绝可还原为"教科书式两方法组合"的方向，要求命名其坍塌到的先验方法与组合给不出的结构性质。Idea 经内部评审 + 面向更广文献的 novelty 检查 + embedding 近重复过滤。6 个主题上 6.27 分（最强基线 5.36），接近人类论文参考 6.29；消融显示去掉 gap 建模降 0.72、去掉跨轨迹信号降 0.65。【推断】ToI 把"知识接入"从 RAG 拼接升级为**结构化的演化证据**，用多轨迹证据门槛直接对抗"撞车/非显而易见"两大风险，是目前 grounded ideation 最精细的注入格式设计。

**(b) AI Research Agents Narrow Scientific Exploration（Tang & Yang，arXiv:2605.27905）**【原文，摘要】：5 个 agent 框架 × 5 个 LLM 生成 219,655 个 idea，四个一致发现：AI idea 比同领域人类论文**更集中**；比起后续人类工作，更贴近起始文献；与未来人类研究方向对齐更差；位于历史科学生态位的**低影响区**。"current AI research agents appear better suited to local elaboration than to broadening scientific exploration."【推断】这是"外部知识降低原创性"忧虑的最强实证：文献 grounded 的 idea 系统性地是局部精加工。M6 设计必须内建抗收敛机制。

**(c) IDEAgent（arXiv:2607.22375）**【原文，摘要】：把 ideation 建模为 Quality-Diversity（QD）联合搜索：idea 以 lineage 演化，Quality 由多目标反馈驱动定向 repair/refine，Diversity 由轻量顺序记忆 + 与已完成 idea、其历史祖先、被拒提案的显式比较保证。新指标 Yield（满足质量阈的互异 idea 最大集合）上比最优基线高 3.89×。【推断】对应分类学中"多样性作为一等约束"的位置——防同质化不靠检索靠记忆比较。

另注：arXiv:2606.12071《On the limits of LLM-as-judge for scientific novelty assessment》【原文，仅见标题/被引】提示 novelty 判定本身作为 judge 任务有已知局限，与 AI-Scientist 评测互为印证。

---

## 7. 统一字段对比

| 系统 | 知识来源 | 接入时机 | 表示/注入格式 | 防污染/防幻觉 | 对搜索方向 |
|---|---|---|---|---|---|
| Arbor-grounded | alphaXiv 论文 + web | 构想中（IDEATE 可选工具） | 隔离上下文→压缩 digest（summary+findings+编号来源），落 `node.grounding` | 未打开的来源被丢弃；与 audit 车道零共享文本；默认关 | 扩大（可选输入，可不用） |
| Arbor-audit | 同上，独立 fresh search | 审计时（add 时预检/merge 前） | novel/partial/prior-art 三档 verdict + 重叠风险，落 `node.related_work` | 独立 SearchAgent；仅摘要深度（2048 tok）即可判先验 | 不约束（advisory，never blocks） |
| AI-Scientist v1/v2 | Semantic Scholar | 构想**后**（新颖性闸门，迭代≤10 轮×10 条） | 元数据列表→LLM 二元 novel 判定 | 几乎无；关键词匹配导致已知技术误判 novel（2502.14297 实测全误判） | 硬约束（非 novel 即弃），但判定不可靠 |
| KAPSO | 仓库语料 + MediaWiki 知识库 + episodic 经验 | 全程：初始化(seed repo)/每轮(KR)/失败后(ERA) | 类型化 bounded knowledge packet（四类型+typed edges+provenance+置信度） | provenance 链路（query_used/source_pages/commit）；bounded 集合 | 强约束（seed repo 锚定起点）；PIVOT 排除当前 seed 以纠错 |
| R&D-Agent | 内部经验（历史方案+评估反馈） | 构想前/中（memory context 注入推理管线） | 跨分支最优+相似度加权采样子集 | 固定 dev/test 切分防评估污染 | 收敛加速为主，采样核保多样性 |
| openresearch-cli | alphaXiv/OpenAlex/bioRxiv 全文 | 由宿主 agent 自定 | CLI 一等命令（`orx lit`/`orx paper`），skill 注入 prompt | 无内建；仅"优先于通用 web 搜索"的偏好声明 | 中性，看宿主 |
| ToI | 引文图（学术演化轨迹） | 构想前（离线建树）+构想后（novelty fullcheck） | gap 中心的演化树+跨轨迹信号卡；方向须≥2 轨迹证据 | NON-OBVIOUSNESS GATE；embedding 去重；novelty 复核 | 扩大且结构化（指向未解 gap 而非已有方案） |
| IDEAgent | 文献 + 内部 lineage 记忆 | 搜索中（QD 演化全程） | 与祖先/被拒集的显式比较 | 多样性约束即防同质化机制 | 主动扩大（QD 目标） |

## 8. 分类学：时机 × 来源 × 用途

**时机轴（接入点）**：
1. 构想前/离线建库（ToI 演化树、KAPSO learn/research、TrustResearcher KG）——最贵，结构化程度最高；
2. 构想中作为可选工具（Arbor grounded ideation、orx-lit）——按需、agent 自主；
3. 构想中作为强制上下文（R&D-Agent memory、KAPSO KR）——每轮注入；
4. 构想后新颖性闸门（AI-Scientist，veto 式）；
5. 验证后/merge 前审计（Arbor novelty audit，advisory）；
6. 失败后条件化增强（KAPSO ERA）——信号触发，非常驻。

**来源轴**：公共文献库（S2/alphaXiv/OpenAlex）/ 通用 web / 代码仓库语料 / 策展知识库（MediaWiki）/ 内部经验（episodic lessons、跨分支解）。

**用途轴**：启发（ideation 输入）/ 锚定（seed repo、起点选择）/ 约束（环境约束、契约）/ 修复（ERA）/ 审计（novelty verdict）/ 引用（写作与 merge 溯源）。

【推断】关键张力矩阵：
- **启发 vs 审计必须隔离**（Arbor 两车道是唯一显式实现）：同一证据既当灵感又当新颖性证明 = 循环论证；
- **约束越强、撞车越少但原创空间越小**（KAPSO 锚定 vs ToI 仅指方向）；
- **审计硬闸门 vs 软建议**：AI-Scientist 硬闸门+弱判定 = 高误报漏报双输；Arbor 软建议+后置 = 把误判代价降到"浪费一次实验"以下。

## 9. 利弊分析（聚焦两个关注问题）

**(1) 外部知识是否降低原创性/导致撞车？**
- 实证：2605.27905 的大规模证据表明当前 agent 的 grounded idea 显著更集中、更贴近起始文献、更低影响【原文】。RAG 式拼接（flat context）是主因之一——ToI 的动机正是批评"treat papers as unstructured context"【原文】。
- 反例/缓解：ToI 用"gap 中心 + ≥2 轨迹证据 + 非显而易见闸门"把文献从"答案库"转成"未解问题地图"，Novelty/Groundedness 双高【原文+消融】；IDEAgent 用 QD 把多样性设为与质量并列的目标函数【原文】。结论【推断】：问题不在"接外部知识"，而在注入格式——注入**方案**会导致克隆，注入**gap/约束/失败**则扩大探索。

**(2) Novelty audit 的误报问题**
- 双向失效：AI-Scientist 实测是**漏报**（已知技术判 novel，因关键词匹配+10 条浅检索）【原文 2502.14297】；反过来 LLM-as-judge 对新颖性判断本身有保守偏置（同评测中其评审 agent 拒掉 9/10 人类已接收论文）【原文】，即作为闸门会**误杀**。
- 缓解设计【原文+推断】：Arbor 的 advisory 定位（never blocks）+ 三档 verdict（novel/partial-overlap/prior-art-exists）+ 独立 SearchAgent + 来源必须实际打开，是目前最稳的工程答案；ToI 把 novelty check 放在内部评审之后且面向"broader literature beyond Tr"（防止审计只查自己用过的语料）。

## 10. 对 AutoResearch M6 的建议

【推断，综合上述证据】

1. **采用 Arbor 式两车道 + 默认软审计**：M6 拆为 `ground`（构想期可选工具，intent 化查询，隔离上下文+压缩 digest）与 `audit`（后置、advisory、三档 verdict、独立检索上下文，绝不复用 ground 抓取的文本）。审计不做 veto——误杀代价大于浪费一次实验；verdict 落节点字段供 merge/写报告溯源。
2. **注入格式学 ToI 而非 RAG**：M6 对外部文献的输出应是**结构化 gap/约束/演化信号**（带 provenance），而非摘要拼接；加"非显而易见闸门"与"≥2 独立来源证据"规则，直接对冲 2605.27905 揭示的收敛效应。
3. **M6 vs M5（记忆）边界**：M5 = 内部经验（本框架实验 trace 蒸馏的教训、历史方案、失败模式），M6 = 外部世界（文献/web/外部 repo）。接口上 M6 提供 `query(intent)` 与 `audit(idea)` 两个算子可见的工具；M5 提供 `recall(signal)`。两者的输出在注入搜索上下文前**分开标注来源类型**（学 Arbor 的 grounding vs related_work 字段分离），因为内部经验可信度和外部文献证据的用法不同：前者约束"别再试"，后者回答"世界已知什么"。KAPSO 式 ERA（失败触发的知识增强）可作为 M5×M6 的联合入口：失败信号同时检索内部教训与外部修复 heuristic。
4. **M6 vs M2（算子）边界**：M2 算子（如 idea 变异、合并、refine）消费 M6 的产物但不拥有检索逻辑；M6 只管"取、压、证、隔离"，不管"怎么用"。多样性约束（IDEAgent 式 QD）属于 M2/搜索策略层，M6 只负责提供去重所需的 embedding/来源证据。
5. **防污染清单**：(a) ground 与 audit 零共享；(b) benchmark 模式下 M6 默认全关（Arbor 理由：保证评测公平）；(c) 引用必须实际打开过；(d) 审计用浅读（摘要级）+ 新鲜检索；(e) 审计结果永不做硬闸门。
6. **预算分级**：构想期深读（~6k token/页，保方法章节），审计期浅读（~2k，摘要足够）——Arbor 的双 token 预算设计可直接借鉴。

---

## 来源

- Arbor: github.com/RUC-NLPIR/Arbor `docs/search.md`、`src/search_agent/`、README；arXiv:2606.11926
- AI-Scientist: sakana.ai/ai-scientist；arXiv:2408.06292（v1）、arXiv:2504.08066（v2）；独立评测 arXiv:2502.14297
- KAPSO: arXiv:2601.21526v2（HTML 全文 §2–§4）
- R&D-Agent: arXiv:2505.14738v2（HTML 全文 §3、消融 §4.3）
- openresearch-cli: github.com/alphaXiv/openresearch-cli README、SYSTEM_PROMPT.md
- Tree-of-Ideas: arXiv:2608.10740（PDF 全文含 prompt 附录）
- Narrow Exploration: arXiv:2605.27905（摘要）
- IDEAgent: arXiv:2607.22375（摘要）
- 旁证：arXiv:2603.24402（AI-Supervisor 对比表）、arXiv:2606.12071（LLM-judge novelty 局限，标题级）
