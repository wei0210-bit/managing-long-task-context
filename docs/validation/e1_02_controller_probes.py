"""Independent synthetic E1-02 probes. Expectations frozen in adjacent JSON."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import managing_long_task_context as context
import test_handoff_writes as fixtures
import test_handoff_protocol as read_fixtures
from handoff_test_authority import SyntheticChildAuthority


class ControllerWriteProbes(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HandoffWriteTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.base_dir / self.fixture.task_id

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def controls(self):
        return [e for e in (json.loads(line) for line in
                (self.root / "events.jsonl").read_text().splitlines())
                if e["event_type"].startswith("handoff_")]

    def cancel(self):
        f = self.fixture
        arguments = {
            "operation": "cancel_handoff", "task_id": f.task_id,
            "base_dir": str(f.base_dir.resolve()), "workspace_root": str(f.workspace.resolve()),
            "package_root": str(f.package.resolve()), "request_id": "ROOT-CANCEL-001",
            "controller_generation": 7, "handoff_id": f.handoff_id,
        }
        expected = {key: arguments[key] for key in (
            "operation", "task_id", "base_dir", "workspace_root",
            "controller_generation", "handoff_id")}
        expected.update({key: f.record[key] for key in (
            "package_manifest_sha256", "contract_version", "contract_digest")})
        expected["arguments_sha256"] = fixtures._canonical_sha256(arguments)
        authority = fixtures.SyntheticWriteAuthorizer(expected, f.record, purpose="cancel")
        kwargs = dict(arguments)
        kwargs.pop("operation")
        return context.cancel_handoff(
            **kwargs, runtime_identity=object(), write_authorizer=authority,
            handoff_verifier=fixtures.SyntheticHandoffVerifier(f.record, f.reference_contents),
        )

    def test_w01_content_pass_does_not_replace_write_authority(self):
        with patch.object(fixtures.SyntheticWriteAuthorizer, "authorize",
                          return_value={"status": "unknown"}):
            report = self.fixture._prepare()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.controls(), [])

    def test_w02_valid_prepare_is_not_activation(self):
        report = self.fixture._prepare()
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["controller_generation"], 7)
        self.assertEqual([e["event_type"] for e in self.controls()], ["handoff_prepared"])

    def test_w03_prepare_duplicate_is_idempotent_but_changed_content_conflicts(self):
        first = self.fixture._prepare()
        self.assertEqual(first["check_status"], "pass", first)
        before = self.files()
        again = self.fixture._prepare()
        self.assertEqual(again["check_status"], "pass", again)
        self.assertEqual(self.files(), before)
        changed = deepcopy(self.fixture.record)
        changed["created_at"] = "2026-09-15T00:00:02Z"
        different = self.fixture._prepare(record=changed)
        self.assertNotEqual(different["check_status"], "pass", different)
        self.assertEqual(self.files(), before)

    def test_w04_each_direct_writer_is_fenced_before_original_file_changes(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        f = self.fixture
        contract = deepcopy(f.published)
        contract.pop("seal", None)
        contract["version"] = 2
        calls = {
            "publish_contract": lambda: context.publish_contract(contract, confirmed_by="publisher", base_dir=f.base_dir),
            "record": lambda: context.record(f.task_id, statement="unauthorized observation", item_type="observation", actor="publisher", source="synthetic", base_dir=f.base_dir),
            "update_item": lambda: context.update_item(f.task_id, "C-012345678901", actor="publisher", metadata={"changed": True}, base_dir=f.base_dir),
            "checkpoint": lambda: context.checkpoint(f.task_id, phase="unauthorized", completed=[], evidence_added=[], next_action="stop", actor="publisher", base_dir=f.base_dir),
            "mark_truth_sources_dirty": lambda: context.mark_truth_sources_dirty(f.task_id, change_kind="source", actor="publisher", reason="synthetic", base_dir=f.base_dir),
            "observe_truth_source": lambda: context.observe_truth_source(f.task_id, source_id="SRC-1", actor="publisher", verification_refs=["ref:synthetic"], base_dir=f.base_dir),
            "externalize_item": lambda: context.externalize_item(f.task_id, "C-012345678901", summary="synthetic", external_ref="file:/synthetic", actor="publisher", base_dir=f.base_dir),
            "restore_externalization_controls": lambda: context.restore_externalization_controls(f.task_id, "C-012345678901", from_item_id="C-012345678902", actor="publisher", reason="synthetic", base_dir=f.base_dir),
        }
        for operation, call in calls.items():
            with self.subTest(operation=operation):
                # A mistakenly accepted writer must not contaminate the next case.
                f = fixtures.HandoffWriteTests()
                f.setUp()
                self.addCleanup(f.doCleanups)
                self.fixture = f
                self.root = f.base_dir / f.task_id
                self.assertEqual(f._prepare()["check_status"], "pass")
                contract = deepcopy(f.published)
                contract.pop("seal", None)
                contract["version"] = 2
                before = self.files()
                with self.assertRaises(context.ContextError) as caught:
                    call()
                # An unrelated invalid-item/undeclared-source error cannot prove fencing.
                self.assertIn("HANDOFF", str(caught.exception))
                self.assertEqual(self.files(), before)

    def test_w07_authorization_binding_and_expiry_cannot_be_self_reported(self):
        original = fixtures.SyntheticWriteAuthorizer.authorize
        for field, invalid in (("controller_generation", True),
                               ("controller_generation", 7.0),
                               ("operation", "cancel_handoff"),
                               ("expires_at", "2020-01-01T00:00:00Z")):
            with self.subTest(field=field, value=invalid):
                def altered(authority, request):
                    result = original(authority, request)
                    result[field] = invalid
                    return result
                with patch.object(fixtures.SyntheticWriteAuthorizer, "authorize", altered):
                    report = self.fixture._prepare()
                self.assertNotEqual(report["check_status"], "pass", report)
                self.assertEqual(self.controls(), [])

    def test_w06_cancel_does_not_restore_unauthenticated_legacy_writes(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        report = self.cancel()
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["controller_generation"], 7)
        before = self.files()
        with self.assertRaises(context.ContextError):
            context.record(self.fixture.task_id, statement="cannot bypass after cancel",
                           item_type="observation", actor="publisher", source="synthetic",
                           base_dir=self.fixture.base_dir)
        self.assertEqual(self.files(), before)

    def test_w05_registered_child_progress_survives_but_cannot_publish_contract(self):
        old = read_fixtures.HandoffProtocolTests()
        old.setUp()
        self.addCleanup(old.doCleanups)
        _, task_root = old._materialize_prepared_handoff()
        record = json.loads((task_root / "handoff" / f"{old.handoff_id}.json").read_text())
        authority = SyntheticChildAuthority(base_dir=old.base_dir, workspace=old.workspace,
                                            record=record)
        item = context.record(old.task_id, statement="handoff replayed observation",
                              item_type="observation", actor="publisher", source="public-record",
                              base_dir=old.base_dir, runtime_identity=authority.identity,
                              write_authorizer=authority)
        self.assertEqual(item["statement"], "handoff replayed observation")
        before = {str(p.relative_to(task_root)): p.read_bytes()
                  for p in task_root.rglob("*") if p.is_file()}
        contract = json.loads((task_root / "task-contract.json").read_text())
        contract.pop("seal", None)
        contract["version"] = 2
        with self.assertRaises(context.ContextError):
            context.publish_contract(contract, confirmed_by="publisher", base_dir=old.base_dir,
                                     runtime_identity=authority.identity, write_authorizer=authority)
        after = {str(p.relative_to(task_root)): p.read_bytes()
                 for p in task_root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_w09_unknown_cancel_authority_cannot_restore_dispatch(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        before = self.files()
        with patch.object(fixtures.SyntheticWriteAuthorizer, "authorize",
                          return_value={"status": "unknown"}):
            report = self.cancel()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.files(), before)

    def test_w05b_cancel_does_not_make_child_a_contract_publisher(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        self.assertEqual(self.cancel()["check_status"], "pass")
        f = self.fixture
        class InconsistentHostResult:
            def authorize(self, request):
                result = {key: value for key, value in request.items()
                          if key not in {"arguments", "runtime_identity"}}
                result.update({
                    "status": "pass", "purpose": "contract_publish", "role": "child",
                    "subject_id": "synthetic:child-not-publisher", "work_item_id": "CHILD-WORK",
                    "scope_digest": "a" * 64, "target_activation_status": "not_activated",
                    "observed_at": "2026-09-15T00:00:01Z", "expires_at": "2030-01-01T00:00:00Z",
                    **{key: f.record[key] for key in (
                        "source_session_ref", "target_session_ref", "authorization_ref")},
                })
                return result
        contract = deepcopy(f.published)
        contract.pop("seal", None)
        contract["version"] = 2
        before = self.files()
        with self.assertRaises(context.ContextError):
            context.publish_contract(contract, confirmed_by="publisher", base_dir=f.base_dir,
                                     runtime_identity=object(), write_authorizer=InconsistentHostResult())
        self.assertEqual(self.files(), before)

    def test_w08_changed_authority_file_invalidates_same_call_observation(self):
        original = fixtures.SyntheticWriteAuthorizer.authorize
        def changed(authority, request):
            result = original(authority, request)
            (self.fixture.workspace / "authorization.txt").write_text("revoked\n")
            return result
        with patch.object(fixtures.SyntheticWriteAuthorizer, "authorize", changed):
            report = self.fixture._prepare()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.controls(), [])

    def test_w10_missing_log_cannot_revert_prepared_task_to_legacy_writer(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        (self.root / "events.jsonl").unlink()  # disposable synthetic fixture only
        before = self.files()
        with self.assertRaises(context.ContextError):
            context.record(self.fixture.task_id, statement="cannot bypass",
                           item_type="observation", actor="publisher", source="synthetic",
                           base_dir=self.fixture.base_dir)
        self.assertEqual(self.files(), before)

    def test_w10b_missing_record_directory_does_not_erase_protocol_history(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        (self.root / "handoff").rename(self.root / "isolated-handoff-away")
        before = self.files()
        with self.assertRaises(context.ContextError):
            context.record(self.fixture.task_id, statement="cannot bypass missing directory",
                           item_type="observation", actor="publisher", source="synthetic",
                           base_dir=self.fixture.base_dir)
        self.assertEqual(self.files(), before)

    def test_w10c_stale_snapshot_cannot_conceal_protocol_in_authoritative_events(self):
        snapshot = self.root / "snapshot.json"
        before_prepare = snapshot.read_bytes()
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        (self.root / "handoff").rename(self.root / "isolated-handoff-away")
        snapshot.write_bytes(before_prepare)
        before = self.files()
        with self.assertRaises(context.ContextError):
            context.record(self.fixture.task_id, statement="stale cache cannot authorize",
                           item_type="observation", actor="publisher", source="synthetic",
                           base_dir=self.fixture.base_dir)
        self.assertEqual(self.files(), before)

    def test_w08b_changed_record_after_authorization_cannot_allow_direct_write(self):
        old = read_fixtures.HandoffProtocolTests()
        old.setUp()
        self.addCleanup(old.doCleanups)
        _, task_root = old._materialize_prepared_handoff()
        path = task_root / "handoff" / f"{old.handoff_id}.json"
        record = json.loads(path.read_text())
        authority = SyntheticChildAuthority(base_dir=old.base_dir, workspace=old.workspace,
                                            record=record)
        original = authority.authorize
        def changed(request):
            result = original(request)
            edited = deepcopy(record)
            edited["controller_generation"] = 8
            path.write_text(json.dumps(edited))
            return result
        authority.authorize = changed
        before_events = (task_root / "events.jsonl").read_bytes()
        with self.assertRaises(context.ContextError):
            context.record(old.task_id, statement="handoff replayed observation",
                           item_type="observation", actor="publisher", source="public-record",
                           base_dir=old.base_dir, runtime_identity=authority.identity,
                           write_authorizer=authority)
        self.assertEqual((task_root / "events.jsonl").read_bytes(), before_events)

    def test_w11_two_pass_fields_do_not_prove_prepared_content(self):
        with patch.object(fixtures.SyntheticHandoffVerifier, "verify",
                          return_value={"status": "pass", "content_status": "pass"}):
            report = self.fixture._prepare()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.controls(), [])

    def test_w12_prepare_requires_committed_contract_binding(self):
        path = self.root / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[0]["payload"]["integrity_digest"] = "sha256:" + "0" * 64
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        report = self.fixture._prepare()
        self.assertEqual(report["check_status"], "unknown", report)
        self.assertEqual(self.controls(), [])

    def test_w13_legacy_writes_do_not_inherit_handoff_event_count_limit(self):
        helper = read_fixtures.HandoffProtocolTests()
        helper.task_id = self.fixture.task_id
        events = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
        items = [helper._valid_item_event(index) for index in range(1999)]
        events.extend(items)
        self.assertEqual(len(events), 2000)
        (self.root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        snapshot_path = self.root / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["items"] = {e["payload"]["item"]["id"]: e["payload"]["item"] for e in items}
        snapshot["event_count"] = len(events)
        snapshot["updated_at"] = events[-1]["created_at"]
        snapshot_path.write_text(json.dumps(snapshot))
        self.assertFalse((self.root / "handoff").exists())
        for statement in ("legacy event 2001", "legacy event 2002"):
            result = context.record(self.fixture.task_id, statement=statement,
                                    item_type="observation", actor="publisher", source="synthetic",
                                    base_dir=self.fixture.base_dir)
            self.assertEqual(result["statement"], statement)
        self.assertEqual(len((self.root / "events.jsonl").read_text().splitlines()), 2002)

    def test_w03b_recovery_cannot_hide_a_changed_request_workspace(self):
        self.assertEqual(self.fixture._prepare()["check_status"], "pass")
        f = self.fixture
        other = f.workspace.parent / "other-request-workspace"
        other.mkdir()
        before = self.files()
        report = context.prepare_handoff(
            f.task_id, base_dir=f.base_dir, workspace_root=other, package_root=f.package,
            request_id=f.record["request_id"], controller_generation=7, record=f.record,
        )
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
