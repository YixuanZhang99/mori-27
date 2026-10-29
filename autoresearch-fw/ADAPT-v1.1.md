# ADAPT-v1.1.md — 缺口适配开发规划（基于 15 个新工作的压力测试）

> 依据：`../docs/新增工作九模块映射表.md`（2026-08 调研，15 个工作：dgm / AIDE² / SEAL / MetaSkill-Evolve / EvolveNet / OpenRSI / Simple Baselines / prime-agent / argus / moss / PAST-Bench / BigBang-v1 / openresearch-cli / openevolve / shinkaevolve）。
> 当前进度基线：AIDE 复刻基本完成、Arbor 功能开发完成（未测试）。
> 本文性质：**规划增量，不是返工指令**。G1–G4 全部可以通过"加字段/加标注轴"吸收，现有 AIDE/Arbor 复刻代码不需要推翻。

---

## 0. 总原则：缺口分级 = 类型层 / 协议层 / 实践层

| 层级 | 含义 | 何时做 |
|---|---|---|
| **类型层**（改 core/types.py） | 加字段、加枚举，向后兼容（新字段都有默认值） | **立即**（ Arbor 测试前完成，成本最低） |
| **协议层**（改 Protocol/不变量） | M8 可靠性轴、X3 可见性、evolvability 元属性 | 里程碑间隙，随下个 milestone 一起 |
| **实践层**（新 recipe/新组件） | 最小基线 recipe、merge 算子、双层 loop | 排入 M3 或 M3.5，**不阻塞现有里程碑** |

---

## 1. G1 Candidate 层级化（最高优先级，类型层）

**发现**：dgm / AIDE² / SEAL / MetaSkill-Evolve / EvolveNet / prime-agent 六个系统把被进化对象从"任务解工件"上移为"求解器自身"（harness / skill / 验证器 / agent 代码库）。我们的 `Candidate` 目前只有 L0 语义。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 1.1 | `Candidate` 增加 `level: Literal["L0","L1","L2"] = "L0"`，默认 L0 → 现有代码零影响 | core/types.py | **P0 立即** |
| 1.2 | `Candidate` 增加 `verifier_ref: str | None = None`——当 agent 自写测试/验收标准时，验证器成为 Candidate 的显式组件（SEAL 教训：(π,T) 联合进化导致 verifier–deployment gap） | core/types.py | **P0 立即** |
| 1.3 | SPEC 补一段"L1+ 的评估语义"：评估一个 L1 Candidate = 让它跑 N 个任务/种子后聚合（嵌套/元评估），`EvalRequest` 增加 `nested: bool = False` 标注 | SPEC.md §Evaluator | P1 里程碑间隙 |
| 1.4 | 双层 loop（外环改内环 harness）**不做进框架内核**，做成 M3.5 的 recipe（AIDE²/dgm 复刻配方）；`ExecutorSpec` 增加 `level: int = 0` 字段预留跨层异质 | SPEC.md + 开发计划 | P2 M3.5 |

**验收**：types.py 改动后跑 M0 契约测试必须全绿（全字段有默认值，纯增量）。

## 2. G2 信息边界 / X3 可见性（类型层 + 协议层）

**发现**：SEAL 密封审计（只回 1 bit）、ShinkaEvolve/AIDE² public-private 双分数、EvolveNet 数据本地性、BigBang-v1 答案隔离——五个独立工作撞上同一维度："哪个模块能看见什么"是一等设计变量。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 2.1 | `EvalResult.metrics` 的 key 规范从 `{split}.{name}` 扩为 `{split}.{visibility}.{name}`（如 `public.dev.acc` / `private.dev.acc`）；visibility 缺省 = public，向后兼容 | SPEC.md + types.py 校验器 | **P0 立即**（改动小，赶在 Arbor 测试前） |
| 2.2 | SPEC 新增横切轴 **X3 Visibility/Trust Boundary**：M8 产出的每个指标带可见性；M1/M2 的 context 组装（M5.retrieve 出口处）强制执行 `forbidden_channels` 过滤——private 指标永不进入 Executor 可见上下文 | SPEC.md §X3 | P1 |
| 2.3 | 评估卫生（decontamination / 答案隔离 / 域封禁清单）从 X1 拆出归入 X3；Arbor 已有 `contamination.py` 参照，只需在 SPEC 中重新归口 | SPEC.md §X3 | P1 |
| 2.4 | M8/M9 增加"内生 vs 外生"标注：`Evaluator.exogeneity: Literal["exogenous","endogenous"]`；endogenous 时强制要求配外部审计门（SEAL 四条件：外生性/密封性/最小反馈/保守更新） | SPEC.md §M8/M9 | P1 |

