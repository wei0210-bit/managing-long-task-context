from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context
from managing_long_task_context.evidence import (
    BUILTIN_RESOLVER_CAPABILITIES, evaluate_evidence, runtime_evidence_handler_errors,
)

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
COMMAND = "python3 -m unittest discover -s tests"


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class WorkerReportTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(context, "worker_report_handlers"), "host-bound worker-report API missing")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Tests")
        (self.root / ".gitignore").write_text(".context-reports/\nignored\n")
        (self.root / "tracked").write_text("baseline")
        self.git("add", ".gitignore", "tracked")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.output = self.root / ".context-reports/output.log"
        self.output.parent.mkdir()
        self.output.write_bytes(b"OK\n")
        self.path = self.root / ".context-reports/report.json"
        self.contract = {
            "workspace_root": str(self.root), "seal": {"integrity_digest": "sha256:" + "a" * 64},
            "required_capabilities": ["evidence-handlers/v1"],
            "evidence_handlers": {"schema": "evidence-handlers/v1", "types": {
                "worker-report": {"resolver_capability": "project:worker-report/v1",
                                  "verifier_capability": "project:worker-report-claim/v1"}}},
        }
        self.criterion = {"worker_report_claim": {"commands": [COMMAND]},
                          "required_scope": {"module": "tests"}, "max_evidence_age_seconds": 3600}
        self.report = {
            "schema": 1, "task_id": "TASK-1", "orca_task_id": "task_live",
            "orca_dispatch_id": "ctx_live", "contract_digest": self.contract["seal"]["integrity_digest"],
            "loaded_module_file": "/pinned/src/managing_long_task_context/__init__.py",
            "loaded_manifest_sha256": "b" * 64, "code_revision": {"commit": self.head, "dirty": False},
            "checks": [{"command": COMMAND, "exit_code": 0,
                        "output_file": ".context-reports/output.log",
                        "output_sha256": hashlib.sha256(self.output.read_bytes()).hexdigest(), "output_summary": "OK"}],
            "files_modified": [], "deferred_suggestions": [], "outcome_claim": "succeeded",
            "written_at": "2026-10-07T00:00:00Z",
        }
        self.evidence = {"evidence_id": "EV-1", "kind": "worker-report", "locator": ".context-reports/report.json",
                         "generated_at": "2026-10-07T00:00:00Z", "scope": {"module": "tests"},
                         "repo_revision": self.head, "contract_version": 1}
        self.resolvers, self.verifiers = context.worker_report_handlers(self.root)
        self.write_report()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def write_report(self, report=None):
        self.path.write_text(json.dumps(self.report if report is None else report))
        self.evidence["artifact_digest"] = digest(self.path.read_bytes())

    def evaluate(self):
        return evaluate_evidence(self.evidence, self.criterion, self.contract,
                                 resolvers=self.resolvers, verifiers=self.verifiers, now=NOW)

    def claim(self):
        return self.verifiers["worker-report"]["handler"](self.evidence, self.criterion, {})

    def assert_code(self, status, code):
        value = self.claim()
        self.assertEqual(value["status"], status, value)
        self.assertIn(code, value["codes"])

    def test_pass_with_host_root_independent_of_cwd_and_contract_root(self):
        self.contract["workspace_root"] = "/untrusted/model/root"
        self.assertEqual(self.evaluate()["status"], "pass")

    def test_constructor_rejects_relative_missing_and_file_roots(self):
        for root in (".", self.root / "missing", self.root / "tracked", None):
            with self.subTest(root=root), self.assertRaises((ValueError, TypeError)):
                context.worker_report_handlers(root)

    def test_rejects_traversal_absolute_outside_and_bad_locator_types(self):
        for locator in ("../report.json", ".context-reports/../report.json", str(self.path),
                        "/outside/report.json", "", ".", None, 1, "bad\x00path"):
            with self.subTest(locator=locator):
                self.evidence["locator"] = locator
                self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_rejects_file_and_parent_symlinks_inside_or_outside_workspace(self):
        (self.root / "link").symlink_to(self.path)
        (self.root / "dirlink").symlink_to(self.path.parent, target_is_directory=True)
        (self.root / "outside").symlink_to(self.root.parent, target_is_directory=True)
        for locator in ("link", "dirlink/report.json", "outside/report.json"):
            with self.subTest(locator=locator):
                self.evidence["locator"] = locator
                self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_symlink_substitution_between_path_check_and_read_rejected(self):
        from managing_long_task_context import worker_report as module
        outside = self.root.parent / (self.root.name + "-outside.json")
        outside.write_bytes(self.path.read_bytes())
        self.addCleanup(outside.unlink)
        original = module._path

        def substitute(root, locator):
            result = original(root, locator)
            self.path.unlink()
            self.path.symlink_to(outside)
            return result

        with patch.object(module, "_path", side_effect=substitute):
            result = self.resolvers["worker-report"]["handler"](self.evidence, self.criterion, self.contract, NOW)
        self.assertNotEqual(result["resolve"]["status"], "pass")

    def test_artifact_digest_required_and_exact(self):
        for value in (None, "bad", "sha256:" + "f" * 64, 7):
            with self.subTest(value=value):
                self.evidence["artifact_digest"] = value
                self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_report_missing_unreadable_directory_or_invalid_json(self):
        for raw in (b"[]", b"null", b"1", b"{", b"\xff"):
            self.path.write_bytes(raw)
            self.evidence["artifact_digest"] = digest(raw)
            self.assertNotEqual(self.evaluate()["status"], "pass")
        self.evidence["locator"] = ".context-reports"
        self.assertNotEqual(self.evaluate()["status"], "pass")
        self.evidence["locator"] = ".context-reports/missing"
        self.assertNotEqual(self.evaluate()["status"], "pass")
        with patch("os.open", side_effect=PermissionError):
            self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_all_required_fields_missing_or_wrong_typed_are_nonpass(self):
        original = copy.deepcopy(self.report)
        for field in original:
            for value in (None, {}, []):
                with self.subTest(field=field, value=value):
                    changed = copy.deepcopy(original)
                    changed[field] = value
                    if value is None:
                        changed.pop(field)
                    self.write_report(changed)
                    # Empty lists are valid for these report arrays.
                    if field not in ("checks", "files_modified", "deferred_suggestions") or value != []:
                        self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_nested_check_and_revision_fields_are_checked(self):
        for field in ("command", "exit_code", "output_file", "output_sha256", "output_summary"):
            for value in (None, [], {}):
                with self.subTest(field=field, value=value):
                    changed = copy.deepcopy(self.report)
                    changed["checks"][0][field] = value
                    self.write_report(changed)
                    self.assertNotEqual(self.evaluate()["status"], "pass")
        for revision in ({}, {"commit": self.head, "dirty": "false"}, {"commit": [], "dirty": False}):
            self.report["code_revision"] = revision
            self.write_report()
            self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_f01_every_check_hash_requires_64_lowercase_hex_even_unsealed(self):
        for value in ('bad', 'A' * 64, 'g' * 64, 'a' * 63, 'a' * 65, 'a' * 64 + '\n'):
            with self.subTest(value=value):
                report = copy.deepcopy(self.report)
                report['checks'].append({**report['checks'][0], 'command': 'unsealed command',
                                         'output_sha256': value})
                self.write_report(report)
                self.assertNotEqual(self.evaluate()['status'], 'pass')

    def test_boolean_exit_code_not_success(self):
        self.report["checks"][0]["exit_code"] = False
        self.write_report()
        self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_schema_time_digest_and_check_element_shapes(self):
        cases = [("schema", False), ("schema", 0), ("schema", ""),
                 ("written_at", "2026-10-07T00:00:00"), ("loaded_manifest_sha256", "bad"),
                 ("contract_digest", "bad"), ("checks", [None]), ("checks", [0]),
                 ("files_modified", [False])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(self.report)
                report[field] = value
                self.write_report(report)
                self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_bounded_reads_and_io_failure_paths(self):
        from managing_long_task_context import worker_report as module
        with patch.object(module.ev, "MAX_LOCAL_ARTIFACT_BYTES", 1):
            self.assertNotEqual(self.evaluate()["status"], "pass")
        for exc in (OSError(), RuntimeError(), ValueError()):
            with patch("pathlib.Path.is_symlink", side_effect=exc):
                self.assertNotEqual(self.evaluate()["status"], "pass")
        with patch("pathlib.Path.resolve", return_value=self.root.parent):
            self.assertNotEqual(self.evaluate()["status"], "pass")
        original = module._read_bytes
        def unreadable_output(root, path):
            return (None, {"status": "unknown", "codes": ["PERMISSION_DENIED"]}) if path == self.output else original(root, path)
        with patch.object(module, "_read_bytes", side_effect=unreadable_output):
            self.assert_code("unknown", "OUTPUT_UNVERIFIED")
        with patch.object(module.ev, "MAX_LOCAL_ARTIFACT_BYTES", len(self.path.read_bytes())):
            self.output.write_bytes(b"x" * (len(self.path.read_bytes()) + 1))
            self.report["checks"][0]["output_sha256"] = hashlib.sha256(self.output.read_bytes()).hexdigest()
            self.write_report()
            self.assert_code("unknown", "OUTPUT_UNVERIFIED")

    def test_status_failure_and_malformed_rename_are_unknown(self):
        head = subprocess.CompletedProcess([], 0, (self.head + "\n").encode(), b"")
        for status in (subprocess.CompletedProcess([], 1, b"", b""),
                       subprocess.CompletedProcess([], 0, b"R  .gitattributes\x00", b""),
                       subprocess.CompletedProcess([], 0, b"x\x00", b"")):
            with patch("subprocess.run", side_effect=[head, status]):
                self.assert_code("unknown", "REVISION_MISMATCH")

    def test_contract_digest_mismatch_and_missing_seal(self):
        self.report["contract_digest"] = "sha256:" + "f" * 64
        self.write_report()
        self.assertNotEqual(self.evaluate()["status"], "pass")
        self.contract["seal"] = None
        self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_freshness_scope_and_all_revision_requirement_aliases(self):
        self.evidence["generated_at"] = "2026-10-06T00:00:00Z"
        self.assertNotEqual(self.evaluate()["status"], "pass")
        self.evidence["generated_at"] = "2026-10-07T00:00:00Z"
        self.evidence["scope"] = {"module": "other"}
        self.assertNotEqual(self.evaluate()["status"], "pass")
        self.evidence["scope"] = {"module": "tests"}
        for field in ("required_revision", "required_repo_revision", "repo_revision", "revision"):
            with self.subTest(field=field):
                criterion = copy.deepcopy(self.criterion)
                target = self.criterion if field.startswith("required_") else self.criterion["required_scope"]
                target[field] = "f" * 40
                self.assertNotEqual(self.evaluate()["status"], "pass")
                self.criterion = criterion

    def test_required_command_nonzero_fails(self):
        self.report["checks"][0]["exit_code"] = 1
        self.write_report()
        self.assert_code("fail", "COMMAND_FAILED")

    def test_missing_empty_or_malformed_sealed_commands_unknown(self):
        for claim in (None, {}, [], {"commands": []}, {"commands": COMMAND}, {"commands": [False]}):
            self.criterion["worker_report_claim"] = claim
            self.assert_code("unknown", "NO_SEALED_COMMANDS")

    def test_missing_required_command_unknown(self):
        self.criterion["worker_report_claim"]["commands"].append("missing command")
        self.assert_code("unknown", "COMMAND_MISSING")

    def test_every_matching_check_must_succeed(self):
        failed = copy.deepcopy(self.report["checks"][0])
        failed["exit_code"] = 2
        self.report["checks"].append(failed)
        self.write_report()
        self.assert_code("fail", "COMMAND_FAILED")

    def test_head_mismatch_and_report_dirty_unknown(self):
        self.report["code_revision"]["commit"] = "f" * 40
        self.write_report()
        self.assert_code("unknown", "REVISION_MISMATCH")
        self.report["code_revision"] = {"commit": self.head, "dirty": True}
        self.write_report()
        self.assert_code("unknown", "REVISION_MISMATCH")

    def test_actual_tracked_staged_and_untracked_changes_unknown(self):
        (self.root / "tracked").write_text("dirty")
        self.assert_code("unknown", "REVISION_MISMATCH")
        self.git("add", "tracked")
        self.assert_code("unknown", "REVISION_MISMATCH")
        self.git("commit", "-qm", "next")
        self.report["code_revision"]["commit"] = self.git("rev-parse", "HEAD").strip()
        self.write_report()
        (self.root / "untracked").write_text("dirty")
        self.assert_code("unknown", "REVISION_MISMATCH")

    def test_dirty_exclusions_and_ignored_files_do_not_block(self):
        for relative in (".prime/local", ".prime/scripts/merge-events.py", ".githooks/pre-commit", ".gitattributes", "ignored"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("managed")
        self.assertEqual(self.evaluate()["status"], "pass")
        (self.root / ".githooks/other").write_text("unmanaged")
        self.assert_code("unknown", "REVISION_MISMATCH")

    def test_rename_from_dirty_path_to_excluded_path_remains_dirty(self):
        self.git("mv", "tracked", ".gitattributes")
        self.assert_code("unknown", "REVISION_MISMATCH")

    def test_git_launch_timeout_nonzero_and_bad_status_unknown(self):
        for exc in (FileNotFoundError(), PermissionError(), OSError(), subprocess.TimeoutExpired("git", 5)):
            with self.subTest(exc=type(exc).__name__), patch("subprocess.run", side_effect=exc):
                self.assert_code("unknown", "REVISION_MISMATCH")
        for completed in (subprocess.CompletedProcess([], 1, b"", b""),
                          subprocess.CompletedProcess([], 0, b"bad", b"")):
            with patch("subprocess.run", return_value=completed):
                self.assert_code("unknown", "REVISION_MISMATCH")

    def test_output_missing_changed_or_wrong_digest_unknown(self):
        for path, checksum in ((".context-reports/missing", "a" * 64),
                               (".context-reports/output.log", "a" * 64)):
            self.report["checks"][0].update(output_file=path, output_sha256=checksum)
            self.write_report()
            self.assert_code("unknown", "OUTPUT_UNVERIFIED")

    def test_output_traversal_absolute_and_symlink_unknown(self):
        (self.root / ".context-reports/link").symlink_to(self.output)
        for path in ("../output.log", str(self.output), ".context-reports/link", ".context-reports"):
            self.report["checks"][0]["output_file"] = path
            self.write_report()
            self.assert_code("unknown", "OUTPUT_UNVERIFIED")

    def test_non_succeeded_outcome_nonpass(self):
        self.report["outcome_claim"] = "failed"
        self.write_report()
        self.assertNotEqual(self.evaluate()["status"], "pass")

    def test_verifier_rechecks_artifact_digest_after_resolver(self):
        self.path.write_text(json.dumps({**self.report, "outcome_claim": "failed"}))
        self.assertNotEqual(self.claim()["status"], "pass")

    def test_builtin_capabilities_are_merged(self):
        for kind, capability in BUILTIN_RESOLVER_CAPABILITIES.items():
            self.assertEqual(self.resolvers[kind]["capability"], capability)
        self.contract["evidence_handlers"]["types"]["file"] = {
            "resolver_capability": "builtin:file/v1", "verifier_capability": "project:fixture/v1"}
        self.contract["acceptance_criteria"] = [{"required_evidence_types": ["worker-report", "file"]}]
        self.verifiers["file"] = {"capability": "project:fixture/v1", "handler": lambda *args: {"status": "pass", "codes": []}}
        self.assertEqual(runtime_evidence_handler_errors(self.contract, resolvers=self.resolvers, verifiers=self.verifiers)[0], [])
        evidence = {**self.evidence, "kind": "file", "locator": str(self.output),
                    "artifact_digest": digest(self.output.read_bytes())}
        self.assertEqual(evaluate_evidence(evidence, self.criterion, self.contract,
                                         resolvers=self.resolvers, verifiers=self.verifiers, now=NOW)["status"], "pass")

    def test_complete_gate_with_report_contract_example(self):
        contract = json.loads((ROOT / "assets/task-contract.example.json").read_bytes())
        contract["workspace_root"] = str(self.root)
        contract["task_id"] = "TASK-1"
        contract["acceptance_criteria"] = [{"id": "AC-01", "criterion": "Sealed commands have verified outputs",
            "required_evidence_types": ["worker-report"], "required_scope": {"module": "tests"},
            "required_hops": [], "required_delivery_types": [], "independent_validation_required": False,
            **self.criterion}]
        published = context.publish_contract(contract, confirmed_by="task-publisher",
            base_dir=self.root / ".prime/context")
        self.report["contract_digest"] = published["seal"]["integrity_digest"]
        self.write_report()
        self.evidence["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = context.gate("TASK-1", stage="completion", evidence_map={"AC-01": {"evidence": [self.evidence],
            "delivery_receipts": []}}, base_dir=self.root / ".prime/context", resolvers=self.resolvers,
            verifiers=self.verifiers)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["decision"], "pass")


if __name__ == "__main__":
    unittest.main()
