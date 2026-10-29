# ZOO.md — Benchmark 适配器契约与 MLE-Bench Lite 接入指南

> zoo = 领域差异的唯一合法位置（CLAUDE.md 禁止事项 #6）。框架核心不许出现 benchmark 特殊分支。

## 1. 适配器契约（`core` 侧已冻结）

每个 benchmark 是一个目录，实现 `TaskAdapter` Protocol：

```python
class TaskAdapter(Protocol):
    name: str
    def setup(self, workspace: Workspace) -> None:
        """准备初始 artifact：代码、数据、评估脚本全部落进 workspace 并 git init。"""
    def eval_contract(self) -> EvalContract:
        """见 SPEC §10：metric_direction / eval_cmd / fidelity_levels / required_outputs / protected_paths。"""
    def initial_artifact(self) -> ArtifactRef:
        """初始 trunk 引用（对应 AO 形式化的 M0）。"""
    def provenance(self) -> ProvenanceDoc:
        """数据来源、版本 hash、协议来源、许可。"""
```

目录结构（arbor-zoo 四件套的升级）：
```
zoo/{benchmark}/
├── adapter.py        # TaskAdapter 实现
├── eval/             # 评估脚本（不可变，入 protected_paths）
├── assets/           # 初始代码/数据（或下载脚本 + hash 校验）
├── PROVENANCE.md     # 版本、hash、协议、许可
└── README.md         # 任务描述、指标方向、fidelity 档位说明
```

**EvalContract 填写纪律**：
- `fidelity_levels` 至少一档 `dev`；有 held-out 协议的 benchmark 必须声明 `admission` 与 `audit` 档（对应不同数据划分或种子集）
- `protected_paths` 必须覆盖：评估脚本、测试数据、ground truth
- 指标 key 带 split 前缀（`"dev/medal"`, `"admission/loss"`），与 EvalResult.metrics 对齐

## 2. MLE-Bench Lite 接入指南（P0）

### 2.1 基本情况
- 来源：OpenAI MLE-bench（arXiv:2410.07095），Kaggle 竞赛集合；Lite 为常用子集（**任务清单以官方 repo 当期版本为准，接入时锁定并记录 hash**；不同论文使用的子集口径有差异，复刻报告必须声明所用清单）。
- 官方协议要点：每任务给训练/测试数据与 sample submission；按 Kaggle 排行榜分位数发牌（bronze/silver/gold）；报告 valid submission / above median / any medal 等比率；官方资源档为单 GPU（Arbor 等系统按单 A100 + 官方时间预算执行）。
- 官方仓库含 grading 逻辑与 leaderboard；社区有 validation server 模式（不给 agent 直接返回 test 分数）与 transcript 审计惯例——**适配器必须默认隐藏 test 分数**。

### 2.2 接入步骤
1. **锁定任务清单**：从官方 repo 取当期 Lite list，写入 `PROVENANCE.md`（含 commit sha）。
2. **数据快照**：下载全部任务数据到 `assets/`（或提供带 hash 校验的下载脚本）；磁盘与许可检查。
3. **eval_contract**：
   - `metric_direction` 逐任务声明（各竞赛指标方向不一）
   - `eval_cmd`：产出 submission → 本地 grader（按官方 grading 移植）→ 解析分数
   - `fidelity_levels`：`dev`（本地验证划分，供搜索自由使用）；**`audit`**（官方 medal 判定，仅终评调用）；MLE-Bench 原生只有两层，若需三层协议用"本地 dev / 官方 validation server / 最终 grading"映射
   - `required_outputs`：官方要求的 submission 路径
4. **任务切分策略**：与对标系统保持一致（AIDE/AIRA/Arbor 均在全部 Lite 任务上报告比率），不要自行挑子集。
5. **环境固定**：按 REPLICATION.md §1 执行（评估脚本 hash、数据 hash、种子声明）。
6. **冒烟测试**：随机 3 个任务跑 `recipes/aide.yaml` 短预算（2 cycles），确认 valid submission 流程贯通。

### 2.3 陷阱清单
- ❌ agent 直接读到 test 分数或 leaderboard 阈值文件 → 评估脚本放 protected_paths 且工作区不可见
- ❌ 不同论文的"Lite"口径不同 → 报告中永远附任务清单 hash
- ❌ 单 seed 报告 → medal 判定在边界任务上波动大，≥3 seeds
- ❌ 忽略 valid submission 率 → 低 valid 率会虚高 medal 率（分母变小），两个指标必须同时报

## 3. 后续 benchmark 接入要点

| Benchmark | 优先级 | 关键差异点 | 接入要点 |
|---|---|---|---|
| NanoGPT-Bench | P0 | 指标=达到目标 loss 的步数；多 seed paired | fidelity 级联天然场景：短训档位→完整档位；paired-seed 验收 |
| llm-speedrun（nanoGPT speedrun 系） | P0 | 墙钟预算内 loss；社区有统计验收惯例 | resume_from 必备；记录每 run 种子方差 |
| karpathy/autoresearch | P1 | 固定时间预算 final loss；Arbor AO 任务之一 | 直接对齐 Arbor 论文任务定义，便于与其 Table 2 对照 |
| MLGym-Bench | P1 | 任务多样性强 | 验证泛化；注意其评估器形态差异 |
| FML-Bench | P1 | 接入前先核实其官方协议与维护状态 | 协议核实记录进 PROVENANCE.md |

## 4. DomainPlugin（可选增强层）

当同一 benchmark 被反复使用时，把 eval_contract + protected_paths + 预算包 + 领域 prompt 注入打包为 plugin（Arbor 插件模式）：
```yaml
# plugins/mle_kaggle.yaml
name: mle_kaggle
eval_contract: {...}
protected_paths: ["eval/**", "data/test/**"]
profiles:
  quick:  { max_cycles: 5,  executor_timeout: 3600 }
  full:   { max_cycles: 24, executor_timeout: 86400 }
prompt_injections: {...}
```
zoo 适配器回答"这个 benchmark 是什么"，plugin 回答"这类任务怎么跑"——两者正交。

## 5. RE-Bench 时间预算对照接入（B3，仅适配机制）

- 选择 METR RE-Bench，锁定官方 revision `a0cc6d4a91b20f84ebef505d5c72358f88b3b389`；上游已标记 deprecated，禁止 drifting checkout。
- `zoo/re_bench/assets/` 固定 7 任务 suite 和 36 个官方文件 hash；不复制 official solution 或受保护答案。
- 真实执行依赖 Vivaria 与 `metr.task_protected_scoring`。`REBenchAdapter.grade_score_log()` 只调用官方任务模块的 `TaskFamily.aggregate_scores`，不自造替代指标。
- agent 工作区仅含 description 与 task provenance；真实 Vivaria score log 和聚合分数只进入 run-level audit，dev 反馈不含 raw score。
- `ScoreRunRecord` 与 `compare_scores_same_budget` 用于通用数值评分，不挪用 MLE medal 字段。只有同 snapshot、同 backbone、同声明预算、相同任务及 seed 集合、至少 3 seeds 的完整 7 任务双臂矩阵才能比较。
- 每个 agent 使用独立进程组并执行 wallclock timeout。超时后只有官方 manifest 明确 `score_on_usage_limits: true` 且已有真实 score log 才允许评分；实际墙钟原样保留，其他成本超支不豁免。
- 缺 log、空／畸形 log、非有限分数、文件篡改和不完整矩阵均失败关闭。协议夹具只验证机制，不是 RE-Bench 外部成绩；B3 仍需真实 campaign。
