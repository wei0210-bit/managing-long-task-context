"""Frozen public-gate cases; fixtures are synthetic, not real model outputs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get("COMPLETION_PACKAGE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context

spec = importlib.util.spec_from_file_location("completion_example", ROOT / "examples/strict_completion.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)

GOLD = {
    "C01": "pass", "C02": "unknown", "C03": "unknown", "C04": "unknown",
    "C05": "unknown", "C06": "unknown", "C07": "unknown", "C08": "unknown",
    "C09": "unknown", "C10": "unknown", "C11": "unknown", "C12": "fail",
    "C13": "unknown", "C14": "unknown", "C15": "fail", "C16": "unknown",
    "C17": "unknown", "C18": "unknown", "C19": "pass", "C20": "unknown",
}
RESULTS = []
CONTENT = b"strict completion result\n"
OBSERVED_AT = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def run_case(case):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "result.txt").write_bytes(CONTENT)
        git_env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                   "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                   "GIT_AUTHOR_DATE": "2026-09-10T00:00:00Z", "GIT_COMMITTER_DATE": "2026-09-10T00:00:00Z"}

        def git(*args):
            return subprocess.run(["git", "-C", str(workspace), "-c", "core.hooksPath=/dev/null",
                                   "-c", "commit.gpgsign=false", *args], env=git_env,
                                  capture_output=True, text=True, check=True, timeout=5).stdout.strip()

        git("init", "--quiet", "--initial-branch=main")
        git("add", "result.txt")
        git("commit", "--quiet", "-m", "fixed offline artifact")
        revision = git("rev-parse", "HEAD")
        base = root / "context"
        contract = {
            "schema": 1, "task_id": "DOC-EXAMPLE", "version": 1,
            "issued_by": "task-publisher", "issued_at": "2026-08-27T04:00:00Z",
            "authorized_approvers": [], "objective": "Verify the exact example artifact content",
            "scope": ["offline example"], "out_of_scope": [], "constraints": [],
            "workspace_root": str(workspace),
            "required_capabilities": ["evidence-handlers/v1"],
            "evidence_handlers": {"schema": "evidence-handlers/v1", "types": {"file": {
                "resolver_capability": "builtin:file/v1",
                "verifier_capability": example.VERIFIER_CAPABILITY,
            }}},
            "acceptance_criteria": [{
                "id": "AC-01", "criterion": "The result contains exactly strict completion result followed by a newline",
                "required_evidence_types": ["file"], "required_revision": revision,
                "required_scope": {"module": "docs-example", "contract_version": 1},
                "max_evidence_age_seconds": 3600,
            }],
        }
        evidence = {
            "evidence_id": "EV-DOC-001", "kind": "file", "locator": "result.txt",
            "artifact_digest": "sha256:" + hashlib.sha256(CONTENT).hexdigest(),
            "generated_at": OBSERVED_AT.isoformat(),
            "scope": {"module": "docs-example", "contract_version": 1},
            "repo_revision": revision, "contract_version": 1,
            "status": "pass", "checker_result": {"status": "pass", "ran": True},
        }
        evidence_map = {"AC-01": {"evidence": [evidence]}}
        if case == "C02":
            extra = deepcopy(contract["acceptance_criteria"][0])
            extra["id"] = "AC-02"
            contract["acceptance_criteria"].append(extra)
        if case in {"C12", "C15"}:
            (workspace / "result.txt").write_bytes(b"strict completion result: FAILED\n")
            evidence["artifact_digest"] = "sha256:" + hashlib.sha256((workspace / "result.txt").read_bytes()).hexdigest()
        if case == "C11":
            (workspace / "result.txt").write_text('{"status":"pass","unrelated":"weather"}')
            evidence["artifact_digest"] = "sha256:" + hashlib.sha256((workspace / "result.txt").read_bytes()).hexdigest()
        if case == "C03":
            evidence["locator"] = "missing.txt"
        if case == "C05":
            evidence["expires_at"] = "2020-01-01T00:00:00Z"
        if case == "C06":
            evidence["contract_version"] = 2
        if case == "C07":
            evidence["repo_revision"] = "b" * 40
        if case == "C08":
            outside = root / "outside.txt"
            outside.write_bytes(CONTENT)
            evidence["locator"] = str(outside)
        if case == "C10":
            evidence_map = {"AC-01": {"status": "pass", "completed": True}}
        if case == "C20":
            git("commit", "--allow-empty", "--quiet", "-m", "different current version")
        if case == "C17":
            extra = deepcopy(contract["acceptance_criteria"][0])
            extra["id"] = "AC-02"
            contract["acceptance_criteria"].append(extra)
            (workspace / "second.txt").write_bytes(CONTENT)
            second = deepcopy(evidence)
            second.update(evidence_id="EV-DOC-002", locator="second.txt")
            evidence_map["AC-02"] = {"evidence": [second]}
        ctx = context.bind(base)
        ctx.publish_contract(contract, confirmed_by="task-publisher")
        if case == "C09":
            item = ctx.record(statement="Two current observations disagree", task_id="DOC-EXAMPLE",
                              item_type="observation", actor="reviewer", source={"kind": "test", "ref": "fixture"})
            ctx.update_item("DOC-EXAMPLE", item["id"], actor="reviewer", status="conflicted",
                            conflicts_with=["EV-DOC-001"], conflict_reason="No authoritative resolution")

        # The callback is host code, not a callable obtained from model JSON.
        checker = (example.make_file_claim_verifier(workspace)
                   if hasattr(example, "make_file_claim_verifier") else example.verify_file_claim)
        calls = []

        def checked(envelope, criterion, resolution):
            if case == "C14":
                calls.append({"status": "unknown", "reason": "actual injected TimeoutError"})
                raise TimeoutError("isolated checker timeout")
            value = checker(envelope, criterion, resolution)
            calls.append(deepcopy(value))
            if case == "C16" or (case == "C17" and criterion["id"] == "AC-02"):
                (workspace / "result.txt").write_bytes(b"changed after check\n")
            return value

        verifiers = {} if case == "C13" else {"file": {"capability": example.VERIFIER_CAPABILITY, "handler": checked}}
        before = {p.name: p.read_bytes() for p in (base / "DOC-EXAMPLE").iterdir() if p.is_file()}
        original_open = Path.open

        def bounded_permission(path, *args, **kwargs):
            if case == "C04" and path == workspace / "result.txt":
                raise PermissionError("synthetic filesystem denial")
            return original_open(path, *args, **kwargs)

        started = time.perf_counter_ns()
        with patch.object(Path, "open", bounded_permission), patch.object(context, "_trusted_utc_now", return_value=OBSERVED_AT):
            report = ctx.gate("DOC-EXAMPLE", stage="completion", evidence_map=evidence_map,
                              verifiers=verifiers, emit=False)
            first = deepcopy(report)
            if case in {"C18", "C19"}:
                if case == "C18":
                    (workspace / "result.txt").write_bytes(b"changed after first request\n")
                report = ctx.gate("DOC-EXAMPLE", stage="completion", evidence_map=evidence_map,
                                  verifiers=verifiers, emit=False)
        elapsed = time.perf_counter_ns() - started
        after = {p.name: p.read_bytes() for p in (base / "DOC-EXAMPLE").iterdir() if p.is_file()}
        statuses = [v["status"] for v in report["criteria"].values()]
        actual = report.get("decision", "pass" if report["passed"] else "fail" if "fail" in statuses else "unknown")
        result = {
            "id": case, "expected": GOLD[case], "actual": actual,
            "model_raw": {"source": "synthetic_fixture_not_model", "decision": "complete"},
            "checker_results": calls, "gate": report, "elapsed_ns": elapsed,
            "requests": 2 if case in {"C18", "C19"} else 1,
            "automatic_retries": 0, "tokens": None, "state_unchanged": before == after,
            "first_passed": first["passed"],
            "input": {"contract": contract, "evidence_map": evidence_map},
        }
        # Remove temp paths from diagnostic artifacts without changing tested inputs.
        return json.loads(json.dumps(result).replace(str(root), "<isolated-root>"))


class CompletionUpgradeTests(unittest.TestCase):
    def test_frozen_cases(self):
        for case, expected in GOLD.items():
            with self.subTest(case=case):
                result = run_case(case)
                RESULTS.append(result)
                self.assertTrue(result["state_unchanged"])
                self.assertEqual(result["actual"], expected)
                self.assertEqual(result["gate"]["passed"], expected == "pass")
                if case in {"C18", "C19"}:
                    self.assertTrue(result["first_passed"])


if __name__ == "__main__":
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompletionUpgradeTests))
    output = os.environ.get("COMPLETION_RESULTS")
    if output:
        Path(output).write_text(json.dumps(RESULTS, indent=2) + "\n")
    raise SystemExit(not outcome.wasSuccessful())
