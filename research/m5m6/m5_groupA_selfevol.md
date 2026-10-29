# M5 Memory 定稿依据（A 组）：自进化 / RSI 系统中的记忆设计深挖

调研日期：2026-08-25。范围：DGM、AIDE²/AIDE、MetaSkill-Evolve、prime-agent、ShinkaEvolve、EvolveNet、MOSS（背景已知，做二轮源码/论文级补充）；新增：AI-Scientist-v2、Agent Laboratory(+AgentRxiv)、IBM TSM（Trajectory-Informed Memory Generation）、MemRL、CODESKILL。
标注约定：【原文】= 一手来源直接证据；【推断】= 分析者判断；【背景】= 沿用 lead 提供的已知结论。

---

## 1. 逐系统五维拆解（表示 / 写入 / 读取 / 更新遗忘 / 作用域）

### 1.1 DGM（Darwin Gödel Machine, arXiv:2505.22954）

- **表示**：记忆 = 无界 agent archive，每个条目是一个完整 agent 基因型：`archive/<child_id>/code/`（完整源码）+ `performance.txt`（基准分）+ 谱系元数据（parent、children 计数）。【背景】+【原文：github.com/mmtmn/Darwin-Godel-Machine README「Each subdirectory contains: the full working code of the agent; its performance score」】。注意：第三方复现 lemoz/darwin-godel-machine 还实现了论文的父代选择规则——`sigmoid(performance) × 1/(1+children)` 探索奖励，categorical 采样【原文：repo README Archive Management 节】。
- **写入**：自修改循环产出 child agent → 基准评测 → 通过 validity 检查（能解析、能跑、保持工具能力）即入档。准入门 = 经验验证而非证明（这是 DGM 对 Gödel machine 的核心改造）；无淘汰，archive 单调增长（"unbounded, per the paper"【原文：lemoz repo】）。
- **读取**：读的不是"经验文本"而是"可分叉的祖先"——parent selection 按性能×新颖度采样；agent 自我诊断时读自己的执行日志/反馈。无语义检索。
- **更新/遗忘**：不更新旧条目（append-only），遗忘靠选择压力而非删除。context collapse 防护 = 无（不需要——记忆不进 context，进的是代码本身）。
- **作用域**：全局 archive，跨 run 即整个进化过程本身。无任务局部层。
- **利弊**：利——记忆即制品（artifact），天然可执行、可回滚（任何祖先可重新分叉）、谱系可审计；败——(a) 记忆粒度=整个 agent，无法表达"局部教训"，同类 bug 在不同分支反复犯；(b) 依赖可自动评分的 benchmark，评测被 hack 时整个 archive 被污染且无检测机制；(c) 无压缩，长程进化后检索/选择退化为纯标量打分，丢失"为什么有效"。**失败场景：评测信号稀疏或不可验证的开放研究任务。**

### 1.2 AIDE / AIDE²（WecoAI/aideml；AIDE² = AI-Scientist-v2 内部树搜索的进化轨迹）

**二轮源码证据（WecoAI/aideml `aide/journal.py`）**：
- **表示**：`Journal` = `list[Node]` 的树。每个 `Node` 是结构化 dataclass：`code, plan, step, id, ctime, parent, children, _term_out, exec_time, exc_type, exc_info, exc_stack, analysis, metric: MetricValue, is_buggy`。【原文：journal.py L19-60】——即"代码+计划+执行结果+LLM 事后分析+标量指标"五元组，**非自由文本、非 embedding**。
- **写入**：每步执行后 `absorb_exec_result()` 吸收终端输出与异常；`is_buggy` 由 agent 自判（`exc_type is not None` 或无有效 metric 时恒为 True）。【原文：journal.py `is_buggy` 注释】准入门=无门禁，全部节点入 journal；错误也被保留为可调试素材。
- **读取**：`generate_summary(include_code=False)` 只遍历 `good_nodes`，输出 `Design/Results/Validation Metric` 三段式摘要注入后续 prompt——**读取键 = 结构位置（树）× 质量过滤（good/buggy）× 指标排序（`get_best_node`）**，无语义检索。【原文：journal.py `generate_summary`】`stage_name` 属性（draft/debug/improve）与 `debug_depth` 决定下一步行为，是"结构化的情节索引"。
- **更新/遗忘**：节点不可变；遗忘是上下文层的——summary 默认不含 code、只含 good nodes，`trim_long_string` 截断终端输出。**AIDE₀（原始 AIDE）正是靠这套 L1 全历史运行；AIDE₈₅ 进化出的"压缩摘要+12 条 one-liner"是 L2 被进化出来的直接证据【背景】**。context collapse 防护 = `generate_summary` 的有损压缩 + buggy 节点默认不进摘要。
- **作用域**：任务局部（一次运行一个 journal）；跨任务迁移需人工复制。
- **利弊**：利——schema 极简、决策相关字段齐全（buggy/metric/parent），debug_depth 防止无限 debug 循环；败——(a) `is_buggy` 依赖 LLM 自判，误判的好方案会被永久排除出摘要（good_nodes 过滤是硬性的）；(b) metric 方向冲突仅 `logger.warning` 不纠错【原文：`_warn_on_direction_conflict`】；(c) 无语义检索，摘要随节点数线性增长，长任务下 prompt 膨胀——正是 AIDE₈₅ 要自己进化出压缩机制的原因。**失败场景：评测指标多方向/不可比、或失败原因超出 LLM 自判能力时。**

