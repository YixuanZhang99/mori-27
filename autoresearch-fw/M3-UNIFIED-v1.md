# M3-UNIFIED-v1.md — 统一预算控制（记账/配额/科目/对账）模块设计文档

> 依据：`../research/m3/m3_axes_final.md`（14 轴定稿 N1–N14）、`../research/m3/m3_deepdive.md`（逐轴五段式深挖）、`../research/m3/m3_分歧_公理.md`（七分歧裁决 + 公理 J1–J10 + 根因对账 + 自我证成公约预算侧修订建议 (f)(g) + 契约修订建议 R1–R4）、`../research/m3/groupA_budget_design.md` / `groupB_budget_failures.md`（原始调研）。结构与风格对齐 `M1-UNIFIED-v1.md` / `M2-UNIFIED-v1.md` / `M4-UNIFIED-v1.md` / `M8M9-UNIFIED-v1.md`。所有数字引自上述底稿，不确定处标【推断】；AIDE² 数字一律标【厂商博客级，非同行评审，关键数字未见独立复核】。
> 定位：M3 BudgetController 的最终形态设计。回答一个问题——**FunSearch 的墙钟账户 / AIDE 的节点数上限 / MEMOIR 的评估次数（B=16、<$1）/ AIRA-dojo 的 remaining_time / agentgateway 的金融级预扣结算这些预算设计能否被同一个实现兼容？答案：能。它们之间的差异全部是"币种族 + 配额执行模式 + 科目体系 + 上限语义"的配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 BudgetLedger/CurrencyAccount/ReserveRecord/CostAccount/M3HealthProbe/RejectNotice 数据模型与"只报价不决策"边界协议、reserve→settle 预扣结算、append-only 台账与口径版本戳（内核，不可换）+ 四指标健康仪表盘与效率-健康分轴（内核，永驻）+ 价目表/降级档/profile 一等配置（可热替换，对照可执行）+ 十四轴编译成的 profile（配置）+ 双速调度（sync 禁 LLM，运行时）**。
> 模块定位公理（GB 根因 3）：**M3 是失效放大器而非失效点**——M3 掌握其他所有模块的资源开关，其失效不表现为自身异常而表现为所有他模块的系统性降级（GEPA 的账本从来是平的，85–90% 错配存在于科目结构而非数字）。因此 M3 的健康不能由"账平"自证，必须由独立于记账逻辑的结构性比率外证。M3 只报价、预扣、结算、拒绝；不制定价目表（归 M2/M8M9）、不做降档决策（归 M1 重发）、不做准入裁决（归 M9）。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条既有框架级不变量 + 两个候选 + 自我证成公约预算侧条款（f)(g)

以下四条不变量横跨 M5/M8/M9/M2/M1 等模块独立出现（与 M1-UNIFIED §0.0 逐字一致）；第五候选 I-披露由 M2 提出；第六候选 I-可逆由 M4 提出（M1 完成第四投影验证）。M3 的贡献是三个物化形态 + 一次 I-β 投影验证，**不贡献新候选不变量**（根因对账见 §0.3）：

1. **不变量 I-α（锚点存在性）**：→ M3 侧投影：**标准币锚定（N14）是预算层的锚点组件**——跨期对照的"等预算"以不可漂物理量（有效调用数×上下文长度，或固定基准模型等价 token）定义，价格漂移的优化压力（供应商调价、模型档切换）无法修改标准币的锚。汇率表版本化（不可漂的口径历史）与 M8 Receipt 锚点纪律同构。
2. **不变量 I-β（质量指标一等化）**：→ **M3 侧投影（第五投影确认，强度最高一环）**：M1 对账已建立"健康不可内观测"四模块同型链（M9 闸门判别质量/M2 算子产率/M4 档案健康/M1 策略健康）；M3 补上第五环且是强度最高的一环——前四环的失效至少显形于自身账上，M3 的失效连自己的账都是平的（"裁判不能给自己计分"的预算层实例）。**M3HealthProbe 四指标（有效预算率/对账差额率/隐性科目占比/对照兑现率）全部是结构性比率而非账务勾稽**——这反向论证了 I-β 的必要性条件：质量指标必须独立于被测机制的内部一致性。另：N11×N13 分轴（效率管"值不值"、健康管"自己坏没坏"）是 I-β"按用途分离物化"形态（M1 已记）的预算层实例——单读效率指标=奖励预算侧作弊。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：→ M3 侧投影：reserve/拒绝/熔断/转账全部为确定性规则执行（成本计算与配额比较是算术不是判断）；LLM 在 M3 的唯一合法位置是归因报告撰写辅助（不判定）——预算执行路径无 LLM 终裁（§4 矩阵中 LLM 档几乎不存在的原因）。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：→ M3 侧投影（**物化形态贡献：成本归因谱系**）：I-谱系要求"记录带谱系"——M3 回答"成本记录的谱系键是什么"：不是模块名（代码结构谱系），而是 intent 链（决策因果谱系）。AllocationIntent.intent_id/policy_version 进台账 schema（N10）即 I-谱系的预算层物化；"谱系"从候选/策略版本扩展到**成本归因链**（intent→算子→失败→debug），每一笔花费都能回答"谁的决策"。作废 reserve 追加 reserve_released 条目而非删除（append-only，硬证据不删除）。
5. **候选不变量 I-披露（信号通道最小披露）【候选，M2 提出，待框架级确认】**：→ M3 侧投影：M3→M1 只允许 IntentReceipt 与块级余量摘要两条信道（双喂口径同源，N12）；M3→M2 只经算子签名 remaining_budget 字段；prompt 级预算提示至多软引导档，不构成旁路执行信道（TALE：建议档过紧反推高消耗）。
6. **候选不变量 I-可逆（不可逆操作滞后于证据成熟度）【候选，M4 提出】**：→ M3 侧投影（预算层执行面）：配额触顶后档案驱逐/快照复活/谱系记代等不可逆操作的配额消耗须单独审批（J4 级联冻结）；硬触顶进入只读结算态——M3 是 I-可逆在预算层的**执行机构**（不可逆操作都要花预算，预算闸是最硬的可执行层）。

**自我证成公约预算侧条款（修订建议稿，待框架定稿裁决）【推断】**：在 M1-UNIFIED §0.1 公约五条（a–e）基础上，根因对账（§0.3 根因 2）揭示公约的预算侧盲区——**公约不设防预算层则公约本身失效**，增列：

- **(f) 对照预算的制度保障四层链为公约级要求**（物化=J8，**执行机构=M3**）：比例锁定（启动时与主科目同时锁定，建议 5–10%【推断，无文献定值】）+ 例外程序（挪用须显式记录{谁批的/理由/补跑计划}）+ 过期降权（连续 N 期未补跑→全部待证声明自动标注"对照已过期"）+ 兑现率监控（入 N13 健康指标广播全框架）。对照预算保留科目的执行机构是 M3，公约条款（a)–(e) 的"对照不可移除"若无预算侧锁定则被"这期预算紧先保主线"的局部理性击穿（保险悖论）。
- **(g) 对照公平性的预算前提显式化（防"压评估抬噪声底"绕过条款，物化=J6/J7）**：跨期重跑退化基线的"等预算"以标准币定义；对照运行期的评估保底（噪声底低于最小可裁决改进量，由 M8 噪声测量定值）不可被主线节流挪用——公约的举证门槛"同预算对照 + 增量超 M8 噪声底"以预算等价性为前提，而**压评估=抬噪声底=让被证组件更易"通过"对照**是"不动任何代码就使评估失效"的合法路径（B-5），公约的显著性判据可被预算侧静默绕过，本条款予以封闭。
- **管辖范围追加**：标准币定义与锚传承协议（基准模型退役后的换锚规则——空白，见 §9-5）、有效预算率的跨 run 可比性声明格式。

### 0.1 公理 J1–J10（失效证据 → 内核物化）

> 合并规则：B-B1+B-B2→J1；B-B3+B-B4→J2；B-B8+B-B9→J6；B-B10+B-B11→J7；B-B12+B-B13→J8；B-B14+B-B15→J9；B-B16+B-B17→J10；B-B5→J3、B-B6→J4、B-B7→J5（1:1 落位）。降级：**J7 的边际回报均衡化部分为 SHOULD**（均衡化协议无实现先例）、**J10 的双向隔离激励分析部分为 SHOULD**（机制推演无对照实验）。17 条候选全部保留，无降级为实现建议的条目。

