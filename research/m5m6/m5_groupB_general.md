# M5 Memory 设计空间调研：通用 LLM Agent 记忆架构（Group B）

> 调研日期：2026-08-25。目标：为 AutoResearch 框架 M5 Memory 模块定稿提供设计空间。
> 标注约定：【原文】= 一手论文/代码/官方文档直接陈述；【推断】= 本报告作者的归纳、外推或判断。
> 对经典基线仅提取设计轴；对 ACE 与 2026 新工作做重点深挖。

---

## 0. TL;DR

1. 2025–2026 的核心共识已经从"记忆=向量库+RAG"转向**记忆=可演化的结构化工件（evolving artifact）**：ACE playbook、A-MEM 卡片、Voyager skill、MemoryOS 分页、MemSkill 技能库都是"写入后要被反复修改的对象"。
2. **写入侧的最大陷阱是 LLM 整篇重写**：ACE 用实验给出教科书级证据——整篇重写（monolithic rewrite）导致 context collapse，18,282 token 的 playbook 一步退化为 122 token，准确率从 66.7 跌到 57.1（低于无记忆的 63.7 基线）。【原文】
3. 2026 年的前沿是**记忆操作本身可学习/可进化**：MemRL（RL 在情景记忆上做检索价值估计）、MemSkill（记忆操作写成可进化 skill）、MemEvolve（连记忆架构本身都元进化）、Memory as Action（把 prune&write 内化进策略动作空间）、MemP（程序性记忆的构建-检索-更新策略系统化消融）。
4. 对研究型 agent（长时程、假设驱动、证据密集），最关键的设计是：**增量 delta 写入 + 可追溯条目级结构 + 程序性/方法论记忆作为一等公民 + 反馈信号质量控制**。【推断】

---

## 1. 经典基线：设计轴提取

### 1.1 Generative Agents (Park et al., 2023, arXiv:2304.03442)
- **表示**：自然语言 observation 流（stream），每条带时间戳。
- **写入触发**：无门槛，所有感知/对话直接追加。
- **检索**：score = recency × importance × relevance（三个标量加权），注入为 top-k 记忆列表。
- **更新/遗忘**：无显式遗忘；reflection 周期性地把一批 observation 合成为高层 insight 再写回流中（树状聚合）。
- **作用域**：单 agent / 单模拟世界。
- **失效模式**：importance 由 LLM 1–10 打分，噪声大且校准漂移；检索三元组对"方法论类"知识无区分度；记忆流线性膨胀。【推断】

### 1.2 MemGPT / Letta (Packer et al., 2023, arXiv:2310.08560)
- **表示**：分层上下文——main context（OS 级，含 system instructions + 工作上下文）+ archival memory（外部分页存储）。
- **写入触发**：agent 自主调用 memory 函数（self-directed editing），LLM 自己决定何时把 main context 内容换出到 archival。
- **检索**：agent 显式发起 query（语义/分页浏览），注入为函数返回。
- **更新/遗忘**：context 满时由 agent 决定驱逐（paging 类比）；无自动衰减。
- **作用域**：会话级 + 跨会话持久；Letta 后来扩展到 sleep-time 离线整理。
- **失效模式**：记忆管理占用大量推理 token；agent 驱逐决策质量不稳；检索是"agent 想起去查"而非自动注入，可能漏查。【推断】

### 1.3 Voyager (Wang et al., 2023, arXiv:2305.16291)
- **表示**：**可执行代码**（JavaScript skill），skill library 存 embedding 索引。
- **写入触发**：任务成功且 skill 通过自动课程验证后才入库（execution-verified 准入门）。
- **检索**：按当前任务描述 embedding 相似度 top-k，以代码形式注入 prompt。
- **更新/遗忘**：只增不减；同类 skill 靠描述去重。
- **作用域**：Minecraft 环境内，可迁移到新的世界实例。
- **失效模式**：skill 粒度不可控（过细爆炸、过粗难组合）；验证门依赖环境可执行性，难迁移到无 ground truth 任务。【推断】

