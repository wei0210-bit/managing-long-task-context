from __future__ import annotations

import json
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
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

    def assert_unreadable_directory_error(self, directory, *args):
        before = self.git("status", "--porcelain")
        original_mode = directory.stat().st_mode
        directory.chmod(0)
        try:
            try:
                with os.scandir(directory) as entries:
                    list(entries)
            except PermissionError:
                pass
            else:
                self.skipTest("process can list chmod 000 directories; permission denial unavailable")
            out = self.base / "unreadable-logs"
            for run_args in ([], ["--run", "--out-dir", str(out)]):
                with self.subTest(run=bool(run_args)):
                    result = self.cli(*args, *run_args)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(str(directory), result.stderr)
                    self.assertEqual(len(result.stderr.splitlines()), 1)
                    self.assertIn("Permission denied", result.stderr)
                    self.assertFalse(out.exists())
        finally:
            directory.chmod(original_mode)
        self.assertEqual(self.git("status", "--porcelain"), before)

    def test_unreadable_tests_root(self):
        self.assert_unreadable_directory_error(self.repo / "tests", "--term", "widget")

    def test_unreadable_nested_directory(self):
        nested = self.repo / "tests/restricted"
        nested.mkdir()
        (nested / "test_hidden.py").write_text("# widget\n")
        self.assert_unreadable_directory_error(nested, "--path", "src/widget.py")

    def test_unreadable_nested_directory_does_not_hide_failing_run(self):
        nested = self.repo / "tests/restricted"
        nested.mkdir()
        (nested / "test_hidden.py").write_text(
            "import unittest\n# hidden-failure\n"
            "class TestHidden(unittest.TestCase):\n"
            "    def test_bad(self):\n        self.fail('hidden failure')\n")
        data = self.payload("--term", "hidden-failure", "--run",
                            "--out-dir", str(self.base / "readable-logs"))
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["test_modules"], ["tests.restricted.test_hidden"])
        self.assertNotEqual(data["run"][0]["exit_code"], 0)
        self.assertIn("hidden failure", Path(data["run"][0]["log_file"]).read_text())
        self.assert_unreadable_directory_error(nested, "--term", "hidden-failure")

    def assert_scan_failure(self, path, reason, invoke=None):
        """Both scan and run must reject incomplete inventories before any logs."""
        before = self.git("status", "--porcelain")
        out = self.base / "failure-logs"
        for run_args in ([], ["--run", "--out-dir", str(out)]):
            with self.subTest(run=bool(run_args)):
                args = ["--term", "widget", *run_args]
                result = (invoke or self.cli)(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                self.assertIn(str(path), result.stderr)
                self.assertIn(reason, result.stderr)
                self.assertFalse(out.exists())
        self.assertEqual(self.git("status", "--porcelain"), before)

    def move_tests_root(self):
        original = self.repo / "src/original-tests"
        (self.repo / "tests").rename(original)
        return original

    def test_directory_symlink_root(self):
        original = self.move_tests_root()
        root = self.repo / "tests"
        root.symlink_to(original, target_is_directory=True)
        self.assert_scan_failure(root, "symlink")

    def test_directory_symlink_nested(self):
        linked = self.repo / "tests/linked"
        linked.symlink_to(self.repo / "src", target_is_directory=True)
        self.assert_scan_failure(linked, "symlink")

    def test_test_file_symlink(self):
        linked = self.repo / "tests/test_linked.py"
        linked.symlink_to(self.repo / "tests/test_widget.py")
        self.assert_scan_failure(linked, "symlink")

    def test_dangling_symlink_root(self):
        self.move_tests_root()
        linked = self.repo / "tests"
        linked.symlink_to(self.repo / "missing", target_is_directory=True)
        self.assert_scan_failure(linked, "symlink")

    def test_dangling_symlink_nested(self):
        linked = self.repo / "tests/missing"
        linked.symlink_to(self.repo / "missing", target_is_directory=True)
        self.assert_scan_failure(linked, "symlink")

    def test_symlink_loop(self):
        linked = self.repo / "tests/loop"
        linked.symlink_to(linked, target_is_directory=True)
        self.assert_scan_failure(linked, "symlink")

    def test_unreadable_test_file(self):
        path = self.repo / "tests/test_widget.py"
        mode = path.stat().st_mode
        self.addCleanup(path.chmod, mode)
        path.chmod(0)
        try:
            path.read_bytes()
        except PermissionError:
            pass
        else:
            self.skipTest("process can read chmod 000 files; permission denial unavailable")
        self.assert_scan_failure(path, "Permission denied")

    def test_invalid_utf8_test_file(self):
        path = self.repo / "tests/test_invalid.py"
        path.write_bytes(b"# widget\n\xff\n")
        self.assert_scan_failure(path, "utf-8")

    def test_tests_root_regular_file(self):
        self.move_tests_root()
        path = self.repo / "tests"
        path.write_text("# widget\n")
        self.assert_scan_failure(path, "directory")

    def injected_cli(self, operation, replacement, *args):
        # Deterministic filesystem race at a real listing/read boundary; the
        # public main still parses Git inputs and must suppress partial output.
        spec = importlib.util.spec_from_file_location("contract_precheck", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch(operation, new=replacement), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = module.main(["--repo", str(self.repo), *args])
            except SystemExit as exc:
                code = exc.code
        return subprocess.CompletedProcess(args, code, stdout.getvalue(), stderr.getvalue())

    def test_disappearing_directory(self):
        nested = self.repo / "tests/vanished"
        nested.mkdir()
        (nested / "test_hidden.py").write_text("# widget\n")
        real_scandir = os.scandir

        def vanished(path):
            if Path(path) == nested:
                raise FileNotFoundError(2, "No such file or directory", str(nested))
            return real_scandir(path)

        self.assert_scan_failure(nested, "No such file", lambda *args:
                                 self.injected_cli("os.scandir", vanished, *args))

    def test_disappearing_test_file(self):
        path = self.repo / "tests/test_widget.py"
        real_read = Path.read_text

        def vanished(candidate, *args, **kwargs):
            if candidate == path:
                raise FileNotFoundError(2, "No such file or directory", str(path))
            return real_read(candidate, *args, **kwargs)

        self.assert_scan_failure(path, "No such file", lambda *args:
                                 self.injected_cli("pathlib.Path.read_text", vanished, *args))

    def test_absent_tests_remains_successful_empty_scan(self):
        self.move_tests_root()
        data = self.payload("--term", "widget", "--run")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["test_modules"], [])
        self.assertEqual(data["run"], [])

    def test_inventory_and_run_cover_unittest_discovery(self):
        # Use unittest itself in a fresh interpreter so previously imported
        # fixture modules cannot affect this oracle's discovery results.
        discover = """
import json, sys, unittest
from pathlib import Path
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / 'src'))
suite = unittest.TestLoader().discover(
    start_dir=str(repo / 'tests'), pattern='test*.py', top_level_dir=str(repo))
def modules(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from modules(item)
        else:
            yield type(item).__module__
print(json.dumps(sorted(set(modules(suite)))))
"""
        variants = ("test.py", "testlegacy.py", "testWidget.py", "test_x.py",
                    "Test_x.py", "helper.py")
        (self.repo / "tests/__init__.py").write_text("")
        for layout in ("", "nested/deeper"):
            with self.subTest(layout=layout):
                directory = self.repo / "tests"
                for part in Path(layout).parts:
                    directory = directory / part
                    directory.mkdir(exist_ok=True)
                    (directory / "__init__.py").write_text("")
                for name in variants:
                    # Keep Test_x.py separate from test_x.py on filesystems
                    # that treat these two names as the same file.
                    target = directory
                    if name in variants[4:]:
                        target = directory / "excluded"
                        target.mkdir(exist_ok=True)
                        (target / "__init__.py").write_text("")
                    (target / name).write_text(
                        "import unittest\n# discovery-marker widget\n"
                        "class TestDiscovered(unittest.TestCase):\n"
                        "    def test_bad(self):\n"
                        f"        self.fail('discovered failure {name}')\n")
                oracle = subprocess.run(
                    [sys.executable, "-B", "-c", discover, str(self.repo)],
                    env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(oracle.returncode, 0, oracle.stderr)
                discovered = set(json.loads(oracle.stdout))
                prefix = "tests" + ("." + layout.replace("/", ".") if layout else "")
                expected = {prefix + "." + Path(name).stem for name in variants[:4]}
                self.assertTrue(expected <= discovered, discovered)
                excluded = {prefix + ".excluded.Test_x", prefix + ".excluded.helper"}
                self.assertFalse(excluded & discovered)
                # 'unittest' occurs in every candidate, including setUp's files.
                inventory = self.payload("--term", "unittest")
                self.assertTrue(discovered <= set(inventory["test_modules"]), inventory)
                self.assertFalse(excluded & set(inventory["test_modules"]))
                out = self.base / ("oracle-logs-" + (layout.replace("/", "-") or "root"))
                before = self.git("status", "--porcelain")
                data = self.payload("--term", "unittest", "--path", "src/widget.py",
                                    "--run", "--out-dir", str(out))
                runs = {row["module"]: row for row in data["run"]}
                self.assertTrue(discovered <= set(runs), runs)
                mapped = set(data["paths"][0]["tests"])
                hits = {hit["file"] for hit in data["terms"][0]["hits"]}
                for module in expected:
                    file = module.replace(".", "/") + ".py"
                    self.assertIn(file, hits)
                    self.assertIn(file, mapped)
                    self.assertNotEqual(runs[module]["exit_code"], 0)
                    self.assertIn("discovered failure " + Path(file).name,
                                  Path(runs[module]["log_file"]).read_text())
                self.assertEqual(data["status"], "failed")
                self.assertEqual(self.git("status", "--porcelain"), before)

    def test_unicode_separators_preserve_physical_line_numbers(self):
        path = self.repo / "tests/test_unicode.py"
        for separator in ("\u2028", "\u0085"):
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(separator=separator, newline=newline):
                    text = newline.join(["# prefix" + separator + "suffix",
                                         "# physical-marker " + separator + "tail",
                                         "# another line", "# physical-marker again", ""])
                    path.write_bytes(text.encode("utf-8"))
                    data = self.payload("--term", "physical-marker")
                    self.assertEqual(data["terms"][0]["hits"], [
                        {"file": "tests/test_unicode.py", "line": 2,
                         "text": "# physical-marker " + separator + "tail"},
                        {"file": "tests/test_unicode.py", "line": 4,
                         "text": "# physical-marker again"}])

    def assert_argument_loop_error(self, option):
        loop = self.repo / "src/loop.py"
        loop.symlink_to(loop)
        out = self.base / "loop-logs"
        before = self.git("status", "--porcelain")
        for run_args in ([], ["--run"]):
            with self.subTest(run=bool(run_args)):
                args = ["--term", "widget", "--out-dir", str(out), *run_args,
                        option, str(loop)]
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn(option, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(out.exists())
        self.assertEqual(self.git("status", "--porcelain"), before)

    def test_repo_argument_symlink_loop(self):
        self.assert_argument_loop_error("--repo")

    def test_path_argument_symlink_loop(self):
        self.assert_argument_loop_error("--path")

    def test_out_dir_argument_symlink_loop(self):
        self.assert_argument_loop_error("--out-dir")

    def test_name_variants_retain_fail_closed_policy(self):
        for name in ("test.py", "testlegacy.py", "testWidget.py"):
            path = self.repo / "tests" / name
            with self.subTest(name=name, case="invalid-utf8"):
                path.write_bytes(b"# widget\n\xff\n")
                self.assert_scan_failure(path, "utf-8")
            # Retain each hostile fixture while moving it outside tests/;
            # no cleanup hides evidence from the next independent case.
            path.rename(self.repo / "src" / (name + ".invalid"))
            with self.subTest(name=name, case="symlink"):
                path.symlink_to(self.repo / "tests/test_widget.py")
                self.assert_scan_failure(path, "symlink")
            path.rename(self.repo / "src" / (name + ".link"))
            with self.subTest(name=name, case="nonregular"):
                os.mkfifo(path)
                self.assert_scan_failure(path, "regular file")
            path.rename(self.repo / "src" / (name + ".fifo"))
            with self.subTest(name=name, case="unreadable"):
                path.write_text("# widget\n")
                path.chmod(0)
                try:
                    try:
                        path.read_bytes()
                    except PermissionError:
                        self.assert_scan_failure(path, "Permission denied")
                    else:
                        self.skipTest("process can read chmod 000 files")
                finally:
                    path.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
