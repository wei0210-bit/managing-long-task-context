"""Synthetic public-boundary fixtures for the E1-04 gate-combination matrix.

This is deliberately not a TestCase module.  The fixture owns a fresh local
workspace per case and makes each host callback read the real fixture files.
It never represents a Codex/Claude host or a production business action.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import unquote, urlsplit

import managing_long_task_context as context


UNSET = object()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_zulu(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MatrixAuthority:
    """An in-process registered host authority with an opaque identity token."""

    def __init__(self, fixture: "HandoffGateFixture", identity: object, purpose: str) -> None:
        self.fixture = fixture
        self.identity = identity
        self.purpose = purpose

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        fixture = self.fixture
        if request.get("runtime_identity") is not self.identity:
            return {"status": "unknown"}
        arguments = request.get("arguments")
        if not isinstance(arguments, dict) or request.get("arguments_sha256") != canonical_sha256(arguments):
            return {"status": "unknown"}
        expected = {
            "operation": f"{self.purpose}_handoff",
            "task_id": fixture.task_id,
            "base_dir": str(fixture.base_dir.resolve()),
            "workspace_root": str(fixture.workspace.resolve()),
            "package_manifest_sha256": fixture.package_digest,
            "contract_version": 1,
            "contract_digest": fixture.contract_digest,
            "controller_generation": 0,
            "handoff_id": fixture.handoff_id,
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "unknown"}
        source, target = fixture.references["source"], fixture.references["target"]
        result = {
            "status": "pass", **expected, "arguments_sha256": canonical_sha256(arguments),
            "purpose": self.purpose, "subject_id": f"synthetic:{self.purpose}:controller",
            "subject_session_ref": deepcopy(target if self.purpose == "activate" else source),
            "role": "controller", "scope_digest": "a" * 64, "work_item_id": None,
            "source_session_ref": deepcopy(source), "target_session_ref": deepcopy(target),
            "authorization_ref": deepcopy(fixture.references["authorization"]),
            "target_activation_status": "not_activated",
            "observed_at": as_zulu(fixture.now - timedelta(seconds=1)),
            "expires_at": as_zulu(fixture.now + timedelta(minutes=10)),
        }
        # The prospective prepare has no already-active controller to bind; the
        # protocol's exact authorizer shape deliberately omits this field there.
        if self.purpose == "prepare":
            result.pop("subject_session_ref")
        return result


class MatrixVerifier:
    """Reads every referenced file and can change basis only after that read."""

    def __init__(self, fixture: "HandoffGateFixture") -> None:
        self.fixture = fixture
        self.change_after_read = False
        self.calls = 0

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        fixture = self.fixture
        self.calls += 1
        references = [
            fixture.references["source"], fixture.references["target"],
            fixture.references["authorization"], fixture.references["basis"],
            fixture.references["artifacts"],
        ]
        for reference in references:
            path = Path(unquote(urlsplit(reference["uri"]).path))
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                return {"status": "fail", "identity_status": "pass", "authorization_status": "pass", "content_status": "fail"}
            if content != fixture.reference_content[reference["ref_id"]]:
                return {"status": "fail", "identity_status": "pass", "authorization_status": "pass", "content_status": "fail"}
        expected = {
            "task_id": fixture.task_id, "handoff_id": fixture.handoff_id,
            "record_sha256": canonical_sha256(fixture.record), "contract_version": 1,
            "contract_digest": fixture.contract_digest, "workspace_root": str(fixture.workspace.resolve()),
            "package_manifest_sha256": fixture.package_digest, "controller_generation": 0,
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail", "identity_status": "fail", "authorization_status": "fail", "content_status": "fail"}
        # This is intentionally after all semantic reads, but before the caller
        # can commit activation.  It targets the same bearing basis used by the
        # handoff record, completion evidence, truth source, and rule runtime.
        if self.change_after_read:
            fixture.basis_path.write_text("business proof changed after handoff verification\n", encoding="utf-8")
            self.change_after_read = False
        return {
            "status": "pass", "identity_status": "pass", "authorization_status": "pass",
            "content_status": "pass", **expected, "verification_refs": deepcopy(references),
            "observed_at": as_zulu(fixture.now - timedelta(seconds=1)),
            "expires_at": as_zulu(fixture.now + timedelta(minutes=10)),
        }


class HandoffGateFixture:
    """One real-filesystem instance of a selected E1-04 three-switch row."""

    def __init__(self, *, truth_sources: bool, rule_execution: bool, independent_validation: bool) -> None:
        self.truth_sources = truth_sources
        self.rule_execution = rule_execution
        self.independent_validation = independent_validation
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        root = Path(self.temporary.name)
        self.base_dir = root / "context"
        self.workspace = root / "workspace"
        self.package = root / "package"
        self.workspace.mkdir()
        self.package.mkdir()
        (self.package / "skill-manifest.json").write_text("synthetic e1-04 package\n", encoding="utf-8")
        self.package_digest = file_sha256(self.package / "skill-manifest.json")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.task_id = "E1-04-MATRIX"
        self.handoff_id = "HO-E1-04-MATRIX"
        # E0's frozen input starts at 7.  This isolated product fixture starts
        # at 0, so each test asserts the same expected generation *delta*.
        self.initial_generation = 0
        self.basis_path = self.workspace / "basis.txt"
        self.reference_content = {
            "source": "source controller is synthetic and distinct\n",
            "target": "target controller is synthetic and distinct\n",
            "authorization": "synthetic scope permits only handoff activation\n",
            "basis": "business proof: controlled handoff basis accepted\n",
            "artifacts": "synthetic artifact manifest\n",
        }
        for ref_id, content in self.reference_content.items():
            (self.workspace / f"{ref_id}.txt").write_text(content, encoding="utf-8")
        self.basis_digest = file_sha256(self.basis_path)
        self.references = {ref_id: self._reference(ref_id) for ref_id in self.reference_content}
        self.published = context.publish_contract(
            self.contract(), confirmed_by="publisher", base_dir=self.base_dir,
            independent_validation_required=True if independent_validation else None,
        )
        self.contract_digest = self.published["seal"]["integrity_digest"].removeprefix("sha256:")
        if self.truth_sources:
            context.observe_truth_source(
                self.task_id, source_id="TS-BASIS", actor="publisher",
                verification_refs=["synthetic:e1-04:source-readback"], base_dir=self.base_dir,
            )
        cursor = json.loads((self.base_dir / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
        self.record: dict[str, object] = {
            "protocol": "short-session-handoff/v1", "task_id": self.task_id,
            "contract_version": 1, "contract_digest": self.contract_digest,
            "workspace_root": str(self.workspace.resolve()), "package_manifest_sha256": self.package_digest,
            "handoff_id": self.handoff_id, "request_id": "REQ-E1-04-PREPARE", "controller_generation": 0,
            "source_session_ref": self.references["source"], "target_session_ref": self.references["target"],
            "authorization_ref": self.references["authorization"], "basis_refs": [self.references["basis"]],
            "artifact_manifest_ref": self.references["artifacts"],
            "created_at": as_zulu(self.now), "event_cursor": cursor,
        }
        self.verifier = MatrixVerifier(self)
        self.prepare_identity, self.activate_identity = object(), object()
        self.validation_reads = 0

    def close(self) -> None:
        self.temporary.cleanup()

    def _reference(self, ref_id: str) -> dict[str, str]:
        path = self.workspace / f"{ref_id}.txt"
        return {"ref_id": ref_id, "task_id": self.task_id, "uri": path.as_uri(), "sha256": file_sha256(path)}

    def contract(self) -> dict[str, object]:
        criterion: dict[str, object] = {
            "id": "AC-BUSINESS", "criterion": "The actual synthetic business proof is current",
            "required_evidence_types": ["file"],
            "required_scope": {"task_id": self.task_id, "criterion_id": "AC-BUSINESS"},
        }
        if self.independent_validation:
            criterion["independent_validation_required"] = True
        contract: dict[str, object] = {
            "schema": 1, "task_id": self.task_id, "version": 1, "issued_by": "publisher",
            "issued_at": as_zulu(self.now - timedelta(seconds=1)), "authorized_approvers": [],
            "objective": "Synthetic E1-04 three-switch handoff matrix", "scope": ["isolated synthetic host"],
            "out_of_scope": ["production host", "business action"], "constraints": ["no business action"],
            "workspace_root": str(self.workspace.resolve()), "acceptance_criteria": [criterion],
            "actor_roles": {"executor-principal": ["executor"], "validator-principal": ["validator"]},
        }
        capabilities: list[str] = []
        if self.truth_sources:
            capabilities.append("truth-sources/v1")
            contract["truth_sources"] = {
                "schema": "truth-sources/v1", "items": [{
                    "id": "TS-BASIS", "purpose": "Current bearing handoff basis",
                    "source_ref": {"kind": "file", "locator": "basis.txt"}, "owner": "publisher",
                    "max_age_seconds": 3600, "validation_method": "owner-readback",
                    "invalidate_on_change_kinds": ["implementation-change"],
                }],
            }
        if self.rule_execution:
            capabilities.append("rule-execution/v1")
            contract["rule_execution"] = {"schema": 1, "rules": [{
                "rule_id": "bearing-basis-semantic-check", "experience_ref": None,
                "severity": "load-bearing", "applies_at": ["completion"],
                "trigger_id": "handoff-basis", "checker_id": "synthetic-basis-reader",
                "checker_version": "1", "observation_source_id": "synthetic-basis-file",
            }]}
        if capabilities:
            contract["required_capabilities"] = capabilities
        return contract

    def prepare(self) -> dict[str, object]:
        result = context.prepare_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-E1-04-PREPARE", controller_generation=0, record=self.record,
            runtime_identity=self.prepare_identity,
            write_authorizer=MatrixAuthority(self, self.prepare_identity, "prepare"), handoff_verifier=self.verifier,
        )
        return result

    def activate(self) -> dict[str, object]:
        return context.activate_handoff(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace, package_root=self.package,
            request_id="REQ-E1-04-ACTIVATE", controller_generation=0, handoff_id=self.handoff_id,
            runtime_identity=self.activate_identity,
            write_authorizer=MatrixAuthority(self, self.activate_identity, "activate"), handoff_verifier=self.verifier,
        )

    def evidence_map(self) -> dict[str, object]:
        return {"AC-BUSINESS": {"validation_ref": "synthetic-independent-run", "evidence": [{
            "evidence_id": "EV-BASIS", "kind": "file", "locator": "basis.txt",
            "artifact_digest": "sha256:" + self.basis_digest,
            "scope": {"task_id": self.task_id, "criterion_id": "AC-BUSINESS"},
            "generated_at": as_zulu(self.now),
        }]}}

    def file_verifier(self, evidence: dict[str, object], *_args: object) -> dict[str, object]:
        locator = evidence.get("locator")
        if locator != "basis.txt":
            return {"status": "fail", "codes": ["UNEXPECTED_FIXTURE_LOCATOR"]}
        try:
            text = self.basis_path.read_text(encoding="utf-8")
        except OSError:
            return {"status": "fail", "codes": ["BASIS_UNREADABLE"]}
        return ({"status": "pass", "codes": []}
                if text == self.reference_content["basis"] and "business proof" in text
                else {"status": "fail", "codes": ["BASIS_SEMANTIC_REJECTED"]})

    def validation_resolver(self, validation_ref: object) -> dict[str, object]:
        self.validation_reads += 1
        # A trusted synthetic host must really inspect the bearing file before it
        # issues the receipt; the returned digest is bound to the inspected bytes.
        if validation_ref != "synthetic-independent-run" or self.basis_path.read_text(encoding="utf-8") != self.reference_content["basis"]:
            return {"check_result": "fail"}
        return {
            "validation_ref": validation_ref, "task_id": self.task_id, "criterion_id": "AC-BUSINESS",
            "contract_digest": self.published["seal"]["integrity_digest"],
            "workspace_root": str(self.workspace.resolve()),
            "executor_principals": ["executor-principal"], "validator_principal": "validator-principal",
            "run_id": "synthetic-independent-run-001", "checker_id": "synthetic-real-file-reader",
            "validated_at": as_zulu(self.now - timedelta(seconds=1)), "expires_at": as_zulu(self.now + timedelta(minutes=10)),
            "evidence_digests": {"EV-BASIS": "sha256:" + file_sha256(self.basis_path)},
            "repo_revision": None, "check_result": "pass",
        }

    def rule_runtime(self) -> dict[str, object]:
        source_ref = {"path": str(self.basis_path.resolve()), "sha256": self.basis_digest}

        def observe(task_id: str, stage: str, source_id: str) -> dict[str, object]:
            if task_id != self.task_id or stage != "completion" or source_id != "synthetic-basis-file":
                return {"status": "fail", "codes": ["WRONG_RULE_CONTEXT"], "coverage": "complete", "scope": "wrong", "observed_at": as_zulu(self.now), "expires_at": as_zulu(self.now + timedelta(minutes=10)), "source_refs": [], "payload": {}}
            return {"status": "pass", "codes": [], "coverage": "complete", "scope": "bearing handoff basis",
                    "observed_at": as_zulu(self.now - timedelta(seconds=1)), "expires_at": as_zulu(self.now + timedelta(minutes=10)),
                    "source_refs": [source_ref], "payload": {"basis_present": self.basis_path.exists()}}

        def applies(_rule: dict[str, object], _observation: dict[str, object]) -> dict[str, object]:
            return {"status": "applicable", "codes": [], "source_refs": [source_ref]}

        def check(_rule: dict[str, object], _observation: dict[str, object]) -> dict[str, object]:
            return ({"status": "pass", "codes": []}
                    if self.basis_path.read_text(encoding="utf-8") == self.reference_content["basis"]
                    else {"status": "fail", "codes": ["BASIS_RULE_REJECTED"]})

        return {"observe": observe, "applies": applies, "check": check}

    def completion(self, *, evidence_map: dict[str, object] | None = None, validation_resolver: object = UNSET) -> dict[str, object]:
        resolver = (
            self.validation_resolver if validation_resolver is UNSET and self.independent_validation
            else None if validation_resolver is UNSET else validation_resolver
        )
        return context.gate(
            self.task_id, stage="completion", evidence_map=self.evidence_map() if evidence_map is None else evidence_map, base_dir=self.base_dir,
            emit=False, verifiers={"file": self.file_verifier}, rule_runtime=self.rule_runtime() if self.rule_execution else None,
            independent_validation_required=True if self.independent_validation else None,
            validation_resolver=resolver,
        )

    def status(self) -> dict[str, object]:
        return context.handoff_status(
            self.task_id, base_dir=self.base_dir, workspace_root=self.workspace,
            package_root=self.package, handoff_id=self.handoff_id, handoff_verifier=self.verifier,
        )

    def control_events(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in (self.base_dir / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def block_business_completion(self) -> None:
        context.record(
            self.task_id, statement="synthetic business work remains blocked", item_type="observation",
            actor="publisher", source="synthetic-e1-04", base_dir=self.base_dir, metadata={"blocking": True},
        )