### 1.3 MetaSkill-Evolve【背景为主】

- 表示：L1 分支历史（轨迹）；L2 inspiration 检索条目；L3 元技能 `m` = 五元组（结构化 schema）。
- 写入：分支内自主沉淀 L1；元技能经进化/整合写入 L3。
- 读取：L2 为检索式（inspiration），跨分支传播靠 meta 层检索而非全量共享。
- 更新/遗忘：分支局部隔离天然防止全局污染；遗忘机制未见明确证据【推断：依赖分支淘汰】。
- 作用域：分支局部 + meta 检索传播——**"默认私有、按需广播"模型**。
- 利弊：利——隔离性好，坏经验不扩散；败——跨分支转移依赖检索质量，低频但关键教训可能永不被检索到；五元组 schema 的字段设计错误会系统性限制可表达的记忆类型。

### 1.4 prime-agent【背景为主】

- 表示：L1 轨迹 / L2 lessons（`/refine` 产物，自由文本）/ L3 executable skills（代码）。
- 写入：**证据门 + 快照回滚**——记忆变更须有证据支撑，失败可回滚到快照。这是所有调研对象中唯一显式实现"记忆写入事务性"的系统。
- 读取：按层注入；L3 可执行（直接调用）。
- 利弊：利——证据门直接对冲 Xiong et al. 2025 发现的 error propagation（错误经验被 agent 忠实复现）；败——证据门增加写入延迟与成本，且`/refine` 依赖人工/半自动触发，自主性差；三层间一致性（lesson 改了 skill 没改）需额外维护。**失败场景：证据本身被 reward hacking 污染时，证据门反而给假经验背书。**

### 1.5 ShinkaEvolve【背景为主】

- 表示：进化 archive（程序+指标）+ MetaSummarizer 周期性生成的 meta-recommendations（自由文本）+ SystemPromptEvolver 维护的系统提示。
- 写入：周期触发的 summarize（非每步）；prompt 本身作为可进化对象。
- 读取：meta-recommendations 注入后续采样上下文——**把"跨代经验"压缩成一段策略文本，是 L2 的周期 consolidate 形态**。
- 利弊：利——周期摘要显著控制 context 膨胀，prompt 进化让"记忆使用方式"本身可改进；败——摘要周期是超参，周期过长丢失即时教训、过短则摘要质量差；meta-recommendations 自由文本无 schema，难以做冲突检测与回滚。**失败场景：适应度景观快速变化时，滞后摘要会持续推荐过时策略（staleness）。**

### 1.6 EvolveNet【背景为主】

- 表示：L1 本地轨迹（不出域）；L2 行为证据 F/B 集（失败/成功行为片段）；L3 = 共享 harness（可执行知识）。
- 写入：本地自主；跨界仅允许"行为证据"级抽象通过。
- 读取：F/B 集作为正负样例注入；harness 直接执行。
- 作用域：**隐私/域隔离优先**——跨域迁移的货币是行为证据而非原始轨迹。
- 利弊：利——多租户/多域场景下唯一明确的"什么可以出域"设计；败——F/B 抽象损失上下文，证据片段脱离原始任务后可能误导；harness 共享意味着一个被污染的可执行知识影响所有域（单点故障）。

### 1.7 MOSS【背景】

