# Strict Completion Merge Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Strict completion blockers by requiring dated independent validation, using a trusted current-UTC clock, rejecting future delivery receipts, and restoring a clean whole-range diff check.

**Architecture:** Keep the public `gate()` as the only completion entry point but remove its caller-controlled `now` argument. A private UTC clock supplies one observation time to `_gate_core`, which threads that same instant through evidence freshness, independent-validation time, and delivery-receipt time checks. Preserve the existing 300-second clock-skew allowance and tri-state rules; do not expand evidence-ID scope or start R1–R4.

**Tech Stack:** Python 3.10+, standard library only, `unittest`, Git.

**Spec:** `docs/specs/context-skills-v1.1.md`

## Global Constraints

- The completion gate measures evidence age from the gate's actual current UTC time; a public caller cannot override that reference time.
- `MAX_CLOCK_SKEW_SECONDS` remains exactly `300`; an explicit UTC timestamp up to 300 seconds ahead is permitted, while anything further ahead is `fail`.
- When `independent_validation_required` is true, the acceptance mapping requires both `validated_by` and `validated_at`; missing `validated_at` is `unknown`, malformed or too-far-future `validated_at` is `fail`.
- Delivery receipt `sent_at` and `observed_at` must be explicit UTC RFC3339 and must not exceed trusted current UTC plus 300 seconds.
- Tri-state propagation remains `fail > unknown > pass`; any required `unknown` blocks completion.
- `evaluate_evidence(..., now=...)` remains an independently callable deterministic resolver seam; only the public completion `gate()` loses caller time injection.
- Existing compatibility aliases and per-criterion evidence-ID uniqueness remain unchanged. Cross-criterion global ID uniqueness is out of scope.
- Python remains dependency-free and compatible with 3.10 or newer.
- Work only in `/Users/zhaowei/Desktop/David/project/managing-long-task-context/.worktrees/context-strict-s4-s7` on `feat/context-strict-s4-s7`; do not merge, push, or modify `main`.

## Root Cause Record

- Reproduction: against `f0ba541`, public API harnesses returned `passed=True` for missing `validated_at`, `generated_at=2099` paired with caller `now=2099`, and a delivery receipt whose `sent_at`/`observed_at` were in 2099. The baseline suite still reported 97/97 because those public boundaries were absent from the suite.
- Trace: public `gate(now=...)` forwards the caller value to `_gate_core`, which forwards it to every criterion and `evaluate_evidence`; `_independent_validation_check` never reads `validated_at`; `_valid_delivery_receipt` verifies only timestamp syntax. The range diff failure independently traces to Markdown hard-break spaces committed on three report lines.
- Working pattern: evidence freshness already parses explicit UTC and applies `MAX_CLOCK_SKEW_SECONDS=300`; the completion layer should consume the same constant and one trusted UTC observation instead of inventing another policy.
- Confirmed hypothesis: removing the public clock input, threading one private observation time, and applying the existing parser/skew boundary to validation and receipt times closes all three semantic reproductions without changing resolver determinism or evidence-ID scope.

---

### Task 1: Close trusted-time and validation-time blockers

**Files:**
- Modify: `src/managing_long_task_context/__init__.py`
- Modify: `tests/test_context.py`
- Modify: `SKILL.md`
- Modify: `examples/strict_completion.py`
- Modify only to remove three trailing-space characters: `.superpowers/sdd/2026-08-27-context-strict-s4-s7/final-fix-report.md:3-5`

**Interfaces:**
- Consumes: `gate(...)`, `_gate_core(...)`, `_evaluate_completion_criterion(...)`, `_independent_validation_check(...)`, `_valid_delivery_receipt(...)`, and `evidence.MAX_CLOCK_SKEW_SECONDS` from the current branch.
- Produces: public `gate(...)` without a `now` parameter; private `_trusted_utc_now() -> datetime`; one trusted `datetime` passed to each criterion; independent-validation result codes `MISSING_VALIDATED_AT`, `INVALID_VALIDATED_AT`, and `FUTURE_VALIDATED_AT`; delivery-receipt failures that name the offending future time field.
- Preserves: private `_gate_core(..., now: datetime | None, run_probe: bool)` for isolated probe and deterministic internal testing; public `evaluate_evidence(..., now=...)` unchanged.

**Acceptance criteria:**

