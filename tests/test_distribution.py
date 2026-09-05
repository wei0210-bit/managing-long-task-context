from __future__ import annotations

import json
import subprocess
import sys
import unittest
from runpy import run_path
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRICT = ROOT / "skills" / "context-strict"

COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("assets/truth-source-contract.example.json"),
    Path("examples/strict_completion.py"),
    Path("examples/truth_source_contract.py"),
    Path("references/production-failure-patterns.md"),
    Path("references/runtime-identity.md"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("src/managing_long_task_context/truth_sources.py"),
    Path("src/managing_long_task_context/runtime_identity.py"),
    Path("src/managing_long_task_context/_identity_core.py"),
    Path("tests/test_context.py"),
    Path("tests/test_dynamic_context_scenario.py"),
    Path("tests/test_evidence.py"),
    Path("tests/test_production_feedback.py"),
    Path("tests/test_truth_sources.py"),
    Path("tests/test_runtime_identity.py"),
    Path("tests/test_context_doctor.py"),
    Path("tests/fixtures/truth_source_pilot.md"),
)


class ContextStrictDistributionTests(unittest.TestCase):
    def test_generated_diagnostic_tools_match_single_sources(self) -> None:
        for package in (STRICT, ROOT / "skills/context-lite"):
            for filename in ("context_doctor.py", "context_identity_core.py", "skill_package.py"):
                with self.subTest(package=package.name, file=filename):
                    self.assertEqual((package / "scripts" / filename).read_bytes(),
                                     (ROOT / "scripts" / filename).read_bytes())
        self.assertEqual((ROOT / "scripts/context_identity_core.py").read_bytes(),
                         (ROOT / "src/managing_long_task_context/_identity_core.py").read_bytes())

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

    def test_distributed_truth_source_example_executes(self) -> None:
        result = subprocess.run(
            [sys.executable, "examples/truth_source_contract.py"],
            cwd=STRICT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
