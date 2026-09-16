# E4 native-host boundary executor report

Scope is limited to two conservative capability-entry modules, their focused
tests, `references/host-native.md`, and this report.  The frozen execution
contract SHA-256 was verified as
`667ac8dee1457adea9bd00769545a6620c21ffdc63c6b3365f92845942919394`.
No real native task, model call, host bridge, CLI invocation, installation,
package/generated-file/CI edit, commit, push, deployment, or remote-upload
retry was performed.

## Red then green

Red command, after only callable conservative stubs were present:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_native test_handoff_claude_native -v
Ran 6 tests in 0.001s
FAILED (failures=2, errors=4)
```

The failures were behavioral: inventories lacked the frozen schema/evidence
fields, known controls lacked unsupported/zero-grant responses, and malformed
operations were not rejected.  They were not import failures.

Green command after the narrow static implementations:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_native test_handoff_claude_native -v
Ran 6 tests in 0.001s
OK
```

The six tests cover separated Codex/Claude inventories, twenty repeated
side-effect-free observations with detached return values, declared-versus-
unknown boundaries, known control refusal, and malformed/malicious operation
rejection.  They do not claim a real trusted-host path.

## R1 snapshot-label repair

Review found the two inventories omitted their fixed observation date and
scope.  Both now expose `observed_at: 2026-09-15` and the identical scope:
`snapshot of this call environment only; not runtime probing or end-to-end host validation`.
The source descriptions no longer call this a current or automatic runtime
probe.  The same focused command was rerun after this metadata-only repair;
its final green result was:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_native test_handoff_claude_native -v
Ran 6 tests in 0.001s
OK
```

## Files and remaining boundary

- `src/managing_long_task_context/host_codex_native.py`
- `src/managing_long_task_context/host_claude_native.py`
- `tests/test_handoff_codex_native.py`
- `tests/test_handoff_claude_native.py`
- `references/host-native.md`

Both entries are read-only static inventories.  They do not use the E3 ledger
or handoff writers and cannot create a task state.  `start`, `resume`,
`takeover`, and `archive` return `unknown`/`unsupported` with zero grant;
unknown or malformed inputs fail closed without being executed.  Codex
same-parent-tree addressing is schema-declared only; Claude native support is
unavailable in this host and does not borrow CLI evidence.  Trusted identity,
write fencing, clean-history proof, parent survival, cross-parent continuation,
real-host/model/natural validation, and token benefit remain `UNKNOWN` or
`NOT_RUN`.  Manual handoff retains the current identity, record, and old
session; it neither archives the sole recovery entry nor re-dispatches unknown
in-flight work.

Self-review found only the five implementation/test/reference files above plus
this report were added for E4.  `git diff --check` produced no output, but E4
files are untracked until the controller decides integration; this is not a
package or CI verification.