### 1.4 Reflexion (Shinn et al., NeurIPS 2023)
- **表示**：自由文本自我反思（verbal RL 信号），短期 episodic buffer。
- **写入触发**：任务失败后由评估器触发反思，写入下一次 trial 的上下文。
- **检索**：无检索——直接全部注入下一次尝试的 prompt（FIFO 滑窗）。
- **更新/遗忘**：窗口外即遗忘；无跨任务持久。
- **作用域**：单任务内多 trial。
- **失效模式**：反思是"完整重写式"的（ACE 证明这会 collapse）；不积累跨任务知识；依赖可验证的成败信号。【推断】

### 1.5 ExpeL (Zhao et al., AAAI 2024)
- **表示**：两类记忆——经验池（成功/失败轨迹对）+ 抽象出的自然语言 insight 列表。
- **写入触发**：离线训练期收集轨迹后批量抽取 insight（跨任务 compare 成败对）。
- **检索**：insight 全量注入 system prompt；经验按相似度检索 few-shot。
- **更新/遗忘**：离线静态，部署后不更新。
- **作用域**：跨任务（同 benchmark 分布）。
- **失效模式**：离线一次性，无法在线持续适应；insight 全量注入在规模上有上限。【推断】

### 1.6 A-MEM (Xu et al., NeurIPS 2025, arXiv:2502.12110)
- **表示**：Zettelkasten 卡片——每条记忆带 LLM 生成的结构化属性（keywords、tags、contextual description）+ 显式链接到其他卡片。
- **写入触发**：每次交互后由 LLM 构建 note；写入时自动生成链接。
- **检索**：embedding 相似度 + 沿链接做一跳扩展（上下文感知的动态邻域）。
- **更新/遗忘**：**memory evolution**——新卡写入时会触发旧卡属性/链接的就地更新（类似 ACE 的 in-place update 思想）；无衰减遗忘。
- **作用域**：单 agent 长期对话/任务。
- **失效模式**：链接与演化都由 LLM 决定，错误会沿图传播（链接污染）；卡片演化等于局部重写，仍有小规模 brevity 风险。【推断】

---

## 2. ACE（Agentic Context Engineering）深挖 【原文为主】

来源：arXiv:2510.04618（Stanford/SambaNova/UC Berkeley，ICLR 2026 接收）；官方代码 github.com/ace-agent/ace；社区复现 kayba-ai/agentic-context-engine、mgechev/ACE-open。

### 2.1 定位与三角色架构
ACE 把 context adaptation（记忆是其中一种）形式化为 Generator → Reflector → Curator 的循环，构建在 Dynamic Cheatsheet（Suzgun et al., arXiv:2504.07952）之上：
- **Generator**：带当前 playbook 解题，产出推理轨迹，并标注哪些 bullet 有帮助/有误导（helpful/harmful 反馈）。
- **Reflector**：从轨迹中蒸馏具体教训，可多轮迭代精炼（≤5 轮）；有无 ground-truth 均可工作（可用执行反馈，如代码运行成败）。
- **Curator**：把教训合成为**紧凑 delta 条目（候选 bullet）**，由**确定性非 LLM 逻辑**合并进 playbook。

结果：AppWorld +10.6%（平均），金融 FiNER/Formula +8.6%；离线适配延迟较 GEPA 降 82.3%、rollout 降 75.1%；在线较 DC 延迟降 91.5%、token 成本降 83.6%。无标签也能适配。ReAct+ACE（DeepSeek-V3.1）在 AppWorld 平均分 59.4 追平 GPT-4.1 的 IBM CUGA（60.3）。【原文】

