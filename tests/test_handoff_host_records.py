from __future__ import annotations

from copy import deepcopy
import hashlib
import sys
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from handoff_host_records_fixture import LedgerFixture, digest
from handoff_gate_fixtures import HandoffGateFixture, as_zulu, canonical_sha256
from test_handoff_activation import ActivationAuthority, ActivationVerifier, _ref
import managing_long_task_context as context
from managing_long_task_context.host_records import SCHEMA, _d
from managing_long_task_context.host_records import HostTaskLedger


class HostRecordReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = LedgerFixture()
        self.addCleanup(self.fixture.close)
        self.ledger = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )

    def test_fresh_gen0_request_is_durably_reserved_once(self) -> None:
        first = self.ledger.reserve(self.fixture.request(), "start_child")
        self.assertEqual(first["status"], "pass", first)
        self.assertTrue(first["launch_allowed"], first)
        second = self.ledger.reserve(self.fixture.request(), "start_child")
        self.assertEqual(second["status"], "pass", second)
        self.assertEqual(second["reason_code"], "ALREADY_RESERVED", second)
        self.assertFalse(second["launch_allowed"], second)

    def test_mismatched_observation_cannot_finish_prior_attempt_or_unlock_replacement(
        self,
    ) -> None:
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        forged = self.fixture.observation()
        forged.update(
            {
                "operation": "resume_child",
                "argv_sha256": "e" * 64,
                "cwd": "/private/tmp/not-the-authorized-workspace",
                "thread_id": "00000000-0000-4000-8000-000000000000",
            }
        )
        rejected = self.ledger.record_observation("attempt-001", forged)
        self.assertEqual(rejected["status"], "fail", rejected)
        self.assertEqual(
            rejected["reason_code"], "OBSERVATION_BINDING_MISMATCH", rejected
        )

        replacement = self.fixture.request(attempt_id="attempt-002")
        self.fixture.host.registered_attempts.add("attempt-002")
        self.fixture.host.registered_request = replacement
        blocked = self.ledger.reserve(replacement, "start_child")
        self.assertEqual(blocked["status"], "unknown", blocked)
        self.assertFalse(blocked["launch_allowed"], blocked)

    def test_current_controller_rejects_old_generation_before_reserving(self) -> None:
        handoff = HandoffGateFixture(
            truth_sources=False,
            rule_execution=False,
            independent_validation=False,
        )
        self.addCleanup(handoff.close)
        self.assertEqual(handoff.prepare()["check_status"], "pass")
        self.assertEqual(handoff.activate()["check_status"], "pass")
        identity = object()
        now = datetime.now(timezone.utc).replace(microsecond=0)

        class ActiveHost:
            task_id = handoff.task_id
            registered_runtime_identity = identity

            def observe_execution_state(
                self, request: dict[str, object], _operation: str
            ) -> dict[str, object]:
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
                        "registered_identity_id": "host",
                        "sha256": "e" * 64,
                    },
                    "exclusivity_status": "exclusive",
                    "thread_state": "idle",
                    "observed_at": as_zulu(now),
                    "expires_at": as_zulu(now + timedelta(minutes=1)),
                    "observation_ref": {
                        "ref_id": "hostobs",
                        "uri": "file:///private/tmp/hostobs",
                        "sha256": "f" * 64,
                    },
                    "request_binding_sha256": canonical_sha256(
                        {
                            key: request[key]
                            for key in (
                                "task_id",
                                "attempt_id",
                                "thread_id",
                                "workspace_root",
                            )
                        }
                    ),
                }

        class ActiveAuthorizer:
            def authorize(self, request: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "pass",
                    "operation": request["operation"],
                    "purpose": "dispatch",
                    "task_id": request["task_id"],
                    "base_dir": request["base_dir"],
                    "workspace_root": request["workspace_root"],
                    "package_manifest_sha256": request["package_manifest_sha256"],
                    "contract_version": request["contract_version"],
                    "contract_digest": request["contract_digest"],
                    "controller_generation": request["controller_generation"],
                    "handoff_id": request["handoff_id"],
                    "arguments_sha256": request["arguments_sha256"],
                    "subject_id": "controller",
                    "role": "controller",
                    "scope_digest": "a" * 64,
                    "work_item_id": None,
                    "source_session_ref": handoff.record["source_session_ref"],
                    "target_session_ref": handoff.record["target_session_ref"],
                    "authorization_ref": handoff.record["authorization_ref"],
                    "target_activation_status": "activated",
                    "observed_at": as_zulu(now),
                    "expires_at": as_zulu(now + timedelta(minutes=1)),
                    "subject_session_ref": handoff.record["target_session_ref"],
                }

        request = {
            "task_id": handoff.task_id,
            "attempt_id": "attempt-stale-gen",
            "contract_version": 1,
            "contract_digest": handoff.contract_digest,
            "baseline": "baseline",
            "workspace_root": str(handoff.workspace.resolve()),
            "controller_generation": 0,
            "thread_id": None,
            "argv_sha256": "a" * 64,
            "config_digest": "b" * 64,
            "prompt_sha256": "c" * 64,
            "authorization_digest": "d" * 64,
        }
        ledger = HostTaskLedger(
            handoff.base_dir, ActiveHost(), identity, ActiveAuthorizer()
        )
        rejected = ledger.reserve(request, "start_child")
        self.assertEqual(rejected["status"], "unknown", rejected)
        self.assertEqual(
            rejected["reason_code"], "CONTROLLER_GENERATION_MISMATCH", rejected
        )
        self.assertFalse(rejected["launch_allowed"], rejected)
        current = dict(request)
        current["attempt_id"] = "attempt-current-gen"
        current["controller_generation"] = 1
        allowed = ledger.reserve(current, "start_child")
        self.assertEqual(allowed["status"], "pass", allowed)
        self.assertTrue(allowed["launch_allowed"], allowed)

    def test_contract_change_makes_old_result_unprocessable_without_erasing_history(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        published = self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": "attempt-001",
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": request["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "result bound to contract v1",
            }
        )
        self.assertEqual(published["status"], "pass", published)
        contract = json.loads(
            (
                self.fixture.base_dir / self.fixture.task_id / "task-contract.json"
            ).read_text()
        )
        contract.pop("seal")
        contract["version"] = 2
        contract["objective"] = "changed synthetic scope"
        context.publish_contract(
            contract, confirmed_by="publisher", base_dir=self.fixture.base_dir
        )
        verifier = type(
            "Verifier", (), {"verify": lambda self, _request: {"status": "pass"}}
        )()
        rejected = self.ledger.reconcile_result("attempt-001", "result-001", verifier)
        self.assertEqual(rejected["status"], "unknown", rejected)
        self.assertEqual(rejected["reason_code"], "RESULT_BINDING_STALE", rejected)
        events = (
            (self.fixture.base_dir / self.fixture.task_id / "events.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(sum("host-result-published" in line for line in events), 1)
        self.assertEqual(sum("host-result-processed" in line for line in events), 0)

    def test_conflicting_reservation_history_is_unknown_not_last_write_wins(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        conflicting = dict(request)
        conflicting["prompt_sha256"] = "f" * 64
        self.fixture.host.registered_requests["attempt-001"] = conflicting
        observation = self.fixture.host.observe_execution_state(
            conflicting, "start_child"
        )
        payload = {
            "schema": SCHEMA,
            "type": "host-attempt-reserved",
            "task_id": self.fixture.task_id,
            "attempt_id": "attempt-001",
            "reservation_id": "resv.attempt-001",
            "operation": "start_child",
            "request": conflicting,
            "request_sha256": _d(conflicting),
            "host_observation": observation,
            "created_at": "2026-09-15T00:00:00Z",
        }
        event = context._new_event(
            self.fixture.task_id, "host-attempt-reserved", "registered-host-1", payload
        )
        with (self.fixture.base_dir / self.fixture.task_id / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        recovered = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )
        view = recovered.observe("attempt-001")
        self.assertEqual(view["status"], "unknown", view)

    def test_nonterminal_observations_do_not_unlock_prior_attempt(self) -> None:
        for label, update in (
            ("nonzero-exit", {"exit_status": 7}),
            ("bad-utf8", {"stdout_utf8": False}),
            ("output-limit", {"output_over_limit": True}),
        ):
            with self.subTest(label=label):
                fixture = LedgerFixture()
                self.addCleanup(fixture.close)
                ledger = HostTaskLedger(
                    fixture.base_dir, fixture.host, fixture.host.identity, None
                )
                self.assertTrue(
                    ledger.reserve(fixture.request(), "start_child")["launch_allowed"]
                )
                observation = fixture.observation()
                observation["thread_id"] = "11111111-1111-4111-8111-111111111111"
                observation.update(update)
                self.assertEqual(
                    ledger.record_observation("attempt-001", observation)["status"],
                    "pass",
                )
                if label == "bad-utf8":
                    events = [
                        json.loads(line)
                        for line in (
                            fixture.base_dir / fixture.task_id / "events.jsonl"
                        )
                        .read_text()
                        .splitlines()
                    ]
                    payload = next(
                        event["payload"]
                        for event in events
                        if event["event_type"] == "host-attempt-observed"
                    )
                    self.assertEqual(
                        payload["observation"]["stdout_digest"],
                        observation["stdout_digest"],
                    )
                blocked = ledger.reserve(
                    fixture.request(attempt_id="attempt-002"), "start_child"
                )
                self.assertEqual(blocked["status"], "unknown", blocked)
                self.assertFalse(blocked["launch_allowed"], blocked)

    def test_same_result_identity_different_content_is_preserved_and_immediately_unknown(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        common = {
            "task_id": self.fixture.task_id,
            "attempt_id": "attempt-001",
            "result_version": "result-001",
            "contract_version": 1,
            "contract_digest": request["contract_digest"],
            "baseline": self.fixture.baseline,
            "workspace_root": str(self.fixture.workspace.resolve()),
        }
        self.assertEqual(
            self.ledger.publish_result({**common, "content": "first body"})["status"],
            "pass",
        )
        conflict = self.ledger.publish_result({**common, "content": "second body"})
        self.assertEqual(conflict["status"], "unknown", conflict)
        self.assertEqual(conflict["reason_code"], "RESULT_IDENTITY_CONFLICT", conflict)
        events = (
            (self.fixture.base_dir / self.fixture.task_id / "events.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(sum("host-result-published" in line for line in events), 2)

    def test_observe_returns_result_and_processed_summaries_without_naked_pass(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        self.assertEqual(
            self.ledger.publish_result(
                {
                    "task_id": self.fixture.task_id,
                    "attempt_id": "attempt-001",
                    "result_version": "result-001",
                    "contract_version": 1,
                    "contract_digest": request["contract_digest"],
                    "baseline": self.fixture.baseline,
                    "workspace_root": str(self.fixture.workspace.resolve()),
                    "content": "body",
                }
            )["status"],
            "pass",
        )
        verifier = type(
            "Verifier", (), {"verify": lambda self, _request: {"status": "unknown"}}
        )()
        self.assertEqual(
            self.ledger.reconcile_result("attempt-001", "result-001", verifier)[
                "status"
            ],
            "pass",
        )
        recovered = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )
        view = recovered.observe("attempt-001")
        self.assertEqual(view["status"], "unknown", view)
        self.assertEqual(view["reason_code"], "RESULT_VERDICT_NOT_PASS", view)
        self.assertEqual(view["processed"][0]["verdict"], "unknown", view)

    def test_repeat_reconciliation_preserves_prior_verdict_and_rechecks_host_authorization(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        self.assertEqual(
            self.ledger.publish_result(
                {
                    "task_id": self.fixture.task_id,
                    "attempt_id": "attempt-001",
                    "result_version": "result-001",
                    "contract_version": 1,
                    "contract_digest": request["contract_digest"],
                    "baseline": self.fixture.baseline,
                    "workspace_root": str(self.fixture.workspace.resolve()),
                    "content": "body",
                }
            )["status"],
            "pass",
        )
        fail_verifier = type(
            "FailVerifier", (), {"verify": lambda self, _request: {"status": "fail"}}
        )()
        self.assertEqual(
            self.ledger.reconcile_result("attempt-001", "result-001", fail_verifier)[
                "verdict"
            ],
            "fail",
        )
        repeated = self.ledger.reconcile_result(
            "attempt-001", "result-001", fail_verifier
        )
        self.assertEqual(repeated["reason_code"], "ALREADY_PROCESSED", repeated)
        self.assertEqual(repeated["verdict"], "fail", repeated)
        self.fixture.host.state_path.write_text(
            json.dumps(
                {
                    "identity": "registered-host-1",
                    "exclusive": True,
                    "authorized": False,
                    "thread_state": "idle",
                }
            )
        )
        revoked = self.ledger.reconcile_result(
            "attempt-001", "result-001", fail_verifier
        )
        self.assertEqual(revoked["status"], "unknown", revoked)
        self.assertEqual(revoked["reason_code"], "HOST_AUTHORIZATION_DENIED", revoked)

    def test_action_outcome_requires_reserved_attempt_and_is_idempotent(self) -> None:
        missing = self.ledger.record_action_outcome(
            "action-001", "attempt-missing", "executed"
        )
        self.assertEqual(missing["status"], "fail", missing)
        self.assertEqual(missing["reason_code"], "ATTEMPT_NOT_RESERVED", missing)
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        first = self.ledger.record_action_outcome(
            "action-001", "attempt-001", "execution_unknown"
        )
        self.assertEqual(first["status"], "pass", first)
        duplicate = self.ledger.record_action_outcome(
            "action-001", "attempt-001", "execution_unknown"
        )
        self.assertEqual(duplicate["reason_code"], "ALREADY_ACTION_OUTCOME", duplicate)
        conflict = self.ledger.record_action_outcome(
            "action-001", "attempt-001", "executed"
        )
        self.assertEqual(conflict["status"], "unknown", conflict)
        events = (
            (self.fixture.base_dir / self.fixture.task_id / "events.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(
            sum("host-business-action-observed" in line for line in events), 1
        )

    def test_long_attempt_id_and_invalid_text_fail_closed_without_throwing(
        self,
    ) -> None:
        attempt_id = "a" * 96
        request = self.fixture.request(attempt_id=attempt_id)
        self.fixture.host.registered_attempts.add(attempt_id)
        self.fixture.host.registered_requests[attempt_id] = request
        reserved = self.ledger.reserve(request, "start_child")
        self.assertTrue(reserved["launch_allowed"], reserved)
        self.assertLessEqual(len(reserved["reservation_id"]), 96)
        invalid_text = self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": attempt_id,
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": request["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "\ud800",
            }
        )
        self.assertEqual(invalid_text["status"], "fail", invalid_text)
        unreserved = self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": "attempt-missing",
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": request["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "body",
            }
        )
        self.assertEqual(unreserved["status"], "fail", unreserved)
        self.assertEqual(unreserved["reason_code"], "ATTEMPT_NOT_RESERVED", unreserved)

    def test_observation_is_appended_without_a_second_reservation(self) -> None:
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        recorded = self.ledger.record_observation(
            "attempt-001", self.fixture.observation()
        )
        self.assertEqual(recorded["status"], "pass", recorded)
        view = self.ledger.observe("attempt-001")
        self.assertEqual(view["current_state"], "observed", view)
        recovered = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )
        self.assertEqual(recovered.observe("attempt-001")["current_state"], "observed")

    def test_observation_archive_rejects_symlink_parent_and_target_without_escape(
        self,
    ) -> None:
        for attack in ("parent", "target"):
            with self.subTest(attack=attack):
                fixture = LedgerFixture()
                try:
                    ledger = HostTaskLedger(
                        fixture.base_dir, fixture.host, fixture.host.identity, None
                    )
                    self.assertTrue(
                        ledger.reserve(fixture.request(), "start_child")[
                            "launch_allowed"
                        ]
                    )
                    observation = fixture.observation()
                    summary = {
                        key: value
                        for key, value in observation.items()
                        if key != "stdout"
                    }
                    observation_digest = _d(summary)
                    task_root = fixture.base_dir / fixture.task_id
                    archive = (
                        task_root
                        / "attempts"
                        / "attempt-001"
                        / "observations"
                        / f"{observation_digest}.json"
                    )
                    outside = Path(fixture.tmp.name) / f"outside-observation-{attack}"
                    outside.mkdir()
                    escaped = outside / "escaped.json"
                    if attack == "parent":
                        (task_root / "attempts").symlink_to(
                            outside, target_is_directory=True
                        )
                    else:
                        archive.parent.mkdir(parents=True)
                        escaped.write_text("sentinel\n", encoding="utf-8")
                        archive.symlink_to(escaped)

                    rejected = ledger.record_observation(
                        "attempt-001", observation
                    )

                    self.assertEqual(rejected["status"], "unknown", rejected)
                    self.assertEqual(
                        rejected["reason_code"],
                        "OBSERVATION_COMMIT_UNKNOWN",
                        rejected,
                    )
                    if attack == "parent":
                        self.assertFalse(
                            any(outside.rglob("*.json")),
                            "archive escaped through a symlinked parent",
                        )
                    else:
                        self.assertTrue(archive.is_symlink())
                        self.assertEqual(
                            escaped.read_text(encoding="utf-8"), "sentinel\n"
                        )
                    events = [
                        json.loads(line)
                        for line in (task_root / "events.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ]
                    self.assertNotIn(
                        "host-attempt-observed",
                        [event["event_type"] for event in events],
                    )
                finally:
                    fixture.close()

    def test_result_is_archived_then_processed_without_business_action(self) -> None:
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        published = self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": "attempt-001",
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": self.fixture.request()["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "actual synthetic result body\n",
            }
        )
        self.assertEqual(published["status"], "pass", published)

        class Verifier:
            def verify(self, request: dict[str, object]) -> dict[str, str]:
                return (
                    {"status": "pass"}
                    if request["content"] == "actual synthetic result body\n"
                    else {"status": "fail"}
                )

        processed = self.ledger.reconcile_result(
            "attempt-001", "result-001", Verifier()
        )
        self.assertEqual(processed["status"], "pass", processed)
        self.assertEqual(processed["action_state"], "not_started", processed)

    def test_result_archive_rejects_symlink_parent_and_target_without_escape(
        self,
    ) -> None:
        for attack in ("parent", "target"):
            with self.subTest(attack=attack):
                fixture = LedgerFixture()
                try:
                    ledger = HostTaskLedger(
                        fixture.base_dir, fixture.host, fixture.host.identity, None
                    )
                    request = fixture.request()
                    self.assertTrue(
                        ledger.reserve(request, "start_child")["launch_allowed"]
                    )
                    content = "symlink-safe result\n"
                    content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    task_root = fixture.base_dir / fixture.task_id
                    archive = (
                        task_root
                        / "results"
                        / "attempt-001"
                        / "result-001"
                        / f"{content_digest}.json"
                    )
                    outside = Path(fixture.tmp.name) / f"outside-result-{attack}"
                    outside.mkdir()
                    escaped = outside / "escaped.json"
                    if attack == "parent":
                        (task_root / "results").symlink_to(
                            outside, target_is_directory=True
                        )
                    else:
                        archive.parent.mkdir(parents=True)
                        escaped.write_text("sentinel\n", encoding="utf-8")
                        archive.symlink_to(escaped)

                    rejected = ledger.publish_result(
                        {
                            "task_id": fixture.task_id,
                            "attempt_id": "attempt-001",
                            "result_version": "result-001",
                            "contract_version": 1,
                            "contract_digest": request["contract_digest"],
                            "baseline": fixture.baseline,
                            "workspace_root": str(fixture.workspace.resolve()),
                            "content": content,
                        }
                    )

                    self.assertEqual(rejected["status"], "unknown", rejected)
                    self.assertEqual(
                        rejected["reason_code"],
                        "RESULT_PUBLICATION_UNKNOWN",
                        rejected,
                    )
                    if attack == "parent":
                        self.assertFalse(
                            any(outside.rglob("*.json")),
                            "archive escaped through a symlinked parent",
                        )
                    else:
                        self.assertTrue(archive.is_symlink())
                        self.assertEqual(
                            escaped.read_text(encoding="utf-8"), "sentinel\n"
                        )
                    events = [
                        json.loads(line)
                        for line in (task_root / "events.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ]
                    self.assertNotIn(
                        "host-result-published",
                        [event["event_type"] for event in events],
                    )
                finally:
                    fixture.close()

    def test_fifo_result_archive_is_rejected_without_processing_event(self) -> None:
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": "attempt-001",
                "result_version": "result-fifo",
                "contract_version": 1,
                "contract_digest": self.fixture.request()["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "body",
            }
        )
        events = [
            json.loads(line)
            for line in (self.fixture.base_dir / self.fixture.task_id / "events.jsonl")
            .read_text()
            .splitlines()
        ]
        archive = (
            self.fixture.base_dir
            / self.fixture.task_id
            / next(
                e["payload"]["archive_ref"]["uri"]
                for e in events
                if e["event_type"] == "host-result-published"
            )
        )
        archive.unlink()
        os.mkfifo(archive)

        class V:
            def verify(self, _request: dict[str, object]) -> dict[str, str]:
                return {"status": "pass"}

        self.assertEqual(
            self.ledger.reconcile_result("attempt-001", "result-fifo", V())["status"],
            "unknown",
        )

    def test_expired_host_observation_does_not_erase_history_or_authorize_new_start(
        self,
    ) -> None:
        self.assertTrue(
            self.ledger.reserve(self.fixture.request(), "start_child")["launch_allowed"]
        )
        self.fixture.host.state_path.write_text(
            json.dumps(
                {
                    "identity": "registered-host-1",
                    "exclusive": True,
                    "thread_state": "idle",
                    "ttl_seconds": -1,
                }
            )
        )
        fresh = HostTaskLedger(
            self.fixture.base_dir, self.fixture.host, self.fixture.host.identity, None
        )
        self.assertEqual(fresh.observe("attempt-001")["status"], "pass")
        blocked = fresh.reserve(
            self.fixture.request(attempt_id="attempt-002"), "start_child"
        )
        self.assertFalse(blocked["launch_allowed"], blocked)

    def test_replacement_makes_late_prior_result_historical_not_processable(
        self,
    ) -> None:
        first = self.fixture.request()
        self.assertTrue(self.ledger.reserve(first, "start_child")["launch_allowed"])
        ended = self.fixture.observation()
        ended["thread_id"] = "11111111-1111-4111-8111-111111111111"
        self.assertEqual(
            self.ledger.record_observation("attempt-001", ended)["status"], "pass"
        )
        replacement = self.fixture.request(attempt_id="attempt-002")
        self.assertTrue(
            self.ledger.reserve(replacement, "start_child")["launch_allowed"]
        )
        late = self.ledger.publish_result(
            {
                "task_id": self.fixture.task_id,
                "attempt_id": "attempt-001",
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": first["contract_digest"],
                "baseline": self.fixture.baseline,
                "workspace_root": str(self.fixture.workspace.resolve()),
                "content": "late prior result",
            }
        )
        self.assertEqual(late["status"], "unknown", late)
        self.assertEqual(late["reason_code"], "LATE_RESULT_REQUIRES_REVIEW", late)
        events = [
            json.loads(line)
            for line in (self.fixture.base_dir / self.fixture.task_id / "events.jsonl")
            .read_text()
            .splitlines()
        ]
        published = next(
            event["payload"]
            for event in events
            if event["event_type"] == "host-result-published"
        )
        self.assertTrue(published["late"], published)
        verifier = type(
            "Verifier", (), {"verify": lambda self, _request: {"status": "pass"}}
        )()
        rejected = self.ledger.reconcile_result("attempt-001", "result-001", verifier)
        self.assertEqual(rejected["status"], "unknown", rejected)
        self.assertEqual(
            rejected["reason_code"], "ATTEMPT_SUPERSEDED_BY_REPLACEMENT", rejected
        )

    def test_observe_keeps_latest_bounded_summary_and_marks_truncation_unknown(
        self,
    ) -> None:
        request = self.fixture.request()
        self.assertTrue(self.ledger.reserve(request, "start_child")["launch_allowed"])
        common = {
            "task_id": self.fixture.task_id,
            "attempt_id": "attempt-001",
            "contract_version": 1,
            "contract_digest": request["contract_digest"],
            "baseline": self.fixture.baseline,
            "workspace_root": str(self.fixture.workspace.resolve()),
        }
        for number in range(65):
            published = self.ledger.publish_result(
                {
                    **common,
                    "result_version": f"result-{number:03d}",
                    "content": f"body-{number}",
                }
            )
            self.assertEqual(published["status"], "pass", published)
        view = self.ledger.observe("attempt-001")
        self.assertEqual(view["status"], "unknown", view)
        self.assertEqual(view["reason_code"], "SUMMARY_LIMIT", view)
        self.assertTrue(view["summary_truncated"], view)
        self.assertEqual(view["result_total"], 65, view)
        self.assertEqual(len(view["results"]), 64, view)
        self.assertEqual(view["results"][-1]["result_version"], "result-064", view)

    def test_prepared_rejects_reserve_and_child_cannot_cross_attempt_result(
        self,
    ) -> None:
        handoff = HandoffGateFixture(
            truth_sources=False, rule_execution=False, independent_validation=False
        )
        self.addCleanup(handoff.close)
        identity = object()
        now = datetime.now(timezone.utc).replace(microsecond=0)

        class Host:
            task_id = handoff.task_id
            registered_runtime_identity = identity

            def observe_execution_state(
                self, request: dict[str, object], _operation: str
            ) -> dict[str, object]:
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
                        "registered_identity_id": "host",
                        "sha256": "e" * 64,
                    },
                    "exclusivity_status": "exclusive",
                    "thread_state": "idle",
                    "observed_at": as_zulu(now),
                    "expires_at": as_zulu(now + timedelta(minutes=1)),
                    "observation_ref": {
                        "ref_id": "hostobs",
                        "uri": "file:///private/tmp/hostobs",
                        "sha256": "f" * 64,
                    },
                    "request_binding_sha256": canonical_sha256(
                        {
                            key: request[key]
                            for key in (
                                "task_id",
                                "attempt_id",
                                "thread_id",
                                "workspace_root",
                            )
                        }
                    ),
                }

        def request(attempt_id: str) -> dict[str, object]:
            return {
                "task_id": handoff.task_id,
                "attempt_id": attempt_id,
                "contract_version": 1,
                "contract_digest": handoff.contract_digest,
                "baseline": "baseline",
                "workspace_root": str(handoff.workspace.resolve()),
                "controller_generation": 0,
                "thread_id": None,
                "argv_sha256": "a" * 64,
                "config_digest": "b" * 64,
                "prompt_sha256": "c" * 64,
                "authorization_digest": "d" * 64,
            }

        def ended_observation(attempt_id: str) -> dict[str, object]:
            observed_at = as_zulu(now)
            stdout = "ended\n"
            return {
                "task_id": handoff.task_id,
                "attempt_id": attempt_id,
                "reservation_id": f"resv.{attempt_id}",
                "operation": "start_child",
                "argv_sha256": "a" * 64,
                "cwd": str(handoff.workspace.resolve()),
                "thread_id": "11111111-1111-4111-8111-111111111111",
                "exit_status": 0,
                "timeout": None,
                "observed_at": observed_at,
                "stdout": stdout,
                "stdout_digest": __import__("hashlib")
                .sha256(stdout.encode())
                .hexdigest(),
                "stdout_bytes": len(stdout.encode()),
                "stdout_utf8": True,
                "host_identity_ref": {
                    "registered_identity_id": "host",
                    "sha256": "e" * 64,
                },
                "host_exclusivity_status": "exclusive",
                "host_observed_at": observed_at,
                "host_observation_ref": {
                    "ref_id": "hostobs",
                    "uri": "file:///private/tmp/hostobs",
                    "sha256": "f" * 64,
                },
                "stderr_digest": __import__("hashlib").sha256(b"").hexdigest(),
                "stderr_bytes": 0,
                "output_over_limit": False,
            }

        host = Host()
        unfenced = HostTaskLedger(handoff.base_dir, host, identity, None)
        self.assertTrue(
            unfenced.reserve(request("attempt-001"), "start_child")["launch_allowed"]
        )
        self.assertEqual(
            unfenced.record_observation(
                "attempt-001", ended_observation("attempt-001")
            )["status"],
            "pass",
        )
        self.assertTrue(
            unfenced.reserve(request("attempt-002"), "start_child")["launch_allowed"]
        )
        self.assertEqual(
            unfenced.record_observation(
                "attempt-002", ended_observation("attempt-002")
            )["status"],
            "pass",
        )
        self.assertEqual(handoff.prepare()["check_status"], "pass")

        class ChildAuthority:
            def authorize(self, incoming: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "pass",
                    "operation": incoming["operation"],
                    "purpose": "result",
                    "task_id": incoming["task_id"],
                    "base_dir": incoming["base_dir"],
                    "workspace_root": incoming["workspace_root"],
                    "package_manifest_sha256": incoming["package_manifest_sha256"],
                    "contract_version": incoming["contract_version"],
                    "contract_digest": incoming["contract_digest"],
                    "controller_generation": incoming["controller_generation"],
                    "handoff_id": incoming["handoff_id"],
                    "arguments_sha256": incoming["arguments_sha256"],
                    "subject_id": "child",
                    "role": "child",
                    "scope_digest": "a" * 64,
                    "work_item_id": "attempt-002",
                    "source_session_ref": handoff.record["source_session_ref"],
                    "target_session_ref": handoff.record["target_session_ref"],
                    "authorization_ref": handoff.record["authorization_ref"],
                    "target_activation_status": "not_activated",
                    "observed_at": as_zulu(now),
                    "expires_at": as_zulu(now + timedelta(minutes=1)),
                }

        fenced = HostTaskLedger(handoff.base_dir, host, identity, ChildAuthority())
        prepared_reserve = fenced.reserve(request("attempt-003"), "start_child")
        self.assertEqual(prepared_reserve["status"], "unknown", prepared_reserve)
        self.assertEqual(
            prepared_reserve["reason_code"],
            "HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED",
            prepared_reserve,
        )
        own = fenced.publish_result(
            {
                "task_id": handoff.task_id,
                "attempt_id": "attempt-002",
                "result_version": "result-002",
                "contract_version": 1,
                "contract_digest": handoff.contract_digest,
                "baseline": "baseline",
                "workspace_root": str(handoff.workspace.resolve()),
                "content": "owned child result",
            }
        )
        self.assertEqual(own["status"], "pass", own)
        cross = fenced.publish_result(
            {
                "task_id": handoff.task_id,
                "attempt_id": "attempt-001",
                "result_version": "result-001",
                "contract_version": 1,
                "contract_digest": handoff.contract_digest,
                "baseline": "baseline",
                "workspace_root": str(handoff.workspace.resolve()),
                "content": "cross attempt result",
            }
        )
        self.assertEqual(cross["status"], "unknown", cross)
        self.assertEqual(
            cross["reason_code"], "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH", cross
        )

    def _reserve_after_prepare_or_cancel(
        self,
        operation: str,
        attempt_id: str,
        *,
        cancel: bool = True,
        subject_ref: str = "source",
        controller_generation: int = 0,
        matching_host_identity: bool = True,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """A source controller stays dispatch-eligible after its handoff is cancelled."""
        fixture = LedgerFixture()
        self.addCleanup(fixture.close)
        package = fixture.workspace.parent / "package"
        package.mkdir()
        manifest = package / "skill-manifest.json"
        manifest.write_text("synthetic fixture package\n", encoding="utf-8")
        contents = {
            "source": "synthetic source controller\n",
            "target": "synthetic target controller\n",
            "authorization": "synthetic source may dispatch\n",
            "basis": "frozen synthetic baseline\n",
            "artifacts": "synthetic handoff materials\n",
        }
        refs = {}
        for key, content in contents.items():
            path = fixture.workspace / f"{key}.txt"
            path.write_text(content, encoding="utf-8")
            refs[key] = _ref(fixture.task_id, key, path)
        events_path = fixture.base_dir / fixture.task_id / "events.jsonl"
        cursor = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])["event_id"]
        request = fixture.request(
            attempt_id=attempt_id,
            thread_id=(
                "11111111-1111-4111-8111-111111111111"
                if operation == "resume_child"
                else None
            ),
        )
        request["controller_generation"] = controller_generation
        fixture.host.registered_requests[attempt_id] = request
        record = {
            "protocol": "short-session-handoff/v1",
            "task_id": fixture.task_id,
            "contract_version": request["contract_version"],
            "contract_digest": request["contract_digest"],
            "workspace_root": str(fixture.workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "handoff_id": "HO-CANCELLED-SOURCE",
            "request_id": "REQ-PREPARE-CANCELLED-SOURCE",
            "controller_generation": 0,
            "source_session_ref": refs["source"],
            "target_session_ref": refs["target"],
            "authorization_ref": refs["authorization"],
            "basis_refs": [refs["basis"]],
            "artifact_manifest_ref": refs["artifacts"],
            "created_at": "2026-09-15T00:00:00Z",
            "event_cursor": cursor,
        }
        verifier = ActivationVerifier(record, contents)

        class InitialAuthority(ActivationAuthority):
            def authorize(self, incoming: dict[str, object]) -> dict[str, object]:
                response = super().authorize(incoming)
                response.pop("subject_session_ref", None)
                return response

        prepare_identity = object()
        common = {
            "base_dir": fixture.base_dir,
            "workspace_root": fixture.workspace,
            "package_root": package,
            "controller_generation": 0,
            "handoff_verifier": verifier,
        }
        prepared = context.prepare_handoff(
            fixture.task_id,
            **common,
            request_id=record["request_id"],
            record=record,
            runtime_identity=prepare_identity,
            write_authorizer=InitialAuthority(record, prepare_identity, purpose="prepare"),
        )
        self.assertEqual(prepared["check_status"], "pass", prepared)
        if cancel:
            cancel_identity = object()
            cancelled = context.cancel_handoff(
                fixture.task_id,
                **common,
                request_id="REQ-CANCEL-CANCELLED-SOURCE",
                handoff_id=record["handoff_id"],
                runtime_identity=cancel_identity,
                write_authorizer=InitialAuthority(record, cancel_identity, purpose="cancel"),
            )
            self.assertEqual(cancelled["check_status"], "pass", cancelled)

        dispatch_identity = fixture.host.identity if matching_host_identity else object()
        arguments = {
            "operation": "host_reserve",
            "task_id": fixture.task_id,
            "base_dir": str(fixture.base_dir.resolve()),
            "attempt_id": request["attempt_id"],
            "request_sha256": digest(request),
        }
        arguments["operation"] = operation
        expected = {
            "operation": "host_reserve",
            "task_id": fixture.task_id,
            "base_dir": str(fixture.base_dir.resolve()),
            "workspace_root": str(fixture.workspace.resolve()),
            "package_manifest_sha256": record["package_manifest_sha256"],
            "contract_version": 1,
            "contract_digest": record["contract_digest"],
            "controller_generation": controller_generation,
            "handoff_id": record["handoff_id"],
            "arguments_sha256": digest(arguments),
        }

        class SourceAuthority:
            def authorize(self, incoming: dict[str, object]) -> dict[str, object]:
                if incoming.get("runtime_identity") is not dispatch_identity:
                    return {"status": "unknown"}
                if any(incoming.get(key) != value for key, value in expected.items()):
                    return {"status": "unknown"}
                if incoming.get("arguments") != arguments:
                    return {"status": "unknown"}
                if any(
                    (fixture.workspace / f"{key}.txt").read_text(encoding="utf-8")
                    != value
                    for key, value in contents.items()
                ):
                    return {"status": "unknown"}
                now = datetime.now(timezone.utc).replace(microsecond=0)
                return {
                    "status": "pass",
                    **expected,
                    "purpose": "dispatch",
                    "subject_id": "registered-source",
                    "role": "controller",
                    "scope_digest": digest(contents["authorization"]),
                    "work_item_id": None,
                    "subject_session_ref": deepcopy(refs[subject_ref]),
                    "source_session_ref": deepcopy(refs["source"]),
                    "target_session_ref": deepcopy(refs["target"]),
                    "authorization_ref": deepcopy(refs["authorization"]),
                    "target_activation_status": "not_activated",
                    "observed_at": as_zulu(now),
                    "expires_at": as_zulu(now + timedelta(minutes=1)),
                }

        ledger = HostTaskLedger(
            fixture.base_dir, fixture.host, dispatch_identity, SourceAuthority()
        )
        first = ledger.reserve(request, operation)
        repeated = ledger.reserve(request, operation)
        return first, repeated

    def test_cancelled_source_controller_can_reserve_start_once(self) -> None:
        first, repeated = self._reserve_after_prepare_or_cancel(
            "start_child", "attempt-001"
        )
        self.assertEqual(first["status"], "pass", first)
        self.assertTrue(first["launch_allowed"], first)
        self.assertEqual(repeated["reason_code"], "ALREADY_RESERVED", repeated)
        self.assertFalse(repeated["launch_allowed"], repeated)

    def test_cancelled_source_controller_can_reserve_resume_once(self) -> None:
        first, repeated = self._reserve_after_prepare_or_cancel(
            "resume_child", "attempt-002"
        )
        self.assertEqual(first["status"], "pass", first)
        self.assertTrue(first["launch_allowed"], first)
        self.assertEqual(repeated["reason_code"], "ALREADY_RESERVED", repeated)
        self.assertFalse(repeated["launch_allowed"], repeated)

    def test_cancelled_handoff_rejects_target_session_controller(self) -> None:
        result, _ = self._reserve_after_prepare_or_cancel(
            "start_child", "attempt-001", subject_ref="target"
        )
        self.assertEqual(result["status"], "unknown", result)
        self.assertFalse(result["launch_allowed"], result)

    def test_cancelled_handoff_rejects_unregistered_host_identity(self) -> None:
        result, _ = self._reserve_after_prepare_or_cancel(
            "start_child", "attempt-001", matching_host_identity=False
        )
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(result["reason_code"], "HOST_RUNTIME_IDENTITY_MISMATCH", result)
        self.assertFalse(result["launch_allowed"], result)

    def test_cancelled_handoff_rejects_wrong_controller_generation(self) -> None:
        result, _ = self._reserve_after_prepare_or_cancel(
            "start_child", "attempt-001", controller_generation=1
        )
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(result["reason_code"], "CONTROLLER_GENERATION_MISMATCH", result)
        self.assertFalse(result["launch_allowed"], result)

    def test_prepared_handoff_still_rejects_source_controller_dispatch(self) -> None:
        result, _ = self._reserve_after_prepare_or_cancel(
            "start_child", "attempt-001", cancel=False
        )
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(
            result["reason_code"], "HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED", result
        )
        self.assertFalse(result["launch_allowed"], result)
