# Truth Source Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `truth-sources/v1` controls to Context Strict so stale, dirty, changed, missing, or unknown load-bearing originals block release, resume, handoff, and completion without adding truth-source work to contracts that never enable the capability.

**Architecture:** Keep the sealed contract and append-only event ledger in `__init__.py`, and add a focused `truth_sources.py` module for schema validation, safe file fingerprinting, and pure state evaluation. Read APIs use an existing shared lock and no writes; write APIs use the existing exclusive lock. Completion validates truth sources before evidence and again at a fresh tail linearization point.

**Tech Stack:** Python 3.10+, Python standard library, `unittest`, POSIX `fcntl`/`openat` semantics on macOS and Linux.

**Spec:** `docs/superpowers/specs/2026-08-31-truth-source-contract-design.md`

**Execution model:** Every implementation Agent must use `gpt-5.6-terra` with `high` reasoning. The controller inspects and independently reruns verification before accepting any task.

## Global Constraints

- Preserve the principle: “保持有效的前提下尽量经济，但不能因为经济而失效。”
- `truth_sources` is task-contract-level and optional; never add it through `setdefault`.
- A task that has never enabled `truth-sources/v1` must retain exact persisted bytes, seal digest, brief, diagnostics, gate reports, and zero truth-source adapter/workspace-source I/O.
- First-version sources are workspace-relative regular files only. Reject absolute paths, dot segments, glob, directories, symlinks, URL, Git, credentials, and unsafe platform fallbacks.
- Persist only control metadata. Resolver-read bytes, excerpts, summaries, indexes, and caches never enter contracts, events, snapshots, briefs, reports, exceptions, or logs.
- `fail` and `unknown` both block gates. Truth-source observation never substitutes for completion evidence.
- Public callers cannot provide time, fingerprint, generation, event payload, or a probe-bypass flag.
- Read APIs write no task, lock, or temporary files. `publish_contract`, `mark_truth_sources_dirty`, and `observe_truth_source` are the only truth-control writers.
- Use only the Python standard library; do not add runtime dependencies or network calls.
- Root files are the single source. Do not manually edit `skills/context-strict/`; regenerate it with `scripts/sync_context_strict_skill.py` in Task 7.
- Do not modify Context Lite.
- Implementers do not push, merge, install global skills, publish releases, edit GitHub issues, alter this plan/spec, lower a test threshold, or dispatch their own subagents.
- Any Agent that implements, runs acceptance evidence, or independently reruns verification uses `gpt-5.6-terra` with `high` reasoning. Read-only advisory review that runs no commands may use the controller's current model.
- Each task dispatch must include its objective, exact scope, out-of-scope work, owned files, deliverables, checks, pass/fail criteria, required evidence, and side-effect boundary before execution starts.
- If a required check is infeasible or reality conflicts with the frozen contract, stop and return evidence. A required failure blocks acceptance.

## File Map

- Create `src/managing_long_task_context/truth_sources.py`: capability/schema checks, secure file resolver, and pure truth-state evaluator.
- Modify `src/managing_long_task_context/__init__.py`: shared/exclusive lock seams, pure probe, event projection, committed view, recovery, public APIs, brief and gate integration.
- Create `tests/test_truth_sources.py`: legacy hashes, schema, resolver, reducer, recovery, API, brief, locking, gate, concurrency, and leakage tests.
- Modify `tests/test_context.py`: retain existing probe/clock assertions and add only cross-feature regressions that belong to the public context API.
- Create `assets/truth-source-contract.example.json`: optional capability example; keep `assets/task-contract.example.json` legacy-compatible.
- Create `examples/truth_source_contract.py`: public API example and reusable real-file pilot runner.
- Create `tests/fixtures/truth_source_pilot.md`: controlled real-file pilot fixture.
- Modify `SKILL.md` and `README.md`: use, boundaries, rollout prerequisite, costs, and residual risks.
- Modify `scripts/sync_context_strict_skill.py` and `tests/test_distribution.py`: explicit parity list and distributed example execution.
- Generate matching files under `skills/context-strict/` only through the sync script.
- Create `docs/validation/2026-08-31-truth-source-contract-pilot.md`: natural-execution evidence and residual risks.
- Create `docs/validation/2026-08-31-truth-source-contract-test-report.json`: resolver-readable final test report.

---

### Task 1: Freeze Legacy Behavior and Make Reads Side-Effect Free

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:108-120,1537-1581,1725-1745,2281-2307`
- Create: `tests/test_truth_sources.py`
- Modify: `tests/test_context.py:97-114,2317-2406`

**Interfaces:**
- Consumes: existing exclusive `_locked(root: Path)` and public `audit`, `brief`, `brief_diagnostics`, `gate` signatures.
- Produces: `_shared_locked_existing(root: Path) -> ContextManager[None]`; it opens an existing `.lock` with `LOCK_SH` and never creates a path.
- Produces: `_run_bad_sample_probe(now: datetime) -> dict[str, Any]` with the existing probe ID, counters, and reject/pass semantics but no temporary task.
- Public API signatures and legacy report shapes remain unchanged.

**Dispatch contract:** Scope is only legacy characterization, shared-read locking, and the pure probe. Do not add truth-source fields, schema checks, events, adapters, or gate results. Required evidence is the exact hash table, zero-write spies, focused RED/GREEN output, full regression, diff, and commit SHA.

- [ ] **Step 1: Add an exact legacy characterization test before production changes**

Create `LegacyTruthSourceCompatibilityTests` in `tests/test_truth_sources.py`. Patch `_now`, `_trusted_utc_now`, and `uuid.uuid4`; publish the exact `LEGACY-GOLDEN` contract below and hash files/public values with sorted compact JSON.

```python
LEGACY_HASHES = {
    "brief": "sha256:1017b34d7e09589d35c1d6535e7feaeba4d6d9b74706f535084ff355fb75bfd4",
    "contract_file": "sha256:c0fbeee12dcf8486d743c46465d38e91fd952b9ae93381c691282b39190d7892",
    "diagnostics": "sha256:ca9e69d280821cd39d127bfce0837e6909b57f5212f96fc52c86a93b1c2c188f",
    "events_file": "sha256:7d33c3fc8a0abd6cc7942420c3cf86cdf497bd5be1d0f7ae47a231c72f3e65d9",
    "gate_completion": "sha256:caa88b955439ca7e0a90bafdc2be4b6466bab8b795d7bd60cffaff2c9b3d111b",
    "gate_handoff": "sha256:a451310f64c7464896b06a5905e905c6080f300948c58830bd978968b7a5d242",
    "gate_release": "sha256:3d2ef964067cff8e4c50387108cc70e93d8f68caa036ddb9f6520abd409af895",
    "gate_resume": "sha256:533bb8cfcfc8e956141f84148f28e153cfeddfd99422bb6b83b5123e3a330282",
    "seal": "sha256:a80fcf6e033fbdcea3f96f8d12719b92405a9ec3cf203f70636bfef307ba0ab0",
    "snapshot_file": "sha256:1af1f6ee2f763cdb86901a9665b17be14f331669ffeac8db21d905753f3d72b9",
}

LEGACY_CONTRACT = {
    "schema": 1,
    "task_id": "LEGACY-GOLDEN",
    "version": 1,
    "issued_by": "publisher",
    "issued_at": "2026-08-31T02:00:00+00:00",
    "authorized_approvers": [],
    "objective": "Preserve legacy behavior",
    "scope": ["strict context"],
    "out_of_scope": [],
    "constraints": ["no truth sources"],
    "acceptance_criteria": [{
        "id": "AC-01",
        "criterion": "Legacy behavior stays exact",
        "required_evidence_types": ["test-report"],
    }],
}
```

Assert all ten hashes exactly and patch the future truth evaluator symbol with a call-if-used failure after that symbol exists. This test is a characterization test and must PASS on commit `752b48b` before production changes.

- [ ] **Step 2: Run the characterization and capture the baseline**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.LegacyTruthSourceCompatibilityTests -v
```

Expected: PASS with the ten hashes above. If any hash differs before implementation, stop and reconcile the active commit; do not rewrite expected values.

- [ ] **Step 3: Add failing zero-write and lock tests**

Add `ReadOnlyLockingTests` with these methods:

```python
def test_bad_sample_probe_preserves_stats_without_filesystem_writes(self):
    with patch("tempfile.TemporaryDirectory", side_effect=AssertionError("probe wrote temp state")):
        report = context.audit("TASK-001", base_dir=self.base, emit=False)
    self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
    self.assertEqual(report["stats"]["probe_scanned"], 1)
    self.assertEqual(report["stats"]["probe"], "pass")

def test_missing_shared_lock_fails_without_creating_anything(self):
    (self.base / "TASK-001" / ".lock").unlink()
    before = sorted((self.base / "TASK-001").iterdir())
    with self.assertRaisesRegex(context.ContextError, "READ_LOCK_UNAVAILABLE"):
        context.brief("TASK-001", base_dir=self.base)
    self.assertEqual(sorted((self.base / "TASK-001").iterdir()), before)

def test_read_apis_make_no_write_calls(self):
    calls = (context.audit, context.brief, context.brief_diagnostics)
    with patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")), \
         patch.object(context, "_atomic_write_json", side_effect=AssertionError("write")), \
         patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temp")):
        for function in calls:
            function("TASK-001", base_dir=self.base, emit=False) if function is context.audit else function("TASK-001", base_dir=self.base)
        context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)
```

