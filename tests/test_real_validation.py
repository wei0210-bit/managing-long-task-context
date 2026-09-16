"""Behavior tests for prospective real-validation evidence recording."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "real_validation.py"


def observation() -> dict[str, object]:
    return {
        "schema": "real-validation-observation/v1",
        "observation_id": "OBS-20260916-001",
        "task_id": "TASK-REAL-001",
        "started_at": "2026-09-16T03:00:00Z",
        "sampling": "prospective",
        "project": {
            "root": "/private/tmp/real-project",
            "revision": "git:097c952e37e7f971274e70579c33c2727cc67fb0",
            "dirty": False,
        },
        "skill": {
            "selection": "strict",
            "package_root": "/Users/example/.codex/skills/context-strict",
            "skill_version": "0.8.0",
            "manifest_sha256": "a" * 64,
        },
        "host": {
            "provider": "codex-desktop",
            "interface": "native",
            "session_id": None,
            "identity_evidence_ref": None,
        },
        "execution": {
            "model": "model-a",
            "reasoning_effort": "high",
            "configuration_ref": "host-config:task-real-001",
        },
        "comparison": {
            "group_id": "GROUP-REAL-001",
            "task_definition_ref": "repo:fixtures/task-real-001.json@097c952",
        },
        "claims": {
            "native_host_takeover": "NOT_RUN",
            "natural_project_effect": "UNKNOWN",
            "token_cost_benefit": "UNKNOWN",
        },
        "acceptance_refs": [
            "repo:docs/superpowers/plans/short-session-handoff.md@097c952"
        ],
        "privacy": {"raw_content_retained": False, "secrets_retained": False},
    }


def event(event_id: str, event_type: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "real-validation-event/v1",
        "event_id": event_id,
        "observation_id": "OBS-20260916-001",
        "task_id": "TASK-REAL-001",
        "event_type": event_type,
        "observed_at": "2026-09-16T03:10:00Z",
        "actor": "observer-01",
        "source_refs": ["repo:docs/validation/source.json@097c952"],
        "payload": payload,
    }


class RealValidationRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = self.base / "store"

    def _write(self, name: str, value: object) -> Path:
        path = self.base / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return path

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _start(self) -> dict[str, object]:
        supplied = self._write("observation.json", observation())
        result = self._run("start", "--root", str(self.store), "--input", str(supplied))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def _record(self, value: dict[str, object]) -> subprocess.CompletedProcess[str]:
        supplied = self._write(f"{value['event_id']}.json", value)
        return self._run(
            "record",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
            "--input",
            str(supplied),
        )

    def test_start_creates_read_only_observation_and_unknown_claim_status(self) -> None:
        receipt = self._start()
        status = self._run(
            "status",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
        )

        self.assertEqual(receipt["status"], "ok")
        metadata = self.store / "OBS-20260916-001" / "observation.json"
        self.assertTrue(metadata.is_file())
        self.assertEqual(stat.S_IMODE(metadata.stat().st_mode), 0o444)
        self.assertEqual(status.returncode, 0, status.stderr or status.stdout)
        report = json.loads(status.stdout)
        self.assertEqual(
            report["claims"],
            {
                "native_host_takeover": "UNKNOWN",
                "natural_project_effect": "UNKNOWN",
                "token_cost_benefit": "UNKNOWN",
            },
        )
        self.assertEqual(report["event_counts"], {})

    def test_start_is_idempotent_and_rejects_conflicting_observation(self) -> None:
        self._start()
        same = self._write("same-observation.json", observation())
        repeated = self._run(
            "start", "--root", str(self.store), "--input", str(same)
        )
        conflicting_value = observation()
        conflicting_value["project"] = dict(conflicting_value["project"], dirty=True)
        conflicting = self._write("conflicting-observation.json", conflicting_value)
        conflict = self._run(
            "start", "--root", str(self.store), "--input", str(conflicting)
        )

        self.assertEqual(repeated.returncode, 0)
        self.assertEqual(json.loads(repeated.stdout)["status"], "duplicate")
        self.assertEqual(conflict.returncode, 2)
        self.assertEqual(
            json.loads(conflict.stdout)["code"], "OBSERVATION_ID_CONFLICT"
        )

    def test_concurrent_same_start_has_one_create_and_one_duplicate(self) -> None:
        supplied = self._write("concurrent-observation.json", observation())
        command = [
            sys.executable,
            str(SCRIPT),
            "start",
            "--root",
            str(self.store),
            "--input",
            str(supplied),
        ]
        processes = [
            subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE)
            for _ in range(2)
        ]
        results = [process.communicate(timeout=10) for process in processes]

        self.assertEqual([process.returncode for process in processes], [0, 0])
        statuses = sorted(json.loads(stdout)["status"] for stdout, _ in results)
        self.assertEqual(statuses, ["duplicate", "ok"])

    def test_native_success_is_material_but_never_an_automatic_verified_claim(self) -> None:
        self._start()
        native = event(
            "EV-NATIVE-001",
            "native_control",
            {
                "operation": "transfer_control",
                "outcome": "succeeded",
                "trigger_mode": "automatic",
                "trigger_evidence_ref": "host-trigger:auto-001",
                "source_session_ref": "host-session:source",
                "target_session_ref": "host-session:target",
                "identity_verified": True,
                "write_fencing_verified": True,
                "clean_history_verified": True,
                "parent_survival_verified": True,
                "cross_parent_continuation_verified": True,
                "predecessor_retained_until_success": True,
            },
        )
        recorded = self._record(native)
        status = self._run(
            "status",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
        )

        self.assertEqual(recorded.returncode, 0, recorded.stderr or recorded.stdout)
        report = json.loads(status.stdout)
        self.assertEqual(report["event_counts"], {"native_control": 1})
        self.assertTrue(report["material_available"]["native_host_takeover"])
        self.assertEqual(report["claims"]["native_host_takeover"], "UNKNOWN")

    def test_record_is_idempotent_for_same_event_and_rejects_conflicting_reuse(self) -> None:
        self._start()
        boundary = event(
            "EV-BOUNDARY-001",
            "boundary",
            {
                "claim_status": {
                    "native_host_takeover": "NOT_RUN",
                    "natural_project_effect": "UNKNOWN",
                    "token_cost_benefit": "UNKNOWN",
                },
                "reason": "Recording began before any native takeover attempt.",
            },
        )
        first = self._record(boundary)
        repeated = self._record(boundary)
        conflicting = dict(boundary)
        conflicting["payload"] = dict(boundary["payload"], reason="Different claim")
        conflict = self._record(conflicting)

        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        self.assertEqual(json.loads(repeated.stdout)["status"], "duplicate")
        self.assertEqual(conflict.returncode, 2)
        self.assertEqual(json.loads(conflict.stdout)["code"], "EVENT_ID_CONFLICT")

    def test_concurrent_same_event_has_one_create_and_one_duplicate(self) -> None:
        self._start()
        supplied = event(
            "EV-CONCURRENT-001",
            "boundary",
            {
                "claim_status": {
                    "native_host_takeover": "NOT_RUN",
                    "natural_project_effect": "UNKNOWN",
                    "token_cost_benefit": "UNKNOWN",
                },
                "reason": "Concurrent retries must converge on one immutable event.",
            },
        )
        path = self._write("concurrent.json", supplied)
        command = [
            sys.executable,
            str(SCRIPT),
            "record",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
            "--input",
            str(path),
        ]
        processes = [
            subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE)
            for _ in range(2)
        ]
        results = [process.communicate(timeout=10) for process in processes]

        self.assertEqual([process.returncode for process in processes], [0, 0])
        statuses = sorted(json.loads(stdout)["status"] for stdout, _ in results)
        self.assertEqual(statuses, ["duplicate", "ok"])
        event_path = (
            self.store
            / "OBS-20260916-001"
            / "events"
            / "EV-CONCURRENT-001.json"
        )
        self.assertEqual(stat.S_IMODE(event_path.stat().st_mode), 0o444)

    def test_natural_usage_and_cost_events_remain_raw_material_not_benefit_proof(self) -> None:
        self._start()
        task = event(
            "EV-TASK-001",
            "task_outcome",
            {
                "natural_project": True,
                "skill_selection": "strict",
                "outcome": "completed",
                "acceptance": "pass",
                "extra_turns": 1,
                "retries": 0,
                "manual_corrections": 0,
            },
        )
        usage = event(
            "EV-USAGE-001",
            "usage",
            {
                "event_id": "PROVIDER-USAGE-001",
                "session_id": "SESSION-001",
                "task_id": "TASK-REAL-001",
                "provider": "provider-a",
                "model": "model-a",
                "reasoning_effort": "high",
                "mode": "delta",
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_tokens": 20,
                "cache_write_tokens": 0,
                "cache_accounting": "included",
                "source_ref": "provider-receipt:usage-001",
                "observed_at": "2026-09-16T03:10:00Z",
            },
        )
        cost = event(
            "EV-COST-001",
            "cost",
            {
                "provider": "provider-a",
                "currency": "USD",
                "amount": "0.1234",
                "billing_scope": "partial",
                "includes_retries": None,
                "skill_attribution": "unknown",
            },
        )
        for supplied in (task, usage, cost):
            result = self._record(supplied)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

        status = self._run(
            "status",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
        )
        report = json.loads(status.stdout)
        self.assertEqual(
            report["event_counts"], {"cost": 1, "task_outcome": 1, "usage": 1}
        )
        self.assertTrue(report["material_available"]["natural_project_effect"])
        self.assertTrue(report["material_available"]["token_cost_benefit"])
        self.assertEqual(report["claims"]["natural_project_effect"], "UNKNOWN")
        self.assertEqual(report["claims"]["token_cost_benefit"], "UNKNOWN")

    def test_rejects_duplicate_json_keys_symlink_inputs_and_secret_fields(self) -> None:
        duplicate = self.base / "duplicate.json"
        duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
        duplicate_result = self._run(
            "start", "--root", str(self.store), "--input", str(duplicate)
        )

        valid = self._write("valid.json", observation())
        linked = self.base / "linked.json"
        linked.symlink_to(valid)
        symlink_result = self._run(
            "start", "--root", str(self.store), "--input", str(linked)
        )

        unsafe = observation()
        unsafe["access_token"] = "must-not-be-retained"
        unsafe_result = self._run(
            "start",
            "--root",
            str(self.store),
            "--input",
            str(self._write("unsafe.json", unsafe)),
        )

        self.assertEqual(duplicate_result.returncode, 2)
        self.assertEqual(json.loads(duplicate_result.stdout)["code"], "JSON_DUPLICATE_KEY")
        self.assertEqual(symlink_result.returncode, 2)
        self.assertEqual(json.loads(symlink_result.stdout)["code"], "INPUT_NOT_REGULAR")
        self.assertEqual(unsafe_result.returncode, 2)
        self.assertEqual(json.loads(unsafe_result.stdout)["code"], "SENSITIVE_FIELD")

    def test_invalid_usage_numbers_fail_closed_without_a_traceback(self) -> None:
        self._start()
        supplied = event(
            "EV-USAGE-BAD",
            "usage",
            {
                "event_id": "PROVIDER-USAGE-BAD",
                "session_id": "SESSION-001",
                "task_id": "TASK-REAL-001",
                "provider": "provider-a",
                "model": "model-a",
                "reasoning_effort": "high",
                "mode": "delta",
                "input_tokens": None,
                "output_tokens": 10,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_accounting": "included",
                "source_ref": "provider-receipt:usage-bad",
                "observed_at": "2026-09-16T03:10:00Z",
            },
        )

        result = self._record(supplied)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "FIELD_INVALID")
        self.assertNotIn("Traceback", result.stderr)

    def test_rejects_event_store_symlink_without_writing_through_it(self) -> None:
        self._start()
        observation_dir = self.store / "OBS-20260916-001"
        events_dir = observation_dir / "events"
        events_dir.rmdir()
        escape = self.base / "escape"
        escape.mkdir()
        events_dir.symlink_to(escape, target_is_directory=True)
        supplied = event(
            "EV-BOUNDARY-ESCAPE",
            "boundary",
            {
                "claim_status": {
                    "native_host_takeover": "NOT_RUN",
                    "natural_project_effect": "UNKNOWN",
                    "token_cost_benefit": "UNKNOWN",
                },
                "reason": "The event store must not redirect this write.",
            },
        )

        result = self._record(supplied)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "EVENT_STORE_NOT_DIRECTORY")
        self.assertFalse((escape / "EV-BOUNDARY-ESCAPE.json").exists())

    def test_status_fails_closed_on_unexpected_event_store_entry(self) -> None:
        self._start()
        unexpected = self.store / "OBS-20260916-001" / "events" / "notes.txt"
        unexpected.write_text("not an event", encoding="utf-8")

        result = self._run(
            "status",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "EVENT_STORE_SHAPE")

    def test_duplicate_start_fails_closed_when_event_store_is_missing(self) -> None:
        self._start()
        events = self.store / "OBS-20260916-001" / "events"
        events.rmdir()
        supplied = self._write("same-observation.json", observation())

        result = self._run(
            "start", "--root", str(self.store), "--input", str(supplied)
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stdout)["code"], "EVENT_STORE_NOT_DIRECTORY"
        )

    def test_rejects_broken_root_symlink_without_creating_its_target(self) -> None:
        target = self.base / "outside" / "store"
        linked_root = self.base / "linked-store"
        linked_root.symlink_to(target, target_is_directory=True)
        supplied = self._write("observation.json", observation())

        result = self._run(
            "start", "--root", str(linked_root), "--input", str(supplied)
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "ROOT_SYMLINK")
        self.assertFalse(target.exists())

    def test_manual_native_success_is_not_automatic_takeover_material(self) -> None:
        self._start()
        manual = event(
            "EV-NATIVE-MANUAL",
            "native_control",
            {
                "operation": "transfer_control",
                "outcome": "succeeded",
                "trigger_mode": "manual",
                "trigger_evidence_ref": None,
                "source_session_ref": "host-session:source",
                "target_session_ref": "host-session:target",
                "identity_verified": True,
                "write_fencing_verified": True,
                "clean_history_verified": True,
                "parent_survival_verified": True,
                "cross_parent_continuation_verified": True,
                "predecessor_retained_until_success": True,
            },
        )

        recorded = self._record(manual)
        status = self._run(
            "status",
            "--root",
            str(self.store),
            "--observation-id",
            "OBS-20260916-001",
        )

        self.assertEqual(recorded.returncode, 0, recorded.stderr or recorded.stdout)
        report = json.loads(status.stdout)
        self.assertFalse(report["material_available"]["native_host_takeover"])
        self.assertEqual(report["claims"]["native_host_takeover"], "UNKNOWN")

    def test_rejects_incomplete_native_success_and_invalid_usage_boundaries(self) -> None:
        self._start()
        incomplete = event(
            "EV-NATIVE-INCOMPLETE",
            "native_control",
            {
                "operation": "transfer_control",
                "outcome": "succeeded",
                "trigger_mode": "automatic",
                "trigger_evidence_ref": "host-trigger:auto-incomplete",
                "source_session_ref": "host-session:source",
                "target_session_ref": "host-session:target",
                "identity_verified": True,
                "write_fencing_verified": True,
                "clean_history_verified": False,
                "parent_survival_verified": True,
                "cross_parent_continuation_verified": True,
                "predecessor_retained_until_success": True,
            },
        )
        usage = event(
            "EV-USAGE-OVERFLOW",
            "usage",
            {
                "event_id": "PROVIDER-USAGE-OVERFLOW",
                "session_id": "SESSION-001",
                "task_id": "TASK-REAL-001",
                "provider": "provider-a",
                "model": "model-a",
                "reasoning_effort": "high",
                "mode": "delta",
                "input_tokens": 10,
                "output_tokens": 1,
                "cache_read_tokens": 11,
                "cache_write_tokens": 0,
                "cache_accounting": "included",
                "source_ref": "provider-receipt:usage-overflow",
                "observed_at": "2026-09-16T03:10:00Z",
            },
        )

        native_result = self._record(incomplete)
        usage_result = self._record(usage)

        self.assertEqual(native_result.returncode, 2)
        self.assertEqual(
            json.loads(native_result.stdout)["code"], "NATIVE_SUCCESS_INCOMPLETE"
        )
        self.assertEqual(usage_result.returncode, 2)
        self.assertEqual(
            json.loads(usage_result.stdout)["code"], "USAGE_CACHE_EXCEEDS_INPUT"
        )

    def test_rejects_usage_task_mismatch_and_invalid_cost(self) -> None:
        self._start()
        usage = event(
            "EV-USAGE-WRONG-TASK",
            "usage",
            {
                "event_id": "PROVIDER-USAGE-WRONG-TASK",
                "session_id": "SESSION-001",
                "task_id": "TASK-OTHER",
                "provider": "provider-a",
                "model": "model-a",
                "reasoning_effort": "high",
                "mode": "delta",
                "input_tokens": 10,
                "output_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_accounting": "included",
                "source_ref": "provider-receipt:wrong-task",
                "observed_at": "2026-09-16T03:10:00Z",
            },
        )
        cost = event(
            "EV-COST-INVALID",
            "cost",
            {
                "provider": "provider-a",
                "currency": "usd",
                "amount": "-1",
                "billing_scope": "full-task",
                "includes_retries": True,
                "skill_attribution": "full",
            },
        )

        usage_result = self._record(usage)
        cost_result = self._record(cost)

        self.assertEqual(usage_result.returncode, 2)
        self.assertEqual(json.loads(usage_result.stdout)["code"], "TASK_MISMATCH")
        self.assertEqual(cost_result.returncode, 2)
        self.assertEqual(json.loads(cost_result.stdout)["code"], "FIELD_INVALID")


if __name__ == "__main__":
    unittest.main()
