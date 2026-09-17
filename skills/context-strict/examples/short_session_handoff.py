"""Run a local synthetic short-session handoff without a host adapter or business action.

The activation flow is gated by the packaged Strict-only preflight and reports the three
migration results separately.  A manual fallback run recovers information only.  Nothing
here archives a session or creates a v2 receipt.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import managing_long_task_context as context


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PLAN = "docs/superpowers/plans/synthetic-migration-plan.md"
CATEGORIES = ("objective", "current_state", "constraints", "next_action", "unresolved_risks")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _reference(task_id: str, reference_id: str, path: Path) -> dict[str, str]:
    return {
        "ref_id": reference_id,
        "task_id": task_id,
        "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _zulu(value: datetime) -> str:
    return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _full_package_check() -> bool:
    """Do the complete manifest content check before creating any local task state."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
    completed = subprocess.run(
        [
            sys.executable, str(PACKAGE_ROOT / "scripts" / "context_doctor.py"),
            "check", "--mode", "full", "--package-root", str(PACKAGE_ROOT),
        ],
        cwd=PACKAGE_ROOT, env=environment, text=True, capture_output=True, timeout=30,
    )
    if completed.returncode != 0:
        return False
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False
    return report.get("status") == "pass" and report.get("full_verification") == "pass"


def _git(workspace: Path, *arguments: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "synthetic",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid", "GIT_COMMITTER_NAME": "synthetic",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    })
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments], cwd=workspace, env=environment,
        text=True, capture_output=True, check=True, timeout=30,
    ).stdout.strip()


def _authoritative_workspace(workspace: Path) -> dict[str, str]:
    """Commit a plan, then one AUTHORITATIVE_NOW entry whose verified commit precedes it."""
    _git(workspace, "init", "-q")
    plan = workspace / PLAN
    plan.parent.mkdir(parents=True)
    plan.write_text("---\nstatus: synthetic\nimplementation_authorized: true\n---\n# Synthetic plan\n", encoding="utf-8")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "verified synthetic baseline")
    verified = _git(workspace, "rev-parse", "HEAD")
    plan_sha256 = hashlib.sha256(plan.read_bytes()).hexdigest()
    manifest_sha256 = hashlib.sha256((PACKAGE_ROOT / "skill-manifest.json").read_bytes()).hexdigest()
    (workspace / "CONTEXT.md").write_text("\n".join([
        "---", "authority: AUTHORITATIVE_NOW", f"plan_path: {PLAN}", f"plan_sha256: {plan_sha256}",
        f"package_manifest_sha256: {manifest_sha256}", f"baseline_head: {verified}",
        f"implementation_head: {verified}", f"verified_head: {verified}", "verified_at: 2026-09-17T00:00:00Z",
        "---", "", "# Synthetic recovery entry", "", f"- Current plan: [plan]({PLAN})", "",
    ]), encoding="utf-8")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "recovery entry")
    return {"verified_head": verified, "plan_sha256": plan_sha256}


