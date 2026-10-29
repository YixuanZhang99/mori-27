# AutoResearch 系统设计空间与 Arbor Baseline 统一分析

> 基于《Toward Generalist Autonomous Research via Hypothesis-Tree Refinement》（Arbor，arXiv:2606.11926，人大高瓴 × MSRA，2026.06）
> 用途：① AutoResearch 方向 related work 骨架；② 自研系统的设计 checklist 与差异化定位工具。

---

## 0. 一页总览

**核心命题**：AutoResearch / Autonomous Optimization（AO）系统的差异可以完备地分解为 **7 个正交设计维度**的取值组合：

```
系统 = ⟨ D1 搜索对象, D2 状态拓扑, D3 记忆语义层级, D4 提议算子,
         D5 前沿控制, D6 证据准入协议, D7 执行模型 ⟩
```

**关键结论**（由 Arbor 消融实验支撑）：
- **D3（语义记忆）比 D2（结构）更值钱**：去掉 insight feedback，MLE-Bench Lite Any Medal 从 81.82 → 54.54；去掉树结构只降到 63.64。结构是记忆的载体，记忆才是增益来源。
- **D6（dev/test 准入纪律）是"研究系统"与"长时间运行的 agent"的分水岭**：裸跑的强 coding agent 会出现明显的 dev 过拟合（Claude Code 在 Terminal-Bench 上 dev 75.00 / test 71.70）。
- **强模型 + 无结构 ≈ 弱模型 + 好结构**：Codex 用 GPT-5.5 (xhigh) 在 MLE-Bench Lite 仅 68.18 Any Medal；Arbor 同模型 86.36，且 gold 率 77.27 为全表最高。

---

## 1. Arbor 论文速览

### 1.1 问题形式化：Autonomous Optimization (AO)

$$P = (M_0, O, E_{dev}, E_{test})$$

- $M_0$：可修改的初始 artifact（代码库 + 数据）
- $O$：优化目标（指标方向）
- $E_{dev}$：探索期可自由使用的评估器
- $E_{test}$：held-out 评估器，衡量提升是否可迁移
- 目标：$M^* = \arg\max_{M' \in A} S_{test}(M')$，且搜索过程不得把 $E_{test}$ 当 oracle

### 1.2 方法：Hypothesis Tree Refinement (HTR)

- **节点三元组**：$n = \langle h_n, \iota_n, \mu_n \rangle$ = ⟨假设, 洞察, 元数据(状态/分数/结果/git 分支引用)⟩
- **双层架构**：长寿命 coordinator（拥有树，六步循环 Observe → Ideate → Select → Dispatch → Backpropagate → Decide）+ 短寿命 executor（一个假设一个隔离 git worktree，**hypothesis-bound：不许中途改假设**，否则返回的分数失去归因意义）
- **insight 向上抽象**：叶子实验结果 → 方向级 lesson → 全局 prior
- **held-out merge gate**：候选只有在 $E_{test}$ 上超过当前 best 才合并进主干

### 1.3 主要实验结果

- 6 个真实研究任务（模型训练 / harness 工程 / 数据合成各 2 个），Arbor 全部取得最佳 held-out 结果，平均相对增益 > 2.5× Codex / Claude Code（同接口同预算 48h）
- MLE-Bench Lite：GPT-5.5 backbone 下 86.36% Any Medal、77.27% Gold（对比表内最高）
- 跨任务迁移：BrowseComp 上进化出的 harness 冻结后直接提升 HLE（25.50→31.50）与 DeepSearchQA（61.00→69.00）
- Token 消耗 20.12M–43.19M，与单轨迹 baseline 同量级——增益来自预算的**组织方式**而非总量

---

## 2. Baseline 的两层角色（读表前必读）

| 角色 | 系统 | 性质 | 能回答的问题 |
|---|---|---|---|
| **受控对照**（论文 Table 2） | Codex (GPT-5.5)、Claude Code (Opus 4.6)，均开 `/goal` 长任务模式 | 同初始材料、同评估器、同 48h 预算、同 prompt | 同等模型能力与资源下，**显式研究状态管理**的增量价值 |
| **榜单参照**（论文 Table 3） | AIDE、ML-Master 1/2.0、AIRA-dojo、InternAgent、R&D-Agent、Famou-Agent 2.0、MARS、Leeroo、AIBuildAI、LoongFlow、AI-Scientist、Codex | MLE-Bench 官方榜单 + AI-Scientist 论文数字，**backbone 混杂** | Arbor 在整个赛道中的绝对位置 |

