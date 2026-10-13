"""Public-package distribution checks for verified experience controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"


class ExperienceDistributionTests(unittest.TestCase):
    def _build(self, source: Path, destination: Path, *, revision: str) -> Path:
        completed = subprocess.run(
            [sys.executable, str(PACKAGER), "build", "--source", str(source),
             "--destination", str(destination), "--source-revision", revision],
            cwd=destination.parent, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "pass")
        return destination

    def test_lite_package_runs_candidate_cli_test_and_example_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary).resolve()
            package = outside / "context-lite"
            built = subprocess.run(
                [sys.executable, str(PACKAGER), "build", "--source", str(ROOT / "skills/context-lite"),
                 "--destination", str(package), "--source-revision", "git:ticket-6"],
                cwd=outside, capture_output=True, text=True, check=False, timeout=60,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertEqual(json.loads(built.stdout)["skill_version"],
                             json.loads((ROOT / "skills/context-lite/skill-package.json").read_text())["skill_version"])
            test_path = package / "tests" / "test_context_experience_cli.py"
            example_path = package / "examples" / "experience_candidates.py"
            self.assertTrue(test_path.is_file(), test_path)
            self.assertTrue(example_path.is_file(), example_path)
            test_run = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(package / "tests"),
                 "-p", test_path.name, "-q"],
                cwd=outside, capture_output=True, text=True, check=False, timeout=60,
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
            )
            self.assertEqual(test_run.returncode, 0, test_run.stdout + test_run.stderr)
            example_run = subprocess.run(
                [sys.executable, str(example_path)], cwd=outside, capture_output=True,
                text=True, check=False, timeout=60,
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
            )
            self.assertEqual(example_run.returncode, 0, example_run.stdout + example_run.stderr)
            self.assertEqual(json.loads(example_run.stdout)["status"], "pass")




if __name__ == "__main__":
    unittest.main()
