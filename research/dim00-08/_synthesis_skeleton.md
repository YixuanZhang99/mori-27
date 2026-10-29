# 综合文档骨架（待 dim01-08 结果填充）

## 候选模块划分（九模块 + 两横切层）

控制面（决策）:
- M1 Coordinator/Policy：全局策略（Observe/Ideate/Select/Decide），可插拔 policy（LLM 自由策略 | UCT | Boltzmann | MAP-Elites 调度）
- M2 Operator：候选生成算子（draft/improve/debug/crossover/hypothesis-refine/LLM-diff），算子选择策略与算子本身解耦（AIRA 教训：算子质量先于拓扑）
- M3 BudgetController：轮数/时间/token/方向级预算、收敛检测、early stop、multi-fidelity 级联调度

数据面（状态）:
- M4 ResearchState：搜索拓扑（chain/tree/DAG/population/island）+ 节点 schema（hypothesis/artifact-ref/evidence/insight）+ 多投影（程序态/LLM 态/人读态/约束态）
- M5 Memory：内生经验（trace → lesson → knowledge → wisdom 的 promotion 管线；检索注入契约；防污染）
- M6 Knowledge：外部知识（文献/web/repo/playbook；grounding vs novelty-audit 两车道；知识图 schema）

执行面（落地）:
- M7 Executor：假设绑定执行（worktree 隔离、修复循环、结构化回报）；角色分工是 Executor 编排的配置
- M8 Evaluator：评估契约（metric_direction/eval_cmd/返回类型 = status+score+cost+diagnostics+uncertainty+artifacts；多保真度；污染检测）
- M9 AdmissionGate：准入协议（dev/admission/final-audit 三层；margin gate；ratchet；ensemble）

横切层:
- X1 Provenance & Audit：git lineage、checkpoint/resume、事件总线、防篡改
- X2 HITL：interaction modes、gate 超时、steering

## 待验证问题（从 dim01-08 结果回答）
1. 搜索拓扑能否统一为"前沿容器 + 选择算子"接口，使 tree/DAG/island 可配置？（dim01/05/08）
2. 记忆的时间尺度分层与假设层级绑定能否统一为"记忆后端"接口？（dim02）
3. 成本如何进入选择与准入？Evaluator 返回类型的最小完备集？（dim03/07）
4. 职能分工与假设分工能否统一为 Executor 编排配置？（dim04）
5. 开源进化框架（OpenEvolve 等）的模块接口清单，与上面九模块的映射？（dim06）
6. 评测协议三层化（dev/admission/audit）的各家实现与陷阱？（dim08）
7. 多样性机制如何与语义假设管理共存？（dim05）