| # | 公理 | 强制级别 | 失效证据指认（关键数字） | 违反检测 |
|---|---|---|---|---|
| J1 | **科目体系必须是决策因果链的投影，隐性科目一等化，跨模块补贴双记**——科目集 {explore, exploit, reeval, control, handoff, repair, overhead} 按决策成因划分；隐性科目（reeval 验证表/repair/overhead）有独立配额与占比报警线，超限触发归因报告而非静默记账；凡模块 A 决策在模块 B 名下产生成本，台账双记（B 记账、A 记消耗） | MUST | GEPA 85–90% rollout 在验证表维护隐性科目、账上记作"评估"（6,438/678/6,858/2,157 vs 737/79/558/269，验证/训练比 8.7–8.9×，arXiv:2507.19457【原文明确无成本控制】）；AIDE² 外环 ~90% 拒绝率=从未入表的沉没科目【厂商博客级】 | 按模块名划账=架构评审拒绝；隐性科目无独立配额=构建期报错；跨模块成本转移无双记条目=审计不通过 |
| J2 | **成本穿透：嵌套深度无计费豁免，固定开销显式化**——嵌套算子/子调用沿调用链上卷实际消耗，per-candidate 成本含嵌套展开树；无上卷能力的调用按成本上界预扣；固定开销（启动/加载/落盘/谱系）独立科目并摊销；有效预算率为一等健康指标 | MUST | M2-O16×O19"嵌套算子成本必须进漏斗核算否则预算失控"【设计者预言】；aider 重试率 15–28%；AIDE₈₅ 进化出"bug rate>15% 才挂 debug"反证 debug 开销默认无约束【厂商博客级】 | 算子无上卷能力且未按上界预扣=构建期拒绝；固定开销未科目化=审计不通过；有效预算率时序缺失=构建期报错 |
| J3 | **截断 run 是一等数据，不得混记或丢弃**——被节流终止的 run/代/候选必须带截断归因标记（触顶的配额维度、已消耗量、进行到的相位）入台账；统计层消费完成数据时须声明截断处理方式（删失/加权/独立报告），混记视为数据污染 | MUST | 被截断 run 系统性是"探索更激进/任务更难"的 run（非随机缺失，GB B-3a）；FunSearch 4h 固定重置被 PDE-SHARP 原样继承（arXiv:2511.00183） | 截断 run 无归因标记=构建期拒绝；统计报告无截断处理声明=评审退回 |
| J4 | **软阈广播+硬熔断只读结算态：超限模式广播与级联冻结**——配额触顶 80% 软阈即向 intent_queue 与各模块广播"收敛模式"；驱逐/重置/快照复活等不可逆操作的配额消耗须单独审批；硬触顶后进入只读结算态，超额状态下执行不可逆操作=运行期拦截；"仅监控告警"为反模式永久禁止（alert 是验尸报告不是护栏） | MUST | 2025-11 四个 LangChain agent 死循环 264h 烧 $47k（无 per-agent 硬上限+无法调用前拦截，Waxell 2026-04）；Helicone/LangSmith/Braintrust 全为事后监控 | 无软阈广播通道=构建期拒绝；超额状态下不可逆操作且无审批记录=运行期拦截+审计不通过 |
| J5 | **配额计量单位必须对齐被控资源**——配额声明必须指明计量维度（调用数/token/美元/墙钟）及其与搜索进度（有效候选数）的换算率；换算率随（模型×供应商）漂移时，硬上限须在漂移维度上重标定 | MUST | aider 重试率 15–28%：1000 次调用配额对应 token 量波动 ±28%——配额以调用数计而消耗以 token 计，硬上限在错误维度收紧；promptolution"同额美元≠同额搜索深度"（CAPO 93.7 vs 78.1） | 配额声明无计量维度与换算率=配置评审拒绝；供应商/模型变更后配额未重标定且无豁免=审计不通过 |
| J6 | **台账值必带口径版本戳 + 跨期对照以标准币为锚**——每条成本记录附（供应商, 模型版本, tokenizer/计数器版本, 单价表版本, 日期）五元组；无版本戳历史账目跨 run 比较降权或禁用；"等预算"以不可漂量定义（有效调用数×上下文长度，或标准币=固定基准模型等价 token）；换算函数本身版本化（不重写旧账、但可重译——append-only 与可比性的唯一相容解） | MUST | aider 同模型 DeepSeek-V3 换供应商 diff 合规率 98.7%→84.0%（双漂混淆归因，2024-09~2025-01）；LLM API 2024–2026 多次数量级调价；M2-O3"换供应商=触发台账重置"先例 | 台账记录缺版本五元组任一=构建期拒绝；跨期对照以裸美元/token 定义等预算=评审退回 |
| J7 | **噪声底预算是不可压缩的保底科目 + 科目边际回报均衡化**——任何节流方案必须为评估/重评保留使噪声底低于"最小可裁决改进量"的保底预算（由 M8 噪声测量定值）；总预算低于保底时 M3 须**拒绝开跑**并报告"预算不足以产生可证结论"，而非静默压缩评估；预算分配应按各科目已测边际回报做均衡，一手证据出现时预算结构须随证据再平衡（SHOULD：均衡化协议无实现先例，边际回报测量本身待建） | MUST（保底）/ **SHOULD**（均衡化） | SB P(Shinka>IID RS)=0.49（arXiv:2602.16805）为举证门槛；M8 噪声分解"预测噪声>数据噪声"（arXiv:2512.21326）；Archive-Sampling 显著优于固定采样（arXiv:2302.00463）；压评估抬噪声底=公约显著性判据的预算侧绕过路径（B-5） | 节流方案压缩 reeval 至保底以下=运行期拦截；低于保底仍开跑=审计不通过；均衡化长期未重估且无豁免=降级警告 |
| J8 | **对照科目宪法化：比例锁定 + 例外程序 + 过期降权 + 兑现率监控**——退化基线重跑/组件消融/锚点重评的配额在 run 启动时与主科目同时锁定（总预算×固定比例，建议 5–10%【推断，无文献定值】），禁止余额分配；挪用须显式例外记录{谁批的/理由/补跑计划}；连续 N 期未补跑触发结论降权（"对照已过期"标注）；兑现率入 N13 常驻报告 | MUST | ShinkaEvolve 三消融为生态稀有例外（arXiv:2509.19349）；对照科目全生态零实现（GA 前沿空位 1）；连续挪用 N 期后"无人记得最后一次有效对照是何时"（GB B-6）；保险悖论 | 对照科目未启动时锁定=构建期拒绝；例外挪用无审批条目=审计不通过；对照过期标注未广播=报警 |
| J9 | **intent-消耗对账闭环常驻 + 对账差额显式归宿**——每个 intent 到期必须结算（承诺份额 vs 实际消耗 vs 产出差）；对账报告为 M1 下一代分配的强制输入；无结算的 intent 不得续约；intent 层与 call 层差额必须入账到具名科目（重试损耗/嵌套展开/固定开销/未兑现份额），"差额"本身不得作为合法科目；差额率（\|差\|/总预算）为一等健康指标 | MUST | GEPA 85–90% 以"论文附录数字"而非"运行期对账报警"出现=对账层缺失的直接证据；aider 重试率 15–28% 使份额→token 换算率漂移无监控；M1 拿失真反馈做下一代分配（GB B-7） | intent 到期无结算记录=审计不通过；份额分配反馈不来自对账=架构评审拒绝；台账出现无名差额科目=构建期报错 |
| J10 | **修复类消耗按决策归因入账 + 复活候选沉没成本隔离**——debug/重试/回滚/复活消耗必须归因到引发它的决策（产出失败候选的算子 intent、触发自修改的配置版本）并沿链上卷；无归因的修复消耗记"系统损耗"科目并常驻报告占比，超阈触发审计；回滚链长度设配额上限，超限冻结该自修改 intent；复活候选沉没成本既不计入"已投资价值"也不计入成本-产出比分母（SHOULD：双向隔离的下游激励分析为机制推演，无对照实验） | MUST（归因上卷+回滚链配额）/ **SHOULD**（双向隔离激励分析） | AIDE₈₅ 进化出"bug rate>15% 才挂 debug"——fix-vs-regenerate 分界点真实存在且远离两个朴素默认【厂商博客级】；AIDE² 反作弊层被自修改改坏+修复无科目（E2 预算侧投影）；回滚链无配额可烧预算于改坏-回滚循环 | 修复消耗无归因链且无系统损耗入账=审计不通过；回滚链超配额未冻结=运行期拦截；沉没成本计入价值或分母且无豁免=降级警告 |

### 0.2 根因对账备注