**注意**：不要求现在就实现密封门——先让类型系统**能表达**，实现排 M3。

## 3. G3 模块可进化性标注（协议层，改动最小）

**发现**：MetaSkill-Evolve（M2/M3 可进化）、OpenRSI（算子策略被 RL 训练）、dgm（刻意冻结 exploration）、AIDE²（自我改进把自己的反作弊层改坏而不自知）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 3.1 | 每个模块 config 增加 `evolvability: fixed | configurable | learnable | self_modifiable`，默认 `fixed` | SPEC.md 配置体系 | **P0 立即**（纯标注） |
| 3.2 | CLAUDE.md 新增不变量：**self_modifiable 模块的任何变更必须走 StateMutation + X1 记录；M8/M9 的代码版本必须纳入谱系覆盖**（AIDE² 活例） | CLAUDE.md | **P0 立即**（文档改动） |
| 3.3 | CLAUDE.md 新增反模式禁令：禁止 agent 在无 X1 记录的情况下改写自己的评估器/准入门代码 | CLAUDE.md | P0 |

## 4. G4 评估可靠性轴 + 归因轴（协议层 + 实践层）

**发现**：Simple Baselines 证明 ~100 题小验证集使复杂 scaffold 选择退化为噪声（P(Shinka>IID RS)=0.49）；PAST-Bench 把 Task score 与 Mechanism score 解耦（分数涨≠通路对）；EvolveNet "gate 不 rank"。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 4.1 | M8 从单一带宽轴扩为三正交轴：**带宽 × 统计可靠性 × 归因正确性**；`EvalResult` 已有 `uncertainty` 字段，补 `n_evals: int = 1` 与可选 `attribution_evidence: str | None` | SPEC.md §M8 | P1 |
| 4.2 | **最小基线 recipe（IID RS / SCS）列为所有 benchmark 的强制对照组**——任何花哨 M1/M4/M5 配置必须证明相对退化配置的增量。这是 Simple Baselines 给整个框架的奥卡姆剃刀，实现成本极低（一个退化配置的 recipe YAML） | recipes/ + REPLICATION.md | **P1 里程碑间隙即可做，半天工作量** |
| 4.3 | M9 准入门规则补充："准入决策基于保守差分证据 + 回滚"为默认；merge 算子（EvolveNet 模式：输入 = delta + per-item 翻转证据）排入 M3 | SPEC.md §M9 + 开发计划 | P2 |

## 5. 结合当前进度的行动序列（建议给 Codex 的下一批指令）

```
当前：AIDE 复刻完成，Arbor 功能完成未测试

Step 0（现在，半天）：类型层增量
  - Candidate.level / verifier_ref（G1）
  - metrics key 的 visibility 段（G2.1）
  - evolvability 标注（G3.1）
  - 跑 M0 契约测试确认全绿 → 然后才开始 Arbor 测试

Step 1（Arbor 测试期，并行）：文档层增量
  - SPEC §X3、§M8 三轴、§M8/M9 内外生标注
  - CLAUDE.md 两条新不变量 + 一条新禁令
  - 不影响测试中的代码

Step 2（Arbor 测试通过后）：最小基线 recipe
  - IID RS + SCS 两个退化配置（G4.2）
  - 在 MLE-Bench Lite 上跑 AIDE-复刻 vs IID RS 的对照 → 第一份"增量归因"证据
  - 这同时解决 Arbor 未测试的评估可信度问题

Step 3（M3 规划时）：实践层
  - merge/aggregate 算子（EvolveNet）
  - public/private 可见性过滤的真实实现（X3）
  - 双层 loop recipe（AIDE²/dgm，M3.5）
```

