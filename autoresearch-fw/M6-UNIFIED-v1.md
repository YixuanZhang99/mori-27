# M6-UNIFIED-v1.md — 统一知识模块（外部世界接入）设计文档

> 依据：`../research/m5m6/m6_axes_final.md`（16 轴定稿 K1–K16）、`../research/m5m6/m6_deepdive_part1/2.md`（逐轴深挖）、`../research/m5m6/m6_分歧_公理.md`（七分歧裁决 + 公理 D1–D10 + 根因对账）、`../docs/M5记忆与M6知识设计深度分析.md` 第二/三部分（三维分类学 + 三条定稿边界 + 定稿配置）。结构与风格对齐 `M2-UNIFIED-v1.md` / `M5-UNIFIED-v1.md` / `M8M9-UNIFIED-v1.md`。所有数字引自上述底稿，不确定处标【推断】。
> 定位：M6 Knowledge 的最终形态设计。回答一个问题——**Arbor 的两车道 / AI-Scientist 的新颖性闸门 / KAPSO 的 ERA 联合检索 / Tree-of-Ideas 的 gap 信号卡 / IDEAgent 的去重证据供给 / openresearch-cli 的零耦合工具面这些经典设计能否被同一个实现兼容？答案：能（除了 AI-Scientist 的 veto 档——它是被禁止取值而非配置差异）。它们之间的差异几乎全部是配置差异，共性全部上收到内核。**
> 核心公式：**统一实现 = 冻结的 GroundedQuery/KnowledgeDigest/GapSignalCard/AuditVerdict/FetchLedger/DualRateLedger 数据模型与双率记账规则（内核，不可换）+ 两车道物理隔离与审计 advisory 硬约束（内核）+ 六操作面可替换实现（插件，各分确定性/LLM/可学习三档，audit_judge 无可学习档）+ 十六轴编译成的 profile（配置）+ 双速调度与检索预算经济学协议（运行时）**。

---

## 0. 设计公理（从失效模式分析强制推出，不可协商）

### 0.0 开篇声明：四条框架级不变量 + 第五候选（与 M2/M5/M8M9 对齐，M6 侧投影）

以下四条不变量横跨 M2/M5/M8/M9 独立出现（与 M2-UNIFIED §0.0 逐字一致）；M6 经根因对账后**不提出第六条候选不变量**——三根因全部被既有四条 + 第五候选覆盖或互补（详见 `m6_分歧_公理.md` 任务三）：

1. **不变量 I-α（锚点存在性）**：框架内任何被优化压力触及的积累物必须配一个物理上不可被该压力修改的锚点组件。→ M6 侧投影（**互补**）：两车道零共享 + 更广文献检索是给 novelty 判定**造一个锚**（独立检索=判定的外部锚定信号）；K16 隔离违规检测是给这个锚配 I-α 式的谱系/审计兜底（AIDE² 反作弊层自毁同构：结构约束必须有运行时验证）。M6 的失效不是锚被压力改坏，而是**锚根本不存在**——审计没有独立于构想的证据来源，"未找到先验"只是"构想期没读过"的重述。
2. **不变量 I-β（质量指标一等化）**：任何裁决/积累机制必须暴露其判别质量指标；"机制动作次数"不得作为健康证据。→ M6 侧投影（**完全覆盖**）：K14"无质量数据的 verdict 不得进 merge 参考"与 M9 侧"无探针的门不得行使否决权"、M2 侧"无漏斗数据的算子不得参与自适应选择"是同一规则在第三个模块的同型实例；verdict 的 reliability 字段直接复用 M8 ReliabilityMeta 形态。**M6 的反直觉补充**：advisory（无权力）信号比 veto 信号更需要质量度量——veto 的误判会以"好 idea 被杀"显性暴露，advisory 的误判永远沉默（AI-Scientist 12/12 误判存活到第三方复评才暴露）。这把 I-β 的适用范围从"行使权力的机制"推广到"被消费的参考信号"。
3. **不变量 I-LLM（LLM 建议、确定性终裁）**：→ M6 侧投影：novelty 判定由 LLM 产三档 advisory 建议，终裁权在 M9 综合裁决 + 金标复核（D2/D3）；引用合法性判据是行为事实（fetch ledger 台账查询）而非 LLM 自证（D7）。
4. **不变量 I-谱系（记录带谱系、可失效、不删除硬证据）**：→ M6 侧投影：fetch ledger（url+content_hash+车道标签）/ grounding/related_work 分别溯源 / eval_mode 随候选入谱系 / 格式契约版本入 X1 / 违规 verdict 软作废硬永存（复用 M8M9 票据失效语义）。
5. **候选不变量 I-披露（信号通道最小披露）【候选，待框架级确认】**：框架内任何进入优化循环消费侧的信号通道，默认实行最小披露——每个字段必须回答"接收方能拿它讨好谁/过拟合谁"。**M6 是 I-披露的第四模块投影，并实质性加强其上收论证**：M6 的注入格式最小化（方案全文→压缩 digest→gap/约束信号）是 I-披露在"外部知识→构想"通道的降档阶梯，与 M2 侧"数值→分档→方向→1bit"同构；但该通道的失效机制**不是讨好/过拟合**（构想 LLM 不拿注入文本讨好谁），而是**分布拖拽**（注入表示对生成分布的一阶矩拖拽，2605.27905 的 219,655 idea 四一致负发现）——这证明 I-披露的约束力比"防 hacking/防讨好"更一般：即使接收方完全无害，过宽披露仍经注意力/先验通道造成系统性退化。M2 原论证的两条投影机制（可讨好面、注意力稀缺）由此补上第三种机制。此外 K9 benchmark 全关=披露降档的极限（0 bit），为 I-披露补充"披露档位影响测量有效性"的新维度。【推断：I-披露上收与否及精确措辞由框架定稿阶段裁决，M6 贡献的第三机制与第三/第四模块投影建议计入其普适性论证】

> 边界备注：I-披露与 K2 车道隔离**互补不互相覆盖**——披露闸按**接收方**降档（能给构想器看多少），车道隔离按**用途**分道（同一页面不能既 inspire 又 certify）；完全最小披露的系统仍可单车道循环论证，两车道隔离的系统仍可 flat 拼接吃收敛效应。故 D1（隔离）与 D5（格式）必须同时在位。

### 0.1 公理 D1–D10（失效证据 → 内核物化，全部 MUST）

与 `m6_分歧_公理.md` 严格一致。全 MUST 的理由：直接锚点全部是**双向误判/群体级收敛/幻觉污染**级别的已付费学费（12/12、9/10、219,655 idea、57%），无"修复手段存在"或"证据偏旧"的降级理由；参数级内容（抽样比例 10–20%、报警阈值等）为【推断】占位符——公理级别 MUST（机制必须在位），参数级别只保证可配、可记账、可回滚。

