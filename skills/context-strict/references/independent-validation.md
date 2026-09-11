# Independent validation boundary

Use this only when a sealed acceptance criterion needs an independently checked host
result. This is a local mechanism, not an adapter: no Codex or Claude host adapter has
been verified.

The host passes `independent_validation_required=True` and a callable
`validation_resolver` to `bind()`, `publish_contract()`, or `gate()`. A bound context
captures both; calls cannot replace them. The contract criterion declares
`independent_validation_required: true`; the completion evidence entry may carry only a
`validation_ref` **for the independent receipt**; normal criterion evidence is still
required. The resolver is called once with that reference and must return a host receipt
bound to the sealed task, criterion, contract digest, canonical workspace,
evidence digests, required revision, distinct executor and validator principals, run and
checker IDs, current UTC times, and `check_result` (`pass`, `fail`, or `unknown`).

Never treat a model-provided receipt, status, actor label, or different thread name as
proof. The model cannot supply host policy or a resolver. In-process Python code is the
trust boundary: this library cannot authenticate a caller that can replace the host or
library code. A required stored `true` criterion with no trusted resolver blocks as
`unknown`; a trusted self-review or checker `fail` blocks as `fail`. Criteria that are
explicitly `false` or omitted remain on the existing low-risk path. Existing true
criteria cannot be downgraded without explicit host policy `False`.

`assurance: verified` means only that this independent-receipt layer verified; it never
overrides the normal evidence resolver/verifier or a semantic business check that fails.

The synthetic [example](../examples/independent_validation.py) uses a fixed fixture-owned
receipt registry, runs one valid receipt, then demonstrates both unknown-reference and
stored-true/no-resolver blocking. It has no credentials or production-host claim.
