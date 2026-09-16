"""Pure validation helpers for the short-session handoff read path."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


CAPABILITY = "short-session-handoff/v1"
MAX_EVENTS = 2000
MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_SNAPSHOT_ITEMS = 2000
READ_PARSE_REBUILD_SECONDS = 5
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EVENT_TYPES = frozenset({"handoff_prepared", "handoff_activated", "handoff_cancelled"})
_RECORD_FIELDS = frozenset({"protocol", "task_id", "contract_version", "contract_digest", "workspace_root", "package_manifest_sha256", "handoff_id", "request_id", "controller_generation", "source_session_ref", "target_session_ref", "authorization_ref", "basis_refs", "artifact_manifest_ref", "created_at", "event_cursor"})
_EVENT_FIELDS = frozenset({"type", "task_id", "request_id", "handoff_id", "created_at", "expected_controller_generation", "controller_generation", "record_sha256", "verification_refs"})
_RESULT_REQUIRED = frozenset({"status", "identity_status", "authorization_status", "content_status", "task_id", "handoff_id", "controller_generation", "contract_version", "contract_digest", "workspace_root", "package_manifest_sha256", "record_sha256", "verification_refs", "observed_at", "expires_at"})

_WRITE_AUTHORIZATION_FIELDS = frozenset({
    "status", "operation", "purpose", "task_id", "base_dir", "workspace_root",
    "package_manifest_sha256", "contract_version", "contract_digest",
    "controller_generation", "handoff_id", "arguments_sha256", "subject_id", "role",
    "scope_digest", "work_item_id", "source_session_ref", "target_session_ref",
    "authorization_ref", "target_activation_status", "observed_at", "expires_at",
})
_DELTA_VERIFICATION_FIELDS = frozenset({
    "status", "task_id", "handoff_id", "record_sha256", "contract_version",
    "contract_digest", "workspace_root", "package_manifest_sha256",
    "controller_generation", "before_events_sha256", "after_events_sha256",
    "delta_event_ids", "delta_events_sha256", "non_bearing", "observed_at",
    "expires_at",
})
_OPERATION_PURPOSES = {
    "prepare_handoff": frozenset({"prepare"}),
    "cancel_handoff": frozenset({"cancel"}),
    "activate_handoff": frozenset({"activate"}),
    "publish_contract": frozenset({"contract_publish"}),
    "mark_truth_sources_dirty": frozenset({"truth_source_dirty"}),
    "observe_truth_source": frozenset({"truth_source_observe"}),
    "record": frozenset({"dispatch", "progress", "result", "item_record"}),
    "update_item": frozenset({"progress", "result", "item_update"}),
    "checkpoint": frozenset({"progress", "result", "checkpoint"}),
    "externalize_item": frozenset({"item_externalize"}),
    "restore_externalization_controls": frozenset({"externalization_restore"}),
    "host_reserve": frozenset({"dispatch"}),
    "host_observe": frozenset({"result"}),
    "host_result_publish": frozenset({"result"}),
    "host_result_process": frozenset({"dispatch"}),
    "host_action_observe": frozenset({"result"}),
}


def unknown_response(reason: str, *, code: str = "HANDOFF_UNAVAILABLE", ref: str = "handoff", commit_status: str = "unknown") -> dict[str, Any]:
    return {"check_status": "unknown", "commit_status": commit_status, "controller_generation": None, "blocking_reasons": [{"code": code, "ref": ref, "message": reason}], "verification_refs": [], "next_readonly_action": "Repair or provide readable handoff evidence, then re-check."}


def _failure(reason: str, *, code: str, ref: str) -> dict[str, Any]:
    result = unknown_response(reason, code=code, ref=ref)
    result["check_status"] = "fail"
    return result


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _utc(value: object) -> bool:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _reference_error(value: object, *, task_id: str) -> str | None:
    if not isinstance(value, Mapping) or set(value) != {"ref_id", "task_id", "uri", "sha256"}:
        return "reference fields are invalid"
    if not _identifier(value.get("ref_id")):
        return "reference id is invalid"
    if value.get("task_id") != task_id:
        return "reference task does not match record"
    if not isinstance(value.get("uri"), str) or not value["uri"] or len(value["uri"]) > 2048:
        return "reference URI is invalid"
    if not isinstance(value.get("sha256"), str) or _SHA256.fullmatch(value["sha256"]) is None:
        return "reference digest is invalid"
    return None


def validate_record(record: object) -> tuple[dict[str, Any] | None, str | None]:
    """Validate frozen record structure without following any reference."""
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        return None, "record fields are invalid"
    value = dict(record)
    if value.get("protocol") != CAPABILITY or not _identifier(value.get("task_id")):
        return None, "record protocol or task is invalid"
    version = value.get("contract_version")
    if type(version) not in {int, float, str} or isinstance(version, bool) or (isinstance(version, str) and not version.strip()):
        return None, "record contract version is invalid"
    if not isinstance(value.get("contract_digest"), str) or _SHA256.fullmatch(value["contract_digest"]) is None:
        return None, "record contract digest is invalid"
    if not isinstance(value.get("workspace_root"), str) or not value["workspace_root"].startswith("/"):
        return None, "record workspace root is invalid"
    if not isinstance(value.get("package_manifest_sha256"), str) or _SHA256.fullmatch(value["package_manifest_sha256"]) is None:
        return None, "record package digest is invalid"
    if any(not _identifier(value.get(field)) for field in ("handoff_id", "request_id", "event_cursor")):
        return None, "record identifier is invalid"
    if type(value.get("controller_generation")) is not int or value["controller_generation"] < 0:
        return None, "record controller generation is invalid"
    basis = value.get("basis_refs")
    if not isinstance(basis, list) or not basis or len(basis) > 256:
        return None, "record basis references are invalid"
    references = [value["source_session_ref"], value["target_session_ref"], value["authorization_ref"], *basis, value["artifact_manifest_ref"]]
    seen: set[str] = set()
    for reference in references:
        error = _reference_error(reference, task_id=value["task_id"])
        if error is not None:
            return None, f"record reference: {error}"
        ref_id = reference["ref_id"]
        if ref_id in seen:
            return None, "record reference IDs conflict"
        seen.add(ref_id)
    if not _utc(value.get("created_at")):
        return None, "record creation time is invalid"
    return value, None


def validate_protocol_event(event: object, *, task_id: str) -> str | None:
    if not isinstance(event, Mapping) or set(event) != _EVENT_FIELDS:
        return "handoff event fields are invalid"
    if event.get("type") not in _EVENT_TYPES or event.get("task_id") != task_id:
        return "handoff event type or task is invalid"
    if any(not _identifier(event.get(field)) for field in ("request_id", "handoff_id")) or not _utc(event.get("created_at")):
        return "handoff event identity or time is invalid"
    if any(type(event.get(field)) is not int or event[field] < 0 for field in ("expected_controller_generation", "controller_generation")):
        return "handoff event generation is invalid"
    if not isinstance(event.get("record_sha256"), str) or _SHA256.fullmatch(event["record_sha256"]) is None:
        return "handoff event record digest is invalid"
    refs = event.get("verification_refs")
    if not isinstance(refs, list) or not refs or len(refs) > 256:
        return "handoff event verification references are invalid"
    seen: set[str] = set()
    for reference in refs:
        error = _reference_error(reference, task_id=task_id)
        if error is not None or reference["ref_id"] in seen:
            return "handoff event verification references are invalid"
        seen.add(reference["ref_id"])
    return None


def _prepared(events: Sequence[Mapping[str, Any]], *, task_id: str, handoff_id: str) -> tuple[Mapping[str, Any] | None, str | None]:
    projection, error = _control_projection(events, task_id=task_id)
    if error is not None:
        return None, error
    pending = projection.get("pending")
    if not isinstance(pending, Mapping) or pending.get("handoff_id") != handoff_id:
        return None, "handoff is not currently prepared"
    return pending, None


def _as_utc(value: object) -> datetime | None:
    if not _utc(value):
        return None
    assert isinstance(value, str)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalized_path(value: str | Path, *, field: str, require_exists: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{field} must be absolute")
    try:
        return path.resolve(strict=require_exists)
    except OSError as exc:
        raise ValueError(f"{field} is unavailable") from exc


def _package_manifest_sha256(package_root: Path) -> str:
    manifest = package_root / "skill-manifest.json"
    try:
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > MAX_LOG_BYTES:
            raise ValueError("package manifest is unavailable")
        digest = hashlib.sha256()
        total = 0
        with manifest.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                total += len(chunk)
                if total > MAX_LOG_BYTES:
                    raise ValueError("package manifest exceeds byte limit")
                digest.update(chunk)
    except OSError as exc:
        raise ValueError("package manifest is unavailable") from exc
    return digest.hexdigest()


def _record_references(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(record["source_session_ref"]), dict(record["target_session_ref"]),
        dict(record["authorization_ref"]), *[dict(item) for item in record["basis_refs"]],
        dict(record["artifact_manifest_ref"]),
    ]


def _capture_prepare_inputs(
    task_id: str, *, base_dir: Path,
) -> dict[str, Any]:
    """Read only committed control facts under the core shared lock."""
    from . import (
        _handoff_strict_task_view_locked, _paths, _shared_locked_existing,
    )

    paths = _paths(task_id, base_dir)
    with _shared_locked_existing(paths["root"]):
        view = _handoff_strict_task_view_locked(task_id, paths)
    return {
        "contract_version": view["contract_version"],
        "contract_digest": view["contract_digest"], "contract": view["contract"],
        "events": view["events"], "event_ids": view["event_ids"],
        "event_fingerprint": view["events_digest"],
    }


def _control_events(events: Sequence[Mapping[str, Any]], *, task_id: str) -> tuple[list[Mapping[str, Any]], str | None]:
    controls: list[Mapping[str, Any]] = []
    request_bindings: dict[str, tuple[object, ...]] = {}
    for event in events:
        if event.get("event_type") not in _EVENT_TYPES:
            continue
        payload = event.get("payload")
        error = validate_protocol_event(payload, task_id=task_id)
        if error is not None or not isinstance(payload, Mapping):
            return [], error or "handoff control event is invalid"
        if payload.get("type") != event.get("event_type"):
            return [], "handoff event envelope type differs from payload type"
        binding = (
            payload.get("type"), payload.get("handoff_id"),
            payload.get("expected_controller_generation"), payload.get("record_sha256"),
        )
        request_id = payload.get("request_id")
        if request_id in request_bindings and request_bindings[request_id] != binding:
            return [], "handoff request id conflicts in authoritative events"
        request_bindings[str(request_id)] = binding
        controls.append(payload)
    return controls, None


def _control_projection(
    events: Sequence[Mapping[str, Any]], *, task_id: str,
) -> tuple[dict[str, Any], str | None]:
    """Rebuild the sole control state from the frozen three-event protocol."""
    controls, error = _control_events(events, task_id=task_id)
    if error is not None:
        return {}, error
    generation: int | None = None
    pending: Mapping[str, Any] | None = None
    active: Mapping[str, Any] | None = None
    cancelled: Mapping[str, Any] | None = None
    closed: dict[str, str] = {}
    requests: dict[str, tuple[object, ...]] = {}
    for event in controls:
        event_type = event["type"]
        handoff_id = event["handoff_id"]
        request_id = event["request_id"]
        binding = (
            event_type, handoff_id, event["expected_controller_generation"],
            event["controller_generation"], event["record_sha256"],
        )
        if request_id in requests:
            if requests[request_id] != binding:
                return {}, "handoff request id conflicts in authoritative events"
            return {}, "handoff request id is duplicated in authoritative events"
        requests[request_id] = binding
        expected = event["expected_controller_generation"]
        actual = event["controller_generation"]
        if generation is None:
            generation = expected
        if expected != generation:
            return {}, "handoff control generation order is invalid"
        if event_type == "handoff_prepared":
            if pending is not None or handoff_id in closed:
                return {}, "handoff prepared order conflicts"
            if actual != expected:
                return {}, "handoff prepared generation is invalid"
            pending = event
        elif event_type == "handoff_cancelled":
            if pending is None or pending.get("handoff_id") != handoff_id or actual != expected:
                return {}, "handoff cancellation order is invalid"
            if event.get("record_sha256") != pending.get("record_sha256"):
                return {}, "handoff cancellation record differs from prepared"
            closed[handoff_id] = "cancelled"
            cancelled = event
            pending = None
        else:
            if pending is None or pending.get("handoff_id") != handoff_id or actual != expected + 1:
                return {}, "handoff activation order is invalid"
            if event.get("record_sha256") != pending.get("record_sha256"):
                return {}, "handoff activation record differs from prepared"
            closed[handoff_id] = "activated"
            active = event
            pending = None
            generation = actual
    return {
        "controls": controls, "generation": generation, "pending": pending,
        "active": active, "cancelled": cancelled, "closed": closed, "request_bindings": requests,
    }, None


def _legacy_control_event_present(path: Path, *, task_id: str) -> bool:
    """Stream only the irreversible control fact for pre-protocol tasks.

    Legacy writers did not inherit the handoff read budget.  This deliberately
    avoids rebuilding or retaining their item history; an unreadable line is
    still fail-closed because it could conceal a control event.
    """
    from . import _strict_handoff_json_load

    try:
        with path.open("rb") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                if not raw_line.endswith(b"\n"):
                    raise ValueError(f"truncated authoritative event at line {line_no}")
                try:
                    event = _strict_handoff_json_load(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"invalid authoritative event at line {line_no}") from exc
                if not isinstance(event, Mapping):
                    raise ValueError(f"non-object authoritative event at line {line_no}")
                if event.get("event_type") not in _EVENT_TYPES:
                    continue
                payload = event.get("payload")
                error = validate_protocol_event(payload, task_id=task_id)
                if error is not None or not isinstance(payload, Mapping):
                    raise ValueError(error or "handoff control event is invalid")
                if payload.get("type") != event.get("event_type"):
                    raise ValueError("handoff event envelope type differs from payload type")
                return True
    except OSError as exc:
        raise ValueError("authoritative event history is unreadable") from exc
    return False


def _existing_prepare_response(
    controls: Sequence[Mapping[str, Any]], *, task_id: str, base_dir: Path,
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a prior committed fact only when the entire prepared binding matches."""
    wanted = (
        "handoff_prepared", record["request_id"], record["handoff_id"],
        record["controller_generation"], _canonical_sha256(record),
    )
    matching = [
        event for event in controls
        if (
            event.get("type"), event.get("request_id"), event.get("handoff_id"),
            event.get("expected_controller_generation"), event.get("record_sha256"),
        ) == wanted
    ]
    if not matching:
        return None
    if len(matching) != 1:
        raise ValueError("prepared request has conflicting authoritative events")
    from . import _paths, _read_handoff_json
    stored, digest = _read_handoff_json(_paths(task_id, base_dir)["handoff_root"] / f"{record['handoff_id']}.json")
    if digest != wanted[-1] or stored != dict(record):
        raise ValueError("prepared request record differs from authoritative event")
    if any(
        event.get("handoff_id") == record["handoff_id"]
        and event.get("type") in {"handoff_activated", "handoff_cancelled"}
        for event in controls
    ):
        raise ValueError("prepared request is no longer pending")
    return {
        "check_status": "pass", "commit_status": "confirmed_committed",
        "controller_generation": record["controller_generation"], "blocking_reasons": [],
        "verification_refs": _record_references(record),
        "next_readonly_action": "Read handoff_status; activation remains ungranted.",
    }