GB 三共同根因全部被既有框架覆盖（详见 m3_分歧_公理.md 任务三）：根因 1（科目=决策因果链投影）→ **I-谱系预算层物化**（成本归因谱系，不上收新原则）；根因 2（预算测量值与评估分数同构漂移）→ I-β 一半覆盖（版本戳/标准币与 M8 Receipt 同构）+ **揭示自我证成公约预算侧盲区**（公约修订建议 (f)(g)，§0.0）；根因 3（激励不对称达极致 + M3 失效放大器）→ **I-β 第五投影确认** + 质量指标独立性必要条件论证。M3 不贡献新候选不变量——与 M1 的结论同型。

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（双速调度 sync 禁 LLM / 超限模式广播协议 /        │
│          双喂分发协议 / 对账结算调度）                                │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  操作面接口：quote_reserve / settle / reject_route /          │
│          throttle_broadcast / transfer / reconcile /                 │
│          report_efficiency / health_probe                            │
│          每操作面三类实现：确定性 | LLM 辅助 | 自适应                   │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：reserve→settle 预扣结算（TALE 合理区间+押金档）     │
│          + 硬+软上限（软阈广播收敛相位+硬熔断只读结算态+级联冻结）      │
│          + 七科目决策因果链投影（control 四层保障链宪法化）             │
│          + 转账白名单事件触发 + 修复按决策归因+沉没隔离                │
│          + intent-call 对账闭环（差额显式归宿）+ 双喂同源分发          │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：BudgetLedger / CurrencyAccount /               │
│          ReserveRecord / CostAccount / M3HealthProbe / RejectNotice  │
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（边界协议/预扣结算/版本戳 self_mutable=false）
         ↑ Layer 3 标注 evolvability: strategies_only（降级档组合/效率指标档位可配置）
         ↑ 经典系统 = profile = Layer 3 策略选择 + Layer 4 配置
```

**M3 的模块分工**（轴系原则 2，刚性边界）：M3 管"预算的记账、预扣、结算、拒绝、节流"（资源开关的执行机构）；**分配意图归 M1**（M3 只报价不决策——预算不足以 rejected_budget 回流 M1 重发低档，档位选择是分配语义，M1 单一作者）；**定价归 M2/M8M9**（op tax 与 eval-tax 价目表，M3 只消费不制定）；**准入归 M9**（admission_outcome 是 cost-of-pass 的 R 来源，M3 不判定）；**噪声底测量归 M8**（reeval 保底定值的唯一来源）；**修复消耗的源头归因归 M2-O12/M4 buggy_leaf**（提供归因链）；**台账 append-only 入 X1**。跨界处只留接口不留轴。

---

## 2. Layer 1：冻结数据模型

六个新类型。与既有类型的挂接：CurrencyAccount 消费 M2-O19 op tax 与 M8M9 eval-tax 价目表（只消费不制定）；ReserveRecord/RejectNotice 挂接 M1 AllocationIntent/IntentReceipt 契约（R1 修订后的分币种 budget_estimate）；CostAccount 七科目枚举与 M1 cost_account 同步扩枚举（R2）；M3HealthProbe 与 M4-P19 探针同构、向全框架广播；全部台账条目 append-only 入 X1。

```python
# core/budget/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

BudgetUnit = Literal["token", "usd", "eval_count", "node", "wallclock"]  # N1 五单位封闭枚举
# 墙钟账户带独立 ttl 语义：不可囤、不可转移，到期即蒸发（N1 深挖，×N8 转账白名单不覆盖 wallclock）

# ---- 口径版本戳（N14：台账值是有时效有版本的测量值，不是物理常数）----
@dataclass(frozen=True)
class AccountingStamp:                       # ★每条成本记录强制携带的版本五元组（J6）
    supplier: str                            # 供应商（aider 98.7%→84.0% 双漂教训：与模型版本成组出现）
    model_version: str
    tokenizer_version: str                   # tokenizer/计数器版本（token 计数漂移维度）
    price_table_version: str                 # 单价表版本（M2 op tax / M8M9 eval-tax 价目快照）
    date: str                                # 记录日期
    # 缺五元组任一的记录=构建期拒绝；无戳历史账目在跨 run 比较中降权或禁用

# ---- 多币种账户族（N1：跨币种只在显式汇率层折算，账本内不混记）----
@dataclass
class CurrencyAccount:
    unit: BudgetUnit
    ceiling: float                           # 上限；须声明计量维度与→搜索进度换算率（J5）
    spent: float = 0.0
    reserved: float = 0.0                    # 预扣占用（reserve→settle 生命周期）
    floor: float = 0.0                       # 保底档（J7：reeval 由 M8 噪声测量定值；低于保底拒绝开跑）
    conversion_to_progress: Optional[float] = None  # 本币种→有效候选数的换算率声明（J5）

@dataclass(frozen=True)
class ExchangeRateTable:                     # 版本化汇率表（N1×N14 刚性联动）
    table_version: str                       # 汇率表版本变更事件入 X1；未版本化的汇率表=裸数字记账反模式
    rates: dict                              # (from_unit, to_unit) -> rate；token↔USD 供应商价目驱动，
                                             #   eval↔USD 由 eval-tax 档表驱动
    standard_coin_anchor: str = ""           # 标准币锚定声明（固定基准模型等价 token）；
                                             #   美元/token→标准币的换算函数本身版本化
                                             #   （不重写旧账、但可重译——append-only 与可比性的唯一相容解）

# ---- 台账（N2/N10：append-only，三级键，policy_version 一等字段）----
LedgerLevel = Literal["call", "op", "block"] # 三级键：call 防漏、op 归因（→M2-O20）、block 决策（→M1）

@dataclass
class LedgerEntry:
    entry_id: str
    level: LedgerLevel
    account: str                             # 科目（CostAccount 七枚举）
    block_id: str                            # 三级键第二级（对齐 AllocationIntent.block_id）
    op_kind: str = ""                        # 三级键第三级：op_kind×model_tier
    model_tier: str = ""
    eval_tier: str = ""
    unit: BudgetUnit = "token"
    reserved: float = 0.0
    settled: float = 0.0
    intent_id: str = ""                      # ★成本归因谱系键①：决策因果谱系（I-谱系预算层物化）
    policy_version: str = ""                 # ★一等字段②：成本可按签发策略版本切片
                                             #   （EvoX J 信号同构；M3 对 M1 策略进化的唯一反馈通道【推断】）
    admission_outcome: Optional[bool] = None # 准入结果绑定（cost-of-pass 的 R 可在台账内计算的前提）
    stamp: Optional[AccountingStamp] = None  # ★口径版本五元组（J6，缺=构建期拒绝）
    truncation_marker: Optional[dict] = None # J3：{触顶配额维度, 已消耗量, 进行到相位}——
                                             #   截断 run 是一等数据，无标记入账=构建期拒绝
    entry_kind: Literal["reserve", "settle", "reserve_released", "transfer",
                        "exception_appropriation", "system_loss", "reconcile_delta"] = "settle"
    # append-only：作废 reserve 追加 reserve_released 而非删除（防"幽灵预扣"，N9×N10）

BudgetLedger = list                          # append-only 容器；物化入 X1，只增不改

# ---- 预扣-结算（N5：reserve→settle，TALE 合理区间）----
@dataclass
class ReserveRecord:
    reserve_id: str
    intent_id: str                           # 预扣锚定 intent（预扣失败即 rejected_budget 回流）
    amounts: dict                            # {unit: amount} 分币种预扣（×N1；任一币种余额不足即拒绝）
    quantile_used: float = 0.5               # 预扣分位数（按 op_kind×model_tier×供应商切片
                                             #   历史 settle 分布 P50–P75 起步【推断，零文献】）
    settled_amounts: Optional[dict] = None   # 结算实际值（供应商回报后多退少补）
    settle_deviation: Optional[float] = None # ★settle 偏差率字段：|settle−reserve|/reserve，
                                             #   按切片常驻报告（×N13）——指示重试风暴/嵌套失控的
                                             #   早期探针而非记账误差
    nested_call_policy: Literal["rollup", "押金上界"] = "rollup"  # J2：无上卷能力按成本上界预扣
    status: Literal["open", "settled", "released"] = "open"
    # reserve 与 settle 各记一条台账、差额独立入账（J9 差额归宿原料）；
    # 预扣估计须落 TALE 合理预算区间——过紧反推高消耗（budget 10→实际 157 tokens），
    # 过松锁死额度降低并发：过紧与过松同为失效配置

