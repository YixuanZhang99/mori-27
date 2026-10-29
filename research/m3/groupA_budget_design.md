# M3 BudgetController 调研 · A 组：设计空间 + 前沿（合并组）

> 范围：预算执行层——记账/计费、配额与节流、消费 M1 的 intent_queue（AllocationIntent/IntentReceipt，可拒绝）、预算科目体系（含自我证成对照保留科目 5–10%）、成本台账。
> 边界：分配意图归 M1；算子定价消费 M2-O19 op tax；评估定价消费 M8M9 eval-tax；准入侵 M9。
> 核心输入契约（M1-UNIFIED §2）：`AllocationIntent{intent_id, block_id, kind∈{explore,exploit,reeval,handoff,spawn_island}, target, budget_estimate, cost_account, priority, rationale, expected_gain(可空,强制CI), policy_version, ttl_blocks=1, snapshot_ref}`；回流 `IntentReceipt{verdict∈{accepted, rejected_budget, rejected_quota, deferred}, reason, executed_cost}`。**可拒绝性 + ttl 易腐 + 快照绑定是 M3 侧设计的三条类型层锚点。**

---

## 第一部分：系统/机制卡片

### 卡片 1：多预算账户并存——没有单一"预算"，只有账户族
- **证据**：
  - FunSearch：预算单位是**墙钟**（论文实验约 4h/轮、采样数百万程序），配合岛数与样本数上限；无美元账户。
  - AIRA-dojo：算子签名显式携带 `remaining_time: float`——**墙钟作为一等运行时参数**喂给每个算子，供算子内部自适应（如少 prompt 几轮）。
  - AIDE：预算单位是**节点数**（树搜索节点上限，如 24h 内 N 节点），调试节点单独设上限（参照值 10 节点或 12h，M2-UNIFIED §3.4）。
  - MEMOIR 类对比协议：共享执行预算 B=16（评估次数），per-instance timeout 10s，全程 <$1/run（arXiv:2605.17539）。
  - RelayEvolve：预算以**整代 handoff** 为单位跨模型档位分配（arXiv:2608.05651，本地 m2/groupC 卡片 6）。
- **归纳**：实践中至少五种计量单位并存——**token / 美元 / 评估次数 / 节点数 / 墙钟**；且单系统常同时设两种以上（FunSearch=墙钟+样本数；AIDE=节点数+墙钟）。M3 的账本必须是**多币种账户族 + 显式汇率表**（token↔USD 由供应商价目驱动；eval↔USD 由 eval-tax 档表驱动），单币种账户会在换供应商/换模型档时静默失真。
- **M3 落点**：`BudgetAccount{unit∈{token,usd,eval_count,node,wallclock}, ceiling, spent, reserved}`；跨币种只在显式汇率层折算，不在账本内混记。

### 卡片 2：计费粒度与成本归因——per-call 是噪声，per-generation/phase 是信号
- **证据**：
  - RelayEvolve（本地 m2/groupC 卡片 6）：**逐 call 路由是错的问题**——LLM 调用之间状态耦合（上下文、子代质量），正确决策单位是 population 整代移交。对应 M2-O19："决策单位是相位/代，不是单次调用"。
  - M2-O20 sub_funnels：嵌套算子成本必须拆成内部调用序列上报，否则预算失控不可诊断。
  - TensorZero / Helicone 式工业栈：per-call + per-task 成本归因为标准能力（LLM-Harness 综述，openreview 3hXEPbG0dh）。
  - 同一编码 agent 任务 token 消耗跨 run 方差可达 30×（arXiv:2604.22750）；精度相近的 agent 间成本方差 50×（arXiv:2511.14136）——**高方差意味着 per-call 均值无管理意义，需要块级聚合**。
- **归纳**：三层粒度各司其职——per-call（原子记账，防漏）、per-node/call-group（算子归因，喂 M2-O20）、per-block/per-generation（决策粒度，对齐 M1 AllocationIntent 的 block_id 与 h~10 代一块的假设）。
- **M3 落点**：台账三级键 `(account, block_id, op_kind×model_tier)`；向 M1 回流只在块级发生（避免高频信号噪声）。

### 卡片 3：硬上限 vs 软上限+降级档——监控≠执行，预留-结算分离
- **证据**：
  - **监控与执行的架构区分**（Waxell 2026-04）：Helicone/LangSmith/Braintrust 全是事后监控；"alert 是验尸报告不是护栏"。2025-11 四个 LangChain agent 死循环跑 264h 烧 $47k 的事故根因=无 per-agent 硬上限+无法在下次调用前终止。执行层必须在**下一次 API 调用发出前**拦截。
  - **预留-结算（reserve-settle）模式**（Solo agentgateway 2026-06，github.com/day0ops/quota-management）：网关在请求出闸前按估计成本**预留**预算，供应商回报实际 token 后**结算**差额；支持层级预算、预测、审批。这是金融级配额控制的标准形态。
  - 降级档先例：M8M9 cascade 三档（shallow n_trials=2 → deep n_trials=5 + full_trace）+ ICC 自动调 n_trials；M2 模型档（o3 ~$0.15–0.60/iter vs o3-mini ~$0.03–0.12 vs Gemini-Flash ~$0.01–0.05，OpenEvolve README）；FrugalGPT 级联最高省 98% 成本（Chen et al. 2024）。
  - TALE 的 token 弹性（arXiv:2412.18547）：**过紧的预算反而增加 token 消耗**（budget 10 → 实际 157 tokens）——降级不是单调免费的，存在"合理预算区间"，越界双输。TALE-EP 平均省 67% token、精度损失 <3%。
