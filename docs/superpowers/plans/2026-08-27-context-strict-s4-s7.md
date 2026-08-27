# Context Strict S4-S7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Strict completion depend on freshly resolved evidence, accurately named integrity protection, deterministic fail/unknown propagation, and an isolated production-path audit probe.

**Architecture:** Add a focused `evidence.py` module that owns resolver/verifier layering and built-in local resolvers while the existing package entrypoint continues to own contracts, the event ledger, audit, and gates. Keep the current public import path and event layout; integrate evidence evaluation into `gate(stage="completion")` without treating runtime claims or caller-supplied `result` values as proof.

**Tech Stack:** Python 3.10+, Python standard library, `unittest`.

**Spec:** `docs/specs/context-skills-v1.1.md`

## Global Constraints

- `context-strict` remains independent from `context-lite`; this plan changes only the existing Strict implementation, tests, contract example, and Strict documentation.
- No production code may be written before the assigned test has been run and observed failing for the expected behavior.
- Keep `managing_long_task_context` as the public import path and keep all 18 baseline tests green.
- Use only the Python standard library; do not add package dependencies or network calls.
- Resolver layers are `resolve`, `integrity_and_freshness`, and `scope`; semantic support is a separate `claim` result produced only by a typed verifier or independent validator.
- Required evidence resolving to `fail` or `unknown` blocks completion; caller-supplied `result: "pass"`, runtime messages, traces, and Agent reports never override resolver/verifier results.
- Contract SHA-256 protection is named `integrity_digest` and is described only as content-integrity protection, not identity authentication.
- A task dispatch must contain scope, owned files, deliverables, acceptance criteria, failure conditions, exact verification commands, and required evidence before work starts.
- Agent reports and green commands from another Agent are not controller verification; the controller inspects every diff and runs fresh verification before accepting each task.
- Implementers do not push, merge, publish, change GitHub issues, or dispatch their own subagents/reviewers.

---

### Task 1: Add pluggable evidence resolvers and separate claim verification (S4)

**Scope:** Implement deterministic evidence evaluation and built-in offline resolvers for `file`, `git-commit`, `test-report`, and syntax-only `url`. Do not change `gate()` in this task.

**Owned files:**
- Create: `src/managing_long_task_context/evidence.py`
- Create: `tests/test_evidence.py`

**Interfaces:**
- Produces `evaluate_evidence(evidence, criterion, contract, *, resolvers=None, verifiers=None, now=None) -> dict[str, Any]`.
- Produces `canonical_json_bytes(value) -> bytes`, a dependency-free RFC 8785-compatible encoder for the schema's supported JSON values.
- A resolver is a callable `(evidence, criterion, contract, now) -> Mapping[str, Any]` returning the three non-semantic checks named `resolve`, `integrity_and_freshness`, and `scope`.
- A verifier is a callable `(evidence, criterion, resolution) -> Mapping[str, Any]` returning one `claim` check.
- Produces `default_resolvers() -> dict[str, Callable[..., Mapping[str, Any]]]` for `file`, `git-commit`, `test-report`, and `url`.
- Produces deterministic checks shaped as `{"status": "pass|fail|unknown", "codes": ["..."]}` and an overall tri-state using fail-before-unknown-before-pass propagation.

**Deliverables:**
- Resolver output cannot set semantic claim status; an unregistered verifier yields `unknown` with `CLAIM_NOT_VERIFIED` even if a resolver includes an extra forged `claim: pass` key.
- Local paths resolve from `contract.workspace_root`; final realpaths must remain under `workspace_root` or `evidence_roots`.
- File and test-report integrity use `sha256:<lowercase-hex>`; test-report digest covers RFC 8785 canonical UTF-8 JSON excluding its top-level `artifact_digest`.
- Canonical JSON accepts `null`, booleans, strings, integers, arrays, and string-keyed objects; it rejects floats and non-string keys in this first Strict tranche, orders object keys by UTF-16 code units, and uses minimal JSON string escaping. This deliberately prevents Python-specific float rendering from pretending to be cross-runtime canonicalization.
- Freshness uses the supplied UTC `now`, `generated_at`, `expires_at`, `max_evidence_age_seconds`, and optional `evidence_freshness_by_type` override.
- Required scope is a subset of evidence scope. Missing keys or unequal values produce `SCOPE_MISMATCH`.
- `git-commit` uses `git -C <workspace_root> cat-file -e <sha>^{commit}` with an exact 40-lowercase/uppercase-hex locator.
- Default `url` accepts only credential-free HTTPS syntax but returns `unknown`/`NETWORK_BLOCKED`; it performs no request.

