# 九模块分析卡片 · Group C：MOSS (HKGAI) & PAST-Bench (Gen-Verse)

调研方式：web_open_url 打开 GitHub README、关键文档（MOSS `host-daemon/src/cli/moss_capability/evolution.md`）、PAST-Bench 论文 arXiv 摘要页、示例 `family.yaml` 源码。标注【原文】= 一手材料明确；【推断】= 分析者判断。

---

## 1. MOSS — Self-Evolution through Source-Level Rewriting in Autonomous Agent Systems

**一句话定位**：构建在 OpenClaw agent 框架之上的"源码级自我进化"系统——周期性扫描会话中的失败 turn 聚成 failure batch，调用外部 coding-agent CLI 重写自身 TypeScript 源码，用临时 trial worker 重放 batch 验证，经用户显式授权后做容器热替换（带健康探针回滚）。
**出处**：https://github.com/hkgai-official/Moss （HKGAI-official 组织）；Apache 2.0（openclaw/ 为 vendored MIT）。
**时间**：【原文未标注发布日期；推断】2025–2026 年新作（依赖 Claude Code CLI 2.x、GPT-5.4 等模型命名）。

### 九模块映射

| 模块 | 实现 |
|---|---|
| **M1 Policy/Coordinator** | 事件驱动而非主动选点：两个证据通道——(1) cron 周期 auto-scan（默认 30 min）扫描所有 agent 新会话中的 underperforming turns 入 batch；(2) 用户对话中显式 `moss evo flag`。用户对话驱动 start/stop/apply。进化内部是**确定性七阶段流水线**：`Locate → Plan → Plan-Review → Implement → Code-Review → Task-Evaluate → Verdict`（README Architecture 节，原文明确）。 |
| **M2 Operator** | 类型化动作即七阶段的阶段角色：定位、规划、规划评审、实现、代码评审、评估、裁决。Plan/Plan-Review 与 Implement/Code-Review 各自构成多轮 inner loop 直至批准或轮次上限。代码修改**委托给可插拔外部 coding-agent CLI**（Claude Code / Codex / DeepSeek-TUI / OpenCode，实现 `CodingAgentRunner` 4 方法接口）。无 crossover/种群操作。 |
| **M3 BudgetController** | 明确且精细：三档 depth tier（`shallow/standard/deep`），五个预算旋钮联动缩放：max_iter (3/5/8)、max_plan_rounds (1/2/3)、max_code_retries (0/1/2)、n_trials_per_task (2/3/5)、plateau_no_improvement_iters (1/2/3)（evolution.md 表格，原文明确）。收敛判据：Verdict 返回 `CONVERGED / NEED_MORE_WORK / FUNDAMENTAL_LIMIT_MODEL / FUNDAMENTAL_LIMIT_ARCHITECTURE`；plateau guard 防停滞；stop sentinel 安全停止。 |
| **M4 Frontier/State** | 本质是**单链迭代**（iter 1..N 顺序优化一个 batch），非树/DAG/population。状态机：`pending_evolution → running → converged/applied/failed`；"fresh-start-only"，restart 不续跑旧 iter（原文：completed iters NOT resumed，iter-level resume 计划 v2.7）。 |
| **M5 Memory** | **层级：仅 L1 原始记录为主**。持久化全部落盘于 `evo-loop-state/`：manifest.json、batch json、每 iter 的 plan-attempt-\*.md / code-attempt-\*.md、build log、finalize/summary.md、evolution-log.jsonl（事件流）。失败 batch 保留用于 post-mortem（"Failed batches stay on disk"）。**无 L2 洞见提炼、无 L3 方法知识库**——跨 batch 不积累可复用修复经验，每次进化 fresh-start。【推断】这是明显缺口。 |
| **M6 Knowledge** | 外部知识 = 外部 coding-agent CLI 所带的基础模型能力 + 被进化系统自身的全部源码。无检索式知识库、无文献/经验库接入。 |
| **M7 Executor** | **role = 异质**（Locate/Plan/Plan-Review/Implement/Code-Review/Task-Evaluate/Verdict 七个专门化角色，且支持 `agent_override` 按角色混用不同 provider/模型——mixed-provider runs，原文明确）；**hypothesis = 冻结**（每个 batch 修复目标由 failure evidence 事先确定，循环内不自由提出新假设，只迭代实现方案）。执行体为 ephemeral trial-worker 容器重放 batch。 |
| **M8 Evaluator** | **带宽档位：完整轨迹级**。验证方式 = trial workers 重放 failure batch（行为级 replay）+ build smoke-test + 容器 90s 健康探针。Verdict 阶段产出 scoring matrices（"diagnosis, plans, diffs, scoring matrices 均可审计"）。即既有工件（diff/build log）又有轨迹重放得分，属最高档。 |
| **M9 AdmissionGate** | 双重门：(1) 自动门——Verdict=CONVERGED 才允许 apply；(2) **人在环硬门**——swap 必须用户显式授权（"Do not invoke `moss evo apply` without the user's explicit go-ahead"，操作规则第 1 条）；(3) 运行时门——90s 健康探针失败自动 rollback。 |
| **X1 溯源审计** | 极强：全部中间工件落盘可读、evolution-log.jsonl 全事件流、archive/<batch_id>/ 归档失败 run、agent 对 evo-loop-state 只读（"read-only access by design"）。 |
| **X2 人在环** | 核心设计：用户拥有 depth tier 选择权（"the user owns this trade-off"，禁止 agent 静默选档）、flag 触发权、apply 授权权；用户投诉原文须原样保留为证据（规则 4）。 |