⚠️ 读 Table 3 的注意点：
- 真正有框架级对照价值的只有 **Gemini-3-Flash 同 backbone 组**：AIDE 45.45 / LoongFlow 77.27 / AI-Scientist 81.82 / Arbor 81.82（Any Medal）
- 跨行比较存在 backbone 混杂（MARS 用 Gemini-3-Pro、AIBuildAI 用 Opus 4.6 等），论文自己也承认：框架 model-agnostic，但天花板取决于 task–backbone fit（Opus 4.6 擅长 BrowseComp 类诊断推理，GPT-5.5 擅长 ML 工程知识密集型任务）

---

## 3. 七维设计空间详解

### D1 搜索对象（优化什么）

| 取值 | 代表系统 |
|---|---|
| 论文 / 想法 | AI-Scientist v1/v2、Agent Laboratory |
| ML 工程代码 | AIDE、ML-Master、AIRA-dojo、AIBuildAI、MLE-Bench 系 |
| 程序 / 算子 | FunSearch、AlphaEvolve |
| Agent harness | AutoHarness、Meta-Harness、AHE |
| 数据 | DataMaster |
| 因子 / 模型（工业 R&D） | R&D-Agent |
| **任意 artifact（AO 统一形式化）** | **Arbor** |

趋势：搜索对象不断泛化，Arbor 的 AO 形式化把以上全部收编为 $M_0$ 的实例。

### D2 状态拓扑（探索结构怎么组织）

```
单轨迹 ──→ 线性 pipeline ──→ 扁平队列/种群 ──→ 树 ──→ 种群×树(空白)
(Codex)    (AI-Scientist v1)  (FunSearch)      (AIDE, Arbor)
```

- 树的双重作用：① 保持探索的分支结构；② 提供从"宽泛方向"到"可执行干预"的抽象层级
- AlphaEvolve 的 island 模型提供多样性，但与语义树结构互不兼容——**混合拓扑是空白点**

### D3 记忆语义层级（经验以什么粒度沉淀）⭐ 最重要维度

| 层级 | 形态 | 代表 |
|---|---|---|
| L0 无显式记忆 | 对话历史 / 文件系统 | Codex、Claude Code |
| L1 语法层记忆 | code + score | AIDE、FunSearch、AlphaEvolve |
| L2 蒸馏文本 | lesson / wisdom / playbook / cognitive cache | ML-Master 2.0（L1/L2/L3 缓存）、MARS（反思组件）、Reflexion |
| L3 语义绑定记忆 | hypothesis ↔ insight ↔ evidence 锚定，可向上抽象 | **Arbor** |
| L4 跨 run 持久化 | 假设级知识图谱，跨任务累积检索 | **空白（本团队方向）** |

Arbor 消融：D3 从 L3 降到 L1（w/o insight feedback）损失 −27.28 个百分点；D2 降级（w/o tree）损失 −18.18。**语义记忆 > 结构本身**。

### D4 提议算子（新候选从哪来）

| 取值 | 代表 |
|---|---|
| 自由生成 | Codex、AI-Scientist v1 |
| 反思式修正 | Reflexion、MARS |
| 显式算子集（draft/improve/debug/analyze） | AIDE、AIRA-dojo |
| LLM diff 变异（程序级） | FunSearch、AlphaEvolve |
| 文献条件化 | AI-Researcher、R&D-Agent |
| 知识库检索条件化 | AIBuildAI 2.0（~1000 文档 agentic RAG）、ML-Master 2.0（L3 wisdom 检索） |
| **证据条件化 ideation**（树上 validated insight 作正约束、pruned 节点作负约束） | **Arbor** |

空白：**显式负样本库条件化**——把失败假设编码为可检索的负样本，主动约束生成（Arbor 的负约束是被动的）。

### D5 前沿控制（下一步试什么）

| 取值 | 代表 |
|---|---|
| 无（顺序执行到预算耗尽） | Codex、Claude Code |
| 验证分数 best-first | AIDE |
| MCTS | ML-Master、AIRA-dojo（可选策略） |
| fitness 选择压 | FunSearch、AlphaEvolve |
| 职能角色调度 | AIBuildAI（manager→designer/coder/tuner）、LoongFlow |
| **coordinator 全局策略**（证据感知、可并行、可剪枝、选择理由不限于分数最大化——也包括"消除歧义""验证关键假设"） | **Arbor** |

注意 Arbor 的 Select 语义：选择某个假设可能因为它**失败时能提供最大信息**——这是实验设计思维，不是纯 exploit。

### D6 证据准入协议（什么算"真正的进步"）⭐ 分水岭维度

| 取值 | 代表 |
|---|---|
| 无（最后状态即结果） | Codex、Claude Code、多数 pipeline |
| fitness / dev 直接采纳 | FunSearch、AlphaEvolve、AIDE |
| 奖牌阈值（benchmark 外置） | MLE-Bench 各系统 |
| **held-out merge gate**（dev 指导搜索，test 决定合并；dev/test 分歧本身作为"可能在钻评估器空子"的证据） | **Arbor** |