- 纯 L1 fresh-start，无跨 batch 沉淀。**作为对照组的价值：证明"无记忆基线"在某些任务上不差，从而隔离出记忆设计的真实增益**；同时说明当任务间同构性低、或跨 batch 经验的信噪比差时，无记忆优于坏记忆（呼应 Xiong et al. 的 misaligned replay 发现）。

---

## 2. 补充调研

### 2.1 AI-Scientist-v2（SakanaAI/AI-Scientist-v2, 2025-04）

- **表示**：树搜索组件直接构建于 AIDE 之上【原文：README Acknowledgement「The tree search component ... is built on top of the AIDE project」】，即继承 §1.2 的 Journal/Node schema；外加 idea JSON（`--load_ideas`）与 LaTeX 论文稿作为阶段产物。
- **写入**：BFTS（best-first tree search）逐节点扩展；无独立的"经验写入"步骤——记忆=树本身。
- **读取**：best-first 按 metric 扩展；**无跨 run 记忆**——每次实验从头建树，无 lessons 库、无跨实验检索。【原文：README 全流程描述中无任何 memory/experience 组件】【推断：这是 v2 相对 DGM 的明显回退——放弃跨实验积累换取单任务树搜索深度】
- **更新/遗忘**：节点不可变；树搜索的剪枝即遗忘。
- **作用域**：实验局部。
- **利弊**：利——复用 AIDE 验证过的 schema，工程成本低；败——同一 ideation→experiment 管线反复运行时重复犯同类错误（无跨 run 学习），单实验成本 $15-20【原文：README FAQ】使"重复犯错"代价高昂。**失败场景：需要多轮迭代同一研究线时。**

### 2.2 Agent Laboratory / AgentRxiv（arXiv:2501.04227 / 2503.18102）

- **表示**：阶段化工作流（lit review→plan→data→experiments→report），各 agent 间传递的是对话历史+产物文件；`state_saves` checkpoint 目录【原文：README Tip #3】= 唯一的持久记忆，形式为 pickled 状态。AgentRxiv 增加**跨 lab 的论文级共享记忆**：agent 上传/检索彼此的 PDF 研究成果。
- **写入**：子任务完成自动 checkpoint；AgentRxiv 上传由 agent 完成论文后触发。
- **读取**：checkpoint 用于断点恢复（非经验检索）；AgentRxiv 用搜索查询检索论文——**检索单位=整篇论文，键=文本查询**。
- **更新/遗忘**：无显式机制。
- **作用域**：run 局部 + AgentRxiv 全局（论文粒度）。
- **利弊**：利——checkpoint 使长管线可恢复，AgentRxiv 是最朴素的"多智能体累积科学"记忆层；败——run 内无经验沉淀（mle-solver 的 top programs & results 只在 run 内循环【原文：README 架构图】），跨 run 只有论文这种极粗粒度；论文检索无质量门（无引用/复现验证）。**失败场景：agent 从 AgentRxiv 检索到错误结论的论文并无验证地 build upon——错误以出版物形式固化传播。**

### 2.3 【2026 新工作】IBM TSM — Trajectory-Informed Memory Generation（arXiv:2603.10600, 2026-02, IBM Research；已应用于 CUGA 平台）

本次调研中**记忆工程最完整的 2026 系统**，五维全有显式设计【原文：arXiv:2603.10600v1 §3】：
- **表示**：结构化 tip schema：`(id, category∈{strategy,recovery,optimization}, content, purpose, steps[], trigger, negative_example?, app_context, task_category, priority∈{critical..low}, source_trajectory_ids[], timestamp)` + 双表示存储（embedding 用于语义搜索 + 结构化 metadata 用于过滤）。从同一条轨迹同时生成 domain-specific 与 generic 两级 tip。
- **写入**：离线三阶段管线——Trajectory Intelligence Extractor（语义解析思维类型：analytical/planning/validation/reflection/self-correction）→ Decision Attribution Analyzer（因果归因：immediate/proximate/root cause + contributing factors）→ Contextual Learning Generator（三类 tip）。**无 ground-truth 标签时由 agent 自反思信号推断结果**。写入门禁 = Phase 2 consolidation：子任务描述泛化（实体抽象/动作归一/上下文剥离）→ 层次聚类（阈值~0.85）→ LLM 合并去重。
- **读取**：两策略——(a) 余弦检索 τ∈[0.5,0.7] + top-k∈[5,10]；(b) LLM-guided selection（多一次调用，做 metadata 过滤+类别优先级）。注入格式为 prompt 中 task context 之后、agent instructions 之前的 guidelines 段，含 `[PRIORITY:HIGH]` 等可扫读标记。预算=top-5。
- **更新/遗忘**：冲突解决用 outcome metadata——**成功轨迹的 tip 优先于失败轨迹、recovery tip（已验证的纠正模式）优先于预防性建议**【原文：§3.2.3】；合并后重写 canonical cluster description 并重新 embed。
- **作用域**：全局记忆库，task-level 与 subtask-level 双粒度共存；subtask 抽象是跨任务迁移的关键机制。
- **实验证据**【原文：§4，AppWorld】：subtask tips + LLM 检索：held-out SGC +14.3pp（难任务 +28.5pp，+149% 相对）；**top-3 过严限制会使总分跌破基线（−2.9pp TGC）——"检索不足比不检索更糟"**；τ=0.6 是甜点；粒度决定 TGC、检索策略决定 SGC；简单任务注入 tip 有轻微干扰（train D1：100%→94.4%）。
- **失败场景**：(a) 无 ground truth 且 agent 自评偏差大时，错误归因被写入并带 provenance 背书；(b) 聚类阈值 0.85 是手调的，跨域部署需重调；(c) 只学"已有轨迹里发生的事"，无法学反事实。

