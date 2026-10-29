# AutoResearch 架构核查与补充探针

核查日期：2026-10-29。对象：用户提供的 `AutoResearch-接续开发完整包.zip` 解压后的原始 `AutoResearch-handoff/`。本报告只审阅源码并运行离线探针，没有修改生产代码、历史 verifier 或验收证书，也没有调用真实模型 API。

## 一、定位和代码组织

本包是「研究资料 + 设计契约 + 可执行的治理型进化内核 + 历史验收证据」的完整交接快照。当前可执行主体是 `m0/`；其定位是给候选生成、评估、准入、预算和恢复过程加上可核验约束的 Python 框架原型。它不是已经提供终端用户界面的应用，也不是已证明外部 benchmark 效果的 v1.0 产品。

核心源码位于 `m0/core/`，共 64 个 `.py` 文件、10,356 行（包括注释和空行，不含 vendor、tests、zoo）。最大的四个文件是 `loop.py`（1,675 行）、`openevolve_interop.py`（926 行）、`executor/m0.py`（777 行）、`orchestration.py`（697 行）。

| 位置 | 当前作用 | 核查入口 |
|---|---|---|
| `m0/core/loop.py` | 三个主 API：`evolve`、`inspect`、`replay`；生命周期、单候选/批量路径、checkpoint 和恢复编排 | 137、180、1580、1614 行 |
| `m0/core/policy/` | M1 规则策略、供亲、intent 发出、降档重发、证据吸收 | `scheduler.py:11`、`absorb.py:12` |
| `m0/core/operator/` | M2 draft、反射 improve、evolve-block；独立 debug/crossover 扩展 | `ops.py:17`、28、70、95、137 |
| `m0/core/budget/` | M3 单 token 账本、七账户、control 锁定；独立多物理单位预算扩展 | `ledger.py:23`、`currency.py:20` |
| `m0/core/frontier/`、`archive.py`、`map_elites.py` | M4 谱系树、骨架边/引用边、软剪枝、岛屿迁移、网格精英和供亲 | `frontier/research.py:80`、`archive.py:23` |
| `m0/core/memory/` | M5 L1/L2/L3 经验、作用域、晋升、检索、失效、checkpoint | `store.py:36`、128、172、199、243 |
| `m0/core/knowledge/` | M6 外部知识供给与审计通道分离，注入 ground/audit 后端 | `service.py:21`、75、118 |
| `m0/core/executor/` | M7 git worktree、子进程 journal、资源策略、Bubblewrap/seccomp、线程池、外部 evaluator/proposer 协议 | `service.py:38`、`pool.py:18`、`external.py:56`、`proposal.py:45` |
| `m0/core/eval/` | M8 per-item 结果、级联评估、judge 校准、受控 evaluator 升级；M9 flip-count gate 和 Receipt | `gate.py:13`、`cascade.py:12`、`meta_gate.py:69` |
| `m0/core/state.py` | 单写者验证并应用状态变更；恢复时重放已记录变更 | 34、44、63 行 |
| `m0/core/x1/` | JSONL 追加式证据、规范 checkpoint、治理审计和 Receipt 链 | `store.py:11`、`audit.py`、`checkpoint.py` |
| `m0/core/hitl/` | X2 auto/review、按内容哈希审批、暂停/恢复 | `controller.py` |
| `m0/core/tasks/benchmark.py` | 验证/测试分离的选择契约与可重放回执；同模型同预算配对比较 | 15、59、169、249 行 |
| `m0/zoo/` | MLE-Bench Lite / RE-Bench 的适配与 campaign runner | 各子目录 `adapter.py`、`runner.py` |
| `m0/core/openevolve_interop.py` | vendored OpenEvolve 数据库、artifact、Frontier 和 embedding 状态互操作 | 326、776 行及导入导出函数 |
| `autoresearch-fw/` | 设计目标、模块规格、验收定义、版本开发记录；不等于全部已经接线运行 | `VISION.md`、`SPEC.md`、`RUBRIC.md` |
| `docs/`、`research/`、`plans/`、`papers/` | 设计总结、证据卡片、历史计划和参考资料 | 根 README 导航 |

## 二、真实执行路径

