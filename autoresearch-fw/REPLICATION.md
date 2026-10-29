# REPLICATION.md — 复刻规格与验收标准

> 复刻是框架正确性的验收方式：**经典系统 = 本框架的一份 recipe；复现其行为/数字 = 框架语义正确的证据。**
> 原则：机制层必须忠实，实现层允许偏离，差异必须分析并公开。诚实比精确重要。

## 0. 忠实度分级

| 层 | 内容 | 要求 |
|---|---|---|
| 机制层 | 搜索循环结构、算子语义、状态读写时机、准入规则 | **必须复刻**——偏离即不是该系统 |
| 接口层 | 数据在模块间的流向（什么信息在什么时刻可见） | 必须复刻 |
| 实现层 | prompt 措辞、LLM 调用细节、超时数值 | 允许偏离，记入差异分析 |
| 环境层 | backbone 模型、数据版本、硬件 | 允许偏离，但复刻报告必须声明 |

## 1. 环境固定（一切复刻的前提）

方法学参照 AIRA-dojo（其在固定环境内复现 AIDE 并解释 +10.7 点差异）：
1. **评估脚本不可变**：zoo 适配器的 eval 脚本 + 数据纳入 protected_paths，运行时 SHA-256 校验。
2. **数据版本锁定**：固定下载快照，记录 hash 进 PROVENANCE.md。
3. **种子声明**：所有随机性走显式 seed；复刻跑 ≥3 seeds 报 mean±std。
4. **预算对齐**：与目标系统论文的报告预算同量级（MLE-Bench 系默认单 A100 + 官方时间预算；Arbor AO 任务 48h 档按需）。
5. **backbone 声明**：复刻报告必须写明 backbone；跨 backbone 的数字只作定位、不作优劣断言。

## 2. 一期复刻目标 A：AIDE（M1 验收）

**为什么选它**：算子语义最简（draft/debug/improve）、无语义记忆、无准入 gate——框架内核的最小充分测试。

### 必须复刻的机制
- [ ] 搜索循环：多个初始 draft → best-first 改进当前最优 → buggy 节点走 debug
- [ ] 三算子语义：draft（全新解）/ debug（修 buggy）/ improve（改进有效解）
- [ ] 持久状态：solution tree，节点 = 完整代码 + validation 分数 + 执行摘要（Σ(T) 注入后续 prompt）
- [ ] 终选规则：validation best；submission 文件由框架按官方协议产出
- [ ] debug 尝试上限（AIDE 有 debug 深度限制，语义等价即可）

### 允许偏离
- prompt 文本、具体模型调用编排、单文件 vs 模块化的代码组织

### 验收区间（MLE-Bench Lite，官方协议）
| 指标 | 参考锚点 | 一期验收标准 |
|---|---|---|
| Valid submission | AIDE 77.27%（Gemini-3-Flash，Arbor Table 3） | ≥ 70%（同 backbone 档） |
| Any Medal | AIDE 45.45%；AIRA-dojo 复现+升级后 47.7% | ≥ 目标系统同 backbone 报告值 −10pp |
| 行为级 | 树形态（draft 扇出 → improve 链 + debug 支链） | 结构可观测、与 AIDE 论文描述一致 |

注：MLE-Bench 榜单随时间更新，复刻时以当前官方 leaderboard 同 backbone 条目为锚；所有锚点数字进复刻报告。

## 3. 一期复刻目标 B：Arbor（M2 验收）

**为什么选它**：语义内核与本框架最近（假设树 + insight 上溯 + merge gate），验证差异化机制的承载力。

### 必须复刻的机制
- [ ] 六步循环：Observe → Ideate → Select → Dispatch → Backpropagate(absorb) → Decide
- [ ] 假设绑定：executor `hypothesis_frozen=True`；返回恰好四元组证据
- [ ] insight 上溯：叶子 insight → 祖先抽象 → 全局 prior，在 Ideate 时作为正/负约束注入
- [ ] held-out merge gate：dev 改进 ≥ 阈值触发；admission 评估严格改进才 merge；margin 可配
- [ ] worktree 隔离 + score_split 记录（dev/test 分数分字段）
- [ ] 预算：max_cycles / max_tree_depth 可配（默认 20 / 2）

### 允许偏离
- coordinator/executor 的 prompt、具体 LLM 编排、UI/CLI 形态

### 验收标准（行为级为主，数字级为辅）
| 指标 | 参考锚点 | 验收标准 |
|---|---|---|
| merge gate 生效 | Arbor 实测每任务 merge 2-9 次（Arbor Table 5） | 可观测到触发→评估→采纳/拒绝的完整轨迹 |
| dev/test 反差 | Arbor Terminal-Bench：dev 72.22 < test 77.36（gate 抗过拟合） | 复刻 run 中出现 gate 拒绝高 dev 候选的案例 |
| insight 可见性 | w/o insight 消融 −27pp | 树上可读出方向级 insight，且 Ideate 引用之 |
| Any Medal（MLE-Bench Lite） | Arbor：Gemini-3-Flash 81.82% / GPT-5.5 86.36% | ≥ 同 backbone 报告值 −15pp（一期不追求追平，追求机制可观测） |

## 4. 三期复刻目标：OpenEvolve（M3 验收，纲要）

- 必须复刻：MAP-Elites + island 前沿、diff 变异、cascade 评估、异步配额
- 验收：程序进化任务（如 circle packing 类官方示例）达到 OpenEvolve README 报告的同量级分数；迁移与胞格竞争可观测

## 5. 复刻报告模板（每个 recipe 必填）

```markdown
# 复刻报告：{recipe_name} v{version}
- 目标系统/锚点数字（含来源链接、backbone、日期）：
- 本框架配置：（recipe yaml 全文或 diff）
- 环境：（backbone/硬件/数据 hash/seeds）
- 结果：3 seeds mean±std，逐指标对照表
- 差异分析：（数值差归因：backbone/环境/实现；机制差归因：哪些机制未复刻及原因）
- 行为观察：（树形态/gate 轨迹/记忆内容的定性对照）
- 结论：复刻通过 / 有条件通过（条件）/ 未通过（下一步）
```

## 6. 已知风险

- **榜单漂移**：MLE-Bench leaderboard 持续更新，锚点数字以复刻当日为准并截图存档。
- **小样本波动**：Lite 子集任务数有限（以官方 repo 当期 task list 为准），2-3 个任务的波动即可改变排名——验收看区间不看点值，行为级证据优先。
- **backbone 不可得性**：若目标 backbone 不可用/过贵，用同档替代并在报告中声明换算依据（Arbor 的 backbone 研究 [Arbor §5.5] 可作参照）。
