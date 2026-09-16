"""Independent E3 public transport probes. All commands are this local fake CLI.

Transport-only cases use an explicitly synthetic ledger; they do not claim
durability, real Codex behavior, or business completion. Integration is separate.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


THREAD = "22222222-2222-4222-8222-222222222222"


def fake_cli():
    target = Path(os.environ["E3_PROBE_RECORD"])
    with target.open("a") as stream:
        stream.write(
            json.dumps(
                {"argv": sys.argv[2:], "cwd": os.getcwd(), "stdin": sys.stdin.read()}
            )
            + "\n"
        )
    prompt = sys.argv[-1]
    if prompt == "timeout":
        time.sleep(3)
    if prompt == "malformed":
        print("not JSON")
        return
    print(json.dumps({"type": "thread.started", "thread_id": THREAD}))
    print(
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0}}
        )
    )


class BoundaryLedger:
    """Only tests the transport's treatment of a trusted ledger response."""

    def __init__(self):
        self.reserved = []
        self.observations = []
        self.persist_raises = False

    def reserve(self, request, operation):
        self.reserved.append(deepcopy(request))
        return {
            "status": "pass",
            "launch_allowed": True,
            "reservation_id": "synthetic-reservation",
            "reason_code": "RESERVED",
        }

    def record_observation(self, attempt_id, observation):
        self.observations.append(deepcopy(observation))
        if self.persist_raises:
            raise OSError("synthetic receipt lost")
        return {"status": "pass", "recorded": True}

    def observe(self, attempt_id):
        return {"status": "unknown", "attempt_id": attempt_id}


class TransportProbes(unittest.TestCase):
    def setUp(self):
        from managing_long_task_context.host_codex_cli import (
            CodexCliConfig,
            CodexCliHost,
        )

        self.Config, self.Host = CodexCliConfig, CodexCliHost
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.marker = self.root / "launched.jsonl"
        self.config = self.Config(
            executable_argv_prefix=(
                sys.executable,
                str(Path(__file__).resolve()),
                "--fake-child",
            ),
            workspace_root=str(self.root),
            model="synthetic-model",
            reasoning_effort="high",
            sandbox_mode="read-only",
            approval_policy="on-request",
            timeout_seconds=1,
        )
        self.request = {
            "task_id": "ROOT-E3",
            "attempt_id": "attempt-root-1",
            "contract_version": 1,
            "contract_digest": "a" * 64,
            "baseline": "b" * 64,
            "workspace_root": str(self.root),
            "controller_generation": 0,
            "thread_id": None,
            "authorization_digest": "c" * 64,
        }
        self.ledger = BoundaryLedger()
        self.observer_mode = "valid"
        self.host = self.Host(
            config=self.config, ledger=self.ledger, observe_host=self.observe_host
        )

    def observe_host(self, query):
        if self.observer_mode == "bare-pass":
            return {"status": "pass"}
        now = datetime.now(timezone.utc)
        binding = {
            "task_id": "ROOT-E3",
            "attempt_id": "attempt-root-1",
            "thread_id": self.request["thread_id"],
            "workspace_root": str(self.root),
        }
        binding_sha = hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "status": "pass",
            "task_id": "ROOT-E3",
            "attempt_id": "attempt-root-1",
            "thread_id": self.request["thread_id"],
            "workspace_root": str(self.root),
            "baseline": "b" * 64,
            "controller_generation": 0,
            "request_binding_sha256": binding_sha,
            "exclusivity_status": "exclusive",
            "thread_state": "idle",
            "identity_status": "pass",
            "authorization_status": "pass",
            "host_identity_ref": {
                "registered_identity_id": "fixed-root-fixture",
                "sha256": "d" * 64,
            },
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=30))
            .isoformat()
            .replace("+00:00", "Z"),
            "observation_ref": {
                "ref_id": "fixed-root-proof",
                "uri": (self.root / "proof").as_uri(),
                "sha256": "e" * 64,
            },
        }

    def launch(self, prompt, *, resume=False):
        with patch.dict(os.environ, {"E3_PROBE_RECORD": str(self.marker)}):
            return (self.host.resume_child if resume else self.host.start_child)(
                self.request, prompt
            )

    def launches(self):
        if not self.marker.exists():
            return []
        return [json.loads(line) for line in self.marker.read_text().splitlines()]

    def test_p01_p06_prompt_is_one_literal_argument_and_stdin_eof(self):
        prompt = '--dangerously-bypass-approvals-and-sandbox; $(touch PWNED)\n"literal"'
        result = self.launch(prompt)
        self.assertEqual(len(self.launches()), 1, result)
        observed = self.launches()[0]
        self.assertEqual(observed["stdin"], "")
        self.assertEqual(observed["cwd"], str(self.root))
        self.assertEqual(observed["argv"][-2:], ["--", prompt])
        self.assertFalse((self.root / "PWNED").exists())
        self.assertEqual(result["check_status"], "unknown")
        self.assertNotIn(prompt, json.dumps(self.ledger.observations))

    def test_p06_bare_pass_is_not_host_authority(self):
        self.observer_mode = "bare-pass"
        result = self.launch("valid prompt")
        self.assertEqual(result["check_status"], "unknown")
        self.assertEqual(self.launches(), [])
        self.assertEqual(self.ledger.reserved, [])

    def test_p05_lost_persistence_receipt_does_not_claim_not_attempted(self):
        self.ledger.persist_raises = True
        result = self.launch("valid prompt")
        self.assertEqual(len(self.launches()), 1, result)
        self.assertEqual(result["check_status"], "unknown")
        self.assertNotEqual(result["launch_status"], "not_attempted", result)

    def test_p05_malformed_exit_zero_not_confirmed_thread_execution(self):
        result = self.launch("malformed")
        self.assertEqual(len(self.launches()), 1, result)
        self.assertEqual(result["check_status"], "unknown")
        self.assertEqual(self.ledger.observations[0].get("thread_id"), None)

    def test_p15_prompt_over_budget_does_not_reserve_or_launch(self):
        result = self.launch("x" * 8001)
        self.assertEqual(result["check_status"], "unknown")
        self.assertEqual(self.launches(), [])
        self.assertEqual(self.ledger.reserved, [])

    def test_p15_exact_prompt_budget_is_accepted_as_one_argument(self):
        prompt = "界" * 8000
        result = self.launch(prompt)
        self.assertEqual(len(self.launches()), 1, result)
        self.assertEqual(self.launches()[0]["argv"][-1], prompt)
        self.assertEqual(result["launch_status"], "exited", result)

    def test_p15_invalid_text_encoding_or_nul_is_rejected_before_reservation(self):
        for prompt in ("\ud800", "text\x00hidden"):
            with self.subTest(kind=repr(prompt)):
                result = self.launch(prompt)
                self.assertEqual(result["check_status"], "unknown")
                self.assertEqual(self.launches(), [])
                self.assertEqual(self.ledger.reserved, [])

    def test_p07_expired_host_observation_after_reservation_does_not_start(self):
        original_observer = self.host.observe_host

        def short_receipt(query):
            value = original_observer(query)
            value["expires_at"] = (
                (datetime.now(timezone.utc) + timedelta(milliseconds=20))
                .isoformat()
                .replace("+00:00", "Z")
            )
            return value

        class SlowLedger(BoundaryLedger):
            def reserve(inner, request, operation):
                value = super().reserve(request, operation)
                time.sleep(0.04)  # Expiry test, not a race-order guess.
                return value

        self.ledger = SlowLedger()
        self.host = self.Host(
            config=self.config, ledger=self.ledger, observe_host=short_receipt
        )
        result = self.launch("valid prompt")
        self.assertEqual(self.launches(), [], result)
        self.assertEqual(result["check_status"], "unknown")

    def test_p02_resume_uses_exact_thread_and_supported_config_arguments(self):
        self.request["thread_id"] = THREAD
        result = self.launch("repair current task", resume=True)
        self.assertEqual(len(self.launches()), 1, result)
        args = self.launches()[0]["argv"]
        self.assertIn("resume", args)
        self.assertIn(THREAD, args)
        self.assertNotIn("--last", args)
        self.assertNotIn("-s", args)
        self.assertIn("--json", args)
        self.assertEqual(self.ledger.observations[0]["thread_id"], THREAD)


