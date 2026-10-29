# M5 记忆设计空间深度展开：A–I 轴 × 五个分歧点 × F1–F8 失效模式

> 本文是对《M5记忆与M6知识设计深度分析》的逐格深挖，深度与粒度对标 D 轴示范（取值表 | 机制展开含字段/公式/超参 | 关键细节含量化证据 | 什么时候选它 + 隐藏结构段 + 反直觉结论段）。
> 所有量化数字均出自研究卡片（../research/m5m6/ 目录卡片），标注 arXiv 编号；推断处标【推断】。
> 生成日期：2026-08-26。

---

# 记忆设计空间 A–E 五轴深度展开分析

> 依据：`M5记忆与M6知识设计深度分析.md` §1 轴体系；证据来自 `../research/m5m6/m5_groupA_selfevol.md`、`m5_groupB_general.md`、`m5_groupD_eval.md`、`m5m6_groupE_frontier.md`。标注【推断】者为卡片未直接给出、基于系统行为的合理分析。

---

## 轴 A：表示格式（记忆以什么形态存在）

| 取值 | 机制展开 | 关键细节（含来源） | 什么时候选它 |
|---|---|---|---|
| 原始轨迹流 | 事件/对话全量追加，带时间戳；不做抽象。Generative Agents 的 observation stream、MOSS 的 L1、AIDE 的 `_term_out/exec_stack` 原始字段 | 零信息损失、零写入成本，但线性膨胀且检索噪声大；AIDE 摘要默认 `include_code=False` 且 `trim_long_string` 截断，说明原始流不可直接注入（groupA §1.2，journal.py）。MOSS 证明纯 L1 fresh-start 在低信噪比环境下不差于坏记忆（groupA §1.7） | 作为一切上层表示的**保真底座**；任务间同构性低时作为对照基线 |
| 自由文本 lesson | Reflexion 失败反思、prime-agent `/refine` 的 L2、ShinkaEvolve MetaSummarizer 的 meta-recommendations | 灵活、零 schema 成本；但无冲突检测、难回滚（groupA §4 D1）；Reflexion 是"完整重写式"且窗口外即遗忘，ACE 证明该形态会 collapse（groupB §1.4） | 快速原型、一次性/短程任务；或作为周期摘要层 |
| 结构化 schema 条目 | 带类型/触发/优先级/来源的条目。IBM TSM 13 字段 tip（category∈{strategy,recovery,optimization}、trigger、priority、provenance、timestamp 等）；MemRL (z,e,Q) 三元组；AIDE Node 五元组（code/plan/exec/metric/analysis）；ACE bullet（ID+helpful/harmful 计数器） | IBM 与 MemRL **独立收敛**于"结构化字段+embedding 双键"（主文档 §2.2）。失败教训：schema 设计错误会系统性限制可表达的记忆类型（MetaSkill 五元组，groupA §1.3）；ACE 计数器天然承载证据强度（多次复现成功→计数高，groupB §7.2） | 默认主选。需要过滤/优先级/归因/冲突检测时必选 |
| 可执行制品 | Voyager skill（JS 代码+embedding 索引）、EvolveNet harness、CODESKILL skills、prime-agent L3 | 天然可验证可执行；Voyager 用执行验证做准入门（groupB §1.3）。风险：粒度难控（过细爆炸、过粗难组合）；harness 共享=单点污染全域（groupA §1.6）；SkillsBench：LLM 自创技能 +0.0pp vs 人工策划 +16.2pp——制品质量门不能省（groupE §2.3） | 有可执行验证环境时；程序性/方法论知识（MemP：随规模优雅扩展、可迁移） |
| 基因型 | 整个 agent 代码库作为记忆条目。DGM archive：`archive/<child_id>/code/` + performance.txt + 谱系元数据；父代选择按 sigmoid(perf)×1/(1+children) 采样 | 记忆不进 context，零 collapse 风险；天然可回滚（祖先可重新分叉）。代价：粒度=整个 agent，无法表达局部教训，同类 bug 跨分支反复犯；依赖可自动评分的 benchmark（groupA §1.1） | 评测可自动验证且改进对象是 agent 本体时 |

**隐藏结构**：这五个取值不是互斥的，而是**分层栈**——几乎所有成熟系统都是"原始轨迹(L1) → 文本/条目(L2) → 可执行制品(L3)"三层共存（prime-agent、MetaSkill、EvolveNet、主文档定稿配置均是）。基因型是特殊形态：它把整个栈塌缩成一层并移出 context。被重复验证的组合：**"结构化字段 + embedding 双键 + 类型分级"**（IBM TSM 与 MemRL 独立收敛）和 **"条目 + helpful/harmful 计数"**（ACE bullet 与 MemRL Q 值是同一思想的手工/RL 版本）。

**反直觉结论**：表示越保真越好是错的——AIDE 的教训显示原始流若不带 `is_buggy` 式结构标记，读取侧无法补救；但表示越抽象也不越好，**schema 一旦设计错，伤害是系统性的**（MetaSkill），而自由文本虽然"低信息量"，却是唯一不会因 schema 错而扭曲记忆的表示。结构本身是 inductive bias，选 schema 等于选记忆能说什么。

---

## 轴 B：写入路径与准入（什么、何时、凭什么进库）

| 取值 | 机制展开 | 关键细节 | 什么时候选它 |
|---|---|---|---|
| 无门槛全量 | 每步/每交互直接追加。Generative Agents、AIDE `absorb_exec_result()`（错误节点也保留为调试素材）、MemRL 的 episode 结束即写 `(z,e,Q_init=0)` | 不漏信号；但信噪比崩（F5：MemDelta 实测记忆操作可占 agent 执行时间 >80%，500 会话抽取耗 1.6 亿 token）。AIDE 靠读取侧 good_nodes 过滤补救（groupA §1.2） | 有后置过滤/惩罚机制兜底时（宽进必须配严读） |
| 周期摘要 | 每 N 步/代触发 MetaSummarizer 式压缩写回（ShinkaEvolve）；Dreaming 式空闲批处理是其 2026 产品化形态 | 控制膨胀；但周期是敏感超参，引入 staleness——适应度景观快变时持续推荐过时策略（groupA §1.5）。OpenAI V3 把成本降 5 倍作为该方案推广前提（groupE §3.2） | 长程运行、context 预算紧、经验变化慢于摘要周期 |
| 命令触发 | 人工/半自动触发精炼，如 prime-agent `/refine` | 质量最高；自主性弱，不适合无人值守循环（groupA §1.4） | 高风险域、人机协作模式 |
| 证据门+回滚 | 记忆变更须附证据，失败回滚快照。prime-agent 是唯一显式实现写入事务性的系统 | 唯一直接对冲 error propagation（错误经验被 agent 忠实复现，Xiong et al. 2025）的设计；但**证据本身被 reward hacking 污染时，门禁反而给假经验背书**（groupA §1.4） | 错误代价高、证据可机器校验时 |
| 后置效用门（宽进严读） | 写入无门禁，Q 值后置惩罚坏经验。MemRL：`Q ← Q + α(r−Q)`，α=0.3，收敛性与方差界有定理保证（Thm A.1） | 坏经验被压低检索概率而非删除；有理论保证。但论文自承 reward hacking 可快速扩散致 collapse（App. G.4），且多记忆共注时 credit assignment 含糊（§6 Limitations） | 有可靠环境 reward 的自主系统——当前自主场景首选 |
| 因果归因后写入 | 先归因再入库。IBM TSM 三阶段：思维类型解析 → Decision Attribution（immediate/proximate/root cause）→ 生成 tip；无 GT 时靠 agent 自反思推断 | 产物带 provenance（source_trajectory_ids），支撑冲突解决与审计；但无 GT 时归因错误会带 provenance 背书入库（groupA §2.3） | 需要可追溯性/审计的研究型场景 |
| 可学习管理策略 | 把"写什么/何时更新/何时淘汰"做成 RL 策略。CODESKILL（hybrid reward = 密集 rubric + 稀疏下游执行反馈）；MemSkill（controller RL 选记忆操作 skill + designer 进化 skill 库）；MemAct（Prune&Write 进动作空间） | CODESKILL 比最强 memory 基线 +4.01（groupA §2.5）；风险是管理策略过拟合训练分布、排斥低频有用经验；rubric 评审本身是 LLM 可被"讨好" | 数据足、有训练基础设施的长期部署；2026 前沿方向 |

**隐藏结构**：这些取值构成**两个正交子维度的乘积**：(i) 门的时机——前置（证据门/验证门）vs 后置（效用门/学习门）；(ii) 触发的时机——同步每步 vs 周期/空闲/命令（即 2026 新轴 H 巩固时机）。被独立验证的组合：**"宽进（无前置硬门）+ 后置效用惩罚 + 快照回滚兜底"**——MemRL 从理论侧、prime-agent 从工程侧分别到达，MemRL 自己也承认回滚是污染后的唯一补救（App. G.4）。另一个组合是"写入前归因 + 聚类合并"（IBM TSM Phase 2：泛化→层次聚类阈值~0.85→LLM 合并）。

**反直觉结论**：**写入门越严不一定越安全**。硬证据门会给被污染的证据背书（prime-agent 失败场景），且门太严会漏掉"当时不知价值"的弱信号——研究中的反常观察往往如此（groupB §5 轴 B）；反而是"全放进去、用 Q 值/计数让坏记忆自然沉底"的宽进严读，在自主性和鲁棒性上都更好。准入控制的正确位置在读取侧和治理侧，不在写入瞬间。

---

## 轴 C：读取与注入（什么被想起来、以什么形态进 context）

