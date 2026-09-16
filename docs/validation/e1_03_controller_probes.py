"""Root-owned isolated probes, frozen separately from executor implementation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import managing_long_task_context as context
import test_handoff_writes as fixtures
import test_handoff_protocol as budget_fixtures
import e1_02_controller_probes as prior_probes


class RegisteredTarget:
    """Synthetic host: identities and scope are registered, not model assertions."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.identity = object()
        self.mutate = None
        self.after = None

    def authorize(self, request):
        f = self.fixture
        if request.get("runtime_identity") is not self.identity:
            return {"status": "unknown"}
        if request.get("operation") != "activate_handoff":
            return {"status": "unknown"}
        expected = {
            "operation": "activate_handoff", "task_id": f.task_id,
            "base_dir": str(f.base_dir.resolve()), "workspace_root": str(f.workspace.resolve()),
            **{k: f.record[k] for k in ("package_manifest_sha256", "contract_version",
                                      "contract_digest", "controller_generation", "handoff_id")},
        }
        if any(type(request.get(k)) is not type(v) or request.get(k) != v
               for k, v in expected.items()):
            return {"status": "unknown"}
        args = request.get("arguments")
        expected_args = {
            "operation": "activate_handoff", "task_id": f.task_id,
            "base_dir": str(f.base_dir.resolve()), "workspace_root": str(f.workspace.resolve()),
            "package_root": str(f.package.resolve()), "controller_generation": 7,
            "handoff_id": f.handoff_id, "request_id": "ROOT-ACTIVATE-001",
        }
        if args != expected_args or request.get("arguments_sha256") != fixtures._canonical_sha256(expected_args):
            return {"status": "unknown"}
        for name, content in f.reference_contents.items():
            if (f.workspace / f"{name}.txt").read_text() != content:
                return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        result = {
            "status": "pass", **expected,
            "arguments_sha256": fixtures._canonical_sha256(expected_args),
            "purpose": "activate", "subject_id": "registered-host-subject-73",
            "subject_session_ref": deepcopy(f.record["target_session_ref"]),
            "role": "controller", "work_item_id": None, "scope_digest": "a" * 64,
            **{k: deepcopy(f.record[k]) for k in
               ("source_session_ref", "target_session_ref", "authorization_ref")},
            "target_activation_status": "not_activated",
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if self.mutate:
            self.mutate(result)
        if self.after:
            self.after()
        return result


class ActivationControllerProbes(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.HandoffWriteTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.base_dir / self.f.task_id
        self.assertEqual(self.f._prepare()["check_status"], "pass")
        self.authority = RegisteredTarget(self.f)

    def files(self, *, stat=False):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                if stat else p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def activations(self):
        return [e for e in map(json.loads, (self.root / "events.jsonl").read_text().splitlines())
                if e["event_type"] == "handoff_activated"]

    def activate(self, **override):
        f = self.f
        kwargs = dict(base_dir=f.base_dir, workspace_root=f.workspace, package_root=f.package,
                      request_id="ROOT-ACTIVATE-001", controller_generation=7, handoff_id=f.handoff_id,
                      runtime_identity=self.authority.identity, write_authorizer=self.authority,
                      handoff_verifier=fixtures.SyntheticHandoffVerifier(f.record, f.reference_contents))
        kwargs.update(override)
        return context.activate_handoff(f.task_id, **kwargs)

    def status(self, *, verifier=True):
        f = self.f
        return context.handoff_status(
            f.task_id, base_dir=f.base_dir, workspace_root=f.workspace, package_root=f.package,
            handoff_id=f.handoff_id, handoff_verifier=fixtures.SyntheticHandoffVerifier(
                f.record, f.reference_contents) if verifier else None)

    def test_a01_valid_target_and_idempotent_request(self):
        report = self.activate()
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["commit_status"], "confirmed_committed", report)
        self.assertEqual(report["controller_generation"], 8, report)
        before = self.files(stat=True)
        again = self.activate()
        self.assertEqual(again["commit_status"], "confirmed_committed", again)
        self.assertEqual(len(self.activations()), 1)
        self.assertEqual(self.files(stat=True), before)

    def test_a02_no_authority_verifier_or_registered_identity(self):
        for kwargs in ({"write_authorizer": None}, {"handoff_verifier": None},
                       {"runtime_identity": object()}):
            with self.subTest(kwargs=tuple(kwargs)):
                before = self.files()
                result = self.activate(**kwargs)
                self.assertNotEqual(result["check_status"], "pass", result)
                self.assertEqual(self.files(), before)
                self.assertEqual(self.activations(), [])

    def test_a03_subject_binding_cannot_be_replaced_by_label(self):
        mutations = {
            "missing": lambda r: r.pop("subject_session_ref"),
            "source": lambda r: r.update(subject_session_ref=deepcopy(self.f.record["source_session_ref"])),
            "label": lambda r: (r.pop("subject_session_ref"), r.update(subject_id="target")),
            "expired": lambda r: r.update(expires_at="2000-01-01T00:00:00Z"),
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                self.authority.mutate = mutation
                before = self.files()
                report = self.activate()
                self.assertNotEqual(report["check_status"], "pass", report)
                self.assertEqual(self.files(), before)

    def test_a04_basis_changes_after_host_authorization(self):
        before = self.files()
        self.authority.after = lambda: (self.f.workspace / "basis.txt").write_text("changed evidence")
        report = self.activate()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.activations(), [])

    def test_a05_invalid_generation_is_not_an_integer(self):
        for value in (True, 7.0, 6):
            with self.subTest(value=repr(value)):
                before = self.files()
                report = self.activate(controller_generation=value)
                self.assertNotEqual(report["check_status"], "pass", report)
                self.assertEqual(self.files(), before)

    def test_a04_record_changes_after_authorization_do_not_activate(self):
        path = self.root / "handoff" / f"{self.f.handoff_id}.json"
        changed = deepcopy(self.f.record)
        changed["created_at"] = "2026-09-15T00:00:02Z"
        before_events = (self.root / "events.jsonl").read_bytes()
        self.authority.after = lambda: path.write_text(json.dumps(changed))
        report = self.activate()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), before_events)
        self.assertEqual(self.activations(), [])

    def test_a04_package_changes_during_host_check_do_not_activate(self):
        before = self.files()
        self.authority.after = lambda: (self.f.package / "skill-manifest.json").write_text("different package")
        report = self.activate()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.activations(), [])
        self.assertEqual(self.files(), before)

    def test_a05_duplicate_wrong_workspace_is_not_recovered_as_success(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        alternate = Path(self.f.temporary.name) / "wrong-workspace"
        alternate.mkdir()
        before = self.files()
        result = self.activate(workspace_root=alternate)
        self.assertNotEqual(result["check_status"], "pass", result)
        self.assertEqual(self.files(), before)

    def test_a06_changed_evidence_does_not_erase_committed_fact(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        (self.f.workspace / "basis.txt").write_text("evidence changed after commit")
        before = self.files(stat=True)
        report = self.status()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(report["commit_status"], "confirmed_committed", report)
        self.assertEqual(report["controller_generation"], 8, report)
        self.assertEqual(self.files(stat=True), before)

    def test_a07_twenty_status_queries_and_missing_verifier_are_readonly(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        before = self.files(stat=True)
        reports = [self.status(verifier=False) for _ in range(20)]
        for report in reports:
            self.assertEqual(report["check_status"], "unknown", report)
            self.assertEqual(report["commit_status"], "confirmed_committed", report)
            self.assertEqual(report["controller_generation"], 8, report)
        self.assertEqual(self.files(stat=True), before)
        self.assertEqual(len(self.activations()), 1)

    def test_a06_duplicate_after_evidence_change_reports_fact_not_current_pass(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        (self.f.workspace / "basis.txt").write_text("changed after initial activation")
        before = self.files(stat=True)
        report = self.activate()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(report["commit_status"], "confirmed_committed", report)
        self.assertEqual(self.files(stat=True), before)

    def test_a04_expired_verifier_at_commit_cannot_activate(self):
        f = self.f
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=1)
        class ShortReceipt(fixtures.SyntheticHandoffVerifier):
            def verify(inner, request):
                result = super().verify(request)
                result["expires_at"] = expires.strftime("%Y-%m-%dT%H:%M:%SZ")
                return result
        before = self.files()
        with patch.object(context, "_trusted_utc_now", return_value=now + timedelta(seconds=2)):
            report = self.activate(handoff_verifier=ShortReceipt(f.record, f.reference_contents))
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.activations(), [])
        self.assertEqual(self.files(), before)

    def fill_valid_log(self, size):
        helper = budget_fixtures.HandoffProtocolTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.task_id = self.f.task_id
        helper._fill_log_with_complete_items(self.root / "events.jsonl", size)

    def test_a10_large_log_atomic_activation_has_bounded_output(self):
        self.fill_valid_log(8 * 1024 * 1024 - 64 * 1024)
        report = self.activate()
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(len(self.activations()), 1)
        self.assertLessEqual((self.root / "events.jsonl").stat().st_size, 8 * 1024 * 1024)
        self.assertFalse(list(self.root.glob(".handoff-events-*")))

    def test_a10_atomic_activation_refuses_final_log_over_budget(self):
        self.fill_valid_log(8 * 1024 * 1024)
        before = self.files()
        report = self.activate()
        self.assertNotEqual(report["check_status"], "pass", report)
        self.assertEqual(self.activations(), [])
        self.assertEqual(self.files(), before)

    def progress(self, *, role="controller", old_source=False, generation=8, activation_state="activated"):
        f = self.f
        identity = object()
        source = f.record["source_session_ref"]
        target = f.record["target_session_ref"]
        if role == "child":
            path = f.workspace / "registered-child.txt"
            path.write_text("registered independent child of root-work\n")
            subject = fixtures._reference(f.task_id, "registered-child", path)
        else:
            subject = source if old_source else target
        arguments = {
            "operation": "record", "task_id": f.task_id, "base_dir": str(f.base_dir.resolve()),
            "statement": "root bounded progress", "item_type": "observation", "actor": "same-user-label",
            "source": "synthetic-root", "evidence": None, "scope": None, "verification_method": None,
            "mutable": False, "ttl_hours": None, "item_id": "C-ROOT-PROGRESS", "supersedes": None,
            "metadata": None,
        }
        expected = {
            "operation": "record", "task_id": f.task_id, "base_dir": str(f.base_dir.resolve()),
            "workspace_root": str(f.workspace.resolve()), "controller_generation": generation,
            **{k: f.record[k] for k in ("package_manifest_sha256", "contract_version", "contract_digest", "handoff_id")},
            "arguments_sha256": fixtures._canonical_sha256(arguments),
        }
        class Authority:
            def authorize(inner, request):
                if request.get("runtime_identity") is not identity or request.get("arguments") != arguments:
                    return {"status": "unknown"}
                if any(type(request.get(k)) is not type(v) or request.get(k) != v for k, v in expected.items()):
                    return {"status": "unknown"}
                for name, content in f.reference_contents.items():
                    if (f.workspace / f"{name}.txt").read_text() != content:
                        return {"status": "unknown"}
                now = datetime.now(timezone.utc).replace(microsecond=0)
                return {
                    "status": "pass", **expected, "purpose": "progress", "role": role,
                    "subject_id": "registered-child" if role == "child" else "registered-controller",
                    "subject_session_ref": deepcopy(subject), "scope_digest": "a" * 64,
                    "work_item_id": "root-work" if role == "child" else None,
                    **{k: deepcopy(f.record[k]) for k in ("source_session_ref", "target_session_ref", "authorization_ref")},
                    "target_activation_status": activation_state, "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
        return context.record(f.task_id, statement="root bounded progress", item_type="observation",
                              actor="same-user-label", source="synthetic-root", item_id="C-ROOT-PROGRESS",
                              base_dir=f.base_dir, runtime_identity=identity, write_authorizer=Authority())

    def test_a08_target_controller_can_write_but_old_source_cannot(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        before = self.files()
        with self.assertRaises(context.ContextError):
            self.progress(old_source=True)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.progress()["id"], "C-ROOT-PROGRESS")

    def test_a08_original_child_does_not_need_to_impersonate_controller(self):
        self.assertEqual(self.activate()["check_status"], "pass")
        item = self.progress(role="child")
        self.assertEqual(item["id"], "C-ROOT-PROGRESS")

    def test_a08_cancel_does_not_revoke_original_child_progress_scope(self):
        previous = prior_probes.ControllerWriteProbes()
        previous.fixture, previous.root = self.f, self.root
        self.assertEqual(previous.cancel()["check_status"], "pass")
        item = self.progress(role="child", generation=7, activation_state="not_activated")
        self.assertEqual(item["id"], "C-ROOT-PROGRESS")
        self.assertEqual(self.activations(), [])


if __name__ == "__main__":
    unittest.main()
