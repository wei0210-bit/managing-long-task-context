"""Minimal independent-process synthetic host for E1-03 recovery tests.

This module is deliberately not a TestCase.  Every command creates or reads an
isolated temporary host supplied by the parent test, and prints one JSON line
per observable phase/result.  It performs no model or business action.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import unquote, urlsplit

import managing_long_task_context as context


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _emit(**value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def _read_config(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("fixture configuration is not an object")
    return value


def _reference(task_id: str, ref_id: str, path: Path) -> dict[str, str]:
    return {
        "ref_id": ref_id, "task_id": task_id, "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class SyntheticHost:
    """Registered fixture host: inputs never get reflected back as authority."""

    def __init__(self, record: dict[str, object], contents: dict[str, str], identity: object, base_dir: Path) -> None:
        self.record = record
        self.contents = contents
        self.identity = identity
        self.base_dir = str(base_dir.resolve())

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        references = [
            self.record["source_session_ref"], self.record["target_session_ref"],
            self.record["authorization_ref"], *self.record["basis_refs"],
            self.record["artifact_manifest_ref"],
        ]
        for reference in references:
            if not isinstance(reference, dict):
                return {"status": "fail"}
            path = Path(unquote(urlsplit(str(reference["uri"])).path))
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
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        if request.get("runtime_identity") is not self.identity:
            return {"status": "unknown"}
        arguments = request.get("arguments")
        operation = request.get("operation")
        if not isinstance(arguments, dict) or request.get("arguments_sha256") != _digest(arguments):
            return {"status": "unknown"}
        purpose = {"prepare_handoff": "prepare", "activate_handoff": "activate"}.get(operation)
        if purpose is None:
            return {"status": "unknown"}
        expected = {
            "operation": operation, "task_id": self.record["task_id"],
            "base_dir": self.base_dir,
            "workspace_root": self.record["workspace_root"],
            "package_manifest_sha256": self.record["package_manifest_sha256"],
            "contract_version": self.record["contract_version"],
            "contract_digest": self.record["contract_digest"],
            "controller_generation": self.record["controller_generation"],
            "handoff_id": self.record["handoff_id"],
        }
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        target = deepcopy(self.record["target_session_ref"])
        source = deepcopy(self.record["source_session_ref"])
        response = {
            "status": "pass", **expected, "arguments_sha256": _digest(arguments),
            "purpose": purpose, "subject_id": "fixture:registered-target" if purpose == "activate" else "fixture:registered-source",
            "role": "controller", "scope_digest": "a" * 64, "work_item_id": None,
            "source_session_ref": source, "target_session_ref": target,
            "authorization_ref": deepcopy(self.record["authorization_ref"]),
            "target_activation_status": "not_activated",
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if purpose == "activate":
            response["subject_session_ref"] = target
        return response


def _fixture(config: dict[str, object]) -> tuple[dict[str, object], dict[str, str], Path, Path, Path]:
    root = Path(str(config["root"])).resolve()
    base, workspace, package = root / "context", root / "workspace", root / "package"
    task_id, handoff_id = "TASK-PROCESS-001", "HO-PROCESS-001"
    workspace.mkdir(parents=True, exist_ok=True)
    package.mkdir(parents=True, exist_ok=True)
    (package / "skill-manifest.json").write_text("synthetic process package\n", encoding="utf-8")
    published = context.publish_contract({
        "schema": 1, "task_id": task_id, "version": 1, "issued_by": "fixture",
        "issued_at": "2026-09-15T00:00:00Z", "authorized_approvers": [],
        "objective": "process recovery fixture", "scope": ["isolated"], "out_of_scope": [],
        "constraints": ["no business action"],
        "acceptance_criteria": [{"id": "AC-01", "criterion": "synthetic", "required_evidence": ["fixture"]}],
    }, confirmed_by="fixture", base_dir=base)
    cursor = json.loads((base / task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
    contents = {
        "source": "fixture source controller\n", "target": "fixture inactive target\n",
        "authorization": "fixture original scope\n", "basis": "fixture bearing basis\n",
        "artifacts": "fixture artifacts\n",
    }
    references = {}
    for ref_id, content in contents.items():
        path = workspace / f"{ref_id}.txt"
        path.write_text(content, encoding="utf-8")
        references[ref_id] = _reference(task_id, ref_id, path)
    record: dict[str, object] = {
        "protocol": "short-session-handoff/v1", "task_id": task_id,
        "contract_version": 1, "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
        "workspace_root": str(workspace.resolve()),
        "package_manifest_sha256": hashlib.sha256((package / "skill-manifest.json").read_bytes()).hexdigest(),
        "handoff_id": handoff_id, "request_id": "REQ-PROCESS-PREPARE", "controller_generation": 0,
        "source_session_ref": references["source"], "target_session_ref": references["target"],
        "authorization_ref": references["authorization"], "basis_refs": [references["basis"]],
        "artifact_manifest_ref": references["artifacts"], "created_at": "2026-09-15T00:00:01Z", "event_cursor": cursor,
    }
    return record, contents, base, workspace, package


def bootstrap(config: dict[str, object]) -> int:
    record, contents, base, workspace, package = _fixture(config)
    identity = object()
    host = SyntheticHost(record, contents, identity, base)
    result = context.prepare_handoff(
        str(record["task_id"]), base_dir=base, workspace_root=workspace, package_root=package,
        request_id=str(record["request_id"]), controller_generation=0, record=record,
        runtime_identity=identity, write_authorizer=host, handoff_verifier=host,
    )
    config["task_id"], config["handoff_id"] = record["task_id"], record["handoff_id"]
    Path(str(config["config_path"])).write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    _emit(stage="bootstrap", result=result, business_actions=0)
    return 0 if result.get("check_status") == "pass" else 2


def _load_existing(config: dict[str, object]) -> tuple[dict[str, object], dict[str, str], Path, Path, Path]:
    root = Path(str(config["root"])).resolve()
    base, workspace, package = root / "context", root / "workspace", root / "package"
    record = json.loads((base / "TASK-PROCESS-001" / "handoff" / "HO-PROCESS-001.json").read_text(encoding="utf-8"))
    contents = {name: (workspace / f"{name}.txt").read_text(encoding="utf-8") for name in ("source", "target", "authorization", "basis", "artifacts")}
    return record, contents, base, workspace, package


def _wait_gate(path: str) -> None:
    with Path(path).open("rb", buffering=0) as gate:
        if gate.read(1) != b"G":
            raise RuntimeError("fixture gate did not release")


def activate(config: dict[str, object]) -> int:
    record, contents, base, workspace, package = _load_existing(config)
    identity = object()
    host = SyntheticHost(record, contents, identity, base)
    fault = str(config.get("fault", "none"))
    event_path = base / str(record["task_id"]) / "events.jsonl"
    original_fsync, original_replace = context.os.fsync, context.os.replace
    seen_temp_fsync = False

    def injected_fsync(fd: int) -> None:
        nonlocal seen_temp_fsync
        descriptor_stat = os.fstat(fd)
        temp_matches_fd = any(
            candidate.name.startswith(".handoff-events-")
            and candidate.stat().st_dev == descriptor_stat.st_dev
            and candidate.stat().st_ino == descriptor_stat.st_ino
            for candidate in event_path.parent.iterdir()
        )
        if (
            not seen_temp_fsync
            and temp_matches_fd
        ):
            seen_temp_fsync = True
            _emit(stage="before_temp_fsync", fault=fault)
            if fault == "sigterm_before_temp_fsync":
                _wait_gate(str(config["gate_path"]))
            if fault == "temp_fsync_error":
                raise OSError("fixture injected temporary event fsync failure")
            original_fsync(fd)
            _emit(stage="after_temp_fsync_before_publish", fault=fault)
            if fault == "sigterm_after_temp_fsync":
                _wait_gate(str(config["gate_path"]))
            return
        original_fsync(fd)

    def injected_replace(source: object, destination: object) -> None:
        destination_path = Path(destination)
        if destination_path == event_path:
            _emit(stage="before_events_publish", fault=fault)
            original_replace(source, destination)
            _emit(stage="after_events_publish", fault=fault)
            if fault == "sigterm_after_events_publish":
                _wait_gate(str(config["gate_path"]))
            return
        if destination_path.name == "snapshot.json":
            _emit(stage="before_snapshot_replace", fault=fault)
            if fault == "snapshot_replace_error":
                raise OSError("fixture injected snapshot replacement failure")
            original_replace(source, destination)
            _emit(stage="after_snapshot_replace_before_response", fault=fault)
            if fault == "sigterm_after_snapshot_replace":
                _wait_gate(str(config["gate_path"]))
            return
        original_replace(source, destination)

    if fault != "none":
        context.os.fsync, context.os.replace = injected_fsync, injected_replace
    try:
        if config.get("barrier_path"):
            _emit(stage="ready", pid=os.getpid())
            _wait_gate(str(config["barrier_path"]))
        result = context.activate_handoff(
            str(record["task_id"]), base_dir=base, workspace_root=workspace, package_root=package,
            request_id=str(config.get("request_id", "REQ-PROCESS-ACTIVATE")), controller_generation=0,
            handoff_id=str(record["handoff_id"]), runtime_identity=identity,
            write_authorizer=host, handoff_verifier=host,
        )
        _emit(stage="result", result=result, business_actions=0)
        return 0 if result.get("check_status") == "pass" else 3
    finally:
        context.os.fsync, context.os.replace = original_fsync, original_replace


def status(config: dict[str, object]) -> int:
    record, _contents, base, workspace, package = _load_existing(config)
    result = context.handoff_status(
        str(record["task_id"]), base_dir=base, workspace_root=workspace,
        package_root=package, handoff_id=str(record["handoff_id"]),
    )
    _emit(stage="status", result=result, business_actions=0)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"bootstrap", "activate", "status"}:
        raise SystemExit("usage: handoff_process_fixture.py COMMAND CONFIG_PATH")
    config = _read_config(argv[2])
    return {"bootstrap": bootstrap, "activate": activate, "status": status}[argv[1]](config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