### 2.2 Delta 增量合并 vs 整篇重写（核心设计决策）
- **表示**：playbook = 分区（STRATEGIES AND HARD RULES / CODE SNIPPETS / TROUBLESHOOTING AND PITFALLS 等）的**带 ID bullet 列表**；每个 bullet = 元数据（唯一 ID + helpful/harmful 计数器）+ 内容（可复用策略、领域概念、常见失败模式）。
- **写入**：Curator 只产出 delta（ADD / 更新既有 bullet 计数 / 内容微调），合并是**非 LLM 的确定性操作**——这是与 Dynamic Cheatsheet / Reflexion 式"让 LLM 整篇重写记忆"的根本分野。
- **好处**：(1) 局部化——只动相关 bullet；(2) 细粒度检索；(3) 多个 delta 可并行合并，支持批量适配；(4) 保留历史原文，不被压缩。【原文】

### 2.3 Context Collapse：18282 → 122 的机制
ACE §2.2 在 AppWorld 上的案例研究（Figure 2）：当 LLM 被要求在每一步**整篇重写**累积上下文时——
- 第 60 步：上下文 18,282 token，准确率 66.7；
- 第 61 步：上下文**塌缩到 122 token**，准确率 57.1——**低于无适配基线 63.7**。
- 机制：随上下文变大，模型倾向于把它"总结"成短得多的泛化文本（brevity bias 的极端形式），累积的细节被一次性抹除。作者强调这不是 Dynamic Cheatsheet 特有的 bug，而是**一切 end-to-end LLM 重写式记忆更新的根本风险**。【原文】
- 【推断】机制本质是：重写 = 每次都要把"旧知识 + 新观察"重新过一次有损压缩器（LLM 生成），误差随步数复利累积；且 LLM 的"生成简洁答案"先验在重写任务中被放大。delta 合并把压缩器从更新路径上移除，只在 Reflector 抽取新教训时经过 LLM——新信息天然是小的，压缩损失有界。

### 2.4 Grow-and-Refine 循环
- **Grow**：新 bullet 带新 ID 追加；已有 bullet 就地更新（如计数器 +1）。
- **Refine**：基于语义 embedding 的去重合并，可主动（每个 delta 后）或惰性（超窗口才触发）执行；社区实现还加了按 helpful/harmful 计数的低价值剪枝（max_bullets 上限）与 hybrid 检索注入。
- 关键平衡：增长是一等原则（反对 brevity），精炼只控冗余不控篇幅。【原文+社区实现】

### 2.5 已知失效模式（作者自陈，Appendix B）
- 依赖足够强的 Reflector；抽不出洞见时上下文会被噪声污染。
- **反馈信号质量是命门**：无 GT 标签也无执行信号时（FiNER 无标签设置），ACE 和 DC 都会退化——"context adaptation depends critically on feedback quality"。【原文】
- 并非所有任务受益：HotPotQA 类只需简洁高层指令，Game of 24 类一条规则即可——长 playbook 冗余。
- 【推断】ACE 默认全量/半全量注入 playbook，长 playbook 下成本靠 KV cache 复用摊销；对"研究型 agent"的证据级条目（大段引用）该策略可能撑不住，需要真正的检索门。

---

## 3. 2026 年最新工作深挖（4+2 个）

### 3.1 MemRL（arXiv:2601.03192，2026-01，上海 AI Lab 系）
- **一句话**：非参数自进化——把情景记忆当 Q 表，用运行时 RL 学"哪条记忆值得检索"。【原文摘要】
- **表示**：情景记忆条目（轨迹/策略 + 环境反馈效用值）；推理模型权重冻结。
- **写入**：episode 结束后写入，附带由环境反馈更新的 utility 估计。
- **检索**：**Two-Phase Retrieval**——先语义召回，再用学到的效用值过滤噪声、挑高价值策略；直接攻击"被动语义匹配召回噪声"这一 RAG 式记忆主失效模式。
- **更新/遗忘**：RL 式价值更新替代启发式打分；冻结权重规避灾难性遗忘（stability–plasticity 的解耦：stable reasoning / plastic memory）。
- **评测**：HLE、BigCodeBench、ALFWorld、Lifelong Agent Bench 超 SOTA。
- **对 M5 的启示**：检索排序信号应从"相似度"升级为"相似度 × 已验证效用"；helpful/harmful 计数（ACE）是该思想的轻量近似。【推断】

