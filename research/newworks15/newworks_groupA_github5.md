# Group A：五个 GitHub 新工作的九模块统一抽象分析

调研日期：2026（以 repo 主页与 README 实际内容为准）。九模块抽象：M1 Policy/Coordinator（选点控制）、M2 Operator（类型化研究动作）、M3 BudgetController、M4 Frontier/State（树/DAG/population）、M5 Memory（L1原始记录/L2洞见/L3方法知识）、M6 Knowledge、M7 Executor（role 同质/异质 × hypothesis 冻结/自由）、M8 Evaluator（标量→多指标+工件→+文本反馈→完整轨迹）、M9 AdmissionGate；X1 溯源审计、X2 人在环。六大数据类型：Candidate / ExecutorSpec / EvalRequest / EvalResult / EvidenceRecord / StateMutation。

标注约定：**[repo]** = repo 明确实现；**[推断]** = 分析者推断。

---

## 1. openresearch-cli（alphaXiv）

**一句话定位**：本地优先的 autoresearch CLI/仪表盘——把每个实验做成一个 git worktree/branch，在任意算力后端上并行驱动多个编程 agent（Claude Code / Codex / OpenCode）跑"文献调研→实验→分析"闭环。
**出处**：https://github.com/alphaXiv/openresearch-cli （Rust 实现，二进制 `orx`；245★，README + `src/`）。时间：活跃维护，README 含遥测/update 机制，属 2025-2026 代工具。

| 模块 | 对应实现 |
|---|---|
| M1 Policy | [repo] 用户给一个 goal，"Autoresearch — describe a goal and let the agent run autonomously toward it: proposing, launching, and analyzing experiments"。选点策略封装在被 skill 化的编码 agent 内（`orx install-skills` 把 OpenResearch skill 注入 Claude Code/Codex），**无独立的学习型选点控制器** |
| M2 Operator | [repo] 无显式类型化算子集；动作空间 = 底层编码 agent 的通用工具（编辑/运行/分析）+ orx 命令面（`create-experiment`, `exp run`, `query`, `chart`, `report`）。draft/improve/debug 等语义隐含在 agent 行为里 |
| M3 BudgetController | [repo] 弱。无显式预算/收敛控制器；并行度由 worktree 数决定，停止靠人或 goal 完成判断（推断） |
| M4 Frontier/State | [repo] **实验树**："every experiment is a git branch… The root is your baseline; children are variants measured against it, so lineage stays explicit"。拓扑=树，状态载体=git |
| M5 Memory | [repo] L1 = 本地 SQLite store + runs/logs/artifacts（`runs`, `logs`, `search-logs`, `artifacts`, `wandb` 命令）；L2/L3 语义层**无**（记忆层级：仅 L1） |
| M6 Knowledge | [repo] `lit`/`paper`：跨 alphaXiv、OpenAlex、bioRxiv 的全文文献检索；`/reproduce-paper`、`/paper-to-marimo` 流程 |
| M7 Executor | [repo] Executor = 外部编码 agent harness（Claude Code/Codex/OpenCode 可选），跑在 SSH/Slurm/K8s/Modal/HF 等算力上。**role=同质**（多个相同 agent 并行于不同 worktree），**hypothesis=自由**（agent 自主决定改什么） |
| M8 Evaluator | [repo] 评估带宽：**多指标+工件档**。runs 产生 logs/artifacts/wandb 指标，`query`/`chart`/`report` 做聚合分析；无自动文本评判，无轨迹级评估 |
| M9 AdmissionGate | [repo] 无显式准入门。实验与 baseline 的对比展示在树里，采纳/保留由人决定（推断） |
| X1 溯源 | [repo] **强项**：git branch/commit 即谱系；"remote launches push the exact branch first" 保证可复现 |
| X2 人在环 | [repo] 本地 dashboard + agent chat，人全程可介入；默认本地私有 |