## 6. 明确不做的事（防止范围蔓延）

- **不做**生产热替换/容器健康探针（Moss 的 DevOps 语义）——我们是研究框架不是在线服务
- **不做**联邦拓扑/数据本地性（EvolveNet 的多信任域）——单租户框架，X3 表达可见性已足够
- **不做**RL 训练算子策略（OpenRSI 的 Frontis-MA1）——推理时框架，learnable 标注是预留不是承诺
- **不做**递归自我改进内核（双层 loop 只做 recipe 级支持，不进主循环）

## 7. 新增：M5 统一记忆子系统适配（基于 2026-08 M5/M6 深度调研）

> 依据：`M5-UNIFIED-v1.md`（本目录，正式设计文档）+ `../docs/M5记忆设计空间深度展开_A-I轴_分歧点_失效模式.md`（证据基础）。
> 结论：ACE / MemRL / DGM / IBM TSM / prime-agent / Dreaming 全部可表达为同一内核上的 profile——M5 不需要为每个经典设计写一套实现。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 7.1 | 新建 `core/memory/types.py`：MemoryEntry（强制 provenance/time）+ LifecycleState 五态 + EvidenceRecord——全字段有默认值，纯增量 | M5-UNIFIED §2-3 | **P1**（随 Step 1 文档层并行） |
| 7.2 | 生命周期状态机迁移函数 + append-only 证据日志（复用 X1 存储）；硬编码不变量：算子只提议不执行、delete 仅卫生事件、降级不删除 | M5-UNIFIED §3 | P1 |
| 7.3 | 五个算子 Protocol（encode/admit/retrieve/consolidate/retire）+ 确定性实现全套 + two_stage retrieve 骨架（效用重排与状态过滤不可关闭） | M5-UNIFIED §4 | P2（M5b 期） |
| 7.4 | 双速调度器：sync 槽硬约束禁 LLM；idle 槽放重型巩固 | M5-UNIFIED §5 | P2 |
| 7.5 | profile 机制 + ace/memrl 两个起始 profile；no_governance 仅作显式对照基线 | M5-UNIFIED §6 | P2 |
| 7.6 | tenure 评测协议挂钩 M8：profile 消融 ≥3 个 tenure 点、排名反转作为一等发现报告 | M5-UNIFIED §8 | 随 M8 里程碑 |

**新增不做清单**：
- **不做**在线记忆架构自进化（MemEvolve 留作设计期实验）
- **不做**可学习记忆算子的默认启用（RL 训练永远是显式 opt-in，排 M5d/M3.5）
- **不做**用户象限记忆（轴 I 已声明 about=工作 × for=性能）

## 8. 新增：M8/M9 统一评估与准入子系统适配（基于 2026-08 评估/门控深度调研）