**Acceptance criteria:**
- A custom resolver whose three layers pass still evaluates to `unknown` without a verifier and to `pass` with an explicit passing verifier.
- Missing file returns `fail`/`NOT_FOUND`; a symlink escaping allowed roots returns `fail`/`OUTSIDE_ALLOWED_ROOT`.
- Wrong file/test-report digest returns `fail`/`DIGEST_MISMATCH`; expired evidence returns `fail`/`STALE`; wrong scope returns `fail`/`SCOPE_MISMATCH`.
- A real commit in a temporary Git repository passes the resolver layers; a nonexistent commit fails.
- A valid HTTPS locator is `unknown`, while `http`, embedded credentials, malformed URLs, loopback, private, and link-local literal hosts fail syntax/security checks without network access.
- `canonical_json_bytes({"\ue000": 2, "😀": 1, "a": "\n"})` equals the hand-authored UTF-8 bytes for `{"a":"\\n","😀":1,"\ue000":2}`, and floats are rejected.

**Failure conditions:**
- Any resolver can directly make `claim` pass.
- Any allowed-root escape, missing target, bad digest, stale evidence, or scope mismatch evaluates to pass.
- URL resolution performs network I/O or accepts a credential-bearing/non-HTTPS locator.
- Expected values in tests are computed using production digest helpers.

- [ ] **Step 1: Write focused failing tests**

Create `tests/test_evidence.py` with real temporary files and repositories. The first test must include this independently defined resolver/verifier pair:

```python
def passing_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "pass", "codes": []},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
        "claim": {"status": "pass", "codes": []},
    }


def passing_verifier(evidence, criterion, resolution):
    return {"status": "pass", "codes": []}
```

Assert the resolver-only result is `unknown` with `CLAIM_NOT_VERIFIED`, then pass `verifiers={"file": passing_verifier}` and assert all four checks and the overall result are `pass`. Add literal fixtures for missing file, allowed-root escape, digest mismatch, stale evidence, scope mismatch, valid/invalid Git commits, a canonical test report, URL syntax/security boundaries, UTF-16 key ordering, and float rejection. Canonical expected bytes must be hand-authored and must not use the production encoder.

- [ ] **Step 2: Run RED verification**

Run:

```bash
python3 -m unittest tests.test_evidence -v
```

Expected: import error for `managing_long_task_context.evidence`, proving the production module does not exist yet.

- [ ] **Step 3: Implement the evidence module**

Use these constants and public entrypoint shape:

```python
PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"


def evaluate_evidence(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    resolvers: Mapping[str, Resolver] | None = None,
    verifiers: Mapping[str, Verifier] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    kind = str(evidence.get("kind") or "")
    resolver = dict(default_resolvers() if resolvers is None else resolvers).get(kind)
    if resolver is None:
        checks = {
            "resolve": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "integrity_and_freshness": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "scope": check(UNKNOWN, "UNSUPPORTED_KIND"),
        }
    else:
        checks = normalize_resolver_checks(resolver(evidence, criterion, contract, observed_now))
    verifier = dict(verifiers or {}).get(kind)
    checks["claim"] = (
        normalize_check(verifier(evidence, criterion, checks))
        if verifier is not None and all(value["status"] == PASS for value in checks.values())
        else check(UNKNOWN, "CLAIM_NOT_VERIFIED")
    )
    statuses = [value["status"] for value in checks.values()]
    status = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else PASS
    return {"evidence_id": evidence.get("evidence_id"), "kind": kind, "status": status, "checks": checks}
```

The implementation may add private helpers and type aliases, but must keep the public signature and output keys above. Resolver normalization must accept only the three named resolver layers and must ignore every resolver-provided semantic field.

Implement `canonical_json_bytes` recursively: use literal `null`/`true`/`false`, base-10 integers, `json.dumps(value, ensure_ascii=False, separators=(",", ":"))` for individual strings, preserve array order, and sort object keys with `key.encode("utf-16-be", "surrogatepass")`. Reject floats, non-string keys, and unsupported objects with `TypeError`.

