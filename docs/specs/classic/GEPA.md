# C01 — GEPA 反思式 prompt 优化

状态：规格冻结（2026-11-05，C01 单组件 pilot）；继承 [COMMON](COMMON.md)。目标：从完整公共入口跑通单组件 GEPA，第一任务选 GSM8K 小子集；小子集不用于宣称原论文公开区间。

## 依据、已有与缺口

依据：`autoresearch-fw/M2-UNIFIED-v1.md §8.2`、`M4-UNIFIED-v1.md §8.3`、ADR-0、[已有源码核对](../../../research/2026-11-05-classic-method-fidelity.md)。参考固定为 [gepa-ai/gepa / 3d344691](https://github.com/gepa-ai/gepa/tree/3d34469165f0d604df3b48f1d5c776e9080f3da0)。
当前 `InstanceFrontier` 已有完整逐实例分数表/去冗余覆盖/供亲；`GEPAInstancePolicy` 公共接线仅支持完整 binary dev verdict，代码明确缺 minibatch、配对接纳和独立 validation。
旧 `gepa_reflective.json` 是 greedy 子集，不复用其名字伪装完整方法。

## 九模块配置

| 模块 | 本方法要求 |
| --- | --- |
| policy | instance-frontier 供亲；固定 seed 的 shuffled minibatch；单组件版本无组件选择歧义 |
| operator | 用该批父代 rollout/错误反馈反思并改写 prompt；首版 merge 关闭且显式声明 |
| budget | 生成、反思、父子训练评估、全 validation 评估分别计量；用尽正常停 |
| frontier | 候选×固定 validation item 分数表；保留实例赢家，即使均分不是全局最佳 |
| memory | 仅训练 minibatch 的 reflective dataset，含来源；不把 held-out 错误作提示 |
| knowledge | benchmark 下关闭 |
| execution | 复用 M7 及计量 provider；固定 solver/model 参数 |
| evaluation | train minibatch 配对父子；validation 供亲/终选；独立 test 只在冻结后评分 |
| admission | 与 pinned upstream 对齐的配对改进判定，成功后更新 validation；治理交付单列 |

GSM8K pilot：按 item ID 排序，将官方 train 前 64 题作反思训练、随后 64 题作 validation，官方 test 前 128 题仅终评；实际数据 revision、内容 hash 在运行 manifest 冻结。minibatch=8，search seeds=0/1/2，最多 10 次提案，成本限额可提前停；这些是本仓库小试跑参数，不是论文参数。反思与 solver 可同一服务，所有调用同账本。
item ID 固定为 `gsm8k:<dataset_revision>:<original_split>:<zero-padded original row index>`，先对完整源 split 编号再切分/抽批，不能用当前 minibatch 下标重编号。当前 `core/tasks/gsm8k.py` 的列表内编号不能直接当此稳定身份；只复用其答案解析和评分规则。每份 manifest 同时绑定行内容 hash，防止同 ID 替换内容。
配对规则固定为 pinned `StrictImprovementAcceptance`：同一批次的子代分数和严格大于父代才接受；相等或更低均拒绝。对应 G2 测试必须覆盖三个分支。

## 最小施工

- 复用：`m0/core/frontier/gepa.py`、`composition/gepa_policy.py`、`core/tasks/gsm8k.py` 的解析/评分与现有 M7/provider。
- 新增：`m0/zoo/gepa_gsm8k/domain.py`、`runner.py`、`PROVENANCE.md`，`m0/config/profiles/gepa_gsm8k.json`；训练/validation 角色必须进入通用评估请求身份，不将训练偷标成 final。
- 修改：GEPA 策略、反思配方和 registry 最少接线；若现有 runtime 无法表达额外配对评估，先固定通用请求接缝，再在此方法实现，不另写循环。
- 新增公开入口测试：`m0/tests/test_gepa_recipe.py`，复用现有 `test_gepa_instance_frontier.py`、`test_gepa_instance_policy.py`。

## 可拒绝的验收条款

- G1：父代 A=[1,0]、B=[0,1] 均分相同但分别覆盖实例；两者均有供亲资格，不退化为单 best。
- G2：父子使用完全相同的训练 item IDs；一个批次生成一次并持久化，恢复不重抽。接受、拒绝、tie 均与固定参考一致。
- G3：仅通过配对规则的提案触发 validation 更新；失败候选及其成本留存。
- G4：构造两份各自合法冻结、只在 test 标签上不同的 manifest，同 seed 下搜索 prompt/选择行为一致，最终 test 成绩可不同；运行中篡改任一冻结数据则必须拒绝，不能将篡改当合法新 split。两份 run 的身份不同，不混合其证据。
- G5：反思 prompt 实际包含本批 rollout 来源；空反思不能作为完成；记录回放不调用模型。

current：`PYTHONPATH=m0 python m0/examples/gepa_instance_offline.py`，只验证选择机制。
current（工作区实现，尚待合入验收）：`PYTHONPATH=m0 python -m zoo.gepa_gsm8k.runner --mode fixture --output <new-dir>`；真实运行显式 `--mode live --manifest <frozen-json>`，相同命令契约由 COMMON 继承。
报告：accuracy、逐题结果、evaluation 次数、生成/评估 tokens、各 seed 搜索与 IID-RS 结果；不强行要求提高准确率，不把小子集结果关闭 B4。

## 冻结的数据流与最小接缝

参考源码：`strategies/acceptance.py`、`strategies/batch_sampler.py`、`proposer/reflective_mutation/reflective_mutation.py`、`core/engine.py`（以上均为开头固定 revision）。
本 pilot 为 adapted：单 prompt、merge 关闭、skip_perfect_score 关闭；实例赢家等分去冗余沿用本仓库确定性插入顺序。批次采样使用独立 `Random(seed)` 流；不宣称与上游全局随机流逐位一致。训练集必须整除 minibatch，首版不实现非整除补齐或多提案并行抽批。

数据来源固定为 [openai/grade-school-math@3101c7d](https://github.com/openai/grade-school-math/tree/3101c7d5072418e28b9008a6636bde82a006892c)。源 train/test SHA256 分别为 `17f347dc51477c50d4efb83959dbb7c56297aba886e5544ee2aaed3024813465`、`3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14`。

一轮（例：cycle=1，父代 P，训练 ID 批 B）：
1. policy 只读 validation 的逐题分数，选 P；GEPA operator 的纯 `evaluation_plan(request)` 返回通用 `PairedEvaluationPlan`，绑定 B 和 `EvalRequest(split_id="train", fidelity=<批次身份>)`。批次按 seed/轮次确定，计划在调用前进入现有日志，恢复验证同一计划。
2. runtime 为 P/B 预留独立 `training` operation，调用现有 `_evaluate_physical`；public train rollout/错误与来源引用成为反思配方输入，validation 原始错误不进入反思。
3. M7 生成 C，只计生成成本；runtime 再为 C/B 预留 `training` operation，用完全相同请求评估。
4. 严格改进才进入原有 `dev` operation（该任务的完整 validation）。拒绝时保留实际 train evidence、成本和明确拒绝决策；不伪造 validation 评估。训练结果只有 `train/score`，不含 frontier 的 `dev/score`，因此不获得供亲资格。
5. 完整 validation 结果更新 instance frontier；PopulationFrontier 容量设为至少初始候选加最多提案数，避免有效实例赢家因均分未胜出而丢失。incumbent 的全局均分判定与供亲资格独立。
6. 搜索结束冻结选中 artifact 后才评分 test；test 标签不参与前述任何方法输入，所有 solver/reflection 调用继续同一计量 provider 和累计账本。

通用变更限于：`PairedEvaluationPlan`、`training` 预算操作（明确 train split）、在既有 hierarchical cycle 中插入父代/子代筛选调用。公开 Framework API 不变，不添加第二套主循环。拒绝、错误、预算不足均保留已知费用；不能把未知费用当零。现有 GEPA 公共 verdict 接线仅接纳 dev 证据，恢复时同样排除 train 记录。


施工核对补充：PopulationFrontier 的既有抽样票据只适用于它自己的 sampler；GEPA 接线另记由 InstanceFrontier 可重算的供亲票据，恢复时核对实际成员/预算资格。Domain 的 `evaluation_contexts` 声明 train/dev/final 的独立固定身份，整份数据身份另外进入 profile。`metric_final` 准入插件只按 dev 选 incumbent，复用既有 final 预算操作在搜索冻结后做一次最终评分，不添加 admission split，也不把 final 分数反馈给搜索。它不宣称已实现原三层治理门槛。

首版 live 有一个初始独立 IID-RS control（仅 validation），暂不宣称等预算 IID-RS 对照或论文分数复现。完整多 seed 等预算对照仍是 C01 实测交付的剩余项，不因 fixture 通过而关闭。所有具体差异见 `m0/zoo/gepa_gsm8k/PROVENANCE.md`。
