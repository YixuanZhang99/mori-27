# C05 — OpenEvolve 进化宿主

状态：规格草案；继承 [COMMON](COMMON.md)。依据：REPLICATION §4、M2 §8.1、M4 §8.2、M8M9 §8.1。
参考采用现有 `m0/vendor/openevolve/` 文件快照及 [THIRD_PARTY_NOTICES](../../../THIRD_PARTY_NOTICES.md)，原包记录 HEAD `5153a7d74ee615b7090ec52903629870ecdacdf1` 不自动证明逐文件未改。
2026-11-05 查询上游 HEAD 为 `73448d715968b3578d8458b16295e827edd2b6bf`；本项不随之升级宿主。先对本仓快照做文件级来源核对并冻结 hash。

| 模块 | 本方法要求 |
| --- | --- |
| policy | 复用宿主 parent/inspiration 选择与 island 调度 |
| operator | diff mutation、marker 校验和有限 patch resample |
| budget | generation/evaluation 配额；异步配额独立阶段 |
| frontier | 同时有 MAP-Elites cell 与 islands、胞格替换、迁移 |
| memory | 程序及 artifacts 历史，不默认引入语义记忆 |
| knowledge | 关闭 |
| execution | 复用 M7；先串行机制适配，异步未接通时标 adapted |
| evaluation | stage cascade 真实短路，text/artifacts 经过公开视图 |
| admission | 胞格竞争保留优胜；与治理最终交付分别记录 |

已有 `openevolve_interop.py` 的数据库往返、`MapElitesArchive`、种群和 cascade 不能证明这些在同一配置闭环。
优先薄适配 vendor 的选择/数据库，不重新实现整个 ProgramDatabase；新增 `m0/config/profiles/openevolve_program.json`、`m0/tests/test_openevolve_recipe.py`，必要接缝落 `m0/core/composition/openevolve_adapter.py`。
首任务选 vendored `examples/circle_packing/`，冻结其实际任务参数、源码和 evaluator hash；若其依赖无法满足则明确阻塞这一任务，不悄悄换成 toy 分数。

验收 O1：两个特征 cell 各自保留 elite，替换不丢谱系；O2：岛间迁移改变可采样成员；O3：stage1 失败时 stage2 未被调用也未收费；O4：diff 无法应用时有限重采样后失败；O5：同一任务/模型/总预算下跑 vendor 与 mori 两臂，报告实际差异与成本。
先交付串行 adapted 版本；只有异步配额也完成才称完整参考调度。宿主互操作测试绿灯不构成 B2/B5 打平或效率达标。
真实试跑先 1 seed smoke，再 3 seeds；“同量级分数”须在运行前指定比较来源和区间，不能看完结果再设阈值。