# ---- 科目体系（N7：决策因果链投影，七科目封闭枚举）----
CostAccountKind = Literal["explore", "exploit", "reeval", "control",
                          "repair", "handoff", "overhead"]
# 科目按决策成因划分（产生新候选 vs 维护既有候选可信度），非代码模块图投影；
# 按模块名命名的科目不在合法取值集（J1）。与 M1 cost_account/IntentKind 同步扩枚举（R2）。

@dataclass
class CostAccount:
    account: CostAccountKind
    ceiling: float
    spent: float = 0.0
    locked_share: float = 0.0                # control 科目：启动时与主科目同时锁定的固定比例
                                             #   （建议 5–10%【推断】，J8；启动时锁定不可被
                                             #   普通转账路径触及——硬编码）
    floor: float = 0.0                       # reeval 保底：f(M8 noise_floor)，定值归 M8 噪声测量（J7）
    quota: Optional[float] = None            # 隐性科目（reeval 验证表/repair/overhead）独立配额（J1：
                                             #   无独立配额=构建期拒绝）
    alarm_ratio: Optional[float] = None      # 隐性科目占比报警线（阈值占位待标定，§9-1）
    # handoff/spawn_island 类 intent 按主要消耗成因归科【推断，规则待补】；
    # 跨模块补贴双记：模块 A 决策在模块 B 名下产生成本 → B 记账、A 记消耗（J1）

# ---- 健康探针（N13：M3 是失效放大器，健康不能由"账平"自证）----
@dataclass
class M3HealthProbe:                         # 与 M4-P19 探针同构；读数向全框架广播
    effective_budget_ratio: float = 0.0      # ①有效预算率 = 进入搜索的预算/名义预算（B-B4；抓 B-2
                                             #   固定开销吞噬"名义 100 实际 70"）
    reconcile_delta_ratio: float = 0.0       # ②对账差额率 = |intent 层−call 层差|/总预算
                                             #   （B-B15；抓 B-7 差额无主；并入 settle/reserve 偏差）
    hidden_account_ratio: float = 0.0        # ③隐性科目占比 = reeval 验证表+repair+overhead 合计占比
                                             #   （B-B1；抓 B-1——GEPA 85–90% 即③缺失的直接证据）
    control_fulfillment_ratio: float = 0.0   # ④对照配额兑现率 = control 实际执行/启动时锁定配额
                                             #   （B-B12/B-B13；抓 B-6"无人记得最后一次有效对照"）
    thresholds: dict = field(default_factory=dict)  # ★四指标阈值全部占位待标定（§9-1：零标定，
                                             #   首版只能以 GEPA 8.7× 类极端值定保守上限【推断】）
    # 阈值联动：③超阈→归因报告；④连续 N 期不足→待证声明标注"对照已过期"（→M8/M9 裁决置信、
    #   →M4 报告）；②超阈→对账审计。四指标全部是结构性比率而非账务勾稽（I-β 独立性必要条件）

# ---- 拒绝分流（N9：三态拒绝是给 M1 的决策提示，非错误码）----
@dataclass
class RejectNotice:                          # M3→M1 拒绝回流（载体=IntentReceipt.verdict，一等谱系事件）
    intent_id: str
    verdict: Literal["rejected_budget",      # 钱不够 → M1 重发低档意图（唯一降档通道，N6）
                     "rejected_conflict",    # 配额结构性触顶/冲突 → M1 重新分配方向
                     "rejected_invalid"]     # 不可执行/不合法（schema 违约、幽灵快照等）→ M1 修复意图本身
    reason: str                              # 拒绝原因摘要；回流 M1 与 X1：{intent_id, 原因, 预算余量}
    remaining_budget: Optional[dict] = None  # 分币种余量（×N1/N12 块级摘要随回流携带）
    # 三态语义是给 M1 的决策提示而非错误码：rejected_budget="降价重发"、
    # rejected_conflict="此路结构性满，改分配"、rejected_invalid="别改分配，修意图"——
    # 合并为单态 reject 会迫使 M1 盲猜重发策略（AIDE² ~90% 拒绝率下盲猜代价最大【厂商博客级】）
    # 注：M1 原契约四态 {accepted, rejected_budget, rejected_quota, deferred} 的映射：
    #   rejected_quota→rejected_conflict 主干；deferred 语义并入 rejected_conflict（可等待子标注）
    #   【推断：枚举归一化归属 R4 联合裁决范围，见 §9-6】
