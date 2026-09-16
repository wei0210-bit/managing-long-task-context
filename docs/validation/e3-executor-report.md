# E3 Codex CLI transport executor report

Scope: `host_codex_cli.py`, its isolated standard-library fixture/tests, the
transport reference, and this report. No real Codex task, model call, install,
commit, push, deployment, or package/distribution edit was performed.

Current local evidence:

- `test_handoff_codex_cli`: 15/15 passed. These use a real local Python fixture
  subprocess, not `subprocess.run` mocks. Coverage includes literal argv prompt
  separation, canonical cwd, DEVNULL EOF, precise resume UUID/JSON event,
  trusted receipt rejection, no duplicate start after reservation, bounded
  stdout/stderr, direct-child timeout behavior, inherited-pipe uncertainty,
  malformed/conflicting/invalid-UTF8 event streams, invalid text before reserve,
  config TOML value rejection, and program/workspace replacement after reserve.
- The inherited-pipe path is additionally run in a separate Python interpreter
  with `ResourceWarning` enabled. It waits a bounded interval for the fixture
  grandchild to release both pipes and asserts no unclosed `BufferedReader`
  warning; readers close their own streams, while the main thread never closes
  a reader still blocked on a descendant-held pipe.
- One transport test is a real temporary `HostTaskLedger` vertical slice:
  contract → reserve → Python fixture → 0600 stdout/exit archive → new Ledger
  instance observes persisted state → duplicate same attempt leaves launch count
  at one. It uses the ledger's frozen 21-field observation schema, not the
  isolated fake ledger.
- `test_handoff_host_records`: 15/15 passed; frozen controller probes: 14/14
  passed. These are supporting local protocol checks, not a claim of host or
  business success.

R13 boundary: UTF-8 stdout is preserved by the Ledger in a per-attempt 0600
artifact; events hold bounded metadata and archive reference only. Non-UTF-8
stdout has its actual byte digest/size but no readable original and remains
`execution_unknown`; stderr is digest/size metadata only. Actual Codex host
identity, exclusive control, clean sessions, rollover, parent-exit behavior,
model execution, and business/natural outcomes remain `NOT_RUN`/`unknown`.
