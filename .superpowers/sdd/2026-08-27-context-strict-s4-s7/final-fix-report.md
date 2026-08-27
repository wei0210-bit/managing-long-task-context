# Strict S4-S7 final fix report

Date: 2026-08-27  
Branch: `feat/context-strict-s4-s7`  
Base: `17bb82354693f21643349ea52a1e67ea8f8d3692`  
Implementation commit: `82615a02923ee0dc54e6d12e906ccf9437ee6281`

## TDD RED evidence

Production code was unchanged when the C1-C5 public regressions were first run. The exact command was:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_completion_global_conflict_gate_cannot_be_narrowed_by_required_item_ids \
  tests.test_context.ContextSkillTests.test_completion_consumes_canonical_required_hops \
  tests.test_context.ContextSkillTests.test_completion_rejects_self_reported_unbound_hops \
  tests.test_context.ContextSkillTests.test_completion_requires_validator_when_independent_validation_is_requested \
  tests.test_context.ContextSkillTests.test_completion_rejects_same_producer_and_validator \
  tests.test_context.ContextSkillTests.test_completion_callbacks_cannot_mutate_sealed_requirements_or_callers \
  tests.test_context.ContextSkillTests.test_publish_rejects_invalid_freshness_windows \
  tests.test_context.ContextSkillTests.test_publish_rejects_invalid_freshness_override \
  tests.test_context.ContextSkillTests.test_completion_rejects_future_date_only_and_naive_generated_at \
  tests.test_context.ContextSkillTests.test_public_audit_and_gate_signatures_do_not_expose_probe_bypass \
  tests.test_context.ContextSkillTests.test_public_probe_bypass_keyword_is_rejected -v
```

Result: exit 1; 11 tests ran in 0.050s; 16 failures and 0 errors. The captured output is `/tmp/context-strict-c1-c5-red.txt`. Load-bearing excerpts:

- C1: `AssertionError: True is not false` when only the normal item ID was requested and a different item was conflicted.
- C2: canonical hops, unbound caller hops, absent validator, and same producer/validator all returned completion pass (`True is not false`).
- C3: a resolver/verifier that cleared callback inputs made completion pass (`True is not false`).
- C4: string/negative windows and invalid overrides were accepted (`ContextError not raised`); future/date-only/naive timestamps were not all rejected.
- C5: both public signatures contained `_run_probe`, and both public bypass calls failed to raise `TypeError`.

The broader I1-I5/Minor RED command ran 16 focused tests in 0.213s and produced 29 failures plus 8 errors (`/tmp/context-strict-i1-i5-minor-red.txt`). It demonstrated exception escape, malformed/missing identity bypasses, incorrect tri-state/counters, ignored revision constraints, stale documentation, fragment/URL/error-code mismatches, and unbounded/I/O failure behavior.

Late self-review regressions were also written before their fixes. They genuinely reproduced: malformed evidence kind softened to unknown (4 failures); incomplete receipt, receipt-producer independence, malformed sibling preflight, and standalone example failures (4 failures); actor-role brief omission plus invalid UTF-8 event escape (1 failure, 1 error); and pre-JSON security-key coercion, malformed approver authorization, and explicitly required superseded-item bypass (4 failures). All are green in the final suites below.

## Finding-by-finding disposition

| Finding | Status | Implementation and regression evidence |
|---|---|---|
| C1 global conflict gate | Addressed | Completion scans every non-superseded item for conflict/blocker state before applying `required_item_ids`; an explicitly required superseded item also fails (`src/managing_long_task_context/__init__.py:1427-1466`). Public regression: `tests/test_context.py:1103` and superseded boundary coverage immediately following it. |
| C2 hops and independent validation | Addressed | Publish validates canonical/compatibility aliases, delivery controls, actor roles, and fail-closed independence (`__init__.py:192-289`). Completion derives hops only from passing evidence-local bindings and checks validator roles/separation across primary evidence and receipts (`__init__.py:1591-1601`, `1713-1737`, `1803-1847`). Regressions: `tests/test_context.py:1217`, `1269`, `1304`, `1339`. |
| C3 callback mutation | Addressed | Gate iterates deep-copied criteria/contract snapshots; criterion evaluation seals private baselines; every resolver/verifier receives independent deep copies (`__init__.py:1482-1511`, `1569-1698`; `src/managing_long_task_context/evidence.py:73-147`). Malicious-callback regression: `tests/test_context.py:1398`. |
| C4 freshness fail-closed | Addressed | Publish accepts only non-negative integer windows and validates override keys before JSON coercion (`__init__.py:259-270`, `614-631`). Evidence accepts explicit UTC RFC3339, enforces the documented 300-second skew, and rejects invalid/stale windows (`evidence.py:489-540`). Regressions: `tests/test_context.py:1493`; `tests/test_evidence.py:506`, `531`. |
| C5 probe bypass | Addressed | Public `audit`/`gate` expose no probe switch and always call private cores with the probe enabled; the recursive bad sample alone uses the private no-probe path (`__init__.py:1178-1220`, `1364-1382`, `1850-1877`). Signature/bypass regressions: `tests/test_context.py:1545`. |
| I1 tri-state aggregation | Addressed | Malformed evidence/receipt/hop bindings are fail; missing required evidence/type/hop/receipt remains unknown; final order is fail > unknown > pass (`__init__.py:1603-1754`; `evidence.py:92-105`). Table regression: `tests/test_context.py:1566`; malformed-kind regression: `tests/test_evidence.py:486`. |
| I2 deterministic failures and bounded reads | Addressed | Resolver/verifier exceptions are normalized (`evidence.py:73-147`, `204-214`); local reads are streamed/bounded to 16 MiB (`evidence.py:429-474`); Git uses a five-second timeout with deterministic launch/timeout codes (`evidence.py:652-670`). Event UTF-8/read failures become counted audit errors (`__init__.py:407-455`). Regressions: `tests/test_evidence.py:582`, `612`; `tests/test_context.py:1689`, `1893`. |
| I3 evidence identity | Addressed | All evidence and receipts are preflighted before any callback; non-mapping, missing/blank/non-string, and duplicate IDs fail across the shared namespace (`__init__.py:1614-1676`). Regression: `tests/test_context.py:1747`. |
| I4 authoritative revision | Addressed | Exact and ancestor requirements are parsed from criterion scope, Git ancestry uses `merge-base --is-ancestor`, and test-report internal revision/scope are authoritative (`evidence.py:241-332`, `551-650`). The real two-commit regression includes exact mismatch, valid ancestry, and reverse ancestor mismatch (`tests/test_evidence.py:635`). |
| I5 brief and executable docs | Addressed | Brief renders evidence, hop, delivery, scope/revision, freshness, independence, and actor-role controls (`__init__.py:1066-1137`). `SKILL.md:72-124` documents structured IDs, bound hops, receipts, UTC/skew, size, and revision behavior. `examples/strict_completion.py:1-96` is directly runnable and uses the public API; regression: `tests/test_context.py:1862`. |
| M1 file locator fragments | Addressed | Local resolution separates the path before `#` while preserving the original locator for verifier input (`evidence.py:385-427`). Regression: `tests/test_evidence.py:558`. |
| M2 normalized URL boundary | Addressed | Hostnames are lowercased and trailing dots removed before localhost checks; ambiguous numeric forms are rejected (`evidence.py:672-711`). Regression: `tests/test_evidence.py:732`. |
| M3 error names and counters | Addressed | Built-ins consistently emit `MALFORMED_LOCATOR`; events count the failing nonblank record, and probe scanned count comes from actual criterion evaluation (`evidence.py:334-427`, `672-711`; `__init__.py:407-455`, `1178-1220`). Regressions: `tests/test_evidence.py:750`; `tests/test_context.py:1881`, `1893`. |

