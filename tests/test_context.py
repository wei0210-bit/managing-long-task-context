from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context
from managing_long_task_context.evidence import canonical_json_bytes


NOW = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)


def passing_verifier(evidence, criterion, resolution):
    return {"status": "pass", "codes": []}


def passing_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "pass", "codes": []},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
    }


def permission_denied_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "unknown", "codes": ["PERMISSION_DENIED"]},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
    }


class ContextSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.contract = {
            "schema": 1,
            "task_id": "TASK-001",
            "version": 1,
            "issued_by": "publisher",
            "issued_at": "2026-08-26T09:00:00+00:00",
            "authorized_approvers": [],
            "objective": "Fix duplicate charges",
            "scope": ["payment callback"],
            "out_of_scope": [],
            "constraints": ["keep public API"],
            "acceptance_criteria": [
                {
                    "id": "AC-01",
                    "criterion": "Duplicate callback creates one charge",
                    "required_evidence": ["integration-test"],
                    "chain_hops": ["entry", "guard", "write"],
                }
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def publish(self) -> dict:
        return context.publish_contract(self.contract, confirmed_by="publisher", base_dir=self.base)

    def completion_file_report(self, timestamp_fields: dict) -> dict:
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        content = b"timestamp completion evidence\n"
        (workspace / "completion.txt").write_bytes(content)
        self.contract["workspace_root"] = str(workspace)
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["file"]
        criterion["required_scope"] = {"task_id": "TASK-001", "criterion_id": "AC-01"}
        criterion["max_evidence_age_seconds"] = 3600
        self.publish()
        evidence = {
            "evidence_id": "EV-TIMESTAMP",
            "kind": "file",
            "locator": "completion.txt",
            "artifact_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "scope": {"task_id": "TASK-001", "criterion_id": "AC-01"},
            **timestamp_fields,
        }
        return context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [evidence],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

    def test_contract_requires_publisher_written_acceptance_criteria(self) -> None:
        bad = dict(self.contract)
        bad["acceptance_criteria"] = []
        with self.assertRaises(context.ContextError):
            context.publish_contract(bad, confirmed_by="publisher", base_dir=self.base)

    def test_contract_change_breaks_release_gate(self) -> None:
        self.publish()
        path = self.base / "TASK-001" / "task-contract.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["objective"] = "Silently changed"
        path.write_text(json.dumps(stored), encoding="utf-8")
        result = context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)
        self.assertFalse(result["passed"])
        self.assertTrue(any("integrity digest is invalid" in error for error in result["errors"]))

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

    def test_release_gate_rejects_legacy_digest_even_when_integrity_digest_is_recomputed(self) -> None:
        self.publish()
        path = self.base / "TASK-001" / "task-contract.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["seal"]["digest"] = "legacy-format"
        digest_input = json.loads(json.dumps(stored))
        digest_input["seal"].pop("integrity_digest")
        stored["seal"]["integrity_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(digest_input)).hexdigest()
        )
        path.write_text(json.dumps(stored), encoding="utf-8")

