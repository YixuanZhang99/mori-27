# CODE-BORROWING.md — 开源代码借鉴指南（给开发 agent）

> 目的：框架剩余开发**不要再 from scratch**。下面是 15+ 个已深度调研的开源仓库，标注了每个仓库里"哪个文件值得搬进我们的哪个模块"。
> 用法：统一浅克隆到 `refs/` 目录；实现某模块前先读对应行。借鉴方式分三档：**抄结构**（读懂后按我们的 Protocol 重写）、**vendor**（直接拷贝源码进 `vendor/` 并保留 license 头）、**adapter**（保留其仓库为依赖，写薄适配层）。
> ⚠️ License 红线：vendor 前必须核对各仓库 LICENSE（多数 MIT/Apache-2.0 可 vendor；**OpenRSI 论文为 CC BY-NC 4.0，代码 license 需单独确认，确认前只许"抄结构"**）。凡 vendor 的代码在文件头注明来源 repo + commit hash。

## 0. 克隆清单（一条命令）

```bash
mkdir -p refs && cd refs
for r in \
  https://github.com/WecoAI/aideml \
  https://github.com/RUC-NLPIR/Arbor \
  https://github.com/algorithmicsuperintelligence/openevolve \
  https://github.com/SakanaAI/ShinkaEvolve \
  https://github.com/jennyzzt/dgm \
  https://github.com/FrontisAI/OpenRSI \
  https://github.com/lbx154/Argus \
  https://github.com/hkgai-official/Moss \
  https://github.com/alphaXiv/openresearch-cli \
  https://github.com/PrimeIntellect-ai/prime-agent \
  https://github.com/junnie00/EvolveNet \
  https://github.com/google-deepmind/funsearch \
  https://github.com/gepa-ai/gepa \
  https://github.com/SakanaAI/AI-Scientist \
  https://github.com/microsoft/RD-Agent \
  https://github.com/Gen-Verse/PAST-Bench \
  https://github.com/endless-frontier/BigBang-v1 ; do
  git clone --depth 1 "$r" || echo "FAIL: $r"
done
# AIRA-dojo：仓库组织路径以论文 arXiv:2507.02554 为准，克隆前先确认
```

---

## 1. 按框架模块的借鉴清单

### core/types.py + M4 Frontier（搜索状态）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **aideml**（AIDE 官方） | `aide/__init__.py`（Node/Journal/MetricValue） | 代码搜索节点最小 schema、is_buggy 一等化。已实现 AIDE 复刻，但作为回归参照保留 | 抄结构 |
| **RUC-NLPIR/Arbor** | `src/coordinator/idea_tree.py` | Node 字段集、MUTABLE_FIELDS 白名单、json/md 双投影、剪枝级联——我们 M4 树的直接蓝本 | 抄结构 |
| **openevolve** | `openevolve/database.py`（ProgramDatabase） | MAP-Elites×岛屿的完整工程实现、`_sample_parent`/`_sample_inspirations`/岛迁移、checkpoint/resume 的 DB 快照合并。我们 M3 阶段进化拓扑的直接蓝本 | 抄结构 |
| **jennyzzt/dgm** | archive 相关源码（`dgm/` 目录） | 档案树 + stepping stones 语义 + "功能性存活门"（可编译+保留编辑能力才准入） | 抄结构 |
| **LoongFlow**（见 refs 或 arXiv:2512.24077） | `boltzmann.py` / `base_memory.py` | EvolveMemory ABC（add/sample/get_best/diversity/checkpoint）≈ 我们 M4 Protocol 的原型 | 抄结构 |

### M2 Operator（算子）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **AIRA-dojo** | operators 目录 | **纯函数算子签名** `op(llm, cfg, memory_op, task_desc, journal, *nodes, budget)`、0/1/2 arity——我们 M2 Protocol 的直接模板 | 抄结构 |
| **FrontisAI/OpenRSI** | 四算子实现（Draft/Improve/Debug/Crossover）+ 父采样 F(p)（reward×子代方差×稀少度） | 四算子语义的最完备开源实现；F(p) 公式可直接进 M1 | **抄结构**（license 确认前勿 vendor） |
| **openevolve** | diff 变异 + `max_patch_resamples` + marker 校验 | LLM diff patch 的重试与校验工程细节 | 抄结构 |
| **SakanaAI/ShinkaEvolve** | `shinka/edit/` patch 应用器 + `patch_type_probs` | diff/full rewrite 概率混合（[0.6,0.3,0.1]）的实战配比 | 抄结构 |
| **junnie00/EvolveNet** | 服务器端聚合器（scope 分类 global/home/reject + compose + revise） | **merge/aggregate 算子**的唯一开源实现：输入 = delta + per-item 翻转证据（G4.3 的直接蓝本） | 抄结构 |