1. 调用方提供 proposer callable、evaluator callable、`LoopConfig` 和一个新的工作目录，创建 `Framework`；已有证据的工作目录必须显式选择恢复（`loop.py:140–195`）。
2. 主循环构造 token 账本、M9 gate、frontier、memory、规则策略与 StateApplier（`loop.py:196–208`）。
3. genesis 和后续单候选依次执行 intent 申请、预留、调用前预算检查、propose/apply、evaluate、记录终态、计量结算（`loop.py:619–688`）。
4. `BestFirstPolicy.absorb` 把 EvidenceRecord 转为确定性 StateMutation；StateApplier 逐项验证后更新 frontier/memory（`policy/absorb.py:26–61`、`state.py:44–127`）。
5. M9 比较候选与 incumbent 的逐样本成败变化，只用 F/B/N 和 noise floor 判定；aggregate score 用于供亲/展示，不进入此处终裁（`eval/gate.py:19–68`）。准入产生 Receipt，状态终结为 MERGE 或 PRUNE。
6. 每隔 `baseline_every` 在独立 control 账户上执行 IID-RS；不进入研究 frontier/memory（`loop.py:1520–1535`）。每周期写 checkpoint；最终输出最优候选、轨迹、预算、健康、治理、自证与恢复信息（`loop.py:1536–1578`）。
7. `batch_size>1` 使用冻结 cohort：全批先预留、执行、验证全体物理成本、结算全部候选，再按输入顺序串行 admission（`orchestration.py:600–686`）。`ExecutorPool` 用线程并行阻塞后端；M0 旧式共享 token meter 的完整段落仍加锁，不能把 `max_inflight` 等同于真实 LLM 吞吐线性增长（`executor/pool.py:18–35`、`executor/m0.py:679`）。
8. 恢复依赖持久化操作边界、原生 outcome、进程身份、账本与 mutation 后缀严格匹配；缺失/歧义证据拒绝恢复。这是所声明窗口的进程崩溃恢复，不能扩张为机器断电或任意真实远端调用均 exactly-once。

`replay()` 不是简单读取旧日志，它会在独立 replay 工作目录重新运行候选链并比较规范 snapshot、Receipt 链、稳定结果和治理；对真实不确定性模型可能不一致并报错（`loop.py:1614–1660`）。

## 三、实现和集成的边界

| 能力 | 当前结论 |
|---|---|
| GEPA-shaped 反射改写 | 有可加载 `gepa_reflective` profile，是 M0 子集，不能称 GEPA 完整复现 |
| FunSearch-shaped 岛屿/evolve-block | 有 `funsearch_island` profile、迁移/供亲/区块改写；配置中的 `representation`/`source` 还留有旧描述，不能只读注释判断实现 |
| MAP-Elites 网格 | 有 `map_elites_grid` profile；读取已准入候选的有限 numeric feature，影响供亲，不进入 M9 |
| 记忆 | 主循环会写入、晋升、保存和恢复；当前 `loop.py` 没有调用 `memory.retrieve()` 来自动组装下一轮 prompt。存储治理已实现，不等于经验已经驱动默认搜索 |
| 知识供给、debug/crossover、多币种、评估器进化、HITL | 存在可调用实现和测试，但不全部自动装入默认 `Framework`；要通过协议组合/后端集成，不应当宣传成一个 profile 开关就全部运行 |
| OpenEvolve | 真正数据库/状态/产物互操作较完整；仍不能等价于完整宿主搜索策略或效果复现 |
| MLE-Bench Lite / RE-Bench | 适配、物理成本/选择证据和本地协议测试存在；包内当前证书明确外部 campaign 未执行 |
| Python 安装/发布 | `pyproject.toml` 只有 project 元数据和 pytest 配置，没有构建后端、运行依赖/开发依赖声明或 CLI 入口；当前应按源码目录运行，不宜描述成已经完整打包的可安装产品 |

已有设计价值：预算、搜索策略、准入分离；拒绝候选仍留证；对照基线独立；最终选择与外部 test 成绩隔离；checkpoint/恢复重用原结果；审计和失败证据明确；许多协议采用失败关闭。

## 四、本次补充发现（当前未修复）

### A1：进程内评估的重复 item_id 可以改变 M9 判决（建议 P1）

- `core/eval/types.py:8–31` 是无运行时校验的 dataclass；`core/eval/gate.py:19–30` 把 incumbent 压成字典，却对 candidate 原列表逐条累加，没有唯一 ID 校验。
- `loop.py:652–655` 对普通进程内 evaluator 仅校验 EvalResult 类型和 candidate_id，没有在入 gate 前约束 item 集合、唯一性、verdict 范围和 head 绑定。
- 可达性：不是仅手工调用内部函数。通过文档所述的 `Framework(LLM, evaluator, ...)` 公共调用可复现：基线 a=0,b=1；候选 a=1,a=1,b=0，唯一样本实际一胜一负，但被计为 F=2/B=1/N=3，候选准入且 `governance_pass=true`。
- 修复方向：构造/接收 EvalResult 时集中验证唯一 ID、二元 verdict、候选/head 绑定；对比较样本集合定义固定契约。子集比较如需支持，应显式声明，不要依赖静默交集。
- 限定：外部 evaluator 协议已经有更严格的 envelope 校验，不能把此缺口泛化为所有执行路径都相同。

### A2：未知 token 用量被当作零或估算值入账（建议 P1）

- `core/llm.py:32–37` 对 provider 缺失 usage 默认为零；`take_usage`（54–60 行）对无 meter 对象也返回零。
- 单候选主循环 `loop.py:638,682` 以 `metered or cfg.intent_cost` 结算。全部缺失时将 intent 估算值当作实际支出；仅 proposer 缺失而 evaluator 有用量时，只计 evaluator，丢掉未知 proposer 成本。两种探针均 `governance_pass=true`。
- 可达性：文档推荐的 OpenAICompatibleLLM 收到缺 usage 的兼容 provider 响应即可走该分支，不需要手工改账本。探针用离线 callable 模拟同一 meter 行为，没有声称某真实 provider 一定省略 usage。
- 修复方向：用量区分 measured / estimated / unavailable；声明实测时缺失立即拒绝认证，估算模式可运行但不得出具实测成本结论；proposal、evaluation 分别计量再汇总。
- 限定：`tasks/benchmark.py` 的 measured campaign contract 已更严格，这里是 M0 默认适配/结算链，不应说整个项目所有成本比较都失效。

