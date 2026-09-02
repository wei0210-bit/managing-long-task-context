from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


NOW = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)


def passing_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "pass", "codes": []},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
    }


def passing_verifier(evidence, criterion, resolution):
    return {"status": "pass", "codes": []}


class DynamicContextScenarioTests(unittest.TestCase):
    def test_state_changes_overflow_conflict_handoff_and_ordered_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir, patch.object(
            context, "_trusted_utc_now", return_value=NOW
        ):
            root = Path(temporary_dir)
            base = root / ".prime" / "context"
            bound = context.bind(base)
            task_id = "DYNAMIC-001"
            contract = {
                "schema": 1,
                "task_id": task_id,
                "version": 1,
                "issued_by": "publisher",
                "issued_at": "2026-09-02T06:00:00Z",
                "authorized_approvers": [],
                "workspace_root": str(root),
                "objective": "Exercise context controls across changing task state",
                "scope": ["dynamic scenario"],
                "out_of_scope": [],
                "constraints": ["no external side effects"],
                "required_capabilities": ["evidence-handlers/v1"],
                "evidence_handlers": {
                    "schema": "evidence-handlers/v1",
                    "types": {
                        "integration-test": {
                            "resolver_capability": "scenario:resolver/v1",
                            "verifier_capability": "scenario:verifier/v1",
                        }
                    },
                },
                "acceptance_criteria": [
                    {
                        "id": "AC-01",
                        "criterion": "One execution proves export before snapshot",
                        "required_evidence_types": ["integration-test"],
                        "required_hops": ["export", "snapshot"],
                        "required_hops_mode": "single-evidence-ordered",
                        "required_delivery_types": [],
                        "independent_validation_required": False,
                    }
                ],
            }
            bound.publish_contract(contract, confirmed_by="publisher")
            contract_path = base / task_id / "task-contract.json"
            self.assertEqual(stat.S_IMODE(contract_path.stat().st_mode) & 0o222, 0)

            bound.record(
                task_id,
                item_id="REQUIRED-LARGE",
                statement="R" * 9000,
                item_type="observation",
                actor="executor",
                source={"kind": "tool", "ref": "live-probe"},
                metadata={"required": True, "severity": "critical"},
            )
            handlers = {
                "resolvers": {
                    "integration-test": {
                        "capability": "scenario:resolver/v1",
                        "handler": passing_resolver,
                    }
                },
                "verifiers": {
                    "integration-test": {
                        "capability": "scenario:verifier/v1",
                        "handler": passing_verifier,
                    }
                },
            }
            self.assertFalse(bound.gate(task_id, stage="release", emit=False, **handlers)["passed"])

            bound.externalize_item(
                task_id,
                "REQUIRED-LARGE",
                summary="Required live probe is stored in the stable external record.",
                external_ref="file:/tmp/dynamic-context.md#required-live-probe",
                actor="context-maintainer",
            )
            self.assertTrue(bound.gate(task_id, stage="release", emit=False, **handlers)["passed"])

            conflict = bound.record(
                task_id,
                item_id="CONFLICT",
                statement="The export status is disputed",
                item_type="observation",
                actor="executor",
                source={"kind": "tool", "ref": "probe-a"},
            )
            bound.update_item(
                task_id,
                conflict["id"],
                actor="validator",
                status="conflicted",
                conflicts_with=["probe-b"],
                conflict_reason="probe-a and probe-b disagree",
            )
            self.assertFalse(bound.gate(task_id, stage="resume", emit=False, **handlers)["passed"])
            bound.record(
                task_id,
                item_id="CONFLICT-RESOLVED",
                statement="Readback confirms the export is complete",
                item_type="verified-fact",
                actor="validator",
                source={"kind": "tool", "ref": "probe-c"},
                evidence=["probe-c:readback"],
                scope={"scenario": "dynamic"},
                verification_method="read-back",
                supersedes="CONFLICT",
            )

            bound.checkpoint(
                task_id,
                phase="verified",
                completed=["externalized detail", "resolved conflict"],
                evidence_added=["probe-c:readback"],
                next_action="run ordered completion gate",
                actor="executor",
            )
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(elsewhere)
                handoff = bound.gate(task_id, stage="handoff", emit=False, **handlers)
                split = bound.gate(
                    task_id,
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [
                                {"evidence_id": "EV-EXPORT", "kind": "integration-test", "covered_hops": ["export"]},
                                {"evidence_id": "EV-SNAPSHOT", "kind": "integration-test", "covered_hops": ["snapshot"]},
                            ],
                            "delivery_receipts": [],
                        }
                    },
                    emit=False,
                    **handlers,
                )
                complete = bound.gate(
                    task_id,
                    stage="completion",
                    evidence_map={
                        "AC-01": {
                            "evidence": [
                                {
                                    "evidence_id": "EV-ORDERED",
                                    "kind": "integration-test",
                                    "covered_hops": ["prepare", "export", "verify", "snapshot"],
                                }
                            ],
                            "delivery_receipts": [],
                        }
                    },
                    emit=False,
                    **handlers,
                )
            finally:
                os.chdir(previous)

            self.assertTrue(handoff["passed"], handoff["errors"])
            self.assertEqual(handoff["storage"]["base_dir_source"], "bound")
            self.assertFalse(split["passed"])
            self.assertTrue(complete["passed"], complete["errors"])


if __name__ == "__main__":
    unittest.main()
