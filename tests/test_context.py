from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


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
        self.assertTrue(any("seal is invalid" in error for error in result["errors"]))

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
        self.publish()
        incomplete = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "result": "pass",
                    "evidence": ["test:run-01"],
                    "evidence_types": ["integration-test"],
                    "covered_hops": ["entry", "write"],
                }
            },
            base_dir=self.base,
            emit=False,
        )
        self.assertFalse(incomplete["passed"])
        complete = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "result": "pass",
                    "evidence": ["test:run-01"],
                    "evidence_types": ["integration-test"],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            base_dir=self.base,
            emit=False,
        )
        self.assertTrue(complete["passed"], complete["errors"])

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