Also add a `threading.Event` test proving an exclusive `_locked()` writer cannot finish while `_shared_locked_existing()` is held. Use `wait(2)` and `join(2)` only; do not use `sleep()`.

For a missing/unreadable lock or unsupported shared-lock platform, assert: `audit` and every gate return `passed=False` with `READ_LOCK_UNAVAILABLE` recorded as an unknown blocking condition; `brief` and `brief_diagnostics` raise `ContextError("READ_LOCK_UNAVAILABLE")`; no path is created in any case.

- [ ] **Step 4: Run the new tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.ReadOnlyLockingTests -v
```

Expected: FAIL because `_shared_locked_existing` is missing and `_run_bad_sample_probe` creates a temporary task.

- [ ] **Step 5: Implement the shared-read lock and pure in-memory probe**

Add next to `_locked`:

```python
@contextmanager
def _shared_locked_existing(root: Path):
    if fcntl is None:
        raise ContextError("READ_LOCK_UNAVAILABLE: shared locking is unsupported")
    lock_path = root / ".lock"
    try:
        handle = lock_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise ContextError("READ_LOCK_UNAVAILABLE: existing task lock is unreadable") from exc
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        except OSError as exc:
            raise ContextError("READ_LOCK_UNAVAILABLE: shared lock acquisition failed") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```

Rewrite `_run_bad_sample_probe` to call `_evaluate_completion_criterion` directly with the same bad contract/criterion and `evidence_entry=None`. Preserve this exact result structure:

```python
return {
    "id": "PROBE-COMPLETION-EMPTY-EVIDENCE",
    "scanned": 1,
    "expected": "reject",
    "actual": "reject" if rejected else "accept",
    "status": "pass" if rejected else "fail",
}
```

Wrap each public read API's task read/plan/evaluation in `_shared_locked_existing(paths["root"])`. Do not call a public read API from another public read API while holding the lock; extract/reuse existing private planning functions instead.

- [ ] **Step 6: Run focused and full GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.LegacyTruthSourceCompatibilityTests \
  tests.test_truth_sources.ReadOnlyLockingTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: focused tests PASS; full suite has at least 113 tests and zero failures; the legacy hash table is unchanged.

- [ ] **Step 7: Commit and report**

```bash
git add src/managing_long_task_context/__init__.py tests/test_context.py tests/test_truth_sources.py
git commit -m "fix: make context reads side-effect free"
```

Report the baseline hashes, RED failure, GREEN counts, zero-write evidence, changed files, commit SHA, and concerns. Controller reruns all commands and obtains an independent spec-compliance review before TSC-02.

---

### Task 2: Add Contract Schema Validation and a Secure File Resolver

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Create: `src/managing_long_task_context/truth_sources.py`
- Modify: `tests/test_truth_sources.py`

**Interfaces:**
- Produces `CAPABILITY = "truth-sources/v1"` and `SUPPORTED_CAPABILITIES = frozenset({CAPABILITY})`.
- Produces `TruthResolver = Callable[[str | Path, Mapping[str, Any]], Mapping[str, Any]]`; the first argument is the sealed contract's `workspace_root` and the second is one declared `source_ref`.
- Produces `truth_sources_enabled(contract: Mapping[str, Any]) -> bool`.
- Produces `validate_truth_source_contract(contract: Mapping[str, Any], *, supported_capabilities: AbstractSet[str] = SUPPORTED_CAPABILITIES) -> list[str]`.
- Produces `resolve_file_source(workspace_root: str | Path, source_ref: Mapping[str, Any]) -> dict[str, Any]` returning exactly `status`, `code`, and `fingerprint`.

**Dispatch contract:** Own only the new module and its tests. Do not import it into `__init__.py`, write events, change gates/briefs, add network/Git support, or return absolute paths/source bytes. Pass requires schema table coverage, root-FD safety, exact size boundary, balanced FDs, canary non-leakage, and unchanged evidence tests.

- [ ] **Step 1: Write failing schema tests**

Add `TruthSourceSchemaTests` covering both directions of capability pairing, unique/non-empty `required_capabilities`, unsupported capabilities, subtree/item/source-ref allowlists, unique IDs, 160-character purpose, 128-character owner, exact `owner-readback`, positive integer age, unique non-empty change kinds, absolute existing non-symlink workspace root, and every locator rule.

```python
def test_truth_sources_requires_exact_capability_pair(self):
    with_sources = self.contract(truth_sources=self.valid_truth_sources())
    self.assertIn(
        "contract.truth_sources requires required_capabilities truth-sources/v1",
        validate_truth_source_contract(with_sources),
    )
    capability_only = self.contract(required_capabilities=["truth-sources/v1"])
    self.assertIn(
        "contract.required_capabilities truth-sources/v1 requires truth_sources",
        validate_truth_source_contract(capability_only),
    )

def test_unknown_nested_fields_are_rejected(self):
    contract = self.valid_contract()
    contract["truth_sources"]["items"][0]["expected_digest"] = "sha256:" + "0" * 64
    errors = validate_truth_source_contract(contract)
    self.assertIn("contract.truth_sources.items[0] has unknown fields: ['expected_digest']", errors)
```

- [ ] **Step 2: Write failing secure resolver tests**

Add `SecureFileResolverTests` with exact methods:

- `test_rejects_absolute_escape_glob_and_dot_segments_without_open`
- `test_rejects_empty_nul_hash_tilde_empty_segment_and_segment_whitespace_without_open`
- `test_rejects_workspace_root_intermediate_and_final_symlinks`
- `test_rejects_directory_and_non_regular_final_targets`
- `test_root_swap_cannot_redirect_resolution_outside_workspace`
- `test_changed_during_read_returns_unknown`
- `test_exactly_16_mib_passes_and_one_byte_more_fails`
- `test_every_success_and_failure_path_closes_all_fds`
- `test_errno_and_unsupported_platform_map_to_all_stable_codes`
- `test_result_and_exception_never_contain_file_canary`

The happy-path assertion is:

```python
result = resolve_file_source(workspace.resolve(), {"kind": "file", "locator": "docs/status.md"})
self.assertEqual(result["status"], "pass")
self.assertIsNone(result["code"])
self.assertRegex(result["fingerprint"], r"^sha256:[0-9a-f]{64}$")
self.assertEqual(set(result), {"status", "code", "fingerprint"})
```

Patch the module's `os.open`/`os.close` with counting wrappers for FD balance. Use `threading.Event` barriers around the final file read for root-swap and changed-during-read tests; no `sleep()`.

- [ ] **Step 3: Run the new tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceSchemaTests \
  tests.test_truth_sources.SecureFileResolverTests -v
```

Expected: FAIL with `ModuleNotFoundError` or missing interface errors.

- [ ] **Step 4: Implement exact schema constants and validation**

Start the module with these allowlists and patterns:

```python
CAPABILITY = "truth-sources/v1"
SUPPORTED_CAPABILITIES = frozenset({CAPABILITY})
TRUTH_ROOT_FIELDS = frozenset({"schema", "items"})
TRUTH_ITEM_FIELDS = frozenset({
    "id", "purpose", "source_ref", "owner", "max_age_seconds",
    "validation_method", "invalidate_on_change_kinds",
})
SOURCE_REF_FIELDS = frozenset({"kind", "locator"})
SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
VERIFICATION_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}\Z")
MAX_SOURCE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
```

Return field-qualified deterministic strings in source order. Unknown required capabilities are errors. Missing `truth_sources` and missing `required_capabilities` return no truth-source errors and perform no workspace validation.

- [ ] **Step 5: Implement rooted FD traversal and bounded hashing**

Open the filesystem root, every absolute `workspace_root` component, every locator directory component, and the final file using `dir_fd` plus `O_NOFOLLOW|O_CLOEXEC`; directory components also use `O_DIRECTORY`. Reject platforms missing required flags as `unknown/TRUTH_SOURCE_RESOLVER_UNKNOWN`.

Use this result helper and errno mapping:

```python
def _result(status: str, code: str | None, fingerprint: str | None = None) -> dict[str, Any]:
    return {"status": status, "code": code, "fingerprint": fingerprint}

ERRNO_CODES = {
    errno.ENOENT: ("fail", "TRUTH_SOURCE_NOT_FOUND"),
    errno.ELOOP: ("fail", "TRUTH_SOURCE_SYMLINK"),
    errno.ENOTDIR: ("fail", "TRUTH_SOURCE_NOT_REGULAR_FILE"),
    errno.EACCES: ("unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
    errno.EPERM: ("unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
}
```

After final open: `before = os.fstat(fd)`, require `stat.S_ISREG`, reject `st_size > MAX_SOURCE_BYTES`, hash incrementally from the same FD while enforcing the cumulative limit, then `after = os.fstat(fd)`. Compare `(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns)`; a difference returns `unknown/TRUTH_SOURCE_CHANGED_DURING_READ`. Close every owned FD in `finally` in reverse order.

Static locator/root rejection returns `fail/TRUTH_SOURCE_UNSAFE_PATH`; symlink, non-regular, missing, and too-large paths use their corresponding stable spec codes. Map `EIO`, `ESTALE` (when available), `EBUSY`, and interrupted/short unexpected reads to `unknown/TRUTH_SOURCE_TRANSIENT_IO`; permissions to `unknown/TRUTH_SOURCE_PERMISSION_DENIED`; missing required platform flags or unclassified OS errors to `unknown/TRUTH_SOURCE_RESOLVER_UNKNOWN`. Task 2 tests cover every resolver-owned code; the final Task 4–6 matrix covers every remaining stable code listed in spec section 7.3.