> 依据：`M8M9-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m8m9/ 下` 五份调研卡片与两份轴系深挖。
> 结论：OpenEvolve 级联 / ShinkaEvolve 契约 / SEAL 密封门 / MOSS 三门 / PAST-Bench 机制分 / MLOps registry 全部可表达为同一内核上的 profile（§8 兼容性验证，六个 profile 无一处改内核）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 8.1 | EvalResult 扩展（per-item items 数组强制非空 / public-private-text_feedback 物理分离 / EvaluationCard 强制谱系 / ReliabilityMeta 强制 CI95）+ 新增 Verdict / Receipt 类型——**并入 Step 0 类型层改动** | M8M9-UNIFIED §2 | **P0**（E9a，与 G1/G2/M5a 同批） |
| 8.2 | 判定规则库封闭枚举（flip_count / non_regression / msprt / e_value_gate / noise_floor_zero / absolute_conjunction）+ 票据失效引擎（head_sha/base_sha/gate_graph_version/evaluator_version 四绑）+ Gate.consume() 白名单黑名单 | M8M9-UNIFIED §3/§6 | P1（E9b） |
| 8.3 | 四条框架级不变量上收 CLAUDE.md：I-α 锚点存在性、I-β 质量指标一等化、I-LLM（LLM 建议确定性终裁）、I-谱系（软证据作废硬证据永存） | M8M9-UNIFIED §0.0；Stage 3 根因对账 | **P0**（文档改动，随 Step 1） |
| 8.4 | 公理 B3 immutable core 清单：M8 评分代码/测试/计时/日志管道 + M9 准入规则 + 反作弊层列入进化禁止修改集；M8/M9 代码入 X1 谱系 | M8M9-UNIFIED B3 | **P0**（CLAUDE.md 禁令） |
| 8.5 | sealed_audit judge + isotonic 校准 + judge 三探针（位置交换/长度/自我偏好）+ gate_quality_probe 伴生组件 | M8M9-UNIFIED §4/§5 | P2（E9c/E9d） |
| 8.6 | meta-gate 递归（评估器变更先过 held-out 不回退硬门、通过即 epoch 边界级联作废旧 receipt、anchor 永存）+ E1 漂移归因（anchor 双 e-process） | M8M9-UNIFIED §6.4 | 随治理里程碑（E9e），不阻塞 Step 0–3 |

**新增不做清单**：
- **不做**评估器全自动无门共进化（meta-gate 永远在位）
- **不做**对 agent 全透明反馈的默认档（`full` 仅调试期显式声明）
- **不做** LLM 终裁路径（decision_rule 无 LLM 实现档）
- **不做**聚合总分作 M9 终裁输入（gate-not-rank 硬编码，combined_score 仅 display）

## 9. 新增：M2 统一算子子系统适配（基于 2026-08 算子深度调研）

> 依据：`M2-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m2/` 下三份调研卡片、19 轴定稿、三批逐格深挖、分歧裁决与公理 C1–C12。
> 结论：OpenEvolve diff / GEPA 反思变异 / DGM 自修改 / OpenRSI 统一动作空间 / FunSearch 岛隔离 全部可表达为同一算子内核上的 profile（§8，五个 profile，各自违反的公理已诚实标注）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 9.1 | 四算子集 {draft, improve, debug, crossover} 落成纯函数签名（AIRA-dojo 风格 `op(llm, cfg, memory_op, task_desc, journal, *input_nodes, step_count, remaining_time)`）+ 退化基线 IID-RS/SCS 永驻不可移除（Occam 自检及格线） | M2-UNIFIED §3 | **P0**（M2a，与 Step 0 类型层同批） |
| 9.2 | 四段漏斗记账（proposed→applicable→runnable→admitted + diff_inflation + crossover_validity + sub_funnels）+ 多样性探针——C1/C6 双 MUST，无漏斗数据的算子不得参与自适应选择 | M2-UNIFIED §2/§3 | **P0**（M2a） |
| 9.3 | M2 消费 M8 白/黑名单（白：public 标量/结构化错误定位/card.scorer_version；黑：text_feedback 未剥离版/private/combined_score/full trace）+ 第五候选不变量 I-披露（信号通道最小披露，待框架级确认） | M2-UNIFIED §2/§0 | **P0**（类型层强制，随 8.1 EvalResult 扩展同批） |
| 9.4 | 变异表示层：确定性 patcher + [0.6,0.3,0.1] 概率混合 + per-(模型,表示,任务族) apply 失败率台账 + 新颖性闸 0.95 + plateau 归因二分 | M2-UNIFIED §3 | P1（M2b） |
| 9.5 | 上下文配方 ContextRecipe（消费 M5 视图声明；作用域记忆按算子类型路由：draft/improve→兄弟记忆，debug→祖先链；新鲜度/抽象度门在 M2 入口） | M2-UNIFIED §2/§3 | P1（M2b，依赖 M5b 视图接口） |
| 9.6 | 自修改四件套（冻结边界/功能性存活门/证据化小写+快照回滚/X1 覆盖 gate 代码——**第④件最先做**，唯一实证抓到过真失效的件）+ self_mutable 位声明 | M2-UNIFIED §3/§6 | P1（M2b 冻结声明）→P2（M2c+） |
| 9.7 | op tax 经济学（显式定价+档位打包+整代 handoff 上报 M3，禁止逐 call 路由） | M2-UNIFIED §3 | P2（M2d，与 M3 联动） |
| 9.8 | 可学习算子（learnable 档）三前置硬编码：漏斗数据就位 + 可重跑评估 + RL 设施；默认永远固定 prompt | M2-UNIFIED §4 | P3（M2e，显式 opt-in） |

