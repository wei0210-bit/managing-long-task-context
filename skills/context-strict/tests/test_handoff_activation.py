from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _ref(task_id: str, ref_id: str, path: Path) -> dict[str, str]:
    return {
        "ref_id": ref_id, "task_id": task_id, "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class ActivationVerifier:
    def __init__(self, record: dict[str, object], contents: dict[str, str]) -> None:
        self.record = record
        self.contents = contents

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        refs = [
            self.record["source_session_ref"], self.record["target_session_ref"],
            self.record["authorization_ref"], *self.record["basis_refs"],
            self.record["artifact_manifest_ref"],
        ]
        for ref in refs:
            assert isinstance(ref, dict)
            path = Path(unquote(urlsplit(ref["uri"]).path))
            if path.read_text(encoding="utf-8") != self.contents[ref["ref_id"]]:
                return {"status": "fail"}
        expected = {
            "task_id": self.record["task_id"], "handoff_id": self.record["handoff_id"],
            "record_sha256": _digest(self.record),
            "contract_version": self.record["contract_version"],
            "contract_digest": self.record["contract_digest"],
            "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "controller_generation": self.record["controller_generation"],
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "status": "pass", "identity_status": "pass", "authorization_status": "pass",
            "content_status": "pass", **expected, "verification_refs": refs,
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


class ActivationAuthority:
    """Synthetic registered-host policy; it never derives identity from the request."""

    def __init__(self, record: dict[str, object], identity: object, *, purpose: str) -> None:
        self.record = record
        self.identity = identity
        self.purpose = purpose

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        if request.get("runtime_identity") is not self.identity:
            return {"status": "unknown"}
        arguments = request.get("arguments")
        if not isinstance(arguments, dict) or request.get("arguments_sha256") != _digest(arguments):
            return {"status": "unknown"}
        target = self.record["target_session_ref"]
        source = self.record["source_session_ref"]
        assert isinstance(target, dict) and isinstance(source, dict)
        expected = {
            "task_id": self.record["task_id"], "base_dir": request.get("base_dir"),
            "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": self.record["contract_version"],
            "contract_digest": self.record["contract_digest"],
            "controller_generation": self.record["controller_generation"],
            "handoff_id": self.record["handoff_id"], "operation": self.purpose + "_handoff",
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "status": "pass", **expected, "arguments_sha256": _digest(arguments),
            "purpose": self.purpose, "subject_id": "synthetic:target-controller",
            "subject_session_ref": deepcopy(target if self.purpose == "activate" else source),
            "role": "controller", "scope_digest": "a" * 64, "work_item_id": None,
            "source_session_ref": deepcopy(source), "target_session_ref": deepcopy(target),
            "authorization_ref": deepcopy(self.record["authorization_ref"]),
            "target_activation_status": "not_activated",
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


class HandoffActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.base_dir, self.workspace, self.package = root / "context", root / "workspace", root / "package"
        self.workspace.mkdir()
        self.package.mkdir()
        (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
        self.task_id, self.handoff_id = "TASK-ACTIVATION-001", "HO-ACTIVATION-001"
        published = context.publish_contract({
            "schema": 1, "task_id": self.task_id, "version": 1, "issued_by": "publisher",
            "issued_at": "2026-09-15T00:00:00Z", "authorized_approvers": [],
            "objective": "synthetic activation", "scope": ["isolated"], "out_of_scope": [],
            "constraints": ["no business action"],
            "acceptance_criteria": [{"id": "AC-01", "criterion": "activate", "required_evidence": ["synthetic"]}],
        }, confirmed_by="publisher", base_dir=self.base_dir)
        cursor = json.loads((self.base_dir / self.task_id / "events.jsonl").read_text().splitlines()[-1])["event_id"]
        self.contents = {"source": "source\n", "target": "target\n", "authorization": "scope\n", "basis": "basis\n", "artifacts": "artifacts\n"}
        refs = {}
        for ref_id, text in self.contents.items():
            path = self.workspace / f"{ref_id}.txt"
            path.write_text(text, encoding="utf-8")
            refs[ref_id] = _ref(self.task_id, ref_id, path)
        self.record: dict[str, object] = {
            "protocol": "short-session-handoff/v1", "task_id": self.task_id,
            "contract_version": 1, "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
            "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256((self.package / "skill-manifest.json").read_bytes()).hexdigest(),
            "handoff_id": self.handoff_id, "request_id": "REQ-PREPARE-ACTIVATION", "controller_generation": 0,
            "source_session_ref": refs["source"], "target_session_ref": refs["target"],
            "authorization_ref": refs["authorization"], "basis_refs": [refs["basis"]],
            "artifact_manifest_ref": refs["artifacts"], "created_at": "2026-09-15T00:00:01Z", "event_cursor": cursor,
        }
        self.verifier = ActivationVerifier(self.record, self.contents)
        self.prepare_identity, self.activate_identity = object(), object()
        self.assertEqual(self._prepare()["check_status"], "pass")

    def _prepare(self) -> dict[str, object]:
        arguments = {
            "operation": "prepare_handoff", "task_id": self.task_id, "base_dir": str(self.base_dir.resolve()),
            "workspace_root": str(self.workspace.resolve()), "package_root": str(self.package.resolve()),
            "request_id": self.record["request_id"], "controller_generation": 0, "record": self.record,
        }
        class PrepareAuthority(ActivationAuthority):
            def authorize(authority, request):
                response = super().authorize(request)
                response.pop("subject_session_ref", None)
                return response
        return context.prepare_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id=str(self.record["request_id"]), controller_generation=0, record=self.record,
            runtime_identity=self.prepare_identity,
            write_authorizer=PrepareAuthority(self.record, self.prepare_identity, purpose="prepare"),
            handoff_verifier=self.verifier,
        )

    def test_target_confirmed_activation_appends_once_and_advances_generation(self) -> None:
        result = context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-ACTIVATE-001", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=self.activate_identity,
            write_authorizer=ActivationAuthority(self.record, self.activate_identity, purpose="activate"),
            handoff_verifier=self.verifier,
        )

        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        self.assertEqual(result["controller_generation"], 1, result)
        events = [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text().splitlines()]
        activated = [event for event in events if event["event_type"] == "handoff_activated"]
        self.assertEqual(len(activated), 1)
        self.assertEqual(activated[0]["payload"]["controller_generation"], 1)

    def test_status_preserves_durable_activation_when_current_verifier_is_unavailable(self) -> None:
        self.test_target_confirmed_activation_appends_once_and_advances_generation()

        report = context.handoff_status(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["commit_status"], "confirmed_committed", report)
        self.assertEqual(report["controller_generation"], 1, report)

    def test_cancelled_handoff_keeps_original_controller_for_the_next_prepare(self) -> None:
        cancel_identity = object()
        class InitialCancelAuthority(ActivationAuthority):
            def authorize(authority, request):
                response = super().authorize(request)
                response.pop("subject_session_ref", None)
                return response
        cancelled = context.cancel_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-CANCEL-ACTIVATION", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=cancel_identity,
            write_authorizer=InitialCancelAuthority(self.record, cancel_identity, purpose="cancel"),
            handoff_verifier=self.verifier,
        )
        self.assertEqual(cancelled["check_status"], "pass", cancelled)
        target_path = self.workspace / "target-next.txt"
        target_path.write_text("target next\n", encoding="utf-8")
        second = deepcopy(self.record)
        second.update({"handoff_id": "HO-ACTIVATION-002", "request_id": "REQ-PREPARE-ACTIVATION-002"})
        second["target_session_ref"] = _ref(self.task_id, "target-next", target_path)
        identity = object()
        result = context.prepare_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-PREPARE-ACTIVATION-002", controller_generation=0, record=second,
            runtime_identity=identity,
            write_authorizer=ActivationAuthority(second, identity, purpose="prepare"),
            handoff_verifier=ActivationVerifier(second, {**self.contents, "target-next": "target next\n"}),
        )

        self.assertEqual(result["check_status"], "pass", result)
        events = [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event_type"] for event in events].count("handoff_prepared"), 2)

    def test_two_activations_advance_generation_and_keep_first_commit_history(self) -> None:
        self.test_target_confirmed_activation_appends_once_and_advances_generation()
        target_path = self.workspace / "target-second.txt"
        target_path.write_text("target second\n", encoding="utf-8")
        second = deepcopy(self.record)
        second.update({
            "handoff_id": "HO-ACTIVATION-SECOND", "request_id": "REQ-PREPARE-SECOND",
            "controller_generation": 1, "source_session_ref": deepcopy(self.record["target_session_ref"]),
            "target_session_ref": _ref(self.task_id, "target-second", target_path),
        })
        second_contents = {**self.contents, "target-second": "target second\n"}
        prepare_identity = object()
        prepared = context.prepare_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-PREPARE-SECOND", controller_generation=1, record=second,
            runtime_identity=prepare_identity,
            write_authorizer=ActivationAuthority(second, prepare_identity, purpose="prepare"),
            handoff_verifier=ActivationVerifier(second, second_contents),
        )
        self.assertEqual(prepared["check_status"], "pass", prepared)
        activate_identity = object()
        activated = context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-ACTIVATE-SECOND", controller_generation=1, handoff_id="HO-ACTIVATION-SECOND",
            runtime_identity=activate_identity,
            write_authorizer=ActivationAuthority(second, activate_identity, purpose="activate"),
            handoff_verifier=ActivationVerifier(second, second_contents),
        )
        first_status = context.handoff_status(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            handoff_id=self.handoff_id, handoff_verifier=self.verifier,
        )

        self.assertEqual(activated["controller_generation"], 2, activated)
        self.assertEqual(first_status["commit_status"], "confirmed_committed", first_status)
        self.assertEqual(first_status["controller_generation"], 1, first_status)

    def test_active_generation_and_source_mismatch_are_rejected_without_a_control_event(self) -> None:
        self.test_target_confirmed_activation_appends_once_and_advances_generation()
        before = (self.base_dir / self.task_id / "events.jsonl").read_bytes()
        bad = deepcopy(self.record)
        bad.update({"handoff_id": "HO-BAD-SOURCE", "request_id": "REQ-BAD-SOURCE", "controller_generation": 1})
        identity = object()
        prepared = context.prepare_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-BAD-SOURCE", controller_generation=1, record=bad,
            runtime_identity=identity,
            write_authorizer=ActivationAuthority(bad, identity, purpose="prepare"),
            handoff_verifier=ActivationVerifier(bad, self.contents),
        )
        activation_identity = object()
        wrong_generation = context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-WRONG-GENERATION", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=activation_identity,
            write_authorizer=ActivationAuthority(self.record, activation_identity, purpose="activate"),
            handoff_verifier=self.verifier,
        )

        self.assertNotEqual(prepared["check_status"], "pass", prepared)
        self.assertNotEqual(wrong_generation["check_status"], "pass", wrong_generation)
        self.assertEqual((self.base_dir / self.task_id / "events.jsonl").read_bytes(), before)

    def test_precommit_bearing_evidence_change_is_not_an_attempted_commit(self) -> None:
        (self.workspace / "basis.txt").write_text("changed basis\n", encoding="utf-8")
        report = context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-ACTIVATE-CHANGED", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=self.activate_identity,
            write_authorizer=ActivationAuthority(self.record, self.activate_identity, purpose="activate"),
            handoff_verifier=self.verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["commit_status"], "not_attempted", report)

    def _run_registered_child_delta(self, mode: str = "pass") -> tuple[dict[str, object], list[dict[str, object]], bytes]:
        child_identity = object()
        observed: list[dict[str, object]] = []

        class ChildAuthority:
            def authorize(_, request):
                arguments = request.get("arguments")
                if request.get("runtime_identity") is not child_identity or not isinstance(arguments, dict):
                    return {"status": "unknown"}
                if request.get("operation") != "record" or arguments.get("statement") != "child progress during activation":
                    return {"status": "unknown"}
                now = datetime.now(timezone.utc).replace(microsecond=0)
                return {
                    "status": "pass", "operation": "record", "purpose": "progress",
                    "task_id": self.record["task_id"], "base_dir": str(self.base_dir.resolve()),
                    "workspace_root": self.record["workspace_root"],
                    "package_manifest_sha256": self.record["package_manifest_sha256"],
                    "contract_version": 1, "contract_digest": self.record["contract_digest"],
                    "controller_generation": 0, "handoff_id": self.handoff_id,
                    "arguments_sha256": _digest(arguments), "subject_id": "synthetic:child",
                    "role": "child", "scope_digest": "c" * 64, "work_item_id": "WORK-CHILD-1",
                    "source_session_ref": self.record["source_session_ref"],
                    "target_session_ref": self.record["target_session_ref"],
                    "authorization_ref": self.record["authorization_ref"],
                    "target_activation_status": "not_activated",
                    "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

        class DeltaVerifier(ActivationVerifier):
            did_write = False
            def verify(inner, request):
                result = super().verify(request)
                if not inner.did_write:
                    inner.did_write = True
                    event_path = self.base_dir / self.task_id / "events.jsonl"
                    before = event_path.read_bytes()
                    context.record(
                        self.task_id, statement="child progress during activation", item_type="observation",
                        actor="same-label", source="synthetic", base_dir=self.base_dir,
                        metadata={"blocking": True} if mode == "blocking" else None,
                        runtime_identity=child_identity, write_authorizer=ChildAuthority(),
                    )
                    after = event_path.read_bytes()
                    event = json.loads(after.splitlines()[-1])
                    inner.observed_child_delta = {
                        "before": hashlib.sha256(before).hexdigest(),
                        "after": hashlib.sha256(after).hexdigest(),
                        "event": event, "event_id": event["event_id"],
                        "event_digest": _digest([event]), "work_item_id": "WORK-CHILD-1",
                        "scope_digest": "c" * 64,
                    }
                return result
            def verify_delta(inner, request):
                observed.append(dict(request))
                actual = inner.observed_child_delta
                if (
                    request.get("before_events_sha256") != actual["before"]
                    or request.get("after_events_sha256") != actual["after"]
                    or request.get("delta_event_ids") != [actual["event_id"]]
                    or request.get("delta_events_sha256") != actual["event_digest"]
                    or request.get("delta_events") != [actual["event"]]
                    or actual["work_item_id"] != "WORK-CHILD-1" or actual["scope_digest"] != "c" * 64
                ):
                    return {"status": "unknown"}
                now = datetime.now(timezone.utc).replace(microsecond=0)
                if mode == "wrong_digest":
                    request = {**request, "delta_events_sha256": "0" * 64}
                if mode == "after_delta_change":
                    (self.workspace / "basis.txt").write_text("changed after delta\n", encoding="utf-8")
                return {
                    "status": "pass", **{key: request[key] for key in (
                        "task_id", "handoff_id", "record_sha256", "contract_version", "contract_digest",
                        "workspace_root", "package_manifest_sha256", "controller_generation",
                        "before_events_sha256", "after_events_sha256", "delta_event_ids", "delta_events_sha256",
                    )}, "non_bearing": True,
                    "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

        verifier = DeltaVerifier(self.record, self.contents)
        if mode == "missing":
            verifier.verify_delta = None  # type: ignore[method-assign]
        result = context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-ACTIVATE-DELTA", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=self.activate_identity,
            write_authorizer=ActivationAuthority(self.record, self.activate_identity, purpose="activate"),
            handoff_verifier=verifier,
        )

        event_bytes = (self.base_dir / self.task_id / "events.jsonl").read_bytes()
        return result, observed, event_bytes

    def test_registered_child_progress_delta_can_cross_activation_verification(self) -> None:
        result, observed, _ = self._run_registered_child_delta()
        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["delta_event_ids"].__class__, list)

    def test_unverifiable_or_bearing_child_delta_blocks_activation_without_rollback(self) -> None:
        for mode, expected_callbacks in (("missing", 0), ("wrong_digest", 1), ("after_delta_change", 1), ("blocking", 0)):
            with self.subTest(mode=mode):
                fixture = HandoffActivationTests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                result, observed, event_bytes = fixture._run_registered_child_delta(mode)
                events = [json.loads(line) for line in event_bytes.splitlines()]
                self.assertNotEqual(result["check_status"], "pass", result)
                self.assertEqual(len(observed), expected_callbacks)
                self.assertEqual([event["event_type"] for event in events].count("handoff_activated"), 0)
                self.assertIn("item-recorded", [event["event_type"] for event in events])
