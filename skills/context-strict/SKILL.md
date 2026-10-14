---
name: context-strict
description: Keep a shared factual ledger for multi-agent or multi-session work, changing facts, frozen agreements, evidence pointers and checkpoint summaries.
---

# Context Strict: shared ledger

Context Strict records what agents know, where it came from, and what remains uncertain.
Orca manages sessions, plans, dispatch, waiting, execution and review. The ledger reports
missing, stale, conflicted and unverified information; its diagnostics do not authorize
or prevent agent actions.

## Read the shared record

For multi-agent work, pass the absolute `.prime/context/<task-id>/` path or its
`task-contract.json` path. Receivers read the contract original and use that same ledger.
The seal records what was agreed at that time; it does not impose an execution gate.
See `references/agent-role-handoff.md` and `references/bot-pipeline-handoff.md` for
information to carry. Session transfer itself belongs to Orca.

Use Strict automatically for audit-sensitive, frozen-acceptance or multi-agent work.
Use Context Lite automatically for a single low-risk primary agent
needing multi-turn recovery. Static single-turn judgments need neither.

## Record facts and checkpoints

```python
import managing_long_task_context as context

ctx = context.bind("/absolute/project/.prime/context")
ctx.publish_contract(contract, confirmed_by="publisher")
ctx.record("TASK-001", statement="Observed original result", item_type="observation",
           actor="worker", source={"kind": "file", "ref": "/absolute/result.json"})
ctx.checkpoint("TASK-001", phase="implementation", completed=["change recorded"],
               evidence_added=["file:/absolute/result.json"], next_action="review result", actor="worker")
packet = ctx.brief("TASK-001")
report = ctx.gate("TASK-001", stage="completion", emit=False)
```

Facts carry type, actor, source, evidence pointers, scope and verification time.
Changing facts carry a TTL. `verified-fact` records a declared verification method and
supporting references; Strict does not execute that verification. `update_item` preserves
provenance. `externalize_item` retains identity and records the original file's digest.
Read the original when a pointer is missing or changed; diagnosis reports that difference.

`brief` returns selected context with omitted IDs and overflow diagnostics when the
budget is insufficient. `brief_diagnostics` describes size and selection. Neither refuses
handoff or completion. Contract/history corruption can make a record unreadable; this is
a storage integrity error, independent of the agent's authority to work.

## API

| Call | Record or observation |
|---|---|
| `bind(base_dir)` | Select one absolute ledger |
| `publish_contract(...)` | Seal the agreement and retain previous contract bytes |
| `contract_diff(...)` | Compare retained versions |
| `record(...)` / `update_item(...)` | Append typed facts and state changes |
| `externalize_item(...)` / `restore_externalization_controls(...)` | Keep provenance when detail moves to an original file |
| `checkpoint(...)` | Record progress, evidence, blockers and next action |
| `brief(...)` / `brief_diagnostics(...)` | Summarize context and report omissions |
| `audit(...)` / `gate(...)` | Read-only ledger health and missing/unverified evidence reports |
| `mark_truth_sources_dirty(...)` / `observe_truth_source(...)` | Record changes and observations of original files |
| `record_acceptance(...)` / `latest_acceptance(...)` / `acceptance_status(...)` | Record a supplied acceptance conclusion and report its evidence/revision currency |
| `worker_report_handlers(...)` | Read-only worker-report registration helpers; execution claims remain unverified |
| `bind_experience(...)` | Record and query experience, including its provenance and review history |
| `publish_context(...)` / `align_context(...)` | Share the selected ledger without overwriting newer local records |
| `check_store(...)` / `read_task(...)` | Inspect shared storage |
| `runtime_identity(...)` / `checked_resume(...)` | Report package identity alongside available context |

`gate` is retained as a compatibility name for a report. Every stage is read-only,
`blocking=false`, and evidence claims stay `unknown`; legacy resolver/verifier options
are ignored. No callbacks are invoked. `record_acceptance(acceptance_report=...)` records
a caller-supplied conclusion; without one the report stays unknown. No commands are rerun.
Legacy execution-policy fields in a contract are historical declarations only.

## Storage and sharing

The task store contains `task-contract.json`, append-only `events.jsonl`, rebuildable
`snapshot.json`, `contract-history/` and separate acceptance records. Experience lives in
`.prime/experience/`. New portable experience stores retain relative provenance and project
identity so checkouts can consult the same history. Experience never gains action authority. Lifecycle review/approval labels record caller
declarations; legacy checker callbacks are ignored.

`publish_context` and `align_context` retain their existing data-integrity and secret checks.
They share records; they do not dispatch agents or change session ownership. Ordinary Git
commits keep ignored stores separate. Publishing to a remote is an explicit caller action.

## Package identity and health

Search context on demand with `python3 scripts/context_search.py search "协调者租约"`
from the project worktree. Optional `--task TASK-001`, `--kind fact|decision|contract|doc`,
`--limit 20` and explicit `--include /path/to/memory` narrow or extend the search.
Current ledger items exclude superseded facts; `--history` adds labeled event history.
Results contain source paths, starting lines, snippets and freshness metadata: read the
original file before using a result. Every search refreshes the disposable
`.prime/search/index.sqlite` cache; lock conflicts report `index_stale: true`, and SQLite
without trigram reports `degraded: like-scan`. `python3 scripts/context_search.py rebuild`
rebuilds the cache from files. Search never writes the ledger or original documents.

`skill-package.json` declares this package. Build the full package using
`scripts/skill_package.py`, observe identity using `scripts/context_doctor.py`, and consult
`references/runtime-identity.md` for details. Identity diagnosis and available ledger context
are returned separately; a non-pass diagnosis is reported without directing agent execution.

`scripts/context_status.py` and `usage_freshness` report ledger health. Freshness warnings
(stale checkpoints, duplicate copies, many contract versions) are observations. Package
lineage from `scripts/package_lineage.py` remains advisory. The repository root synchronization script regenerates the installable Strict package.
