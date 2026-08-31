---
name: context-strict
description: Use when work spans multiple turns, sessions, or agents and depends on changing facts, controlled acceptance criteria, evidence-backed handoffs, or protection against stale, conflicting, and misattributed context.
---

# Managing Long-Task Context

## Core Principle

上下文管理的敌人不是忘记，而是**记错且不自知**。

- 任务发布者在发布时定义目标、范围、约束和验收标准。
- 执行者与验证者不得编写、放宽或静默重解释验收标准。
- 新信息先作为观察、假设、决定或问题登记；有来源、证据、范围和核实时间后，才能成为已验证事实。
- Agent 交接与压缩摘要只用于导航，不能替代原始证据。

## Required Workflow

### 1. Publish and seal the task contract

从 `assets/task-contract.example.json` 创建合同，由任务发布者填写验收标准并明确确认：

```python
import json
from pathlib import Path
import managing_long_task_context as context

contract = json.loads(Path("task-contract.json").read_text())
context.publish_contract(contract, confirmed_by="task-publisher")
context.gate("TASK-001", stage="release")
diagnostics = context.brief_diagnostics("TASK-001")
```

合同发布后会生成完整性摘要。它检测发布后的内容变化（包括确认者和确认时间），但不认证谁作出了确认；身份认证需要外部签名或受信存储。任何修改都会使摘要失效；变更必须提高版本并由发布者或授权人重新确认。
`fits=false` 时按 overflow 信息外置明细并保留简洁稳定引用、解冲突或拆任务；禁止删除验收标准或 mandatory 条目。

### Truth Sources（可选）

仅当任务的决策确实依赖会变化的本地原件时，才从
`assets/truth-source-contract.example.json` 声明 `truth_sources` 和
`required_capabilities: ["truth-sources/v1"]`；完整可运行流程见
`examples/truth_source_contract.py`。固定顺序是：发布合同 → owner 对**所有**声明原件执行
`observe_truth_source` → `gate(..., stage="release")`。声明范围内发生真实变更后，先由
调用方显式 `mark_truth_sources_dirty`，owner 重新读取原件并观测，才可 handoff 或 completion。

brief 只携带稳定路径和控制元数据；执行者必须自行读取原件，不能把 brief、聊天摘要或上游转述当作
原件。未观测、dirty、过期、字节变化、不可读和 unknown 都会阻断质量门；truth observation 只是
上下文控制，不是 completion evidence，也不能证明 owner 理解了原件语义。

该能力不保存原始 bytes，不自动推断变更、不提供 actor 身份认证，也没有事件 hash chain。启用前，
参与同一任务的每个 runtime 都必须升级；旧 runtime 可能忽略 capability。未声明时不会执行
truth-source 扫描，也不会向 prompt 注入 truth-source 控制块。

### 2. Record context without laundering assumptions into facts

```python
context.record(
    "TASK-001",
    statement="数据库可能缺少幂等约束",
    item_type="assumption",
    actor="executor-01",
    source={"kind": "agent-inference", "ref": "code-review-01"},
    scope={"module": "payment-callback"},
)
```

`verified-fact` 必须提供独立证据、验证方法、适用范围和核实时间。会变化的事实应设置 `mutable=True` 与 `ttl_hours`，恢复任务时重新观测。
登记或更新 required/conflicted 后运行 `brief_diagnostics()`；即使 overflow，事实仍须入账。

### 3. Update by event; never overwrite history

使用 `update_item(...)` 验证、冲突标记或废弃旧条目。新结论通过 `supersedes` 指向旧条目；旧记录保留。

### 4. Checkpoint and hand off from controlled state

```python
context.checkpoint(
    "TASK-001",
    phase="root-cause-verification",
    completed=["已复现重复回调"],
    evidence_added=["test:integration-run-018"],
    next_action="检查异常重试路径",
    actor="executor-01",
)

diagnostics = context.brief_diagnostics("TASK-001", phase="root-cause-verification")
if not diagnostics["fits"]:
    raise RuntimeError(diagnostics["overflow"])
context.gate("TASK-001", stage="handoff")
brief = context.brief("TASK-001", phase="root-cause-verification")
child = await rlm(brief["prompt"], name="root-cause-verifier")
```

