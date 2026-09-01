# Context package hardening validation

Generated: 2026-09-01T02:23:45Z
Status: implementation PASS; release and installation NOT PERFORMED
Branch: `codex/truth-source-contract`
Base revision: `1f322af4f4cfe69b24b4dc802a1cdc71ebdf6502`
Validated source identity: `git:1f322af4f4cfe69b24b4dc802a1cdc71ebdf6502+working-tree`

## Frozen scope

- Strict package version/capability identity and executable consistency.
- Context Lite deterministic validator.
- Deterministic routing recommendation with human final selection.
- No safety hard-stop changes and no v6 T2-specific prompt tuning.

## Verification results

| Check | Result | Evidence |
| --- | --- | --- |
| Root Python 3.12 suite | PASS | 238 tests, 0 failures |
| Distributed Strict Python 3.12 suite | PASS | 211 tests, 0 failures |
| Focused package/Lite/router tests | PASS | 27 tests, including tamper and preservation failures |
| Skill structure validation | PASS | Context Lite and Context Strict both valid |
| Strict source/package check | PASS | 14 payload files, 4 documented paths, 10 Python exports |
| Lite source/package check | PASS | 4 payload files, 2 documented paths, 0 Python exports |
| Syntax compilation | PASS | all three new scripts under Python 3.12 |
| Whitespace/diff check | PASS | `git diff --check` produced no errors |
| Strict runtime safety diff | PASS | no working-tree changes under either Strict `src/managing_long_task_context` copy |
| T2-specific prompt scan | PASS | no T2/evidence-ID tuning text in changed Skill or routing files |

## Complete package receipts

### Context Strict

- `skill_version`: `0.3.0`
- Python package version: `0.3.0`
- files: 14
- source tree SHA-256: `0f814c1d2e65a7d5fd7c763eb211eac83bcce6c238836777497f74814770e74d`
- working-tree manifest SHA-256: `86b09a27ebd497cd9fff180db903c3571bd5b196e09012cd30d4703c3bf0ea9d`
- pinned manifest and source-revision verification: PASS

### Context Lite

- `skill_version`: `1.1.0`
- files: 4
- source tree SHA-256: `6563086e490e2c2c7ebb022f7a73812d3376a4f35c4fafab82417165df6dca6a`
- working-tree manifest SHA-256: `548dce951a44fc386f41f79b662ba016eff569a814e578fbad1f33219223ec76`
- pinned manifest and source-revision verification: PASS

Negative tests prove fail-closed handling for missing files, added files, file tampering,
manifest identity drift, external manifest-hash mismatch, source-revision mismatch,
missing documented APIs, missing required package paths, invalid Lite structure,
unsafe observation commands, goal conflicts, and failed candidate validation.

## Installation/evaluation boundary

The existing global Lite and Strict installations correctly fail the new verifier with
`PACKAGE_MANIFEST_MISSING`; they were not modified. The v6 SKILL-only snapshot remains a
legacy evaluation artifact and is not upgraded by this implementation.

The manifest hashes above identify the current working tree, not a release commit. After
review and commit, build both packages again with `git:<exact-commit>`, freeze the new
manifest hashes in the installation/evaluation receipt, and only then install or evaluate.

## Residual risk

- Static validation proves package integrity and declared interface presence, not long-task behavioral effectiveness.
- Lite stable-reference validation intentionally accepts a small read-only command allowlist; uncommon observation methods must use an explicit `observe:` or `read:` reference.
- Routing is only as complete as its supplied risk facts and must be rerun when task scope changes.
- No independent model/agent behavioral review or live three-arm evaluation was performed in this implementation phase.