| # | 公理 | 强制级别 | 失效证据指认（关键数字） | 违反检测 |
|---|---|---|---|---|
| D1 | **启发与审计物理隔离，禁降级档**：ground/audit 两车道独立检索、零共享抓取文本、字段分离（grounding vs related_work 类型不同、写入权限按车道校验）；单车道与共享缓存的逻辑分离均为禁止取值；隔离落到数据层/运行时层/部署层三层机制，不靠实现纪律 | MUST | AI-Scientist false-novel 12/12——深层死因是单车道结构而非参数，加 10×10 预算修复无效（arXiv:2502.14297）；Arbor "the two lanes run independent searches and never share fetched text"【原文】；2606.12071 comparative 偏袒 27.2%→49.1%（"见过"即污染） | K16 静态配置检查（启动时校验缓存命名空间/字段路由）+ 运行时抓取文本哈希重叠扫描（同 content_hash 跨车道=违规，作废 verdict） |
| D2 | **审计永不阻断：advisory 是唯一合法定位**：audit verdict 仅作 M9 merge/准入的参考输入，三档（novel/partial-overlap/prior-art-exists），veto 档在类型层不可选；裁决权（含忽略 verdict）在 M9；merge 决策记录须注明消费的 audit_id 与档位 | MUST | AI-Scientist 双向误判：false-novel 12/12 + false-kill 9/10（2502.14297）；RQ-Bench 人机一致性 22%（2606.12071）；veto 把判定器的不可知错误率直接换算成流水线误杀/漏放率 | verdict 阻断流水线=构建期拒绝；M9 决策记录缺 audit 消费标注=审计不通过 |
| D3 | **审计判别质量必须独立测量：无质量数据的 verdict 不得进参考**：建立抽样人工/金标复核台账（prior-art verdict 高比例全检 + novel verdict 10–20% 随机抽 + merge 采纳样本事后金标）；verdict 携带 reliability 字段（sampled_rate/false_novel_rate/false_kill_rate/n_reviewed，复用 M8 ReliabilityMeta 形态）；无复核覆盖的 verdict 按"无审计"处理而非按"novel"处理；误判率超阈的审计配置计零 | MUST | 同 D2 双率；K14 盲区——advisory verdict 的误判永远沉默，AI-Scientist 12/12 误判存活到第三方复评才暴露；M2-O20 同型先例（无漏斗数据的算子不得参与自适应选择） | verdict 缺 reliability 字段或不带 audit_query_trace=拒绝入台账；复核采样缺失=K14 审计不通过 |
| D4 | **审计检索独立且面向更广文献：审计费是购买 verdict 信息量的唯一支付**：audit 由专门检索通道全新执行（独立 session/缓存命名空间，查询仅从 idea 文本构造，不得由 ground digest 派生）；audit 语料集 ⊇ ground 语料集作为配置不变量；后端静默降级按车道分别记账（审计实际覆盖的后端集落 verdict 元数据） | MUST | Arbor 独立 SearchAgent【原文】；ToI "broader literature beyond Tr"【原文】；AI-Scientist ≤10 条元数据+LLM 一票的浅判定失效（2502.14297）；复用 ground 结果的"审计"信息量恒等于零 | K16 启动校验语料包含关系；audit 查询文本与 ground digest 相似度超阈=软破窗报警 |
| D5 | **注入表示的语法主语必须是 gap/约束/失败模式，不是方案**：flat RAG 拼接为禁止默认；注入格式默认压缩 digest（隔离上下文中生成），成熟档升 gap 信号卡；信号卡须带 ≥2 独立轨迹证据 + 非显而易见闸门（闸门是 schema 校验规则不是 prompt 建议）；任何格式档变更按实验对待（强制 2×2 消融重跑、版本入 X1、可回滚） | MUST | 2605.27905 五框架×五 LLM、219,655 个 idea 四一致负发现（更集中、更贴近起始文献、与未来人类方向对齐更差、低影响区）；ToI 消融去 gap 建模 −0.72、去跨轨迹信号 −0.65（arXiv:2608.10740） | packet/digest schema 缺 provenance/类型字段=构建期拒绝；格式变更无 2×2 消融记录=配置评审拒绝 |
| D6 | **注入后收敛效应必须外置探针监控，fitness 不得作触发条件**：ground 车道开启的任何运行必须配分布探针（idea 分布集中度、与起始文献距离的时间序列+报警）；报警语义=多样性指标异常，禁止以 fitness 为触发条件；探针指标复用 M2-O9 DiversityProbe 基础设施；语义距离量用嵌入时须多模型投票+人工抽检锚定并记录嵌入模型版本（换模型=台账重置） | MUST | K15 盲区——收敛效应在 fitness 曲线上隐形（局部精加工使分数不降甚至微升，plateau 被误读为收敛）；2605.27905 四发现在 fitness 曲线上全部不可见【推断】；与 M2-O1 plateau 归因陷阱同构 | ground 开启而探针时间序列缺失=构建期报错（同型 M2-C1"无探针的循环默认视为已塌缩"） |
| D7 | **引用诚实以行为事实为判据：未打开来源丢弃 + 全链路 provenance**：维护抓取台账 fetch ledger（url, content_hash, timestamp, 车道标签），引用合法性=台账查询；一切产物（digest/信号卡/packet/verdict）内嵌 provenance 字段；凭 LLM 记忆生成的引用为禁止取值；provenance 记录带车道标签（K16 重叠审计的前置） | MUST | AI-Scientist 57% 手稿含幻觉数值、中位 5 条引用且多数过时（2502.14297）——幻觉多为"元数据冒充阅读"的合理外推；Arbor "Sources that were never actually opened are dropped"【原文】；KAPSO SOURCE_REPO/commit provenance【原文】 | 产物缺 provenance=构建期拒绝；引用来源不在 fetch ledger=运行期拦截；截断边界未记录进 provenance=台账不完整报警 |
| D8 | **M6 不拥有消费逻辑：双工具契约是唯一供给通道**：M6 仅暴露 `query(intent)`（ground）与 `audit(idea)`（audit）两个类型化入口；产物以带标签字段进 M2-O5 ContextRecipe 经白名单筛选后进上下文；M2 不直连检索后端；缺字段的产物在类型层被拒 | MUST | R&D-Agent 消融 w/o Memory Context −9% vs w/o Reasoning Pipeline −24%（arXiv:2505.14738）——知识价值上限由消费管线决定而非知识质量；openresearch-cli 零耦合路线的责任真空（防污染/审计时机/压缩/provenance 无人负责）【推断】 | M2 侧出现直连知识后端的调用=构建期拒绝；产物 schema 缺类型/provenance/来源类型标签=类型层拒绝 |
| D9 | **失败触发的联合入口必须来源分标**：失败信号同时路由 M5 recall 与 M6 repair 检索时，两路产物注入前必须分开标注来源类型（`era_internal`/`era_external`）；分标义务独立于检索预算——即使只查一路产物也须带标签；失败信号复用 M8 白名单字段，不新建失败表示 | MUST | KAPSO ERA【原文】；边界定稿【原文】（内部经验约束"别再试什么"/外部文献回答"世界已知什么"，混注=让 LLM 猜证据极性）；MemRL `include_negative` 分块先例；R&D-Agent 纯内部记忆 −9% 的有限价值 | 汇合上下文缺来源类型标签=O5 配方校验拒绝；repair intent 出现在非失败触发上下文=运行期拦截 |
| D10 | **评测模式 M6 全关，模式标识进谱系**：benchmark/评测模式 ground/audit 两车道全关，模式标识由 M8/M9 传入（M6 不自判）；eval_mode 随每条候选进 X1 谱系（跨模式分数禁止混报）；公平模式是跨模块联合状态（M5 只读 + M6 关 + M8 密封），单模块开关不构成公平 | MUST | Arbor 双车道默认 off 的公平性论证【原文】；2605.27905 开着检索的产出更集中更不原创；57% 幻觉数值（2502.14297）——"开而不洁比不开更糟" | benchmark 标识下任一车道产生检索记录=违规事件进 X1 并作废相关产物；候选记录缺 eval_mode 字段=拒绝入库 |

---

## 1. 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4  调度与协议（双速 sync 禁 LLM / ERA 联合入口 / 2×2 消融协议  │
│          / 检索预算分级与上报 M3）                                   │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  操作面接口：retrieve / compress / card_compose /          │
│          audit_judge / ledger_record / probe                      │
│          每操作面三类实现：确定性 | LLM | 可学习（audit_judge 除外）   │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  冻结机制：两车道物理隔离三层实现 + 审计双触发三档 advisory    │
│          （类型层禁止 veto）+ 双预算 6k/2k + benchmark 模式全关        │
│          + fetch ledger 引用诚实 + 双率台账 + 注入引力探针（X1）       │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  冻结数据模型：GroundedQuery / KnowledgeDigest /            │
│          GapSignalCard / AuditVerdict / FetchLedger / DualRateLedger│
└──────────────────────────────────────────────────────────────────┘
         ↑ Layer 1/2 标注 evolvability: kernel_fixed（隔离/审计防护组件 self_mutable=false）
         ↑ Layer 3 标注 evolvability: operators_only（检索 prompt 可进化须逐版本入 X1）
         ↑ 经典系统 = profile = Layer 3 实现选择 + Layer 4 配置
```

**M6 的模块分工**（三条定稿边界）：M6 = 外部世界——回答"世界已知什么"，只管"取、压、证、隔离"四件事；注入/去重执行/QD 约束归 M2（M6 只供给证据），准入/merge 裁决归 M9（audit verdict 只是参考输入），失败信号语义归 M8，预算总额归 M3，内部经验归 M5。跨界处只留接口（K10 联合入口 / K13 双工具契约）不留轴。

---

## 2. Layer 1：冻结数据模型

六个新类型。与既有类型的挂接：GroundedQuery 的 repair intent 消费 M8 白名单失败信号（"items 的错误定位信息"）；AuditVerdict 复用 M8 ReliabilityMeta 形态；GapSignalCard 与 KnowledgeDigest 以带标签字段进 M2-O5 ContextRecipe；FetchLedger/DualRateLedger 复用 X1 append-only 存储。

```python
# core/knowledge/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