```

**设计决定说明**：
- `AccountingStamp` 五元组成组出现的原因（N14 深挖）：供应商切换同时动成本与质量（98.7%→84.0%），只记价格版本则"成本效率变化"无法归因到价格还是行为——缺一不可。
- `BudgetLedger` 三级键对应三种不同消费者（call=完整性校验防漏、op=M2 漏斗核算、block=M1 下一代分配）——"记全、看粗"：记账层全粒度保留，暴露给决策层的粒度必须经块级聚合降噪（per-call 均值在 30×/50× 方差环境下数学存在但管理无义，arXiv:2604.22750 / 2511.14136）。
- `ReserveRecord.settle_deviation` 把 settle 差额从"记账误差"升格为信号（N5 深挖）：按（op_kind×model_tier×供应商）切片后是重试风暴/嵌套失控的早期探针。
- `CostAccount.locked_share` 的启动时锁定不可被普通转账路径触及是硬编码（N7×N8 硬耦合：control 保留份额只在白名单+例外程序下物理不可掏空——"立法 vs 司法"）。
- `RejectNotice` 三态分流是**给 M1 的决策提示而非错误码**（N9 深挖）——拒绝回流是一等谱系事件（全生态零实现的空位设计），携带"哪个方向的 intent 在什么预算下不可执行"的信息。
- `M3HealthProbe` 四指标覆盖 GB 八条失效中五条的可观测面——健康指标本质上是把失效集编译成常驻探针；指标自身的监控成本未估算（自指风险，§9-1）。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 只报价不决策：M3 边界协议（N6/N9，全部接口设计的生成元）

- **M3 只做四件事：报价（reserve）、预扣、结算、拒绝**。预算不足时以 `rejected_budget` 经 IntentReceipt 回流 M1，由 M1 以低档参数重发 intent——**降档决策一次都不在 M3 发生**（档位选择=分配语义，M1 单一作者；M3 自动降档使 M1 的 expected_gain 承诺与实际执行配置脱钩，对账闭环自此失真）。
- 边界的深层价值（N6 深挖）：M3 的日志语义干净——台账里只有"执行了什么 intent、花了多少"，没有"M3 擅自改了什么"，一切配置变更经 M1 重发留下 intent 谱系（policy_version 关联），对账闭环可完整重建因果链。
- **降级档位集=模型降级/评估降档 n_trials↓/采样降频三杠杆组合 + 保底档不可再降**（TALE：降级非单调免费，存在合理预算区间，越界双输）；保底档定值是统计问题不是成本问题——评估保底由 M8 噪声测量定值（噪声底须低于最小可裁决改进量），**总预算低于保底时 M3 拒绝开跑并报告"预算不足以产生可证结论"**，而非静默压缩评估（J7；SB P=0.49 是举证门槛）。
- 拒绝-重发回路的 ttl 冲突（R4）见 §9-6：ttl_blocks=1 下重发意图可能出生即过期，本文件只登记不裁决。

### 3.2 硬+软上限与级联冻结（N4，分歧 2 落地）

- **默认 `硬上限 + 软上限降级档`**：软阈 80% 广播"收敛模式"（→M1/M4/M2，把"触顶"从一个时刻变成一个**相位**，给各模块有序收敛的机会）+ 不可逆操作（驱逐/重置/快照复活）配额单独审批 + 硬触顶 terminate-before-call 后入**只读结算态**；纯硬熔断仅作软档失效后的最后保险；**"仅监控告警"为反模式永久禁止**（alert 是验尸报告不是护栏；$47k 死循环事故：2025-11 四个 LangChain agent 跑 264h，Waxell 2026-04——执行层必须在下一次 API 调用发出前拦截）。
- **80% 具体取值无实证支撑（GB 提议值），列为待标定参数**（§9-4）；超限模式广播协议全生态零实现，是空位设计。
- **级联冻结硬编码**（J4）：触顶后档案照常驱逐/谱系照常记代/复活重耗配额=一次超额沿模块边界级联成多次不可逆（每步局部合理）——超额状态下任何模块执行不可逆操作=运行期拦截。
- **截断 run 双重身份**（J3）：既是已消耗成本又是非随机缺失数据（被截断 run 系统性是"探索更激进/任务更难"的 run）——带截断归因标记入台账，统计层消费完成数据须声明删失处理方式，混记视为数据污染；节流机制本身是选择压力（配额周期与搜索相位解耦时，"何时停"等价于"选择谁死"）。

### 3.3 科目体系与对照宪法（N7/N8，分歧 4/5 落地——全 14 轴裁决强度最高的两条）

- **科目=决策因果链投影，模块图投影在任何场景下都不是合法默认值**（只是"未做科目设计"的别名）：科目体系的失效不违反任何内部一致性（GEPA 的账本从来是平的，85–90% 错配存在于科目结构而非数字），错配只在与成本成因对齐的替代科目表对照时才暴露——而替代科目表不存在 ⇒ **科目设计无法靠运行中发现问题修正，必须第 0 天按决策因果链立账**。
- **配比档默认 `固定下限 + 弹性上部`**：control 5–10% 硬下限（【推断，无文献定值】）、reeval 噪声底保底由 M8 测量定值，其余弹性由 M1 信号驱动；隐性科目一等化=独立配额+占比报警线。
- **对照科目四层制度保障链（J8，缺一即被局部理性击穿）**：(a) 启动时与主科目**同时锁定**、按固定比例 5–10% 分配（非余额模式——余额模式下对照的存在性依赖当期运气，制度上等于没有）；(b) 挪用须显式例外记录{谁批的/理由/补跑计划}，审批条目为一等台账类型；(c) 连续 N 期未补跑触发结论降权（待证声明自动标注"对照已过期"，广播→M8/M9 裁决置信、→M4 报告）；(d) 对照配额兑现率入 N13 健康指标常驻报告。保险悖论（没出事时保费永远显得浪费）⇒ 该保障无法依赖任何当期决策者的自觉，只能内生于配额设计。该科目即 M1-UNIFIED §0.1 自我证成公约"对照预算为 M3 保留科目"的物化点，M3 是公约的预算侧执行机构（条款 (f)(g)，§0.0）。
- **转账白名单事件触发**（N8）：仅三类事件——adjudicable=None（M1-G17 不可裁决→重评转账）/ 相位切换 / Verdict——全部入台账；禁转使统计事件被迫等人，自由转账使科目体系形同虚设（均非法）。

### 3.4 效率指标分治与双喂分发（N11/N12，分歧 6/7 落地）

- **默认 `admitted_per_usd 为主（效率级，喂 M1 重排）+ cost-of-pass C/R-CPST 口径为采购对照（→M4 报告、降级档比较）`**——两指标按用途分治而非竞争：admitted_per_usd 以 M9 准入为产出端口（内部闭环，对齐 M2-O19"有效搜索深度"）；cost-of-pass 以任务成功为产出端口（外部采购对标的唯一诚实口径——便宜 19× 的模型若需 3× 重试则生产更贵；Efficient Agents GAIA $0.398→$0.228、cost-of-pass 改善 28.4%，arXiv:2508.02694）。**单价指标（cost_per_call、$/token）永久禁止作决策依据**（方向性奖励高重试率组件）。
- **CPST 口径强制**：R 的分母固定为 CPST 端到端摊销（含重试/工具/缓存）；**M3 向 M1 报效率信号必须报 CPST 口径**，否则 M1 学会偏爱"便宜而脆"的配置；cost-of-pass 跨系统引用无 CPST 口径声明=报告退回；口径依赖 N2 三级键与 N8 修复归属全部到位方可跨系统比较。
- **两级反馈**：效率级（admitted_per_usd/cost_per_block/eval_spend_fraction）喂 M1 重排；异常级（成本方差突增/对照饿死/settle 偏差）触发降级/熔断。**效率必须与健康（N13）联读**——压评估、挪对照在当期 admitted_per_usd 上总表现为改善，单读效率指标=奖励预算侧作弊。
- **预算余量双喂同源**（N12）：M1 收块级余量摘要（随 IntentReceipt 或独立心跳，BATS arXiv:2511.17006——无预算感知时更大预算不提升性能）；算子收 per-call remaining_budget（算子签名扩展，AIRA-dojo 先例）；两处**口径同源为隐藏硬要求**（不同源则"M1 以为有余量、算子已自收缩"错位）；prompt 级预算提示至多软引导档、不得作执行依据（TALE：告知紧约束反增 token 消耗，budget 10→实际 157 tokens）；余量多币种分别报（×N1）。

### 3.5 intent-call 对账闭环与差额归宿（J9，N2×N5 结算层）

- **每个 intent 到期必须结算**：承诺份额 vs 实际消耗 vs 产出差三件套；对账报告（按 intent 的兑现率与成本方差）为 M1 下一代分配的**强制输入**（份额分配反馈不来自对账=架构评审拒绝）；无结算的 intent 不得续约。
- **差额显式归宿**：intent 层与 call 层账本的差额必须入账到具名科目（重试损耗/嵌套展开/固定开销/未兑现份额），**"差额"本身不得作为合法科目**；差额率为一等健康指标常驻报告（N13②）。
- 块级是对账的最小可行粒度（N3 深挖）：粒度小于块则承诺未兑现即被结算（误报），大于块则对账滞后（ttl 已过期）。结算层是无人拥有的跨模块公共品，**M3 的核心架构职责正是拥有它**。
- **重试/回滚/复活按决策归因 + 沉没成本双向隔离**（J10/N8）：修复消耗归因到引发决策的 intent 并沿链上卷（与对账闭环共享同一份因果链数据）；无归因记"系统损耗"科目常驻报告、超阈触发审计；回滚链长度设配额上限、超限冻结该自修改 intent；复活候选沉没成本既不计入"已投资价值"也不计入成本-产出比分母（双向隔离为唯一中性解；激励分析部分 SHOULD——机制推演无对照实验）。

---

## 4. Layer 3：操作面×实现类矩阵

八操作面（M3 的全部对外能力面）× 三实现类：

| 操作面 | 确定性实现（默认与兜底） | LLM 辅助实现 | 自适应实现（opt-in） | 默认实现类 |
|---|---|---|---|---|
| quote_reserve（报价预扣） | 分币种余额检查+按切片 P50–P75 分位数预扣；TALE 合理区间校验 | —（报价是算术不是判断） | reserve 分位数按 settle 偏差率反馈校准（先记账后定参，零文献） | 确定性 |
| settle（结算） | 供应商回报实际成本多退少补；reserve/settle 各记一条；作废追加 reserve_released | — | — | 确定性 |
| reject_route（拒绝分流） | 三态分流规则引擎（余额/配额/合法性判定均为确定性比较） | — | — | 确定性 |
| throttle_broadcast（节流广播） | 软阈 80% 检测+收敛模式广播+硬触顶只读结算态+级联冻结拦截 | — | 软阈位置按截断偏差观测校准（待标定，§9-4） | 确定性 |
| transfer（科目转账） | 白名单三类事件触发+例外程序审批条目；control 锁定不可触及硬编码 | — | — | 确定性 |
| reconcile（对账结算） | intent 到期结算三件套+差额归具名科目+差额率计算 | 归因报告撰写辅助（不判定） | — | 确定性 |
| report_efficiency（效率报告） | admitted_per_usd 主+cost-of-pass CPST 对照两级反馈 | — | 效率-性能相关性监测（效度未验证，§9-7） | 确定性 |
| health_probe（健康探针） | 四指标结构性比率常驻计算+阈值联动广播 | 健康异常归因摘要撰写辅助（不判定） | 阈值自标定（运行数据积累后，首版无） | 确定性 |

**为什么 M3 的 LLM 档几乎不存在**（与 M1/M2 的对比说明）：M3 的全部核心动作——余额比较、预扣、结算、上限检测、白名单匹配、比率计算——都是**算术与规则匹配**，其正确性标准是可重放、可审计、确定性（台账是 X1 一等证据，非确定性的执行路径本身即失效源）；预算执行层的价值恰恰在于"LLM 不可绕过"（prompt 级预算提示已被 TALE 证为建议档）。LLM 在 M3 的唯一合法位置是**报告撰写辅助**（对账归因报告、健康异常摘要的文本化），且明确不判定——判定规则（阈值比较）保持确定性。这与 I-LLM（LLM 建议、确定性终裁）在"执行机构"上的投影一致：M1/M2 的 LLM 档存在于内容生产侧，M3 没有内容生产面。

**硬编码约束汇总**：reserve/settle/拒绝/熔断/转账无 LLM 终裁路径（I-LLM）；仅监控告警永禁；按模块名划账不在合法取值集；隐性科目无独立配额=构建期拒绝；control 启动时锁定不可被普通转账触及；节流压缩 reeval 至保底以下=运行期拦截；低于保底开跑=审计不通过；台账缺版本五元组=构建期拒绝；单价指标永禁决策用途；prompt 级预算提示不得作执行依据。

---

## 5. Layer 4：双速调度 YAML

```yaml
# budget/schedule.yaml
schedules:
  sync:                        # 关键路径，每次 intent 验收/调用出闸前后；硬约束：禁 LLM
    - op: quote_reserve        # N5 分币种预扣（TALE 合理区间校验；余额不足→rejected_budget）
      constraint: no_llm
    - op: pre_call_intercept   # N4 terminate-before-call：下一次 API 调用发出前拦截
      constraint: no_llm
    - op: soft_threshold_check # 80% 软阈检测→收敛模式广播（→M1/M4/M2）
    - op: reject_route         # N9 三态分流（rejected_budget/rejected_conflict/rejected_invalid）
    - op: cascade_freeze       # J4：超额状态不可逆操作运行期拦截
  idle:                        # 默认档：块边界/空闲窗
    - op: settle               # 结算+差额独立入账；作废 reserve 追加 reserve_released
    - op: reconcile            # J9：intent 到期结算三件套→对账报告喂 M1 下一代分配
    - op: margin_broadcast     # N12 双喂：M1 块级余量摘要+算子 per-call remaining_budget（同源视图）
    - op: health_probe         # N13 四指标常驻计算+阈值联动（对照过期标注广播→M8/M9/M4）
    - op: efficiency_report    # N11：admitted_per_usd 喂 M1 重排（CPST 口径）；cost-of-pass→M4 报告
  scheduled:                   # 可选：长程维护
    - op: rate_table_revalidation  # N14：汇率表版本化更新+主动对账（定期重测单位成本）
      cron: "on_price_change"
    - op: floor_recalibration  # J7：reeval 保底随 M8 噪声底测量重定值
      cron: "on_noise_floor_update"

