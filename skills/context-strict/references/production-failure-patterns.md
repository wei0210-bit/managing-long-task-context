# Production failure patterns

Read this reference only when designing or reviewing a Strict contract, verifier,
externalization, or recovery path. Normal execution should use `brief()` and the
sealed contract instead of loading this file.

## Ask what goes red

For every important claim, ask: **if the claim is false, what deterministic check
becomes red?** A caveat written only in prose is not a control. Bind it to a contract
field, resolver, verifier, freshness rule, truth source, or gate that can fail.

## Evidence is not its own truth

An evidence object is a claim envelope. A resolver establishes that the referenced
artifact can be read and is fresh/in-scope; a verifier establishes that its contents
support the criterion. Do not let an envelope prove itself merely by repeating the
expected scope, revision, status, or hop names.

## Ordered chains need one ordered witness

Legacy `required_hops` uses aggregate coverage across all passing evidence. That is
appropriate for independent requirements, but it can incorrectly assemble a causal
chain from unrelated artifacts. For a sequence that must be proven by one execution,
seal:

```json
{
  "required_hops": ["export", "snapshot"],
  "required_hops_mode": "single-evidence-ordered"
}
```

The ordered mode requires `evidence-handlers/v1`. One passing evidence object's
`covered_hops` must contain the required list as an ordered subsequence. Split or
reversed evidence remains unknown and blocks completion. Omission of the mode keeps
the legacy aggregate behavior.

## Externalization is not supersession

Use `record(..., supersedes=old_id)` only when a new fact replaces the old fact.
The old item becomes invalid for current use. Do not use supersession merely to make a
brief shorter: a new stub can silently lose `required`, `severity`, evidence, scope, or
freshness controls.

Use `externalize_item()` when the fact is unchanged and only its wording is bulky. It
keeps the item ID, fact controls, evidence, original actor, and `verified_at`, while
replacing the statement with a concise summary and stable external reference. The
prior event retains the original text. The reference must use an existing canonical
absolute `file:` path (an optional `#anchor` is allowed); relative paths, symlinks,
missing files, non-regular files, and oversized files fail closed. The API stores a
bounded SHA-256 fingerprint without loading the file into the model context. Audit and
transition gates block if the reference becomes unreadable or its content changes.
An identical retry is a no-op; changing an already externalized item requires a
separate explicit state transition rather than overwriting its provenance.
`update_item()` therefore rejects all reserved externalization metadata fields. If the
underlying fact changes, record and verify the replacement with `supersedes`. For an
early 0.5 record that has the same summary/reference but no reference digest, the same
`externalize_item()` call validates the file and appends exactly one digest-sealing
migration event; it does not rewrite the original event.

`restore_externalization_controls()` exists only for a legacy supersede-based repair.
It copies `required` and `severity` from the directly superseded source to its target,
refuses lineage or value conflicts, preserves every other target field, and records the
reason in the append-only event.

## Contract protection is advisory, not a security boundary

New contracts are atomically published with read-only file mode and seal
`file_protection=read-only-advisory-v1`. This catches common in-place editor mistakes.
It does not defeat a process that can chmod the file or replace it through a writable
parent directory. The integrity digest and gate remain authoritative; identity still
requires external authentication or signed storage.

Use `protect_contract=False` only as an explicit compatibility escape hatch. The seal
records `file_protection=none`. A controlled higher-version publish can replace a
read-only contract and reapplies the guard.

## Base-directory drift is duplicate state, not recovery

Relative default storage follows the current working directory. A process launched
from another directory can therefore create or look for a different task with the same
ID. Prefer `context.bind("/absolute/path/.prime/context")`; `MLTC_BASE_DIR` is accepted
only when absolute. The library never searches parent directories automatically.

Audit, gate, and brief diagnostics expose `resolved_base_dir`, `task_root`, and
`base_dir_source`. Lock errors include the resolved lock path. Treat a mismatch as a
configuration error; do not merge two stores by guessing which is newer.

## Overflow is an unusable handoff

`brief_diagnostics()` returns every omitted mandatory ID and `usable=false` on
overflow. `brief()` never returns a partial mandatory packet. Release, resume, and
handoff all block until detail is safely externalized, conflicts are resolved, or the
publisher deliberately splits/version-updates the task. Do not raise the budget first
or remove mandatory controls to make the gate green.
