# plan_m2_unified.md — M2 Operator 统一设计梳理

> 目标：对 M2（算子：变异/交叉/重写/反思等产生新候选的机制）执行六步流程，产出《M2-UNIFIED-v1.md》。
> 排序依据：M2 是 M5/M8M9 之后设计空间最异质且素材最齐的模块（dim 调研 + 15 工作压力测试 + CODE-BORROWING 均大量覆盖）。

## Stage 1 — 调研（3 个并行 subagent）
- **组 A：M2 算子设计空间（经典+自进化）**：重挖既有材料（dim01/02/03、newworks A/B/E 组、CODE-BORROWING 的 AIRA-dojo 纯函数签名与 OpenRSI 四算子）+ 补 2025-2026：LLM 变异算子（GEPA/EvoPrompt/FunSearch/openevolve diff evolution）、程序交叉、反思算子、算子组合策略。
- **组 B：算子失效证据**（公理反推原料）：算子导致的退化案例（多样性崩塌、reward hacking 被算子放大、Simple Baselines 证明花哨算子无增量、AIDE² 自改改坏反作弊层、context 污染变异、diff 应用失败率等）。
- **组 C：2026 前沿扫描（查新轴）**：可学习算子（RL 训练的变异策略、ShinkaEvolve BanditBase 算子选择）、算子的谱系与治理、meta-evolution、算子组合的自动化搜索、代码 diff 模型的算子化。

## Stage 2 — 轴系建立 + 逐格深挖（1-2 个 subagent）
对标 M5/M8M9：取值表（机制展开|量化证据|何时选）+ 隐藏结构 + 反直觉结论。

## Stage 3 — 分歧裁决 + 失效→公理（1 个 subagent）
含与既有框架级不变量（I-α/I-β/I-LLM/I-谱系）的对账。

## Stage 4 — 统一设计文档（1 个 writer subagent）
《M2-UNIFIED-v1.md》进 autoresearch-fw/；四层骨架；兼容性验证 ≥3 经典 profile（候选：openevolve diff 进化 / GEPA 反思变异 / DGM 自修改 / OpenRSI 四算子 / FunSearch）；更新 README 与 ADAPT。

## 纪律
同 M5/M8M9：数字只出自卡片；推断标【推断】；失效证据不足处允许"公理少、profile 多"；冻结内核接口对接六数据类型；产出引用用新目录结构（research/m2/）。
