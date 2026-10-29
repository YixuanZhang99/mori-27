# Plan: AutoResearch 模块化设计空间深度调研与统一抽象

## 目标
为用户自研"可配置 AutoResearch 框架"（对标 vLLM/SGLang 在 infra、VeRL 在 RL 的生态位）
建立：(1) 相关工作的机制级深入理解；(2) 可落地的模块化抽象（模块边界 + 接口契约 +
每模块的设计选项与权衡）；(3) 参考架构与组合配置示例。

## 已有材料（无需重复调研）
- Arbor 论文全文（arXiv:2606.11926，已精读）
- Codex 总结：八轴分析卡 + 六深读单元 + 两层 baseline 划分
- ChatGPT 总结：十模块框架 + One Graph/Two Loops/One Boundary + 批判性判断
- 我此前的七维设计空间文档

## Stage 1 — 深度调研（skill: deep-research-swarm，Route B 聚焦式）
派 6 个并行 explore subagent，每个负责一个"机制单元"，统一输出模板：
  机制拆解（核心循环伪代码级）/ 模块边界与接口（什么是可插拔的、契约是什么）/
  关键设计决策与权衡 / 消融或实验证据（什么设计真正重要）/ 八轴卡 / 对统一框架的接口启示

- U1: AIDE + AIRA-dojo —— 搜索策略×算子解耦（tree/greedy/MCTS/evolution × operator set）
- U2: ML-Master 1.0/2.0 + 记忆线（HCC、Reflexion、playbook/ACE）—— 记忆时间尺度与 promotion
- U3: MARS + 成本敏感搜索 —— cost-aware MCTS、comparative reflection、multi-fidelity
- U4: R&D-Agent + AIBuildAI —— 角色分工、战略-执行分层、multi-start
- U5: LoongFlow + FM Agent + AlphaEvolve —— population/island/MAP-Elites/多样性
- U6: KAPSO + AiScientist-2026 —— 知识平面、provenance、File-as-Bus、durable workspace

补充（主线空闲时自己做，不另派 agent）：
- Arbor GitHub 仓库的实际模块划分（RUC-NLPIR/Arbor）
- InternAgent/AutoMLGen 的 MCGS（图搜索 vs 树）要点
- 综述 Tie et al. 2025 + sandbagging 研究的评估协议要点

## Stage 2 — 综合抽象（我自己做，research 与 writing 分离）
产出统一模块化框架文档，核心内容：
1. 模块 taxonomy：从 7 维/10 模块收敛到一套带接口契约的模块划分
   （State / Operator / Policy / Executor / Evaluator / Memory / Knowledge / Admission / Budget）
2. 每个模块：职责定义、接口契约（输入输出类型）、设计选项谱系、代表实现、权衡
3. 系统映射：各代表系统 = 模块配置的组合（更新版映射表）
4. 参考架构草案：控制面/数据面分离 + 配置驱动组合示例（类 VeRL yaml 风格）
5. 验证：reviewer subagent 审查抽象的完备性与一致性

## Stage 3 — 交付
- /mnt/agents/output/AutoResearch模块化统一抽象.md（主交付物）
- 如环境允许，转 docx 一并交付