currency:                      # 分歧 1（N1）
  units: [token, usd, eval_count, node, wallclock]  # 子集声明；单币种仅原型期+豁免声明
  exchange_rate_table: versioned     # 刚性联动 N14；未版本化=裸数字记账反模式
  standard_coin: benchmark_model_equivalent_token  # 跨期"等预算"锚（不可漂量）
  wallclock_semantics: {hoardable: false, transferable: false}  # 独立 ttl 语义

ceiling:                       # 分歧 2（N4）
  mode: hard_plus_soft         # monitor_only 永禁；hard_only 仅作最后保险
  soft_threshold: 0.8          # 占位待标定（§9-4）
  post_hard_state: read_only_settlement
  truncation_marker: required  # J3：无归因标记入账=构建期拒绝

reserve:                       # 分歧 3（N5）
  mode: reserve_settle
  quantile: [0.5, 0.75]        # 按 (op_kind×model_tier×供应商) 切片历史 settle 分布【推断占位】
  nested_call_policy: rollup   # 无上卷能力→押金上界（J2）

accounts:                      # 分歧 4/5（N7/N8）
  projection: decision_causal_chain  # 模块图投影非法
  kinds: [explore, exploit, reeval, control, repair, handoff, overhead]
  floors: {control: [0.05, 0.10], reeval: from_m8_noise_floor}  # 固定下限+弹性上部
  hidden_account_quota: required     # 隐性科目独立配额+占比报警线
  control_lock:
    timing: at_run_start       # 启动时与主科目同时锁定；普通转账路径不可触及（硬编码）
    exception_procedure: {record: [approver, reason, make_up_plan], entry_kind: exception_appropriation}
    expiry: {consecutive_periods_missed: mark_stale_control}   # 过期降权广播
  transfer_whitelist: [adjudicable_none, phase_switch, verdict]  # 事件触发，全量入台账
  repair_attribution: decision_chain  # 按决策归因+沉没双向隔离；回滚链配额上限

rejection:                     # N9
  ordering: priority_with_ttl_sweep   # ttl_blocks=1 易腐品主动清理；snapshot_ref 过期同废
  three_way: true

efficiency:                    # 分歧 6（N11）
  primary: admitted_per_usd    # 效率级喂 M1 重排
  procurement: cost_of_pass_cpst   # CPST 端到端摊销口径声明强制
  unit_price_metrics: forbidden    # cost_per_call、$/token 永禁决策用途

feedback:                      # 分歧 7（N12）
  targets: {m1: block_level, operators: per_call}
  source: single_ledger_view   # 同源口径为隐藏硬要求；prompt 级至多软引导

health:                        # N13
  metrics: [effective_budget_ratio, reconcile_delta_ratio,
            hidden_account_ratio, control_fulfillment_ratio]
  thresholds: {}               # ★全占位待标定（§9-1）
  broadcast: framework_wide
```

**与其他模块的协议钩子**：
- **M1**：intent_queue 消费端；rejected_budget→M1 重发低档（唯一降档通道）；块级余量摘要+对账报告为 M1 下一代分配强制输入；reserve 失败→IntentReceipt{verdict=rejected_budget, executed_cost=0}；软停剩余预算意图由 M1 交还 M3。
- **M2**：消费 O19 op tax 价目表（不制定）；op 层台账喂 O20 sub_funnels；算子签名扩展 remaining_budget 字段；嵌套算子上卷协议与 O16 共同定义。
- **M8M9**：消费 eval-tax 价目表（deterministic≈免费→LLM judge $0.01–0.03→多 judge probe $0.05–0.10）；reeval 保底定值消费 M8 噪声底测量（单一来源）；对照过期标注影响 M9 裁决置信；admission_outcome 由 M9 准入回流。
- **M4**：超限模式广播冻结驱逐/复活；buggy_leaf 复活通道提供修复归因链；run 报告附 cost-of-pass（CPST 口径）与科目结构归档。
- **X1**：台账 append-only（reserve/settle/reserve_released/transfer/exception_appropriation/system_loss/reconcile_delta 全为一等条目类型）；汇率表版本变更、截断标记、健康读数时序、拒绝/作废事件全部入谱系。

---

## 6. 七分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | 币种族（N1） | 跨供应商/跨期对照需求 × 价目外部化 | 多币种账户族+显式汇率表（版本化刚性联动） | `budget_units` 子集 + 版本化汇率表 | 汇率表未版本化=裸数字记账反模式；单币种须豁免声明 | reserve 分币种预扣（任一不足即拒绝）；汇率表版本变更入 X1 |
| 2 | 上限性质（N4） | 下游不可逆链 × 截断统计消费 | 硬上限+软上限降级档（80% 软阈占位）；仅监控永禁 | `ceiling_mode` + `soft_threshold` | 级联冻结；截断归因标记强制；硬触顶只读结算态 | 超限模式广播→M1/M4/M2（空位设计） |
| 3 | reserve 松紧（N5） | 成本可预测性 × 并发 | TALE 合理区间（P50–P75 占位）；过紧过松同为失效 | `reserve_quantile` + `nested_call_policy` | 无上卷按成本上界预扣 | settle/reserve 偏差率按切片入 N13 |
| 4 | 科目投影（N7，最高强度裁决） | 无（模块图投影任何场景非法） | 决策因果链投影+固定下限+弹性上部 | 七科目封闭枚举 + `account_floor` | 按模块名划账非法；隐性科目无配额=构建拒绝 | handoff 类按主要消耗成因归科【推断】 |
| 5 | 对照保障强度（N7×N8） | 无（弱保障任何场景非法） | 四层链：比例锁定 5–10%+例外程序+过期降权+兑现率监控 | `control_lock` | 启动时锁定不可被普通转账触及；审批条目一等台账类型 | 兑现率连续 N 期不足→"对照已过期"广播 |
| 6 | 效率指标（N11） | 用途（内部调度 vs 外部采购） | admitted_per_usd 主 + C/R-CPST 采购对照；单价永禁 | `efficiency_metrics` 双指标 | CPST 口径声明强制；单价指标不在合法取值集 | 效率级喂 M1（CPST 口径）、异常级触发降级/熔断 |
| 7 | 双喂分发粒度（N12） | 消费者决策层级 | M1 块级+算子 per-call 双喂同源；prompt 级仅软引导 | `feedback_targets` + 同源视图声明 | 不同源=配置评审拒绝；prompt 提示不得作执行依据 | 双喂口径校验为定期自检项【推断：协议待建】 |

---

## 7. 证据强度与投资优先序

**证据强度排序**（合并 Group A/B 结论与深挖，强→弱）：

1. **reserve→settle 预扣结算与调用前拦截**（agentgateway 金融级四步配额先例；$47k 死循环事故；TALE token 弹性）——执行语义方向最强；reserve 估计模型零文献。
2. **科目=决策因果链投影与隐性科目一等化**（GEPA 85–90%、8.7–8.9×【原文明确】；AIDE² ~90% 拒绝率【厂商博客级】）——失效证据最锋利；四指标阈值零标定。
3. **口径版本戳与标准币锚定**（aider 98.7%→84.0% 双漂；LLM API 2024–2026 数量级调价；与 M8 Receipt 同构）——方向强；标准币定义与锚传承空白。
4. **效率指标分治**（Efficient Agents 28.4%，arXiv:2508.02694；Erol 2025；CPST 2026-04）——单场景证据强，进化循环定义无文献。
5. **双喂分发**（BATS arXiv:2511.17006；AIRA remaining_time）——单 agent 场景，进化循环收益无一手证据。
6. **软阈广播/对照四层链/三态分流**——全生态零实现的空位设计，纯公理推导+反面锚点。
7. **保底档定值/回滚链配额/拒绝-重发时延**——无参照、未量化，最弱。

**投资顺序表**：

| 顺位 | 投资方向 | 依据 |
|---|---|---|
| **0（最高优先，显式置顶）** | **N13 四指标标定 + N6 拒绝-重发与 ttl_blocks=1 冲突解决（R4 联合裁决）** | 四指标是 M3 全部健康制度的触发线而阈值零标定（§9-1）；拒绝-重发回路若不可用，"M3 只报价不决策"边界原则（全部接口设计的生成元）的执行层可行性受损（§9-3/9-6）——两者置顶 |
| 1 | BudgetLedger 三级键+版本五元组 schema + reserve→settle 链路 | 六轴契约交汇点（J6/J9/J3 的载体），先建 schema 后谈机制 |
| 2 | 七科目体系 + control 四层保障链 + 转账白名单 | 分歧 4/5 是全轴系最高强度裁决；公约 (f)(g) 的物化点 |
| 3 | 硬+软上限与级联冻结、截断标记 | $47k 事故的直防；不可逆级联的唯一拦截层 |
| 4 | 双喂同源分发 + 效率双指标（CPST 口径） | BATS/28.4% 方向证据强，口径建设前置 |
| 5 | reeval 保底定值（依赖 M8 噪声测量）+ 对账差额归宿 | J7/J9 制度层；依赖 M8 在先 |
| 6 | 标准币锚定与锚传承协议 | 跨期对照公平性前提；空白待建 |

---

## 8. Profile 兼容性验证（统一性的证明）

五个经典/反例系统全部编译为 profile（Layer 3 策略选择 + Layer 4 配置），**无一处需要改内核**；每个 profile 诚实标注该系统实际违反的公理。

### 8.1 funsearch_wallclock（墙钟单账户 + 周期重置）

```yaml
profile:
  name: funsearch_wallclock
  axes: {N1: 单币种(wallclock, 4h/轮+样本数上限), N2: per-call(隐式), N3: per-block(4h 重置周期),
         N4: 纯硬熔断(杀半岛), N5: 事后结算, N7: 模块图投影(未声明), N9: 无拒绝回流}
  currency: {units: [wallclock], exemption: "原型期声明——但跨期对照需求存在，豁免实际不成立"}
  ceiling: {mode: hard_only}   # 违反 J4，见标注
