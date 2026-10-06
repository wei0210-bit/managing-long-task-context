from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


RECORDED_AT = "2026-10-06T08:00:00+00:00"
UPDATED_AT = "2026-10-06T09:00:00+00:00"


class UpdateItemVerifiedAtTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / ".prime" / "context"
        clock = patch.object(context, "_now", return_value=RECORDED_AT)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        context.publish_contract(
            {
                "schema": 1,
                "task_id": "UPDATE-FACT",
                "version": 1,
                "issued_by": "publisher",
                "issued_at": RECORDED_AT,
                "authorized_approvers": [],
                "objective": "Preserve verification provenance during item updates",
                "scope": ["update_item"],
                "out_of_scope": [],
                "constraints": [],
                "acceptance_criteria": [
                    {
                        "id": "AC-01",
                        "criterion": "Verification provenance is preserved",
                        "required_evidence": ["test-report"],
                    }
                ],
            },
            confirmed_by="publisher",
            base_dir=self.base,
        )
        self.fact = context.record(
            "UPDATE-FACT",
            statement="The callback writes once",
            item_type="verified-fact",
            actor="original-verifier",
            source={"kind": "test-report", "ref": "run-01.json"},
            evidence=["run-01.json"],
            verification_method="Inspect the integration test report",
            scope={"module": "callback"},
            metadata={"priority": "normal"},
            base_dir=self.base,
        )
        self.clock.return_value = UPDATED_AT

    def update(self, **changes) -> dict:
        return context.update_item(
            "UPDATE-FACT",
            self.fact["id"],
            actor="current-editor",
            base_dir=self.base,
            **changes,
        )

    def test_metadata_update_preserves_verification_time(self) -> None:
        updated = self.update(metadata={"priority": "high"})
        self.assertEqual(updated["metadata"], {"priority": "high"})
        self.assertEqual(updated["updated_at"], UPDATED_AT)
        self.assertEqual(updated["verified_at"], RECORDED_AT)

    def test_metadata_update_preserves_original_actor(self) -> None:
        updated = self.update(metadata={"priority": "high"})
        self.assertEqual(updated["actor"], "original-verifier")

    def test_conflicted_status_preserves_verification_time(self) -> None:
        updated = self.update(
            status="conflicted",
            conflicts_with=["run-02.json"],
            conflict_reason="A later report observed two writes",
        )
        self.assertEqual(updated["status"], "conflicted")
        self.assertEqual(updated["verified_at"], RECORDED_AT)

    def test_superseded_status_preserves_verification_time(self) -> None:
        updated = self.update(status="superseded", superseded_by="replacement-fact")
        self.assertEqual(updated["status"], "superseded")
        self.assertEqual(updated["verified_at"], RECORDED_AT)

    def test_new_evidence_refreshes_time_and_preserves_original_actor(self) -> None:
        updated = self.update(evidence=["run-02.json"])
        self.assertEqual(updated["evidence"], ["run-02.json"])
        self.assertEqual(updated["verified_at"], UPDATED_AT)
        self.assertEqual(updated["actor"], "original-verifier")

    def test_new_method_refreshes_time_and_preserves_original_actor(self) -> None:
        updated = self.update(verification_method="Repeat the integration test")
        self.assertEqual(updated["verification_method"], "Repeat the integration test")
        self.assertEqual(updated["verified_at"], UPDATED_AT)
        self.assertEqual(updated["actor"], "original-verifier")

    def test_none_verification_inputs_preserve_verification_time(self) -> None:
        updated = self.update(evidence=None, verification_method=None)
        self.assertEqual(updated["verified_at"], RECORDED_AT)

    def test_update_event_envelope_records_current_editor(self) -> None:
        self.update(metadata={"priority": "high"})
        events = [
            json.loads(line)
            for line in (self.base / "UPDATE-FACT" / "events.jsonl").read_text().splitlines()
        ]
        event = events[-1]
        self.assertEqual(event["event_type"], "item-updated")
        self.assertEqual(event["actor"], "current-editor")
        self.assertEqual(event["payload"]["item"]["id"], self.fact["id"])


if __name__ == "__main__":
    unittest.main()
