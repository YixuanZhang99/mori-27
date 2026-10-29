# S6 周期 anchor、代理有效性与负反馈（v65）

S6 为已有分层预算增加可选 `proxy_validity`，周期性调用独立开发校准数据，检查探索指标的改善是否仍对应目标指标。当前配置运行版本为 `composed-v6`；旧 v1–v5 检查点缺少校准调用与来源状态，明确拒绝自动升级。公开入口仍是 `Framework.from_profile()`，默认未启用校准监控的配置保持原研究协议。

本阶段对应 [逐项清单](ABSTRACTION_ALIGNMENT.md)的 M3-06，并复用 [S5 物理预算](HIERARCHICAL_BUDGET_V64.md)、[S4 准入](LAYERED_ADMISSION_V63.md)和 [S3 作用域经验](CONTEXT_FEEDBACK_V62.md)。后续 worktree/中断接管与种群分别属于 S7/S8，不因 S6 增量而宣称已经组装。

## 配置与数据边界

在已有 `budget=hierarchical` 的 options 中显式增加以下完整对象；这些字段全部必需，未知字段会被拒绝：

```python
profile["budget"]["options"]["proxy_validity"] = {
    "every_n_cycles": 2,
    "anchor_request": {
        "fidelity": "true",
        "split_id": "calibration",
        "seed_set": [11, 29],
    },
    "proxy_metric": "dev/score",
    "true_metric": "true/score",
    "proxy_direction": "maximize",
    "true_direction": "maximize",
    "min_pairs": 3,
    "window": 8,
    "min_rank_correlation": 0.5,
}
```

此处阈值和周期只展示配置结构，不是研究任务通用参数。proxy_metric/direction 必须与 frontier 的探索目标相同；true 指标可用不同量纲或优化方向，不能把两种原始分数直接相减当作同指标改善。

S6 的 layered admission 另支持 `dev_metric` / `dev_direction`，分别默认继承其 `metric` / `direction`。dev 字段必须与 frontier 的 proxy 目标一致；gate 的 metric/direction 可独立指向 admission 数据上的质量目标。例如探索 loss(minimize) 与准入 quality(maximize) 可显式分开，回执同时绑定两套规则。calibration 的 true 指标由 proxy_validity 单独声明，不能因同叫 quality 就混用数据 split。

`anchor_request` 是完整 EvalRequest，但 split 必须为 `calibration`；可带 domain 明确支持的 seed/时限/token/resume 字段。原生 domain 必须通过 `evaluation_context_for(request)` 声明 calibration 的真实内容身份，并支持该请求。calibration 必须与已启用的 dev、admission、final_audit 内容上下文不同，运行中身份漂移仍拒绝。

calibration 是允许反馈给研究过程的开发校准数据，不是隐藏终审数据。admission/final 的任何结果都不能冒充 proxy 样本或 anchor；三层协议的终审不回流约束保持。内容 hash 不自动证明外部数据集真的隔离，domain 仍负责校验实际数据、规则及评估器版本。

## 配对证据与周期

每个样本配对同一候选、同一产物的成功 dev proxy 结果和真实 calibration 结果。固定绑定包括候选、产物、完整请求、fidelity、seed、内容上下文、评估器版本、逻辑 run 与来源回执；请求只改标签、错绑候选或重复回执不能增加有效样本。

初次需要 anchor，之后按 cycle 从零计数的 `cycle % every_n_cycles == 0` 触发；进入 degraded 后，每个候选都必须有真实 anchor 才能考虑推进。为建立可比较的 incumbent 基线，runtime 可以额外调用 baseline anchor；baseline 不增加 rank 的候选样本数。所需 baseline 与 candidate 的整组预算全部授予后才开始，baseline 先执行。若其返回已知失败，保留费用和降级状态，释放尚未开始的 candidate anchor 并否决本轮晋升；不猜测缺失基线质量。只有完整身份和原 proxy receipt 均匹配的成功结果才可复用缓存。

anchor 使用独立的 `anchor` 物理操作预扣，仍受 global/direction/candidate 所有单位限制；可在 `operation_reservations` 中配置完整单位篮子。不配置 override 时沿用默认 reservation。校准不消耗 M9 admission 的 call_budget，但不能因此绕过物理预算；已知失败仍计费，未知用量保留预扣，已开始的未完成调用不自动重试。规范的 FAILED_TO_RUN anchor 是拒绝证据，会进入 degraded 并否决对应推进；错绑身份或未知计量是完整性错误，终止执行。错绑但用量已知仍先结算，未知用量保持未结预扣。