- **归纳**：合法设计空间 = {硬熔断（terminate-before-call）, 软上限+降级档（模型降级/评估降档 n_trials↓/采样降频）, 预留-结算}；纯 prompt 级预算注入不可作执行依据（token 弹性证明 LLM 不服从紧约束）。降级档须有**保底档不可再降**（否则降级链本身成为静默质量坍塌通道）。
- **M3 落点**：每条 AllocationIntent 验收路径 = reserve（按 budget_estimate 预扣）→ execute → settle（按实际成本多退少补，差入台账）；rejected_budget 触发 M1 重发低档意图而非 M3 侧自动降档（档位选择=分配语义，归 M1；M3 只报价与拒绝）。

### 卡片 4：科目体系与转账——对照保留科目是自我证成的物理基础
- **证据**：
  - M1 H3 三账户物化点：`cost_account ∈ {explore, exploit, reeval}` 已在类型层；自我证成公约（M1 §0.1）要求退化对照永驻——C10/G12 的 IID-RS/SCS 对照**不可从构建中移除** ⇒ 对照科目必须有**保留份额**，否则高负载时对照意图永远被 production 意图饿死。
  - 任务设定：对照保留科目 5–10%。
  - G17 不可裁决→重评转账（M1 §3.5）：CI 跨度覆盖噪声底时 `adjudicable=None`，预算从 production 科目转入 reeval 科目——**既有的科目间转账先例**，触发条件是统计事件而非人工。
  - Snell et al. 2024 预算对齐评测：compute 拉平后复杂推理策略常不优于简单基线——对照科目的产出（"省下的预算再投资为搜索深度"，AIDE² 16× 压缩先例）是框架自我证成的直接证据。
- **归纳**：科目设计 = {固定配比（简单、可审）, 动态配比（M1 信号驱动，需防自谋）, 保留份额（对照/重评科目硬下限，不可被借用）}。转账规则必须**白名单化**（哪些科目对可转、触发条件、上限比例），否则科目体系形同虚设。
- **M3 落点**：科目表 `{explore, exploit, reeval, control(≥5–10% 硬下限), handoff}`；转账仅允许 adjudicable=None / 相位切换 / Verdict 三类事件触发，全部入台账。

### 卡片 5：成本台账与效率指标——admitted_per_usd 而非 cost_per_call
- **证据**：
  - M2-O19 目标函数：固定总预算下有效搜索深度，核算单位 **admitted_per_usd**。
  - cost-of-pass（Erol et al. 2025）：v(m,p)=C(m,p)/R(m,p)，单次成本/成功率=期望成功成本；METR 将其扩展为模型/人混合 frontier。**$/token 是错的采购指标**：便宜 19× 的模型若需 3× 重试则生产上更贵（digitalapplied CPST 2026-04；CPST=含重试/工具/缓存摊销的端到端成功成本）。
  - Efficient Agents（arXiv:2508.02694）：GAIA 上用 cost-of-pass 做框架级选型，保留 OWL 96.7% 性能同时成本 $0.398→$0.228（cost-of-pass 改善 28.4%）。
  - M8M9 eval-tax 定价锚点：deterministic <1ms≈免费 → LLM judge $0.01–0.03/call → 多 judge probe $0.05–0.10；"门控频率与单次评估成本共享一条预算曲线联合优化"。
- **归纳**：台账 schema 最小字段 = `{account, block_id, unit, reserved, settled, op_kind, model_tier, eval_tier, intent_id, policy_version, admission_outcome}`；衍生指标分两级——**效率级**（admitted_per_usd、cost_per_block、eval_spend_fraction）喂 M1 重排优先级，**异常级**（成本方差突增、对照科目被饿死、settle/reserve 偏差率）触发降级或熔断。
- **M3 落点**：台账 append-only 入 X1（对齐 M2 §3.6"先建日志后调策略"）；policy_version 字段使成本可按签发策略版本切片（EvoX J 信号同构）。

