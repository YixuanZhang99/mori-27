# REFERENCES.md — 按模块的精读清单（实现时看这些文件）

> 用法：实现某模块前，先读对应行的代码文件（优先级高于论文）；论文用于理解"为什么"。
> 完整调研笔记在 research/dim00-08/（9 个 dim 文件）（每个 dim 文件含一手引用与代码级细节）。
> 仓库克隆建议：`refs/` 目录下集中 clone，浅克隆即可。

## 总入口：三个必克隆仓库

| 仓库 | 为什么 |
|---|---|
| `RUC-NLPIR/Arbor` | 语义状态 + 准入 + 插件化的最近参照，工程完整度最高 |
| `facebookresearch/aira-dojo`（或官方组织路径，以论文为准） | 五元组形式化 + registry + Hydra 组装的教科书 |
| `codelion/openevolve` | 进化系五组件架构 + 全 YAML 配置的教科书 |

## 按模块

### 六数据类型 / 节点 schema
| 看什么 | 路径 | 学什么 |
|---|---|---|
| Arbor Node + IdeaTree | `src/coordinator/idea_tree.py` | Node 字段集、MUTABLE_FIELDS 白名单、json/md 双投影、constraints_block |
| AIDE Node + Journal | aideml 仓库 `aide/__init__.py`（Node/Journal/MetricValue） | 代码搜索节点的最小 schema、is_buggy 一等化 |
| KAPSO 测量记录 | 论文 arXiv:2601.21526 §evaluator contract | R(c)=(status,M,F,A) 四元组、随机 K rollout 聚合 |

### M1 Policy
| 看什么 | 学什么 |
|---|---|
| Arbor `src/coordinator/main.py` + `orchestrator.py` + `prompts.py` | 六步循环的实际编排；coordinator 工具面（`tools/tree_ops.py`） |
| Arbor `src/coordinator/context_prune.py` + `core/config_schema.py` ContextConfig | policy 运行时上下文压缩（window/compact_threshold/keep_recent） |
| AIRA-dojo solvers（greedy/mcts/evolutionary） | 策略作为可注册组件的写法 |

### M2 Operator
| 看什么 | 学什么 |
|---|---|
| AIRA-dojo operators | 纯函数签名 `op(llm, cfg, memory_op, task_desc, journal, *nodes, budget)`；0/1/2 arity |
| aideml `Agent` 的 draft/improve/debug | 三算子语义（复刻 AIDE 的忠实度基准） |
| OpenEvolve diff 变异 + `max_patch_resamples` | LLM diff 的重试与 marker 校验 |
| MARS 论文 arXiv:2602.02660（comparative reflective memory） | 差分归因 lesson 三元组的 prompt 结构 |

### M3 BudgetController
| 看什么 | 学什么 |
|---|---|
| Arbor `src/coordinator/convergence.py` | ConvergenceDetector：velocity/exhausted_parents/建议文本（一期最好的收敛检测参照） |
| MARS 论文（budget-aware MCTS） | 成本进入价值函数的方式与 w 敏感性 |
| dim03 §paired-seed funnel | 多 seed 统计验收流程（3 seeds 筛 → 10 seeds 验） |

### M4 Frontier
| 看什么 | 学什么 |
|---|---|
| Arbor `idea_tree.py`（同上） | 树 + 剪枝级联 + 白名单更新 |
| AutoMLGen 论文 arXiv:2510.08511（MCGS） | 骨架边/引用边双层图的语义（一期只需数据结构预留） |
| OpenEvolve `ProgramDatabase`（三期） | MAP-Elites + island + 迁移的工程实现 |
| LoongFlow 仓库 `boltzmann.py` / `base_memory.py`（三期） | EvolveMemory ABC（add/sample/get_best/diversity/checkpoint）≈ Frontier 接口原型 |

