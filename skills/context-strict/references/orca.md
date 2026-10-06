# Orca dispatch and handoff

## Why

Orca records who owns work and when a worker has settled. It does not know the task's
acceptance criteria, it does not verify success, and it does not stop two workers from
writing the same files. Context Strict holds the sealed contract, facts, and evidence.
This reference is the collaboration procedure for the points where work changes hands:
a supervised dispatch, a review, a coordinator takeover, and an unsupervised handoff.

Orca commands and flags are defined by the installed Orca build, not here. `<orca>`
below stands for the exact executable a worker's live preamble uses, or that a
coordinator used to run `skills get`; do not hard-code another name. Load Orca's own
guides with `<orca> skills get orchestration` (supervised work) or
`<orca> skills get orca-cli` (handoffs).

## Boundary: Orca settlement is not acceptance

| Question | Authority |
|---|---|
| Which attempt is active, has the worker settled, who owns the terminal | Orca Run / Task / Dispatch |
| Objective, scope, constraints, acceptance criteria | Sealed contract in `.prime/context/<task-id>/` |
| Whether a criterion is met | Strict completion gate over resolved evidence |

A valid `worker_done` settles the Orca Task and Dispatch automatically and releases
downstream Orca work. Orca has no separate review or acceptance status, and the
coordinator does not settle the Task a second time. Acceptance is an independent
conclusion on the Strict side: a worker's `--outcome succeeded` is a lifecycle fact
and a lead, never evidence that a criterion is met. The coordinator reports the
completion gate result (`pass`, `fail`, or `unknown`) whatever outcome the worker sent.

For a Task whose worker was stopped with `worker-stop`, ingest the worker's report
first, then use `task-update --status completed --result` to record the Task's
conclusion. The result must explicitly say "lifecycle conclusion, not acceptance"
and state the Strict acceptance result separately.

## Where a worker reads the task store

The coordinator is the only writer of the task store and the experience store.
Workers and reviewers only read.

| Placement | How the worker reads |
|---|---|
| Same workspace (Orca `--worktree current`) | Read the task store and the sealed contract file directly in that workspace. |
| New worktree on the same machine (Orca `new-child`) | The new checkout has no task store, because `.prime/context/` is gitignored. The dispatch spec gives the absolute path of the coordinator's workspace. Read the sealed contract file under that path, and call `read_task(task_id, Path("<coordinator workspace>"))` with that path as the root. Read-only entries below may use the coordinator workspace and context root; do not write to either store. |
| Remote host | Not supported. |

Read-only roles (workers, reviewers, and cold readers) may use:

| Entry | Writes files? | Basis |
|---|---|---|
| Dispatch spec and sealed contract file | No | Direct read |
| `read_task(task_id, Path(<coordinator workspace>))` | No | Existing project-store read |
| `brief(task_id, base_dir=<coordinator workspace>/.prime/context)` / `brief_diagnostics(...)` | No | Shared lock on the existing `.lock`; read-only tests |
| `checked_resume(...)`, with coordinator workspace/context root and no handlers | No | Includes read-only resume gate; hash and permission tests |
| `scripts/context_status.py` | No | Five-section read-only wrapper |

