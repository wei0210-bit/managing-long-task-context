from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


NOW = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)


def passing_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "pass", "codes": []},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
    }


def passing_verifier(evidence, criterion, resolution):
    return {"status": "pass", "codes": []}


class ProductionFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / ".prime" / "context"
        self.clock = patch.object(context, "_trusted_utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def contract(self, task_id: str = "PROD-001") -> dict:
        return {
            "schema": 1,
            "task_id": task_id,
            "version": 1,
            "issued_by": "publisher",
            "issued_at": "2026-09-02T05:00:00Z",
            "authorized_approvers": [],
            "workspace_root": str(self.root),
            "objective": "Harden production context behavior",
            "scope": ["context controls"],
            "out_of_scope": [],
            "constraints": ["preserve hard stops"],
            "acceptance_criteria": [
                {
                    "id": "AC-01",
                    "criterion": "The controlled behavior is verified",
                    "required_evidence_types": ["integration-test"],
                    "required_hops": [],
                    "required_delivery_types": [],
                    "independent_validation_required": False,
                }
            ],
        }

    def publish(self, task_id: str = "PROD-001", **kwargs) -> dict:
        return context.publish_contract(
            self.contract(task_id),
            confirmed_by="publisher",
            base_dir=self.base,
            **kwargs,
        )

    def test_contract_publish_is_read_only_by_default_and_opt_out_is_sealed(self) -> None:
        protected = self.publish("PROTECTED")
        protected_path = self.base / "PROTECTED" / "task-contract.json"

        self.assertEqual(
            protected["seal"]["file_protection"],
            "read-only-advisory-v1",
        )
        self.assertEqual(stat.S_IMODE(protected_path.stat().st_mode) & 0o222, 0)
        with self.assertRaises(PermissionError):
            protected_path.open("w", encoding="utf-8")

        unprotected = self.publish("UNPROTECTED", protect_contract=False)
        unprotected_path = self.base / "UNPROTECTED" / "task-contract.json"
        self.assertEqual(unprotected["seal"]["file_protection"], "none")
        self.assertNotEqual(stat.S_IMODE(unprotected_path.stat().st_mode) & 0o200, 0)
        self.assertTrue(
            context.audit("UNPROTECTED", base_dir=self.base, emit=False)["passed"]
        )

    def test_contract_protection_is_audited_and_does_not_block_versioned_publish(self) -> None:
        published = self.publish("PROTECTED")
        contract_path = self.base / "PROTECTED" / "task-contract.json"
        contract_path.chmod(0o644)

        report = context.audit("PROTECTED", base_dir=self.base, emit=False)

        self.assertFalse(report["passed"])
        self.assertIn("CONTRACT_FILE_PROTECTION_MISSING", report["errors"])

        update = self.contract("PROTECTED")
        update["version"] = 2
        update["objective"] = "Harden production context behavior, version two"
        republished = context.publish_contract(
            update,
            confirmed_by="publisher",
            base_dir=self.base,
        )
        self.assertEqual(republished["version"], 2)
        self.assertNotEqual(published["seal"]["integrity_digest"], republished["seal"]["integrity_digest"])
        self.assertEqual(stat.S_IMODE(contract_path.stat().st_mode) & 0o222, 0)

    def test_contract_protection_option_requires_a_real_boolean(self) -> None:
        with self.assertRaisesRegex(TypeError, "protect_contract must be a boolean"):
            self.publish("BAD-PROTECTION", protect_contract="false")
        self.assertFalse((self.base / "BAD-PROTECTION").exists())

    def test_contract_protection_check_fails_closed_when_stat_is_unavailable(self) -> None:
        protected = self.publish("PROTECTION-UNAVAILABLE")

        self.assertEqual(
            context._contract_file_protection_errors(
                protected,
                self.root / "missing-contract.json",
            ),
            ["CONTRACT_FILE_PROTECTION_UNAVAILABLE"],
        )

    def _record_oversized_required_items(self, task_id: str = "OVERFLOW") -> list[str]:
        self.publish(task_id)
        identifiers = []
        for index in range(3):
            item_id = f"REQ-{index + 1}"
            context.record(
                task_id,
                item_id=item_id,
                statement=f"required-{index}-" + "R" * 5000,
                item_type="observation",
                actor="executor",
                source={"kind": "tool", "ref": f"probe-{index}"},
                metadata={"required": True, "severity": "high"},
                base_dir=self.base,
            )
            identifiers.append(item_id)
        return identifiers

    def test_brief_overflow_lists_every_omitted_mandatory_item_and_is_not_usable(self) -> None:
        identifiers = self._record_oversized_required_items()

        diagnostics = context.brief_diagnostics(
            "OVERFLOW", max_chars=8000, base_dir=self.base
        )

        self.assertEqual(diagnostics["status"], "overflow")
        self.assertFalse(diagnostics["usable"])
        omitted = diagnostics["overflow"]["omitted_mandatory_ids"]
        self.assertEqual(len(omitted), 2)
        self.assertEqual(
            set(diagnostics["items"]["selected_ids"] + omitted),
            set(identifiers),
        )
        with self.assertRaisesRegex(context.ContextError, "BRIEF_REQUIRED_OVERFLOW"):
            context.brief("OVERFLOW", max_chars=8000, base_dir=self.base)

    def test_every_transition_gate_blocks_mandatory_brief_overflow(self) -> None:
        self._record_oversized_required_items()
        context.checkpoint(
            "OVERFLOW",
            phase="handoff",
            completed=["captured state"],
            evidence_added=[],
            next_action="externalize required detail",
            actor="executor",
            base_dir=self.base,
        )

        for stage in ("release", "resume", "handoff"):
            with self.subTest(stage=stage):
                report = context.gate(
                    "OVERFLOW", stage=stage, base_dir=self.base, emit=False
                )
                self.assertFalse(report["passed"])
                self.assertIn(
                    "BRIEF_REQUIRED_OVERFLOW: mandatory items exceed max_chars",
                    report["errors"],
                )

    def test_externalize_item_preserves_identity_controls_and_verification_time(self) -> None:
        self.publish("EXTERNALIZE")
        external_record = self.root / "seed-context.md"
        external_record.write_text("# Live executions\n\nVerified detail.\n", encoding="utf-8")
        original = context.record(
            "EXTERNALIZE",
            item_id="FACT-001",
            statement="A" * 6000,
            item_type="verified-fact",
            actor="observer",
            source={"kind": "tool", "ref": "live-readback"},
            evidence=["file:/tmp/readback.json#result"],
            scope={"system": "seed"},
            verification_method="read-back",
            mutable=True,
            ttl_hours=24,
            metadata={"required": True, "severity": "critical"},
            base_dir=self.base,
        )

        externalized = context.externalize_item(
            "EXTERNALIZE",
            "FACT-001",
            summary="Live execution detail is stored externally.",
            external_ref=f"file:{external_record.resolve()}#live-executions",
            actor="context-maintainer",
            base_dir=self.base,
        )

        self.assertEqual(externalized["id"], original["id"])
        self.assertEqual(externalized["statement"], "Live execution detail is stored externally.")
        for field in (
            "type", "status", "actor", "source", "evidence", "scope",
            "verification_method", "mutable", "ttl_hours", "verified_at",
            "created_at", "supersedes", "superseded_by", "conflicts_with",
            "conflict_reason",
        ):
            self.assertEqual(externalized[field], original[field], field)
        self.assertTrue(externalized["metadata"]["required"])
        self.assertEqual(externalized["metadata"]["severity"], "critical")
        self.assertEqual(
            externalized["metadata"]["externalized_ref"],
            f"file:{external_record.resolve()}#live-executions",
        )
        self.assertRegex(
            externalized["metadata"]["externalized_ref_digest"],
            r"^sha256:[0-9a-f]{64}$",
        )
        events = [
            json.loads(line)
            for line in (self.base / "EXTERNALIZE" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(events[-1]["event_type"], "item-externalized")
        self.assertEqual(events[1]["payload"]["item"]["statement"], "A" * 6000)

    def test_externalize_rejects_missing_reference_without_mutating_state(self) -> None:
        self.publish("EXTERNALIZE-MISSING")
        original = context.record(
            "EXTERNALIZE-MISSING",
            item_id="FACT-001",
            statement="Bulky verified detail",
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "live-readback"},
            metadata={"required": True},
            base_dir=self.base,
        )
        events_path = self.base / "EXTERNALIZE-MISSING" / "events.jsonl"
        before_events = events_path.read_bytes()

        with self.assertRaisesRegex(
            context.ContextError,
            "EXTERNALIZED_REF_INVALID: TRUTH_SOURCE_NOT_FOUND",
        ):
            context.externalize_item(
                "EXTERNALIZE-MISSING",
                "FACT-001",
                summary="Detail is external.",
                external_ref=f"file:{self.root.resolve() / 'missing.md'}#detail",
                actor="context-maintainer",
                base_dir=self.base,
            )

        self.assertEqual(events_path.read_bytes(), before_events)
        self.assertEqual(
            json.loads(
                (self.base / "EXTERNALIZE-MISSING" / "snapshot.json")
                .read_text(encoding="utf-8")
            )["items"]["FACT-001"],
            original,
        )

    def test_externalized_reference_drift_blocks_gate_and_identical_retry_is_idempotent(self) -> None:
        self.publish("EXTERNALIZE-DRIFT")
        external_record = self.root / "stable-record.md"
        external_record.write_text("version one", encoding="utf-8")
        context.record(
            "EXTERNALIZE-DRIFT",
            item_id="FACT-001",
            statement="Bulky verified detail",
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "live-readback"},
            metadata={"required": True},
            base_dir=self.base,
        )
        first = context.externalize_item(
            "EXTERNALIZE-DRIFT",
            "FACT-001",
            summary="Detail is in the stable record.",
            external_ref=f"file:{external_record.resolve()}#detail",
            actor="context-maintainer",
            base_dir=self.base,
        )
        events_path = self.base / "EXTERNALIZE-DRIFT" / "events.jsonl"
        event_count = len(events_path.read_text(encoding="utf-8").splitlines())

        retry = context.externalize_item(
            "EXTERNALIZE-DRIFT",
            "FACT-001",
            summary="Detail is in the stable record.",
            external_ref=f"file:{external_record.resolve()}#detail",
            actor="context-maintainer",
            base_dir=self.base,
        )

        self.assertEqual(retry, first)
        self.assertEqual(
            len(events_path.read_text(encoding="utf-8").splitlines()),
            event_count,
        )
        with self.assertRaisesRegex(
            context.ContextError,
            "EXTERNALIZATION_METADATA_IMMUTABLE",
        ):
            context.update_item(
                "EXTERNALIZE-DRIFT",
                "FACT-001",
                actor="context-maintainer",
                metadata={"externalized_ref_digest": "sha256:" + "0" * 64},
                base_dir=self.base,
            )
        self.assertEqual(
            len(events_path.read_text(encoding="utf-8").splitlines()),
            event_count,
        )
        self.assertTrue(
            context.gate(
                "EXTERNALIZE-DRIFT", stage="release", base_dir=self.base, emit=False
            )["passed"]
        )

        external_record.write_text("version two", encoding="utf-8")
        report = context.gate(
            "EXTERNALIZE-DRIFT", stage="release", base_dir=self.base, emit=False
        )
        self.assertFalse(report["passed"])
        self.assertIn(
            "FACT-001: EXTERNALIZED_REF_DIGEST_MISMATCH",
            report["errors"],
        )

    def test_truth_enabled_audit_also_checks_externalized_reference_digest(self) -> None:
        task_id = "EXTERNALIZE-TRUTH"
        workspace = self.root.resolve()
        truth_file = workspace / "truth.md"
        truth_file.write_text("authoritative", encoding="utf-8")
        contract = self.contract(task_id)
        contract["workspace_root"] = str(workspace)
        contract["required_capabilities"] = ["truth-sources/v1"]
        contract["truth_sources"] = {
            "schema": "truth-sources/v1",
            "items": [
                {
                    "id": "TS-STATUS",
                    "purpose": "Authoritative status",
                    "source_ref": {"kind": "file", "locator": "truth.md"},
                    "owner": "publisher",
                    "max_age_seconds": 3600,
                    "validation_method": "owner-readback",
                    "invalidate_on_change_kinds": ["implementation-change"],
                }
            ],
        }
        context.publish_contract(
            contract,
            confirmed_by="publisher",
            base_dir=self.base,
        )
        external_record = workspace / "external-detail.md"
        external_record.write_text("version one", encoding="utf-8")
        context.record(
            task_id,
            item_id="FACT-001",
            statement="Bulky detail",
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "readback"},
            base_dir=self.base,
        )
        context.externalize_item(
            task_id,
            "FACT-001",
            summary="Detail is stored externally.",
            external_ref=f"file:{external_record}#detail",
            actor="context-maintainer",
            base_dir=self.base,
        )

        self.assertTrue(context.audit(task_id, base_dir=self.base, emit=False)["passed"])
        external_record.write_text("version two", encoding="utf-8")
        report = context.audit(task_id, base_dir=self.base, emit=False)
        self.assertFalse(report["passed"])
        self.assertIn(
            "FACT-001: EXTERNALIZED_REF_DIGEST_MISMATCH",
            report["errors"],
        )

    def test_identical_externalize_call_seals_legacy_digest_with_one_event(self) -> None:
        task_id = "EXTERNALIZE-LEGACY"
        self.publish(task_id)
        external_record = self.root.resolve() / "legacy-detail.md"
        external_record.write_text("legacy detail", encoding="utf-8")
        summary = "Legacy detail is stored externally."
        legacy = context.record(
            task_id,
            item_id="FACT-001",
            statement=summary,
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "readback"},
            metadata={
                "required": True,
                "externalized_by": "legacy-maintainer",
                "externalized_at": "2026-09-02T05:30:00+00:00",
                "externalized_ref": f"file:{external_record}#detail",
                "externalized_from_digest": "sha256:" + "1" * 64,
            },
            base_dir=self.base,
        )
        events_path = self.base / task_id / "events.jsonl"
        before_count = len(events_path.read_text(encoding="utf-8").splitlines())
        self.assertFalse(context.audit(task_id, base_dir=self.base, emit=False)["passed"])

        migrated = context.externalize_item(
            task_id,
            "FACT-001",
            summary=summary,
            external_ref=f"file:{external_record}#detail",
            actor="migration-maintainer",
            base_dir=self.base,
        )

        self.assertEqual(migrated["id"], legacy["id"])
        self.assertEqual(migrated["statement"], legacy["statement"])
        self.assertEqual(migrated["actor"], legacy["actor"])
        self.assertEqual(
            migrated["metadata"]["externalized_from_digest"],
            legacy["metadata"]["externalized_from_digest"],
        )
        self.assertRegex(
            migrated["metadata"]["externalized_ref_digest"],
            r"^sha256:[0-9a-f]{64}$",
        )
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(events), before_count + 1)
        self.assertEqual(events[-1]["event_type"], "item-updated")
        self.assertEqual(events[-1]["actor"], "migration-maintainer")
        self.assertTrue(context.audit(task_id, base_dir=self.base, emit=False)["passed"])

    def test_restore_externalization_controls_changes_only_required_and_severity(self) -> None:
        self.publish("RESTORE")
        context.record(
            "RESTORE",
            item_id="OLD",
            statement="Original verified fact",
            item_type="verified-fact",
            actor="observer",
            source={"kind": "tool", "ref": "readback"},
            evidence=["file:/tmp/evidence.json#result"],
            scope={"system": "seed"},
            verification_method="read-back",
            metadata={"required": True, "severity": "high", "owner": "ops"},
            base_dir=self.base,
        )
        target = context.record(
            "RESTORE",
            item_id="STUB",
            statement="See external detail",
            item_type="verified-fact",
            actor="observer",
            source={"kind": "tool", "ref": "readback"},
            evidence=["file:/tmp/evidence.json#result"],
            scope={"system": "seed"},
            verification_method="read-back",
            supersedes="OLD",
            metadata={},
            base_dir=self.base,
        )
        before = deepcopy(target)

        repaired = context.restore_externalization_controls(
            "RESTORE",
            "STUB",
            from_item_id="OLD",
            actor="context-maintainer",
            reason="restore controls lost by legacy externalization",
            base_dir=self.base,
        )

        expected = deepcopy(before)
        expected["metadata"] = {"required": True, "severity": "high"}
        self.assertEqual(repaired, expected)
        events = [
            json.loads(line)
            for line in (self.base / "RESTORE" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(
            events[-1]["payload"]["control_restoration"],
            {
                "from_item_id": "OLD",
                "fields": ["required", "severity"],
                "reason": "restore controls lost by legacy externalization",
            },
        )

    def test_bound_context_survives_cwd_changes_and_reports_storage_origin(self) -> None:
        bound = context.bind(self.base)
        bound.publish_contract(self.contract("BOUND"), confirmed_by="publisher")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            packet = bound.brief("BOUND")
            diagnostics = bound.brief_diagnostics("BOUND")
        finally:
            os.chdir(previous)

        self.assertEqual(packet["task_id"], "BOUND")
        self.assertEqual(diagnostics["storage"]["base_dir_source"], "bound")
        self.assertEqual(diagnostics["storage"]["resolved_base_dir"], str(self.base.resolve()))
        self.assertEqual(
            diagnostics["storage"]["task_root"],
            str((self.base / "BOUND").resolve()),
        )

    def test_missing_task_error_names_resolved_lock_path(self) -> None:
        expected = str((self.base / "MISSING" / ".lock").resolve())

        with self.assertRaises(context.ContextError) as raised:
            context.brief("MISSING", base_dir=self.base)

        self.assertIn(expected, str(raised.exception))

    def test_absolute_environment_base_dir_is_visible_and_relative_value_is_rejected(self) -> None:
        with patch.dict(os.environ, {"MLTC_BASE_DIR": str(self.base.resolve())}):
            context.publish_contract(
                self.contract("ENV-BOUND"),
                confirmed_by="publisher",
            )
            report = context.audit("ENV-BOUND", emit=False)

        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["storage"]["base_dir_source"], "environment")
        self.assertEqual(report["storage"]["resolved_base_dir"], str(self.base.resolve()))

        with patch.dict(os.environ, {"MLTC_BASE_DIR": "relative/context"}):
            with self.assertRaisesRegex(context.ContextError, "MLTC_BASE_DIR_INVALID"):
                context.brief("ENV-BOUND")

    def _ordered_contract(self, task_id: str, *, mode: str = "single-evidence-ordered") -> dict:
        contract = self.contract(task_id)
        contract["required_capabilities"] = ["evidence-handlers/v1"]
        contract["evidence_handlers"] = {
            "schema": "evidence-handlers/v1",
            "types": {
                "integration-test": {
                    "resolver_capability": "test:integration-resolver/v1",
                    "verifier_capability": "test:integration-verifier/v1",
                }
            },
        }
        contract["acceptance_criteria"][0]["required_hops"] = ["export", "snapshot"]
        contract["acceptance_criteria"][0]["required_hops_mode"] = mode
        return contract

    def _completion(self, task_id: str, hop_lists: list[list[str]]) -> dict:
        return context.gate(
            task_id,
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [
                        {
                            "evidence_id": f"EV-{index}",
                            "kind": "integration-test",
                            "covered_hops": hops,
                        }
                        for index, hops in enumerate(hop_lists, start=1)
                    ],
                    "delivery_receipts": [],
                }
            },
            resolvers={
                "integration-test": {
                    "capability": "test:integration-resolver/v1",
                    "handler": passing_resolver,
                }
            },
            verifiers={
                "integration-test": {
                    "capability": "test:integration-verifier/v1",
                    "handler": passing_verifier,
                }
            },
            base_dir=self.base,
            emit=False,
        )

    def test_ordered_hops_require_an_enabled_handler_contract(self) -> None:
        contract = self.contract("ORDERED-NO-HANDLER")
        contract["acceptance_criteria"][0]["required_hops"] = ["export", "snapshot"]
        contract["acceptance_criteria"][0]["required_hops_mode"] = "single-evidence-ordered"

        with self.assertRaisesRegex(
            context.ContextError,
            "single-evidence-ordered requires evidence-handlers/v1",
        ):
            context.publish_contract(
                contract,
                confirmed_by="publisher",
                base_dir=self.base,
            )

        invalid = self._ordered_contract("ORDERED-INVALID", mode="unordered")
        with self.assertRaisesRegex(context.ContextError, "required_hops_mode"):
            context.publish_contract(
                invalid,
                confirmed_by="publisher",
                base_dir=self.base,
            )

    def test_ordered_hops_reject_split_and_reversed_evidence(self) -> None:
        context.publish_contract(
            self._ordered_contract("ORDERED"),
            confirmed_by="publisher",
            base_dir=self.base,
        )

        split = self._completion("ORDERED", [["export"], ["snapshot"]])
        reversed_order = self._completion("ORDERED", [["snapshot", "export"]])

        self.assertFalse(split["passed"])
        self.assertFalse(reversed_order["passed"])
        for report in (split, reversed_order):
            criterion = report["criteria"]["AC-01"]
            self.assertEqual(
                criterion["hop_validation"]["code"],
                "SINGLE_EVIDENCE_ORDERED_HOPS_MISSING",
            )

    def test_ordered_hops_accept_one_passing_ordered_subsequence(self) -> None:
        context.publish_contract(
            self._ordered_contract("ORDERED"),
            confirmed_by="publisher",
            base_dir=self.base,
        )

        report = self._completion(
            "ORDERED", [["prepare", "export", "verify", "snapshot", "archive"]]
        )

        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(
            report["criteria"]["AC-01"]["hop_validation"],
            {
                "mode": "single-evidence-ordered",
                "status": "pass",
                "code": None,
                "evidence_id": "EV-1",
            },
        )

    def test_legacy_aggregate_hops_still_accept_split_evidence(self) -> None:
        contract = self._ordered_contract("AGGREGATE")
        contract["acceptance_criteria"][0].pop("required_hops_mode")
        context.publish_contract(
            contract,
            confirmed_by="publisher",
            base_dir=self.base,
        )

        report = self._completion("AGGREGATE", [["export"], ["snapshot"]])

        self.assertTrue(report["passed"], report["errors"])


if __name__ == "__main__":
    unittest.main()