class LedgerProbes(unittest.TestCase):
    def setUp(self):
        from handoff_host_records_fixture import LedgerFixture
        from managing_long_task_context.host_records import HostTaskLedger

        self.fixture = LedgerFixture()
        self.addCleanup(self.fixture.close)
        self.Ledger = HostTaskLedger
        self.ledger = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )
        result = self.ledger.reserve(self.fixture.request(), "start_child")
        self.assertTrue(result["launch_allowed"], result)
        request = self.fixture.request()
        self.result = {
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
        self.result.update(
            result_version="v1", content="ROOT-CHECK: actual result evidence"
        )

    def events(self):
        # The event log is the explicitly frozen externally auditable commit
        # boundary, not a private projection implementation under test.
        path = self.fixture.base_dir / self.fixture.task_id / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_p01_unicode_workspace_keeps_cross_layer_digest_compatible(self):
        from handoff_host_records_fixture import LedgerFixture

        parent = Path(self.fixture.tmp.name) / "中文工作区"
        parent.mkdir()
        with patch.object(tempfile, "tempdir", str(parent)):
            other = LedgerFixture()
        self.addCleanup(other.close)
        ledger = self.Ledger(other.base_dir, other.host, other.host.identity, None)
        reply = ledger.reserve(other.request(), "start_child")
        self.assertTrue(reply["launch_allowed"], reply)

    def test_p09_replaced_attempt_late_result_cannot_be_current_pass(self):
        from types import SimpleNamespace

        observation = self.fixture.observation()
        observation["thread_id"] = THREAD
        self.assertEqual(
            self.ledger.record_observation("attempt-001", observation)["status"], "pass"
        )
        replacement = self.ledger.reserve(
            self.fixture.request(attempt_id="attempt-002"), "start_child"
        )
        self.assertTrue(replacement["launch_allowed"], replacement)
        late = self.ledger.publish_result(self.result)
        self.assertEqual(late["status"], "unknown", late)
        self.assertEqual(
            sum(e["event_type"] == "host-result-published" for e in self.events()), 1
        )
        processed = self.ledger.reconcile_result(
            "attempt-001", "v1", SimpleNamespace(verify=lambda _: {"status": "pass"})
        )
        self.assertEqual(processed["status"], "unknown", processed)
        self.assertFalse(
            any(e["event_type"] == "host-result-processed" for e in self.events())
        )

    def test_p07_impostor_cannot_publish_on_a_registered_attempt(self):
        stranger = self.Ledger(self.fixture.base_dir, self.fixture.host, object(), None)
        before = self.events()
        response = stranger.publish_result(self.result)
        self.assertNotEqual(response["status"], "pass", response)
        self.assertEqual(self.events(), before)

    def test_p08_repeat_processing_commits_only_once(self):
        published = self.ledger.publish_result(self.result)
        self.assertEqual(published["status"], "pass", published)

        class ContentVerifier:
            def verify(inner, data):
                return {
                    "status": (
                        "pass"
                        if data["content"] == "ROOT-CHECK: actual result evidence"
                        else "fail"
                    )
                }

        for _ in range(3):
            response = self.ledger.reconcile_result(
                "attempt-001", "v1", ContentVerifier()
            )
            self.assertEqual(response["status"], "pass", response)
        committed = [
            event
            for event in self.events()
            if event["event_type"] == "host-result-processed"
        ]
        self.assertEqual(len(committed), 1)

    def test_p11_archive_change_during_verification_prevents_commit(self):
        self.assertEqual(self.ledger.publish_result(self.result)["status"], "pass")
        root = self.fixture.base_dir / self.fixture.task_id
        published = next(
            event["payload"]
            for event in self.events()
            if event["event_type"] == "host-result-published"
        )
        archive = root / published["archive_ref"]["uri"]

        class ChangingVerifier:
            def verify(inner, data):
                self.assertEqual(data["content"], "ROOT-CHECK: actual result evidence")
                archive.write_text(
                    json.dumps({"content": "changed after verification"})
                )
                return {"status": "pass"}

        response = self.ledger.reconcile_result("attempt-001", "v1", ChangingVerifier())
        self.assertNotEqual(response["status"], "pass", response)
        self.assertEqual(
            [
                event
                for event in self.events()
                if event["event_type"] == "host-result-processed"
            ],
            [],
        )

    def test_p09_conflicting_result_bodies_remain_readable_and_never_process(self):
        self.assertEqual(self.ledger.publish_result(self.result)["status"], "pass")
        conflict = {**self.result, "content": "ROOT-CHECK: contradictory defect signal"}
        reply = self.ledger.publish_result(conflict)
        self.assertEqual(reply["status"], "unknown", reply)
        publications = [
            e["payload"]
            for e in self.events()
            if e["event_type"] == "host-result-published"
        ]
        self.assertEqual(len(publications), 2)
        bodies = {
            json.loads(
                (
                    self.fixture.base_dir
                    / self.fixture.task_id
                    / p["archive_ref"]["uri"]
                ).read_text()
            )["content"]
            for p in publications
        }
        self.assertEqual(bodies, {self.result["content"], conflict["content"]})
        from types import SimpleNamespace

        reply = self.ledger.reconcile_result(
            "attempt-001", "v1", SimpleNamespace(verify=lambda _: {"status": "pass"})
        )
        self.assertEqual(reply["status"], "unknown", reply)
        self.assertFalse(
            any(e["event_type"] == "host-result-processed" for e in self.events())
        )

    def test_p10_checker_missing_or_failing_cannot_be_a_business_pass(self):
        from types import SimpleNamespace

        self.assertEqual(self.ledger.publish_result(self.result)["status"], "pass")
        unavailable = self.ledger.reconcile_result("attempt-001", "v1", object())
        self.assertEqual(unavailable["status"], "unknown", unavailable)
        self.assertFalse(
            any(e["event_type"] == "host-result-processed" for e in self.events())
        )
        for _ in range(2):
            failed = self.ledger.reconcile_result(
                "attempt-001",
                "v1",
                SimpleNamespace(verify=lambda _: {"status": "fail"}),
            )
            self.assertEqual(failed.get("verdict"), "fail", failed)
        self.assertEqual(
            sum(e["event_type"] == "host-result-processed" for e in self.events()), 1
        )

    def test_p11_verifier_revokes_authorization_no_processing_commit(self):
        self.assertEqual(self.ledger.publish_result(self.result)["status"], "pass")

        class RevokingVerifier:
            def verify(inner, data):
                path = self.fixture.host.state_path
                state = json.loads(path.read_text())
                state["authorized"] = False
                path.write_text(json.dumps(state))
                return {"status": "pass"}

        response = self.ledger.reconcile_result("attempt-001", "v1", RevokingVerifier())
        self.assertEqual(response["status"], "unknown", response)
        self.assertFalse(
            any(e["event_type"] == "host-result-processed" for e in self.events())
        )


if __name__ == "__main__":
    if "--fake-child" in sys.argv:
        fake_cli()
    else:
        unittest.main()
