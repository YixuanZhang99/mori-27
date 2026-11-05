# 设计银行中的其余工作：接入规格目录

状态：**候选范围卡，不是已实现支持清单，也不是本轮全部排期**。
依据：[统一抽象 §5](../../AutoResearch模块化统一抽象.md)、[新增 15 工作映射](../../新增工作九模块映射表.md)、各 UNIFIED 的 profile 节。
以下机制描述来自仓内设计材料，本轮未逐一重新核实其外部论文/源码。开始某项时只核对其固定来源、公开许可与具体任务，再将范围卡提升为独立冻结 spec；不因调研表一行文字声称完整复现。

C01–C08 已有独立规格。其余各项的最小交付与“什么才算完成”如下；未列模块沿用 COMMON，不隐含新增能力。

## 整方法扩展候选

| ID / 工作 | 设计要求 / 涉及模块 | 最小接入与验收 | 依赖与状态 |
| --- | --- | --- | --- |
| E01 ShinkaEvolve | M1 Bandit；M2 patch；M4 岛屿；M7 三池；M8 public/private | 模型选择状态可恢复，成本更新影响选择；公开反馈进生成，private 不进；proposal/eval/db 配额实测 | C05 后；不是只有 public/private 字段即完成 |
| E02 DGM | M1 powerlaw；M2 self-modify；M4 永久 archive；M5 genotype；M7 agent-as-candidate | 固定外环，修改 agent 工件，运行任务集聚合；非当前最优 stepping stone 能继续供亲；功能性存活门可拒绝 | 需 L1 candidate、嵌套评估和自修改边界；后置 |
| E03 OpenRSI | M1 父采样；M2 四算子同动作空间；M8 reward | draft/improve/debug/crossover 真实路由及父数检查；训练/推理相同动作编码 | C03/C06；先推理适配，RL 训练单列，代码许可核实前不 vendor |
| E04 AIDE² | 外环改 harness，内环解题；M3 固定费用；M8 嵌套 | 同一内任务集合比较两个 harness，外层只消费允许指标；内外成本无漏记 | C03+E02；材料含博客级证据，不能据此写完整论文复现 |
| E05 MetaSkill-Evolve | M2/M3 可进化；M4 lineage/inspiration DAG；M5 L1–L3 | skill/meta-skill 双时间尺度，冻结任务复评，策略变更可回滚且来源可查 | 自修改接缝后；不先实现学习系统 |
| E06 EvolveNet | M2 aggregate/merge；M4 星形；M5 本地/共享；M9 gate-not-rank | 两个隔离客户端只交换允许 delta，按 per-item flips 合成并准入；本地数据不出域 | C08+聚合契约；先本地双客户端 fixture，非分布式生产声明 |
| E07 prime-agent | M5 executable L3；M9 自改准入 | refine 生成可执行检查，证据 gate 通过后晋升；失败回滚恢复旧层 | 先作为 memory 扩展；完整 RLM harness 后置 |
| E08 KAPSO | M4 git DAG；M5 episodic；M6 类型知识/ERA；M8 多 rollout | 失败触发内外两路检索，来源分标，包实际进入修复；固定任务多 rollout | C04；先本地知识包，联网 research 单列 |
| E09 ML-Master 2.0 | M1 MCTS；M5 L1/L2/L3 HCC | 分层压缩/晋升、授权跨 run recall，固定任务对照证明读取路径 | C06+C04；记忆插件先于新整方法 |
| E10 FM Agent | M2 crossover；M4 cluster/island；M7 双池/Ray | 小规模双池资源反压、跨岛供亲与失败隔离；核心未开放时只能称机制适配 | C05/C07；不将闭源部分当可完整复刻 |
| E11 AIBuildAI | M1 manager；M4 multi-start；M6 RAG；M7 异质角色 | 两起点、两角色、分层知识包与独立 aggregator 的闭环 | C08；来源开放程度核实前只做机制 spec |
| E12 AiScientist-2026 | 层级编排；M5 File-as-Bus；M7 专家；M9 ratchet | 版本化文件工件驱动上下阶段；只有可执行证据可更新 best | 与 AI-Scientist veto 反例不是同一目标；需独立来源锁定 |
| E13 RelayEvolve | M1 相位；M3 handoff | 预声明 Relay Gain 信号触发一次相位切换，整代成本记账 | 需要已观察到相位问题后才装回 |
| E14 EvoX | M1 策略种群 | 固定策略族与独立元评估，策略 lineage 与任务分数分开 | 设计银行，非首批 |
| E15 EvoDiverse | M4 多池交换 | 多池隔离、受控交换改变供亲、预算与来源留存 | C05 后；最初先作为 frontier 插件 |

## 运行模式和治理机制（不伪装成整方法复现）

