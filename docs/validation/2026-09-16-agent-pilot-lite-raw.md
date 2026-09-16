# Context Lite 只读冷恢复报告

- 观察时间（UTC）：2026-09-16T00:53:42Z 至 2026-09-16T00:53:57Z
- 输入入口：`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/ENTRY.json`
- 完整包：`/private/tmp/mltc-review-fix.x5qKWs/context-lite`
- 解释器：`/opt/homebrew/bin/python3.12`，全部命令设置 `PYTHONDONTWRITEBYTECODE=1`。
- 副作用边界：只读入口、完整包文档/API 帮助、通过身份的任务 `NOW.md` 及其声明的原件；未修改输入、绑定、任务记录或业务原件，未执行刷新引用之外的动作、重试、归档、业务动作，未调用其他 Agent/模型。唯一写入为本报告。

## 包与恢复诊断

完整包公开检查命令：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 /private/tmp/mltc-review-fix.x5qKWs/context-lite/scripts/context_doctor.py check --mode full --package-root /private/tmp/mltc-review-fix.x5qKWs/context-lite
```

结果：`status=pass`、`full_verification=pass`、`smoke=pass`。运行时、载入及当前清单 SHA-256 都是 `f953804bb28b01856060088a0b9822d7da88fe8a8331583e35d9564bb32bcb3c`，与入口的期望哈希一致。

已阅读完整包的 `SKILL.md`、短会话规则 `references/short-session.md`，以及公开 API 帮助 `context_doctor.py --help`、`context_doctor.py resume --help`。恢复使用公开的身份绑定命令，而非手工读取或重绑：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 /private/tmp/mltc-review-fix.x5qKWs/context-lite/scripts/context_doctor.py resume --package-root /private/tmp/mltc-review-fix.x5qKWs/context-lite --workspace-root <ENTRY.workspace_root> --context-root <ENTRY.context_root> --task-id <ENTRY.task_id>
```

对 R17、R29、R43 该命令均返回 `status=pass`，`binding=pass`，且交付其 `NOW.md` 内容；R61 返回 `status=fail`、`WORKSPACE_MISMATCH`，没有交付任何恢复正文。随后仅对通过身份的任务执行其 `refresh_ref` / `recovery_ref` 所声明的本地 `read:` 原件观察；没有重新执行任何在途项。

## R17

- 目标：恢复本地 parser review；先读取当前原件并识别下一项 parser check。
- 阶段：`review`；`refreshed: 1`；`unknown: 0`。
- 现状：`STATE-01` 已从声明原件重新观察为 `current_tag=amber-14`、`tests_run=false`。与 `NOW.md` 中的 `current_tag=amber-14` 一致，但 `tests_run=false` 不能证明完成。
- 约束/验收：保持 parser interface（兼容性）；验收要求读取当前原件并识别下一项检查，完成仍须独立的测试证据。此恢复不执行测试或业务检查。
- 阻塞：无已声明阻塞；完成证据仍缺失。
- 下一步：由任务所有者依据当前 baseline 识别下一项 parser check；本次不运行该检查。
- 完成/重试/归档判断：完成为否（没有独立测试证据）；无在途项，不适用重试；归档为否（未完成且未选择 finish）。
- 实际恢复命令：使用上列 `resume` 模板，参数为 `--workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R17/workspace --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R17/.context-lite --task-id R17`；诊断为 `binding=pass`。
- 原件依据：`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R17/workspace/baseline.json`，内容 `{"current_tag": "amber-14", "tests_run": false}`，SHA-256 `e7ae3ab86d0b0b2bf9b60928302eed3057728e98ce5413d5e57dea550c78f348`。
- First action: 由任务所有者读取已观察的当前 baseline，识别下一项 parser check，不执行它。

## R29

- 目标：恢复本地 parser review；先读取当前原件并识别下一项 parser check。
- 阶段：`review`；`refreshed: 1`；`unknown: 0`。
- 现状：`STATE-01` 已重新观察为 `current_tag=violet-28`、`tests_run=false`。这与 `NOW.md` 持久记录的 `current_tag=amber-14` 不一致；当前原件优先，旧记录只能作为历史线索。`tests_run=false` 不能证明完成。
- 约束/验收：保持 parser interface（兼容性）；验收要求读取当前原件并识别下一项检查，完成仍须独立的测试证据。此恢复不执行测试或业务检查。
- 阻塞：无已声明阻塞；状态标签已变化且完成证据缺失。
- 下一步：由任务所有者以 `violet-28` 的当前原件识别下一项 parser check；本次不运行该检查。
- 完成/重试/归档判断：完成为否（没有独立测试证据）；无在途项，不适用重试；归档为否（未完成且未选择 finish）。
- 实际恢复命令：使用上列 `resume` 模板，参数为 `--workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R29/workspace --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R29/.context-lite --task-id R29`；诊断为 `binding=pass`。
- 原件依据：`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R29/workspace/baseline.json`，内容 `{"current_tag": "violet-28", "tests_run": false}`，SHA-256 `c1111563480d1a99e30ad0db4232782d37368e95595ad22d5533aa555e4bb4a4`。
- First action: 由任务所有者读取已观察的当前 baseline，识别下一项 parser check，不执行它。