def _existing_cancel_response(
    controls: Sequence[Mapping[str, Any]], *, request_id: str, record: Mapping[str, Any],
) -> dict[str, Any] | None:
    wanted = (
        "handoff_cancelled", request_id, record["handoff_id"],
        record["controller_generation"], _canonical_sha256(record),
    )
    matching = [
        event for event in controls
        if (
            event.get("type"), event.get("request_id"), event.get("handoff_id"),
            event.get("expected_controller_generation"), event.get("record_sha256"),
        ) == wanted
    ]
    if not matching:
        return None
    if len(matching) != 1:
        raise ValueError("cancellation request has conflicting authoritative events")
    return {
        "check_status": "pass", "commit_status": "confirmed_committed",
        "controller_generation": record["controller_generation"], "blocking_reasons": [],
        "verification_refs": _record_references(record),
        "next_readonly_action": "Read handoff_status; activation remains ungranted.",
    }


def _recover_committed_prepare(
    task_id: str, *, base_dir: Path | None, record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover only a uniquely readable prepared fact after a failed commit call."""
    from . import ContextError

    if base_dir is None or record is None:
        return None
    try:
        capture = _capture_prepare_inputs(task_id, base_dir=base_dir)
        controls, error = _control_events(capture["events"], task_id=task_id)
        if error is not None:
            return None
        return _existing_prepare_response(
            controls, task_id=task_id, base_dir=base_dir, record=record,
        )
    except (ContextError, OSError, TypeError, ValueError):
        return None


def _recover_committed_cancel(
    task_id: str, *, base_dir: Path | None, request_id: str, record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover only a uniquely readable cancelled fact after a failed commit call."""
    from . import ContextError

    if base_dir is None or record is None:
        return None
    try:
        capture = _capture_prepare_inputs(task_id, base_dir=base_dir)
        controls, error = _control_events(capture["events"], task_id=task_id)
        if error is not None:
            return None
        return _existing_cancel_response(controls, request_id=request_id, record=record)
    except (ContextError, OSError, TypeError, ValueError):
        return None


def _authorizer_request(
    *, operation: str, task_id: str, base_dir: Path, workspace_root: Path,
    package_manifest_sha256: str, contract_version: object, contract_digest: str,
    controller_generation: int, handoff_id: str | None, arguments: Mapping[str, Any],
    runtime_identity: Any,
) -> dict[str, Any]:
    normalized_arguments = json.loads(json.dumps(arguments, ensure_ascii=False, sort_keys=True))
    return {
        "operation": operation,
        "task_id": task_id,
        "base_dir": str(base_dir),
        "workspace_root": str(workspace_root),
        "package_manifest_sha256": package_manifest_sha256,
        "contract_version": contract_version,
        "contract_digest": contract_digest,
        "controller_generation": controller_generation,
        "handoff_id": handoff_id,
        "arguments": normalized_arguments,
        "arguments_sha256": _canonical_sha256(normalized_arguments),
        "runtime_identity": runtime_identity,
    }


def _authorized_write(
    request: Mapping[str, Any], *, write_authorizer: Any, record: Mapping[str, Any],
    now: datetime, allowed_roles: frozenset[str] = frozenset({"controller"}),
    require_work_item: bool = False, required_subject_session_ref: Mapping[str, Any] | None = None,
    allowed_target_activation_status: frozenset[str] = frozenset({"not_activated"}),
) -> tuple[dict[str, Any] | None, str | None]:
    authorize = getattr(write_authorizer, "authorize", None)
    if not callable(authorize):
        return None, "runtime write authorizer is unavailable"
    try:
        result = authorize(dict(request))
    except Exception:
        return None, "runtime write authorizer failed"
    expected_fields = _WRITE_AUTHORIZATION_FIELDS | (
        {"subject_session_ref"} if required_subject_session_ref is not None else set()
    )
    if not isinstance(result, Mapping) or set(result) != expected_fields:
        return None, "runtime write authorizer result is malformed"
    value = dict(result)
    if value.get("status") != "pass":
        return None, "runtime write authorizer did not grant the operation"
    for field in (
        "operation", "task_id", "base_dir", "workspace_root", "package_manifest_sha256",
        "contract_version", "contract_digest", "controller_generation", "handoff_id",
        "arguments_sha256",
    ):
        expected = request.get(field)
        if type(value.get(field)) is not type(expected) or value.get(field) != expected:
            return None, "runtime write authorizer binding differs from request"
    operation = request.get("operation")
    if value.get("purpose") not in _OPERATION_PURPOSES.get(operation, frozenset()):
        return None, "runtime write authorizer purpose is not allowed for operation"
    role = value.get("role")
    purpose = value.get("purpose")
    if role not in allowed_roles or not isinstance(value.get("subject_id"), str) or not value["subject_id"].strip():
        return None, "runtime write authorizer identity is invalid"
    if purpose in {"prepare", "cancel", "dispatch", "contract_publish"} and role != "controller":
        return None, "runtime write authorizer purpose requires controller role"
    if role == "child" and purpose not in {"progress", "result"}:
        return None, "runtime write authorizer child purpose is invalid"
    if not isinstance(value.get("scope_digest"), str) or _SHA256.fullmatch(value["scope_digest"]) is None:
        return None, "runtime write authorizer scope is invalid"
    work_item = value.get("work_item_id")
    if (require_work_item or role == "child") and not _identifier(work_item):
        return None, "runtime write authorizer child work item is invalid"
    if not require_work_item and role == "controller" and work_item is not None:
        return None, "runtime write authorizer controller work item is invalid"
    if value.get("target_activation_status") not in allowed_target_activation_status:
        return None, "runtime target activation status is invalid"
    for field in ("source_session_ref", "target_session_ref", "authorization_ref"):
        if value.get(field) != record.get(field):
            return None, "runtime write authorizer reference binding differs from record"
    if required_subject_session_ref is not None:
        if _reference_error(value.get("subject_session_ref"), task_id=str(record.get("task_id"))) is not None:
            return None, "runtime write authorizer subject session reference is invalid"
        if role == "controller" and value.get("subject_session_ref") != dict(required_subject_session_ref):
            return None, "runtime write authorizer subject differs from required controller"
    now = datetime.now(timezone.utc)
    observed_at, expires_at = _as_utc(value.get("observed_at")), _as_utc(value.get("expires_at"))
    if observed_at is None or expires_at is None or observed_at > now or expires_at < now:
        return None, "runtime write authorizer observation is stale or invalid"
    return value, None


def _verify_prepare_content(
    *, capture: Mapping[str, Any], record: Mapping[str, Any],
    reference_fingerprints: Sequence[tuple[str, str]], handoff_verifier: Any,
) -> str | None:
    """Use the #16 full verifier contract for a prospective prepared event."""
    verify = getattr(handoff_verifier, "verify", None)
    if not callable(verify):
        return "runtime handoff verifier is unavailable"
    record_digest = _canonical_sha256(record)
    payload = {
        "type": "handoff_prepared", "task_id": record["task_id"],
        "request_id": record["request_id"], "handoff_id": record["handoff_id"],
        "created_at": record["created_at"],
        "expected_controller_generation": record["controller_generation"],
        "controller_generation": record["controller_generation"],
        "record_sha256": record_digest, "verification_refs": _record_references(record),
    }
    prospective = {
        "task_id": record["task_id"], "handoff_id": record["handoff_id"],
        "record": dict(record), "record_sha256": record_digest,
        "contract": capture["contract"],
        "events": [*capture["events"], {"event_type": "handoff_prepared", "payload": payload}],
        "workspace_root": record["workspace_root"],
        "package_manifest_sha256": record["package_manifest_sha256"],
        "reference_fingerprints": tuple(reference_fingerprints),
    }
    request = _handoff_request(prospective, observed_at=datetime.now(timezone.utc))
    try:
        result = verify(dict(request))
    except Exception:
        return "runtime handoff verifier failed"
    if evaluate_handoff_capture(prospective, host_result=result, now=datetime.now(timezone.utc)).get("check_status") != "pass":
        return "runtime handoff verifier did not establish content"
    return None


def _verify_existing_content(
    *, capture: Mapping[str, Any], record: Mapping[str, Any],
    reference_fingerprints: Sequence[tuple[str, str]], handoff_verifier: Any,
) -> tuple[str | None, datetime | None]:
    verify = getattr(handoff_verifier, "verify", None)
    if not callable(verify):
        return "runtime handoff verifier is unavailable", None
    prospective = {
        "task_id": record["task_id"], "handoff_id": record["handoff_id"],
        "record": dict(record), "record_sha256": _canonical_sha256(record),
        "contract": capture["contract"], "events": capture["events"],
        "workspace_root": record["workspace_root"],
        "package_manifest_sha256": record["package_manifest_sha256"],
        "reference_fingerprints": tuple(reference_fingerprints),
    }
    try:
        result = verify(_handoff_request(prospective, observed_at=datetime.now(timezone.utc)))
    except Exception:
        return "runtime handoff verifier failed", None
    now = datetime.now(timezone.utc)
    if evaluate_handoff_capture(prospective, host_result=result, now=now).get("check_status") != "pass":
        return "runtime handoff verifier did not establish current content", None
    return None, _as_utc(result.get("expires_at")) if isinstance(result, Mapping) else None


def evaluate_handoff_capture(capture: Mapping[str, Any], *, host_result: object, now: datetime) -> dict[str, Any]:
    """Combine captured authoritative facts with a runtime-only host verdict."""
    record, error = validate_record(capture.get("record"))
    if error is not None or record is None:
        return _failure(error or "record invalid", code="HANDOFF_RECORD_INVALID", ref="record")
    if capture.get("task_id") != record["task_id"] or capture.get("handoff_id") != record["handoff_id"]:
        return _failure("requested handoff does not match record", code="HANDOFF_REQUEST_MISMATCH", ref="record")
    contract, seal = capture.get("contract"), None
    if isinstance(contract, Mapping):
        seal = contract.get("seal")
    if not isinstance(contract, Mapping) or not isinstance(seal, Mapping):
        return unknown_response("sealed task contract is unavailable", code="HANDOFF_CONTRACT_UNAVAILABLE", ref="contract")
    if type(record["contract_version"]) is not type(contract.get("version")) or record["contract_version"] != contract.get("version") or record["contract_digest"] != str(seal.get("integrity_digest", "")).removeprefix("sha256:"):
        return unknown_response("record contract binding differs from authoritative contract", code="HANDOFF_CONTRACT_MISMATCH", ref="contract")
    if capture.get("workspace_root") != record["workspace_root"]:
        return unknown_response("record workspace binding differs from request", code="HANDOFF_WORKSPACE_MISMATCH", ref="record.workspace_root")
    if capture.get("package_manifest_sha256") != record["package_manifest_sha256"]:
        return unknown_response("record package binding differs from current package", code="HANDOFF_PACKAGE_MISMATCH", ref="record.package_manifest_sha256")
    projection, projection_error = _control_projection(capture.get("events", []), task_id=record["task_id"])
    if projection_error is not None:
        return unknown_response(projection_error, code="HANDOFF_EVENT_UNAVAILABLE", ref="events.jsonl")
    prepared = next(
        (event for event in projection["controls"] if event.get("type") == "handoff_prepared"
         and event.get("handoff_id") == record["handoff_id"]),
        None,
    )
    if not isinstance(prepared, Mapping) or prepared.get("record_sha256") != capture.get("record_sha256") or prepared.get("controller_generation") != record["controller_generation"]:
        return unknown_response("prepared event is not bound to record", code="HANDOFF_RECORD_DIGEST_MISMATCH", ref="events.jsonl")
    active = projection.get("active")
    pending = projection.get("pending")
    if active is not None and active.get("handoff_id") == record["handoff_id"]:
        observed_generation = active.get("controller_generation")
        commit_status = "confirmed_committed"
    elif pending is not None and pending.get("handoff_id") == record["handoff_id"]:
        observed_generation = record["controller_generation"]
        commit_status = "confirmed_not_committed"
    else:
        return unknown_response("handoff is no longer current", code="HANDOFF_EVENT_UNAVAILABLE", ref="events.jsonl")
    if not isinstance(host_result, Mapping) or not _RESULT_REQUIRED.issubset(host_result):
        return unknown_response("runtime verifier result is malformed", code="HANDOFF_VERIFIER_MALFORMED", ref="verifier")
    statuses = [host_result.get(field) for field in ("status", "identity_status", "authorization_status", "content_status")]
    if any(status not in {"pass", "fail", "unknown"} for status in statuses):
        return unknown_response("runtime verifier result has invalid status", code="HANDOFF_VERIFIER_MALFORMED", ref="verifier")
    if any(status != "pass" for status in statuses):
        response = unknown_response("runtime verifier did not establish all required checks", code="HANDOFF_VERIFIER_REJECTED", ref="verifier")
        if "fail" in statuses:
            response["check_status"] = "fail"
        return response
    bindings = {"task_id": record["task_id"], "handoff_id": record["handoff_id"], "controller_generation": record["controller_generation"], "contract_version": record["contract_version"], "contract_digest": record["contract_digest"], "workspace_root": record["workspace_root"], "package_manifest_sha256": record["package_manifest_sha256"], "record_sha256": capture.get("record_sha256")}
    if any(
        type(host_result.get(key)) is not type(value) or host_result.get(key) != value
        for key, value in bindings.items()
    ):
        return unknown_response("runtime verifier binding differs from authoritative capture", code="HANDOFF_VERIFIER_BINDING_MISMATCH", ref="verifier")
    observed_at, expires_at = _as_utc(host_result.get("observed_at")), _as_utc(host_result.get("expires_at"))
    if observed_at is None or expires_at is None or expires_at < now.astimezone(timezone.utc) or observed_at > now.astimezone(timezone.utc):
        return unknown_response("runtime verifier observation is stale or invalid", code="HANDOFF_VERIFIER_STALE", ref="verifier")
    required_ref_values = [record["source_session_ref"], record["target_session_ref"], record["authorization_ref"], *record["basis_refs"], record["artifact_manifest_ref"]]
    required_refs = {item["ref_id"]: dict(item) for item in required_ref_values}
    verifier_refs = host_result.get("verification_refs")
    try:
        verifier_by_id = {item.get("ref_id"): dict(item) for item in verifier_refs if isinstance(item, Mapping)} if isinstance(verifier_refs, list) else {}
    except TypeError:
        verifier_by_id = {}
    if not isinstance(verifier_refs, list) or len(verifier_by_id) != len(verifier_refs) or verifier_by_id != required_refs:
        return unknown_response("runtime verifier did not cover every required reference", code="HANDOFF_VERIFIER_REFERENCE_COVERAGE", ref="verifier")
    event_refs = prepared.get("verification_refs")
    if not isinstance(event_refs, list) or any(not isinstance(item, Mapping) or required_refs.get(item.get("ref_id")) != dict(item) for item in event_refs):
        return unknown_response("prepared event verification references are not bound by record", code="HANDOFF_EVENT_REFERENCE_MISMATCH", ref="events.jsonl")
    return {"check_status": "pass", "commit_status": "not_attempted", "controller_generation": observed_generation, "blocking_reasons": [], "verification_refs": [dict(item) for item in verifier_refs], "next_readonly_action": "Read handoff_status; activation and business completion remain ungranted."}


def _handoff_request(capture: Mapping[str, Any], *, observed_at: datetime) -> dict[str, Any]:
    record = capture["record"]
    assert isinstance(record, Mapping)
    return {
        "task_id": capture["task_id"], "handoff_id": capture["handoff_id"],
        "record_sha256": capture["record_sha256"], "contract_version": record.get("contract_version"),
        "contract_digest": record.get("contract_digest"), "workspace_root": capture["workspace_root"],
        "package_manifest_sha256": capture["package_manifest_sha256"],
        "controller_generation": record.get("controller_generation"),
        "source_session_ref": record.get("source_session_ref"), "target_session_ref": record.get("target_session_ref"),
        "authorization_ref": record.get("authorization_ref"), "basis_refs": record.get("basis_refs"),
        "artifact_manifest_ref": record.get("artifact_manifest_ref"), "observed_at": observed_at.isoformat(),
    }


def validate_handoff(
    task_id: str,
    *,
    base_dir: str | Path,
    workspace_root: str | Path,
    package_root: str | Path,
    handoff_id: str,
    handoff_verifier: Any = None,
) -> dict[str, Any]:
    """Read a published handoff without granting control or writing state."""
    from . import ContextError, _handoff_capture_locked, _trusted_utc_now

    def not_attempted_unknown(reason: str, *, code: str, ref: str) -> dict[str, Any]:
        return unknown_response(
            reason, code=code, ref=ref, commit_status="not_attempted",
        )

    try:
        capture = _handoff_capture_locked(
            task_id, base_dir=base_dir, workspace_root=workspace_root,
            package_root=package_root, handoff_id=handoff_id,
        )
    except (ContextError, OSError, ValueError, TypeError) as exc:
        return not_attempted_unknown(str(exc), code="HANDOFF_READ_UNAVAILABLE", ref="storage")
    verifier = getattr(handoff_verifier, "verify", None)
    if not callable(verifier):
        return not_attempted_unknown("runtime handoff verifier is unavailable", code="HANDOFF_VERIFIER_UNAVAILABLE", ref="verifier")
    now = _trusted_utc_now()
    try:
        result = verifier(_handoff_request(capture, observed_at=now))
    except Exception:
        return not_attempted_unknown("runtime handoff verifier failed", code="HANDOFF_VERIFIER_UNAVAILABLE", ref="verifier")
    try:
        final = _handoff_capture_locked(
            task_id, base_dir=base_dir, workspace_root=workspace_root,
            package_root=package_root, handoff_id=handoff_id,
        )
    except (ContextError, OSError, ValueError, TypeError) as exc:
        return not_attempted_unknown(str(exc), code="HANDOFF_RECHECK_UNAVAILABLE", ref="storage")
    if final["observation_token"] != capture["observation_token"]:
        return not_attempted_unknown("handoff input changed during final verifier callback", code="HANDOFF_INPUT_CHANGED", ref="storage")
    report = evaluate_handoff_capture(final, host_result=result, now=_trusted_utc_now())
    if report.get("commit_status") == "unknown":
        report["commit_status"] = "not_attempted"
    return report


def handoff_status(
    task_id: str,
    *,
    base_dir: str | Path,
    workspace_root: str | Path,
    package_root: str | Path,
    handoff_id: str,
    handoff_verifier: Any = None,
) -> dict[str, Any]:
    """Return the same point-in-time read-only handoff observation."""
    report = validate_handoff(
        task_id, base_dir=base_dir, workspace_root=workspace_root,
        package_root=package_root, handoff_id=handoff_id,
        handoff_verifier=handoff_verifier,
    )
    # Never overwrite a durable activation merely because the current verifier
    # later becomes unavailable.  This replay intentionally does not read
    # bearing references: those belong solely to the current check above.
    try:
        from . import _paths, _read_handoff_json
        base = _normalized_path(base_dir, field="base_dir")
        capture = _capture_prepare_inputs(task_id, base_dir=base)
        projection, error = _control_projection(capture["events"], task_id=task_id)
        controls = projection.get("controls", []) if error is None else []
        selected = [event for event in controls if event.get("handoff_id") == handoff_id]
        prepared = [event for event in selected if event.get("type") == "handoff_prepared"]
        activated = [event for event in selected if event.get("type") == "handoff_activated"]
        cancelled = [event for event in selected if event.get("type") == "handoff_cancelled"]
        if len(prepared) != 1 or len(activated) > 1 or len(cancelled) > 1:
            raise ValueError("handoff control facts are invalid")
        record, digest = _read_handoff_json(_paths(task_id, base)["handoff_root"] / f"{handoff_id}.json")
        record, record_error = validate_record(record)
        if record_error is not None or record is None or digest != prepared[0].get("record_sha256"):
            raise ValueError("handoff status record binding is invalid")
        if activated:
            report["commit_status"] = "confirmed_committed"
            report["controller_generation"] = activated[0].get("controller_generation")
        elif cancelled or prepared:
            report["commit_status"] = "confirmed_not_committed"
            report["controller_generation"] = prepared[0].get("controller_generation")
        else:
            report["commit_status"] = "unknown"
    except Exception:
        report["commit_status"] = "unknown"
    return report


def prepare_handoff(
    task_id: str,
    *,
    base_dir: str | Path,
    workspace_root: str | Path,
    package_root: str | Path,
    request_id: str,
    controller_generation: int,
    record: Mapping[str, Any],
    runtime_identity: Any = None,
    write_authorizer: Any = None,
    handoff_verifier: Any = None,
) -> dict[str, Any]:
    """Prepare one handoff after out-of-lock host checks and a short commit lock."""
    from . import ContextError, _handoff_prepare_commit

    validated_record: dict[str, Any] | None = None
    base: Path | None = None
    commit_attempted = False
    try:
        validated_record, error = validate_record(record)
        if error is not None or validated_record is None:
            raise ValueError(error or "record is invalid")
        if (
            validated_record["task_id"] != task_id
            or validated_record["request_id"] != request_id
            or type(controller_generation) is not int
            or controller_generation != validated_record["controller_generation"]
        ):
            raise ValueError("prepare request does not match record")
        base = _normalized_path(base_dir, field="base_dir")
        workspace = _normalized_path(workspace_root, field="workspace_root", require_exists=True)
        package = _normalized_path(package_root, field="package_root", require_exists=True)
        if not workspace.is_dir() or not package.is_dir() or validated_record["workspace_root"] != str(workspace):
            raise ValueError("prepare workspace binding is invalid")
        manifest_digest = _package_manifest_sha256(package)
        if manifest_digest != validated_record["package_manifest_sha256"]:
            raise ValueError("prepare package binding is invalid")
        capture = _capture_prepare_inputs(task_id, base_dir=base)
        if (
            type(capture["contract_version"]) is not type(validated_record["contract_version"])
            or capture["contract_version"] != validated_record["contract_version"]
            or capture["contract_digest"] != validated_record["contract_digest"]
            or validated_record["event_cursor"] not in capture["event_ids"]
        ):
            raise ValueError("prepare sealed contract or event cursor binding is invalid")
        projection, control_error = _control_projection(capture["events"], task_id=task_id)
        if control_error is not None:
            raise ValueError(control_error)
        controls = projection["controls"]
        if projection.get("pending") is not None:
            existing = _existing_prepare_response(
                controls, task_id=task_id, base_dir=base, record=validated_record,
            )
            if existing is not None:
                return existing
            raise ValueError("another handoff is already pending")
        active = projection.get("active")
        cancelled = projection.get("cancelled")
        require_subject: Mapping[str, Any] | None = None
        current_control = active if isinstance(active, Mapping) else cancelled
        if isinstance(current_control, Mapping):
            if validated_record["controller_generation"] != current_control.get("controller_generation"):
                raise ValueError("prepare controller generation differs from current controller")
            from . import _paths, _read_handoff_json
            active_record, active_digest = _read_handoff_json(
                _paths(task_id, base)["handoff_root"] / f"{current_control['handoff_id']}.json"
            )
            active_record, active_error = validate_record(active_record)
            if active_error is not None or active_record is None or active_digest != current_control.get("record_sha256"):
                raise ValueError("current controller record is invalid")
            current_subject = (
                active_record["target_session_ref"] if isinstance(active, Mapping)
                else active_record["source_session_ref"]
            )
            if validated_record["source_session_ref"] != current_subject:
                raise ValueError("prepare source does not match current controller")
            require_subject = current_subject
        from . import _handoff_reference_fingerprints
        first_refs = _handoff_reference_fingerprints(validated_record, workspace=workspace)
        arguments = {
            "operation": "prepare_handoff", "task_id": task_id, "base_dir": str(base),
            "workspace_root": str(workspace), "package_root": str(package),
            "request_id": request_id, "controller_generation": controller_generation,
            "record": validated_record,
        }
        authorization_request = _authorizer_request(
            operation="prepare_handoff", task_id=task_id, base_dir=base,
            workspace_root=workspace, package_manifest_sha256=manifest_digest,
            contract_version=capture["contract_version"], contract_digest=capture["contract_digest"],
            controller_generation=controller_generation, handoff_id=validated_record["handoff_id"],
            arguments=arguments, runtime_identity=runtime_identity,
        )
        authorization, authorization_error = _authorized_write(
            authorization_request, write_authorizer=write_authorizer, record=validated_record,
            now=datetime.now(timezone.utc), required_subject_session_ref=require_subject,
        )
        if authorization_error is not None:
            raise ValueError(authorization_error)
        verifier_error = _verify_prepare_content(
            capture=capture, record=validated_record,
            reference_fingerprints=first_refs, handoff_verifier=handoff_verifier,
        )
        if verifier_error is not None:
            raise ValueError(verifier_error)
        second_refs = _handoff_reference_fingerprints(validated_record, workspace=workspace)
        if second_refs != first_refs:
            raise ValueError("prepare references changed during host verification")
        commit_attempted = True
        return _handoff_prepare_commit(
            task_id, base_dir=base, record=validated_record, capture=capture,
            authorization=authorization, reference_fingerprints=second_refs,
            workspace_root=workspace, package_root=package,
        )
    except (ContextError, OSError, TypeError, ValueError) as exc:
        recovered = _recover_committed_prepare(
            task_id, base_dir=base, record=validated_record,
        ) if commit_attempted else None
        if recovered is not None:
            return recovered
        return unknown_response(
            str(exc), code="HANDOFF_PREPARE_REJECTED", ref="prepare",
        )


def cancel_handoff(
    task_id: str,
    *,
    base_dir: str | Path,
    workspace_root: str | Path,
    package_root: str | Path,
    request_id: str,
    controller_generation: int,
    handoff_id: str,
    runtime_identity: Any = None,
    write_authorizer: Any = None,
    handoff_verifier: Any = None,
) -> dict[str, Any]:
    """Cancel only a currently prepared, host-confirmed inactive handoff."""
    from . import ContextError, _handoff_cancel_commit, _paths, _read_handoff_json

    validated_record: dict[str, Any] | None = None
    base: Path | None = None
    commit_attempted = False
    try:
        if not _identifier(request_id) or not _identifier(handoff_id) or type(controller_generation) is not int:
            raise ValueError("cancel request identity is invalid")
        base = _normalized_path(base_dir, field="base_dir")
        workspace = _normalized_path(workspace_root, field="workspace_root", require_exists=True)
        package = _normalized_path(package_root, field="package_root", require_exists=True)
        if not workspace.is_dir() or not package.is_dir():
            raise ValueError("cancel workspace or package is invalid")
        record, record_digest = _read_handoff_json(_paths(task_id, base)["handoff_root"] / f"{handoff_id}.json")
        validated_record, error = validate_record(record)
        if error is not None or validated_record is None:
            raise ValueError(error or "prepared record is invalid")
        manifest_digest = _package_manifest_sha256(package)
        if (
            validated_record["task_id"] != task_id
            or validated_record["handoff_id"] != handoff_id
            or validated_record["workspace_root"] != str(workspace)
            or validated_record["package_manifest_sha256"] != manifest_digest
            or validated_record["controller_generation"] != controller_generation
            or record_digest != _canonical_sha256(validated_record)
        ):
            raise ValueError("cancel record binding is invalid")
        capture = _capture_prepare_inputs(task_id, base_dir=base)
        if (
            type(capture["contract_version"]) is not type(validated_record["contract_version"])
            or capture["contract_version"] != validated_record["contract_version"]
            or capture["contract_digest"] != validated_record["contract_digest"]
        ):
            raise ValueError("cancel sealed contract binding is invalid")
        projection, control_error = _control_projection(capture["events"], task_id=task_id)
        if control_error is not None:
            raise ValueError(control_error)
        controls = projection["controls"]
        existing = _existing_cancel_response(
            controls, request_id=request_id, record=validated_record,
        )
        if existing is not None:
            return existing
        prepared = [event for event in controls if event.get("handoff_id") == handoff_id and event.get("type") == "handoff_prepared"]
        terminal = [event for event in controls if event.get("handoff_id") == handoff_id and event.get("type") in {"handoff_activated", "handoff_cancelled"}]
        if len(prepared) != 1 or terminal:
            raise ValueError("handoff is not verifiably prepared and inactive")
        event = prepared[0]
        if (
            event.get("record_sha256") != record_digest
            or event.get("expected_controller_generation") != controller_generation
            or event.get("controller_generation") != controller_generation
        ):
            raise ValueError("prepared event binding is invalid")
        if any(event.get("request_id") == request_id for event in controls):
            raise ValueError("cancel request id already belongs to another operation")
        require_subject: Mapping[str, Any] | None = None
        active = projection.get("active")
        if isinstance(active, Mapping):
            active_record, active_digest = _read_handoff_json(
                _paths(task_id, base)["handoff_root"] / f"{active['handoff_id']}.json"
            )
            active_record, active_error = validate_record(active_record)
            if active_error is not None or active_record is None or active_digest != active.get("record_sha256"):
                raise ValueError("active controller record is invalid")
            if validated_record["source_session_ref"] != active_record["target_session_ref"]:
                raise ValueError("cancel source does not match active controller")
            require_subject = active_record["target_session_ref"]
        from . import _handoff_reference_fingerprints
        first_refs = _handoff_reference_fingerprints(validated_record, workspace=workspace)
        arguments = {
            "operation": "cancel_handoff", "task_id": task_id, "base_dir": str(base),
            "workspace_root": str(workspace), "package_root": str(package),
            "request_id": request_id, "controller_generation": controller_generation,
            "handoff_id": handoff_id,
        }
        authorization_request = _authorizer_request(
            operation="cancel_handoff", task_id=task_id, base_dir=base,
            workspace_root=workspace, package_manifest_sha256=manifest_digest,
            contract_version=capture["contract_version"], contract_digest=capture["contract_digest"],
            controller_generation=controller_generation, handoff_id=handoff_id,
            arguments=arguments, runtime_identity=runtime_identity,
        )
        authorization, authorization_error = _authorized_write(
            authorization_request, write_authorizer=write_authorizer, record=validated_record,
            now=datetime.now(timezone.utc), required_subject_session_ref=require_subject,
        )
        if authorization_error is not None:
            raise ValueError(authorization_error)
        verifier_error, _ = _verify_existing_content(
            capture=capture, record=validated_record,
            reference_fingerprints=first_refs, handoff_verifier=handoff_verifier,
        )
        if verifier_error is not None:
            raise ValueError(verifier_error)
        second_refs = _handoff_reference_fingerprints(validated_record, workspace=workspace)
        if second_refs != first_refs:
            raise ValueError("cancel references changed during host verification")
        commit_attempted = True
        return _handoff_cancel_commit(
            task_id, base_dir=base, record=validated_record, capture=capture,
            authorization=authorization, reference_fingerprints=second_refs,
            request_id=request_id, workspace_root=workspace, package_root=package,
        )
    except (ContextError, OSError, TypeError, ValueError) as exc:
        recovered = _recover_committed_cancel(
            task_id, base_dir=base, request_id=request_id, record=validated_record,
        ) if commit_attempted else None
        if recovered is not None:
            return recovered
        return unknown_response(
            str(exc), code="HANDOFF_CANCEL_REJECTED", ref="cancel",
        )


def _delta_events(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]], *, task_id: str,
) -> tuple[list[Mapping[str, Any]] | None, str | None]:
    if len(after) < len(before) or any(
        _canonical_sha256(left) != _canonical_sha256(right)
        for left, right in zip(before, after)
    ):
        return None, "authoritative event history changed non-monotonically"
    delta = list(after[len(before):])
    for event in delta:
        if event.get("event_type") in _EVENT_TYPES:
            return None, "handoff control changed during activation verification"
        if event.get("event_type") != "item-recorded":
            return None, "ordinary delta is not a non-bearing progress event"
        payload = event.get("payload")
        item = payload.get("item") if isinstance(payload, Mapping) else None
        metadata = item.get("metadata") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping) or item.get("type") != "observation"
            or item.get("status") != "active" or item.get("conflicts_with") not in ([], None)
            or item.get("supersedes") is not None or item.get("superseded_by") is not None
            or (isinstance(metadata, Mapping) and any(
                key in metadata and bool(metadata[key]) for key in ("blocking", "blocker", "completed", "completion")
            ))
            or not isinstance(event.get("event_id"), str) or event.get("task_id") != task_id
        ):
            return None, "ordinary delta may affect a bearing task conclusion"
    return delta, None


