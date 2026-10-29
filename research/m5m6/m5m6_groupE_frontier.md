# M5/M6 补盲调研（Group E）：2026 年自进化 Agent 的记忆与知识前沿

- 调研日期：2026-08-25
- 范围：2026 年（重点 6–8 月）arXiv 论文、综述、工业界产品动态
- 基线参照：ACE（delta-merge 上下文进化）、MetaSkill（双时间尺度元技能）、prime-agent /refine 循环、PAST-Bench（通路归因）

---

## 0. 执行摘要

2026 年上半年该领域出现**爆发式增长**（一篇综述统计其 1250 篇语料中 74% 发表于 2026 年，2026 Q2 单季约 500 篇）。核心结论：

1. **"Dreaming / 离线记忆巩固"在 2026 年被工业界产品化**——OpenAI（Dreaming V3，6 月 4 日）、Anthropic（Claude Managed Agents "Dreaming"，5 月 6 日）、Perplexity（Brain，6 月 18 日）三家几乎同期上线"空闲时回顾会话 → 提炼 → 写回可读记忆"的架构。这是 prime-agent /refine 循环的**异步化、批处理化**取值，但其"用户可审查/可回滚的纯文本记忆层"治理设计是新约束。
2. **学术界的重心从"积累更多经验"转向"记忆库的生命周期治理"**：Library Drift（技能库静默退化）、TAME（可信记忆演化）、记忆投毒（sleeper poisoning）、评测诚信（tenure crossover）等论文把"遗忘/退休/卫生（hygiene）"提升为一等设计目标——这是**真正的新轴**（治理轴），不在 ACE/MetaSkill 的框架内。
3. **记忆操作本身被参数化/可学习化**：MemSkill 把"怎么写记忆"做成可进化的技能库（meta-level 上移一层），与 MetaSkill 双时间尺度结构同构但作用于 memory-write 算子而非任务技能——属于已有轴的新取值，但值得 M5 显式建模。
4. **结构化增量存储**：DeltaMem 的双残差树（Task-Tree / Env-Tree 解耦 + delta 节点 + 命中计数触发的巩固）与 ACE delta-merge 高度同构，但新增了"任务策略 vs 环境知识"的**显式双通道解耦**——这是对 ACE 单一流水线的结构性扩展。

---

## 1. 2026 年新综述（taxonomy 提取）

### 1.1 "Self-Improvements in Modern Agentic Systems: A Survey"（2026-07-14）
- 链接：https://arxiv.org/html/2607.13104v1
- 【原文】涵盖 memory、weight 更新（SIA: self improving ai with harness & weight updates, arXiv:2605.27276）、test-time learning；引用 "Learning to forget: continual learning with adaptive weight decay"（arXiv:2604.27063）与 Zep 时序知识图谱。
- 【推断】其 "what improves × degree of loop closure" 双轴可直接映射到 M5 的"改进对象"维度。

### 1.2 "Recursive Self-Improvement in AI: From Bounded Self-Refinement to Autonomous Research Loops"（2026-07-08）
- 链接：https://arxiv.org/html/2607.07663v1
- 【原文】1250 篇语料（2024–2026），74% 发表于 2026；四技术类别 + foundations；两条组织轴：(i) 系统改进什么（deployment behavior / policy / evaluator / research process），(ii) 闭环程度（人在环 vs 全自主）。
- 【推断】memory/knowledge 在该综述中归入 "deployment behavior" 改进——即权重不动的自进化路径，与 ACE 一致。

### 1.3 "Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers"（2026-03-08）
- 链接：https://arxiv.org/html/2603.07670v1
- 【原文】write–manage–read 循环形式化；三维 taxonomy：时间范围 × 表征基底 × 控制策略；五机制族（context 压缩、RAG 存储、反思自改进、层次虚拟上下文、策略学习的管理）；开放挑战：持续巩固、因果接地检索、可信反思、**学习遗忘（learned forgetting）**、多模态具身记忆。