### A3：单币账本的输入及生命周期校验弱于多币账本（建议 P1/P2）

- `BudgetLedger.quote_reserve`（`ledger.py:57–81`）拒绝 settled intent，却未拒绝尚 open 的同 ID intent：同 intent 连续 reserve 100 两次均 granted，后来 settle 10 后 spent=110，出现幽灵占用。直接公共 ledger API 可达；未发现默认 Framework 自行发出重复 intent 的证据，因此不应声称常规 run 必然触发。
- `BudgetLedger.settle`（99–115 行）不校验 actual_cost 非负/有限数。直接调用可落账 -20；进程内 LLM 报 -10、evaluator 报 5 时，公共 Framework 仍返回并准入 genesis，账本 settle=-5。终局治理审计会正确报失败，因此是入口缺少失败关闭，不是负成本获得成功审计证书。
- `MultiCurrencyBudgetLedger` 已有重复预留与成本有限/非负校验（`currency.py:75–89,124–134`），可作为统一约束的参考。
- 修复方向：单币与多币共用前置校验；先验证后改变 reserves/spent；用无效 meter/重复 intent 回归验证预算状态不发生变化。

### A4：运行时会计版本信息固定为 mock（建议 P2）

`Framework.__init__` 在 `loop.py:155–157` 固定写 supplier=mock、model_version=mock-v1、tokenizer=t1、price_table=p1、date=2026-10-26。真实模型适配器也没有在此注入真实 stamp 的公开参数。对账结构可以一致，但无法由该 stamp 追溯真实供应商/模型/价格版本。应注入会计上下文；未知的价格版本明示 unavailable，不能用 p1 暗示已有真实价格表。

### A5：主循环恢复分支集中导致维护风险（建议 P2）

`Framework.evolve` 从 180 行延伸到 1578 行，把 checkpoint、外部/进程内恢复、genesis、单候选、batch、control、结算和状态后缀写在一个方法里。现有大量故障注入测试是优点，但继续增加窗口容易出现路径不对称（例如普通路径和外部协议的验证差异）。建议先保持行为不变，将操作边界/结算/恢复验证拆成可复用的类型化组件，再扩大真实 campaign。

### 其他明确边界

- AppendOnlyStore（`x1/store.py:17–31`）是 API 上只追加的 JSONL 和实例级线程锁，不是不可篡改存储、跨进程事务数据库或强制持久化 fsync 机制；与文档“不认证断电”的边界一致。
- 默认 budget 中的 reeval_floor 只在初始化时用于可启动检查（`ledger.py:29–39`），不是在 `_available` 中持续锁定的独立保留资金；实际语义应与名称/设计解释保持一致。
- default `evolve` 内部使用 `asyncio.run`，不能直接嵌入已有 event loop 的同线程上下文；服务化应另做 async 外观。
- 目前不存在真实外部 API、外部 benchmark 和 USD 效率的已完成证据；490 个历史本地测试不能替代这三项认证。
- B1 的 `_self_attestation`（`loop.py:74–102`）实际比较 `best_score - mean(IID-RS)` 与调用方设置的固定 `noise_floor`；它没有自动估计统计噪声、置信区间，也没有让主搜索与 IID-RS 使用同一个最终选择算子。主搜索的 archive best 与对照均值具有不同选择含义，因此 `PASS` 应解读为此特定描述性规则满足，不能直接作为统计显著优于公平随机搜索的证据。默认 noise_floor=0 更不能替代噪声估计。独立 benchmark 的 `SelectionContract` 没有自动接入这条路径。这是方法学限制，不等于现有 B1 代码偏离其文档定义。

## 五、复现证据

脚本：`docs/review/architecture-probes.py`。
本次输出：`docs/review/architecture-probe-results.json`。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 docs/review/architecture-probes.py \
  m0
```

脚本不调用网络、不读取凭据、不修改生产源码，只在自动清理的临时目录写入运行证据。退出 0 表示这些已列出观察成功复现，绝不等于代码安全或正确。应连同源代码版本/原包 manifest 保存；修复后须更新审计证据，不能把旧观察当作未来版本状态。

## 六、接续顺序建议

1. 先补 A1–A4 的数据/成本边界，再做真实付费模型调用。
2. 明确 Linux x86_64 认证环境和 Mac 本地可用子集；补运行依赖与可重复的 CI 环境。
3. 建立「经典系统 → profile → 已接线机制 → 独立扩展 → 未实现/未认证」支持矩阵。
4. 先以小规模真实 GEPA 负载核验 B1、真实 meter 和价格版本，再开展既定外部配对 campaign。
5. 在不改变 Receipt、ledger 和恢复证据语义的前提下拆解超长主循环，减少不同执行路径的校验漂移。
