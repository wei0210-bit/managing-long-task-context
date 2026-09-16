# 发布前对抗复审与修复

状态：`PASS_WITH_LIMITATIONS`。2026-09-16。

发布前独立审查最初发现 6 个 P1 和 1 个 P2：首次 import 前载荷篡改未被运行身份发现、CLI 可执行文件原地改写、宿主归档沿符号链接越界、超时后代继续运行、Lite `NOW.md` 符号链接越界、Strict 包内测试边界不自洽，以及深层 handoff JSON 抛出裸 `RecursionError`。候选在修复前停止提交和安装。

每项均先用真实行为测试重现错误，再做最小修复：

| 项目 | 修复后独立复验 |
|---|---|
| 载荷身份 | 首次 import 前篡改受控模块后返回 `RUNTIME_UNVERIFIED` |
| CLI 配置 | 原地改写绝对 argv 文件后返回 `HOST_CONFIG_PATH_CHANGED`，不启动 |
| 宿主归档 | observation/result 的父目录和目标 symlink 均 fail-closed，外部无写入 |
| 进程树 | timeout/output-limit 后代 marker 均未生成；POSIX 使用独立进程组终止 |
| Lite NOW | symlink 返回 exit 2 / `unknown` / `material=null`，不泄露外部内容 |
| 分发测试 | Strict 包排除两个依赖源码树的 root-only 测试；包内 434/434、0 skip |
| 深层 JSON | 10,000 层输入返回协议 `unknown`，不抛裸异常 |

主控完整回归：569/569，0 skip；显式注入已核验的 Strict 0.7.0 基线包，未把迁移测试 skip 算通过。源码树外完整包：Strict 434/434、Lite 64/64，均 0 skip；两包 `check-source`、build、verify 和 full doctor 通过。CI 已改为对两个构建包运行完整 `unittest discover`，不再只选模块。

独立复审结论：7/7 原漏洞路径均已关闭，可继续提交、安装、推送和创建 PR。

限制：上述证据来自本机 POSIX 合成夹具和临时完整包，不是远程 CI 回执；非 POSIX 分支不具备同等进程组保证；真实 Codex/Claude native-host 自动接管仍为 `NOT_RUN/UNKNOWN`，本次发布不得扩大宣称。
