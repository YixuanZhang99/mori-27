# M6 Knowledge 定稿轴系（Stage 2 · 轴系建立）

> 依据：`docs/M5记忆与M6知识设计深度分析.md` 第二/三部分（三维分类学 + 5 设计模式 + 边界定稿）、`research/m5m6/m6_groupC_knowledge.md`（Arbor / AI-Scientist / KAPSO / R&D-Agent / openresearch-cli / ToI / IDEAgent / 2605.27905）、`research/m5m6/m5m6_groupE_frontier.md`（前沿补盲）。格式对标 `m2/m2_axes_final.md`。数字均引自上述三份产物；新补搜标【新搜】，调研者归纳标【推断】。

## 轴系设计原则（与 M2/M5/M8M9 轴系的风格一致性约定）

1. **轴 = 决策维度，不是组件列表**。每条轴回答一个"实现 M6 时必须做的、可不同答的选择"；"接不接 Semantic Scholar API"这类组件问题不成轴（归 K3 来源混合的取值细节），"检索意图集的开闭与粒度"才成轴。
2. **取值 = 可互斥、可组合的配置点**。同轴取值互斥（选一档），跨轴自由组合（强相关处以"×"标注）。每轴给默认值；默认值 = 在"评估噪声中等、预算有限、需保 benchmark 公平"的标准 AutoResearch 场景下证据最强的档。
3. **每条轴必须被证据锚定**：至少一条失效反例（反推）或一手实证（正推）。纯概念轴剔除。
4. **职责边界显式化（三条定稿边界写入轴取值约束）**：
   - **启发与审计隔离**：ground 与 audit 两车道零共享抓取文本、字段分离（K2 为硬约束轴，不允许合并取值）；
   - **审计永不做硬闸门**：audit verdict 只 advisory， veto 式取值在 K7 中被标记为禁止默认（AI-Scientist 双向误判反例）；
   - **M6 不拥有消费逻辑**：M6 只管"取、压、证、隔离"，注入/去重执行/QD 约束归 M2，准入裁决归 M9——跨界处只留接口（K10/K13）不留轴。
5. **接口依赖标注**：每条轴标注它消费谁（M5 recall / M8 失败信号 / M3 预算）、向谁供给（M2 算子上下文 / X1 谱系 provenance）。
6. **盲区轴从失效反推**（学 M2 O9/O20 做法）：对照 AI-Scientist 双向误判、2605.27905 收敛效应、两车道循环论证三类已记录失效，补 K14–K16 三条监控轴——"审计判别质量从未被独立测量""注入后的收敛效应在 fitness 曲线上隐形""隔离违规无检测手段"分别是它们的根因。

---

## 第〇部分：合并与裁决

### 候选轴处置表

| 候选 | 处置 | 理由 |
|---|---|---|
| 三维分类学（时机/来源/用途） | **细化拆散**：时机→K1+K7；来源→K3；用途→不成独立轴，降解为 K5 检索意图集 + K4 注入格式的取值语义 | 分类学是描述框架不是决策轴；"用途"六值（启发/锚定/约束/修复/审计/引用）实际是车道×意图的乘积，独立成轴会与 K1/K5 重复计数 |
| 车道隔离结构 | **独立成轴 K2** | 三条定稿边界之首，且是唯一有显式工程实现（Arbor）的结构性决策 |
| 触发时机 vs 审计时机 | **拆为 K1（ground 车道触发）与 K7（audit 车道时机与阻断性）** | 两者违约代价不同源：K1 影响预算与原创性，K7 影响误杀/漏报；合并会掩盖"审计永不阻断"约束的落点 |
| 阅读深度/预算分级 | **独立成轴 K6**（吸收"检索迭代轮数"） | Arbor 双 token 预算（6k/2k）是可复用一手设计；与 K1 正交（同一时机可选不同深度档） |
| benchmark 公平模式 | **并入 K9 防污染策略**（作为其最强档取值） | "M6 默认全关"是防污染谱系的端点，非独立决策 |
| 引用诚实（来源必须实际打开） | **独立成轴 K12 provenance/引用诚实** | 有独立失效证据（AI-Scientist 57% 手稿含幻觉数值、中位 5 条引用且过时）与独立机制（未打开来源丢弃、provenance 链路） |
| 联合入口（M5×M6 ERA） | **独立成轴 K10** | 跨模块联动的唯一显式设计点（KAPSO ERA）；M5/M6 边界定稿指定其为联合入口 |
| 多样性供给 | **独立成轴 K11**（M6 侧只供给证据，QD 执行归 M2） | IDEAgent Yield 3.89× 证据强；但边界定稿明确多样性约束属 M2，故本轴只覆盖"M6 供给什么抗收敛证据" |
| 消费管线接口 | **独立成轴 K13** | R&D-Agent 消融（−9% vs −24%）证明无好消费管线则知识价值有限；接口契约是 M6 对 M2 的唯一义务 |
| 后端/key 管理细节 | **剔除**，并入 K3 取值描述 | 组件级问题（原则 1） |
| 离线建库（ToI EvoGraph / KAPSO learn） | **不成轴**，作为 K1 的取值 ① | 是时机档而非独立维度 |
| 盲区三轴（审计判别质量 / 收敛效应监控 / 隔离违规检测） | **全部成轴 K14/K15/K16** | 对照 M2 从失效反推 O9/O20 的先例；三类失效均有已记录一手证据且无任何既有轴覆盖 |

