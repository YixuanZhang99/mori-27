# AutoResearch 安全与来源审计（2026-10-29）

范围：静态审阅交接包及纯 Python BPF 决策模拟。未修改生产代码，未安装内核过滤器，未调用被审计 syscall，未执行真实漏洞利用。所有路径相对于项目根目录。

## 需优先修复：seccomp 的 x32 ABI 覆盖缺口

- 位置：`m0/core/executor/seccomp.py:72–85`。
- 原因：过滤器检查 `AUDIT_ARCH_X86_64` 后仅比较原生 x86_64 syscall 编号，未拒绝或完整处理 `__X32_SYSCALL_BIT`。x32 与 x86_64 使用相同 audit arch。
- 复现：`python3 docs/review/seccomp-probe.py m0`。脚本读取现有字节码，解释其中的 LD/JEQ/RET 指令，不向内核安装或执行该过滤器。
- 本次模拟：native `add_key`、native `ptrace` → `ERRNO_EPERM`；x32 `add_key`、x32 `ptrace` → `ALLOW`；不同 audit arch → `KILL_PROCESS`。
- 结论边界：已确认 **BPF 决策覆盖缺口**。实际危险调用是否可执行取决于内核是否支持对应 ABI、权限及其他隔离层；本次没有验证真实 Linux 内核利用，也没有验证 Bubblewrap 沙箱逃逸。
- 建议：发布到执行不可信代码的环境前，拒绝 x32 syscall bit 或明确完整支持该 ABI，并增加相关字节码测试和 Linux 集成测试；更改策略版本并保留 v57 历史记录。
- 依据：[Linux man-pages seccomp(2)，Filters 段](https://man7.org/linux/man-pages/man2/seccomp.2.html)。该段明确说明两种 ABI 共用 arch，denylist 必须处理带 x32 bit 的编号。

## 资源和恢复边界

- `external.py:64–92` 的 `resource_policy` 默认为空；`resources.py:8–14` 只提供可选单进程限制，不能称为 cgroup 总配额。
- `process.py:108–110` 全量读取 stdout/stderr，`external.py:208–210` 全量读取 JSON 响应。建议对输出、响应、持久化目录设定上限；本次未通过生成大文件测试此风险。
- `x1/store.py:17–32` 是应用层 JSONL 追加 API，没有进程间锁、fsync 或坏尾行恢复；`process_wrapper.py:32–35` 使用 replace 但没有 fsync。已有 owner-crash 测试不能外推为断电、磁盘损坏或多 owner 并发安全。

## 已有保护和明确的信任边界

- `sandbox.py:50–79` 实现 Bubblewrap namespace 隔离、清空环境、移除 capability、只读系统/保护目录。`external.py:77–85` 默认启用并在缺少 bwrap 时失败关闭，需显式 `None/False` 才关闭。
- 外部命令通过 argv 传递，不经过 shell。`workspace.py:24–35` 拒绝绝对路径、`..`、`.git` 和受治理路径中的符号链接。
- `proposal.py:3–7,176–183,214–225` 的 proposer 是受信适配器，继承网络及环境；direct-prctl 不提供文件系统、网络或凭据隔离，fallback 也不在此证书范围。

## 包与发布来源

- 原始包：1,048 个文件，40,890,087 字节。未找到常见 `.env`/私钥/credentials/secrets 文件；扫描不大于 2MB 的可解码文本中的 GitHub/OpenAI/AWS 密钥和私钥头模式未命中。这是启发式检查，不能证明不存在任意秘密。
- 原包包含 `m0/vendor/openevolve/.git`。直接添加可产生 gitlink；建议将 vendor 作为普通源码导入，把嵌套 Git 元数据保留在本地原包。
- 核验到 OpenEvolve 上游 `https://github.com/codelion/openevolve.git`，HEAD `5153a7d74ee615b7090ec52903629870ecdacdf1`，包内 `LICENSE` 为 Apache-2.0。
- 根目录没有 LICENSE；`papers/lfsrc` 参考源码未附独立许可证和锁定 commit，PDF/论文源码包也不能默认具有公开再分发许可。本次最终按用户确认采用公开化名仓库；未替整个包赋予统一开源许可证，来源核查仍是单独事项。
- 74 个 `.log`/`.jsonl` 中包含历史验收证据，不宜统一忽略全部此类文件。
- MLE-Bench Lite 和 RE-Bench 的 provenance/快照契约不能代替真实 benchmark 执行；v57 明确未执行外部 benchmark/provider campaign。审计没有产生外部基准分数。
