"""Run an approved, current experience rule through the public Strict gate."""

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

import managing_long_task_context as context


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _cli(*arguments: str) -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "context_experience.py"), *arguments], capture_output=True, check=False, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout)


def run_example() -> dict[str, object]:
    with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
        root = Path(temporary_dir)
        workspace = root / "workspace"
        workspace.mkdir()
        store_root = workspace / ".context-experience"
        original = workspace / "original.txt"
        original.write_text("current original rule\n", encoding="utf-8")
        candidate = workspace / "candidate.json"
        candidate.write_text(json.dumps({
            "schema": 1, "experience_id": "current-original", "revision": 1,
            "claim": "Read the current original before relying on the selected rule.",
            "tags": ["verification"], "applicability": ["Local original exists."],
            "exclusions": ["none-known"], "source_refs": [_ref(original)], "supersedes": None,
        }), encoding="utf-8")
        _cli("init", "--workspace", str(workspace), "--store", str(store_root))
        _cli("record", "--workspace", str(workspace), "--store", str(store_root), "--input", str(candidate))

        now = datetime.now(timezone.utc).replace(microsecond=0)
        materials: dict[str, dict[str, str]] = {}
        for name in ("cross", "counterexample", "effectiveness", "original-pass", "mutated-fail", "restored-pass", "mutation-hit", "representative-run", "non-applicable-run"):
            path = workspace / f"{name}.txt"
            path.write_text(f"verified {name}\n", encoding="utf-8")
            materials[name] = _ref(path)
        common = {"checker_id": "example-host", "checker_version": "1", "validated_at": now.isoformat().replace("+00:00", "Z"), "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")}
        validation_refs = {
            "cross": {**common, "source_refs": [materials["cross"]], "independence_basis": "Separate reviewer."},
            "counterexample": {**common, "source_refs": [materials["counterexample"]], "original_pass_ref": materials["original-pass"], "mutated_fail_ref": materials["mutated-fail"], "restored_pass_ref": materials["restored-pass"], "mutation_hit_ref": materials["mutation-hit"]},
            "effectiveness": {**common, "source_refs": [materials["effectiveness"]], "representative_run_ref": materials["representative-run"], "non_applicable_run_ref": materials["non-applicable-run"]},
        }

        def evidence_checker(record: object, refs: dict[str, object]) -> dict[str, object]:
            del record
            proof_refs = [item for group in refs.values() for item in group["source_refs"]]
            return {"status": "pass", "codes": []} if all(Path(item["path"]).read_text(encoding="utf-8").startswith("verified ") for item in proof_refs) else {"status": "fail", "codes": ["MATERIAL_REJECTED"]}

        store = context.bind_experience(workspace, store_root)
        if store.review("current-original", 1, validation_refs, evidence_checker=evidence_checker)["status"] != "pass":
            raise RuntimeError("review did not validate")
        current = store.get("current-original", 1)["data"]
        assert isinstance(current, dict)
        grant = workspace / "grant.txt"
        grant.write_text("approved by host\n", encoding="utf-8")
        approval_ref = {"workspace_id": current["workspace_id"], "experience_id": "current-original", "revision": 1, "record_digest": current["record_digest"], "source_ref": _ref(grant)}
        if store.approve("current-original", 1, approval_ref, evidence_checker=evidence_checker, approval_checker=lambda record, reference: {"status": "pass", "codes": []} if Path(reference["source_ref"]["path"]).read_text(encoding="utf-8").startswith("approved ") else {"status": "fail", "codes": ["APPROVAL_REJECTED"]})["status"] != "pass":
            raise RuntimeError("approval did not pass")

        evidence = workspace / "execution.txt"
        evidence.write_text("checked current original\n", encoding="utf-8")
        source_ref = _ref(evidence)
        contract = {
            "schema": 1, "task_id": "EXPERIENCE-RULE-EXAMPLE", "version": 1,
            "issued_by": "publisher", "issued_at": "2026-09-07T00:00:00Z", "authorized_approvers": [],
            "objective": "Execute an approved experience rule", "scope": ["example"], "out_of_scope": [], "constraints": ["offline only"],
            "acceptance_criteria": [{"id": "AC-01", "criterion": "gate runs", "required_evidence_types": ["test-report"]}],
            "workspace_root": str(workspace), "required_capabilities": ["rule-execution/v1"],
            "rule_execution": {"schema": 1, "rules": [{"rule_id": "current-original-required", "experience_ref": {"experience_id": "current-original", "revision": 1, "store_root": str(store_root)}, "severity": "load-bearing", "applies_at": ["handoff"], "trigger_id": "controlled-modification", "checker_id": "original-check", "checker_version": "1", "observation_source_id": "workspace-observer"}]},
        }
        base_dir = root / ".prime" / "context"
        context.publish_contract(contract, confirmed_by="publisher", base_dir=base_dir)
        context.checkpoint("EXPERIENCE-RULE-EXAMPLE", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)

        def observe(task: str, stage: str, source: str) -> dict[str, object]:
            del task, stage, source
            observed = datetime.now(timezone.utc)
            return {"status": "pass", "codes": [], "coverage": "complete", "scope": "controlled modification", "observed_at": observed.isoformat(), "expires_at": (observed + timedelta(minutes=5)).isoformat(), "source_refs": [source_ref], "payload": {"controlled_modification": True}}

        def verify_experience(reference: dict[str, object]) -> dict[str, object]:
            selected = context.bind_experience(workspace, Path(str(reference["store_root"]))).get(str(reference["experience_id"]), int(reference["revision"]))["data"]
            if not isinstance(selected, dict):
                return {"status": "fail", "codes": ["EXPERIENCE_UNAVAILABLE"]}
            source = Path(selected["source_refs"][0]["path"])
            return {"status": "pass", "codes": []} if source.read_text(encoding="utf-8") == "current original rule\n" and selected["claim"] == "Read the current original before relying on the selected rule." else {"status": "fail", "codes": ["EXPERIENCE_SEMANTICS_REJECTED"]}

        return context.gate("EXPERIENCE-RULE-EXAMPLE", stage="handoff", base_dir=base_dir, emit=False, rule_runtime={"observe": observe, "applies": lambda rule, observation: {"status": "applicable", "codes": [], "source_refs": [source_ref]}, "check": lambda rule, observation: {"status": "pass", "codes": []} if evidence.read_text(encoding="utf-8") == "checked current original\n" else {"status": "fail", "codes": ["ORIGINAL_UNREAD"]}, "verify_experience": verify_experience})


if __name__ == "__main__":
    print(run_example())