**新增不做清单**：
- **不做**全量历史拼接喂变异器（AIDE₀ 已证失效配置；上下文必须走 ContextRecipe）
- **不做** LLM 自判 is_buggy 硬过滤（只能由环境事实判定）
- **不做**逐 call 模型路由（RelayEvolve 状态耦合论证；整代 handoff 才对）
- **不做**算子自适应选择的默认启用（规则表为默认；bandit/RL 须挣得存在——增量超评估噪声底）
- **不做**无谱系的宽作用域联合编辑（WHERE×WHY 坐标强制入 X1）

## 10. 新增：M6 统一外部知识子系统适配（基于 2026-08 M5/M6 深度调研）

> 依据：`M6-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m5m6/` 下 M6 调研卡片、16 轴定稿、两批逐格深挖、分歧裁决与公理 D1–D10。
> 结论：Arbor 两车道 / KAPSO ERA / Tree-of-Ideas / IDEAgent QD 可表达为同一内核上的 profile；AI-Scientist veto 方案作为反例 profile 收录（不可编译，作 lint 规则测试集）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 10.1 | 双工具契约 query(intent)+audit(idea) 为 M6 唯一供给通道（intent 枚举 related_work/survey/lookup/explore/repair；audit 不入 intent 体系）+ KnowledgeDigest/AuditVerdict/FetchLedger 类型层——并入 Step 0 | M6-UNIFIED §2 | **P0**（M6a） |
| 10.2 | 两车道物理隔离三层实现：字段分离写权限（node.grounding vs node.related_work）+ 独立检索上下文（缓存命名空间隔离，audit 查询不得含 ground digest）+ 启动静态检查；D1 禁降级 | M6-UNIFIED §3.1 | **P0**（M6a，CLAUDE.md 禁令） |
| 10.3 | 审计双触发三档 advisory（add 预检 + merge 前复核；novel/partial-overlap/prior-art-exists；类型层禁止 veto 闸门，裁决权归 M9）+ verdict 携带 reliability 字段（无复核覆盖=按无审计处理） | M6-UNIFIED §3.2 | P1（M6b） |
| 10.4 | 注入格式契约：压缩 digest 起步、gap 信号卡为演进目标（语法主语必须是 gap/约束，schema 校验）、flat RAG 禁默认；任何注入格式变更强制 2×2 消融重跑 | M6-UNIFIED §3.6 | P1（M6b） |
| 10.5 | benchmark 模式 M6 全关且 eval_mode 由 M8/M9 传入并进 X1 谱系（D10；"全关必须跨 M5/M6/M8 联合生效"） | M6-UNIFIED §3.4 | **P0**（随 8.1 同批） |
| 10.6 | ERA 联合入口协议：M8 失败信号同时触发 M5 retrieve + M6 repair，产物 era_internal/era_external 分标进 M2 ContextRecipe（三方契约，依赖 M5b 与 M2b） | M6-UNIFIED §3.5 | P2（M6c） |
| 10.7 | 三盲区轴"先记账后定参"：双率台账（false-novel/false-kill，抽样复核协议）、注入引力探针（fitness 禁作报警触发）、隔离违规检测——先落 schema 与台账，阈值留配置 | M6-UNIFIED §3.7/§3.8 | P2（M6c）→P3（M6d 定参） |

