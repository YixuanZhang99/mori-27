# CLAUDE.md — 开发纪律（本仓库的宪法执行细则）

> 你在开发一个可配置的 AutoResearch/AutoOptimization 框架（类比 vLLM 之于推理、VeRL 之于 RLHF）。
> 目标是让 AIDE/Arbor/OpenEvolve 等经典系统都成为本框架的一份预设配置（recipe）。
> **SPEC.md 是宪法，本文档是执行纪律。偏离规格前必须先写 ADR。**

## 文档地图（先读再写码）

| 文档 | 作用 | 何时读 |
|---|---|---|
| SPEC.md | 六数据类型 + 九模块 Protocol + 验收标准 | 每次动手前 |
| REPLICATION.md | 复刻目标的忠实度标准与验收区间 | 写 recipe / 跑复刻前 |
| ZOO.md | benchmark 适配器契约 | 接入新 benchmark 前 |
| REFERENCES.md | 按模块的源码/论文精读清单 | 实现某模块卡壳时 |
| docs/adr/ | 架构决策记录 | 想偏离规格时先写这个 |

## 不变量（违反 = PR 拒绝）

1. **模块间只传六个数据类型**：`Candidate / ExecutorSpec / EvalRequest / EvalResult / EvidenceRecord / StateMutation`（core/types.py）。禁止在模块边界发明新数据结构。
2. **Protocol 先行**：任何模块先写/改 Protocol 与类型，通过评审后再写实现。
3. **失败是一等状态**：评估/执行失败编码进 `EvalStatus`/`executor_status` 字段，禁止异常穿越主循环。
4. **软决策 LLM 化，硬保证机制化**：预算、dev/test 纪律、串行写（状态写 semaphore=1）、作用域隔离、protected hash 用代码强制，不得依赖 prompt 自觉。
5. **credit assignment 只认骨架边**：frontier 的引用边只用于信息流，禁止参与 reward 回传/选择权重。
6. **记忆晋升只增量合并**（delta），禁止整篇重写。
7. **准入信号必须可执行/可复算**：LLM judge 不得单独放行任何 merge。
8. **一切变更留痕**：StateMutation 必带 rationale；git branch 是 artifact 的唯一引用形式。

## 禁止事项（反模式，有实证教训）

- ❌ 平铺文本记忆全局注入（AIRA 消融：无效果）
- ❌ test/admission 反馈无限次参与搜索决策（adaptive overfitting；走 M9 call_budget）
- ❌ executor 在 `hypothesis_frozen=True` 时修改假设（归因完整性崩坏）
- ❌ 一期实现 MCTS/进化拓扑/学习型 π_op/容器隔离/Web UI（SPEC 已排期，提前做 = 范围蔓延）
- ❌ 绕过 registry 直接硬编码模块实例化
- ❌ 在 recipe 之外为特定 benchmark 写特殊分支逻辑（领域差异只能进 zoo 适配器或 DomainPlugin）

## 工作方式

### 每个 PR
1. 改动对应 SPEC 的哪一节，写在 PR 描述里；规格变更 = 同 PR 附 ADR。
2. 单测覆盖新逻辑；跨模块改动必须跑契约测试（mock Evaluator + mock LLM 全循环）。
3. commit message：`[M4] frontier: add ref-edge support (SPEC §6)`

### 复刻纪律（本项目的生命线）
- 每个 recipe 提交时必须附**复刻报告**：目标系统报告值 / 本框架复现值（3 seeds）/ 差异分析（backbone、环境、实现差）/ 结论。
- 数字对不上不阻塞合并，但**差异分析缺失阻塞合并**。诚实比精确重要。
- 环境固定方法见 REPLICATION.md §环境固定（不可变评估脚本、固定数据版本、声明种子）。

### 里程碑出口检查
- [ ] M1：`recipes/aide.yaml` 复刻通过；checkpoint 中断可 resume；三元组报告生成
- [ ] M2：`recipes/arbor.yaml` 行为复刻通过（merge gate 生效、insight 上溯可见）；三层 admission 可配
- [ ] M3：`recipes/openevolve.yaml` 通过；MAP-Elites/island frontier；L3 记忆层

### 卡住时
1. 查 REFERENCES.md 对应模块的精读清单（那里列了"照抄哪个文件的哪个类"）
2. 查 SPEC 该模块的"证据指针"
3. 仍有歧义 → 在 issue 里写明两个候选解释，@架构负责人裁决，不要自行揣摩