- `inspect.signature(context.gate).parameters` does not contain `now`, and `context.gate(..., now=...)` raises `TypeError`.
- A file evidence generated in 2099 cannot pass completion by supplying a forged public reference time.
- Missing `validated_at` produces independent-validation `unknown/MISSING_VALIDATED_AT`; malformed and more-than-300-seconds-future values produce `fail` with their explicit codes.
- A correctly authorized independent validator with a valid explicit-UTC `validated_at` at or before trusted current time can pass.
- A delivery receipt with `sent_at` or `observed_at` beyond trusted current UTC plus 300 seconds is `fail`; a timestamp within the 300-second allowance is not rejected merely for clock skew.
- Existing deletion re-resolution, scope, hop, delivery, probe-isolation, and full-suite behavior remain green.
- The documented example calls the real public API without `now` and generates a current UTC evidence timestamp so it remains executable after 2026-08-27.
- `git diff --check 17bb82354693f21643349ea52a1e67ea8f8d3692..HEAD` is silent.

**Failure conditions:**

- Public `gate()` still accepts a caller time, reads time from the evidence map, or uses a different time per criterion.
- Missing `validated_at` is softened to pass, while malformed/future validation times are softened to unknown.
- All positive clock skew is rejected, contradicting the agreed 300-second allowance.
- Delivery receipts are only syntax-checked and future timestamps still pass.
- Tests call `_gate_core` instead of exercising public `gate`, assert source text, or use production code to calculate their expected result.
- The implementation changes `evaluate_evidence`'s public deterministic `now` seam, adds cross-criterion ID behavior, or touches R1–R4.
- Existing tests are deleted or weakened to accommodate the new public signature.

- [ ] **Step 1: Add RED public tests without changing production code**

Extend the datetime import exactly as follows:

```python
from datetime import datetime, timedelta, timezone
```

At RED time, keep every existing `now=NOW` call unchanged. Add these public behavior tests; the validation/receipt fixtures deliberately use the current public `now=NOW` only to isolate their missing checks before the public clock seam is removed in Step 3:

```python
def test_public_gate_rejects_caller_supplied_now(self):
    self.publish()
    self.assertNotIn("now", inspect.signature(context.gate).parameters)
    with self.assertRaises(TypeError):
        context.gate("TASK-001", stage="release", now=NOW, base_dir=self.base, emit=False)

def test_completion_requires_validated_at_for_independent_validation(self):
    criterion = self.contract["acceptance_criteria"][0]
    criterion["required_evidence"] = ["custom"]
    criterion["chain_hops"] = []
    criterion["independent_validation_required"] = True
    self.contract["actor_roles"] = {
        "executor-01": ["executor"],
        "validator-01": ["validator"],
    }
    self.publish()
    report = context.gate(
        "TASK-001",
        stage="completion",
        evidence_map={
            "AC-01": {
                "validated_by": "validator-01",
                "evidence": [{
                    "evidence_id": "EV-UNDATED",
                    "kind": "custom",
                    "produced_by": "executor-01",
                }],
            }
        },
        resolvers={"custom": passing_resolver},
        verifiers={"custom": passing_verifier},
        now=NOW,
        base_dir=self.base,
        emit=False,
    )
    self.assertFalse(report["passed"])
    self.assertEqual(report["criteria"]["AC-01"]["independent_validation"], {
        "status": "unknown", "codes": ["MISSING_VALIDATED_AT"]
    })

    dated_report = context.gate(
        "TASK-001",
        stage="completion",
        evidence_map={
            "AC-01": {
                "validated_by": "validator-01",
                "validated_at": NOW.isoformat().replace("+00:00", "Z"),
                "evidence": [{
                    "evidence_id": "EV-DATED",
                    "kind": "custom",
                    "produced_by": "executor-01",
                }],
            }
        },
        resolvers={"custom": passing_resolver},
        verifiers={"custom": passing_verifier},
        now=NOW,
        base_dir=self.base,
        emit=False,
    )
    self.assertTrue(dated_report["passed"], dated_report["errors"])
    self.assertEqual(dated_report["criteria"]["AC-01"]["independent_validation"], {
        "status": "pass", "codes": []
    })

def test_completion_rejects_invalid_and_future_validated_at(self):
    criterion = self.contract["acceptance_criteria"][0]
    criterion["required_evidence"] = ["custom"]
    criterion["chain_hops"] = []
    criterion["independent_validation_required"] = True
    self.contract["actor_roles"] = {
        "executor-01": ["executor"],
        "validator-01": ["validator"],
    }
    self.publish()
    for value, code in (("not-a-time", "INVALID_VALIDATED_AT"),
                        ("2099-01-01T00:00:00Z", "FUTURE_VALIDATED_AT")):
        with self.subTest(value=value):
            report = context.gate(
                "TASK-001",
                stage="completion",
                evidence_map={
                    "AC-01": {
                        "validated_by": "validator-01",
                        "validated_at": value,
                        "evidence": [{
                            "evidence_id": "EV-DATED",
                            "kind": "custom",
                            "produced_by": "executor-01",
                        }],
                    }
                },
                resolvers={"custom": passing_resolver},
                verifiers={"custom": passing_verifier},
                now=NOW,
                base_dir=self.base,
                emit=False,
            )
            self.assertFalse(report["passed"])
            independence = report["criteria"]["AC-01"]["independent_validation"]
            self.assertEqual(independence["status"], "fail")
            self.assertIn(code, independence["codes"])

def test_completion_rejects_future_delivery_receipt_timestamps(self):
    criterion = self.contract["acceptance_criteria"][0]
    criterion["required_evidence"] = ["custom"]
    criterion["chain_hops"] = []
    criterion["required_delivery_types"] = ["feishu"]
    self.publish()

    def run(sent_at, observed_at):
        receipt = valid_delivery_receipt(
            "EV-RECEIPT-TIME",
            artifact_ref="EV-PRIMARY",
            sent_at=sent_at,
            observed_at=observed_at,
        )
        return context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [{"evidence_id": "EV-PRIMARY", "kind": "custom"}],
                    "delivery_receipts": [receipt],
                }
            },
            resolvers={
                "custom": passing_resolver,
                "delivery-receipt": passing_resolver,
            },
            verifiers={
                "custom": passing_verifier,
                "delivery-receipt": passing_verifier,
            },
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

    near = (NOW + timedelta(seconds=299)).isoformat().replace("+00:00", "Z")
    far = (NOW + timedelta(seconds=301)).isoformat().replace("+00:00", "Z")
    baseline = NOW.isoformat().replace("+00:00", "Z")
    within_skew_report = run(near, near)
    self.assertTrue(within_skew_report["passed"], within_skew_report["errors"])
    for field, sent_at, observed_at, code in (
        ("sent_at", far, baseline, "FUTURE_DELIVERY_SENT_AT"),
        ("observed_at", baseline, far, "FUTURE_DELIVERY_OBSERVED_AT"),
    ):
        with self.subTest(field=field):
            future_report = run(sent_at, observed_at)
            self.assertFalse(future_report["passed"])
            receipt_result = future_report["criteria"]["AC-01"]["evidence_results"][1]
            self.assertIn(code, receipt_result["checks"]["resolve"]["codes"])
```

