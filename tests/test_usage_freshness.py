from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from managing_long_task_context.usage_freshness import usage_freshness_report


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class UsageFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _write_ledger(
        self,
        *,
        event_at: datetime,
        checkpoint_at: datetime,
        version: int = 5,
    ) -> None:
        (self.root / "task-contract.json").write_text(
            json.dumps({"schema": 1, "task_id": "H3", "version": version}),
            encoding="utf-8",
        )
        (self.root / "events.jsonl").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "event_id": "E-1",
                    "task_id": "H3",
                    "event_type": "note",
                    "actor": "tester",
                    "created_at": event_at.isoformat().replace("+00:00", "Z"),
                    "payload": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "snapshot.json").write_text(
            json.dumps(
                {
                    "latest_checkpoint": {
                        "created_at": checkpoint_at.isoformat().replace("+00:00", "Z")
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.root / ".lock").write_text("", encoding="utf-8")
        (self.root / "handoff").mkdir()
        (self.root / "handoff" / "note.txt").write_text("ledger", encoding="utf-8")

    def _codes(self, report: dict) -> list[str]:
        return [item["code"] for item in report["warnings"]]

    def _tree_bytes(self) -> dict[str, bytes]:
        snapshot: dict[str, bytes] = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root).as_posix()
            if path.is_symlink():
                snapshot[relative] = b"symlink:" + os.readlink(path).encode()
            elif path.is_file():
                snapshot[relative] = path.read_bytes()
            elif path.is_dir():
                snapshot[relative] = b"dir"
        return snapshot

    def test_newer_regular_file_is_ledger_activity(self) -> None:
        event_at = NOW - timedelta(hours=2)
        self._write_ledger(event_at=event_at, checkpoint_at=NOW - timedelta(hours=1))
        extra = self.root / "notes.txt"
        extra.write_text("newer", encoding="utf-8")
        os.utime(extra, (NOW.timestamp(), NOW.timestamp()))
        report = usage_freshness_report(self.root, now=NOW)
        self.assertIn("LEDGER_ACTIVITY", self._codes(report))
        self.assertEqual(report["stats"]["ledger_newer_files"], 1)

    def test_ledger_only_has_no_ledger_activity(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=2),
            checkpoint_at=NOW - timedelta(hours=1),
        )
        report = usage_freshness_report(self.root, now=NOW)
        self.assertNotIn("LEDGER_ACTIVITY", self._codes(report))
        self.assertEqual(report["stats"]["ledger_newer_files"], 0)

    def test_checkpoint_73_hours_old_is_unknown_gap(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=74),
            checkpoint_at=NOW - timedelta(hours=73),
        )
        report = usage_freshness_report(self.root, now=NOW)
        self.assertEqual(report["status"], "unknown")
        self.assertIn("CHECKPOINT_GAP", self._codes(report))

    def test_fresh_checkpoint_version_five_and_no_extra_files_passes(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=1),
            checkpoint_at=NOW - timedelta(hours=1),
            version=5,
        )
        report = usage_freshness_report(self.root, now=NOW)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["stats"]["contract_version"], 5)
        self.assertEqual(report["stats"]["checkpoint_age_hours"], 1.0)

    def test_version_six_warns_contract_cap(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=1),
            checkpoint_at=NOW - timedelta(hours=1),
            version=6,
        )
        report = usage_freshness_report(self.root, now=NOW)
        self.assertIn("CONTRACT_VERSION_CAP", self._codes(report))

    def test_stray_names_match_finder_copies_only(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=1),
            checkpoint_at=NOW - timedelta(hours=1),
        )
        older = (NOW - timedelta(hours=2)).timestamp()
        for name in ("notes 2.md", ".DS_Store", "chapter 20.py", "notes 2.1.md"):
            path = self.root / name
            path.write_text("x", encoding="utf-8")
            os.utime(path, (older, older))
        report = usage_freshness_report(self.root, now=NOW)
        stray = [item["message"] for item in report["warnings"] if item["code"] == "STRAY_NAME"]
        self.assertIn("stray name: notes 2.md", stray)
        self.assertIn("stray name: .DS_Store", stray)
        self.assertNotIn("stray name: chapter 20.py", stray)
        self.assertNotIn("stray name: notes 2.1.md", stray)

    def test_report_does_not_change_directory_bytes(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=1),
            checkpoint_at=NOW - timedelta(hours=1),
        )
        before = self._tree_bytes()
        usage_freshness_report(self.root, now=NOW)
        self.assertEqual(self._tree_bytes(), before)

    def test_missing_directory_is_unknown_without_exception(self) -> None:
        missing = self.root / "absent"
        report = usage_freshness_report(missing, now=NOW)
        self.assertEqual(report["status"], "unknown")
        self.assertFalse(missing.exists())

    def test_naive_now_raises_value_error(self) -> None:
        self._write_ledger(
            event_at=NOW - timedelta(hours=1),
            checkpoint_at=NOW - timedelta(hours=1),
        )
        with self.assertRaises(ValueError):
            usage_freshness_report(self.root, now=datetime(2026, 9, 22, 12, 0))


if __name__ == "__main__":
    unittest.main()
