from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _reference(task_id: str, ref_id: str, path: Path) -> dict[str, str]:
    return {
        "ref_id": ref_id,
        "task_id": task_id,
        "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class SyntheticWriteAuthorizer:
    """Synthetic trusted host; it derives its answer from isolated fixture files."""

    def __init__(self, expected: dict[str, object], record: dict[str, object], *, purpose: str = "prepare") -> None:
        self.expected = expected
        self.record = record
        self.purpose = purpose
        self.calls: list[dict[str, object]] = []

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(request))
        if any(request.get(key) != value for key, value in self.expected.items()):
            return {"status": "fail"}
        return {
            "status": "pass",
            **self.expected,
            "purpose": self.purpose,
            "subject_id": "synthetic:controller-old",
            "role": "controller",
            "scope_digest": "a" * 64,
            "work_item_id": None,
            "source_session_ref": self.record["source_session_ref"],
            "target_session_ref": self.record["target_session_ref"],
            "authorization_ref": self.record["authorization_ref"],
            "target_activation_status": "not_activated",
            "observed_at": "2026-09-15T00:00:01Z",
            "expires_at": "2030-01-01T00:00:00Z",
        }


class SyntheticHandoffVerifier:
    """A synthetic verifier that independently reads every declared fixture."""

    def __init__(self, record: dict[str, object], contents: dict[str, str]) -> None:
        self.record = record
        self.contents = contents

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        references = [
            self.record["source_session_ref"], self.record["target_session_ref"],
            self.record["authorization_ref"], *self.record["basis_refs"],
            self.record["artifact_manifest_ref"],
        ]
        for reference in references:
            assert isinstance(reference, dict)
            path = Path(unquote(urlsplit(reference["uri"]).path))
            if path.read_text(encoding="utf-8") != self.contents[reference["ref_id"]]:
                return {"status": "fail"}
        expected = {
            "task_id": self.record["task_id"], "handoff_id": self.record["handoff_id"],
            "record_sha256": _canonical_sha256(self.record),
            "contract_version": self.record["contract_version"],
            "contract_digest": self.record["contract_digest"],
            "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "controller_generation": self.record["controller_generation"],
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail"}
        return {
            "status": "pass", "identity_status": "pass", "authorization_status": "pass",
            "content_status": "pass", **expected, "verification_refs": references,
            "observed_at": "2026-09-15T00:00:01Z", "expires_at": "2030-01-01T00:00:00Z",
        }


class HandoffWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.base_dir = root / "context"
        self.workspace = root / "workspace"
        self.package = root / "package"
        self.workspace.mkdir()
        self.package.mkdir()
        (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
        self.task_id = "TASK-WRITE-001"
        self.handoff_id = "HO-WRITE-001"
        contract = {
            "schema": 1,
            "task_id": self.task_id,
            "version": 1,
            "issued_by": "publisher",
            "issued_at": "2026-09-15T00:00:00Z",
            "authorized_approvers": [],
            "objective": "Synthetic prepared handoff",
            "scope": ["isolated test"],
            "out_of_scope": [],
            "constraints": ["no business action"],
            "acceptance_criteria": [{
                "id": "AC-01", "criterion": "prepared", "required_evidence": ["synthetic"],
            }],
        }
        self.published = context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base_dir)
        root_path = self.base_dir / self.task_id
        event_cursor = json.loads((root_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
        references: dict[str, dict[str, str]] = {}
        self.reference_contents = {
            "source": "synthetic source controller\n",
            "target": "synthetic inactive target\n",
            "authorization": "synthetic original scope\n",
            "basis": "synthetic basis evidence\n",
            "artifacts": "synthetic artifact manifest\n",
        }
        for ref_id, content in self.reference_contents.items():
            path = self.workspace / f"{ref_id}.txt"
            path.write_text(content, encoding="utf-8")
            references[ref_id] = _reference(self.task_id, ref_id, path)
        self.record = {
            "protocol": "short-session-handoff/v1",
            "task_id": self.task_id,
            "contract_version": 1,
            "contract_digest": self.published["seal"]["integrity_digest"].removeprefix("sha256:"),
            "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256((self.package / "skill-manifest.json").read_bytes()).hexdigest(),
            "handoff_id": self.handoff_id,
            "request_id": "REQ-PREPARE-001",
            "controller_generation": 7,
            "source_session_ref": references["source"],
            "target_session_ref": references["target"],
            "authorization_ref": references["authorization"],
            "basis_refs": [references["basis"]],
            "artifact_manifest_ref": references["artifacts"],
            "created_at": "2026-09-15T00:00:01Z",
            "event_cursor": event_cursor,
        }

    def _prepare(self, *, record: dict[str, object] | None = None) -> dict[str, object]:
        actual_record = record or self.record
        arguments = {
            "operation": "prepare_handoff",
            "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()),
            "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()),
            "request_id": actual_record["request_id"],
            "controller_generation": actual_record["controller_generation"],
            "record": actual_record,
        }
        expected = {
            "operation": "prepare_handoff",
            "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()),
            "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": actual_record["package_manifest_sha256"],
            "contract_version": actual_record["contract_version"],
            "contract_digest": actual_record["contract_digest"],
            "controller_generation": actual_record["controller_generation"],
            "handoff_id": actual_record["handoff_id"],
            "arguments_sha256": _canonical_sha256(arguments),
        }
        authorizer = SyntheticWriteAuthorizer(expected, actual_record)
        return context.prepare_handoff(
            self.task_id,
            base_dir=self.base_dir,
            workspace_root=self.workspace,
            package_root=self.package,
            request_id=str(actual_record["request_id"]),
            controller_generation=int(actual_record["controller_generation"]),
            record=actual_record,
            runtime_identity=object(),
            write_authorizer=authorizer,
            handoff_verifier=SyntheticHandoffVerifier(actual_record, self.reference_contents),
        )

    def test_prepare_persists_one_bound_event_without_activating(self) -> None:
        result = self._prepare()

        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        self.assertEqual(result["controller_generation"], 7, result)
        task_root = self.base_dir / self.task_id
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), self.record)
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        prepared = events[-1]
        self.assertEqual(prepared["event_type"], "handoff_prepared")
        self.assertEqual(prepared["payload"]["record_sha256"], _canonical_sha256(self.record))
        self.assertEqual(prepared["payload"]["controller_generation"], 7)

    def test_repeating_the_same_prepare_request_is_idempotent(self) -> None:
        first = self._prepare()
        event_path = self.base_dir / self.task_id / "events.jsonl"
        before = event_path.read_bytes()

        second = self._prepare()

        self.assertEqual(first["commit_status"], "confirmed_committed", first)
        self.assertEqual(second["check_status"], "pass", second)
        self.assertEqual(second["commit_status"], "confirmed_committed", second)
        self.assertEqual(event_path.read_bytes(), before)

    def test_existing_prepare_does_not_bypass_wrong_workspace_or_package(self) -> None:
        self.assertEqual(self._prepare()["check_status"], "pass")
        alternate_workspace = self.temporary.name and Path(self.temporary.name) / "other-workspace"
        alternate_package = Path(self.temporary.name) / "other-package"
        alternate_workspace.mkdir()
        alternate_package.mkdir()
        (alternate_package / "skill-manifest.json").write_text("other package\n", encoding="utf-8")

        for label, kwargs in (
            ("workspace", {"workspace_root": alternate_workspace, "package_root": self.package}),
            ("package", {"workspace_root": self.workspace, "package_root": alternate_package}),
        ):
            with self.subTest(label=label):
                report = context.prepare_handoff(
                    self.task_id, base_dir=self.base_dir, request_id=self.record["request_id"],
                    controller_generation=7, record=self.record, **kwargs,
                )
                self.assertNotEqual(report["check_status"], "pass", report)

    def test_cancel_appends_one_fact_without_changing_generation(self) -> None:
        self._prepare()
        arguments = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()), "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
        }
        expected = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": 1, "contract_digest": self.record["contract_digest"],
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "arguments_sha256": _canonical_sha256(arguments),
        }
        authorizer = SyntheticWriteAuthorizer(expected, self.record, purpose="cancel")

        result = context.cancel_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, request_id="REQ-CANCEL-001", controller_generation=7,
            handoff_id=self.handoff_id, runtime_identity=object(),
            write_authorizer=authorizer,
            handoff_verifier=SyntheticHandoffVerifier(self.record, self.reference_contents),
        )

        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        self.assertEqual(result["controller_generation"], 7, result)
        events = [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[-1]["event_type"], "handoff_cancelled")
        self.assertEqual(events[-1]["payload"]["controller_generation"], 7)

    def test_repeating_the_same_cancel_request_is_idempotent(self) -> None:
        self._prepare()
        arguments = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()), "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
        }
        expected = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": 1, "contract_digest": self.record["contract_digest"],
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "arguments_sha256": _canonical_sha256(arguments),
        }
        kwargs = {
            "base_dir": self.base_dir, "workspace_root": self.workspace,
            "package_root": self.package, "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "runtime_identity": object(),
            "write_authorizer": SyntheticWriteAuthorizer(expected, self.record, purpose="cancel"),
            "handoff_verifier": SyntheticHandoffVerifier(self.record, self.reference_contents),
        }
        first = context.cancel_handoff(self.task_id, **kwargs)
        event_path = self.base_dir / self.task_id / "events.jsonl"
        before = event_path.read_bytes()

        second = context.cancel_handoff(self.task_id, **kwargs)

        self.assertEqual(first["check_status"], "pass", first)
        self.assertEqual(second["check_status"], "pass", second)
        self.assertEqual(event_path.read_bytes(), before)

    def test_existing_cancel_does_not_bypass_wrong_workspace_or_package(self) -> None:
        self.assertEqual(self._prepare()["check_status"], "pass")
        arguments = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()), "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
        }
        expected = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": 1, "contract_digest": self.record["contract_digest"],
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "arguments_sha256": _canonical_sha256(arguments),
        }
        self.assertEqual(context.cancel_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, request_id="REQ-CANCEL-001", controller_generation=7,
            handoff_id=self.handoff_id, runtime_identity=object(),
            write_authorizer=SyntheticWriteAuthorizer(expected, self.record, purpose="cancel"),
            handoff_verifier=SyntheticHandoffVerifier(self.record, self.reference_contents),
        )["check_status"], "pass")
        alternate_workspace = Path(self.temporary.name) / "other-workspace"
        alternate_package = Path(self.temporary.name) / "other-package"
        alternate_workspace.mkdir()
        alternate_package.mkdir()
        (alternate_package / "skill-manifest.json").write_text("other package\n", encoding="utf-8")

        for label, kwargs in (
            ("workspace", {"workspace_root": alternate_workspace, "package_root": self.package}),
            ("package", {"workspace_root": self.workspace, "package_root": alternate_package}),
        ):
            with self.subTest(label=label):
                report = context.cancel_handoff(
                    self.task_id, base_dir=self.base_dir, request_id="REQ-CANCEL-001",
                    controller_generation=7, handoff_id=self.handoff_id, **kwargs,
                )
                self.assertNotEqual(report["check_status"], "pass", report)

    def test_prepare_recovers_committed_event_when_snapshot_write_fails_after_fsync(self) -> None:
        original_replace = context.os.replace

        def fail_snapshot_replace(source: object, destination: object) -> None:
            if Path(destination).name == "snapshot.json":
                raise OSError("synthetic snapshot replacement failure")
            original_replace(source, destination)

        with patch.object(context.os, "replace", side_effect=fail_snapshot_replace):
            result = self._prepare()

        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        events = [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event_type"] for event in events].count("handoff_prepared"), 1)

    def test_cancel_recovers_committed_event_when_snapshot_write_fails_after_fsync(self) -> None:
        self.assertEqual(self._prepare()["check_status"], "pass")
        arguments = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()), "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
        }
        expected = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": 1, "contract_digest": self.record["contract_digest"],
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "arguments_sha256": _canonical_sha256(arguments),
        }
        original_replace = context.os.replace

        def fail_snapshot_replace(source: object, destination: object) -> None:
            if Path(destination).name == "snapshot.json":
                raise OSError("synthetic snapshot replacement failure")
            original_replace(source, destination)

        with patch.object(context.os, "replace", side_effect=fail_snapshot_replace):
            result = context.cancel_handoff(
                self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                package_root=self.package, request_id="REQ-CANCEL-001", controller_generation=7,
                handoff_id=self.handoff_id, runtime_identity=object(),
                write_authorizer=SyntheticWriteAuthorizer(expected, self.record, purpose="cancel"),
                handoff_verifier=SyntheticHandoffVerifier(self.record, self.reference_contents),
            )

        self.assertEqual(result["check_status"], "pass", result)
        self.assertEqual(result["commit_status"], "confirmed_committed", result)
        events = [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event_type"] for event in events].count("handoff_cancelled"), 1)

    def test_cancelled_handoff_cannot_validate_as_prepared(self) -> None:
        self.assertEqual(self._prepare()["check_status"], "pass")
        arguments = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_root": str(self.package.resolve()), "request_id": "REQ-CANCEL-001",
            "controller_generation": 7, "handoff_id": self.handoff_id,
        }
        expected = {
            "operation": "cancel_handoff", "task_id": self.task_id,
            "base_dir": str(self.base_dir.resolve()), "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": 1, "contract_digest": self.record["contract_digest"],
            "controller_generation": 7, "handoff_id": self.handoff_id,
            "arguments_sha256": _canonical_sha256(arguments),
        }
        self.assertEqual(context.cancel_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, request_id="REQ-CANCEL-001", controller_generation=7,
            handoff_id=self.handoff_id, runtime_identity=object(),
            write_authorizer=SyntheticWriteAuthorizer(expected, self.record, purpose="cancel"),
            handoff_verifier=SyntheticHandoffVerifier(self.record, self.reference_contents),
        )["check_status"], "pass")

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=SyntheticHandoffVerifier(self.record, self.reference_contents),
        )

        self.assertNotEqual(report["check_status"], "pass", report)

    def test_unknown_handoff_activation_fences_writes_before_authorizer(self) -> None:
        self.assertEqual(self._prepare()["check_status"], "pass")
        event_path = self.base_dir / self.task_id / "events.jsonl"
        events = [json.loads(line) for line in event_path.read_text().splitlines()]
        activated = json.loads(json.dumps(events[-1]))
        activated.update({"event_id": "EV-SYNTHETIC-ACTIVATION", "event_type": "handoff_activated"})
        activated["payload"].update({
            "type": "handoff_activated", "request_id": "REQ-ACTIVATE-OTHER",
            "handoff_id": "HO-OTHER-001",
        })
        event_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in [*events, activated]),
            encoding="utf-8",
        )

        class MustNotAuthorize:
            calls = 0

            def authorize(self, request: object) -> object:
                self.calls += 1
                raise AssertionError("unknown handoff activation must be rejected before host authorization")

        authorizer = MustNotAuthorize()
        before = event_path.read_bytes()
        with self.assertRaises(context.ContextError):
            context.record(
                self.task_id, statement="activated handoff cannot dispatch", item_type="observation",
                actor="synthetic:controller", source="synthetic", base_dir=self.base_dir,
                runtime_identity=object(), write_authorizer=authorizer,
            )
        self.assertEqual(authorizer.calls, 0)
        self.assertEqual(event_path.read_bytes(), before)

    def test_legacy_tasks_with_2000_or_2001_events_remain_unfenced(self) -> None:
        for count in (2000, 2001):
            with self.subTest(count=count):
                fixture = HandoffWriteTests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                first = context.record(
                    fixture.task_id, statement="legacy seed", item_type="observation",
                    actor="synthetic:legacy", source="synthetic", base_dir=fixture.base_dir,
                )
                event_path = fixture.base_dir / fixture.task_id / "events.jsonl"
                events = [json.loads(line) for line in event_path.read_text().splitlines()]
                seed = next(event for event in events if event["event_type"] == "item-recorded")
                additional = []
                for index in range(count - 2):
                    event = json.loads(json.dumps(seed))
                    event["event_id"] = f"EV-{index:012x}"
                    event["payload"]["item"]["id"] = f"C-LEGACY-{index:08d}"
                    additional.append(event)
                event_path.write_text(
                    "".join(json.dumps(event, sort_keys=True) + "\n" for event in [*events, *additional]),
                    encoding="utf-8",
                )

                item = context.record(
                    fixture.task_id, statement=f"legacy remains compatible {count}",
                    item_type="observation", actor="synthetic:legacy", source="synthetic",
                    base_dir=fixture.base_dir,
                )

                self.assertEqual(item["statement"], f"legacy remains compatible {count}")
                self.assertEqual(first["statement"], "legacy seed")

    def test_uncertain_legacy_event_history_cannot_claim_no_handoff_control(self) -> None:
        event_path = self.base_dir / self.task_id / "events.jsonl"
        event_path.write_bytes(event_path.read_bytes() + b'{"event_type":"handoff_prepared"')
        before = event_path.read_bytes()

        with self.assertRaises(context.ContextError):
            context.record(
                self.task_id, statement="uncertain legacy history", item_type="observation",
                actor="synthetic:legacy", source="synthetic", base_dir=self.base_dir,
            )

        self.assertEqual(event_path.read_bytes(), before)

    def test_duplicate_event_type_cannot_hide_legacy_handoff_control(self) -> None:
        event_path = self.base_dir / self.task_id / "events.jsonl"
        event_path.write_bytes(
            event_path.read_bytes()
            + b'{"event_type":"handoff_prepared","event_type":"item-recorded"}\n'
        )
        before = event_path.read_bytes()

        with self.assertRaises(context.ContextError):
            context.record(
                self.task_id, statement="duplicate key cannot become legacy", item_type="observation",
                actor="synthetic:legacy", source="synthetic", base_dir=self.base_dir,
            )

        self.assertEqual(event_path.read_bytes(), before)
