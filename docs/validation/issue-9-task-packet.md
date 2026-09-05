# Issue 9 development task packet

Approved source: docs/specs/runtime-identity-doctor.md and GitHub issue 9.
Branch: codex/runtime-identity-doctor. Baseline: 6e7edfc.
Principle: correctness first; economy without weakening hard stops.

## Implementation executor — Terra / high

Own scripts/context_identity_core.py, scripts/context_doctor.py, scripts/sync_context_tools.py,
src/managing_long_task_context/runtime_identity.py, __init__.py integration,
skills/context-lite/scripts/context_lite.py, and targeted implementation-only tests if needed.
Implement the complete frozen API, report, binding semantics, runtime baseline, full smoke,
identity-only checks and checked resume. Generated copies are produced by sync, not hand edited.
Coordinate generated _identity_core.py with primary agent. No ownership of acceptance test files.

Deliver code, exact commands/exit codes, scope limitations, and any unresolved failing acceptance IDs.
Run targeted tests plus existing context and Lite tests after integration becomes available.
Fail if any required check returns pass on unknown/mismatch, if old contracts/records are changed,
or if an unrelated fallback bypasses a hard stop. Do not alter frozen criteria to make tests green.

## Independent test executor — Terra / high

Own tests/test_runtime_identity.py and tests/test_context_doctor.py only.
Read spec and existing fixtures; independently test public interfaces, not private implementation.
Cover AC1–13, at least 10 unit, 9 integration and 6 package scenarios in aggregate.
Include real worktrees, race/no-overwrite, wrong PYTHONPATH, import-time baseline changes,
unknown binding, full without task, Lite layout, zero history I/O in identity, real-file hashes.
Use temporary directories and unittest. Report failures rather than weakening assertions.

## Primary integration and review

Own package declarations/versions, sync_context_strict_skill.py, distribution-test updates,
SKILL/README/reference documentation, task context and validation report. Independently read implementation
and execute root suite, generated Strict suite, full package builds/verifies and independent CLI smoke.
Check docs/API paths, generated-copy parity and AC-to-test coverage before declaring complete.

## Predetermined verification

Host check found system python3 is 3.9, below pyproject's >=3.10 requirement.
Use /opt/homebrew/bin/python3.12 for the commands below on this machine; child
commands use sys.executable so package smoke runs with the same supported interpreter.

1. python3 -m unittest discover -s tests -p 'test_runtime_identity.py' -v
2. python3 -m unittest discover -s tests -p 'test_context_doctor.py' -v
3. python3 -m unittest discover -s tests -v
4. python3 scripts/sync_context_strict_skill.py; inspect generated changes and parity.
5. Build both skills with scripts/skill_package.py build into fresh temporary paths, then verify each.
6. From outside repo with explicit Strict PYTHONPATH=<package>/src, run each package doctor full.
7. Run generated Strict tests and record command, exit code and counts.

Acceptance source is the numbered AC1–13 in the spec. Every verdict must cite executed test names
or independently read artifacts, not an agent status message. Full and identity diagnostics measure
elapsed time and output characters; zero historical reads must have executable assertions.

## Side-effect and human gates

Only this branch/workspace and temporary test directories are writable scope. No global installation,
merge, remote code push, production actions, evaluation jobs or edits in other projects.
No external natural verification is scheduled or claimed. Completion here means implementation and
local artifact verification; distribution and actual user/eval results remain separate outcomes.