- [ ] **Step 2: Run RED verification before production edits**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_public_gate_rejects_caller_supplied_now \
  tests.test_context.ContextSkillTests.test_completion_requires_validated_at_for_independent_validation \
  tests.test_context.ContextSkillTests.test_completion_rejects_invalid_and_future_validated_at \
  tests.test_context.ContextSkillTests.test_completion_rejects_future_delivery_receipt_timestamps -v
```

Expected RED causes against `f0ba541`: public `gate` exposes `now`; missing/malformed/future `validated_at` does not block; future receipt timestamps pass. The +299-second receipt subcase may already pass, but the same test must fail on the +301-second subcases. If a test errors because its fixture is malformed, fix the fixture and re-run until it fails on the intended production behavior.

- [ ] **Step 3: Introduce one trusted UTC observation per public gate**

In `src/managing_long_task_context/__init__.py`, import the existing skew constant and add the private clock boundary:

```python
from .evidence import MAX_CLOCK_SKEW_SECONDS, canonical_json_bytes, evaluate_evidence

def _trusted_utc_now() -> datetime:
    return datetime.now(timezone.utc)
```

Remove `now` from the public `gate` signature. At the start of `_gate_core`, normalize exactly one observation time:

```python
observed_now = (now or _trusted_utc_now()).astimezone(timezone.utc)
```

Pass `observed_now`, not the optional parameter, to every `_evaluate_completion_criterion` call. Public `gate()` calls `_gate_core(..., now=_trusted_utc_now(), run_probe=True)`; `_run_bad_sample_probe()` may keep calling private `_gate_core` without a supplied time.

Only after `_trusted_utc_now` exists, patch that external system-clock boundary in `ContextSkillTests.setUp`:

```python
self.clock = patch.object(context, "_trusted_utc_now", return_value=NOW)
self.clock.start()
self.addCleanup(self.clock.stop)
```

Then remove `now=NOW` from every public `context.gate` call, including the new validation/receipt tests, except the intentional `assertRaises(TypeError)` call in `test_public_gate_rejects_caller_supplied_now`. Retain `now=NOW` in direct `evaluate_evidence` calls. The already-existing `test_completion_rejects_future_date_only_and_naive_generated_at` must now exercise the trusted patched UTC rather than a public override.

- [ ] **Step 4: Enforce validation and receipt timestamps with tri-state semantics**

Extract one parser from the existing `_valid_explicit_utc_timestamp` logic:

```python
def _parse_explicit_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or _EXPLICIT_UTC_RFC3339_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)
```

Pass the trusted `now` to `_independent_validation_check`. Before role separation, enforce:

```python
validated_at_value = entry.get("validated_at")
if validated_at_value is None:
    return {"status": "unknown", "codes": ["MISSING_VALIDATED_AT"]}
