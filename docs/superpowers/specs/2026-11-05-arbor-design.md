# C04 Arbor 接入设计草案

状态：基于用户已批准的经典工作计划细化；AIDE 矩阵运行期间在独立的干净历史 worktree 上进行离线施工。
实施顺序不变：AIDE 实测、合入与分支退役之后，将这里的离线改动衔接实际 main，再创建唯一 Arbor 方法分支。
来源核对见 [源码核对记录](2026-11-05-arbor-source-notes.md)，上游固定 a633f56f2601387402194481e846e3375e822afa。

## 目标和边界

完成 docs/specs/classic/ARBOR.md 全部九模块要求及 R1–R6，提供命名 profile、默认离线入口、真实三任务三 seed 诊断、计量、回放和官方冻结提交评分。
使用现有公共 Framework，不另建搜索主循环、账本、执行器或评分器。
保留默认 20 cycles / depth 2，首轮 pilot 5 cycles / depth 2 / margin 0 / admission query cap 3。
全部真实调用继续原累计 ¥200 campaign；不能复制或打印凭据。
不将三任务小预算结果称为论文复现，不以 fixture 代替真实 gate。
知识联网与跨 run 技能迁移继续关闭，它们不属于本 recipe 的 benchmark 范围。

## 实现方式

考虑过三个路径：直接配置 llm_cycles（不能消费 ideation 上下文、没有上溯，排除）；移植上游独立 orchestrator（违反公共 Framework，排除）；在现有 composition 上补方法策略和受信记忆协作（采用）。
这是实现者对已批准模块设计的选择，不增加用户未批准的功能目标。

保持 M1 四个现有 hook，但其内部必须有真实六阶段行为，不能仅重命名日志。新 observe 内完成语义上的观察与生成，select 消费已经产生的真实选项；现有 ideate hook 只传递已选假设：

1. Observe：从数值树视图、预算和经 M5 投影的记忆准备当前观察，不读取私有 evaluator。
2. Ideate：一次计量规划调用产生 1–3 个可执行假设，含合法扩展父节点、引用来源、机制和预期现象。未执行假设留在有界 pending 集；下一周期可以选择已有假设，也可以在剩余额度内补充。
3. Select：从实际 pending 集选择一个 hypothesis_id，再映射到该周期 candidate_id。保留候选批次及选择理由；禁止事后把执行结果写成选择理由。
4. Dispatch：M7 固定选中假设，在隔离 worktree 构造并由 PublicTrainDomain 训练/评分。代码 lineage 和参考来源边区分；只有实际执行结果才进入已评估 frontier。
5. Backpropagate：真实 dev 结果产生源绑定叶 insight；按 skeleton 父链增量更新祖先摘要和全局 prior。每次合成必须消费旧摘要加本次新证据，保存完整来源集合；不是简单复制同一字符串到所有节点。
6. Decide：沿用 layered admission，dev trigger → 独立 admission → 严格改进才更新 trunk；拒绝时 trunk 不变。final 只在搜索结束冻结后执行，不进入 insight 或规划。

## 组件和接缝

`ArborPolicy`（新 `m0/core/composition/arbor_policy.py`）负责观察、提出和选择假设，使用现有 metered provider。它保存 pending 假设和本次选择的可恢复状态。普通 LLMCyclesPolicy 不改变默认行为。

`ArborCoordinator`（新 `m0/core/composition/arbor_runtime.py`）由 driver 持有，类似现有 FunSearch 协作对象，负责来源验证、六阶段事件、假设与 candidate 绑定、受信上溯和恢复核对。它没有自己的循环，不直接绕过 InvocationLifecycle 发起模型、训练或 gate 调用。

规划输入：为这个显式配置的策略，在 observe 前经现有 ContextPackBuilder 取 run-scoped M5 记忆并通过 M7 project_context 投影。保持 ConfiguredExecution.selection_view 的文本移除规则；不能从 frontier.result 旁路读取原始反馈。原有策略仍按现有顺序取父代相关 context。

