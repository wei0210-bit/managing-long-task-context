from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/contract_precheck.py"


class ContractPrecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_")}
        self.git("init", "-q")
        (self.repo / "tests").mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "src/widget.py").write_text("VALUE = 1\n")
        (self.repo / "tests/test_literal.py").write_text(
            "import unittest\n# release v1.2+\n# v1x2+ is different\n"
            "class TestLiteral(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertTrue(True)\n"
            "# release v1.2+ again\n")
        (self.repo / "tests/test_widget.py").write_text(
            "import unittest\nfrom widget import VALUE\n"
            "class TestWidget(unittest.TestCase):\n"
            "    def test_value(self):\n        self.assertEqual(VALUE, 1)\n")
        (self.repo / "tests/test_failure.py").write_text(
            "import unittest\n# failure-marker\n"
            "class TestFailure(unittest.TestCase):\n"
            "    def test_bad(self):\n        self.fail('intentional failure')\n")
        (self.repo / "tests/test_mention.py").write_text(
            "import unittest\n# widget is affected\n"
            "class TestMention(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertTrue(True)\n")
        self.git("add", "tests", "src")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              env=self.env, capture_output=True, text=True,
                              check=True).stdout

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def payload(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_literal_lines_and_repeated_terms(self):
        data = self.payload("--term", "v1.2+", "--term", "absent")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["terms"], [
            {"term": "v1.2+", "hits": [
                {"file": "tests/test_literal.py", "line": 2, "text": "# release v1.2+"},
                {"file": "tests/test_literal.py", "line": 7, "text": "# release v1.2+ again"}]},
            {"term": "absent", "hits": []}])
        self.assertEqual(data["test_modules"], ["tests.test_literal"])

    def test_path_import_and_text_mentions(self):
        data = self.payload("--path", "src/widget.py", "--path", "src/missing.py")
        self.assertEqual(data["paths"], [
            {"path": "src/widget.py", "tests": ["tests/test_mention.py", "tests/test_widget.py"]},
            {"path": "src/missing.py", "tests": []}])
        self.assertEqual(data["test_modules"], ["tests.test_mention", "tests.test_widget"])

    def test_run_records_failure_and_continues_with_success(self):
        out = self.base / "logs"
        before = self.git("status", "--porcelain")
        data = self.payload("--term", "failure-marker", "--path", "src/widget.py",
                            "--run", "--out-dir", str(out))
        self.assertEqual(data["status"], "failed")
        runs = {item["module"]: item for item in data["run"]}
        self.assertNotEqual(runs["tests.test_failure"]["exit_code"], 0)
        self.assertEqual(runs["tests.test_widget"]["exit_code"], 0)
        for entry in runs.values():
            log = Path(entry["log_file"])
            self.assertTrue(log.is_relative_to(out))
            self.assertTrue(log.is_file())
        self.assertIn("intentional failure", Path(runs["tests.test_failure"]["log_file"]).read_text())
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertFalse(list(self.repo.rglob("__pycache__")))

    def test_scan_is_read_only_and_deduplicates_modules(self):
        before = self.git("status", "--porcelain")
        data = self.payload("--term", "widget", "--path", "src/widget.py")
        self.assertEqual(len(data["test_modules"]), len(set(data["test_modules"])))
        self.assertNotIn("run", data)
        self.assertEqual(self.git("status", "--porcelain"), before)

    def test_run_default_logs_and_no_hits(self):
        (self.repo / ".gitignore").write_text(".context-reports/\n")
        before = self.git("status", "--porcelain")
        data = self.payload("--path", "src/widget.py", "--run")
        self.assertEqual(data["status"], "ok")
        for entry in data["run"]:
            self.assertTrue(Path(entry["log_file"]).is_relative_to(self.repo / ".context-reports"))
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.payload("--term", "absent", "--run")["run"], [])

    def test_parameter_errors_have_no_stdout_or_logs(self):
        cases = [[], ["--term", ""], ["--unknown"], ["--path", "../outside.py"],
                 ["--repo", ".", "--term", "x"],
                 ["--repo", str(self.base), "--term", "x"],
                 ["--term", "x", "--run", "--out-dir", "relative"],
                 ["--term", "x", "--run", "--out-dir", str(self.repo / "logs")]]
        for args in cases:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
        self.assertFalse((self.repo / "logs").exists())

    def test_symlink_output_cannot_escape_allowed_directory(self):
        (self.repo / ".context-reports").symlink_to(self.repo / "src", target_is_directory=True)
        result = self.cli("--term", "x", "--run", "--out-dir",
                          str(self.repo / ".context-reports/logs"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.repo / "src/logs").exists())

    def test_nested_modules_and_absolute_path(self):
        nested = self.repo / "tests/nested"
        nested.mkdir()
        (nested / "test_nested.py").write_text(
            "import unittest\n# widget\n"
            "class TestNested(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertTrue(True)\n")
        data = self.payload("--path", str(self.repo / "src/widget.py"), "--run",
                            "--out-dir", str(self.base / "logs"))
        self.assertIn("tests.nested.test_nested", data["test_modules"])
        self.assertTrue(all(entry["exit_code"] == 0 for entry in data["run"]))


if __name__ == "__main__":
    unittest.main()