### 装不下的机制（九模块表达不了的设计）
1. **生产环境在线热替换语义**：进化对象不是离线候选解，而是**正在服务的 agent 自身容器**；apply = compose recreate + 健康探针 + 自动回滚，且"apply 后当前进程被新版替换，新实例收到 apply-complete 消息重新自我定位"——这是"系统进化即部署"的 DevOps 语义，九模块（面向搜索/研究流程）没有对应概念。
2. **失败证据的保真规则**："用户投诉措辞本身是重要证据，不得转述后再 flag"——证据链完整性约束，超出 M5 记忆分层范畴。
3. **自指身份连续性**：新旧版本间通过 webhook 交接自我认知（re-orient），属 agent 身份管理，无模块对应。

### 对我们框架的启发
1. **M3 预算档位化**：把 max_iter/plan_rounds/retries/trials/plateau 打包成 shallow/standard/deep 三档并要求显式选择，比单旋钮更可用；且把成本-时间 trade-off 显式交给人。
2. **AdmissionGate 三段式设计**（自动收敛门 → 人授权门 → 运行时健康门 + 回滚）是任何"会落地的"进化系统值得抄的安全范式。
3. **反面启发**：MOSS 的 M5 只有 L1 原始日志、fresh-start-only、无跨 batch 经验沉淀——验证了 L2/L3 记忆层与 iter-resume 正是差异化空间（其自己也在 v2.7  roadmap 里承认）。

---

## 2. PAST-Bench — Benchmarking the Foundations of Recursive Self-Improvement in Personal Agents

**性质**：**Benchmark（非系统）**，附带诊断驱动的参照框架 Hermes+。
**一句话定位**：评估"持久化个人 agent 是否真的因过去经验而变好"——用有序 fresh-session 任务族序列 + persistence 开/关配对控制 + 工件/轨迹级归因证据，把"分数提升"与"提升是否经由预期的 save→retrieve→update 通路"分开测量。
**出处**：https://github.com/Gen-Verse/PAST-Bench ；论文 arXiv:2608.04003（Xue, Ding, Shen, Wang, Yin, Wu, Chen, Wang Mengdi, Yang Ling；v1 提交 2026-08-04【原文】）。Apache 2.0。

### 能力维度（对应"它测试 agent 什么"）
四类能力、26 个 task family、204 个 episode【原文，README Benchmark Structure 与论文摘要一致】：

| 能力维度 | Families | Episodes | 测什么 |
|---|---|---|---|
| Memory | 5 | 41 | 保留稳定偏好、约束、先例（如 SM01 preference adoption、SM02 constraint retention、EP01 prior-case recall） |
| Procedural Reuse | 8 | 64 | 复用程序/技能（SOP bootstrap、latent rule induction、failure-to-rule） |
| Proactive Information Gathering | 6 | 48 | 行动前主动查先验上下文（发布决策跟进、oncall 交接查询等运维场景） |
| Update | 7 | 51 | 替换过期事实/规则/程序（fact correction、rule migration、exception pollution）——论文称 Hermes+ 在此类提升最强 |