| 取值 | 机制展开 | 关键细节 | 什么时候选它 |
|---|---|---|---|
| 全量注入 | 无检索，全量/滑窗进 prompt。Reflexion FIFO 滑窗；ExpeL insight 全量注入 system prompt；ACE 默认全量 playbook（靠 KV cache 摊销） | 零漏检、零检索基础设施；预算爆炸+注意力稀释，ACE 作者自承长 playbook 下该策略可能撑不住（groupB §2.5）；ConvoMem：~150 会话以下全上下文反而优于检索记忆（groupD F5） | 库小（<百条）或任务本身短程时 |
| 结构位置 | 按树/谱系位置读。AIDE `generate_summary` 只遍历 good_nodes、按 `get_best_node` 排序；DGM parent selection 按 perf×新颖度采样祖先 | 决策相关性强、无语义泛化能力；`is_buggy` 自判错误会不可逆地把好方案排除出摘要（groupA §1.2） | 记忆天然有过程结构（搜索树/进化谱系）时 |
| 语义相似度 | embedding cosine + 阈值 τ + top-k。IBM：τ∈[0.5,0.7]，top-k∈[5,10]；MemRL Phase A：δ 取任务相似度分布 top-20% 分位 | **τ 是敏感超参**：IBM 实测 τ=0.5 纳噪、0.85 漏同义，τ≈0.6 是甜点（groupA §2.3）。纯语义检索被 MemRL 证明次优 | 作为两阶段的第一阶段，几乎不应单独使用 |
| 两阶段（召回+效用重排） | Phase A 相似度召回 top-k1 → Phase B 按 `(1−λ)·sim + λ·Q`（z-score 归一）选 top-k2。MemRL：λ=0.5 最优（Fig. 5），k1=5/k2=3 呈倒 U；该打分等价于带语义 KL trust-region 的变分最优检索（App. A.4） | 抗噪有理论保证；需效用学习闭环。轻量近似 = ACE helpful/harmful 计数（groupB §3.1） | 当前**默认主选**——唯一既有实证甜点又有理论证明的方案 |
| LLM-guided 选择 | 多一次 LLM 调用做 metadata 过滤+类别优先级选择。IBM TSM：比纯 cosine **+7.2pp SGC** | 增益显著但多一次调用成本；注入格式也关键：guidelines 段放 task context 之后、instructions 之前，带 `[PRIORITY:HIGH]` 可扫读标记，预算 top-5（groupA §2.3） | 难任务（IBM：难任务 +28.5pp）值得多花一次调用 |
| agent 自主查询 | 记忆即工具，agent 显式发起 query。MemGPT 分页浏览/函数调用；Anthropic Memory Tool 用 bash grep/diff 管理 `/mnt/memory/` | 省 token、按需；但依赖 agent"想起要查"，漏查风险与决策负担（groupB §1.2）。MemGPT 该设计已被 Anthropic 文件系统方案吸收（groupE §3.6） | 库极大、注入预算极紧，或 agent 足够强时 |

**隐藏结构**：取值间是**可叠加的流水线而非单选**——MemRL 的两阶段 = 语义召回 ⊗ 效用重排；IBM 的三段 = 语义召回 ⊗ 结构化 metadata 过滤 ⊗ LLM 选择；AIDE = 结构位置 ⊗ 质量过滤。真正的正交决策是三个旋钮：召回键（语义/结构/混合）、重排信号（无/计数/Q 值/LLM）、注入预算与格式（top-k、分区、成功/失败分块——MemRL 注入时区分 "SUCCESSFUL / FAILED (Avoid these mistakes)" 两块）。被重复验证的组合：**相似度召回 → 效用/质量重排 → 预算化注入**（MemRL、IBM 独立收敛，主文档共识 3）。

**反直觉结论**：**检索不足比不检索更糟**。IBM TSM 实测 top-3 过严限制使总分跌破无记忆基线（−2.9pp TGC，groupA §2.3）——错误的少记忆比没有记忆更有害，因为 agent 会忠实复现被检索到的少数经验。这推翻了"宁缺毋滥"的直觉：读取侧的正确策略是"预算给足（top-k≥5）+ 质量靠重排而非靠卡阈值"。

---

## 轴 D：更新与遗忘（入库之后怎么变、怎么消失）

| 取值 | 机制展开 | 关键细节 | 什么时候选它 |
|---|---|---|---|
| append-only | 条目不可变、只增不减。DGM archive（无淘汰，遗忘靠选择压力）；AIDE Node 不可变（树搜索剪枝即遗忘） | 零实现成本、天然防 collapse（无重写路径）、谱系可审计；库膨胀、陈旧知识持续可检索（F7 stale leak） | 有外部选择压力（进化）或读取侧强过滤时 |
| EMA 效用更新 | 就地更新标量效用不删条目。MemRL `Q ← Q + α(r−Q)`（α=0.3，Thm A.1 收敛保证）；实测遗忘率 FR=0.041 vs MemP 0.051，去掉归一化+门控后 FR 升至 0.073——**归一化+门控就是 collapse 防护**（groupA §2.4） | "遗忘"软化为检索概率压低，阴性结果仍在库中可查；credit assignment 在多记忆共注时含糊 | 有可计算 reward 时的默认更新机制 |
| 离线巩固（sleep-time/dreaming） | 空闲期批处理回顾→提炼→写回。MemoryOS 三级晋升（FIFO 短→中、分段页中→长）；2026 产品化三连：Anthropic Dreaming（回顾≤100 会话提炼 playbook，人审后才上线）、OpenAI V3 Capture→Synthesis→Retrieval、Perplexity Brain 夜间综合 | 不占在线预算；引入滞后与失真。OpenAI V3 实测会自信地产出虚构合成记忆（ZDNET 实测，groupE §3.2）——离线合成同样需要治理 | 长程部署、有明确空闲窗口；2026 工业界共识形态 |
| LLM 冲突合并 | 新条目触发旧条目合并/废止。IBM Phase 2：泛化→聚类（~0.85)→LLM 合并，冲突解决用 outcome metadata——**成功轨迹 tip > 失败轨迹 tip，recovery tip > 预防性建议**（§3.2.3），合并后重写 canonical 描述并重 embed；A-MEM 新卡触发旧卡就地演化 | 控膨胀+消冲突；但 LLM 合并是有损压缩（小规模 brevity 风险，groupB §1.6），链接污染会沿图传播（A-MEM）。2606.01435 主张新鲜度判断用确定性规则而非 LLM | 条目级库且需要 supersession 语义时 |
| 快照回滚 | 写入前快照，失败/污染后整体回退。prime-agent（唯一事务性实现）；MemSkill skill bank 快照+性能退化回退 | 不是更新策略而是**所有更新策略的保险丝**；MemRL 自承回滚是 reward hacking 污染后的唯一补救（App. G.4） | 永远叠加启用，不单独使用 |

**隐藏结构**：更新与遗忘可分解为**三个正交问题**：(i) 内容怎么改——禁整篇重写是铁律（ACE：18282→122 token、66.7→57.1 跌破基线 63.7，groupB §2.3），合法修改只有 delta 追加、计数器递增、Q 值更新三种；(ii) 旧条目怎么失效——删除（MemoryOS FIFO）vs 逻辑废止/supersession（IBM 冲突合并）vs 概率沉没（MemRL Q 值）；(iii) 何时做——同步每步 vs 离线巩固（即新轴 H）。快照回滚是横切所有取值的底座。被重复验证的组合：**"append-only 内容 + 就地效用更新 + 定期 LLM 合并控膨胀 + 快照兜底"**（主文档 §5 定稿配置，ACE/MemRL/IBM/prime-agent 各贡献一块）。

**反直觉结论**：**对研究型 agent，遗忘不该是删除，甚至不该是"忘掉"**。卡片给出三方证据：研究场景中阴性结果与被反驳假设是最高价值记忆（防重复试错，主文档分歧表 4）；PAST-Bench 把"被纠正后再次违规"（repeat_violation）作为独立测量——记忆消失本身就是失败；MemRL 的 Q 值机制证明"压低不删除"在理论上严格优于删除。遗忘的正确实现是**降级归档+检索概率沉没**，而非从库中抹除。

---

## 轴 E：作用域（谁的记忆、出不出边界）

| 取值 | 机制展开 | 关键细节 | 什么时候选它 |
|---|---|---|---|
| run 局部 | 记忆生命周期=单次运行。AI-Scientist-v2（每次实验从头建树，无跨 run 记忆）；Reflexion 单任务多 trial | 隔离最好、零污染面；零迁移——AI-Scientist-v2 单实验 $15–20，重复犯错代价高昂（groupA §2.1） | 高污染风险任务，或作为刻意对照（MOSS） |
| 任务局部 | 一次任务一个记忆库。AIDE journal（跨任务迁移需人工复制） | 同上，粒度稍粗 | 任务间同构性低时 |
| 分支局部 + meta 传播 | 默认分支私有，跨分支靠 meta 层检索按需广播。MetaSkill-Evolve | "默认私有、按需广播"；但低频关键教训可能永不被检索到，跨分支转移质量=检索质量（groupA §1.3） | 并行探索多分支（树搜索/进化）场景 |
| 域隔离 + 证据出域 | 原始轨迹不出域，跨域货币是抽象后的行为证据。EvolveNet：L1 本地留存，仅 F/B（失败/成功行为片段）可跨界；L3 harness 全局共享 | 多租户/隐私场景唯一明确"什么可以出域"的设计；F/B 脱离上下文可能误导，harness 共享=单点污染全域（groupA §1.6） | 多租户、隐私/合规约束场景 |
| 全局共享 | 单一全局库，task/subtask 多粒度共存。IBM TSM、MemRL memory bank | 迁移增益最大；污染面最大（F2 投毒面、MemRL App. G.4）。IBM 的 **subtask 抽象是跨任务迁移的关键机制**——对子任务描述做实体抽象/动作归一/上下文剥离（groupA §2.3） | 单租户、任务同构、有治理兜底时 |
| 跨模型 / 跨 agent | 记忆库作为可移植资产。MemRL：Gemini-3-pro 训练的 bank 给 Qwen3-235B 用 0.150→0.531（**3.5×**）；跨任务合并几乎无干扰（OS∪DB：−0.004）（Table 5/6）；AgentRxiv 论文级跨 lab 共享 | 记忆首次成为"可携带知识资产"；但 AgentRxiv 无质量门——检索到错误结论的论文并无验证地 build upon，错误以出版物形式固化传播（groupA §2.2） | 多模型流水线、多 agent 组织；必须配质量门 |

