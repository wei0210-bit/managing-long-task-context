"""Runnable Strict lifecycle example with real temporary source materials."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from managing_long_task_context import bind_experience


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run_example() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        store_root = workspace / ".context-experience"
        original = workspace / "original.txt"
        original.write_text("workspace source\n", encoding="utf-8")
        candidate = workspace / "candidate.json"
        candidate.write_text(json.dumps({"schema": 1, "experience_id": "example-001", "revision": 1, "claim": "Check originals before relying on an experience.", "tags": ["example"], "applicability": ["A local original exists."], "exclusions": ["none-known"], "source_refs": [_ref(original)], "supersedes": None}), encoding="utf-8")
        for command in (["init"], ["record", "--input", str(candidate)]):
            completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "context_experience.py"), *command, "--workspace", str(workspace), "--store", str(store_root)], capture_output=True, text=True, check=False)
            if completed.returncode:
                raise RuntimeError(completed.stdout)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        refs: dict[str, object] = {}
        for name in ("cross", "counterexample", "effectiveness", "original-pass", "mutated-fail", "restored-pass", "mutation-hit", "representative-run", "non-applicable-run"):
            path = workspace / f"{name}.txt"
            path.write_text(f"checked {name} material\n", encoding="utf-8")
            refs[name] = _ref(path)
        common = {"checker_id": "example-host", "checker_version": "1", "validated_at": now.isoformat().replace("+00:00", "Z"), "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")}
        validation_refs = {"cross": {**common, "source_refs": [refs["cross"]], "independence_basis": "Separate reviewer and original."}, "counterexample": {**common, "source_refs": [refs["counterexample"]], "original_pass_ref": refs["original-pass"], "mutated_fail_ref": refs["mutated-fail"], "restored_pass_ref": refs["restored-pass"], "mutation_hit_ref": refs["mutation-hit"]}, "effectiveness": {**common, "source_refs": [refs["effectiveness"]], "representative_run_ref": refs["representative-run"], "non_applicable_run_ref": refs["non-applicable-run"]}}
        def evidence_checker(record, received):
            return {"status": "pass", "codes": []} if all(Path(item["path"]).read_text(encoding="utf-8").startswith("checked ") for group in received.values() for item in group["source_refs"]) else {"status": "fail", "codes": ["MATERIAL_REJECTED"]}
        store = bind_experience(workspace, store_root)
        reviewed = store.review("example-001", 1, validation_refs, evidence_checker=evidence_checker)
        before_approval = store.get("example-001", 1)["data"]
        grant = workspace / "grant.txt"
        grant.write_text("authorized by example host\n", encoding="utf-8")
        approval_ref = {"workspace_id": before_approval["workspace_id"], "experience_id": "example-001", "revision": 1, "record_digest": before_approval["record_digest"], "source_ref": _ref(grant)}
        approved = store.approve("example-001", 1, approval_ref, evidence_checker=evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []} if Path(ref["source_ref"]["path"]).read_text(encoding="utf-8").startswith("authorized") else {"status": "fail", "codes": ["APPROVAL_REJECTED"]})
        return {"review": reviewed, "approve": approved, "get": store.get("example-001", 1)}


if __name__ == "__main__":
    result = run_example()
    current = result["get"]["data"]
    assert isinstance(current, dict)
    print(json.dumps({
        "status": result["approve"]["status"],
        "experience_id": current["experience_id"],
        "revision": current["revision"],
    }, ensure_ascii=False))