**最终轴系：16 轴**（K1–K16）。

---

## K1 Ground 车道触发时机与策略

**一句话定义**：外部知识在搜索循环的哪个相位、以何种触发方式（常驻/按需/信号条件化）进入构想过程。

| 取值 | 描述 |
|---|---|
| 构想前离线建库 | ToI EvoGraph 演化树、KAPSO learn——最贵、结构化程度最高 |
| 构想中可选工具 | Arbor grounded lane、orx-lit：agent 自主决定何时查，默认按需 |
| 构想中强制注入 | R&D-Agent memory context 式每轮注入（外部版即 KAPSO KR） |
| 失败后条件化增强 | KAPSO ERA：失败信号 s≠∅ 才追加检索，非常驻 |
| 全程组合 | 初始化锚定 + 每轮基础检索 + 失败增强（KAPSO 三点位） |

**关键证据锚点**：KAPSO 三点位级联检索（WSR 主 + PFR 兜底 + ERA 增强，arXiv:2601.21526）；R&D-Agent 消融 w/o Memory Context −9%（35.1→32.0 Any Medal）vs w/o Reasoning Pipeline −24%（arXiv:2505.14738）——注入时机价值受消费管线制约；Arbor ground 车道默认 off。
**默认值**：构想中可选工具（intent 化）+ 失败后条件化增强；离线建库仅在领域冷启动且无内部经验时开启。
**耦合**：×K6（时机决定深度档）；×K10（失败触发即 ERA 联合入口）；×M3（常驻注入的 token 成本须进预算核算）；×K9（benchmark 模式下本轴强制 off）。

## K2 车道隔离结构（硬约束轴）

**一句话定义**：启发（ground）与审计（audit）两条车道的检索上下文、抓取文本与落地字段的隔离强度。

| 取值 | 描述 |
|---|---|
| 单车道混合 | 同一检索结果既启发又作证——循环论证（禁止取值） |
| 逻辑分离 | 两次检索但共享缓存/抓取文本（弱隔离，禁止取值） |
| 两车道零共享 + 字段分离 | 独立检索、从不共享抓取文本；`node.grounding` vs `node.related_work` 字段分离（Arbor 唯一显式实现） |

**关键证据锚点**：Arbor `docs/search.md`【原文】："The two lanes run independent searches and never share fetched text — so the same page can't both inspire an idea and certify it as novel"；AI-Scientist 单车道反例：12/12 idea（含 micro-batching、自适应学习率等已知技术）全判 novel（arXiv:2502.14297）。
**默认值**：两车道零共享 + 字段分离（**定稿边界，无降级档**；单车道与逻辑分离为禁止取值）。
**耦合**：×K8（audit 检索独立性是隔离的执行面）；×K16（隔离违规需独立检测手段）；产物字段进 X1 谱系（grounding/related_work 分别溯源）。

## K3 来源混合与后端配置

**一句话定义**：M6 检索覆盖的来源类型组合与后端优先级、降级策略。