Lane = Literal["ground", "audit"]                # K2 车道标签：一切产物的强制字段
Intent = Literal["related_work", "survey", "lookup", "explore", "repair"]
# Arbor 四 intent（related_work=重叠/缺口评估, survey=领域格局, lookup=具体事实,
# explore=开放扫描）+ repair（ERA 失败修复）★ audit 不走 intent 体系——audit 语义
# 不出现在 intent 词汇表是刻意的排他设计（K5×K16），审计只走 audit(idea) 入口

# ---- ground 车道查询（K5 的物化；配置即数据，YAML 可扩）----
@dataclass
class GroundedQuery:
    query_id: str
    intent: Intent                               # ★ 强制：无 intent 的自由文本查询=类型层拒绝
    text: str
    context: dict = field(default_factory=dict)
    # repair 专属：{failure_signal: M8 白名单错误定位字段}——失败信号不重新建模，
    # 直接复用 M8 白名单字段作 ERA query 构造原料（分歧 7 前置条件）
    depth_tier: Literal["shallow_2k", "deep_6k", "mid"] = "deep_6k"
    # K6：lookup→shallow_2k，survey/explore→deep_6k，repair（失败触发）→mid
    eval_mode: Literal["research", "benchmark"] = "research"
    # ★ D10：由 M8/M9 传入，M6 不自判；benchmark 时本对象构造即拒绝（车道全关）

# ---- 压缩产物（K4 取值②；ground 车道默认返回形态）----
@dataclass
class KnowledgeDigest:
    digest_id: str
    query: GroundedQuery                         # 谱系：由哪个查询产生
    summary: str                                 # 在隔离上下文中生成——压缩过程与消费过程
    findings: list[str] = field(default_factory=list)  # 同窗口=原文已污染主上下文（实现陷阱）
    sources: list[str] = field(default_factory=list)   # 编号来源，每项须命中 FetchLedger
    confidence: float = 0.0
    provenance: dict = field(default_factory=dict)
    # ★ D7：{query_used, source_pages, opened: [url+ts], truncation_boundary}；
    # 截断边界未记录=台账不完整报警
    lane: Lane = "ground"                        # 写死：digest 只能产自 ground 车道

# ---- gap 信号卡（K4 取值③/K11 取值③；ToI 结构的本框架物化）----
@dataclass
class GapSignalCard:
    gap_id: str                                  # 稳定标识，进 X1 谱系
    kind: Literal["convergent", "cross_link"]    # 共享 gap / 跨轨迹桥接
    statement: str                               # gap 内容：遗留什么未解、为何卡住
    evidence: list[dict] = field(default_factory=list)
    # ★ 硬约束：≥2 条独立轨迹 {trace_id, paper_id, path_excerpt}——演化树路径片段
    # 而非论文正文段落（引用正文=退化为带编号的方案拼接）；单谱系延续被拒
    trajectory_independence: bool = False        # 两条证据不得同谱系
    non_obviousness_gate: dict = field(default_factory=dict)
    # ★ 非显而易见闸门（schema 校验规则，不是 prompt 建议——填不出即拒）：
    # {collapses_to: str|None（若可还原为教科书式组合，命名其坍塌到的先验方法）,
    #  structural_novelty: str（组合给不出的结构性质）}
    constraints: list[str] = field(default_factory=list)   # 环境/资源约束（可来自 KAPSO 式 Environment 条目）
    failure_modes: list[dict] = field(default_factory=list)
    # 已知失败模式，与 M5 pitfall 条目对齐且分标来源类型（era_internal/era_external，D9）
    provenance: dict = field(default_factory=dict)       # K12 契约，同 KnowledgeDigest
    ttl: Optional[float] = None                  # gap 时效（生态位会移动）；过期条目运行期拦截

# ---- 审计裁决（K7 的物化；三档 advisory，类型层无 veto 档）----
AuditTier = Literal["novel", "partial_overlap", "prior_art_exists"]
# 语义（K7 深挖）：novel="未找到先验"（受来源覆盖与判定机制双重限制，不是"不存在"）

@dataclass
class AuditReliability:                          # ★ 复用 M8 ReliabilityMeta 形态（D3）
    sampled_rate: float = 0.0                    # 复核覆盖率
    false_novel_rate: Optional[float] = None     # 漏报率（金标复核实测）
    false_kill_rate: Optional[float] = None      # 误杀率
    n_reviewed: int = 0                          # 已复核样本数；低于噪声底（样本不足）
                                                 # 的 verdict 按"无审计"处理而非按"novel"

@dataclass
class AuditVerdict:
    audit_id: str
    idea_id: str                                 # X1 坐标
    verdict: AuditTier                           # ★ 枚举不含 veto——类型层禁止（D2）
    audit_phase: Literal["add_precheck", "merge_review"]  # 双触发标注：预检护树/复核护名
    closest_paper_id: Optional[str] = None       # 最接近论文
    overlap_risk: str = ""                       # 具体重叠点/风险描述
    audit_query_trace: list[dict] = field(default_factory=list)
    # ★ D3：query 序列+backend 命中数——误判归因要区分"检索没查到"（K3/K6 问题）
    # 与"查到了但判错"（judge 问题）；缺此字段=拒绝入台账
    backends_covered: list[str] = field(default_factory=list)
    # 本次审计实际覆盖的后端集（K3 静默降级按车道分别记账的落点）
    reliability: AuditReliability = field(default_factory=AuditReliability)  # 缺=拒绝入台账
    fetch_refs: list[str] = field(default_factory=list)  # FetchLedger 引用（K12）
    lane: Lane = "audit"                         # 写死

# ---- 抓取台账（D7 的物化；K12/K14/K16 三轴共同前置——一次设计到位）----
@dataclass
class FetchLedger:
    seq: int                                     # 单调递增，append-only（复用 X1）
    url: str
    content_hash: str                            # ★ 重叠审计的判定键：违规=同一 fetch 产物
    # （content_hash）跨车道流动，而非"同来源巧合重合"（同一论文被两车道各自命中合法且期望）
    timestamp: float = 0.0
    lane: Lane = "ground"                        # ★ 车道标签：K16 重叠扫描的前置
    truncation_boundary: Optional[str] = None    # 截断位置记录（"打开过但被截断算不算读过"）
    backend: str = ""                            # 实际命中后端（静默降级记账）

# ---- 双率台账（K14 的物化；对标 M2-O20 FunnelRecord）----
@dataclass
class DualRateLedger:
    verdict_id: str
    idea_id: str
    verdict: AuditTier
    audit_query_trace: list[dict] = field(default_factory=list)  # 同 AuditVerdict，复核原料
    fetch_refs: list[str] = field(default_factory=list)
    sampled_for_review: bool = False
    review_truth: Optional[Literal["true_novel", "true_overlap"]] = None  # 人工/金标标注
    error_kind: Optional[Literal["false_novel", "false_kill", "correct",
                                 "isolation_violation"]] = None
    # ★ isolation_violation 单列：隔离违规作废的 verdict 不计入 false-novel/false-kill，
    # 以免污染校准信号（K16×K14）
    reviewer: str = ""                           # 人 / 金标集标识
    review_date: float = 0.0                     # 复核时机错开（verdict 后 ≥1 周【推断】占位）
```

**双工具契约（K13/D8：M6 对外的唯一供给通道）**：

```python
# core/knowledge/api.py —— 类型层强制，M2 不直连检索后端
def query(q: GroundedQuery) -> KnowledgeDigest | GapSignalCard | list[TypedPacket]:
    """ground 车道唯一入口。返回对象结构上不含可写入 related_work 的句柄（D1 数据层物化）；
       repair intent 仅在 ERA 失败触发上下文合法，否则运行期拦截（D9）"""

def audit(idea: IdeaNode) -> AuditVerdict:
    """audit 车道唯一入口。独立 SearchAgent、独立 session/缓存命名空间；
       查询仅从 idea 文本构造（不得由 ground digest 派生，D4）；
       verdict 永远 advisory——本函数返回类型里不存在 veto 语义"""

