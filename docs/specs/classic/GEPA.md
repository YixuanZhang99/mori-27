# C01 — GEPA 反思式 prompt 优化

状态：首项规格草案；继承 [COMMON](COMMON.md)。目标：从完整公共入口跑通单组件 GEPA，第一任务选 GSM8K 小子集；小子集不用于宣称原论文公开区间。

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
配对 acceptance 的 strict/tie 行为须从固定上游源码提取成测试后冻结；不能沿用默认 metric gate 猜测。该项未完成前规格状态不升为“冻结”。

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
proposed：`PYTHONPATH=m0 python -m zoo.gepa_gsm8k.runner --mode fixture --output <new-dir>`；真实运行显式 `--mode live --manifest <frozen-json>`，相同命令契约由 COMMON 继承。
报告：accuracy、逐题结果、evaluation 次数、生成/评估 tokens、各 seed 搜索与 IID-RS 结果；不强行要求提高准确率，不把小子集结果关闭 B4。
