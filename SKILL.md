---
name: managing-long-task-context
description: Use when work spans multiple turns, sessions, or agents and depends on changing facts, controlled acceptance criteria, evidence-backed handoffs, or protection against stale, conflicting, and misattributed context.
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

Legacy `required_hops` aggregates hop coverage across passing evidence. When one
execution must prove an ordered chain, set
`required_hops_mode: "single-evidence-ordered"`; one passing evidence object must contain
the sequence in order. This opt-in mode requires `evidence-handlers/v1`.

Independent validation requires declared actor roles, a separate validator, and explicit
UTC `validated_at`. Delivery receipts require stable IDs, target/artifact references,
external ID, sent/observed times, and readback method. Evidence freshness, scope, and Git
revision rules remain verifier-backed hard stops.

When designing/reviewing these controls, read
`references/production-failure-patterns.md` and ask: **if this claim is false, what goes
red?** Do not load that reference for routine execution.

## API

| Call | Purpose |
|---|---|
| `bind(base_dir)` | Bind all operations to one absolute context store |
| `publish_contract(...)` | Validate, seal, and atomically publish a contract |
| `record(...)` / `update_item(...)` | Append facts and state transitions |
| `externalize_item(...)` | Shrink wording without changing fact identity or controls |
| `restore_externalization_controls(...)` | Narrow migration for legacy lost required/severity controls |
| `checkpoint(...)` | Record phase delta, blockers, evidence, and next action |
| `brief(...)` / `brief_diagnostics(...)` | Produce or preflight the controlled handoff packet |
| `audit(...)` / `gate(...)` | Run integrity, state, truth, and acceptance checks |

State lives under `.prime/context/<task-id>/` as a sealed contract, append-only
`events.jsonl`, and rebuildable `snapshot.json`. Events are history; snapshot is a cache;
neither is injected by default.

## Hard stops

- Missing, unsealed, modified, or unauthorized contract: stop and return to publisher.
- Missing, stale, unknown, conflicted, or untraceable load-bearing fact: stop depending on it.
- Unusable brief, missing checkpoint, mismatched evidence handler, or failed self-probe: do not hand off or complete.
- A summary without a stable path to the original is unverified; read the original.
- New machinery without a realistic dynamic scenario is candidate-only, not proven.