- [ ] **Step 6: Run focused and neighboring GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceSchemaTests \
  tests.test_truth_sources.SecureFileResolverTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all focused and full tests PASS; no test or exception contains the file-only canary.

- [ ] **Step 7: Commit and report**

```bash
git add src/managing_long_task_context/truth_sources.py tests/test_truth_sources.py
git commit -m "feat: add truth source contract resolver"
```

Report the schema case table, stable errno/code mapping, FD counts, 16 MiB boundary, canary scan, test counts, commit SHA, and residual platform concerns.

---

### Task 3: Add Strict Event Reduction, Contract Resets, and Crash Recovery

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:174-404,405-526,622-681,1582-1724`
- Modify: `tests/test_truth_sources.py`

**Interfaces:**
- Consumes: `validate_truth_source_contract`, `truth_sources_enabled`, `CAPABILITY` from Task 2.
- Produces `_canonical_contract_input(contract: Mapping[str, Any]) -> bytes`, canonicalizing only publisher-supplied fields and excluding `seal`.
- Produces `_matching_contract_publish_events(contract: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`.
- Produces `_append_missing_publish_event_locked(contract: Mapping[str, Any], paths: Mapping[str, Path], *, events: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> dict[str, Any]`.
- Produces `_rebuild_snapshot(task_id: str, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]` as the single strict reducer entrypoint used by reads, recovery, and audit.
- Produces `_truth_source_reset_payload(contract: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any] | None`.
- Produces `_apply_truth_control_event(snapshot: dict[str, Any], event: Mapping[str, Any]) -> dict[str, Any]`.
- Produces `_committed_contract_errors(contract: Mapping[str, Any], events: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> list[str]`.
- Produces `_load_committed_task_view_locked(task_id: str, paths: Mapping[str, Path]) -> dict[str, Any]` with `contract`, `snapshot`, `events`, `contract_digest`, `event_tail_id`, `event_count`, and `truth_history_enabled`.

**Dispatch contract:** Own contract validation, reducer, publish reset/recovery, committed view, and audit consistency only. Do not add mark/observe APIs, live source resolution, brief/gate output, documentation, or distribution copies. Legacy hash constants and public shapes must remain exact.

- [ ] **Step 1: Write failing reducer and reset tests**

Add:

- `TruthSourceReducerTests.test_first_truth_enabled_publish_creates_generation_one_reset`
- `test_repeated_dirty_increments_once_per_event_and_preserves_unaffected_sources`
- `test_contract_update_atomically_replaces_sources_and_removes_deleted_ids`
- `test_capability_removal_and_later_no_truth_versions_keep_empty_resets_monotonic`
- `test_rebuild_rejects_jump_unknown_source_and_malformed_control_event`
- `test_poisoned_event_cannot_be_healed_by_later_observation`

Assert the first reset projection exactly:

```python
self.assertEqual(snapshot["truth_sources"], {
    "generation": 1,
    "sources": {
        "TS-STATUS": {
            "required_generation": 1,
            "observed_generation": None,
            "observation": None,
            "status": "unobserved",
        }
    },
})
```

- [ ] **Step 2: Write failing committed-contract and failure-injection tests**

Add:

- `TruthSourceRecoveryTests.test_missing_publish_event_same_version_retry_repairs_without_reseal`
- `test_duplicate_or_mismatched_latest_publish_event_fails_closed`
- `test_snapshot_write_failure_rebuilds_from_complete_event_log`
- `test_capability_add_modify_remove_fail_closed_at_every_publish_write_cut`

Inject failures at contract temporary-file write, contract atomic replace, event append, and snapshot atomic replace for capability add, modify, and remove. On a missing-event retry, assert `confirmed_at` and `integrity_digest` match the already-written sealed contract and exactly one matching publish event exists. At every other cut, assert the next read either reconstructs the unique committed view or returns one stable code from `CONTRACT_COMMIT_MISSING_EVENT`, `CONTRACT_COMMIT_DUPLICATE_EVENT`, or `CONTRACT_COMMIT_MISMATCH`; it must never continue from the stale snapshot.

- [ ] **Step 3: Run reducer/recovery tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceReducerTests \
  tests.test_truth_sources.TruthSourceRecoveryTests -v
```

Expected: FAIL because current contract publication has no reset, reducer ignores truth events, and same-version retry is rejected.

- [ ] **Step 4: Integrate schema validation without changing legacy defaults**

At the end of `_validate_contract_shape`, extend the existing error list:

```python
errors.extend(validate_truth_source_contract(contract))
```

Do not add `required_capabilities` or `truth_sources` defaults. Keep `_canonical_contract` unchanged so declared fields are naturally sealed.

- [ ] **Step 5: Implement reset creation and strict event reduction**

Use this reset shape:

```python
def _truth_source_reset_payload(contract, snapshot):
    current = snapshot.get("truth_sources")
    history_enabled = isinstance(current, Mapping)
    enabled = truth_sources_enabled(contract)
    if not history_enabled and not enabled:
        return None
    previous = current.get("generation", 0) if isinstance(current, Mapping) else 0
    source_ids = [item["id"] for item in contract.get("truth_sources", {}).get("items", [])]
    return {
        "schema": CAPABILITY,
        "generation": previous + 1,
        "source_ids": source_ids,
    }
```

When `_apply_event` sees `contract-published` with a reset, validate exact payload fields, require generation `previous + 1`, and replace `sources` with fresh unobserved entries. For dirty/observe events, validate allowlists, actor, UTC time, contract digest, generation, source membership, arrays, and fingerprint before applying. Raise `_EventReadError`/`ContextError` on the first invalid transition; never return a partially updated snapshot.

- [ ] **Step 6: Implement committed view and idempotent publish repair**

The latest `contract-published` event must uniquely match current version, digest, `confirmed_by`, and `confirmed_at`. `_load_committed_task_view_locked` reads events once, rebuilds snapshot in memory when event count differs, validates the latest reset against the current sealed contract, and returns the frozen view.

Only a current contract with `truth-sources/v1` or an event history containing a truth reset enters this recovery/commit-consistency path. A never-enabled legacy task keeps its existing read and same-version-publish behavior and does not perform an added truth recovery scan.

In `publish_contract`, before the ordinary “greater version” rejection, read and rebuild the existing ledger once:

```python
events = _read_events(paths["events"])
rebuilt = _rebuild_snapshot(task_id, events)
same_publisher_fields = _canonical_contract_input(value) == _canonical_contract_input(existing)
matching_events = _matching_contract_publish_events(existing, events)
if same_publisher_fields and confirmed_by == existing["seal"]["confirmed_by"] and not matching_events:
    _append_missing_publish_event_locked(existing, paths, events=events, snapshot=rebuilt)
    return existing
```

The repair event uses the existing seal and deterministic reset from event-rebuilt state. `_load_committed_task_view_locked` short-circuits before snapshot comparison and raises exactly one stable error when the current truth-enabled sealed contract is uncommitted. Audit/gates expose exactly `CONTRACT_COMMIT_MISSING_EVENT` only when there is no matching publish event and no duplicate/mismatch. Same-publisher/same-version `publish_contract` recognizes only that state and repairs it. One matching event keeps the same-version rejection; duplicate and mismatched states raise `CONTRACT_COMMIT_DUPLICATE_EVENT` or `CONTRACT_COMMIT_MISMATCH` with field-qualified diagnostics that contain no source bytes and are never auto-repaired.

- [ ] **Step 7: Run focused, legacy, and full GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceReducerTests \
  tests.test_truth_sources.TruthSourceRecoveryTests \
  tests.test_truth_sources.LegacyTruthSourceCompatibilityTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: reducer/recovery PASS; legacy ten hashes unchanged; full suite zero failures.

- [ ] **Step 8: Commit and report**

```bash
git add src/managing_long_task_context/__init__.py tests/test_truth_sources.py
git commit -m "feat: persist truth source control state"
```

Report event transition matrix, recovery cut matrix, rebuilt/snapshot equality, unchanged seal evidence, legacy hashes, tests, commit SHA, and concerns.

---

### Task 4: Add Dirty and Observation Write APIs

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:515-681,2347-2392`
- Modify: `tests/test_truth_sources.py`

**Interfaces:**
- Produces `mark_truth_sources_dirty(task_id: str, *, change_kind: str, actor: str, reason: str, base_dir: str | Path | None = None) -> dict[str, Any]`.
- Produces `observe_truth_source(task_id: str, *, source_id: str, actor: str, verification_refs: Sequence[str], base_dir: str | Path | None = None) -> dict[str, Any]`.
- Adds both names to `run()` and `__all__`.
- Consumes the Task 2 secure resolver and Task 3 committed view/reducer.

**Dispatch contract:** Only add explicit write APIs and tests. Do not infer changes from Git/items/checkpoints, batch-observe, accept caller time/digest/generation, alter gates/briefs, or authenticate actor identity. All rejection paths must preserve event bytes/count.

- [ ] **Step 1: Write failing dirty API tests**

Add `TruthSourceApiTests`:

```python
def test_mark_dirty_updates_only_matching_sources_once(self):
    before = self.snapshot()["truth_sources"]["generation"]
    result = context.mark_truth_sources_dirty(
        self.task_id,
        change_kind="implementation-change",
        actor="executor-01",
        reason="authentication behavior changed",
        base_dir=self.base,
    )
    self.assertEqual(result["generation"], before + 1)
    self.assertEqual(result["affected_source_ids"], ["TS-STATUS"])

def test_mark_dirty_without_matching_change_kind_writes_nothing(self):
    before = self.events_bytes()
    with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_CHANGE_KIND_UNDECLARED"):
        context.mark_truth_sources_dirty(
            self.task_id, change_kind="typo-change", actor="executor-01",
            reason="must not write", base_dir=self.base,
        )
    self.assertEqual(self.events_bytes(), before)
```

- [ ] **Step 2: Write failing observation API tests**

Add exact cases:

- `test_observe_requires_declared_owner_and_stable_refs`
- `test_observe_binds_current_contract_generation_fingerprint_and_time`
- `test_observe_rejects_undeclared_file_change_until_marked_dirty`
- `test_repeated_same_fingerprint_observe_refreshes_same_generation`
- `test_resolver_failure_writes_no_event`

For undeclared change: observe baseline, change actual file bytes, assert `TRUTH_SOURCE_UNDECLARED_CHANGE` and unchanged event count, mark a declared change, then observe successfully.

- [ ] **Step 3: Run API tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceApiTests -v
```

Expected: FAIL with missing public API attributes.

- [ ] **Step 4: Implement dirty event writing under the exclusive lock**

Validate non-empty single-line actor/reason/change kind, load the committed view, find sorted matching source IDs, and reject no-match before creating an event. Use payload:

```python
payload = {
    "contract_digest": view["contract_digest"],
    "generation": view["snapshot"]["truth_sources"]["generation"] + 1,
    "change_kind": change_kind,
    "reason": reason,
    "affected_source_ids": affected_source_ids,
}
```

Append exactly one `truth-sources-dirtied` event and return only `event_id`, `generation`, and `affected_source_ids`.

- [ ] **Step 5: Implement owner-bound observation**

Validate `verification_refs` against `VERIFICATION_REF_RE`, require the exact declared owner, and resolve the current file while holding the exclusive task lock. If the current source is clean and a previous fingerprint differs, raise `TRUTH_SOURCE_UNDECLARED_CHANGE` before event creation. Otherwise append:

```python
payload = {
    "source_id": source_id,
    "contract_digest": view["contract_digest"],
    "observed_generation": source_state["required_generation"],
    "fingerprint": resolution["fingerprint"],
    "verification_refs": list(verification_refs),
}
```

Return `event_id`, `source_id`, `observed_generation`, `fingerprint`, and the event's `created_at` as `observed_at`. Do not return verification refs or file content.

- [ ] **Step 6: Expose dispatcher and public names**

Add exact action keys:

```python
"mark_truth_sources_dirty": mark_truth_sources_dirty,
"observe_truth_source": observe_truth_source,
```

Add both functions to `__all__`; do not change any existing action name.

- [ ] **Step 7: Run focused and full GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceApiTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all API tests PASS, rejection-path event bytes stay exact, full suite zero failures.

- [ ] **Step 8: Commit and report**

```bash
git add src/managing_long_task_context/__init__.py tests/test_truth_sources.py
git commit -m "feat: add truth source sync APIs"
```

Report RED/GREEN, event deltas, return examples, undeclared-change sequence, no-write failures, test count, commit SHA, and concerns.

---

### Task 5: Evaluate Live Truth State and Render Mandatory Brief Controls

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Modify: `src/managing_long_task_context/truth_sources.py`
- Modify: `src/managing_long_task_context/__init__.py:915-1514`
- Modify: `tests/test_truth_sources.py`

**Interfaces:**
- Produces `evaluate_truth_sources(contract: Mapping[str, Any], snapshot: Mapping[str, Any], *, now: datetime, resolver: TruthResolver | None = None) -> dict[str, Any] | None`.
- Returns `None` for undeclared contracts without calling resolver.
- Truth-enabled return contains overall `status`, `passed`, ordered `results`, and `stats` with `truth_sources_checked` and `truth_source_resolution_attempts`.
- Produces `_truth_brief_items(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]`, projecting only `id`, `purpose`, `source_ref`, `owner`, `status`, `required_generation`, `observed_generation`, `observed_at`, and `fingerprint`; evaluator/gate-only `codes` never enter brief.
- Produces `_plan_brief_from_view(task_id: str, *, contract: Mapping[str, Any], snapshot: Mapping[str, Any], truth_evaluation: Mapping[str, Any] | None, phase: str | None, include: Sequence[str] | None, max_items: int | None, max_chars: int) -> dict[str, Any]` so public brief/diagnostics and gate preflight reuse one evaluation without nested locks or duplicate resolution.

**Dispatch contract:** Own evaluator and brief/diagnostics only. Do not run completion evidence, append events, alter gate verdicts, expose verification refs, or relax overflow. Legacy hashes and zero truth I/O must remain exact.

- [ ] **Step 1: Write failing evaluator state-table tests**

Add `TruthSourceEvaluationTests` covering unobserved, contract mismatch, owner mismatch, generation mismatch/dirty, malformed/future/stale observation, missing/permission/changed file, and pass. Assert control-invalid cases call resolver zero times.

```python
evaluation = evaluate_truth_sources(contract, snapshot, now=NOW, resolver=resolver)
self.assertEqual(evaluation["status"], "fail")
self.assertIn("TRUTH_SOURCE_DIRTY", evaluation["results"][0]["codes"])
self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
resolver.assert_not_called()
```

The result item allowlist is exactly `id`, `purpose`, `source_ref`, `owner`, `status`, `codes`, `required_generation`, `observed_generation`, `observed_at`, and `fingerprint`.

- [ ] **Step 2: Write failing brief and diagnostics tests**

Add `TruthSourceBriefTests`:

- `test_brief_uses_live_evaluator_not_cached_pass`
- `test_brief_resolves_each_declared_source_once`
- `test_truth_block_is_mandatory_and_counts_fixed_prompt_chars`
- `test_truth_block_never_contains_file_canary_or_verification_refs`
- `test_handoff_preflight_internal_plan_can_reuse_supplied_evaluation`
- `test_legacy_brief_is_byte_identical_and_never_calls_evaluator`

Assert the packet block shape and exact item allowlist:

```python
self.assertEqual(packet["truth_sources"], {
    "schema": "truth-sources/v1",
    "items": _truth_brief_items(evaluation),
})
self.assertNotIn("codes", packet["truth_sources"]["items"][0])
```

- [ ] **Step 3: Run evaluator/brief tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceEvaluationTests \
  tests.test_truth_sources.TruthSourceBriefTests -v
```

Expected: FAIL because evaluator and truth brief block are missing.

- [ ] **Step 4: Implement deterministic evaluator precedence**

For each source, check control state before file I/O in this order: missing observation, contract digest, owner, generation, timestamp format/future skew/freshness. Only a control-valid item calls the resolver. Merge statuses with `fail > unknown > pass`; map a live fingerprint mismatch to `fail/TRUTH_SOURCE_CHANGED`.

```python
overall = (
    "fail" if any(item["status"] == "fail" for item in results)
    else "unknown" if any(item["status"] == "unknown" for item in results)
    else "pass"
)
return {
    "status": overall,
    "passed": overall == "pass",
    "results": results,
    "stats": {
        "truth_sources_checked": len(results),
        "truth_source_resolution_attempts": attempts,
    },
}
```

Use event `created_at` as `observed_at`; enforce explicit UTC RFC3339 and the existing 300-second future skew.

- [ ] **Step 5: Add the mandatory compact brief block**

Pass a precomputed evaluation into `_build_brief_packet`/`_plan_brief_from_view`. Add `truth_sources` only when evaluation is not `None`, using `_truth_brief_items` rather than the full evaluator results. Render its JSON-safe allowlisted items before ordinary selected context items. Include it in fixed prompt computation, CJK-weighted token diagnostics, and mandatory overflow; never subject it to `max_items`.

Public `brief` and `brief_diagnostics` acquire one shared lock, load one committed view, sample one trusted UTC, evaluate once, and call the private planner. Gate integration is deferred to Task 6.

- [ ] **Step 6: Run focused, legacy, and full GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceEvaluationTests \
  tests.test_truth_sources.TruthSourceBriefTests \
  tests.test_truth_sources.LegacyTruthSourceCompatibilityTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: focused tests PASS; file-only canary absent; legacy hashes exact; full suite zero failures.

- [ ] **Step 7: Commit and report**

```bash
git add src/managing_long_task_context/truth_sources.py src/managing_long_task_context/__init__.py tests/test_truth_sources.py
git commit -m "feat: render live truth source controls"
```

Report state table, resolution counts, sample safe packet, overflow metrics, canary scan, hashes, test count, commit SHA, and concerns.

---

### Task 6: Enforce Four-Stage Gates and Completion Tail Linearization

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:1582-1961,2281-2307`
- Modify: `tests/test_truth_sources.py`

**Interfaces:**
- Public `gate()` signature stays unchanged.
- Internal `_gate_core` receives `clock: Callable[[], datetime]` instead of a pre-sampled `now`; legacy/no-truth calls it once, truth-enabled completion calls it at entry and tail.
- Produces `_audit_from_view(task_id: str, *, contract: Mapping[str, Any], snapshot: Mapping[str, Any], events: Sequence[Mapping[str, Any]], documents: Sequence[str | Path] | None, max_pointer_lag_seconds: float, now: datetime, run_probe: bool) -> dict[str, Any]`; `_audit_core` and `_gate_core` delegate to it after one locked load.
- Produces `_evaluate_truth_phase_locked(view: Mapping[str, Any], *, now: datetime) -> dict[str, Any] | None`.
- Produces `_truth_entry_token(view: Mapping[str, Any]) -> dict[str, Any]` containing the committed `contract_digest`, `event_tail_id`, `event_count`, truth generation, and ordered `(source_id, required_generation)` pairs.
- Truth-enabled gate adds `truth_source_results`; stats add `truth_sources_checked` and `truth_source_resolution_attempts`. Legacy reports add neither.

**Dispatch contract:** Own gate integration and concurrency tests only. Do not modify evidence semantics, append events, add test-only public hooks, use sleeps, or change legacy output. Entry-invalid completion must call zero evidence callbacks; tail-invalid completion may have callbacks but cannot pass.

- [ ] **Step 1: Write the failing four-stage matrix**

Add `TruthSourceGateTests.test_all_four_stages_fail_closed_for_every_invalid_truth_state`. Use subtests for unobserved, dirty, stale, changed, missing, permission, malformed-event unknown, and each stage. Assert `passed is False` and the stable code is in `truth_source_results`.

- [ ] **Step 2: Write failing completion short-circuit and tail tests**

Add:

- `test_completion_entry_invalid_calls_zero_evidence_resolvers_and_verifiers`
- `test_completion_tail_detects_mark_during_evidence_callback`
- `test_completion_tail_detects_contract_update_during_callback`
- `test_completion_tail_detects_file_change_during_callback`
- `test_completion_tail_uses_new_clock_and_detects_freshness_expiry`
- `test_mark_cannot_enter_tail_control_file_verdict_critical_section`
- `test_release_resume_handoff_hold_shared_lock_until_verdict_is_fixed`
- `test_truth_enabled_read_apis_preserve_tree_bytes_and_reject_every_write_primitive`
- `test_legacy_gate_has_zero_truth_io_and_unchanged_shape`

Use this barrier pattern, with every `wait`/`join` capped at two seconds:

```python
callback_entered = threading.Event()
allow_callback_return = threading.Event()

def blocking_resolver(evidence, criterion, contract, now):
    callback_entered.set()
    self.assertTrue(allow_callback_return.wait(2))
    return passing_resolver(evidence, criterion, contract, now)
```

Run gate in thread A, wait for `callback_entered`, perform the real writer/file mutation in the main thread, release the callback, join, and assert final failure.

For shared-lock proof, do not infer blocking merely because a writer thread has not run. While the gate is paused inside the locked evaluation, launch a separate `multiprocessing.Process` that independently opens `.lock`, calls `fcntl.flock(fd, LOCK_EX | LOCK_NB)`, and returns `blocked` only for `EACCES`/`EAGAIN`/`BlockingIOError`. Require the child to report `blocked` and exit cleanly within two seconds. Then start the real mark writer with a `writer_attempting` barrier, release the tail, and prove the writer completes only afterward. Apply the same independent nonblocking probe to release, resume, and handoff verdict phases. Any acquired lock, timeout, missing child result, or unexpected errno fails the test.

For the truth-enabled zero-write test, capture a sorted recursive map of every task path to type and file bytes before/after each public `audit`, `brief`, `brief_diagnostics`, and gate call. Wrap `builtins.open` and `Path.open` to reject modes containing `w`, `a`, `x`, or `+`; wrap `os.open` to reject `O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`, and `O_APPEND`, while allowing resolver reads. Additionally patch `_append_event_locked`, `_atomic_write_json`, `os.replace`, `tempfile.TemporaryDirectory`, `Path.mkdir`, `os.mkdir`, and `os.makedirs` to fail if called. Run this after a real truth-enabled observation so conditional pass-path writes cannot hide behind legacy tests.

- [ ] **Step 3: Run gate tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceGateTests -v
```

Expected: FAIL because gates do not consume truth evaluation and completion has no tail phase.

- [ ] **Step 4: Integrate one locked truth phase into release/resume/handoff**

Within one shared-lock critical section: load committed view, sample current UTC, run audit from that view, evaluate sources once, reuse that evaluation in brief preflight, and fix the verdict. Any truth `fail`/`unknown` adds stable errors. Do not invoke public `brief_diagnostics` from inside gate. `_audit_from_view` checks only contract/event/snapshot structure and never invokes the truth evaluator or opens declared source files.

- [ ] **Step 5: Short-circuit invalid completion entry**

Before iterating criteria:

```python
entry_truth = _evaluate_truth_phase_locked(entry_view, now=clock())
if entry_truth is not None and not entry_truth["passed"]:
    criterion_reports = {}
    criteria_checked = 0
    evidence_attempts = 0
    truth_blocked = True
```

Do not call `_evaluate_completion_criterion`, custom resolver, or verifier when `truth_blocked` is true.

- [ ] **Step 6: Add fresh tail validation before a successful completion verdict**

After evidence evaluation, only when no current errors and entry truth was declared/pass, reacquire the existing shared lock, reload committed view, call `clock()` again, compare `_truth_entry_token(tail_view)` with the captured entry token, recheck freshness and live files, then fix the verdict before releasing the lock. Any contract digest, event tail/count, truth generation, required generation, freshness, or file change adds errors and replaces the displayed `truth_source_results` with the tail results. A source may not become passing again during callbacks and erase the fact that a control event occurred.

Stats sum entry and tail resolution attempts. A normal truth-enabled completion checks `N` sources twice; legacy still samples clock once and has the Task 1 hash/report shape.

- [ ] **Step 7: Run focused and full GREEN verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_truth_sources.TruthSourceGateTests \
  tests.test_truth_sources.ReadOnlyLockingTests \
  tests.test_truth_sources.LegacyTruthSourceCompatibilityTests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all barrier tests finish under two seconds, no deadlocks, invalid entry makes zero callbacks, tail races fail, legacy hashes stay exact, full suite zero failures.

- [ ] **Step 8: Commit and report**

```bash
git add src/managing_long_task_context/__init__.py tests/test_truth_sources.py
git commit -m "feat: gate on live truth sources"
```

Report the stage/state matrix, callback and clock counts, barrier trace, lock ordering, stats examples, legacy hashes, full count, commit SHA, and concerns.

---

### Task 7: Document and Build the Installable Context Strict Package

**Worker:** Fresh implementation Agent, `gpt-5.6-terra`, reasoning `high`.

**Files:**
- Create: `assets/truth-source-contract.example.json`
- Create: `examples/truth_source_contract.py`
- Create: `tests/fixtures/truth_source_pilot.md`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `scripts/sync_context_strict_skill.py`
- Modify: `tests/test_distribution.py`
- Generate: matching `skills/context-strict/` files through the sync script

**Interfaces:**
- Produces `run_pilot(*, base_dir: Path, spec_path: Path, fixture_path: Path) -> dict[str, Any]` in the example.
- CLI accepts `--base-dir`, `--spec`, and `--fixture`; no argument uses a temporary workspace for the distributed smoke example.
- `COPIED_FILES` in sync and parity tests must match exactly.

**Dispatch contract:** Own documentation, example, fixture, explicit copy lists, and generated distribution only. Do not change runtime semantics, manually edit generated files, install globally, push, merge, or claim old runtimes enforce capabilities. Example must restore any mutable fixture in `finally`.

- [ ] **Step 1: Write failing distribution tests**

Add:

```python
def test_distribution_includes_truth_source_files(self):
    required = (
        Path("assets/truth-source-contract.example.json"),
        Path("examples/truth_source_contract.py"),
        Path("src/managing_long_task_context/truth_sources.py"),
        Path("tests/test_truth_sources.py"),
        Path("tests/fixtures/truth_source_pilot.md"),
    )
    for relative in required:
        self.assertEqual((STRICT / relative).read_bytes(), (ROOT / relative).read_bytes())

def test_distributed_truth_source_example_executes(self):
    result = subprocess.run(
        [sys.executable, "examples/truth_source_contract.py"],
        cwd=STRICT, capture_output=True, text=True, timeout=30,
    )
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

- [ ] **Step 2: Run distribution tests and capture RED evidence**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_distribution.ContextStrictDistributionTests -v
```

Expected: FAIL because the new asset/example/fixture/distribution files do not exist.

- [ ] **Step 3: Write the optional contract asset and public example**

Use the exact `truth_sources` schema from the approved spec. Keep the legacy asset unchanged. The example must use only public APIs and return:

```python
{
    "explicit_dirty_release_passed": True,
    "dirty_handoff_codes": ["TRUTH_SOURCE_DIRTY"],
    "reobserved_handoff_passed": True,
    "undeclared_change_code": "TRUTH_SOURCE_UNDECLARED_CHANGE",
    "changed_handoff_codes": ["TRUTH_SOURCE_CHANGED"],
    "recovered_handoff_passed": True,
    "canary_leaked": False,
    "fixture_restored": True,
}
```

`run_pilot` reads and saves original fixture bytes, executes both workflows, writes the required checkpoint before handoff, and scans JSON-serialized contract/events/snapshot/brief/report/errors for both canaries below:

```python
SPEC_CANARY = "协调删除、截断事件并重建 snapshot 的行为不可检测"
FIXTURE_CANARY_PREFIX = "TRUTH_SOURCE_PILOT_CANARY_"
```

The first canary already exists only in the design-spec source bytes; the second is introduced only in the isolated fixture mutation. Never place either canary in actor, reason, purpose, verification refs, exceptions, or other caller-supplied control metadata. Restore original fixture bytes in `finally`. Raise unless every eight-key result above matches and both canary scans are clean.

- [ ] **Step 4: Update Strict docs with operational boundaries**

Add a compact Truth Sources section to root `SKILL.md` covering:

- when to declare the optional capability;
- publish → observe all → release;
- mark dirty after declared changes;
- brief carries paths/control metadata, while executors read originals;
- unknown/fail blocks and truth observation is not completion evidence;
- no raw bytes, no automatic change inference, no actor authentication, no event hash chain;
- every participating runtime must be upgraded before use;
- no declaration means no truth-source scan or prompt block.

Update README installation/use examples and point to the new asset/example. Do not duplicate the full design spec.

- [ ] **Step 5: Update both explicit copy lists and synchronize**

Add the same five paths from Step 1 to `COPIED_FILES` in both the sync script and distribution test. Then run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_context_strict_skill.py
```

Inspect generated diffs; reject any unlisted or manual distribution change.

- [ ] **Step 6: Run root, distribution, example, and build smoke verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)
(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 examples/truth_source_contract.py)
truth_build_root="$(mktemp -d /tmp/context-strict-truth.TSC-07.XXXXXX)"
mkdir -p "$truth_build_root/wheel"
python3 -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir "$truth_build_root/wheel" ./skills/context-strict
python3 -m venv "$truth_build_root/venv"
"$truth_build_root/venv/bin/python" -m pip install --no-deps \
  "$truth_build_root/wheel/managing_long_task_context-0.2.0-py3-none-any.whl"
"$truth_build_root/venv/bin/python" -c "import managing_long_task_context; import managing_long_task_context.truth_sources"
echo "$truth_build_root"
git diff --check
```

Expected: `mktemp` prints a unique task-scoped build root on every run; root/distribution suites PASS, both examples PASS, wheel build plus isolated install/import PASS, and parity has no drift. Leave the unique temporary root outside the repository for operating-system cleanup; no implementation Agent performs a destructive cleanup.

- [ ] **Step 7: Commit and report**

```bash
git add SKILL.md README.md assets/truth-source-contract.example.json \
  examples/truth_source_contract.py tests/fixtures/truth_source_pilot.md \
  scripts/sync_context_strict_skill.py tests/test_distribution.py \
  skills/context-strict
git commit -m "docs: distribute truth source controls"
```

Report RED/GREEN, sync file list, root/distribution counts, example output, install/import output, diff, commit SHA, and residual deployment risks.

---

### Task 8: Run Natural Pilots and Close the Frozen Acceptance Contract

**Worker:** Fresh implementation Agent for pilot execution, `gpt-5.6-terra`, reasoning `high`; a different `gpt-5.6-terra` / `high` Agent performs the final acceptance review. The controller performs fresh verification after both and is the producer of the final validation artifacts.

**Files:**
- Create: `docs/validation/2026-08-31-truth-source-contract-pilot.md`
- Create: `docs/validation/2026-08-31-truth-source-contract-test-report.json`
- Runtime only: `.prime/context/TRUTH-SOURCE-PILOT-*` and `.prime/context/TRUTH-SOURCE-CONTRACT-001`
- Restore without committed change: `tests/fixtures/truth_source_pilot.md`

**Interfaces:**
- Consumes the public example/pilot and all public Context Strict APIs.
- Produces a human-readable validation record and a `context-test-report/v1` artifact with current full Git revision, exact commands, exit status, generated time, scope, and canonical artifact digest.
- Produces the final evidence map for task contract `TRUTH-SOURCE-CONTRACT-001`; the independent validator is not the report producer.

**Dispatch contract:** Execute public APIs and collect evidence only. Do not modify runtime code/tests/spec/plan, repair a failure, change acceptance, push, merge, install globally, or claim completion from green tests alone. Any failure stops the pilot and is reported with restored fixture evidence.

**Frozen acceptance contract:** The current pre-execution contract is task ID `TRUTH-SOURCE-CONTRACT-001`, version `1`, publisher `user-zhaowei`, seal digest `sha256:7c6c496c7684be728fdfbefa3e4d95d17f8ded3cdc2320abdaae60148827b7b2`, with exact actor roles `codex-root=["executor"]`, `independent-review-agent=["validator"]`, `user-zhaowei=["publisher"]`. Its six criteria below are immutable.

| AC | Frozen criterion | Evidence ID | Required type | Independent validation |
|---|---|---|---|---|
| AC-01 | 未声明 truth_sources 的旧合同保持合同摘要、brief、gate 与零额外文件读取的兼容行为，并有黄金测试锁定。 | `EV-TSC-AC-01` | `test-report` | required |
| AC-02 | truth-sources/v1 的可选 schema、required_capabilities、字段类型、唯一 ID、owner、age、change kind 与安全相对路径均被确定性校验。 | `EV-TSC-AC-02` | `test-report` | required |
| AC-03 | mark_truth_sources_dirty 与 observe_truth_source 以追加事件维护 generation、合同摘要、fingerprint、actor、原因和验证引用；未标 dirty 的字节变化不能被静默接受。 | `EV-TSC-AC-03` | `test-report` | required |
| AC-04 | release、resume、handoff、completion 对未观测、dirty、stale、changed、missing、unreadable 或 unknown 状态 fail closed，completion 在状态无效时不运行昂贵 evidence resolver。 | `EV-TSC-AC-04` | `test-report` | required |
| AC-05 | 首版文件解析器拒绝绝对路径、路径逃逸、目录、glob 与 symlink，使用单一文件描述符防 TOCTOU，执行 16 MiB 上限，且 brief、事件、快照和报告不泄漏原件正文。 | `EV-TSC-AC-05` | `test-report` | required |
| AC-06 | 根包与 context-strict 分发包保持一致，完整测试通过，并在本仓库自然验证 dirty 阻断 handoff、重新观测后放行且控制面无正文泄漏。 | `EV-TSC-AC-06` | `test-report` | required |

The frozen criteria have no `required_scope`, `required_revision`, hops, deliveries, or freshness override. The controller must not add them at evidence time. Each evidence envelope still carries an exact per-criterion scope so the claim verifier can bind one shared report to six distinct claims.

The version-1 contract predates file-backed completion evidence and lacks `workspace_root`. Before Task 8 runs, the controller must receive the user's execution approval and publish a dogfood version 2. It copies publisher fields exactly, removes only `seal`, sets `version=2`, and adds exactly `workspace_root`, `required_capabilities=["truth-sources/v1"]`, and the `TS-DESIGN-SPEC` declaration below. Reject the transition unless a structural diff proves only those fields and the newly generated seal changed; the six criteria, roles, scope, constraints, and all other publisher fields must remain structurally equal. The pilot worker and reviewer may not perform this publisher action.

```python
EXPECTED_TASK_TRUTH_SOURCES = {
    "schema": "truth-sources/v1",
    "items": [{
        "id": "TS-DESIGN-SPEC",
        "purpose": "已批准 Truth Source Contract 设计规格",
        "source_ref": {
            "kind": "file",
            "locator": "docs/superpowers/specs/2026-08-31-truth-source-contract-design.md",
        },
        "owner": "codex-root",
        "max_age_seconds": 86400,
        "validation_method": "owner-readback",
        "invalidate_on_change_kinds": ["spec-change"],
    }],
}
```

- [ ] **Step 1: Publish/recover dogfood contract v2, observe its source, and record the baseline**

After the user's execution approval, the controller performs and verifies the exact version-2 transition above. Because v2 itself enables `truth-sources/v1`, a crash after contract replacement but before event append must re-enter the Task 3 same-version recovery path rather than accepting `version == 2` as committed. The built-in `test-report` resolver then resolves repository-relative validation artifacts without any custom resolver or unsealed root injection. Record v1/v2 seals, the structural diff, the unique v2 publish event, and the source observation event.

```python
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))
import managing_long_task_context as context
from managing_long_task_context.evidence import canonical_json_bytes

