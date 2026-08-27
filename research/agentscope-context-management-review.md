# AgentScope 上下文管理机制对照评审

## 结论

AgentScope 没有推翻已批准的双 skill 设计。`context-lite` 与 `context-strict` 继续保持运行时独立、由人手动选择、只共享最小交换格式，是合理边界。

AgentScope 最值得借鉴的不是某个 memory 后端，而是四个设计区分：

1. **任务恢复上下文不等于 Agent 运行态快照**。AgentScope 的运行态包含会话、压缩摘要、未压缩消息、当前 reply、权限、工具缓存、任务和 middleware 状态；`NOW.md` 或 Strict 的任务快照不可能替代它。
2. **checkpoint 必须在原对话消失后仍可独立理解**。相对时间、代词式指针和后台进行中的工作都要显式解析成稳定引用。
3. **多 Agent handoff 是一个可靠投递协议，不是一条自然语言消息**。至少要区分排队、消费、确认和失败，不能把“已入队”当成“对方已接收并完成”。
4. **消息事件、追踪数据和验收证据是三类东西**。运行事件与 OpenTelemetry 很适合调试和关联，但默认不能替代 Strict 的证据 resolver、独立验证和完成门禁。

建议在进入实现前对已批准设计做四处小修订，见“值得借鉴并应修订”。不建议引入 AgentScope 依赖、不建议共享底层引擎，也不建议把 AgentScope 的长期记忆或完整 Session 服务搬进两个 skill。

## 调研边界

