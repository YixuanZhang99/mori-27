# FlashRSI / RSIHub：能力与结果证据核对

核对日期：2026-11-04。仅研究官方当前 README、文档、配置与代表性源码；没有运行模型、基准或付费服务。本记录不评价 mori-27 的实测性能。采用 research skill 的一手来源记录流程；本执行者本身是已委派的研究子任务，未再委派。

辅助阅读的本地参考版本：FlashRSI `4c7f6327fdec7ce09150a1b2958f8051a9653e4a`；RSIHub `d6554299c58bf0fe2db04ddda0277f9db67ea680`。在线 `main` 会变化，引用链接反映本次访问；本地源码检查不能替代当前线上所有文件的一致性审计。

## 四种证据不能混用

| 层级 | FlashRSI | RSIHub |
| --- | --- | --- |
| 方法实现 | 13 种适配实现：OPRO、GEPA、EvoPrompt、ACE、SkillOpt、Evo-Harness、AHE、ADAS、DarwinX、Meta-Harness、ModularRSI、RRSI、Arbor。不要把“适配实现”说成原论文全部功能及结果的精确复现。 | 5 个方法家族：Hill Climb、A-Evolve、AHE、GEPA、HyperAgents；另有不同 target/runtime/full-benchmark recipe 变体，不应将每个变体计成新方法。 |
| 任务接入 | 30 个 benchmark adapter，29 套可用 HF prepared 数据、34 个配置；不是 30 套全部实测通过。 | 主要通过 Harbor；可见主 recipes 是固定 Terminal-Bench 2.0 子集，以及两个全部 89 题的 full profiles。另有论文海报 skill evaluator。 |
| 公开结果 | 12 方法 × Claude Code/Mini-Agent 的源任务和冻结迁移矩阵；Arbor 不在该研究结果中。 | README 给出 4 方法 × MiniSWE/Codex 在 Terminal-Bench 2、Tau³ Banking 的 seed→evolved 成绩。 |
| 本次独立复现 | 无：只核查官方发布与实现。 | 无：只核查官方发布与实现。 |

