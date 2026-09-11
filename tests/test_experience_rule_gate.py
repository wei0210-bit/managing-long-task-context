from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _run_cli(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "context_experience.py"), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout)
    return json.loads(completed.stdout)


def _approved_experience(workspace: Path, store_root: Path, *, revision: int = 1, approve: bool = True, validity_seconds: int = 24 * 60 * 60) -> None:
    original = workspace / "original.txt"
    original.write_text("original evidence\n", encoding="utf-8")
    candidate = workspace / "candidate.json"
    candidate.write_text(json.dumps({
        "schema": 1, "experience_id": "review-originals", "revision": revision,
        "claim": "Read the current original before relying on this rule.",
        "tags": ["verification"], "applicability": ["Local original is available."],
        "exclusions": ["none-known"], "source_refs": [_ref(original)],
        "supersedes": None if revision == 1 else {"experience_id": "review-originals", "revision": revision - 1},
    }), encoding="utf-8")
    _run_cli("init", "--workspace", str(workspace), "--store", str(store_root))
    _run_cli("record", "--workspace", str(workspace), "--store", str(store_root), "--input", str(candidate))
    if not approve:
        return

    now = datetime.now(timezone.utc).replace(microsecond=0)
    proof_refs: dict[str, dict[str, str]] = {}
    for name in ("cross", "counterexample", "effectiveness", "original-pass", "mutated-fail", "restored-pass", "mutation-hit", "representative-run", "non-applicable-run"):
        path = workspace / f"{name}-{revision}.txt"
        path.write_text(f"verified {name}\n", encoding="utf-8")
        proof_refs[name] = _ref(path)
    common = {
        "checker_id": "test-host", "checker_version": "1",
        "validated_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(seconds=validity_seconds)).isoformat().replace("+00:00", "Z"),
    }
    validation_refs = {
        "cross": {**common, "source_refs": [proof_refs["cross"]], "independence_basis": "Separate reviewer."},
        "counterexample": {**common, "source_refs": [proof_refs["counterexample"]], "original_pass_ref": proof_refs["original-pass"], "mutated_fail_ref": proof_refs["mutated-fail"], "restored_pass_ref": proof_refs["restored-pass"], "mutation_hit_ref": proof_refs["mutation-hit"]},
        "effectiveness": {**common, "source_refs": [proof_refs["effectiveness"]], "representative_run_ref": proof_refs["representative-run"], "non_applicable_run_ref": proof_refs["non-applicable-run"]},
    }

    def evidence_checker(record: object, references: dict[str, object]) -> dict[str, object]:
        del record
        source_refs = [reference for group in references.values() for reference in group["source_refs"]]
        return {"status": "pass", "codes": []} if all(Path(reference["path"]).read_text(encoding="utf-8").startswith("verified ") for reference in source_refs) else {"status": "fail", "codes": ["UNVERIFIED"]}

    store = context.bind_experience(workspace, store_root)
    reviewed = store.review("review-originals", revision, validation_refs, evidence_checker=evidence_checker)
    if reviewed["status"] != "pass":
        raise AssertionError(reviewed)
    current = store.get("review-originals", revision)["data"]
    assert isinstance(current, dict)
    grant = workspace / "grant.txt"
    grant.write_text("approved by trusted host\n", encoding="utf-8")
    approval_ref = {
        "workspace_id": current["workspace_id"], "experience_id": "review-originals",
        "revision": revision, "record_digest": current["record_digest"], "source_ref": _ref(grant),
    }
    approved = store.approve(
        "review-originals", revision, approval_ref,
        evidence_checker=evidence_checker,
        approval_checker=lambda record, reference: {"status": "pass", "codes": []} if Path(reference["source_ref"]["path"]).read_text(encoding="utf-8").startswith("approved ") else {"status": "fail", "codes": ["UNAPPROVED"]},
    )
    if approved["status"] != "pass":
        raise AssertionError(approved)


def _contract(workspace: Path, store_root: Path) -> dict[str, object]:
    return {
        "schema": 1, "task_id": "EXPERIENCE-RULE-001", "version": 1,
        "issued_by": "publisher", "issued_at": "2026-09-07T00:00:00Z",
        "authorized_approvers": [], "objective": "Use approved current experience",
        "scope": ["strict rule"], "out_of_scope": [], "constraints": [],
        "acceptance_criteria": [{"id": "AC-01", "criterion": "gate runs", "required_evidence_types": ["test-report"]}],
        "workspace_root": str(workspace), "required_capabilities": ["rule-execution/v1"],
        "rule_execution": {"schema": 1, "rules": [{
            "rule_id": "originals-required",
            "experience_ref": {"experience_id": "review-originals", "revision": 1, "store_root": str(store_root)},
            "severity": "load-bearing", "applies_at": ["handoff"],
            "trigger_id": "controlled-modification", "checker_id": "original-check",
            "checker_version": "1", "observation_source_id": "workspace-observer",
        }]},
    }


