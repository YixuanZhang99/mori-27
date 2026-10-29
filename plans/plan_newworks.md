# 新增15个工作的九模块压力测试计划

目标：验证九模块+六类型的统一抽象对新一批工作的覆盖力，并帮助用户深入理解这些工作。

## 统一分析卡片（每个子代理必须对每个系统逐项回答）
- 系统一句话定位 + 出处（repo/论文/博客）
- M1 Policy/Coordinator：怎么选点/控制
- M2 Operator：有哪些算子（类型化动作），内部结构
- M3 BudgetController：预算与收敛
- M4 Frontier/State：拓扑（树/DAG/population/无）
- M5 Memory：语义层级（L1/L2/L3）与作用域
- M6 Knowledge：外部知识接入
- M7 Executor：执行体形态（role/hypothesis 两旋钮取值）
- M8 Evaluator：评估带宽（标量→trajectory 哪档）
- M9 AdmissionGate：准入/最终选择机制
- X1 溯源 / X2 HITL
- **装不下的机制**：任何九模块表达不了的设计（缺口信号）
- 对我们框架 SPEC 的启发（1-3 条）

## 分工（4 个并行 explore 子代理，输出到 /mnt/agents/output/research/）
- A: openresearch-cli, prime-agent, argus, OpenRSI, BigBang-v1（GitHub 仓库）
- B: dgm (jennyzzt/dgm), AIDE^2 + Simple Baselines (weco.ai blog)
- C: moss (hkgai-official/Moss), PAST-Bench (Gen-Verse/PAST-Bench)
- D: SEAL (2607.24300), MetaSkill-Evolve (2607.05297), EvolveNet (2608.04968)（arXiv）
- openevolve / shinkaevolve：已有 dim06 调研覆盖，由我直接补卡

## 汇总
产出 /mnt/agents/output/新增工作九模块映射表.md：映射大表 + 缺口清单 + 对 SPEC/REFERENCES 的修订建议
