"""E1-03 public-seam recovery probes using independent Python processes.

The helpers intentionally exercise only prepare_handoff, activate_handoff and
handoff_status.  Faults are injected at real os.fsync/os.replace boundaries;
no private commit helper is mocked or made to report success.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import queue
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
FIXTURE = ROOT / "tests" / "handoff_process_fixture.py"


class HandoffProcessRecoveryTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "host"
        self.config_path = Path(self.temporary.name) / "fixture.json"
        self.config: dict[str, object] = {"root": str(self.root), "config_path": str(self.config_path)}
        self._child_output: dict[int, tuple[queue.Queue[str | None], threading.Thread]] = {}
        self._cleaned_children: set[int] = set()
        self._write_config()
        bootstrap = self._run("bootstrap")
        self.assertEqual(bootstrap.returncode, 0, (bootstrap.stderr, bootstrap.lines))
        self.assertEqual(bootstrap.lines[-1]["stage"], "bootstrap", bootstrap.lines)
        self.assertEqual(bootstrap.lines[-1]["result"]["check_status"], "pass", bootstrap.lines)

    def _write_config(self) -> None:
        self.config_path.write_text(json.dumps(self.config, sort_keys=True), encoding="utf-8")

    def _command(self, command: str, *, config_path: Path | None = None) -> list[str]:
        return [PYTHON, str(FIXTURE), command, str(config_path or self.config_path)]

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = "src:tests"
        return environment

    def _run(self, command: str, *, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            self._command(command), cwd=ROOT, env=self._environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
        )
        result.lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]  # type: ignore[attr-defined]
        return result

    def _spawn_activate(self, *, fault: str = "none", request_id: str = "REQ-PROCESS-ACTIVATE", barrier_path: Path | None = None, gate_path: Path | None = None, config_path: Path | None = None) -> subprocess.Popen[str]:
        target_config_path = config_path or self.config_path
        child_config = self.config if config_path is None else dict(self.config)
        child_config.update({"fault": fault, "request_id": request_id, "config_path": str(target_config_path)})
        if barrier_path is not None:
            child_config["barrier_path"] = str(barrier_path)
        else:
            child_config.pop("barrier_path", None)
        if gate_path is not None:
            child_config["gate_path"] = str(gate_path)
        else:
            child_config.pop("gate_path", None)
        target_config_path.write_text(json.dumps(child_config, sort_keys=True), encoding="utf-8")
        process = subprocess.Popen(
            self._command("activate", config_path=target_config_path), cwd=ROOT, env=self._environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        self.assertIsNotNone(process.stdout)
        lines: queue.Queue[str | None] = queue.Queue()

        def collect() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        self._child_output[id(process)] = (lines, reader)
        # Register immediately: an assertion in _next_phase must not strand a
        # FIFO-blocked child merely because _finish was never reached.
        self.addCleanup(self._cleanup_child, process)
        return process

    def _cleanup_child(self, process: subprocess.Popen[str]) -> None:
        """Idempotently reap a child and its pipes on every test exit path."""
        marker = id(process)
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill already issued
            self.fail("child did not exit after forced cleanup")
        output = self._child_output.get(marker)
        if output is not None:
            _queue, reader = output
            reader.join(timeout=5)
            if reader.is_alive():  # pragma: no cover - pipe should close after wait
                self.fail("stdout collector did not exit during cleanup")
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()
        self._cleaned_children.add(marker)

    def _next_phase(self, process: subprocess.Popen[str], *, timeout: float = 5.0) -> dict[str, object]:
        lines, _reader = self._child_output[id(process)]
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            self.fail(f"child did not reach observable phase; rc={process.poll()}")
        self.assertIsNotNone(line, f"child stdout closed before phase; rc={process.poll()}")
        return json.loads(line)

    def _finish(self, process: subprocess.Popen[str], *, timeout: float = 5.0) -> tuple[int, list[dict[str, object]], str]:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
            stderr = process.stderr.read() if process.stderr is not None else ""
            self.fail(f"child deadlocked; stderr={stderr}")
        output, reader = self._child_output[id(process)]
        reader.join(timeout=timeout)
        self.assertFalse(reader.is_alive(), "stdout collector did not finish")
        raw_lines: list[str] = []
        while True:
            try:
                line = output.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                raw_lines.append(line)
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        lines = [json.loads(line) for line in raw_lines if line.strip()]
        return process.returncode, lines, stderr

    @property
    def task_root(self) -> Path:
        return self.root / "context" / "TASK-PROCESS-001"

    def _events(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in (self.task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def _activation_count(self) -> int:
        return sum(event["event_type"] == "handoff_activated" for event in self._events())

    def _status(self) -> subprocess.CompletedProcess[str]:
        completed = self._run("status")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.lines[-1]["stage"], "status", completed.lines)
        return completed

    def test_normal_child_activation_is_one_durable_fact_with_reviewable_output(self) -> None:
        completed = self._run("activate")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = completed.lines[-1]
        self.assertEqual(result["stage"], "result", completed.lines)
        self.assertEqual(result["business_actions"], 0, completed.lines)
        self.assertEqual(result["result"]["check_status"], "pass", result)
        self.assertEqual(result["result"]["controller_generation"], 1, result)
        self.assertEqual(self._activation_count(), 1)
        status = self._status().lines[-1]["result"]
        self.assertEqual(status["commit_status"], "confirmed_committed", status)
        self.assertEqual(status["controller_generation"], 1, status)

    def test_two_real_processes_at_a_named_barrier_commit_at_most_one_activation(self) -> None:
        barrier = Path(self.temporary.name) / "activate-barrier"
        os.mkfifo(barrier)
        first = self._spawn_activate(barrier_path=barrier)
        second = self._spawn_activate(barrier_path=barrier)
        self.assertEqual(self._next_phase(first)["stage"], "ready")
        self.assertEqual(self._next_phase(second)["stage"], "ready")
        with barrier.open("wb", buffering=0) as release:
            release.write(b"GG")
        first_rc, first_lines, first_err = self._finish(first)
        second_rc, second_lines, second_err = self._finish(second)

        self.assertIn(first_rc, {0, 3}, first_err)
        self.assertIn(second_rc, {0, 3}, second_err)
        self.assertTrue(first_lines and second_lines, (first_lines, second_lines))
        self.assertEqual(self._activation_count(), 1)
        self.assertEqual(self._status().lines[-1]["result"]["controller_generation"], 1)
        before = (self.task_root / "events.jsonl").read_bytes()
        self.config.pop("barrier_path", None)
        self.config.pop("gate_path", None)
        self.config["fault"] = "none"
        self._write_config()
        replay = self._run("activate")
        self.assertIn(replay.returncode, {0, 3}, replay.stderr)
        self.assertEqual((self.task_root / "events.jsonl").read_bytes(), before)
        self.assertEqual(self._activation_count(), 1)

    def test_two_distinct_requests_for_one_legal_candidate_have_one_committed_winner(self) -> None:
        barrier = Path(self.temporary.name) / "distinct-request-barrier"
        first_config = Path(self.temporary.name) / "request-a.json"
        second_config = Path(self.temporary.name) / "request-b.json"
        os.mkfifo(barrier)
        first = self._spawn_activate(
            request_id="REQ-PROCESS-A", barrier_path=barrier, config_path=first_config,
        )
        self.assertEqual(self._next_phase(first)["stage"], "ready")
        second = self._spawn_activate(
            request_id="REQ-PROCESS-B", barrier_path=barrier, config_path=second_config,
        )
        self.assertEqual(self._next_phase(second)["stage"], "ready")
        with barrier.open("wb", buffering=0) as release:
            release.write(b"GG")
        first_rc, first_lines, first_err = self._finish(first)
        second_rc, second_lines, second_err = self._finish(second)

        self.assertIn(first_rc, {0, 3}, first_err)
        self.assertIn(second_rc, {0, 3}, second_err)
        first_result = next(line["result"] for line in first_lines if line.get("stage") == "result")
        second_result = next(line["result"] for line in second_lines if line.get("stage") == "result")
        activated = [event for event in self._events() if event["event_type"] == "handoff_activated"]
        self.assertEqual(len(activated), 1)
        self.assertEqual(activated[0]["payload"]["controller_generation"], 1)
        winner_request = activated[0]["payload"]["request_id"]
        self.assertIn(winner_request, {"REQ-PROCESS-A", "REQ-PROCESS-B"})
        results_by_request = {
            "REQ-PROCESS-A": first_result,
            "REQ-PROCESS-B": second_result,
        }
        winner = results_by_request[winner_request]
        loser = results_by_request[( {"REQ-PROCESS-A", "REQ-PROCESS-B"} - {winner_request} ).pop()]
        self.assertEqual(winner["check_status"], "pass", winner)
        self.assertEqual(winner["commit_status"], "confirmed_committed", winner)
        self.assertNotEqual(loser["commit_status"], "confirmed_committed", loser)
        self.assertNotEqual(loser["check_status"], "pass", loser)

    def test_before_temp_fsync_error_keeps_the_strict_old_log_not_committed(self) -> None:
        process = self._spawn_activate(fault="temp_fsync_error")
        before = self._next_phase(process)
        self.assertEqual(before["stage"], "before_temp_fsync")
        rc, lines, stderr = self._finish(process)

        fresh = self._status().lines[-1]["result"]
        self.assertNotEqual(rc, 0, (lines, stderr, fresh))
        self.assertTrue(any(line.get("stage") == "result" for line in lines), lines)
        self.assertEqual(self._activation_count(), 0)
        self.assertEqual(fresh["commit_status"], "confirmed_not_committed", fresh)
        self.assertEqual(fresh["controller_generation"], 0, fresh)

    def test_sigterm_after_temp_fsync_before_publish_is_not_a_retryable_commit(self) -> None:
        gate = Path(self.temporary.name) / "after-temp-fsync-gate"
        os.mkfifo(gate)
        process = self._spawn_activate(fault="sigterm_after_temp_fsync", gate_path=gate)
        before = self._next_phase(process)
        self.assertEqual(before["stage"], "before_temp_fsync")
        self.assertEqual(self._next_phase(process)["stage"], "after_temp_fsync_before_publish")
        # A FIFO holds the child after genuine temp fsync and before canonical
        # replace; termination is tied to the publication boundary, not timing.
        process.send_signal(signal.SIGTERM)
        rc, _lines, _stderr = self._finish(process)

        self.assertEqual(rc, -signal.SIGTERM)
        fresh = self._status().lines[-1]["result"]
        self.assertEqual(self._activation_count(), 0)
        self.assertEqual(fresh["commit_status"], "confirmed_not_committed", fresh)
        self.assertEqual(fresh["controller_generation"], 0, fresh)

    def test_fsync_then_snapshot_replace_failure_recovers_once_in_new_process(self) -> None:
        process = self._spawn_activate(fault="snapshot_replace_error")
        self.assertEqual(self._next_phase(process)["stage"], "before_temp_fsync")
        self.assertEqual(self._next_phase(process)["stage"], "after_temp_fsync_before_publish")
        self.assertEqual(self._next_phase(process)["stage"], "before_events_publish")
        self.assertEqual(self._next_phase(process)["stage"], "after_events_publish")
        self.assertEqual(self._next_phase(process)["stage"], "before_snapshot_replace")
        rc, lines, stderr = self._finish(process)

        self.assertEqual(rc, 0, (lines, stderr))
        fresh = self._status().lines[-1]["result"]
        self.assertEqual(fresh["commit_status"], "confirmed_committed", fresh)
        self.assertEqual(fresh["controller_generation"], 1, fresh)
        self.assertEqual(self._activation_count(), 1)

    def test_sigterm_after_snapshot_replace_before_response_recovers_without_duplicate(self) -> None:
        gate = Path(self.temporary.name) / "after-replace-gate"
        os.mkfifo(gate)
        process = self._spawn_activate(fault="sigterm_after_snapshot_replace", gate_path=gate)
        self.assertEqual(self._next_phase(process)["stage"], "before_temp_fsync")
        self.assertEqual(self._next_phase(process)["stage"], "after_temp_fsync_before_publish")
        self.assertEqual(self._next_phase(process)["stage"], "before_events_publish")
        self.assertEqual(self._next_phase(process)["stage"], "after_events_publish")
        self.assertEqual(self._next_phase(process)["stage"], "before_snapshot_replace")
        self.assertEqual(self._next_phase(process)["stage"], "after_snapshot_replace_before_response")
        process.send_signal(signal.SIGTERM)
        rc, _lines, _stderr = self._finish(process)

        self.assertEqual(rc, -signal.SIGTERM)
        fresh = self._status().lines[-1]["result"]
        self.assertEqual(fresh["commit_status"], "confirmed_committed", fresh)
        self.assertEqual(fresh["controller_generation"], 1, fresh)
        before = (self.task_root / "events.jsonl").read_bytes()
        replay = self._run("activate")
        self.assertIn(replay.returncode, {0, 3}, replay.stderr)
        self.assertEqual((self.task_root / "events.jsonl").read_bytes(), before)
        self.assertEqual(self._activation_count(), 1)

    def test_sigterm_after_canonical_events_publish_before_snapshot_is_committed_once(self) -> None:
        gate = Path(self.temporary.name) / "after-events-publish-gate"
        os.mkfifo(gate)
        process = self._spawn_activate(fault="sigterm_after_events_publish", gate_path=gate)
        self.assertEqual(self._next_phase(process)["stage"], "before_temp_fsync")
        self.assertEqual(self._next_phase(process)["stage"], "after_temp_fsync_before_publish")
        self.assertEqual(self._next_phase(process)["stage"], "before_events_publish")
        self.assertEqual(self._next_phase(process)["stage"], "after_events_publish")
        process.send_signal(signal.SIGTERM)
        rc, _lines, _stderr = self._finish(process)

        self.assertEqual(rc, -signal.SIGTERM)
        fresh = self._status().lines[-1]["result"]
        self.assertEqual(fresh["commit_status"], "confirmed_committed", fresh)
        self.assertEqual(fresh["controller_generation"], 1, fresh)
        self.assertEqual(self._activation_count(), 1)

    def test_parent_cleanup_reaps_a_child_blocked_at_a_named_gate(self) -> None:
        gate = Path(self.temporary.name) / "cleanup-gate"
        os.mkfifo(gate)
        process = self._spawn_activate(fault="sigterm_after_temp_fsync", gate_path=gate)
        self.assertEqual(self._next_phase(process)["stage"], "before_temp_fsync")
        self.assertEqual(self._next_phase(process)["stage"], "after_temp_fsync_before_publish")

        self._cleanup_child(process)

        self.assertIsNotNone(process.returncode)
        self.assertIn(id(process), self._cleaned_children)
        self.assertFalse(self._child_output[id(process)][1].is_alive())

    def test_unreadable_tail_never_uses_snapshot_as_commit_proof(self) -> None:
        event_path = self.task_root / "events.jsonl"
        event_path.write_bytes(event_path.read_bytes() + b'{"event_type":"handoff_activated"')
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.task_root.rglob("*") if path.is_file()}
        fresh = self._status().lines[-1]["result"]
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.task_root.rglob("*") if path.is_file()}

        self.assertEqual(fresh["check_status"], "unknown", fresh)
        self.assertEqual(fresh["commit_status"], "unknown", fresh)
        self.assertEqual(before, after)

    def test_twenty_status_processes_are_read_only_after_a_commit(self) -> None:
        self.assertEqual(self._run("activate").returncode, 0)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.task_root.rglob("*") if path.is_file()}
        reports = [self._status().lines[-1]["result"] for _ in range(20)]
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.task_root.rglob("*") if path.is_file()}

        self.assertTrue(all(report["commit_status"] == "confirmed_committed" for report in reports), reports)
        self.assertTrue(all(report["check_status"] == "unknown" for report in reports), reports)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