No scoped finding is residual.

## GREEN verification

Required focused suites, run after the final implementation:

```text
python3 -m unittest tests.test_evidence -v
Ran 36 tests in 0.346s — OK

python3 -m unittest tests.test_context -v
Ran 61 tests in 0.474s — OK
```

The task-specific targeted command exercised global conflicts, unbound hops, mutation, freshness, public probe bypass, callback/permission/Git failures, identity, exact/ancestor revision, standalone docs, receipt independence, and invalid event UTF-8:

```text
Ran 15 tests in 0.356s — OK
```

Full suite:

```text
python3 -m unittest discover -s tests -v
Ran 97 tests in 0.717s — OK
exit status: 0
```

Diff/status evidence:

```text
git diff --check
exit status: 0; no output

git diff --check HEAD^ HEAD
exit status: 0; no output

git status --short
exit status: 0; no output immediately after implementation commit
```

An independent read-only final diff audit also reported no remaining Critical, Important, or Minor blocker and independently confirmed 36/36 evidence, 61/61 context, and 97/97 full-suite results.

## Commit and changed files

Implementation commit: `82615a02923ee0dc54e6d12e906ccf9437ee6281` (`fix: close strict evidence bypasses`).

Changed implementation files:

- `SKILL.md`
- `examples/strict_completion.py`
- `src/managing_long_task_context/__init__.py`
- `src/managing_long_task_context/evidence.py`
- `tests/test_context.py`
- `tests/test_evidence.py`

This report is committed separately as the only follow-up artifact.

## Compatibility decisions, residual risks, and concerns

- `required_evidence` and `chain_hops` remain compatibility aliases only when they do not conflict with canonical fields. The legacy entry-level `covered_hops` may still be present but never proves a hop; evidence-local bindings do.
- Caller `result` and persisted resolver status remain non-authoritative. Custom resolvers/verifiers remain injectable, but every completion invocation runs them afresh with isolated copies and deterministic tri-state normalization.
- Missing observations remain recoverable `unknown`; malformed input or explicit invalidity is `fail`. Receipts now require the complete v1.1 shape and participate in validator/producer separation.
- The built-in URL resolver intentionally performs no network access, so a syntactically valid public HTTPS URL remains `unknown/NETWORK_BLOCKED` unless an explicit resolver is supplied.
- The contract digest remains an integrity mechanism, not identity authentication, as documented. No event-chain signing, handoff migration/repair state machine, or Lite behavior was added.
- Residual risk for this wave: none within C1-C5, I1-I5, or M1-M3. No spec conflict or unresolved concern was found.
