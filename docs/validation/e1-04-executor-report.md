# E1-04 executor report: AC1--AC3 gate matrix

Contract SHA256 was rechecked as `4f33bb0f711e877d370b76faeae9ffa57d11fa661c0bf70f093602e5555e7624`. Scope is only the original gate-combination matrix; no production host, business action, paid model, migration implementation, source edit, commit, or deployment occurred.

## Actual runs

The detailed 24-case record is [e1-04-executor-runs.json](e1-04-executor-runs.json). Every case created a separate `/private/tmp` synthetic workspace and real `basis.txt`, published a sealed contract, prepared a real handoff, and called `activate_handoff`. Valid rows then called the existing completion gate. The fixture's host verifier, file verifier, independent receipt resolver, and optional rule runtime all read the fixture's actual text, not a handwritten status result.

| Frozen cases | Switches | valid | invalid basis | changed after check |
| --- | --- | ---: | ---: | ---: |
| E0-148--150 | none | pass | blocked | blocked |
| E0-151--153 | independent validation | pass | blocked | blocked |
| E0-154--156 | rule execution | pass | blocked | blocked |
| E0-157--159 | rule + independent | pass | blocked | blocked |
| E0-160--162 | Truth Sources | pass | blocked | blocked |
| E0-163--165 | Truth Sources + independent | pass | blocked | blocked |
| E0-166--168 | Truth Sources + rule | pass | blocked | blocked |
| E0-169--171 | all three | pass | blocked | blocked |

For all 8 valid rows, activation returned `pass/confirmed_committed`, one `handoff_activated` event existed, controller generation became 1, and completion passed. Each valid row then separately called completion with the literal empty evidence map; all 8 were blocked for missing `file` evidence. For all 8 missing-basis rows, the post-prepare removal of the actual bearing `basis.txt` made activation `unknown/not_attempted`, added no activation event, and the public `handoff_status` reported generation 0 with `confirmed_not_committed`. For all 8 changed-after-check rows, the verifier first read all handoff references semantically and only then changed that same `basis.txt`, before activation commit; observed result was likewise `unknown/not_attempted`, no activation event, and public status generation 0. The later completion call also remained closed in both invalid classes.

The test directly loads each row's stimulus and expected check/commit/generation delta from frozen `tests/fixtures/handoff/cases.json` (SHA256 `87c7fac347d430476dd1fb0f3e73ad976670b2885da0ce44dffc82b5fc19ba4c`); it does not maintain a hand-written ID-to-switch map. The fixture asserts the actual sealed contract fields for each row: optional `truth-sources/v1` and `rule-execution/v1` capability membership, criterion-level `independent_validation_required`, and nonempty seal digest.

The frozen rows start at controller generation 7; the isolated product fixture starts at 0. It therefore asserts the frozen `expected_generation_delta` (not a false equality of absolute generations): valid is `0 → 1`, invalid is `0 → 0`, corresponding to frozen `7 → 8` and `7 → 7`. This is a state-machine equivalence mapping, not an assertion that the frozen initial input was run verbatim.

## AC2 and AC3 results

A separate all-three-switch run persisted a real blocking context item before transfer. Handoff preparation and activation still passed at generation 1, proving that a complete transfer basis is not treated as business completion; the original completion gate remained false due to the explicit blocker.

Independent-validation negatives exercised the same public completion seam after a successful activation: model self-report, malformed forged checker result, same validator/executor principal, and expired receipt all remained blocked. The valid path is a synthetic trusted callback with distinct executor/validator principals; it reads `basis.txt` before issuing its receipt and binds task, criterion, current sealed contract digest, workspace, and actual evidence digest. It is not real-host identity verification.

## TDD and regression evidence

The first red run exposed a fixture-only contract mismatch: its `prepare` authority supplied `subject_session_ref`, although the pre-activation authority shape must omit it. A later audit also found the initial hand-written E0 ID-to-switch map was wrong; that run is discarded as per-ID evidence. The test now loads the frozen cases directly. The minimal fixture corrections made explicit `validation_resolver=None` stay absent rather than silently falling back to the synthetic resolver, and preserved a literal empty evidence map instead of rebuilding it. The corrected direct-consumption run passed in 0.346 s. No product source changed.

Existing public tests were then run, not merely cited:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_truth_sources test_independent_validation test_rule_execution test_handoff_activation -v
138 passed, 0 failed, 4.800 s
```

## Denominator and boundary

Executed/required matrix cases: 24/24. Valid allows: 8/8. Valid-row empty-business-evidence blocks: 8/8. Removed-basis blocks: 8/8. Post-verifier-change blocks: 8/8. Skipped: 0. False allow: 0. False block: 0. Program repeat and host callback timing are local synthetic evidence only; model verdict, token use, and natural usage are `UNKNOWN`.

Not run by this owned slice: E0-172--177 real Codex/Claude host-level migration, the isolated old-package process mechanism owned by the migration executor, production business action, model/token measurement, and root's full regression. The E2 distribution difference remains outside scope and was not modified.
