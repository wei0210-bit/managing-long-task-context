from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package_lineage.py"


def load_lineage():
    spec = importlib.util.spec_from_file_location("package_lineage_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINEAGE = load_lineage()


def git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Lineage Test",
        "GIT_AUTHOR_EMAIL": "lineage@example.invalid",
        "GIT_COMMITTER_NAME": "Lineage Test",
        "GIT_COMMITTER_EMAIL": "lineage@example.invalid",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        env=git_environment(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {arguments[0]} failed: {completed.stderr}")
    return completed.stdout.strip()


def init_repo(path: Path, *, with_origin_main: bool = True) -> str:
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(path)],
        env=git_environment(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Lineage Test"],
        env=git_environment(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "lineage@example.invalid"],
        env=git_environment(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    (path / "tracked.txt").write_text("seed\n", encoding="utf-8")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-qm", "seed")
    sha = git(path, "rev-parse", "HEAD")
    if with_origin_main:
        git(path, "update-ref", "refs/remotes/origin/main", sha)
    return sha


def tracked_hashes(repo: Path) -> dict[str, str]:
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        env=git_environment(),
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout.split(b"\0")
    hashes: dict[str, str] = {}
    for raw in listing:
        if not raw:
            continue
        relative = raw.decode()
        hashes[relative] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    return hashes


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
    )


class PackageLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def test_ancestor_commit_is_pass_and_exit_zero(self) -> None:
        sha = init_repo(self.repo)
        report = LINEAGE.package_lineage_report(self.repo, f"git:{sha}")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["codes"], [])
        self.assertEqual(report["default_ref"], "origin/main")
        completed = run_cli("--repo", str(self.repo), "--source-revision", f"git:{sha}")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "pass")

    def test_commit_not_on_origin_main_fails(self) -> None:
        init_repo(self.repo)
        (self.repo / "tracked.txt").write_text("later\n", encoding="utf-8")
        git(self.repo, "add", "tracked.txt")
        git(self.repo, "commit", "-qm", "later")
        sha = git(self.repo, "rev-parse", "HEAD")
        report = LINEAGE.package_lineage_report(self.repo, f"git:{sha}")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["codes"], ["PACKAGE_LINEAGE_NOT_ON_DEFAULT"])
        completed = run_cli("--repo", str(self.repo), "--source-revision", f"git:{sha}")
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["codes"], ["PACKAGE_LINEAGE_NOT_ON_DEFAULT"])

    def test_local_without_confirm_is_warn(self) -> None:
        report = LINEAGE.package_lineage_report(self.repo, "local:note")
        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["codes"], ["PACKAGE_LINEAGE_LOCAL_UNCONFIRMED"])
        completed = run_cli("--repo", str(self.repo), "--source-revision", "local:note")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "warn")

    def test_local_with_confirm_is_pass(self) -> None:
        report = LINEAGE.package_lineage_report(self.repo, "local:note", confirmed_local=True)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["codes"], [])
        completed = run_cli("--repo", str(self.repo), "--source-revision", "local:note", "--confirm-local")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "pass")

    def test_unresolved_shapes_are_unknown(self) -> None:
        for revision in ("candidate:dirty", "git:test-revision"):
            with self.subTest(revision=revision):
                report = LINEAGE.package_lineage_report(self.repo, revision)
                self.assertEqual(report["status"], "unknown")
                self.assertEqual(report["codes"], ["PACKAGE_LINEAGE_UNRESOLVED"])

    def test_missing_origin_main_is_unknown(self) -> None:
        sha = init_repo(self.repo, with_origin_main=False)
        report = LINEAGE.package_lineage_report(self.repo, f"git:{sha}")
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(report["codes"], ["PACKAGE_LINEAGE_UNRESOLVED"])

    def test_empty_revision_is_missing(self) -> None:
        report = LINEAGE.package_lineage_report(self.repo, "")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["codes"], ["PACKAGE_LINEAGE_MISSING"])
        completed = run_cli("--repo", str(self.repo), "--source-revision", "   ")
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["codes"], ["PACKAGE_LINEAGE_MISSING"])

    def test_report_does_not_change_tracked_hashes(self) -> None:
        sha = init_repo(self.repo)
        before = tracked_hashes(self.repo)
        LINEAGE.package_lineage_report(self.repo, f"git:{sha}")
        LINEAGE.package_lineage_report(self.repo, "local:note")
        run_cli("--repo", str(self.repo), "--source-revision", f"git:{sha}")
        self.assertEqual(tracked_hashes(self.repo), before)


if __name__ == "__main__":
    unittest.main()