| ID / 工作 | 所需模块 | 最小规格与验收 |
| --- | --- | --- |
| X01 Codex/Claude Code | M1 单链、M7 外部 agent | 作为执行后端 adapter；输入任务、返回 artifact/成本，失败可分类；不复刻模型产品本身 |
| X02 openresearch-cli | M4 git 谱系、M6 工具、M7 launch | 一个实验一个隔离 worktree，CLI 引用对应工件；SSH/Slurm 等后端各自有证据才宣称支持 |
| X03 Moss | M7 角色与阶段、M9 自动/人工/健康三门 | 三门分别可拒绝、失败恢复旧 artifact；已有预算/审批复用，不新建 daemon |
| X04 Argus | M7 多角色、M9 Reviewer、X1 resume | 执行/评审权限分离，仅从已验证状态续跑；一次拒绝演示足以验收关键机制 |
| X05 SEAL | M8 密封反馈、M9 外部门 | 搜索只见规定 bit；验证器无写权限；正/负例与回滚可重放。不是调低反馈字数即可 |
| X06 BigBang-v1 | M8 评测卫生 | 固定数据/答案隔离/去污染与 judge 协议；不宣称复刻其模型训练或 35B 权重 |
| X07 Simple Baselines | M1 IID-RS/SCS、M5 最小记忆 | 无 fitness 供亲的独立对照，同总预算、相同 seed/task 口径，包含失败；复用现有 control |
| X08 agentgateway | M3 reserve/settle | 预算机制参考；当前账本已有对应能力，只补实际缺口，不作为新增研究方法 |
| X09 MLOps registry | M8/M9 canary/registry | 精确工件准入、canary 失败回滚；运营扩展，不纳入首批研究 benchmark |

## M5/M6 局部 profile（逐插件验收）

| Profile | 最小接入 | 决定性验收 |
| --- | --- | --- |
| ace | structured bullets + deterministic delta merge | 增量写不覆盖旧有效条目；容量有界；具体经验被下一次生成引用 |
| memrl | (z,e,Q) + two-stage retrieval | 固定相似度下 Q 更新改变排序；跨任务仅在声明同构时允许 |
| ibm_tsm | domain-specific/generic 双份、冲突合并 | domain-only 不跨任务；冲突取舍有来源；scheduled consolidate 单独测试 |
| dreaming | scheduled playbook、人审晋升 | 未批准只生成候选，批准绑定内容且可回滚 |
| no_governance | 对照用 none/similarity/noop | 必须显式选择，不作为默认正式运行；不能绕过外部费用上限 |
| arbor_two_lane | 独立 ground/audit | 命名空间/来源/注入分离；benchmark 无检索调用；完整联网留 C04 后 |
| kapso_era | 失败驱动 recall+repair | M5/M6 分标且真实进入修复上下文 |
| tree_of_ideas | gap signal card | 每张卡有已打开来源与作用域；卡影响 ideation；novelty 建议不得独自 veto |
| ideagent_qd | 去重证据供给 | M6 只供证据，M2 执行约束；embedding 版本变化使旧比较失效 |
| ai_scientist_veto | **反例，不支持取值** | 单车道 LLM novelty 一票否决在配置或权限验证时拒绝；不能将其列为“已支持经典工作” |

M5 的 dgm/prime_agent 归 E02/E07；M8M9 的 openevolve_cascade/shinkaevolve_contract/seal_gate/moss_three_gates 归 C05/E01/X05/X03，不重复开项目。
`gepa_validation_heavy` 是计费失效反例，归 C01 的所有评估计量测试，不是另一个可交付 GEPA 算法。

## benchmark 是任务，不是方法

| 任务族 | 接入位置与下一步 | 当前边界 |
| --- | --- | --- |
| MLE-Bench Lite | 既有 `m0/zoo/mle_bench_lite/`；C03/C04/C06/C08 复用 | 三任务实测 != 全 22 任务；不把旧 baseline/full 重命名为 AIDE/Arbor |
| OR3 bin packing | 既有 `m0/zoo/funsearch_binpacking/`；C02 | 固定参考程序 dev 评分 != 真实程序搜索 |
| GSM8K | 既有任务评分；C01 补 train/validation/test adapter | toy 不算真实模型成绩 |
| RE-Bench | 既有 `m0/zoo/re_bench/`；另排真实资源 | 七任务 campaign 未完成，不能作为 B3 已达标 |
| NanoGPT-Bench / llm-speedrun | 训练 checkpoint + fidelity/paired seed；GPU 明确后接 | 不阻塞首批 CPU 方法 |
| karpathy/autoresearch / MLGym / FML-Bench | 按 ZOO 独立锁定任务/环境/评分 | 核实协议后再施工，非本轮首发清单 |
| PAST-Bench | M8 task/mechanism 双分；三类 persistence controls | 单独验证 memory 通路，不用任务分上涨代替归因 |
| PostTrainBench | 原 RUBRIC B3 的备选 | 已选 RE-Bench，不并行再接一套 |

FlashRSI、RSIHub、penguin-harness、RSI-Anything 是工程参照，已有固定来源比较见 [研究记录](../../../research/2026-11-04-framework-development-priorities.md)。每个经典方法开始时复查与它直接相关的 recipe/runner/report 模式；不是把四个仓库也作为四个待复刻算法。
