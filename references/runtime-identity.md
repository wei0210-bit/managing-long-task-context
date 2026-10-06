# Runtime identity and workspace binding

Run a full diagnostic after installing/updating a complete package, or when
investigating its health. Use identity-only checks during recovery. Neither result
replaces evidence freshness, conflict checks, `audit()` or `gate()`.

## Complete package first

Use Python 3.10 or later, as required by the package. The `python3` examples
assume that command selects a supported interpreter.

The maintained source tree has no generated manifest. Build and verify a package
before checking installed identity. A missing manifest is unknown, not a healthy
development shortcut. Retain the build receipt's manifest SHA-256 independently;
do not derive an expected hash from an arbitrary currently loaded package.

For Strict, explicitly set `PYTHONPATH` to the selected package's `src` directory.
The diagnostic does not repair Python's module search path: a different loaded
module must be reported as a mismatch. The `PACKAGE`, `WORKSPACE` and `CONTEXT`
placeholders below must be replaced by absolute paths.

```sh
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_doctor.py check --mode full --package-root PACKAGE
```

For Lite, use the same command without `PYTHONPATH`. Package-only full checks run
their normal and rejection smoke cases in temporary storage. Passing does not
establish the identity of any existing task or a different running process.

## Bind an existing task explicitly

The task must already exist; binding creates only `context-binding.json`. Strict
`CONTEXT` is the absolute context store (usually `WORKSPACE/.prime/context`). Lite
`CONTEXT` is `WORKSPACE/.context-lite`, not `WORKSPACE`; its existing `write
--base-dir WORKSPACE` argument retains its old meaning.

```sh
python3 PACKAGE/scripts/context_doctor.py init-binding --package-root PACKAGE --expected-manifest-sha256 HASH --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
```

Repeat identical initialization safely. A differing binding is a conflict and is
not overwritten. Old tasks remain usable through legacy APIs, but without an
explicit binding the new checked recovery is unknown and returns no content.
Version upgrades or moves require an explicitly reviewed migration; automatic
rebinding is not provided. Keep the old binding and task materials until that
migration is resolved. Restarting alone does not authorize a new package hash.

Git workspaces must name their actual worktree root. Branch/HEAD changes are not
identity changes, but another worktree is a different workspace. A stored binding
may keep the absolute paths or the project-relative values `workspace_root: "."`
and `context_root: ".prime/context"`; both match the same worktree. A context store
can be outside the workspace; task paths cannot escape that store through a
symlink. A symlink to the installed package itself is resolved normally.

## Recover using a check in the caller

```sh
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_doctor.py check --mode identity --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_doctor.py resume --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
```

Lite uses the same commands without `PYTHONPATH`; its validator also exposes
`resume` with the same arguments. Successful recovery returns `diagnostic` and
`context`. A failed or unknown identity returns `context: null`. Strict's existing
context errors still block recovery; Python callers receive the original error.

Long-running Strict callers should use the check in their own process:

```python
import managing_long_task_context as context

client = context.bind(
    "/absolute/workspace/.prime/context",
    workspace_root="/absolute/workspace",
    package_root="/absolute/context-strict-package",
)
packet = client.checked_resume("TASK")
```

This captures both roots; later `chdir()` does not redirect the client. Legacy
`bind(base_dir)` and the old APIs keep their existing behavior and do not gain
implicit protection. `runtime_identity(package_root=...)` inspects the caller
without claiming task binding or completion.

## Strict resume gate (0.9.0)

`checked-resume-gate/v1` is listed by `runtime_identity()`, `checked_resume()`,
and the package capabilities. Older global installations have no resume gate
until the explicit global synchronization step; check the capability, not just pass.

Strict returns `diagnostic`, `context`, and the unmodified `resume_gate` report.
Identity failure still returns null. When Strict identity passes but the resume
gate fails or is unknown, it still returns context for diagnosis: **nonempty
context does not authorize continuing; require `diagnostic.status == "pass"`.**
Lite resume is unchanged: a failed resume returns null. Tampered contracts and
brief overflow still raise `ContextError` in Python / `RESUME_BLOCKED` in the CLI.

Module-level signature:

