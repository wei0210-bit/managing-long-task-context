"""Public-package distribution checks for verified experience controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"


class ExperienceDistributionTests(unittest.TestCase):
    def _build(self, source: Path, destination: Path, *, revision: str) -> Path:
        completed = subprocess.run(
            [sys.executable, str(PACKAGER), "build", "--source", str(source),
             "--destination", str(destination), "--source-revision", revision],
            cwd=destination.parent, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "pass")
        return destination

    def test_lite_package_runs_candidate_cli_test_and_example_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            outside = Path(temporary)
            package = outside / "context-lite"
            built = subprocess.run(
                [sys.executable, str(PACKAGER), "build", "--source", str(ROOT / "skills/context-lite"),
                 "--destination", str(package), "--source-revision", "git:ticket-6"],
                cwd=outside, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertEqual(json.loads(built.stdout)["skill_version"], "1.3.0")
            test_path = package / "tests" / "test_context_experience_cli.py"
            example_path = package / "examples" / "experience_candidates.py"
            self.assertTrue(test_path.is_file(), test_path)
            self.assertTrue(example_path.is_file(), example_path)
            test_run = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(package / "tests"),
                 "-p", test_path.name, "-q"],
                cwd=outside, capture_output=True, text=True, check=False, timeout=30,
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
            )
            self.assertEqual(test_run.returncode, 0, test_run.stdout + test_run.stderr)
            example_run = subprocess.run(
                [sys.executable, str(example_path)], cwd=outside, capture_output=True,
                text=True, check=False, timeout=30,
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
            )
            self.assertEqual(example_run.returncode, 0, example_run.stdout + example_run.stderr)
            self.assertEqual(json.loads(example_run.stdout)["status"], "pass")

    def test_strict_package_runs_five_file_backed_rule_scenarios_outside_repository(self) -> None:
        program = r'''
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

package = Path(sys.argv[1])
sys.path.insert(0, str(package / "src"))
import managing_long_task_context as context

def source_ref(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def gate_for(workspace, name, required, initial, recovered):
    control = workspace / (name + ".txt")
    control.write_text(initial, encoding="utf-8")
    ref = source_ref(control)
    base = workspace.parent / ".prime" / name
    contract = {
        "schema": 1, "task_id": "DIST-" + name, "version": 1,
        "issued_by": "package-test", "issued_at": "2026-09-07T00:00:00Z",
        "authorized_approvers": [], "workspace_root": str(workspace),
        "required_capabilities": ["rule-execution/v1"],
        "objective": "Verify " + name, "scope": ["external package"], "out_of_scope": [],
        "constraints": ["temporary files only"],
        "acceptance_criteria": [{"id": "AC-01", "criterion": "rule gate runs", "required_evidence_types": ["test-report"]}],
        "rule_execution": {"schema": 1, "rules": [{
            "rule_id": name, "experience_ref": None, "severity": "load-bearing",
            "applies_at": ["handoff"], "trigger_id": "controlled-modification",
            "checker_id": name + "-checker", "checker_version": "1",
            "observation_source_id": "temporary-file-observer",
        }]},
    }
    context.publish_contract(contract, confirmed_by="package-test", base_dir=base)
    context.checkpoint("DIST-" + name, phase="handoff", completed=[], evidence_added=[],
                       next_action="run package gate", actor="package-test", base_dir=base)
    def observe(task, stage, source_id):
        now = datetime.now(timezone.utc)
        return {"status": "pass", "codes": [], "coverage": "complete", "scope": name,
                "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "source_refs": [source_ref(control)], "payload": {"controlled_modification": True}}
    def applies(rule, observation):
        return {"status": "applicable", "codes": [], "source_refs": [source_ref(control)]}
    def check(rule, observation):
        return {"status": "pass", "codes": []} if control.read_text(encoding="utf-8") == required else {"status": "fail", "codes": [name.upper() + "_REJECTED"]}
    runtime = {"observe": observe, "applies": applies, "check": check}
    rejected = context.gate("DIST-" + name, stage="handoff", base_dir=base, emit=False, rule_runtime=runtime)
    control.write_text(recovered, encoding="utf-8")
    accepted = context.gate("DIST-" + name, stage="handoff", base_dir=base, emit=False, rule_runtime=runtime)
    return rejected, accepted

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    workspace = root / "workspace"
    workspace.mkdir()
    cases = {
        "missing-self-tests": ("self-tests: passed\n", "claim: tests passed\n", "self-tests: passed\n"),
        "missing-debt-scan": ("debt-scan: complete\n", "new-work: started\n", "debt-scan: complete\n"),
        "absent-violation-record": ("violation-recorded: yes\n", "violation: found\n", "violation-recorded: yes\n"),
        "line-number-free-control": ("compliance: yes\n", "line: 12\ncompliance: yes\n", "compliance: yes\n"),
        "direct-modification-bypass": ("dispatch: recorded\n", "modification: direct\n", "dispatch: recorded\n"),
    }
    results = {}
    for name, (required, initial, recovered) in cases.items():
        rejected, accepted = gate_for(workspace, name, required, initial, recovered)
        results[name] = {"rejected": rejected["passed"], "accepted": accepted["passed"],
                         "codes": rejected["rules"][0]["codes"]}
    print(json.dumps(results, sort_keys=True))
    assert all(not item["rejected"] and item["accepted"] and item["codes"] for item in results.values())
'''
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            outside = Path(temporary)
            package = self._build(ROOT / "skills/context-strict", outside / "context-strict", revision="git:ticket-6")
            self.assertTrue((package / "tests" / "test_experience_distribution.py").is_file())
            environment = dict(os.environ, PYTHONPATH=str(package / "src"))
            completed = subprocess.run(
                [sys.executable, "-c", program, str(package)], cwd=outside, env=environment,
                capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            results = json.loads(completed.stdout)
            self.assertEqual(set(results), {
                "missing-self-tests", "missing-debt-scan", "absent-violation-record",
                "line-number-free-control", "direct-modification-bypass",
            })

    def test_historical_strict_package_rejects_rule_execution_capability(self) -> None:
        historical_revision = "3e954eb"
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            outside = Path(temporary)
            archive = outside / "historical.tar"
            with archive.open("wb") as stream:
                archived = subprocess.run(
                    ["git", "archive", "--format=tar", historical_revision + ":skills/context-strict"],
                    cwd=ROOT, stdout=stream, stderr=subprocess.PIPE, check=False,
                )
            self.assertEqual(archived.returncode, 0, archived.stderr.decode("utf-8", "replace"))
            unpacked = subprocess.run(["tar", "-xf", str(archive), "-C", str(outside)], capture_output=True, text=True, check=False)
            self.assertEqual(unpacked.returncode, 0, unpacked.stdout + unpacked.stderr)
            historical = outside
            program = r'''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
import managing_long_task_context as context
try:
    context.publish_contract({
        "schema": 1, "task_id": "OLD-CAPABILITY", "version": 1, "issued_by": "test",
        "issued_at": "2026-09-07T00:00:00Z", "authorized_approvers": [],
        "objective": "old package rejection", "scope": [], "out_of_scope": [], "constraints": [],
        "acceptance_criteria": [], "workspace_root": str(Path.cwd()),
        "required_capabilities": ["rule-execution/v1"],
    }, confirmed_by="test", base_dir=Path.cwd() / ".prime")
except context.ContextError as error:
    print(str(error))
    raise SystemExit(0)
raise SystemExit(1)
'''
            environment = dict(os.environ, PYTHONPATH=str(historical / "src"))
            rejected = subprocess.run([sys.executable, "-c", program, str(historical)], cwd=outside,
                                      env=environment, capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
            self.assertIn("rule-execution/v1", rejected.stdout)
            self.assertIn("unsupported", rejected.stdout.lower())


if __name__ == "__main__":
    unittest.main()
