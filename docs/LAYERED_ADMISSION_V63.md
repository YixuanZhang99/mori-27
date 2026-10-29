# S4 三层准入与独立终审（v63）

本页保留 S4/v63 引入的协议与当时边界；后续 S5/v64 运行版本为 `composed-v5`，多层物理预算和最新恢复限制见 [S5 指南](HIERARCHICAL_BUDGET_V64.md)。

本增量在同一 `Framework.from_profile()` 配置入口增加 `admission=layered`，运行版本为 `composed-v4`。它把 dev 探索、admission 晋升与 final_audit 报告分开，保留 [S1 组装](COMPOSED_RUNTIME.md)、[S2 证据契约](EVALUATION_CONTRACT_V61.md)与 [S3 经验回流](CONTEXT_FEEDBACK_V62.md)的行为。五阶段中，分层预算仍属于 S5；[逐项清单](ABSTRACTION_ALIGNMENT.md)中的旧缺口不会因增加三层协议自动关闭。

默认 `composed_prompt` 的 `admission=metric` 仍是显式 dev-only 兼容配置。三层必须选用原生 domain 并显式启用；不将默认配置描述为已经完成设计文档的“三层默认协议”。本页描述实现与边界，当前提交是否通过 Mac/Linux 检查以逐项清单和同 SHA 的 CI 证据为准。

## 启用方式

以下片段接在已配置 provider、原生 domain、LoopConfig 的应用中。`profile` 是 `composed_prompt` 配置字典，`domain` 是满足下节契约的原生对象，不是旧 PromptEvaluator：

```python
profile["domain"] = {"name": "native"}
profile["admission"] = {
    "name": "layered",
    "options": {
        "metric": "dev/score",
        "direction": "maximize",
        "trigger": {"min_dev_gain": 0.02},
        "margin": 0.01,
        "call_budget": 20,
        "layers": ["dev", "admission", "final_audit"],
        "admission_fidelity": "admission",
        "admission_seeds": [11, 29],
        "final_fidelity": "final_audit",
        "final_seeds": [41, 67],
        "selection": "best",
        "monotonicity": True,
        "final_audit": {"isolation": True, "runs": 1},
        "integrity_hooks": ["hash_check", "canary_scan", "source_blocklist"],
        "blocked_patterns": ["FINAL_SECRET_CANARY"],
        "blocked_sources": ["file:///restricted/final-answer.txt"],
    },
}
framework = Framework.from_profile(profile, llm, domain, config, workdir)
result = framework.evolve(task)
report = result["reporting"]
```

metric 与 direction 必须与 frontier 的探索目标一致。默认 metric 为 `dev/score`，这是指标键名，不能用于推断数据属于 dev；实际 split 由严格身份绑定决定。可执行的离线 domain 示例见 `m0/tests/test_composed_admission.py` 中 `LayeredDomain`，它使用合成数据验证协议，不代表真实隔离数据集的质量。

## 原生 domain 与数据权限

domain 实现既有的 `validate_request(request)`、`evaluate(proposal, request)`、`evaluator_version`、dev `evaluation_context`，并增加：

```python
def evaluation_context_for(self, request):
    return self.contexts[request.split_id]
```

该方法接收完整 `EvalRequest`。必须支持启用的 split/fidelity/seed 请求，并为 dev、admission、final_audit 返回非空且互不相同的内容上下文摘要。两层配置只要求 dev/admission。运行前冻结这些身份，每次调用及恢复重新校验；仅修改 split 名但复用同一内容摘要会在模型调用前拒绝。

每份结果必须由 producer 绑定候选、产物、请求、evaluator version、该 split 的内容上下文、fidelity 和 seed，并声明真实计量覆盖。候选与 incumbent 在 admission 使用同一请求和 seed 集合；已有结果只能按完整身份缓存复用。摘要格式或不同字符串本身不能证明外部文件真的隔离，domain 仍负责声明和校验实际内容。框架没有给同进程恶意插件提供内存沙箱。

`legacy_prompt` 只有 dev 能力，不能悄悄把三层请求降级成重复 dev 调用。S4 不自动迁移旧 domain；不支持的请求在付费调用前失败。

## 触发、比较与调用次数

每个候选先执行 dev。首个成功候选可触发 admission；之后须比当前 gate-selected 候选的 dev 结果严格改善，并达到 `min_dev_gain`。maximize 使用 candidate − incumbent，minimize 相反；`min_dev_gain=0` 仍不放行相等分数。阈值是绝对差值，不是百分比或统计显著性。

