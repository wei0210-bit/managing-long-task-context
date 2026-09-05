---
name: context-lite
description: Use when a single primary agent needs low-risk, multi-turn task recovery from a small Markdown record rather than an auditable multi-agent control system.
---

# Context Lite

Use this Skill only after the user manually selects Lite. It records enough task
context to resume safely; it does not audit work, prove completion, or replace
live project observation.

For `start` and `checkpoint`, run `scripts/context_lite.py validate` or its atomic
`write` action instead of reproducing the checks in prose. If the helper cannot run,
do not claim deterministic validation; preserve the old `NOW.md` and report the
validator as unavailable. `skill-package.json` identifies this capability, and
installation or evaluation must use the complete package rather than `SKILL.md` alone.

```sh
python3 scripts/context_lite.py validate --file <candidate> --task-id <task-id>
python3 scripts/context_lite.py write --candidate <candidate> --base-dir <workspace> --task-id <task-id>
```

## Use When

After installing/updating a complete package, run `scripts/context_doctor.py check
--mode full --package-root <absolute-package>`. For identity-bound recovery use its
`resume` command with explicit `--package-root`, `--workspace-root`, `--context-root`
(the `.context-lite` directory), and `--task-id`. Initialize the existing task's binding
explicitly with `init-binding` and the trusted build receipt's manifest hash. Missing
or mismatched identity returns no recovery text; do not silently rebind. Full checks
are not per-turn work; legacy validate/write semantics are unchanged.

- One primary agent owns a low-risk task that spans turns, context windows, or days.
- Ordinary review or tests can recover mistakes, and the goal is to avoid repeated
  exploration, lost decisions, or an unclear next step.

## Do Not Use When

- The task needs auditability, frozen acceptance, independent validation, or more
  than one agent writing the same state.
- It includes publication, payment, deletion, sending messages, or another external
  side effect whose completion needs evidence. Manually select the existing Strict
  Skill at the repository root instead.

## Quick Reference

| Item | Fixed rule |
| --- | --- |
| Task ID | `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; no `/`, path separators, or `..` |
| `NOW.md` lines | At most 80 |
| `NOW.md` Unicode characters | At most 8,000 |
| One line | At most 500 characters |
| `Next` | At most 3 items; item 1 is the unique first action |

Store each task at `.context-lite/<task-id>/NOW.md`. Use the fixed template in
`assets/NOW.template.md`; do not add headings. Keep only the goal, current state,
decisions, blockers, and next work—not chat history, long logs, or copied code.
Load only `NOW.md` and targeted `refresh_ref`/`recovery_ref` observations; read
archives or logs only for a specific discrepancy.

## Stable References

Write references that a new turn can locate without guessing:

- File: absolute path; for a cross-workspace relative path also state its source
  workspace.
- Repository material: repository path plus immutable revision; include an exact
  symbol when the reference is code.
- Work item: exact issue or PR identifier; remote content: its full URL.
- External execution: an actually observed job, tool, or message ID. Never infer a
  session ID. A correlation reference locates an action; it never authorizes retry.
- Refresh or recovery: an exact read-only command, path, or external observation
  method. Do not put a mutating command in `refresh_ref` or `recovery_ref`.

## start

**Observations:** collect the task ID, exact goal, workspace, current UTC time, and
the current completion condition.

**Validation sequence:** validate the ID; inspect `.context-lite/<task-id>/`. If it
does not exist, create the directory and initial `NOW.md` from the fixed template.
If it exists, compare the stored exact goal before writing anything.

**Success output:** report the task ID, phase, `refreshed: 0`, `unknown: 0`, current
blockers, and one first action. A repeated `start` with the same ID and goal returns
the existing task unchanged.

**Hard stop:** if the existing goal differs, do not overwrite it; fail and ask for a
new task ID. Do not create a second active record for the same ID.

## checkpoint

**Observations:** reread live mutable sources, record their UTC RFC3339 observations,
and collect the proposed complete replacement of `NOW.md`.

**Validation sequence:** before any replacement, verify the fixed heading order,
stable references, UTC absolute timestamps, the unique first action, and every size
limit in the quick reference. Convert relative times and pointers such as “here” or
“the earlier task” into stable references. Then write and validate a temporary file
in the same directory and atomically rename it to `NOW.md`.

**Success output:** report the task ID, phase, refreshed count, `unknown` count,
blockers, and one first action; state that the validated checkpoint replaced
`NOW.md`.

**Hard stop:** on validation or write failure, preserve the old `NOW.md`; a temporary
file is never resumable state. On any limit breach, report the over-limit section
and the applicable exact form: `<n>/80 lines`, `<n>/8,000 Unicode characters`,
`line <n>: <m>/500 characters`, or `Next: <n>/3 items`; then offer exactly these
remedies:

1. Move raw material to an external artifact and keep a concise reference.
2. Remove resolved state.
3. Split the work into a separate task ID.

Never silently truncate Acceptance, Blockers, or the unique first action.

## resume

**Observations:** treat `NOW.md` as a lead, not live truth. Independently re-observe
every mutable `STATE-*` through its `refresh_ref`, and every `RUN-*` through its
matching read-only `recovery_ref`.

**Validation sequence:** map each refresh result only to its declared stable ID. A
missing, inaccessible, ambiguous, or stale observation changes only that state or
run to `unknown`; it does not invalidate unrelated entries. A recovery reference
must not update another `RUN-*`. Preserve old content as historical context only.

**Success output:** report the task ID, phase, refreshed count, unknown count,
blockers, and one first action. Make unknown states and runs explicit before any new
work begins.

**Hard stop:** this restores only persisted task context. It never restores hidden
reasoning, prior messages, credentials, processes, permissions, connections,
executor state, or a previous turn. It never auto-retries an in-flight action;
re-execution requires clear evidence it did not run and either that it is safe to
retry or explicit new user authorization.

## finish

**Observations:** verify that the user has selected a completion path and identify
the exact task directory.

**Validation sequence:** use archive by default: atomically move the record to
`.context-lite/archive/<task-id>-<UTC-timestamp>/`. For deletion, require the user
to explicitly select `--delete` and reconfirm the exact `.context-lite/<task-id>`
path after being told it is irreversible.

**Success output:** report the task ID, final phase, refreshed count, unknown count,
blockers, one first action (or `none` when finished), and whether the record was
archived or deleted.

**Hard stop:** without the exact deletion confirmation, keep the record and archive
instead. Neither finish path creates long-term memory or claims audited completion.

## Response Contract

For every action, return: task ID; phase; `refreshed: <count>`; `unknown: <count>`;
blockers; and exactly one `First action:`. If blocked, say what observation or user
authorization is needed. Do not claim that a checkpoint, refresh, archive, or record
proves an external result.
