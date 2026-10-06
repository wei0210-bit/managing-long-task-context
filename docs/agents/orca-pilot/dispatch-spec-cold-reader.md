# Cold-reader dispatch spec

## Objective, change, constraints, ownership

- Objective: `<cold-read-objective>`.
- Concrete result: `<facts-and-recovery-questions-to-answer>`.
- Constraints: `<cold-read-invariants-and-do-not-touch-boundaries>`; read source and stores only.
- Owned editable paths: only `<worker-workspace-absolute-path>/.context-reports/<skill-task-id-fixed-before-dispatch>/` for this Dispatch's report and logs.
- Baseline commit: `<cold-read-baseline-commit>`.
- Current branch/commit to inspect: `<cold-read-current-branch-and-commit>`.
- Original state/artifact paths: `<current-original-state-and-artifact-absolute-paths>`.
- Check commands: `<cold-read-observation-and-verification-commands>`.

Start from the original contract and supplied pointers, without prior conversations
or another agent's investigation transcript. Re-observe changing originals. Report
objective, current state, constraints, next action, and unresolved risks with
original-file/log pointers; identify every fact that cannot be established.
Do not implement changes, write context stores, or take over coordinator control.

Add `findings` and `readback` fields to the report for the five fact categories above.
`outcome_claim` states whether the requested cold-read criteria were met, including
any unknowns. The report is an observation for verification, not a control-transfer
receipt or proof of session migration.

## Task and acceptance

- Skill `task_id`: `<skill-task-id-fixed-before-dispatch>` (distinct from the Orca Task id).
- Coordinator workspace (absolute): `<coordinator-workspace-absolute-path>`.
- Worker workspace (absolute): `<worker-workspace-absolute-path>`.
- Sealed contract (absolute): `<sealed-contract-absolute-path>`.
- Contract seal digest: `<contract-seal-digest>`.
- Project convention paths: `<project-convention-absolute-paths>`.

Acceptance criteria, copied verbatim from the sealed contract:

```text
<acceptance-criteria-verbatim-from-sealed-contract>
```

Open and read the original contract before acting. The contract remains authoritative;
never paraphrase, summarize, weaken, or add acceptance criteria. Verify its seal against
the supplied digest. If it is missing, unreadable, unsealed, stale, or mismatched, stop
and ask the coordinator using the live preamble's `ask` command.

The coordinator alone writes the task and experience stores. Read-only task access uses
the dispatch spec, sealed contract, and `read_task(task_id, Path("<coordinator-workspace-absolute-path>"))`.
A new worktree has no gitignored task store: read from the coordinator's absolute path.
Do not call `checked_resume()`, depend on `brief()`, or write either store. Remote hosts
are outside this pilot.

## Pinned runtime

- Package (absolute): `<pinned-package-absolute-path>`.
- Expected manifest SHA-256: `<expected-manifest-sha256>`.
- Source revision: `<pinned-source-revision>`.

For this pilot, take the fixed values from `pinned-package.md`; use the same
`PYTHONPATH=<pinned-package-absolute-path>/src` for the version proof and checks.
Run the proof from the worker workspace:

```sh
PYTHONPATH="<pinned-package-absolute-path>/src" python3 -c 'import json, sys, managing_long_task_context as m; r = m.runtime_identity(package_root=sys.argv[1]); print(json.dumps({"loaded_module_file": m.__file__, "loaded_manifest_sha256": r["identity"]["loaded_manifest_sha256"]}))' "<pinned-package-absolute-path>"
```

This uses `runtime_identity(*, package_root)` and the returned
`identity.loaded_manifest_sha256`. Save the actual output. Resolve `loaded_module_file`
and require it to be under the pinned package directory; require a nonempty
`loaded_manifest_sha256` exactly equal to the expected digest. If either check fails,
stop and ask the coordinator; the worker's results are void. Leave global skill
installations unchanged.

## Durable report and settlement

- Report path template (absolute):
  `<worker-workspace-absolute-path>/.context-reports/<skill-task-id-fixed-before-dispatch>/<dispatch-id>.json`.
- Check output paths (absolute):
  `<worker-workspace-absolute-path>/.context-reports/<skill-task-id-fixed-before-dispatch>/<dispatch-id>-<check-name>.log`.

The coordinator fills every task-specific placeholder before dispatch, leaving the
literal `<dispatch-id>` for the worker. The worker takes the actual Orca Task and
Dispatch ids from `--task-id` and `--dispatch-id` in the live preamble's
`=== CLI COMMANDS ===` section, and substitutes that Dispatch id in output paths.

Write the JSON report immediately after the checks finish, before `worker_done`.
Use `report-example.json` only as a structural example: all its values are synthetic.
Required fields: `schema`, `task_id`, `orca_task_id`, `orca_dispatch_id`,
`contract_digest`, `loaded_module_file`, `loaded_manifest_sha256`, `code_revision`
(commit id and whether there are uncommitted changes), `checks` (each command, exit
code, output file path, and output summary), `files_modified`, `deferred_suggestions`,
`outcome_claim`, and `written_at` (UTC). Use actual observations; a check not run is
explicitly reported as not run, never given a passing exit code. Keep report and log
files out of Git.

Record each out-of-scope suggestion separately in `deferred_suggestions`; leave it
unimplemented and outside this round's acceptance. Re-check coordinator follow-ups at
natural checkpoints and immediately before settlement. Send heartbeats at the live
preamble's cadence even during long checks.

Send `worker_done` exactly once using the live preamble's command and ids, with
`--report-path` pointing to the written JSON and a three-sentence summary (work,
verification, remaining uncertainty). Use `--outcome failed` if the task is incomplete
or a blocker remains; include `--files-modified` only for actual changes. Orca settles
on that message; the claim is a lead for coordinator verification, not Strict
acceptance. Stop this dispatched work after sending it.
