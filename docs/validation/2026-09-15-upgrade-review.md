# E1–E6 升级代码审核

结论：**CHANGES_REQUESTED / DONE_WITH_CONCERNS**。四项 P2 缺陷已由主控在 Python 3.12.13 下复现；本轮只新增审核工件，没有修产品源码、安装、提交或发布。建议修复后复审再考虑扩大试用。

## 范围与身份

- `/review` 审核：`codex/short-session-remaining` 工作区中 E1–E6 的 tracked diff 加 untracked 新模块；不是只看 E4–E6 最后几行。生成包副本按单一维护源去重检查。
- 比较基线：已刷新 `origin/main`，与 HEAD 同为 `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`。没有对应 PR。当前代码尚未提交，HEAD 不包含这批升级。
- 主计划 v0.37 SHA-256：`e921718df9a04d3373819369429e1041aa201a26fb92cd28ec8cc9649117fbe2`。本报告补充后续发现，不抹掉历史绿色或修改冻结预期。
- `host_records.py` SHA-256：`31cbf86fcde2fda4d40dbe3b0e327e16fa97510472079b6854dd7356c12465e8`。
- `host_codex_cli.py` SHA-256：`3831ce1c7ee21f7f466edccce59e10cf843d00c7456b0e0f67b9fd654435e5eb`。
- `scripts/context_usage.py` SHA-256：`fffdfd4617f682de89e430714c2c339d3412b21be300892c4edefe58972f8de4`。

## 发现

### R1 — [P2] 首次取消交接后原主控无法继续派单（置信度 10/10）

位置：`src/managing_long_task_context/host_records.py:752`，锁内同样限制位于 803 附近。触发代码为 `or fence.get("phase") != "activated"`。

实际公开调用 `prepare_handoff → cancel_handoff` 均返回 `pass / confirmed_committed`，权威日志保留两事件、代次仍为 0；真实授权路径返回 `phase=cancelled, role=controller` 且关联原 source session，但 `HostTaskLedger.reserve(start_child)` 返回 `unknown / HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED`，无启动许可、无日志变化。取消恢复规则 H08 与宿主派单状态判断不一致。`resume_child` 共用该限制，公开探针实际验证的是 start_child。

最小修复：两处资格判断都接受已核实原主控的 cancelled 状态，仍保留身份、代次、授权和锁内重检；prepared 继续禁止新派单。补首次取消后 start/resume 正例，以及错误身份、旧代次、prepared 负例。不应通过放宽所有阶段解决。

### R2 — [P2] 同一 JSON 行重复 thread_id 隐藏线程冲突（置信度 10/10）

位置：`src/managing_long_task_context/host_codex_cli.py:591`：`event = json.loads(raw_line.decode("utf-8"))`。

固定 Python 子进程输出同一对象内两个不同 thread_id，最后一个与 resume 请求一致。默认 JSON 解析只保留最后一个，公开 `resume_child` 返回 `launch_status=exited, commit_status=confirmed_committed`，记录了一条观察；按文档冲突应为 execution_unknown。现有负例只覆盖跨行冲突。

这不是业务完成被放行：`check_status` 仍为 unknown；这里是线程身份冲突被丢弃。实证使用现有 FakeLedger，未宣称验证了真实台账随后解锁或真实宿主行为。程序中 `_observation_proves_ended` 会消费这种线程匹配/退出观察，故应在解析边界保留冲突。

最小修复：解析时拒绝重复键，补 start/resume 的同行冲突反例，断言 execution_unknown、thread_id 不可用且仍记录原始观察。

### R3 — [P2] 深层 JSON 在执行后抛异常，跳过观察落盘（置信度 10/10）

位置：`src/managing_long_task_context/host_codex_cli.py:592`，只捕获 `(UnicodeDecodeError, json.JSONDecodeError)`；调用 `_observation` 位于 209，发生在 `record_observation` 异常保护之前。

公开 resume 的固定子进程输出 10000 层数组、20087 bytes 的合法 JSON，低于 64 KiB 单行预算。Python 3.12.13 实测 RecursionError，已有 1 次预留、0 次观察，调用方拿不到结构化 execution_unknown，也没有走原输出归档。并非重复执行已被证实，而是已经执行后的诊断与恢复依据丢失。

最小修复：受限解析失败转为 unknown，同时继续有界 stdout 与退出证据归档，不能用宽泛异常后伪造成功。补真实 fixture 子进程的深度异常测试。