| 取值 | 描述 |
|---|---|
| 纯公共文献库 | Semantic Scholar / alphaXiv / OpenAlex（AI-Scientist、orx-lit） |
| 文献 + 通用 web | Arbor 默认 `[alphaxiv, jina]` 全免 key 组合 |
| + 代码仓库语料 / 策展知识库 | KAPSO：2000+ 仓库语料 + MediaWiki 策展 KB（Neo4j+Weaviate 双索引） |
| 有序 backend 列表 + 静默降级 | 缺 key 后端静默跳过，结果合并去重（Arbor backend 协议） |

**关键证据锚点**：Arbor 后端有序列表（alphaxiv/jina/serper/exa/exa-mcp/自托管 endpoint，缺 key 静默跳过）【原文】；KAPSO 语料规模 2000+ 仓库、条目带 SOURCE_REPO/commit provenance【原文】；AI-Scientist 仅 Semantic Scholar 关键词检索是漏报根因之一（2502.14297）。
**默认值**：文献 + 通用 web（`[alphaxiv, jina]` 免 key 起步）；仓库语料/策展 KB 按领域接入。
**耦合**：×K12（来源决定 provenance 链路的可追性）；×K8（audit 须面向"更广文献"，来源集不得与 ground 子集重合，ToI 教训）。

## K4 注入格式（反收敛的核心旋钮）

**一句话定义**：M6 产物注入搜索上下文时的表示形态——方案拼接还是结构化信号。

| 取值 | 描述 |
|---|---|
| flat RAG 拼接 | 摘要/原文段落直接进上下文——已被证伪的失效配置 |
| 压缩 digest | summary + findings + 编号来源，隔离上下文中生成（Arbor） |
| gap/约束/失败模式信号卡 | ToI：gap 中心演化信号卡 + 方向须 ≥2 条独立轨迹证据 + 非显而易见闸门 |
| 类型化 bounded packet | KAPSO：四类型（Principle/Implementation/Environment/Heuristic）+ typed edges + 置信度 + provenance |

**关键证据锚点**：2605.27905 大规模实证：5 框架 × 5 LLM 生成 219,655 个 idea，AI idea 系统性更集中、更贴近起始文献、位于历史生态位低影响区——"注入方案→克隆；注入 gap/约束→扩大探索"；ToI 6 主题 6.27 分 vs 最强基线 5.36（人类参考 6.29），去 gap 建模 −0.72、去跨轨迹信号 −0.65（arXiv:2608.10740）。
**默认值**：压缩 digest 起步，成熟后升级 gap 信号卡；flat RAG 拼接为禁止默认。
**耦合**：×K15（注入格式是收敛效应的第一调节阀，须配监控）；×K11（信号卡是多样性供给的载体）；×K13（格式即 M6→M2 契约的 schema）。

## K5 检索意图集（intent taxonomy）

**一句话定义**：ground 车道对算子暴露的查询意图词汇表及其开闭性。

| 取值 | 描述 |
|---|---|
| 无 intent（自由文本查询） | 通用 web 搜索形态，不可审计查询目的 |
| Arbor 四 intent | `related_work`（重叠/缺口评估）、`survey`（领域格局+取舍）、`lookup`（具体事实）、`explore`（开放扫描） |
| 四 intent + 失败修复意图 | + ERA 式 `repair`（失败条件化的 heuristics/诊断/替代实现检索） |

**关键证据锚点**：Arbor `ResearchSearch` 工具 4 intent【原文】；KAPSO ERA 失败条件化检索 `RetrieveKnowledge(g, r̂, s)`【原文】。
**默认值**：Arbor 四 intent + repair；意图集为配置即数据（YAML 可扩）。
**耦合**：×K1（repair intent 仅在后置/失败触发档位可用）；×K16（intent 标注是 ground/audit 归属判定的依据——audit 不走 intent 体系，走独立 audit(idea) 入口）。

## K6 阅读深度与预算分级

**一句话定义**：单次检索/访问的 token 预算与迭代深度，按车道与相位分级。

| 取值 | 描述 |
|---|---|
| 统一浅读 | 全部按摘要级截断（~2k token/页） |
| 统一深读 | 全部保方法/结果章节（~6k token/页）——审计车道浪费预算 |
| 分级双预算 | 构想深读 `research_visit_tokens`≈6000；审计浅读 `visit_max_content_tokens`≈2048（"abstracts are enough to judge prior art"） |
| 分级 + 迭代轮数上限 | AI-Scientist 参数化：≤10 轮 × ≤10 条结果/轮（其判定失败在意图词匹配而非预算本身，但轮数上限仍是必要护栏） |