**六数据类型**：Candidate≈experiment（git branch）[repo]；ExecutorSpec≈harness+model+compute 选择 [repo]；EvalRequest≈`exp run`/远程 launch [推断]；EvalResult≈runs 记录（logs/artifacts/metrics）[repo]；EvidenceRecord≈artifacts+SQLite 记录 [repo]；StateMutation≈git commit/branch 创建 [repo]。

**【装不下的机制】**：① "skill 注入"——把 orx 能力以 skill 形式装进第三方编码 agent，使**控制器本身可被任意外部 agent 驱动**（M1 外置化、可插拔）；② 计算后端即一等公民（SSH/Slurm/K8s/Modal/HF/Ray 统一 launch），九模块没有"ComputeFabric"维度；③ 本地遥测/隐私边界设计。这些主要是工程维度缺口，非算法缺口。

**启发**：① git worktree 作为 M4 状态载体 + X1 溯源是极低成本高可靠方案；② M6 文献检索应做成 CLI 一等命令而非 prompt 内行为；③ "agent chat 带全项目上下文" 是 X2 人与 M5 记忆交互的好范式。

---

## 2. prime-agent（PrimeIntellect）

**一句话定位**：自我改进的 RLM（Recursive Language Model）编码/研究 agent——持久 IPython REPL 为唯一控制环境，递归子 agent 为函数调用，"Continual Harness" 把 prompt/记忆/skill/子agent规格当作可精化的持久状态。
**出处**：https://github.com/PrimeIntellect-ai/prime-agent （MIT，基于 `pi-mono`/PRIME-RL 生态）。时间：2025-2026 代。

| 模块 | 对应实现 |
|---|---|
| M1 Policy | [repo] RLM 主循环本身即 policy："persistent Python control environment"中模型以代码决定下一步；`/goal` 保持跨轮目标；无独立选点器 |
| M2 Operator | [repo] 无研究动作类型化；动作空间=Python 代码（文件/shell/工具/子agent 都是代码调用）。类型化发生在 skill 层（可复用 workflow 打包为 skill） |
| M3 BudgetController | [repo] `/autonomous` "continues within configured turn, token, and time budgets and can run user-defined quality gates"；自动 compaction 控制上下文预算。明确的 turn/token/time 三预算 |
| M4 Frontier/State | [repo] 无搜索树/DAG；状态=持久 IPython kernel 状态 + harness 持久文件 + 会话快照（单线程轨迹，非分支搜索） |
| M5 Memory | [repo] **三层齐备的雏形**：L1=会话轨迹/kernel 状态（daemon 持久、可 reattach）；L2=`/refine` 沉淀的 "memories/supplemental prompts"（evidence-backed lessons）；L3=可执行 skills + subagent specifications（方法知识，且可执行）。记忆层级：**L1+L2+L3 明确分层** |
| M6 Knowledge | [repo] 无内置文献/外部知识库；靠通用工具（shell/网络）获取 |
| M7 Executor | [repo] `rlm(...)` 生成真实子 agent，并行/后台执行并程序化返回结果。**role=异质可选**（子agent规格是 harness 状态的一部分，可定制分工；默认同质副本），**hypothesis=自由** |
| M8 Evaluator | [repo] 评估带宽：**标量/自定义 gate 档**——autonomous 模式的 quality gates 只验证 gate 所查内容（"A passed gate checks only what that gate verifies"）；`/refine` 是 trajectory 级复盘但服务于自我改进而非候选评分（推断：文本反馈档部分存在） |
| M9 AdmissionGate | [repo] `/refine` 的准入语义："small, evidence-backed updates"，"never rewrites the immutable base system prompt, and recorded snapshots support rollback"——对**harness 自身变更**的准入门，而非对研究候选的准入门 |
| X1 溯源 | [repo] refinement history 记录 + 快照回滚 |
| X2 人在环 | [repo] TUI、attach/reattach、agent 间直接通信也允许人 steer；警告"非安全沙箱" |

