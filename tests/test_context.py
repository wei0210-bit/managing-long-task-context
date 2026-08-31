from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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


def valid_delivery_receipt(evidence_id="EV-RECEIPT", **overrides):
    value = {
        "evidence_id": evidence_id,
        "kind": "delivery-receipt",
        "delivery_type": "feishu",
        "channel": "feishu",
        "target_id": "chat-01",
        "artifact_ref": "EV-FILE",
        "external_id": "message-01",
        "sent_at": "2026-08-27T04:31:00Z",
        "observed_at": "2026-08-27T04:32:00Z",
        "verification_method": "read-back",
    }
    value.update(overrides)
    return value


class ContextSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.clock = patch.object(context, "_trusted_utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
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

    def test_public_gate_rejects_caller_supplied_now(self):
        self.publish()
        self.assertNotIn("now", inspect.signature(context.gate).parameters)
        with self.assertRaises(TypeError):
            context.gate("TASK-001", stage="release", now=NOW, base_dir=self.base, emit=False)

    def test_public_gate_observes_trusted_utc_once_including_audit_probe(self):
        self.publish()
        with patch.object(
            context,
            "_trusted_utc_now",
            side_effect=[NOW, NOW + timedelta(seconds=1)],
        ) as clock:
            report = context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)

        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(clock.call_count, 1)

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
            "covered_hops": ["entry", "guard", "write"],
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
            base_dir=self.base,
            emit=False,
        )

    def test_contract_requires_publisher_written_acceptance_criteria(self) -> None:
        bad = dict(self.contract)
        bad["acceptance_criteria"] = []
        with self.assertRaises(context.ContextError):
            context.publish_contract(bad, confirmed_by="publisher", base_dir=self.base)

    def test_publish_rejects_malformed_authorized_approvers(self) -> None:
        bad = deepcopy(self.contract)
        bad["task_id"] = "TASK-MALFORMED-APPROVERS"
        bad["authorized_approvers"] = "attacker"

        with self.assertRaisesRegex(context.ContextError, "authorized_approvers"):
            context.publish_contract(bad, confirmed_by="a", base_dir=self.base)

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

    def test_brief_diagnostics_reports_ready_budget_and_advisory_token_range(self) -> None:
        self.publish()
        item = context.record(
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

        diagnostics = context.brief_diagnostics("TASK-001", base_dir=self.base)
        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        self.assertEqual(diagnostics["status"], "ready")
        self.assertIsNone(diagnostics["overflow"])
        self.assertEqual(diagnostics["budget"]["max_chars"], 8000)
        self.assertEqual(diagnostics["budget"]["prompt_chars"], len(prompt))
        self.assertEqual(
            diagnostics["budget"]["selection_wrapper_chars"]
            + diagnostics["budget"]["prompt_adjustment_chars"],
            diagnostics["budget"]["fixed_prompt_chars"],
        )
        self.assertEqual(
            diagnostics["budget"]["item_contribution_chars"],
            len(prompt) - diagnostics["budget"]["fixed_prompt_chars"],
        )
        self.assertEqual(
            diagnostics["budget"]["prompt_adjustment_chars"]
            + diagnostics["budget"]["selection_prompt_chars"],
            len(prompt),
        )
        self.assertLessEqual(
            diagnostics["budget"]["fixed_prompt_chars"],
            diagnostics["budget"]["prompt_chars"],
        )
        self.assertEqual(diagnostics["items"]["candidate_count"], 1)
        self.assertEqual(diagnostics["items"]["selected_count"], 1)
        self.assertEqual(diagnostics["items"]["selected_ids"], [item["id"]])
        self.assertEqual(diagnostics["items"]["omitted_count"], 0)
        text = diagnostics["text"]
        self.assertEqual(
            text["ascii_chars"] + text["cjk_chars"] + text["other_chars"],
            len(prompt),
        )
        estimate = diagnostics["token_estimate"]
        self.assertTrue(estimate["advisory"])
        self.assertEqual(estimate["method"], "portable-heuristic-v1")
        self.assertEqual(estimate["semantics"], "heuristic-not-guaranteed")
        self.assertLessEqual(estimate["range_low"], estimate["range_high"])

    def test_brief_diagnostics_reports_mandatory_overflow_without_hiding_item(self) -> None:
        self.publish()
        required = context.record(
            "TASK-001",
            statement="R" * 9000,
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-oversized"},
            metadata={"required": True},
            base_dir=self.base,
        )

        diagnostics = context.brief_diagnostics("TASK-001", max_chars=8000, base_dir=self.base)

        self.assertEqual(diagnostics["status"], "overflow")
        self.assertEqual(diagnostics["overflow"]["kind"], "mandatory")
        self.assertEqual(diagnostics["overflow"]["code"], "BRIEF_REQUIRED_OVERFLOW")
        self.assertEqual(diagnostics["overflow"]["item_ids"], [required["id"]])
        self.assertEqual(diagnostics["items"]["mandatory_count"], 1)
        self.assertGreater(diagnostics["budget"]["mandatory_prompt_chars"], 8000)
        with self.assertRaisesRegex(
            context.ContextError,
            "BRIEF_REQUIRED_OVERFLOW: mandatory items exceed max_chars",
        ):
            context.brief("TASK-001", max_chars=8000, base_dir=self.base)

    def test_brief_diagnostics_distinguishes_fixed_and_max_items_overflow(self) -> None:
        self.contract["objective"] = "O" * 9000
        self.publish()

        fixed = context.brief_diagnostics("TASK-001", max_chars=8000, base_dir=self.base)

        self.assertEqual(fixed["status"], "overflow")
        self.assertEqual(fixed["overflow"]["kind"], "fixed")
        self.assertGreater(fixed["budget"]["fixed_prompt_chars"], 8000)

        self.contract["task_id"] = "TASK-002"
        self.contract["objective"] = "Compact objective"
        context.publish_contract(self.contract, confirmed_by="publisher", base_dir=self.base)
        first = context.record(
            "TASK-002",
            statement="First required observation",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-01"},
            metadata={"required": True},
            base_dir=self.base,
        )
        second = context.record(
            "TASK-002",
            statement="Second required observation",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-02"},
            metadata={"required": True},
            base_dir=self.base,
        )

        max_items = context.brief_diagnostics(
            "TASK-002",
            max_items=1,
            base_dir=self.base,
        )

        self.assertEqual(max_items["status"], "overflow")
        self.assertEqual(max_items["overflow"]["kind"], "max_items")
        self.assertEqual(max_items["items"]["mandatory_count"], 2)
        self.assertEqual(len(max_items["items"]["selected_ids"]), 1)
        self.assertEqual(len(max_items["overflow"]["item_ids"]), 1)
        self.assertEqual(
            set(max_items["items"]["selected_ids"] + max_items["overflow"]["item_ids"]),
            {first["id"], second["id"]},
        )

    def test_brief_diagnostics_classifies_empty_prompt_overflow_as_fixed(self) -> None:
        self.publish()
        ready = context.brief_diagnostics("TASK-001", base_dir=self.base)
        max_chars = ready["budget"]["fixed_prompt_chars"] - 1

        diagnostics = context.brief_diagnostics(
            "TASK-001",
            max_chars=max_chars,
            base_dir=self.base,
        )

        self.assertEqual(diagnostics["status"], "overflow")
        self.assertEqual(diagnostics["overflow"]["kind"], "fixed")
        self.assertGreater(diagnostics["budget"]["fixed_prompt_chars"], max_chars)
        with self.assertRaisesRegex(
            context.ContextError,
            "BRIEF_REQUIRED_OVERFLOW: brief content exceeds max_chars",
        ):
            context.brief("TASK-001", max_chars=max_chars, base_dir=self.base)

    def test_brief_diagnostics_rejects_include_filter_that_omits_required_item(self) -> None:
        self.publish()
        required = context.record(
            "TASK-001",
            statement="Required observation",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-required"},
            metadata={"required": True},
            base_dir=self.base,
        )

        legacy_packet = context.brief("TASK-001", include=[], base_dir=self.base)
        diagnostics = context.brief_diagnostics("TASK-001", include=[], base_dir=self.base)

        self.assertEqual(legacy_packet["observations"], [])
        self.assertEqual(diagnostics["status"], "overflow")
        self.assertFalse(diagnostics["fits"])
        self.assertEqual(diagnostics["overflow"]["kind"], "include")
        self.assertEqual(diagnostics["overflow"]["item_ids"], [required["id"]])
        self.assertEqual(diagnostics["items"]["filtered_mandatory_ids"], [required["id"]])

    def test_brief_diagnostics_does_not_rerender_full_mandatory_sets(self) -> None:
        self.publish()
        for index in range(20):
            context.record(
                "TASK-001",
                statement=f"required-{index}-" + "R" * 10000,
                item_type="observation",
                actor="executor",
                source={"kind": "tool", "ref": f"probe-{index}"},
                metadata={"required": True},
                base_dir=self.base,
            )

        with patch.object(
            context,
            "_brief_to_markdown",
            wraps=context._brief_to_markdown,
        ) as render:
            diagnostics = context.brief_diagnostics("TASK-001", base_dir=self.base)

        self.assertEqual(diagnostics["status"], "overflow")
        self.assertEqual(diagnostics["items"]["mandatory_count"], 20)
        self.assertLessEqual(render.call_count, 6)

    def test_brief_token_estimate_weights_cjk_without_becoming_a_gate(self) -> None:
        self.contract["task_id"] = "ASCII-001"
        self.contract["objective"] = "A" * 120
        context.publish_contract(self.contract, confirmed_by="publisher", base_dir=self.base)
        ascii_diagnostics = context.brief_diagnostics("ASCII-001", base_dir=self.base)

        self.contract["task_id"] = "CJK00-001"
        self.contract["objective"] = "界" * 120
        context.publish_contract(self.contract, confirmed_by="publisher", base_dir=self.base)
        cjk_diagnostics = context.brief_diagnostics("CJK00-001", base_dir=self.base)

        self.assertEqual(ascii_diagnostics["status"], "ready")
        self.assertEqual(cjk_diagnostics["status"], "ready")
        self.assertGreater(cjk_diagnostics["text"]["cjk_chars"], ascii_diagnostics["text"]["cjk_chars"])
        self.assertGreater(
            cjk_diagnostics["token_estimate"]["range_low"],
            ascii_diagnostics["token_estimate"]["range_low"],
        )

    def test_handoff_gate_rejects_unrenderable_brief_with_diagnostics(self) -> None:
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
        context.checkpoint(
            "TASK-001",
            phase="handoff",
            completed=["captured current state"],
            evidence_added=[],
            next_action="externalize oversized detail and keep its stable reference",
            actor="executor",
            base_dir=self.base,
        )

        report = context.gate("TASK-001", stage="handoff", emit=False, base_dir=self.base)

        self.assertFalse(report["passed"])
        self.assertIn(
            "BRIEF_REQUIRED_OVERFLOW: mandatory items exceed max_chars",
            report["errors"],
        )
        self.assertEqual(report["stats"]["brief_status"], "overflow")
        self.assertEqual(report["stats"]["brief_overflow_kind"], "mandatory")
        self.assertGreater(report["stats"]["brief_mandatory_prompt_chars"], 8000)

    def test_handoff_gate_fails_closed_when_brief_preflight_is_unavailable(self) -> None:
        self.publish()
        context.checkpoint(
            "TASK-001",
            phase="handoff",
            completed=["captured current state"],
            evidence_added=[],
            next_action="continue from the controlled checkpoint",
            actor="executor",
            base_dir=self.base,
        )

        with patch.object(
            context,
            "_plan_brief",
            side_effect=context.ContextError("synthetic preflight failure"),
        ):
            report = context.gate("TASK-001", stage="handoff", emit=False, base_dir=self.base)

        self.assertFalse(report["passed"])
        self.assertIn(
            "brief preflight unavailable: synthetic preflight failure",
            report["errors"],
        )

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
                    "evidence": [dict(evidence, covered_hops=["entry", "write"])],
                    "covered_hops": ["entry", "write"],
                }
            },
            verifiers={"file": passing_verifier},
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
                    "evidence": [
                        dict(evidence, covered_hops=["entry", "guard", "write"])
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            verifiers={"file": passing_verifier},
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
            "covered_hops": ["entry", "guard", "write"],
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
                            "covered_hops": ["entry", "guard", "write"],
                        }
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            resolvers={"custom": permission_denied_resolver},
            verifiers={"custom": passing_verifier},
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
            "covered_hops": ["entry", "guard", "write"],
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
        evidence = {
            "evidence_id": "EV-FILE",
            "kind": "file",
            "covered_hops": ["entry", "guard", "write"],
        }
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
            base_dir=self.base,
            emit=False,
            **dependencies,
        )
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["criteria"]["AC-01"]["missing_delivery_types"], ["feishu"])

        verified_entry = dict(
            entry,
            delivery_receipts=[valid_delivery_receipt()],
        )
        unverified = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={"AC-01": verified_entry},
            resolvers=dependencies["resolvers"],
            verifiers={"file": passing_verifier},
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
            {
                "evidence_id": "EV-INCOMPLETE-RECEIPT",
                "kind": "delivery-receipt",
                "delivery_type": "feishu",
            },
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
                    "evidence": [
                        {
                            "evidence_id": "EV-COMPLETE",
                            "kind": "custom",
                            "covered_hops": ["entry", "guard", "write"],
                        }
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertIn(f"required context item is conflicted: {item['id']}", report["errors"])
        self.assertEqual(report["criteria"]["AC-01"]["status"], "pass")

    def test_completion_global_conflict_gate_cannot_be_narrowed_by_required_item_ids(self) -> None:
        self.contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
        self.publish()
        normal = context.record(
            "TASK-001",
            statement="Normal completion context",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-normal"},
            base_dir=self.base,
        )
        conflicted = context.record(
            "TASK-001",
            statement="Disputed completion context",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "probe-conflicted"},
            base_dir=self.base,
        )
        context.update_item(
            "TASK-001",
            conflicted["id"],
            actor="validator",
            status="conflicted",
            conflicts_with=["EV-DISPUTE"],
            conflict_reason="Independent observation disagrees",
            base_dir=self.base,
        )

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [
                        {
                            "evidence_id": "EV-COMPLETE",
                            "kind": "custom",
                            "covered_hops": ["entry", "guard", "write"],
                        }
                    ],
                    "covered_hops": ["entry", "guard", "write"],
                }
            },
            required_item_ids=[normal["id"]],
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(any(conflicted["id"] in error for error in report["errors"]))

    def test_completion_rejects_explicitly_required_superseded_item(self) -> None:
        self.contract["acceptance_criteria"][0]["required_evidence"] = ["custom"]
        self.publish()
        superseded = context.record(
            "TASK-001",
            statement="An obsolete implementation observation",
            item_type="observation",
            actor="executor",
            source={"kind": "tool", "ref": "obsolete-observation"},
            base_dir=self.base,
        )
        context.update_item(
            "TASK-001",
            superseded["id"],
            actor="executor",
            status="superseded",
            base_dir=self.base,
        )

        evidence_map = {
            "AC-01": {
                "evidence": [
                    {
                        "evidence_id": "EV-COMPLETE",
                        "kind": "custom",
                        "covered_hops": ["entry", "guard", "write"],
                    }
                ]
            }
        }
        dependencies = {
            "resolvers": {"custom": passing_resolver},
            "verifiers": {"custom": passing_verifier},
        }
        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map=evidence_map,
            required_item_ids=[superseded["id"]],
            base_dir=self.base,
            emit=False,
            **dependencies,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(any("superseded" in error for error in report["errors"]))

        effective_only = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map=evidence_map,
            base_dir=self.base,
            emit=False,
            **dependencies,
        )
        self.assertTrue(effective_only["passed"], effective_only["errors"])

    def test_completion_consumes_canonical_required_hops(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion.pop("chain_hops")
        criterion["required_hops"] = ["ingress", "commit"]
        self.publish()

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [{"evidence_id": "EV-HOPS", "kind": "custom"}],
                    "covered_hops": [],
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["criteria"]["AC-01"]["missing_hops"], ["commit", "ingress"])

    def test_completion_rejects_self_reported_unbound_hops(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion.pop("chain_hops")
        criterion["required_hops"] = ["ingress", "commit"]
        self.publish()

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [{"evidence_id": "EV-UNBOUND", "kind": "custom"}],
                    "covered_hops": ["ingress", "commit"],
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["criteria"]["AC-01"]["missing_hops"], ["commit", "ingress"])

    def test_completion_requires_validator_when_independent_validation_is_requested(self) -> None:
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
                    "validated_at": NOW.isoformat().replace("+00:00", "Z"),
                    "evidence": [
                        {
                            "evidence_id": "EV-NO-VALIDATOR",
                            "kind": "custom",
                            "produced_by": "executor-01",
                        }
                    ]
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(any("independent" in error.lower() for error in report["errors"]))

    def test_completion_rejects_same_producer_and_validator(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["chain_hops"] = []
        criterion["independent_validation_required"] = True
        self.contract["actor_roles"] = {
            "executor-01": ["executor", "validator"],
        }
        self.publish()

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "validated_by": "executor-01",
                    "validated_at": NOW.isoformat().replace("+00:00", "Z"),
                    "evidence": [
                        {
                            "evidence_id": "EV-SELF-VALIDATED",
                            "kind": "custom",
                            "produced_by": "executor-01",
                        }
                    ],
                }
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": passing_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(any("validator" in error.lower() for error in report["errors"]))

    def test_completion_rejects_validator_who_produced_delivery_receipt(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["chain_hops"] = []
        criterion["required_delivery_types"] = ["feishu"]
        criterion["independent_validation_required"] = True
        self.contract["actor_roles"] = {
            "executor-01": ["executor"],
            "validator-01": ["validator"],
        }
        self.publish()
        receipt = {
            "evidence_id": "EV-RECEIPT-BY-VALIDATOR",
            "kind": "delivery-receipt",
            "delivery_type": "feishu",
            "channel": "feishu",
            "target_id": "chat-01",
            "artifact_ref": "EV-PRIMARY",
            "external_id": "message-01",
            "sent_at": "2026-08-27T04:31:00Z",
            "observed_at": "2026-08-27T04:32:00Z",
            "verification_method": "read-back",
            "produced_by": "validator-01",
        }

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "validated_by": "validator-01",
                    "validated_at": NOW.isoformat().replace("+00:00", "Z"),
                    "evidence": [
                        {
                            "evidence_id": "EV-PRIMARY",
                            "kind": "custom",
                            "produced_by": "executor-01",
                        }
                    ],
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
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        independence = report["criteria"]["AC-01"]["independent_validation"]
        self.assertEqual(independence["status"], "fail")
        self.assertIn("VALIDATOR_NOT_INDEPENDENT", independence["codes"])

    def test_completion_callbacks_cannot_mutate_sealed_requirements_or_callers(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion.pop("chain_hops")
        criterion["required_hops"] = ["immutable-hop"]
        criterion["required_delivery_types"] = ["feishu"]
        self.publish()
        contract_path = self.base / "TASK-001" / "task-contract.json"
        caller_contract_before = deepcopy(self.contract)
        stored_contract_before = contract_path.read_bytes()
        evidence_map = {
            "AC-01": {
                "evidence": [{"evidence_id": "EV-MALICIOUS", "kind": "custom"}],
                "covered_hops": ["immutable-hop"],
                "delivery_receipts": [],
            }
        }
        evidence_map_before = deepcopy(evidence_map)

        def malicious_resolver(evidence, callback_criterion, callback_contract, now):
            evidence.clear()
            callback_criterion.clear()
            callback_contract.get("acceptance_criteria", []).clear()
            return passing_resolver(evidence, callback_criterion, callback_contract, now)

        def malicious_verifier(evidence, callback_criterion, resolution):
            evidence.clear()
            callback_criterion.clear()
            resolution.clear()
            return {"status": "pass", "codes": []}

        report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map=evidence_map,
            resolvers={"custom": malicious_resolver},
            verifiers={"custom": malicious_verifier},
            base_dir=self.base,
            emit=False,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(evidence_map, evidence_map_before)
        self.assertEqual(self.contract, caller_contract_before)
        self.assertEqual(contract_path.read_bytes(), stored_contract_before)
        self.assertEqual(report["criteria"]["AC-01"]["missing_hops"], ["immutable-hop"])
        self.assertEqual(report["criteria"]["AC-01"]["missing_delivery_types"], ["feishu"])

    def test_publish_rejects_invalid_freshness_windows(self) -> None:
        invalid_windows = ["3600", -1]
        for index, maximum in enumerate(invalid_windows):
            with self.subTest(maximum=maximum):
                contract = deepcopy(self.contract)
                contract["task_id"] = f"TASK-WINDOW-{index}"
                contract["acceptance_criteria"][0]["max_evidence_age_seconds"] = maximum
                with self.assertRaisesRegex(context.ContextError, "max_evidence_age_seconds"):
                    context.publish_contract(
                        contract,
                        confirmed_by="publisher",
                        base_dir=self.base,
                    )

    def test_publish_rejects_invalid_freshness_override(self) -> None:
        contract = deepcopy(self.contract)
        contract["task_id"] = "TASK-OVERRIDE"
        contract["acceptance_criteria"][0]["max_evidence_age_seconds"] = 3600
        contract["acceptance_criteria"][0]["evidence_freshness_by_type"] = {
            "custom": "unbounded"
        }

        with self.assertRaisesRegex(context.ContextError, "evidence_freshness_by_type"):
            context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)

    def test_publish_validates_security_field_types_before_json_coercion(self) -> None:
        numeric_actor = deepcopy(self.contract)
        numeric_actor["task_id"] = "TASK-NUMERIC-ACTOR"
        numeric_actor["actor_roles"] = {7: ["validator"]}
        numeric_actor["acceptance_criteria"][0]["independent_validation_required"] = True

        numeric_freshness_kind = deepcopy(self.contract)
        numeric_freshness_kind["task_id"] = "TASK-NUMERIC-FRESHNESS"
        numeric_freshness_kind["acceptance_criteria"][0][
            "evidence_freshness_by_type"
        ] = {7: 3600}

        for contract in (numeric_actor, numeric_freshness_kind):
            with self.subTest(task_id=contract["task_id"]):
                with self.assertRaises(context.ContextError):
                    context.publish_contract(
                        contract,
                        confirmed_by="publisher",
                        base_dir=self.base,
                    )

    def test_completion_rejects_future_date_only_and_naive_generated_at(self) -> None:
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        content = b"timestamp boundary evidence\n"
        (workspace / "completion.txt").write_bytes(content)
        self.contract["workspace_root"] = str(workspace)
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["file"]
        criterion["required_scope"] = {"task_id": "TASK-001", "criterion_id": "AC-01"}
        criterion["max_evidence_age_seconds"] = 3600
        self.publish()
        fixtures = {
            "future": "2099-01-01T00:00:00Z",
            "date-only": "2026-08-27",
            "naive": "2026-08-27T04:30:00",
        }
        for label, generated_at in fixtures.items():
            with self.subTest(label=label):
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [
                                {
                                    "evidence_id": f"EV-{label.upper()}",
                                    "kind": "file",
                                    "locator": "completion.txt",
                                    "artifact_digest": "sha256:"
                                    + hashlib.sha256(content).hexdigest(),
                                    "generated_at": generated_at,
                                    "scope": {
                                        "task_id": "TASK-001",
                                        "criterion_id": "AC-01",
                                    },
                                }
                            ],
                            "covered_hops": ["entry", "guard", "write"],
                        }
                    },
                    verifiers={"file": passing_verifier},
                    base_dir=self.base,
                    emit=False,
                )
                self.assertFalse(report["passed"])
                codes = report["criteria"]["AC-01"]["evidence_results"][0]["checks"][
                    "integrity_and_freshness"
                ]["codes"]
                expected = "FUTURE_GENERATED_AT" if label == "future" else "INVALID_GENERATED_AT"
                self.assertIn(expected, codes)

    def test_public_audit_and_gate_signatures_do_not_expose_probe_bypass(self) -> None:
        for function in (context.audit, context.gate):
            with self.subTest(function=function.__name__):
                self.assertNotIn("_run_probe", inspect.signature(function).parameters)

    def test_public_probe_bypass_keyword_is_rejected(self) -> None:
        self.publish()
        calls = (
            (context.audit, {"task_id": "TASK-001"}),
            (context.gate, {"task_id": "TASK-001", "stage": "release"}),
        )
        for function, kwargs in calls:
            with self.subTest(function=function.__name__):
                with self.assertRaises(TypeError):
                    function(
                        **kwargs,
                        base_dir=self.base,
                        emit=False,
                        _run_probe=False,
                    )

    def test_completion_tri_state_aggregation_is_fail_unknown_pass(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion.pop("required_evidence")
        criterion.pop("chain_hops")
        criterion.update(
            required_evidence_types=["custom"],
            required_hops=["bound-hop"],
            required_delivery_types=["feishu"],
            independent_validation_required=False,
        )
        self.publish()

        def tri_state_resolver(evidence, callback_criterion, callback_contract, now):
            status = evidence.get("resolution_status", "pass")
            if status == "missing-checks":
                return {"resolve": {"status": "pass", "codes": []}}
            codes = [] if status == "pass" else [f"EXPLICIT_{str(status).upper()}"]
            return {
                "resolve": {"status": status, "codes": codes},
                "integrity_and_freshness": {"status": "pass", "codes": []},
                "scope": {"status": "pass", "codes": []},
            }

        primary = {
            "evidence_id": "EV-REQUIRED",
            "kind": "custom",
            "covered_hops": ["bound-hop"],
        }
        receipt = valid_delivery_receipt()
        cases = {
            "required-pass": (
                {"evidence": [primary], "delivery_receipts": [receipt]},
                "pass",
            ),
            "required-fail": (
                {
                    "evidence": [dict(primary, resolution_status="fail")],
                    "delivery_receipts": [receipt],
                },
                "fail",
            ),
            "required-unknown": (
                {
                    "evidence": [dict(primary, resolution_status="unknown")],
                    "delivery_receipts": [receipt],
                },
                "unknown",
            ),
            "extra-fail": (
                {
                    "evidence": [primary, dict(primary, evidence_id="EV-EXTRA", resolution_status="fail")],
                    "delivery_receipts": [receipt],
                },
                "fail",
            ),
            "extra-unknown": (
                {
                    "evidence": [
                        primary,
                        dict(primary, evidence_id="EV-EXTRA", resolution_status="unknown"),
                    ],
                    "delivery_receipts": [receipt],
                },
                "unknown",
            ),
            "missing-evidence": (
                {"evidence": [], "delivery_receipts": [receipt]},
                "unknown",
            ),
            "missing-type": (
                {
                    "evidence": [dict(primary, evidence_id="EV-OTHER", kind="other")],
                    "delivery_receipts": [receipt],
                },
                "unknown",
            ),
            "missing-hop": (
                {
                    "evidence": [{key: value for key, value in primary.items() if key != "covered_hops"}],
                    "delivery_receipts": [receipt],
                },
                "unknown",
            ),
            "missing-receipt": ({"evidence": [primary], "delivery_receipts": []}, "unknown"),
            "missing-checks": (
                {
                    "evidence": [dict(primary, resolution_status="missing-checks")],
                    "delivery_receipts": [receipt],
                },
                "unknown",
            ),
            "malformed-receipt": (
                {"evidence": [primary], "delivery_receipts": ["receipt:pointer"]},
                "fail",
            ),
        }
        dependencies = {
            "resolvers": {
                "custom": tri_state_resolver,
                "other": tri_state_resolver,
                "delivery-receipt": tri_state_resolver,
            },
            "verifiers": {
                "custom": passing_verifier,
                "other": passing_verifier,
                "delivery-receipt": passing_verifier,
            },
        }

        for label, (entry, expected) in cases.items():
            with self.subTest(label=label):
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={"AC-01": deepcopy(entry)},
                    base_dir=self.base,
                    emit=False,
                    **dependencies,
                )
                self.assertEqual(report["criteria"]["AC-01"]["status"], expected)
                self.assertEqual(report["passed"], expected == "pass")

    def test_completion_normalizes_resolver_and_verifier_exceptions(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["chain_hops"] = []
        self.publish()

        resolver_exceptions = (
            (PermissionError("denied"), "PERMISSION_DENIED"),
            (TimeoutError("late"), "RESOLVER_TIMEOUT"),
            (OSError("temporary"), "TRANSIENT_IO"),
            (RuntimeError("boom"), "RESOLVER_ERROR"),
        )
        for index, (exception, expected_code) in enumerate(resolver_exceptions):
            with self.subTest(exception=type(exception).__name__):
                def raising_resolver(evidence, callback_criterion, callback_contract, now, error=exception):
                    raise error

                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [
                                {"evidence_id": f"EV-RESOLVER-{index}", "kind": "custom"}
                            ]
                        }
                    },
                    resolvers={"custom": raising_resolver},
                    verifiers={"custom": passing_verifier},
                    base_dir=self.base,
                    emit=False,
                )
                self.assertFalse(report["passed"])
                result = report["criteria"]["AC-01"]["evidence_results"][0]
                self.assertEqual(result["status"], "unknown")
                self.assertIn(expected_code, result["checks"]["resolve"]["codes"])

        def raising_verifier(evidence, callback_criterion, resolution):
            raise RuntimeError("verifier boom")

        verifier_report = context.gate(
            "TASK-001",
            stage="completion",
            evidence_map={
                "AC-01": {"evidence": [{"evidence_id": "EV-VERIFIER", "kind": "custom"}]}
            },
            resolvers={"custom": passing_resolver},
            verifiers={"custom": raising_verifier},
            base_dir=self.base,
            emit=False,
        )
        verifier_result = verifier_report["criteria"]["AC-01"]["evidence_results"][0]
        self.assertFalse(verifier_report["passed"])
        self.assertEqual(verifier_result["status"], "unknown")
        self.assertIn("VERIFIER_ERROR", verifier_result["checks"]["claim"]["codes"])

    def test_completion_requires_unique_nonempty_evidence_ids_before_resolution(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion["required_evidence"] = ["custom"]
        criterion["chain_hops"] = []
        self.publish()
        resolver_calls: list[str] = []

        def counting_resolver(evidence, callback_criterion, callback_contract, now):
            resolver_calls.append(str(evidence.get("evidence_id")))
            return passing_resolver(evidence, callback_criterion, callback_contract, now)

        cases = {
            "missing": {"evidence": [{"kind": "custom"}]},
            "blank": {"evidence": [{"evidence_id": "   ", "kind": "custom"}]},
            "numeric": {"evidence": [{"evidence_id": 7, "kind": "custom"}]},
            "duplicate-primary": {
                "evidence": [
                    {"evidence_id": "EV-DUP", "kind": "custom"},
                    {"evidence_id": "EV-DUP", "kind": "custom"},
                ]
            },
            "duplicate-across-receipt": {
                "evidence": [{"evidence_id": "EV-SHARED", "kind": "custom"}],
                "delivery_receipts": [
                    {
                        "evidence_id": "EV-SHARED",
                        "kind": "delivery-receipt",
                        "delivery_type": "feishu",
                    }
                ],
            },
            "malformed-sibling": {
                "evidence": [
                    "not-an-evidence-object",
                    {"evidence_id": "EV-VALID-SIBLING", "kind": "custom"},
                ]
            },
        }
        dependencies = {
            "resolvers": {
                "custom": counting_resolver,
                "delivery-receipt": counting_resolver,
            },
            "verifiers": {
                "custom": passing_verifier,
                "delivery-receipt": passing_verifier,
            },
        }

        for label, entry in cases.items():
            with self.subTest(label=label):
                resolver_calls.clear()
                report = context.gate(
                    "TASK-001",
                    stage="completion",
                    evidence_map={"AC-01": deepcopy(entry)},
                    base_dir=self.base,
                    emit=False,
                    **dependencies,
                )
                self.assertFalse(report["passed"])
                self.assertEqual(report["criteria"]["AC-01"]["status"], "fail")
                self.assertEqual(resolver_calls, [])
                codes = {
                    code
                    for result in report["criteria"]["AC-01"]["evidence_results"]
                    for check in result["checks"].values()
                    for code in check["codes"]
                }
                if label.startswith("duplicate"):
                    expected = "DUPLICATE_EVIDENCE_ID"
                elif label == "malformed-sibling":
                    expected = "MALFORMED_EVIDENCE"
                else:
                    expected = "MALFORMED_EVIDENCE_ID"
                self.assertIn(expected, codes)

    def test_markdown_brief_renders_strict_completion_controls(self) -> None:
        criterion = self.contract["acceptance_criteria"][0]
        criterion.pop("required_evidence")
        criterion.pop("chain_hops")
        self.contract["actor_roles"] = {
            "executor-01": ["executor"],
            "validator-01": ["validator"],
        }
        criterion.update(
            required_evidence_types=["test-report"],
            required_hops=["entry", "write"],
            required_delivery_types=["feishu"],
            required_scope={"module": "payment-callback", "environment": "test"},
            max_evidence_age_seconds=3600,
            evidence_freshness_by_type={"test-report": 600},
            required_revision="a" * 40,
            revision_match="exact",
            independent_validation_required=True,
        )
        self.publish()

        prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

        for expected in (
            'required_evidence_types=["test-report"]',
            'required_hops=["entry","write"]',
            'required_delivery_types=["feishu"]',
            'required_scope={"environment":"test","module":"payment-callback"}',
            "max_evidence_age_seconds=3600",
            'evidence_freshness_by_type={"test-report":600}',
            f'required_revision={"a" * 40}',
            "revision_match=exact",
            "independent_validation_required=true",
            'actor_roles={"executor-01":["executor"],"validator-01":["validator"]}',
        ):
            self.assertIn(expected, prompt)

    def test_documented_structured_completion_example_executes(self) -> None:
        example_path = ROOT / "examples" / "strict_completion.py"
        completed = subprocess.run(
            [sys.executable, str(example_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        namespace = {"__file__": str(example_path), "__name__": "strict_completion_example"}
        exec(compile(example_path.read_text(encoding="utf-8"), str(example_path), "exec"), namespace)

        self.clock.stop()
        try:
            report = namespace["run_example"]()
        finally:
            self.clock.start()

        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["criteria"]["AC-01"]["status"], "pass")

    def test_audit_counts_event_attempt_that_fails_to_parse(self) -> None:
        self.publish()
        events_path = self.base / "TASK-001" / "events.jsonl"
        with events_path.open("ab") as handle:
            handle.write(b"{malformed-json\n")

        report = context.audit("TASK-001", base_dir=self.base, emit=False)

        self.assertFalse(report["passed"])
        self.assertEqual(report["stats"]["events_checked"], 2)
        self.assertEqual(report["stats"]["contracts_checked"], 1)

    def test_audit_normalizes_invalid_utf8_event_and_counts_attempt(self) -> None:
        self.publish()
        events_path = self.base / "TASK-001" / "events.jsonl"
        with events_path.open("ab") as handle:
            handle.write(b"\xff\n")

        report = context.audit("TASK-001", base_dir=self.base, emit=False)

        self.assertFalse(report["passed"])
        self.assertEqual(report["stats"]["events_checked"], 2)
        self.assertTrue(any("UTF-8" in error for error in report["errors"]))

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

        with self.assertRaises(TypeError):
            context.audit(
                "TASK-001",
                base_dir=self.base,
                emit=False,
                _run_probe=False,
            )

    def test_gate_rejects_external_probe_bypass(self) -> None:
        self.publish()

        with self.assertRaises(TypeError):
            context.gate(
                "TASK-001",
                stage="release",
                base_dir=self.base,
                emit=False,
                _run_probe=False,
            )

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