        report = context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)

        self.assertFalse(report["passed"])
        self.assertIn(
            "contract.seal.digest is unsupported; use contract.seal.integrity_digest",
            report["errors"],
        )

    def test_verified_fact_requires_evidence_scope_and_method(self) -> None:
        self.publish()
        with self.assertRaises(context.ContextError):
            context.record(
                "TASK-001",
                statement="Database has a unique index",
                item_type="verified-fact",
                actor="executor",
                source={"kind": "tool", "ref": "schema-query"},
                base_dir=self.base,
            )

    def test_verified_fact_update_preserves_explicit_conflicted_status(self) -> None:
        self.publish()
        fact = context.record(
            "TASK-001",
            statement="Callback writes exactly once",
            item_type="verified-fact",
            actor="validator-01",
            source={"kind": "test-report", "ref": "artifacts/run-018.json"},
            evidence=["artifacts/run-018.json"],
            verification_method="integration test inspection",
            scope={"module": "payment-callback"},
            base_dir=self.base,
        )

        conflicted = context.update_item(
            "TASK-001",
            fact["id"],
            actor="validator-02",
            status="conflicted",
            conflicts_with=["EV-019"],
            conflict_reason="A second report observed two writes",
            base_dir=self.base,
        )

        self.assertEqual(conflicted["status"], "conflicted")
        self.assertEqual(conflicted["conflicts_with"], ["EV-019"])
        self.assertEqual(conflicted["conflict_reason"], "A second report observed two writes")
        self.assertIsNotNone(conflicted["verified_at"])

    def test_assumption_requires_explicit_verification_to_become_fact(self) -> None:
        self.publish()
        item = context.record(
            "TASK-001",
            statement="Database may lack idempotency",
            item_type="assumption",
            actor="executor",
            source={"kind": "agent-inference", "ref": "review-01"},
            scope={"module": "payment"},
            base_dir=self.base,
        )
        with self.assertRaises(context.ContextError):
            context.update_item(
                "TASK-001",
                item["id"],
                actor="verifier",
                promote_to="verified-fact",
                base_dir=self.base,
            )
        with self.assertRaises(context.ContextError):
            context.update_item(
                "TASK-001",
                item["id"],
                actor="verifier",
                promote_to="verified-fact",
                evidence=["db:schema-query-02"],
                verification_method="direct schema inspection",
                scope={"database": "payments-v2"},
                base_dir=self.base,
            )
        verified = context.update_item(
            "TASK-001",
            item["id"],
            actor="verifier",
            promote_to="verified-fact",
            source={"kind": "tool", "ref": "schema-query-02"},
            evidence=["db:schema-query-02"],
            verification_method="direct schema inspection",
            scope={"database": "payments-v2"},
            base_dir=self.base,
        )
        self.assertEqual(verified["type"], "verified-fact")
        self.assertEqual(verified["status"], "active")

    def test_brief_excludes_superseded_items_and_keeps_evidence(self) -> None:
        self.publish()
        old = context.record(
            "TASK-001",
            statement="No unique index",
            item_type="assumption",
            actor="executor",
            source={"kind": "agent-inference", "ref": "review"},
            scope={"database": "payments"},
            base_dir=self.base,
        )
        new = context.record(
            "TASK-001",
            statement="Unique index exists",
            item_type="verified-fact",
            actor="verifier",
            source={"kind": "tool", "ref": "schema-query"},
            evidence=["db:schema-query-02"],
            verification_method="direct schema inspection",
            scope={"database": "payments"},
            supersedes=old["id"],
            base_dir=self.base,
        )
        packet = context.brief("TASK-001", base_dir=self.base)
        ids = {item["id"] for item in packet["facts"] + packet["assumptions"]}
        self.assertIn(new["id"], ids)
        self.assertNotIn(old["id"], ids)
        self.assertIn("db:schema-query-02", packet["facts"][0]["evidence"])

    def test_markdown_brief_keeps_item_control_fields(self) -> None:
        self.publish()
        fact = context.record(
            "TASK-001",
            statement="Unique index exists",
            item_type="verified-fact",
            actor="validator-01",
            source={"kind": "tool", "ref": "schema-query-02"},
            evidence=["db:schema-query-02"],
            verification_method="direct schema inspection",
            scope={"database": "payments"},
            base_dir=self.base,
        )

        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        self.assertIn(f"- {fact['id']}: Unique index exists", prompt)
        self.assertIn("status=active", prompt)
        self.assertIn('source={"kind":"tool","ref":"schema-query-02"}', prompt)
        self.assertIn('evidence=["db:schema-query-02"]', prompt)
        self.assertIn('scope={"database":"payments"}', prompt)
        self.assertIn(f"verified_at={fact['verified_at']}", prompt)
        self.assertIn(f"updated_at={fact['updated_at']}", prompt)

    def test_markdown_brief_keeps_conflict_and_priority_controls(self) -> None:
        self.publish()
        item = context.record(
            "TASK-001",
            statement="Probe results disagree",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-02"},
            metadata={"required": True, "blocker": True, "severity": "critical"},
            base_dir=self.base,
        )
        conflicted = context.update_item(
            "TASK-001",
            item["id"],
            actor="validator-01",
            status="conflicted",
            conflicts_with=["EV-019"],
            conflict_reason="A second report observed two writes",
            base_dir=self.base,
        )

        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        self.assertIn(f"- {conflicted['id']}: Probe results disagree", prompt)
        self.assertIn('conflicts_with=["EV-019"]', prompt)
        self.assertIn('conflict_reason="A second report observed two writes"', prompt)
        self.assertIn('metadata={"blocker":true,"required":true,"severity":"critical"}', prompt)

    def test_markdown_brief_keeps_acceptance_evidence_and_hops(self) -> None:
        self.publish()

        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        self.assertIn(
            '- AC-01: Duplicate callback creates one charge | '
            'required_evidence=["integration-test"] | '
            'chain_hops=["entry","guard","write"]',
            prompt,
        )

    def test_markdown_brief_keeps_contract_scope_and_constraints(self) -> None:
        self.publish()

        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        self.assertIn("## Scope", prompt)
        self.assertIn("- payment callback", prompt)
        self.assertIn("## Out of Scope", prompt)
        self.assertIn("## Constraints", prompt)
        self.assertIn("- keep public API", prompt)

    def test_brief_budget_prefers_required_conflict_and_decision(self) -> None:
        self.publish()
        assumption = context.record(
            "TASK-001",
            statement="A" * 900,
            item_type="assumption",
            actor="executor",
            source={"kind": "agent-inference", "ref": "review-01"},
            base_dir=self.base,
        )
        decision = context.record(
            "TASK-001",
            statement="D" * 900,
            item_type="decision",
            actor="publisher",
            source={"kind": "task-contract", "ref": "decision-01"},
            metadata={"severity": "high"},
            base_dir=self.base,
        )
        required = context.record(
            "TASK-001",
            statement="R" * 900,
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-01"},
            metadata={"required": True, "severity": "critical"},
            base_dir=self.base,
        )
        conflict_candidate = context.record(
            "TASK-001",
            statement="C" * 900,
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-02"},
            base_dir=self.base,
        )
        conflicted = context.update_item(
            "TASK-001",
            conflict_candidate["id"],
            actor="validator-01",
            status="conflicted",
            conflicts_with=[required["id"]],
            conflict_reason="Probe results disagree",
            base_dir=self.base,
        )

        packet = context.brief("TASK-001", max_chars=5600, base_dir=self.base)
        selected_ids = {
            item["id"]
            for key in ("facts", "observations", "assumptions", "decisions", "questions")
            for item in packet[key]
        }

        self.assertIn(required["id"], selected_ids)
        self.assertIn(conflicted["id"], selected_ids)
        self.assertIn(decision["id"], selected_ids)
        self.assertNotIn(assumption["id"], selected_ids)
        self.assertLessEqual(len(packet["prompt"]), 5600)

    def test_brief_max_items_caps_candidates_before_character_budget(self) -> None:
        self.publish()
        context.record(
            "TASK-001",
            statement="B" * 5000,
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "oversized-blocker"},
            metadata={"blocker": True},
            base_dir=self.base,
        )
        decision = context.record(
            "TASK-001",
            statement="Short decision",
            item_type="decision",
            actor="publisher",
            source={"kind": "task-contract", "ref": "short-decision"},
            base_dir=self.base,
        )

        packet = context.brief("TASK-001", max_chars=3000, max_items=1, base_dir=self.base)
        selected_ids = {
            item["id"]
            for key in ("facts", "observations", "assumptions", "decisions", "questions")
            for item in packet[key]
        }

        self.assertNotIn(decision["id"], selected_ids)

    def test_brief_rejects_required_items_that_exceed_budget(self) -> None:
        self.publish()
        context.record(
            "TASK-001",
            statement="R" * 9000,
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-oversized"},
            metadata={"required": True},
            base_dir=self.base,
        )

        with self.assertRaisesRegex(context.ContextError, "BRIEF_REQUIRED_OVERFLOW"):
            context.brief("TASK-001", max_chars=8000, base_dir=self.base)

    def test_brief_rejects_non_positive_character_budget(self) -> None:
        self.publish()
        with self.assertRaisesRegex(ValueError, "max_chars must be positive"):
            context.brief("TASK-001", max_chars=0, base_dir=self.base)

    def test_handoff_requires_checkpoint(self) -> None:
        self.publish()
        before = context.gate("TASK-001", stage="handoff", base_dir=self.base, emit=False)
        self.assertFalse(before["passed"])
        context.checkpoint(
            "TASK-001",
            phase="analysis",
            completed=["reproduced"],
            evidence_added=["test:run-01"],
            next_action="inspect retry path",
            actor="executor",
            base_dir=self.base,
        )
        after = context.gate("TASK-001", stage="handoff", base_dir=self.base, emit=False)
        self.assertTrue(after["passed"], after["errors"])

    def test_completion_requires_evidence_types_and_chain_hops(self) -> None:
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        content = b"completion evidence\n"
        (workspace / "completion.txt").write_bytes(content)
        self.contract["workspace_root"] = str(workspace)
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["file"]
        criterion["required_scope"] = {"task_id": "TASK-001", "criterion_id": "AC-01"}
        criterion["max_evidence_age_seconds"] = 3600
        self.publish()
        evidence = {
            "evidence_id": "EV-AC-01",
            "kind": "file",
            "locator": "completion.txt",
            "artifact_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-001", "criterion_id": "AC-01"},
        }
        malformed = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "result": "pass",
                    "evidence": ["test:run-01"],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        self.assertFalse(malformed["passed"])
        self.assertEqual(
            malformed["criteria"]["AC-01"]["evidence_results"][0]["checks"]["resolve"],
            {"status": "fail", "codes": ["MALFORMED_EVIDENCE"]},
        )
        incomplete = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [evidence],
                    "covered_hops": ["entry", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        self.assertFalse(incomplete["passed"])
        self.assertEqual(incomplete["criteria"]["AC-01"]["missing_hops"], ["guard"])
        complete = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [evidence],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        self.assertTrue(complete["passed"], complete["errors"])
        checks = complete["criteria"]["AC-01"]["evidence_results"][0]["checks"]
        self.assertEqual(checks["integrity_and_freshness"], {"status": "pass", "codes": []})
        self.assertEqual(checks["scope"], {"status": "pass", "codes": []})

    def test_completion_gate_accepts_criterion_owner_pass(self) -> None:
        self.publish()
        owner_report = {
            "status": "pass",
            "evidence_results": [],
            "missing_evidence_types": [],
            "missing_hops": [],
            "missing_delivery_types": [],
        }

        production_owner = context._evaluate_completion_criterion

        def owner_for_real_criterion(criterion, *args, **kwargs):
            if criterion["id"] == "AC-01":
                return owner_report
            return production_owner(criterion, *args, **kwargs)

        with patch.object(
            context,
            "_evaluate_completion_criterion",
            side_effect=owner_for_real_criterion,
        ):
            report = context.gate(
                "TASK-001",
                stage="completion",
                evidence_map={"AC-01": {}},
                base_dir=self.base,
                emit=False,
            )

        self.assertTrue(report["passed"], report["errors"])

    def test_completion_gate_rejects_criterion_owner_fail(self) -> None:
        self.publish()
        owner_report = {
            "status": "fail",
            "evidence_results": [],
            "missing_evidence_types": [],
            "missing_hops": [],
            "missing_delivery_types": [],
        }

        with patch.object(context, "_evaluate_completion_criterion", return_value=owner_report):
            report = context.gate(
                "TASK-001",
                stage="completion",
                evidence_map={"AC-01": {"evidence": [{"evidence_id": "EV-PATCH"}]}},
                base_dir=self.base,
                emit=False,
            )

        self.assertFalse(report["passed"])
        self.assertIn("criterion AC-01 status is fail", report["errors"])

    def test_completion_gate_rejects_criterion_owner_unknown(self) -> None:
        self.publish()
        owner_report = {
            "status": "unknown",
            "evidence_results": [],
            "missing_evidence_types": [],
            "missing_hops": [],
            "missing_delivery_types": [],
        }

        with patch.object(context, "_evaluate_completion_criterion", return_value=owner_report):
            report = context.gate(
                "TASK-001",
                stage="completion",
                evidence_map={"AC-01": {"evidence": [{"evidence_id": "EV-PATCH"}]}},
                base_dir=self.base,
                emit=False,
            )

        self.assertFalse(report["passed"])
        self.assertIn("criterion AC-01 status is unknown", report["errors"])

    def test_completion_rejects_missing_generated_at_when_freshness_required(self) -> None:
        report = self.completion_file_report({})

        self.assertFalse(report["passed"])
        result = report["criteria"]["AC-01"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["evidence_results"][0]["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["MISSING_GENERATED_AT"]},
        )

    def test_completion_rejects_invalid_generated_at_when_freshness_required(self) -> None:
        report = self.completion_file_report({"generated_at": "not-a-time"})

        self.assertFalse(report["passed"])
        result = report["criteria"]["AC-01"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["evidence_results"][0]["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["INVALID_GENERATED_AT"]},
        )

    def test_completion_rejects_invalid_expires_at(self) -> None:
        report = self.completion_file_report(
            {"generated_at": "2026-08-27T04:30:00Z", "expires_at": "not-a-time"}
        )

        self.assertFalse(report["passed"])
        result = report["criteria"]["AC-01"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["evidence_results"][0]["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["INVALID_EXPIRES_AT"]},
        )

    def test_completion_re_resolves_deleted_evidence(self) -> None:
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        artifact = workspace / "completion.txt"
        content = b"fresh completion evidence\n"
        artifact.write_bytes(content)
        self.contract["workspace_root"] = str(workspace)
        criterion = self.contract["acceptance_criteria"][0]
        criterion.pop("required_evidence")
        criterion["required_evidence_types"] = ["file"]
        self.publish()
        evidence = {
            "evidence_id": "EV-DELETION",
            "kind": "file",
            "locator": "completion.txt",
            "artifact_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-001", "criterion_id": "AC-01"},
            "resolver_status": "pass",
        }
        entry = {
            "result": "pass",
            "evidence": [evidence],
            "covered_hops": ["entry", "guard", "write"],
        }

        before = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": entry},
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        self.assertTrue(before["passed"], before["errors"])

        artifact.unlink()
        after = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": entry},
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

        self.assertTrue(before["passed"])
        self.assertFalse(after["passed"])
        result = after["criteria"]["AC-01"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["evidence_results"][0]["checks"]["resolve"],
            {"status": "fail", "codes": ["NOT_FOUND"]},
        )
        self.assertTrue(any("AC-01" in error and "EV-DELETION" in error for error in after["errors"]))

    def test_completion_rejects_unknown_required_evidence(self) -> None:
        self.contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
        self.publish()
        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "result": "pass",
                    "evidence": [
                        {
                            "evidence_id": "EV-UNKNOWN",
                            "kind": "custom",
                            "resolver_status": "pass",
                        }
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            resolvers={"custom": permission_denied_resolver},
            verifiers={"custom": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        result = report["criteria"]["AC-01"]
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["missing_evidence_types"], [])
        self.assertEqual(
            result["evidence_results"][0]["checks"]["resolve"],
            {"status": "unknown", "codes": ["PERMISSION_DENIED"]},
        )
        self.assertTrue(any("AC-01" in error and "EV-UNKNOWN" in error for error in report["errors"]))

    def test_completion_rejects_stale_and_scope_mismatched_evidence(self) -> None:
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        content = b"scope and freshness evidence\n"
        (workspace / "completion.txt").write_bytes(content)
        self.contract["workspace_root"] = str(workspace)
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["file"]
        criterion["required_scope"] = {"task_id": "TASK-001", "criterion_id": "AC-01"}
        criterion["max_evidence_age_seconds"] = 3600
        self.publish()
        common = {
            "kind": "file",
            "locator": "completion.txt",
            "artifact_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        }

        stale = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [
                        dict(
                            common,
                            evidence_id="EV-STALE",
                            generated_at="2026-08-27T03:00:00Z",
                            scope={"task_id": "TASK-001", "criterion_id": "AC-01"},
                        )
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        mismatched = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [
                        dict(
                            common,
                            evidence_id="EV-SCOPE",
                            generated_at="2026-08-27T04:30:00Z",
                            scope={"task_id": "TASK-001"},
                        )
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(stale["passed"])
        self.assertEqual(stale["criteria"]["AC-01"]["status"], "fail")
        self.assertEqual(
            stale["criteria"]["AC-01"]["evidence_results"][0]["checks"][
                "integrity_and_freshness"
            ],
            {"status": "fail", "codes": ["STALE"]},
        )
        self.assertFalse(mismatched["passed"])
        self.assertEqual(mismatched["criteria"]["AC-01"]["status"], "fail")
        self.assertEqual(
            mismatched["criteria"]["AC-01"]["evidence_results"][0]["checks"]["scope"],
            {"status": "fail", "codes": ["SCOPE_MISMATCH"]},
        )

    def test_completion_requires_delivery_receipt(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["file"]
        criterion["required_delivery_types"] = ["feishu"]
        self.publish()
        evidence = {"evidence_id": "EV-FILE", "kind": "file"}
        entry = {
            "evidence": [evidence],
            "covered_hops": ["entry", "guard", "write"],
        }
        dependencies = {
            "resolvers": {"file": passing_resolver, "delivery-receipt": passing_resolver},
            "verifiers": {"file": passing_verifier, "delivery-receipt": passing_verifier},
        }

        missing = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": entry},
            now=NOW,
            base_dir=self.base,
            emit=False,
            **dependencies,
        )
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["criteria"]["AC-01"]["missing_delivery_types"], ["feishu"])

        verified_entry = dict(
            entry,
            delivery_receipts=[
                {
                    "evidence_id": "EV-RECEIPT",
                    "kind": "delivery-receipt",
                    "delivery_type": "feishu",
                }
            ],
        )
        unverified = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": verified_entry},
            resolvers=dependencies["resolvers"],
            verifiers={"file": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )
        self.assertFalse(unverified["passed"])
        unverified_result = unverified["criteria"]["AC-01"]
        self.assertEqual(unverified_result["missing_delivery_types"], ["feishu"])
        self.assertEqual(unverified_result["evidence_results"][1]["status"], "unknown")

        verified = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": verified_entry},
            now=NOW,
            base_dir=self.base,
            emit=False,
            **dependencies,
        )
        self.assertTrue(verified["passed"], verified["errors"])
        self.assertEqual(verified["criteria"]["AC-01"]["missing_delivery_types"], [])

    def test_completion_requires_list_evidence_container(self) -> None:
        self.contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
        self.publish()
        dependencies = {
            "resolvers": {"custom": passing_resolver},
            "verifiers": {"custom": passing_verifier},
        }

        for evidence_value in (
            {"evidence_id": "EV-SINGLETON", "kind": "custom"},
            "custom:pointer",
        ):
            with self.subTest(evidence=evidence_value):
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": evidence_value,
                            "covered_hops": ["entry", "guard", "write"],
                        }
                    },
                    now=NOW,
                    base_dir=self.base,
                    emit=False,
                    **dependencies,
                )

                self.assertFalse(report["passed"])
                result = report["criteria"]["AC-01"]
                self.assertEqual(result["status"], "fail")
                self.assertEqual(
                    result["evidence_results"][0]["checks"]["resolve"],
                    {"status": "fail", "codes": ["MALFORMED_EVIDENCE"]},
                )

    def test_completion_requires_list_delivery_receipts_container(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["required_delivery_types"] = ["feishu"]
        self.publish()
        dependencies = {
            "resolvers": {"custom": passing_resolver, "delivery-receipt": passing_resolver},
            "verifiers": {"custom": passing_verifier, "delivery-receipt": passing_verifier},
        }

        for receipt_value in (
            {
                "evidence_id": "EV-RECEIPT-SINGLETON",
                "kind": "delivery-receipt",
                "delivery_type": "feishu",
            },
            "receipt:pointer",
        ):
            with self.subTest(receipt=receipt_value):
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [{"evidence_id": "EV-CUSTOM", "kind": "custom"}],
                            "covered_hops": ["entry", "guard", "write"],
                            "delivery_receipts": receipt_value,
                        }
                    },
                    now=NOW,
                    base_dir=self.base,
                    emit=False,
                    **dependencies,
                )

                self.assertFalse(report["passed"])
                result = report["criteria"]["AC-01"]
                self.assertEqual(result["status"], "fail")
                self.assertEqual(
                    result["evidence_results"][1]["checks"]["resolve"],
                    {"status": "fail", "codes": ["MALFORMED_EVIDENCE"]},
                )
                self.assertEqual(result["missing_delivery_types"], ["feishu"])

    def test_completion_rejects_invalid_delivery_receipt_fields(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["required_delivery_types"] = ["feishu"]
        self.publish()
        dependencies = {
            "resolvers": {
                "custom": passing_resolver,
                "wrong-receipt-kind": passing_resolver,
                "delivery-receipt": passing_resolver,
            },
            "verifiers": {
                "custom": passing_verifier,
                "wrong-receipt-kind": passing_verifier,
                "delivery-receipt": passing_verifier,
            },
        }

        for receipt in (
            {
                "evidence_id": "EV-WRONG-KIND",
                "kind": "wrong-receipt-kind",
                "delivery_type": "feishu",
            },
            {"evidence_id": "EV-NO-DELIVERY-TYPE", "kind": "delivery-receipt"},
        ):
            with self.subTest(receipt=receipt):
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [{"evidence_id": "EV-CUSTOM", "kind": "custom"}],
                            "covered_hops": ["entry", "guard", "write"],
                            "delivery_receipts": [receipt],
                        }
                    },
                    now=NOW,
                    base_dir=self.base,
                    emit=False,
                    **dependencies,
                )

                self.assertFalse(report["passed"])
                result = report["criteria"]["AC-01"]
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["missing_delivery_types"], ["feishu"])

    def test_completion_keeps_conflicted_items_blocking(self) -> None:
        self.contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
        self.publish()
        item = context.record(
            "TASK-001",
            statement="Observed completion state is disputed",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-01"},
            base_dir=self.base,
        )
        context.update_item(
            "TASK-001",
            item["id"],
            actor="validator",
            status="conflicted",
            conflicts_with=["EV-OTHER"],
            conflict_reason="Independent probe disagrees",
            base_dir=self.base,
        )

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [{"evidence_id": "EV-COMPLETE", "kind": "custom"}],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            now=NOW,
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertIn(f"required context item is conflicted: {item['id']}", report["errors"])
        self.assertEqual(report["criteria"]["AC-01"]["status"], "pass")

    def test_audit_self_probe_and_counts_are_explicit(self) -> None:
        self.publish()
        context.record(
            "TASK-001",
            statement="Observed duplicate callback",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "log-query-01"},
            base_dir=self.base,
        )
        report = context.audit("TASK-001", base_dir=self.base, emit=False)
        self.assertEqual(report["stats"]["probe"], "pass")
        self.assertEqual(report["stats"]["checked"], 1)
        self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
        self.assertEqual(report["stats"]["probe_scanned"], 1)
        self.assertEqual(report["stats"]["probes_checked"], 1)
        self.assertEqual(report["stats"]["contracts_checked"], 1)
        self.assertEqual(report["stats"]["items_checked"], 1)
        self.assertGreaterEqual(report["stats"]["events_checked"], 2)

    def test_audit_probe_does_not_mutate_real_ledger(self) -> None:
        self.publish()
        context.record(
            "TASK-001",
            statement="Observed duplicate callback",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "log-query-01"},
            base_dir=self.base,
        )
        task_dir = self.base / "TASK-001"
        before = {
            name: (task_dir / name).read_bytes()
            for name in ("task-contract.json", "events.jsonl", "snapshot.json")
        }

        context.audit("TASK-001", base_dir=self.base, emit=False)

        after = {
            name: (task_dir / name).read_bytes()
            for name in ("task-contract.json", "events.jsonl", "snapshot.json")
        }
        self.assertEqual(after, before)

    def test_audit_fails_when_bad_sample_is_not_rejected(self) -> None:
        self.publish()
        owner_report = {
            "status": "pass",
            "evidence_results": [],
            "missing_evidence_types": [],
            "missing_hops": [],
            "missing_delivery_types": [],
        }

        with patch(
            "managing_long_task_context._evaluate_completion_criterion",
            return_value=owner_report,
        ):
            report = context.audit("TASK-001", base_dir=self.base, emit=False)

        self.assertFalse(report["passed"])
        self.assertEqual(report["stats"]["probe"], "fail")
        self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
        self.assertTrue(
            any("PROBE-COMPLETION-EMPTY-EVIDENCE" in error for error in report["errors"])
        )

    def test_audit_rejects_external_probe_bypass(self) -> None:
        self.publish()

        report = context.audit(
            "TASK-001",
            base_dir=self.base,
            emit=False,
            _run_probe=False,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["stats"]["probe"], "fail")
        self.assertEqual(report["stats"]["probe_scanned"], 0)
        self.assertEqual(report["stats"]["probes_checked"], 0)
        self.assertIn("external callers cannot skip the audit bad-sample probe", report["errors"])

    def test_gate_rejects_external_probe_bypass(self) -> None:
        self.publish()

        report = context.gate(
            "TASK-001",
            stage="release",
            base_dir=self.base,
            emit=False,
            _run_probe=False,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["stats"]["probe"], "fail")
        self.assertEqual(report["stats"]["probe_scanned"], 0)
        self.assertEqual(report["stats"]["probes_checked"], 0)
        self.assertIn("external callers cannot skip the audit bad-sample probe", report["errors"])

    def test_pointer_freshness_audit_detects_stale_target(self) -> None:
        self.publish()
        docs = Path(self.temp.name) / "docs"
        docs.mkdir()
        target = docs / "DETAILS.md"
        source = docs / "MAIN.md"
        target.write_text("old", encoding="utf-8")
        source.write_text("详见 `DETAILS.md`", encoding="utf-8")
        target_time = target.stat().st_mtime - 10
        import os

        os.utime(target, (target_time, target_time))
        report = context.audit(
            "TASK-001",
            documents=[source],
            max_pointer_lag_seconds=1,
            base_dir=self.base,
            emit=False,
        )
        self.assertTrue(any("stale pointer target" in warning for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