**关键证据锚点**：Arbor 双 token 预算 2048/6000【原文】；AI-Scientist 10 轮 × 10 条配置下仍 12/12 误判——预算不能弥补判定机制缺陷（2502.14297）。
**默认值**：分级双预算（构想 6k / 审计 2k）+ 迭代轮数上限。
**耦合**：×M3（每页 token × 轮数 = 检索成本科目）；×K1（失败触发检索用中档深度）。

## K7 审计时机与阻断性（硬约束轴）

**一句话定义**：novelty audit 在流水线中的触发点及其 verdict 对流程的阻断权力。

| 取值 | 描述 |
|---|---|
| 构想后 veto 闸门 | AI-Scientist：非 novel 即弃——**禁止取值**（双向误判反例） |
| add 时后台预检 | Arbor `auto_search_on_add`：新 idea 入树即触发后台审计，verdict 落字段不阻塞 |
| merge 决策前 advisory 审计 | Arbor 默认：审计对象是"已验证的 idea"，确认 win 是否也是 contribution |

**关键证据锚点**：AI-Scientist 双向误判实测：漏报——12/12 idea（含已知技术）全判 novel；误杀——其评审 agent 拒掉 9/10 人类已接收论文（arXiv:2502.14297）；arXiv:2606.12071 指 LLM-as-judge 做 novelty 判定有已知局限；Arbor "it never blocks a run"【原文】。
**默认值**：add 时预检 + merge 前复核双触发，三档 verdict（novel / partial-overlap / prior-art-exists）；**verdict 永不做硬闸门（定稿边界）**——误杀代价大于浪费一次实验。
**耦合**：×K14（verdict 质量需独立度量才能保持 advisory 定位的可信性）；×M9（verdict 是 merge/准人的参考输入，但裁决权在 M9 不在 M6）；×K2（审计走独立车道）。

## K8 审计检索独立性

**一句话定义**：audit 车道的检索是否复用 ground 车道的上下文、语料与中间产物。

| 取值 | 描述 |
|---|---|
| 复用 ground 结果 | 用构想期读过的文献做新颖性判断——自我指涉（禁止取值） |
| 独立 fresh search | 专门 SearchAgent 全新检索，"so it can't be fooled by whatever grounded ideation read earlier"（Arbor） |
| 独立 + 面向更广文献 | ToI：novelty 检查面向 "broader literature beyond Tr"，不只查自己用过的语料 |

**关键证据锚点**：Arbor 独立 SearchAgent 设计【原文】；ToI 更广文献复核【原文】；AI-Scientist 关键词浅检索（≤10 条元数据 + LLM 一票）即独立性不足的失效形态（2502.14297）。
**默认值**：独立 fresh search + 更广文献；审计检索语料集 ⊇ ground 语料集。
**耦合**：×K2（本轴是车道隔离在检索执行面的落实）；×K3（更广文献要求来源配置支持）；×K16（违规检测验证独立性是否被实际执行）。

## K9 防污染与 benchmark 公平模式

**一句话定义**：M6 在评测场景下的可用性策略与内容污染的结构性防护。

| 取值 | 描述 |
|---|---|
| 无防护常开 | 评测时可从网上抄现成想法/结果——公平性破产 |
| benchmark 模式全关 | Arbor 默认：两车道默认全关，"系统不能从网上抄一个现成想法或结果" |
| benchmark 全关 + 方案泄漏检测 | 全关之上，对产出做与已知方案的相似度扫描（防 M5 内部污染外溢）【推断】 |

**关键证据锚点**：Arbor 双车道默认 off 的公平性论证【原文】；AI-Scientist 复评的另一发现：论文中位仅 5 条引用且多数过时、57% 手稿含幻觉数值（2502.14297）——开而不洁比不开更糟。
**默认值**：研发模式按 K1 配置开启；**benchmark/评测模式 M6 全关（定稿）**。
**耦合**：×M8（评测模式标识由 M8/M9 传入）；×K15（研发模式的多样性监控数据是判断"开着是否有益"的依据）。

## K10 M5×M6 联合入口（ERA 模式）★跨模块接口

**一句话定义**：失败信号等触发事件是否同时路由到内部经验检索（M5）与外部知识检索（M6），及两路产物的标注与汇合方式。

