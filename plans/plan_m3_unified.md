# M3 BudgetController 模块统一梳理计划（六步方法论，轻量规模）

> 启动：2026-08-28。前序完成：M5 ✅ / M8+M9 ✅ / M2 ✅ / M6 ✅ / M4 ✅ / M1 ✅。M3 为收尾模块。

## M3 职责界定
- M3 = 预算执行层：记账/计费、配额与节流、intent_queue 消费（M1→M3 唯一通道，G13 契约已定）、预算科目体系（含自我证成对照保留科目 5–10%）、成本台账上报。
- 边界：分配意图归 M1（M3 可拒绝、不回算策略）；算子定价消费 M2-O19 op tax；评估定价消费 M8M9 eval-tax；档案经济学为 M4 横切约束。
- 已定接口：M1-G13 AllocationIntent/IntentReceipt；M2-O19 op tax 上报；M8M9 eval-tax；M1-G17 不可裁决→预算向重评转移。

## Stage 1 — 调研（2 并行 subagent）
- A 组：设计空间+前沿合并（预算模型/计费粒度/配额机制/节流策略/跨科目转账/成本台账）
  → research/m3/groupA_budget_design.md
- B 组：失效证据 → 候选公理 → research/m3/groupB_budget_failures.md

## Stage 2 — 轴系 + 深挖（单批或两批，视轴数）
## Stage 3 — 分歧裁决 + 公理 + 根因对账
## Stage 4 — autoresearch-fw/M3-UNIFIED-v1.md + 索引更新 + 九模块闭环总结
