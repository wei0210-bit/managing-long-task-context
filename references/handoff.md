# Short-session handoff

Use this protocol only when the sealed task contract explicitly lists
`short-session-handoff/v1` in `required_capabilities`. Older contracts do not
gain it automatically, and an older package cannot migrate a live handoff by
reading these instructions.

Before any handoff request, run full verification against the complete built
package. Every call binds an absolute `base_dir`, `workspace_root`, and
`package_root`; a `BoundContext` must have captured the latter two at bind
time and rejects caller overrides.

Call `prepare_handoff(task_id, ..., record=...)` to persist a complete,
reference-bound candidate. `validate_handoff(..., handoff_id=...)` is read
only. `activate_handoff(..., request_id=..., controller_generation=...,
handoff_id=...)` and `cancel_handoff(...)` require a registered host identity,
a write authorization, and a content-reading handoff verifier.
`handoff_status(...)` is read only.

Package identity comes from the built package manifest and its import-time
runtime path. The host independently binds registered identity and
authorization to each request. The supplied example uses a fixed synthetic
registry that reads local fixture files: it is not a Codex/Claude adapter and
does not prove a real host identity or run a business action.
If there is no trusted host callback, return `unknown`; never invent a receipt
or reflect a request into a synthetic pass. Legacy direct writers may not
recognize handoff authority history, so the host must keep them fenced rather
than treating this reference as an automatic migration.

`check_status` reports current verification, while `commit_status` reports
only whether a durable control event is known to have committed. They are
separate: an `unknown` result must not trigger a blind retry. Read
`handoff_status` and investigate persisted records before a new request.
Activation does not make business completion pass; the existing completion
gate decides independently. In-flight child authorization remains bounded by
its registered work item and host policy.

No automatic adapter selection, occupancy threshold, background scheduler, or
live host migration is provided here.

## Session migration: mode, preflight, and three results

Choose and record the mode before any new session exists: `strict_protocol` or
`manual_fallback`. Missing, ambiguous (`automatic`, `skill`, `normal`), or silently switched
modes stop the migration. A Strict step that is UNKNOWN never turns into `manual_fallback`.

Strict v1 flow, in this order and reusing only the five v1 calls above:

```text
preflight --stage prepare  -> prepare_handoff
  -> create target -> obtain a real, re-readable thread ID
  -> target reads material and writes its readback
  -> preflight --stage activate (trusted host verifier) -> activate_handoff
  -> preflight --stage status -> report three results
```

Manual fallback only recovers information: `preflight --stage recovery` compares the handoff
material and never calls a v1 write entry, never writes control events, and never grants a
controller generation or archive permission.

Run the Strict-only script from the complete built package:

```text
PYTHONPATH=<package>/src python <package>/scripts/handoff_preflight.py
  --mode strict_protocol|manual_fallback --stage prepare|activate|status|recovery
  --package-root ABS --workspace-root ABS --task-id ID --plan RELATIVE
  --expected-plan-sha256 SHA256 --expected-verified-head GIT_SHA_OR_NONE
  [--context-root ABS --handoff-id ID]            (Strict only)
  [--handoff-file ABS --expected-handoff-sha256 SHA256
   --recovery-checklist ABS --expected-checklist-sha256 SHA256]
  [--recovery-readback ABS]
```

| Mode | Stage | Required facts |
|---|---|---|
| `strict_protocol` | `prepare` | package, plan/CONTEXT, Git scope, handoff + checklist, sealed contract listing this capability; no handoff record yet |
| `strict_protocol` | `activate` | the above plus the currently prepared record, exact readback, and a trusted host verifier |
| `strict_protocol` | `status` | readable v1 control events re-verified now; material is optional but all-or-none |
| `manual_fallback` | `recovery` | package, plan/CONTEXT, Git scope, handoff + checklist + exact readback |

Any other mode/stage pair or a non-applicable argument is `PREFLIGHT_INPUT_INVALID`. The CLI
has no host verifier, so Strict `activate`/`status` verification stays unknown unless host code
calls `run_preflight(..., handoff_verifier=...)` in-process with its trusted verifier.

The preflight reads the recovery entry `CONTEXT.md`: exactly one `AUTHORITATIVE_NOW`, split Git
fields (`baseline_head`, `implementation_head`, `verified_head`, `verified_at`; no
`observed_head`), the plan path/SHA, and the verified package manifest SHA. It reads `HEAD`
live: `verified_head` must be an ancestor, and later changes may touch only the plan,
`CONTEXT.md`, and `docs/superpowers/evidence/context-strict-migration/<run-id>/`. Relative links
must name tracked files. Every material input is a regular, non-symlinked file inside the
workspace, at most 1 MiB, hashed from the same bytes it parses.

`recovery-checklist/v1` (source session) and `recovery-readback/v1` (target session) contain
exactly `schema`, `task_id`, `handoff_sha256`, `plan_sha256`, `facts` (the readback adds
`checklist_sha256`). `facts` holds 1–64 objects with exactly `fact_id`, `category`, `value`,
`source_ref`; IDs are unique and each category `objective`, `current_state`, `constraints`,
`next_action`, `unresolved_risks` appears. Text must be NFC with LF only and is never trimmed or
case-folded. The checklist digest is SHA-256 of canonical JSON (sorted keys, compact separators,
`ensure_ascii=false`, facts sorted by `fact_id`).

The report (`migration-preflight/v1`) separates `preflight_status` from `migration_outcome`:

- `material_integrity=pass` only means files, paths, digests, and bindings match.
- `information_recovery=pass` only when every checklist fact is read back exactly; it covers the
  listed facts, not the whole old session. Without a readback it is `unknown`.
- `control_transfer` is `pass` only from a committed v1 activation that the current trusted
  verifier re-checks; history stays visible as `commit_status` when the current check is unknown.
- `source_retirement` is `not_allowed` and `archive_allowed=false` in every mode of this phase.

When any result is unknown: keep the source session, stop dispatching new controller work from it,
allow read-only checks, never blindly retry creation, activation, or archive, and follow the single
`next_readonly_action`. Exit `0/1/2` reports preflight `pass/fail/unknown` only.

For the opt-in, local-only Codex CLI adapter candidate, read
`references/host-codex-cli.md`. Its fixture tests do not establish real host
identity, clean-session creation, or production takeover support.
