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
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

package = Path(sys.argv[1])
sys.path.insert(0, str(package / "src"))
import managing_long_task_context as context

def source_ref(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def gate_for(workspace, name, checker, recover):
    case = workspace / name
    case.mkdir(exist_ok=True)
    observation = case / "observation.json"
    observation.write_text(json.dumps({"case": name}), encoding="utf-8")
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
                "source_refs": [source_ref(observation)], "payload": {"controlled_modification": True}}
    def applies(rule, observation):
        return {"status": "applicable", "codes": [], "source_refs": [source_ref(case / "observation.json")]}
    def check(rule, observation):
        return {"status": "pass", "codes": []} if checker(case) else {"status": "fail", "codes": [name.upper() + "_REJECTED"]}
    runtime = {"observe": observe, "applies": applies, "check": check}
    rejected = context.gate("DIST-" + name, stage="handoff", base_dir=base, emit=False, rule_runtime=runtime)
    recover(case)
    accepted = context.gate("DIST-" + name, stage="handoff", base_dir=base, emit=False, rule_runtime=runtime)
    return rejected, accepted

def self_test_fixture(case):
    guards = [case / name for name in ("scope_guard.py", "evidence_guard.py", "dispatch_guard.py")]
    (case / "claimed-self-tests.json").write_text(json.dumps({"claim": "already self-tested"}), encoding="utf-8")
    for guard in guards:
        guard.write_text("import sys\nraise SystemExit(2)\n", encoding="utf-8")
    def checker(root):
        return all(
            subprocess.run([sys.executable, str(guard), "--self-test"], cwd=root, capture_output=True).returncode == 0
            for guard in guards
        )
    def recover(root):
        implementation = """import sys
def allowed(value):
    return value == 'allowed-sample'
if sys.argv[1:] == ['--self-test']:
    assert allowed('allowed-sample')
    assert not allowed('rejected-sample')
    raise SystemExit(0)
raise SystemExit(0 if len(sys.argv) == 2 and allowed(sys.argv[1]) else 1)
"""
        for guard in guards:
            guard.write_text(implementation, encoding="utf-8")
    return checker, recover

def debt_scan_fixture(case):
    debt_source = case / "debt-source.json"
    debt_source.write_text(json.dumps([{"id": "DEBT-1", "area": "parser"}, {"id": "DEBT-2", "area": "routing"}]), encoding="utf-8")
    tickets = case / "tickets.json"
    original_ticket = {"ticket_id": "NEW-1", "opened_ns": time.time_ns(), "scope": "new work without debt scan"}
    tickets.write_text(json.dumps([original_ticket]), encoding="utf-8")
    scan = case / "debt-scan.json"
    def checker(root):
        try:
            source = json.loads(debt_source.read_text(encoding="utf-8"))
            scan_data = json.loads(scan.read_text(encoding="utf-8"))
            opened = json.loads(tickets.read_text(encoding="utf-8"))
            new_ticket = next(item for item in opened if item["ticket_id"] == "NEW-2")
            return (scan_data["source_sha256"] == hashlib.sha256(debt_source.read_bytes()).hexdigest()
                    and scan_data["debt_ids"] == [item["id"] for item in source]
                    and opened[0] == original_ticket
                    and new_ticket["debt_scan_sha256"] == hashlib.sha256(scan.read_bytes()).hexdigest()
                    and scan_data["created_ns"] < new_ticket["opened_ns"])
        except (KeyError, OSError, ValueError, TypeError, StopIteration):
            return False
    def recover(root):
        source = json.loads(debt_source.read_text(encoding="utf-8"))
        scan_data = {"source_sha256": hashlib.sha256(debt_source.read_bytes()).hexdigest(), "debt_ids": [item["id"] for item in source], "created_ns": time.time_ns()}
        scan.write_text(json.dumps(scan_data, sort_keys=True), encoding="utf-8")
        history = json.loads(tickets.read_text(encoding="utf-8"))
        history.append({"ticket_id": "NEW-2", "opened_ns": time.time_ns(), "scope": "new work after debt scan", "debt_scan_sha256": hashlib.sha256(scan.read_bytes()).hexdigest()})
        tickets.write_text(json.dumps(history, sort_keys=True), encoding="utf-8")
    return checker, recover

def violation_ledger_fixture(case):
    actions = case / "actions.json"
    ledger = case / "violations.json"
    action = {"action_id": "ACT-1", "task_id": "DIST-absent-violation-record", "violation": {"code": "DISPATCH_MISSING"}}
    actions.write_text(json.dumps([action]), encoding="utf-8")
    ledger.write_text("[]", encoding="utf-8")
    def checker(root):
        try:
            recorded = {(entry["action_id"], entry["task_id"], entry["code"]) for entry in json.loads(ledger.read_text())}
            return all((item["action_id"], item["task_id"], item["violation"]["code"]) in recorded for item in json.loads(actions.read_text()) if item.get("violation"))
        except (KeyError, OSError, ValueError, TypeError):
            return False
    def recover(root):
        ledger.write_text(json.dumps([{ "action_id": action["action_id"], "task_id": action["task_id"], "code": action["violation"]["code"] }]), encoding="utf-8")
    return checker, recover