### 2.4 【2026 新工作】MemRL（arXiv:2601.03192, ICML 2026, SJTU/MemTensor 等）

- **表示**：**Intent-Experience-Utility 三元组** `(z, e, Q)`——intent 为 embedding 键，experience 为 LLM 摘要的 high-level script（成功）或 reflection（失败，含 ROOTCAUSE/PATTERN TO AVOID/CORRECT APPROACH 三段【原文：App. I 模板】），Q 为标量效用。语义与效用显式分列。
- **写入**：每条轨迹结束后 LLM 摘要写回 `(z, e_new, Q_init=0)`；**无人工门禁，但 Q 值本身是后置质量门**——坏经验会被环境奖励自然压低检索概率而非删除。
- **读取**：Two-Phase Retrieval：Phase A 余弦相似度召回 top-k1（阈值 δ 取数据集内任务相似度分布的 top-20% 分位【原文：App. E.2】）；Phase B 按 `(1−λ)·sim + λ·Q`（z-score 归一，λ=0.5 最优【原文：Fig. 5】）选 top-k2。注入格式区分成功/失败记忆块（"SUCCESSFUL EXPERIENCES / FAILED EXPERIENCES (Avoid these mistakes)"）。理论证明该打分等价于带语义 KL trust-region 的变分最优检索策略【原文：App. A.4】。
- **更新/遗忘**：Monte Carlo 更新 `Q ← Q + α(r − Q)`（α=0.3），收敛性与方差界有定理保证【原文：Thm A.1】；遗忘率 FR=0.041 vs MemP 0.051；去掉归一化+相似度门 FR 升至 0.073【原文：§5.4.2】——**归一化+门控就是 context collapse 防护**。
- **作用域**：全局 memory bank；跨模型迁移实验：Gemini-3-pro 训练的 bank 直接给 Qwen3-235B 用，0.150→0.531（3.5×）【原文：Table 5】；跨任务合并几乎无干扰（OS∪DB：−0.004）【原文：Table 6】。
- **失败场景**：(a) **reward hacking——论文自承"maliciously injected sample could rapidly diffuse pollution... causing agent collapse"【原文：App. G.4】**，且只更新被注入 context 的记忆，credit assignment 在多记忆共注时含糊【原文：§6 Limitations】；(b) 任务相似度低时退化为单任务反思（HLE 上跨任务无增益【原文：Table 3】）；(c) 基础模型太弱时成功轨迹太少，Q 估计被噪声主导【原文：App. E.4 no-signal 讨论】。

### 2.5 【2026 新工作】CODESKILL（arXiv:2605.25430, 2026-05）

- **表示**：多粒度 procedural skills（可执行/半结构化），skill bank 维持**稳定大小**（不显式遗忘但有容量控制）。
- **核心创新**：**把 skill 提取与 skill-bank 维护本身做成可学习的管理策略**，用 RL 训练——hybrid reward = 密集 rubric 式 skill 质量反馈 + 稀疏的下游冻结 agent 可验证执行反馈【原文：abstract】。
- **结果**：EnvBench / SWE-Bench Verified / Terminal-Bench 2 平均 pass rate 比无 skill +9.69，比最强 prompt/memory 基线 +4.01。
- **意义与失败场景**：把"写什么/何时更新/何时淘汰"从手工启发式提升为可优化对象，是目前唯一对记忆管理策略做 RL 的工作【推断】。风险：管理策略的过拟合——在训练分布上学到的保留/淘汰偏好可能系统性排斥新颖但低频有用的经验；且 rubric 评审本身是 LLM，存在被 skill 文本"讨好"的空间。