### 卡片 6：前沿 2025–26——预算感知的四个新机制
- **BATS（Budget-Aware Test-time Scaling, arXiv:2511.17006, 2025-11）**：只给更大工具调用预算**不提升**性能（agent 无预算意识、触顶早）；Budget Tracker 插件提供持续预算感知；BATS 按剩余资源在"深挖/转向"间自适应。统一成本度量合并 token+工具消耗。→ **预算余量应作为观察量反馈给决策层（M1），而非只作 M3 内部状态。**
- **Agent Contracts（arXiv:2601.08815, 2026-01）**：资源约束的形式契约框架；指出 LLMOps 平台在组织层、serving 系统在推理层，**agent 行为层无正式资源契约**——正是 M3 的位置。
- **BAVT / turn-control（arXiv:2510.16786）**：良好校准的固定轮数上限可省 68% 成本且几乎不掉 solve rate，甚至因行为更聚焦而提升；动态轮数分配优于最优固定上限。→ **块级意图配额（每 block 几轮）是可校准的执行旋钮。**
- **Dual-Pool Token-Budget Routing（Liu et al. 2026，服务端）**：按估计 token 预算把请求路由到短/长上下文池，GPU-hours 省 31–42%（Azure 踪迹、A100 规模年省 $2.86M）。→ 预算信号可穿透到 serving 层。
- **级联/路由经济学汇总**：FrugalGPT 98%；Task Cascades 在 90% 目标准确率下再省 36%；Morph 五杠杆叠加 70–85%（路由 40–70%、压缩 50–70%、缓存 90%/hit、批处理 50%）；85% budget+10% balanced+5% frontier 配比≈省 92%（iternal 2026-03，厂商级证据，谨慎引用）。**与 M3 的交集**：这些都是"同等意图下的降本"（供给端），M3 是"哪些意图值得执行"（需求端）——两者正交，M3 消费其定价表但不复制其机制。
- **token 弹性警示的推论**：prompt 注入预算约束只是"建议档"，硬执行必须在外部拦截层（卡片 3）。

---

## 第二部分：候选轴系初稿（B# 编号，12 条）

| # | 轴名 | 取值谱（默认档加粗） | 关键证据/出处 |
|---|---|---|---|
| B1 | **预算币种族** | {token, **usd+token 双账户**, eval_count, node, wallclock} × 显式汇率表 {有, 无} | FunSearch=墙钟；AIDE=节点；AIRA=remaining_time；卡片 1 |
| B2 | **记账粒度层级** | {per-call, per-node, **三级键 (call→op→block)**} | RelayEvolve 反 per-call 路由；O20 sub_funnels；run 间方差 30× |
| B3 | **决策粒度** | {per-call, per-node, **per-block/per-generation**（对齐 ttl_blocks）} | RelayEvolve handoff；M1 block_id |
| B4 | **上限性质** | {硬熔断, **硬上限+软上限降级档**, 仅监控告警（反模式）} | Waxell 监控≠执行；$47k 事故；agentgateway |
| B5 | **配额执行模式** | {事后结算, **reserve→settle 预扣-结算**, 审批制（人授权硬门）} | agentgateway 四步；卡片 3 |
| B6 | **降级档位集** | {模型降级, 评估降档 n_trials↓, 采样降频, **三者组合+保底档**}；降级决策归属 {M3 自动, **M3 拒绝+M1 重发低档**} | M8M9 cascade 三档；TALE 弹性→保底档必要 |
| B7 | **科目体系** | 科目集 {explore/exploit/reeval/**+control 保留 5–10%**/handoff}；配比 {固定, M1 信号动态, **固定下限+弹性上部**} | M1-H3 三账户；C10/G12 对照不可移除 |
| B8 | **科目间转账规则** | {禁转, **白名单事件触发（adjudicable=None/相位切换/Verdict）**, 自由转账（反模式）} | G17 重评转账先例；M1 STOP_ACTION_TABLE |
| B9 | **意图处置语义** | 验收 {先进先出, **priority 重排+ttl 过期清理**}；拒绝分流 {rejected_budget vs rejected_quota vs deferred 三态} | IntentReceipt 四态枚举；ttl_blocks=1 易腐品 |
| B10 | **台账 schema 与可见性** | 最小字段集（卡片 5）；append-only 入 X1；**policy_version 可切片** | M2 §3.6；EvoX J 信号同构 |
| B11 | **效率指标体系** | {cost_per_call, **admitted_per_usd + cost-of-pass v=C/R + CPST**, $/token（反模式）}；反馈对象 {M1 重排, M4 报告, 熔断器} | M2-O19；Erol 2025；Efficient Agents 28.4% |
| B12 | **预算余量反馈** | {M3 内部状态, **作为观察量喂 M1（BATS 式预算感知）**, 喂算子（AIRA remaining_time 式）} | BATS 2025-11；AIRA-dojo 签名 |

**轴间硬耦合（供后续裁决）**：
- B4×B6：选"硬上限+降级档"必须同时定降级归属（B6 推荐 M3 拒绝→M1 重发，保持分配语义单一作者）。
- B7×B8：control 科目保留份额只有在 B8=白名单时才不可被掏空。
- B2×B11：三级键是 admitted_per_usd 能按算子/相位归因的前提。
- B5×token 弹性：reserve 的估计值须落在 TALE"合理预算区间"，过紧估计反而推高实际消耗（卡片 3/6）。

**前沿空位（推断，供 B 组失效分析对照）**：
1. 无系统实现"对照科目保留份额"——FunSearch/AIDE/OpenEvolve 均无自我证成预算线；这是框架的空位设计。
2. 无系统将 IntentReceipt 式拒绝回流作为一等谱系事件（AIDE² ~90% 外环拒绝率为旁证）。
3. 预算币种间汇率（eval↔token↔usd）全部由手工配置文件承担，无版本化汇率表先例。