受信上溯：发生在现有已预留的 planning/absorb envelope 内。独立 absorber 会话只获得当前公开 dev evidence、选中假设、已授权旧摘要和 skeleton 路径；不得共享 planner 的任意会话状态。模型提出内容，driver 绑定实际 evidence refs、源候选和祖先身份后由 M5 写入，serial mutation 发布。不要放松普通 policy 只能更新当前节点的限制。

Memory 内容区分：叶 L1 原始摘要；祖先/全局 L2 洞见（模型解释，不是已证明的科学事实）。正/负约束必须保留来源、dev 成败及有限 gate 接纳/拒绝状态；不能把 admission 分数、标签、反馈文本或任何 final 结果送入规划。高 dev 但 gate 拒绝只说明未通过准入，不能伪造失败原因。

具体来源表示采用现有 ContextMemory.bindings 的受信派生角色 `tree_insight`（类似现有 proxy_feedback 的独立授权路径）：绑定本次真实 dev receipt、已授权旧摘要版本、扁平化的全部原始来源集合、目标祖先/虚拟全局 root、规范化内容及合成输入/输出 refs。普通 policy 不能自行注册该角色。`_validate_entry` 单独验证这个角色，保留普通 dev 的单源候选约束。每次摘要产生新版本，旧版本保留证据但不再检索；不能覆盖原历史。

有限准入信息另用 `admission_verdict` 派生绑定，只允许 candidate_id、admit 布尔值和实际 receipt_id，不含自由文本 reason 或分数。coordinator 从原 controller receipt 推导；snapshot 恢复重新核对原 receipt。它只用于标注假设通过/未通过准入，不授权读取 gate 数据。

必须区分假设 skeleton parent 和实际代码基底：保持上游从派发时当前 trunk 的固定 artifact 构造，不能因为现有 parent_artifacts 接口方便而改成从非 trunk 研究分支继续训练。新 `hypothesis_refine` recipe 使用 driver 绑定的 `hypothesis_binding`，显式记录 hypothesis_id、skeleton parents、trunk candidate/artifact/materialization refs 和 context ref。没有 trunk 时允许空基底。ConstructionPlan 对这个 recipe 校验 parent_artifacts 恰好等于该基底；普通 recipe 仍要求 artifact parents 与 candidate.parents 一致。绑定和原 trunk 决策链由 coordinator 重算，不能接受模型填入代码或 refs。reference edges 只表示想法来源，不改变 skeleton/depth 或代码基底。

生成 wire schema 固定 `new_ideas`（1–3 项或仅选择已有 pending 时为空）和 `selection`。新 idea 包含 `parent_id`（nullable）、`hypothesis`、`expected_observation`、`source_refs`；host 分配稳定 ID，不信任模型生成 ID。selection 指已有 pending ID 或本批下标；没有真实 pending 项不能选择。每个新假设的父节点必须存在、执行成功、有非空 artifact；允许无父代探索。选择时重新核对父资格、depth 和预算。pending 只保存计划，未执行前不能拥有实测 score 或 admission 状态。已选项只能消费一次。

拟使用 interfaces：

- `ArborPolicy.observe(state, budget) -> dict`：state 显式含 projected planning_context；产生批次并保持 pending；返回当期策略。
- `ArborPolicy.select(frontier, budget) -> Selection`：从 pending 中选择合法、预算可承担、depth <= 2 的假设及父代；`ideate(context, parent, k)` 返回已选固定假设，不再生成第二个计划。
- `ArborCoordinator.prepare_observation(state, context) -> dict`：绑定输入来源，不增加模型调用。
- `ArborCoordinator.backpropagate(proposal, public_evidence, context, *, cycle, llm) -> list[StateMutation]`：运行于现有已计量 absorb 调用内；从 driver 持有的原始记录验证来源和 ancestry，生成本轮合法写入。
- `ArborCoordinator.commit_decision(candidate_id, decision)`：仅记录有限准入状态、更新方法视图；trunk 变更权仍在现有 admission/runtime。
- `ArborCoordinator.restore(checkpoint, original_events)`：核对 pending、选择、假设绑定及摘要来源，不信任可改的 checkpoint 自报状态；recorded replay 不调用 provider。