---

## 3. 跨系统利弊矩阵（何时失败）

| 系统 | 核心记忆主张 | 首要失败模式 |
|---|---|---|
| DGM | 记忆=可分叉基因型 archive | 评测不可验证/被 hack；教训粒度太粗 |
| AIDE(²) | 结构化树 journal + 有损摘要注入 | `is_buggy` 自判错误不可逆；摘要线性膨胀 |
| MetaSkill-Evolve | 分支私有 + meta 检索传播 | 低频关键教训永不被检索 |
| prime-agent | 证据门 + 快照回滚 | 证据被污染时门禁背书假经验；自主性弱 |
| ShinkaEvolve | 周期 meta 摘要 + prompt 进化 | 摘要滞后（staleness）推荐过时策略 |
| EvolveNet | 行为证据出域 + 共享 harness | harness 单点污染全域；F/B 脱离上下文误导 |
| MOSS | 无跨 batch 记忆（对照） | 任务同构时的积累增益全部放弃 |
| AI-Scientist-v2 | 单 run 树搜索，无跨 run | 高价实验重复犯错 |
| Agent Lab/Rxiv | checkpoint + 论文级共享 | 无验证的论文级错误传播 |
| IBM TSM | 三类型结构化 tip + 因果归因 + 聚类合并 | 无 GT 时归因错误带 provenance 背书；简单任务受干扰 |
| MemRL | (intent, exp, Q) 三元组 + 值感知检索 | reward hacking 快速扩散；低相似度退化为 Reflexion |
| CODESKILL | 记忆管理策略本身可 RL 学习 | 管理策略过拟合训练分布 |

共性失败面（多系统独立证据）：**(1) 检索不足/错检比无记忆更差**（IBM TSM top-3 实验 −2.9pp；Xiong et al. 2025 的 misaligned replay）；**(2) 质量门缺位时错误经验被忠实复现并扩散**（MemRL App. G.4、prime-agent 证据门的存在理由）；**(3) 摘要/压缩必然引入滞后与失真**（ShinkaEvolve、AIDE 摘要膨胀问题）；**(4) 写入侧的自评偏差不可逆**（AIDE `is_buggy`、IBM 无 GT 归因）。

---

## 4. M5 设计决策清单（五决策点 × 可选值 × 已观测证据）

### D1 表示格式
| 可选值 | 已观测实例 | 证据要点 |
|---|---|---|
| 自由文本 lesson | prime-agent L2、ShinkaEvolve meta-recommendations | 灵活但无冲突检测、难回滚 |
| 结构化 schema | IBM TSM tip 13 字段、MemRL (z,e,Q)、AIDE Node、MetaSkill 五元组 | 支持过滤/优先级/归因；schema 设计错误系统性限制表达 |
| 可执行代码/制品 | DGM archive、prime-agent L3、EvolveNet harness、CODESKILL skills | 天然可验证可回滚；粒度粗或单点污染 |
| embedding 键值 | MemRL intent、IBM TSM 双表示 | 检索键；必须与标量/结构化字段组合（纯语义检索被 MemRL 证明次优）|
| 原始轨迹 | MOSS L1、MemRL e 的底层 | 保真但不可直接复用，需摘要层 |

**证据结论**：双表示（embedding + 结构化 metadata）+ 类型分级（strategy/recovery/optimization 或 F/B）是当前最强配置（IBM TSM、MemRL 双向验证）。

### D2 写入路径
| 可选值 | 实例 | 证据要点 |
|---|---|---|
| 全量自主写入（无门禁） | AIDE journal、MOSS | 简单；错误进库（AIDE 靠 good_nodes 过滤补救于读取侧） |
| 周期性 summarize | ShinkaEvolve MetaSummarizer、IBM Phase 2 合并 | 控制膨胀；引入滞后 |
| 命令/触发式 refine | prime-agent `/refine` | 质量高；自主性弱 |
| 证据门 + 回滚 | prime-agent | 唯一直接对冲 error propagation 的写入设计 |
| 后置效用门（写入宽松、读取侧惩罚） | MemRL（Q 值压低而非删除） | 有收敛保证（Thm A.1）；依赖可靠 reward |
| 因果归因后写入 | IBM TSM Decision Attribution | 产生 provenance；无 GT 时归因可能错 |
| 管理策略可学习 | CODESKILL | 唯一 RL 化写入/维护；过拟合风险 |