### 3.2 MemSkill（arXiv:2602.02474，2026-02）
- **一句话**：把记忆操作（抽取/巩固/剪枝）本身做成**可学习、可进化的 skill 库**。【原文摘要】
- **结构**：controller（学选哪些 skill）→ LLM executor（按 skill 产记忆）→ designer（定期复盘 hard case，提出 skill 的改进与新 skill）。选择策略与技能集双闭环进化。
- **动机**：现有系统的记忆操作是静态手工流程，硬编码了人类先验，在长历史上低效。
- **评测**：LoCoMo、LongMemEval、HotpotQA、ALFWorld。
- **对 M5 的启示**：AutoResearch 的"研究方法论记忆"恰好是 skill 化记忆的最佳载体——"如何做消融""如何记录阴性结果"是可复用例程；且 skill 本身可被 designer 角色进化，契合 AutoResearch 的自动化研究元循环。【推断】

### 3.3 MemEvolve + EvolveLab（arXiv:2512.18746，2025-12，NeurIPS 方向工作）
- **一句话**：元进化——不仅进化记忆内容，还进化**记忆架构本身**（encode/store/retrieve/manage 四元设计空间内搜索）。【原文摘要】
- **贡献**：EvolveLab 把 12 个代表性记忆系统蒸馏成统一模块化代码库；MemEvolve 在该空间上联合进化经验知识与架构，SmolAgent/Flash-Searcher 提升最高 17.06%，且跨任务、跨 LLM 迁移。
- **对 M5 的启示**：(1) 四元分解（encode/store/retrieve/manage）可作为 M5 内部模块接口的事实标准；(2) "没有唯一最优记忆架构，应按任务搜索"是对 M5 定稿的重要警示——M5 应暴露可配置轴而非锁死单点。【推断】

### 3.4 MemoryOS（arXiv:2506.06326，EMNLP 2025）
- **一句话**：操作系统类比的三级记忆存储。
- **结构**：short-term（当前对话页）→ mid-term（按 dialogue-chain FIFO 换入换出）→ long-term personal memory（segmented page 组织，分段页式整理）；四模块：Storage / Updating / Retrieval / Generation。
- **更新**：短→中用 FIFO 链式批量转储；中→长用分段页聚合（类 OS 的页置换 + 段式管理）。
- **评测**：LoCoMo 上 F1 +49.11%、BLEU-1 +46.18%（GPT-4o-mini）。【原文】
- **对 M5 的启示**：层级 + 显式晋升/降级策略是成本与保真度工程权衡的成熟模板；但 FIFO/分段是内容无关启发式，对研究型 agent 应换成重要性/假设相关性门控。【推断】

### 3.5 MemP（Procedural Memory，arXiv:2508.06433）
- **一句话**：把程序性记忆当一等优化对象，系统消融 构建×检索×更新 三组策略。
- **设计点**：构建（全轨迹 vs 显式 guideline 引导）；检索 key（query-vector vs keyword-vector）；更新（普通追加 / 验证过滤 / 反思式 / 动态丢弃）。
- **发现**：程序性记忆随规模优雅扩展、可迁移到邻近任务；测试期持续更新带来"近线性"的任务掌握曲线。【原文】
- **对 M5 的启示**：研究型 agent 的"可复用研究流程"（文献筛选协议、统计检验流程）正是程序性记忆；更新策略中"验证过滤 + 动态丢弃"组合值得默认采用。【推断】

### 3.6 Memory as Action / MemAct（arXiv:2510.12635）
- **一句话**：不把记忆管理外包给固定启发式，而把 **Prune&Write 原子操作放进策略动作空间**，用 RL（DCPO 算法）训练 agent 自主决定何时删哪些历史、写什么 memory note；memory action 记录就地保留、可被未来修改。
- **对 M5 的启示**：长时程研究 agent 的工作上下文管理（何时把中间结果折叠成 note、何时丢弃原始轨迹）本质是序列决策；短期可用启发式+LLM 判断近似，长期看"上下文管理可训练"是方向。【推断】

