"""P12: real isolated process death, never a business/CLI/model task."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys
from types import SimpleNamespace
import unittest

from handoff_host_records_fixture import LedgerFixture, RegisteredHost
from managing_long_task_context.host_records import HostTaskLedger

ROOT = Path(__file__).resolve().parents[2]


def child(config_path: str, phase: str) -> None:
    value = json.loads(Path(config_path).read_text())
    fixture = SimpleNamespace(
        task_id=value["task_id"],
        baseline=value["request"]["baseline"],
        workspace=Path(value["workspace"]),
        base_dir=Path(value["base_dir"]),
    )
    host = object.__new__(RegisteredHost)
    host.fixture, host.task_id = fixture, fixture.task_id
    host.identity = object()
    host.registered_runtime_identity = host.identity
    host.state_path = fixture.workspace / "host-state.json"
    host.registered_attempts = {value["request"]["attempt_id"]}
    host.registered_requests = {value["request"]["attempt_id"]: value["request"]}
    ledger = HostTaskLedger(fixture.base_dir, host, host.identity, None)
    if phase == "reserve":
        print("ready-reserve", flush=True)
        sys.stdin.buffer.read(1)
        print(json.dumps(ledger.reserve(value["request"], "resume_child")), flush=True)
        return
    original = os.replace
    event_path = fixture.base_dir / fixture.task_id / "events.jsonl"

    def barrier_replace(source, destination, *args, **kwargs):
        target = Path(destination).resolve() == event_path.resolve()
        if target and phase == "before":
            print("barrier-before", flush=True)
            sys.stdin.buffer.read(1)
        result = original(source, destination, *args, **kwargs)
        if target and phase == "after":
            print("barrier-after", flush=True)
            sys.stdin.buffer.read(1)
        return result

    os.replace = barrier_replace
    result = ledger.reconcile_result(
        "attempt-001", "v1", SimpleNamespace(verify=lambda _: {"status": "pass"})
    )
    print(json.dumps(result), flush=True)


class ProcessProbes(unittest.TestCase):
    def exercise(self, phase: str, expected_before_retry: int) -> None:
        fixture = LedgerFixture()
        self.addCleanup(fixture.close)
        request = fixture.request()
        ledger = HostTaskLedger(
            fixture.base_dir, fixture.host, fixture.host.identity, None
        )
        self.assertTrue(ledger.reserve(request, "start_child")["launch_allowed"])
        result = {
            key: request[key]
            for key in (
                "task_id",
                "attempt_id",
                "contract_version",
                "contract_digest",
                "baseline",
                "workspace_root",
            )
        }
        result.update(result_version="v1", content="P12 synthetic verified artifact")
        self.assertEqual(ledger.publish_result(result)["status"], "pass")
        config = fixture.workspace / "process-config.json"
        config.write_text(
            json.dumps(
                {
                    "task_id": fixture.task_id,
                    "workspace": str(fixture.workspace),
                    "base_dir": str(fixture.base_dir),
                    "request": request,
                }
            )
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            str(config),
            phase,
        ]
        environment = {
            **os.environ,
            "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'tests'}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(ready, "processing child did not reach the frozen barrier")
            line = process.stdout.readline()
            self.assertEqual(line.decode().strip(), f"barrier-{phase}")
            process.kill()
            process.communicate(timeout=5)
            self.assertLess(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        def count():
            events = [
                json.loads(line)
                for line in (fixture.base_dir / fixture.task_id / "events.jsonl")
                .read_text()
                .splitlines()
            ]
            return sum(e["event_type"] == "host-result-processed" for e in events)

        self.assertEqual(count(), expected_before_retry)
        command[-1] = "none"
        for _ in range(2):
            recovered = subprocess.run(
                command, capture_output=True, env=environment, timeout=5, text=True
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(
                json.loads(recovered.stdout)["status"], "pass", recovered.stdout
            )
        self.assertEqual(count(), 1)

    def test_before_commit_death_recovers_as_not_committed(self):
        self.exercise("before", 0)

    def test_after_commit_death_recovers_without_duplicate(self):
        self.exercise("after", 1)

    def test_two_processes_resume_one_thread_at_most_one_reservation(self):
        fixture = LedgerFixture()
        self.addCleanup(fixture.close)
        environment = {
            **os.environ,
            "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'tests'}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        processes = []
        try:
            for attempt in ("attempt-001", "attempt-002"):
                request = fixture.request(
                    attempt_id=attempt, thread_id="11111111-1111-4111-8111-111111111111"
                )
                config = fixture.workspace / (attempt + ".json")
                config.write_text(
                    json.dumps(
                        {
                            "task_id": fixture.task_id,
                            "workspace": str(fixture.workspace),
                            "base_dir": str(fixture.base_dir),
                            "request": request,
                        }
                    )
                )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--child",
                        str(config),
                        "reserve",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
                processes.append(process)
                self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                self.assertEqual(process.stdout.readline().strip(), b"ready-reserve")
            for process in processes:
                process.stdin.write(b"G")
                process.stdin.flush()
            results = []
            for process in processes:
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error)
                results.append(json.loads(output))
            self.assertEqual(
                sum(r["launch_allowed"] is True for r in results), 1, results
            )
            events = [
                json.loads(line)
                for line in (fixture.base_dir / fixture.task_id / "events.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(
                sum(e["event_type"] == "host-attempt-reserved" for e in events), 1
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
