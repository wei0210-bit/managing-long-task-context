---
name: context-strict
description: Use when work spans multiple turns, sessions, or agents (including bot-to-bot pipelines) and depends on changing facts, controlled acceptance criteria, evidence-backed handoffs that carry `.prime/context/<task-id>/` paths, or protection against stale, conflicting, and misattributed context.
---

# Managing Long-Task Context

## Principle and identity

上下文管理的敌人不是忘记，而是**记错且不自知**。承重上下文从严，过程上下文从简；在保持有效的前提下尽量经济，不能因为经济而失效。

`skill-package.json` is the package identity. Installation and evaluation must use the
complete package plus generated manifest/hash, never a copied `SKILL.md` alone.

Use Strict for multi-agent work, frozen acceptance, changing truth, independent
validation, or external side effects. A single low-risk agent needing only multi-turn
recovery should use Context Lite; a static single-turn judgment should use neither.

## Workflow

After package installation/update, run `scripts/context_doctor.py check --mode full
--package-root <absolute-package>` (Strict needs explicit `PYTHONPATH=<package>/src`).
For bound task recovery, prefer `checked_resume()`; it checks identity before returning
context. Missing/mismatched identity stops recovery without silently rebinding. Full
diagnosis is not a per-turn step. See `references/runtime-identity.md` when configuring
binding or diagnosing an error; legacy direct APIs remain outside this identity check.

For an explicitly enabled `short-session-handoff/v1` contract, use only the
on-demand handoff calls and read `references/handoff.md`. They do not provide
verified native takeover, automatic switching, or a resident scheduler. Native
limits are in `references/host-native.md`. For host-supplied window/usage signals,
use `scripts/context_usage.py` per `references/context-usage.md`; recommendations
never grant control. Do not scan chats or call a model to produce these signals.

### Session migration: one mode, three separate results

Before creating any new session, record `migration_mode: strict_protocol` or
`migration_mode: manual_fallback`. Never omit it, never use `automatic`, `skill`, or `normal`,
and never switch modes silently. From the complete built package, run
`scripts/handoff_preflight.py` (`PYTHONPATH=<package>/src`) with the stage inputs in
`references/handoff.md`. Its exit `0/1/2` means only preflight `pass/fail/unknown`, never
that migration, takeover, or archive finished.

Report `information_recovery`, `control_transfer`, and `source_retirement` separately; never a
single `migration_success`. File, path, and SHA checks prove only `material_integrity`.
`information_recovery=pass` needs an exact readback of the five fact categories `objective`,
`current_state`, `constraints`, `next_action`, and `unresolved_risks`. A `clientThreadId`, task
title, self-report, or chat reply never proves `control_transfer`. `manual_fallback` always keeps
`control_transfer=unknown` and `source_retirement=not_allowed`. In this phase every mode keeps
`archive_allowed=false`: never archive the source session.

On any UNKNOWN, keep the source session, stop dispatching new controller work from it, allow
only read-only checks, do not blindly retry create/activate/archive, and give one read-only
next action. BLOCKED is only for a concrete external blocker, NOT_RUN for work not run, UNKNOWN
for facts that cannot be proven; `brief_diagnostics().usable=true` proves structure, not currency.

### 1. Bind storage, publish, then release

Prefer one absolute store so process `cwd` cannot select a different task:

```python
import managing_long_task_context as context

ctx = context.bind("/absolute/project/.prime/context")
ctx.publish_contract(contract, confirmed_by="task-publisher")
release = ctx.gate("TASK-001", stage="release", verifiers=runtime_verifiers)
```

The publisher owns objective, scope, constraints, and acceptance criteria. Executors
and validators may not weaken or reinterpret them. New contracts are atomically
published read-only as an advisory mistake guard; controlled changes require a higher
version and fresh authorized confirmation. `protect_contract=False` is an auditable
compatibility escape hatch, not the default.

New contracts should enable `evidence-handlers/v1` and map every required evidence kind
to stable resolver/verifier capability IDs. Built-in resolver kinds are `file`,
`git-commit`, `test-report`, and `url`; custom kinds require matching runtime handlers.
Use `assets/task-contract.example.json` and run `examples/strict_completion.py`.

### 2. Record facts without laundering inference

```python
ctx.record(
    "TASK-001",
    statement="数据库可能缺少幂等约束",
    item_type="assumption",
    actor="executor-01",
    source={"kind": "agent-inference", "ref": "code-review-01"},
    scope={"module": "payment-callback"},
)
```

`verified-fact` requires evidence, verification method, scope, and verification time.
Changing facts also require `mutable=True` and `ttl_hours`; stale facts must be
re-observed. Use `update_item()` for state transitions. Use
`record(..., supersedes=old_id)` only when a new fact replaces an old fact.

