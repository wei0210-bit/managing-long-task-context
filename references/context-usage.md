# Context usage 本地观察

`scripts/context_usage.py` 是只读、一次性的标准库工具。它不扫描目录、轮询、写台账、调用模型或提供方，也不会启动、终止、归档或接管任务。它只解释调用者明确传入的本地 JSON；`source_ref` 是出处标签，不是自动信任、计费账单或全任务覆盖证明。

## 两个公开函数

`summarize_usage(events)` 接收最多 1000 条已规范化事件。每条必须包含：

- `event_id`、`session_id`、`task_id`、`provider`、`model`、`source_ref`：非空字符串；
- `mode`：`delta` 或 `cumulative`；
- `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_write_tokens`：非 bool 的非负整数；
- `cache_accounting`：`included` 或 `separate`；
- `observed_at`：带时区的 RFC3339 时间。

`included` 表示 input 已含 cache，两个 cache 计数不得超过 input；`separate` 才把 cache 加到 `total_tokens`。delta 按唯一 `event_id` 加一次；完全相同的重复记录去重，内容不同的同 ID 使整体成为 `unknown`。cumulative 只采用同一 session 的最后一个单调快照，不累计每次快照。一个 session 中混用 mode、provider、model、cache 口径或 task 会使整体成为 `unknown`。主/子会话各自保留，绝不因 task 相同而合并。

成功结果的 `total_tokens` 仅是完整、可核查的**已提供观察集**总量，绝不是当前窗口使用量或全任务成本。`input_tokens` 保留调用方报送的原始 input；`normalized_input_tokens` 仅为计算总量而把 `separate` cache 纳入 input 的口径，避免把两者混为同一数字。`measurement: observed` 只表示调用方报送的观察，不表示工具独立实测。`task_total_tokens`、`cost`、`skill_attribution` 一律为 `null`；空列表表示没有 usage 而为 unknown，不能以字符数补算；完整字段的明确零计数仍可报告 0。

`evaluate_pressure(sample, previous=None, *, now)` 只返回推荐，固定含有 `decision`、`reason`、`estimated`、`dedup_key`、`notify`、`automatic_action: false` 和下一份 `previous`。sample 必须包含 session/sample ID、观测和失效时间、`window_tokens`/`used_tokens`/`reserve_tokens`/`growth_tokens`、`basis`（`current-window` 或 `estimate`）及四个明确 bool：`safe_point`、`task_complete`、`execution_unknown`、`milestone`。

- 仅当安全点明确、任务未完成、执行不确定为 false，且 `window_tokens - used_tokens <= reserve_tokens + growth_tokens` 时，返回 `prepare`；`milestone` 不阻断有效的当前窗口建议。这是建议，不是执行动作。
- 过期读数只有在明确安全里程碑时才降级为 `milestone`；非安全节点、任务完成或执行结果不确定都为 `defer`。
- 缺失或非法的窗口数值（含超窗口）不计算百分比，也绝不返回 `prepare`。这是 E6 v1“缺量一律 unknown”的受限替代：仅当 session/sample ID、观测和失效 UTC 时间（观测不在未来）、全部四个 bool 安全字段都有效，且 `safe_point: true`、`milestone: true`、`task_complete: false`、`execution_unknown: false` 时，才给出一次 `milestone` 建议。缺身份/时间/安全字段、非 bool、伪造的 `cumulative` 当前窗口、完成或执行未知仍为 `unknown`，不能借该降级路径变绿。
- RFC3339 值会先安全换算到 UTC；越过 Python UTC 可表示范围的正/负偏移、无时区或坏时间均为结构化 `unknown`，不会产生 traceback 或部分总量。合法跨时区时间仍照常比较。
- `previous` 由宿主自有存储；仅同 session、同 sample、完全相同内容且此前 `notified: true`，才让 20 次重复观察的后续 `notify` 为 false。未通知的 defer 记录不会提前消耗后续到期安全里程碑的首次提醒；跨 session 不共享去重；同 sample 内容改变明确 `unknown`，不会被冷却掩盖。

## 有界 CLI

```sh
python3 scripts/context_usage.py summarize --input /absolute/path/usage.json
python3 scripts/context_usage.py pressure --input /absolute/path/pressure.json --now 2026-09-15T12:00:00Z
```

`summarize` 输入恰为 `{ "events": [ ... ] }`；`pressure` 输入为 `{ "sample": { ... }, "previous": { ... } }`，其中 `previous` 可省略。CLI 只读取显式、非符号链接的常规文件，最大 1 MiB / 1000 条事件。重复 JSON 键、NaN、非法 UTF-8、目录、符号链接、超限或未知文档形状均输出结构化 `unknown` 并以状态 2 结束；不会跳过坏行后继续产生部分结果。

这不是真实宿主、模型、自然项目、产品 token 节省、重试成本或费用的验证。上述无法从本地观察取得的项目均保持 `UNKNOWN`。