Do not call writing entries: `record`, `update_item`, `checkpoint`,
`publish_contract`, `init-binding`, `publish_context`, `align_context`, or
`record_acceptance` (#46). `gate()` is not a separate entry for read-only roles.
Acceptance conclusions are read through `brief()` and the status command;
#46 defines their presentation, and is outside this implementation scope.

## Dispatch spec

Every dispatch spec is self-contained and contains:

1. Objective, the concrete change, constraints, and file ownership (which paths this
   worker may edit). Parallel executors each use their own worktree; the coordinator
   integrates their branches one at a time, and conflicts or out-of-scope edits found
   during integration show whether ownership held.
2. The skill `task_id`, fixed before dispatch.
3. Acceptance criteria copied verbatim from the sealed contract, with the absolute
   contract file path and the seal digest attached. The contract is authoritative;
   never paraphrase, summarize, or weaken the criteria. This matches item 5 of the
   handoff pack in `SKILL.md`.
4. The absolute path of the coordinator's workspace (needed for a new worktree).
5. The report path template from the worker report contract below, with the literal
   placeholder `<dispatch-id>`.
6. The pinned package path, its expected manifest digest, and the version-proof command.

Choose any further context from the role whitelist in `agent-role-handoff.md`.

Immediately after publishing a contract, run `context_doctor.py init-binding` for
that task. Publishing does not initialize the binding; without this step,
`checked_resume()` returns `BINDING_MISSING`. See
[#55](https://github.com/wei0210-bit/managing-long-task-context/issues/55); this is
a procedure requirement only.

Follow the complete `init-binding` command in SKILL.md section 1, immediately
between publication and release. Use the independently retained manifest digest
from the dispatch or handoff material, never an automatically derived expected
value. Only the coordinator initializes binding; without it recovery returns
`BINDING_MISSING` and null context.

## Worker report contract

A worker report is a durable evidence source that the coordinator checks before
ingesting it. It is not a handoff receipt, it does not transfer control, and it is
not a verified fact until the coordinator has ingested and checked it.

**Path:** `<worker workspace root>/.context-reports/<task_id>/<dispatch-id>.json`.
`task_id` is the skill task id from the dispatch spec. The worker takes the dispatch
id from the `--dispatch-id` value that Orca already filled in under the preamble's
`=== CLI COMMANDS ===` section. The coordinator learns the dispatch id and workspace
from the `worker-start` receipt, so it can derive the path even when no `worker_done`
arrives. Projects keep `.context-reports/` out of Git; never commit a report.

**Timing:** write the report as soon as the checks finish and before `worker_done`.
Pass the same path as `worker_done --report-path`.

**Required fields:**

| Field | Content |
|---|---|
| `schema` | Report schema version |
| `task_id` | Skill task id |
| `orca_task_id` | Orca Task id from the preamble |
| `orca_dispatch_id` | Orca Dispatch id from the preamble |
| `contract_digest` | Seal digest of the contract the worker read |
| `loaded_module_file` | From the version proof below |
| `loaded_manifest_sha256` | From the version proof below |
| `code_revision` | Commit id and whether the tree had uncommitted changes |
| `checks` | Per check: command, exit code, output file path, and output summary |
| `files_modified` | Files the worker changed |
| `deferred_suggestions` | Out-of-scope findings, one entry each; not acted on |
| `outcome_claim` | The worker's own claim; a lead, not a verdict |
| `written_at` | UTC timestamp |

**Version proof:** run this with the same `PYTHONPATH` the checks use, so it reports
the module that process actually imports:

```sh
PYTHONPATH=<pinned-package>/src python3 -c 'import json, sys, managing_long_task_context as m; r = m.runtime_identity(package_root=sys.argv[1]); print(json.dumps({"loaded_module_file": m.__file__, "loaded_manifest_sha256": r["identity"]["loaded_manifest_sha256"]}))' <pinned-package>
```

`<pinned-package>` is the absolute package path from the dispatch spec. If
`loaded_module_file` is not under the pinned package, or the digest differs from the
expected value, that worker's result is void.

**When blocked:** if the contract is missing, unreadable, unsealed, or stale, first ask
the coordinator with the preamble's `ask` command. If that does not resolve it, send
`worker_done` once with `--outcome failed` and state the reason. Never exit silently,
never report success, and never invent or infer acceptance criteria.

**Heartbeats:** a long gate or test run must not stop heartbeats. Keep sending them at
the preamble's cadence while it runs, for example by running it in the background. A
heartbeat proves liveness only.

## Reviewer task

The coordinator creates the reviewer task only after it has collected the executor
reports and integrated their branches. It does not use an Orca DAG dependency for this.

The reviewer receives: the contract path and seal digest, the base commit, the
coordinator's integrated branch, every executor report path, and the coordinator's own
check log. It only reads. It writes its own report under the same report contract;
`checks` records the commands it actually ran, `outcome_claim` is its review verdict,
and it adds a `findings` list.

Base drift: if the base branch moves after the reviewer task is created, the base
commit the review relied on is no longer current. Record the base commit in the
reviewer task, and if it changes, re-run the review against the new base instead of
reusing the old findings.

The coordinator ingests the reviewer report as one piece of evidence and then runs the
completion gate. This procedure does not enable the contract's
`independent_validation_required`.

## Coordinator: ingest and deduplicate

This is a manual procedure for the coordinator, not enforced by code.

1. Before ingesting a report, look in the snapshot for a main item with that report's
   `orca_dispatch_id`.
2. If there is none, record one main item:
   `record(task_id, item_type="observation", metadata={"orca_dispatch_id": ..., "report_sha256": ..., "role": "report-ingest"}, ...)`.
3. Then record each entry of `deferred_suggestions` as its own item, in report order.
   Its metadata carries the same `orca_dispatch_id` and a `report_item` sequence number,
   and its content is marked `{"deferred": true}`.
4. If the main item exists but there are fewer suggestion items than the report has,
   record only the missing sequence numbers. If all are present, write nothing.

When a review report covers multiple tasks, record each suggestion under the
`task_id` marked for that entry in the report. If an entry has no `task_id`, record
it under the coordinator's current task and add `{"report_task_unspecified": true}`
to its metadata.

Pass condition: each dispatch id has exactly one main item, and its number of
suggestion items equals the number in the report.

Re-check every load-bearing claim in a report against originals (Git state, test logs,
the output files) before relying on it, then run the completion gate.

## Coordinator takeover

If the coordinator exits mid-run, a new session rebinds the Run with Orca's `run-use`
(exact flags from Orca's guide for the installed build; Orca fences the old
coordinator), then runs `checked_resume()` for the task. Only the session bound to the
Run may write to the task store. This is a convention, not enforced by code. Then apply
the ingest procedure above; it does not re-dispatch work that already has a report.

When `checked_resume()` or the status command reports a non-pass resume gate,
keep the returned context for diagnosis and use `diagnostic.status`, not its
presence, to decide whether to continue. Re-observe expired facts with `ttl_hours`
and refresh via `update_item`; facts without a TTL need
`record(..., supersedes=<old id>)` with `ttl_hours`. Resolve conflicts by
superseding the losing side and reactivating any conflicted winner with
`update_item(status="active")`. Blocking items allow dispatch only of work to
解除该阻塞; other new execution waits for the gate to pass. Supply `rule_runtime`
in the Python host when unavailable. For a read race or gate exception, rerun
once; a persistent discrepancy is handled as a gate error, never repeated blindly.

After `run-use`, do not acknowledge a delivery batch id copied from the takeover
document. Run `check` after takeover and use the delivery batch id it returns for
the acknowledgment; rebinding the Run can change that id.

## Unsupervised handoff (orca-cli)

A handoff to another agent or worktree creates no Run, Task, or Dispatch, so Orca
reports nothing about completion. The handoff message is the only carrier:

1. It includes the same handoff pack from `SKILL.md`, with the absolute Strict path
   and the acceptance criteria copied verbatim with contract path and seal digest.
2. Pass the handoff gate and produce a usable `brief()` first when the runtime is
   available.
3. Orca's handoff ends with the original agent stopping once the prompt send is
   confirmed. That is Orca's ownership rule; it says nothing about whether the receiver
   read the material or took control. On the Strict side, under the session-migration
   rules in `SKILL.md`, `control_transfer` stays `unknown` until proven by readback,
   and the source session and its records are kept, not archived. The original agent
   stopping work and the source session being retired are different things.

## Out of scope

This reference does not define Orca commands or flags, routing, retries, or
escalation, and it does not replace `brief()`, `gate()`, or `short-session-handoff/v1`.
Keep these rules in this package; do not write them into Orca's own skill directories.
