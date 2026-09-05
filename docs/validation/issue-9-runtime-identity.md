# Issue 9 validation

Status: implementation and independent local validation passed (2026-09-05 UTC).

Source: GitHub issue 9, docs/specs/runtime-identity-doctor.md.
Branch: codex/runtime-identity-doctor; base commit 6e7edfc.
Execution model: gpt-5.6-terra, reasoning high, for implementation and acceptance tests.
Primary agent owns integration, code review and independent command execution.

## Verification scope

Local development and complete package behavior only. No global install, merge,
code push, production operation, online Eval or measured token saving is claimed.
Use Python 3.12 on this host; system Python 3.9 is below project requirements.

## Evidence

Commands and bounded outputs are captured under .scratch/issue9-validation/ by
.scratch/issue9_validate.py. This directory is intentionally local and ignored;
final portable results and test references are summarized here after verification.
Package source revisions identify working-tree content, not an uncommitted Git revision.

## Independent review findings

Before final tests the primary review requested:

- Capture manifest before and after all controlled imports, using actual module paths.
- Publish complete bindings atomically with no overwrite; do not expose partial JSON.
- Fail closed on Git inspection errors and binding symlink escape.
- Parse and hash identical manifest bytes; preserve all full-verification errors.
- Preserve specified unknown state for old bindings and unconfigured bound clients.

All listed findings were resolved and the final suites were re-run by the primary.
Final review additionally retained the doctor's own loaded path alongside the
Strict runtime paths, added the doctor's import baseline, used built-in file
evidence and an exact missing-evidence assertion for smoke, and verified successful
bound Strict recovery followed by rejection of a modified sealed contract.

## Executed results

Interpreter: /opt/homebrew/bin/python3.12. All commands exited 0.

| Check | Result |
|---|---|
| Root unittest discovery | 291 executed, 291 passed |
| Generated Strict unittest discovery | 263 discovered, 255 passed, 8 skipped |
| Root/Strict/Lite generated copy parity | Passed in root distribution suite |
| Strict complete package build and verify | 25 payload files, 15 exports, 5 documented paths checked |
| Lite complete package build and verify | 7 payload files, 3 documented paths checked |
| Strict full doctor outside development checkout | pass; explicit package/src PYTHONPATH |
| Lite full doctor outside development checkout | pass; no development PYTHONPATH |
| git diff --check | Passed |
| Sealed Context Strict completion gate | 13/13 criteria passed; no errors |

The 8 skipped Strict-distribution cases require the development tree containing
both Lite and Strict sources; they all ran in the root suite. The Strict runtime
acceptance cases also execute in the standalone Strict test suite. No assertion
was removed or relaxed to obtain these results.

Reproduce: synchronize with scripts/sync_context_strict_skill.py, run unittest
discovery at the repository root and skills/context-strict, then build each
skills/context-* source into a fresh temporary destination with skill_package.py
build and verify it. Run each package's scripts/context_doctor.py check --mode full
--package-root ABSOLUTE_PACKAGE from outside the checkout, with explicit
PYTHONPATH=ABSOLUTE_PACKAGE/src only for Strict. Exact expanded commands and
stdout/stderr hashes are in .scratch/issue9-validation/commands.json.

## Acceptance evidence mapping

R = tests/test_runtime_identity.py; D = tests/test_context_doctor.py.

| AC | Independent executable evidence |
|---|---|
| 1 | R test_identity_report_has_complete_schema_and_explicit_full_not_run; CLI input cases |
| 2 | R test_workspace_and_storage_mismatches_never_pass_for_same_task_name; D real Git worktree test |
| 3 | R identical binding byte comparison, conflicting initialization, concurrent two-writer test |
| 4 | R test_bound_strict_resume_succeeds_from_another_cwd_and_preserves_sealed_errors; D commit/branch test |
| 5 | R missing/invalid/unreadable bindings and schema/UTC/extra-field tests |
| 6 | D full tampering test; R identity full_verification=not_run |
| 7 | R wrong PYTHONPATH, changed/appearing manifest during import, post-import change, foreign-doctor test |
| 8 | D complete-package full checks plus Lite valid/invalid recovery; full uses exact expected rejection |
| 9 | D test_full_task_check_does_not_change_task_bytes and cleanup failure; R bound recovery hashes |
| 10 | R sys.addaudithook test asserts zero history/evidence open attempts; full/smoke remain not_run |
| 11 | Original context/evidence/truth/production tests and R sealed-contract failure after identity passes |
| 12 | Root distribution/package tests, two independent package builds/verifies/full commands |
| 13 | R guarded missing-binding and foreign-doctor tests; D rejected Lite recovery returns context=null |

## Measured diagnostic work (single local sample)

The additional metrics probe counts Python-process file-open attempts, including
runtime/stdlib imports during the diagnostic, but not file reads inside Git's
subprocess. It records unique paths as well as attempts; these are not token counts.
Timing excludes Python startup and the initial doctor import but includes runtime
loading inside the check. Identity uses a bound task; full is package-only, so these
are different scopes, not a controlled speed benchmark.

| Skill/mode | Seconds | Output characters | Open attempts / unique paths | History opens |
|---|---:|---:|---:|---:|
| Strict identity | 0.116 | 1850 | 66 / 62 | 0 |
| Strict full | 0.115 | 1343 | 146 / 92 | 2 (temporary smoke only) |
| Lite identity | 0.034 | 1838 | 10 / 6 | 0 |
| Lite full | 0.010 | 1326 | 30 / 13 | 0 |

Evidence: .scratch/issue9-validation/metrics.json. No claim of measured token
savings or faster completion follows from these numbers.

## Frozen package receipts

These identify the verified working-tree artifacts, not a published release.
Temporary built packages were cleaned after verification; build inputs remain in
the working tree and the original receipts remain in local validation logs.

| Package | Version | Manifest SHA-256 |
|---|---|---|
| Strict | 0.6.0 | e6f1b6943b7e61e355cdc12670cfde1463d0f4ff8f77346e2fddaee6332206ca |
| Lite | 1.2.0 | a847ee93b508172faf10d601c9458428e377832b40d393eaf2a0def2e1055dc5 |

Strict working-tree build-input digest: a7f6a85ffc3aa72d82ac0185f4e87c9cad7ecedfdb92c95b57c4f2e99c973cbf.
Lite working-tree build-input digest: fe9a083f51139bc9ad792bd430221d282fafdcbbcc8b08d184cdc1f0f7c4955b.
These are the runner's input fingerprints embedded in source_revision, distinct
from the manifest's source_tree_sha256 calculation.

## Boundaries

Light identity checks do not detect payload edits which leave the manifest
unchanged; full verification does. The process baseline is not malicious-runtime
authentication, and cannot prove which SKILL.md text an Agent read. Legacy APIs
remain compatible and outside the new identity wrapper. No global installation,
commit, merge, remote code push, or online Eval has been performed for this change.
