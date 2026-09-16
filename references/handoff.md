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

For the opt-in, local-only Codex CLI adapter candidate, read
`references/host-codex-cli.md`. Its fixture tests do not establish real host
identity, clean-session creation, or production takeover support.