### M3 BudgetController（预算与收敛）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **Arbor** | `src/coordinator/convergence.py` | ConvergenceDetector（velocity/exhausted_parents/建议文本）——收敛检测的最近参照 | 抄结构 |
| **hkgai-official/Moss** | `host-daemon/src/cli/moss_capability/evolution.md` + 实现 | **三档预算包**（shallow/standard/deep × max_iter/plan_rounds/retries/trials/plateau 五旋钮联动缩放）——比单旋钮更可用，直接抄档位表 | 抄结构（Apache-2.0） |
| **openevolve** | cascade 配置（`cascade_thresholds` 0.5/0.75/0.9） | 级联评估阈值"相对当前最优自动收紧"的早停语义 | 抄结构 |
| **AIDE² 博客**（无代码，weco.ai/blog/first-evidence-of-recursive-self-improvement） | §The inner-loop evaluation | 固定美元预算约束 + token 省下再投资于搜索步数的预算再配置思想——写进 M3 设计注释 | 读 |

### M5 Memory（记忆分层）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **PrimeIntellect-ai/prime-agent**（MIT） | `/refine` 命令实现 + refinement 快照回滚 | **记忆变更的 AdmissionGate**：L2/L3 写入要小步、有证据、可回滚；"immutable base prompt + 可精化 supplemental 层"分层 | 抄结构/vendor |
| **jennyzzt/dgm** | 自我诊断日志读取 | "读自己的评测日志作为诊断材料"的 context 组装方式 | 读 |
| ML-Master 2.0 / ACE / Arbor insight 上溯 | 见 REFERENCES.md §M5（论文为主） | L1/L2/L3 promote 算子、delta 合并 | 读 |

### M7 Executor（执行体）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **Arbor** | `src/executor/` + `coordinator/tools/executor_run.py` + `executor_io.py` + `worktree.py` + `tests/test_executor_io.py` / `test_executor_tamper.py` | worktree 生命周期、结构化回报、outcome 分类、**契约测试写法（直接可搬）** | 抄结构 + 抄测试 |
| **alphaXiv/openresearch-cli** | Rust 源码中 worktree/算力后端 launch 部分 | git worktree 作为状态载体的极简方案；SSH/Slurm/K8s/Modal 后端统一 launch 的接口形态（我们三期 ComputeFabric 参照）。注意 Rust 实现，**只抄接口形态** | 读 |
| **lbx154/Argus** | 四角色管线 + Reviewer 实现 + checkpoint/resume | 执行-评审制度性分离的运行时结构；"从最近验证位置续跑"的状态设计；后端可替换的 ExecutorSpec 抽象粒度 | 抄结构 |
| **hkgai-official/Moss** | `CodingAgentRunner` 4 方法接口 | 可插拔外部 coding-agent CLI（Claude Code/Codex/...）的最小接口——ExecutorSpec 抽象到"外部 agent CLI"粒度的实战样本 | 抄结构（Apache-2.0） |

### M8 Evaluator（评估）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **Arbor** | `docs/plugins.md` + `src/coordinator/tools/protected.py` + `integrity.py` | eval_contract YAML 插件声明 + SHA-256 运行时防篡改 | 抄结构 |
| **SakanaAI/ShinkaEvolve** | `shinka/utils/wrap_eval.py`（`run_shinka_eval`）+ 评估返回结构 | **public/private 指标 + text_feedback 的返回契约**（X3 可见性的直接蓝本）；多次运行聚合 + validate_fn 脚手架 | 抄结构 |
| **openevolve** | `openevolve/evaluator.py` | cascade stage1/2/3 + artifacts 侧信道（含安全过滤+字节上限） | 抄结构 |
| **gepa-ai/gepa** | adapter + reflective dataset 采集 | 轨迹级反馈（最高带宽档）的工程实现；`CandidateSelector/BatchSampler/StopperProtocol/AcceptanceCriterion` 全 Protocol DI 风格 | 抄结构 |
| **endless-frontier/BigBang-v1**（Apache-2.0） | 评测脚本（decontamination：查询拒绝/域过滤/答案隔离；manifest+MD5 钉死数据） | **评估卫生清单**——X3 的工程条目；完整轨迹 JSONL 记录格式 | 抄结构 |

