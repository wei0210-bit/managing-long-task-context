from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRICT = ROOT / "skills" / "context-strict"

COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("examples/strict_completion.py"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("tests/test_context.py"),
    Path("tests/test_evidence.py"),
)


class ContextStrictDistributionTests(unittest.TestCase):
    def test_distribution_matches_maintained_sources(self) -> None:
        expected_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8").replace(
            "name: managing-long-task-context",
            "name: context-strict",
            1,
        )
        self.assertEqual((STRICT / "SKILL.md").read_text(encoding="utf-8"), expected_skill)

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


if __name__ == "__main__":
    unittest.main()