```
内核复用：wallclock 为五币种合法取值之一（独立 ttl 语义：不可囤不可转移）；单币种档在配置层可表达。
**公理违反标注**：原系统**违反 J4（纯硬熔断无软阈相位——4h 固定重置在演化后期截断正在突破的谱系，配额周期与搜索相位解耦="何时停"等价于"选择谁死"）**、**违反 J3（截断 run 无归因标记，4h 超参无论证被 PDE-SHARP 生态原样继承 arXiv:2511.00183）**、**违反 J6（无口径版本戳，墙钟数字跨期可比性依赖未声明的不漂假设）**、**违反 J9/J13（无对账层、无健康指标）**。【诚实标注】

### 8.2 aira_remaining_time（剩余时间一等参数 + 算子消费）

```yaml
profile:
  name: aira_remaining_time
  axes: {N1: 单币种(wallclock→remaining_time), N5: reserve→settle(时间片),
         N12: 喂算子(per-call remaining_time 一等运行时参数)}
  currency: {units: [wallclock]}
  feedback: {targets: {operators: per_call}}   # 算子签名携带剩余时间——N12 喂算子档一手先例
```
内核复用：remaining_time 一等参数=N12"喂算子"档的一手原型；算子按剩余预算内部整形（少 prompt 几轮）为双喂协议的行为聚焦端先例。
**公理违反标注**：原系统**部分覆盖 N12 但缺 M1 侧块级余量摘要（单 agent 场景，无双喂同源口径——"对谁说什么粒度"只做了算子侧）**、**违反 J6（remaining_time 无版本戳，硬件/实现变更后时间预算不可比）**；预算感知收益在进化循环中无一手证据（§9-6）。【诚实标注】

### 8.3 relayevolve_handoff（整代 handoff 计费）

```yaml
profile:
  name: relayevolve_handoff
  axes: {N1: 单币种(usd, 相位预算占比), N2: 三级键雏形(相位级), N3: per-generation(整代 handoff),
         N6: 模型降级(便宜→强模型接力), N7: 模块图投影(相位账)}
  allocation: {granularity: per_generation}   # 决策单位=整代——N3 默认值一手原型
  phase: {strong_model_budget_share: 0.85}    # 0.85 先例起点、非通用常数
```
内核复用："逐 call 路由是错的问题、正确决策单位是整代"=N2/N3 块级粒度的一手锚；强/弱模型价差（o3 $0.15–0.60 vs Flash $0.01–0.05）为多币种汇率需求的天然场景。
**公理违反标注**：原系统**违反 J9（无 intent-消耗对账层——连各相位实际成本都不准确，"便宜模型何时移交"这一被证有真实大增量的决策的输入失真【推断成分中等】）**、**违反 J6（相位成本按当期价目记账，无口径版本戳）**、**违反 J1（相位账=模块图投影变体，移交成本归科未定义）**；单系统锚定面过宽（与 M1-UNIFIED §9-3 同源）。【诚实标注】

### 8.4 agentgateway_reserve_settle（预扣结算工业先例）

```yaml
profile:
  name: agentgateway_reserve_settle
  axes: {N1: 多币种(usd+调用数, 层级预算), N4: 硬上限+审批层, N5: reserve→settle(金融级四步),
         N9: 审批制例外通道}
  reserve: {mode: reserve_settle, hierarchy: true, approval_layer: optional}
  # 金融级配额控制标准形态：预留/结算/层级/审批四步（Solo 2026-06）
```
内核复用：reserve→settle 默认值的**唯一工业一手先例**；"先扣押金后结算"天然偏向多扣多退，为 J2 押金档（无上卷按成本上界预扣）的单层类比。
**公理违反标注**：本 profile 为**正面先例**（无公理违反）；限制标注：单系统工业实践无学术消融；嵌套深度>1 时的押金递归规则无证据（N2 深挖空缺）；审批制硬门不适于自动研究循环默认档（仅作对照挪用等大额例外通道）。【诚实标注】

### 8.5 gepa_validation_heavy（反例 profile：85–90% 隐性科目）

```yaml
profile:
  name: gepa_validation_heavy
  axes: {N1: 单币种(usd 隐式), N7: 模块图投影(验证开销记作"评估"), N13: 无健康指标,
         N4: 仅监控(无成本控制, 作者自承)}
  accounts: {projection: module_graph}   # ★反例：按模块名划账——不在合法取值集，仅作对照臂
  # 四任务 rollout：6,438/678/6,858/2,157 vs 纯训练 737/79/558/269，验证/训练比 8.7–8.9×
  # 85–90% rollout 花在"维护验证表"隐性科目（arXiv:2507.19457，原文明确无成本控制）
