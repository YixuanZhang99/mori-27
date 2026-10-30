# S9 MLE-Bench Lite：配置路径与同预算试跑

本阶段把公开训练数据上的真实评分接入 `Framework.from_profile()`，使 S6 的 anchor、秩相关监控和负反馈与 S8 种群搜索在同一任务上运行。旧 `governed_agent` 的 M0/提交合法性入口保留；新的入口是 `zoo.mle_bench_lite.composed_agent`。它们不是同一个实验协议，不能混合成绩。

v68 验收使用离线数据与本地模型服务 fixture 检查机制。它不代表已经调用真实外部模型或获得 MLE-Bench 成绩。真正的试跑必须准备官方数据、真实模型凭据和 Linux 执行环境，单独保存证据。

## 首轮支持任务

当前真实数据实现面向以下三个 CSV 任务；这只是 MLE-Bench Lite 22 题的子集。

| 任务 | 类型 | 当前输入范围 |
| --- | --- | --- |
| `spooky-author-identification` | 文本分类 | 公开训练文本、作者标签和测试文本 |
| `leaf-classification` | 多分类 | 公开 CSV 特征；不读取额外叶片图像 |
| `nomad2018-predict-transparent-conductors` | 多目标回归 | 公开 CSV 特征；不读取额外几何文件 |

以上输入范围同时适用于 baseline 和 full。不能把子集结果写成全套 22 题成绩，也不能由这三题推断图像、音频或其他任务的效果。

## 数据和评分

官方公开训练数据按固定种子拆成训练、dev、calibration、admission、final 五块；每块身份由实际内容决定。calibration 是允许反馈的开发数据；admission 和 final 受既有准入/终审隔离约束。官方 private 数据与最终 grader 留在外部试跑控制器中。

候选是一个由模型生成的 Python 程序。每个候选只生成并训练一次，产出固定的验证预测和官方公开 test 预测。dev、anchor 和 gate 重评分同一份预测，避免把重新生成或重新训练产生的随机变化误当成候选质量变化。验证行打乱并匿名化，候选程序不接收 split 标签和验证答案；答案只由受信任的评分器使用。

分类任务用 dev accuracy 作为探索代理，用 calibration 的负 log loss 作为 anchor 目标。回归任务用 dev 的负平均绝对对数误差作为代理，用 calibration 的逐目标负 RMSLE 均值作为 anchor 目标。两套指标都统一为越大越好，但量纲不同；只比较相应指标的同口径结果，不直接相减。

官方最终 grader 只在所有对照组的提交都冻结后运行。它产生的原始分数、奖牌及 private 信息不得反馈给后续搜索、记忆或其他对照组。内部 final split 的终审与这次官方外部评分是不同的证据。

生产试跑在首次调用模型之前核验完整评分环境。`official_root` 必须是锁定 revision 的干净 Git checkout；实际导入的 `mlebench`、`registry`、`data`、`grade` 模块必须来自该目录，并记录源码 SHA-256。每个任务的 public/private 目录、answers、gold submission 和 sample submission 必须符合官方 Registry 路径与普通文件要求；缺少私有评分答案不能留到花费完模型预算后才发现。

preflight 按受保护 `checksums.yaml` 对 public/private CSV 文件清单逐个重新计算官方 MD5，并另存 SHA-256 与相对路径，不依赖修改时间缓存，也不把标签内容写入试跑 spec。开始前、每个 agent 启动前和每次官方最终评分前都重新核对这一身份；源码、评分答案或准备数据变化会阻断后续付费调用/评分。测试注入的 fixture grader 明确标记为测试证据，不通过这一分支生成生产成绩。

## 两个对照组

| 组 | 搜索方式 | 共用约束 |
| --- | --- | --- |
| `baseline` | 基础 greedy 配置，不启用 anchor 和种群 | 同一模型、数据内容、种子、代码生成/执行器、评分定义、token 上限和运行时限 |
| `full` | population、双亲 crossover、anchor、秩相关监控与有来源的负反馈 | 同一三层准入与物理预算；anchor 等附加操作也占用本组预算 |

这个比较测量整个组合带来的差异。单独归因记忆或种群的贡献，需要另设关闭单个模块的实验，不能由 baseline/full 两组直接得出。

“同预算”指预先声明的资源上限相同，不要求实际消耗正好相等。报告必须列出各组真实 token、墙钟时间和失败率；不补零未知费用，不用未提供的价格表推断美元成本。所有模型调用必须有独立用量回执，试跑控制器复核总量及实际模型身份。

调用证据包括开始、完成、请求摘要和费用回执。失败后仍保留已知用量；存在未完成或缺失费用的调用时，分别报告已知部分和未知状态，不能把已知部分当作完整总量。请求模型固定，实际返回模型也须在整个试跑矩阵中保持一致；别名不等于已证明相同的实际模型。

返回中缺少实际模型身份、模型发生漂移或调用证据损坏时，该运行不进入有效比较，整个试跑停止后续付费运行并保留剩余矩阵行。即使模型身份缺失，已经收到的合法 token 账单仍计入 `known_tokens`；费用已知与身份有效是两个不同状态。不能因为模型字段无效而抹掉账单，也不能把未取得费用的请求记成零。

## 试跑入口