```python
checked_resume(task_id, *, package_root, workspace_root, base_dir,
               resolvers=None, verifiers=None, rule_runtime=None)
```

It reads `brief()` first, then calls `gate(stage="resume", emit=False)` with the
same base_dir and all non-superseded items. Only when neither resolver nor verifier
was supplied, exact errors from `runtime_evidence_handler_errors` containing
`capability unavailable: expected ` become `resume_handlers=not_run`; completion
needs host handlers. Capability mismatch and explicit missing handlers remain
`resume_gate=fail`. `RULE_RUNTIME_UNAVAILABLE` becomes `resume_rules=unknown`;
other errors fail with `RESUME_GATE_FAILED`. Warnings stay in the raw gate report.

Compare brief `context_version` with gate `stats.events`: a difference adds a
separate `resume_race=unknown/RESUME_GATE_RACE`; missing counts are
`RESUME_RACE_UNCHECKED`. Handler classification checks the read contract version
against the gate's version. Race never changes a real gate failure to unknown.
Gate exceptions yield unknown / `RESUME_GATE_UNAVAILABLE` and preserve context.
CLI stdout remains one JSON object; fail exits 1, unknown exits 2, pass exits 0.

Recovery actions: stale facts with `ttl_hours` need re-observation and
`update_item`; those without TTL need `record(..., supersedes=<old id>)` with TTL.
Resolve conflicts by superseding losers and `update_item(status="active")` on a
conflicted winner. Dispatch may target 解除该阻塞; other new execution waits for
pass. Missing rule runtime needs a Python host with `rule_runtime`. Races and gate
exceptions allow one rerun; handle persistent errors, do not retry indefinitely.

Known limitations: `BoundContext.gate` injects `independent_validation_required`
but `BoundContext.checked_resume` does not, so policy conclusions may differ.
The bound resume API does not forward host handlers; use the module-level API.
Experience-stage unknowns such as `STORE_NOT_INITIALIZED` lack
`RULE_RUNTIME_UNAVAILABLE` and conservatively remain gate failures.

## Read task status

```sh
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_status.py --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK --json
```

This read-only command shows identity, resume gate, latest checkpoint, all recorded
Orca dispatch IDs, and brief markdown. Identity/gate/brief come from checked
recovery; checkpoint/dispatches come from `read_task`'s snapshot and are marked
unverified when identity did not pass. Missing/inconsistent snapshots are unavailable.
A nondefault context root makes snapshot sections unavailable. Missing binding
shows a complete init-binding command with an independent-digest placeholder;
only the coordinator executes it after checking that digest. It never connects
to Orca or reads worker reports. Exit codes match doctor resume.

## Interpret the report

`pass`, `fail`, `unknown` map to exit codes 0, 1, 2. Missing/unreadable observations
are unknown; confirmed identity conflicts are fail. `checks` explains each item,
`codes` is a stable sorted list, and `next_action` identifies remediation.
`full_verification: not_run` is expected in identity mode. Scope distinguishes
package-only, task, and process-only checks. No full result proves business work
complete or means a different Agent has restarted.

Identity mode reads metadata, not the event history or evidence originals. It
does not hash every payload file or run smoke tests. The subsequent normal
`brief()` recovery has its own required reads and safety controls.

The process records its manifest identity around controlled module loading.
Missing/changed loading metadata is unknown, and later manifest changes reject
checked recovery until restart and resolution of the expected binding. Payload
changes without a manifest change are only detected by full verification. This
mechanism assumes normal complete-package installation; it is not protection
against malicious runtime manipulation or arbitrary concurrent partial writes.
It also cannot verify which instructions a model actually read.

## Distribution and verification

`scripts/sync_context_strict_skill.py` also runs tool synchronization; generated
tool copies must remain byte-identical to their single maintained sources.
Full diagnostics are offline and temporary. They may create temporary samples,
but must not rewrite a real task. Initialization is a separate explicit write.
Temporary cleanup errors are failures, not silently successful completion.

Use the test matrix in `docs/specs/runtime-identity-doctor.md` in the development
repository. Package receipts and automated tests prove delivery behavior; natural
multi-session evaluation and measured token savings remain separate evidence.