contract_path = Path(".prime/context/TRUTH-SOURCE-CONTRACT-001/task-contract.json")
current = json.loads(contract_path.read_text(encoding="utf-8"))
stable_fields = {
    key: value
    for key, value in current.items()
    if key not in {
        "seal", "version", "workspace_root", "required_capabilities", "truth_sources"
    }
}
stable_digest = "sha256:" + hashlib.sha256(canonical_json_bytes(stable_fields)).hexdigest()
assert stable_digest == "sha256:2401a461d5fc879f6bbeb11146f80e41abf75d151c775203251f3e92a86dd897"
assert "sha256:" + hashlib.sha256(
    canonical_json_bytes(current["acceptance_criteria"])
).hexdigest() == "sha256:ab94662c50b233aab4c48521b7bbeec2d13efaa2a6aaa3a21eb634fff5ed5288"
assert "sha256:" + hashlib.sha256(
    canonical_json_bytes(current["actor_roles"])
).hexdigest() == "sha256:7284e01516b8b7c059cd7fb1f94f2d05d1e4bf405bc3778ce579de7a3d21fac3"

expected_truth_sources = {
    "schema": "truth-sources/v1",
    "items": [{
        "id": "TS-DESIGN-SPEC",
        "purpose": "已批准 Truth Source Contract 设计规格",
        "source_ref": {
            "kind": "file",
            "locator": "docs/superpowers/specs/2026-08-31-truth-source-contract-design.md",
        },
        "owner": "codex-root",
        "max_age_seconds": 86400,
        "validation_method": "owner-readback",
        "invalidate_on_change_kinds": ["spec-change"],
    }],
}

