# E1-03 独立进程恢复验证报告

时间：2026-09-15T10:00:30Z。范围仅为本地临时目录中的合成宿主；未安装、未提交、未推送、未部署、未调用模型或业务动作。

## 先前 append 实现的保留反例

在 v1.2 原 `_append_event_locked` 上，夹具用 `os.fstat(fd)` 对 `events.jsonl` 的 dev/ino 精确匹配 event fd。在完整 JSON newline 已 `flush`、真实 `os.fsync(fd)` 之前，注入 `OSError`。

- 子进程 stdout 到达 `before_event_fsync`；退出码却为 `0`，返回 `pass / confirmed_committed / generation=1`。
- 新 Python 进程只读 `handoff_status` 返回 `check_status=unknown`（没有 verifier）但 `commit_status=confirmed_committed, generation=1`。
- 这证明“可读的未 fsync append”被恢复路径错误当作提交。该失败证据未被随后 v1.3 绿测覆盖，也没有改成半行来规避。

v1.3 将控制事件限定为同锁内临时 events 文件 fsync 后 atomic replace canonical events；canonical replace 是本报告后续测试的线性化点。

## 实测结果

命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_process_recovery -v
```

初始 v1.3 运行 9/9 通过，14.122 秒，退出 0。主控审查发现失败路径回收缺口后，补入立即注册 cleanup 和显式阻塞 FIFO child 回收用例；复跑 10/10 通过，8.272 秒，退出 0。最后补入同一合法候选的不同请求 ID 竞争；复跑 11/11 通过，5.819 秒，退出 0。每个子进程 stdout 是可复核 JSON phase；父进程只在确认 phase 后使用 FIFO 屏障或 SIGTERM，没有 sleep 猜测时序，所有子进程均 wait/回收。

| 合同 AC | 实际独立进程证据 | 结果 |
| --- | --- | --- |
| AC1 | 正常 child `activate_handoff` 输出 pass、generation=1；events 中 activated=1；新进程 status 确认提交 | 通过 |
| AC3 | 两个 Python child 在命名 FIFO 屏障后竞争；activated=1、generation=1；同请求 replay bytes 不变 | 通过 |
| AC3 不同请求 | A、B 先各自用独立 config 文件启动并输出 `ready`，确认分别加载 `REQ-PROCESS-A/B` 后才释放同一 FIFO；同一合法 target 仅一条 activated/gen=1，胜者回执 committed，败者不称自己的请求已提交 | 通过 |
| AC6 prepublish | `before_temp_fsync` 注入 OSError，和 `after_temp_fsync_before_publish` FIFO 后 SIGTERM；严格旧 canonical log 令新进程 status 为 `confirmed_not_committed / generation=0` | 通过 |
| AC6 postpublish | `after_events_publish` SIGTERM、snapshot replace OSError、snapshot replace 后响应前 SIGTERM；新进程 status 均为 `confirmed_committed / generation=1`，activated=1，无重复 | 通过 |
| AC6 损坏 | 完整 prepared 状态后追加半行；新进程 status `unknown`，且全部任务文件 bytes/mtime 不变 | 通过 |
| AC7 | 正常提交后由 20 个新 Python process 调用 status；均 `check=unknown, commit=confirmed_committed`，任务文件 bytes/count/mtime 不变，`business_actions=0` | 通过 |
| 进程回收 | child spawn 后立刻登记 cleanup；显式验证 FIFO 阻塞 child 被父进程 cleanup 后已退出且 stdout reader 已结束 | 通过 |

关联合同命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_activation test_handoff_process_recovery test_handoff_writes test_handoff_concurrency test_handoff_protocol -v
```

56/56 通过，13.216 秒，退出 0。E0 fixture 固定检查通过（0.044 秒）；`git diff --check` 退出 0。

## 限制

这是本地合成宿主和真实文件 I/O 边界的机制证据，不证明机器掉电、目录项断电恢复、真实宿主身份、自然使用、模型稳定性或 token 成本。后五项均为 UNKNOWN/NOT_RUN；业务动作计数为 0。

验收时 SHA-256：process tests `5b93b9f351c5619ffef360b8160b119f11586287a92094640d02e39169427a20`；fixture `622c47aaa989739fcfaff44072f39a0412938d24f4726e7148f66cda0c0a8e84`；core `bc3b1959e25987321cc0ef09a24a8f88d981dc1501beff01e01172805ce918b6`；handoff `d772cd37787c8e481233fb54b4c4e4aad56b61dc903b69ce10c0d562864a97d1`；合同 v1.3 `1b8aa9154f36e7495c27d598a3ea0bf666dc9fe599dbab18f7cb824ab2ee7e04`。