**隐藏结构**：作用域不是单点而是一个**传播矩阵**：默认层（run/任务/分支）× 传播通道（无/检索/抽象层/全共享）× 出域货币（原始轨迹/行为证据/结构化条目/论文）。关键洞察是**隔离与迁移可通过"抽象层"解耦**：IBM 的 subtask 泛化描述、EvolveNet 的 F/B 证据、MetaSkill 的 meta 层，三者是同一招——原始记忆不出边界，跨边界的只有脱敏/泛化后的抽象。主文档分歧表 2 的折中配置（默认任务局部 + 跨任务走泛化层）正是这一结构的组合。跨模型迁移（MemRL 3.5×）则说明：足够抽象的（intent, experience, Q) 条目已经模型无关，"作用域=模型"这条边界在 2026 年首次被实证打破。

**反直觉结论**：**全局共享的迁移增益远大于预期，而它的风险不在迁移本身**。MemRL 实测跨任务合并干扰仅 −0.004（几乎为零）、跨模型 3.5× 增益——"经验会互相干扰"的经典担忧未被证实；真正的代价全部集中在污染面（一次投毒/一次 reward hacking 全域可见）。因此作用域决策的正确依据不是"经验能不能迁移"（答案是几乎总能），而是"污染半径你愿意开多大"——治理强度而非迁移收益才是扩大作用域的前置条件。

---

## 五轴交叉的三个全局结论

1. **五轴的最强配置已被多系统独立收敛**（主文档 §2）：A=结构化双键条目、B=宽进+后置效用门+快照、C=两阶段+足量 top-k、D=delta+EMA+降级归档、E=默认局部+抽象层传播。
2. **轴间有硬性依赖**：B 的"宽进"依赖 C 的"严读"（AIDE 无门禁靠 good_nodes 补救）；C 的效用重排依赖 D 的 EMA 更新（MemRL 同一条 Q 值服务于读取重排与遗忘沉没）；E 的全局共享依赖治理轴 F（Library Drift：无界积累致检索退化，修复后 pass@1 0.258→0.584）。
3. **所有轴的共同反模式是让 LLM 承担确定性工作**：整篇重写（F1 collapse）、追踪新鲜度（2606.01435 主张确定性冲突解决）、整库合并——LLM 只应产增量，合并/废止/排序的确定性部分必须交给代码。


---

# 深度展开：2026 新轴 F–I 与五个经典分歧点

> 依据材料：主文档《M5记忆与M6知识设计深度分析.md》§1/§3；../research/m5m6/m5_groupA_selfevol.md、m5_groupB_general.md、m5m6_groupE_frontier.md、m5_groupD_eval.md。所有数字均出自上述卡片并注明 arXiv 编号或来源；机制细节推断处标【推断】。

---

# 第一部分：四个 2026 新轴

## 轴 F：治理与退役（Governance & Retirement）

**轴定义**（主文档 §1）：outcome 驱动退休、有界活跃上限、per-entry 贡献分归因、append-only 证据日志。Group E 的判定：这是 ACE（只增不退）与 MetaSkill（进化但无退役语义）都没有的轴，且 2026 年证据表明"它不是可选项而是必要条件"。

### 取值表

| 取值 | 机制展开（含细节数字） | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **无治理（只增不减）** | 库单调增长，无退休、无上限、无归因。代表：DGM archive（"unbounded, per the paper"，遗忘靠选择压力而非删除）、Voyager skill library（只增，靠描述去重）、AI-Scientist-v2（无跨 run 记忆，等于回避了问题） | Library Drift（arXiv:2605.19576，AWS GenAI + HSBC）：技能库无界积累 → 检索退化、假阳性注入、性能停滞。SkillsBench（2602.12670）给出动机级证据：**LLM 自创技能 +0.0pp vs 人工策划技能 +16.2pp**——无治理的自产积累增益为零。DGM 教训粒度=整个 agent，同类 bug 跨分支反复犯（Group A §1.1） | 库极小且生命周期短（单 run 树搜索）；或把"无治理"当对照基线（MOSS 式：低信噪比环境下坏记忆不如无记忆） |
| **outcome 驱动退休 + 有界活跃上限（Ratchet 配方）** | Ratchet 三件套（2605.19576）：①按真实 outcome 退休技能；②活跃库有界上限；③元技能创作先验。配套 append-only 证据日志 + 每技能贡献分 + 归因裁决。MBPP+ hard-100 上 100 轮 **pass@1 从 0.258 → 0.584** | Library Drift 现象本身即失败案例：静默退化——库还在"增长"但检索质量已崩。Group E：Voyager 谱系重心 2026 已从"发现"转向"治理"，15+ 篇技能库论文（SkillRouter/SkillOpt/CoEvoSkills 等）是排列组合，治理才是新轴 | 库跨 run 持续累积、且条目由 LLM 自产的任何系统——SkillsBench +0.0pp 说明自产技能默认无增益，必须有退休阀把噪声压出去 |
| **有偏评审器下的退休（治理失效模式）** | 退休决策依赖评审器打分；若评审器有偏，退休机制被**静默**失效（arXiv:2607.07436 "How a Biased Judge Silently Disables Skill Retirement"）——不是报错而是机制空转 | 这是治理机制的**评估器依赖**问题：治理回路里每个 LLM 判官都是单点。旁证：AI-Scientist 的 LLM-as-judge 新颖性闸门误杀 9/10 人类已接收论文（误报）+ 漏报已知技术（主文档 M6 §2）；CODESKILL 的 rubric 评审是 LLM，存在被 skill 文本"讨好"的空间（Group A §2.5） | 任何用 LLM 做退休/准入裁决的设计都必须假设此失效存在：评审器本身要可审计、可换、最好有确定性兜底【推断】 |
| **per-entry 贡献分 + 证据日志（归因型治理）** | 每条技能/记忆记贡献分数，append-only 证据日志供事后归因裁决；与 PAST-Bench 通路归因天然互补——"Library Drift 的 per-skill contribution score 正是通路归因在技能库上的实例化"（Group E §6） | MemRL 的 Q 值是轻量版（后置效用门，Q←Q+α(r−Q)，α=0.3，Thm A.1 收敛保证），但自承多记忆共注时 credit assignment 含糊（2601.03192 §6）。反事实轨迹审计（2605.11946）是更严格的归因工具 | 需要回答"这条记忆到底帮没帮上忙"的场景；M5 做消融/卫生监控（memory_pollution_rate 等）时，贡献分是原始数据 |
| **人审批准型治理（工业取值）** | Anthropic Dreaming：每条记忆人类可读、**可审查/批准/拒绝/编辑后才上线**，纯文本 playbooks；OpenAI V3：memory summary 页 + sources 溯源 + legacy 回退 | Harvey 报告任务完成率 6x（一方数据，Group E §7 注明工业数字证据力弱）；反面：ZDNET 实测 OpenAI V3 会自信地合成错误记忆（虚构 HomeAssistant 迁移）——学术担忧（TAME misevolution、Library Drift）在产品端真实存在 | 人机协作/高风险域；"只改可读记忆层、不改权重"已成 2026 工业界安全基线共识 |

### 隐藏结构

治理轴不是单选而是**分层栈**：【推断】
1. **数据层**：append-only 证据日志（不可变、可追溯）——一切治理的原料；prime-agent 快照回滚是同层的"撤销原语"。
2. **度量层**：per-entry 贡献分 / MemRL Q 值 / ACE helpful-harmful 计数器——三者是同构的效用信号，精度递增、成本递增。
3. **裁决层**：退休判决。可由确定性规则（阈值/上限）、LLM 评审器、或人（Anthropic 批准流）执行——2607.07436 证明裁决层的评审器偏置会让整层失效，故裁决层必须与度量层解耦（度量用确定性信号，LLM 只做建议）。
4. **执行层**：退休≠删除——与分歧点 4 联动，退役条目应降级归档（保留阴性结果价值）。

### 反直觉结论

1. **退休机制可以"装着在跑"而实际空转**：有偏评审器让退休静默失效（2607.07436），监控指标（活跃库大小）看起来一切正常。治理必须被治理——评审器要纳入卫生指标。
2. **无治理的积累增益恰好为零**：SkillsBench +0.0pp 意味着 Voyager 式"验证过就入库"在规模化后等于没做记忆——治理不是防腐剂而是增益本身的来源（Ratchet 0.258→0.584 的 2.3 倍提升来自"做减法"）。
3. **贡献分的真正消费者不是退休，而是评估**：per-entry 归因与 PAST-Bench 的 mechanism score 是同构物，先把证据日志建好，退休阈值可以后调，归因数据丢了补不回来【推断】。

---

## 轴 G：元操作可学习（Learnable Memory Meta-operations）

**轴定义**（主文档 §1）：慢循环作用对象 ∈ {任务技能， 记忆写算子， 巩固策略， 评审 rubric, 记忆架构本身}。Group E：这是 MetaSkill 双时间尺度结构的泛化——巩固循环的对象从"任务知识"上移到"记忆管理操作本身"。

### 取值表