**六数据类型**：Candidate≈无（不评估研究候选）[推断：无对应物]；ExecutorSpec≈subagent specifications + skill 描述 [repo]；EvalRequest/EvalResult≈quality gate 调用与结果 [repo，弱]；EvidenceRecord≈refinement 的 evidence 记录与快照 [repo]；StateMutation≈harness 状态更新（版本化、可回滚）[repo]。

**【装不下的机制】**：① **Harness-as-state / 自我改进环**：被优化对象不是研究候选而是 agent 自身的操作手册（prompt/memory/skill/subagent spec），九模块抽象中 M5/M7 是"被 M1 使用"的，而这里它们是**被 M1 改写**的——元层缺口；② RLM "prompt-as-a-variable / context 即变量" 编程模型，把上下文管理变成一等编程操作；③ daemon/heartbeat/schedule 的时间维度（agent 可被定时器重新进入）；④ agent-to-agent 直接通信（去中心化的多 agent 编排，不经过 M1 路由）。

**启发**：① M5 的 L2/L3 写入需要一个独立 AdmissionGate（`/refine` + 快照回滚正是"记忆变更的准入控制"）；② "immutable base prompt + 可精化 supplemental 层" 是安全的自我改进分层，值得移植到 Operator/Policy 的自我保护；③ 预算控制显式三件套（turn/token/time）+ 质量门可直接借鉴为 M3 规范。

---

## 3. Argus（lbx154）

**一句话定位**：自进化多 agent 研究运行时——固定四角色管线 `Manager → Planner → Engineer ⇄ Reviewer`，执行与评审分离，项目可从"最近验证位置"断点续跑、7×24 自治。
**出处**：https://github.com/lbx154/Argus （Preview v0.1.1；188★；附技术报告 arXiv:2608.05144）。时间：2026（README 有 2026-08 微信群有效期）。

| 模块 | 对应实现 |
|---|---|
| M1 Policy | [repo] **Manager**："Interprets operator intent, selects the workflow, and owns stage transitions"——显式工作流选择与阶段转移控制 |
| M2 Operator | [repo] 无通用研究算子类型化；但 **Vertical** 机制允许领域自定义 "stages, tools, evidence requirements, and completion standards"——算子/阶段是可扩展的领域定义（推断：类型化在 Vertical 层） |
| M3 BudgetController | [repo] 无显式预算/收敛控制器；长时运行靠 checkpoint + resume（"stops, resumes, survives a runtime replacement, and continues from its latest verified position"） |
| M4 Frontier/State | [repo] 单项目阶段状态机（非树/population）；状态=tasks/checkpoints/decisions，跨会话与运行时升级存活 |
| M5 Memory | [repo] "Persistent state: Tasks, checkpoints, decisions, **Skills**, and evidence survive sessions"。L1=任务/检查点/证据；L3=Skills（可复用方法）；L2 洞见层不明确（记忆层级：**L1+L3**） |
| M6 Knowledge | [repo] 无内置外部知识检索；靠 Engineer 的"real tool use"（files/terminals/experiments/APIs） |
| M7 Executor | [repo] **role=异质**（四固定角色，权责分明）；**hypothesis=自由**（Engineer 自主实现；Planner 定义任务与所需证据，部分约束方向）。后端可换：Copilot CLI/Pi/Codex/Claude Code/OpenCode/Grok Build |
| M8 Evaluator | [repo] **Reviewer 独立评审**："Independently checks correctness, evidence, limitations, and completion"——评估带宽：**文本反馈+证据工件档**（判断以自然语言+evidence 检查形式给出；非标量 leaderboard） |
| M9 AdmissionGate | [repo] **Reviewer 判决即准入**："normal rounds end with a Reviewer judgment"；只有通过验证的进度才成为新的 resume 位置（"verified progress"） |
| X1 溯源 | [repo] decisions/evidence 持久化 + "inspectable artifacts" |
| X2 人在环 | [repo] 强：terminal cockpit、Web UI、Telegram/飞书机器人（`/nudge`, `/backlog`）、安装契约要求 sudo/登录前人工批准 |

