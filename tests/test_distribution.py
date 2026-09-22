from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from runpy import run_path
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRICT = ROOT / "skills" / "context-strict"

COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("assets/truth-source-contract.example.json"),
    Path("assets/experience-candidate.schema.json"),
    Path("assets/experience-validation.schema.json"),
    Path("assets/rule-execution.schema.json"),
    Path("examples/strict_completion.py"),
    Path("examples/truth_source_contract.py"),
    Path("examples/experience_review.py"),
    Path("examples/experience_candidates.py"),
    Path("examples/rule_execution.py"),
    Path("examples/experience_rule_gate.py"),
    Path("examples/independent_validation.py"),
    Path("examples/short_session_handoff.py"),
    Path("references/production-failure-patterns.md"),
    Path("references/independent-validation.md"),
    Path("references/runtime-identity.md"),
    Path("references/handoff.md"),
    Path("references/bot-pipeline-handoff.md"),
    Path("references/host-codex-cli.md"),
    Path("references/host-native.md"),
    Path("scripts/handoff_preflight.py"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("src/managing_long_task_context/usage_freshness.py"),
    Path("src/managing_long_task_context/truth_sources.py"),
    Path("src/managing_long_task_context/runtime_identity.py"),
    Path("src/managing_long_task_context/handoff.py"),
    Path("src/managing_long_task_context/host_codex_cli.py"),
    Path("src/managing_long_task_context/host_records.py"),
    Path("src/managing_long_task_context/host_codex_native.py"),
    Path("src/managing_long_task_context/host_claude_native.py"),
    Path("src/managing_long_task_context/_identity_core.py"),
    Path("src/managing_long_task_context/_experience_store.py"),
    Path("src/managing_long_task_context/experience.py"),
    Path("src/managing_long_task_context/rule_execution.py"),
    Path("tests/test_context.py"),
    Path("tests/test_completion_upgrade.py"),
    Path("tests/test_dynamic_context_scenario.py"),
    Path("tests/test_evidence.py"),
    Path("tests/test_production_feedback.py"),
    Path("tests/test_truth_sources.py"),
    Path("tests/test_runtime_identity.py"),
    Path("tests/test_context_experience_cli.py"),
    Path("tests/test_experience_review.py"),
    Path("tests/test_rule_execution.py"),
    Path("tests/test_experience_rule_gate.py"),
    Path("tests/test_independent_validation.py"),
    Path("tests/test_handoff_activation.py"),
    Path("tests/test_handoff_protocol.py"),
    Path("tests/handoff_test_authority.py"),
    Path("tests/test_handoff_codex_cli.py"),
    Path("tests/handoff_codex_fixture.py"),
    Path("tests/test_handoff_host_records.py"),
    Path("tests/handoff_host_records_fixture.py"),
    Path("tests/handoff_gate_fixtures.py"),
    Path("tests/test_handoff_codex_native.py"),
    Path("tests/test_handoff_claude_native.py"),
    Path("tests/test_handoff_preflight.py"),
    Path("tests/fixtures/truth_source_pilot.md"),
)

# Independent expectation: Strict-only preflight files, never derived from the sync script.
PREFLIGHT_FILES = (Path("scripts/handoff_preflight.py"), Path("tests/test_handoff_preflight.py"))


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
            for filename in ("context_doctor.py", "context_experience.py", "context_identity_core.py", "skill_package.py", "context_usage.py"):
                with self.subTest(package=package.name, file=filename):
                    self.assertEqual((package / "scripts" / filename).read_bytes(),
                                     (ROOT / "scripts" / filename).read_bytes())
            for relative in ("tests/test_context_usage.py", "references/context-usage.md"):
                self.assertEqual((package / relative).read_bytes(), (ROOT / relative).read_bytes())
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

    def test_distributed_independent_validation_example_executes_from_skill_root(self) -> None:
        result = subprocess.run(
            [sys.executable, "examples/independent_validation.py"],
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
            Path("examples/independent_validation.py"),
            Path("references/independent-validation.md"),
            Path("tests/test_independent_validation.py"),
        ):
            self.assertEqual(COPIED_FILES.count(relative), 1)

    def test_distributed_truth_source_example_executes(self) -> None:
        result = subprocess.run(
            [sys.executable, "examples/truth_source_contract.py"],
            cwd=STRICT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_dist_01_preflight_script_and_tests_are_byte_identical_generated_copies(self) -> None:
        for relative in PREFLIGHT_FILES:
            with self.subTest(path=str(relative)):
                self.assertEqual((STRICT / relative).read_bytes(), (ROOT / relative).read_bytes())

    def test_dist_02_preflight_is_listed_exactly_once_in_independent_and_sync_lists(self) -> None:
        sync_copied_files = run_path(ROOT / "scripts/sync_context_strict_skill.py")["COPIED_FILES"]
        declaration = json.loads((STRICT / "skill-package.json").read_text(encoding="utf-8"))
        for relative in PREFLIGHT_FILES:
            with self.subTest(path=str(relative)):
                self.assertEqual(COPIED_FILES.count(relative), 1)
                self.assertEqual(sync_copied_files.count(relative), 1)
                self.assertEqual(declaration["required_paths"].count(relative.as_posix()), 1)
        self.assertEqual(COPIED_FILES, sync_copied_files)

    def test_dist_03_lite_sources_tools_and_built_package_never_contain_preflight(self) -> None:
        lite = ROOT / "skills" / "context-lite"
        self.assertEqual(sorted(path.name for path in lite.rglob("*handoff_preflight*")), [])
        self.assertNotIn("handoff_preflight.py", run_path(ROOT / "scripts/sync_context_tools.py")["TOOLS"])
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "context-lite"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts/skill_package.py"), "build", "--source", str(lite),
                 "--destination", str(package), "--source-revision", "test:lite-boundary"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            manifest = json.loads((package / "skill-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([entry["path"] for entry in manifest["files"] if "handoff_preflight" in entry["path"]], [])

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
