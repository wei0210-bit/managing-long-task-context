# Evidence handler contract validation

Generated: 2026-09-02T04:49:26Z
Status: implementation PASS; installation, merge, push, and live Eval NOT PERFORMED
Branch: `codex/evidence-handler-contract`
Base revision: `c99404bbc028324b60faedf675d0408d850c94c4`
Validated source identity: `git:c99404bbc028324b60faedf675d0408d850c94c4+working-tree`

## Frozen scope

- Opt-in `evidence-handlers/v1` declarations validated before contract publication.
- Runtime resolver/verifier capability matching at every gate.
- Missing-evidence diagnostics that distinguish built-in and custom kinds.
- Preferred `record(..., supersedes=...)` path and a complete evidence-map example.
- No safety hard-stop changes and no changes outside this repository.

## Verification results

| Check | Result | Evidence |
| --- | --- | --- |
| Focused handler-contract tests | PASS | 7 tests, including publish-before-write, handler mismatch, callback suppression, diagnostics, and wrappers |
| Root Python 3.12 suite | PASS | 245 tests, 0 failures |
| Distributed Strict Python 3.12 suite | PASS | 218 tests, 0 failures |
| Distribution suite | PASS | 5 tests, root/distributed parity preserved |
| Strict executable example | PASS | publish, release, resolver, verifier, and completion all passed |
| Skill structure validation | PASS | root and distributed Strict both valid |
| Root package verification | PASS | 18 files, 4 documented paths, 10 Python exports |
| Distributed package verification | PASS | 14 files, 4 documented paths, 10 Python exports |
| Syntax compilation | PASS | root/distributed modules and examples |
| Whitespace/diff check | PASS | `git diff --check` produced no errors |

## Capability and compatibility result

New contracts may opt in to `evidence-handlers/v1`. Every required evidence kind must
then name stable resolver and verifier capabilities before the contract is sealed.
Built-in resolver capabilities are canonical; custom kinds remain supported through
explicit capability-wrapped runtime handlers.

Release, resume, handoff, and completion fail closed when the current runtime does not
match the sealed handler identities. A mismatch is checked before resolver or verifier
callbacks execute. Contracts that do not opt in retain the previous callable interface
and report shape.

## Complete package receipts

### Root source package

- `skill_version`: `0.4.0`
- Python package version: `0.4.0`
- files: 18
- source tree SHA-256: `b0ad15d681c9c5b2872ba8c01bbfacdd9eaa4dd43d17639b6688f2350b0486e8`
- working-tree manifest SHA-256: `aa916f26d13ac1e2d4ad3cddeeb17ddcdbe7a6bf7aa29144eeffa939551bebb3`

### Distributed Context Strict package

- `skill_version`: `0.4.0`
- Python package version: `0.4.0`
- files: 14
- source tree SHA-256: `86184e532421205af09171e24747f14eb1a289fbd85d450abc5cc82efdf2450d`
- working-tree manifest SHA-256: `bb7505c2af38680993255045923889253f96bc9e414976d074750544259f6b64`

Both package builds were verified against their generated manifest and exact external
manifest hash. These hashes identify the current working tree, not a release commit.

## TDD and safety evidence

The new tests first failed against the previous implementation for missing publication
validation, missing runtime capability checks, unsupported wrapped handlers, and absent
diagnostic guidance. A dedicated safety probe then exposed that mismatched handlers were
still invoked; the final implementation now blocks before callbacks and records zero
evidence attempts for that case.

## Delivery boundary and residual risk

- No global installation, merge, push, QMS-os modification, or external evaluation was performed.
- Existing sealed contracts remain legacy until deliberately republished with the opt-in capability.
- Static and unit validation prove package/interface consistency, not long-task behavioral effectiveness.
- After review and commit, rebuild both packages with the exact commit revision before installation or Eval.