**新增不做清单**：
- **不做**审计 veto 硬闸门（AI-Scientist 12/12 false-novel + 9/10 false-kill 双反例；类型层禁止）
- **不做**单车道或共享缓存中间档（"见过即污染" 27.2%→49.1%；D1 硬约束禁降级）
- **不做**未实际打开来源的引用（fetch ledger 行为事实为引用诚实判据）
- **不做**常驻强制注入（收益最高的两端都绑定信息缺口事件；常驻注入只值 −9%）
- **不做** audit_judge 可学习档（判别质量必须先被独立测量，且学习化会引入新的可讨好面）

## 11. 新增：M4 统一前沿/档案子系统适配（基于 2026-08 档案/前沿深度调研）

> 依据：`M4-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m4/` 下三份调研卡片、20 轴定稿、三批逐格深挖、分歧裁决与公理 E1–E12。
> 结论：FunSearch 岛 / OpenEvolve MAP-Elites / GEPA pareto / DGM 树档案 / EvoDiverse / EvolveNet 联邦 全部可表达为同一档案内核上的 profile（§8，六个 profile 附违反公理诚实标注）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 11.1 | ArchiveEntry 类型层：三资格位（archived / parent_eligible / deliver_eligible）+ CI 一等字段 + 谱系四元组 + buggy_leaf 状态——并入 Step 0 | M4-UNIFIED §2 | **P0**（M4a，与 G1 候选层级化同批） |
| 11.2 | ParentPool 五字段契约（island_id / children_count / rarity / per_instance_best / parent_eligible）写死对齐 M2-O11，供给函数可热替换（E2，"Database 即算法"，结构-策略禁焊死） | M4-UNIFIED §2/§3 | **P0**（M4a） |
| 11.3 | 驱逐协议：噪声底下不裁决（E12）+ CI 下界裁决 + 软删除深度缓冲 + **硬删除 API 不存在**（E5）；失败候选只认环境事实判定 + debug 复活通道 | M4-UNIFIED §3 | **P0**（M4a，CLAUDE.md 禁令） |
| 11.4 | grid×islands 默认拓扑 + 亲本三路采样骨架（0.7/0.2 + double selection，公式归 M1）+ 常驻退化自检（SCS/单链投影，增量须超 M8 噪声底，P15） | M4-UNIFIED §3 | P1（M4b） |
| 11.5 | ArchiveHealthProbe 四族探针（跨代/跨岛/跨实例/供给熵浓度，与 M2 DiversityProbe 字段级对齐，alarm→X1）——**顺位 0：度量实现与标定是 M4 后续最高优先依赖**，先记账后定参 | M4-UNIFIED §2/§7 | P1（M4b 起持续） |
| 11.6 | M5 沉淀通道：档案→M5 encode/admit 递交 level=L2 candidate 条目，provenance 复用谱系四元组，沉淀资格=交付资格（启用序 P13→P20→P14） | M4-UNIFIED §3 | P2（M4c，依赖 M5b） |
| 11.7 | 跨 run 合并双前置（锚点重标定 + 驱逐可证伪）+ MergeEvidence 类型 + 异源谱系边入 X1；移交估值 Relay Gain（决策粒度=移交集级） | M4-UNIFIED §3 | P3（M4d） |
| 11.8 | 候选不变量 I-可逆（不可逆操作滞后于证据成熟度）上收 CLAUDE.md 待框架定稿确认（与 I-披露并列候选） | M4-UNIFIED §0 | **P0**（文档改动） |

**新增不做清单**：
- **不做**硬删除/杀岛类不可逆档案操作（E5；一切不可逆操作滞后于证据成熟度——I-可逆）
- **不做** best_so_far 单峰档案作默认（早熟锁定；仅作退化自检对照）
- **不做**点估计驱逐（CI 下界才裁决；噪声底下不裁决）
- **不做**无门控的跨 run 档案合并（EvolveNet 无门控链式为反面反证）
- **不做**档案健康无探针运行（二阶治理指标缺失=现行主流框架集体盲区，E1/E4 传感义务）

## 12. 新增：M1 统一策略子系统适配（基于 2026-08 策略层深度调研）