# M6 → M2 供给字段（进 O5 ContextRecipe 白名单）：grounding_packets / era_external
# M6 ← M5 消费（K10）：M5.retrieve(query=失败摘要, scope=任务局部, include_negative=True)
# M6 → M9 供给：AuditVerdict 经 M2 流转至 merge 决策，裁决权在 M9 不在 M6
```

**设计决定说明**：
- `Intent` 枚举含 repair 但**不含任何 audit 语义**是 K2 隔离在 API 层的钉死——自由文本查询无法区分"启发"与"自我验证"（若 ground 被用来查"我这个 idea 是不是 novel"，就是在自建一条无隔离的伪 audit 车道）。
- `AuditVerdict.reliability` 与 `audit_query_trace` 是 D3 的物化：无复核覆盖的 verdict 按"无审计"处理而非按"novel"处理——把"检索失败默认映射为 novel=True"（AI-Scientist 错误方向被默认值放大的教训）反向硬编码。
- `FetchLedger` 是 K12/K14/K16 三轴的共同前置：url+content_hash+timestamp+车道标签四字段一旦建成，两条盲区轴（K14 复核采样、K16 重叠审计）从"新建检测系统"降级为"对现有台账跑查询"——故按三轴需求一次设计到位。
- `GapSignalCard.evidence` 引用**路径片段**（演化关系）而非论文正文段落——否则信号卡退化为"引用更多的 flat RAG"（消融 −0.72/−0.65 证明两个结构成分各自扛真实增益，闸门是格式的一部分不是可选质检）。

---

## 3. Layer 2：冻结机制（内核，不可学习、不可绕过）

### 3.1 两车道物理隔离：三层实现（D1，分歧 5 硬约束落地）

"两车道零共享"不能靠实现纪律，必须落到三层机制（对标 M2-O17 第④件 AIDE² 教训——结构约束必须有谱系/审计兜底）：

1. **字段分离（数据层）**：IdeaNode schema 中 `grounding`（list[digest_ref]）与 `related_work`（AuditVerdict 对象）是两个类型不同的独立字段；写入权限按车道做调用方校验——`query()` 返回对象结构上**不含**可写入 related_work 的句柄。
2. **独立检索上下文（运行时层）**：audit 由专门 SearchAgent 全新检索（"so it can't be fooled by whatever grounded ideation read earlier"，Arbor【原文】）。工程要点：(a) 两车道独立检索 session/缓存命名空间，禁止共享 HTTP cache 与 embedding cache 键空间；(b) audit 查询**仅从 idea 文本构造**，不得由 ground digest 派生（否则 digest 内容经查询词泄漏进 audit 上下文，形成软破窗——D4 软破窗报警）；(c) audit 语料集 ⊇ ground 语料集为配置不变量。
3. **静态检查（部署层，K16）**：启动时校验两车道独立 backend 配置、独立上下文构造、分离落库字段、语料包含关系；K16 检查代码本身的版本入 X1（复用 M2-O17④——检查器被改坏就是下一个 AIDE²）。运行时重叠审计（同 content_hash 跨车道=违规，报警+作废 verdict，软作废硬永存）在 verdict 进入 merge 参考前启用。

**禁降级声明（分歧 5 正式裁决）**：本隔离为**无条件硬约束**——单车道混合与逻辑分离（共享缓存）均为禁止取值。"逻辑分离到底污染多少 verdict 质量"虽无定量测量（证据空缺），但中间档的失效形态是**信息量为零且静默**——在失效不可检测的方向上不允许省预算。隔离的最大威胁不是恶意绕过而是"热心"的工程优化（统一缓存"省 API 调用"），故隔离声明必须编译成运行时不变量。

### 3.2 审计双触发与三档 advisory（D2/D3，分歧 3 正式裁决）

- **双触发默认**：(a) **add 时后台预检**（Arbor `auto_search_on_add`）：新 idea 入树即触发后台审计，verdict 落 `related_work` 字段不阻塞（"it never blocks a run"）——审计对象是"未验证的 idea"，价值=防谱系树在已知方向上扩张（护树）；(b) **merge 决策前复核**：审计对象是"已验证的 idea"，确认 win 是否也是 contribution（护名）。
- **三档 verdict 与 M9 职责切分**：novel=merge 报告 contribution 措辞依据之一，**不构成加分**；partial_overlap=M9 必须要求谱系/报告显式定位差异，**不构成减分**；prior_art_exists=强参考信号，merge 须给出"实证增益独立于先验"的论证，**仍不是一票否决**——裁决权（含忽略 verdict 的权力）永远由 M9 基于 fitness 显著性+预算+verdict 综合行使。
- **类型层禁止 veto**（D2）：`AuditTier` 枚举无 veto 档；veto 把判定器的不可知错误率（RQ-Bench 人机一致性 22%）直接换算成流水线误杀/漏放率。三档与 advisory 互为前提：硬闸门迫使判定器把不确定性压成错误，"不阻断"使 verdict 可以诚实报告不确定性。
- **advisory 的可信性由 D3 台账持续挣得**：无质量数据的 verdict 不得进 merge 参考（对标 M2-O20"无漏斗数据的算子不得参与自适应选择"）。误杀代价（整个已验证分支）> 浪费一次实验——该论证只在 false-kill 率被实测且有界时成立。

### 3.3 阅读深度双预算（K6）

- **分级双预算默认**：构想深读 `research_visit_tokens`≈6000（方法/结果章节在截断后幸存）；审计浅读 `visit_max_content_tokens`≈2048（"abstracts are enough to judge prior art"，Arbor【原文】——先验判定是存在性命题，深读不加宽度只烧预算）。
- **失败触发检索用中档深度**；**迭代轮数上限**为必要护栏（AI-Scientist ≤10 轮 × ≤10 条配置下仍 12/12 误判——预算不能弥补判定机制缺陷，但上限防 agent 把检索当无限预算循环）。
- 深度档绑定**车道+intent**（lookup 浅读、survey/explore 深读、repair 中档），不绑定任务难度；每页 token × 轮数 = 检索成本科目进 M3。
- 截断位置有语义：截断器须感知章节结构（alphaXiv SDK 全文路线可得结构化章节，纯网页抓取只能按字符截断）——深度档可兑现性依赖来源后端结构化程度（×K3）【推断】。

### 3.4 benchmark 模式全关与 eval_mode 谱系（D10，分歧 6 落地）

- **benchmark/评测模式 M6 两车道全关**（定稿）：模式标识 `eval_mode ∈ {research, benchmark}` 由 M8/M9 传入，**M6 不自判**——模式判定权与评估语义同侧。
- **eval_mode 随每条候选进 X1 谱系**——否则同一报告里的两组分数可能跑在不同污染档位上而不可归因（跨模式分数禁止混报）。
- **公平模式是跨模块联合状态**（M5 只读快照 + M6 全关 + M8 密封），单模块开关是假公平；联合状态归属 M8 评估编排层，M6 只消费模式标识。
- **泄漏检测档**（全关+对产出做与已知方案相似度扫描，防 M5 内部记忆外溢）默认关、条件触发（M5 global scope 且题集重叠风险时）——阈值/扫描语料/误报处置全线无标定，按"先记账后定参"处理【推断，无一手先例】。
- 注意：2×2 消融（§3.6）中"关 ground"格同时是公平模式的演练场——一套协议服务两个轴。

### 3.5 ERA 联合入口协议（D9，分歧 7 落地）

- **默认联合触发 + 来源类型分标**：失败信号 s≠∅ 同时触发 M5 `retrieve(query=失败摘要, scope=任务局部, include_negative=True)` 与 M6 `query(intent=repair)`——一次失败、两路归因（"世界已知不行" vs "我们试过不行"）。
- **分标义务独立于检索预算**：即使只查一路，产物也必须带来源类型标签（`era_internal`/`era_external`）——分标是零成本的结构收益，混注=让 LLM 猜证据极性。
- **三方拓扑**：ERA 产物**不直接进变异器 prompt**，而是作为 M2-O5 ContextRecipe 的两类带标签食材，经 O5 白名单筛选后才进上下文（保持"M6 不拥有消费逻辑"边界）；配方变更按实验对待（M2 idle 槽 recipe_experiment）自然覆盖 ERA 注入形态的 A/B。
- **失败信号不重新建模**：s 直接复用 M8 白名单"items 的错误定位信息"（traceback/失败类别）；s 若只是"分数没涨"级模糊信号，ERA 退化为噪声触发的预算泄漏（分歧 1 前置条件）。
- **成本**：ERA 是失败条件化成本，进 M3 独立科目；失败率高的任务成本线性放大，ERA 每候选触发上限可配。repair intent 仅在 ERA 上下文合法（K5 排他）。
- **PIVOT 纠错档**（PIVOT 决策时重跑检索并排除当前 seed 仓库）：注入格式为强锚定档（类型化 packet/seed 锚定）时配套；信号卡弱约束档可省。

### 3.6 注入格式变更强制 2×2 消融协议（D5×K15）

- **触发条件**：K4 取值切换（digest→信号卡等）、信号卡 schema 变更、K11 供给档位变更。
- **协议**：变更版本作为配方/契约版本入 X1；开/关 ground × 开/关 audit 四格对照在同一任务族上跑固定预算，报告四个多样性指标（集中度/起始文献距离/与历史轨迹重叠度/产量）+ fitness；fitness 差分判定用 M8 CI/噪声底（B7 计零规则复用）；**回滚条件**：多样性指标退化超阈值且 fitness 增量低于噪声底。
- **语法主语校验规则（D5 的 schema 物化）**：注入内容的语法主语必须是 gap/约束/失败模式而非方案——写成 schema 校验（信号卡 evidence ≥2 独立轨迹、非显而易见闸门填不出即拒）而非 prompt 建议；flat RAG 拼接仅作 2×2 对照基线保留。

### 3.7 注入引力探针与收敛效应监控（D6，K15 盲区补轴）

- **探针架在注入事件两侧**：每次 K1 触发检索时记录 (a) 注入前窗口（近 W 个 idea 的分布统计）、(b) 注入 packet/digest 指纹（内容哈希+类型）、(c) 注入后窗口（下 W 个 idea 分布统计+与注入内容的相似度分布）。核心报告量：**注入引力 = 注入后窗口 idea 与注入 packet 的相似度均值 − 与随机历史 packet 的相似度均值**。引力>0 且持续=注入在拉拽种群（方案克隆形态）；引力≈0 而多样性上升=gap 信号卡理想形态。【推断：原创设计，无一手实现】
- **fitness 禁作报警触发条件（D6 硬编码）**：收敛效应的最危险形态是 fitness 上升（局部精加工产出高分低风险改进，plateau 被误读为收敛）——用 fitness 触发=让失效自己报告自己。报警语义=多样性指标异常。
- **指标陷阱双层处理**：种群内部集中度用行为级/模板级指标（复用 M2-O9 DiversityProbe，嵌入指标禁用——arXiv:2508.13333）；"与文献的距离"这类本质语义的量允许多嵌入模型投票+人工抽检锚定，探针记录标注嵌入模型版本（换模型=参照系变=台账重置，同型 M2-C4）。
- **O8 通过 + K15 报警 = 重新发明轮子**：M2-O8 管"种群 vs 内部档案"，K15 管"种群 vs 外部文献"——两条轴必须共存的最小案例。

### 3.8 "先记账后定参"原则（三盲区轴显式声明）

K14/K15/K16 三条盲区轴的**检测机制层零先例**：双率台账之外的采样协议参数、注入引力探针灵敏度（W 窗口、显著性检出所需注入次数）、重叠审计误报率（"同 fetch 产物 vs 同来源"口径的合法交集大小）全线无一手标定；三轴的根因证据全是失效侧——无任何系统报告"装了监控后的运行数据"，收益是"避免已知灾难"而非"证明有效"。落地策略只能是**先记账、后定参**（对齐 M2"先建日志，后调策略" / M5-A5）：fetch ledger、双率台账、探针时间序列从第一天就记录，阈值与采样率是【推断】占位符——设计只保证可配、可记账、可回滚。

### 3.9 证据日志（复用 X1，append-only）

与 M2/M5/M8M9 共用同一 X1 存储。每个产物携带：来源 ID+打开记录+车道标签（grounding/related_work 分别溯源）、audit_query_trace+backends_covered、K4 格式契约版本、K16 静态检查结果与违规事件、eval_mode、探针时间序列与 2×2 消融记录。违规作废 verdict 的处置可追溯（软作废硬永存，复用 M8M9 票据失效语义）。

---

## 4. Layer 3：操作面×实现类矩阵

六操作面 × 三实现类：

| 操作面 | 确定性实现（默认与兜底） | LLM 实现（主力生成） | 可学习实现（opt-in） | 默认实现类 |
|---|---|---|---|---|
| retrieve（检索执行） | 有序 backend 列表+静默降级+结果合并去重（Arbor 协议）；缓存命名空间路由 | LLM 查询构造（intent→检索词扩展） | —（证据空缺：检索质量的可学习优化无先例） | 确定性 + LLM 查询构造 |
| compress（压缩 digest） | 章节感知截断器（方法/结果幸存）、未打开来源丢弃（台账查询） | 隔离上下文中生成 summary+findings+编号来源 | —（压缩质量由 K15 探针间接测量，不单列学习档） | LLM（隔离上下文）+ 确定性截断 |
| card_compose（信号卡构建） | 演化树路径提取、≥2 轨迹独立性校验、非显而易见闸门 schema 校验（填不出即拒） | gap 陈述撰写、跨轨迹桥接识别（ToI EvoAgent 形态） | —（离线建库期批处理，学习化无信号来源【推断】） | LLM + 确定性闸门校验 |
| audit_judge（新颖性判定） | 金标探针集注入检测（已知 novel/已知 prior-art 探针样本定期过管线） | 专门 SearchAgent fresh search + 三档 verdict 生成（独立上下文，查询仅从 idea 文本构造） | **无可学习档**（见下） | LLM（advisory）+ 确定性探针 |
| ledger_record（台账记账） | fetch ledger 写入（url+content_hash+车道标签）、双率台账写入、重叠哈希扫描 | —（记账层禁止 LLM，I-LLM） | — | 确定性（唯一） |
| probe（分布探针） | 集中度/起始文献距离时间序列计算（行为级指标）、注入引力统计、报警阈值比较 | 语义距离的人工抽检锚定材料准备 | —（探针是 I-β 锚点组件，self_mutable=false） | 确定性 |

**audit_judge 无可学习档的理由（硬编码）**：(a) D3 要求误判率被金标复核独立测量——可学习判定器的训练信号恰恰只能来自其自身 verdict 的历史，用被判对象的历史训练判定器=把 K14 想消除的"误判沉默"制度化（同型 M5"有偏评审器使退休机制静默空转"，arXiv:2607.07436）；(b) RQ-Bench（2606.12071）证明 LLM novelty 判定的失效是**评价维度缺失**（狭隘误读为新颖）而非参数不足，学习化放大偏置而非修复；(c) 审计 prompt/检索深度/来源集的校准走 K14 台账反馈环（版本化+进 X1+按实验对待），不走梯度。校准反馈环本身必须被监控（谁校准校准器），开启前置=台账积累 ≥数十个标注样本且双率稳定超出目标带。

**实现类升级前置（对齐 M2 C10 同型门）**：任何操作面升级须消融证明增量超 M8 噪声底；`injection_mode=forced`（强制每轮注入）开启须有 M2 侧 ContextRecipe 已被消融验证的记录，否则配置评审拒绝（分歧 2：未验证管线前的常驻注入=常驻成本+常驻收敛拖拽换不来稳定增益）。

---

## 5. Layer 4：调度 YAML（双速，对齐 M2/M5/M8M9 先例）

```yaml
# knowledge/schedule.yaml
schedules:
  sync:                        # 关键路径，每次 query/audit 调用前后；硬约束：禁 LLM（对齐 M5-A4）
    - op: fetch_ledger_record  # 抓取台账写入（url+content_hash+timestamp+车道标签）
      constraint: no_llm       # 记账层 LLM 注册到 sync 直接报错
    - op: provenance_check     # 引用合法性=台账查询；来源不在 fetch ledger=运行期拦截（D7）
    - op: intent_gate          # repair intent 上下文合法性校验；audit 语义出现在 ground 查询=报警（D9/K16）
    - op: eval_mode_gate       # benchmark 标识下任一车道检索=违规事件进 X1 并作废产物（D10）
  idle:                        # 默认档：空闲窗/代际边界
    - op: overlap_audit        # K16 运行时重叠扫描（audit 产物 vs ground 抓取历史 content_hash 比对）
    - op: injection_gravity    # D6：注入引力统计+分布探针时间序列+报警（fitness 禁作触发）
    - op: digest_refresh       # ttl 过期 digest/信号卡处置（降级不删除，对齐 M5-A2）
  scheduled:                   # 可选：长程维护
    - op: dual_rate_review     # K14 抽样复核（prior-art 高比例全检 + novel 10–20% 随机抽 + merge 采纳金标）
      cron: "weekly"           # 复核时机错开 verdict ≥1 周【推断】占位
    - op: golden_probe_set     # 金标探针集注入审计管线（每领域已知 novel/已知 prior-art 各 ≥10 条）
    - op: ablation_2x2         # K15：格式变更强制重跑 + 定期漂移复跑（报告四多样性指标+fitness）