### 1.4 "A Survey on the Evolution of LLM Agent Memory Mechanisms"（2026-05-07）
- 链接：https://arxiv.org/html/2605.06716v1
- 【原文】演化路径三阶段：Storage（忠实记录）→ Reflection（纠错）→ Experience（高阶抽象）；Reflection 与 Experience 的关键区分：前者把精炼单元注回记忆 ℳ，后者抽出独立规则集 𝒦 作为策略先验——"从轨迹局部精炼到跨轨迹抽象"的范式转移。
- 【推断】这为 M5 提供了现成判别：ACE delta-merge 属 Experience 型；Voyager/ExpeL 属 Reflection→Experience 过渡。

### 1.5 "A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve"（arXiv:2507.21046，2026 持续更新版本被广泛引用）
- 2025 年首发但 2026 年所有新论文（Metis 等）都以其为 taxonomy 基线；无全新替代版。

---

## 2. 新发现学术工作清单（含出处与日期）

### 2.1 记忆/经验存储结构

| 工作 | 日期 / 链接 | 一句话定位 + 核心创新 | 与已知设计的关系 |
|---|---|---|---|
| **DeltaMem**（双残差树经验记忆） | 2026-06-02, arXiv:2606.03083, github.com/import-myself/DeltaMem | 经验存为相对最相似链的紧凑 delta 节点；**Task-Tree（程序性技能 ⟨α,π,ω⟩）与 Env-Tree（场景陈述性知识 ⟨α,κ⟩）显式解耦**；成功命中计数 ≥K_cons 触发 LLM 把链蒸馏为新根节点（神经科学启发的自主巩固）。【原文】 | ACE delta-merge 的**结构化扩展**：增量存储同构，但新增"任务/环境双通道"轴与"巩固阈值"旋钮（MetaSkill 双时间尺度的树内版本）。ALFWorld/ScienceWorld/WebShop 上优于 Synapse/AWM/ReasoningBank。 |
| **Metis: Bridging Text and Code Memory for Self-Evolving Agents** | 2026-06-23, arXiv:2606.24151 | 文本记忆与代码记忆双模态桥接。【原文（标题/引文）】 | 表征基底轴的新取值（自然语言 ↔ 可执行代码双库）。 |
| **Trajectory-informed memory generation for self-improving agent systems** | 2026, arXiv:2603.10600 | 由轨迹直接生成记忆。【原文（引文）】 | ACE 谱系新取值。 |
| **Yunjue Agent tech report** | 2026, arXiv:2601.18226 | 完全可复现、零起点 in-situ 自进化系统。【原文（引文）】 | 工程复现性贡献。 |
| **MemEx (RL): scaling long-horizon LLM agents via indexed experience memory** | 2026, arXiv:2603.04257 | 索引化经验记忆 + RL。【原文（引文）】 | 检索轴 + 训练信号组合。 |
| **Organize then Retrieve: Hierarchical Memory Navigation** | 2026-06-10, arXiv:2606.11680 | 层次化记忆导航提升检索效率。【原文（标题）】 | 检索侧，非新轴。 |
| **SIA: self improving ai with harness & weight updates** | 2026, arXiv:2605.27276 | harness（脚手架）+ 权重双更新。【原文（引文）】 | 把"改什么"扩展到 harness 层——M5 需注意 harness 作为独立改进对象。 |

### 2.2 记忆操作的可学习化 / 元层上移（重点）

