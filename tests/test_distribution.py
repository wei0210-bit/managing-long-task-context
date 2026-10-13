from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from runpy import run_path
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRICT = ROOT / "skills" / "context-strict"


def _project_version() -> str:
    project = re.search(
        r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)",
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    ).group(1)
    return re.search(r'^version\s*=\s*"([^"]+)"\s*$', project, re.MULTILINE).group(1)


COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("assets/truth-source-contract.example.json"),
    Path("assets/experience-candidate.schema.json"),
    Path("assets/experience-validation.schema.json"),
    Path("examples/strict_completion.py"),
    Path("examples/truth_source_contract.py"),
    Path("examples/experience_review.py"),
    Path("examples/experience_candidates.py"),
    Path("references/production-failure-patterns.md"),
    Path("references/runtime-identity.md"),
    Path("references/bot-pipeline-handoff.md"),
    Path("references/agent-role-handoff.md"),
    Path("scripts/coordinator_ops.py"),
    Path("tests/test_coordinator_ops.py"),
    Path("scripts/context_skill_router.py"),
    Path("tests/test_context_skill_router.py"),
    Path("scripts/context_status.py"), Path("tests/test_resume_gate.py"),
    Path("tests/test_ledger_reports.py"),
    Path("tests/test_update_item_verified_at.py"),
    Path("tests/test_brief_rendering.py"),
    Path("scripts/package_lineage.py"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("src/managing_long_task_context/usage_freshness.py"),
    Path("src/managing_long_task_context/project_store.py"),
    Path("src/managing_long_task_context/acceptance.py"),
    Path("tests/test_acceptance_records.py"),
    Path("src/managing_long_task_context/worker_report.py"),
    Path("tests/test_worker_report.py"),
    Path("src/managing_long_task_context/contract_history.py"),
    Path("tests/test_contract_history.py"),
    Path("src/managing_long_task_context/truth_sources.py"),
    Path("src/managing_long_task_context/runtime_identity.py"),
    Path("src/managing_long_task_context/_identity_core.py"),
    Path("src/managing_long_task_context/_experience_store.py"),
    Path("src/managing_long_task_context/experience.py"),
    Path("tests/test_context.py"),
    Path("tests/test_evidence.py"),
    Path("tests/test_production_feedback.py"),
    Path("tests/test_truth_sources.py"),
    Path("tests/test_runtime_identity.py"),
    Path("tests/test_project_store.py"),
    Path("tests/test_context_experience_cli.py"),
    Path("tests/test_experience_review.py"),
    Path("tests/test_experience_cross_checkout.py"),
    Path("tests/fixtures/truth_source_pilot.md"),
)

# Independent expectation: Strict-only preflight files, never derived from the sync script.
PREFLIGHT_FILES = ()


