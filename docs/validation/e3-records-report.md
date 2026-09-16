# E3 record-layer repair report

Scope: E3 host record persistence only. This repair changed the record ledger,
its strict replay hook, and isolated standard-library tests/fixtures. It did
not run a real Codex task, a model, a business action, an installation, a
deployment, or a package build.

## Frozen counterexamples and local outcome

- A controller request from generation 0 after activation at generation 1 is
  rejected before reservation; it cannot obtain `launch_allowed=true`.
- An observation with a different operation/argv/cwd/thread cannot end the
  prior attempt. A nonzero exit, non-UTF-8 stdout, or output limit also keeps
  the prior attempt unsafe and blocks a replacement.
- A v1 result cannot be processed after the contract moves to v2. A same
  attempt/result-version with different content archives both originals and
  immediately returns unknown; it is not silently selected as current.
- Strict replay rejects conflicting reservations for one attempt instead of
  last-write-wins projection.
- Repeated reconciliation preserves its prior verdict and rechecks a fresh
  host authorization receipt. `observe` returns bounded result/processed/action
  summaries and reports a non-pass verdict as unknown.
- Action outcomes require a reserved attempt, repeat idempotently, and refuse a
  changed outcome after `execution_unknown` without a new business action.
- A 96-character attempt receives a bounded reservation ID. Invalid UTF-8
  text and an unreserved result fail closed without raising through the public
  API.
- Once a replacement is reserved, a late result from its ended predecessor is
  still archived as `late` evidence but cannot be reconciled as current. A
  prepared handoff cannot reserve, and a child authorization is bound to its
  exact attempt for observation, result publication, and action outcome.
- A summary keeps the newest 64 entries and explicit totals. Any omission is
  `unknown/SUMMARY_LIMIT`, rather than a claim of complete recovery.

## Evidence

The initial red run added 6 counterexample methods (15 record tests total) and
failed with 7 assertion failures plus 1 error: arbitrary action recording,
overlong reservation ID, three unsafe observation unlocks, naked successful
observe, missing repeated verdict, and same-result content conflict. The error
was the pre-repair surrogate encoding exception.

The controller's independently supplied P11 red case (host authorization
revoked between verification and commit) initially produced
`PROCESSED/pass` in 14 probes (13 passed, 1 failed). The P01 Unicode
cross-layer digest probe also regressed once when record hashing used an ASCII
escape encoding (1 failed). Both are now green with the public synthetic
suite. A transport peer independently reproduced the late-predecessor-result
case; it is frozen locally as the replacement-result test below.

After the narrow repair:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 \
  -m unittest test_handoff_host_records test_handoff_codex_cli \
  test_handoff_protocol test_handoff_writes test_handoff_gate_combinations -q

Ran 76 tests in 6.882s
OK
```

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 \
  docs/validation/e3_controller_probes.py -q

Ran 16 tests in 0.565s
OK
```

This is local synthetic evidence only. It does not prove actual host
exclusivity, Codex CLI behavior outside the fixture, model execution, token
cost, a power-loss recovery, or natural business use.