> 依据：`M1-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m1/` 下三份调研卡片、18 轴定稿、三批逐格深挖、分歧裁决与公理 H1–H12。
> 结论：FunSearch / ShinkaEvolve / DGM / RelayEvolve / EvoX / AIDE² 的策略层全部可表达为同一策略内核上的 profile（§8，六个 profile 附违反公理诚实标注）。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 12.1 | ParentFormula f×g 二元接口（分数项×拥挤项）+ **默认 greedy argmax 供亲（v1.2 用户裁决）+ 强制伴随 H2 监控与结构多样性承载** + weighted_sigmoid/three_way 永驻对照臂 + 拥挤项符号派生表硬编码（淘汰制→penalty_inverse / 永久制→bonus_linear，随 M4-P10 联动重配置）——并入 Step 0 | M1-UNIFIED §2/§3 | **P0**（M1a） |
| 12.2 | intent_queue 为 M1→M3 唯一通道：AllocationIntent + IntentReceipt（ttl / expected_gain CI / policy_version / snapshot_ref 四关键字段；可拒绝性是本质升级；ratio_table 降为永驻对照位） | M1-UNIFIED §2 | **P0**（M1a，M3 契约前提） |
| 12.3 | 输入统计量规则（G17）：四类决策门槛协议表（加压/切换/停止/分配各有"不可裁决"默认动作，触发预算向重评转移）+ 决策用分/报告用分类型层分离 | M1-UNIFIED §3 | **P0**（M1a，CLAUDE.md 禁令） |
| 12.4 | 停止动作查表（M9 Verdict×scope→动作硬编码查表，M1 不复算统计量）+ 相位信号层级（Relay Gain 主判据 + 预算比例兜底 + Verdict 恒叠加；wall_clock 禁独用） | M1-UNIFIED §2/§3 | P1（M1b） |
| 12.5 | 动作可逆性（G18，I-可逆第四投影）：快照复用 M4-P13 双快照 + snapshot_ref 类型层绑定 + 策略状态随快照回滚（bandit 统计量不复位）+ pmin 类型层饿死地板 | M1-UNIFIED §3 | P1（M1b） |
| 12.6 | 自我证成公约落地：退化基线永驻对照 + 对照预算 5–10% 为 M3 保留科目 + 显著性口径单源 + 降级流程闭环 | M1-UNIFIED §0.1/§3 | P1（M1b，与 M2-C10/M4-P15 统一表述） |
| 12.7 | PolicyLineage 通用四元组（policy_id / parent_policy_ids / deploy_context / acceptance_evidence）；策略非 frozen 档强制谱系（构建期拒绝） | M1-UNIFIED §2/§4 | P2（M1c） |
| 12.8 | 标定任务（投资顺位 0）：G2 符号联动规则首验 + f(信噪比) 中间段标定——M1 全部自适应档的共同前置 | M1-UNIFIED §7 | P1 起持续 |

**新增不做清单**：
- **不做** wall_clock/日历型相位切换独用（Fixed-switch 全败；二维观测量禁降维成日历量）
- **不做**点估计驱动的策略决策（G17；SB P=0.49 与 EoH 5× 是同一信噪比函数的两极）
- **不做** pmin 可关的 bandit（饿死是乘性分配渐近性质，pmin 写进类型层）
- **不做** M1 侧复算统计量（只消费 M9 Verdict 枚举 + M8 ReliabilityMeta，查表执行）
- **不做**运行期策略自修改默认档（frozen 默认；可学习档强制谱系+离线 meta，RL 训练为占位端点）

## 13. 新增：M3 统一预算控制子系统适配（基于 2026-08 预算层调研）

> 依据：`M3-UNIFIED-v1.md`（本目录，正式设计文档）+ `../research/m3/` 下两份调研卡片、14 轴定稿、逐格深挖、分歧裁决与公理 J1–J10。
> 结论：FunSearch 墙钟 / AIRA remaining_time / RelayEvolve handoff / agentgateway reserve-settle 可表达为同一预算内核上的 profile；GEPA validation-heavy 作反例 profile 收录。

**适配动作**：