def _recovery_material(workspace: Path, task_id: str, plan_sha256: str) -> dict[str, str]:
    """Source handoff and checklist; the target writes its readback only after reading them."""
    material = workspace / "handoff-material"
    material.mkdir()
    handoff = material / "handoff.md"
    handoff.write_text("# Synthetic handoff\nobjective, state, constraints, next action, risks\n", encoding="utf-8")
    handoff_sha256 = hashlib.sha256(handoff.read_bytes()).hexdigest()
    facts = [
        {"fact_id": f"F-{index}", "category": category, "value": f"synthetic {category}", "source_ref": f"handoff.md#L{index}"}
        for index, category in enumerate(CATEGORIES, start=1)
    ]
    checklist = {"schema": "recovery-checklist/v1", "task_id": task_id, "handoff_sha256": handoff_sha256,
                 "plan_sha256": plan_sha256, "facts": facts}
    checklist_sha256 = _digest(dict(checklist, facts=sorted(facts, key=lambda item: item["fact_id"])))
    readback = {"schema": "recovery-readback/v1", "task_id": task_id, "handoff_sha256": handoff_sha256,
                "plan_sha256": plan_sha256, "checklist_sha256": checklist_sha256, "facts": list(reversed(facts))}
    (material / "checklist.json").write_text(json.dumps(checklist, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"handoff": str(handoff), "handoff_sha256": handoff_sha256, "checklist": str(material / "checklist.json"),
            "checklist_sha256": checklist_sha256, "readback": str(material / "readback.json"),
            "readback_text": json.dumps(readback, ensure_ascii=False, indent=2)}


def _preflight_arguments(mode: str, stage: str, *, workspace: Path, base_dir: Path, task_id: str, handoff_id: str,
                         authority: dict[str, str], material: dict[str, str]) -> list[str]:
    arguments = [
        "--mode", mode, "--stage", stage, "--package-root", str(PACKAGE_ROOT), "--workspace-root", str(workspace),
        "--task-id", task_id, "--plan", PLAN, "--expected-plan-sha256", authority["plan_sha256"],
        "--expected-verified-head", authority["verified_head"],
        "--handoff-file", material["handoff"], "--expected-handoff-sha256", material["handoff_sha256"],
        "--recovery-checklist", material["checklist"], "--expected-checklist-sha256", material["checklist_sha256"],
    ]
    if mode == "strict_protocol":
        arguments += ["--context-root", str(base_dir), "--handoff-id", handoff_id]
    if stage != "prepare":
        arguments += ["--recovery-readback", material["readback"]]
    return arguments


def _load_preflight() -> object:
    scripts = str(PACKAGE_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("handoff_preflight", PACKAGE_ROOT / "scripts" / "handoff_preflight.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _results(outcome: dict[str, object]) -> dict[str, object]:
    """Three separate results; there is deliberately no single migration-success value."""
    information, control, retirement = (
        outcome["information_recovery"], outcome["control_transfer"], outcome["source_retirement"],
    )
    assert isinstance(information, dict) and isinstance(control, dict) and isinstance(retirement, dict)
    return {
        "information_recovery": information["status"], "control_transfer": control["status"],
        "controller_generation": control["controller_generation"], "source_retirement": retirement["status"],
        "archive_allowed": retirement["archive_allowed"],
    }


class SyntheticHost:
    """A fixed local registry that reads fixture contents before it approves anything."""

    def __init__(self, record: dict[str, object], contents: dict[str, str], identity: object, purpose: str, base_dir: Path) -> None:
        self.record = deepcopy(record)
        self.contents = dict(contents)
        self.identity = identity
        self.purpose = purpose
        self.base_dir = str(base_dir.resolve())

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        references = [
            self.record["source_session_ref"], self.record["target_session_ref"],
            self.record["authorization_ref"], *self.record["basis_refs"], self.record["artifact_manifest_ref"],
        ]
        for reference in references:
            assert isinstance(reference, dict)
            path = Path(unquote(urlsplit(reference["uri"]).path))
            if path.read_text(encoding="utf-8") != self.contents[reference["ref_id"]]:
                return {"status": "fail"}
        expected = {
            "task_id": self.record["task_id"], "handoff_id": self.record["handoff_id"],
            "record_sha256": _digest(self.record), "contract_version": self.record["contract_version"],
            "contract_digest": self.record["contract_digest"], "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "controller_generation": self.record["controller_generation"],
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "status": "pass", "identity_status": "pass", "authorization_status": "pass",
            "content_status": "pass", **expected, "verification_refs": references,
            "observed_at": _zulu(now), "expires_at": _zulu(now + timedelta(minutes=1)),
        }

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        arguments = request.get("arguments")
        expected = {
            "task_id": self.record["task_id"], "base_dir": self.base_dir,
            "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": self.record["contract_version"], "contract_digest": self.record["contract_digest"],
            "controller_generation": self.record["controller_generation"], "handoff_id": self.record["handoff_id"],
            "operation": f"{self.purpose}_handoff",
        }
        if (
            request.get("runtime_identity") is not self.identity
            or not isinstance(arguments, dict)
            or request.get("arguments_sha256") != _digest(arguments)
            or any(request.get(key) != value for key, value in expected.items())
        ):
            return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        source = self.record["source_session_ref"]
        target = self.record["target_session_ref"]
        result = {
            "status": "pass", **expected, "arguments_sha256": _digest(arguments),
            "purpose": self.purpose, "subject_id": "synthetic:registered-controller", "role": "controller",
            "scope_digest": "a" * 64, "work_item_id": None,
            "source_session_ref": deepcopy(source), "target_session_ref": deepcopy(target),
            "subject_session_ref": deepcopy(target if self.purpose == "activate" else source),
            "authorization_ref": deepcopy(self.record["authorization_ref"]), "target_activation_status": "not_activated",
            "observed_at": _zulu(now), "expires_at": _zulu(now + timedelta(minutes=1)),
        }
        if self.purpose in {"prepare", "cancel"}:
            result.pop("subject_session_ref")
        return result


def _flow(task_id: str, handoff_id: str, *, activate: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="mltc-handoff-example-") as temporary:
        root = Path(temporary).resolve()
        base_dir, workspace = root / "context", root / "workspace"
        workspace.mkdir()
        contents = {
            "source": "synthetic source controller\n", "target": "synthetic target controller\n",
            "authorization": "fixed registered authorization\n", "basis": "readable local basis\n",
            "artifacts": "synthetic artifact manifest\n",
        }
        for reference_id, text in contents.items():
            (workspace / f"{reference_id}.txt").write_text(text, encoding="utf-8")
        authority = _authoritative_workspace(workspace) if activate else None
        published = context.publish_contract({
            "schema": 1, "task_id": task_id, "version": 1, "issued_by": "synthetic-publisher",
            "issued_at": "2026-09-15T00:00:00Z", "authorized_approvers": [],
            "objective": "local synthetic handoff", "scope": ["temporary fixture"], "out_of_scope": ["business action"],
            "constraints": ["no network", "no host adapter"], "required_capabilities": ["short-session-handoff/v1"],
            "acceptance_criteria": [{"id": "AC-LOCAL", "criterion": "synthetic only", "required_evidence": ["local fixture"]}],
        }, confirmed_by="synthetic-publisher", base_dir=base_dir)
        cursor = json.loads((base_dir / task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
        references = {
            reference_id: _reference(task_id, reference_id, workspace / f"{reference_id}.txt") for reference_id in contents
        }
        record: dict[str, object] = {
            "protocol": "short-session-handoff/v1", "task_id": task_id, "contract_version": 1,
            "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
            "workspace_root": str(workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256((PACKAGE_ROOT / "skill-manifest.json").read_bytes()).hexdigest(),
            "handoff_id": handoff_id, "request_id": f"REQ-{handoff_id}-PREPARE", "controller_generation": 0,
            "source_session_ref": references["source"], "target_session_ref": references["target"],
            "authorization_ref": references["authorization"], "basis_refs": [references["basis"]],
            "artifact_manifest_ref": references["artifacts"], "created_at": "2026-09-15T00:00:01Z", "event_cursor": cursor,
        }
        identity = object()
        verifier = SyntheticHost(record, contents, identity, "prepare", base_dir)
        bound = context.bind(base_dir, workspace_root=workspace, package_root=PACKAGE_ROOT)
        gates: dict[str, object] = {}
        if activate:
            assert authority is not None
            material = _recovery_material(workspace, task_id, authority["plan_sha256"])
            preflight = _load_preflight()

            def gate(stage: str, host: object) -> dict[str, object]:
                report, _ = preflight.run_preflight(  # type: ignore[attr-defined]
                    _preflight_arguments("strict_protocol", stage, workspace=workspace, base_dir=base_dir, task_id=task_id,
                                         handoff_id=handoff_id, authority=authority, material=material),
                    handoff_verifier=host,
                )
                gates[stage] = report["preflight_status"]
                return report

            gate("prepare", None)
        prepared = bound.prepare_handoff(
            task_id,
            request_id=record["request_id"], controller_generation=0, record=record, runtime_identity=identity,
            write_authorizer=verifier, handoff_verifier=verifier,
        )
        validated = bound.validate_handoff(
            task_id,
            handoff_id=handoff_id, handoff_verifier=verifier,
        )
        if not activate:
            cancel_identity = object()
            cancel_host = SyntheticHost(record, contents, cancel_identity, "cancel", base_dir)
            cancelled = bound.cancel_handoff(
                task_id,
                request_id=f"REQ-{handoff_id}-CANCEL", controller_generation=0, handoff_id=handoff_id,
                runtime_identity=cancel_identity, write_authorizer=cancel_host, handoff_verifier=cancel_host,
            )
            return {"prepare": prepared, "validate": validated, "cancel": cancelled}
        if activate:
            Path(material["readback"]).write_text(material["readback_text"], encoding="utf-8")
        gate("activate", verifier)
        activate_identity = object()
        activate_host = SyntheticHost(record, contents, activate_identity, "activate", base_dir)
        activated = asyncio.run(context.run(
            "activate_handoff", task_id=task_id, base_dir=base_dir, workspace_root=workspace, package_root=PACKAGE_ROOT,
            request_id=f"REQ-{handoff_id}-ACTIVATE", controller_generation=0, handoff_id=handoff_id,
            runtime_identity=activate_identity, write_authorizer=activate_host, handoff_verifier=activate_host,
        ))
        event_path = base_dir / task_id / "events.jsonl"
        before_repeat = event_path.read_bytes()
        repeated = asyncio.run(context.run(
            "activate_handoff", task_id=task_id, base_dir=base_dir, workspace_root=workspace, package_root=PACKAGE_ROOT,
            request_id=f"REQ-{handoff_id}-ACTIVATE", controller_generation=0, handoff_id=handoff_id,
            runtime_identity=activate_identity, write_authorizer=activate_host, handoff_verifier=activate_host,
        ))
        after_repeat = event_path.read_bytes()
        status = bound.handoff_status(
            task_id,
            handoff_id=handoff_id, handoff_verifier=activate_host,
        )
        activation_events = sum(
            json.loads(line)["event_type"] == "handoff_activated"
            for line in after_repeat.decode("utf-8").splitlines()
        )
        strict_report = gate("status", activate_host)
        manual = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "scripts" / "handoff_preflight.py"),
             *_preflight_arguments("manual_fallback", "recovery", workspace=workspace, base_dir=base_dir, task_id=task_id,
                                   handoff_id=handoff_id, authority=authority, material=material)],
            cwd=root, env={**os.environ, "PYTHONPATH": str(PACKAGE_ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            text=True, capture_output=True, timeout=60,
        )
        return {
            "prepare": prepared, "validate": validated, "activate": activated, "repeat": repeated, "status": status,
            "repeat_activate_same_event_log": before_repeat == after_repeat, "activation_events": activation_events,
            "preflight": gates, "strict_outcome": strict_report["migration_outcome"],
            "manual_exit": manual.returncode, "manual": json.loads(manual.stdout),
        }


def main() -> int:
    if not _full_package_check():
        print(json.dumps({"full_verification": "fail", "reason": "complete package verification blocked synthetic handoff"}, ensure_ascii=False))
        return 2
    identity = context.runtime_identity(package_root=PACKAGE_ROOT)
    if identity["status"] != "pass":
        print(json.dumps({"identity": identity["status"], "reason": "runtime identity blocked synthetic handoff"}, ensure_ascii=False))
        return 2
    primary = _flow("TASK-EXAMPLE-001", "HO-EXAMPLE-001", activate=True)
    cancelled = _flow("TASK-EXAMPLE-002", "HO-EXAMPLE-002", activate=False)
    report = {
        "identity": identity["status"], "prepare": primary["prepare"]["check_status"],
        "validate": primary["validate"]["check_status"], "activate": primary["activate"]["commit_status"],
        "repeat_activate_generation": primary["repeat"]["controller_generation"],
        "repeat_activate_same_event_log": primary["repeat_activate_same_event_log"],
        "activation_events": primary["activation_events"],
        "status": primary["status"]["commit_status"], "cancel": cancelled["cancel"]["commit_status"],
        "strict_preflight": primary["preflight"],
        "strict_migration_results": _results(primary["strict_outcome"]),
        "manual_fallback_results": {"preflight_exit": primary["manual_exit"], **_results(primary["manual"]["migration_outcome"])},
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    expected = {
        "identity": "pass", "prepare": "pass", "validate": "pass",
        "activate": "confirmed_committed", "repeat_activate_generation": 1,
        "repeat_activate_same_event_log": True, "activation_events": 1,
        "status": "confirmed_committed", "cancel": "confirmed_committed",
        "strict_preflight": {"prepare": "pass", "activate": "pass", "status": "pass"},
        "strict_migration_results": {
            "information_recovery": "pass", "control_transfer": "pass", "controller_generation": 1,
            "source_retirement": "not_allowed", "archive_allowed": False,
        },
        "manual_fallback_results": {
            "preflight_exit": 0, "information_recovery": "pass", "control_transfer": "unknown",
            "controller_generation": None, "source_retirement": "not_allowed", "archive_allowed": False,
        },
    }
    return 0 if report == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