**六数据类型**：Candidate≈无显式候选对象（产出是 artifacts）[推断]；ExecutorSpec≈backend+role prompt 配置 [repo]；EvalRequest≈Planner 定义的 "evidence it must produce" [repo]；EvalResult≈Reviewer judgment [repo]；EvidenceRecord≈持久 evidence/decision 记录 [repo]；StateMutation≈checkpoint/阶段转移 [repo]。

**【装不下的机制】**：① **执行-评审的制度性分离**（separation of execution and judgment）作为运行时宪法——M8/M9 不只是组件而是**权限结构**（Reviewer 有独立权威）；② "runtime replacement 可存活"：状态与外底层 agent CLI 解耦，换后端不丢进度——Executor 热替换；③ Vertical 领域垂直化框架（领域自定义完成标准=领域化 M8/M9）；④ 手机/Telegram/飞书作为人在环界面（X2 的渠道维度）。

**启发**：① M9 应设计为有独立权威的角色而非流水线末尾的函数——"从最近验证位置续跑"把 AdmissionGate 与 M4 状态绑定，是好范式；② Planner 为每个任务声明"必须产出的证据"（EvalRequest 与证据要求绑定）值得进框架；③ 后端可替换性说明 ExecutorSpec 应抽象到"外部 agent CLI"粒度。

---

## 4. OpenRSI / OpenMLE / Frontis-MA1（FrontisAI）

**一句话定位**：把"AI 改进 AI"工程化的全栈系统——以 MLE 为可执行试验场，围绕四个可训练原子算子（Draft/Improve/Debug/Crossover）统一 post-training（SFT+RL）与推理时长时程进化搜索（OpenMLE-Evo），训练出 meta-evolution 模型 Frontis-MA1。
**出处**：https://github.com/FrontisAI/OpenRSI （首个 release 2026-07-31；OpenMLE Sandbox 2026-08-09；论文《Frontis-MA1: Training an AI4AI Model towards RSI in MLE》；CC BY-NC 4.0）。这是五者中**算法上最贴近九模块抽象**的系统。

| 模块 | 对应实现 |
|---|---|
| M1 Policy | [repo] 双重：推理时=OpenMLE-Evo 的搜索控制（Inference Loop: Choose Operator → Select Parent → Generate → Execute → Evaluate&Rank → Update Database；scaffold 可换 Greedy/abMCTS/AIRA-EVO/OpenEvolve）；训练时=Frontis-MA1 模型本身学会选算子（RL 中 "Sample Operator" 由 policy model 输出）。**Policy 是被训练的对象** |
| M2 Operator | [repo] **四个类型化原子算子：Draft（从零生成）、Improve（带执行反馈 refine 父程序）、Debug（修复失败程序）、Crossover（重组两个父程序）**——"A unified action space for code evolution"，训练与推理共享同一动作空间 |
| M3 BudgetController | [repo] "12-hour per-task budget on one RTX 4090 capped at 12 GB VRAM"；OpenMLE-Evo-Max 提供异步多 GPU 搜索 profile。预算=时间墙+硬件约束 |
| M4 Frontier/State | [repo] **解树（solution tree）**："Operator-driven expansion of the solution tree"，边样式=算子（实线 Draft/虚线 Improve/点线 Debug/双线 Crossover）；底层 vendored AIRA-Dojo runtime；journal+checkpoint 持久化。拓扑=树（crossover 引入局部 DAG 性）[推断] |
| M5 Memory | [repo] **Program Database**："stores every executed program with its score & metadata"，父采样 F(p) 倾向 high reward / high children variance / rarely sampled；Evo-Max 加入 "benchmark-independent experience priors"（跨任务经验先验≈L3 方法知识）。记忆层级：**L1（全部程序+分数+元数据）+ L3（经验先验）**；L2 洞见层无显式实现 |
| M6 Knowledge | [repo] 无外部文献知识；知识来自执行反馈与训练数据（OpenMLE Tasks/SFT Traces，且对所有评测 benchmark 去重） |
| M7 Executor | [repo] **role=同质**（单一 35B policy 模型生成所有算子调用）；**hypothesis=自由**（无冻结假设，程序自由演化）。执行体=OpenMLE Sandbox（分布式代码执行+自动评测，CPU/GPU 调度） |
| M8 Evaluator | [repo] **标量档为主但通向训练**：沙箱执行得 score → score-to-reward 归一化（0–1）→ task-level adaptive bounds → entropic/group advantage（RL）；评估带宽=**标量+执行错误信号**（Debug 算子消费错误信息，故含部分文本反馈档） |
| M9 AdmissionGate | [repo] Evaluate & Rank + database 更新即准入；SFT 数据侧有 "Success & High-Score Rollout Filtering + Reward-Based Deduplication"（训练数据准入）；MLE-Bench medal/Match-SOTA 为最终选择 |
| X1 溯源 | [repo] journal/checkpoint/谱系树边带算子标注；训练数据对评测集去重（decontamination）是审计行为 |
| X2 人在环 | [repo] 无（全自治设计） |

