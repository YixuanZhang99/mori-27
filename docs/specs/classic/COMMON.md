# 经典工作 spec 共用契约

状态：规划规格。所有方法文件继承本页，不表示新 profile 已实现。

## 边界与路径

- 逻辑模块固定为 policy/operator/budget/frontier/memory/knowledge/execution/evaluation/admission。
- 保留当前 Python >=3.11、JSON profiles、registry、`Framework.from_profile(profile, provider, domain, config, workdir)` 和 `evolve/inspect/replay`。不为复刻另建主循环或换 YAML 配置体系。
- profile 放 `m0/config/profiles/`，方法策略与配方沿用 `m0/core/composition/`，任务差异放 `m0/zoo/`，公开行为测试放 `m0/tests/`。本文所列“新增”路径尚不存在。
- 复用 `AssemblyConfig`、`Proposal`、`OperatorRequest`、`EvidenceRecord`、`EvalRequest/EvalResult`；具体签名以 `m0/core/composition/contracts.py`、`m0/core/executor/types.py` 为准。旧 SPEC 示例不是第二套接口实现要求。
- 若方法表达确实受当前协议阻塞，只增加一个通用能力接缝并记录使用者与测试；禁止 `if recipe == ...` 绕过预算、证据与权限。

## 方法一致性

每份报告包含 `method_id / reference_revision / recipe_revision / fidelity / deviations`。
`fidelity` 取 `mechanism_subset`、`adapted`、`reference_protocol`；三者是说明标签，不预设新运行时类。
对照来源与本框架分别报告，旧名字里包含 GEPA/FunSearch 不自动构成复现。

供亲资格、档案保留、终选资格必须分开：不能把未击败 incumbent 的候选全部丢弃而仍声称是 Pareto 或岛屿搜索。
方法内部配对接纳规则与治理最终交付规则分别记录。治理若删掉方法本应保留的候选或反馈，标为 adapted 并分析影响。
正式受治理运行继续满足现有成本与独立对照约束；允许用上游程序作外部参考臂，但不能将其称为已具备本框架的治理属性。

## 输出和验收

每方法提交以下内容，复用现有日志而非再造证书系统：

1. 命名 profile、一个可复制的离线命令、一个显式 opt-in 的真实运行命令；默认命令不调用外部模型。
2. 冻结任务/参考版本/模型参数/种子/总预算/数据及 split hash。
3. 方法关键决策轨迹：候选、父代、算子、输入反馈来源、评分、接纳/拒绝、成本与最终选择。
4. fixture 与真实 run 分开；逐 seed 结果包含失败及费用；不剔除失败后缩分母。
5. 最终候选先冻结再测 held-out；最终标签/分数不回流搜索、反思、记忆。
6. 一次有意义的停止/恢复或记录回放场景，核对不重复已完成外部调用。复用现有恢复测试，不重新枚举所有故障切点。
7. README 链接 spec、命令、结果和剩余差距；不把“测试全绿”写成“性能达标”。

真实小试跑默认三个预声明 seed，资源不足可以先单 seed smoke；后者不能称统计验证。
¥200 是之前用户授权的全项目累计上限，不是每个方法重新获得 ¥200；继续原账本。密钥只由已有配置读取，文档、命令输出和结果中不复制其内容。
目标是先可运行与可核对，不强求结果提升；负结果同样交付。

## 验证命令约定

仓库根 `PYTHONPATH=m0 python -m pytest -q <tests>` 为针对性命令；须使用已安装锁定依赖的解释器。
每个实现任务先用关键反例证明缺口，再做最小修复，针对性通过后做一次现有合入检查。
本文档中的 proposed 命令是接口目标；标为 current 的才是已有命令。
不开新付费 campaign 来验收纯文档变更。