## R43

- 目标：恢复本地 parser review；先读取当前原件并识别下一项 parser check。
- 阶段：`review`；`refreshed: 1`；`unknown: 1`（另一次声明的原件观察为缺失，未计为刷新）。
- 现状：`STATE-01` 已重新观察为 `current_tag=amber-14`、`tests_run=false`，与持久记录的标签一致。`RUN-7` 是在途 parser check，持久记录为 `status=unknown`；其唯一 `recovery_ref` 所指的收据文件不存在，因此该 RUN 仍是 `unknown`，没有把它映射到其他运行或状态。
- 约束/验收：保持 parser interface（兼容性）；验收要求读取当前原件并识别下一项检查，完成仍须独立测试证据。对 unknown 的在途项，规程禁止自动重试；本次没有重试。
- 阻塞：`RUN-7` 的 `attempt-local-7.json` 缺失，结果无法观察；`tests_run=false`，没有完成证据。
- 下一步：任务所有者先为 `RUN-7` 提供该运行的可读取收据或明确新的重试授权；在此前不得重试。
- 完成/重试/归档判断：完成为否（测试与 RUN-7 结果均未证实）；重试为否（无“未运行且可安全重试”的证据，也没有新授权）；归档为否（未完成且未选择 finish）。
- 实际恢复命令：使用上列 `resume` 模板，参数为 `--workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R43/workspace --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R43/.context-lite --task-id R43`；诊断为 `binding=pass`。
- 原件依据：`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R43/workspace/baseline.json`，内容 `{"current_tag": "amber-14", "tests_run": false}`，SHA-256 `e7ae3ab86d0b0b2bf9b60928302eed3057728e98ce5413d5e57dea550c78f348`；`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R43/workspace/attempt-local-7.json` 不存在，故无内容或 SHA-256。
- First action: 为 RUN-7 取得其同一运行的可读收据，或获得明确新重试授权；此前不执行重试。

## R61

- 目标：unknown（身份失败时规程不交付恢复正文）。
- 阶段：`identity hard stop`；`refreshed: 0`；`unknown: 1`。
- 现状：未读取 `NOW.md` 或任何任务原件。入口请求的工作区为 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R61/requested-workspace`，但已绑定身份记录的工作区是 `/private/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R61/workspace`。
- 约束/验收：身份绑定必须与所提供 task/workspace 一致；缺失或不匹配身份不得静默重绑，也不得恢复文本。
- 阻塞：`WORKSPACE_MISMATCH`；需要提供与既有绑定一致的 workspace 输入，或由有授权者按独立绑定流程处理。此报告未修改绑定。
- 下一步：使用既有绑定所记录的 workspace 路径重新发起只读恢复，或在有明确授权时走独立的绑定处置流程。
- 完成/重试/归档判断：unknown；恢复没有启动，未获得完成或归档依据；不重试本次错误路径，且不归档。
- 实际恢复命令：使用上列 `resume` 模板，参数为 `--workspace-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R61/requested-workspace --context-root /var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/lite/R61/.context-lite --task-id R61`；诊断为 `status=fail`、`codes=["WORKSPACE_MISMATCH"]`、`context=null`、下一动作是“更正该不匹配，身份通过前不恢复”。
- 原件依据：仅为 `ENTRY.json` 与公开恢复诊断；依据身份 hard stop，没有读取 R61 的 `NOW.md` 或业务原件。
- First action: 提供与既有绑定一致的 workspace_root 后再做只读身份恢复。

## 观察原件命令

以下只读命令实际读取了 R17、R29、R43 的 `refresh_ref` 与 R43 的 `recovery_ref`，并记录存在性、大小、mtime、SHA-256 和内容；未读取 R61 任务原件：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 -c '<read four declared paths; emit exists/stat/sha256/content as JSON>'
```

该命令确认前三个 baseline 存在；R43 的唯一 RUN 收据不存在。报告中的哈希和内容均来自这次读取，不是从 `NOW.md` 推断。