| 工作 | 日期 / 链接 | 定位 + 创新 | 关系 |
|---|---|---|---|
| **MemSkill: Learning and Evolving Memory Skills for Self-Evolving Agents** | 2026-02（v2 2026-05-24）, arXiv:2602.02474 | **把记忆操作（抽取/巩固/修订）本身重构为可进化的技能库**。三组件：controller（RL 训练，按 span 选 Top-K 技能）+ executor（LLM 一次成型生成 skill-guided 记忆）+ designer（周期性地从 hard-case buffer 聚类选代表失败，LLM 精炼旧技能/提出新技能）。双库解耦：memory bank（trace 特有）vs skill bank（跨 trace 共享）。含回滚（skill bank 快照 + 性能退化回退）。LoCoMo/LongMemEval/HotpotQA/ALFWorld 验证。【原文】 | **MetaSkill 双时间尺度在 memory-write 算子上的同构实例**：controller=快时间尺度（学会用技能），designer=慢时间尺度（进化技能库）。新贡献点：把"巩固循环的对象"从任务技能换成了记忆管理技能——对 M5/M6 是明确的轴扩展提示。 |
| **MemEvolve: Meta-evolution of agent memory systems** | 2025-12, arXiv:2512.18746 | 记忆系统架构的元进化。【原文（引文）】 | 元层进化，与 MemSkill 互补（进化架构而非算子）。 |
| **MemRL: Self-evolving agents via runtime RL on episodic memory** | 2026, arXiv:2601.03192 | 情景记忆上的运行时 RL。【原文（引文）】 | 训练信号轴取值。 |
| **Mem-α: learning memory construction via RL** | 2025-09, arXiv:2509.25911 | RL 学习记忆构建。【原文（引文）】 | 同上。 |

### 2.3 技能库生态（Voyager 谱系的 2026 爆发）

| 工作 | 日期 / 链接 | 定位 |
|---|---|---|
| **SkillRL**（递归技能增强 RL） | 2026-02, arXiv:2602.08234，ICLR 2026 Workshop on Memory Agents **Oral** | 技能库 + RL 递归进化。【原文】 |
| **AutoSkill**（经验驱动终身学习） | 2026-03, arXiv:2603.01145 | 技能自进化。【原文】 |
| **CoEvoSkills**（协同进化验证） | 2026-04, arXiv:2604.01687 | 技能与验证器协同进化。【原文】 |
| **SkillFoundry**（异质科学资源 → 技能库） | 2026-04, arXiv:2604.03964 | 知识来源扩展到科学文献。【原文】 |
| **SkillX**（自动构建技能知识库） | 2026-04, arXiv:2604.04804 | 技能 KB 构建自动化。【原文】 |
| **SkillClaw**（集体进化） | 2026-04, arXiv:2604.08377 | 多技能集体进化。【原文】 |
| **SkillForge**（云技术支持域） | 2026-04, arXiv:2604.08618 | 域特异技能锻造。【原文】 |
| **SkillOpt: Executive Strategy for Self-Evolving Agent Skills** | 2026, arXiv:2605.23904，被引 64 | 技能进化的高层策略控制。【原文】 |
| **SkillEvolver: Skill learning as a meta-skill** | 2026, arXiv:2605.10500 | 技能学习本身作为元技能。【原文（引文）】 |
| **Trace2Skill**（轨迹局部教训 → 可迁移技能） | 2026, arXiv:2603.25158 | 蒸馏迁移性。【原文（引文）】 |
| **SkillRouter**（规模化技能路由） | 2026, arXiv:2603.22455 | 检索/路由层。【原文（引文）】 |
| **SkillAdaptor**（轨迹 → 自适应技能） | 2026-06, arXiv:2606.01311 | 执行失败下的技能适应。【原文】 |
| **SkillFlow**（终身技能发现与进化 benchmark） | 2026, arXiv:2604.17308 | 基准。【原文（引文）】 |
| **SkillsBench** | 2026, arXiv:2602.12670 | 基准；**关键发现：LLM 自创技能 +0.0pp，人工策划技能 +16.2pp**——成为 Library Drift 论文的动机证据。【原文】 |
| **EvoSkill / XSkill / ProcMem / AutoRefine / Experiential Reflective Learning** | 2026, arXiv:2603.02766 / 2603.12056 / 2602.01869 / 2601.22758 / 2603.24639 | 多智能体技能发现 / 多模态持续学习 / 非参数 PPO 程序记忆 / 轨迹到可复用专长 / 经验反思学习。【原文（引文）】 |
| **MUSE-Autoskill** | 2026-05, arXiv:2605.27366 | 技能创建-记忆-管理-评估四合一循环。【原文（引文）】 |
| **MetaSkill-evolve**（双时间尺度元技能进化） | 2026-07, arXiv:2607.05297 | 我们已知 MetaSkill 线的 2026 演进版，被 RSI 架构论文引用。【原文（引文）】 |