| 取值 | 描述 |
|---|---|
| 各自独立无联动 | 失败只查 M5 或只查 M6 |
| 联合触发 + 来源类型分标 | KAPSO ERA + Arbor 字段分离思想：失败信号同时触发 M5 recall 与 M6 repair 检索，注入前分开标注"内部经验/外部文献" |
| 联合触发 + PIVOT 纠错 | KAPSO：PIVOT 决策时重跑检索并排除当前种子仓库 |

**关键证据锚点**：KAPSO ERA `RetrieveKnowledge(g, r̂, s≠∅)` 与 PIVOT 排除当前 seed【原文】；边界定稿：内部经验约束"别再试什么"，外部文献回答"世界已知什么"，两者用法不同必须分标。
**默认值**：联合触发 + 来源类型分标。
**耦合**：**消费 M5 `recall(signal)`**；×M2（汇合后的上下文配方归 M2 O5 域）；×K5（repair intent 是本入口的 M6 侧实现）。

## K11 多样性供给（M6 侧抗收敛职责）

**一句话定义**：M6 为对抗 idea 同质化向搜索层供给的证据类型——M6 只供给，QD/去重执行归 M2。

| 取值 | 描述 |
|---|---|
| 不供给 | 只回答查询，不提供任何抗收敛信号 |
| 去重证据供给 | 提供 embedding/来源证据供 M2 做近重复拦截与祖先/被拒集比较（IDEAgent 分工） |
| gap 地图供给 | ToI：convergent（≥2 轨迹共享 gap）与 cross-link（跨轨迹桥接）信号，方向须 ≥2 独立轨迹证据 |

**关键证据锚点**：IDEAgent QD 建模 Yield 指标 3.89×（arXiv:2607.22375）；ToI 去跨轨迹信号 −0.65 消融；2605.27905 收敛效应实证（219,655 idea）。
**默认值**：去重证据供给（最低档必配）；gap 地图供给在离线建库（K1 取值①）开启时配套。
**耦合**：**向 M2 供给**（QD 约束、新颖性闸、多样性维护的执行全部在 M2/搜索策略层——定稿边界）；×K4（gap 信号卡是供给载体）；×K15（供给效果是收敛监控的输入）。

## K12 Provenance 与引用诚实

**一句话定义**：M6 产物的来源可追溯性机制——引用必须基于实际打开的来源，全链路带 provenance。

| 取值 | 描述 |
|---|---|
| 无 provenance | 引用凭 LLM 记忆生成（禁止取值） |
| 未打开来源丢弃 | Arbor："Sources that were never actually opened are dropped, so citations stay honest" |
| 全链路 provenance | KAPSO：query_used / source_pages / 路径 / commit 全记录；ToI：方向须引用 ≥2 条独立轨迹证据 |

**关键证据锚点**：AI-Scientist 57% 手稿含幻觉数值、中位 5 条引用且多数过时（2502.14297）；Arbor 丢弃未打开来源【原文】；KAPSO provenance 字段【原文】。
**默认值**：未打开来源丢弃 + 全链路 provenance（最低档必配）。
**耦合**：**进 X1 谱系**（grounding/related_work 字段携带来源 ID 与打开记录）；×K4（信号卡/digest/packet 均内嵌 provenance 字段）；×K14（审计 verdict 附最接近论文与重叠风险，是判别质量度量的原料）。

## K13 消费管线接口（M6→M2 契约）

**一句话定义**：M6 对算子暴露的工具面形态与产物 schema——M6 只管"取、压、证、隔离"，不拥有消费逻辑。

| 取值 | 描述 |
|---|---|
| 无契约（宿主自定） | openresearch-cli 式：CLI 一等命令 + system prompt 偏好声明，防污染/审计时机/digest 压缩全部无人负责 |
| 双工具契约 | 定稿：M6 暴露 `query(intent)`（ground 车道）与 `audit(idea)`（audit 车道）两个类型化入口，产物为带 provenance 的 bounded packet |
| 双工具 + skill 注入 | 契约之上向宿主 agent 注入使用偏好（orx-lit "start here" 式） |