### D3 读取路径
| 可选值 | 实例 | 证据要点 |
|---|---|---|
| 结构位置（树/谱系） | AIDE、DGM parent selection | 决策相关性强；无语义泛化 |
| 语义相似度（cosine+阈值） | IBM cosine τ≈0.6、MemRL Phase A | τ 是敏感超参（IBM：0.5 纳噪、0.85 漏同义） |
| LLM-guided 选择 | IBM TSM | SGC +7.2pp over cosine；多一次调用 |
| 相似度×效用混合 | MemRL Phase B（λ=0.5 最优，倒 U） | 有变分最优性证明 |
| 注入位置/格式 | IBM：task 后 instructions 前、优先级标记；MemRL：成功/失败分块 | top-k 过小可跌破基线；k1=5,k2=3 倒 U 甜点 |
| 预算 | IBM top-5；AIDE 摘要截断 | 无统一最优，需按任务难度调 |

### D4 更新/遗忘
| 可选值 | 实例 | 证据要点 |
|---|---|---|
| append-only + 选择压力 | DGM、AIDE | 永不遗忘，防 collapse 靠读取侧过滤 |
| EMA 效用更新 | MemRL Q←Q+α(r−Q) | 有方差界证明；credit assignment 含糊 |
| LLM 合并/冲突解决 | IBM Phase 2（成功>失败、recovery>预防） | 需要 outcome metadata 才可靠 |
| 快照回滚 | prime-agent | 唯一事务性设计 |
| 容量控制/稳定大小 | CODESKILL | 淘汰策略本身可学习 |
| 无遗忘（对照） | MOSS | 低信噪比环境下坏记忆不如无记忆 |

### D5 作用域
| 可选值 | 实例 | 证据要点 |
|---|---|---|
| 任务/run 局部 | AIDE、AI-Scientist-v2 | 隔离最好；零迁移 |
| 分支局部 + meta 传播 | MetaSkill-Evolve | 默认私有、按需广播 |
| 域隔离 + 证据出域 | EvolveNet | 隐私优先；抽象损失 |
| 全局共享 | IBM、MemRL | 迁移增益大（MemRL 跨模型 3.5×）；污染面最大 |
| 跨模型/跨 agent | MemRL Table 5/6、AgentRxiv | 记忆库可作可移植知识资产；需质量门 |
| 多粒度并存 | IBM task-level + subtask-level | subtask 抽象是跨任务迁移的关键机制 |

---

## 5. 对 M5 的直接建议（推断）

1. 表示：采用**结构化 tip/skill schema + embedding 双键**，至少区分 success/failure（或 strategy/recovery）两类——IBM 与 MemRL 独立收敛于此。
2. 写入：**宽进严读**（写入不做硬门，读取侧用效用/质量分惩罚）比硬证据门更适合自主系统；但保留 prime-agent 式快照以便污染后回滚（MemRL App. G.4 同样指出可清除性是污染后的唯一补救）。
3. 读取：**相似度召回 → 效用/质量重排**两段式，λ≈0.5 起步；预算 top-5 起步，严禁过小 top-k（IBM 负结果）。
4. 更新：EMA 效用（有理论保证）+ 周期 LLM 合并（控制膨胀）；冲突解决利用 outcome provenance。
5. 作用域：默认任务局部，跨任务迁移走 subtask/泛化描述层；跨 run 共享前过一道验证。

## 来源
- arXiv:2505.22954（DGM）；github.com/WecoAI/aideml `aide/journal.py`（AIDE 源码）；github.com/SakanaAI/AI-Scientist-v2 README；github.com/SamuelSchmidgall/AgentLaboratory README（+arXiv:2501.04227, 2503.18102）；arXiv:2603.10600v1（IBM TSM，全文 §1-6）；arXiv:2601.03192v2（MemRL，全文+附录）；arXiv:2605.25430（CODESKILL，abstract）；github.com/lemoz/darwin-godel-machine 与 mmtmn/Darwin-Godel-Machine（DGM 复现，旁证）。MetaSkill-Evolve / prime-agent / ShinkaEvolve / EvolveNet / MOSS 沿用 lead 背景，本轮未新增一手证据（标注【背景】）。