**关系判断**：以上绝大多数是 Voyager/ExpeL 谱系在"技能获取来源、验证器、路由、域"上的排列组合（已有轴的新取值），**不构成新设计轴**；例外见 §3。

### 2.4 记忆治理 / 失败模式 / 安全（2026 新出现的子领域）

| 工作 | 日期 / 链接 | 定位 + 创新 |
|---|---|---|
| **Library Drift + Ratchet**（AWS GenAI Innovation Center + HSBC） | 2026-05-19, arXiv:2605.19576；姊妹篇 arXiv:2605.22148 | **命名并复现"技能库漂移"**：无界积累 → 检索退化、假阳性注入、性能停滞。修复配方 Ratchet：outcome 驱动的技能退休 + 活跃库有界上限 + 元技能创作先验；append-only 证据日志 + 每技能贡献分数 + 归因裁决；MBPP+ hard-100 上 100 轮 pass@1 从 0.258 → 0.584。【原文】 |
| **How a Biased Judge Silently Disables Skill Retirement** | 2026-07-08, arXiv:2607.07436 | 有偏评审器会静默失效退休机制——治理机制的**评估器依赖**。【原文（标题）】 |
| **TAME: Trustworthy Test-Time Evolution of Agent Memory** | 2026-02（v2 2026-06-06）, arXiv:2602.03224 | 首次把"记忆误演化（misevolution）"的可信性风险作为一等目标；指出现有评测只看任务效用、忽略连续记忆更新引入的风险。【原文】 |
| **Hidden in Memory: Sleeper Memory Poisoning in LLM Agents** | 2026-05, arXiv:2605.15338 | 记忆库的休眠投毒攻击。【原文（引文）】 |
| **Supersede: Diagnosing and training the memory-update gap** | 2026-06, arXiv:2606.27472 | 记忆更新缺口的诊断与训练。【原文（引文）】 |
| **Don't ask the LLM to track freshness: deterministic memory conflict resolution** | 2026-06, arXiv:2606.01435 | 用确定性规则（而非 LLM）处理记忆新鲜度/冲突。【原文（引文）】 |
| **Ground Truth First: Longitudinal Evaluation Instrument + Tenure Crossover** | 2026-07-24, arXiv:2607.21962 | **纵向评测发现"任期交叉"**：记忆架构排名随使用时长反转——短期最优架构长期可能最差。【原文（标题）】 |
| **LoCoMo audit**（Penfield Labs 博客） | 2026, penfieldlabs.substack.com | 主流记忆基准 LoCoMo 答案键 6.4% 错误、judge 接受率高达 63%——评测诚信警告。【原文】 |
| **From Memory to Skills: Evidence-Grounded Co-Evolution Governance** | 2026-07-18, arXiv:2607.16621 | 记忆→技能的证据接地协同进化治理。【原文（标题）】 |
| **Counterfactual trace auditing of LLM agent skills** | 2026-05, arXiv:2605.11946 | 反事实轨迹审计技能归因。【原文（引文）】 |
| **SkillCoach: Self-Evolving Rubrics** | 2026-07-02, arXiv:2607.01874 | 评审 rubric 本身自进化。【原文（标题）】 |

### 2.5 RSI / 架构层

