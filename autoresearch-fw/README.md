# AutoResearch 框架开发材料包

> 用途：驱动 Claude Code（或任何 coding agent）持续开发"可配置 AutoResearch 框架"的完整材料。
> 用法：将本目录作为仓库初始文档集提交到 git 仓库根目录，开发 agent 以 CLAUDE.md 为行为准则、SPEC.md 为技术宪法。

## 包内容

| 文件 | 角色 | 一句话说明 |
|---|---|---|
| **VISION.md** | 最高裁决依据 | 框架存在理由（治理层定位）、关键设计五条、开发四原则；一切范围争论的最终裁决层 |
| **RUBRIC.md** | 完工验收定义 | A 架构质量 7 条 + B benchmark 5 条 + C 治理 4 条 + D 研究新鲜度持续义务；全部达标 = v1.0 |
| **research/refresh/2026-10.md** | 首轮研究刷新 | RQGM（命中强制复审）/ HGM / DGM-H / OpenMLE（四算子外部印证）/ MASS；benchmark 版图确认 |
| **SPEC.md** | 技术宪法 | 六数据类型 + 九模块两横切层的 Protocol 规格 + 验收标准 |
| **CLAUDE.md** | 开发纪律 | 不变量、禁止事项、PR/复刻纪律、里程碑出口检查 |
| **REPLICATION.md** | 复刻规格 | AIDE/Arbor/OpenEvolve 的忠实度标准、环境固定方法、验收区间、报告模板 |
| **ZOO.md** | 接入契约 | TaskAdapter Protocol + MLE-Bench Lite 接入步骤与陷阱 + 后续 benchmark 表 |
| **REFERENCES.md** | 精读清单 | 按模块索引"实现时看哪个仓库的哪个文件"+ 论文速查表 |
| **ADAPT-v1.1.md** | 缺口适配规划 | 15 个新工作压力测试后的 G1-G4 适配动作与行动序列（不推翻现有代码） |
| **CODE-BORROWING.md** | 代码借鉴指南 | 15+ 开源仓库的分模块借鉴清单（克隆命令、文件级映射、反 from-scratch 纪律） |
| **M5-UNIFIED-v1.md** | M5 统一设计 | 统一记忆子系统：冻结内核（条目模型+生命周期状态机+证据日志）+ 五算子插件 + 经典系统 profile 化 + 双速调度 |
| **M8M9-UNIFIED-v1.md** | M8/M9 统一设计 | 统一评估器与准入门：冻结 EvalResult/Verdict/Receipt 模型与判定规则库（gate-not-rank/密封准入/票据失效）+ 六算子插件 + 六经典 profile + meta-gate 递归 |
| **M2-UNIFIED-v1.md** | M2 统一设计 | 统一算子子系统：四算子集纯函数签名 + 上下文配方（消费 M5 视图）+ 反馈带宽白/黑名单（消费 M8）+ 四段漏斗记账 + 多样性探针 + 自修改四件套 + 五经典 profile + C1–C12 公理 |
| **M6-UNIFIED-v1.md** | M6 统一设计 | 统一外部知识子系统：两车道物理隔离（ground/audit）+ gap 信号卡注入 + 三档 advisory 审计（永不阻断）+ FetchLedger/双率台账/注入引力探针 + ERA 联合入口 + 五 profile（含反例）+ D1–D10 公理 |
| **M4-UNIFIED-v1.md** | M4 统一设计 | 统一前沿/档案子系统：grid×islands 默认拓扑 + 三资格位（archived/parent_eligible/deliver_eligible）+ ArchiveHealthProbe 四族探针 + 驱逐可证伪（CI 下界+软删除）+ 跨 run 合并双前置 + M5 沉淀通道 + 六 profile + E1–E12 公理 |
| **M1-UNIFIED-v1.md** | M1 统一设计 | 统一策略子系统：f×g 亲本公式二元接口 + intent_queue 可拒绝分配意图 + 相位信号（Relay Gain 主判据）+ 停止动作查表（只消费 M9 Verdict）+ 策略谱系四元组 + 自我证成公约 + 六 profile + H1–H12 公理（v1.1：R1/R2 契约扩展） |
| **M3-UNIFIED-v1.md** | M3 统一设计 | 统一预算控制子系统：多币种账户族+版本化汇率 + reserve→settle 预扣结算 + 七科目决策因果链投影 + 对照科目四层制度链 + M3HealthProbe 四指标 + 三态拒绝分流 + 五 profile（含反例）+ J1–J10 公理 |
| **开发指南-v1.md** | 施工图纸层 | UNIFIED→代码的中间层：每模块一页（接口签名/默认行为/公理锚点/分歧锚点/公理即测试/初版不做）；当前含 M1 页 |
| **初版范围-v2.md** | ADR-0 范围定案 | **M0 内核路线**：6 概念内核（K1–K6）+ 扩展装回触发条件表；OpenEvolve fork + GEPA 首发；GEPA×骨架张力登记与翻案条件；成功标准（v1 已被取代） |
| **开发纪律-v1.md** | 开发纪律四件套 | CONTEXT.md 术语表 + 公理即测试 CI（T-H1 等 6 条）+ 曳光弹工单 #1 + 公理-宿主接缝对照表（S-1~S-6） |

## 配套材料（在 output 根目录，建议一并拷入仓库 docs/）

- `../docs/AutoResearch模块化统一抽象.md` —— 设计决策的完整证据链（为什么这样划分模块）
- `../docs/AutoResearch框架开发计划.md` —— ADR、里程碑、团队分工
- `../research/dim00-08/autoresearch_modular_dim00-08（9 个文件）` —— 九个机制单元的深读笔记（100+ 一手引用）
- `../research/dim00-08/autoresearch_modular_cross_verification.md` —— 收敛结论、冲突区、跨系统 insight
- `../docs/M5记忆与M6知识设计深度分析.md` —— M5/M6 设计空间全景（A–I 轴 + 分歧点 + F1–F8 失效模式）
- `../docs/M5记忆设计空间深度展开_A-I轴_分歧点_失效模式.md` —— 上述表格的逐格深挖（每个取值含机制/量化证据/选用条件）

## 给开发 agent 的启动指令（建议）

```
先通读 CLAUDE.md 与 SPEC.md 全文，然后：
1. 按 SPEC §1 实现 core/types.py（六数据类型 + 白名单校验）
2. 按 SPEC §3-§13 实现九个模块的 Protocol（不含实现）
3. 按 SPEC §2 写出主循环骨架（mock Policy/Evaluator 可跑通 100 cycle 契约测试）
完成上述 M0 内容后停下来报告，等待评审后再进入 M1。
```

## 人机分工

- **开发 agent**：按 SPEC 实现、跑测试、写复刻报告
- **架构评审（Kimi/人）**：每个里程碑评审复刻报告与架构变更；规格歧义由人裁决后写入 ADR
- **里程碑节奏**：M0 类型与 Protocol 冻结 → M1 框架版 AIDE → M2 框架版 Arbor → M3 进化系覆盖 + 发布（详见开发计划 §4）