其他组件复用：M7 `hypothesis_frozen=True`、构造格式修复、Git artifact backend、PublicTrainBundle 的固定预测、LayeredAdmissionController、hierarchical budget 和原 currency authority。
任务指标模式需要显式支持 admission context，仍保留旧 proxy 模式默认装配。不得因切换评分而影响 AIDE 已冻结证据。

## 预算和停止

- cycles 指实际主候选尝试，初始候选也计数；pending 未派发不算训练节点，但其规划费必须计入。
- 构造固定假设，最多 2 次构造尝试。每次都计费；改变假设的输出拒绝，不能作为第二个研究方向提交。
- 最多三条新假设/轮，pending 总量上限 3 × max_cycles；达到树深度或预算上限的方向不能派发。
- 使用现有低样本规则收敛：min_samples=4、patience=3、min_improvement=0；它是显式的 adapted 停止规则，不声称等同上游全部 warn/force/stop 行为。
- 每轮 planning 预留覆盖一轮 ideation 以及最多 depth+1 次反馈合成；各 provider 调用继续原独立 CNY 预留和结算。无未知费用时才开始下一单元格。
- 一次独立初始 control，fresh session、无 main memory。单列成本，不冒充未成功 main 候选的替代成绩。

## 验收和交付

- R1：通过 Framework 执行两个以上周期，检查六阶段真实顺序、pending 选择、hypothesis_id/candidate_id、独立引用边及全部规划费用。
- R2：M7 构造修复接受同假设实现；篡改假设拒绝。输入意图/effective hypothesis 一致。运行失败保留，不能偷偷替换方向。
- R3：同一固定 artifact 在 dev 优于 trunk、admission 差于 trunk，真实拒绝且 trunk 保持；同分和 margin 边界测试。gate cap=3 被严格执行。
- R4：叶负面 dev 结果的来源进入祖先和全局 prior；下一次实际规划 prompt 可见；多个子节点增量合成保留先前来源。
- R5：关闭 insight 的配对 fixture 实际改变规划输入/模型输出，不能只检查 memory 文件存在。
- R6：final 内容替换不影响之前规划、树、insight 或选中 artifact；gate 原始分数/标签/文本同样不得进入 planner。
- 公共 resume/replay：保留 pending、固定假设、trunk 和摘要；完整候选后的恢复不重发 provider；回放不训练、不调用官方 grader。
- 失败保留：无有效候选、规划格式错误、构造失败、训练超时、gate 拒绝/耗尽分别报告；没有官方成绩时为 null。
- 默认 offline CLI 跑真实 synthetic 训练流；live 先 spooky seed 0 完整 smoke，再同一预声明协议下执行三个任务 × seeds 0/1/2。固定 split_seed=7，low/16384 alias，与原 campaign 共用限额。
- 搜索结束后官方评分；method-report 包括 fidelity=adapted、source revision、deviations、逐阶段费用、dev/admission/final 区别及全部失败。若真实 trace 无自然拒绝，报告事实并附独立机制反例。
- 最终全检查、一次整分支独立审查、最终准确提交的 Mac/Linux/MLE CI 后合入，保留归档 tag、退役唯一方法分支，再进入 OpenEvolve。

## Builder 核对

已进行一次独立只读 builder check：未发现必须向用户追问的重要缺口。随后实现者依据实际单源记忆校验和 parent_artifacts 约束，补充了上面的派生绑定、有限 verdict 以及假设谱系/当前 trunk 基底分离；这些是实现原机制所需的明确接缝，不扩大目标。实际实现仍须通过原始事件重建与输入隔离测试。
