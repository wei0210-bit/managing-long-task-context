"""R-P2-01: public CLI log targets must never redirect repository writes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(os.environ.get(
    "PRECHECK_SCRIPT_UNDER_TEST",
    str(Path(__file__).resolve().parents[1] / "scripts" / "contract_precheck.py"),
)).absolute()


class OutdirLogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="precheck-log-targets-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "repo"
        (self.repo / "tests").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.pop("PYTHONPATH", None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.trace = self.base / "executed"
        self.env["LOG_TARGET_TRACE"] = str(self.trace)
        subprocess.run(["git", "init", "-q", str(self.repo)], env=self.env, check=True)
        for name in ("test_a.py", "test_b.py"):
            (self.repo / "tests" / name).write_text(
                "import os, pathlib, unittest\n# LOG_TARGET_TOKEN\n"
                "class Check(unittest.TestCase):\n"
                "    def test_pass(self):\n"
                "        with pathlib.Path(os.environ['LOG_TARGET_TRACE']).open('a') as trace:\n"
                "            trace.write(__file__ + '\\n')\n"
                "        self.assertTrue(True)\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        self.victim = self.repo / "src" / "important.txt"
        self.victim.write_bytes(b"KEEP_THIS_SOURCE\n")
        self.before = self.victim.read_bytes()
        self.out = self.repo / ".context-reports" / "output"
        self.target = self.out / "0000.log"

    def invoke(self, hook=None):
        args = ["--repo", str(self.repo), "--term", "LOG_TARGET_TOKEN",
                "--run", "--out-dir", str(self.out)]
        if hook is None:
            command = [sys.executable, str(SCRIPT)] + args
        else:
            command = [sys.executable, "-c", hook, str(SCRIPT)] + args
        return subprocess.run(command, cwd=str(self.base), env=self.env,
                              capture_output=True, text=True, timeout=30)

    def assert_rejected(self, result):
        # Check preservation before the exit status, so the red run exposes the
        # destructive write itself rather than just an unexpected success code.
        self.assertEqual(self.victim.read_bytes(), self.before)
        self.assertFalse(self.trace.exists(), "test methods executed before rejection")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertTrue(result.stderr.startswith("contract_precheck.py: error:"))
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def test_link_to_repository_source_preserves_bytes(self):
        self.out.mkdir(parents=True)
        self.target.symlink_to(self.victim)
        self.assert_rejected(self.invoke())
        self.assertTrue(self.target.is_symlink())

    def test_dangling_log_link_is_rejected(self):
        self.out.mkdir(parents=True)
        missing = self.repo / "src" / "missing.txt"
        self.target.symlink_to(missing)
        self.assert_rejected(self.invoke())
        self.assertFalse(missing.exists())
        self.assertTrue(self.target.is_symlink())

    def test_directory_log_target_is_rejected(self):
        self.target.mkdir(parents=True)
        sentinel = self.target / "sentinel"
        sentinel.write_bytes(b"keep\n")
        self.assert_rejected(self.invoke())
        self.assertEqual(sentinel.read_bytes(), b"keep\n")

    def test_later_unsafe_target_blocks_every_test_and_preserves_logs(self):
        self.out.mkdir(parents=True)
        self.target.write_bytes(b"existing log\n")
        (self.out / "0001.log").symlink_to(self.victim)
        self.assert_rejected(self.invoke())
        self.assertEqual(self.target.read_bytes(), b"existing log\n")

    def test_hard_link_to_source_is_rejected(self):
        self.out.mkdir(parents=True)
        os.link(self.victim, self.target)
        self.assert_rejected(self.invoke())

    def test_fifo_target_is_rejected_without_blocking(self):
        self.out.mkdir(parents=True)
        os.mkfifo(self.target)
        self.assert_rejected(self.invoke())

    def test_link_swapped_in_at_open_is_rejected(self):
        self.out.mkdir(parents=True)
        self.target.write_bytes(b"old log\n")
        self.env["LOG_SWAP_TARGET"] = str(self.target)
        self.env["LOG_SWAP_VICTIM"] = str(self.victim)
        fired = self.base / "hook-fired"
        self.env["LOG_SWAP_FIRED"] = str(fired)
        hook = r'''
import os, pathlib, runpy, sys
target = pathlib.Path(os.environ['LOG_SWAP_TARGET'])
fired = pathlib.Path(os.environ['LOG_SWAP_FIRED'])
def swap(event, args):
    if event == 'open' and os.path.basename(str(args[0])) == target.name and not fired.exists():
        fired.write_bytes(b'fired')
        target.unlink()
        target.symlink_to(os.environ['LOG_SWAP_VICTIM'])
sys.addaudithook(swap)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        result = self.invoke(hook)
        self.assertTrue(fired.exists(), "log-opening race hook never fired")
        self.assert_rejected(result)

    def test_clean_outdir_runs_all_selected_files(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "ok")
        self.assertEqual(len(value["run"]), 2)
        self.assertEqual({Path(p).name for p in self.trace.read_text().splitlines()},
                         {"test_a.py", "test_b.py"})
        for record in value["run"]:
            self.assertEqual(record["exit_code"], 0)
            log = Path(record["log_file"])
            self.assertEqual(log.parent.resolve(), self.out.resolve())
            self.assertFalse(log.is_symlink())
            self.assertIn("Ran 1 test", log.read_text())
        self.assertEqual(self.victim.read_bytes(), self.before)
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def test_existing_regular_logs_can_be_reused(self):
        self.out.mkdir(parents=True)
        self.target.write_bytes(b"old log\n")
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ok")
        self.assertIn("Ran 1 test", self.target.read_text())


if __name__ == "__main__":
    unittest.main()