if current["version"] == 1:
    assert current["seal"]["integrity_digest"] == (
        "sha256:7c6c496c7684be728fdfbefa3e4d95d17f8ded3cdc2320abdaae60148827b7b2"
    )
    publisher_fields = {key: value for key, value in current.items() if key != "seal"}
    publisher_fields["version"] = 2
    publisher_fields["workspace_root"] = (
        "/Users/zhaowei/Desktop/David/project/managing-long-task-context"
    )
    publisher_fields["required_capabilities"] = ["truth-sources/v1"]
    publisher_fields["truth_sources"] = expected_truth_sources
    sealed_version_two = context.publish_contract(
        publisher_fields,
        confirmed_by="user-zhaowei",
        base_dir=Path(".prime/context"),
    )
elif current["version"] == 2:
    assert current["required_capabilities"] == ["truth-sources/v1"]
    assert current["truth_sources"] == expected_truth_sources
    commit_audit = context.audit(
        "TRUTH-SOURCE-CONTRACT-001", base_dir=Path(".prime/context"), emit=False
    )
    if commit_audit["passed"]:
        sealed_version_two = current
    elif commit_audit["errors"] == ["CONTRACT_COMMIT_MISSING_EVENT"]:
        publisher_fields = {key: value for key, value in current.items() if key != "seal"}
        sealed_version_two = context.publish_contract(
            publisher_fields,
            confirmed_by="user-zhaowei",
            base_dir=Path(".prime/context"),
        )
        assert sealed_version_two["seal"] == current["seal"]
    else:
        raise AssertionError(commit_audit)
