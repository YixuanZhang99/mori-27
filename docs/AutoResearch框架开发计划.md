# AutoResearch 框架开发计划（v0.1）

> 目标产物：可插拔、可灵活配置的 AutoOptimization 框架（类比 vLLM/SGLang 在推理 infra、VeRL 在 RLHF 的生态位）。
> 核心叙事：**"一个框架，配置复刻所有经典系统；一套接口，组合出没人做过的新系统。"**
> 依据：《AutoResearch模块化统一抽象.md》（同目录）（九模块契约）+ `../research/dim00-08/` 九个机制单元调研。
> 团队：3+ 人；首发验证场景：MLE-Bench 类便宜 benchmark。日期：2026-08-05

---

## 1. 产品定位与差异化（写进 README 的三句话）

1. **复刻即验证**：AIDE / Arbor / OpenEvolve / LoongFlow / R&D-Agent 都是本框架的一份预设配置（recipe）。复刻其报告结果是框架正确性的验收标准。
2. **接口是超集**：Evaluator 分层返回类型、三层 Admission、分级 Memory 后端、Frontier 三旋钮——经典系统各自写死的部分，在这里全部是配置项。
3. **组合即创新**：跨 run 语义记忆（L3）、三层准入协议、语义 QD descriptor 等已被调研验证的空白组合，开箱即用。

区别于 Arbor（写死树+LLM cycles）、OpenEvolve（无语义记忆/准入）、AIRA-dojo（无持久记忆/准入/知识层）——调研已证实三者交集无人占据。

---

## 2. 架构决策（ADR，开发前冻结）

| # | 决策 | 结论 | 理由 |
|---|---|---|---|
| ADR-1 | 语言/运行时 | Python 3.11+，asyncio 一等公民 | 生态（所有对标系统均 Python）；executor/evaluator 并行需原生异步（FM Agent/OpenEvolve 验证） |
| ADR-2 | 配置系统 | Pydantic schema + YAML 组合（ Hydra 风格 defaults 组），recipe = 命名预设 | AIRA-dojo（Hydra）与 OpenEvolve（全 YAML）共同验证；类型安全优于纯 Hydra |
| ADR-3 | 扩展机制 | 全部模块 registry 化（`@register("policy", "mcts")`），entry_points 支持第三方包 | "一行配置切换"的叙事依赖于此；AIRA registry + OpenEvolve 注入对象先例 |
| ADR-4 | 隔离执行 | 一期 git worktree（无容器依赖）；二期可选 Docker backend | Arbor/KAPSO 验证 worktree 成本最低且 provenance 免费；容器规模化才刚需 |
| ADR-5 | 状态存储 | git DAG = artifact lineage（branch 即引用）+ SQLite/JSON = 索引层（Frontier/Memory） | KAPSO 验证"无需另建状态库"；索引层支持多投影 |
| ADR-6 | 数据类型 | 冻结 dataclass/pydantic：`Candidate / ExecutorSpec / EvalRequest / EvalResult / EvidenceRecord / StateMutation` | 接口闭合性（reviewer Maj-1 教训）：模块间只传这六个类型 |
| ADR-7 | LLM 抽象 | provider 接口（anthropic/openai/openai-compatible/litellm），支持 per-role 模型配置与 Bandit 选择器（二期） | Arbor/ShinkaEvolve 先例；coordinator 与 executor 可用不同模型是常见需求 |
| ADR-8 | 事件系统 | event bus + subscriber（日志/dashboard/审计/记忆钩子都挂这里） | Arbor 验证；记忆后端的 checkpoint 钩子订阅此总线 |
| ADR-9 | monorepo 结构 | `core`（框架）/ `recipes`（预设配置）/ `zoo`（benchmark 适配器）/ `cli` 四包分离 | 复刻叙事要求 recipes 是一等公民；zoo 借鉴 arbor-zoo 四件套 |
| ADR-10 | 一期不做 | 容器隔离、Web UI、MCTS/evo 高级拓扑实现、学习型 π_op、分布式（Ray） | 调研证据：算子与记忆到位前拓扑无差异；先证明框架语义正确 |