lane_isolation:                # D1：启动静态检查清单（K16 最低档必配）
  static_checks: [backend_config_independent, cache_namespace_separated,
                  field_routing_separated, corpus_superset_audit_over_ground]
  violation_action: invalidate_verdict_soft   # 软作废硬永存，error_kind=isolation_violation 单列

budget:                        # K6：显式分级定价，注册进 M3
  research_visit_tokens: 6000  # 构想深读
  visit_max_content_tokens: 2048  # 审计浅读
  era_per_candidate_cap: configurable   # ERA 每候选触发上限（失败条件化成本独立科目）
  accounting: {query: per_page_token_x_rounds, audit: per_call_flat}

era:                           # K10/D9：联合入口
  trigger: failure_signal_structured    # s 唯一合法来源=M8 白名单错误定位字段
  routes: {internal: M5.retrieve(scope=task, include_negative=true),
           external: M6.query(intent=repair)}
  labeling: required           # era_internal/era_external 分标义务独立于检索预算
  injection_path: M2_O5_context_recipe_whitelist   # ERA 产物不直接进变异器 prompt

format_contract:               # K4/D5：注入格式即契约版本
  injection_format: digest     # flat(禁) | digest | signal_card | typed_packet
  on_change: [bump_contract_version, rerun_2x2_ablation, record_to_X1, rollback_ready]
  signal_card_schema: {min_independent_traces: 2, non_obviousness_gate: required}
