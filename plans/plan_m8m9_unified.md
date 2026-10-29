# plan_m8m9_unified.md — M8 Evaluator + M9 AdmissionGate 统一设计梳理

> 目标：对 M8/M9 执行 M5 方法论六步流程（饱和调研→轴系→逐格深挖→分歧裁决→失效反推公理→统一实现+兼容性验证），产出《M8M9-UNIFIED-v1.md》。
> 捆绑理由：M8 管度量、M9 管裁决，公理 A3（LLM建议/确定性终裁）即两者分界；失效证据链（F8 评估幻觉、评审器偏置、误杀）跨两模块。

## Stage 1 — 饱和调研（4 个并行 explore subagent，本阶段）

- **组 A：M8 评估设计空间（学术+自进化）**
  既有素材：dim06 笔记、15 工作卡片（openevolve 级联评估 / shinka public-private / DGM 自判 buggy / SEAL 密封门 / PAST-Bench 机制分 / MOSS 三级预算）——需读卡片重挖评估维度。
  新调研：2025-2026 评估设计新工作（cascade evaluation、nested/meta-evaluation、verifier 设计、statistical reliability：多次运行聚合/置信区间/种子预算）。
  产出：/mnt/agents/output/research/m8m9_groupA_eval_design.md

- **组 B：评估失效证据（公理反推的原料）**
  既有：F8 深挖（LoCoMo 6.4%、judge 62.8%）、2607.07436 评审器偏置、AI-Scientist 误杀 9/10。
  新调研：reward hacking / benchmark gaming / judge bias / LLM-as-judge 可靠性 / eval contamination / pass@k 方差 的 2025-2026 系统证据。
  产出：/mnt/agents/output/research/m8m9_groupB_eval_failures.md

- **组 C：M9 准入门设计空间**
  既有：MOSS 三阶段门、SEAL 1-bit 外生门、EvolveNet scope-typed merge、prime-agent evidence gate、ShinkaEvolve 契约。
  新调研：acceptance/admission/gating 在自进化、AutoML、A/B 测试传统（sequential testing、conservative gate、multiplicity 校正）、promotion criteria 的 2026 工作。
  产出：/mnt/agents/output/research/m8m9_groupC_gate_design.md

- **组 D：2026 前沿扫描（查新轴）**
  对标 M5 的轴 F–I 发现过程：扫 2026 H1 评估/门控/治理新产品与新论文（eval-ops、LLM judge 产品化、agent eval 平台、statistical rigor 运动），找"轴系外的维度"。
  产出：/mnt/agents/output/research/m8m9_groupD_frontier.md

## Stage 2 — 轴系建立 + 逐格深挖（2 个并行 subagent）
- M8 轴系+深挖（对标 A–I 深度：取值表|机制展开|量化证据|何时选 + 隐藏结构 + 反直觉结论）
- M9 轴系+深挖 + M8×M9 耦合点（A3 公理的分界线在哪）

## Stage 3 — 分歧点 + 失效模式（1 个 subagent）
- M8/M9 经典分歧（如：内生vs外生验证器、单次vs多次评估、严格门误杀vs宽门污染…）各自双方最强论据+裁决规则
- 失效模式集（F8 扩展 + gate 特有失效）解剖 + 反推公理候选

## Stage 4 — 统一设计文档（lead 整合或 1 个 writer subagent）
- 《M8M9-UNIFIED-v1.md》：公理（每条指认失效证据）+ 四层骨架（冻结内核/算子插件/profile/调度）+ 兼容性验证（≥3 经典系统 profile 化：openevolve级联 / PAST-Bench机制分 / SEAL密封门 / MOSS三门 / ShinkaEvolve契约…）+ 与 ADAPT 的衔接分期
- 更新 README.md 与 ADAPT-v1.1.md

## 纪律
- 先查前提(b)：失效证据不足的维度允许"公理少、profile 多"，不造公理
- 数字只出自卡片/一手来源，推断标【推断】
- 骨架与 M5-UNIFIED 同款四层；冻结内核接口=六数据类型