方法与结果范围：[FlashRSI README](https://github.com/RUC-NLPIR/FlashRSI#supporting-methods)。RSIHub 方法/任务清单：[recipes inventory](https://github.com/simple-agent-lab/RSIHub/blob/main/recipes/README.md)。FlashRSI 数据及验证状态：[benchmark 配置索引](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/benchmark-quickstart.md)。

## 可展示的典型方法与任务

- FlashRSI：OPRO/GEPA/EvoPrompt 对指令做搜索；ACE 累积 playbook；SkillOpt/Evo-Harness 演化 skills；AHE/Meta-Harness/RRSI 修改 harness；ADAS 使用设计 archive；DarwinX/ModularRSI/Arbor 使用分支或树式搜索。这是方法目录与对应实现存在的证据，不是本次逐个算法正确性审计。[方法目录](https://github.com/RUC-NLPIR/FlashRSI/tree/main/flashrsi/algorithms)
- FlashRSI 已发布实验的 4 个源任务为 SearchQA、HotpotQA、Terminal-Bench 2.0、AppWorld；迁移到 NQ、TriviaQA、MuSiQue、SWE-bench、BFCL Multi-Turn、OfficeQA Pro、DeepSearchQA。[结果矩阵](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/public/project-assets/results-matrix.html)
- 更广 adapter 覆盖数学、代码修复、网页检索、办公文档、API、交互环境；但 DeepSWE 明确只做接口适配，未下载官方任务或开展实验；HLE 是纯文本子集，SpreadsheetBench 2 不含 Visualization，BFCL 是 Multi-Turn Base 范围。[接入范围与限制](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/benchmark-quickstart.md)
- RSIHub 可展示可组合的选择、rollout、分析、mutation、validation、gate、record；实际 GEPA recipe 含 Pareto parent selection、同一 minibatch 比较、结构化反思证据、组件轮换修改、canonical gate。其组件包括 prompt 与整个 skill 目录。[GEPA recipe](https://github.com/simple-agent-lab/RSIHub/blob/main/recipes/gepa/README.md)

## 具体公开分数：作者报告，未经本次独立重跑

FlashRSI 下表均为同一 target 的初始→最终百分比分数；不是通用模型排行榜分数，不能据此与另一框架直接排胜负。

| 方法 / target | 任务 | 初始 → 最终 |
| --- | --- | --- |
| OPRO / Claude Code | SearchQA | 73.93 → 81.43 |
| GEPA / Claude Code | HotpotQA | 57.32 → 62.20 |
| RRSI / Claude Code | Terminal-Bench 2.0 | 63.33 → 76.67 |
| RRSI / Claude Code | AppWorld | 64.88 → 92.86 |
| GEPA / Mini-Agent | HotpotQA→DeepSearchQA 冻结迁移 | 52.00 → 34.00 |

分数来源：[官方结果矩阵](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/public/project-assets/results-matrix.html)。正向提升与迁移退步同时存在。项目页面明确标记 summary table 已有、raw logs 待补；本次没有找到可把以上每格成绩连到公开完整运行配置、种子、逐题轨迹的实验包，故不能把这些表格当成已独立审计的复现证据。[项目页源码](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/public/project.html)

RSIHub：下表为 README 的 full benchmark score，非 train 或 sealed-only score；方法顺序固定为 AHE / HyperAgents / A-Evolve / GEPA。

| benchmark / target | seed | evolved，依上述方法顺序 |
| --- | --- | --- |
| Terminal-Bench 2 / MiniSWE | 56.2 | 65.2 / 69.7 / 69.7 / 64.0 |
| Terminal-Bench 2 / Codex | 69.7 | 71.9 / 70.8 / 70.8 / 69.7 |
| Tau³ Banking / MiniSWE | 27.8 | 28.9 / 33.0 / 27.8 / 29.9 |
| Tau³ Banking / Codex | 24.7 | 34.0 / 28.9 / 28.9 / 33.0 |

README 声明 target 为 GPT-5.4 high，Codex mutate 为 GPT-5.4 xhigh；Terminal-Bench 划分为 50 train / 19 gate / 20 sealed；Banking 为 50 / 20 / 27。因此 full benchmark 含训练与 gate 题，不能改称纯 holdout 成绩。[官方结果及设置](https://github.com/simple-agent-lab/RSIHub#benchmark-results)

RSIHub 另有 4 篇人工选论文的海报 skill 演化：Gen0 1/4→Gen2 4/4，模型 `gpt-5.6-sol`、每题一次尝试、无 Docker。这个二值 reward 只度量 SVG 可渲染与几何完整性；审美、传播质量、论文忠实度仅是 advisory feedback。它是小型展示，不是广泛任务能力的统计证据。[公开逐题 snapshot](https://github.com/simple-agent-lab/RSIHub/blob/main/docs/results/paper-poster-skill-evolution.json)

## 源码和配置揭示的边界

| 检查点 | 观察与含义 |
| --- | --- |
| FlashRSI GEPA | 有真实 `evolve` 循环、train minibatch、dev population、reflection proposal、筛选和最终 selection；源码不是只有配置名。仅改一个 instruction file，省略 compound-system module rotation，拒绝 `use_merge: true`。[源码](https://github.com/RUC-NLPIR/FlashRSI/blob/main/flashrsi/algorithms/gepa/__init__.py)、[适配说明](https://github.com/RUC-NLPIR/FlashRSI/blob/main/docs/gepa.md) |
| FlashRSI 示例 ≠ 公开成绩配置 | `examples/gepa.yaml` 是 HotpotQA context/MiniAgent，limit 60、自定义 50/25/25 划分、seed42、模型占位符。不能将它作为上述结果矩阵的完整实验设置。[示例](https://github.com/RUC-NLPIR/FlashRSI/blob/main/examples/gepa.yaml) |
| RSIHub GEPA | 真实 mutate operator 读取反思证据、调用 agent 修改 checkout 并产生 patch。可修改面是 `target/**`，component focus 不等于更窄的权限边界；系统感知 merge 未启用，因为 driver 使用单 parent lineage。[operator](https://github.com/simple-agent-lab/RSIHub/blob/main/library/mutate/gepa.py)、[recipe 解释](https://github.com/simple-agent-lab/RSIHub/blob/main/recipes/gepa/README.md) |
| RSIHub 默认示例 ≠ full benchmark table | 默认 GEPA 是 20 generations、预算150美元、Harbor/Docker、`terminal-bench-2-30-v1`、50/40/10 split、repetitions=1。此示例不能被当作 README 89题/97题结果的完全可复现实验包。[实际配置](https://github.com/simple-agent-lab/RSIHub/blob/main/recipes/gepa/evolve.yaml) |
| RSIHub 结果凭证 | 官方运行指南要求 archive、generation tags、candidate commits、evaluator receipts、operator artifacts 一致；运行中的进程/容器不代表 generation 完成。该机制的实现与某个公开分数已附全套公开原始凭证是两件事。[运行与验证指南](https://github.com/simple-agent-lab/RSIHub/blob/main/docs/guides/recipe-to-experiment.md) |

## 对 mori-27 对照表的写法建议（判断标准，不是 mori 审计结论）

应分别列出：方法核心逻辑是否实现；真实任务 adapter 是否能调用官方 evaluator；是否完成 baseline→mutation→evaluation→selection；是否有固定测试集的前后分数与逐题凭证；是否验证重复运行、成本及迁移表现。测试数量、协议文档数量、mock 分数和学习日志都不能替代这些实验成绩。与上面两者比较前，要固定模型、任务集、预算、评分协议及可变更范围。

缺失某项时应直写“未实现”“只有 adapter”“仅 smoke”“没有有效基准成绩”或“本次未核实”，不要把未找到证据等同绝对不存在，也不要把已有 framework gate/audit 能力包装成 agent benchmark 提升。