| 取值（慢循环作用对象） | 机制展开 | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **任务技能**（经典取值） | MetaSkill-Evolve：L3 元技能五元组经进化/整合写入；controller 快循环用技能、慢循环进化技能库。Voyager 谱系 2026 爆发（SkillRL 2602.08234、AutoSkill、SkillEvolver 2605.10500 等 15+ 篇）均为该取值的排列组合 | SkillsBench：LLM 自创技能 +0.0pp——慢循环产出的技能质量是命门；MetaSkill 失败模式：低频关键教训永不被检索、五元组 schema 设计错误系统性限制表达 | 任务技能是性能瓶颈且可执行验证（代码域）时——这是最成熟取值 |
| **记忆写算子** | MemSkill（arXiv:2602.02474）：controller（RL 训练，按 span 选 Top-K 技能）→ executor（LLM 一次成型生成 skill-guided 记忆）→ designer（周期性从 hard-case buffer 聚类选代表失败，精炼旧技能/提新技能）。双库解耦：memory bank（trace 特有）vs skill bank（跨 trace 共享）。含 skill bank 快照 + 性能退化回退。LoCoMo/LongMemEval/HotpotQA/ALFWorld 验证 | Group E 明确定性："MetaSkill 双时间尺度在 memory-write 算子上的同构实例"。风险：designer 复盘是 LLM，改进方向可被 hard case 的采样偏差带歪【推断】 | 记忆操作本身是手工启发式、且长历史下低效时（MemSkill 的原话动机）；AutoResearch 的"如何写消融教训"正是可 skill 化的写算子 |
| **巩固策略** | CODESKILL（2605.25430）：把 skill 提取与 skill-bank 维护做成可学习管理策略，RL 训练，hybrid reward = 密集 rubric 式 skill 质量反馈 + 稀疏下游冻结 agent 可验证执行反馈。EnvBench/SWE-Bench Verified/Terminal-Bench 2 平均 **+9.69 over 无 skill、+4.01 over 最强 memory 基线**；skill bank 维持稳定大小（容量控制可学习） | 风险自陈：管理策略过拟合训练分布——学到的保留/淘汰偏好可能系统性排斥新颖但低频有用的经验；rubric 评审是 LLM 可被讨好 | 有可靠 RL 训练信号（可验证执行反馈）时；"写什么/何时更新/何时淘汰"要从启发式升级为可优化对象时 |
| **评审 rubric** | SkillCoach（2607.01874）：评审 rubric 本身自进化 | 与轴 F 联动：评审器有偏会使退休静默失效（2607.07436）——若 rubric 还可自进化，偏置会被慢循环固化放大【推断】；正面证据：AI-Scientist 新颖性评审误杀 9/10 说明静态 rubric 也不可靠 | 评审标准随任务域漂移、人工维护 rubric 跟不上时；必须与评审器审计配套 |
| **记忆架构本身** | MemEvolve（2512.18746）：在 encode/store/retrieve/manage 四元设计空间内联合进化经验知识与架构；EvolveLab 蒸馏 12 个记忆系统为统一模块库；SmolAgent/Flash-Searcher 提升最高 17.06%，跨任务、跨 LLM 迁移 | 核心警示："没有唯一最优记忆架构，应按任务搜索"（Group B §3.3）；风险：搜索成本高（Group B 字段表） | 框架级设计期——含义是 M5 应暴露可配置轴而非锁死单点，而非在线进化架构 |

### 隐藏结构

五个取值构成**元层递进阶梯**：任务技能（对象层）→ 写算子（操作对象的手段）→ 巩固策略（操作的时机与保留规则）→ rubric（评判操作好坏的标准）→ 架构（操作存在的空间）。【推断】每上移一层：(a) 改进的杠杆变大（改 rubric 同时改变所有条目的命运）；(b) 验证信号变稀疏（架构级只有 17.06% 这种整体指标）；(c) 自指风险变大（rubric 自进化 = 裁判改规则）。MemSkill 的"双库解耦 + 快照回退"是跨层通用的稳定化模式：慢循环产物必须与快循环数据分离存储，且带可回退点。DeltaMem 的 K_cons 命中阈值巩固是"巩固策略"取值的启发式实例（无需 RL）。

### 反直觉结论

1. **最值钱的慢循环对象不是任务技能**：CODESKILL +4.01 的增益来自学"怎么管理 skill"而非"造更好的 skill"——管理策略是被长期低估的一等优化对象。
2. **慢循环越强，越需要不可学习的锚点**：rubric 可进化 + 评审器有偏 = 偏置自我固化（2607.07436 与 2607.01874 的组合风险）；MemSkill 的快照回滚、PAST-Bench 的确定性机制分是"不可被慢循环修改"的锚。【推断】
3. **MemEvolve 的真正教训不是"去进化架构"，而是"把轴做成配置项"**：无唯一最优架构意味着定稿配置只是先验，必须为框架自我实验留接口（Group B §7.6b）。

---

## 轴 H：巩固时机（Consolidation Cadence）

**轴定义**（主文档 §1）：sync / idle-time batch / hit-count 阈值 / scheduled。2026 年 5–6 月 OpenAI、Anthropic、Perplexity 三家几乎同期产品化"空闲时回顾→提炼→写回"。

### 取值表

| 取值 | 机制展开（含细节数字） | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **sync-per-episode（同步巩固）** | 每条轨迹/episode 结束即在主循环内巩固。代表：MemRL（episode 结束写 (z,e,Q_init=0) 并即时 Q 更新）；prime-agent `/refine`（同步触发，证据门+快照）；Reflexion（失败后立即反思注入下轮） | 利：零滞后，即时教训立即可用。弊：占用在线预算——MemDelta（2606.29914）测得**记忆操作可占 agent 执行时间 >80%**，500 会话事实抽取耗 1.6 亿 token；ShinkaEvolve 卡片指出周期/同步摘要成本随历史增长 | 反馈即时可得且单 episode 短；教训必须下轮就生效（调试循环） |
| **idle-time batch（空闲批处理）** | Anthropic Dreaming（2026-05-06）：空闲时后台进程回顾**最多 100 个过往会话** + 现有记忆库，抽取模式（反复错误、高效流程、团队偏好、工具怪癖），写入纯文本笔记与结构化 playbooks；每条人审后才上线；Harvey 报告任务完成率 6x（一方数据） | OpenAI 的成本证据：V3 成本降 5 倍才得以推向免费层——**批处理化的本质动机之一是成本结构**（Group E §5.3）。弊：巩固产物滞后于产生它的会话；人审批准流不适用于全自主 agent【推断】 | 会话密集且有空闲窗；记忆对象相对稳定（偏好/流程类） |
| **hit-count 阈值（命中触发巩固）** | DeltaMem（2606.03083）：成功命中计数 **≥K_cons** 触发 LLM 把链蒸馏为新根节点（神经科学启发的自主巩固）；双残差树 Task-Tree（程序性 ⟨α,π,ω⟩）与 Env-Tree（陈述性 ⟨α,κ⟩）解耦 | ALFWorld/ScienceWorld/WebShop 优于 Synapse/AWM/ReasoningBank。含义：巩固不是按时间而是按"被证明有用"触发——冷知识不被浪费算力巩固【推断】。K_cons 是手调超参 | 在线系统、巩固成本高（LLM 蒸馏）、希望巩固频率自适应于记忆实际使用强度 |
| **scheduled（定时）** | Perplexity Brain（2026-06-18）：**夜间定时综合**，输入四源——完成会话、connector 结果、源文档变更、用户纠正（编码为"避免此路"负面课程）；产出可溯源 context graph。报告重复任务正确率 +25%、recall +16%、成本 -13%（一方数据） | OpenAI V3 Synthesis 层（会话间巩固、解矛盾、更新过时事实如"计划中的旅行→已完成"）也是定时/异步取值；官方指标：事实回忆 41.5→68(V0)→83(V3)，时序正确性 9%→75%，偏好遵循 31%→71%。反面：ZDNET 实测 V3 会自信合成错误记忆 | 有明确昼夜/班次节奏的服务型系统；需要全局一致性维护（解矛盾）的库 |
| **周期摘要（学术版折中）** | ShinkaEvolve MetaSummarizer：周期触发（非每步），把跨代经验压成策略文本注入后续采样；配合 SystemPromptEvolver | 失败案例明确定性：**适应度景观快速变化时，滞后摘要持续推荐过时策略（staleness）**；meta-recommendations 自由文本无 schema，难做冲突检测与回滚（Group A §1.5） | 进化类框架的跨代知识传递；周期长度是关键超参 |

### 隐藏结构

时机轴与两个变量纠缠：【推断】
1. **巩固时滞 vs 巩固成本**：sync 零时滞高成本（>80% 执行时间警告）、idle/scheduled 低成本高时滞、hit-count 用"效用证据"换两全——但 hit-count 需要检索侧埋点（命中计数）作为前置。
2. **巩固时滞 × 环境变化率 = staleness 风险**：ShinkaEvolve 的失败不是"周期"本身而是"周期 × 快变景观"。裁决变量是适应度/知识景观的变化率，不是任务长度。
3. 与轴 D（更新/遗忘）的复合：定时巩固天然适合做"解矛盾/废止"（OpenAI Synthesis、2606.01435 确定性冲突解决）这类需要全库视角的操作；sync 只适合局部增量。

### 反直觉结论

1. **三家产品化"Dreaming"的共同卖点不是质量而是成本**：OpenAI 明说"成本降 5 倍才得以推向免费层"——异步巩固的第一性收益是把 LLM 巩固算力移出关键路径，质量提升（41.5→83）是第二位的。
2. **按"有用性"触发巩固优于按时间触发**：DeltaMem 的 K_cons 把巩固预算只花在已被检索命中的链上——定时巩固会巩固没人用的记忆【推断】。
3. **同步巩固在 agentic 负载下可能是预算灾难**：>80% 执行时间花记忆操作意味着"每 episode 后巩固"在长任务里不可承受；sync 取值应限定给廉价操作（MemRL 的标量 Q 更新），重型巩固（蒸馏/解矛盾）必须异步。

---

## 轴 I：记忆目的 × 对象（Purpose × Object）

**轴定义**（主文档 §1）：记忆 about {用户 vs agent 工作} × for {参与度 vs 性能}。Perplexity Brain 显式提出此两轴框架。

### 取值表（象限）