### 评估协议设计（重点）
1. **任务族序列结构（以 SM01 的 family.yaml 为原文证据）**：每个 family 定义 `episode_order`：cold_baseline → learn_a（首次显式引入偏好）→ learn_b（表面变体强化）→ eval_near（近迁移，**移除偏好措辞**）→ eval_far（远迁移，更大表面漂移）→ 3 个 control。`history_plan` 用 anchor 分支：learn 段连续会话，eval 段从 anchor 分叉的 fresh session，control 段全新 session。
2. **配对控制（防"假提升"的核心）**：`control_set: [no_persistence, shortcut, wrong_mechanism]`——(a) 运行时消融关掉持久化（`--compare-no-persistence`），同 family 同接口跑 with/without evolve，取 delta；(b) shortcut 控制：答案线索本地可见，检验 agent 是否靠泄露而非记忆；(c) wrong-mechanism / no-local-clue 控制：必须真正依赖持久记忆才能得分。family.yaml 还写明 `false_positive_pattern`（"评估 prompt 重复偏好或泄露期望输出风格"）与 `expected_control_result`（关掉持久化后偏好一致行为应显著下降）。
3. **触发器强度分级（防过拟合/难度刻度）**：trigger_strength T1（隐含在笔记中须自行提取）→ T2（持久规则但无 save 措辞）→ T3（直接显式 save 指令）；`trigger_mixing_rule` 禁止同族混合 correction 触发器， sibling family 用于对比测量。
4. **双重计分（输出与归因分离）**：Primary outcome = **Task score / Mechanism score**；归因证据 = persistent artifacts（memories/skills/session 文件）+ runtime telemetry（memory write、skill use、session search、检索时机、update 事件）。论文关键发现【原文摘要】：headline gain 相同的 agent，其提升是否有预期通路证据可差异巨大——即分数与机制解耦。
5. **Judge 与可复现性**：LLM judge（默认 MiniMax-M2.7，config.yaml 固定 judge 模型）+ 确定性可评分工件；输出三件套 `sequence_results.json / sequence_summary.json / sequence_comparison.json`（含 delta）。
6. **实验矩阵**：7 个 base model（MiniMax-M2.7、GLM-5.1、Kimi K2.6、DeepSeek-V4-Pro、GPT-5.4 等）× 4 个 agent 框架（Hermes、Hermes+、nanobot、ZeroClaw，Agent Zero 无持久化后端单独跑）+ Hermes+ 五机制（Plan/Render/Route/Gate/Close）消融。
7. **Dev/test 划分**：【原文未见显式 dev/test split】；防过拟合主要靠 trigger_removal（eval episode 移除教学措辞）、near/far 迁移距离、三类 matched control、以及 family.yaml 中显式声明的 false_positive_pattern 约束。【推断】这是协议可加强点：任务族本身公开在 repo 中，长期有污染风险。

### 对 ZOO.md benchmark 接入策略与三层评估协议的启发
1. **接入策略**：PAST-Bench 以 CLI（`past-bench evolve --family ... --agent ... --compare-no-persistence`）+ adapter 模式接入外部 agent（agents/ 下已适配 4 个框架，实现 adapter 即可接入 ZOO）；接入时必须支持**持久化开/关的运行时消融**这一硬要求，否则无法出 delta 分。
2. **三层评估协议可直接对齐其三级证据**：L1 任务分（标量/多指标）↔ Task score；L2 工件检查 ↔ persistent artifacts（记忆/技能文件是否真实写入）；L3 轨迹审计 ↔ runtime telemetry（检索时机、update 事件）。其"Mechanism score 与 Task score 解耦报告"应成为我们协议的强制项，防止"分数涨了但通路不对"。
3. **任务族模板化**：family.yaml 的声明式字段（trigger_strength、episode_order、control_set、false_positive_pattern、must_demonstrate）是设计自家纵向评估任务族的高质量 schema，可直接借鉴。

### 装不下的机制
- 作为 benchmark 不直接适用 M1–M9；但注意其**Hermes+** 是个迷你系统：五机制 Plan/Render/Route/Gate/Close 对应 M2（类型化经验操作）+ M5（经验表示/路由/检索/更新，即 L1→L2 的管线化）。【推断】Hermes+ 本质是"经验生命周期"五阶段管线，与我们 M5 分层正交但互补。
- 真正的新机制信号：**"通路归因"作为一等评估对象**（提升是否经由 intended save→retrieve→update pathway），九模块里 M8 只描述评估带宽，未描述"归因正确性"这一维度——这是最该补的缺口。

---

## 附：一手来源清单
- MOSS README（github.com/hkgai-official/Moss）：七阶段流水线、provider 表、架构图、CLI 表
- MOSS `host-daemon/src/cli/moss_capability/evolution.md`：depth tier 预算表、操作规则 5 条、状态文件清单
- PAST-Bench README（github.com/Gen-Verse/PAST-Bench）：四维能力表、实验矩阵、输出三件套
- arXiv:2608.04003 摘要：26 scenarios/204 episodes、机制-分数解耦发现、Hermes+ 五机制
- `self-evolve-tasks-v2/memory_ability/SM01_preference_adoption/family.yaml`：episode_order、control_set、trigger 分级、false_positive_pattern 等协议字段