### M9 AdmissionGate（准入）

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **Arbor** | 论文 Algorithm 1 + `idea_tree.py` score_split + `docs/how-it-works.md` | margin gate、merge 唯一通道——已实现 Arbor 复刻，作回归参照 | 回归参照 |
| **hkgai-official/Moss** | Verdict 阶段 + apply 授权 + 健康探针回滚 | **三段式准入**：自动收敛门 → 人授权门 → 运行时门+回滚 | 抄结构 |
| **lbx154/Argus** | Reviewer 判决 + "verified progress 才可 resume" | 准入与状态绑定：只有通过门的进度成为新 resume 位置 | 抄结构 |
| **prime-agent** | `/refine` 准入语义（small, evidence-backed, 快照回滚） | 对内自改准入的范式 | 抄结构 |
| **SEAL 论文**（arXiv:2607.24300，无代码） | Table 2 四条件 + Algorithm 1 | 密封外部审计门设计（外生/密封/1bit/保守非回归+回滚）——M3 阶段外生门的规格来源 | 读 |

### M1 Policy + X1/X3

| 来源 | 文件 | 借鉴什么 | 方式 |
|---|---|---|---|
| **Arbor** | `src/coordinator/main.py` + `orchestrator.py` + `checkpoint.py` + `contamination.py` + `src/events/` | 六步循环编排、版本化 Checkpoint、canary 扫描、事件总线 | 抄结构 |
| **SakanaAI/ShinkaEvolve** | `shinka/llm/bandit`（BanditBase: select_llm/update/update_cost/posterior/get_state/set_state） | **LLM 选择作为有状态可持久化的注入对象**——我们 ExecutorSpec.llm_policy 的模板 | 抄结构 |
| **ShinkaEvolve** | `shinka/core/async_runner.py` | proposal/eval/db 三池独立配额的异步流水线 | 抄结构 |
| **GEPA** | checkpoint/resume + adapter state | 进化搜索的可复现性设计 | 抄结构 |
| **Gen-Verse/PAST-Bench**（Apache-2.0） | `family.yaml` schema（episode_order/control_set/trigger_strength/false_positive_pattern/must_demonstrate） | 纵向记忆评测任务族的声明式 schema——我们设计自家回归评测时直接借用 | 抄结构 |

---

## 2. 按"剩余开发任务"排序的 Top-8 借鉴优先级

| 优先级 | 任务 | 主要借鉴来源 | 预估省时 |
|---|---|---|---|
| 1 | Arbor 测试与收尾 | Arbor 自身的 `tests/`（test_executor_io/tamper 等契约测试模式） | 直接决定测试质量 |
| 2 | M0 契约测试补强 | GEPA 的全 Protocol DI + aideml 的 Node/Journal 单测 | 高 |
| 3 | X3 可见性 + public/private 指标 | **ShinkaEvolve `run_shinka_eval`** + BigBang-v1 评估卫生脚本 | 高（避免自造契约） |
| 4 | M3 预算档位化 | **Moss evolution.md 三档表** + openevolve cascade 阈值 | 中 |
| 5 | 记忆准入（L2/L3 写入门） | **prime-agent `/refine`** + 快照回滚 | 高 |
| 6 | M3 阶段：MAP-Elites/岛屿拓扑 | **openevolve ProgramDatabase**（最完整）+ ShinkaEvolve 三池异步 | 很高（两周以上工作量） |
| 7 | M3 阶段：merge/aggregate 算子 | **EvolveNet 聚合器** | 高 |
| 8 | M3.5：双层 loop recipe | **dgm archive** + AIDE² 博客（无代码，读思想） | 中 |

## 3. 反 from-scratch 纪律（写入给 Codex 的指令）

1. 实现任何模块前，先在本文件中找到对应行，读完来源代码并写 5 行"借鉴笔记"（来源文件、commit、借了什么、改了什么）到 PR 描述。
2. 若判断某来源不可借鉴（接口不合等），**必须在 PR 中说明理由**——不允许无声地 from scratch。
3. vendor 的代码放 `vendor/{repo名}/`，保留原 license 头，文件首行注明来源 URL + commit hash；license 不明的（OpenRSI）只抄结构。
4. 测试代码同样优先借鉴（Arbor/aideml 的契约测试模式），不重复发明测试夹具。