触发后单独评估 admission。首次缺少可复用基线时，基线和候选都算调用；计划会先确认整个缺失调用组能放进 call_budget，避免只执行一半的比较。成功候选只有在 admission 改善严格大于 `margin` 才替换 incumbent。失败结果不晋升，未触发或无预算结果保留拒绝原因。dev 上的最高分不因此成为最后发布的候选。

`call_budget` 默认 20，硬限制 admission 已开始调用次数，包含基线和失败调用；缓存命中不重复计数。计数在调用前持久化，未知失败不能免费重试。final_audit 的一回合限制独立于 admission call_budget，但仍必须有可用物理预算。

每次 admission/final 调用分别申请全局 token 预扣；一组 admission 调用的预扣需全部成功后才开始，失败时释放尚未开始的预扣。已知用量按真实 token 结算；业务身份错误仍不能逃避已知费用，未知计量不能假定为零。当前使用独立 `reeval` 账户和 `LoopConfig.intent_cost` 估算，尚无方向/候选层级、GPU·h 或时间硬顶；这部分是 S5。

## 回执与终审

`LayeredDecision` 的回执 hash 绑定规则、dev/admission 的受限比较视图和结果。`validate_layered_receipt()` 必须取得实际 dev/admission 记录，核对身份、投影与摘要，并重算 dev trigger 和 admission margin；伪造分数后重新计算 hash 不能代替原始记录。费用、完整私有契约和私有反馈不属于判定视图。完整证据另存 journal，用于成本审计和恢复。

结束探索时，先冻结 gate-selected 候选，再对其执行最多一次 final_audit。结果不能回写 incumbent、frontier、policy、operator、memory 或 knowledge；final 更高或更低都不重开搜索。报告分别包含：

| 字段 | 含义 |
| --- | --- |
| `dev_best` | 所观察成功 dev 结果中的最佳候选 |
| `gate_selected` | 通过 admission 规则选出的候选 |
| `final_audit` | 冻结候选的独立终审状态、受限结果和调用数 |
| `gate_calls` / `gate_call_budget` | 已开始 admission 次数与硬上限 |

`layers=["dev", "admission"]` 会明确报告 final disabled。无候选、预算不足或评估失败也以状态/原因区分，不生成伪成功终审。`best_score` 仍是 gate-selected 候选的 dev 分数，不能当作 admission 或 final 成绩；应读取三元组报告。

## 防泄漏与恢复边界

必需的 `hash_check` 对应证据/产物/请求身份校验。可选 `canary_scan` 按配置的字面字符串扫描任务、生成上下文和候选产物；`source_blocklist` 对上下文来源引用做精确匹配。它们不是通用 URL 规范化、网络访问控制或语义泄漏检测。final 数据不会成为后续生成输入，但框架无法自动识别调用方错误标为 public 的秘密。

`composed-v4` 保存独立调用计划、已开始记录、缓存、比较回执、冻结候选和终审状态。恢复比对只追加日志，不能用旧 checkpoint 抹掉已发生的付费调用。cycle 中途停止不会提前终审；正常结束或预算停止才冻结，完成后的恢复不会再次终审。旧 v1/v2/v3 检查点缺少新契约，明确拒绝自动升级。

仍只支持 serial、tree、inprocess 与完整 cycle 边界恢复；未完成付费操作不自动重调。replay 使用新资源/组件实例独立重执行，真实收费并保留逻辑 run 身份；它不是免费读取旧 final 结果。详见 S1/S3 的工厂、内部状态和导出文件校验要求。

`selection=top_k`、关闭 monotonicity、多个 final 回合、关闭隔离、HITL/human_approval、未知钩子或选项均显式拒绝。旧 M0 二元 gate、Linux worktree/seccomp、HITL 组件及其历史测试继续保留，不代表已接入本配置路径。

## 回归入口

v63 显式执行 `test_layered_admission.py` 与 `test_composed_admission.py`，同时保留 v62 全部组。公开 Framework 回归覆盖 dev 过拟合不能晋升、最终反向得分不改变冻结候选、call_budget 边界、已知失败计费、全局预算不足零调用、恢复时终审只发生一次、split 内容碰撞、错绑身份、阻断来源和两层模式。组件回归覆盖配对缓存、实际记录复算、重 hash 篡改、恢复丢失调用与不支持配置。

本地用 `make check`，受支持 Linux 用 `make accept-linux`。验收范围与真实历史来源见 [v63 verifier 说明](../m0/verifier/v63/README.md)。