复核纠正：最初 1100 层在 Python 3.9.6 复现，但在项目 Python 3.12.13 未复现；保留这一事实，正式探针用 10000 层，两环境均复现，未改解释器递归上限。阈值不应写成跨环境常量。

### R4 — [P2] 压力采样遇到不可编码字符串时 CLI 崩溃（置信度 10/10）

位置：`scripts/context_usage.py:461`，缺量里程碑分支同样位于 417：`hashlib.sha256(encoded.encode("utf-8")).hexdigest()`。

输入 JSON 使用 ASCII 转义的孤立代理字符 `\ud800` 作为 session_id，解析可以接受，但 canonical 指纹编码抛 UnicodeEncodeError。真实 pressure CLI 退出 1、stdout 为空、stderr traceback；约定应退出 2 并输出结构化 unknown。此问题影响两包共用工具，导致本次提醒/观察无法被正常消费，不是授予了切换权限。

最小修复：统一 canonical/UTF-8 边界拒绝不可编码输入，覆盖正常压力和缺量里程碑两分支、session/sample/额外字段与真实 CLI。无需新增框架或提示词。

## 本轮实际验证

| 验证 | 实际结果 | 边界 |
| --- | --- | --- |
| CLI / ledger / usage / Lite handoff 原有测试 | 70/70，17.562 秒 | 本轮主控重跑；不是完整 550 项回归 |
| Strict / Lite check-source | pass，67 / 17 文件 | 文档、API、文件一致性 |
| 两份已有完整候选包 verify | pass | 身份完整不代表上述行为无缺陷 |
| git diff --check | pass | 仅格式检查 |
| 新公开取消/派单探针 | R1 复现 | 真实产品路径；身份/宿主为合成夹具 |
| 新输入探针 | R2–R4 复现 | 实际 Python 子进程；CLI 两例使用 FakeLedger |

Strict manifest：`a6dd801dd5595c75d02f2b7ebd44f128fbf3150950cd53075a88dac47309b18c`，0.8.0；Lite manifest：`23ba12cd500f7247317d898e2fbf720be068bec2d854c3f0eedb6e792bfce62f`，1.4.0。已验证包位于 `/private/tmp/mltc-remaining-controller.hDcO2Z/context-{strict,lite}-final`。存在性和内容已核实，临时目录后续可能被清理。

复跑：从候选工作区执行以下命令。两个 probe 的退出 0 表示**缺陷成功复现**，不是修复通过；转成回归测试时必须按期望安全行为断言。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_cli test_handoff_host_records test_context_usage test_context_lite_handoff -q
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/upgrade_review_cancel_probe.py "$PWD"
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/upgrade_review_input_probes.py --repository "$PWD"
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 scripts/skill_package.py check-source --source skills/context-strict
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 scripts/skill_package.py check-source --source skills/context-lite
```

## 计划完成度与审核限制

- E1–E3：本地协议、分发、CLI/台账已经实现；R1–R3 是已有实现的真实缺口。E4 只实现能力报告/拒绝入口，真实原生接管仍 BLOCKED，不冒充完整宿主适配。
- E5：Lite 本地 flush/cold-check 已有；仍不证明模型冷启动理解或允许自动归档。E6：有计量解释与压力建议工具，R4 待修；无真实 token 收益。E7：条件未触发，继续后置，不以扩大范围补偿这次缺陷。
- 主控结合两个独立专项 Agent（测试、可维护性）复核。额外 security 专项因 Agent 线程上限启动失败；没有六专项全部完成、独立外部 Claude/Codex 红队或全面安全审计的结论。未调用嵌套模型、真实宿主任务或付费 eval。
- 原始 550 项绿色属于历史验收，不代表本轮全量重跑；程序重复不证明模型稳定性。审核 token 成本未独立计量、收益 UNKNOWN。
- 排除用户原始资料、带 ` 2` 文件、.DS_Store 和无关既有改动。候选包不重新生成、不全局安装、不提交/推送。审核只新增本报告及两份复跑工件。

## 建议的下一步

仅修 R1–R4：先冻结四类期望，执行者定点修复，主控独立复验；随后全量回归及两包源码树外验证。身份边界、旧代次阻断、完成 gate 与未知不重试策略保持不变。不优先扩写说明或增加更多上下文记录，以有效、精致、经济为约束。