validated_at = _parse_explicit_utc_timestamp(validated_at_value)
if validated_at is None:
    return {"status": "fail", "codes": ["INVALID_VALIDATED_AT"]}
if validated_at > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
    return {"status": "fail", "codes": ["FUTURE_VALIDATED_AT"]}
```

For each otherwise well-formed delivery receipt, parse `sent_at` and `observed_at` and fail the receipt result if either exceeds the same boundary. Use stable codes `FUTURE_DELIVERY_SENT_AT` and `FUTURE_DELIVERY_OBSERVED_AT`; preserve existing `MALFORMED_DELIVERY_RECEIPT` for malformed syntax.

- [ ] **Step 5: Update public docs and the executable example**

In `SKILL.md`, remove the public `now=` argument and state that completion uses the gate's current UTC. Add `validated_at` to the independent-validation mapping example.

In `examples/strict_completion.py`, replace the fixed evidence time and public `now=` with:

```python
generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

Use `generated_at` in the evidence object and call public `context.gate()` without a time override. Keep the existing executable-example test as the consumer-facing proof.

- [ ] **Step 6: Remove the committed report whitespace and run GREEN verification**

Remove only the Markdown hard-break spaces on lines 3–5 of `.superpowers/sdd/2026-08-27-context-strict-s4-s7/final-fix-report.md`; do not rewrite or reinterpret the old report.

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_public_gate_rejects_caller_supplied_now \
  tests.test_context.ContextSkillTests.test_completion_requires_validated_at_for_independent_validation \
  tests.test_context.ContextSkillTests.test_completion_rejects_invalid_and_future_validated_at \
  tests.test_context.ContextSkillTests.test_completion_rejects_future_delivery_receipt_timestamps \
  tests.test_context.ContextSkillTests.test_completion_rejects_future_date_only_and_naive_generated_at \
  tests.test_context.ContextSkillTests.test_documented_structured_completion_example_executes -v
python3 -m unittest tests.test_context -v
python3 -m unittest tests.test_evidence -v
python3 -m unittest discover -s tests -v
git diff --check f0ba5415c5a2c7fdf0d6e4ff27d1a49ac7915baf..HEAD
git diff --check 17bb82354693f21643349ea52a1e67ea8f8d3692..HEAD
```

Expected: every focused and full test has zero failures/errors; both diff checks are silent.

- [ ] **Step 7: Self-review, commit, and report evidence**

Confirm the public signature has no caller clock, all completion criteria share one trusted instant, the 300-second allowance has both inside/outside boundary tests, and no out-of-scope ID/R1–R4 change exists.

```bash
git add src/managing_long_task_context/__init__.py tests/test_context.py SKILL.md examples/strict_completion.py .superpowers/sdd/2026-08-27-context-strict-s4-s7/final-fix-report.md
git commit -m "fix: trust completion validation time"
git status --short
```

**Required report evidence:** exact RED command and expected failure excerpts; focused GREEN counts; context/evidence/full-suite counts; both diff-check exit codes; public `gate` signature; boundary results at +299 and +301 seconds; commit SHA; changed-file list; self-review findings and concerns.

---

## Plan Self-Review Record

- Spec coverage: this plan maps v1.1 current-UTC freshness and required `validated_at` directly to one trusted gate observation and uses the existing 300-second skew decision consistently for evidence, validation, and delivery timestamps.
- Scope coverage: it closes only the two semantic blockers and the exact diff-check failure selected by the user; cross-criterion ID uniqueness, R1–R4, migration, repair, handoff, and Lite remain untouched.
- Placeholder scan: completed; every new test body has a complete public input and literal status/code expectation, with no deferred or incomplete implementation instruction.
- Type consistency: public `gate` loses `now`; private `_gate_core` retains optional `datetime`; `_independent_validation_check` gains the normalized `datetime`; `evaluate_evidence` retains its existing deterministic `now` interface.