- [ ] **Step 4: Run GREEN verification**

Run:

```bash
python3 -m unittest tests.test_evidence -v
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: every evidence test passes; the full suite reports the 18 baseline tests plus the new evidence tests with 0 failures; `git diff --check` is silent.

- [ ] **Step 5: Mutation/self-review and commit**

Confirm that removing verifier separation breaks the forged-claim test, changing realpath containment breaks the symlink test, accepting unknown as pass breaks the custom-resolver test, and changing scope subset logic breaks the mismatch test.

```bash
git add src/managing_long_task_context/evidence.py tests/test_evidence.py
git commit -m "feat: resolve strict evidence in layers"
```

**Required report evidence:** RED command/output/reason, GREEN commands/counts, the four check dictionaries from the custom resolver test, built-in resolver case table, commit SHA, changed-file list, self-review findings, and concerns.

---

### Task 2: Rename contract protection to integrity_digest (S5)

**Scope:** Correct the contract field name and documentation semantics. Do not add identity signatures, trusted storage, migration, or completion resolver logic.

**Owned files:**
- Modify: `src/managing_long_task_context/__init__.py`
- Modify: `tests/test_context.py`
- Modify: `SKILL.md`
- Modify: `assets/task-contract.example.json` only if a seal example is added; otherwise leave it unchanged.

**Interfaces:**
- Keeps `publish_contract(contract, *, confirmed_by, base_dir=None)` unchanged.
- Consumes `canonical_json_bytes` from `managing_long_task_context.evidence`; contract and test-report digests must not maintain separate canonicalization algorithms.
- Produces `contract["seal"]["integrity_digest"]` formatted `sha256:<64 lowercase hex>` and no `seal.digest`.
- Contract-published events use payload key `integrity_digest`; brief packets use `contract_integrity_digest`.

**Deliverables:**
- Canonical contract bytes retain `seal.confirmed_by` and `seal.confirmed_at` and exclude only `seal.integrity_digest`.
- Validation reports `contract.seal.integrity_digest` for missing/invalid values and “contract integrity digest is invalid” after mutation.
- `SKILL.md` explicitly says the digest detects post-publication content change but does not authenticate who confirmed it; external signatures or trusted storage are needed for identity authentication.

**Acceptance criteria:**
- Published contracts contain only `integrity_digest`, with the `sha256:` prefix.
- Mutating objective, confirmer, or confirmation timestamp causes release gate failure.
- Existing baseline mutation test remains behaviorally valid with its expected message updated.
- Repository docs no longer call the digest an identity seal or imply SHA-256 authenticates the confirmer.

**Failure conditions:**
- New contracts still write `digest`, accept both names silently, or omit the `sha256:` prefix.
- Canonicalization drops the entire seal and therefore fails to protect confirmer/timestamp fields.
- Tests inspect source text instead of exercising published contracts and the release gate.

- [ ] **Step 1: Write failing public-behavior tests**

Add:

```python
def test_contract_uses_integrity_digest_without_identity_claim(self) -> None:
    published = self.publish()
    digest = published["seal"]["integrity_digest"]
    self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
    self.assertNotIn("digest", published["seal"])


def test_contract_integrity_covers_confirmation_metadata(self) -> None:
    self.publish()
    path = self.base / "TASK-001" / "task-contract.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["seal"]["confirmed_by"] = "attacker"
    path.write_text(json.dumps(stored), encoding="utf-8")
    report = context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)
    self.assertFalse(report["passed"])
    self.assertTrue(any("integrity digest is invalid" in error for error in report["errors"]))
```

- [ ] **Step 2: Run RED verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_contract_uses_integrity_digest_without_identity_claim \
  tests.test_context.ContextSkillTests.test_contract_integrity_covers_confirmation_metadata -v
```

Expected: the first test errors because `integrity_digest` is absent and the second fails because current canonicalization discards the whole seal.

- [ ] **Step 3: Implement exact digest semantics and update docs**

Use this canonicalization rule:

```python
def _canonical_contract(contract: Mapping[str, Any]) -> bytes:
    value = deepcopy(dict(contract))
    seal = value.get("seal")
    if isinstance(seal, dict):
        seal.pop("integrity_digest", None)
    return canonical_json_bytes(value)


def _contract_digest(contract: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_contract(contract)).hexdigest()
```

