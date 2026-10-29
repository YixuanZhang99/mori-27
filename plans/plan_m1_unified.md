# M1 Policy 模块统一梳理计划（六步方法论）

> 启动：2026-08-28。前序完成：M5 ✅ / M8+M9 ✅ / M2 ✅ / M6 ✅ / M4 ✅。M1 之后余 M3（轻量收尾）。

## M1 职责界定（调研前置假设）
- M1 = 全局搜索策略层：探索/利用权衡、亲本选择公式（M4 供信号、M1 出公式，O11/P7 契约已定）、相位调度（何时切阶段/何时停）、跨岛/跨任务的分配意图、退化自检的触发策略。
- 边界：预算记账/计费/配额执行归 M3 BudgetController（M1 出"分配意图"，M3 出"执行与节流"）；算子选择 π_op 归 M2-O2；准入裁决归 M9；档案结构归 M4。
- 已定接口：M4-P8（亲本采样骨架 0.7/0.2 + double selection，公式归 M1）；M2-O2（规则表默认，bandit 须挣得存在）；M9 noise_floor_zero（复杂度判定的噪声底来源）。

## Stage 1 — 调研（3 并行 subagent）
- A 组：策略设计空间（亲本选择公式族、探索/利用机制、相位调度、停止判据、分配策略）
  → research/m1/groupA_policy_design.md
- B 组：失效证据（贪心塌缩、探索预算失控、plateau 误判、相位切换失效、分配不公等）→ 候选公理
  → research/m1/groupB_policy_failures.md
- C 组：2025–2026 前沿（LLM 进化系统策略层新工作）+ 新轴候选 + 阴性发现
  → research/m1/groupC_policy_new.md

## Stage 2 — 轴系 + 逐格深挖（五段式模板沿用 m2/m4 先例）
## Stage 3 — 分歧裁决 + 公理 + 根因对账（四条不变量 + 候选 I-披露/I-可逆）
## Stage 4 — autoresearch-fw/M1-UNIFIED-v1.md + 索引更新