**六数据类型**：Candidate=program（代码+score+metadata）[repo]；ExecutorSpec=算子类型+模型+沙箱配置（Hydra config）[repo]；EvalRequest=沙箱执行任务包 [repo]；EvalResult=score(+error)[repo]；EvidenceRecord=journal/checkpoint/rollout 记录 [repo]；StateMutation=database 更新+树扩展（边带算子类型）[repo]。**六类型全覆盖，是本组映射最完整的系统。**

**【装不下的机制】**：① **训练-推理同动作空间**（operators 既被 SFT/RL 训练又被搜索组合）——九模块把 M2 当作静态集合，这里 M2 本身是**可学习对象**，meta-evolution 维度装不下；② RL 奖励工程细节（task-level adaptive bounds、entropic advantages、父采样 F(p) 用 children variance 作内在动机）——M3/M8 无法表达"奖励塑形"层；③ Evo-Max 的"benchmark-independent experience priors"——跨任务迁移的 L3 记忆从哪来、如何注入，是 M5/M6 边界外机制；④ mechanism ladder（Evolution→Self-Evolution→Meta-Evolution→RSI）的**层级定位**本身是元框架。

**启发**：① 四算子（Draft/Improve/Debug/Crossover）可作为我们 M2 的最小完备算子集基准；② "训练数据对所有评测 benchmark 去重"应成为 X1 审计的标准条目；③ 父采样函数 F(p)（reward × 子代方差 × 稀少度）是 M1 选点策略的具体可借鉴公式；④ 评估带宽可以"恰好够训练用"——标量+错误信号即可驱动 RL，高带宽评估不是必要条件。

---

## 5. BigBang-v1（endless-frontier）

**一句话定位**：面向长时程搜索/编码/科研/AI 研究的 35B-A3B agentic 模型（基于 Qwen3.6-35B-A3B），repo 附带一个轻量通用 agent harness（`search`/`visit`/`code_exec` 三工具）与八个 benchmark 的严格评测协议。
**出处**：https://github.com/endless-frontier/BigBang-v1 （Apache-2.0；模型在 HF endless-frontier/BigBang-v1）。注意：**这是"模型+评测 harness"，不是 AutoResearch 系统**——九模块大多无对应物，这本身就是重要定位信号。

