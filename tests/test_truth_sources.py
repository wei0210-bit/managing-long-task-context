from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


LEGACY_HASHES = {
    "brief": "sha256:1017b34d7e09589d35c1d6535e7feaeba4d6d9b74706f535084ff355fb75bfd4",
    "contract_file": "sha256:c0fbeee12dcf8486d743c46465d38e91fd952b9ae93381c691282b39190d7892",
    "diagnostics": "sha256:ca9e69d280821cd39d127bfce0837e6909b57f5212f96fc52c86a93b1c2c188f",
    "events_file": "sha256:7d33c3fc8a0abd6cc7942420c3cf86cdf497bd5be1d0f7ae47a231c72f3e65d9",
    "gate_completion": "sha256:caa88b955439ca7e0a90bafdc2be4b6466bab8b795d7bd60cffaff2c9b3d111b",
    "gate_handoff": "sha256:a451310f64c7464896b06a5905e905c6080f300948c58830bd978968b7a5d242",
    "gate_release": "sha256:3d2ef964067cff8e4c50387108cc70e93d8f68caa036ddb9f6520abd409af895",
    "gate_resume": "sha256:533bb8cfcfc8e956141f84148f28e153cfeddfd99422bb6b83b5123e3a330282",
    "seal": "sha256:a80fcf6e033fbdcea3f96f8d12719b92405a9ec3cf203f70636bfef307ba0ab0",
    "snapshot_file": "sha256:1af1f6ee2f763cdb86901a9665b17be14f331669ffeac8db21d905753f3d72b9",
}

LEGACY_CONTRACT = {
    "schema": 1,
    "task_id": "LEGACY-GOLDEN",
    "version": 1,
    "issued_by": "publisher",
    "issued_at": "2026-08-31T02:00:00+00:00",
    "authorized_approvers": [],
    "objective": "Preserve legacy behavior",
    "scope": ["strict context"],
    "out_of_scope": [],
    "constraints": ["no truth sources"],
    "acceptance_criteria": [{
        "id": "AC-01",
        "criterion": "Legacy behavior stays exact",
        "required_evidence_types": ["test-report"],
    }],
}


def _hash_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class LegacyTruthSourceCompatibilityTests(unittest.TestCase):
    maxDiff = None

    def test_legacy_public_reports_and_ledgers_remain_exact(self) -> None:
        now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary_dir, \
             patch.object(context, "_now", return_value=now.isoformat()), \
             patch.object(context, "_trusted_utc_now", return_value=now), \
             patch.object(
                 context.uuid,
                 "uuid4",
                 return_value=uuid.UUID("01234567-89ab-cdef-0123-456789abcdef"),
             ):
            base = Path(temporary_dir) / ".prime" / "context"
            published = context.publish_contract(LEGACY_CONTRACT, confirmed_by="publisher", base_dir=base)
            task_dir = base / "LEGACY-GOLDEN"
            hashes = {
                "brief": _hash_json(context.brief("LEGACY-GOLDEN", base_dir=base)),
                "contract_file": _hash_file(task_dir / "task-contract.json"),
                "diagnostics": _hash_json(context.brief_diagnostics("LEGACY-GOLDEN", base_dir=base)),
                "events_file": _hash_file(task_dir / "events.jsonl"),
                "gate_completion": _hash_json(context.gate("LEGACY-GOLDEN", stage="completion", base_dir=base, emit=False)),
                "gate_handoff": _hash_json(context.gate("LEGACY-GOLDEN", stage="handoff", base_dir=base, emit=False)),
                "gate_release": _hash_json(context.gate("LEGACY-GOLDEN", stage="release", base_dir=base, emit=False)),
                "gate_resume": _hash_json(context.gate("LEGACY-GOLDEN", stage="resume", base_dir=base, emit=False)),
                "seal": published["seal"]["integrity_digest"],
                "snapshot_file": _hash_file(task_dir / "snapshot.json"),
            }

        self.assertEqual(hashes, LEGACY_HASHES)


class ReadOnlyLockingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.addCleanup(self.temp.cleanup)
        context.publish_contract(
            {
                "schema": 1,
                "task_id": "TASK-001",
                "version": 1,
                "issued_by": "publisher",
                "issued_at": "2026-08-31T02:00:00+00:00",
                "authorized_approvers": [],
                "objective": "Keep reads side-effect free",
                "scope": ["strict context"],
                "out_of_scope": [],
                "constraints": [],
                "acceptance_criteria": [{
                    "id": "AC-01",
                    "criterion": "Read behavior is preserved",
                    "required_evidence_types": ["test-report"],
                }],
            },
            confirmed_by="publisher",
            base_dir=self.base,
        )

    def _assert_read_lock_failure(self) -> None:
        for function in (context.audit,):
            report = function("TASK-001", base_dir=self.base, emit=False)
            self.assertFalse(report["passed"])
            self.assertTrue(any("READ_LOCK_UNAVAILABLE" in error for error in report["errors"]))
        for stage in ("release", "resume", "handoff", "completion"):
            report = context.gate("TASK-001", stage=stage, base_dir=self.base, emit=False)
            self.assertFalse(report["passed"])
            self.assertTrue(any("READ_LOCK_UNAVAILABLE" in error for error in report["errors"]))
        with self.assertRaisesRegex(context.ContextError, "READ_LOCK_UNAVAILABLE"):
            context.brief("TASK-001", base_dir=self.base)
        with self.assertRaisesRegex(context.ContextError, "READ_LOCK_UNAVAILABLE"):
            context.brief_diagnostics("TASK-001", base_dir=self.base)

    def test_bad_sample_probe_preserves_stats_without_filesystem_writes(self) -> None:
        with patch("tempfile.TemporaryDirectory", side_effect=AssertionError("probe wrote temp state")):
            report = context.audit("TASK-001", base_dir=self.base, emit=False)
        self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
        self.assertEqual(report["stats"]["probe_scanned"], 1)
        self.assertEqual(report["stats"]["probe"], "pass")

    def test_missing_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        (task_dir / ".lock").unlink()
        before = sorted(task_dir.iterdir())
        self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_unreadable_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        lock_path = task_dir / ".lock"
        before = sorted(task_dir.iterdir())
        original_open = Path.open

        def unreadable(path: Path, *args, **kwargs):
            if path == lock_path or path.name == ".lock":
                raise OSError("denied for test")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=unreadable):
            self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_unsupported_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        before = sorted(task_dir.iterdir())
        with patch.object(context, "fcntl", None):
            self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_read_apis_make_no_write_calls(self) -> None:
        calls = (context.audit, context.brief, context.brief_diagnostics)
        with patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")), \
             patch.object(context, "_atomic_write_json", side_effect=AssertionError("write")), \
             patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temp")):
            for function in calls:
                if function is context.audit:
                    function("TASK-001", base_dir=self.base, emit=False)
                else:
                    function("TASK-001", base_dir=self.base)
            context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)

    def test_exclusive_writer_cannot_finish_while_shared_lock_is_held(self) -> None:
        root = self.base / "TASK-001"
        writer_started = threading.Event()
        writer_finished = threading.Event()

        def writer() -> None:
            writer_started.set()
            with context._locked(root):
                writer_finished.set()

        with context._shared_locked_existing(root):
            thread = threading.Thread(target=writer)
            thread.start()
            self.assertTrue(writer_started.wait(2))
            self.assertFalse(writer_finished.wait(2))
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(writer_finished.is_set())


if __name__ == "__main__":
    unittest.main()
