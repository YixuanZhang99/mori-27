# 记忆设计空间 A–E 五轴深度展开分析

> 依据：`M5记忆与M6知识设计深度分析.md` §1 轴体系；证据来自 `research/m5_groupA_selfevol.md`、`m5_groupB_general.md`、`m5_groupD_eval.md`、`m5m6_groupE_frontier.md`。标注【推断】者为卡片未直接给出、基于系统行为的合理分析。

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