准备锁定的官方 MLE-Bench revision、对应 Kaggle 规则授权和 prepared 数据后，在支持 Bubblewrap 的 Linux x86_64 上执行。模型 API key 放在环境变量中，不放到命令行或证据文件中。当前 CLI 要求显式指定模型和预算。

```bash
cd m0
python -m zoo.mle_bench_lite.pilot \
  --official-root /path/to/mle-bench \
  --data-root /path/to/prepared/data \
  --output-root /path/to/new/pilot \
  --model SAME_MODEL \
  --token-budget 60000 \
  --time-limit 3600 \
  --solution-timeout 300 \
  --iterations 6 \
  --seeds 1 2 3 \
  --tasks spooky-author-identification leaf-classification nomad2018-predict-transparent-conductors
```

上面的数字只是命令结构示例；实际试跑使用明确冻结的模型和预算参数。`--preflight-only` 用于先核对数据、协议和环境，不启动模型实验。每次运行使用新 output 目录；失败记录保留，不删除失败后只报告成功样本。

试跑保存 `pilot_spec.json`、每次运行的 `run.json`、审计证据、冻结提交和 `pilot.json`。报告标识 `subset_only=true`、`formal_benchmark_complete=false`，展示完整任务 × 种子 × 组矩阵，保留超时、缺提交、评分失败、模型不匹配和预算超限。只对实际完成并通过证据检查的结果作配对比较，不生成正式 22 题分数或 host-parity 结论。

## GitHub 云端入口

用户不必自备 Linux 机器。仓库的独立手动工作流 `.github/workflows/mle-pilot.yml` 使用 GitHub-hosted Ubuntu CPU runner；push/PR 的自动验收不会启动付费试跑。手动输入 `mode=preflight|run`、模型、每组 token 上限、运行时限、迭代数和 1–3 个种子。工作流固定上述三个任务，模型和预算不会自行选取。

`mode` 默认 `preflight`；模型和 token 上限必填。每次任务/种子/组默认最多运行 600 秒，三个任务 × 两组 × 1–3 个种子对应 6–18 次运行。预先声明的搜索时限总和不得超过 5 小时；工作流总时限为 6 小时，另覆盖准备和官方评分。token 上限按每次运行声明，预检同时列出整个矩阵的总额度；这不是美元费用上限。

在仓库配置 `MLE_MODEL_API_KEY`、`KAGGLE_USERNAME`、`KAGGLE_KEY` secrets，并先满足三个竞赛的规则授权；可用 `MLE_API_BASE` 变量指定兼容服务。凭据仅注入相应下载/模型步骤，生成程序不继承它们。`preflight` 会准备和验证数据，但不调用模型。

CPU 依赖由 `scripts/requirements-mle-pilot.lock` 固定版本和下载 hash，安装到沙箱可见的 `/usr/local/share` 环境；官方源码从固定 revision checkout 导入。普通 CI 另有 `mle-cloud-runtime` job：在独立环境实际加载这份依赖、三个任务注册和官方 grader，用合成数据完成 CSV 评分。该检查禁用网络调用、不需要 Kaggle/API 凭据，也不产生真实 benchmark 成绩。

官方 checkout 必须启用 Git LFS：三个 leaderboard 文件在 Git 中只是指针，未拉取实际对象会被 protected snapshot 校验拒绝。自动 runtime smoke 和手动试跑都检查对象的实际内容 hash，不跳过这一约束。

云试跑的完整数据与工作区留在 runner 内；公开 artifact 仅导出明确允许的摘要/计量字段，不上传官方数据、派生训练 CSV、候选工作区、完整日志或凭据。实际试跑状态以手动工作流与其报告为准，云端环境检查通过不代表试跑已经执行。

## 验收和当前边界

`test_mle_composed.py` 覆盖公开 Framework 的实际生成、固定预测重评分、anchor/负反馈/crossover 链路、数据和费用身份、失败关闭及 Linux 隔离；`test_mle_provider.py` 验证真实 HTTP 调用、返回模型身份、独立用量回执与未知费用失败关闭；`test_mle_pilot.py` 覆盖真实子进程的双组编排、先冻结后评分、同模型同预算协议和失败矩阵。Mac 的可移植机制测试与 Linux 的真实隔离测试分别统计。

v68 保留 v67 全部命令与超时，新增上述显式组。先运行 Mac `make check`、`make build` 和 `make verify-import`，再以同一提交通过 Linux 全量 CI，最后推进 main。最新结果见 [逐项清单](ABSTRACTION_ALIGNMENT.md)和对应 SHA 的 CI 证据。

本阶段不把配置接线和 fixture 测试当作真实成绩，不认证所有 22 个任务，也不宣称 baseline/full 差异具有统计显著性。完整 campaign 继续使用原有严格全矩阵协议，子集试跑没有放松其完整性要求。

真实试跑使用 Linux Bubblewrap/seccomp，Mac 的可移植测试仅运行受信测试代码，不提供等价沙箱。当前每候选训练一次，之后重评分；外层进程运行时限是实际截止约束，CPU 库线程数设置为 2，不等于 cgroup CPU/GPU/磁盘硬配额。单次模型请求可能因输入 token 超过预留，实际用量照实保留并停止新调用。中断且缺少终态的训练或模型调用拒绝自动重跑，不宣称任意断电恢复。
