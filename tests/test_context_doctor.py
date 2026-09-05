from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"
SOURCES = {"strict": ROOT / "skills/context-strict", "lite": ROOT / "skills/context-lite"}


def valid_now(task_id: str = "TASK-001") -> str:
    return f"""# {task_id}: Verify protected resume

Updated: 2026-09-01T02:00:00Z
Phase: implementation

## Acceptance
- Validator tests pass.

## Current State
- [STATE-01] Source is present | mutable: true | source: /tmp/source.json | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: test -r /tmp/source.json

## Decisions
- Use the standard library | why: portable | evidence: /tmp/design.md

## In Flight
- [RUN-01] Validate candidate | owner: agent | status: pending | started_at: 2026-09-01T02:00:00+00:00 | correlation_ref: tool:validator-01 | recovery_ref: test -r /tmp/result.json

## Blockers
- none

## Next
1. First: run the focused validator tests

## Refresh On Resume
- STATE-01 -> test -r /tmp/source.json
- RUN-01 -> test -r /tmp/result.json
"""


@unittest.skipUnless((ROOT / "skills/context-lite").is_dir(), "Lite package scenarios run from the development source")
class ContextDoctorAcceptanceTests(unittest.TestCase):
    """Doctor CLI and independently built package cases: AC1, 6, 8--10 and 12--13."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.packages: dict[str, Path] = {}
        cls.hashes: dict[str, str] = {}
        for name, source in SOURCES.items():
            package = cls.root / name
            completed = subprocess.run(
                [sys.executable, str(PACKAGER), "build", "--source", str(source),
                 "--destination", str(package), "--source-revision", "git:doctor-acceptance"],
                cwd=ROOT, text=True, capture_output=True, timeout=30,
            )
            if completed.returncode:
                raise AssertionError(completed.stdout + completed.stderr)
            cls.packages[name] = package
            cls.hashes[name] = json.loads(completed.stdout)["manifest_sha256"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context_root = self.root / "context"
        self.workspace = self.root / "workspace"
        self.context_root.mkdir()
        self.workspace.mkdir()
        (self.context_root / "TASK-001").mkdir()

    def doctor(self, kind: str, *args: str, expected: int = 0,
               extra_env: dict[str, str] | None = None, package: Path | None = None) -> dict:
        package = package or self.packages[kind]
        environment = os.environ.copy()
        if kind == "strict":
            environment["PYTHONPATH"] = str(package / "src")
        if extra_env:
            environment.update(extra_env)
        completed = subprocess.run(
            [sys.executable, str(package / "scripts/context_doctor.py"), *args],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def binding_args(self, kind: str) -> list[str]:
        return ["--package-root", str(self.packages[kind]),
                "--expected-manifest-sha256", self.hashes[kind],
                "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                "--task-id", "TASK-001"]

    def init(self, kind: str) -> dict:
        return self.doctor(kind, "init-binding", *self.binding_args(kind))

    def check_identity(self, kind: str, expected: int = 0) -> dict:
        return self.doctor(kind, "check", "--mode", "identity", "--package-root", str(self.packages[kind]),
                           "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                           "--task-id", "TASK-001", expected=expected)

    # Package scenario 1+2: full is an independent integrity proof, not identity proof.
    def test_full_package_check_passes_and_identity_explicitly_does_not_claim_full_integrity(self) -> None:
        for kind in ("strict", "lite"):
            with self.subTest(package=kind):
                # Bindings are package-specific identity records.  Each
                # subscenario receives a fresh task directory.
                shutil.rmtree(self.context_root)
                self.context_root.mkdir()
                (self.context_root / "TASK-001").mkdir()
                full = self.doctor(kind, "check", "--mode", "full", "--package-root", str(self.packages[kind]))
                self.assertEqual(full["scope"], "package")
                self.assertEqual(full["status"], "pass", full)
                self.assertEqual(full["binding"], None)
                self.assertEqual(full["full_verification"], "pass")
                self.init(kind)
                identity = self.check_identity(kind)
                self.assertEqual(identity["status"], "pass", identity)
                self.assertEqual(identity["full_verification"], "not_run")

    # Package scenario 3+4: full catches tampering, while an absent manifest is unknown.
    def test_full_check_detects_package_tamper_and_missing_manifest_is_unknown(self) -> None:
        for kind in ("strict", "lite"):
            with self.subTest(package=kind):
                copied = self.root / f"{kind}-tampered"
                shutil.copytree(self.packages[kind], copied)
                (copied / "SKILL.md").write_text("tampered\n", encoding="utf-8")
                report = self.doctor(kind, "check", "--mode", "full", "--package-root", str(copied),
                                     package=copied, expected=1)
                self.assertEqual(report["status"], "fail")
                self.assertTrue({"PACKAGE_HASH_MISMATCH", "PACKAGE_IDENTITY_MISMATCH"}.intersection(report["codes"]))

                manifest = copied / "skill-manifest.json"
                manifest.unlink()
                missing = self.doctor(kind, "check", "--mode", "identity", "--package-root", str(copied),
                                      "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                                      "--task-id", "TASK-001", package=copied, expected=2)
                self.assertEqual(missing["status"], "unknown")
                self.assertIn("RUNTIME_UNVERIFIED", missing["codes"])

    # Integration/package scenario 5: Lite context-root maps directly to CONTEXT/TASK/NOW.md.
    def test_lite_checked_resume_returns_valid_now_and_rejects_invalid_now(self) -> None:
        self.init("lite")
        now = self.context_root / "TASK-001/NOW.md"
        now.write_text(valid_now(), encoding="utf-8")
        passed = self.doctor("lite", "resume", "--package-root", str(self.packages["lite"]),
                             "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                             "--task-id", "TASK-001")
        self.assertEqual(passed["diagnostic"]["status"], "pass", passed)
        self.assertEqual(passed["context"], valid_now())
        now.write_text(valid_now().replace("## Decisions", "## Notes"), encoding="utf-8")
        blocked = self.doctor("lite", "resume", "--package-root", str(self.packages["lite"]),
                              "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                              "--task-id", "TASK-001", expected=1)
        self.assertIsNone(blocked["context"])
        self.assertIn("RESUME_BLOCKED", blocked["diagnostic"]["codes"])

    # Package scenario 6: an identity failure never returns protected resume text.
    def test_resume_rejects_missing_binding_before_reading_lite_now(self) -> None:
        now = self.context_root / "TASK-001/NOW.md"
        now.write_text(valid_now(), encoding="utf-8")
        result = self.doctor("lite", "resume", "--package-root", str(self.packages["lite"]),
                             "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                             "--task-id", "TASK-001", expected=2)
        self.assertIsNone(result["context"])
        self.assertEqual(result["diagnostic"]["status"], "unknown")
        self.assertIn("BINDING_MISSING", result["diagnostic"]["codes"])

    # Integration: full with real task remains read-only; all temporary smoke belongs outside it.
    def test_full_task_check_does_not_change_task_bytes(self) -> None:
        self.init("lite")
        task = self.context_root / "TASK-001"
        now = task / "NOW.md"
        now.write_text(valid_now(), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in task.iterdir() if path.is_file()}
        report = self.doctor("lite", "check", "--mode", "full", "--package-root", str(self.packages["lite"]),
                             "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
                             "--task-id", "TASK-001")
        after = {path.name: path.read_bytes() for path in task.iterdir() if path.is_file()}
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(before, after)

    # AC9: a failed cleanup is a visible failure, never a success claim.
    def test_full_reports_cleanup_failure_instead_of_claiming_temporary_cleanup(self) -> None:
        runner = r'''
import importlib.util, json, sys, tempfile
from pathlib import Path
script = Path(sys.argv[1])
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("doctor_cleanup_failure", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def fail_cleanup(self):
    raise OSError("injected cleanup failure")
tempfile.TemporaryDirectory.cleanup = fail_cleanup
raise SystemExit(module.main(sys.argv[2:]))
'''
        package = self.packages["lite"]
        completed = subprocess.run(
            [sys.executable, "-c", runner, str(package / "scripts/context_doctor.py"),
             "check", "--mode", "full", "--package-root", str(package)],
            cwd=self.root, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "fail")
        self.assertIn("CLEANUP_FAILED", report["codes"])

    # Integration: actual Git worktrees are separate workspace identities even with a common git dir.
    def test_same_git_repository_different_worktrees_are_not_the_same_workspace(self) -> None:
        repository = self.root / "repository"
        subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True,
                       text=True, capture_output=True, timeout=20)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "tests@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "Acceptance Tests"], check=True)
        (repository / "README").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-m", "seed"], check=True,
                       text=True, capture_output=True, timeout=20)
        second = self.root / "second-worktree"
        subprocess.run(["git", "-C", str(repository), "worktree", "add", "-b", "other", str(second)], check=True,
                       text=True, capture_output=True, timeout=20)
        self.workspace.rmdir()
        self.workspace = repository
        self.init("lite")
        report = self.doctor("lite", "check", "--mode", "identity", "--package-root", str(self.packages["lite"]),
                             "--context-root", str(self.context_root), "--workspace-root", str(second),
                             "--task-id", "TASK-001", expected=1)
        self.assertEqual(report["status"], "fail")
        self.assertIn("WORKSPACE_MISMATCH", report["codes"])

    # AC4: branch and HEAD are observables, not keys for an existing binding.
    def test_normal_commit_and_branch_switch_keep_the_same_workspace_binding_valid(self) -> None:
        repository = self.root / "branch-repository"
        subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True,
                       text=True, capture_output=True, timeout=20)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "tests@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "Acceptance Tests"], check=True)
        (repository / "README").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-m", "one"], check=True,
                       text=True, capture_output=True, timeout=20)
        self.workspace.rmdir()
        self.workspace = repository
        self.init("lite")
        (repository / "README").write_text("two\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "commit", "-am", "two"], check=True,
                       text=True, capture_output=True, timeout=20)
        subprocess.run(["git", "-C", str(repository), "checkout", "-b", "next"], check=True,
                       text=True, capture_output=True, timeout=20)
        report = self.check_identity("lite")
        self.assertEqual(report["status"], "pass", report)


if __name__ == "__main__":
    unittest.main()
