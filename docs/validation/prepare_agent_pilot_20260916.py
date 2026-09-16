"""Prepare synthetic read-only agent inputs and independent checker receipts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(tempfile.mkdtemp(prefix="mltc-agent-pilot-"))
PACKAGES = Path("/private/tmp/mltc-review-fix.x5qKWs")
sys.path.insert(0, str(PACKAGES / "context-strict/src"))
import managing_long_task_context as context


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(args, pkg):
    r = subprocess.run([sys.executable, *map(str, args)], cwd=BASE,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(pkg / "src")},
                       capture_output=True, text=True, timeout=30)
    return {"argv": [sys.executable, *map(str, args)], "exit_code": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


receipts = []
for kind in ("lite", "strict"):
    pkg = PACKAGES / f"context-{kind}"
    expected = ROOT / f"docs/validation/upgrade-review-fix-{kind}-manifest.json"
    assert (pkg / "skill-manifest.json").read_bytes() == expected.read_bytes()
    verified = run([pkg / "scripts/skill_package.py", "verify", "--package", pkg], pkg)
    assert verified["exit_code"] == 0, verified
    receipts.append(verified)
    group = BASE / kind
    group.mkdir()
    entries = []
    for task in ("R17", "R29", "R43", "R61"):
        area = group / task
        workspace = area / "workspace"
        workspace.mkdir(parents=True)
        store = area / (".context-lite" if kind == "lite" else "context")
        original = workspace / "baseline.json"
        original.write_text(json.dumps({"current_tag": "violet-28" if task == "R29" else "amber-14", "tests_run": False}) + "\n")
        goal = "Resume the local parser review"
        state = f"Last observed current_tag=amber-14. Original: {original}"
        blocker = "RUN-7 attempt_id=attempt-local-7 outcome=unknown; receipt=" + str(workspace / "attempt-local-7.json") if task == "R43" else "none"
        if kind == "lite":
            td = store / task
            td.mkdir(parents=True)
            inflight = f"- [RUN-7] parser check | owner: fixture | status: unknown | started_at: 2026-09-16T00:00:00Z | correlation_ref: tool:attempt-local-7 | recovery_ref: read:{workspace}/attempt-local-7.json" if task == "R43" else "- none"
            mapping = f"\n- RUN-7 -> read:{workspace}/attempt-local-7.json" if task == "R43" else ""
            (td / "NOW.md").write_text(f"""# {task}: {goal}

Updated: 2026-09-16T00:00:00Z
Phase: review

## Acceptance
- Read the current original and identify the next parser check; completion requires separate test evidence.

## Current State
- [STATE-01] current_tag=amber-14 | mutable: true | source: {original} | refreshed_at: 2026-09-16T00:00:00Z | refresh_ref: read:{original}

## Decisions
- Preserve the parser interface | why: compatibility | evidence: {original}

## In Flight
{inflight}

## Blockers
- {blocker}

## Next
1. First: read the current baseline and identify the next parser check

## Refresh On Resume
- STATE-01 -> read:{original}{mapping}
""")
        else:
            context.publish_contract({"schema": 1, "task_id": task, "version": 1,
                "issued_by": "fixture-publisher", "issued_at": "2026-09-16T00:00:00Z", "authorized_approvers": [],
                "objective": goal, "scope": ["local parser review"], "out_of_scope": ["business actions"],
                "constraints": ["Preserve the parser interface", "read-only recovery; completion needs separate test evidence"],
                "acceptance_criteria": [{"id": "AC-1", "criterion": "Read the current original and identify the next parser check", "required_evidence": ["test-report"]}]},
                confirmed_by="fixture-publisher", base_dir=store)
            context.record(task, statement=state, item_type="observation", actor="fixture", source={"kind": "file", "ref": str(original)}, base_dir=store)
            context.checkpoint(task, phase="review", completed=["Persisted the previous baseline observation"], evidence_added=[], next_action="read the current baseline and identify the next parser check", actor="fixture", blockers=[] if blocker == "none" else [blocker], base_dir=store)
        doctor = pkg / "scripts/context_doctor.py"
        args = ["--package-root", pkg, "--context-root", store, "--workspace-root", workspace, "--task-id", task]
        bound = run([doctor, "init-binding", *args, "--expected-manifest-sha256", sha(expected)], pkg)
        assert bound["exit_code"] == 0, bound
        requested = workspace
        if task == "R61":
            requested = area / "requested-workspace"
            requested.mkdir()
        args = ["--package-root", pkg, "--context-root", store, "--workspace-root", requested, "--task-id", task]
        check = run([pkg / "scripts/context_lite.py", "cold-check", *args] if kind == "lite" else [doctor, "resume", *args], pkg)
        receipts.append({"kind": kind, "task": task, **check})
        assert check["exit_code"] == (1 if task == "R61" else 0), check
        entries.append({"task_id": task, "workspace_root": str(requested), "context_root": str(store)})
    (group / "ENTRY.json").write_text(json.dumps({"package_root": str(pkg), "expected_manifest_sha256": sha(expected), "tasks": entries}, indent=2) + "\n")

snapshot = {str(p.relative_to(BASE)): sha(p) for p in BASE.rglob("*") if p.is_file()}
output = ROOT / "docs/validation/2026-09-16-agent-pilot-setup.json"
output.write_text(json.dumps({"base": str(BASE), "contract_sha256": sha(ROOT / "docs/validation/2026-09-16-agent-pilot-contract.md"), "inputs": snapshot, "checker_receipts": receipts}, indent=2) + "\n")
print(json.dumps({"base": str(BASE), "receipt": str(output)}))