Construct `seal` with `confirmed_by` and `confirmed_at` before computing `integrity_digest`. Rename stored event and brief keys. Update the skill prose with the exact limitation described in Deliverables.

- [ ] **Step 4: Run GREEN verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_contract_uses_integrity_digest_without_identity_claim \
  tests.test_context.ContextSkillTests.test_contract_integrity_covers_confirmation_metadata \
  tests.test_context.ContextSkillTests.test_contract_change_breaks_release_gate -v
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all three focused tests pass; full suite has 0 failures; `git diff --check` is silent.

- [ ] **Step 5: Self-review and commit**

Inspect every production/document reference returned by `rg -n 'seal.*digest|contract_digest|integrity_digest' src tests SKILL.md assets` and confirm old contract-field semantics are gone without renaming `artifact_digest`, `payload_digest`, or `content_digest` from the spec.

```bash
git add src/managing_long_task_context/__init__.py tests/test_context.py SKILL.md assets/task-contract.example.json
git commit -m "fix: name contract integrity protection accurately"
```

**Required report evidence:** RED and GREEN output, one published seal example, mutation result, the reference scan, commit SHA, changed-file list, and concerns.

---

### Task 3: Enforce resolver-backed completion evidence (S6)

**Scope:** Replace caller-asserted completion with fresh evidence evaluation, tri-state criterion results, hop coverage, delivery-receipt checks, and existing conflict gates. Do not implement handoff state machines or network resolution.

**Owned files:**
- Modify: `src/managing_long_task_context/__init__.py`
- Modify: `tests/test_context.py`
- Modify: `tests/test_evidence.py` only when an integration fixture belongs with resolver tests.

**Interfaces:**
- Extends `gate(..., resolvers=None, verifiers=None, now=None)`; existing non-completion callers remain source-compatible.
- Completion evidence entries contain `evidence: list[Mapping[str, Any]]`, `covered_hops: list[str]`, and optional `delivery_receipts: list[Mapping[str, Any]]`.
- Supports criterion key `required_evidence_types`; retains `required_evidence` as the current compatibility alias until the schema migration tranche.
- Adds `criteria` to the completion report, keyed by criterion ID, with `status`, `evidence_results`, `missing_evidence_types`, `missing_hops`, and `missing_delivery_types`.
- Adds private `_evaluate_completion_criterion(criterion, evidence_entry, contract, *, resolvers, verifiers, now) -> dict[str, Any]`; Task 4 uses this exact production boundary for failure injection.

**Deliverables:**
- `gate(stage="completion")` calls `evaluate_evidence` on every supplied evidence/receipt during every invocation and does not trust persisted `resolver_status` or caller `result`.
- Empty evidence, malformed string pointers, fail, unknown, stale, scope mismatch, unresolved conflict, missing hop, and missing required delivery type all block completion with stable error text containing the criterion/evidence ID.
- Criterion status uses fail-before-unknown-before-pass. Completion passes only when every criterion passes and global audit/context gates have no errors.
- A delivery receipt counts only when `kind == "delivery-receipt"`, its `delivery_type` is required, and resolver plus verifier return pass.

**Acceptance criteria:**
- A real file with correct digest, fresh timestamp, matching scope, and a passing typed verifier allows the existing AC-01 fixture to pass when all hops are present.
- Deleting the file makes the next gate invocation fail; reusing the previous report does not help.
- Unknown custom resolver blocks completion even when caller supplies `result: "pass"`.
- Stale and scope-mismatched evidence block completion.
- Required delivery without a verified receipt blocks completion.
- Existing conflicted-item test path remains blocking.

**Failure conditions:**
- Any string-only pointer or caller `result` can make completion pass.
- Resolver/verifier is skipped because evidence previously stored `resolver_status: "pass"`.
- Unknown is treated as warning or pass.
- Missing hops or receipts are not represented in the returned criterion result.

- [ ] **Step 1: Write failing completion-gate tests**

Replace the current happy-path evidence strings with a real file evidence object and literal SHA-256 fixture computed in the test using `hashlib.sha256(content).hexdigest()`, not production helpers. Add separate tests named:

```python
test_completion_re_resolves_deleted_evidence
test_completion_rejects_unknown_required_evidence
test_completion_rejects_stale_and_scope_mismatched_evidence
test_completion_requires_delivery_receipt
```

