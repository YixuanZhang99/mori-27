# Dim 00: Arbor 开源仓库（RUC-NLPIR/Arbor）工程实现分析

> 主线调研，2026-08-05，基于仓库 clone 实读（src/ + docs/ + skills/ + arbor-zoo/）。
> 意义：Arbor 是目前已开源的、最接近"可配置 AutoResearch 框架"形态的实现，其工程划分是直接参照系。

## 1. 仓库顶层结构

```
src/
├── cli/            # CLI、intake 对话、replay、dashboard、tree_export
├── coordinator/    # 控制面：main/orchestrator/idea_tree/convergence/contamination/checkpoint/hitl/context_prune
│   └── tools/      # coordinator 的工具：executor_run/executor_io/tree_ops/git_ops/worktree/protected/integrity/research_ctx/search_ctx/record_finding/ask_user
├── core/           # 数据面与底座：agent/config(4文件)/context/experiment(GitManager+ExperimentTracker)/git_artifacts/skill_registry
│   ├── llm/        # LLM provider 抽象：base/claude/openai_compat/openai_responses/litellm_provider/oauth
│   └── tools/      # 基础工具：bash/executor_tool...
├── events/         # 事件总线 + subscribers（dashboard、日志等解耦）
├── executor/       # 执行面
├── mcp/            # MCP server（把 Arbor 能力暴露给外部 agent）
├── plugins/        # 领域插件加载
├── report/         # REPORT.md 生成
├── search_agent/   # 外部知识搜索（grounded ideation / novelty audit 两车道）
├── skills/         # skill 加载
├── webui/          # 只读监控
└── zoo/            # arbor-zoo：任务包（task.py/solution.py/eval.py/PROVENANCE.md 四件套 + _template）
skills/             # Claude-agent 风格的 agent 定义：coordinator/executor/ideate/search/merge-eval/orchestrator/setup-intake/resume-report/tools/plugins-hitl-budget
```

## 2. 关键设计事实（对框架设计的直接启示）

### 2.1 状态核心：IdeaTree / Node schema（src/coordinator/idea_tree.py）
Node 字段：`id, parent_id, children_ids, depth, hypothesis, status(pending/running/done/merged/pruned...), insight, result, score, score_split(dev|test), test_score(merge 时写入), code_ref(git branch), related_work(novelty audit), grounding(ideation 引用), eval_status(scored|skipped|failed_to_run), stop_reason, attempt`
- **MUTABLE_FIELDS 白名单**：所有状态变更集中在受控字段集——"LLM policy 决策，受控 mutation 落树"的论文主张在代码里就是这个白名单。
- IdeaTree 接口：`get_pending_leaves / get_path_to_root / get_best_done_node / is_improvement / add_node / update_node / prune_node(级联) / next_child_id / save(json+md 双写, atomic) / get_constraints_block / to_compact_summary`
- 树同时序列化为 JSON（程序态）和 Markdown（人读 + LLM 读）——**同一状态的多种投影**。

### 2.2 配置面（src/core/config_schema.py）
- LLMConfig：provider(auto)/model/api_key/base_url/reasoning_effort/thinking_budget/max_tokens/重试参数
- TimeoutConfig：executor 172800s、eval 86400s、time_budget、heartbeat 30s、stall 检测 1800s
- ContextConfig：window 200k、compact_threshold 0.8
- UIConfig：interaction_mode(auto|direction|review|collaborative)、各 gate 超时
- 配置来源五层：setup 向导 → 全局 config → 项目 config 文件 → CLI flags → 会话内 slash 命令（后者覆盖前者）

### 2.3 领域插件（docs/plugins.md）——"一次 YAML 切换到新领域"
```yaml
name: my_domain
eval_contract:
  metric_direction: maximize
  eval_cmd: "bash {cwd}/eval.sh"
  # 可选：submission_path / contamination block
protected_paths: [...]      # 运行时 SHA-256 manifest 防篡改，不止 merge 时检查
required_outputs: [...]
profiles:                   # 预算包：max_cycles/max_tree_depth/executor_timeout/time_budget
config_overrides: {...}
# prompt injections：领域知识注入 agent system prompt
```
**Plugin（优化什么）与 Skill（怎么推理）正交**——这是 Arbor 最重要的框架级抽象。

### 2.4 评估纪律
- dev 信号自由迭代；held-out merge gate **带 margin**（可配置阈值），不是简单 >。
- `score_split` 字段显式记录分数来自 dev 还是 test；`test_score` 仅在 merge 时写。

### 2.5 收敛与停止（src/coordinator/convergence.py）
ConvergenceDetector：`on_experiment_complete` 触发；信号含 consecutive no-improvement、改进速度 velocity、exhausted parents（子节点全耗尽的父方向）；输出 level + reason + suggestions；可写 stop signal。——**预算控制不止"轮数上限"，还有方向级耗尽检测**。

### 2.6 外部知识两车道（docs/search.md + src/search_agent/）
- Grounded ideation（IDEATE 时搜文献辅助想点子，落 `node.grounding`）与 Novelty audit（实验成功后查 prior art，落 `node.related_work`）**独立检索、互不共享抓取文本**，默认关闭（保 benchmark 公平）。
- 搜索在隔离 context 执行，只回 compact digest；未实际打开的来源被丢弃（引用诚实性）。

### 2.7 工程韧性
- Checkpoint（版本化，含 GitState/InflightExecutor/CacheAnchor/messages）→ 可 resume、replay、tree export
- events 总线 + subscribers：dashboard/日志/UI 与主循环解耦
- MCP server：框架能力可被外部 agent 调用
- executor outcome 分类：`scored / skipped / failed_to_run`——失败是一等公民的状态而非异常
- arbor-zoo 任务包四件套 `task.py / solution.py / eval.py / PROVENANCE.md` + `_template`：benchmark 即代码包

## 3. 对我们框架设计的启示

1. **控制面/数据面分离已被验证**：coordinator（策略）只通过 tools 变更 IdeaTree（MUTABLE_FIELDS 白名单），executor 在 worktree 内自治。
2. **三个正交的配置轴**：Provider/LLM（用谁）× Plugin（优化什么：eval_contract+protected+budget）× Skill（怎么想：单步推理质量）。再加 InteractionMode（人参与多深）。
3. **状态的多投影**：同一 IdeaTree → JSON（程序）/ Markdown compact summary（LLM 上下文）/ 树形文本（人）/ constraints block（负约束）。状态模块接口应按"投影"设计而非按"存储"设计。
4. **评估协议一等公民**：score_split、test_score、margin gate、protected_paths hash、contamination probe 都是协议层的具象化。
5. **Arbor 未模块化的地方（=我们的差异化空间）**：搜索拓扑写死为单棵树（无 population/DAG）；Select 由 coordinator LLM 隐式完成（无 UCT/Boltzmann 等可插拔 policy）；无跨 run 记忆层；无 multi-fidelity 评估级联；executor 固定单假设（无职能分工角色的配置化）。