**关键证据锚点**：R&D-Agent 消融：w/o Memory Context −9% vs w/o Reasoning Pipeline −24%——知识模块无好消费管线则价值有限（arXiv:2505.14738）；openresearch-cli 零耦合路线的代价：防污染、审计时机、压缩无人负责【推断】。
**默认值**：双工具契约（`query(intent)` + `audit(idea)`）。
**耦合**：**向 M2 供给的唯一通道**；×M9（audit verdict 经 M2 流转至 merge 决策，裁决权在 M9）；×K4/K12（产物 schema = 格式 + provenance 的并集）。

## K14 审计判别质量度量（盲区补轴，对标 M2-O20）

**一句话定义**：novelty audit 的误判率（false-novel 漏报 / false-kill 误杀）是否作为一等健康指标被独立测量与台账化。

| 取值 | 描述 |
|---|---|
| 无度量 | 审计判别质量是暗数据（AI-Scientist 现状：上线即 12/12 误判而不自知） |
| 抽样人工/金标复核台账 | 定期对 verdict 抽样标注，报告 false-novel / false-kill 双率 |
| 台账 + 校准反馈 | 双率反馈校准审计 prompt、检索深度（K6）与来源集（K3） |

**关键证据锚点**：AI-Scientist 实测双率：false-novel 12/12（已知技术全判 novel）、false-kill 9/10（人类已接收论文被拒）（arXiv:2502.14297）；arXiv:2606.12071 指 LLM-as-judge novelty 判定存在系统性局限——无度量则 advisory 定位的可信性无从谈起。
**默认值**：抽样复核台账（最低档必配；M2-O20 同型先例：无漏斗数据的算子不得参与自适应选择——此处无质量数据的 verdict 不得进 merge 参考）。
**耦合**：×K7（台账是维持"审计永不阻断"约定可信的前提）；消费 X1 谱系中的 grounding/related_work 记录做复核采样。

## K15 注入后收敛效应监控（盲区补轴，对标 M2-O9）

**一句话定义**：ground 车道开启后，idea 种群的分布集中度/原创性位移是否被持续测量——收敛效应在 fitness 曲线上隐形。

| 取值 | 描述 |
|---|---|
| 无探针 | 收敛效应完全隐形（2605.27905 的四项负发现正是无监控系统的群体级表现） |
| 分布探针监控 | idea embedding 分布集中度、与起始文献距离、生态位影响区估计的时间序列监控 + 报警 |
| 监控 + 2×2 消融对照 | 开/关 ground × 开/关 audit 的内置消融协议，报告 idea 多样性指标 |

**关键证据锚点**：2605.27905：219,655 个 AI idea 四一致发现——更集中、更贴近起始文献、与未来人类方向对齐更差、位于低影响区（arXiv:2605.27905）；M5/M6 设计文档第三部分定稿的 M6 消融协议（2×2 + 多样性指标报告）。
**默认值**：分布探针监控（最低档必配）；2×2 消融在每次 K4 注入格式变更时强制重跑。
**耦合**：×K4（注入格式变更按实验对待：记录、对照、可回滚）；×K11（监控结果是多样性供给策略的调整信号）；探针指标向 M2-O9 多样性维护对齐复用。

## K16 车道隔离违规检测（盲区补轴）

**一句话定义**：ground/audit 零共享约束是否被运行时机制实际验证，而非仅靠实现纪律。

| 取值 | 描述 |
|---|---|
| 无检测（纪律依赖） | 隔离只存在于文档承诺；缓存复用、共享 session、prompt 泄漏均可静默破窗 |
| 静态配置检查 | 启动时校验两车道独立 backend 配置、独立上下文、分离落库字段 |
| 运行时文本重叠审计 | 抓取文本哈希台账：audit 车道产物与 ground 历史抓取做重叠扫描，违规即报警作废 verdict |

**关键证据锚点**：【推断，根因证据充分】Arbor 的隔离承诺目前仅靠实现纪律（`docs/search.md` 为设计声明，无运行时验证机制的报告）；单车道失效的代价已有实证（AI-Scientist 12/12 误判 = 隔离不存在的直接后果）；对标 M2-O17 谱系覆盖 gate 代码的教训（AIDE² 反作弊层被改坏而不自知——结构约束必须有谱系/审计兜底）。
**默认值**：静态配置检查（最低档必配）；运行时重叠审计在审计 verdict 进入 merge 参考前启用。
**耦合**：×K2/K8（本轴是两条结构轴的验证层）；违规记录进 X1 谱系（作废 verdict 的处置可追溯）。

---

## 总览表

