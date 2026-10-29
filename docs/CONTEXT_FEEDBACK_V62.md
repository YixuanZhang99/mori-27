# S3 作用域上下文与本地知识回流

本页记录 S3 引入的契约，运行版本和阶段边界按 S3 当时状态阅读。三层准入见 [S4 指南](LAYERED_ADMISSION_V63.md)；后续 S5/v64 的 `composed-v5` 和最新迁移限制见 [S5 指南](HIERARCHICAL_BUDGET_V64.md)。

S3 将 M5 检索结果作为实际 ContextPack 送入配置路径的 ideation/operator，并以显式 research 配置接入本地文件知识的 ground/audit 双车道。当前运行版本为 `composed-v3`，每次新运行有独立 logical_run_id。实现条款和验收结果追加在 [统一抽象对照清单](ABSTRACTION_ALIGNMENT.md)；本页说明使用范围，不代替当前提交的 Mac/Linux 证据。

当前检索是有作用域的词项相似度与效用排序，知识源是明确配置且实际打开的 UTF-8 文件。没有联网搜索、向量检索、语义质量评测或外部知识服务认证。S4 三层准入、S5 分层预算，以及 S1 尚未接通的拓扑/worktree/HITL/事件总线条款仍按清单保留。

## M5 从证据到下一轮输入

默认 `memory={"name": "scoped"}` 现在构造 `ContextMemory`。driver 根据 logical_run_id 与完整 canonical 证据生成 receipt hash，替换 policy 提议中的通用来源引用，并检查 candidate、run/task/domain、evaluation_context、dev split 和信任等级。即使两个 run 产出相同评估，receipt 也不会混用。policy 可以提出经验内容，不能伪造来源、提高信任等级或将其他候选的经验冒充本轮结果。

后续 cycle 先由 frontier 生成拓扑范围，再由 M5 在该范围内检索。ContextPack 保存查询、范围、长度预算、经验正文与 provenance、ground 知识来源，并生成内容 hash。`context_pack_ref` 随 Candidate 保存；默认 operator 将实际包放入模型输入。skill 不能改写权威检索内容或其引用，operator 不能丢弃或替换引用。

M5 中的 `gated` 在当前实现表示已验证的成功 dev 评估，不等于 S4 独立 admission 已通过。失败证据保留为 `ungated`；默认 trust_floor 会过滤它。是否包含 negative 经验是另外的显式筛选条件，不能把二者混成“所有失败默认进入生成”。

## 检索配置

通过原公共入口传入配置字典：

```python
from core.composition.defaults import composed_profile

profile = composed_profile(name="scoped-prompt")
profile["memory"] = {
    "name": "scoped",
    "options": {
        "context_scope": "ancestors",
        "top_k": 5,
        "max_chars": 6000,
        "trust_floor": "gated",
        "levels": ["L1", "L2"],
        "include_negative": True,
        "include_imported": False,
    },
}
framework = Framework.from_profile(profile, llm, evaluator, config, workdir)
result = framework.evolve(task)
```

| 选项 | 默认值与约束 |
| --- | --- |
| context_scope | `ancestors`；可选 `parents`、`ancestors`、`parent_siblings`、`run` |
| top_k | 5；正整数，先按权限/拓扑筛选再排序 |
| max_chars | 6000；至少 1024，约束序列化 ContextPack 长度 |
| trust_floor | `gated`；接受 ungated/gated/verified/human，不能靠配置把低信任经验升级 |
| levels | L1/L2；可显式选择不重复的 L1/L2/L3 |
| include_negative | `true`；是否允许效用标记为负面的经验 |
| include_imported | `false`；导入存储与允许注入是两个独立步骤 |
| imports | 默认空数组；每项为明确的 path 和 `sha256:...` 内容摘要 |
| export_on_finish | `false`；结束时导出本运行符合条件的 L2/L3 经验 |

`ancestors` 沿 parent 骨架边查找，`parent_siblings` 取父节点及其兄弟，`run` 放宽到当前运行的候选集合。当前不沿 reference 边自动扩张权限范围。范围内仍须满足 run/task/domain、内容身份、状态、信任和层级规则；无关节点不能通过提高 relevance 或 utility 越权进入结果。

长度限制单位是字符，不是 token，也不是 S5 的物理成本预算。超出包上限的条目不会进入生成输入；如果范围描述本身无法在上限内表达则拒绝。journal 分别记录检索命中和最终纳入的 ID，不能把被截除条目当作模型已经读取。

经验失效不删除历史。失效状态、superseded 信息和引用检查会影响下一次检索；默认存储保留原条目及事件，用于核对为何某条经验不再注入。

## 本地知识双车道

知识需显式设置 research 模式，注册名为 `local_files`：

```python
profile["mode"] = "research"
profile["knowledge"] = {
    "name": "local_files",
    "options": {
        "ground_files": [{"path": "/absolute/path/ground.txt"}],
        "audit_files": [{"path": "/absolute/path/audit.txt"}],
        "max_results": 5,
        "max_file_bytes": 1_048_576,
        "ground_namespace": "ground",
        "audit_namespace": "audit",
    },
}
```

文件条目还可指定 `sha256`。构造时实际打开文件，限长读取、UTF-8 解码并绑定 URI、字节数和内容 hash；提供摘要但内容不符、重复文件、空文件或超限都拒绝。ground/audit 各有独立 backend、查询调用和 namespace，namespace 不得相同。max_results 默认 5、上限 100；max_file_bytes 默认 1 MiB、上限 16 MiB。

