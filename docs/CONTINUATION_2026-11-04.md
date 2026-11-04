# 持续开发接续记录（2026-11-04）

## 目标与事实基线

按现有 VISION、RUBRIC、统一抽象及逐项对照清单推进到可复现使用的发布候选。保留六概念内核、公开 Framework 入口和历史验收证据；真实可用性、架构完整性和外部效果分别验收。

- 原仓库：<https://github.com/YixuanZhang99/mori-27>。
- main：`49be71ec079f1412a4a8e74086064c4db121c363`，S8/v67。
- 已有后续分支：`codex/mle-composed-pilot`，`dfe29cb4265fd939a203d587a57b523efbe52c36`，S9/v68。接续工作应检查并保留这项既有成果，避免从 main 重做 S9。
- [v68 CI 41032740938](https://github.com/YixuanZhang99/mori-27/actions/runs/41032740938) 两个 job 成功。已下载并检查 artifact 中 summary、certificate 与日志：1,740 pytest，38 检查，verifier 退出 0，历史未变，外部模型与 benchmark 未执行。
- 本地采用 Python 3.12.3、仓库 uv.lock；v67 基线 `make check` 实际通过：1,472 portable、160 Linux deselected、11 axioms、4 离线示例、43 tooling；未把 Linux deselected 计为通过。
- 当前本机 `.venv` 位于用户目录；`scripts/check_linux.py` 实测沙箱不可访问该解释器，完整 Linux 验收需要 docs/DEVELOPMENT.md 所述系统路径环境或同 SHA CI。不可因此扩大沙箱挂载或关闭隔离。

## 下一阶段顺序

1. **接续并核验 S9**：审查 v67→v68 变更，复现影响真实试跑的具体缺陷；每个修复先有失败回归，再做最小修改。维护 `docs/MLE_COMPOSED_V68.md` 中固定预测、隔离评分、同预算、未知费用和失败矩阵契约。
2. **冷启动与运行证据**：按文档建立锁定环境，验证公开入口、四个离线示例、构建和导入完整性；本机限制与 CI 证据分开记录。发现的问题回到所属模块修复，不能加一条不经 Framework 的演示路径冒充接通。
3. **真实小规模试跑**：先落实模型、预算、Kaggle 数据和规则授权，再执行 preflight；通过后才跑三个任务的 baseline/full 配对。结果必须包含所有失败、实际费用、实际模型、数据身份及冻结提交。无这些条件时继续离线开发，不使用 fixture 填真实结果。
4. **治理与架构缺口**：根据逐项清单关闭 composed 路径常驻 IID-RS、X2 HITL、X1 事件订阅、通用执行角色和并行池等仍开放范围；先用真实使用反馈排序，每项建立独立设计和验收边界，不同时扩展全部模块。
5. **差异化实验**：参考研究记录中的固定 SHA，优先检验“同预算搜索是否优于 IID-RS”“失败/中断费用能否完整归因”“代理误导是否被阻断且终审不泄漏”。这些是待验证假设，不预先宣称他人无法实现或全面领先。

## 清晰结构与开发纪律

- `m0/core/`：领域无关机制；`m0/core/composition/`：配置组装与执行闭环；`m0/zoo/`：任务、数据与评分适配；禁止 benchmark 特例进入内核。
- `docs/ABSTRACTION_ALIGNMENT.md`：条款及阶段事实源，保留基线记录并追加阶段证据。
- `autoresearch-fw/VISION.md`、`RUBRIC.md`：产品方向与完成标准，不为测试通过放宽标准。
- `research/`：对标证据、固定 commit 和可复现实验；不把 README 声明当作已运行结果。
- `plans/`：历史计划；新阶段执行说明跟随其设计与验收文档，不用旧计划覆盖新代码事实。
- 功能改动需要行为回归；跨模块改动必须通过公开 Framework 入口。只进行有需求证据的局部重构，避免目录重排造成无效迁移。

## 提交、同步与回滚

用户已授权定期向原仓库提交，并选择为当前 `NeekYoung12` 账号开通写权限。开通前本地继续工作，不擅自改用 fork。

- 每个独立、可复核的修复或里程碑建立一个本地 commit，说明条款、行为、验证及限制。
- 每个验证通过的里程碑推送验证分支；若持续阶段超过一个工作日，也在通过当日检查后保存远端检查点。
- 推送前 fetch 并检查分歧；原仓库 main 仅在同 SHA 全量 CI 通过后 fast-forward。禁止 force push，禁止把另一 SHA 的 CI 当作当前通过。
- 无写权限时保留本地 commit 和可移交 bundle，明确报告尚未同步；不把本地 commit 描述为远端备份。
- 回滚以独立 commit 和已有稳定 SHA 为锚点，公共历史采用 revert；不得删除失败记录、覆写旧 verifier 或重造历史证书。

## 持续工作与复审节奏

本聊天已创建 active goal，持续推进上述发布候选目标。每个里程碑完成后回顾条款、结构、失败模式、对标证据和下一个最小交付。

另已建立每周一 09:00（Asia/Shanghai）的开发复审 heartbeat；每月首次复审补研究刷新。复审先检查在途开发和 Git 状态，避免并发写同一工作区；无实质变化时不通知，有重要发现、阶段完成、失败或用户必须处理的事项才通知。

复审固定关注 FlashRSI、RSIHub、penguin-harness、RSI-Anything 的新增提交，记录“可借鉴机制、适用边界、是否推翻现有决策、验证方法”。独特性以实测组合能力与证据质量建立，不使用缺乏支持的排他性宣传。

## 本次验证记录

- v67 `make check` 退出 0；可移植测试用时 433.85 秒。
- 原始 v68 MLE 目标组本机通过：105 passed、3 deselected，33.02 秒。
- 已复现并修复匿名标签排序泄漏；初始攻击回归先失败后通过，第一轮相关组 109 passed、3 deselected。随后补充配对密钥和恢复拒绝、沙箱前置检查；最终 `make check` 退出 0：1,587 portable、163 Linux deselected（234.68 秒）、11 axioms、4 离线示例、52 tooling；`make build` 生成 wheel/sdist 成功。Linux 全量仍待运行，deselected 不计通过。
- `make verify-import` 通过：1,020 个原始负载文件，零错误。
- 独立修复审查未发现重要缺陷；不能代替全量验收。

## 用户最新运行选择

用户指定 DeepSeek 最新 V4.1-Flash（API ID `deepseek-flash`）和本轮累计 200 元总上限。GitHub Secrets 因协作者权限暂不可配置，改用仓库外本地私有配置文件；只验证该文件存在、非符号链接和权限 0600，不显示或复制内容。此前没有启动任何真实模型调用。

真实试跑还需要 DeepSeek 参数兼容、人民币跨 run 费用预留/结算、可用 Linux 依赖环境和 Kaggle 规则/数据权限。当前 token 上限不能冒充人民币硬上限。

goal 曾由用户在界面暂停；用户后续明确要求继续本轮工作，但工具仍显示 paused。工具不能替用户恢复状态；跨轮自动工作需要用户在 goal 控件点击继续。每周复审须尊重用户暂停，暂停期间仅做用户新授权的操作。

用户随后确认三个 Kaggle 竞赛规则均已接受。离开前一次性配置脚本已提供：导入 legacy Kaggle 凭据，创建系统路径下本任务环境目录，安装 Git LFS；用户完成标记出现后继续依赖安装和数据验证。尚无付费调用。

## 一次性本地配置完成后的状态

2026-11-04 后续核验更新（覆盖上文关于环境不可用和 goal 暂停的旧状态）：

- goal 工具确认 `active`，无需用户再次点击继续。
- 仓库外两份私有配置均存在、非符号链接、权限 0600；只在本地进程内使用，未显示密钥或提交到 Git。
- DeepSeek 官方 `/models` 认证成功，返回列表包含 `deepseek-flash`；没有发起付费生成请求。
- Kaggle 三个竞赛的文件列表均可访问；官方固定 revision 的数据准备命令全部退出 0，未关闭校验或覆盖官方 checksum。
- 系统路径下分别安装锁定开发环境和 hash-locked CPU pilot 环境；实际 Bubblewrap/seccomp 内的 Python、NumPy、pandas、scikit-learn 导入通过。
- 官方三个任务的注册、protected snapshot 和合成 CSV 评分 smoke 通过。真实 prepared 数据的完整 pilot 环境预检 `ready=true`，无缺失项；这仍不代表模型实验已运行。
- 非秘密的本地路径、候选六次运行参数与准备证据保存于聊天工作目录的 `outputs/local-run-settings.json`、`local-model-readiness.json`、`local-kaggle-readiness.json`、`local-mle-runtime.json`、`local-mle-preflight.json`。这些记录不包含密钥。
- GitHub API 仍报告当前账号 `push=false`、`admin=false`；本地工作继续，尚不能声称远端备份完成。

用户所需的人工配置已完成。下一步是软件工作：按 DeepSeek 研究记录实现 `max_tokens` 请求兼容和跨任务、跨输出目录的累计人民币账本，先验证请求前预留、已知用量结算、未知调用阻断与恢复，再启动已授权的真实试跑。配置文件中明确保留 `paid_generation_enabled=false` 和 `currency_controller_implemented=false`，不能以环境预检通过替代费用控制验收。