| 模块 | 对应实现 |
|---|---|
| M1 Policy | [repo] 无独立控制器；policy=模型本身的工具调用循环（OpenAI-compatible tool-calling loop，每条轨迹上限 500 次工具调用） |
| M2 Operator | [repo] 工具即动作：`search`（Serper/Google）、`visit`（Jina Reader + 目标条件化的摘要模型抽取）、`code_exec`（E2B 持久沙箱）。**无研究算子类型化**（无 draft/debug/crossover） |
| M3 BudgetController | [repo] 500 tool calls/轨迹；BrowseComp 用 5× discard-all + 第 5 次强制给答案；xbench Avg@5、FrontierScience Avg@30（重复采样即预算分配） |
| M4 Frontier/State | 无/默认。单条轨迹，无树/population；SWE-Bench Pro/SciCode 走各自官方 harness |
| M5 Memory | 无/默认。仅 per-item 持久 E2B 沙箱（轨迹内）；跨轨迹无记忆（记忆层级：**仅 L1-轨迹内**） |
| M6 Knowledge | [repo] **这是其核心**：`search`+`visit` 二级外部知识获取（搜索结果→Jina 读页→摘要模型按 goal 抽取），并做评测期 decontamination（拒绝显式针对 HF 的查询、过滤 huggingface.co/hf.co 结果、封禁 visit 这些域、reference answer 不出现在 agent 可见消息里） |
| M7 Executor | [repo] **role=同质**（单模型）；**hypothesis=自由**；执行体=E2B 沙箱+web 工具 |
| M8 Evaluator | [repo] 评测带宽：**标量档**——`--judge` 用独立 OpenAI-compatible judge 打分解析 score；SciCode pass@1 累积子问题 all-or-nothing；SWE-Bench 官方 evaluator |
| M9 AdmissionGate | [repo] 评测协议层面：discard-all 重试与强制作答规则；无研究候选准入 |
| X1 溯源 | [repo] 强：每条 JSON 记录含 benchmark/item/repeat/final response/tool-call count/**完整 conversation trajectory**；输出路径防覆盖；数据下载用 manifest+MD5 钉死；THIRD_PARTY.md 许可证审计 |
| X2 人在环 | 无/默认 |

**六数据类型**：Candidate≈最终 response [repo，弱]；ExecutorSpec≈endpoint/工具配置（.env）[repo]；EvalRequest≈runner 调用 [repo]；EvalResult≈JSON 记录+ judge score [repo]；EvidenceRecord≈完整轨迹 JSONL [repo]；StateMutation≈无 [无对应物]。

**【装不下的机制】**：① **评测期数据防污染策略**（decontamination policy：查询拒绝、域过滤、答案不可见）——这是"评估完整性"维度，九模块中 X1 只覆盖溯源，不覆盖"评估者与被评者的信息隔离"；② `visit` 的双阶段设计（原始抓取→独立摘要模型 goal-conditioned 抽取）——知识获取管线内部的**信息压缩层**，M6 无法表达其内部结构；③ Avg@K / discard-all 等**采样-聚合协议**作为预算与评分的耦合设计。

**启发**：① X1 应扩展出"评估卫生（evaluation hygiene）"子维度：decontamination、答案隔离、域封禁清单；② EvidenceRecord 存完整轨迹（含工具计数）应成为默认而非高档选项——他们即使在标量评测档也保留全轨迹；③ 对"模型即系统"类工作，九模块分析卡应允许大量"无/默认"，这正是区分 AutoResearch 系统与 agentic 模型的判别器。

---

## 跨系统小结（缺口信号聚合）

1. **元层机制是共同缺口**：prime-agent 的 harness 自我精化、OpenRSI 的"算子/策略可训练"、Argus 的运行时可替换——九模块把各模块当静态组件，而这批新工作都在**让某个模块本身成为优化对象**。建议框架加"元层标注"：每个模块标注 {固定 / 可配置 / 可学习 / 可自我改写}。
2. **评估完整性（evaluation hygiene）独立于 X1**：BigBang-v1 与 OpenRSI 都把 decontamination 当一等工程，建议从 X1 拆出。
3. **算子集收敛信号**：OpenRSI 的 Draft/Improve/Debug/Crossover 与用户抽象中的 draft/debug/improve/crossover 完全同构——M2 四算子已获独立印证。
4. **AdmissionGate 的两种形态**：Argus 是"有独立权威的评审角色"，prime-agent 是"对自身变更的证据门+回滚"——M9 应支持"对外候选"与"对内自改"两种准入。
5. **M5 分层被独立验证**：prime-agent（轨迹/lessons/executable skills）与 OpenRSI（program DB/experience priors）都自发形成 L1→L3 结构，但**L2 洞见层普遍最弱**（仅 prime-agent 的 `/refine` 明确实现）。
