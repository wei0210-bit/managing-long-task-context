# E1-02 执行者报告

状态：源码机制与定向验证已交主控独立复验；未提交、未部署、未运行真实宿主或业务动作。E2 分发同步仍未解决。

## 实现边界

- `prepare_handoff` / `cancel_handoff`：锁外进行可信 authorizer 与 #16 完整 verifier 检查；短锁内复读有界权威日志、合同、记录和引用指纹后追加固定协议事件。
- 八个既有写入口：协议历史存在时均要求 runtime-only `runtime_identity` 与 `write_authorizer`；prepared 仅允许带具体 work item 的 child progress/result。取消后仍不允许裸写。
- 无交接历史的旧任务保持既有调用签名和行为。目录丢失而权威日志仍含 control event 时 fail-closed；无 handoff 目录时只流式侦测控制事实，不把 #16 的 2000 事件／8 MiB 读取预算施加给旧 item 历史。

## 验证实际结果

| 检查 | 实际结果 |
| --- | --- |
| `python3.12 -m unittest test_handoff_writes test_handoff_concurrency test_handoff_protocol -v` | 44 次独立执行通过，0.837 秒，退出 0；其中本执行者新增 16 条、首单只读 28 条；并发模块以模块别名复用夹具，不再重复收集写测试类 |
| `python3.12 docs/validation/e1_02_controller_probes.py -q` | 18 通过，0.330 秒，退出 0 |
| `python3.12 docs/validation/e1_01_controller_probes.py -q` | 10 通过，0.052 秒，退出 0 |
| legacy Truth Source fast path 定向测试 | 1 通过，0.008 秒，退出 0 |
| `python3.12 -m unittest discover -s tests -q` | 本窄修复前最近一次为 438 次、32.612 秒；437 通过，1 个预存 E2 分发比较失败。当前修复后的完整回归留给主控最终复验，不能据此声称当前全绿。 |
| `git diff --check` | 退出 0 |

红绿摘要：首次 prepare 调用缺公开入口仅为 scaffold 缺失，不计行为红。行为红→绿保留为相同 prepare 幂等（初始返回 `HANDOFF_PREPARE_REJECTED: handoff control history already exists`）、相同 cancel 幂等（初始返回 `HANDOFF_CANCEL_REJECTED: handoff is not verifiably prepared and inactive`）、并发相同 prepare（初始第二调用因 capture 改变返回 unknown）、事件 fsync 后快照替换失败（初始误报 `confirmed_not_committed`）。后者现以有界权威事件重读：仅唯一匹配的已刷盘控制事实返回 `confirmed_committed`，不可重读则为 `unknown`。

## 冻结 AC 对照

1. 已覆盖：`test_prepare_persists_one_bound_event_without_activating`、W01/W02。
2. 已覆盖：W08/W08b/W11/W12，以及 prepare/cancel 的 `os.replace(snapshot.json)` 真实 I/O 故障边界；事件已 fsync 而快照更新失败时绝不回报确定未提交。
3. 已覆盖：并发相同 prepare、dispatch-first 令 prepare 拒绝，以及 `test_prepare_between_legacy_fence_and_writer_lock_fences_dispatch`。后者用合法 `str` 输入在 legacy fence 后、写锁前同步暂停；prepare 提交后恢复 writer，锁内重读检测已启用协议并拒绝，未写 `item-recorded`。
4. 已覆盖：首单 child progress/update/checkpoint 正例与 W05；越权 child 负例由主控 authority policy 覆盖。
5. 已覆盖：W04 的八入口无身份副作用前拒绝、W06/W10/W10b/W10c，以及任一 `handoff_activated` 控制事实（含不同 handoff id）均在直接 writer 调用 authorizer 前 fail-closed。
6. 已覆盖本单边界：cancel 成功、代次不变、W06/W09、已取消 handoff 的 validate 非 pass；activated 后的新身份／完整激活仍为 #18，直接 writer 在该状态统一拒绝。
7. 已覆盖：prepare/cancel 相同请求幂等、并发 prepare 与 W03；已有控制事实不能绕过本次 workspace/package 输入绑定或缺失宿主核验。只有已完成本次输入、授权、内容核验并进入 commit hook 后的异常，才会重读权威事件恢复已刷盘结果。
8. 已覆盖本单机制：首单 host lock handshake、W08/W08b 与 capture/commit 复核、dispatch-first 在 prepare authorizer 的锁外回调期间实际写入，以及 prepare-first 的锁内再核验。没有把外部旧 pass 复用于另一请求。
9. 已覆盖只读回归 28/28、独立探针 10/10，以及 2000／2001 条合法旧事件仍可写的兼容测试；截断或重复键旧日志拒绝而非声称没有控制事实。全回归唯一分发比较失败仍是 E2 留项。

## 未声明的证明

真实宿主、真实子进程启动/停止、自然使用、token/业务收益均为 UNKNOWN。本报告不把本地 synthetic 机制验证视为生产启用或分发包通过。

## 交接文件 SHA-256

- `src/managing_long_task_context/__init__.py`：`4dcac6ed1a40c348adf5cc050f86f61ec782c7817541a44995407e8e56c8824f`
- `src/managing_long_task_context/handoff.py`：`c9ddf7e010a6c95c28d5df12d9e4d0c94fb6eb8029d3a03b667a06e701d1bd1c`
- `tests/test_handoff_writes.py`：`e069f47bd82253e6bbc35e4ba4bdd6591c54bc440b8528c255ffa1e3fd0204d5`
- `tests/test_handoff_concurrency.py`：`87de8df694fac1498b5b9449f6c98df34ca85e05cbb586c1542480fd527256dd`
