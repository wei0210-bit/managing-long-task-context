"""Public full-package boundary: host modules cannot be untracked side loads."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HostDistributionTests(unittest.TestCase):
    def test_complete_candidate_contains_and_tracks_both_host_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / "package"
            build = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/skill_package.py"),
                    "build",
                    "--source",
                    str(ROOT / "skills/context-strict"),
                    "--destination",
                    str(package),
                    "--source-revision",
                    "candidate:e3-local-test",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            declaration = json.loads((package / "skill-package.json").read_text())
            for name in ("host_codex_cli", "host_records", "host_codex_native", "host_claude_native"):
                relative = f"src/managing_long_task_context/{name}.py"
                self.assertIn(relative, declaration["required_paths"])
                self.assertTrue((package / relative).is_file())
            script = """
import json,sys
import managing_long_task_context as c
from managing_long_task_context.host_codex_cli import CodexCliHost
from managing_long_task_context.host_records import HostTaskLedger
print(json.dumps(c.runtime_identity(package_root=sys.argv[1])))
"""
            run = subprocess.run(
                [sys.executable, "-c", script, str(package)],
                cwd=root,
                env={
                    **os.environ,
                    "PYTHONPATH": str(package / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["status"], "pass", report)
            for name in ("host_codex_cli", "host_records", "host_codex_native", "host_claude_native"):
                for mutation in ("missing", "tamper", "outside-import"):
                    with self.subTest(module=name, mutation=mutation):
                        candidate = root / f"{name}-{mutation}"
                        shutil.copytree(package, candidate)
                        module = candidate / f"src/managing_long_task_context/{name}.py"
                        if mutation == "missing":
                            module.unlink()  # This test's own isolated package only.
                        elif mutation == "tamper":
                            module.write_bytes(
                                module.read_bytes() + b"\n# injected test mutation\n"
                            )
                        else:
                            outside = root / f"outside-{name}.py"
                            shutil.copy2(module, outside)
                            program = """
import importlib.util,json,sys
name='managing_long_task_context.'+sys.argv[3]
spec=importlib.util.spec_from_file_location(name,sys.argv[2])
module=importlib.util.module_from_spec(spec)
sys.modules[name]=module
spec.loader.exec_module(module)
import managing_long_task_context as c
print(json.dumps(c.runtime_identity(package_root=sys.argv[1])))
"""
                            probe = subprocess.run(
                                [
                                    sys.executable,
                                    "-c",
                                    program,
                                    str(candidate),
                                    str(outside),
                                    name,
                                ],
                                cwd=root,
                                env={
                                    **os.environ,
                                    "PYTHONPATH": str(candidate / "src"),
                                    "PYTHONDONTWRITEBYTECODE": "1",
                                },
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            self.assertEqual(probe.returncode, 0, probe.stderr)
                            identity = json.loads(probe.stdout)
                            self.assertNotEqual(identity["status"], "pass", identity)
                            self.assertIn("RUNTIME_PATH_MISMATCH", identity["codes"])
                            continue
                        check = subprocess.run(
                            [
                                sys.executable,
                                str(candidate / "scripts/skill_package.py"),
                                "verify",
                                "--package",
                                str(candidate),
                            ],
                            cwd=root,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        self.assertNotEqual(check.returncode, 0, check.stdout)
                        self.assertEqual(json.loads(check.stdout)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