| 工作 | 日期 / 链接 | 定位 |
|---|---|---|
| **How to Realize Recursively Self-Improving Agents and Personal Singularity** | 2026-07-14, arXiv:2607.12254 | Goal/Scope/Tool/Benchmark 驱动的多智能体 RSI 架构，引用 Gödel Agent、Voyager、MetaSkill-evolve。【原文】 |
| **MiniMax M2.7**（工业） | 2026-03, minimax.io/news/minimax-m27-en | 宣称"首个参与自身递归自我改进的模型"，100+ 自主优化循环。【原文（引文转述）】 |
| **Nous Research Hermes Agent** | 2026, github.com/NousResearch/hermes-agent，23k+ stars | 开源自改进 agent：内建学习循环 = 技能创建 + 记忆检索 + Atropos RL 训练。【原文（引文）】 |
| **ACE（Agentic Context Engineering）已入 ICLR 2026** | arXiv 原 2510.x，ICLR 2026 录用 | 我们基线已被主流会议确认。【原文（引文）】 |

---

## 3. 工业界动态（2026 年 4–7 月，记忆产品化）

### 3.1 Anthropic — Claude Managed Agents
- **Memory Tool（文件系统挂载）**：2026-04-23 公测。记忆作为文件挂载在 agent 容器 `/mnt/memory/`，agent 可用 bash/code execution grep/diff/重组自己的记忆；Console/API 可导出编辑。【原文：https://www.getfeather.store/theory/anthropic-memory-tool-google-openai-comparison-2026 ，2026-07-14】
- **Dreaming**：2026-05-06 Code with Claude 大会发布。空闲时后台进程回顾最多 100 个过往会话 + 现有记忆库，抽取模式（反复错误、高效流程、团队偏好、工具怪癖），写入纯文本笔记与结构化 "playbooks"；**不改权重，每条记忆人类可读、可审查/批准/拒绝/编辑后才上线**。Harvey 报告任务完成率 6x 提升。【原文：https://www.buildmvpfast.com/blog/claude-dreaming-self-improving-agents-anthropic-2026 ，2026-05-15】
- 记忆 API GA：2026-07-22（`agent-memory-2026-07-22`）。【原文：https://academy.kspl.tech/blog/anthropic-agent-memory-api-july-22-ga 】

### 3.2 OpenAI — ChatGPT Dreaming V3
- 2026-06-04 发布（Plus/Pro 美国先行）。三层架构：Capture（会话中被动识别值得记的事实/偏好）→ Synthesis（会话间巩固、解矛盾、更新过时事实，如"计划中的旅行"自动变为"已完成的旅行"）→ Retrieval（上下文相关拉取）。替代旧的 saved-memories 列表；**用户侧控制：memory summary 页（审查/编辑/删除）、memory sources 溯源、可回退 legacy 模式、Temporary Chats 免记忆**。官方指标：事实回忆 41.5(2024)→68(V0)→83(V3)；时序正确性 9%→75%；偏好遵循 31%→71%；成本降 5 倍才得以推向免费层。【原文：OpenAI 官方 Release Notes 2026-06-04 https://help.openai.com/en/articles/6825453 ；https://www.zdnet.com/article/chatgpts-new-memory-upgrade-can-also-worsen-answers/ 2026-06-18】
- 【推断】ZDNET 实测显示 V3 会自信地产生错误的合成记忆（虚构 HomeAssistant 迁移）——印证 TAME/Library Drift 的学术担忧在产品端真实存在。

### 3.3 Perplexity — Brain
- 2026-06-18 发布（Max/Enterprise Max Research Preview）。**明确提出记忆两轴框架：记忆"关于什么"（用户 vs agent 的工作）× 记忆"为了什么"（engagement vs performance）**；Brain 选 work-memory × performance。构建可溯源 context graph（每条记忆可回溯到产生它的会话/文件/connector）；夜间定时综合；输入四源：完成会话、connector 结果、源文档变更、**用户纠正（编码为"避免此路"的负面课程）**。报告重复任务正确率 +25%、recall +16%、历史上下文任务成本 -13%。【原文：https://www.marktechpost.com/2026/06/18/perplexity-launches-brain/ ；https://kalinga.ai/perplexity-brain-ai-memory-guide/ 2026-06-22】