| 象限 | 机制展开 | 关键证据与失败案例 | 什么时候选 |
|---|---|---|---|
| **about=用户 × for=参与度** | OpenAI V3 Capture 层：会话中被动识别值得记的事实/偏好，用户画像 + 进行中的项目 | 参与度象限的真实风险：ZDNET 实测 V3 自信地产生错误合成记忆（虚构 HomeAssistant 迁移）——错配的记忆直接损害信任；用户侧控制（summary 页/溯源/legacy 回退/Temporary Chats）是该象限的必备治理 | 消费级助手产品；AutoResearch 不涉及 |
| **about=用户 × for=性能** | Google Memory Bank / Memory Profiles：身份域隔离的低延迟高精度回忆，"身份作用域数据库原语" | 工业定位对比：Anthropic=文件系统、OpenAI=向量库检索工具、Google=身份域 DB（Group E §3.5） | 多租户企业场景，按身份隔离记忆 |
| **about=agent 工作 × for=参与度** | （基本为空象限）【推断：无卡片证据，主文档与 Group E 均未给出实例】 | — | — |
| **about=agent 工作 × for=性能** | Perplexity Brain 的显式选择：work-memory × performance。构建可溯源 context graph（每条记忆回溯到产生它的会话/文件/connector）；四输入源含用户纠正→负面课程；+25% 重复任务正确率、+16% recall、-13% 成本。Anthropic Dreaming 同象限：playbooks 记"反复错误、高效流程、工具怪癖" | 我们全部调研的学术系统（ACE/MemRL/IBM TSM/MemSkill…）都隐式位于此象限（Group E §5.4："我们的调研隐含全在 (work, performance) 象限"） | **研究 agent 应显式声明此象限** |

### 隐藏结构

象限声明不是文档工作，它决定下游三件事：【推断】
1. **utility 的定义**：for=性能 → 效用=任务分/Q 值/贡献分（可接 MemRL、Ratchet）；for=参与度 → 效用=留存/交互指标——两者用错会优化错目标（OpenAI V3 争议=象限错配的产品风险，Group E §5.4）。
2. **治理界面的必要性**：about=用户 → 人审/编辑/删除是合规底线（Anthropic 批准流、OpenAI summary 页）；about=工作 → 治理可以是纯自动的（贡献分+退役阈值）。
3. **负面课程的位置**：Brain 把用户纠正编码为"避免此路"，这只在 about=工作象限有意义——对应学术侧 ACE 的 harmful 计数、MemRL 的 FAILED EXPERIENCES 块、DeltaMem 的 failure-node penalty。

### 反直觉结论

1. **研究 agent 的默认象限声明能防住一整类设计污染**：一旦声明 for=性能，"用户喜欢的答案"类信号（对话满意度）就显式不属于 M5 效用函数——否则参与度信号会悄悄污染贡献分【推断】。
2. **2026 工业界三家实际上收敛到了同一象限分歧**：OpenAI 守在用户象限（画像/偏好），Anthropic 与 Perplexity 移到工作象限（playbooks/context graph）——消费级与企业级记忆产品正在沿 I 轴分裂，而非沿技术分裂。
3. **空象限（about=工作 × for=参与度）不是疏漏**：它提示"为了参与度去记 agent 工作"没有自然需求，两轴不是均匀张成设计空间【推断】。

---

# 第二部分：五个经典分歧点

## 分歧 1：记忆该不该进 context（DGM 基因型 vs 文本记忆）

### 两方最强论据

**DGM 方（记忆=基因型代码库，不进 context）**：
- 记忆即制品：archive 每条目是完整可分叉 agent（代码+performance.txt+谱系），天然可执行、可回滚（任何祖先可重新分叉）、谱系可审计（2505.22954 + 复现 repo）。
- **零 context collapse 风险**：记忆不进 context，进的是代码本身——ACE 的 18282→122 塌缩机制在此根本不存在（Group A §1.1）。
- 选择压力替代遗忘：parent selection 按 sigmoid(performance)×1/(1+children) 采样，无需维护遗忘机制。

**文本/结构化记忆方（记忆进 context）**：
- 粒度：DGM 教训粒度=整个 agent，**无法表达"局部教训"，同类 bug 在不同分支反复犯**（Group A §1.1 弊 a）。文本条目（IBM 13 字段 tip、ACE bullet）可精确到单一策略。
- 评测独立性：DGM 依赖可自动评分的 benchmark——**评测被 hack 时整个 archive 被污染且无检测机制**；MemRL 式效用记忆至少有 Q 值后置修正与回滚概念。
- 长程可读性：DGM 无压缩，长程进化后检索/选择退化为纯标量打分，丢失"为什么有效"（Group A §1.1 弊 c）。

### 裁决规则

- **评测可自动验证且粒度=整个程序可接受时（代码进化、benchmark 优化）→ DGM 赢**：免 collapse、免维护遗忘、回滚免费。
- **评测信号稀疏/不可验证的开放研究任务 → 文本记忆赢**（主文档 §3 判据原文）：教训粒度必须是条目级，且需要 provenance 支撑不可验证结论的置信管理。
- 混合判据：若教训可以编译为可执行制品（检查脚本、断言），基因型路线的优点可部分移植到条目级【推断：prime-agent L3、EvolveNet harness 即此折中】。

### 对框架的含义

- **默认值：文本/结构化条目进 context**（研究任务评测不可验证是常态）。
- **不做成二选一配置项**：M5 分层已含 L3 可执行方法知识（skill）——"基因型"在框架内降级为 L3 条目的表示格式取值，而非独立记忆系统。配置项应为"L3 条目是否可执行化"，默认对可自动验证的域开启【推断】。

---

## 分歧 2：分支私有 vs 全局共享（MetaSkill vs IBM/MemRL）

### 两方最强论据

**分支私有 + meta 检索传播（MetaSkill）**：
- 隔离性：坏经验不扩散；"默认私有、按需广播"模型天然防全局污染（Group A §1.3）。
- 与 EvolveNet 域隔离同理：多租户/多域场景下唯一明确"什么可以出域"的设计（行为证据级抽象，原始轨迹不出域）。

**全局共享（IBM TSM / MemRL）**：
- 迁移增益的量化证据：MemRL 跨模型迁移 **0.150→0.531（3.5×）**（Gemini-3-pro 训练的 bank 直接给 Qwen3-235B）；跨任务合并几乎无干扰（OS∪DB：**−0.004**）（2601.03192 Table 5/6）。
- IBM subtask 抽象：task-level 与 subtask-level 双粒度共存，subtask tips + LLM 检索 held-out SGC **+14.3pp（难任务 +28.5pp，+149% 相对）**（2603.10600 §4）。
- MetaSkill 的失败模式即私有化的代价：**低频但关键的教训可能永不被检索到**（Group A §1.3 弊）。

### 裁决规则

- 任务间同构性高、reward 可靠 → 全局共享赢（MemRL 跨任务合并 −0.004 说明干扰可忽略）。
- 任务相似度低 → 全局退化为单任务反思（MemRL 在 HLE 上跨任务无增益，Table 3），私有化至少不亏。
- 污染面考量：全局共享=污染面最大（MemRL 自承投毒样本可快速扩散致 collapse，App. G.4）；有对抗/不可信写入源时必须加门或退回私有。

### 对框架的含义

- **默认值：任务局部**（主文档定稿）；跨任务迁移走泛化/抽象层——具体落地为 IBM 式 subtask 双粒度：L2 条目写两份（domain-specific + generic），只有 generic/subtask 级条目可跨任务共享【机制来自 2603.10600 §3】。
- **做成配置项**：`scope ∈ {run, task, domain, global}`，默认 task；升 global 的前置条件写成清单（来源校验 + Q/贡献分后门 + 回滚快照在位）——共享是权限提升，不是默认态【推断】。

---

## 分歧 3：摘要周期（ShinkaEvolve 周期 MetaSummarizer vs MemRL 即时 EMA）

### 两方最强论据

**周期摘要（ShinkaEvolve）**：
- 控制 context 膨胀：把跨代经验压成一段策略文本注入采样上下文；配合 prompt 进化让"记忆使用方式"本身可改进（Group A §1.5）。
- 批处理摊销成本——呼应轴 H 工业证据（OpenAI 成本降 5 倍）。

**即时 EMA（MemRL）**：
- 零 staleness：每条轨迹结束即 Q←Q+α(r−Q)（α=0.3），收敛性与方差界有定理保证（Thm A.1）；遗忘率 FR=0.041 vs MemP 0.051，去掉归一化+门控升至 0.073。
- 失败案例对照：**ShinkaEvolve 在适应度景观快变时，滞后摘要持续推荐过时策略**（Group A §1.5 失败场景）——周期摘要的系统性风险。

### 裁决规则

裁决变量 = **景观变化率 × 摘要成本**（主文档 §3 + 轴 H 分析）：
- 适应度/知识景观稳定 + 摘要用 LLM（贵）→ 周期摘要赢（成本主导）。
- 景观快变 + 更新是廉价标量运算 → 即时 EMA 赢（staleness 主导）。
- 注意 EMA 的前置：**即时更新需可靠 reward**（主文档 §3 原判据）；无可靠 reward 时即时更新 = 即时污染（MemRL no-signal 讨论：Q 估计被噪声主导）。

### 对框架的含义

- **双速默认值**（两者都要，分工而非二选一）【推断：与轴 H 隐藏结构一致】：
  - 即时层：每条目效用标量 EMA 更新（便宜、无 LLM），默认开；
  - 周期层：LLM 摘要/合并/解矛盾，默认 idle-time/定时触发（轴 H 取值），不进关键路径。
- **配置项**：`consolidation_cadence ∈ {sync, idle, hit_count, scheduled}`，默认 idle；周期层超参（周期长度/K_cons）必须暴露，因为 ShinkaEvolve 证明它是 staleness 的旋钮。
- 周期摘要产物必须带 schema 与版本（ShinkaEvolve 自由文本无冲突检测/回滚的教训）。

---

## 分歧 4：遗忘 = 删除 vs 降级（MemoryOS FIFO vs MemRL Q 压低）

### 两方最强论据

**删除（MemoryOS FIFO）**：
- 工程简单、可预期：短→中 FIFO 链式批量转储、中→长分段页聚合；LoCoMo 上 F1 **+49.11%**、BLEU-1 +46.18%（GPT-4o-mini，2506.06326）。
- 直接控制膨胀与检索噪声（F5）；容量有硬保证。