def line_reference_fixture(case):
    issue = case / "issue.json"
    issue.write_text(json.dumps({"issue_id": "ISSUE-1", "references": [{"path": "policy.md", "line": 12}]}), encoding="utf-8")
    def checker(root):
        try:
            item = json.loads(issue.read_text())
            references = item["references"]
            return bool(references) and all(
                set(ref).issubset({"path", "symbol"})
                and isinstance(ref.get("path"), str) and ref["path"]
                for ref in references
            )
        except (KeyError, OSError, ValueError, TypeError):
            return False
    def recover(root):
        issue.write_text(json.dumps({"issue_id": "ISSUE-1", "references": [{"path": "policy.md", "symbol": "retention-policy"}]}), encoding="utf-8")
    return checker, recover

def dispatch_fixture(case):
    artifact = case / "artifact.txt"
    artifact.write_text("first revision\n", encoding="utf-8")
    before = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.write_text("direct revision\n", encoding="utf-8")
    direct = {"action_id": "ACT-1", "task_id": "DIST-direct-modification-bypass", "sequence": 3, "before_sha256": before, "after_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    actions = case / "actions.json"
    actions.write_text(json.dumps([direct]), encoding="utf-8")
    violations = case / "violations.json"
    violations.write_text(json.dumps([{ "action_id": "ACT-1", "task_id": direct["task_id"], "code": "DISPATCH_MISSING" }]), encoding="utf-8")
    dispatch = case / "dispatch.json"
    acceptance = case / "acceptance.json"
    def checker(root):
        try:
            history = json.loads(actions.read_text())
            known_violations = {(entry["action_id"], entry["code"]) for entry in json.loads(violations.read_text())}
            current = history[-1]
            if ("ACT-1", "DISPATCH_MISSING") not in known_violations or current["action_id"] == "ACT-1":
                return False
            frozen = json.loads(acceptance.read_text())
            sent = json.loads(dispatch.read_text())
            return (current["task_id"] == sent["task_id"] == direct["task_id"]
                    and current["action_id"] == sent["action_id"]
                    and frozen["task_id"] == current["task_id"]
                    and sent["acceptance_sha256"] == hashlib.sha256(acceptance.read_bytes()).hexdigest()
                    and frozen["sequence"] < sent["sequence"] < current["sequence"]
                    and current["before_sha256"] != current["after_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest())
        except (KeyError, OSError, ValueError, TypeError, IndexError):
            return False
    def recover(root):
        frozen = {"task_id": direct["task_id"], "criteria": ["preserve dispatch evidence"], "sequence": 4}
        acceptance.write_text(json.dumps(frozen, sort_keys=True), encoding="utf-8")
        sent = {"action_id": "ACT-2", "task_id": direct["task_id"], "acceptance_sha256": hashlib.sha256(acceptance.read_bytes()).hexdigest(), "sequence": 5}
        dispatch.write_text(json.dumps(sent, sort_keys=True), encoding="utf-8")
        current_before = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.write_text("dispatched revision\n", encoding="utf-8")
        history = json.loads(actions.read_text())
        history.append({"action_id": "ACT-2", "task_id": direct["task_id"], "sequence": 6, "before_sha256": current_before, "after_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
        actions.write_text(json.dumps(history, sort_keys=True), encoding="utf-8")
    return checker, recover

with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
    root = Path(temporary)
    workspace = root / "workspace"
    workspace.mkdir()
    cases = {
        "missing-self-tests": self_test_fixture,
        "missing-debt-scan": debt_scan_fixture,
        "absent-violation-record": violation_ledger_fixture,
        "line-number-free-control": line_reference_fixture,
        "direct-modification-bypass": dispatch_fixture,
    }
    results = {}
    for name, fixture in cases.items():
        case = workspace / name
        case.mkdir()
        checker, recover = fixture(case)
        rejected, accepted = gate_for(workspace, name, checker, recover)
        results[name] = {"rejected": rejected["passed"], "accepted": accepted["passed"],
                         "codes": rejected["rules"][0]["codes"]}
    print(json.dumps(results, sort_keys=True))
    assert all(not item["rejected"] and item["accepted"] and item["codes"] for item in results.values())
'''
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            outside = Path(temporary)
            package = self._build(ROOT / "skills/context-strict", outside / "context-strict", revision="git:ticket-6")
            self.assertTrue((package / "tests" / "test_experience_rule_gate.py").is_file())
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