### 3.7 备选参考（未深挖但相关）
- A Survey of Agent Memory in the Second Half（arXiv:2602.06052，2026-01，v4 2026-08）：三维度统一视图——substrate（参数/外部）、认知机制（sensory/working/episodic/semantic/procedural）、主体（user/agent）；并指出**记忆操作的学习策略（RL 化的 context curation、决策时巩固、可移植 skill 生态）是新兴前沿**。【原文摘要】
- Adaptive memory admission control（arXiv:2603.04549，2026）：记忆**准入门**的可学习化，直接对应"写入准入"轴。
- Hybrid episodic-procedural tool-use agent（arXiv:2512.07287，2026）：情景+程序性混合记忆的工程实证。
- Agentic Memory（arXiv:2601.01885，2026）：统一长短时记忆管理的可学习化。

---

## 4. 统一字段对照表

| 系统 | 表示格式 | 写入触发/准入门 | 检索与注入 | 更新/遗忘 | 作用域 | 已知失效模式 |
|---|---|---|---|---|---|---|
| Generative Agents | NL 事件流+时间戳 | 无门槛全量 | recency×importance×relevance 加权 top-k | reflection 树状聚合；无遗忘 | 单 agent | 打分噪声、线性膨胀 |
| MemGPT/Letta | 分层：main ctx + 分页 archival | agent 自主调函数 | agent 显式查询，函数返回注入 | 手动换页驱逐 | 跨会话 | 管理开销大、漏查 |
| Voyager | 可执行代码 skill | 执行验证通过才入库 | 任务 embedding 相似度，代码注入 | 只增 | 环境内迁移 | 粒度难控、依赖可验证环境 |
| Reflexion | 自由文本反思 | 失败后 | 全量滑窗注入 | 窗口外遗忘 | 单任务多 trial | 重写式、不跨任务 |
| ExpeL | 轨迹池 + insight 列表 | 离线批量抽取 | insight 全量+轨迹 few-shot | 静态 | 跨任务(同分布) | 不在线、规模上限 |
| A-MEM | Zettelkasten 卡片+属性+链接 | 每交互构建 note | embedding+链接一跳扩展 | 新卡触发旧卡就地演化 | 单 agent 长期 | 链接污染传播 |
| **ACE** | 分区 bullet 列表（ID+helpful/harmful 计数） | Reflector 蒸馏→Curator 产 delta | 细粒度 bullet 检索/全量 playbook | **非 LLM 确定性 delta 合并**；grow-and-refine 去重剪枝 | 离线 prompt 优化 + 在线记忆 | 依赖反馈信号质量；Reflector 弱则污染；简单任务冗余 |
| MemRL | 情景条目+效用值 | episode 结束 | 两阶段：语义召回→效用过滤 | RL 价值更新；权重冻结 | 运行时连续学习 | 需可计算环境反馈 |
| MemSkill | 记忆操作 skill 库+产出记忆 | controller 选 skill 执行 | 由 skill 定义 | designer 复盘进化 skill 集 | 跨任务泛化 | skill 进化稳定性 |
| MemEvolve | 四元(encode/store/retrieve/manage)架构搜索空间 | 依被进化架构 | 依被进化架构 | 架构级元进化 | 跨任务/跨 LLM | 搜索成本 |
| MemoryOS | 三级存储（短/中/长）+ 分页 | FIFO 链式+分段页 | 分层检索 | 层级晋升/降级 | 长对话 | 内容无关启发式 |
| MemP | 程序性记忆（方法/流程条目） | 轨迹或 guideline 构建 | query/keyword-vector | 追加/验证过滤/反思/动态丢弃 | 跨任务迁移 | 构建质量依赖轨迹质量 |
| MemAct | 工作上下文即记忆（就地 note） | 策略自主（RL） | 无外部检索，上下文内 | Prune&Write 就地编辑 | 长时程单任务 | 需训练；非平稳上下文 |