def _verify_delta(
    verifier: Any, *, before: Mapping[str, Any], after: Mapping[str, Any],
    delta: Sequence[Mapping[str, Any]], record: Mapping[str, Any], now: datetime,
) -> tuple[str | None, datetime | None]:
    verify_delta = getattr(verifier, "verify_delta", None)
    if not callable(verify_delta):
        return "runtime handoff verifier cannot independently verify the ordinary delta", None
    event_ids = [event.get("event_id") for event in delta]
    if not all(isinstance(event_id, str) for event_id in event_ids):
        return "ordinary delta event identity is invalid", None
    request = {
        "task_id": record["task_id"], "handoff_id": record["handoff_id"],
        "record_sha256": _canonical_sha256(record), "contract_version": record["contract_version"],
        "contract_digest": record["contract_digest"], "workspace_root": record["workspace_root"],
        "package_manifest_sha256": record["package_manifest_sha256"],
        "controller_generation": record["controller_generation"],
        "before_events_sha256": before["event_fingerprint"],
        "after_events_sha256": after["event_fingerprint"],
        "delta_event_ids": event_ids, "delta_events_sha256": _canonical_sha256(list(delta)),
        "delta_events": [dict(event) for event in delta], "observed_at": now.isoformat(),
    }
    try:
        result = verify_delta(dict(request))
    except Exception:
        return "runtime handoff verifier delta callback failed", None
    if not isinstance(result, Mapping) or set(result) != _DELTA_VERIFICATION_FIELDS:
        return "runtime handoff verifier delta result is malformed", None
    value = dict(result)
    expected = {
        key: request[key] for key in _DELTA_VERIFICATION_FIELDS
        if key in request and key != "observed_at"
    }
    if value.get("status") != "pass" or value.get("non_bearing") is not True:
        return "runtime handoff verifier did not approve the ordinary delta", None
    if any(type(value.get(key)) is not type(item) or value.get(key) != item for key, item in expected.items()):
        return "runtime handoff verifier delta binding differs from observation", None
    observed_at, expires_at = _as_utc(value.get("observed_at")), _as_utc(value.get("expires_at"))
    if observed_at is None or expires_at is None or observed_at > now or expires_at < now:
        return "runtime handoff verifier delta observation is stale or invalid", None
    return None, expires_at