### M5 Memory
| 看什么 | 学什么 |
|---|---|
| ML-Master 2.0 论文 arXiv:2601.10402（HCC） | L1/L2/L3 语义与两个 promote 算子；L3 的 (embedding, wisdom) 键值 + cos>δ 预取 |
| ACE 论文（Agentic Context Engineering） | delta 增量合并 vs 整篇重写（context collapse 反例） |
| ML-Master 1.0 论文 arXiv:2506.16499 | scope=parent_siblings 的检索语义 |
| Arbor 论文 §4.2-4.3 | insight 上溯（叶子→方向→全局）的抽象机制 |

### M6 Knowledge（一期 stub，三期前再读）
| 看什么 | 学什么 |
|---|---|
| Arbor `docs/search.md` + `src/search_agent/` | 两车道（grounded_ideation/novelty_audit）隔离设计 |
| KAPSO 类型化知识图 | Principle/Implementation/Environment/Heuristic schema 与分级检索返回 |

### M7 Executor
| 看什么 | 学什么 |
|---|---|
| Arbor `src/executor/` + `coordinator/tools/executor_run.py` + `executor_io.py` + `worktree.py` | worktree 生命周期、executor 结构化回报、outcome 分类（scored/skipped/failed_to_run） |
| Arbor `tests/test_executor_io.py` / `test_executor_tamper.py` | executor 契约的测试写法（直接可借鉴） |
| AIBuildAI 论文 arXiv:2604.14455 | role 异质 + repo 作用域隔离（二期职能分工参照） |

### M8 Evaluator
| 看什么 | 学什么 |
|---|---|
| Arbor `docs/plugins.md` | eval_contract（metric_direction/eval_cmd/required_outputs/protected_paths）的插件化声明 |
| Arbor `src/coordinator/tools/protected.py` + `integrity.py` | 运行时 SHA-256 防篡改 |
| OpenEvolve Evaluator cascade（evaluate_stage1/2/3）+ artifacts 侧信道 | 级联评估与性价比带宽档 |
| ShinkaEvolve 评估返回（public/private metrics + text_feedback） | 反馈权限一等公民化 |

### M9 AdmissionGate
| 看什么 | 学什么 |
|---|---|
| Arbor 论文 Algorithm 1（Decide 步）+ `docs/how-it-works.md` §Evaluation discipline | margin gate、merge 唯一通道、score_split 字段 |
| dim08 §评测协议谱系 | 三层协议（dev/admission/final_audit）与 adaptive overfitting 争议的双方论据 |
| AIRA-dojo 论文 oracle 实验 | 终选独立模块的价值量化（9-13pp 上界、top-3 +10%） |

### X1 Audit / 工程韧性
| 看什么 | 学什么 |
|---|---|
| Arbor `src/coordinator/checkpoint.py` | 版本化 Checkpoint（GitState/InflightExecutor/CacheAnchor/messages） |
| Arbor `src/events/` | 事件总线 + subscribers 解耦 |
| Arbor `src/coordinator/contamination.py` | canary 扫描 + membership probe |

### 配置系统
| 看什么 | 学什么 |
|---|---|
| AIRA-dojo（Hydra + registry + ABC 四层：Task/Solver/Interpreter/Runner） | 配置组装的范式 |
| OpenEvolve（全 YAML + `${ENV}` 插值） | 新任务接入仅需 3 文件的体验设计 |
| Arbor `src/core/config*.py`（4 文件）+ `docs/configuration.md` | 五层覆盖链（setup→全局→项目→CLI→会话内） |

## 论文速查表（arXiv id）

AIDE 2502.13138 · AIRA-dojo 2507.02554 · ML-Master 2506.16499 · ML-Master 2.0 2601.10402 · MARS 2602.02660 · R&D-Agent 2505.14738 · AIBuildAI 2604.14455 · LoongFlow 2512.24077 · FM Agent 2510.26144 · AlphaEvolve（DeepMind 白皮书 2025）· GEPA 2507.19457 · KAPSO 2601.21526 · AiScientist-2026 2604.13018 · AutoMLGen 2510.08511 · InternAgent-1.5 2602.08990 · Arbor 2606.11926 · MLE-bench 2410.07095 · RE-Bench 2411.15114 · PostTrainBench（见 dim03 引用）· Reflexion 2303.11366 · Generative Agents 2304.03442
