# 第三方来源与许可记录

整理日期：2026-10-29。此文件记录包内可核实来源，不替代各文件的许可证，也不为整个项目授予新许可证。

| 材料 | 包内位置 | 可核实来源及状态 |
|---|---|---|
| OpenEvolve 源码快照 | `m0/vendor/openevolve/` | 原嵌套仓库 remote 为 `https://github.com/codelion/openevolve.git`，HEAD 为 `5153a7d74ee615b7090ec52903629870ecdacdf1`；保留其 [Apache-2.0 LICENSE](m0/vendor/openevolve/LICENSE)。导入时排除 27 个 `.git` 元数据文件，将源码作为普通文件提交。HEAD 是原包记录的基准，不能单凭该值证明工作区没有上游修改；本次保真依据为原包逐文件 SHA256。 |
| MLE-Bench Lite 适配资料 | `m0/zoo/mle_bench_lite/` | 参见原始 [PROVENANCE.md](m0/zoo/mle_bench_lite/PROVENANCE.md) 与 snapshot manifest；适配器及静态任务清单不代表包含完整官方数据或完成外部运行。 |
| RE-Bench 适配资料 | `m0/zoo/re_bench/` | 参见原始 [PROVENANCE.md](m0/zoo/re_bench/PROVENANCE.md) 与 snapshot manifest；官方环境和评分运行仍需另行准备。 |
| LoongFlow 参考源码 | `papers/lfsrc/` | 原包中未附独立许可证和锁定 commit；保留为原始研究材料，公开再分发前需补齐来源和许可核查。 |
| 论文、提取文本与论文源码 | `papers/`、`paper.pdf`、`paper_src.tar` | 原始研究材料；本次没有核定每份材料的公开再分发许可。 |

项目根目录原本没有整体 LICENSE。本次按用户确认创建公开仓库；未擅自为原创代码或第三方材料选择 MIT、Apache 等统一许可。公开托管本身不替代各材料的授权来源核查。

完整原包文件清单见 [MANIFEST.json](MANIFEST.json)，导入差异见 [import-audit.json](docs/review/import-audit.json)。