def activate_handoff(
    task_id: str,
    *, base_dir: str | Path, workspace_root: str | Path, package_root: str | Path,
    request_id: str, controller_generation: int, handoff_id: str,
    runtime_identity: Any = None, write_authorizer: Any = None, handoff_verifier: Any = None,
) -> dict[str, Any]:
    """Activate exactly one currently prepared target after fresh host checks."""
    from . import ContextError, _handoff_activate_commit, _handoff_reference_fingerprints, _paths, _read_handoff_json

    base: Path | None = None
    record: dict[str, Any] | None = None
    commit_attempted = False
    try:
        if not _identifier(request_id) or not _identifier(handoff_id) or type(controller_generation) is not int:
            raise ValueError("activation request identity is invalid")
        base = _normalized_path(base_dir, field="base_dir")
        workspace = _normalized_path(workspace_root, field="workspace_root", require_exists=True)
        package = _normalized_path(package_root, field="package_root", require_exists=True)
        if not workspace.is_dir() or not package.is_dir():
            raise ValueError("activation workspace or package is invalid")
        raw_record, record_digest = _read_handoff_json(_paths(task_id, base)["handoff_root"] / f"{handoff_id}.json")
        record, record_error = validate_record(raw_record)
        if record_error is not None or record is None:
            raise ValueError(record_error or "prepared record is invalid")
        manifest_digest = _package_manifest_sha256(package)
        if (
            record["task_id"] != task_id or record["handoff_id"] != handoff_id
            or record["workspace_root"] != str(workspace)
            or record["package_manifest_sha256"] != manifest_digest
            or record["controller_generation"] != controller_generation
            or record_digest != _canonical_sha256(record)
        ):
            raise ValueError("activation record binding is invalid")
        before = _capture_prepare_inputs(task_id, base_dir=base)
        projection, projection_error = _control_projection(before["events"], task_id=task_id)
        if projection_error is not None:
            raise ValueError(projection_error)
        pending = projection.get("pending")
        if not isinstance(pending, Mapping) or pending.get("handoff_id") != handoff_id:
            existing = [event for event in projection["controls"] if event.get("request_id") == request_id]
            if len(existing) == 1 and existing[0].get("type") == "handoff_activated" and (
                existing[0].get("handoff_id"), existing[0].get("expected_controller_generation"),
                existing[0].get("record_sha256"),
            ) == (handoff_id, controller_generation, record_digest):
                return handoff_status(
                    task_id, base_dir=base, workspace_root=workspace, package_root=package,
                    handoff_id=handoff_id, handoff_verifier=handoff_verifier,
                )
            raise ValueError("handoff is not currently prepared")
        if pending.get("record_sha256") != record_digest or pending.get("controller_generation") != controller_generation:
            raise ValueError("prepared handoff binding is invalid")
        first_refs = _handoff_reference_fingerprints(record, workspace=workspace)
        arguments = {
            "operation": "activate_handoff", "task_id": task_id, "base_dir": str(base),
            "workspace_root": str(workspace), "package_root": str(package), "request_id": request_id,
            "controller_generation": controller_generation, "handoff_id": handoff_id,
        }
        authorization_request = _authorizer_request(
            operation="activate_handoff", task_id=task_id, base_dir=base, workspace_root=workspace,
            package_manifest_sha256=manifest_digest, contract_version=before["contract_version"],
            contract_digest=before["contract_digest"], controller_generation=controller_generation,
            handoff_id=handoff_id, arguments=arguments, runtime_identity=runtime_identity,
        )
        authorization, authorization_error = _authorized_write(
            authorization_request, write_authorizer=write_authorizer, record=record,
            now=datetime.now(timezone.utc), required_subject_session_ref=record["target_session_ref"],
        )
        if authorization_error is not None:
            raise ValueError(authorization_error)
        verifier_error, verifier_expires_at = _verify_existing_content(
            capture={
                "task_id": task_id, "handoff_id": handoff_id, "record": record,
                "record_sha256": record_digest, "contract": before["contract"], "events": before["events"],
                "workspace_root": str(workspace), "package_manifest_sha256": manifest_digest,
            }, record=record, reference_fingerprints=first_refs, handoff_verifier=handoff_verifier,
        )
        if verifier_error is not None:
            raise ValueError(verifier_error)
        if _handoff_reference_fingerprints(record, workspace=workspace) != first_refs:
            raise ValueError("activation references changed during host verification")
        after = _capture_prepare_inputs(task_id, base_dir=base)
        if (
            type(after["contract_version"]) is not type(before["contract_version"])
            or after["contract_version"] != before["contract_version"]
            or after["contract_digest"] != before["contract_digest"]
        ):
            raise ValueError("activation contract changed during host verification")
        delta, delta_error = _delta_events(before["events"], after["events"], task_id=task_id)
        if delta_error is not None:
            raise ValueError(delta_error)
        delta_expires_at: datetime | None = None
        if delta:
            delta_error, delta_expires_at = _verify_delta(
                handoff_verifier, before=before, after=after, delta=delta, record=record,
                now=datetime.now(timezone.utc),
            )
            if delta_error is not None:
                raise ValueError(delta_error)
        commit_attempted = True
        return _handoff_activate_commit(
            task_id, base_dir=base, record=record, capture=after, authorization=authorization,
            reference_fingerprints=first_refs, request_id=request_id, workspace_root=workspace,
            package_root=package, verifier_expires_at=verifier_expires_at,
            delta_expires_at=delta_expires_at,
        )
    except (ContextError, OSError, TypeError, ValueError) as exc:
        if commit_attempted and base is not None and record is not None:
            try:
                recovered = _activation_commit_status(
                    task_id, base_dir=base, handoff_id=handoff_id, request_id=request_id,
                    record=record,
                )
                if recovered is not None:
                    return recovered
            except (ContextError, OSError, TypeError, ValueError):
                pass
        return unknown_response(
            str(exc), code="HANDOFF_ACTIVATION_REJECTED", ref="activate",
            commit_status="unknown" if commit_attempted else "not_attempted",
        )


