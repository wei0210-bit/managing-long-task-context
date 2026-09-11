"""Synthetic public-boundary checks for the frozen independence slice.

These fixtures model a host-owned resolver only.  They do not authenticate a
real Codex/Claude host or claim any runtime/token outcome.
"""

from __future__ import annotations

from copy import deepcopy
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import managing_long_task_context as context


NOW = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)


class IndependentValidationPublicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.content = b"synthetic independently checked artifact\n"
        (self.workspace / "result.txt").write_bytes(self.content)
        self.clock = patch.object(context, "_trusted_utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def contract(self, *, version: int = 1, required: bool = True) -> dict[str, object]:
        return {
            "schema": 1,
            "task_id": "IV-TASK",
            "version": version,
            "issued_by": "publisher",
            "issued_at": "2026-09-11T09:00:00Z",
            "authorized_approvers": [],
            "objective": "Exercise the synthetic public completion boundary",
            "scope": ["local fixture"],
            "out_of_scope": [],
            "constraints": [],
            "workspace_root": str(self.workspace),
            "actor_roles": {
                "executor-principal": ["executor"],
                "validator-principal": ["validator"],
            },
            "acceptance_criteria": [{
                "id": "AC-01",
                "criterion": "Synthetic artifact is independently checked",
                "required_evidence": ["file"],
                "required_scope": {"task_id": "IV-TASK", "criterion_id": "AC-01"},
                "independent_validation_required": required,
            }],
        }

    def evidence_entry(self, validation_ref: str = "synthetic-run-01") -> dict[str, object]:
        return {
            "validation_ref": validation_ref,
            "evidence": [{
                "evidence_id": "EV-01",
                "kind": "file",
                "locator": "result.txt",
                "artifact_digest": "sha256:" + hashlib.sha256(self.content).hexdigest(),
                "scope": {"task_id": "IV-TASK", "criterion_id": "AC-01"},
                "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            }],
        }

    def resolver(self, ref: object) -> dict[str, object]:
        contract_path = self.base / "IV-TASK" / "task-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        return {
            "validation_ref": ref,
            "task_id": "IV-TASK",
            "criterion_id": "AC-01",
            "contract_digest": contract["seal"]["integrity_digest"],
            "workspace_root": str(self.workspace.resolve()),
            "executor_principals": ["executor-principal"],
            "validator_principal": "validator-principal",
            "run_id": "synthetic-host-run-01",
            "checker_id": "synthetic-host-checker-01",
            "validated_at": "2026-09-11T09:59:00Z",
            "expires_at": "2026-09-11T10:01:00Z",
            "evidence_digests": {
                "EV-01": "sha256:" + hashlib.sha256(self.content).hexdigest(),
            },
            "repo_revision": None,
            "check_result": "pass",
        }

    def file_verifier(self, evidence: dict[str, object], *_args: object) -> dict[str, object]:
        locator = evidence.get("locator")
        if not isinstance(locator, str):
            return {"status": "fail", "codes": ["MISSING_FIXTURE_LOCATOR"]}
        try:
            actual = (self.workspace / locator).read_bytes()
        except OSError:
            return {"status": "fail", "codes": ["FIXTURE_UNREADABLE"]}
        return (
            {"status": "pass", "codes": []}
            if actual == self.content and b"independently checked" in actual
            else {"status": "fail", "codes": ["FIXTURE_CONTENT_REJECTED"]}
        )

    def test_iv01_public_gate_accepts_current_distinct_trusted_receipt(self) -> None:
        context.publish_contract(
            self.contract(), confirmed_by="publisher", base_dir=self.base,
            independent_validation_required=True,
            validation_resolver=self.resolver,
        )

        report = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, independent_validation_required=True,
            validation_resolver=self.resolver, verifiers={"file": self.file_verifier},
        )

        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(
            report["criteria"]["AC-01"]["independent_validation"]["status"],
            "pass",
        )
        self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], "verified")

    def publish_required(self, *, policy: bool | None = True) -> None:
        context.publish_contract(
            self.contract(), confirmed_by="publisher", base_dir=self.base,
            independent_validation_required=policy,
        )

    def complete(
        self, resolver: object | None = None, entry: dict[str, object] | None = None,
        *, policy: bool | None = True,
    ) -> dict[str, object]:
        return context.gate(
            "IV-TASK", stage="completion",
            evidence_map={"AC-01": entry or self.evidence_entry()}, base_dir=self.base,
            emit=False, independent_validation_required=policy,
            validation_resolver=self.resolver if resolver is None else resolver,
            verifiers={"file": self.file_verifier},
        )

    def test_iv02_to_iv12_receipt_failures_are_trusted_and_blocking(self) -> None:
        self.publish_required()
        cases: list[tuple[str, object, str]] = [
            ("self-review", lambda ref: {**self.resolver(ref), "validator_principal": "executor-principal"}, "failed"),
            ("alias-self-review", lambda ref: {**self.resolver(ref), "executor_principals": ["validator-principal"]}, "failed"),
            ("missing-principal", lambda ref: {**self.resolver(ref), "executor_principals": []}, "unknown"),
            ("missing-time", lambda ref: {key: value for key, value in self.resolver(ref).items() if key != "validated_at"}, "unknown"),
            ("wrong-binding", lambda ref: {**self.resolver(ref), "task_id": "OTHER"}, "unknown"),
            ("wrong-criterion", lambda ref: {**self.resolver(ref), "criterion_id": "AC-OTHER"}, "unknown"),
            ("old-contract-digest", lambda ref: {**self.resolver(ref), "contract_digest": "sha256:old"}, "unknown"),
            ("wrong-workspace", lambda ref: {**self.resolver(ref), "workspace_root": "/wrong"}, "unknown"),
            ("wrong-digest", lambda ref: {**self.resolver(ref), "evidence_digests": {"EV-01": "sha256:wrong"}}, "unknown"),
            ("expired", lambda ref: {**self.resolver(ref), "expires_at": "2026-09-11T09:00:00Z"}, "unknown"),
            ("future", lambda ref: {**self.resolver(ref), "validated_at": "2026-09-11T10:01:00Z"}, "unknown"),
            ("missing-run", lambda ref: {key: value for key, value in self.resolver(ref).items() if key != "run_id"}, "unknown"),
            ("missing-checker", lambda ref: {key: value for key, value in self.resolver(ref).items() if key != "checker_id"}, "unknown"),
            ("malformed", lambda _ref: ["not", "a", "receipt"], "unknown"),
            ("checker-fail", lambda ref: {**self.resolver(ref), "check_result": "fail"}, "failed"),
            ("checker-unknown", lambda ref: {**self.resolver(ref), "check_result": "unknown"}, "unknown"),
        ]
        for label, resolver, expected in cases:
            with self.subTest(label=label):
                report = self.complete(resolver)
                self.assertFalse(report["passed"])
                expected_status = "fail" if expected == "failed" else expected
                self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["status"], expected_status)
                self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], expected)

        model_json = self.evidence_entry()
        model_json.update({"validated_by": "validator-principal", "validated_at": "2026-09-11T09:59:00Z"})
        no_resolver = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": model_json}, base_dir=self.base,
            emit=False, independent_validation_required=True, verifiers={"file": self.file_verifier},
        )
        self.assertFalse(no_resolver["passed"])
        self.assertEqual(
            no_resolver["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown"
        )
        executor_only = self.evidence_entry()
        executor_only.update(executor="executor-principal", result="pass", validation_receipt={"check_result": "pass"})
        executor_claim = context.gate("IV-TASK", stage="completion", evidence_map={"AC-01": executor_only},
                                      base_dir=self.base, emit=False, independent_validation_required=True,
                                      verifiers={"file": self.file_verifier})
        self.assertFalse(executor_claim["passed"])
        self.assertEqual(executor_claim["criteria"]["AC-01"]["independent_validation"]["status"], "unknown")
        raised = self.complete(lambda _ref: (_ for _ in ()).throw(RuntimeError("synthetic host unavailable")))
        self.assertFalse(raised["passed"])
        self.assertEqual(raised["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown")

        revision_contract = self.contract(version=2)
        revision_contract["acceptance_criteria"][0]["required_revision"] = "a" * 40
        context.publish_contract(revision_contract, confirmed_by="publisher", base_dir=self.base)
        revision_entry = self.evidence_entry()
        revision_entry["evidence"][0]["repo_revision"] = "a" * 40
        wrong_revision = self.complete(
            lambda ref: {**self.resolver(ref), "repo_revision": "b" * 40}, revision_entry,
        )
        self.assertFalse(wrong_revision["passed"])
        self.assertEqual(wrong_revision["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown")

    def test_iv13_to_iv18_host_policy_and_bound_override(self) -> None:
        false_contract = self.contract(required=False)
        with self.assertRaisesRegex(context.ContextError, "every acceptance criterion"):
            context.publish_contract(
                false_contract, confirmed_by="publisher", base_dir=self.base,
                independent_validation_required=True,
            )
        self.assertFalse((self.base / "IV-TASK").exists())
        for label, change in (
            ("omitted", lambda item: item.pop("independent_validation_required")),
            ("no-true", lambda item: item.update(independent_validation_required=False)),
        ):
            candidate = self.contract(required=True)
            candidate["task_id"] = f"IV-{label}"
            change(candidate["acceptance_criteria"][0])
            with self.subTest(label=label), self.assertRaises(context.ContextError):
                context.publish_contract(candidate, confirmed_by="publisher", base_dir=self.base,
                                         independent_validation_required=True)

        self.publish_required()
        downgraded = self.contract(version=2, required=False)
        with self.assertRaisesRegex(context.ContextError, "cannot be removed"):
            context.publish_contract(downgraded, confirmed_by="publisher", base_dir=self.base)
        sealed_before = (self.base / "IV-TASK" / "task-contract.json").read_bytes()
        removed = self.contract(version=2, required=False)
        removed["acceptance_criteria"][0]["id"] = "AC-REPLACEMENT"
        with self.assertRaisesRegex(context.ContextError, "cannot be removed"):
            context.publish_contract(removed, confirmed_by="publisher", base_dir=self.base)
        self.assertEqual((self.base / "IV-TASK" / "task-contract.json").read_bytes(), sealed_before)
        context.publish_contract(
            downgraded, confirmed_by="publisher", base_dir=self.base,
            independent_validation_required=False,
        )
        legacy = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, verifiers={"file": self.file_verifier},
        )
        self.assertTrue(legacy["passed"], legacy["errors"])
        self.assertEqual(legacy["criteria"]["AC-01"]["independent_validation"], {"status": "pass", "codes": []})
        unused_calls: list[object] = []
        legacy_with_resolver = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, independent_validation_required=False,
            validation_resolver=lambda ref: unused_calls.append(ref), verifiers={"file": self.file_verifier},
        )
        self.assertTrue(legacy_with_resolver["passed"], legacy_with_resolver["errors"])
        self.assertEqual(unused_calls, [])

        with self.assertRaisesRegex(context.ContextError, "greater version"):
            context.publish_contract(
                self.contract(version=1, required=False), confirmed_by="publisher", base_dir=self.base,
                independent_validation_required=False,
            )
        with self.assertRaisesRegex(context.ContextError, "confirmed_by"):
            context.publish_contract(
                self.contract(version=3, required=False), confirmed_by="not-authorized", base_dir=self.base,
                independent_validation_required=False,
            )

        bound = context.bind(self.base, independent_validation_required=False)
        with self.assertRaisesRegex(context.ContextError, "cannot override"):
            bound.gate("IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                       independent_validation_required=True)
        with self.assertRaisesRegex(context.ContextError, "cannot override"):
            bound.gate("IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                       validation_resolver=self.resolver)

        blocked = context.gate(
            "IV-TASK", stage="release", base_dir=self.base, emit=False,
            independent_validation_required=True,
        )
        self.assertFalse(blocked["passed"])
        self.assertTrue(any("host independent_validation_required=true" in error for error in blocked["errors"]))
        completion_blocked = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, independent_validation_required=True,
            verifiers={"file": self.file_verifier},
        )
        self.assertFalse(completion_blocked["passed"])

    def test_iv19_to_iv22_rechecks_repeat_and_semantic_failure(self) -> None:
        self.publish_required()
        events_path = self.base / "IV-TASK" / "events.jsonl"
        before = events_path.read_bytes()
        calls: list[object] = []

        def counted(ref: object) -> dict[str, object]:
            calls.append(ref)
            return self.resolver(ref)

        first = self.complete(counted)
        second = self.complete(counted)
        self.assertTrue(first["passed"], first["errors"])
        self.assertEqual(first["passed"], second["passed"])
        self.assertEqual(calls, ["synthetic-run-01", "synthetic-run-01"])
        self.assertEqual(events_path.read_bytes(), before)

        semantic = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, independent_validation_required=True,
            validation_resolver=self.resolver,
            verifiers={"file": lambda *_args: {"status": "fail", "codes": ["SEMANTIC_REJECTED"]}},
        )
        self.assertFalse(semantic["passed"])
        self.assertEqual(semantic["criteria"]["AC-01"]["independent_validation"]["assurance"], "verified")

        def contract_mutating(ref: object) -> dict[str, object]:
            receipt = self.resolver(ref)
            context.publish_contract(
                self.contract(version=2), confirmed_by="publisher", base_dir=self.base,
            )
            return receipt

        changed_contract = self.complete(contract_mutating)
        self.assertFalse(changed_contract["passed"])
        self.assertEqual(
            changed_contract["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown"
        )

        def mutating(ref: object) -> dict[str, object]:
            (self.workspace / "result.txt").write_bytes(b"changed during resolver\n")
            return self.resolver(ref)

        mutated = self.complete(mutating)
        self.assertFalse(mutated["passed"])
        self.assertTrue(any("EVIDENCE_CHANGED_OR_UNAVAILABLE" in item for item in mutated["errors"]))
        (self.workspace / "result.txt").write_bytes(self.content)
        renewed = self.complete(self.resolver)
        self.assertTrue(renewed["passed"], renewed["errors"])

    def test_review_cr01_to_cr03_truth_context_and_entry_self_review_block(self) -> None:
        truth_contract = self.contract()
        (self.workspace / "STATUS.md").write_text("synthetic status\n", encoding="utf-8")
        truth_contract.update(
            required_capabilities=["truth-sources/v1"],
            truth_sources={"schema": "truth-sources/v1", "items": [{
                "id": "TS-STATUS", "purpose": "current status",
                "source_ref": {"kind": "file", "locator": "STATUS.md"},
                "owner": "publisher", "max_age_seconds": 60,
                "validation_method": "owner-readback",
                "invalidate_on_change_kinds": ["implementation-change"],
            }]},
        )
        context.publish_contract(truth_contract, confirmed_by="publisher", base_dir=self.base)
        blocked_truth = self.complete(self.resolver)
        self.assertFalse(blocked_truth["passed"])
        self.assertEqual(blocked_truth["criteria"], {})

        self.tearDown()
        self.setUp()
        self.publish_required()
        def conflict_resolver(ref: object) -> dict[str, object]:
            item = context.record("IV-TASK", statement="conflicting callback fact", item_type="observation",
                                  actor="publisher", source={"kind": "test", "ref": "cr02"}, base_dir=self.base)
            context.update_item("IV-TASK", item["id"], actor="publisher", status="conflicted",
                                conflicts_with=["EV-01"], conflict_reason="callback conflict", base_dir=self.base)
            return self.resolver(ref)
        changed = self.complete(conflict_resolver)
        self.assertFalse(changed["passed"])
        self.assertEqual(changed["criteria"]["AC-01"]["status"], "unknown")

        self.tearDown()
        self.setUp()
        self.publish_required()
        entry = self.evidence_entry()
        entry.update(validated_by="validator-principal", executor="validator-principal")
        self_review = self.complete(self.resolver, entry)
        self.assertFalse(self_review["passed"])
        self.assertIn("VALIDATOR_NOT_INDEPENDENT", self_review["criteria"]["AC-01"]["independent_validation"]["codes"])

    def test_review_cr04_emits_final_policy_failure_once(self) -> None:
        context.publish_contract(self.contract(required=False), confirmed_by="publisher", base_dir=self.base)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report = context.gate("IV-TASK", stage="release", base_dir=self.base,
                                  independent_validation_required=True)
        self.assertFalse(report["passed"])
        self.assertIn(f"errors {len(report['errors'])}", output.getvalue())
        self.assertEqual(output.getvalue().count("[release]"), 1)

    def test_iv03_iv14_display_alias_and_same_criterion_omission(self) -> None:
        contract = self.contract()
        contract["workspace_root"] = str(self.workspace.resolve())
        contract["actor_roles"].update({"validator-display": ["validator"]})
        context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
        aliases = self.evidence_entry()
        aliases.update(validated_by="validator-display", executor="executor-display")
        failed = self.complete(lambda ref: {**self.resolver(ref), "executor_principals": ["validator-principal"]}, aliases)
        self.assertEqual(failed["criteria"]["AC-01"]["independent_validation"]["status"], "fail")

        sealed = (self.base / "IV-TASK" / "task-contract.json").read_bytes()
        omitted = self.contract(version=2)
        omitted["acceptance_criteria"][0].pop("independent_validation_required")
        with self.assertRaisesRegex(context.ContextError, "cannot be removed"):
            context.publish_contract(omitted, confirmed_by="publisher", base_dir=self.base)
        self.assertEqual((self.base / "IV-TASK" / "task-contract.json").read_bytes(), sealed)

    def test_iv15_iv18_modern_not_required_assurance(self) -> None:
        modern = self.contract(required=True)
        modern.update(required_capabilities=["evidence-handlers/v1"], evidence_handlers={
            "schema": "evidence-handlers/v1", "types": {"file": {
                "resolver_capability": "builtin:file/v1", "verifier_capability": "builtin:file/v1",
            }},
        })
        context.publish_contract(modern, confirmed_by="publisher", base_dir=self.base)
        downgraded = deepcopy(modern)
        downgraded["version"] = 2
        downgraded["acceptance_criteria"][0]["independent_validation_required"] = False
        context.publish_contract(
            downgraded, confirmed_by="publisher", base_dir=self.base,
            independent_validation_required=False,
        )
        resolver_calls: list[object] = []
        report = context.gate("IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                              base_dir=self.base, emit=False, independent_validation_required=False,
                              validation_resolver=lambda ref: resolver_calls.append(ref),
                              verifiers={"file": {"capability": "builtin:file/v1", "handler": self.file_verifier}})
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], "not_required")
        self.assertEqual(resolver_calls, [])

    def test_iv20_iv21_stable_decision_and_semantic_criterion_failure(self) -> None:
        self.publish_required()
        task_dir = self.base / "IV-TASK"
        state_paths = tuple(task_dir / name for name in ("task-contract.json", "events.jsonl", "snapshot.json"))
        before = {path: path.read_bytes() for path in state_paths}
        first = self.complete(self.resolver)
        second = self.complete(self.resolver)
        for field in ("passed", "decision", "errors", "criteria"):
            self.assertEqual(first.get(field), second.get(field))
        self.assertEqual(
            json.dumps(first["criteria"], sort_keys=True, separators=(",", ":")).encode(),
            json.dumps(second["criteria"], sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertEqual({path: path.read_bytes() for path in state_paths}, before)

        def semantic_reject(evidence: dict[str, object], *_args: object) -> dict[str, object]:
            locator = evidence.get("locator")
            actual = (self.workspace / locator).read_bytes() if isinstance(locator, str) else b""
            return (
                {"status": "fail", "codes": ["SEMANTIC_REJECTED"]}
                if actual == self.content else {"status": "unknown", "codes": ["FIXTURE_UNREADABLE"]}
            )

        semantic = context.gate("IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                                base_dir=self.base, emit=False, independent_validation_required=True,
                                validation_resolver=self.resolver,
                                verifiers={"file": semantic_reject})
        self.assertEqual(semantic["criteria"]["AC-01"]["status"], "fail")

    def test_iv17_omitted_stored_requirement_blocks_release_and_completion(self) -> None:
        omitted = self.contract(required=True)
        omitted["acceptance_criteria"][0].pop("independent_validation_required")
        context.publish_contract(omitted, confirmed_by="publisher", base_dir=self.base)
        for stage in ("release", "completion"):
            with self.subTest(stage=stage):
                report = context.gate("IV-TASK", stage=stage,
                                      evidence_map={"AC-01": self.evidence_entry()} if stage == "completion" else None,
                                      base_dir=self.base, emit=False, independent_validation_required=True,
                                      verifiers={"file": self.file_verifier})
                self.assertFalse(report["passed"])

    def test_iv19_observed_truth_dirty_inside_resolver_blocks_tail(self) -> None:
        contract = self.contract()
        contract["workspace_root"] = str(self.workspace.resolve())
        (self.workspace / "STATUS.md").write_text("observed status\n", encoding="utf-8")
        contract.update(required_capabilities=["truth-sources/v1"], truth_sources={
            "schema": "truth-sources/v1", "items": [{
                "id": "TS-STATUS", "purpose": "current status",
                "source_ref": {"kind": "file", "locator": "STATUS.md"}, "owner": "publisher",
                "max_age_seconds": 60, "validation_method": "owner-readback",
                "invalidate_on_change_kinds": ["implementation-change"],
            }],
        })
        with patch.object(context, "_now", return_value=NOW.isoformat()):
            context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
            context.observe_truth_source("IV-TASK", source_id="TS-STATUS", actor="publisher",
                                         verification_refs=["review:observed"], base_dir=self.base)
        def dirty(ref: object) -> dict[str, object]:
            context.mark_truth_sources_dirty("IV-TASK", change_kind="implementation-change",
                                             actor="publisher", reason="resolver changed input", base_dir=self.base)
            return self.resolver(ref)
        report = self.complete(dirty)
        self.assertFalse(report["passed"])
        self.assertEqual(report["criteria"]["AC-01"]["status"], "unknown")

    def test_truth_tail_lock_failure_preserves_semantic_fail_priority(self) -> None:
        contract = self.contract()
        contract["workspace_root"] = str(self.workspace.resolve())
        (self.workspace / "STATUS.md").write_text("observed status\n", encoding="utf-8")
        contract.update(
            required_capabilities=["truth-sources/v1", "evidence-handlers/v1"],
            evidence_handlers={"schema": "evidence-handlers/v1", "types": {"file": {
                "resolver_capability": "builtin:file/v1", "verifier_capability": "builtin:file/v1",
            }}},
            truth_sources={"schema": "truth-sources/v1", "items": [{
                "id": "TS-STATUS", "purpose": "current status",
                "source_ref": {"kind": "file", "locator": "STATUS.md"}, "owner": "publisher",
                "max_age_seconds": 60, "validation_method": "owner-readback",
                "invalidate_on_change_kinds": ["implementation-change"],
            }]},
        )
        with patch.object(context, "_now", return_value=NOW.isoformat()):
            context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
            context.observe_truth_source("IV-TASK", source_id="TS-STATUS", actor="publisher",
                                         verification_refs=["review:observed"], base_dir=self.base)

        def lock_breaking_receipt(ref: object) -> dict[str, object]:
            receipt = self.resolver(ref)
            task_lock = self.base / "IV-TASK" / ".lock"
            task_lock.unlink()
            task_lock.mkdir()
            return receipt

        def semantic_reject(*_args: object) -> dict[str, object]:
            return {"status": "fail", "codes": ["SEMANTIC_REJECTED"]}

        report = context.gate(
            "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
            base_dir=self.base, emit=False, independent_validation_required=True,
            validation_resolver=lock_breaking_receipt,
            verifiers={"file": {"capability": "builtin:file/v1", "handler": semantic_reject}},
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["criteria"]["AC-01"]["status"], "fail")
        self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown")
        self.assertEqual(report["decision"], "fail")
        self.assertEqual(report["criteria"]["AC-01"]["evidence_results"][0]["status"], "fail")

    def test_fr01_to_fr03_required_workspace_binding_is_explicit_and_economical(self) -> None:
        invalid_cases = [
            ("omitted", None, "MISSING_CONTRACT_WORKSPACE_ROOT", True),
            ("empty", "", "MISSING_CONTRACT_WORKSPACE_ROOT", None),
            ("null", None, "MISSING_CONTRACT_WORKSPACE_ROOT", True),
            ("number", 7, "INVALID_CONTRACT_WORKSPACE_ROOT", None),
            ("relative", "workspace", "INVALID_CONTRACT_WORKSPACE_ROOT", True),
            ("resolution-failure", None, "INVALID_CONTRACT_WORKSPACE_ROOT", None),
        ]

        for label, workspace_root, expected_code, policy in invalid_cases:
            with self.subTest(label=label):
                self.tearDown()
                self.doCleanups()
                self.setUp()
                contract = self.contract()
                if label == "omitted":
                    contract.pop("workspace_root")
                elif label == "resolution-failure":
                    loop = Path(self.temp.name) / "workspace-loop"
                    loop.symlink_to(loop.name)
                    contract["workspace_root"] = str(loop)
                else:
                    contract["workspace_root"] = workspace_root
                contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
                context.publish_contract(
                    contract, confirmed_by="publisher", base_dir=self.base,
                    independent_validation_required=policy,
                )
                entry = self.evidence_entry()
                entry["evidence"][0]["kind"] = "custom"
                evidence_reads: list[str] = []
                receipt_calls: list[object] = []

                def custom_reader(evidence: dict[str, object], *_args: object) -> dict[str, object]:
                    evidence_reads.append(str(evidence.get("locator")))
                    status = "pass" if (self.workspace / "result.txt").read_bytes() == self.content else "fail"
                    return {layer: {"status": status, "codes": []}
                            for layer in ("resolve", "integrity_and_freshness", "scope")}

                def receipt(ref: object) -> dict[str, object]:
                    receipt_calls.append(ref)
                    return self.resolver(ref)

                report = context.gate(
                    "IV-TASK", stage="completion", evidence_map={"AC-01": entry},
                    base_dir=self.base, emit=False, independent_validation_required=policy,
                    validation_resolver=receipt, resolvers={"custom": custom_reader},
                    verifiers={"custom": self.file_verifier},
                )
                self.assertFalse(report["passed"])
                self.assertEqual(report["criteria"]["AC-01"]["status"], "unknown")
                independence = report["criteria"]["AC-01"]["independent_validation"]
                self.assertEqual(independence["status"], "unknown")
                self.assertEqual(independence["assurance"], "unknown")
                self.assertEqual(independence["codes"], [expected_code])
                self.assertEqual(evidence_reads, ["result.txt"])
                self.assertEqual(receipt_calls, [])

        for label in ("dotdot", "symlink"):
            with self.subTest(label=label):
                self.tearDown()
                self.doCleanups()
                self.setUp()
                contract = self.contract()
                if label == "dotdot":
                    contract["workspace_root"] = str(self.workspace / "nested" / "..")
                else:
                    alias = Path(self.temp.name) / "workspace-alias"
                    alias.symlink_to(self.workspace, target_is_directory=True)
                    contract["workspace_root"] = str(alias)
                contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
                context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
                entry = self.evidence_entry()
                entry["evidence"][0]["kind"] = "custom"
                receipt_calls: list[object] = []

                def custom_reader(evidence: dict[str, object], *_args: object) -> dict[str, object]:
                    status = "pass" if (self.workspace / str(evidence["locator"])).read_bytes() == self.content else "fail"
                    return {layer: {"status": status, "codes": []}
                            for layer in ("resolve", "integrity_and_freshness", "scope")}

                def receipt(ref: object) -> dict[str, object]:
                    receipt_calls.append(ref)
                    return self.resolver(ref)

                report = context.gate(
                    "IV-TASK", stage="completion", evidence_map={"AC-01": entry},
                    base_dir=self.base, emit=False, validation_resolver=receipt,
                    resolvers={"custom": custom_reader}, verifiers={"custom": self.file_verifier},
                )
                self.assertTrue(report["passed"], report["errors"])
                self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], "verified")
                self.assertEqual(receipt_calls, ["synthetic-run-01"])

    def test_fr04_nonindependent_missing_workspace_keeps_legacy_without_callback(self) -> None:
        for label, required in (("false", False), ("omitted", None)):
            with self.subTest(label=label):
                self.tearDown()
                self.doCleanups()
                self.setUp()
                contract = self.contract(required=False)
                contract.pop("workspace_root")
                if required is None:
                    contract["acceptance_criteria"][0].pop("independent_validation_required")
                context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
                receipt_calls: list[object] = []
                legacy = context.gate(
                    "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                    base_dir=self.base, emit=False, verifiers={"file": self.file_verifier},
                )
                report = context.gate(
                    "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                    base_dir=self.base, emit=False,
                    validation_resolver=lambda ref: receipt_calls.append(ref),
                    verifiers={"file": self.file_verifier},
                )
                self.assertEqual(report["passed"], legacy["passed"])
                self.assertEqual(report["errors"], legacy["errors"])
                self.assertEqual(report["criteria"], legacy["criteria"])
                self.assertEqual(report["criteria"]["AC-01"]["independent_validation"], {"status": "pass", "codes": []})
                self.assertEqual(receipt_calls, [])

    def test_fr05_damaged_criteria_returns_existing_report_without_callback(self) -> None:
        for damaged in (None, 7):
            for use_resolver in (False, True):
                with self.subTest(damaged=damaged, use_resolver=use_resolver):
                    self.tearDown()
                    self.doCleanups()
                    self.setUp()
                    context.publish_contract(
                        self.contract(), confirmed_by="publisher", base_dir=self.base,
                        protect_contract=False,
                    )
                    contract_path = self.base / "IV-TASK" / "task-contract.json"
                    stored = json.loads(contract_path.read_text(encoding="utf-8"))
                    stored["acceptance_criteria"] = damaged
                    contract_path.write_text(json.dumps(stored), encoding="utf-8")
                    receipt_calls: list[object] = []

                    def receipt(ref: object) -> dict[str, object]:
                        receipt_calls.append(ref)
                        return self.resolver(ref)

                    report = context.gate(
                        "IV-TASK", stage="completion", evidence_map={"AC-01": self.evidence_entry()},
                        base_dir=self.base, emit=False,
                        validation_resolver=receipt if use_resolver else None,
                        verifiers={"file": self.file_verifier},
                    )
                    self.assertFalse(report["passed"])
                    self.assertIn("contract.acceptance_criteria must contain publisher-written criteria", report["errors"])
                    self.assertTrue(any("contract integrity digest is invalid" in error for error in report["errors"]))
                    self.assertEqual(receipt_calls, [])

    def test_iv07_receipt_time_is_checked_at_resolver_and_completion_tail(self) -> None:
        for name, expected_passed in (("expires-during-resolver", False), ("minted-during-resolver", True)):
            with self.subTest(name=name):
                self.publish_required()
                current = [NOW]
                calls: list[object] = []

                def timed(ref: object) -> dict[str, object]:
                    calls.append(ref)
                    receipt = self.resolver(ref)
                    current[0] = NOW + timedelta(minutes=2)
                    if name == "minted-during-resolver":
                        receipt["validated_at"] = "2026-09-11T10:01:00Z"
                        receipt["expires_at"] = "2026-09-11T10:03:00Z"
                    return receipt

                with patch.object(context, "_trusted_utc_now", side_effect=lambda: current[0]):
                    report = self.complete(timed)
                self.assertEqual(report["passed"], expected_passed)
                self.assertEqual(calls, ["synthetic-run-01"])
                assurance = report["criteria"]["AC-01"]["independent_validation"]["assurance"]
                self.assertEqual(assurance, "verified" if expected_passed else "unknown")
                self.tearDown()
                self.setUp()

        contract = self.contract()
        second = deepcopy(contract["acceptance_criteria"][0])
        second.update(id="AC-02", criterion="Second synthetic independent check",
                      required_scope={"task_id": "IV-TASK", "criterion_id": "AC-02"})
        contract["acceptance_criteria"].append(second)
        context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
        first_entry = self.evidence_entry("first")
        second_entry = self.evidence_entry("second")
        second_entry["evidence"][0].update(evidence_id="EV-02", scope={"task_id": "IV-TASK", "criterion_id": "AC-02"})
        current = [NOW]
        calls: list[object] = []

        def staggered(ref: object) -> dict[str, object]:
            calls.append(ref)
            receipt = self.resolver(ref)
            if ref == "first":
                receipt.update(criterion_id="AC-01", evidence_digests={
                    "EV-01": "sha256:" + hashlib.sha256(self.content).hexdigest(),
                }, expires_at="2026-09-11T10:00:30Z")
            else:
                current[0] = NOW + timedelta(minutes=1)
                receipt.update(criterion_id="AC-02", validated_at="2026-09-11T10:01:00Z",
                               expires_at="2026-09-11T10:03:00Z", evidence_digests={
                                   "EV-02": "sha256:" + hashlib.sha256(self.content).hexdigest(),
                               })
            return receipt

        with patch.object(context, "_trusted_utc_now", side_effect=lambda: current[0]):
            report = context.gate(
                "IV-TASK", stage="completion", evidence_map={"AC-01": first_entry, "AC-02": second_entry},
                base_dir=self.base, emit=False, independent_validation_required=True,
                validation_resolver=staggered, verifiers={"file": self.file_verifier},
            )
        self.assertFalse(report["passed"])
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(report["criteria"]["AC-01"]["independent_validation"]["assurance"], "unknown")
        self.assertEqual(report["criteria"]["AC-02"]["independent_validation"]["assurance"], "verified")