不得把聊天总结当作交接依据。模型只消费 `brief()`；`gate()`/resolver 核验证据；ledger、snapshot 和日志仅为具体分歧读取最小片段。

`brief_diagnostics()` 与 `brief()` 共用选择逻辑并区分 overflow；token 范围是跨模型的启发估算（`heuristic-not-guaranteed`），只作 advisory，不参与选择、overflow 或 gate。

### 5. Complete only against publisher-written criteria

完整调用见 `examples/strict_completion.py`。合同使用
`required_evidence_types`、`required_hops`、`required_delivery_types`、
`required_scope`、freshness 和 independent-validation 控制。每个 required hop
必须写在某个实际通过的 evidence 对象自己的 `covered_hops` 中；验收映射顶层的
旧 `covered_hops` 字段只保留兼容性，不能自行证明 hop。需要独立验证时，合同还要
提供 `actor_roles`，且 `validated_by` 必须拥有 validator 角色并与 evidence 的
`produced_by`/owner 分离；验收映射还必须提供不晚于 gate 当前 UTC（加 300 秒时钟偏差）
的显式 UTC RFC3339 `validated_at`。

当 criterion 声明 `required_delivery_types` 时，每个 receipt 必须是带稳定
`evidence_id` 的 `delivery-receipt` 对象，并完整提供 `delivery_type`、`channel`、
`target_id`、`artifact_ref`、`external_id`、`sent_at`、`observed_at` 和
`verification_method`；两个时间字段同样必须使用显式 UTC RFC3339。receipt 也属于
独立验证所引用的证据，因此它的 producer/submitter 不能与 `validated_by` 相同。

本地 file/test-report resolver 以 16 MiB 为读取上限并增量计算摘要。时间必须是显式
UTC RFC3339（`Z` 或 `+00:00`）；只允许最多 300 秒的未来时钟偏差。Git revision
约束使用 `required_revision` 与 `revision_match: exact|ancestor`，test report 内部
revision 和 scope 必须匹配 criterion，而不是只与调用者 envelope 相互一致。

completion gate 使用自身观测到的当前 UTC 判断 evidence、独立验证和 delivery receipt
时间；公共 `context.gate()` 不接受调用方提供的参考时间。

## API

| Call | Purpose |
|---|---|
| `publish_contract(contract, confirmed_by)` | 校验、封印并发布任务合同 |
| `gate(task_id, stage=...)` | 执行 release、resume、handoff 或 completion 质量门 |
| `record(...)` | 登记观察、事实、假设、决定或问题 |
| `update_item(...)` | 验证、标记冲突、解决问题或废弃旧条目 |
| `checkpoint(...)` | 记录阶段增量、证据、阻塞与下一步 |
| `brief(...)` | 生成最小 Active Context / Handoff Packet |
| `brief_diagnostics(...)` | 预检固定提示、条目贡献、mandatory 占用和 advisory token 启发范围；overflow 时仍返回原因 |
| `audit(...)` | 自证检查器有效并输出扫描数量、错误和告警 |

## Persisted State

每个任务只使用三个文件：

```text
.prime/context/<task-id>/
├── task-contract.json   # 发布者拥有的质量基准
├── events.jsonl         # 追加式事实与状态事件
└── snapshot.json        # 可由事件重建的当前视图
```

`events.jsonl` 是追溯记录；`snapshot.json` 不是事实来源；二者默认不注入模型。

## Hard Stops

- 验收标准缺失、未封印或被修改：停止执行，返回发布者。
- 关键事实无来源、无证据、已过期或相互冲突：停止依赖该事实。
- 上一位 Agent 的总结无法追到原始证据：按未验证信息处理。
- 检查器没有统计输出或自检探针失败：检查无效，不得给出“通过”。
- 新机制只写下来但未在真实任务中验证：只能标记为候选措施。
