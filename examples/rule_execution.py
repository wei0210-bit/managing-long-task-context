"""Run one opt-in selected rule through the public Strict handoff gate."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


def run_example() -> dict[str, object]:
    with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
        temporary_root = Path(temporary_dir)
        workspace = temporary_root / "workspace"
        workspace.mkdir()
        evidence = workspace / "dispatch-proof.txt"
        evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
        source_ref = {
            "path": str(evidence.resolve()),
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
        base_dir = temporary_root / ".prime" / "context"
        context.publish_contract({
            "schema": 1, "task_id": "RULE-EXAMPLE", "version": 1,
            "issued_by": "publisher", "issued_at": "2026-09-07T00:00:00Z",
            "authorized_approvers": [], "workspace_root": str(workspace),
            "required_capabilities": ["rule-execution/v1"],
            "objective": "Run a selected rule", "scope": ["example"],
            "out_of_scope": [], "constraints": ["offline only"],
            "acceptance_criteria": [{"id": "AC-01", "criterion": "Gate runs", "required_evidence_types": ["test-report"]}],
            "rule_execution": {"schema": 1, "rules": [{
                "rule_id": "dispatch-required", "experience_ref": None,
                "severity": "load-bearing", "applies_at": ["handoff"],
                "trigger_id": "controlled-modification", "checker_id": "dispatch-proof",
                "checker_version": "1", "observation_source_id": "workspace-observer",
            }]},
        }, confirmed_by="publisher", base_dir=base_dir)
        context.checkpoint("RULE-EXAMPLE", phase="handoff", completed=[], evidence_added=[], next_action="review", actor="publisher", base_dir=base_dir)

        def observe(task: str, stage: str, source_id: str) -> dict[str, object]:
            now = datetime.now(timezone.utc)
            return {"status": "pass", "codes": [], "coverage": "complete", "scope": "controlled modification", "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(), "source_refs": [source_ref], "payload": {"controlled_modification": True}}

        def applies(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
            return {"status": "applicable", "codes": [], "source_refs": [source_ref]}

        def check(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
            return {"status": "pass" if evidence.read_text(encoding="utf-8") == "controlled change was dispatched\n" else "fail", "codes": []}

        return context.gate("RULE-EXAMPLE", stage="handoff", base_dir=base_dir, emit=False, rule_runtime={"observe": observe, "applies": applies, "check": check})


if __name__ == "__main__":
    print(run_example())