工业映射：单次真实评估成本高的场景（如本团队 10h+ 离线评估），可用 **surrogate 指标当 dev、真实评估当准入 gate**，是 D6 的自然延伸。

### D7 执行模型（实验怎么跑、结果归因给谁）

| 取值 | 代表 |
|---|---|
| 共享工作区串行 | Codex、Claude Code、多数 pipeline |
| 隔离环境 | AIRA-dojo |
| 并行评估 | AlphaEvolve |
| **git worktree 隔离 + 兄弟节点并行 + hypothesis-bound 归因** | **Arbor** |

hypothesis-bound 约束的精妙之处：若 executor 在指标停滞时可以改假设，返回的分数就不再是该节点的证据，祖先节点的 insight 也无法解释——**归因完整性是树状记忆可解释的前提**。

---

## 4. 全系统组合映射表

| 系统 | D1 对象 | D2 拓扑 | D3 记忆 | D4 提议 | D5 控制 | D6 准入 | D7 执行 |
|---|---|---|---|---|---|---|---|
| Codex / Claude Code | 任意代码 | 单轨迹 | L0 对话历史 | 自由生成 | 无 | 无 | 共享串行 |
| AI-Scientist v1 (Lu 2024) | 论文 | 线性 | L0 | 自由+novelty check | 固定阶段 | 无 | 串行 |
| AI-Scientist v2 (Yamada 2025) | 论文 | 树 | L1 | 反思式 | 树搜索 | 无 | 串行 |
| AI-Scientist (Chen 2026) | ML 工程 | 树+持久工作区 | L1~L2 | 反思式 | 树搜索 | 无 | 串行 |
| Agent Laboratory | 论文 | 线性 | L0 | 自由 | 固定阶段(人在环) | 无 | 串行 |
| AIDE (Jiang 2025) | ML 代码 | 树 | L1 | 算子集 | best-first | dev 分数 | 隔离 |
| AIRA-dojo (Toledo 2025) | ML 代码(框架) | 树 | L1 | 算子集 | 贪心/MCTS 可配 | dev 分数 | 隔离 |
| ML-Master (Liu 2025) | ML 代码 | 树(MCTS) | L1 | 算子集 | MCTS | dev 分数 | 隔离 |
| ML-Master 2.0 (Zhu 2026) | ML 代码 | 树(MCTS) | **L2 三层认知缓存** | 算子+wisdom 检索 | MCTS | dev 分数 | 隔离 |
| AIBuildAI 2.0 (Zhang 2026) | ML 模型 | 扁平+职能层级 | L2 知识库 RAG | 自由+知识检索 | manager 调度 | dev 分数 | 职能分工 |
| R&D-Agent (Yang 2025) | 因子/模型 | 线性多角色 | L2 摘要 | 文献条件化 | 角色流水线 | dev 分数 | 分工 |
| LoongFlow (Wan 2025) | ML 方案 | 线性多角色 | L2 摘要 | 条件化 | 角色流水线 | dev 分数 | 分工 |
| InternAgent (Team 2026) | 研究方案 | 线性多角色 | L2 | 条件化 | 角色流水线 | dev 分数 | 分工 |
| MARS (Chen 2026b) | ML 代码 | 模块化 | L2 反思文本 | 反思式 | 模块编排 | dev 分数 | 串行 |
| FunSearch (Romera-Paredes 2024) | 程序 | 种群 | L1 程序+fitness | LLM 变异 | fitness 选择 | fitness | 并行 |
| AlphaEvolve (Novikov 2025) | 程序 | 种群(island) | L1 | LLM diff 变异 | fitness 选择 | fitness | 并行评估 |
| DataMaster (Du 2026) | 数据 | 树(DataTree) | L2~L3 全局记忆 | 条件化 | coordinator | dev 分数 | 分工 |
| **Arbor (Jin 2026)** | **任意 artifact** | **假设树** | **L3 语义绑定+向上抽象** | **证据条件化** | **coordinator 六步循环** | **held-out merge gate** | **worktree 并行+hypothesis-bound** |

---

## 5. 演化脉络：一条清晰的维度升级链

```
AIDE(2025.初)          树结构首次引入 ML 工程搜索           [D2↑]
  ↓
AIRA-dojo              算子×策略解耦，搜索策略本身可研究      [D4/D5 模块化]
  ↓
AI-Scientist v2        树搜索进入端到端研究流程              [D2 泛化]
  ↓
ML-Master 2.0          层级认知缓存，记忆首次分层            [D3↑]
  ↓
AlphaEvolve            并行评估+种群多样性（另一条线）        [D7↑, D2 分叉]
  ↓
DataMaster             树+全局记忆迁移到数据对象             [D1 泛化]
  ↓
Arbor(2026.06)         D3/D6/D7 同时拉满，AO 统一形式化      [D3↑↑ D6↑↑ D7↑]
```

