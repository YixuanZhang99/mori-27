# AutoResearch 框架项目产出总索引

> 最后整理：2026-08-26。本目录是 AutoResearch 可配置框架项目的全部产出。

## 目录结构

```
output/
├── README.md            ← 本文件（总索引）
├── autoresearch-fw/     ★ 框架包：交付给开发 agent（Codex）的完整材料
├── docs/                ★ 交付级综合文档（阅读入口）
├── research/            研究卡片与深挖（docs/ 的证据层，按调研轮次分子目录）
├── plans/               各轮任务的工作计划（过程性）
└── papers/              原始论文与源码材料（调研输入）
```

## 快速导航：我要找什么？

| 需求 | 去哪里 |
|---|---|
| 给 Codex 的开发材料（行为规范/技术宪法/复刻规格/借鉴指南/适配规划/统一设计） | `autoresearch-fw/`（其 README.md 有包内导航） |
| 了解九模块抽象的设计依据 | `docs/AutoResearch模块化统一抽象.md` |
| 了解整体开发计划与里程碑 | `docs/AutoResearch框架开发计划.md` |
| 15 个新工作的压力测试结论（G1–G4 缺口） | `docs/新增工作九模块映射表.md` |
| M5 记忆 / M6 知识的设计空间全景 | `docs/M5记忆与M6知识设计深度分析.md` |
| 上述全景的逐格深挖（A–I 轴+分歧+F1–F8 失效模式） | `docs/M5记忆设计空间深度展开_A-I轴_分歧点_失效模式.md` |
| M5 记忆模块统一实现规格 | `autoresearch-fw/M5-UNIFIED-v1.md` |
| M8 评估 + M9 准入门统一实现规格 | `autoresearch-fw/M8M9-UNIFIED-v1.md` |
| M2 算子模块统一实现规格 | `autoresearch-fw/M2-UNIFIED-v1.md` |
| M6 外部知识模块统一实现规格 | `autoresearch-fw/M6-UNIFIED-v1.md` |
| M4 前沿/档案模块统一实现规格 | `autoresearch-fw/M4-UNIFIED-v1.md` |
| M1 策略模块统一实现规格 | `autoresearch-fw/M1-UNIFIED-v1.md` |
| M3 预算控制模块统一实现规格 | `autoresearch-fw/M3-UNIFIED-v1.md` |
| 各模块深挖的证据卡片（量化数字的出处） | `research/` 对应子目录 |

## research/ 子目录（按调研轮次）

| 子目录 | 内容 | 服务的交付文档 |
|---|---|---|
| `dim00-08/` | 第一轮：九个机制单元深读笔记 + 交叉验证（100+ 一手引用） | 模块化统一抽象、SPEC |
| `newworks15/` | 第二轮：15 个新工作的九模块映射卡片（A–E 五组） | 新增工作九模块映射表、ADAPT-v1.1 |
| `m5m6/` | 第三轮：M5/M6 调研卡片（5 组）+ 逐格深挖三件套（轴 A–E / 轴 F–I+分歧 / 失效 F1–F8）+ M6 轴系定稿与深挖 | M5/M6 两份分析文档、M5-UNIFIED-v1、M6-UNIFIED-v1 |
| `m8m9/` | 第四轮：M8/M9 调研卡片（4 组）+ M8/M9 轴系深挖 + 分歧裁决与公理 B1–B11 | M8M9-UNIFIED-v1 |
| `m2/` | 第五轮：M2 算子调研卡片（3 组）+ 19 轴定稿 + 逐格深挖三批 + 分歧裁决与公理 C1–C12 | M2-UNIFIED-v1 |
| `m4/` | 第六轮：M4 前沿/档案调研卡片（3 组）+ 20 轴定稿 + 逐格深挖三批 + 分歧裁决与公理 E1–E12 | M4-UNIFIED-v1 |
| `m1/` | 第七轮：M1 策略调研卡片（3 组）+ 18 轴定稿 + 逐格深挖三批 + 分歧裁决与公理 H1–H12 | M1-UNIFIED-v1 |
| `m3/` | 第八轮：M3 预算调研卡片（2 组）+ 14 轴定稿 + 逐格深挖 + 分歧裁决与公理 J1–J10 | M3-UNIFIED-v1 |

## 维护规则

1. **交付级文档**（给人类/开发 agent 读的定稿）放 `docs/` 或 `autoresearch-fw/`，不放根目录。
2. **过程性卡片**（subagent 调研产出、深挖稿）放 `research/<主题>/`，一轮调研一个子目录。
3. **工作计划**放 `plans/`，完成后不删（留作过程记录）。
4. 框架包 `autoresearch-fw/` 会被整体拷入开发仓库，**内部相对引用必须自洽**；引用包外文件一律用 `../docs/`、`../research/` 前缀。
5. 新文档完成后：更新本索引的导航表，并检查交叉引用路径。

## 模块统一设计进度（M5 方法论逐模块推广）

| 模块 | 状态 | 产物 |
|---|---|---|
| M5 Memory | ✅ 完成 | autoresearch-fw/M5-UNIFIED-v1.md |
| M8+M9 | ✅ 完成（捆绑） | autoresearch-fw/M8M9-UNIFIED-v1.md |
| M2 Operator | ✅ 完成 | autoresearch-fw/M2-UNIFIED-v1.md（素材：research/m2） |
| M6 Knowledge | ✅ 完成 | autoresearch-fw/M6-UNIFIED-v1.md（素材：research/m5m6） |
| M4 Frontier | ✅ 完成 | autoresearch-fw/M4-UNIFIED-v1.md（素材：research/m4） |
| M1 Policy | ✅ 完成 | autoresearch-fw/M1-UNIFIED-v1.md（素材：research/m1） |
| M3 Budget | ✅ 完成 | autoresearch-fw/M3-UNIFIED-v1.md（素材：research/m3） |

**九模块统一设计全部闭环**（M7 按既定决策不做深梳理，走 CODE-BORROWING 直接借鉴）。框架级沉淀：不变量 I-α/I-β/I-LLM/I-谱系（四条既有）+ 候选 I-披露/I-可逆（均获四模块投影验证，待框架定稿上收）+ 自我证成公约（条款 a–g，M3 增列预算侧 f/g 条款）。
| M7 Executor | 不做深梳理（工程问题，走 CODE-BORROWING 直接借鉴） | — |
