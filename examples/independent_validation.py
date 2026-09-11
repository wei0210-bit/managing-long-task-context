"""Run synthetic valid and blocked independent-validation public API cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import tempfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

import managing_long_task_context as context


def run_example() -> dict[str, object]:
    """Return fixture-registry pass, unknown-reference, and no-resolver outcomes."""
    with tempfile.TemporaryDirectory() as temporary_dir:
        root = Path(temporary_dir)
        workspace = root / "workspace"
        workspace.mkdir()
        content = b"synthetic independently checked artifact\n"
        artifact = workspace / "result.txt"
        artifact.write_bytes(content)
        base_dir = root / ".prime" / "context"
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat().replace("+00:00", "Z")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        contract = {
            "schema": 1,
            "task_id": "INDEPENDENT-EXAMPLE",
            "version": 1,
            "issued_by": "synthetic-publisher",
            "issued_at": generated_at,
            "authorized_approvers": [],
            "objective": "Exercise the local independent-validation boundary",
            "scope": ["synthetic example"],
            "out_of_scope": ["host authentication"],
            "constraints": ["offline only"],
            "workspace_root": str(workspace),
            "actor_roles": {
                "synthetic-executor": ["executor"],
                "synthetic-validator": ["validator"],
            },
            "acceptance_criteria": [{
                "id": "AC-01",
                "criterion": "Synthetic artifact is independently checked",
                "required_evidence": ["file"],
                "required_scope": {"example": "independent-validation"},
                "independent_validation_required": True,
            }],
        }
        evidence_map = {"AC-01": {
            "validation_ref": "synthetic-host-run-01",
            "evidence": [{
                "evidence_id": "EV-01", "kind": "file", "locator": "result.txt",
                "artifact_digest": digest, "generated_at": generated_at,
                "scope": {"example": "independent-validation"},
            }],
        }}
        context.publish_contract(
            contract, confirmed_by="synthetic-publisher", base_dir=base_dir,
            independent_validation_required=True,
        )

        # This fixture is a host-owned registry, not an identity adapter. It reads
        # the artifact, binds a one-time sealed receipt, then exposes lookup only.
        if artifact.read_bytes() != content:
            raise RuntimeError("synthetic host content check failed")
        sealed = json.loads((base_dir / "INDEPENDENT-EXAMPLE" / "task-contract.json").read_text())
        receipt_registry = {"synthetic-host-run-01": {
            "validation_ref": "synthetic-host-run-01",
            "task_id": "INDEPENDENT-EXAMPLE",
            "criterion_id": "AC-01",
            "contract_digest": sealed["seal"]["integrity_digest"],
            "workspace_root": str(workspace.resolve()),
            "executor_principals": ["synthetic-executor"],
            "validator_principal": "synthetic-validator",
            "run_id": "synthetic-host-run-01",
            "checker_id": "synthetic-host-checker-01",
            "validated_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "evidence_digests": {"EV-01": digest},
            "repo_revision": None,
            "check_result": "pass",
        }}

        def resolver(validation_ref: object) -> dict[str, object]:
            if not isinstance(validation_ref, str) or validation_ref not in receipt_registry:
                raise LookupError("unknown synthetic host receipt reference")
            return dict(receipt_registry[validation_ref])

        def verifier(evidence: dict[str, object], *_: object) -> dict[str, object]:
            actual = (workspace / str(evidence["locator"])).read_bytes()
            return {"status": "pass", "codes": []} if actual == content else {
                "status": "fail", "codes": ["SYNTHETIC_CONTENT_REJECTED"],
            }

        valid = context.gate(
            "INDEPENDENT-EXAMPLE", stage="completion", evidence_map=evidence_map,
            base_dir=base_dir, emit=False, independent_validation_required=True,
            validation_resolver=resolver, verifiers={"file": verifier},
        )
        unknown_ref_map = {"AC-01": {**evidence_map["AC-01"], "validation_ref": "unknown-ref"}}
        unknown_ref = context.gate(
            "INDEPENDENT-EXAMPLE", stage="completion", evidence_map=unknown_ref_map,
            base_dir=base_dir, emit=False, independent_validation_required=True,
            validation_resolver=resolver, verifiers={"file": verifier},
        )
        blocked = context.gate(
            "INDEPENDENT-EXAMPLE", stage="completion", evidence_map=evidence_map,
            base_dir=base_dir, emit=False, independent_validation_required=True,
            verifiers={"file": verifier},
        )
        return {
            "valid_passed": valid["passed"],
            "valid_assurance": valid["criteria"]["AC-01"]["independent_validation"]["assurance"],
            "unknown_ref_passed": unknown_ref["passed"],
            "unknown_ref_code": unknown_ref["criteria"]["AC-01"]["independent_validation"]["codes"][0],
            "blocked_passed": blocked["passed"],
            "blocked_code": blocked["criteria"]["AC-01"]["independent_validation"]["codes"][0],
        }


if __name__ == "__main__":
    result = run_example()
    expected = {
        "valid_passed": True,
        "valid_assurance": "verified",
        "unknown_ref_passed": False,
        "unknown_ref_code": "VALIDATION_RESOLVER_ERROR",
        "blocked_passed": False,
        "blocked_code": "MISSING_TRUSTED_VALIDATION_RESOLVER",
    }
    if result != expected:
        raise SystemExit(result)
    print(json.dumps(result, sort_keys=True))