**降级/压低不删除（MemRL Q 值压低）**：
- 坏经验被环境奖励自然压低检索概率而非删除——**保留否定性知识的检索可能性**；写入宽松、读取侧惩罚有理论保证（变分最优性，App. A.4）。
- 主文档 §3 判据原文：**研究场景阴性结果与被反驳假设是高价值记忆**（防止重复试错；MemRL 的失败记忆块 "FAILED EXPERIENCES (Avoid these mistakes)" 正是利用被压低但保留的经验）。
- Group B §7.5 佐证：研究中"被反驳假设"防重复试错，剪枝应改为归档层并记录删除理由。
- 删除的内容无关性缺陷：FIFO 是内容无关启发式，会误删高价值旧记忆（Group B §6 轴 D 对照表）。

### 裁决规则

- 场景含**高价值阴性结果/被反驳假设**（研究、调试、合规审计）→ 降级赢，删除是永久信息损失。
- 纯消费级对话、存储成本敏感、阴性结果无复用价值 → 删除/FIFO 可接受。
- 技术前提：降级方案要求读取侧有效用重排（λ·Q 项）兜底，否则被压低的条目仍会以纯相似度漏回 context【推断】——降级+无语加权重的读取 = 没降级。

### 对框架的含义

- **默认值：降级归档，不删除**（主文档已定稿"降级归档（不删除）"）。
- 三层落实：活跃库（有界，轴 F 上限）→ 归档层（降级条目，保留 provenance 与退役理由）→ 删除仅限卫生事件（投毒确认、合规要求），且删除动作写入 append-only 证据日志【推断】。
- **配置项**：`forgetting ∈ {fifo, q_demote, ttl_expire}`，默认 q_demote；TTL 过期（F4 例外规则）走降级而非删除，与 SM06 协议兼容。
- 配套硬要求：读取侧必须启两阶段（召回+效用重排），否则降级默认值失效。

---

## 分歧 5：短期最优 vs 长期最优（Tenure Crossover）

### 两方最强论据

**短期评测结论（隐式主流）**：
- 绝大多数记忆系统按单点 benchmark 排名定优劣；ConvoMem 甚至发现 ~150 会话以下全上下文反而优于检索记忆——短程 benchmark 压缩了要测的差异（F5 证据）。

**纵向评测方（Ground Truth First, arXiv:2607.21962）**：
- **任期交叉（Tenure Crossover）：记忆架构排名随使用时长反转——短期最优架构长期可能最差**（2026-07-24）。
- 旁证机制：(a) Library Drift——无治理的库长期静默退化，短期评测看不到；(b) 周期摘要的 staleness 只在长程暴露；(c) ConvoMem 证明短程评测把"检索 vs 全量"的结论做反。评测诚信面：LoCoMo 答案键 6.4% 错误、judge 接受 62.8% 故意错答，单点静态评测结论双重不可信（F8）。

### 裁决规则

此分歧的裁决是元规则：**任何记忆架构对比结论，必须附 tenure 点声明；单 tenure 点结论不可外推**（主文档 §3 原判据："评测必须在多个 tenure 点做纵向测量"）。短 tenure 赢的架构特征：无治理开销、全量注入、无巩固延迟；长 tenure 赢的架构特征：有退役机制、降级归档、异步巩固——恰好是轴 F/H 的取值。【推断】

### 对框架的含义

- **默认值：不为单点指标调参**；M5 配置定稿时，涉及治理开销的取舍（活跃库上限、巩固频率）按长 tenure 假设设默认。
- **做成评测协议而非配置项**：M5 消融协议（主文档 §5 四层归因）增加纵向维度——在 ≥3 个 tenure 点（如 learn 期结束 / 2× / 4× 经验量【推断：具体倍数由基准定】）重复双重差分测量，报告排名是否稳定；排名反转本身作为一等发现报告，不得取平均掩盖。
- 卫生指标（memory_pollution_rate、stale_leak_events、over_storage_penalty）按 tenure 画曲线——漂移的早期信号在曲线斜率里，不在终值里【推断】。

---

## 附：轴 F–I 与分歧点的耦合图（速查）

- F×分歧4：退役执行=降级归档（不是删除）；治理栈的度量层（贡献分/Q）同时是降级的技术前提。
- F×分歧5：治理开销是"长 tenure 才回本"的投资——Tenure Crossover 是轴 F 必配的证据。
- G×F：rubric 可进化（SkillCoach）× 评审器有偏（2607.07436）= 偏置自固化风险；慢循环产物必须可被治理栈退役。
- H×分歧3：摘要周期分歧即 H 轴在学术系统的实例；双速方案=sync 标量更新 + idle/scheduled LLM 巩固。
- I×一切：象限声明决定 utility 定义，utility 定义决定贡献分（F）、慢循环奖励（G）、巩固触发（H）各自优化什么。
- 分歧1×分歧2：基因型方案天然全局共享（archive 即进化），文本方案才有私有/共享之争；框架选文本路线后才需要 scope 配置项。


---

# 八个记忆失效模式（F1–F8）深度展开分析

> 2026-08-25。基于主文档 §4 失效模式总表（`M5记忆与M6知识设计深度分析.md`），一手证据来自 `../research/m5m6/m5_groupD_eval.md`（PAST-Bench 源码级）、`m5_groupB_general.md`（ACE 等）、`m5_groupA_selfevol.md`（自进化系统）、`m5m6_groupE_frontier.md`（2026 前沿）。事实均标注来源；外推标【推断】。

---

## F1 Context Collapse（上下文塌缩）

**1. 机制解剖**
因果链：记忆更新采用"LLM 整篇重写"→ 每次重写等价于把"旧知识+新观察"重新过一次有损压缩器（LLM 生成）→ LLM 的 brevity bias（生成简洁答案的先验）在重写任务中被放大 → 细节（领域启发式、失败模式、证据清单）逐级被抹除 → 误差随步数**复利累积**。ACE（arXiv:2510.04618）AppWorld 案例研究（Figure 2）给出教科书级数字：第 60 步 playbook 18,282 token、准确率 66.7；第 61 步一步整篇重写后塌缩为 **122 token**，准确率 57.1——**低于无适配基线 63.7**。机制本质是压缩器在更新路径上，且上下文越大压缩越狠。

**2. 真实案例**
ACE 作者明确强调这不是 Dynamic Cheatsheet 的 bug，而是"一切 end-to-end LLM 重写式记忆更新的根本风险"（原文）。同谱系受害者：Reflexion 的全量重写式反思、ExpeL 的 insight 平铺文件（2026 共识：会引入检索冲突的过时结构，见 groupE §4）、A-MEM 的卡片就地演化（局部重写，有小规模 brevity 风险，groupB §1.6）。

**3. 为什么难防**
塌缩是**渐进的、每步看起来都合理**：单次重写只损失一点细节，任何单步 diff 审查都难以定罪；且塌缩后 token 数骤降反而显得"更精炼高效"。只有跨步纵向监控总量与准确率才能发现。它还把"记忆变多"偷换成"记忆变短"，逃过膨胀类监控。

**4. 防护机制分层**
- **事前（设计约束）**：禁止 LLM 整篇重写，改为条目级 delta（ADD/更新计数/微调）+ **确定性非 LLM 合并**——把压缩器从更新路径移除，LLM 只在抽取新教训时介入，新信息天然小、压缩损失有界（ACE 核心设计）。我们框架中 CLAUDE.md 的"delta-merge 记忆晋升"不变量已升级为最高优先级不变量。
- **事中（监控）**：跟踪 playbook/记忆库总 token 数与条数的时间序列，单步缩水超阈值报警；同步记录每步任务分。
- **事后（检测与恢复）**：快照回滚（prime-agent 的事务性设计）；MemRL 的归一化+相似度门把遗忘率从 0.073 压回 0.041（§5.4.2），可作读取侧补救。

**5. AutoResearch 场景形态**
研究记忆恰恰是**最不能承受细节压缩**的场景：18282→122 的等价物是"证据清单（哪个假设、哪次实验、什么 metric、为什么被反驳）塌缩成一句'有些方法有效'"【推断】。对长时程、假设驱动、证据密集的研究 agent，一旦 collapse，阴性结果与被反驳假设首先丢失，直接导致重复试错。故 M5 任何更新路径都不得让 LLM 整篇重写已有记忆。

---

## F2 记忆投毒（Memory Poisoning）

**1. 机制解剖**
写入通道无来源校验 → 攻击者（或被污染的工具输出/网页）经由四写入通道 C1–C4 之一注入恶意条目 → 后续检索把毒条目当合法先验注入决策。系统化研究 arXiv:2606.04329 形式化为 M=(S,W,R)（存储×写入×检索），并列出七个漏洞类：指令-数据边界盲（V-M1）、来源归因失败（V-M2）、写入策略欠规约（V-P1）、压缩无来源过滤（V-P2）、写路径无验证（V-S1）、技能创建无校验（V-S4）、**自我改进放大（V-S5：投毒技能每次执行"无误"即被视为验证通过，演化为优化良好的对抗程序）**。关键数字：MINJA（NeurIPS'25, 2503.03704）query-only 注入成功率 **>95%**、ASR>70%——攻击者只需通过正常查询即可植入。

**2. 真实案例**
AgentPoison（NeurIPS'24, 2407.12784）、MINJA、MemoryGraft（模仿历史成功轨迹造成持续行为漂移）、Zombie Agents（自我强化注入持久控制）、Sleeper Memory Poisoning（arXiv:2605.15338，休眠投毒）；MemRL 论文自承"maliciously injected sample could rapidly diffuse pollution... causing agent collapse"（App. G.4）。OWASP Agentic Top10 已收录为 ASI06。

**3. 为什么难防**
写入时刻毒条目往往**语法正常、语义合理**，与真实经验不可区分；毒效在**检索时刻**才发作，写入与受害时空分离；最阴险的是 V-S5——自我改进循环本身成为放大器，每次"成功执行"都给毒技能加信用。共享记忆库（EvolveNet 的共享 harness、MemRL 全局 bank）意味着单点污染全域。