def _runtime(evidence: Path, workspace: Path) -> dict[str, object]:
    source_ref = _ref(evidence)

    def observe(task: str, stage: str, source_id: str) -> dict[str, object]:
        del task, stage, source_id
        now = datetime.now(timezone.utc)
        return {"status": "pass", "codes": [], "coverage": "complete", "scope": "controlled modification", "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(), "source_refs": [source_ref], "payload": {"controlled_modification": True}}

    def verify_experience(reference: dict[str, object]) -> dict[str, object]:
        record = context.bind_experience(workspace, Path(str(reference["store_root"]))).get(
            str(reference["experience_id"]), int(reference["revision"]),
        )
        data = record.get("data")
        if not isinstance(data, dict) or not data.get("source_refs"):
            return {"status": "fail", "codes": ["EXPERIENCE_ORIGINAL_MISSING"]}
        original = Path(data["source_refs"][0]["path"])
        return {"status": "pass", "codes": []} if original.read_text(encoding="utf-8") == "original evidence\n" and data.get("claim") == "Read the current original before relying on this rule." else {"status": "fail", "codes": ["EXPERIENCE_SEMANTICS_REJECTED"]}

    return {
        "observe": observe,
        "applies": lambda rule, observation: {"status": "applicable", "codes": [], "source_refs": [source_ref]},
        "check": lambda rule, observation: {"status": "pass", "codes": []} if evidence.read_text(encoding="utf-8") == "checked current original\n" else {"status": "fail", "codes": ["ORIGINAL_UNREAD"]},
        "verify_experience": verify_experience,
    }


class ExperienceRuleGateTests(unittest.TestCase):
    def test_handoff_allows_current_approved_same_workspace_exact_experience_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            store_root = workspace / ".context-experience"
            _approved_experience(workspace, store_root)
            evidence = workspace / "execution.txt"
            evidence.write_text("checked current original\n", encoding="utf-8")
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
            report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime(evidence, workspace))

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["rules"][0]["status"], "pass")

    def test_handoff_blocks_unapproved_cross_workspace_missing_or_expired_experience(self) -> None:
        for invalid in ("unapproved", "cross-workspace", "missing-original", "expired"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                store_root = workspace / ".context-experience"
                if invalid == "unapproved":
                    _approved_experience(workspace, store_root, approve=False)
                elif invalid == "cross-workspace":
                    foreign_workspace = temporary_root / "foreign-workspace"
                    foreign_workspace.mkdir()
                    foreign_store = foreign_workspace / ".context-experience"
                    _approved_experience(foreign_workspace, foreign_store)
                    store_root = foreign_store
                elif invalid == "missing-original":
                    _approved_experience(workspace, store_root)
                    (workspace / "original.txt").unlink()
                else:
                    _approved_experience(workspace, store_root, validity_seconds=1)
                    time.sleep(1.2)
                evidence = workspace / "execution.txt"
                evidence.write_text("checked current original\n", encoding="utf-8")
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
                report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime(evidence, workspace))

            self.assertFalse(report["passed"], report)
            self.assertIn(report["rules"][0]["status"], {"fail", "unknown"})

    def test_next_gate_blocks_disputed_or_superseded_reference_without_deleting_history(self) -> None:
        for change in ("dispute", "revoke", "supersede"):
            with self.subTest(change=change), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                store_root = workspace / ".context-experience"
                _approved_experience(workspace, store_root)
                store = context.bind_experience(workspace, store_root)
                before = store.get("review-originals", 1)["data"]
                assert isinstance(before, dict)
                if change == "dispute":
                    dispute = workspace / "dispute.txt"
                    dispute.write_text("contested original\n", encoding="utf-8")
                    self.assertEqual(store.dispute("review-originals", 1, "contested", _ref(dispute))["status"], "pass")
                elif change == "revoke":
                    revocation = workspace / "revocation.txt"
                    revocation.write_text("revoked by trusted host\n", encoding="utf-8")
                    approval_ref = {
                        "workspace_id": before["workspace_id"], "experience_id": "review-originals",
                        "revision": 1, "record_digest": before["record_digest"], "source_ref": _ref(revocation),
                    }
                    self.assertEqual(store.revoke("review-originals", 1, "revoked", approval_ref, approval_checker=lambda record, reference: {"status": "pass", "codes": []})["status"], "pass")
                else:
                    _approved_experience(workspace, store_root, revision=2)
                evidence = workspace / "execution.txt"
                evidence.write_text("checked current original\n", encoding="utf-8")
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
                report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime(evidence, workspace))
                historical = store.get("review-originals", 1)["data"]

            self.assertFalse(report["passed"], report)
            self.assertEqual(report["rules"][0]["status"], "unknown")
            self.assertIsInstance(historical, dict)
            self.assertEqual(historical["claim"], before["claim"])

    def test_gate_returns_input_changed_when_verify_or_check_changes_experience_material(self) -> None:
        for changed_by in ("verify", "check"):
            with self.subTest(changed_by=changed_by), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                store_root = workspace / ".context-experience"
                _approved_experience(workspace, store_root)
                store = context.bind_experience(workspace, store_root)
                evidence = workspace / "execution.txt"
                evidence.write_text("checked current original\n", encoding="utf-8")
                runtime = _runtime(evidence, workspace)
                if changed_by == "verify":
                    dispute = workspace / "dispute.txt"
                    dispute.write_text("contested original\n", encoding="utf-8")

                    def verify(reference: dict[str, object]) -> dict[str, object]:
                        self.assertEqual(store.dispute("review-originals", 1, "contested", _ref(dispute))["status"], "pass")
                        return {"status": "pass", "codes": []}

                    runtime["verify_experience"] = verify
                else:
                    def check(rule: object, observation: object) -> dict[str, object]:
                        (workspace / "original.txt").write_text("changed after callback\n", encoding="utf-8")
                        return {"status": "pass", "codes": []}

                    runtime["check"] = check
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
                report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

            self.assertFalse(report["passed"], report)
            self.assertEqual(report["rules"][0]["status"], "unknown")
            self.assertEqual(report["rules"][0]["codes"], ["INPUT_CHANGED"])

    def test_verify_experience_cannot_mutate_the_selected_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            store_root = workspace / ".context-experience"
            _approved_experience(workspace, store_root)
            evidence = workspace / "execution.txt"
            evidence.write_text("checked current original\n", encoding="utf-8")
            runtime = _runtime(evidence, workspace)

            def mutate_reference(reference: dict[str, object]) -> dict[str, object]:
                reference["revision"] = 999
                reference["store_root"] = "relative-store"
                return {"status": "pass", "codes": []}

            runtime["verify_experience"] = mutate_reference
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
            report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["rules"][0]["status"], "pass")

    def test_invalid_exceptional_or_timeout_verify_experience_blocks_load_bearing_rule(self) -> None:
        cases = (
            ("none", lambda: None, "CALLBACK_INVALID_RESULT"),
            ("bool", lambda: True, "CALLBACK_INVALID_RESULT"),
            ("missing", lambda: {"status": "pass"}, "CALLBACK_INVALID_RESULT"),
            ("bad-status", lambda: {"status": "not-pass", "codes": []}, "CALLBACK_INVALID_RESULT"),
            ("error", lambda: (_ for _ in ()).throw(RuntimeError("sensitive callback detail")), "CALLBACK_ERROR"),
            ("timeout", lambda: (_ for _ in ()).throw(TimeoutError()), "CALLBACK_TIMEOUT"),
        )
        for name, produce, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                store_root = workspace / ".context-experience"
                _approved_experience(workspace, store_root)
                evidence = workspace / "execution.txt"
                evidence.write_text("checked current original\n", encoding="utf-8")
                runtime = _runtime(evidence, workspace)
                runtime["verify_experience"] = lambda reference: produce()
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
                report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

            self.assertFalse(report["passed"], report)
            self.assertEqual(report["rules"][0]["codes"], [expected_code])
            self.assertNotIn("sensitive callback detail", str(report))

    def test_symlink_or_relative_store_reference_is_normalized_to_blocking_unknown(self) -> None:
        for kind in ("symlink", "relative"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                store_root = workspace / ".context-experience"
                _approved_experience(workspace, store_root)
                if kind == "symlink":
                    referenced_store = workspace / "store-link"
                    referenced_store.symlink_to(store_root.name)
                else:
                    referenced_store = Path(".context-experience")
                evidence = workspace / "execution.txt"
                evidence.write_text("checked current original\n", encoding="utf-8")
                contract = _contract(workspace, store_root)
                contract["rule_execution"]["rules"][0]["experience_ref"]["store_root"] = str(referenced_store)
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(contract, confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
                report = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime(evidence, workspace))

            self.assertFalse(report["passed"], report)
            self.assertEqual(report["rules"][0]["status"], "unknown")
            self.assertEqual(report["rules"][0]["codes"], ["EXPERIENCE_REFERENCE_UNAVAILABLE"])

    def test_selected_experience_rule_ands_with_existing_gate_and_disabled_contract_keeps_legacy_path(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            store_root = workspace / ".context-experience"
            _approved_experience(workspace, store_root)
            evidence = workspace / "execution.txt"
            evidence.write_text("checked current original\n", encoding="utf-8")
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace, store_root), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("EXPERIENCE-RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
            runtime = _runtime(evidence, workspace)
            runtime["check"] = lambda rule, observation: {"status": "fail", "codes": ["RULE_FAILED"]}
            blocked = context.gate("EXPERIENCE-RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

            legacy = _contract(workspace, store_root)
            legacy.pop("rule_execution")
            legacy.pop("required_capabilities")
            legacy["task_id"] = "LEGACY-001"
            context.publish_contract(legacy, confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("LEGACY-001", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)
            legacy_report = context.gate("LEGACY-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime={"observe": lambda *args: (_ for _ in ()).throw(AssertionError("must not run"))})

        self.assertFalse(blocked["passed"], blocked)
        self.assertTrue(legacy_report["passed"], legacy_report)
        self.assertNotIn("rules", legacy_report)


if __name__ == "__main__":
    unittest.main()
