"""Executable structured-evidence example for the public Strict API."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import managing_long_task_context as context


def verify_file_claim(evidence, criterion, resolution):
    """Bind a resolver-passing file to this example's acceptance criterion."""

    expected_scope = criterion.get("required_scope", {})
    actual_scope = evidence.get("scope", {})
    supports_claim = all(actual_scope.get(key) == value for key, value in expected_scope.items())
    return {
        "status": "pass" if supports_claim else "fail",
        "codes": [] if supports_claim else ["CLAIM_SCOPE_MISMATCH"],
    }


def run_example():
    with tempfile.TemporaryDirectory() as temporary_dir:
        root = Path(temporary_dir)
        workspace = root / "workspace"
        workspace.mkdir()
        artifact = workspace / "result.txt"
        content = b"strict completion result\n"
        artifact.write_bytes(content)
        base_dir = root / ".prime" / "context"
        contract = {
            "schema": 1,
            "task_id": "DOC-EXAMPLE",
            "version": 1,
            "issued_by": "task-publisher",
            "issued_at": "2026-08-27T04:00:00Z",
            "authorized_approvers": [],
            "objective": "Demonstrate resolver-backed completion",
            "scope": ["documentation example"],
            "out_of_scope": [],
            "constraints": ["offline only"],
            "workspace_root": str(workspace),
            "acceptance_criteria": [
                {
                    "id": "AC-01",
                    "criterion": "The result artifact exists and matches its digest",
                    "required_evidence_types": ["file"],
                    "required_scope": {"module": "docs-example"},
                    "max_evidence_age_seconds": 3600,
                    "required_hops": ["artifact-created"],
                    "required_delivery_types": [],
                    "independent_validation_required": False,
                }
            ],
        }
        context.publish_contract(
            contract,
            confirmed_by="task-publisher",
            base_dir=base_dir,
        )
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return context.gate(
            "DOC-EXAMPLE",
            stage="completion",
            evidence_map={
                "AC-01": {
                    "evidence": [
                        {
                            "evidence_id": "EV-DOC-001",
                            "kind": "file",
                            "locator": "result.txt#complete-artifact",
                            "artifact_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                            "generated_at": generated_at,
                            "scope": {"module": "docs-example"},
                            "covered_hops": ["artifact-created"],
                        }
                    ],
                    "delivery_receipts": [],
                }
            },
            verifiers={"file": verify_file_claim},
            base_dir=base_dir,
            emit=False,
        )


if __name__ == "__main__":
    result = run_example()
    if not result["passed"]:
        raise SystemExit(result["errors"])