When only bulky wording moves elsewhere, use `externalize_item()` instead. It keeps the
same item ID, controls, evidence, source, actor, and `verified_at`, while the event log
retains the original statement. The reference must be an existing canonical absolute
`file:` path; its digest is sealed and later drift blocks gates. Never create a fresh
stub merely to shorten a brief.

### 3. Checkpoint and hand off only a usable brief

```python
ctx.checkpoint(
    "TASK-001", phase="root-cause-verification",
    completed=["已复现重复回调"], evidence_added=["test:run-018"],
    next_action="检查异常重试路径", actor="executor-01",
)
diagnostics = ctx.brief_diagnostics("TASK-001")
if not diagnostics["usable"]:
    raise RuntimeError(diagnostics["overflow"])
ctx.gate("TASK-001", stage="handoff", verifiers=runtime_verifiers)
brief = ctx.brief("TASK-001")
```

Overflow returns every omitted mandatory ID. `brief()` never returns a partial mandatory
packet; release, resume, and handoff all block on overflow. Externalize unchanged detail,
resolve conflicts, or ask the publisher to split/version the task—never delete controls
or blindly raise the budget.

The model consumes `brief()`; resolver/verifier code reads evidence; raw ledger and
snapshot are read only in minimum slices when investigating a concrete discrepancy.
Token estimates are advisory and never weaken selection or a gate.

### 4. Read changing originals, not upstream retellings

Enable `truth-sources/v1` only when decisions depend on changing local originals. The
flow is publish → each owner observes all declared sources → release. A declared change
must be marked dirty and re-observed before handoff/completion. Briefs carry paths and
control metadata, not source contents. See `assets/truth-source-contract.example.json`
and `examples/truth_source_contract.py`.

Unobserved, dirty, expired, changed, unreadable, or unknown sources block the gate.
Truth-source observation is context control, not completion evidence. It does not retain
raw bytes, infer changes, authenticate actors, or provide an event hash chain.

### 5. Complete only against the sealed criteria

```python
evidence_map = {
    "AC-01": {
        "evidence": [{
            "evidence_id": "EV-TEST-019",
            "kind": "test-report",
            "locator": "artifacts/run-019.json",
            "generated_at": "2026-09-02T04:30:00Z",
            "scope": {"module": "payment-callback", "environment": "test"},
            "covered_hops": ["callback-entry", "idempotency-check", "write"],
            "produced_by": "executor-01",
        }],
        "delivery_receipts": [],
    }
}
completion = ctx.gate(
    "TASK-001", stage="completion", evidence_map=evidence_map,
    verifiers=runtime_verifiers,
)
```

Evidence envelopes do not prove themselves: the resolver must read the referenced
artifact and the verifier must establish that it supports the criterion. A caveat that
cannot make a deterministic check red is not an enforced control.

With `evidence-handlers/v1`, completion adds a read-only `decision`
(`pass`/`fail`/`unknown`), not a completed-state write. Unavailable, stale or mismatched
evidence blocks as `unknown`; explicit content
violations remain `fail`. Bind `contract_version` in evidence and the sealed required
scope; legacy envelopes may omit it. Passing local `file` evidence is re-resolved after
all callbacks without retrying verifiers. Other kinds retain their existing guarantees.
The example binds a content-reading checker in host code: never load executable checkers
from model output. A pass is point-in-time, not authorization for a later side effect.

Legacy `required_hops` aggregates hop coverage across passing evidence. When one
execution must prove an ordered chain, set
`required_hops_mode: "single-evidence-ordered"`; one passing evidence object must contain
the sequence in order. This opt-in mode requires `evidence-handlers/v1`.

For a criterion marked `independent_validation_required: true`, host code supplies the
policy and receipt resolver to `bind`, `publish_contract`, or `gate`; model JSON supplies
only a lookup `validation_ref` for that receipt; normal evidence remains required, never
proof. A stored true requirement without a trusted resolver blocks; false/omitted low-risk
criteria keep their existing path. Read
`references/independent-validation.md` when defining this boundary. Delivery receipts
require stable IDs, target/artifact references, external ID, sent/observed times, and
readback method. Evidence freshness, scope, and Git revision rules remain verifier-backed
hard stops.

When designing/reviewing these controls, read
`references/production-failure-patterns.md` and ask: **if this claim is false, what goes
red?** Do not load that reference for routine execution.

## API