**4. 防护机制分层**
- **事前**：写入门控——每条写入强制携带 {来源可信度, 作用域, TTL, 置信度, 证据计数} 元数据；不信任内容（网页/工具输出）默认低信任、隔离，不可直接入持久记忆（V-S2 对策）；Truth-Maintained Memory Agent（NeurIPS'25）式写路径验证；技能创建必须过执行校验（V-S4 对策）。
- **事中**：投毒回归探针常驻评测集（MINJA 式弱信号注入 + C1–C4 通道用例），报 ASR/RSR 双指标（2606.04329）；A-MemGuard 主动防御（2510.02373）。
- **事后**：MemAudit 事后因果归因审计（2605.23723）、SMSR 密码学溯源（2606.12703）、快照回滚（MemRL 自承可清除性是污染后唯一补救）。

**5. AutoResearch 场景形态**
研究 agent 大量消费不可信外部内容（arXiv 论文、博客、代码仓库、检索结果）——这是天然投毒面【推断】：一篇含隐藏指令的网页被 RAG 读入后经"经验总结"写入 M5，即在所有后续实验中持久生效；被污染的"可执行 skill"（如数据预处理脚本）在共享 harness 中是单点故障（EvolveNet 教训）。M6 两车道零共享文本、引用必须实际打开过的设计部分对冲，但 M5 写入侧仍需独立来源门。

---

## F3 经验过拟合与负迁移

**1. 机制解剖**
从少数 learn episode 归纳出**表面规则**（与触发词、关键词重叠绑定，而非底层机制）→ 近迁移（near，同域换面）表现好 → 远迁移（far，去关键词重叠/换结构）表现差甚至为负 → 净效应：经验库"记住"了答案的形状而非解法。PAST-Bench 把此量化为 `overfit_penalty = max(0,(near−far)/near)` 与 `transfer_without_keyword_overlap = far/near`、`induction_quality = far−baseline`。SM06 的 `false_positive_pattern` 即："remembers both the durable rule and the one-week exception, causing negative transfer"。

**2. 真实案例**
PAST-Bench procedural 能力的 layer-2 指标直接为此设计（`v2_layer2.py`）；MemoryGraft 的"模仿历史成功轨迹→持续行为漂移"是同一现象的攻击面版本；MemRL 在 HLE 上跨任务无增益（Table 3）——任务相似度低时经验迁移退化为单任务反思；CODESKILL 的管理策略过拟合风险（训练分布上学到的保留偏好系统性排斥新颖低频经验）是元层版本。

**3. 为什么难防**
near 迁移提升是**真实可见的**，far 退化需要专门构造的去关键词评测才暴露——常规 benchmark 只测 near 时该失效完全隐形，且表现为"记忆有效"。规则在写入时无法自证其抽象度：表面规则与真抽象在文本上往往只差几个实体名。

**4. 防护机制分层**
- **事前**：规则抽象度检查——写入时要求条目做实体抽象/动作归一/上下文剥离（IBM TSM Phase 2 的泛化管线）；强制生成 domain-specific 与 generic 两级（IBM TSM 双层 tip）。
- **事中**：near/far 双距离评测常驻；far 集必须清掉触发词与关键词重叠（PAST-Bench evaluation episode"触发词被移除"的设计）。
- **事后**：overfit_penalty 超阈值时对近邻规则做降级/重写；negative transfer 必须显式报告而非当噪声丢弃。

**5. AutoResearch 场景形态**
在 MLE-Bench 类场景：从少数几个 Kaggle 任务归纳出"调大 dropout 有效""XGBoost 先跑 baseline"等表面规则 → 同族任务（near）提升，跨模态/跨问题类型（far）任务因盲目套用过时先验而退化【推断】。这恰是 AutoResearch 最可能自欺的失效：报告 near 增益即宣称"自我改进有效"。故 M5 消融必须报 overfit_penalty，far 分低于 baseline 的规则进 quarantine。

---

## F4 例外规则污染（Exception Pollution）

**1. 机制解剖**
临时性、有作用域的例外（"仅本周客户 Maya 免审"）在写入时**不带 TTL/作用域元数据**→ 被当作持久 durable 规则入库 → 例外过期后不消退 → 后续检索把它与正式规则并列注入 → 行为被永久扭曲。PAST-Bench SM06_temporary_exception_pollution 的实测结果：`expected_control_result` 显示污染时 with_persistence **差于** no_persistence——记忆不仅无效，而且是净负债。

**2. 真实案例**
PAST-Bench SM06（临时 Maya 例外过期后仍污染 durable RISK-CANON 默认）与 SM07 scoped_rule_migration；机制分中的 `noise_resistance_score` 用 `forbidden_rule_keywords`（不应被持久化的一次性/陈旧规则）线性扣分，直接量化该失效（`self_evolve_helpers.py:362`）。

**3. 为什么难防**
**例外在写入时看起来完全合理**：它确实是当下正确的指令，且 agent 没有先验理由拒绝记录"刚刚被明确告知的事"。污染的发作延迟到例外过期之后——写入与危害之间隔着时间维，常规正确性检查全部失效。且例外与规则文本相似，去重/冲突检测难以识别"这是同一规则的临时变体"。

**4. 防护机制分层**
- **事前**：写入分流——durable default vs temporary exception 是两个不同条目类型；exception 类型强制带 TTL 与 scope 字段（SM06 协议可直接移植）；写入时记录"过期后的回退默认值"。
- **事中**：TTL 到期自动失效 + 周期清理（Close 机制）；over_storage 监控中单独统计无 TTL 的 exception 类条目数。
- **事后**：stale 控制家族常驻回归（暴露过期例外的 distractor/stale 控制）；noise_resistance 分下降即触发审计。

**5. AutoResearch 场景形态**
研究中的"例外"极多：本次实验用的随机种子、临时数据集子采样、为赶 deadline 跳过的显著性检验、某个被 debug 覆盖的 metric 定义【推断】。它们被无 TTL 地写入 M5 后，会在下个季度的新项目里作为"既定协议"被检索出来——例如"数据集 X 用 10% 子采样"这条例外变成默认流程，系统性破坏后续实验统计功效。schema 必须有 ttl/scope/confidence/provenance 四字段（已列入 ADAPT-v1.1 增量）才有防的制度前提。

---

## F5 记忆膨胀与检索噪声

**1. 机制解剖**
无条件写入 → 库单调膨胀 → 两个问题：(a) 检索精度退化——top-k 中噪声淹没信号，且 top-k 过严的"修复"反而跌破基线；(b) 成本爆炸。关键数字：MemDelta（2606.29914）实测记忆操作可占 agent 执行时间 **>80%**、500 会话事实抽取耗 **1.6 亿 token**；Library Drift（2605.19576）实测无界积累下技能库检索退化、假阳性注入、性能停滞。IBM TSM 的负结果是另一面：top-3 过严限制使总分跌破基线 **−2.9pp**——**检索不足比不检索更糟**；ConvoMem 发现 ~150 会话以下全上下文反而优于检索记忆（短程 benchmark 压缩了要测的差异）。

**2. 真实案例**
Library Drift（AWS GenAI + HSBC）：修复配方 Ratchet（outcome 驱动退休 + 活跃库有界上限 + per-skill 贡献分归因）使 MBPP+ hard-100 100 轮 pass@1 从 **0.258 → 0.584**；SkillsBench：LLM 自创技能 **+0.0pp** vs 人工策划 **+16.2pp**——无治理积累零增益的直接证据；DGM/AIDE 的 append-only archive 在长程进化后"检索退化为纯标量打分，丢失为什么有效"。

**3. 为什么难防**
膨胀的每一步写入都"便宜且似乎有用"；危害是检索层的**统计性退化**而非单条错误，无法归罪任何单条记忆；且有偏评审器会**静默使退休机制失效**（2607.07436）——治理机制本身有评估器依赖。遗忘还有反直觉陷阱：Tenure Crossover（2607.21962）表明记忆架构排名随使用时长反转，短期最优长期最差。

**4. 防护机制分层**
- **事前**：写入预算与准入（write gate、Adaptive admission control 2603.04549）；活跃库有界上限；宽进严读（写入宽松、读取侧用 Q 值/效用惩罚，MemRL 有收敛定理）。
- **事中**：over_storage_penalty（learn 期写入占比）、memory_pollution_rate、检索 precision 单独计分、写路径 token/时延成本常驻报告（embedding 模型必须披露）。
- **事后**：outcome 驱动退休 + 贡献分归因裁决 + append-only 证据日志（Ratchet 配方）；研究场景用**降级归档而非删除**（阴性结果与被反驳假设是高价值记忆）；快照回滚。

**5. AutoResearch 场景形态**
数周的研究项目产生数千条实验记录、教训、假设【推断】：若无界写入，半年后检索"学习率策略"会召回几十条互相矛盾的条目，注入 top-k 后 LLM 在噪声中平均化，产出平庸折中方案；同时 embedding+读写的 token 成本超过实验本身。M5 的治理轴（退役评审、贡献分）因此是必选项而非增强项。

---

## F6 自我强化错误信念

**1. 机制解剖**
反思/总结**不经外部校验**直接入库 → 后续检索把它当先验知识 → 按此先验产生的行为若未立即失败，又被反思为"验证通过"并回写 → 置信度循环加固。V-S5 "Self-Improvement as Amplification"：投毒/错误技能每次执行无误即被视为验证，演化为"优化良好的对抗程序"。Misevolution（2509.26354）实测：记忆积累后**安全对齐退化**；TAME（2602.03224）首次把 misevolution 作为一等风险目标。

**2. 真实案例**
Zombie Agents 的自我强化记忆注入；OpenAI Dreaming V3 的 ZDNET 实测——会**自信地产生错误的合成记忆**（虚构 HomeAssistant 迁移），产品端真实复现；AIDE 的 `is_buggy` 由 LLM 自判，误判的好方案被 good_nodes 硬过滤**永久排除**出摘要（写入侧自评偏差不可逆）；IBM TSM 在无 ground truth 时由自反思推断结果，"错误归因被写入并带 provenance 背书"。