def _activation_commit_status(
    task_id: str, *, base_dir: Path, handoff_id: str, request_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    capture = _capture_prepare_inputs(task_id, base_dir=base_dir)
    projection, error = _control_projection(capture["events"], task_id=task_id)
    if error is not None:
        return None
    matches = [event for event in projection["controls"] if event.get("request_id") == request_id]
    if len(matches) != 1:
        return None
    event = matches[0]
    if (
        event.get("type") != "handoff_activated" or event.get("handoff_id") != handoff_id
        or event.get("expected_controller_generation") != record.get("controller_generation")
        or event.get("record_sha256") != _canonical_sha256(record)
    ):
        return None
    return {
        "check_status": "pass", "commit_status": "confirmed_committed",
        "controller_generation": event["controller_generation"], "blocking_reasons": [],
        "verification_refs": _record_references(record),
        "next_readonly_action": "Read handoff_status; business completion remains unknown.",
    }


def authorize_direct_write(
    task_id: str, *, base_dir: str | Path | None, operation: str,
    arguments: Mapping[str, Any], runtime_identity: Any, write_authorizer: Any,
) -> dict[str, Any] | None:
    """Fence a legacy public writer whenever authority history exists.

    ``None`` means no handoff directory has ever been created for this task and
    preserves the legacy signature and behavior.  A present but unreadable
    handoff directory is fail-closed rather than silently becoming legacy.
    """
    from . import (
        ContextError, _handoff_reference_fingerprints, _paths, _read_handoff_json,
        _resolve_base_dir, _shared_locked_existing,
    )

    resolved_base, _ = _resolve_base_dir(base_dir)
    base = _normalized_path(resolved_base, field="base_dir")
    paths = _paths(task_id, base)
    handoff_root = paths["handoff_root"]
    if not paths["root"].exists() and not handoff_root.exists():
        return None
    if not handoff_root.exists():
        if not paths["events"].exists():
            return None
        # A missing handoff directory cannot erase a control event.  Legacy
        # item history never had the handoff parser's storage limits, so scan
        # only for that irreversible fact instead of rebuilding the log.
        try:
            with _shared_locked_existing(paths["root"]):
                control_seen = _legacy_control_event_present(paths["events"], task_id=task_id)
        except (ContextError, OSError, TypeError, ValueError) as exc:
            raise ContextError(
                "HANDOFF_WRITE_FENCED: authoritative event history is unreadable"
            ) from exc
        if not control_seen:
            return None
        raise ContextError("HANDOFF_WRITE_FENCED: handoff record directory is missing")
    try:
        if handoff_root.exists() and (handoff_root.is_symlink() or not handoff_root.is_dir()):
            raise ContextError("handoff record directory is unsafe")
        capture = _capture_prepare_inputs(task_id, base_dir=base)
        controls, error = _control_events(capture["events"], task_id=task_id)
        if error is not None:
            raise ContextError(error)
        if not controls:
            if handoff_root.exists():
                raise ContextError("handoff authority history is unavailable")
            return None
        if not handoff_root.exists():
            raise ContextError("handoff record directory is missing")
        projection, projection_error = _control_projection(capture["events"], task_id=task_id)
        if projection_error is not None:
            raise ContextError(projection_error)
        pending = projection.get("pending")
        active = projection.get("active")
        cancelled = projection.get("cancelled")
        if isinstance(pending, Mapping):
            control_event = pending
            phase = "prepared"
        elif isinstance(active, Mapping):
            control_event = active
            phase = "activated"
        elif isinstance(cancelled, Mapping):
            control_event = cancelled
            phase = "cancelled"
        else:
            raise ContextError("handoff authority history has no current controller")
        handoff_id = control_event.get("handoff_id")
        if not _identifier(handoff_id):
            raise ContextError("handoff authority identity is invalid")
        record, digest = _read_handoff_json(handoff_root / f"{handoff_id}.json")
        record, record_error = validate_record(record)
        if record_error is not None or record is None or digest != control_event.get("record_sha256"):
            raise ContextError("handoff authority record is invalid")
        if (
            record["workspace_root"] == "" or record["package_manifest_sha256"] == ""
            or type(record["contract_version"]) is not type(capture["contract_version"])
            or record["contract_version"] != capture["contract_version"]
            or record["contract_digest"] != capture["contract_digest"]
        ):
            raise ContextError("handoff authority binding is invalid")
        current_generation = control_event.get("controller_generation")
        if type(current_generation) is not int:
            raise ContextError("handoff controller generation is invalid")
        normalized_arguments = {"operation": operation, "task_id": task_id, "base_dir": str(base), **dict(arguments)}
        request = _authorizer_request(
            operation=operation, task_id=task_id, base_dir=base,
            workspace_root=Path(record["workspace_root"]),
            package_manifest_sha256=record["package_manifest_sha256"],
            contract_version=record["contract_version"], contract_digest=record["contract_digest"],
            controller_generation=current_generation, handoff_id=handoff_id,
            arguments=normalized_arguments, runtime_identity=runtime_identity,
        )
        allowed_roles = frozenset({"child"}) if phase == "prepared" else frozenset({"controller", "child"})
        required_session = (
            record["target_session_ref"] if phase == "activated"
            else record["source_session_ref"] if phase == "cancelled" else None
        )
        authorization, auth_error = _authorized_write(
            request, write_authorizer=write_authorizer, record=record,
            now=datetime.now(timezone.utc), allowed_roles=allowed_roles,
            require_work_item=phase == "prepared", required_subject_session_ref=required_session,
            allowed_target_activation_status=(frozenset({"activated"}) if phase == "activated"
                                              else frozenset({"not_activated"})),
        )
        if auth_error is not None:
            raise ContextError(auth_error)
        if phase == "prepared" and authorization.get("purpose") not in {"progress", "result"}:
            raise ContextError("prepared handoff only permits child progress or result")
        fingerprints = _handoff_reference_fingerprints(record, workspace=Path(record["workspace_root"]))
        return {
            "capture": capture, "authorization": authorization, "record": record,
            "reference_fingerprints": fingerprints, "phase": phase,
            "controller_generation": current_generation,
        }
    except (ContextError, OSError, TypeError, ValueError) as exc:
        raise ContextError("HANDOFF_WRITE_FENCED: " + str(exc)) from exc
