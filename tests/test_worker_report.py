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
import managing_long_task_context.worker_report as wr
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
        report, check = wr._read_report(self.root, self.evidence)
        return {"status": check["status"], "checks": {"resolve": check}}

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





















if __name__ == "__main__":
    unittest.main()