Use a passing verifier with the Task 1 signature. For the unknown case, pass a resolver whose `resolve` check is `unknown`/`PERMISSION_DENIED` and keep the caller entry's legacy `result` equal to `pass` to prove it is ignored.

- [ ] **Step 2: Run RED verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_completion_requires_evidence_types_and_chain_hops \
  tests.test_context.ContextSkillTests.test_completion_re_resolves_deleted_evidence \
  tests.test_context.ContextSkillTests.test_completion_rejects_unknown_required_evidence \
  tests.test_context.ContextSkillTests.test_completion_rejects_stale_and_scope_mismatched_evidence \
  tests.test_context.ContextSkillTests.test_completion_requires_delivery_receipt -v
```

Expected: failures or `gate()` keyword errors because completion currently checks only non-empty pointers, declared types, and hops.

- [ ] **Step 3: Implement completion tri-state propagation**

Add keyword-only parameters and evaluate each object:

```python
def gate(
    task_id: str,
    *,
    stage: str,
    evidence_map: Mapping[str, Mapping[str, Any]] | None = None,
    required_item_ids: Sequence[str] | None = None,
    documents: Sequence[str | Path] | None = None,
    resolvers: Mapping[str, Any] | None = None,
    verifiers: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    emit: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
```

Implement `_evaluate_completion_criterion` as the single owner of criterion tri-state derivation. For each criterion, build `evidence_results = [evaluate_evidence(...)]`. Treat a non-mapping evidence entry as a fail with `MALFORMED_EVIDENCE`. Derive supplied kinds from evaluated objects, compare with required types, compare covered/required hops, and evaluate required delivery receipts through the same function. Record all details in `criteria[criterion_id]`; `gate` adds an error for every fail/unknown/missing condition. Never mutate the caller's map.

- [ ] **Step 4: Run GREEN verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_completion_requires_evidence_types_and_chain_hops \
  tests.test_context.ContextSkillTests.test_completion_re_resolves_deleted_evidence \
  tests.test_context.ContextSkillTests.test_completion_rejects_unknown_required_evidence \
  tests.test_context.ContextSkillTests.test_completion_rejects_stale_and_scope_mismatched_evidence \
  tests.test_context.ContextSkillTests.test_completion_requires_delivery_receipt -v
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all focused tests pass; full suite has 0 failures; `git diff --check` is silent.

- [ ] **Step 5: Mutation/self-review and commit**

Confirm the suite fails when `unknown` is changed to pass, when the gate trusts caller `result`, when resolver calls are cached across two invocations, when missing hop errors are removed, or when required receipts are accepted without resolution.

```bash
git add src/managing_long_task_context/__init__.py tests/test_context.py tests/test_evidence.py
git commit -m "feat: gate completion on resolved evidence"
```

**Required report evidence:** RED/GREEN commands and counts, before-delete pass and after-delete fail reports, unknown/stale/scope/receipt criterion results, mutation checks, commit SHA, changed-file list, and concerns.

---

### Task 4: Run audit bad-sample probes in an isolated production ledger (S7)

**Scope:** Replace the in-memory validator helper with one isolated probe that uses production `publish_contract`, event parsing, audit, and completion-gate paths. Do not add repair behavior or write probe events to the audited task.

**Owned files:**
- Modify: `src/managing_long_task_context/__init__.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Keeps `audit(...)` and `gate(...)` public signatures from Task 3.
- Adds private `_run_bad_sample_probe() -> dict[str, Any]` returning `id`, `scanned`, `expected`, `actual`, and `status`.
- Audit stats always include integer `contracts_checked`, `events_checked`, `items_checked`, `pointers_checked`, and `probes_checked`; preserves top-level `stats.checked` as the item-count compatibility alias.
- Audit stats preserve `probe: "pass|fail"` and add `probe_id`, `probe_scanned`, and `probe_expected_rejection`.

**Deliverables:**
- Probe ID is the stable string `PROBE-COMPLETION-EMPTY-EVIDENCE`.
- The probe creates a `TemporaryDirectory`, publishes a valid contract there, calls the production completion gate with empty evidence, and expects rejection.
- Recursion is prevented with one private `_run_probe: bool = True` keyword on `audit` and `gate`; the probe calls `gate(..., _run_probe=False)`.
- Auditing a real task leaves its contract, `events.jsonl`, and snapshot bytes unchanged.
- Scan counters exist even when contract/event parsing fails.

**Acceptance criteria:**
- Existing audit test sees `probe == "pass"`, the stable probe ID, `probe_scanned == 1`, and explicit scan counts.
- A before/after byte comparison proves the audited task's three persisted files are unchanged.
- Monkeypatching the production evidence/gate rejection path so the known-bad sample passes makes the probe and audit fail.
- Full suite remains green with pristine output.

**Failure conditions:**
- Probe calls only `_item_errors` or duplicates completion logic instead of calling production `gate`.
- Probe writes any event into the real task directory.
- Audit omits counts on error paths.
- Recursion guard is public API documentation or allows callers to claim a probe pass without running it.

- [ ] **Step 1: Write failing audit tests**

Extend `test_audit_self_probe_and_counts_are_explicit` to assert:

```python
self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
self.assertEqual(report["stats"]["probe_scanned"], 1)
self.assertEqual(report["stats"]["probes_checked"], 1)
self.assertEqual(report["stats"]["contracts_checked"], 1)
self.assertEqual(report["stats"]["items_checked"], 1)
self.assertGreaterEqual(report["stats"]["events_checked"], 2)
```

Add `test_audit_probe_does_not_mutate_real_ledger`, capturing exact bytes of the real task's contract, events, and snapshot before and after `audit()`. Add `test_audit_fails_when_bad_sample_is_not_rejected` using `unittest.mock.patch("managing_long_task_context._evaluate_completion_criterion", return_value={"status": "pass", "evidence_results": [], "missing_evidence_types": [], "missing_hops": [], "missing_delivery_types": []})`; assert the audit report fails and names the probe.

- [ ] **Step 2: Run RED verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_audit_self_probe_and_counts_are_explicit \
  tests.test_context.ContextSkillTests.test_audit_probe_does_not_mutate_real_ledger \
  tests.test_context.ContextSkillTests.test_audit_fails_when_bad_sample_is_not_rejected -v
```

Expected: missing stats keys and missing production-ledger probe behavior.

- [ ] **Step 3: Implement isolated probe and counters**

Use this result contract:

```python
{
    "id": "PROBE-COMPLETION-EMPTY-EVIDENCE",
    "scanned": 1,
    "expected": "reject",
    "actual": "reject" if not report["passed"] else "pass",
    "status": "pass" if not report["passed"] else "fail",
}
```

The temporary contract must contain one criterion requiring `file` evidence and a passing verifier is not supplied, so empty evidence is rejected by the same Task 3 completion code. Build scan counters from parsed production objects and always emit integer defaults.

- [ ] **Step 4: Run GREEN and whole-branch verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_audit_self_probe_and_counts_are_explicit \
  tests.test_context.ContextSkillTests.test_audit_probe_does_not_mutate_real_ledger \
  tests.test_context.ContextSkillTests.test_audit_fails_when_bad_sample_is_not_rejected -v
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all focused tests pass; full suite has 0 failures; `git diff --check` is silent.

- [ ] **Step 5: Self-review and commit**

Confirm the probe executes in a directory unrelated to the real `base_dir`, production gate code is invoked exactly once per audit, counters are present on failure paths, and the recursion guard is used only internally.

```bash
git add src/managing_long_task_context/__init__.py tests/test_context.py
git commit -m "fix: isolate strict audit probes"
```

**Required report evidence:** RED/GREEN commands and counts, probe result object, before/after ledger byte hashes, failure-injection result, commit SHA, changed-file list, and concerns.

---

## Plan Self-Review Record

- Spec coverage: Task 1 maps to S4 and the v1.1 resolver layers; Task 2 maps to S5; Task 3 maps to every S6 rejection class; Task 4 maps to S7 isolation and scan output.
- Boundary coverage: resolver semantics are separated from verification; completion re-observes evidence; URL remains offline/unknown; audit probes cannot contaminate the real ledger.
- Deferred by scope: handoff state machine, runtime-resume boundary, concurrent event-chain storage, migration/repair, context transfer, and Lite remain separate tranches described by the same v1.1 spec.
- Placeholder scan: no prohibited placeholder or unspecified test/implementation step remains.
- Type consistency: Task 3 consumes Task 1's exact `evaluate_evidence` resolver/verifier signatures; Task 4 consumes Task 3's gate behavior and adds only private recursion control.
