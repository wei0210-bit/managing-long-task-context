from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context
from handoff_test_authority import SyntheticChildAuthority


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reference(task_id: str, ref_id: str, content: str, uri: str) -> dict[str, str]:
    return {
        "ref_id": ref_id,
        "task_id": task_id,
        "uri": uri,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


class SyntheticTrustedVerifier:
    """A labelled synthetic host that independently reads isolated fixture files."""

    def __init__(self, *, expected: dict[str, object], verification_refs: list[dict[str, str]], content_path: Path, content_expected: str = "semantic handoff evidence\n") -> None:
        self.expected = expected
        self.verification_refs = verification_refs
        self.content_path = content_path
        self.content_expected = content_expected

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        if self.content_path.read_text(encoding="utf-8") != self.content_expected:
            return {"status": "fail"}
        if any(request.get(key) != value for key, value in self.expected.items()):
            return {"status": "fail"}
        return {
            "status": "pass",
            "identity_status": "pass",
            "authorization_status": "pass",
            "content_status": "pass",
            **self.expected,
            "observed_at": "2026-09-15T00:00:02Z",
            "expires_at": "2030-01-01T00:00:00Z",
            "verification_refs": self.verification_refs,
        }


class HandoffProtocolTests(unittest.TestCase):
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
        self.task_id = "TASK-001"
        self.handoff_id = "HO-001"

    def _valid_item_event(self, index: int, *, padding: str = "") -> dict[str, object]:
        created_at = "2026-09-15T00:00:03Z"
        item = {
            "id": f"C-{index:012x}",
            "statement": "bounded replay fixture",
            "type": "observation",
            "status": "active",
            "actor": "synthetic:budget",
            "source": {"kind": "synthetic", "ref": "budget-fixture"},
            "evidence": [],
            "scope": {},
            "verification_method": None,
            "mutable": False,
            "ttl_hours": None,
            "verified_at": None,
            "created_at": created_at,
            "updated_at": created_at,
            "supersedes": None,
            "superseded_by": None,
            "conflicts_with": [],
            "conflict_reason": None,
            "metadata": {"padding": padding},
        }
        return {
            "schema": 1,
            "event_id": f"EV-{index + 3:012x}",
            "task_id": self.task_id,
            "event_type": "item-recorded",
            "actor": "synthetic:budget",
            "created_at": created_at,
            "payload": {"item": item},
        }

    def _serialized_valid_item_event(self, index: int, size: int | None = None) -> bytes:
        event = self._valid_item_event(index)
        empty = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if size is None:
            return empty
        self.assertGreaterEqual(size, len(empty))
        item = event["payload"]["item"]
        assert isinstance(item, dict)
        metadata = item["metadata"]
        assert isinstance(metadata, dict)
        metadata["padding"] = "x" * (size - len(empty))
        line = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        self.assertEqual(len(line), size)
        return line

    def _fill_log_with_complete_items(self, path: Path, target_size: int) -> None:
        remaining = target_size - path.stat().st_size
        self.assertGreater(remaining, 0)
        count = (remaining + 59_999) // 60_000
        self.assertLessEqual(count + 2, 2_000)
        with path.open("ab") as stream:
            for index in range(count):
                size = remaining // (count - index)
                line = self._serialized_valid_item_event(index, size)
                self.assertLessEqual(len(line), 64 * 1024)
                stream.write(line)
                remaining -= len(line)
        self.assertEqual(path.stat().st_size, target_size)

    def _materialize_prepared_handoff(self) -> tuple[SyntheticTrustedVerifier, Path]:
        contract = {
            "schema": 1,
            "task_id": self.task_id,
            "version": 1,
            "issued_by": "publisher",
            "issued_at": "2026-09-15T00:00:00Z",
            "authorized_approvers": [],
            "objective": "Read a prepared handoff",
            "scope": ["isolated test"],
            "out_of_scope": [],
            "constraints": ["read only"],
            "acceptance_criteria": [{
                "id": "AC-01",
                "criterion": "Prepared record is readable",
                "required_evidence": ["test-report"],
            }],
        }
        published = context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base_dir)
        task_root = self.base_dir / self.task_id
        published_event_id = json.loads((task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])["event_id"]
        reference_contents = {
            "source": "source identity",
            "target": "target identity",
            "authorization": "delegated scope",
            "basis": "semantic handoff evidence\n",
            "artifacts": "artifact index",
        }
        references = []
        for ref_id, content in reference_contents.items():
            path = self.workspace / f"{ref_id}.txt"
            path.write_text(content, encoding="utf-8")
            references.append(_reference(self.task_id, ref_id, content, path.as_uri()))
        content_path = self.workspace / "basis.txt"
        record = {
            "protocol": "short-session-handoff/v1",
            "task_id": self.task_id,
            "contract_version": 1,
            "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
            "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256((self.package / "skill-manifest.json").read_bytes()).hexdigest(),
            "handoff_id": self.handoff_id,
            "request_id": "REQ-001",
            "controller_generation": 7,
            "source_session_ref": references[0],
            "target_session_ref": references[1],
            "authorization_ref": references[2],
            "basis_refs": [references[3]],
            "artifact_manifest_ref": references[4],
            "created_at": "2026-09-15T00:00:01Z",
            "event_cursor": published_event_id,
        }
        record_digest = _canonical_sha256(record)
        record_dir = task_root / "handoff"
        record_dir.mkdir()
        (record_dir / f"{self.handoff_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8",
        )
        prepared = {
            "schema": 1,
            "event_id": "EV-000000000001",
            "task_id": self.task_id,
            "event_type": "handoff_prepared",
            "actor": "synthetic:publisher",
            "created_at": "2026-09-15T00:00:01Z",
            "payload": {
                "type": "handoff_prepared",
                "task_id": self.task_id,
                "request_id": "REQ-001",
                "handoff_id": self.handoff_id,
                "created_at": "2026-09-15T00:00:01Z",
                "expected_controller_generation": 7,
                "controller_generation": 7,
                "record_sha256": record_digest,
                "verification_refs": [references[3]],
            },
        }
        with (task_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(prepared, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        expected = {
            "task_id": self.task_id,
            "handoff_id": self.handoff_id,
            "controller_generation": 7,
            "contract_version": 1,
            "contract_digest": record["contract_digest"],
            "workspace_root": str(self.workspace.resolve()),
            "package_manifest_sha256": record["package_manifest_sha256"],
            "record_sha256": record_digest,
        }
        return SyntheticTrustedVerifier(
            expected=expected, verification_refs=references, content_path=content_path,
        ), task_root

    def test_valid_complete_prepared_record_passes_without_writing_or_granting_control(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        before = {path.relative_to(task_root): (path.read_bytes(), path.stat().st_mtime_ns) for path in task_root.rglob("*") if path.is_file()}

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        after = {path.relative_to(task_root): (path.read_bytes(), path.stat().st_mtime_ns) for path in task_root.rglob("*") if path.is_file()}
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["commit_status"], "not_attempted", report)
        self.assertEqual(report["controller_generation"], 7)
        self.assertEqual(report["blocking_reasons"], [])
        self.assertEqual(before, after)

    def test_verifier_reference_with_matching_id_but_wrong_digest_cannot_pass(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        original_verify = verifier.verify

        def verify_with_tampered_reference(request: dict[str, object]) -> dict[str, object]:
            result = original_verify(request)
            assert isinstance(result.get("verification_refs"), list)
            result["verification_refs"][0] = {
                **result["verification_refs"][0],
                "sha256": "0" * 64,
            }
            return result

        verifier.verify = verify_with_tampered_reference  # type: ignore[method-assign]
        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_VERIFIER_REFERENCE_COVERAGE")

    def test_duplicate_record_key_is_unverifiable_even_when_last_value_looks_valid(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        original = record_path.read_text(encoding="utf-8")
        record_path.write_text(
            original.replace(
                '"handoff_id":"HO-001"',
                '"handoff_id":"HO-001","handoff_id":"HO-001"',
                1,
            ),
            encoding="utf-8",
        )

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_deeply_nested_record_is_a_protocol_unknown_not_recursion_error(
        self,
    ) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        record_path.write_bytes(b"[" * 10_000 + b"0" + b"]" * 10_000)

        report = context.validate_handoff(
            self.task_id,
            base_dir=self.base_dir,
            workspace_root=self.workspace,
            package_root=self.package,
            handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["commit_status"], "not_attempted", report)
        self.assertEqual(
            report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE"
        )

    def test_changed_host_evidence_before_callback_return_cannot_pass(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        original_verify = verifier.verify
        calls = 0

        def verify_then_change_evidence(request: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            result = original_verify(request)
            if calls == 1:
                verifier.content_path.write_text("changed during final check\n", encoding="utf-8")
            return result

        verifier.verify = verify_then_change_evidence  # type: ignore[method-assign]
        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(calls, 1)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_missing_runtime_verifier_and_missing_authoritative_log_remain_unknown(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        no_verifier = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
        )
        self.assertEqual(no_verifier["check_status"], "unknown", no_verifier)
        self.assertEqual(no_verifier["blocking_reasons"][0]["code"], "HANDOFF_VERIFIER_UNAVAILABLE")

        (task_root / "events.jsonl").unlink()
        missing_log = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )
        self.assertEqual(missing_log["check_status"], "unknown", missing_log)
        self.assertEqual(missing_log["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")
        self.assertEqual(missing_log["commit_status"], "not_attempted", missing_log)
        unknown_status = context.handoff_status(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )
        self.assertEqual(unknown_status["check_status"], "unknown", unknown_status)
        self.assertEqual(unknown_status["commit_status"], "unknown", unknown_status)

    def test_twenty_fixed_readonly_queries_are_semantically_and_bytewise_stable(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        before = {path.relative_to(task_root): (path.read_bytes(), path.stat().st_mtime_ns) for path in task_root.rglob("*") if path.is_file()}
        reports = [context.handoff_status(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        ) for _ in range(20)]
        after = {path.relative_to(task_root): (path.read_bytes(), path.stat().st_mtime_ns) for path in task_root.rglob("*") if path.is_file()}
        self.assertTrue(all(report == reports[0] for report in reports))
        self.assertEqual(reports[0]["check_status"], "pass", reports[0])
        self.assertEqual(before, after)

    def test_foreign_task_event_in_this_authoritative_log_cannot_be_ignored(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        foreign = {
            "schema": 1,
            "event_id": "EV-000000000002",
            "task_id": "TASK-OTHER",
            "event_type": "item-recorded",
            "actor": "synthetic:foreign",
            "created_at": "2026-09-15T00:00:02Z",
            "payload": {"item": {"id": "foreign"}},
        }
        with (task_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(foreign, sort_keys=True, separators=(",", ":")) + "\n")

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_strict_handoff_replay_rejects_item_event_without_a_complete_item(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        incomplete = {
            "schema": 1,
            "event_id": "EV-000000000002",
            "task_id": self.task_id,
            "event_type": "item-recorded",
            "actor": "synthetic:incomplete",
            "created_at": "2026-09-15T00:00:02Z",
            "payload": {},
        }
        with (task_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(incomplete, sort_keys=True, separators=(",", ":")) + "\n")

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_corrupt_truncated_and_unknown_authoritative_events_are_unknown(self) -> None:
        for name, suffix in (
            ("bad-utf8", b"\xff\n"),
            ("truncated", b'{"schema":1'),
            ("unknown-event", b'{"schema":1,"event_id":"EV-000000000002","task_id":"TASK-001","event_type":"unrecognized","actor":"synthetic:x","created_at":"2026-09-15T00:00:02Z","payload":{}}\n'),
        ):
            with self.subTest(name=name):
                root = self.base_dir.parent
                self.base_dir = root / f"context-{name}"
                self.workspace = root / f"workspace-{name}"
                self.package = root / f"package-{name}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, task_root = self._materialize_prepared_handoff()
                with (task_root / "events.jsonl").open("ab") as stream:
                    stream.write(suffix)
                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )
                self.assertEqual(report["check_status"], "unknown", report)
                self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_complete_logs_observe_the_8mib_minus_one_equal_and_plus_one_boundaries(self) -> None:
        root = self.base_dir.parent
        limit = 8 * 1024 * 1024
        for label, target, expected in (
            ("under", limit - 1, "pass"),
            ("exact", limit, "pass"),
            ("over", limit + 1, "unknown"),
        ):
            with self.subTest(label=label):
                self.base_dir = root / f"context-{label}"
                self.workspace = root / f"workspace-{label}"
                self.package = root / f"package-{label}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, task_root = self._materialize_prepared_handoff()
                self._fill_log_with_complete_items(task_root / "events.jsonl", target)

                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )

                self.assertEqual(report["check_status"], expected, report)
                self.assertEqual(report["commit_status"], "not_attempted", report)
                self.assertEqual(report["controller_generation"], 7 if expected == "pass" else None, report)
                if expected == "unknown":
                    self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_complete_event_observes_the_64kib_minus_one_equal_and_plus_one_boundaries(self) -> None:
        root = self.base_dir.parent
        limit = 64 * 1024
        for label, size, expected in (
            ("under", limit - 1, "pass"),
            ("exact", limit, "pass"),
            ("over", limit + 1, "unknown"),
        ):
            with self.subTest(label=label):
                self.base_dir = root / f"context-event-{label}"
                self.workspace = root / f"workspace-event-{label}"
                self.package = root / f"package-event-{label}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, task_root = self._materialize_prepared_handoff()
                with (task_root / "events.jsonl").open("ab") as stream:
                    stream.write(self._serialized_valid_item_event(0, size))

                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )

                self.assertEqual(report["check_status"], expected, report)
                self.assertEqual(report["commit_status"], "not_attempted", report)
                self.assertEqual(report["controller_generation"], 7 if expected == "pass" else None, report)
                if expected == "unknown":
                    self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_READ_UNAVAILABLE")

    def test_float_contract_version_does_not_match_an_integer_contract_version(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["contract_version"] = 1.0
        digest = _canonical_sha256(record)
        record_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        events[-1]["payload"]["record_sha256"] = digest
        (task_root / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")
        verifier.expected["contract_version"] = 1.0
        report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_handoff_envelope_type_must_equal_payload_type(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        events[-1]["event_type"] = "handoff_activated"
        (task_root / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")
        report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_other_handoff_control_change_keeps_readonly_result_unknown(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        activated = dict(events[-1])
        activated["event_id"] = "EV-000000000099"
        activated["event_type"] = "handoff_activated"
        activated["payload"] = {
            **activated["payload"],
            "type": "handoff_activated",
            "handoff_id": "HO-OTHER",
            "request_id": "REQ-OTHER",
            "controller_generation": 8,
        }
        with (task_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(activated, sort_keys=True, separators=(",", ":")) + "\n")

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)

    def test_percent_encoded_local_file_reference_is_readable(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        encoded_path = verifier.content_path.with_name("basis evidence.txt")
        encoded_path.write_text(verifier.content_path.read_text(encoding="utf-8"), encoding="utf-8")
        verifier.content_path = encoded_path
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["basis_refs"][0]["uri"] = encoded_path.as_uri()
        record_digest = _canonical_sha256(record)
        record_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        events[-1]["payload"]["record_sha256"] = record_digest
        events[-1]["payload"]["verification_refs"][0]["uri"] = encoded_path.as_uri()
        (task_root / "events.jsonl").write_text(
            "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        verifier.expected["record_sha256"] = record_digest
        for reference in verifier.verification_refs:
            if reference["ref_id"] == "basis":
                reference["uri"] = encoded_path.as_uri()

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "pass", report)

    def test_uncommitted_contract_publish_event_cannot_be_hidden_by_the_contract_file(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        events[0]["payload"]["integrity_digest"] = "sha256:" + "0" * 64
        (task_root / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")
        report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_expired_authorization_observation_cannot_pass(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        original_verify = verifier.verify

        def expired_result(request: dict[str, object]) -> dict[str, object]:
            result = original_verify(request)
            result["expires_at"] = "2000-01-01T00:00:00Z"
            return result

        verifier.verify = expired_result  # type: ignore[method-assign]
        report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_VERIFIER_STALE")

    def test_withdrawn_authorization_and_verifier_exception_do_not_pass(self) -> None:
        for label, mutate, expected in (
            ("withdrawn", lambda result: result.update(authorization_status="fail"), "fail"),
            ("exception", None, "unknown"),
        ):
            with self.subTest(label=label):
                root = self.base_dir.parent
                self.base_dir = root / f"context-{label}"
                self.workspace = root / f"workspace-{label}"
                self.package = root / f"package-{label}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, _ = self._materialize_prepared_handoff()
                original_verify = verifier.verify
                if mutate is None:
                    def broken_verify(request: dict[str, object]) -> dict[str, object]:
                        raise RuntimeError("synthetic verifier fault")
                    verifier.verify = broken_verify  # type: ignore[method-assign]
                else:
                    def changed_verify(request: dict[str, object]) -> dict[str, object]:
                        result = original_verify(request)
                        mutate(result)
                        return result
                    verifier.verify = changed_verify  # type: ignore[method-assign]

                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )

                self.assertEqual(report["check_status"], expected, report)
                self.assertEqual(report["commit_status"], "not_attempted", report)

    def test_runtime_binding_values_must_match_their_authoritative_types(self) -> None:
        for label, key, value in (
            ("bool-version", "contract_version", True),
            ("float-generation", "controller_generation", 7.0),
        ):
            with self.subTest(label=label):
                root = self.base_dir.parent
                self.base_dir = root / f"context-{label}"
                self.workspace = root / f"workspace-{label}"
                self.package = root / f"package-{label}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, _ = self._materialize_prepared_handoff()
                original_verify = verifier.verify

                def wrong_type_verify(request: dict[str, object]) -> dict[str, object]:
                    result = original_verify(request)
                    result[key] = value
                    return result

                verifier.verify = wrong_type_verify  # type: ignore[method-assign]
                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )

                self.assertEqual(report["check_status"], "unknown", report)
                self.assertEqual(report["commit_status"], "not_attempted", report)

    def test_strict_handoff_replay_rejects_checkpoint_without_a_checkpoint_object(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        incomplete = {
            "schema": 1,
            "event_id": "EV-000000000002",
            "task_id": self.task_id,
            "event_type": "checkpoint-recorded",
            "actor": "synthetic:incomplete",
            "created_at": "2026-09-15T00:00:02Z",
            "payload": {},
        }
        with (task_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(incomplete, sort_keys=True, separators=(",", ":")) + "\n")

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)

    def test_public_record_update_and_checkpoint_remain_visible_after_handoff_replay(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        authority = SyntheticChildAuthority(
            base_dir=self.base_dir, workspace=self.workspace,
            record=json.loads((task_root / "handoff" / f"{self.handoff_id}.json").read_text()),
        )
        recorded = context.record(
            self.task_id, statement="handoff replayed observation", item_type="observation",
            actor="synthetic:writer", source="public-record", base_dir=self.base_dir,
            runtime_identity=authority.identity, write_authorizer=authority,
        )
        authority.allowed_items.add(recorded["id"])
        updated = context.update_item(
            self.task_id, recorded["id"], actor="synthetic:writer",
            metadata={"reviewed": True}, base_dir=self.base_dir,
            runtime_identity=authority.identity, write_authorizer=authority,
        )
        checkpoint = context.checkpoint(
            self.task_id, phase="handoff-check", completed=[], evidence_added=[],
            next_action="read only validation", actor="synthetic:writer",
            related_item_ids=[recorded["id"]], base_dir=self.base_dir,
            runtime_identity=authority.identity, write_authorizer=authority,
        )

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )
        packet = context.brief(self.task_id, base_dir=self.base_dir)

        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(packet["latest_checkpoint"]["id"], checkpoint["id"])
        self.assertEqual(packet["observations"][0]["id"], updated["id"])
        self.assertTrue(packet["observations"][0]["metadata"]["reviewed"])

    def test_missing_or_changed_source_and_artifact_evidence_do_not_pass(self) -> None:
        for label, ref_name, action in (
            ("missing-source", "source", "unlink"),
            ("changed-artifact", "artifacts", "replace"),
        ):
            with self.subTest(label=label):
                root = self.base_dir.parent
                self.base_dir = root / f"context-{label}"
                self.workspace = root / f"workspace-{label}"
                self.package = root / f"package-{label}"
                self.workspace.mkdir()
                self.package.mkdir()
                (self.package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
                verifier, _ = self._materialize_prepared_handoff()
                evidence = self.workspace / f"{ref_name}.txt"
                if action == "unlink":
                    evidence.unlink()
                else:
                    evidence.write_text("unrelated artifact\n", encoding="utf-8")

                report = context.validate_handoff(
                    self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
                    package_root=self.package, handoff_id=self.handoff_id,
                    handoff_verifier=verifier,
                )

                self.assertEqual(report["check_status"], "unknown", report)
                self.assertEqual(report["commit_status"], "not_attempted", report)

    def test_known_business_blocker_remains_ungranted_by_readonly_validation(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        blocker = "known business blocker remains open\n"
        verifier.content_path.write_text(blocker, encoding="utf-8")
        verifier.content_expected = blocker
        record_path = task_root / "handoff" / f"{self.handoff_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["basis_refs"][0]["sha256"] = hashlib.sha256(blocker.encode("utf-8")).hexdigest()
        record_digest = _canonical_sha256(record)
        record_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        events = [json.loads(line) for line in (task_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        events[-1]["payload"]["record_sha256"] = record_digest
        events[-1]["payload"]["verification_refs"][0]["sha256"] = record["basis_refs"][0]["sha256"]
        (task_root / "events.jsonl").write_text(
            "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        verifier.expected["record_sha256"] = record_digest
        for reference in verifier.verification_refs:
            if reference["ref_id"] == "basis":
                reference["sha256"] = record["basis_refs"][0]["sha256"]

        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["commit_status"], "not_attempted", report)
        self.assertIn("business completion remain ungranted", report["next_readonly_action"])

    def test_host_verification_does_not_hold_the_writer_lock(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        authority = SyntheticChildAuthority(
            base_dir=self.base_dir, workspace=self.workspace,
            record=json.loads((task_root / "handoff" / f"{self.handoff_id}.json").read_text()),
        )
        original_verify = verifier.verify
        writer_done = threading.Event()
        writer_errors: list[Exception] = []

        def write_progress() -> None:
            try:
                context.record(
                    self.task_id, statement="writer progressed during verification",
                    item_type="observation", actor="synthetic:writer",
                    source="lock-handshake", base_dir=self.base_dir,
                    runtime_identity=authority.identity, write_authorizer=authority,
                )
            except Exception as exc:  # pragma: no cover - asserted after the handshake
                writer_errors.append(exc)
            finally:
                writer_done.set()

        def verify_after_writer_progress(request: dict[str, object]) -> dict[str, object]:
            worker = threading.Thread(target=write_progress)
            worker.start()
            self.assertTrue(writer_done.wait(1), "writer did not progress while verifier was running")
            worker.join()
            self.assertEqual(writer_errors, [])
            return original_verify(request)

        verifier.verify = verify_after_writer_progress  # type: ignore[method-assign]
        report = context.validate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id,
            handoff_verifier=verifier,
        )

        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(report["blocking_reasons"][0]["code"], "HANDOFF_INPUT_CHANGED")

    def test_workspace_and_package_binding_mismatches_remain_unknown(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        other_workspace = self.workspace.parent / "other-workspace"
        other_workspace.mkdir()
        workspace_report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=other_workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(workspace_report["check_status"], "unknown", workspace_report)

        other_package = self.package.parent / "other-package"
        other_package.mkdir()
        (other_package / "skill-manifest.json").write_text("different package\n", encoding="utf-8")
        package_report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=other_package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(package_report["check_status"], "unknown", package_report)

    def test_read_deadline_breach_is_unknown_before_unbounded_replay(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        with patch.object(context.time, "monotonic", side_effect=[0.0, 0.0, 6.0]):
            report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_replay_deadline_breach_is_unknown_during_rebuild(self) -> None:
        verifier, _ = self._materialize_prepared_handoff()
        with patch.object(context.time, "monotonic", side_effect=[0.0, 0.0, 0.0, 0.0, 0.0, 6.0]):
            report = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(report["check_status"], "unknown", report)

    def test_maximum_reachable_item_records_pass_and_one_more_event_is_unknown(self) -> None:
        verifier, task_root = self._materialize_prepared_handoff()
        log_path = task_root / "events.jsonl"
        with log_path.open("a", encoding="utf-8") as stream:
            for index in range(1_998):
                stream.write(self._serialized_valid_item_event(index).decode("utf-8"))
        at_limit = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(at_limit["check_status"], "pass", at_limit)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(self._serialized_valid_item_event(1_998).decode("utf-8"))
        over_limit = context.validate_handoff(self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=verifier)
        self.assertEqual(over_limit["check_status"], "unknown", over_limit)