```

**与其他模块的协议钩子**：
- **预算上报（→ M3）**：query 按页 token×轮数、audit 按次定额、ERA 独立科目；常驻注入档（forced）的 token 成本线性项单独可见。
- **M9 接口**：merge 决策记录须注明消费的 audit_id 及档位；无 verdict 的 merge 与忽略 verdict 的 merge 可审计区分；无复核覆盖的 verdict 按"无审计"处理（M9 硬规则，同型 B7 噪声底计零）。
- **M8 接口**：失败信号白名单字段供给 ERA；eval_mode 标识传入；2×2 消融 fitness 差分消费 M8 CI/噪声底；审计 prompt 版本变更复用 M8 receipt 失效级联降权机制。
- **M5 接口**：ERA 内部侧走 M5.retrieve 固定骨架（召回→效用重排→状态过滤），include_negative=True 档即内部侧实现。
- **M2 接口**：去重证据（embedding+来源 ID+重叠定位三元组）进 M2 新颖性闸的 similarity_records；gap 信号进 O5 ContextRecipe 注入槽；K15 探针指标复用 M2-O9 DiversityProbe 基础设施与报警→M1 父代切换消费链。

---

## 6. 七分歧裁决编译表

| # | 分歧 | 裁决变量 | 默认值 | 配置项 | 硬编码 | 协议 |
|---|---|---|---|---|---|---|
| 1 | 离线建库 vs 按需检索 | 任务簇可摊销性 × gap 地图需求 | 可选工具+失败触发；离线建库冷启动/升档专用 | `ground_trigger ∈ {offline_kb, on_demand_tool, forced_inject(禁默认), failure_conditioned, full_combo}`，默认 `on_demand_tool + failure_conditioned` | 工具注册时必须同时注册使用时机偏好（无偏好注入的"可选"=实际不用） | 失败触发的 s 唯一合法来源=M8 结构化失败信号（写入 M6×M8 接口契约）；token 成本进 M3 科目 |
| 2 | 强制注入 vs 可选工具 | 消费管线（M2-O5）是否被消融验证 | 可选工具；forced 须有消融记录 | `injection_mode ∈ {on_demand, forced}`（默认 on_demand） | forced 档开启须有配套消融记录，否则配置评审拒绝（C10 同型门） | 2605.27905：默认注入=默认拖拽；R&D-Agent −9%：常驻注入受管线钳制 |
| 3 | 审计 advisory vs veto | 误判双率 × 误杀代价结构（正式确认定稿边界） | 双触发（add 预检+merge 复核）+ 三档 advisory，veto 禁止取值 | —（veto 档在类型层不可选） | AuditTier 枚举无 veto；裁决权（含忽略 verdict）在 M9 | M9 merge 决策记录须注明消费的 audit_id 及档位；无 verdict 的 merge 与忽略 verdict 的 merge 可审计区分；前置=K14 台账+K8 独立检索在位 |
| 4 | gap 信号卡 vs digest 注入 | 离线建库在位 × K15 监控在位 | digest 起步→信号卡为演进目标；flat RAG 禁默认 | `injection_format ∈ {flat(禁), digest, signal_card, typed_packet}`（默认 digest） | 格式变更=契约版本变更入 X1，强制 2×2 重跑；语法主语约束（gap/约束/失败模式）写成 schema 校验规则 | 信号卡 evidence ≥2 独立轨迹+非显而易见闸门填不出即拒（闸门是格式的一部分不是可选质检） |
| 5 | 共享缓存中间档是否允许 | 无（硬约束，禁降级） | 两车道零共享+字段分离为唯一合法取值 | — | 三层机制：字段分离（query() 返回对象结构上不含写 related_work 的句柄）+独立检索上下文（缓存键空间分离）+静态检查 | audit 语料集 ⊇ ground 语料集为配置不变量；在失效不可检测的方向上不允许省预算 |
| 6 | benchmark 全关 vs 泄漏检测档 | M5 跨任务共享 × 题集重叠风险 | benchmark 全关；泄漏检测档默认关、条件触发 | `eval_mode ∈ {research, benchmark}` + `leak_detection ∈ {off, on}`（默认 off） | eval_mode 随每条候选进 X1 谱系（跨模式分数禁止混报） | 公平模式=跨模块联合状态（M5 只读+M6 关+M8 密封）归 M8 评估编排层，M6 只消费模式标识；泄漏检测档"先记账后定参" |
| 7 | 联合入口同步 vs 按需 | 双侧能力 × 失败信号结构化 | 联合触发+来源分标；双路成本上限可配 | ERA 触发上限（进 M3 独立科目） | 分标义务独立于检索预算——即使只查一路产物也须带标签；repair intent 仅在 ERA 上下文合法 | M5×M6×M8 三方契约：信号 schema、分标字段 era_internal/era_external、ERA 产物经 M2-O5 白名单筛选（不直接进变异器 prompt）；PIVOT 档在强锚定格式时配套 |

---

## 7. 证据强度与投资优先序

**证据强度排序**（合并轴系与两批深挖，强→弱）：

1. **审计 advisory+隔离的反向证据**（AI-Scientist 双向误判实测：false-novel 12/12、false-kill 9/10，arXiv:2502.14297；RQ-Bench 人机一致性 22%、comparative 偏袒 27.2%→49.1%，arXiv:2606.12071）——方向最强的恰是**禁止性**证据：D1/D2 锚定的是"不能怎么做"。
2. **收敛效应大规模实证**（2605.27905：5 框架×5 LLM、219,655 个 idea 四一致负发现）——样本量最大，但为框架级聚合，格式作为解释变量是【推断】。
3. **gap 信号卡**（ToI 6 主题 6.27 vs 最强基线 5.36、人类参考 6.29；消融去 gap 建模 −0.72、去跨轨迹信号 −0.65，arXiv:2608.10740）——最强正面数字，但混杂"离线建库"与"信号卡格式"两变量，且仅 6 主题单一评分体系。
4. **消费管线钳制**（R&D-Agent 消融 w/o Memory Context −9% vs w/o Reasoning Pipeline −24%，arXiv:2505.14738）——内部记忆语境，向外部知识契约外推为【推断】。
5. **去重证据供给**（IDEAgent Yield 3.89×，arXiv:2607.22375）——论文自定义指标，无跨系统复现。
6. **预算分级与后端协议**（Arbor 2048/6000 双预算、有序 backend+静默降级、未打开来源丢弃）——单系统工程选择，无消融（4k 审计是否改善 verdict 未知）。
7. **ERA 联合入口与三盲区轴机制层**（KAPSO ERA 无开关消融；K14/K15/K16 检测机制全线无一手先例）——方向有失效侧证据锚定，收益是"避免已知灾难"而非"证明有效"。

**投资顺序表（硬编码进 Layer 3 升级前置与 M3 预算科目）**：

| 顺位 | 投资方向 | 依据 |
|---|---|---|
| 1 | 两车道隔离三层机制 + fetch ledger（K2/K12） | 全部其他机制的语义前提；fetch ledger 是 K12/K14/K16 三轴共同前置，一次建成使两条盲区轴降级为"对台账跑查询" |
| 2 | 双工具契约 + 产物 schema 字段义务（K13/D8） | 契约栈是 M6 全部其他轴的价值乘数（R&D-Agent −9%/−24%） |
| 3 | 审计双触发三档 advisory + 双率台账（K7/K14） | advisory 定位的可信性完全押在 K14 上；台账先行，定参后置 |
| 4 | 分布探针 + 2×2 消融协议（K15/D6） | 探针缺位时 ground 开启=默认拖拽；复用 M2-O9 基础设施使成本可控 |
| 5 | 注入格式升档 digest→gap 信号卡（K4/K11） | 最强正面数字在信号卡档，但前置=离线建库+K15 探针在位 |
| 6 | ERA 联合入口与 PIVOT（K10） | 分标是零成本结构收益先行；联合触发的增量收益未量化，成本上限保守起步 |
| 7 | 来源扩展（仓库语料/策展 KB）与泄漏检测档（K3/K9） | 重来源服务"约束与修复"而非新颖性（audit 要宽不要深）；泄漏检测零先例，记账先行 |

---

## 8. Profile 兼容性验证（统一性的证明）

五个经典系统编译为 profile（Layer 3 实现选择 + Layer 4 配置），**除 AI-Scientist 的 veto 档为禁止取值外，无一处需要改内核**；每个 profile 诚实标注该系统实际违反的公理。

### 8.1 arbor_two_lane（两车道 + 双预算 + 三档 advisory）★默认形态的来源

```yaml
profile:
  name: arbor_two_lane
  axes: {K1: 构想中可选工具(intent化), K2: 两车道零共享+字段分离, K3: 文献+web[alphaxiv,jina]免key,
         K4: 压缩digest, K5: 四intent, K6: 双预算6k/2k, K7: add预检+merge复核三档advisory,
         K8: 独立fresh search, K9: benchmark全关, K12: 未打开来源丢弃, K13: 双工具契约}
  lanes: {ground: {intent_set: [related_work, survey, lookup, explore],
                   backends: [alphaxiv, jina], depth: 6k, default: off},
          audit: {trigger: [auto_search_on_add, pre_merge], depth: 2k,
                  verdict: three_tier_advisory}}   # "it never blocks a run"
  isolation: {field_split: [node.grounding, node.related_work], shared_fetch_text: false}
  citation: {drop_unopened_sources: true}
