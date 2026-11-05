# v70 本地验收与安装可用性证据

源码固定为 `aedede3c2b78a5c2b57074c70d510af710f5af4e`。本机 Linux 完整 v70 于 2026-11-04 08:38:53 UTC 完成，41 项检查全部通过，耗时 901.868 秒；最终全量 pytest 为 1,821 项通过（375.00 秒）。新证书与唯一新 journal 条目逐项匹配，运行前后 SHA 相同、工作树干净、原历史文件未变。摘要与原始文件哈希见 [summary.json](summary.json)。这是本地证据，不是同 SHA 远端 CI；main 尚未更新。

新增两组覆盖剩余物理预算预留及协作进程日志快照，其边界见 [v70 说明](../../../m0/verifier/v70/README.md)。所有旧命令和超时保留。此处记录不会作为 v70 的初始成功证书写入验收源目录；未来版本归档仍须核对原始证书、journal 与来源。

另在独立环境安装本次非 editable wheel，确认 `core.loop` 来自该环境的 site-packages。`composed_prompt`、`population_prompt`、`gepa_reflective`、`funsearch_island` 四种配置均经公开 API 完成 evolve、inspect 和独立计量的 replay，并留下证据。首次自建检查脚本误用 reflective MockLLM 处理 FunSearch 的 evolve-block 提示而失败；改用仓库既有 FunSearchProposer 后通过，安装包与产品代码没有修改。失败记录与修正后的记录分别保留，不能把这次错误描述为产品修复。

全新解包源码和新项目虚拟环境中，`make setup` 成功，随后原样执行 S1 指南第一段 bash 示例成功。三个官方 CPU 合成评分器也从只读源码验证通过。精确范围、限制和文件哈希见 [operability.json](operability.json)：依赖来自本机既有 uv 缓存，尚非裸机安装或真人新人演练；所有安装验证使用离线 fixture，不是外部模型或 benchmark 结果，也不关闭全部 A6/A7/B/C 门槛。

第二轮真实 MLE 试跑已于 2026-11-04 08:39:18 UTC 从相同只读源码启动，最终预检无缺失项。三个任务 × 两方案、seed 1、每 run 60,000 token、4 次迭代及 16,384 输出上限均保持不变，继续复用原 200 元累计账本和已有 0.927284 元费用上界。此记录只证明启动，后续终态、费用和官方评分须独立核验；[第一次结果](../2026-11-04-deepseek-pilot-attempt-1/README.md)完整保留。