## 有效性规则

控制器按两指标的 maximize/minimize 方向统一排序，再计算带平均并列秩的 Spearman 相关系数。仅使用最近 `window` 个有效候选配对；`min_pairs >= 3`，且 window 不小于 min_pairs。成功但恒定的分数导致相关系数未定义，不伪装为 0 或 1。

| 状态 | 含义 |
| --- | --- |
| `warmup` | 有效配对不足 min_pairs，且尚无其他失效告警；不宣称代理已验证 |
| `monitoring` | 样本达到门槛，相关系数有定义且未低于配置阈值，亦无既有失效告警 |
| `degraded` | 已出现独立配对退步、anchor 失败、达到样本门槛后的相关系数未定义或低于阈值 |

min_pairs 只约束秩相关判断。若当前 proxy 严格优于此前同口径 true 最佳样本的 proxy，而当前 true 严格退步，会直接记录 `proxy_improved_true_regressed`；这项确定性配对规则不等待 min_pairs，也不代表统计显著性。

degraded 对本 run 保持有效，不会因后来窗口看起来好转而自动恢复。新的 dev 请求/fidelity/seed 会重置有效 rank 窗口，但既有告警保留；configured run 的数据/评估器身份不允许透明更换。所有报告均带 `statistical=False`，相关阈值不是泛化保证、因果证明或显著性检验。

降级后，候选需超过同一 calibration 请求/内容/版本下所有已观测成功 anchor 的 true 最佳值，才能继续原准入流程。不满足时在 admission 调用前否决，不消耗 M9 查询上限；满足也仍须通过已配置的 dev trigger 与 admission margin。本阶段保留原探索策略/指标，增加强制校准和否决约束，不自动替换成独立的全保真搜索算法。

## 搜索反馈与恢复

可读监控状态通过 `context["proxy_validity"]` 进入后续研究输入，并单独出现在结果 `proxy_validity` 中。输入侧仅含 mode、rank correlation、有效配对数、是否每候选校准、推进规则和最近 5 条告警，不注入整个配对历史。完整结果另保留 basis、配对/告警和开放调用；样本不足或校准失败必须结合状态读取，不能只看一个相关数值。

结构化 M5 负反馈只由真实的 `proxy_improved_true_regressed` 配对产生。内容限定为配置指标、方向、分数、候选/pair 身份及 current/baseline 的四个来源引用；不包含 text_feedback 或 private payload。四份完整原始证据只供 driver 校验来源，不能直接成为可检索文本。

这类校准负反馈由 driver 显式授予当前 run 范围，可以进入非祖先候选的检索，不要求把普通记忆的 context_scope 改为 run；ContextPack 的 scope.run_feedback_ids 标识这项授权。它仍受 include_negative、trust_floor、levels、top_k 与 max_chars 限制，条目被过滤或放不进长度预算时不会强行注入。关闭 include_negative 只关闭 M5 负反馈检索，不抹掉独立监控状态与告警。

这类校准负反馈限定当前 run，不能经通用 memory export 分享到另一 run 或混入跨 run 知识。rank 阈值、未定义相关和 anchor 失败告警保留在监控状态，不凭空生成一条“proxy 提升、true 退步”的经验。恢复时按真实 proxy/anchor 记录复核反馈，即使同时重算负反馈、复合引用和 checkpoint 的 hash，也必须通过 controller 原始回执复核；被拒绝的恢复不会发起新付费调用或改写原 journal。

校准日志保存计划、已开始/失败/完成状态和完整证据，checkpoint 保存对应状态与运行身份。恢复重建并严格比对，不允许使用旧 checkpoint 遗忘已发生调用；replay 仍独立重执行并真实记账。完整状态要求精确一致，因此实测 wallclock 或非确定性结果可能使严格 replay 不匹配。

## 验收

v65 显式执行 `test_proxy_validity.py` 与 `test_composed_proxy.py`，保留 v64 全部命令组、完整离线 research 示例和历史 Linux 安全回归。组件测试与公开 Framework E2E 分别验证配对/窗口机制和配置是否改变真实调用、预算、准入、后续输入与恢复行为。

Mac 使用 `make check`，完整 Linux 使用 `make accept-linux`。只有同一提交的完整 CI 通过后才推进 main；真实结果见逐项清单、CI 新证据及交付报告。历史来源见 [v65 verifier 说明](../m0/verifier/v65/README.md)。