else:
    raise AssertionError(f"unexpected contract version: {current['version']}")

assert sealed_version_two["workspace_root"] == (
    "/Users/zhaowei/Desktop/David/project/managing-long-task-context"
)
assert sealed_version_two["version"] == 2
assert sealed_version_two["required_capabilities"] == ["truth-sources/v1"]
assert sealed_version_two["truth_sources"] == expected_truth_sources
assert context.audit(
    "TRUTH-SOURCE-CONTRACT-001", base_dir=Path(".prime/context"), emit=False
)["passed"]
events = [
    json.loads(line)
    for line in (contract_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
matching_v2_publishes = [
    event
    for event in events
    if event.get("event_type") == "contract-published"
    and event.get("payload", {}).get("version") == 2
    and event.get("payload", {}).get("integrity_digest")
    == sealed_version_two["seal"]["integrity_digest"]
]
assert len(matching_v2_publishes) == 1

observation = context.observe_truth_source(
    "TRUTH-SOURCE-CONTRACT-001",
    source_id="TS-DESIGN-SPEC",
    actor="codex-root",
    verification_refs=["review:spec-approved-2026-08-31"],
    base_dir=Path(".prime/context"),
)
release = context.gate(
    "TRUTH-SOURCE-CONTRACT-001",
    stage="release",
    base_dir=Path(".prime/context"),
    emit=False,
)
assert release["passed"], release
```

```bash
git status --short --branch
git rev-parse HEAD
shasum -a 256 tests/fixtures/truth_source_pilot.md
```

Expected: only the planned validation artifacts may become new; capture the exact branch, revision, and fixture digest.

- [ ] **Step 2: Run the public-API natural pilot in the real workspace**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 examples/truth_source_contract.py \
  --base-dir .prime/context \
  --spec docs/superpowers/specs/2026-08-31-truth-source-contract-design.md \
  --fixture tests/fixtures/truth_source_pilot.md
```

Expected JSON matches the eight-key result from Task 7. Record pilot task IDs, event IDs, dirty/changed codes, gate stats, fingerprints, and canary scan; do not paste source bytes.

- [ ] **Step 3: Prove fixture restoration and control-plane non-leakage**

```bash
shasum -a 256 tests/fixtures/truth_source_pilot.md
git diff -- tests/fixtures/truth_source_pilot.md
rg -n 'TRUTH_SOURCE_PILOT_CANARY_|协调删除、截断事件并重建 snapshot 的行为不可检测' \
  .prime/context/TRUTH-SOURCE-PILOT-*
```

Expected: before/after digest identical, no fixture diff, and `rg` exits exactly `1` with no matches for either source-only canary. Exit `0` (match) or exit greater than `1` (search error) is a hard failure, as is missing restoration.

- [ ] **Step 4: Run fresh root and distribution verification at the current revision**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)
git diff --check
```

Expected: both suites PASS with explicit counts; no unexpected worktree changes.

- [ ] **Step 5: Write the validation record and structured test report**

The Markdown record must list each spec section 12 check, exact command/result, natural event/gate evidence, omissions, skipped checks, unresolved issues, and residual risks. Construct the JSON report from observed runtime values using this exact shape; write the resulting literal JSON with `apply_patch`:

```python
import hashlib
import json
import subprocess
from datetime import datetime, timezone

from managing_long_task_context.evidence import canonical_json_bytes

commands = [
    "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v",
    "(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)",
    "PYTHONDONTWRITEBYTECODE=1 python3 examples/truth_source_contract.py --base-dir .prime/context --spec docs/superpowers/specs/2026-08-31-truth-source-contract-design.md --fixture tests/fixtures/truth_source_pilot.md",
]
report_body = {
    "schema": "context-test-report/v1",
    "command": " && ".join(commands),
    "exit_status": 0,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "repo_revision": subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip(),
    "scope": {
        "feature": "truth-sources/v1",
        "repository": "managing-long-task-context",
    },
}
canonical = canonical_json_bytes(report_body)
report = {
    **report_body,
    "artifact_digest": "sha256:" + hashlib.sha256(canonical).hexdigest(),
}
```

Treat `repo_revision` as the immutable implementation revision under test, captured before the two validation artifacts are created. Confirm it is 40 lowercase hex characters and `generated_at` parses as explicit UTC RFC3339 before writing. Recompute the digest independently from the literal file after removing only `artifact_digest`; never use the production truth-source fingerprint helper to manufacture an expected test assertion.

- [ ] **Step 6: Dispatch an independent acceptance reviewer**

The `gpt-5.6-terra` / `high` reviewer receives the frozen spec, plan, current diff/commits, validation Markdown/JSON, task contract, and these checks:

1. Map AC-01 through AC-06 to direct artifacts and commands.
2. Inspect code paths for legacy short-circuit, poison/recovery, no-write reads, FD safety, gate short-circuit/tail, leakage, and distribution parity.
3. Rerun focused and full tests independently.
4. Verify pilot event/gate evidence and fixture hashes without trusting the executor summary.
5. Return one machine-readable `truth-source-acceptance-review/v1` object, not a prose-only verdict. Its exact top-level and nested allowlists are enforced by Step 7. It must carry the actual reviewed 40-hex implementation revision, actual UTC validation time, exact role/model/reasoning, all six AC verdicts, direct checked references prefixed by `file:`, `command:`, `event:`, `gate:`, or `hash:`, exact rerun commands, empty skipped/omission arrays, and honest residual risks.

The reviewer must not edit files. Any non-pass AC, missing evidence ref, skipped check, omission, revision mismatch, invalid UTC time, role/model/reasoning mismatch, or malformed field blocks the completion gate. After a PASS, the controller creates the exact heading `## Independent Acceptance` and appends `canonical_json_bytes(reviewer_result).decode("utf-8")` verbatim in its JSON code block in the validation Markdown using `apply_patch`. The controller then compares the embedded canonical bytes with the received reviewer object before constructing `evidence_map`; the test-report JSON body and digest remain unchanged.

- [ ] **Step 7: Run the Context Strict completion gate**

The controller, not the pilot worker, finalizes the validation JSON and is therefore the exact report producer `codex-root`. Build all six entries with this closed template, replacing only the criterion ID, frozen evidence ID, report-derived values, and reviewer-provided validation time:

```python
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from managing_long_task_context.evidence import canonical_json_bytes

report_path = Path("docs/validation/2026-08-31-truth-source-contract-test-report.json")
validation_path = Path("docs/validation/2026-08-31-truth-source-contract-pilot.md")
report_body = json.loads(report_path.read_text(encoding="utf-8"))
criterion_ids = ("AC-01", "AC-02", "AC-03", "AC-04", "AC-05", "AC-06")

assert set(reviewer_result) == {
    "schema", "reviewer_role", "model", "reasoning_effort",
    "reviewed_repo_revision", "validated_at", "ac_verdicts", "commands",
    "skipped_checks", "omissions", "residual_risks",
}
assert reviewer_result["schema"] == "truth-source-acceptance-review/v1"
assert reviewer_result["reviewer_role"] == "independent-review-agent"
assert reviewer_result["model"] == "gpt-5.6-terra"
assert reviewer_result["reasoning_effort"] == "high"
assert reviewer_result["reviewed_repo_revision"] == report_body["repo_revision"]
assert re.fullmatch(r"[0-9a-f]{40}", reviewer_result["reviewed_repo_revision"])
validated_time = datetime.fromisoformat(
    reviewer_result["validated_at"].replace("Z", "+00:00")
)
assert re.fullmatch(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)",
    reviewer_result["validated_at"],
)
assert validated_time.tzinfo is not None
assert validated_time.utcoffset() == timedelta(0)
assert validated_time <= datetime.now(timezone.utc) + timedelta(seconds=300)
assert datetime.now(timezone.utc) - validated_time <= timedelta(seconds=3600)
assert set(reviewer_result["ac_verdicts"]) == set(criterion_ids)
for criterion_id in criterion_ids:
    verdict = reviewer_result["ac_verdicts"][criterion_id]
    assert set(verdict) == {"status", "evidence_refs"}
    assert verdict["status"] == "pass"
    assert isinstance(verdict["evidence_refs"], list) and verdict["evidence_refs"]
    assert all(isinstance(ref, str) and ref.strip() for ref in verdict["evidence_refs"])
    assert all(
        ref.startswith(("file:", "command:", "event:", "gate:", "hash:"))
        for ref in verdict["evidence_refs"]
    )
assert isinstance(reviewer_result["commands"], list) and reviewer_result["commands"]
assert all(isinstance(command, str) and command.strip() for command in reviewer_result["commands"])
assert {
    "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v",
    "(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)",
}.issubset(set(reviewer_result["commands"]))
assert reviewer_result["skipped_checks"] == []
assert reviewer_result["omissions"] == []
assert isinstance(reviewer_result["residual_risks"], list)
assert all(isinstance(risk, str) and risk.strip() for risk in reviewer_result["residual_risks"])

reviewer_canonical = canonical_json_bytes(reviewer_result)
reviewer_digest = "sha256:" + hashlib.sha256(reviewer_canonical).hexdigest()
validation_markdown = validation_path.read_text(encoding="utf-8")
assert reviewer_canonical.decode("utf-8") in validation_markdown
validated_at = reviewer_result["validated_at"]
evidence_map = {
    criterion_id: {
        "validated_by": "independent-review-agent",
        "validated_at": validated_at,
        "evidence": [{
            "evidence_id": f"EV-TSC-{criterion_id}",
            "kind": "test-report",
            "locator": str(report_path),
            "artifact_digest": report_body["artifact_digest"],
            "generated_at": report_body["generated_at"],
            "produced_by": "codex-root",
            "reviewer_ref": str(validation_path) + "#independent-acceptance",
            "reviewer_digest": reviewer_digest,
            "reviewer_ac_status": reviewer_result["ac_verdicts"][criterion_id]["status"],
            "scope": {
                "task_id": "TRUTH-SOURCE-CONTRACT-001",
                "criterion_id": criterion_id,
                "feature": "truth-sources/v1",
            },
        }],
        "delivery_receipts": [],
    }
    for criterion_id in criterion_ids
}
```

Use the built-in `test-report` resolver from the sealed version-2 `workspace_root`. Add only a claim verifier that binds the envelope to the current criterion; it may not manufacture a pass or skip built-in resolve/integrity/scope checks:

```python
def verify_report_claim(evidence, criterion, resolution):
    expected_scope = {
        "task_id": "TRUTH-SOURCE-CONTRACT-001",
        "criterion_id": criterion["id"],
        "feature": "truth-sources/v1",
    }
    layers_pass = all(
        resolution[name]["status"] == "pass"
        for name in ("resolve", "integrity_and_freshness", "scope")
    )
    expected_evidence_id = f"EV-TSC-{criterion['id']}"
    codes = []
    if not layers_pass:
        codes.append("CLAIM_RESOLUTION_NOT_PASS")
    if evidence.get("evidence_id") != expected_evidence_id:
        codes.append("CLAIM_EVIDENCE_ID_MISMATCH")
    if evidence.get("locator") != str(report_path):
        codes.append("CLAIM_REPORT_LOCATOR_MISMATCH")
    if evidence.get("artifact_digest") != report_body["artifact_digest"]:
        codes.append("CLAIM_REPORT_DIGEST_MISMATCH")
    if evidence.get("generated_at") != report_body["generated_at"]:
        codes.append("CLAIM_REPORT_TIME_MISMATCH")
    if evidence.get("produced_by") != "codex-root":
        codes.append("CLAIM_PRODUCER_MISMATCH")
    if evidence.get("scope") != expected_scope:
        codes.append("CLAIM_SCOPE_MISMATCH")
    if evidence.get("reviewer_ref") != str(validation_path) + "#independent-acceptance":
        codes.append("CLAIM_REVIEWER_REF_MISMATCH")
    if evidence.get("reviewer_digest") != reviewer_digest:
        codes.append("CLAIM_REVIEWER_DIGEST_MISMATCH")
    if reviewer_canonical.decode("utf-8") not in validation_markdown:
        codes.append("CLAIM_REVIEWER_ARTIFACT_MISMATCH")
    if reviewer_result["ac_verdicts"].get(criterion["id"], {}).get("status") != "pass":
        codes.append("CLAIM_REVIEWER_VERDICT_NOT_PASS")
    if evidence.get("reviewer_ac_status") != "pass":
        codes.append("CLAIM_REVIEWER_ENVELOPE_NOT_PASS")
    return {"status": "pass" if not codes else "fail", "codes": codes}
```

```python
report = context.gate(
    "TRUTH-SOURCE-CONTRACT-001",
    stage="completion",
    evidence_map=evidence_map,
    verifiers={"test-report": verify_report_claim},
    base_dir=Path(".prime/context"),
    emit=False,
)
assert report["passed"], report
```

Expected: all six criteria pass, all evidence attempts are accounted for, and independent validation passes. If the gate fails, report it; do not alter the sealed criteria.

- [ ] **Step 8: Commit validation artifacts and report**

```bash
git add docs/validation/2026-08-31-truth-source-contract-pilot.md \
  docs/validation/2026-08-31-truth-source-contract-test-report.json
git commit -m "test: validate truth source pilots"
```

Report pilot outputs, fixture hashes, canary search, root/distribution counts, independent verdict, completion report, commit SHA, omissions, and residual risks. Do not push, merge, or update the global installation.

After this evidence-only commit, the controller must read `repo_revision` from `docs/validation/2026-08-31-truth-source-contract-test-report.json` and assert that the diff from that exact revision to `HEAD` contains only the two Task 8 validation artifacts. Any runtime, test, fixture, spec, plan, or distribution change invalidates the report and requires a fresh pilot against a new implementation revision.

---

## Controller Review and Dispatch Procedure

For every task:

1. Copy that task's Worker, Files, Interfaces, Dispatch contract, steps, commands, expected failures, pass criteria, and evidence requirements into the Agent prompt.
2. Set `model="gpt-5.6-terra"` and `reasoning_effort="high"` for the implementation Agent and for every independent Agent that executes review commands or acceptance checks.
3. Require the Agent to stop on scope conflict, failed required check, or infeasible verification.
4. After delivery, inspect the actual diff and commit, rerun focused checks and the full suite, then obtain a fresh specification-compliance review and code-quality review from an Agent that did not implement the task.
5. Update `.scratch/truth-source-contract/map.md` and the corresponding issue record only after controller evidence confirms the new status.
6. Do not start a dependent task until the preceding task is accepted.

## Final Verification Contract

The feature is complete only if V-01 through V-11 pass on the single recorded implementation revision and V-12 confirms the subsequent evidence-only commit changes only the two validation artifacts:

| ID | Required check | Pass criterion | Required evidence |
|---|---|---|---|
| V-01 | Legacy exact compatibility | Ten fixed hashes unchanged; truth evaluator and workspace-source I/O count are zero | Hash table, call spies, full output |
| V-02 | Schema/capability | Every approved positive case passes and every invalid pair/field/type/path fails with stable field-qualified error | Table-driven test output |
| V-03 | Secure file resolver | Root/path/symlink/TOCTOU/FD/16 MiB/canary tests pass; no unsafe fallback | Focused output, FD counts, canary scan |
| V-04 | Event and recovery | Reset/reducer/rebuild/poison and every publish crash cut recover or fail closed | Event/rebuild equality and failure-injection matrix |
| V-05 | Write APIs | Dirty/observe transitions bind actor/digest/generation/fingerprint/time; rejection paths write nothing | Event bytes/counts and returned control metadata |
| V-06 | Brief/economy | Declared controls are mandatory and live; legacy output/I/O unchanged; no source bytes or refs leak | Prompt/diagnostics diff, resolver counts, canary scan |
| V-07 | Four gates | Every invalid state blocks all stages; entry-invalid completion calls zero evidence; tail races/freshness block | Stage matrix, callback counts, barrier trace |
| V-08 | Read-only boundary | audit/brief/diagnostics/gate create no task/lock/temp writes | Write-spy and before/after filesystem evidence |
| V-09 | Distribution | Root and installable package byte parity, examples, both suites, isolated import pass | Sync diff, counts, install/import output |
| V-10 | Natural behavior | Explicit dirty and unmarked byte-change pilots block and recover exactly; fixture restored; canary absent | Event IDs, codes, hashes, reports |
| V-11 | Independent acceptance | Different reviewer passes AC-01 through AC-06 at final revision | Reviewer mapping and completion gate report |
| V-12 | Scope and side effects | No Lite/network/Git source/watcher/raw persistence; no push/merge/global install | Final diff, git status, residual-risk report |

A failure in V-01 through V-12 blocks an overall completion claim. Green tests alone do not prove V-09 through V-12.