---

## 5. 记忆设计分类学：4 个正交轴 【推断】

综合上述系统，最能区分设计本质的不是"存什么"（episodic/semantic/procedural 已被反复使用），而是以下四条正交轴：

**轴 A：表示粒度与结构**（representation）
取值：原始轨迹流 → 原子条目（bullet/卡片）→ 结构化工件（分区 playbook / 链接图 / 代码 skill）→ 可学习操作程序（skill/架构本身）。
- 越结构化，检索与局部更新越精确，但写入成本与 schema 设计负担越高；结构本身是 inductive bias，错了会系统性扭曲记忆。

**轴 B：写入路径与准入门**（write path / admission）
取值：无门槛全量 → LLM 整篇重写 → **LLM 产 delta + 确定性合并** → 验证门（执行反馈/效用过滤）→ 可学习准入（RL）。
- 这是 2025–26 最重要的轴：ACE 证明整篇重写必然 collapse；准入门决定信噪比，但门太严会漏掉"尚未知其价值"的弱信号（研究中的反常观察往往如此）。

**轴 C：检索与注入策略**（retrieval & injection）
取值：全量注入 → 启发式打分（recency/importance/similarity）→ 两阶段（召回+效用/重排）→ agent 自主查询（memory-as-tool）→ 无检索（上下文即记忆）。
- 全量注入简单但受预算约束且稀释注意力；自主查询省 token 但依赖 agent "想起要查"；效用加权是未来方向但需要反馈闭环。

**轴 D：更新、巩固与遗忘**（consolidation & forgetting）
取值：只增不减 → 时间衰减 → 启发式剪枝/去重（grow-and-refine）→ 离线巩固（sleep-time/reflection 聚合）→ 演化式就地更新 → RL 价值化遗忘。
- 遗忘是特性不是 bug（防膨胀、防陈旧误导）；但对研究型 agent，"删除"应保守、宜降级归档而非抹除（见 §6）。

（可作第 5 轴：作用域 scope——单 episode / 单任务 / 跨任务 / 跨 agent / 跨模型；ACE 与 MemEvolve 证明了跨模型、跨任务迁移可行，但多数系统未验证。）

---

## 6. 各轴取值利弊对照（压缩版）

| 轴 | 取值 | 利 | 弊 |
|---|---|---|---|
| A 表示 | 原始流 | 零信息损失、零写入成本 | 检索噪声、膨胀、无法局部更新 |
| | 原子条目 | 可 delta、可计数、可去重 | 抽取即有损；粒度敏感 |
| | 结构化工件 | 注入格式稳定、可审计、可移植 | schema 设计负担；结构错误系统性传播 |
| | 代码/skill | 可执行验证、组合性 | 需可执行环境；粒度难控 |
| B 写入 | 全量 | 不漏 | 信噪比崩 |
| | 整篇重写 | 实现极简 | **context collapse（18282→122 实证）**；成本随历史线性 |
| | delta+确定性合并 | 无 collapse、可并行、低成本 | 需 ID/合并协议设计；reflector 质量依赖 |
| | 验证门/效用门 | 高信噪比 | 需反馈信号；漏弱信号 |
| C 检索 | 全量注入 | 无漏检 | 预算爆、注意力稀释 |
| | 启发式打分 | 便宜 | 分数校准差（GA 的 importance 打分噪声） |
| | 两阶段效用过滤 | 抗噪（MemRL 实证） | 需效用学习闭环 |
| | 自主查询 | 省 token、按需 | 漏查风险；增加决策负担 |
| D 更新 | 只增 | 简单、无损 | 膨胀、陈旧知识误导 |
| | 衰减/FIFO | 可预期 | 内容无关，误删高价值旧记忆 |
| | 去重+计数剪枝 | 保密度（ACE） | 语义去重可能合并"看似相同实则条件不同"的条目 |
| | 离线巩固 | 不占在线预算 | 延迟、管道复杂 |
| | RL 价值化 | 最优潜力 | 训练成本、非平稳 |

