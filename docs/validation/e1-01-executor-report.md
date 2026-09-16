# E1-01 执行报告（待主控复验）

执行合同 SHA-256：`39b770f90ae67a16b7fbeddc2e98269217c284e405aa010cf0800d921407fc45`。

已实现仅限两条只读 seam：`validate_handoff` 和 `handoff_status`。协议记录固定读取
`<base>/<task-id>/handoff/<handoff_id>.json`；不会创建目录、写事件、授予控制权或判定业务完成。
宿主核验器仅能从 keyword-only 的 `handoff_verifier` 注入，且必须有 `verify(request)`；JSON 从不产生 callable。

## 实测

| 命令 | 结果 |
| --- | --- |
| `tests/handoff_spec.py … --expected-manifest-sha256 435e…52a7b` | 退出 0；fixture 通过；产品/模型/自然使用均 `NOT_RUN`；0.0298 秒 |
| `python3.12 -m unittest test_handoff_protocol -v` | 退出 0；12 通过、0 失败、0 跳过；0.189 秒 |
| `python3.12 docs/validation/e1_01_controller_probes.py -v` | 退出 0；主控独立公共 seam 反例 4 通过；0.017 秒 |
| `python3.12 -m unittest discover -s tests -q` | 退出 1；408 运行、1 失败；失败仅为 `test_distribution_matches_maintained_sources`，它要求 E2 拥有的 Strict 分发副本同步 `__init__.py`；本单未修改该副本 |
| `git diff --check` | 退出 0 |

红绿逐条证据见 [e1-01-executor-runs.json](e1-01-executor-runs.json)。

## 案例映射

| 合同项 | 公共 seam 测试 | 当前证据 |
| --- | --- | --- |
| 1、7 | `test_valid_complete_prepared_record_passes_without_writing_or_granting_control`；`test_twenty_fixed_readonly_queries_are_semantically_and_bytewise_stable` | 合成可信宿主读取真实临时原件；validate 返回 `not_attempted`；20 次内容、数量与 mtime 不变 |
| 2、3 | `test_verifier_reference_with_matching_id_but_wrong_digest_cannot_pass`；`test_duplicate_record_key_is_unverifiable_even_when_last_value_looks_valid`；`test_missing_runtime_verifier_and_missing_authoritative_log_remain_unknown`；三项 controller probes | 错摘要、错绑定、无 verifier 均为 unknown；不把类型相等或 JSON 形状当身份/许可证明 |
| 5、6 | `test_missing_runtime_verifier_and_missing_authoritative_log_remain_unknown`；`test_foreign_task_event_in_this_authoritative_log_cannot_be_ignored`；`test_corrupt_truncated_and_unknown_authoritative_events_are_unknown`；`test_exact_8mib_log_is_read_and_one_extra_byte_is_rejected` | 缺日志、坏 UTF-8、截断、未知/跨任务事件不从 snapshot 或旧结论放行；精确 8 MiB 通过，超 1 字节 unknown |
| 8 | `test_changed_host_evidence_requires_a_second_runtime_verification`；controller probe `test_final_callback_cannot_leave_changed_evidence_passing` | verifier 在共享锁外执行；最后回调后真实 file 引用原件改变，会在最终指纹重观测中阻断 |

## 明确未完成/未验证

- E0-178～180 的精确 8 MiB 等于/超过已实测；8 MiB 前、最大 items 和 5 秒边界仍未逐项实测。
- 过期/撤回授权及 workspace/package 的各单独负例尚未逐项测试。
- 真实宿主、真实性、模型冷启动、自然使用与 token 收益均未验证；所有正例宿主均为标记为 synthetic 的隔离测试双。
- E2 分发同步尚未授权，本轮全回归因此不是全绿。该失败未修复、未掩盖。

本报告不是主控验收结论。

## 交接更新：停止点（未验收）

本执行轮最后一次稳定针对性运行：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_protocol -q
Ran 17 tests in 0.248s
OK
```

主控独立探针的最近一次已知结果为 8/8 通过；其命令为：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_01_controller_probes.py -v
Ran 8 tests in 0.033s
OK
```

这些分母只表示当前 17 条执行者测试和 8 条主控探针，**不代表 E1-01 全部验收已通过**。

### 已稳定完成的局部项

- 公开 seam、runtime-only verifier、严格 task/base/handoff 输入、record/contract/prepared 绑定、版本类型、外层/内层事件类型、事件重复键及非有限数值、Z 整秒 UTC、三态和最后 callback 后 file 指纹复核均有当前测试或主控 probe。
- 新路径的日志读取已按字节、单条、事件数、读取 deadline 限制；新严格 replay 已逐事件检查 deadline 和 items，而未改旧 `_rebuild_snapshot` 的默认兼容行为。
- 全量旧回归的最后一次实测为 `Ran 408 tests`、仅 E2 分发同步断言失败；本单未修改分发副本。

### 不得计入 AC5/AC6 的失效夹具

`test_exact_8mib_log_is_read_and_one_extra_byte_is_rejected` 和
`test_maximum_reachable_event_count_passes_and_one_more_is_unknown` 当前使用的
`item-recorded` padding/空 payload 并非完整合法 item 事件；+1 情形还追加裸字节而同时引入截断。
因此它们不能证明“完整有效输入”下的 8 MiB−1/等于/+1、单条、items 或资源原因语义，后续执行者必须替换为合法 item 模板并保留可解析三点夹具；本轮不得以它们验收 AC5/AC6。

### 必须接续的未完项

- 用合法 item 模板重建 AC5/6：8 MiB−1/等于/+1、64 KiB−1/等于/+1、最大可达 items、重建期限与稳定 `HANDOFF_RESOURCE_*` 原因；严格 replay 必须拒绝不完整 item payload，且不得改变旧 API。
- 补授权撤回、引用路径/symlink、业务 blocker 的完整读取但不改变业务 gate，以及不持锁阻塞 writer 的进程级证据。
- 主控新复现：同一权威日志加入另一合法外形的 `HO-OTHER` `handoff_activated`（generation 8）后，查询 `HO-001` 仍 pass/generation 7。未实现控制状态不得忽略该事件；后续应 unknown 阻断并测试，不能声称此缺陷已修复。
- 重新运行冻结规格、针对性、主控 probes 及必要旧回归，更新精确分母、原始输出和 E2 分发依赖说明。