| # | 动作 | 位置 | 优先级 |
|---|---|---|---|
| 13.1 | BudgetLedger（append-only，三级键 call→op→block，policy_version/版本戳一等字段，入 X1）+ CurrencyAccount 多币种账户族（版本化汇率表+标准币锚定）——并入 Step 0 | M3-UNIFIED §2 | **P0**（M3a） |
| 13.2 | M1 契约回补（已落地 v1.1）：AllocationIntent 增 budget_unit 必填字段 + IntentKind/cost_account 扩七科目枚举 + control 类意图签发路径 | M1-UNIFIED §2 | **P0**（已完成） |
| 13.3 | "M3 只报价/预扣/拒绝"原则：reserve→settle 预扣结算 + 三态拒绝分流（rejected_budget 回流 M1 重发低档意图，分配语义单一作者）；降档决策不归 M3 | M3-UNIFIED §3 | **P0**（M3a，CLAUDE.md 禁令） |
| 13.4 | 硬+软上限（仅监控永禁）+ 软阈广播（触顶→收敛相位，截断 run 带归因标记入 X1） | M3-UNIFIED §3 | P1（M3b） |
| 13.5 | 七科目决策因果链投影（模块图投影非法）+ 对照科目四层制度链（比例锁定 5–10% + 例外程序 + 过期降权 + 兑现率监控）——自我证成公约预算侧条款 (f)(g) 的执行机构 | M3-UNIFIED §3/§0 | P1（M3b，与 12.6 联动） |
| 13.6 | M3HealthProbe 四指标（有效预算率/差额率/隐性科目占比/对照兑现率）——先记账后定参；效率指标 admitted_per_usd 主 + C/R-CPST 对照（单价指标永禁） | M3-UNIFIED §2/§3 | P1（M3b 起持续） |
| 13.7 | 遗留联合裁决项：N6 拒绝-重发回路与 ttl_blocks=1 时延冲突（R4，M1×M3 联合裁决，未解前拒绝-重发回路不可用则保底档须重新设计） | M3-UNIFIED §9-3 | P1（阻塞 M3b 完成判据） |

**新增不做清单**：
- **不做**仅监控无执行（Waxell $47k 死循环事故；监控≠执行）
- **不做**模块图投影的科目划分（GEPA 85–90% 隐性科目为反例；科目=决策因果链投影）
- **不做**单价指标作效率度量（$/token 方向性奖励高重试组件；admitted_per_usd + C/R-CPST 才对）
- **不做**跨期"等预算"用钱定义（标准币锚定，还原为物理搜索深度）
- **不做** M3 侧降档决策（M3 只报价；降档经拒绝回流 M1 重发——分配语义单一作者）

---

## 附：九模块统一设计闭环状态（2026-08-28）

| 模块 | 统一设计文档 | 公理系 | 轴数 | profile 数 |
|---|---|---|---|---|
| M5 Memory | M5-UNIFIED-v1.md | A1–A8 | 9 轴（A–I） | 7 |
| M8+M9 | M8M9-UNIFIED-v1.md | B1–B11 | 19+19 | 6 |
| M2 Operator | M2-UNIFIED-v1.md | C1–C12 | 19（O1–O20） | 5 |
| M6 Knowledge | M6-UNIFIED-v1.md | D1–D10 | 16（K1–K16） | 5（含 1 反例） |
| M4 Frontier | M4-UNIFIED-v1.md | E1–E12 | 20（P1–P20） | 6 |
| M1 Policy | M1-UNIFIED-v1.md（v1.1） | H1–H12 | 18（G1–G18） | 6 |
| M3 Budget | M3-UNIFIED-v1.md | J1–J10 | 14（N1–N14） | 5（含 1 反例） |
| M7 Executor | 不走统一梳理 | — | — | CODE-BORROWING 直接借鉴 |

框架级沉淀：四条不变量（I-α 锚点存在性 / I-β 质量指标一等化 / I-LLM / I-谱系）+ 两条候选不变量（I-披露：M2/M6 等四模块投影；I-可逆：M9/M4/M2/M1 四投影）+ 自我证成公约（条款 a–g，物化于 M2-C10 / M4-P15 / M1-G12 / M3-J8）。