---

## 7. 对"研究型 agent"（AutoResearch M5）最关键的设计判断 【推断】

研究型 agent 的特征：长时程（数天项目）、假设驱动（记忆要支持"我试过 X 因为假设 Y，证据 Z 反驳了它"）、证据密集（必须可追溯、不可被压缩掉细节）。

1. **最高优先级：delta 写入 + 确定性合并（轴 B）**。ACE 的 collapse 证据对研究场景是致命的——研究记忆恰恰是最不能承受"被总结掉细节"的场景（18282→122 就是证据清单变成一句"有些方法有效"）。M5 的任何更新路径都不应让 LLM 整篇重写已有记忆；LLM 只产增量，合并交给代码。
2. **条目级结构化表示 + 审计元数据（轴 A/C）**。ACE 的 bullet（ID + helpful/harmful 计数）几乎可直接映射为研究记忆的"假设/证据/方法/坑"四区 playbook；计数器机制对"证据强度"是天然载体（多次复现成功的结论计数高）。建议扩展为：每条目带 provenance（来源实验/文献 ID）——这是 ACE 没有但研究必须的。
3. **程序性记忆一等公民（MemP/MemSkill 方向）**。研究能力的复用主要在方法论层面（实验设计模板、统计检查清单、写作模式），应独立成库、独立检索、可被 designer 式角色进化。这与 AutoResearch 的自动化元循环天然契合。
4. **检索用两阶段：相关性召回 + 效用/假设相关性重排（MemRL 思想）**。纯语义相似度会漏掉"方法不同但检验同一假设"的记忆；研究场景的检索 key 应包含当前假设，而非仅当前任务描述。
5. **遗忘保守化：降级而非删除**。研究中"阴性结果"和"被反驳假设"是高价值记忆（防止重复试错）；grow-and-refine 式去重可保留，但剪枝应改为归档层（MemoryOS 式降级），并记录删除理由。
6. **明确的风险提示**：(a) ACE 作者自证——无可靠反馈信号时自适应记忆会退化，研究 agent 的反馈（实验成败）通常是可用的，但"结论是否正确"没有 ground truth，Reflector 可能把误读固化为 playbook 条目，需置信度标记与人工/自动复核通道；(b) MemEvolve 的结论——无单一最优架构，M5 应把上述四轴做成可配置参数，为后续 AutoResearch 自我实验留接口。

---

## 8. 主要一手来源

- ACE: arXiv:2510.04618（HTML v1 全文）；代码 github.com/ace-agent/ace；复现 kayba-ai/agentic-context-engine、mgechev/ACE-open
- Dynamic Cheatsheet: arXiv:2504.07952
- MemRL: arXiv:2601.03192
- MemSkill: arXiv:2602.02474
- MemEvolve/EvolveLab: arXiv:2512.18746
- MemoryOS: arXiv:2506.06326（EMNLP 2025）
- MemP: arXiv:2508.06433
- Memory as Action (MemAct): arXiv:2510.12635
- A-MEM: arXiv:2502.12110（NeurIPS 2025）
- Mem0: arXiv:2504.19413
- 综述：A Survey of Agent Memory in the Second Half, arXiv:2602.06052（v4, 2026-08）；A Survey of Self-Evolving Agents, arXiv:2508.07407 系
- 经典：Generative Agents arXiv:2304.03442；MemGPT arXiv:2310.08560；Voyager arXiv:2305.16291；Reflexion (NeurIPS 2023)；ExpeL (AAAI 2024)
- 备选新工作：arXiv:2603.04549（admission control）、arXiv:2512.07287（hybrid episodic-procedural）、arXiv:2601.01885（unified LTM/STM 学习）