class ContextStrictDistributionTests(unittest.TestCase):
    def test_generated_diagnostic_tools_match_single_sources(self) -> None:
        self.assertEqual(
            (ROOT / "tests/test_context_lite_handoff.py").read_bytes(),
            (ROOT / "skills/context-lite/tests/test_context_lite_handoff.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "tests/test_context_lite_validator.py").read_bytes(),
            (ROOT / "skills/context-lite/tests/test_context_lite_validator.py").read_bytes(),
        )
        for package in (STRICT, ROOT / "skills/context-lite"):
            for filename in ("context_doctor.py", "context_experience.py", "context_identity_core.py", "skill_package.py"):
                with self.subTest(package=package.name, file=filename):
                    self.assertEqual((package / "scripts" / filename).read_bytes(),
                                     (ROOT / "scripts" / filename).read_bytes())
        self.assertEqual((ROOT / "scripts/context_identity_core.py").read_bytes(),
                         (ROOT / "src/managing_long_task_context/_identity_core.py").read_bytes())
        self.assertEqual((ROOT / "scripts/context_experience.py").read_bytes(),
                         (ROOT / "src/managing_long_task_context/_experience_store.py").read_bytes())

    def test_distribution_matches_maintained_sources(self) -> None:
        expected_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8").replace(
            "name: managing-long-task-context",
            "name: context-strict",
            1,
        )
        self.assertEqual((STRICT / "SKILL.md").read_text(encoding="utf-8"), expected_skill)
        expected_package = json.loads((ROOT / "skill-package.json").read_text(encoding="utf-8"))
        expected_package["skill_name"] = "context-strict"
        self.assertEqual(
            json.loads((STRICT / "skill-package.json").read_text(encoding="utf-8")),
            expected_package,
        )

        for relative_path in COPIED_FILES:
            with self.subTest(path=str(relative_path)):
                self.assertEqual(
                    (STRICT / relative_path).read_bytes(),
                    (ROOT / relative_path).read_bytes(),
                )
        for root_only_test in (
            "test_context_doctor.py",
            "test_experience_distribution.py",
        ):
            self.assertFalse((STRICT / "tests" / root_only_test).exists())

    def test_distributed_example_executes_from_skill_root(self) -> None:
        result = subprocess.run(
            [sys.executable, "examples/strict_completion.py"],
            cwd=STRICT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)



    def test_distribution_includes_truth_source_files(self) -> None:
        required = (
            Path("assets/truth-source-contract.example.json"),
            Path("examples/truth_source_contract.py"),
            Path("src/managing_long_task_context/truth_sources.py"),
            Path("tests/test_truth_sources.py"),
            Path("tests/fixtures/truth_source_pilot.md"),
        )
        for relative in required:
            self.assertEqual((STRICT / relative).read_bytes(), (ROOT / relative).read_bytes())

    def test_copy_lists_match_and_include_each_truth_source_file_once(self) -> None:
        sync_copied_files = run_path(ROOT / "scripts/sync_context_strict_skill.py")["COPIED_FILES"]
        self.assertEqual(COPIED_FILES, sync_copied_files)
        for relative in (
            Path("assets/truth-source-contract.example.json"),
            Path("examples/truth_source_contract.py"),
            Path("src/managing_long_task_context/truth_sources.py"),
            Path("tests/test_truth_sources.py"),
            Path("tests/fixtures/truth_source_pilot.md"),
        ):
            self.assertEqual(COPIED_FILES.count(relative), 1)

    def test_worker_report_registration_version_and_export(self) -> None:
        declaration = json.loads((ROOT / "skill-package.json").read_bytes())
        copied = run_path(ROOT / "scripts/sync_context_strict_skill.py")["COPIED_FILES"]
        for relative in (Path("src/managing_long_task_context/worker_report.py"), Path("tests/test_worker_report.py")):
            self.assertEqual(COPIED_FILES.count(relative), 1)
            self.assertEqual(copied.count(relative), 1)
            self.assertEqual(declaration["required_paths"].count(relative.as_posix()), 1)
            self.assertEqual((STRICT / relative).read_bytes(), (ROOT / relative).read_bytes())
        version = _project_version()
        self.assertEqual(declaration["skill_version"], version)
        self.assertEqual(declaration["package_version"], version)
        self.assertEqual(declaration["skill_version"], declaration["package_version"])

    def test_acceptance_registration_version_and_exports(self) -> None:
        declaration = json.loads((ROOT / "skill-package.json").read_bytes())
        copied = run_path(ROOT / "scripts/sync_context_strict_skill.py")["COPIED_FILES"]
        for relative in (Path("src/managing_long_task_context/acceptance.py"), Path("tests/test_acceptance_records.py")):
            self.assertEqual(COPIED_FILES.count(relative), 1)
            self.assertEqual(copied.count(relative), 1)
            self.assertEqual(declaration["required_paths"].count(relative.as_posix()), 1)
            self.assertEqual((STRICT / relative).read_bytes(), (ROOT / relative).read_bytes())
        version = _project_version()
        self.assertEqual(declaration["skill_version"], version)
        self.assertEqual(declaration["package_version"], version)
        result = subprocess.run([sys.executable, "-c", "import managing_long_task_context as m; "
                                "assert all(callable(getattr(m, n, None)) for n in "
                                "('record_acceptance', 'latest_acceptance', 'acceptance_status'))"],
                                env={"PYTHONPATH": str(STRICT / "src")}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_distributed_truth_source_example_executes(self) -> None:
        result = subprocess.run(
            [sys.executable, "examples/truth_source_contract.py"],
            cwd=STRICT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)





    def test_dist_04_second_sync_of_a_copied_tree_writes_no_new_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "root"
            copy.mkdir()
            for name in ("SKILL.md", "skill-package.json", "pyproject.toml"):
                shutil.copy2(ROOT / name, copy / name)
            for name in ("assets", "examples", "references", "scripts", "src", "tests", "skills"):
                shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

            def snapshot() -> dict[str, str]:
                return {
                    path.relative_to(copy).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(copy.rglob("*")) if path.is_file() and "__pycache__" not in path.parts
                }

            before = snapshot()
            for run in (1, 2):
                completed = subprocess.run(
                    [sys.executable, str(copy / "scripts/sync_context_strict_skill.py")], cwd=copy,
                    env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                with self.subTest(sync_run=run):
                    self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