| 轴 | 取值集 | 默认值 | 最强证据 | 接口依赖 |
|---|---|---|---|---|
| K1 ground 触发时机 | 离线建库 / 可选工具 / 强制注入 / 失败触发 / 全程组合 | 可选工具+失败触发 | R&D-Agent −9% vs −24%；KAPSO 三点位 | 消费 M8 失败信号、M3 预算 |
| K2 车道隔离结构 | 单车道(禁) / 逻辑分离(禁) / 两车道零共享+字段分离 | 两车道零共享（硬约束） | Arbor 原文；AIS 12/12 误判 | 字段进 X1 |
| K3 来源混合 | 纯文献 / +web / +repo·策展KB / 有序后端+降级 | 文献+web 免 key 起步 | Arbor backend 协议；KAPSO 2000+ repo | — |
| K4 注入格式 | flat RAG(禁) / digest / gap 信号卡 / 类型化 packet | digest 起步→gap 信号卡 | 219,655 idea 收敛实证；ToI 6.27 vs 5.36 | 向 M2 供给 |
| K5 检索意图集 | 无 intent / 四 intent / +repair | 四 intent+repair | Arbor ResearchSearch；KAPSO ERA | 向 M2 暴露 |
| K6 阅读深度分级 | 统一浅 / 统一深 / 双预算分级 / +轮数上限 | 构想 6k / 审计 2k | Arbor 2048/6000；AIS 10×10 反例 | 消费 M3 预算 |
| K7 审计时机与阻断性 | veto 闸门(禁) / add 预检 / merge 前 advisory | 预检+复核双触发，三档 advisory | AIS 12/12 漏报、9/10 误杀 | verdict 供 M9 参考（裁决权在 M9） |
| K8 审计检索独立性 | 复用(禁) / 独立 fresh search / +更广文献 | 独立+更广文献 | Arbor SearchAgent；ToI beyond-Tr | — |
| K9 防污染与公平模式 | 无防护 / benchmark 全关 / +泄漏检测 | benchmark 模式 M6 全关 | Arbor 公平性论证；57% 幻觉数值 | 消费 M8 评测模式标识 |
| K10 M5×M6 联合入口 | 无联动 / 联合触发+分标 / +PIVOT | 联合触发+来源分标 | KAPSO ERA+PIVOT | **消费 M5 recall**；汇合配方归 M2 |
| K11 多样性供给 | 不供给 / 去重证据 / gap 地图 | 去重证据供给 | IDEAgent Yield 3.89×；ToI −0.65 | **向 M2 供给**（QD 执行在 M2） |
| K12 provenance 诚实 | 无(禁) / 未打开丢弃 / 全链路 | 未打开丢弃+全链路 | AIS 57% 幻觉、5 条过时引用 | **进 X1 谱系** |
| K13 消费管线接口 | 无契约 / 双工具契约 / +skill 注入 | query(intent)+audit(idea) | R&D-Agent −9% vs −24% | **向 M2 供给的唯一通道** |
| K14 审计判别质量度量 | 无 / 抽样复核台账 / +校准反馈 | 抽样复核台账 | AIS false-novel 12/12、false-kill 9/10 | 消费 X1 采样 |
| K15 收敛效应监控 | 无 / 分布探针 / +2×2 消融 | 分布探针监控 | 2605.27905 四一致负发现 | 指标复用 M2-O9 |
| K16 隔离违规检测 | 无 / 静态配置检查 / 运行时重叠审计 | 静态检查（启动时） | Arbor 纪律依赖【推断】；AIDE² 类比 | 违规记录进 X1 |

## 逐格深挖优先级提示

深挖工作量预期最大的三条：
1. **K4 注入格式**（gap 信号卡的 schema 设计 × K15 监控协议 × ToI 机制逐件拆解——格式空间组合爆炸，且是收敛效应的第一调节阀）；
2. **K7+K8+K14 审计三联动**（advisory 定位的可信性依赖误判台账；与 M9 的"参考 vs 裁决"职责切分需逐场景定义；LLM-as-judge novelty 局限文献 2606.12071 需全文精读）；
3. **K10 M5×M6 联合入口**（跨模块契约：与 M5 `recall(signal)` 的信号 schema 对齐、来源分标的下游消费规则、ERA 触发条件与 M2-O5 上下文配方的三方对齐）。