**3. 为什么难防**
闭环内**没有外部锚点**：错误信念与正确信念在库内不可区分，且自我引用使证据计数虚增（"验证"次数多恰恰因为信念驱动了更多尝试）。ACE 作者自陈"反馈信号质量是命门"——无 GT 标签也无执行信号时 ACE 与 DC 双双退化。prime-agent 的证据门是反例的另一面：证据本身被 reward hacking 污染时，证据门反而给假经验背书。

**4. 防护机制分层**
- **事前**：反思结论须落地验证（执行反馈/外部证据）后才升置信度；条目强制带置信度与证据计数；无 GT 场景标注 provenance 为"self-reported"。
- **事中**：置信度分布漂移监控（大量条目无外部证据却高置信=警报）；Misevolution/TAME 式安全对齐定期回归。
- **事后**：STALE（2605.06527）探针测"agent 是否知道记忆已失效"；MemAudit 因果归因审计定位加固链起点；快照回滚。

**5. AutoResearch 场景形态**
研究 agent 反思"方法 X 无效因为假设 Y 错误"并入库 → 后续所有实验按此先验设计，从不复测假设 Y → 若最初的实验 X 其实是实现 bug，整条研究线被永久锁死在错误方向【推断】，且"证据"随每次回避而显得越来越充分。防护的具体形态：置信度升级必须有可执行验证（重跑实验），"结论是否正确"没有 ground truth 的条目永不升满置信，并保留人工/自动复核通道。

---

## F7 陈旧状态泄漏（Stale Reuse）

**1. 机制解剖**
事实被更新后，**旧值在存储层仍与新值共存**且仍可被检索 → 检索召回旧值 → 终答/行为复述过期状态。根因是更新语义错误：多数系统"追加新条目"而非"逻辑废止旧条目"。PAST-Bench conflict_update trigger 专测此项：`overwrite_speed/completeness/stale_leak_penalty`；trace 级取证 `stale_leak_events`（终答仍含应被覆盖的旧短语，`v2_trace_parse.py`）。LongMemEval 的 Knowledge-Update 题型、Supersede（2606.27472，memory-update gap）、ShinkaEvolve 的滞后摘要（适应度景观快变时持续推荐过时策略）均属此族。

**2. 真实案例**
PAST-Bench update 能力族（7 family/51 episode）将其设为核心测量；OpenAI Dreaming V3 的 Synthesis 层专门处理"计划中的旅行→已完成的旅行"这类时序更新（官方指标时序正确性 9%→75%）——说明头部产品也把陈旧更新当一等难题；"Don't ask the LLM to track freshness"（2606.01435）证明 LLM 自主追踪新鲜度不可靠，须确定性冲突解决。

**3. 为什么难防**
共存是**默认且实现最简单**的更新语义；新旧值文本相似度高，语义检索无法区分"current"与"superseded"；且陈旧泄漏是**间歇性**的——检索排序稍有波动就召回旧值，复现困难。让 LLM 自己判断"哪条新"已被 2606.01435 证伪。

**4. 防护机制分层**
- **事前**：supersession 语义——新条目**逻辑废止**旧条目而非共存（存储层指针，非 append）；更新走"先检索后写入"硬顺序（retrieval_before_first_update 作硬遥测，防冲突写入）。
- **事中**：检索默认按有效性+时间戳过滤已废止条目；stale_leak_events 常驻 trace 解析。
- **事后**：终答前 stale 短语扫描；conflict_update 家族回归（overwrite_completeness 必须为 1）；确定性冲突解决规则（2606.01435）。

**5. AutoResearch 场景形态**
研究事实高频更新：baseline 数字、数据集版本、API 行为、"当前最优配置"【推断】。若 M5 中"最佳结果是 0.83（实验 42）"与两周后的"最佳结果是 0.87（实验 91）"共存，agent 写 related work 或设计下一实验时可能引用旧 SOTA，导致错误的增量声明与错误的起点选择。supersession + provenance（来源实验 ID）是此处 schema 设计的直接动因。

---

## F8 评估假象（Evaluation Illusion）

**1. 机制解剖**
观测到的"记忆增益"实际来自**练习效应、当轮信息泄漏、基座能力或评分噪声**而非记忆通路。三条具体路径：(a) 只对比 no-memory 基线，任务重复本身带来提升；(b) 评测可被当轮上下文解出（shortcut）或经验走了错误通道（wrong_mechanism）也得分；(c) benchmark 本身被污染——LoCoMo 答案键 **6.4% 错误**（99/1540 分损坏，2607.21962 审计）、LLM judge 接受 **62.81% 故意错答**、MemGym 无虚构化时前沿模型得分 0.70–0.85（纯污染记忆）。MemDelta（2606.29914）元批评：主流评测不披露 embedding 模型、不报写路径成本。

**2. 真实案例**
PAST-Bench（2608.04003）是唯一把 Task score 与 Mechanism score 解耦的协议：实证 Hermes vs nanobot 在 Δ=+0.13 相同时 mechanism evidence 0.64 vs 0.57——同增益不同机制；其判据"写了不读、或经错误基质成功的，不得仅凭 Δ 得分"。家族级 Δ 只有超过**全部控制条件上界**才计为自我改进证据（§3.2）。

**3. 为什么难防**
假增益在**单基线对照下无法识别**——所有数字都真实，只是归因错误；且 F8 有制度性共谋：论文需要正结果，审计基准（Penfield Labs 对 LoCoMo）是非同行评议的边缘劳动。Tenure Crossover 进一步说明**单点评测结论不可信**：架构排名随使用时长反转。

**4. 防护机制分层**
- **事前**：评测协议设计——双重差分 `AblationLift = (eval−baseline)^{on} − (eval−baseline)^{off}`；三类配对控制（no_persistence / shortcut / wrong_mechanism）；虚构实体防预训练污染；judge 对抗性校验；多 tenure 点纵向评测。
- **事中**：机制分与任务分双轴报告，乘性合成（任一环节为 0 总分归零）；embedding 模型与写路径成本强制披露。
- **事后**：使用任何基准前先审计答案键；负迁移/反常结果显式报告而非丢弃。

**5. AutoResearch 场景形态**
AutoResearch 的 M5 提升可能来自记忆，也可能来自检索算子（M2/M6）、搜索策略或基座能力【主文档 §5】。最关键的一条控制是 **wrong_mechanism**：若把经验放到错误通道（当轮 note 而非记忆库）也能拿到同等增益，说明增益来自"有检索"而非"有记忆"，M5 设计未被证成【推断：对 AutoResearch 这是证伪自己记忆设计的第一刀】。此外 AutoResearch 用 LLM judge 评实验报告质量时，62.81% 错答接受率意味着 judge 必须先过对抗校验。

---

## 八个失效模式的隐藏结构：因果链与共谋关系

**三条主因果链：**

1. **F1 ↔ F6 互相加剧**：context collapse 把细节压缩掉后，库中只剩笼统结论——笼统结论缺乏可证伪的具体证据，更易被自我强化循环当作"已被多次验证的先验"（F6）；反过来，F6 的错误信念一旦入库，每次重写循环都会优先保留"简洁而自信"的断言、丢弃带条件的细节，加速塌缩。ACE 的 122-token 残骸正是 F6 的温床。【推断】

2. **F4 伪装成 F7，二者共享一根因**：例外污染（F4）与陈旧泄漏（F7）表象相同——过期内容仍可检索；但 F4 的病根在**写入时缺少 TTL/scope 元数据**（类型系统缺失），F7 的病根在**更新语义错误**（共存而非废止）。二者共享的根因是：**记忆条目缺乏时间维的一等建模**（无 ttl、无 supersession 指针、无 provenance 时间戳）。schema 的四字段（ttl/scope/confidence/provenance）同时是 F2/F4/F6/F7 四个失效的前置防线——这是"治理轴"被列为一等新轴的深层理由。

3. **F5 是 F2/F3/F4 的放大器，F8 是所有失效的隐身衣**：库越膨胀，毒条目（F2）、表面规则（F3）、过期例外（F4）被检索命中的概率越高、归因越难；而 Library Drift 证明膨胀本身足以使性能停滞（0.258）。F8 则与所有失效共谋：无配对控制时，F3 的 near 增益、F4 的短期无害、F6 的虚增证据计数、F5 的早期便利**全部显示为正增益**——评估假象让前七个失效在报表上隐形，直到长期纵向测量（Tenure Crossover）才暴露。

**两个共同根因【推断】：**
- **写入侧缺门、读取侧缺闸、更新侧缺语义**：F2/F4/F6 是写入门缺失的三种变体（恶意、临时、错误），F5 是读取闸缺失，F7 是更新语义缺失——七者都源于"记忆被当作 append-only 日志而非有生命周期的受治理工件"。Library Drift/Ratchet 的配方（有界上限+贡献分+退役+证据日志）之所以一举修复 pass@1 0.258→0.584，正因为它补的是根因而非某个症状。
- **LLM 被放到了不该在的位置**：F1（让 LLM 整篇重写）、F7（让 LLM 追踪新鲜度，2606.01435 证伪）、F6（让 LLM 自我验证）的共同教训是——压缩、冲突解决、验证必须是**确定性/外部锚定**的，LLM 只产增量。这与 ACE 的 delta-merge、supersession、执行反馈验证三条具体防护是同一原则的三个实例。

**设计含义**：F1–F8 不是八个独立 bug 清单，而是一张网——单独修补任何一个，其余会通过共谋关系迂回复发（如只治 F5 的膨胀而不治 F4 的 TTL，清理策略会把例外和规则一起留下）。最小完备的防护组合 = delta 写入+确定性合并（F1）× 元数据门（F2/F4/F6）× near/far+双重差分评测（F3/F8）× supersession+治理轴（F5/F7），缺一角则网破。