---

## 3. 仓库结构草案

```
autoresearch-fw/
├── core/
│   ├── types.py            # 六大数据类型（ADR-6）
│   ├── registry.py         # 模块注册表
│   ├── config/             # pydantic schema + YAML 组合 + recipe 解析
│   ├── policy/             # M1: llm_cycles / best_first / mcts(二期) / trivial
│   ├── operators/          # M2: draft/debug/improve/crossover/hypothesis_refine/comparative_reflect
│   ├── budget/             # M3: hard caps / convergence(rule-based) / fidelity ladder
│   ├── frontier/           # M4: tree / dag(skeleton+ref edges) / map_elites / island
│   ├── memory/             # M5: L1/L2/L3 统一后端 + promote(delta) + retrieve(scope)
│   ├── knowledge/          # M6: 两车道检索接口（一期 stub，二期实现）
│   ├── executor/           # M7: worktree 隔离 + 修复循环 + 结构化回报
│   ├── evaluator/          # M8: 分层契约 + cascade + paired-seed
│   ├── admission/          # M9: 三层协议 + margin + call_budget + 三元组报告
│   ├── audit/              # X1: git lineage / checkpoint / protected hash / events
│   └── llm/                # ADR-7
├── recipes/                # 复刻预设（框架正确性的验收标准）
│   ├── aide.yaml / aira_mcts.yaml / arbor.yaml / openevolve.yaml
│   ├── loongflow.yaml / rd_agent.yaml / gepa.yaml(二期)
│   └── README.md           # 每个 recipe 复刻了谁、差异点、复刻验证结果
├── zoo/                    # benchmark 适配器（四件套契约）
│   ├── _template/          # task.py / eval.py / solution.py / PROVENANCE.md
│   ├── mle_bench_lite/  nanogpt_bench/  llm_speedrun/  mlgym/  karpathy_autoresearch/
├── cli/                    # run / replay / tree / report / benchmark 子命令
└── docs/
```

---

## 4. 里程碑（建议 10-12 周到 v0.3 可发布态）

### M0 设计冻结（Week 1-2）
- 六大数据类型 + 九模块 Protocol 定义，全员评审签字
- 复刻验证方案：选定 2 个一期复刻目标（建议 **AIDE**（最便宜，算子语义最简）+ **Arbor**（语义内核最近））
- zoo 适配器契约冻结（四件套 + eval_contract schema）
- **出口标准**：一份 `types.py + protocols.py` 骨架，3 人各自能口述模块间数据流

### M1 语义内核跑通（Week 3-5）——"框架版 AIDE"
- 实现：M1(best_first) + M2(draft/debug/improve) + M4(tree) + M5(L1+L2, scope=parent_siblings) + M7(worktree) + M8(基础契约) + M9(dev-only) + X1(checkpoint/events)
- 适配：mle_bench_lite（参考 AIRA-dojo 的环境固定方法）
- **出口标准**：`recipes/aide.yaml` 复刻 AIDE 报告水平（±5pp 内）；checkpoint 中断可 resume

### M2 差异化机制（Week 6-8）——"框架版 Arbor + 超越"
- 实现：M1(llm_cycles) + M2(hypothesis_refine, comparative_reflect) + M4(引用边) + M5(L2 promote delta + insight 上溯) + M9(三层 admission + margin gate + call_budget) + M8(fidelity cascade + paired-seed)
- 适配：nanogpt_bench、llm_speedrun（成本敏感场景，验证 fidelity 级联价值）
- **出口标准**：`recipes/arbor.yaml` 复刻 Arbor 关键行为（merge gate 生效、insight 上溯可见）；三层协议下 dev/test gap 报告自动生成

### M3 生态位与发布（Week 9-12）
- 实现：M4(MAP-Elites/island + Boltzmann 压力) + M5(L3 跨 run 层) + 并行 executor pool 配额
- 复刻：`recipes/openevolve.yaml`（验证进化系覆盖）
- 组合实验（论文素材）：在同一 benchmark 上扫"记忆后端 × 拓扑 × 准入"的因子网格——**这就是 AIRA-dojo 式控制实验，但维度更大，直接产出论文表 1**
- 文档 + 2-3 个 tutorial + benchmark 榜单
- **出口标准**：开源发布 v0.3；一篇技术报告（"统一框架 + 复刻验证 + 组合网格实验"）