| Call | Purpose |
|---|---|
| `bind(base_dir)` | Bind all operations to one absolute context store |
| `runtime_identity(...)` | Observe the calling process's package identity |
| `checked_resume(...)` | Check explicit task/workspace identity before recovery |
| `publish_contract(...)` | Validate, seal, and atomically publish a contract |
| `record(...)` / `update_item(...)` | Append facts and state transitions |
| `externalize_item(...)` | Shrink wording without changing fact identity or controls |
| `restore_externalization_controls(...)` | Narrow migration for legacy lost required/severity controls |
| `checkpoint(...)` | Record phase delta, blockers, evidence, and next action |
| `brief(...)` / `brief_diagnostics(...)` | Produce or preflight the controlled handoff packet |
| `audit(...)` / `gate(...)` | Run integrity, state, truth, and acceptance checks |
| `bind_experience(workspace_root, store_root)` | Bind Strict-only experience review and approval |
| `prepare_handoff(...)` / `validate_handoff(...)` / `activate_handoff(...)` / `cancel_handoff(...)` / `handoff_status(...)` | Explicit host-verified short-session handoff; only when the capability is sealed in the contract |

## Verified experience and rule execution

Use `scripts/context_experience.py` only to initialize, record, query, or get
project-local candidates. They never gain authority automatically. Strict hosts use
`bind_experience()` to review and approve new experience before selecting it; existing
rules may be selected directly by the contract publisher. Opt into
`rule-execution/v1` for selected rules and call `gate()` from the controlled entry:
the library cannot intercept an action when its gate was never called. Runnable
examples: `examples/experience_review.py`, `examples/rule_execution.py`, and
`examples/experience_rule_gate.py`. The candidate CLI example is
`examples/experience_candidates.py`.

State lives under `.prime/context/<task-id>/` as a sealed contract, append-only
`events.jsonl`, and rebuildable `snapshot.json`. Events are history; snapshot is a cache;
neither is injected by default.

## Multi-bot / assistant pipeline handoff (shared truth)

When several bots or agents collaborate on one task (for example plan → Office hours →
writer → reviewer), **Context Strict storage is the shared truth source**. Chat memory
and free-form messages are not enough.

### Required handoff field

Every cross-bot handoff pack MUST include at least one of:

- absolute path to the task store: `<project>/.prime/context/<task-id>/`
- absolute path to the sealed contract file: `.../task-contract.json` (or the
  project-standard contract filename under that task id)

Downstream bots MUST open and read that contract (objective, scope, constraints,
acceptance / verification criteria) **before** implementing or reviewing. Do not
rely on a retelling of AC in chat if the sealed contract exists.

Upstream bots MUST publish or point to a usable Strict pack before asking the next
stage to start. If the path is missing, unreadable, or the contract is unsealed /
stale, stop and ask the publisher to fix it — do not invent acceptance criteria.

### Recommended handoff pack (minimum)

1. Project root (absolute)
2. `.prime/context/<task-id>/` (absolute) **or** `task-contract.json` (absolute)
3. Task id
4. Goal (short; contract remains authoritative)
5. Verification / acceptance criteria (copy from sealed contract; do not weaken)
6. Artifact pointers (branch, PR, diff) when they exist
7. Self-check commands/results when they exist

### Relation to brief() / gates

Prefer producing a usable `brief()` and passing handoff/completion gates when the
runtime is available. The path rule above still applies when a host only exchanges
messages: the message must carry the Strict path so peers can bind the same store.

See also `references/bot-pipeline-handoff.md`.

## Publish guards

新合同应填写现存绝对目录 `workspace_root`，并启用 `evidence-handlers/v1`。自由文本证据类型不会被发布拒绝；用 `managing_long_task_context.evidence.contract_compat_report` 检查缺失或不存在的工作区，以及未映射到内置或已声明 handler 的证据类型。

## Usage freshness

交接前调用 `managing_long_task_context.usage_freshness.usage_freshness_report(task_root, now=...)`。它只读任务目录。账本停更、合同版本超过 5、以及名为 `.DS_Store` 或匹配末尾 ` 2` 副本的条目会给出 warning。最近一次 checkpoint 早于 72 小时，或缺少 checkpoint，报告状态为 unknown。`audit`、`brief`、`gate` 的既有结论不变。

## Hard stops

- Missing, unsealed, modified, or unauthorized contract: stop and return to publisher.
- Missing, stale, unknown, conflicted, or untraceable load-bearing fact: stop depending on it.
- Unusable brief, missing checkpoint, mismatched evidence handler, or failed self-probe: do not hand off or complete.
- A summary without a stable path to the original is unverified; read the original.
- New machinery without a realistic dynamic scenario is candidate-only, not proven.
- Missing migration mode, a single migration-success claim, or an archive request: stop; report the three results separately and keep the source session.
