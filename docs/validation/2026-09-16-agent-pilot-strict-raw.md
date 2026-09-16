# Context Strict 只读恢复报告

时间：2026-09-16 00:54 UTC。范围仅限本组 `ENTRY.json`、指定完整 Context Strict 包的 `SKILL.md`、`references/runtime-identity.md`、公开 CLI 帮助、每个已通过身份检查任务的必要工作区原件。未读取主仓库、旧聊天、其他组或评分材料；未修改输入、绑定、上下文、原件或业务状态；未调用其他 Agent/模型。唯一写入是本报告。

## 身份与方法

- 完整包：`/private/tmp/mltc-review-fix.x5qKWs/context-strict`，`skill_version=0.8.0`。
- `ENTRY.json` 规定的期望 manifest SHA-256：`cbd3499c536c1f6800b45b26c73fb19a7848e1ae7a11fa897fbeb5d22d3550d3`。
- 解释器：`/opt/homebrew/bin/python3.12`；所有 Python 调用设置 `PYTHONDONTWRITEBYTECODE=1`，并为 Strict 显式设置 `PYTHONPATH=/private/tmp/mltc-review-fix.x5qKWs/context-strict/src`。
- 使用公开的 `context_doctor.py check --mode identity` 后紧接 `context_doctor.py resume`。这是恢复规范要求的身份检查路径；未运行 `--mode full`，因为它是安装/更新或包健康调查的全量诊断，不是绑定任务的每轮恢复操作。

实际调用的公共恢复命令（`BASE=/private/tmp/mltc-review-fix.x5qKWs/context-strict`，每行实际均带前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$BASE/src /opt/homebrew/bin/python3.12 $BASE/scripts/context_doctor.py`）为：

```sh
check --mode identity --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R17/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R17/workspace --task-id R17
resume --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R17/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R17/workspace --task-id R17
check --mode identity --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R29/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R29/workspace --task-id R29
resume --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R29/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R29/workspace --task-id R29
check --mode identity --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/workspace --task-id R43
resume --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/workspace --task-id R43
check --mode identity --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/requested-workspace --task-id R61
resume --package-root $BASE --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/context --workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/requested-workspace --task-id R61
```

R17、R29、R43 的两条命令均退出 `0`：`package_manifest=pass`、`runtime_baseline=pass`、`binding=pass`，当前、加载与绑定期望 manifest 均为上述 SHA-256；identity 模式按设计为 `full_verification=not_run`、`smoke=not_run`。R61 的两条命令均退出 `1`，代码为 `WORKSPACE_MISMATCH`，`resume` 返回 `context: null`。

## R17

- **目标**：恢复本地 parser review；唯一验收项 AC-1 是“读取当前原件并识别下一项 parser 检查”，所需证据类型为 `test-report`。
- **恢复现状**：身份与绑定通过，返回 context version 3、contract version 1；最新 checkpoint 为 `review`，下一步为读取当前 baseline 并识别下一项 parser 检查。没有 verified facts、冲突、假设或 checkpoint blocker。
- **原件依据**：读取 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R17/workspace/baseline.json`，内容为 `{"current_tag": "amber-14", "tests_run": false}`。工作区文件清单仅有该 `baseline.json`，没有 `test-report` 原件。该值与恢复包中的历史 observation `current_tag=amber-14` 一致。
- **约束/验收**：必须保持 parser interface；本次为只读恢复，完成需要单独的测试证据。当前 `tests_run=false` 且无 required `test-report`，因此 AC-1 的完成证据为 **unknown/缺失**，不得判完成。
- **阻塞**：没有身份阻塞；缺少测试报告，且“下一项 parser 检查”的具体技术内容未由已允许读取的原件给出。
- **下一步**：在获授权的执行会话中，先根据当前原件确定 parser 检查，再产生并由验收流程解析 `test-report`；不得把本次恢复本身当作完成证据。
- **判断**：完成=否；重试/继续=可以，但仅作为新的受控、授权执行，不是对任何外部操作的盲重试；归档=否，验收未满足。

## R29