```
内核复用：两车道、双预算、三档 verdict、backend 静默降级、未打开丢弃全部是 D1/D2/K6/K12 的原生形态——本 profile 即框架默认配置的命名。
**公理违反标注**：原系统**违反 D1 的验证层精神而非条文**——隔离仅靠实现纪律（docs/search.md 为设计声明，无运行时验证机制报告，缺 K16 档）；**违反 D3**（无误判双率台账，审计真实双率从未被测量）；K16 静态检查清单为 profile 层补齐。【诚实标注】

### 8.2 ai_scientist_veto（单车道 + veto 闸门）★反例 profile——不可编译为合法配置

```yaml
profile:
  name: ai_scientist_veto
  axes: {K1: 构想后veto闸门(禁止取值), K2: 单车道混合(禁止取值), K3: 纯Semantic Scholar关键词,
         K6: ≤10轮×≤10条, K7: veto闸门(禁止取值), K8: 复用ground结果(禁止取值),
         K12: 无provenance(禁止取值), K14: 无度量(禁止取值)}
  # ★ 本 profile 无法通过构建期校验——它的价值是作为 lint 规则的反例测试集
```
**公理违反清单（诚实标注，本 profile 存在的意义）**：
- **违反 D1**（单车道混合：判定分布与构想分布同源，12/12 false-novel 的深层死因是结构而非参数——加 10×10 预算修复无效）；
- **违反 D2**（veto 闸门：非 novel 即弃，把不可知错误率换算成流水线误杀/漏放率；同技术栈评审 agent false-kill 9/10 人类已接收论文）；
- **违反 D3**（无判别质量度量：上线即 12/12 误判而不自知，存活到第三方复评才暴露）；
- **违反 D4**（≤10 条元数据+LLM 一票的浅判定，查询由 idea 自身生成，"无明确匹配即 novel=True"把检索失败默认映射为 novel）；
- **违反 D7**（无 provenance：57% 手稿含幻觉数值、中位 5 条引用且多数过时——元数据冒充阅读）。
框架侧对应防御：AuditTier 枚举无 veto 档（构建期拒绝）、K16 静态检查拒绝单车道配置、novel verdict 的默认语义反转为"未找到"且低复核覆盖按"无审计"处理、引用合法性=fetch ledger 查询（运行期拦截）。

### 8.3 kapso_era（离线建库 + ERA 联合入口）

```yaml
profile:
  name: kapso_era
  axes: {K1: 全程组合(初始化锚定+每轮KR+失败ERA), K3: +2000+仓库语料/策展KB(Neo4j+Weaviate双索引),
         K4: 类型化bounded packet(Principle/Implementation/Environment/Heuristic),
         K5: +repair intent, K10: 联合触发+PIVOT纠错, K12: 全链路provenance(SOURCE_REPO/commit)}
  ground_trigger: full_combo          # RepoRetrieve 置信度 ρ≥τ 用检索仓库做起点
  era: {trigger: failure_signal, labeling: [era_internal, era_external],
        pivot: {rerun_retrieve: true, exclude_current_seed: true}}
  sources: {repo_corpus: 2000+, curated_kb: mediawiki, index: [neo4j, weaviate]}
  provenance: {fields: [query_used, source_pages, path, commit]}
```
内核复用：ERA 联合触发与分标=K10/D9 原生协议；bounded packet=K4 取值④原生；provenance 字段集=D7 原生。
**公理违反标注**：原系统**无 audit 车道**（KAPSO 明确"不声称 novelty"——这是诚实声明而非违规，但意味着 D2/D3/D4 在其形态下无落点，若直接用其检索栈做审计即违反 D1/D4）；ERA 无开关消融（联合触发增量收益未量化，profile 层强制 ERA 成本上限保守起步）；PIVOT 排除粒度（整仓库）可能误伤有效起点【证据空缺】。【诚实标注】

### 8.4 tree_of_ideas（gap 信号卡 + 非显而易见闸门 + 引文演化树）

```yaml
profile:
  name: tree_of_ideas
  axes: {K1: 构想前离线建库, K4: gap信号卡, K8: 独立+面向更广文献(beyond Tr),
         K11: gap地图供给(convergent+cross_link), K12: 全链路provenance(≥2独立轨迹)}
  offline_kb: {build: [evograph_citation_graph, evoagent_cards],  # 演化树不可在线构建
               frontier_select: true}
  signal_card: {min_independent_traces: 2, single_lineage_reject: true,
                non_obviousness_gate: {collapses_to: required, structural_novelty: required}}
  audit: {corpus: broader_literature_beyond_Tr}
```
内核复用：GapSignalCard schema 即 ToI 结构的原生物化（≥2 轨迹、非显而易见闸门、单谱系延续被拒）；6 主题 6.27 vs 5.36、消融 −0.72/−0.65 是信号卡档的最强正面证据。
**公理违反标注**：原系统**无 add/merge 双触发审计管线**（beyond-Tr 复核是构想期组件而非 D2 双触发形态，verdict 无三档语义）；**无 D6 探针**（ToI 自身未监控其注入的收敛效应）；6.27 vs 5.36 混杂"离线建库"与"信号卡格式"两变量、仅 6 主题单一评分体系【证据空缺已标注】。【诚实标注】

### 8.5 ideagent_qd（去重证据供给，多样性约束执行在 M2）

```yaml
profile:
  name: ideagent_qd
  axes: {K4: digest, K11: 去重证据供给, K13: 双工具契约}
  diversity_supply: {evidence: [embedding, source_id, overlap_location],  # 三元组 schema
                     consumers: [M2.novelty_gate, M2.qd_maintenance],     # 执行全部在 M2
                     compare_against: [completed_ideas, ancestors, rejected_proposals]}
  qd_execution: null   # ★ 边界定稿：QD/去重执行归 M2，M6 只供给证据（Yield 3.89×）
