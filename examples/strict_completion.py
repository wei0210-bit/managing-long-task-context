"""Executable structured-evidence example for the public Strict API."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import managing_long_task_context as context


VERIFIER_CAPABILITY = "example:file-claim/v1"


CONTENT_CRITERION = "The result contains exactly strict completion result followed by a newline"


def make_file_claim_verifier(workspace):
    """Host-bound semantic checker, never constructed from model-supplied JSON.

    This intentionally proves only the example's exact content requirement, not
    that a business process ran or that a handwritten test report is authentic.
    """
    trusted_root = Path(workspace).resolve()

    def verify_file_claim(evidence, criterion, resolution):
        if criterion.get("criterion") != CONTENT_CRITERION:
            return {"status": "unknown", "codes": ["UNSUPPORTED_CONTENT_CRITERION"]}
        required_revision = criterion.get("required_revision")
        if required_revision is not None:
            actual = subprocess.run(
                ["git", "-C", str(trusted_root), "rev-parse", "--verify", "HEAD"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if actual.returncode != 0 or actual.stdout.strip() != required_revision:
                return {"status": "unknown", "codes": ["WORKSPACE_REVISION_MISMATCH"]}
        path = (trusted_root / evidence["locator"].split("#", 1)[0]).resolve()
        if trusted_root not in path.parents:
            return {"status": "unknown", "codes": ["WORKSPACE_MISMATCH"]}
        # Read only the small artifact this checker understands. Missing or
        # unreadable evidence is normalized by the caller's evidence evaluator.
        with path.open("rb") as stream:
            content = stream.read(4097)
        if content == b"strict completion result\n":
            return {"status": "pass", "codes": ["EXACT_CONTENT_VERIFIED"]}
        if content == b"strict completion result: FAILED\n":
            return {"status": "fail", "codes": ["CONTENT_REQUIREMENT_VIOLATED"]}
        return {"status": "unknown", "codes": ["UNRELATED_OR_INCOMPLETE_CONTENT"]}

    return verify_file_claim


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
            "required_capabilities": ["evidence-handlers/v1"],
            "evidence_handlers": {
                "schema": "evidence-handlers/v1",
                "types": {
                    "file": {
                        "resolver_capability": "builtin:file/v1",
                        "verifier_capability": VERIFIER_CAPABILITY,
                    }
                },
            },
            "workspace_root": str(workspace),
            "acceptance_criteria": [
                {
                    "id": "AC-01",
                    "criterion": CONTENT_CRITERION,
                    "required_evidence_types": ["file"],
                    "required_scope": {"module": "docs-example", "contract_version": 1},
                    "max_evidence_age_seconds": 3600,
                    "required_hops": ["artifact-created"],
                    "required_hops_mode": "single-evidence-ordered",
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
        runtime_verifiers = {
            "file": {
                "capability": VERIFIER_CAPABILITY,
                "handler": make_file_claim_verifier(workspace),
            }
        }
        release = context.gate(
            "DOC-EXAMPLE",
            stage="release",
            verifiers=runtime_verifiers,
            base_dir=base_dir,
            emit=False,
        )
        if not release["passed"]:
            return release
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
                            "scope": {"module": "docs-example", "contract_version": 1},
                            "contract_version": 1,
                            "covered_hops": ["artifact-created"],
                        }
                    ],
                    "delivery_receipts": [],
                }
            },
            verifiers=runtime_verifiers,
            base_dir=base_dir,
            emit=False,
        )


if __name__ == "__main__":
    result = run_example()
    if not result["passed"]:
        raise SystemExit(result["errors"])
