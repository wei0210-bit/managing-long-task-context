from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from managing_long_task_context.host_codex_cli import CodexCliConfig, CodexCliHost
from managing_long_task_context.host_records import HostTaskLedger
from handoff_host_records_fixture import LedgerFixture


THREAD_ID = "11111111-1111-4111-8111-111111111111"


def trusted_observation(request: dict[str, object]) -> dict[str, object]:
    binding = {
        key: request[key]
        for key in ("task_id", "attempt_id", "thread_id", "workspace_root")
    }
    binding_sha = hashlib.sha256(
        json.dumps(
            binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "pass",
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "thread_id": request["thread_id"],
        "workspace_root": request["workspace_root"],
        "baseline": request["baseline"],
        "controller_generation": request["controller_generation"],
        "identity_status": "pass",
        "authorization_status": "pass",
        "host_identity_ref": {
            "registered_identity_id": "host.codex.fixture",
            "sha256": "d" * 64,
        },
        "exclusivity_status": "exclusive",
        "thread_state": "idle",
        "observed_at": "2026-09-15T12:00:00Z",
        "expires_at": "2099-09-15T12:00:00Z",
        "observation_ref": {
            "ref_id": "fixture-host",
            "uri": "fixture://host",
            "sha256": "e" * 64,
        },
        "request_binding_sha256": binding_sha,
    }


class FakeLedger:
    def __init__(self) -> None:
        self.reservations: list[tuple[dict[str, object], str]] = []
        self.observations: list[tuple[str, dict[str, object]]] = []

    def reserve(self, request: dict[str, object], operation: str) -> dict[str, object]:
        self.reservations.append((dict(request), operation))
        return {
            "status": "pass",
            "reservation_id": "resv.task.attempt",
            "launch_allowed": True,
            "reason_code": "RESERVED",
            "current_state": "reserved",
            "readonly_action": "observe",
        }

    def record_observation(
        self, attempt_id: str, observation: dict[str, object]
    ) -> dict[str, object]:
        self.observations.append((attempt_id, dict(observation)))
        return {
            "status": "pass",
            "recorded": True,
            "reason_code": "OBSERVED",
            "observation_id": "obs.1",
            "current_state": "exited",
        }

    def observe(self, attempt_id: str) -> dict[str, object]:
        return {"status": "pass", "attempt_id": attempt_id, "launch_state": "exited"}


class DenyingLedger(FakeLedger):
    def reserve(self, request: dict[str, object], operation: str) -> dict[str, object]:
        self.reservations.append((dict(request), operation))
        return {
            "status": "pass",
            "reservation_id": "resv.task.attempt",
            "launch_allowed": False,
            "reason_code": "ATTEMPT_ALREADY_IN_FLIGHT",
            "current_state": "running",
            "readonly_action": "observe",
        }


class CodexCliHostTests(unittest.TestCase):
    def _request(
        self, root: Path, *, thread_id: str | None = None
    ) -> dict[str, object]:
        return {
            "task_id": "TASK-E3",
            "attempt_id": "attempt-001",
            "contract_version": 1,
            "contract_digest": "a" * 64,
            "baseline": "baseline-e3",
            "workspace_root": str(root),
            "controller_generation": 7,
            "thread_id": thread_id,
            "authorization_digest": "c" * 64,
        }

    def _host(self, root: Path, ledger: FakeLedger) -> CodexCliHost:
        fixture = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
        return CodexCliHost(
            config=CodexCliConfig(
                executable_argv_prefix=(sys.executable, str(fixture)),
                workspace_root=str(root),
                model="trusted-model",
                reasoning_effort="high",
                sandbox_mode="workspace-write",
                approval_policy="on-request",
                timeout_seconds=10,
            ),
            ledger=ledger,
            observe_host=trusted_observation,
        )

    def test_start_child_uses_fixed_argv_devnull_and_persists_bounded_observation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture_record = root / "fixture.json"
            ledger = FakeLedger()
            host = self._host(root, ledger)
            request = self._request(root)
            prompt = 'quoted "text"\n--fake-option; $(not-a-command)'
            with patch.dict(
                os.environ, {"MLTC_CODEX_FIXTURE_RECORD": str(fixture_record)}
            ):
                result = host.start_child(request, prompt)

            fixture_data = json.loads(fixture_record.read_text(encoding="utf-8"))
            self.assertEqual(result["check_status"], "unknown")
            self.assertEqual(result["launch_status"], "exited")
            self.assertEqual(fixture_data["cwd"], str(root))
            self.assertTrue(fixture_data["stdin_eof"])
            self.assertEqual(fixture_data["stdin_text"], "")
            self.assertIn("--", fixture_data["argv"])
            self.assertEqual(fixture_data["argv"][-1], prompt)
            self.assertNotIn("--fake-option", fixture_data["argv"][:-1])
            self.assertEqual(len(ledger.reservations), 1)
            reserved, operation = ledger.reservations[0]
            self.assertEqual(operation, "start_child")
            self.assertEqual(reserved["thread_id"], None)
            self.assertEqual(reserved["workspace_root"], str(root))
            self.assertIn("argv_sha256", reserved)
            self.assertIn("config_digest", reserved)
            self.assertIn("prompt_sha256", reserved)
            self.assertEqual(len(ledger.observations), 1)
            observation = ledger.observations[0][1]
            self.assertEqual(observation["thread_id"], THREAD_ID)
            self.assertNotIn(prompt, json.dumps(observation))

    def test_busy_reservation_does_not_start_a_second_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            record = root / "fixture.json"
            with patch.dict(os.environ, {"MLTC_CODEX_FIXTURE_RECORD": str(record)}):
                result = self._host(root, DenyingLedger()).start_child(
                    self._request(root), "safe"
                )
            self.assertEqual(result["check_status"], "unknown")
            self.assertEqual(result["reason_code"], "ATTEMPT_ALREADY_IN_FLIGHT")
            self.assertFalse(record.exists())

    def test_malformed_host_observation_blocks_before_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            ledger = FakeLedger()
            host = self._host(root, ledger)
            host = CodexCliHost(
                config=host.config,
                ledger=ledger,
                observe_host=lambda request: {"status": "pass"},
            )
            result = host.start_child(self._request(root), "safe")
            self.assertEqual(result["reason_code"], "HOST_OBSERVATION_UNVERIFIED")
            self.assertEqual(ledger.reservations, [])

    def test_resume_requires_a_precise_uuid_and_uses_it_without_last(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            record = root / "fixture.json"
            host = self._host(root, FakeLedger())
            with patch.dict(os.environ, {"MLTC_CODEX_FIXTURE_RECORD": str(record)}):
                result = host.resume_child(
                    self._request(root, thread_id=THREAD_ID), "resume safely"
                )
            argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
            self.assertEqual(result["thread_id"], THREAD_ID)
            self.assertEqual(argv[:3], ["exec", "resume", THREAD_ID])
            self.assertNotIn("--last", argv)
            self.assertEqual(
                host.resume_child(self._request(root, thread_id="recent"), "safe")[
                    "reason_code"
                ],
                "HOST_RESUME_THREAD_INVALID",
            )

    def test_output_over_budget_kills_only_fixture_process_and_records_no_prompt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            record = root / "fixture.json"
            ledger = FakeLedger()
            with patch.dict(
                os.environ,
                {
                    "MLTC_CODEX_FIXTURE_RECORD": str(record),
                    "MLTC_CODEX_FIXTURE_FLOOD": "1",
                },
            ):
                result = self._host(root, ledger).start_child(
                    self._request(root), "do not retain this prompt"
                )
            self.assertEqual(result["check_status"], "unknown")
            self.assertEqual(len(ledger.observations), 1)
            observation = ledger.observations[0][1]
            self.assertTrue(observation["output_over_limit"])
            self.assertLessEqual(observation["stdout_bytes"], 8 * 1024 * 1024)
            self.assertNotIn("do not retain this prompt", json.dumps(observation))

    def test_output_over_budget_after_valid_thread_remains_execution_unknown(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            ledger = FakeLedger()
            with patch.dict(
                os.environ,
                {
                    "MLTC_CODEX_FIXTURE_RECORD": str(root / "fixture.json"),
                    "MLTC_CODEX_FIXTURE_EVENT_THEN_FLOOD": "1",
                },
            ):
                result = self._host(root, ledger).start_child(
                    self._request(root), "safe"
                )
            self.assertEqual(result["launch_status"], "execution_unknown")
            self.assertTrue(ledger.observations[0][1]["output_over_limit"])

    def test_timeout_observes_only_this_direct_fixture_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            ledger = FakeLedger()
            host = CodexCliHost(
                config=CodexCliConfig(
                    executable_argv_prefix=(sys.executable, str(fixture)),
                    workspace_root=str(root),
                    model="trusted-model",
                    reasoning_effort="high",
                    sandbox_mode="workspace-write",
                    approval_policy="on-request",
                    timeout_seconds=1,
                ),
                ledger=ledger,
                observe_host=trusted_observation,
            )
            started = time.monotonic()
            with patch.dict(
                os.environ,
                {
                    "MLTC_CODEX_FIXTURE_RECORD": str(root / "fixture.json"),
                    "MLTC_CODEX_FIXTURE_SLEEP": "1",
                },
            ):
                result = host.start_child(self._request(root), "safe")
            self.assertLess(time.monotonic() - started, 2.5)
            self.assertEqual(result["launch_status"], "timeout")
            observation = ledger.observations[0][1]
            self.assertTrue(observation["timeout"])
            self.assertIsNone(observation["exit_status"])

    def test_timeout_kills_descendant_process_group_before_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            marker = root / "timeout-descendant-survived"
            fixture = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            host = CodexCliHost(
                config=CodexCliConfig(
                    executable_argv_prefix=(sys.executable, str(fixture)),
                    workspace_root=str(root),
                    model="trusted-model",
                    reasoning_effort="high",
                    sandbox_mode="workspace-write",
                    approval_policy="on-request",
                    timeout_seconds=1,
                ),
                ledger=FakeLedger(),
                observe_host=trusted_observation,
            )
            with patch.dict(
                os.environ,
                {
                    "MLTC_CODEX_FIXTURE_RECORD": str(root / "fixture.json"),
                    "MLTC_CODEX_FIXTURE_SLEEP": "1",
                    "MLTC_CODEX_FIXTURE_DESCENDANT_MARKER": str(marker),
                    "MLTC_CODEX_FIXTURE_DESCENDANT_DELAY": "1.5",
                },
            ):
                result = host.start_child(self._request(root), "safe")
            self.assertEqual(result["launch_status"], "timeout")
            time.sleep(0.8)
            self.assertFalse(marker.exists(), "timed-out descendant remained alive")

    def test_output_over_limit_kills_descendant_process_group_before_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            marker = root / "overflow-descendant-survived"
            ledger = FakeLedger()
            with patch.dict(
                os.environ,
                {
                    "MLTC_CODEX_FIXTURE_RECORD": str(root / "fixture.json"),
                    "MLTC_CODEX_FIXTURE_FLOOD": "1",
                    "MLTC_CODEX_FIXTURE_DESCENDANT_MARKER": str(marker),
                    "MLTC_CODEX_FIXTURE_DESCENDANT_DELAY": "0.5",
                },
            ):
                result = self._host(root, ledger).start_child(
                    self._request(root), "safe"
                )
            self.assertTrue(ledger.observations[0][1]["output_over_limit"])
            self.assertEqual(result["launch_status"], "execution_unknown")
            time.sleep(0.8)
            self.assertFalse(marker.exists(), "over-limit descendant remained alive")

    def test_config_path_replacement_after_reservation_blocks_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            original = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            executable, replacement = (
                root / "trusted-fixture.py",
                root / "replacement.py",
            )
            shutil.copyfile(original, executable)
            shutil.copyfile(original, replacement)

            class ReplacingLedger(FakeLedger):
                def reserve(
                    self, request: dict[str, object], operation: str
                ) -> dict[str, object]:
                    reply = super().reserve(request, operation)
                    os.replace(replacement, executable)
                    return reply

            host = CodexCliHost(
                config=CodexCliConfig(
                    executable_argv_prefix=(sys.executable, str(executable)),
                    workspace_root=str(root),
                    model="trusted-model",
                    reasoning_effort="high",
                    sandbox_mode="workspace-write",
                    approval_policy="on-request",
                    timeout_seconds=10,
                ),
                ledger=ReplacingLedger(),
                observe_host=trusted_observation,
            )
            with patch.dict(
                os.environ,
                {"MLTC_CODEX_FIXTURE_RECORD": str(root / "should-not-exist.json")},
            ):
                result = host.start_child(self._request(root), "safe")
            self.assertEqual(result["reason_code"], "HOST_CONFIG_PATH_CHANGED")
            self.assertFalse((root / "should-not-exist.json").exists())

    def test_config_executable_in_place_rewrite_after_reservation_blocks_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            original = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            executable = root / "trusted-fixture.py"
            shutil.copyfile(original, executable)
            original_stat = executable.stat()

            class RewritingLedger(FakeLedger):
                def reserve(
                    self, request: dict[str, object], operation: str
                ) -> dict[str, object]:
                    reply = super().reserve(request, operation)
                    executable.write_bytes(
                        executable.read_bytes() + b"\n# in-place rewritten payload\n"
                    )
                    rewritten_stat = executable.stat()
                    if (
                        rewritten_stat.st_ino != original_stat.st_ino
                        or rewritten_stat.st_uid != original_stat.st_uid
                        or rewritten_stat.st_mode != original_stat.st_mode
                    ):
                        raise AssertionError("fixture rewrite changed path metadata")
                    return reply

            ledger = RewritingLedger()
            host = CodexCliHost(
                config=CodexCliConfig(
                    executable_argv_prefix=(sys.executable, str(executable)),
                    workspace_root=str(root),
                    model="trusted-model",
                    reasoning_effort="high",
                    sandbox_mode="workspace-write",
                    approval_policy="on-request",
                    timeout_seconds=10,
                ),
                ledger=ledger,
                observe_host=trusted_observation,
            )
            marker = root / "should-not-exist.json"
            with patch.dict(
                os.environ, {"MLTC_CODEX_FIXTURE_RECORD": str(marker)}
            ):
                result = host.start_child(self._request(root), "safe")
            self.assertEqual(result["reason_code"], "HOST_CONFIG_PATH_CHANGED")
            self.assertFalse(marker.exists())

    def test_workspace_replacement_after_reservation_blocks_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            workspace, replacement, retired = (
                root / "workspace",
                root / "replacement",
                root / "retired",
            )
            workspace.mkdir()
            replacement.mkdir()

            class ReplacingLedger(FakeLedger):
                def reserve(
                    self, request: dict[str, object], operation: str
                ) -> dict[str, object]:
                    reply = super().reserve(request, operation)
                    os.replace(workspace, retired)
                    os.replace(replacement, workspace)
                    return reply

            host = self._host(workspace, ReplacingLedger())
            with patch.dict(
                os.environ,
                {"MLTC_CODEX_FIXTURE_RECORD": str(workspace / "should-not-exist.json")},
            ):
                result = host.start_child(self._request(workspace), "safe")
            self.assertEqual(result["reason_code"], "HOST_CONFIG_PATH_CHANGED")
            self.assertFalse((workspace / "should-not-exist.json").exists())

    def test_invalid_prompt_and_baseline_are_rejected_before_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for prompt, baseline, code in (
                ("bad\x00prompt", "baseline-e3", "HOST_REQUEST_INVALID"),
                ("bad\ud800prompt", "baseline-e3", "HOST_PROMPT_ENCODING_INVALID"),
                ("safe", "bad\ud800baseline", "HOST_BASELINE_INVALID"),
            ):
                ledger = FakeLedger()
                request = self._request(root)
                request["baseline"] = baseline
                with self.subTest(code=code):
                    result = self._host(root, ledger).start_child(request, prompt)
                self.assertEqual(result["reason_code"], code)
                self.assertEqual(ledger.reservations, [])

    def test_trusted_config_rejects_nul_and_unknown_toml_policy_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            valid = dict(
                executable_argv_prefix=(sys.executable, str(fixture)),
                workspace_root=str(root),
                model="trusted-model",
                reasoning_effort="high",
                sandbox_mode="read-only",
                approval_policy="on-request",
                timeout_seconds=10,
            )
            self.assertEqual(CodexCliConfig(**valid).approval_policy, "on-request")
            for field, value in (
                ("sandbox_mode", "unknown-sandbox"),
                ("approval_policy", 'on-request"; injected=true'),
                ("model", "trusted\x00model"),
            ):
                invalid = dict(valid)
                invalid[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    CodexCliConfig(**invalid)

    def test_thread_stream_conflict_or_bad_utf8_is_execution_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            record = root / "fixture.json"
            wrong = "22222222-2222-4222-8222-222222222222"
            cases = [
                (
                    json.dumps(
                        {"type": "thread.started", "thread_id": THREAD_ID}
                    ).encode()
                    + b"\n"
                    + json.dumps(
                        {"type": "thread.started", "thread_id": wrong}
                    ).encode()
                    + b"\n"
                ).hex(),
                b"\xff\n".hex(),
            ]
            for payload in cases:
                with (
                    self.subTest(payload=payload[:8]),
                    patch.dict(
                        os.environ,
                        {
                            "MLTC_CODEX_FIXTURE_RECORD": str(record),
                            "MLTC_CODEX_FIXTURE_EVENTS": payload,
                        },
                    ),
                ):
                    result = self._host(root, FakeLedger()).start_child(
                        self._request(root), "safe"
                    )
                self.assertEqual(result["launch_status"], "execution_unknown")

    def _assert_unknown_stream_is_archived(self, payload: bytes, operation: str) -> None:
        """Exercise real transport + ledger; only the external CLI/host are fixtures."""
        fixture = LedgerFixture()
        self.addCleanup(fixture.close)
        ledger = HostTaskLedger(
            fixture.base_dir, fixture.host, fixture.host.identity, None
        )
        config = self._host(fixture.workspace, ledger).config
        prompt = "bounded malformed stream fixture"
        registered = fixture.request(
            thread_id=THREAD_ID if operation == "resume_child" else None
        )
        request = {
            key: value for key, value in registered.items()
            if key not in {"argv_sha256", "config_digest", "prompt_sha256"}
        }
        command = (
            ["exec", "resume", THREAD_ID] if operation == "resume_child"
            else ["exec", "-C", config.workspace_root]
        )
        argv = [
            *config.executable_argv_prefix, *command, "-m", "trusted-model",
            "-c", 'model_reasoning_effort="high"',
            "-c", 'sandbox_mode="workspace-write"',
            "-c", 'approval_policy="on-request"', "--json", "--", prompt,
        ]
        registered.update(
            argv_sha256=_canonical_digest(argv),
            config_digest=_canonical_digest({
                "executable_argv_prefix": list(config.executable_argv_prefix),
                "workspace_root": config.workspace_root, "model": "trusted-model",
                "reasoning_effort": "high", "sandbox_mode": "workspace-write",
                "approval_policy": "on-request", "timeout_seconds": 10,
            }),
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        )
        fixture.host.registered_requests["attempt-001"] = registered
        host = CodexCliHost(
            config, ledger,
            lambda value: fixture.host.observe_execution_state(value, operation),
        )
        counter = fixture.workspace / "count.txt"
        with patch.dict(os.environ, {
            "MLTC_CODEX_FIXTURE_RECORD": str(fixture.workspace / "cli.json"),
            "MLTC_CODEX_FIXTURE_EVENTS": payload.hex(),
            "MLTC_CODEX_FIXTURE_COUNT": str(counter),
        }):
            result = getattr(host, operation)(request, prompt)
            duplicate = getattr(host, operation)(request, prompt)
        self.assertEqual(result["launch_status"], "execution_unknown", result)
        self.assertIsNone(result["thread_id"], result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        self.assertEqual(duplicate["reason_code"], "ALREADY_RESERVED", duplicate)
        self.assertEqual(counter.read_text(), "1")
        self.assertEqual(ledger.observe("attempt-001")["current_state"], "observed")
        archives = list((fixture.base_dir / fixture.task_id / "attempts" /
                         "attempt-001" / "observations").glob("*.json"))
        self.assertEqual(len(archives), 1)
        archived = json.loads(archives[0].read_text())
        self.assertEqual(archived["stdout"].encode("utf-8"), payload)
        self.assertEqual(archived["exit_status"], 0)
        replacement = ledger.reserve(fixture.request(attempt_id="attempt-002"), "start_child")
        self.assertEqual(replacement["reason_code"], "PRIOR_ATTEMPT_IN_FLIGHT_OR_UNKNOWN", replacement)
        self.assertFalse(replacement["launch_allowed"])

    def test_duplicate_json_keys_cannot_hide_thread_conflicts(self) -> None:
        for operation in ("start_child", "resume_child"):
            for first in (THREAD_ID, "22222222-2222-4222-8222-222222222222"):
                with self.subTest(operation=operation, first=first):
                    payload = (
                        '{"type":"thread.started","thread_id":"' + first +
                        '","thread_id":"' + THREAD_ID + '"}\n'
                    ).encode()
                    self._assert_unknown_stream_is_archived(payload, operation)

    def test_deep_json_still_archives_unknown_execution_without_retry(self) -> None:
        payload = (
            '{"type":"thread.started","thread_id":"' + THREAD_ID +
            '","extra":' + '[' * 10000 + '0' + ']' * 10000 + '}\n'
        ).encode()
        self.assertLess(len(payload), 64 * 1024)
        for operation in ("start_child", "resume_child"):
            with self.subTest(operation=operation):
                self._assert_unknown_stream_is_archived(payload, operation)

    def test_stderr_over_budget_and_grandchild_pipe_return_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            record = root / "fixture.json"
            for extra in (
                {"MLTC_CODEX_FIXTURE_STDERR_FLOOD": "1"},
                {"MLTC_CODEX_FIXTURE_GRANDCHILD": "1"},
            ):
                ledger = FakeLedger()
                start = time.monotonic()
                with (
                    self.subTest(extra=extra),
                    patch.dict(
                        os.environ, {"MLTC_CODEX_FIXTURE_RECORD": str(record), **extra}
                    ),
                ):
                    result = self._host(root, ledger).start_child(
                        self._request(root), "safe"
                    )
                self.assertLess(time.monotonic() - start, 2.5)
                self.assertEqual(result["check_status"], "unknown")
                self.assertTrue(
                    ledger.observations[0][1]["output_over_limit"]
                    or extra.get("MLTC_CODEX_FIXTURE_GRANDCHILD") == "1"
                )
                if extra.get("MLTC_CODEX_FIXTURE_GRANDCHILD") == "1":
                    self.assertEqual(result["launch_status"], "execution_unknown")

    def test_inherited_pipe_reader_exits_without_resource_warning(self) -> None:
        """A daemon reader may outlive the direct child, but owns its stream."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
            record = root / "fixture.json"
            script = (
                "import os, sys; "
                "from managing_long_task_context.host_codex_cli import _run_bounded; "
                f"os.environ['MLTC_CODEX_FIXTURE_RECORD'] = {str(record)!r}; "
                "os.environ['MLTC_CODEX_FIXTURE_GRANDCHILD'] = '1'; "
                f"_run_bounded([sys.executable, {str(fixture)!r}], cwd={str(root)!r}, timeout_seconds=1); "
                "import time; time.sleep(6)"
            )
            environment = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            }
            completed = subprocess.run(
                [sys.executable, "-W", "always::ResourceWarning", "-c", script],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=12,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("ResourceWarning", completed.stderr, completed.stderr)

    def test_real_ledger_archives_then_recovers_without_duplicate_launch(self) -> None:
        fixture = LedgerFixture()
        self.addCleanup(fixture.close)
        executable = Path(__file__).with_name("handoff_codex_fixture.py").resolve()
        config = CodexCliConfig(
            executable_argv_prefix=(sys.executable, str(executable)),
            workspace_root=str(fixture.workspace),
            model="trusted-model",
            reasoning_effort="high",
            sandbox_mode="workspace-write",
            approval_policy="on-request",
            timeout_seconds=10,
        )
        prompt = "local fixture integration"
        registered_request = fixture.request()
        request = {
            key: value
            for key, value in registered_request.items()
            if key not in {"argv_sha256", "config_digest", "prompt_sha256"}
        }
        argv = [
            sys.executable,
            str(executable),
            "exec",
            "-C",
            str(fixture.workspace.resolve()),
            "-m",
            "trusted-model",
            "-c",
            'model_reasoning_effort="high"',
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            'approval_policy="on-request"',
            "--json",
            "--",
            prompt,
        ]
        registered_request.update(
            {
                "argv_sha256": _canonical_digest(argv),
                "config_digest": _canonical_digest(
                    {
                        "executable_argv_prefix": [sys.executable, str(executable)],
                        "workspace_root": str(fixture.workspace.resolve()),
                        "model": "trusted-model",
                        "reasoning_effort": "high",
                        "sandbox_mode": "workspace-write",
                        "approval_policy": "on-request",
                        "timeout_seconds": 10,
                    }
                ),
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            }
        )
        fixture.host.registered_requests["attempt-001"] = registered_request
        ledger = HostTaskLedger(
            fixture.base_dir, fixture.host, fixture.host.identity, None
        )
        host = CodexCliHost(
            config=config,
            ledger=ledger,
            observe_host=lambda value: fixture.host.observe_execution_state(
                value, "start_child"
            ),
        )
        record, counter = (
            fixture.workspace / "transport.json",
            fixture.workspace / "launch-count.txt",
        )
        with patch.dict(
            os.environ,
            {
                "MLTC_CODEX_FIXTURE_RECORD": str(record),
                "MLTC_CODEX_FIXTURE_COUNT": str(counter),
            },
        ):
            first = host.start_child(request, prompt)
            duplicate = host.start_child(request, prompt)

        self.assertEqual(first["commit_status"], "confirmed_committed", first)
        self.assertEqual(first["launch_status"], "exited", first)
        self.assertEqual(duplicate["reason_code"], "ALREADY_RESERVED", duplicate)
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")
        archives = list(
            (
                fixture.base_dir
                / fixture.task_id
                / "attempts"
                / "attempt-001"
                / "observations"
            ).glob("*.json")
        )
        self.assertEqual(len(archives), 1)
        self.assertEqual(stat.S_IMODE(archives[0].stat().st_mode), 0o600)
        self.assertIn(
            "thread.started",
            json.loads(archives[0].read_text(encoding="utf-8"))["stdout"],
        )
        recovered = HostTaskLedger(
            fixture.base_dir, fixture.host, fixture.host.identity, None
        )
        view = recovered.observe("attempt-001")
        self.assertEqual(view["status"], "pass", view)
        self.assertEqual(view["current_state"], "observed", view)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