### 3.4 Google — Gemini Enterprise Agent Platform（Vertex AI 更名）
- 2026-04-22 Cloud Next '26 宣布，5 月 21 日完成更名。**Memory Bank**：托管服务，以 Sessions 为源动态生成并管理跨会话长期记忆；**Memory Profiles**（身份域隔离的低延迟高精度回忆）；定位为"身份作用域数据库原语"（vs Anthropic 的文件系统、OpenAI 的向量库检索工具）。【原文：https://siliconangle.com/2026/04/22/... ；https://gcpstudyhub.com/blog/vertex-ai-replaced-by-gemini-enterprise-agent-platform 】

### 3.5 三家设计决策对比（对 M6 直接有用）
| 维度 | Anthropic | OpenAI | Google | Perplexity |
|---|---|---|---|---|
| 记忆位置 | 容器文件系统 /mnt/memory | 后台合成层 + summary 页 | 身份域 DB（Memory Bank） | 可溯源 context graph |
| 写入时机 | 会话间空闲（Dreaming）+ agent 工具自写 | 会话中被动捕获 + 会话间合成 | 会话后自动生成 | 夜间定时综合 |
| 用户可见性 | 纯文本、逐条批准/拒绝/编辑 | summary + sources 溯源 + legacy 回退 | 企业治理面板 | 图可追溯 |
| 记忆对象 | agent 的工作（playbooks） | 用户画像 + 进行中的项目 | 跨会话企业上下文 | agent 的工作（含负面课程） |
| 权重是否变 | 否（明确承诺） | 否 | 否 | 否 |

### 3.6 Letta / MemGPT 系
- 【原文】2026 年无架构级新版本；定位稳定为"自编辑记忆"平台（memory blocks 置顶可编辑 + archival 检索 + 每次记忆编辑都是可审计动作），~23.6k stars。竞争焦点转向与 Mem0/Zep/MemPalace（逐字存储 + 100% LongMemEval）/Ricord（摄入时自动冲突检测、markdown wiki 可读记忆）等的生态对比。【来源：https://www.developersdigest.tech/blog/best-ai-agent-memory-providers-2026 2026-07-02；https://ricord.ai/compare/letta 2026-05-28】
- 【推断】MemGPT 的"agent 自主工具化记忆管理"设计已被 Anthropic 文件系统方案部分吸收（agent 用 bash 管理记忆 = 工具化记忆的特例）。

---

## 4. 已知系统 2026 后续检查

- **Voyager 系**：无官方 Voyager-2；但其"技能库"概念在 2026 年爆发为独立子领域（§2.3 的 15+ 篇），且 SkillsBench 发现"LLM 自创技能零增益"直接挑战 Voyager 式无治理积累——谱系重心已从"发现"转向"治理"。
- **ExpeL 系**：被所有新论文作为 flat-file 经验基线引用并普遍被超越（DeltaMem、SkillAdaptor、AutoRefine 等）；ExpeL 式"抽取教训存平铺文件"已被共识为会引入检索冲突的过时结构。
- **Generative Agents 系**：仅作背景引用；无 2026 直接后续。
- **MemGPT/Letta 系**：见 §3.6。

---

## 5. 判定：哪些带来真正新的设计轴？