只有 ground 包提供可注入的 context_items，包含实际 fetch 引用与 source_pages。audit 使用候选产物独立查询，结果只作为 advisory 证据记录，不能单独批准准入，也不会进入生成上下文或默认 memory。相同内容被两条车道打开会使相应 audit 失效，不论先 ground 还是先 audit；恢复检查不能把该失效状态复活。

benchmark 模式的非空 knowledge 配置会在文件读取和构造之前拒绝。research 模式可以不配置 knowledge，此时仍使用 M5。旧的静态隔离检查保留，新增端到端测试验证模式差异；允许 research 接入不等于开放 benchmark 的外部知识访问。

本地 backend 的零 token 用量来自已知的本地确定性执行；它没有请求模型，也没有联网。这个零值不表示未测量的 CPU 时间、美元或未来付费 backend 都免费。付费知识插件仍需要自己的显式计量与调用契约。

## 显式跨 run 回流

对于具备非空内容身份的 domain，可在首个运行开启导出：

```python
from pathlib import Path

profile["memory"]["options"]["export_on_finish"] = True
source = Framework.from_profile(profile, llm, evaluator, config, source_workdir)
source_result = source.evolve(task)
exported = source_result["memory_export"]
if exported["status"] == "exported":
    snapshot = {
        "path": str(Path(source_workdir) / exported["relative_path"]),
        "sha256": exported["sha256"],
    }
```

正常结束或预算停止后，driver 从本 run 选择有效 active L2/L3 task/domain 条目，写入 `memory-export.json` 并返回相对路径、摘要和 entry_ids；没有合格经验则返回 `no_eligible_lessons`。干净的中途暂停不会提前做结束导出。重复恢复已结束运行会核对导出文件的内容 hash 并复用记录，不覆盖原导出；篡改导出不能通过恢复或 replay 认证。

第二个新 Framework 可以选择 M5 共享：

```python
next_profile["memory"] = {
    "name": "scoped",
    "options": {"imports": [snapshot], "include_imported": True},
}
```

或在 research 模式选择独立的 M6 回流：

```python
next_profile["mode"] = "research"
next_profile["knowledge"] = {
    "name": "local_files",
    "options": {
        "ground_files": [],
        "audit_files": [],
        "memory_imports": [snapshot],
        "ingest_on_finish": False,
    },
}
```

`memory_imports` 将指定快照转为独立 M6 heuristic 记录，后续 ground 上下文在作用域和 evaluation_context 允许时检索它；不复制为 M5 条目。`ingest_on_finish=True` 则让本轮结束导出同时进入本运行的 M6 记录，仍需显式快照配置才能授权下一运行使用。task 经验要求任务和 domain 身份匹配；domain 范围共享需先按现有作用域提升规则完成明确晋升。导入前先核对完整快照和摘要，错误 task/dataset/hash 在付费调用和 journal 写入前拒绝。

## 持久化、作用域和兼容

不同新运行即使 task/profile 相同也获得不同 logical_run_id，避免误共享 run 记忆；因此独立 run 的 checkpoint_ref 不应被强行要求相同。恢复从检查点读取原逻辑身份；独立 replay 为核对同一逻辑执行保留该身份，同时使用新工作目录、新适配器和新组件状态。

`composed-v3` 保存记忆权威绑定、导入记录、知识 manifest、fetch 与失效状态。S1/S2 的旧检查点没有完整的作用域运行身份，不能通过修改版本号自动升级。保留旧证据，在新目录重新评估；同版本恢复仍要求原配置与内容身份匹配。

已绑定的本地文件在一次运行中作为打开时的内容快照使用。恢复/replay 重新构造组件并核对 manifest；若源文件内容改变，不能继续认证为原知识环境。默认 runtime 仍只支持串行、cycle 边界恢复，未完成付费 cycle 仍拒绝自动重调。replay 会再次执行模型和评估，不能称为免费回放。

M5 的组件导出 API 要求调用方逐项指定 entry_ids；上文结束导出由 driver 按明确资格选择本 run 条目，新文件以独占方式创建。导入必须提供准确的内容 hash，并重新验证 scope、内容上下文与来源。hash 是调用方选定快照的依据，不是外部作者身份的数字签名。空 evaluation_context 的旧不透明 evaluator 只能产生 run 经验，不能授权跨 run 导入/导出或知识 ingest。

M6 的 ingest 使用单独的记录集合，不扫描 M5 的隐式全局目录；外部知识不会因此自动写入 M5。组件 API 的 `export_snapshot`、`import_snapshot`、`ingest_memory_export`、`retrieve` 和引用失效操作也可单独使用；不能把单组件调用当作整份 Framework 检查点已更新。跨运行的检索只针对明确授权、内容匹配且未失效的记录，不承诺统一向量库或自动假设聚类索引。

## 验收入口

Mac 使用 `make check`，S3 定向测试组为：

```bash
cd m0
uv run --locked python -m pytest \
  tests/test_composed_context.py \
  tests/test_composition_context.py \
  tests/test_composition_knowledge.py -q --fail-on-skip --strict-markers
```

[v62](../m0/verifier/v62/README.md) 保留全部 v61 命令组与全量 pytest，再加入该组。独立的组件测试不能替代 Framework 的实际回流用例；Mac 通过不代替 Linux 的同 SHA 自动验收。计数、提交和 CI 证据统一追加至 [清单](ABSTRACTION_ALIGNMENT.md)。