**Arbor 的定位**：没有发明新零件，而是把既有零件在三个关键维度上同时推到当前最高取值，并用 AO 形式化统一了搜索对象。其论文消融恰好反向验证了维度的重要性排序：**D3 > D2 > （D6 未消融但 Table 2 的 dev/test 反差提供了证据）**。

---

## 6. 空白设计点（差异化机会）

| # | 空白组合 | 现状 | 机会描述 |
|---|---|---|---|
| 1 | **D3 = L4：跨 run 假设级知识图谱** | Arbor 的树单 run 封存；ML-Master 2.0 的 L3 跨任务但只有平铺 wisdom | 把假设、证伪记录、适用条件作为可检索节点跨任务累积——直接对应本团队经验管理方案 |
| 2 | **D6 × 高成本工业评估** | merge gate 仅见于 Arbor 且 test 成本低 | surrogate/离线代理指标当 dev、10h+ 真实评估当准入 gate；与探索效率设计（surrogate-based）天然耦合 |
| 3 | **D4 = 显式负样本条件化** | Arbor 的负约束被动（pruned 节点）；无人做主动检索式负样本库 | 失败假设编码入库，ideation 时检索相似失败先例主动约束 |
| 4 | **D2 = 种群 × 树混合拓扑** | AlphaEvolve 有 island 无语义；Arbor 有树无多样性机制 | island 内长假设树、island 间周期性迁移 insight |
| 5 | **D5 = 信息价值显式建模** | Arbor 的 Select 由 LLM 隐式权衡 | 把"该实验的信息增益/成本"显式建模（贝叶斯实验设计 × 假设树），与 #2 的 surrogate 联动 |

---

## 7. 自研系统定位 Checklist

> 对自研 AutoResearch 系统，逐维度确认当前取值与目标取值：

| 维度 | 当前取值（待填） | 目标取值 | 与最近邻的差距 |
|---|---|---|---|
| D1 搜索对象 | ？（广告召回 pipeline / 算法组件？） | | |
| D2 状态拓扑 | ？ | | |
| D3 记忆语义层级 | ？（实验日志 + 人类经验的双层管理 → 建议对标 L3/L4） | | |
| D4 提议算子 | ？（LLM 生成提案 → 建议加证据条件化 + 负样本约束） | | |
| D5 前沿控制 | ？（"指导下一步尝试什么"是终极目标 → 建议对标 coordinator Select 的信息价值语义） | | |
| D6 证据准入 | ？（10h+ 真实评估 → surrogate dev + 真实 gate） | | |
| D7 执行模型 | ？ | | |

填写建议：先确定 D1 和 D6（受业务约束最强），再决定 D3 的层级（决定系统上限），最后 D2/D4/D5/D7 围绕 D3 选型。

---

## 8. 参考文献

**核心论文**
- Arbor: Jin et al. Toward Generalist Autonomous Research via Hypothesis-Tree Refinement. arXiv:2606.11926, 2026. https://arxiv.org/abs/2606.11926 （代码：https://github.com/RUC-NLPIR/Arbor）

**受控对照**
- Codex: OpenAI, 2025
- Claude Code: Anthropic, 2025

**树搜索 / 算子化 MLE agent**
- AIDE: Jiang et al., 2025
- AIRA-dojo: Toledo et al., 2025
- ML-Master: Liu et al., 2025b / ML-Master 2.0: Zhu et al., 2026

**端到端研究 pipeline**
- AI-Scientist: Lu et al., 2024 / v2: Yamada et al., 2025 / Chen et al., 2026a
- Agent Laboratory: Schmidgall et al., 2025

**多 agent / 层级系统**
- AIBuildAI: Zhang et al., 2026
- R&D-Agent: Yang et al., 2025
- LoongFlow: Wan et al., 2025
- InternAgent: Team, 2026
- MARS: Chen et al., 2026b
- Leeroo (KAPSO): Nadafian et al., 2026
- Famou-Agent 2.0: Li et al., 2025

**进化计算线**
- FunSearch: Romera-Paredes et al., 2024
- AlphaEvolve: Novikov et al., 2025

**搜索对象扩展**
- AutoHarness: Lou et al., 2026 / Meta-Harness: Lee et al., 2026 / AHE: Lin et al., 2026
- DataMaster: Du et al., 2026

**长程 agent 记忆**
- Reflexion: Shinn et al., 2023
- Generative Agents: Park et al., 2023

**Benchmark**
- MLE-Bench: Chan et al., 2024 / MLAgentBench: Huang et al., 2024 / RE-Bench: Wijk et al., 2024 / PostTrainBench: Rank et al., 2026 / NanoGPT speedrun: Zhao et al., 2025

---

*文档生成日期：2026-08-05。Arbor 为 living technical report，实验范围可能继续扩展，建议定期回看 arXiv 更新。*