```
内核复用：本 profile 编译**必然失败**——模块图投影不在合法取值集（J1 硬编码拒绝）、隐性科目无独立配额（构建期报错）——这本身是统一设计的正确性自检：**GEPA 的配置在本框架的类型层不可表达**。GEPA 的 85–90% 以"论文附录数字"而非"运行期对账报警"存在，是 N13 健康指标（隐性科目占比③）与 J9 对账闭环缺失的双重直接证据。
**公理违反标注**：**违反 J1（隐性科目吞噬主科目、账上记作"评估"——错配不违反任何内部一致性，只在替代科目表对照下暴露）**、**违反 J13/N13（无健康指标，账本永远平但系统已坏）**、**违反 J9（无 intent 级对账，85–90% 错配未在第一期对账暴露）**；作者自承须"动态选择验证子集"补救=承认隐性科目无成本控制【原文明确】。【诚实标注：反例 profile，仅作 G12 级对照臂与失效教具】

**兼容性结论**：五个 profile 覆盖预算层的经典设计空间（墙钟单账户/剩余时间算子整形/整代计费/金融级预扣/隐性科目反例五形态），差异=币种族×执行模式×科目投影×上限语义×反馈分发的选择，全部在配置层。表达不了的进 §9 边界声明。

---

## 9. 诚实边界声明（统一不了的东西，合并后 7 条）

1. **N13 四指标阈值零标定**（本模块最大制度空缺）：有效预算率/对账差额率/隐性科目占比/对照兑现率的"多少算超"无任何系统实现过、无失败分布可参照——首版只能以 GEPA 8.7× 类极端值定保守上限【推断】；阈值联动（例外程序/审计/结论降权的触发线）全部待运行数据标定；健康指标自身的监控成本未估算（指标不能成为新的隐性科目——自指风险未解）。
2. **对照科目 5–10% 无消融**：保留比例只有任务设定与 GEPA 反面锚点，无"3% vs 5% vs 10%"的任何对照证据；对照保留科目在全生态零实现（GA 前沿空位 1）——四层保障链整体是空位设计，AIDE² 的预算保护决策是唯一正面旁证【厂商博客级】。
3. **N6 拒绝-重发回路与 ttl_blocks=1 的时延冲突未解**（最高优先级接口风险）：重发往返时延未量化；ttl=1 下重发意图可能出生即过期（旧 intent 作废、reserve 痕迹须清理，"幽灵预扣"风险）——R4 只登记冲突不裁决（候选方案：同谱系续约 ttl 重置 / M1 侧预发双档意图，归 M1×M3 联合设计）；若该回路实际不可用，"M3 只报价不决策"边界刚性原则（全部接口设计的生成元）的执行层可行性受损。**与 M1-UNIFIED §9 新增条目互为交叉引用**。
4. **reserve/软阈/降级参数全线"先记账后定参"**：reserve 分位数 P50–P75（TALE 合理预算区间只在单任务测得、进化循环未验证、reserve 估计模型零文献）；80% 软阈（GB 提议值无实证）；保底档定值依赖 M8 噪声测量而该测量在多数系统缺位；回滚链配额上限无任何参照——全部是公理推导的占位符，触发线待运行数据标定。
5. **N14 标准币的定义与锚传承是空白**：基准模型选谁、基准模型自身退役后如何换锚（换锚本身是一次口径漂移）无先例——需锚传承协议，空白；"现有框架均无版本戳字段"基于已知公开实现判断、未逐一代码审计【GB 自标推断成分中等】；主动对账本身的预算开销未估算。
6. **多币种账户族与双喂口径零运行先例**：五币种并存的运行系统实例为零（各系统均 1–2 种），N1 是空位设计；双喂同源一致性是设计断言，BATS/AIRA 均为单 agent 场景，进化循环中"余量反馈给分配器"的收益无一手证据。
7. **效率指标的效度未验证**：admitted_per_usd 与最终任务性能的相关性从未被验证（M2-O19 的设计断言）；cost-of-pass 在进化循环（多代、准入中间端口）中的定义无文献——Erol/Efficient Agents 均为单次任务场景；R 的分母口径（intent/块/run）同系统可差数量级，CPST 摊销口径依赖 N2/N8 全部到位方可跨系统比较。

---

## 10. 分阶段落地（M3a–M3c，对接 ADAPT-v1.1）

| 期 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|
| **M3a（类型层+最小执行，P0）** | BudgetLedger（三级键+AccountingStamp 五元组+append-only）/CurrencyAccount×汇率表/ReserveRecord/RejectNotice 落 core/budget/types.py；reserve→settle 链路+三态拒绝分流+硬上限 terminate-before-call；M1 契约 R1/R2 回补联调（分币种 budget_estimate、七科目枚举） | 缺版本五元组的台账条目被构建期拒绝；reserve 余额不足→rejected_budget 回流 M1 链路跑通；作废 reserve 追加 reserve_released 而非删除的单测通过；真实运行产出台账 | M1a（R1/R2 修订后的 AllocationIntent）+ M2 op tax / M8M9 eval-tax 价目表；并入 Step 0/1 |
| **M3b（科目制度+节流相位，P1）** | CostAccount 七科目+隐性科目独立配额+control 四层保障链（启动锁定/例外审批条目/过期降权/兑现率监控）+转账白名单+软阈 80% 广播与级联冻结+截断归因标记+双喂同源分发；funsearch_wallclock / aira_remaining_time / relayevolve_handoff 三 profile | 普通转账路径触及 control 锁定被拒；软阈广播演练通过（触顶相位下不可逆操作被拦截）；截断 run 带标记入台账；对照过期标注广播到 M8/M9 的链路跑通 | M3a + M1 相位/Verdict 事件源 + M4 不可逆操作面；并入 Step 2 |
| **M3c（对账闭环+健康仪表盘，P2）** | intent 到期结算三件套+差额显式归宿+admitted_per_usd/cost-of-pass CPST 双指标+M3HealthProbe 四指标常驻广播+reeval 保底定值（消费 M8 噪声测量）+拒绝开跑路径；agentgateway_reserve_settle / gepa_validation_heavy profile（后者验证类型层不可表达） | 无结算 intent 续约被拒；gepa_validation_heavy 编译被 J1 硬编码拒绝（反例自检通过）；四指标时序入 X1；低于保底开跑被拦截演练通过 | M3b + M8 噪声底测量 + M9 admission_outcome 回流 + 台账数据积累；并入 Step 3 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做 M3 自动降档（分配语义单一作者=M1；M3 只报价与拒绝）
- 不做仅监控告警档（反模式永禁：alert 是验尸报告不是护栏）
- 不做按模块名划账（模块图投影不在合法取值集，仅作反例对照臂）
- 不做单价指标（cost_per_call、$/token）决策用途（永禁）
- 不做 prompt 级预算约束的执行语义（建议档，TALE 证过紧反推高消耗）
- 不做无版本戳的跨期对照（裸美元定义"等预算"=评审退回）
- 不做低于 reeval 保底的开跑（拒绝开跑并报告，不静默压缩评估）

---

## 11. 一句话规格

> **M3 = 冻结的 BudgetLedger（append-only 三级键 call→op→block，intent_id/policy_version/版本五元组为一等字段——I-谱系的成本归因谱系物化）/CurrencyAccount（多币种账户族+版本化汇率表+标准币锚定，跨币种只在显式汇率层折算）/ReserveRecord（reserve→settle 预扣结算，TALE 合理区间 P50–P75 占位，settle 偏差率为重试风暴早期探针）/CostAccount（七科目决策因果链投影——模块图投影永禁，control 5–10% 启动锁定+四层保障链，隐性科目一等化）/M3HealthProbe（有效预算率/差额率/隐性科目占比/对照兑现率四结构性比率，阈值全占位待标定）/RejectNotice（rejected_budget/rejected_conflict/rejected_invalid 三态分流=给 M1 的决策提示非错误码）数据模型与"只报价不决策"边界协议（降档经 rejected_budget 回流 M1 重发，分配语义单一作者）、硬+软上限（80% 软阈广播收敛相位+硬触顶只读结算态+级联冻结，截断 run 带归因标记为一等数据）、intent-call 对账闭环（差额归具名科目、无结算不续约）、效率-健康分轴（admitted_per_usd 主+C/R-CPST 采购对照，单价指标永禁）、双喂同源（M1 块级+算子 per-call，prompt 级仅软引导）、reeval 保底不可压（低于保底拒绝开跑）、修复按决策归因+沉没双向隔离（内核，不可换）+ 十四轴编译成的 profile（FunSearch/AIRA/RelayEvolve/agentgateway 为实例，GEPA 为类型层不可表达的反例）+ 双速调度（sync 禁 LLM，LLM 档仅存于报告撰写辅助）+ J1–J10 公理内核化（J7 均衡化/J10 激励分析为 SHOULD）与四条既有不变量承接（I-β 第五投影确认——M3 是失效放大器，账平≠健康；自我证成公约增列预算侧条款 (f)(g)：对照保留科目执行机构=M3、封闭"压评估抬噪声底"绕过路径）。**
