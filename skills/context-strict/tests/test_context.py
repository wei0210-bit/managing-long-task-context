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

    def enable_evidence_handlers(self, handlers: dict[str, dict[str, str]]) -> None:
        self.contract["required_capabilities"] = ["evidence-handlers/v1"]
        self.contract["evidence_handlers"] = {
            "schema": "evidence-handlers/v1",
            "types": handlers,
        }












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
        path.chmod(0o644)
        path.write_text(json.dumps(stored), encoding="utf-8")
        report = context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)
        self.assertFalse(report["passed"])
        self.assertTrue(any("integrity digest is invalid" in error for error in report["errors"]))


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


    def test_brief_rejects_non_positive_character_budget(self) -> None:
        self.publish()
        with self.assertRaisesRegex(ValueError, 'max_chars must be positive'):
            context.brief('TASK-001', max_chars=0, base_dir=self.base)

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
        packet = context.brief('TASK-001', max_chars=8000, base_dir=self.base)
        self.assertIsNotNone(packet["diagnostics"]["overflow"])

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
        packet = context.brief('TASK-001', max_chars=max_chars, base_dir=self.base)
        self.assertIsNotNone(packet["diagnostics"]["overflow"])

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

        packet = context.brief('TASK-001', include=[], base_dir=self.base)
        self.assertIsNotNone(packet["diagnostics"]["overflow"])
        diagnostics = context.brief_diagnostics("TASK-001", include=[], base_dir=self.base)

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

    def test_publish_rejects_invalid_versions_before_creating_files(self) -> None:
        for version in ("1", 1.5, 1.0, True, False, 0, -1, None):
            for existing_directory in (False, True):
                with self.subTest(version=version, existing_directory=existing_directory):
                    with tempfile.TemporaryDirectory() as directory:
                        base = Path(directory) / ".prime" / "context"
                        task_dir = base / "TASK-001"
                        if existing_directory:
                            task_dir.mkdir(parents=True)
                        contract = deepcopy(self.contract)
                        contract["version"] = version

                        with self.assertRaises(context.ContextError):
                            context.publish_contract(contract, confirmed_by="publisher", base_dir=base)

                        self.assertEqual(set(Path(directory).rglob("*")),
                                         {base.parent, base, task_dir} if existing_directory else set())

    def test_publish_rejects_invalid_update_versions_without_changing_files(self) -> None:
        for version in ("2", 2.5, 2.0, True, False, 0, -1, None):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    base = Path(directory) / ".prime" / "context"
                    context.publish_contract(self.contract, confirmed_by="publisher", base_dir=base)
                    task_dir = base / "TASK-001"
                    before = {path.relative_to(task_dir): path.read_bytes() if path.is_file() else None
                              for path in task_dir.rglob("*")}
                    contract = deepcopy(self.contract)
                    contract["version"] = version
                    with self.assertRaises(context.ContextError):
                        context.publish_contract(contract, confirmed_by="publisher", base_dir=base)
                    after = {path.relative_to(task_dir): path.read_bytes() if path.is_file() else None
                             for path in task_dir.rglob("*")}
                    self.assertEqual(after, before)

    def test_publish_accepts_positive_integer_versions(self) -> None:
        for version in (1, 2, 100):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    base = Path(directory) / ".prime" / "context"
                    contract = deepcopy(self.contract)
                    contract["version"] = version
                    published = context.publish_contract(contract, confirmed_by="publisher", base_dir=base)
                    self.assertEqual(published["version"], version)
                    stored = json.loads((base / "TASK-001" / "task-contract.json").read_text())
                    self.assertEqual(stored, published)

    def test_legacy_sealed_string_version_remains_readable(self) -> None:
        # Preservation: create an already-sealed legacy contract without publishing it.
        legacy = deepcopy(self.contract)
        legacy["version"] = "legacy-1"
        legacy["seal"] = {"confirmed_by": "publisher", "confirmed_at": NOW.isoformat()}
        legacy["seal"]["integrity_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(legacy)).hexdigest()
        )
        task_dir = self.base / "TASK-001"
        task_dir.mkdir(parents=True)
        (task_dir / ".lock").touch()
        path = task_dir / "task-contract.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        before = path.read_bytes()

        packet = context.brief("TASK-001", base_dir=self.base)
        self.assertEqual(packet["task_id"], "TASK-001")
        self.assertEqual(packet["contract_version"], "legacy-1")
        self.assertTrue(context.audit("TASK-001", base_dir=self.base, emit=False)["passed"])
        self.assertTrue(context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)["passed"])
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
