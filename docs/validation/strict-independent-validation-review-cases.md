# Independent-validation review cases (frozen before fix round 1)

2026-09-11. Additive regression cases for defects introduced by the candidate;
the original IV01-IV22 expectations and scope remain unchanged. All synthetic.

| ID | Public scenario | Required verdict |
|---|---|---|
| CR01 | Independent receipt valid, declared Truth Source unobserved/dirty/expired | unknown, no completion pass |
| CR02 | Resolver appends a conflicted observation while file and contract remain unchanged | unknown, no completion pass |
| CR03 | Existing entry producer/owner/executor equals validated_by, host receipt labels differ | fail, preserve VALIDATOR_NOT_INDEPENDENT |
| CR04 | Release base gate passes, host policy contradicts stored false requirement | returned passed=false; emitted error count equals returned report, emit once |

Controller public probe: .superpowers/sdd/strict-independent-validation/controller_probes.py.
Pre-fix output: controller-review-probes-red.json. CR01 (unobserved), CR02 and CR03
actually returned passed=true. CR04 returned false but emitted errors 0. Probe initially
looked for uppercase PASS; its stdout check was corrected before the fix to compare
the actual emitted error count with returned errors (not to relax any expectation).

These checks must become maintained public tests in Task 1. Reuse existing truth entry
and tail; do not add another truth engine or accept callbacks that bypass controls.
Preserve locked entry/tail observation for changed non-truth context as well.
IV matrix gaps identified by independent review must be filled before acceptance;
no mock-only universal-pass semantic checker can serve as actual content verification.
# Receipt-time variants frozen before controller run

CR05 / IV07: A receipt expires while its resolver is running. At the actual
completion point it is no longer current: expected unknown and no pass.
CR06 / IV07: A valid receipt is produced after gate entry but before resolver return.
Its validated_at is not in the future at actual checking time: expected pass with
otherwise valid current evidence. Neither case retries the resolver.
Use a synthetic external clock seam with public gate, not wall-clock sleeping or a
mock of gate internals. Script: receipt_time_probe.py in the plan evidence workspace.