### 新轴（建议加入 M5/M6）
1. **记忆治理/卫生轴（governance & lifecycle）**：退休（outcome-driven retirement）、有界活跃上限、证据日志、归因裁决、回滚快照。代表：Library Drift/Ratchet、TAME、MemSkill 的回滚。**这是 ACE（只增不退）与 MetaSkill（进化但无退役语义）都没有的轴**，且 2026 年证据（SkillsBench +0.0pp、Library Drift 静默失败、biased judge 使退休失效）表明它不是可选项而是必要条件。
2. **记忆元操作的可学习化轴（meta-level of memory ops）**：巩固循环的对象从"任务知识"上移到"记忆管理操作本身"。代表：MemSkill（controller/designer）、MemEvolve、SkillEvolver。是 MetaSkill 双时间尺度的泛化：M5 应允许"慢循环改进的对象"∈{任务技能， 记忆写算子， 记忆架构， 评审 rubric(SkillCoach)}。
3. **异步巩固时机轴（dreaming cadence）**：巩固从"每 episode 后同步"扩展到"空闲期批处理/夜间/定时"（Claude Dreaming、Perplexity Brain、OpenAI V3、DeltaMem 的 K_cons 命中阈值触发）。prime-agent 的 /refine 是同步触发的取值；2026 证据显示**触发时机本身（同步/空闲/阈值/定时）是独立设计维度**，且影响成本结构（OpenAI 明确以成本降 5 倍为推广前提）。
4. **记忆目的×对象轴（Perplexity 两轴）**：memory about {user, agent's work} × for {engagement/personalization, task performance}。我们的调研隐含全在 (work, performance) 象限，但 M5 的 utility 定义应显式声明象限——OpenAI V3 的争议说明错配对象/目的会产生真实产品风险。

### 已有轴的新取值（无需新轴，但需登记取值）
- 双通道解耦（任务策略 vs 环境知识）：DeltaMem——ACE 可吸收为"库的分区结构"取值。
- 表征基底：文本 ↔ 代码桥接（Metis）、可执行对象接地代码（OCM, arXiv:2607.02846）。
- 负面课程/失败记忆的一等化：Perplexity Brain（纠正→"避免此路"）、Library Drift 归因裁决、DeltaMem failure-node penalty——是 ACE delta 内容的取值扩展。
- 冲突解决：确定性规则 vs LLM（arXiv:2606.01435）——write-path 的实现取值。
- 用户可见性/审查界面：纯文本 playbook + 批准流（Anthropic）vs summary+sources（OpenAI）——M6 若涉及人在环，需登记为呈现层取值。

---

## 6. 对 AutoResearch M5/M6 的具体建议

1. **M5 增加"治理与退役"设计选项**：outcome-driven retirement（阈值/贡献分）、活跃库容量上限、证据日志（append-only，供 PAST-Bench 式通路归因消费——两者天然互补：Library Drift 的 per-skill contribution score 正是通路归因在技能库上的实例化）、回滚快照。建议作为必选项而非可选增强。
2. **M5 将"慢循环作用对象"参数化**：{任务技能, 记忆写算子, 巩固策略, 评审 rubric, 记忆架构}，对应 MemSkill / SkillCoach / MemEvolve 各自只覆盖其一；统一视图是缺口也是机会。
3. **M5 增加"巩固触发器"选项**：sync-per-episode / idle-time batch / hit-count threshold(K_cons) / scheduled（夜间）。注意 tenure crossover（arXiv:2607.21962）警告：该选项的优劣依赖评测时长，M6 评测需做纵向多 tenure 点评估。
4. **M6 评测侧新增**：（a）纵向评测协议（tenure crossover 表明单时点排名不可靠）；（b）可信性维度（TAME 的 misevolution 风险、记忆投毒攻击面 arXiv:2605.15338）；（c）基准诚信检查（LoCoMo 6.4% 答案键错误——若用 LoCoMo/LongMemEval 需先审计）。
5. **工业界对照项**：若 AutoResearch 涉及人机交互，对照 Anthropic（逐条批准）vs OpenAI（summary+sources+legacy 回退）两种记忆审查界面登记为呈现层设计取值；"只改可读记忆层、不改权重"已成为 2026 工业界共识安全基线，建议 M5 显式声明。

---

## 7. 局限与不确定性

- 工业界细节（Dreaming V3 三层、Brain 指标、Anthropic playbooks）来自厂商博客与二手报道，【原文】性弱于 arXiv；Harvey 6x、Perplexity +25% 等为一方数据。
- 部分论文（Metis、Yunjue、MemEx 等）仅从引用链获得标题级信息，未逐一读全文；标注为【原文（引文/标题）】。
- arXiv 编号为 26xx 的论文按检索结果原样记录日期；个别 v1/v2 日期可能晚于实际首发。
- 未覆盖非英语（中文社区如 GLM-5 的 agentic engineering 报告 arXiv:2602.15763 仅瞥见）与专利渠道。