- 研究对象：AgentScope 官方主仓库与官方文档。
- 源码快照：官方仓库 `main`，commit [`142c3411b6e7057fb3ef5cf49d7428e731210720`](https://github.com/agentscope-ai/agentscope/tree/142c3411b6e7057fb3ef5cf49d7428e731210720)，提交时间 2026-08-26。
- AgentScope 当前主线已是 2.0。本报告以 `docs.agentscope.io/versions/2.0.8dev` 和上述 commit 为准；只在 tracing 小节引用仍可访问的 1.x 教程，并用当前 2.0 源码交叉确认，不把 1.x Session API 当成当前实现。
- 对照文档：已批准的“双层长任务上下文 Skills”设计。
- 未使用二手文章、社区博客或其他框架实现。
- 本报告只提出修订建议，没有修改已批准设计或生产代码。

## 先区分四种状态

| 类型 | AgentScope 中的对应机制 | 本项目中的位置 | 是否可作为 Strict 完成证据 |
|---|---|---|---|
| 模型工作上下文 | summary、近期 messages、被 offload 的原始内容 | Lite 的高信号恢复摘要 | 否 |
| Agent 运行态 | `AgentState` 的 reply、permission、tool、tasks、middleware context | 由宿主 Agent 框架负责，本项目不保存 | 否 |
| 跨会话长期记忆 | Agentic Memory、ReMe、Mem0 | 两个 skill 默认都不自动写入 | 否 |
| 任务控制与证据 | AgentScope 没有同等强度的内建完成门禁 | Strict 合同、事实账本、resolver、validator、completion gate | 满足 resolver 与 validator 后可以 |

这个区分是本次评审最重要的边界。AgentScope 官方将 `AgentState` 明确定义为要持久化和恢复的运行态，其中包括压缩摘要、未压缩对话、reply context、permission context、tool context、tasks context 和 middleware context：[AgentState 源码](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/state/_state.py#L151-L265)。这比 Lite 或 Strict 的任务状态宽得多。

## 已经覆盖

### 1. Lite 已采用“高信号摘要，不保存整段聊天”

AgentScope 的上下文分为 system prompt、压缩 summary 和近期未压缩 context；旧内容可 offload 后只在摘要里留下可读取路径：[Context Overview](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/context/overview)、[压缩与 offload 源码](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/agent/_agent.py#L615-L658)。

现有 Lite 已经覆盖其核心价值：

- `NOW.md` 只保留目标、验收、当前状态、决策、阻塞和下一步。
- 长日志和大段代码移到外部 artifact，只保留路径或命令。
- `NOW.md` 有 80 行和 8000 字符预算，超限不静默截断。

因此不需要引入自动 conversation compression。AgentScope 的实现可以作为设计依据，但不是 Lite 的运行时依赖。

### 2. Lite 的 `Refresh On Resume` 已覆盖动态状态注入的核心目的

AgentScope 会在推理步骤前注入当前时间、未完成任务数量和上下文使用率，并明确指出动态状态应刷新，固定信息才放 system prompt：[Environment Awareness](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/context/environment-awareness)、[运行态注入源码](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/agent/_agent.py#L1197-L1435)。

现有 Lite 已经要求 mutable 状态通过 `refresh_ref` 重新观测，失败时变成 `unknown`，不得继续沿用旧值。这个设计比简单重复注入旧摘要更符合“当前事实优先”。

### 3. Strict 已经比 AgentScope Plan 更适合完成控制

AgentScope 的 Plan 支持 task ID、owner、`pending / in_progress / completed` 和对称的 `blocks / blocked_by` 依赖：[Plan 文档](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/plan)、[Task 数据模型](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/state/_task.py#L11-L39)。

但官方文档明确说明依赖执行是 advisory，运行时不会阻止模型去做被阻塞任务；任务也可以直接翻为 completed。它没有冻结验收、来源验证、scope、freshness、required hops、delivery receipt 或职责分离。

Strict 已经覆盖并超过这部分：

- publisher / executor / validator 角色分离。
- 追加事件、稳定 item 与 acceptance ID。
- required hops、交付回执和三态 completion gate。
- `unknown` 永远不能算完成。

因此不应把 AgentScope Task 状态作为 Strict 的事实来源或完成判定。

### 4. Strict 的锁、事件账本和快照规则已覆盖持久化顺序问题

AgentScope 在 session lock 内加载并执行，退出前屏蔽取消，先持久化消息和 AgentState，再释放锁，避免下一 worker 读到旧快照：[ChatService 持久化顺序](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_service/_chat.py#L1230-L1306)。

Strict 已有同主机排他文件锁、连续 `seq`、`fsync`、原子 snapshot、事件链摘要和损坏停止规则。无需再引入 Session 服务或消息总线。

### 5. 长期记忆与当前任务状态分离已经覆盖

AgentScope 当前提供 Agentic Memory、ReMe 和 Mem0。Agentic Memory 用短 `MEMORY.md` 作为索引，按需读取主题文件；ReMe 和 Mem0 还可自动提取或检索跨 session 记忆：[Long-Term Memory](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/long-term-memory)。

AgentScope 自己的 Agentic Memory 指令也明确排除 ephemeral task details，并要求当前代码、文件和 Git 事实应实时读取，而不是写进长期记忆：[Agentic Memory 规则](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/middleware/_longterm_memory/_agentic_memory/_middleware.py#L199-L320)。

现有设计已经正确规定 Lite `finish` 不自动生成长期记忆，Strict 的 transfer 也不是长期事实源。无需修订总体原则。

## 值得借鉴并应修订

以下四项是最小修订集。它们不改变两个 skill 的拆分方式，也不增加共享运行时。

### R1. 明确 `resume` 只恢复任务上下文，不恢复进行中的 Agent 运行态

**官方依据**

AgentScope 的可恢复 `AgentState` 不只包含摘要和任务，还包含当前 reply ID / iteration、权限、工具缓存、未压缩消息和 middleware 状态：[AgentState](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/state/_state.py#L151-L265)。外部工具还可能处于 waiting permission 或 submitted-but-awaiting-result 状态：[Message & Event](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/message-and-event)。

AgentScope 的服务层也明确区分 live run lease 和持久化 snapshot：运行中以 live 状态为准，持久化 snapshot 在该时刻必然滞后：[SessionStatus 源码](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_service/_session.py#L61-L95)、[状态优先级](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_service/_session.py#L146-L209)。

**建议落点：Lite + Strict 文档边界**

增加一条共同非目标：

> `resume` 恢复的是任务级工作上下文，不是进程级或 mid-turn Agent 运行态。它不会重建模型内部推理、未落盘消息、权限等待、工具进程、网络连接或后台任务执行器。宿主框架没有提供可验证 runtime state 时，进行中工作必须标为 `unknown`，不得自动重试。

Strict 的 `snapshot.json` 也应明确命名为“控制账本派生快照”，不是 Agent runtime checkpoint。

**验证建议**

- checkpoint 时存在后台工具，但宿主 runtime state 不可读取，resume 后该项必须为 `unknown`。
- resume 不得仅根据旧摘要重复执行外部副作用。
- 宿主报告 live run 时，不得用较旧的任务快照宣称它 idle 或 completed。

### R2. checkpoint 增加自解释引用规则和显式 `In Flight`

**官方依据**

AgentScope 当前的压缩 prompt 特别要求：原对话消失后，所有引用仍需自包含；相对时间转绝对时间；文件、符号、PR/issue、ID、URL、命令和错误字符串使用完整形式；后台工作记录 ID、owner 和 status：[ContextConfig compression prompt](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/agent/_config.py#L66-L99)。

现有 `NOW.md` 已有大部分摘要字段，但没有把 in-flight operation 作为一等结构；`context-transfer/v1` 也没有记录来源 workspace，workspace-relative `file:` 引用跨 skill 或跨目录导入时可能产生歧义。

**建议落点：Lite + 交换格式**

在 `NOW.md` 中增加短小可选章节：

```markdown
## In Flight
- [RUN-01] <动作> | owner: <user/agent> | status: pending/blocked/unknown | started_at: <UTC> | correlation_ref: <job/tool/session id> | recovery_ref: <如何检查真实状态>
```

规则：

- 没有进行中工作时写 `none`，不增加默认负担。
- `checkpoint` 将“今天、刚才、这个文件、上面的测试”等上下文依赖表达改成绝对日期和稳定引用。
- `recovery_ref` 只能用于检查外部现实，不能授权自动重试。
- `resume` 必须先执行 recovery check；无法检查则标 `unknown`。

在 `context-transfer/v1` 增加可选字段：

```json
{
  "source_context": {
    "workspace_root": "/absolute/or-stable-workspace-id",
    "repo_revision": "<commit-or-null>"
  },
  "in_flight_items": [
    {
      "id": "RUN-01",
      "kind": "background-tool",
      "owner": "executor-01",
      "status": "unknown",
      "started_at": "2026-08-27T00:00:00Z",
      "correlation_ref": "job:abc123",
      "recovery_ref": "status-command-or-endpoint"
    }
  ]
}
```

Strict 导入时必须把这些项作为 observation / pending operation，不得从 `pending` 推断仍在运行，也不得自动重试。

### R3. 为 Strict 定义内部 handoff 生命周期和确认语义

**官方依据**

AgentScope 团队中每个 worker 都是独立 session，消息通过 message bus 作为带来源的 `HintBlock` 送达：[Agent Team](https://docs.agentscope.io/versions/2.0.8dev/en/deploy/agent-team)。其源码专门解决“消息恰好在 consumer 结束时到达而被搁置”的竞态：producer 在锁内先入队再检查 consumer，consumer 在同一锁下做最后 drain；异常退出还会释放 consumer 并重新 wake：[inbox handoff 协议](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_bus_ops.py#L139-L322)。

AgentScope 还会在 worker error / interrupted、未能调用 `TeamSay` 时尽力通知 leader：[worker failure report](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_service/_chat.py#L1252-L1296)。但这种通知是 best-effort，而且 `TeamSay` 的成功只说明已向若干 recipient 投递，并不证明 recipient 已理解、接受或验证内容：[TeamSay 源码](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_tool/_team_say.py#L121-L147)。

**建议落点：Strict**

Strict 不需要实现消息总线，但要把 handoff 作为受控状态机记录：

```json
{
  "handoff_id": "HO-018",
  "from_actor": "executor-01",
  "to_actor": "validator-01",
  "payload_digest": "sha256:...",
  "source_event_ids": ["..."],
  "transport_ref": "agentscope:session/message-or-inbox-id",
  "state": "prepared|enqueued|consumed|acknowledged|failed|unknown",
  "recorded_at": "...",
  "acknowledged_at": null
}
```

门禁语义：

- `enqueued` 只表示 transport 接受，不等于交接完成。
- 需要对方实际工作的 handoff，至少到 `acknowledged` 才能关闭。
- worker error、interrupt、消息无法定位或回执不可读时为 `failed` 或 `unknown`，阻止相关验收项完成。
- transport 负责可靠消费；Strict 只记录和验证状态，不在 v2 首版内实现队列、lease 或 wakeup。

这会补齐现有设计中“handoff brief 从受控状态生成”，但未定义 handoff 自身是否真的被目标 Agent 接收的空白。

### R4. 给 Strict 增加事件命名空间与 telemetry correlation，明确 trace 不是证据

**官方依据**

AgentScope 明确把 `Msg` 定义为 Agent 通信与持久化单位，把 `Event` 定义为前端流式交互单位；一组 event 聚合为一个完整 message：[Message & Event](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/message-and-event)。服务层的 event replay log 有最大长度，结束后还会 trim，因此它不是不可变审计账本：[publish_session_event](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_bus_ops.py#L40-L66)、[persist 后 trim](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/app/_service/_chat.py#L1252-L1271)。

AgentScope 的 tracing 使用 OpenTelemetry，记录 agent、model、tool、exception、session/reply/tool-call 关联信息，适合监控和调试：[Tracing 文档](https://doc.agentscope.io/tutorial/task_tracing.html)、[TracingMiddleware](https://github.com/agentscope-ai/agentscope/blob/142c3411b6e7057fb3ef5cf49d7428e731210720/src/agentscope/middleware/_tracing/_trace.py#L117-L254)。源码并未把 span success 当成业务验收通过。

**建议落点：Strict**

在术语中固定区分：

- `control_event`：Strict `events.jsonl` 中的追加控制事件。
- `runtime_event`：AgentScope 等宿主框架产生的流式运行事件。
- `trace_span`：OpenTelemetry 遥测记录。
- `evidence`：经 resolver 和 validator 映射到验收项的原始证据。

在 evidence 与 handoff payload 中增加可选关联字段：

```json
{
  "correlation_refs": [
    {
      "provider": "agentscope",
      "session_id": "...",
      "reply_id": "...",
      "message_id": "...",
      "tool_call_id": "...",
      "trace_id": "..."
    }
  ]
}
```

规则：

- correlation 只帮助定位原始材料。
- runtime event、message、Agent 报告和 span 默认都不能单独使验收项 pass。
- 只有合同声明某种 trace artifact 是必需证据，且 resolver 检查可读性、完整性、scope、freshness，validator 检查其业务含义后，才可以作为一项证据使用。
- 不把 AgentScope 的 streaming event 导入 Strict `events.jsonl`；需要时只保存稳定引用，避免把高频遥测复制成控制账本。

## 与本设计目标无关或不宜照搬

### 1. 不采用完整 `AgentState` 序列化

它适合 AgentScope 自身的 mid-turn / cross-session 运行恢复，但会把模型消息、权限、工具缓存和 middleware 内部结构耦合进两个通用 skill。Lite 会失去纯 Markdown 优势，Strict 也会绑定特定 Agent 框架。

处理方式：只声明 runtime checkpoint 非目标；宿主若有 AgentState，可通过 `correlation_refs` 关联。

### 2. 不采用自动长期记忆写回作为任务 checkpoint

AgentScope 的 ReMe 可以在每次 reply 后自动抽取写回，Mem0 也可自动或由 Agent 控制。它们优化跨 session recall，不提供事实来源、冲突处理、验收映射或证据 resolver；异步检索甚至可能在单次回复结束前尚未注入：[Long-Term Memory 的异步边界](https://docs.agentscope.io/versions/2.0.8dev/en/building-blocks/long-term-memory)。

处理方式：保持 Lite finish 不自动写长期记忆；Strict 只接受经验证的显式输入。

### 3. 不采用 AgentScope Plan 的 completed 作为完成门禁

Plan 适合让 Agent 维护任务队列，但依赖是 advisory，任务状态可由能访问 `AgentState` 的代码直接修改。它不具备 Strict 所需的发布者合同和独立证据。

处理方式：AgentScope task ID 可以成为 correlation ref，不能成为 completion proof。

### 4. 不采用 AgentScope Event replay log 作为审计账本

它服务 SSE 重放和 UI，存在长度上限与 trim；Strict 账本要求追加、连续 seq、摘要链和损坏停止，目标不同。

处理方式：保留 Strict 独立 `events.jsonl`，不共享运行时。

### 5. 不复制消息总线、distributed lease、Agent Team 服务

AgentScope 的 inbox race protocol 和 worker failure report 很有参考价值，但实现消息总线会把当前本地 skill 扩展成分布式 orchestration framework。

处理方式：Strict 规定 handoff 语义与门禁，可靠 transport 由宿主实现。未来若以 AgentScope 作为宿主，再编写一个小 adapter 映射 session/message/tool/trace ID，不修改核心协议。

### 6. 不把 tracing 当作 evidence resolver 的替代品

span 的 OK 只能说明被观测函数没有以异常结束，不能证明需求满足、产物正确、用户收到交付或 scope 匹配。

处理方式：trace 只作定位信息；若合同确实要求 trace，则必须走类型化 verifier。

## 建议修改清单

| 优先级 | 修订 | 落点 | 是否改变已批准架构 |
|---|---|---|---|
| P0 | 声明 task resume 与 runtime resume 的边界 | Lite + Strict | 否 |
| P0 | 增加 `In Flight`、绝对引用规则、resume recovery check | Lite | 否 |
| P0 | 增加 handoff 状态机与确认门禁 | Strict | 否 |
| P1 | 增加 `source_context`、`in_flight_items` | `context-transfer/v1` | 否，仍是向后兼容可选字段 |
| P1 | 区分 control event / runtime event / trace / evidence，增加 `correlation_refs` | Strict | 否 |

## 建议新增验收样本

### Lite

1. checkpoint 中出现“今天”“这个文件”“上面的测试”，输出必须改成绝对日期和稳定路径/测试名。
2. 后台任务只有启动日志、无可查询状态，resume 后必须显示 `unknown`，不得自动重跑。
3. 有 `recovery_ref` 且确认外部任务已完成时，只更新对应 `RUN-*`，不让其他状态失效。
4. transfer 从不同 workspace 导入时，relative locator 必须根据 `source_context` 解析或明确失败，不能静默指向目标 workspace 的同名文件。

### Strict

1. handoff 已 `enqueued` 但无消费或确认，相关 completion 必须不通过。
2. worker 报告完成但 handoff payload digest 与实际 brief 不一致，必须 fail。
3. worker error / interrupted 且 leader 只有 best-effort 通知日志，状态必须是 `unknown` 或 `failed`。
4. AgentScope span 为 OK、Task 状态为 completed，但缺真实 test report / delivery receipt，completion 必须不通过。
5. runtime event replay log 被 trim 后，Strict 控制账本和证据解析仍可独立完成；反过来，仅有 replay log 不得完成。
6. 宿主 session 正在运行而 Strict snapshot 显示旧的 idle，操作状态以 live runtime 为准；无法查询 live runtime 时显示 unknown。

## 最终判断

AgentScope 对本项目的价值主要是补边界，不是提供可直接复用的上下文存储引擎。

- `context-lite` 应吸收其 continuation summary 中“绝对、自包含、记录 in-flight”的规则。
- `context-strict` 应吸收其可靠 inbox handoff 所暴露的投递竞态，但把保证提升到可验证 acknowledgment。
- 交换格式应补上来源 workspace 和进行中操作，避免跨目录恢复时发生指针漂移或误重试。
- AgentScope 的 memory、session、event stream、tracing 和 task plan 都应作为外部运行信息或关联来源，而不是 Strict 的事实与完成门禁。

因此，已批准设计无需推翻，建议在实现前做上述四项协议级增补。