- **目标**：恢复本地 parser review；AC-1、所需 `test-report` 与 R17 相同。
- **恢复现状**：身份与绑定通过，返回 context version 3、contract version 1；checkpoint 为 `review`，无已登记 blocker、verified facts、冲突或假设。
- **原件依据**：读取 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R29/workspace/baseline.json`，内容为 `{"current_tag": "violet-28", "tests_run": false}`；工作区文件清单仅有该原件，不含 `test-report`。恢复 context 的历史 observation 却写为 `current_tag=amber-14`（创建于 2026-09-16T00:19:27.878700+00:00）。
- **约束/验收**：保持 parser interface；只读恢复不能代替 required test evidence。原件与承重 observation 不一致，且没有测试报告；当前状态和 AC-1 完成均为 **unknown**，不得以历史摘要覆盖当前原件。
- **阻塞**：历史 observation 与当前原件不一致，必须由上下文发布者/受控流程记录并消解；缺少 `test-report`。
- **下一步**：停止依赖 `amber-14` observation；由有写入授权的一方基于该当前原件重新观察/解决冲突，再决定具体 parser check 并获得测试报告。本次不修改 context。
- **判断**：完成=否；重试/继续=不应直接重试，须先解决原件与 observation 的不一致；归档=否，验收和状态都未闭合。

## R43

- **目标**：恢复本地 parser review；AC-1 需要 `test-report`。
- **恢复现状**：身份与绑定通过，返回 context version 3、contract version 1。checkpoint 为 `review`，登记 blocker：`RUN-7 attempt_id=attempt-local-7 outcome=unknown`，并指向 `workspace/attempt-local-7.json`。
- **原件依据**：读取 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/workspace/baseline.json`，内容为 `{"current_tag": "amber-14", "tests_run": false}`，与历史 observation 一致。工作区文件清单仅列出 `baseline.json`；尝试读取 checkpoint 指向的 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R43/workspace/attempt-local-7.json` 返回“无此文件或目录”。
- **约束/验收**：保持 parser interface；只读恢复，完成需要单独 `test-report`。`tests_run=false`、所需报告缺失，且既有 attempt 的收据原件不可读；完成为 **unknown**，不能判 pass 或 fail。
- **阻塞**：`attempt-local-7` 的权威结果不可验证；不得从 “outcome=unknown” 推断失败，也不得在缺少收据时盲重试，避免重复执行。
- **下一步**：由有权限的执行/发布者查明或恢复该 attempt 的权威收据及幂等状态；若明确未执行且获授权，才创建新的受控测试运行并提交 `test-report`。
- **判断**：完成=否；重试=否（当前禁止盲重试）；归档=否，存在未解决的 unknown blocker 与未满足验收。

## R61

- **目标/约束**：入口请求从 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/requested-workspace` 恢复；只读恢复必须先通过显式 workspace binding，身份失败按 Strict 停止。
- **恢复现状与诊断**：绑定中封存的 workspace 是 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/strict/R61/workspace`，与入口给出的 `requested-workspace` 不同。identity 检查确认包 manifest 与 runtime baseline 正常，但 `workspace=fail`、代码 `WORKSPACE_MISMATCH`；其报告的 `next_action` 是“Correct the reported mismatch; do not resume until identity passes.”。`resume` 因此返回 `context: null`。
- **原件依据**：严格 hard stop 已触发；未读取 R61 工作区原件、上下文事件或其他材料，避免从未绑定路径恢复或静默重绑。
- **阻塞**：已确认的 workspace binding 冲突；不是可忽略的缺失证据。
- **下一步**：由发布者明确哪一个绝对工作区才是该 task 的合法目标；如确需迁移，走显式审核的迁移/新版本流程，保留旧绑定与任务材料。不得由恢复者运行 `init-binding` 或改写现有绑定。
- **判断**：完成=否/unknown；重试=否，直到身份检查通过；归档=否，身份冲突尚未处理。

## 边界与结论

本次仅证明 R17/R29/R43 的“包—进程—任务绑定”可恢复，不证明业务、parser 检查或验收完成。R29 的当前原件与历史 observation 冲突，R43 的 attempt 收据缺失，均保持为 unknown；R61 严格停止。未进行任何业务动作、外部调用、重绑、测试、修复或归档。