```
内核复用：去重证据三元组直接对接 M2 `VariationProposal.similarity_records`（缺失=拒绝入库的 C3 硬编码已就位）——本 profile 验证的是"M6 只供给、M2 执行"的边界可在类型层表达。
**公理违反标注**：原系统**无 audit 车道与车道隔离概念**（多样性比较与新颖性审计在其形态下未分离，若复用同一检索做审计即违反 D1/D4）；3.89× Yield 为论文自定义指标无跨系统复现；去重证据的嵌入模型选择无标定——与 M2 新颖性闸的嵌入陷阱（arXiv:2508.13333）同源，profile 层强制记录嵌入模型版本（换模型=台账重置）。【诚实标注】

**兼容性结论**：五个 profile 覆盖调研中全部经典系统设计空间，差异 = 车道配置 + 格式档 + 来源集 + 时机组合 + 供给档位，全部在配置层；AI-Scientist 作为反例 profile 证明禁止取值集合真实可执行（其全部关键设计选择落在类型层/构建期拒绝路径上）。表达不了的进 §9 边界声明。

---

## 9. 诚实边界声明（统一不了的东西，合并后 8 条）

1. **三盲区轴（K14/K15/K16）机制层零先例，"先记账后定参"**：双率台账之外的采样协议参数、注入引力探针灵敏度（W 窗口、显著性检出所需注入次数）、重叠审计误报率（"同 fetch 产物 vs 同来源"口径的合法交集大小）全线无一手标定；三轴根因证据全是失效侧——无任何系统报告"装了监控后的运行数据"，收益是"避免已知灾难"而非"证明有效"。所有阈值与采样率是【推断】占位符，设计只保证可配、可记账、可回滚。
2. **K4 格式轴缺"同内容仅改格式"的受控实验**：2605.27905 未按注入格式分层报告（格式作为解释变量是【推断】）；ToI 6.27 vs 5.36 混杂"离线建库"与"信号卡格式"两变量；信号卡 vs digest 的同预算对照不存在——D5 的"语法主语"规则是机制推断+消融旁证，digest 档增益无一手数字。
3. **Arbor 式审计的真实双率从未被测量**：AI-Scientist 的 12/12 与 9/10 是其特定判定栈（关键词+一票 LLM）的数字；独立 SearchAgent+三档+实际打开的审计管线，其 false-novel/false-kill 率无任何一手数据——K14 台账的第一批数据是空白，D3 的目标带只能以"相对上一配置版下降"为动态目标。
4. **KAPSO ERA 无开关消融**：`RetrieveKnowledge(g,r̂,s)` 的增量收益从未与基础检索分离测量；联合入口作为跨模块协议是框架原创设计，证据全靠类比；PIVOT 排除粒度（整仓库）可能误伤有效起点——D9 的分标义务锚点可靠（R&D-Agent −9% 一手），但"联合触发"的增量收益本身未量化。
5. **R&D-Agent −9%/−24% 是内部记忆语境的消融**，向外部知识契约（K13）与时机轴（K1）的外推是【推断】；IDEAgent 3.89× Yield 是论文自定义指标无跨系统复现——消费管线钳制与去重证据供给两条关键证据的跨域迁移性未验证。
6. **K9 泄漏检测档零先例 + audit 车道公平档语义未分离**：检测阈值/扫描语料/误报处置全部无标定；"benchmark 模式下 audit 是否也该全关"Arbor 原文未区分（全关意味着评测产出 novelty 溯源断链）；eval_mode 跨模块联合状态（M5 只读+M6 关+M8 密封）尚无归属模块【推断：可能归 M8】。
7. **参数级占位符全线无敏感性分析**：K6 双预算 2048/6000（Arbor 单系统工程选择，4k 审计是否改善 verdict 未知）、"更广文献"宽度参数（audit/ground 来源集比例）、K14 抽样比例 10–20% 与复核时机 ≥1 周、K15 报警阈值、"打开过但被截断算不算读过"的截断边界规则——设计只保证可配、可记账、可回滚，不保证默认值最优。
8. **RQ-Bench 证据向 idea/方法级判定的外推未证**：2606.12071 是 RQ 级（上游）判定（人机一致性 22%、comparative 偏袒），idea/方法级 novelty 判定的偏置是否同构未证【新搜，外推风险】；"独立 fresh search vs 复用 ground 结果"的 verdict 质量对照实验不存在（D1/D4 禁止取值的依据是机制推断+单车道实证，非 A/B 测量）。

---

## 10. 分阶段落地（M6a–M6d，对接 ADAPT-v1.1）

| 期 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|
| **M6a（类型层+隔离，P0）** | GroundedQuery/KnowledgeDigest/AuditVerdict（AuditTier 无 veto 档）/FetchLedger 落 core/knowledge/types.py；双工具契约骨架（query/audit）；字段分离与写权限校验（query() 返回对象无 related_work 句柄）；K16 静态检查清单初版（缓存命名空间/字段路由/语料包含关系）；eval_mode 字段贯通 | 类型层增量并入 ADAPT-v1.1 Step 0；构造 veto 语义/无 intent 查询/缺 provenance 产物被类型层拒绝的单测通过；benchmark 标识下检索调用=违规事件进 X1 的单测通过 | 无，与 G1/M2a/M5a/E9a 类型层改动同批 |
| **M6b（最小可用 ground，P1）** | retrieve（有序 backend+静默降级+合并去重）+ compress（隔离上下文 digest+章节感知截断）+ 双预算 6k/2k + fetch ledger 全量记账（sync 槽，禁 LLM）+ ERA 联合入口（M5 recall + repair intent 分标 era_internal/era_external，经 M2-O5 白名单）；arbor_two_lane profile（ground 侧） | fetch ledger 在真实运行中产出非零台账；ERA 产物分标字段在 ContextRecipe 白名单校验通过；缺车道标签的 fetch 记录被拒的单测通过 | M6a + M5b retrieve 骨架 + M8 失败信号白名单；并入 Step 1 |
| **M6c（audit 车道+盲区轴记账，P2）** | audit_judge（独立 SearchAgent、查询仅从 idea 文本构造、三档 advisory、audit_query_trace/backends_covered 落元数据）+ 双触发（add 预检+merge 复核）+ DualRateLedger 与抽样复核协议（金标探针集常驻）+ K16 运行时重叠审计 + 注入引力探针与分布时间序列（idle 槽，复用 M2-O9）；kapso_era profile（audit 侧按本框架补建） | 双率台账在真实运行中积累（哪怕全是"待复核"）；重叠违规作废 verdict（软作废硬永存）的集成测试通过；无 reliability 的 verdict 被 M9 按"无审计"处理的契约测试通过 | M6b + M9 merge 决策记录契约；并入 Step 2 |
| **M6d（格式升档+消融协议，P3）** | card_compose（离线建库 EvoGraph 形态+信号卡双闸门 schema 校验）+ 2×2 消融协议强制挂钩格式变更 + gap 地图供给档（K11）+ 泄漏检测档记账骨架；tree_of_ideas / ideagent_qd profile | 信号卡闸门"填不出即拒"单测通过；格式变更触发 2×2 重跑且版本入 X1 的演练通过；探针时间序列可区分注入引力>0/≈0 两种形态（模拟数据） | M6c + 离线建库预算（M3）；并入 Step 3；不阻塞既有里程碑 |

**明确不做**（延续 ADAPT-v1.1 "won't do" 纪律）：
- 不做 veto 档审计（AuditTier 枚举无 veto，类型层禁止，D2）
- 不做单车道/共享缓存中间档（禁降级硬约束，失效不可检测的方向上不省预算，D1）
- 不做 flat RAG 拼接默认档（仅作 2×2 对照基线保留，D5）
- 不做 M2 直连检索后端的任何路径（双工具契约是唯一供给通道，D8）
- 不做 audit_judge 可学习档（训练信号只能来自自身 verdict 历史=制度化误判沉默，§4）
- 不做 fitness 触发的收敛报警（让失效自己报告自己，D6）
- 不做框架外"零耦合"工具面形态（无契约=防污染/审计时机/压缩/provenance 无人负责，K13）

---

## 11. 一句话规格

> **M6 = 冻结的 GroundedQuery/KnowledgeDigest/GapSignalCard/AuditVerdict/FetchLedger/DualRateLedger 数据模型（intent 化查询、双率记账、三档 advisory 类型层无 veto、抓取台账带车道标签）+ 两车道物理隔离三层机制（字段分离/独立检索上下文/静态检查，禁降级）与引用诚实（未打开来源丢弃，引用合法性=台账查询）+ 双工具契约 query(intent)+audit(idea) 为唯一供给通道（M6 不拥有消费逻辑）+ 审计双触发三档 advisory（裁决权归 M9，无质量数据的 verdict 不得进参考）+ 注入语法主语约束与 2×2 强制消融（digest 起步→gap 信号卡，flat RAG 禁默认）+ 注入引力探针（fitness 禁作触发）+ ERA 联合入口（失败信号双路触发、era_internal/era_external 强制分标）+ benchmark 模式全关（eval_mode 进 X1 谱系）+ 六操作面×三实现类矩阵（audit_judge 无可学习档）+ 十六轴编译成的 profile（Arbor/KAPSO/ToI/IDEAgent 是 profile 实例，AI-Scientist 是反例测试集）+ D1–D10 全 MUST 公理内核化与四条既有不变量承接（M6 不贡献新候选，但以"分布拖拽"第三失效机制与第四模块投影强化 I-披露的上收论证）。**