---

## 5. 团队分工建议（3+1 模式）

| 角色 | 负责模块 | 关键交付 |
|---|---|---|
| 负责人 A（架构） | types/registry/config + M1 policy + M2 operators | M0 冻结文档；recipe 解析器 |
| B（数据面） | M4 frontier + M5 memory + M6 knowledge(stub) | 统一记忆后端；树/DAG/MAP-Elites 三种准入结构 |
| C（执行面） | M7 executor + M8 evaluator + M9 admission + X1 audit | worktree 池；fidelity 级联；三层 gate；checkpoint/resume |
| +1（zoo/评测，可兼职） | zoo 适配器 + 复刻验证 + benchmark 榜单 | 每个里程碑的复刻报告 |

协作纪律：**任何跨模块调用只能传六大数据类型**；新模块先写 Protocol 再写实现；每个 recipe 配一份"复刻验证报告"（目标系统报告值 vs 本框架复现值 vs 差异分析）。

---

## 6. Benchmark 接入策略

统一适配器契约（arbor-zoo 四件套的升级版）：
```python
class TaskAdapter(Protocol):
    def setup(self, workspace) -> None: ...
    def eval_contract(self) -> EvalContract: ...   # metric_direction/eval_cmd/fidelity 档位/protected_paths
    def initial_artifact(self) -> ArtifactRef: ...
    def provenance(self) -> ProvenanceDoc: ...
```

| Benchmark | 优先级 | 接入要点 | 验证目标 |
|---|---|---|---|
| MLE-Bench Lite | P0 | 参考 AIRA-dojo 环境固定；validation server 模式 | 复刻 AIDE/Arbor 数字 |
| NanoGPT-Bench / llm-speedrun | P0 | 多 seed paired 评估；fidelity 级联天然场景 | 验证 M8/M9 差异化 |
| karpathy/autoresearch | P1 | 固定时间预算 final loss | 复刻 Arbor AO 任务之一 |
| MLGym-Bench | P1 | 任务多样性 | 泛化性证据 |
| FML-Bench | P1 | 确认其评估协议后接入 | 泛化性证据 |

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 复刻不达标（数字对不上）→ 叙事破产 | M0 就选"最便宜可复刻"目标；复刻报告公开差异分析（backbone/环境差），诚实比精确重要；AIRA-dojo 的 +10.7 点环境固定先例说明差异可解释 |
| 接口过度设计，一期难产 | M1 只允许 best_first + tree + dev-only gate；超集接口但最小实现 |
| 抽象泄漏（某系统机制塞不进九模块） | 维护"无家可归机制清单"（reviewer 已发现 2 个：coordinator 上下文压缩、report 生成），每里程碑评审是否升格为模块 |
| 低样本 regime 机制失效（M9 velocity 等） | 已内置规则式降级路径（见统一抽象 M3）；NanoGPT-Bench 场景样本量足够，无需担心 |
| 与 Arbor 官方演进撞车 | 差异化锚定：跨 run L3 记忆 + 三层准入 + 进化系 frontier——这三个 Arbor roadmap 短期内都不会有；保持兼容其 zoo 任务包格式 |

---

## 8. 第一周行动清单

1. 全员通读《AutoResearch模块化统一抽象.md》（同目录）§3-§6 + dim01/dim06（接口证据最密的两个单元）
2. 起草 `types.py` 与九个 Protocol（0.5 天，A 主笔，全员评审 1 天）
3. 克隆 Arbor 与 OpenEvolve 跑通各自 quickstart（验证理解 + 环境摸底）
4. 确定复刻目标的"忠实度标准"：哪些机制必须复刻（如 AIDE 三算子语义）、哪些允许偏离（如具体 prompt）
5. 建仓库，落地 ADR-2/3/5/8 的基础设施（registry、config、git 层、event bus）
