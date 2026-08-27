"""Fact-grounded context control for long, multi-agent tasks.

The module keeps one publisher-owned task contract, one append-only event log,
and one rebuildable snapshot per task. It is designed for Prime Agent project
skills but uses only the Python standard library.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evidence import MAX_CLOCK_SKEW_SECONDS, canonical_json_bytes, evaluate_evidence

try:  # Prime Agent targets macOS/Linux; keep a safe fallback for other runtimes.
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

SCHEMA_VERSION = 1
ITEM_TYPES = {"observation", "verified-fact", "assumption", "decision", "question"}
ITEM_STATUSES = {"active", "unverified", "conflicted", "superseded"}
GATE_STAGES = {"release", "resume", "handoff", "completion"}
DEFAULT_BASE_DIR = Path(".prime/context")
_POINTER_RE = re.compile(
    r"(?:详见|参见|见|see)\s*[`'\"]([^`'\"]+\.(?:md|txt|json|ya?ml))[`'\"]",
    re.IGNORECASE,
)
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
_EXPLICIT_UTC_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z"
)
_DELIVERY_RECEIPT_STRING_FIELDS = (
    "delivery_type",
    "channel",
    "target_id",
    "artifact_ref",
    "external_id",
    "verification_method",
)
_DELIVERY_RECEIPT_TIME_FIELDS = ("sent_at", "observed_at")


class ContextError(RuntimeError):
    """Raised when a context quality rule blocks an operation."""


class _EventReadError(ContextError):
    """Internal JSONL error carrying the number of attempted event records."""

    def __init__(self, message: str, *, attempted: int) -> None:
        super().__init__(message)
        self.attempted = attempted


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trusted_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _task_dir(task_id: str, base_dir: str | Path | None = None) -> Path:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id.strip()).strip("-")
    if not safe:
        raise ValueError("task_id contains no usable characters")
    return Path(base_dir or DEFAULT_BASE_DIR).expanduser().resolve() / safe


def _paths(task_id: str, base_dir: str | Path | None = None) -> dict[str, Path]:
    root = _task_dir(task_id, base_dir)
    return {
        "root": root,
        "contract": root / "task-contract.json",
        "events": root / "events.jsonl",
        "snapshot": root / "snapshot.json",
        "lock": root / ".lock",
    }


@contextmanager
def _locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContextError(f"missing required file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextError(f"expected JSON object in {path}")
    return value


def _canonical_contract(contract: Mapping[str, Any]) -> bytes:
    value = deepcopy(dict(contract))
    seal = value.get("seal")
    if isinstance(seal, dict):
        seal.pop("integrity_digest", None)
    return canonical_json_bytes(value)


def _contract_digest(contract: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_contract(contract)).hexdigest()


def _version_key(value: Any) -> tuple[int, str]:
    if isinstance(value, int):
        return value, str(value)
    if isinstance(value, float):
        return int(value), str(value)
    text = str(value)
    match = re.search(r"\d+", text)
    return (int(match.group(0)) if match else 0), text


def _validate_contract_shape(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required_strings = ("task_id", "issued_by", "issued_at", "objective")
    for field in required_strings:
        if not isinstance(contract.get(field), str) or not str(contract[field]).strip():
            errors.append(f"contract.{field} must be a non-empty string")
    if "version" not in contract:
        errors.append("contract.version is required")
    for field in ("scope", "out_of_scope", "constraints"):
        value = contract.get(field)
        if not isinstance(value, list):
            errors.append(f"contract.{field} must be a list")
    authorized_approvers = contract.get("authorized_approvers")
    if not _valid_string_list(authorized_approvers, allow_empty=True):
        errors.append(
            "contract.authorized_approvers must be a unique list of non-empty actor IDs"
        )
    criteria = contract.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("contract.acceptance_criteria must contain publisher-written criteria")
        return errors

    actor_roles = contract.get("actor_roles")
    if actor_roles is not None:
        if not isinstance(actor_roles, Mapping):
            errors.append("contract.actor_roles must map actor IDs to role lists")
        else:
            allowed_roles = {"publisher", "executor", "validator"}
            for actor, roles in actor_roles.items():
                if not isinstance(actor, str) or not actor.strip():
                    errors.append("contract.actor_roles keys must be non-empty actor IDs")
                    continue
                if not isinstance(roles, list) or not roles or not all(
                    isinstance(role, str) and role in allowed_roles for role in roles
                ):
                    errors.append(
                        f"contract.actor_roles[{actor!r}] must be a non-empty list of publisher/executor/validator roles"
                    )

    seen: set[str] = set()
    for index, criterion in enumerate(criteria):
        prefix = f"acceptance_criteria[{index}]"
        if not isinstance(criterion, dict):
            errors.append(f"{prefix} must be an object")
            continue
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif criterion_id in seen:
            errors.append(f"duplicate acceptance criterion id: {criterion_id}")
        else:
            seen.add(criterion_id)
        if not isinstance(criterion.get("criterion"), str) or not criterion["criterion"].strip():
            errors.append(f"{prefix}.criterion must be a non-empty string")
        required_evidence = criterion.get("required_evidence_types")
        compatibility_evidence = criterion.get("required_evidence")
        if required_evidence is not None and compatibility_evidence is not None:
            if required_evidence != compatibility_evidence:
                errors.append(
                    f"{prefix}.required_evidence_types conflicts with compatibility alias required_evidence"
                )
        evidence_key = (
            "required_evidence_types"
            if required_evidence is not None
            else "required_evidence"
        )
        evidence_value = required_evidence if required_evidence is not None else compatibility_evidence
        if not _valid_string_list(evidence_value, allow_empty=False):
            errors.append(f"{prefix}.{evidence_key} must be a non-empty list of non-empty strings")

        required_hops = criterion.get("required_hops")
        compatibility_hops = criterion.get("chain_hops")
        if required_hops is not None and compatibility_hops is not None:
            if required_hops != compatibility_hops:
                errors.append(
                    f"{prefix}.required_hops conflicts with compatibility alias chain_hops"
                )
        hops_value = required_hops if required_hops is not None else compatibility_hops
        if hops_value is not None and not _valid_string_list(hops_value, allow_empty=True):
            errors.append(f"{prefix}.required_hops must be a list of non-empty strings")

        delivery_types = criterion.get("required_delivery_types")
        if delivery_types is not None and not _valid_string_list(delivery_types, allow_empty=True):
            errors.append(f"{prefix}.required_delivery_types must be a list of non-empty strings")

        required_scope = criterion.get("required_scope")
        if required_scope is not None and not isinstance(required_scope, Mapping):
            errors.append(f"{prefix}.required_scope must be an object when present")

        maximum = criterion.get("max_evidence_age_seconds")
        if maximum is not None and not _valid_age_window(maximum):
            errors.append(f"{prefix}.max_evidence_age_seconds must be a non-negative integer")
        overrides = criterion.get("evidence_freshness_by_type")
        if overrides is not None:
            if not isinstance(overrides, Mapping):
                errors.append(f"{prefix}.evidence_freshness_by_type must be an object")
            else:
                for kind, window in overrides.items():
                    if not isinstance(kind, str) or not kind.strip() or not _valid_age_window(window):
                        errors.append(
                            f"{prefix}.evidence_freshness_by_type entries require non-empty kinds and non-negative integer windows"
                        )

        independent = criterion.get("independent_validation_required")
        if independent is not None and not isinstance(independent, bool):
            errors.append(f"{prefix}.independent_validation_required must be a boolean")
        if independent is True:
            validators = []
            if isinstance(actor_roles, Mapping):
                validators = [
                    actor
                    for actor, roles in actor_roles.items()
                    if isinstance(roles, list) and "validator" in roles
                ]
            if not validators:
                errors.append(
                    f"{prefix}.independent_validation_required needs contract.actor_roles with a validator"
                )

        errors.extend(_criterion_revision_shape_errors(criterion, prefix))
    return errors


def _valid_string_list(value: Any, *, allow_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
        and len(value) == len(set(value))
    )


def _valid_age_window(value: Any) -> bool:
    return type(value) is int and value >= 0


def _parse_explicit_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or _EXPLICIT_UTC_RFC3339_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _valid_explicit_utc_timestamp(value: Any) -> bool:
    return _parse_explicit_utc_timestamp(value) is not None


def _valid_delivery_receipt(value: Mapping[str, Any]) -> bool:
    return (
        value.get("kind") == "delivery-receipt"
        and all(
            isinstance(value.get(field), str) and bool(str(value[field]).strip())
            for field in _DELIVERY_RECEIPT_STRING_FIELDS
        )
        and all(
            _valid_explicit_utc_timestamp(value.get(field))
            for field in _DELIVERY_RECEIPT_TIME_FIELDS
        )
    )


def _criterion_revision_shape_errors(criterion: Mapping[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    scope = criterion.get("required_scope")
    scope_value = scope if isinstance(scope, Mapping) else {}
    revisions = [
        value
        for value in (
            criterion.get("required_revision"),
            criterion.get("required_repo_revision"),
            scope_value.get("repo_revision"),
            scope_value.get("revision"),
        )
        if value is not None
    ]
    normalized_revisions = {str(value) for value in revisions}
    if len(normalized_revisions) > 1:
        errors.append(f"{prefix} has conflicting revision requirements")
    if any(not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None for value in revisions):
        errors.append(f"{prefix}.required_revision must be a 40-hex Git commit")

    modes = [
        value
        for value in (
            criterion.get("revision_match"),
            criterion.get("revision_mode"),
            scope_value.get("revision_match"),
            scope_value.get("revision_mode"),
        )
        if value is not None
    ]
    normalized_modes = {str(value) for value in modes}
    if len(normalized_modes) > 1:
        errors.append(f"{prefix} has conflicting revision match modes")
    if any(value not in {"exact", "ancestor"} for value in modes):
        errors.append(f"{prefix}.revision_match must be exact or ancestor")
    if modes and not revisions:
        errors.append(f"{prefix}.revision_match requires required_revision")
    return errors


def _validate_sealed_contract(contract: Mapping[str, Any]) -> list[str]:
    errors = _validate_contract_shape(contract)
    seal = contract.get("seal")
    if not isinstance(seal, dict):
        errors.append("contract is not sealed by the task publisher")
        return errors
    if "digest" in seal:
        errors.append("contract.seal.digest is unsupported; use contract.seal.integrity_digest")
    for field in ("confirmed_by", "confirmed_at"):
        if not isinstance(seal.get(field), str) or not seal[field].strip():
            errors.append(f"contract.seal.{field} must be a non-empty string")
    integrity_digest = seal.get("integrity_digest")
    if not isinstance(integrity_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", integrity_digest) is None:
        errors.append("contract.seal.integrity_digest must be sha256:<64 lowercase hex>")
    elif integrity_digest != _contract_digest(contract):
        errors.append("contract integrity digest is invalid: contract changed after publication")
    authorized = {str(contract.get("issued_by", ""))}
    approvers = contract.get("authorized_approvers", [])
    if isinstance(approvers, list):
        authorized.update(str(item) for item in approvers)
    if isinstance(seal, dict) and seal.get("confirmed_by") not in authorized:
        errors.append("contract was sealed by an unauthorized actor")
    return errors


def _empty_snapshot(task_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "task_id": task_id,
        "contract": None,
        "items": {},
        "latest_checkpoint": None,
        "event_count": 0,
        "updated_at": None,
    }


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    attempted = 0
    try:
        if not path.exists():
            return []
        handle = path.open("rb")
    except OSError as exc:
        raise _EventReadError(
            f"cannot read event log {path}: {exc}",
            attempted=0,
        ) from exc
    with handle:
        line_no = 0
        while True:
            try:
                raw_line = handle.readline()
            except OSError as exc:
                raise _EventReadError(
                    f"cannot read event log {path}: {exc}",
                    attempted=attempted + 1,
                ) from exc
            if not raw_line:
                break
            line_no += 1
            if not raw_line.strip():
                continue
            attempted += 1
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _EventReadError(
                    f"invalid UTF-8 in event log at {path}:{line_no}: {exc}",
                    attempted=attempted,
                ) from exc
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise _EventReadError(
                    f"invalid JSONL at {path}:{line_no}: {exc}",
                    attempted=attempted,
                ) from exc
            if not isinstance(event, dict):
                raise _EventReadError(
                    f"event at {path}:{line_no} is not an object",
                    attempted=attempted,
                )
            events.append(event)
    return events


def _apply_event(snapshot: dict[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(snapshot)
    event_type = event.get("event_type")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    if event_type == "contract-published":
        result["contract"] = deepcopy(payload)
    elif event_type in {"item-recorded", "item-updated"}:
        item = payload.get("item")
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.setdefault("items", {})[item["id"]] = deepcopy(item)
    elif event_type == "checkpoint-recorded":
        checkpoint_value = payload.get("checkpoint")
        if isinstance(checkpoint_value, dict):
            result["latest_checkpoint"] = deepcopy(checkpoint_value)
    result["event_count"] = int(result.get("event_count", 0)) + 1
    result["updated_at"] = event.get("created_at")
    return result


def _rebuild_snapshot(task_id: str, events_path: Path) -> dict[str, Any]:
    snapshot = _empty_snapshot(task_id)
    for event in _read_events(events_path):
        snapshot = _apply_event(snapshot, event)
    return snapshot


def _load_snapshot(task_id: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    try:
        snapshot = _read_json(paths["snapshot"])
    except ContextError:
        return _rebuild_snapshot(task_id, paths["events"])
    return snapshot


def _append_event_locked(paths: Mapping[str, Path], snapshot: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    paths["events"].parent.mkdir(parents=True, exist_ok=True)
    with paths["events"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    updated = _apply_event(snapshot, event)
    _atomic_write_json(paths["snapshot"], updated)
    return updated


def _new_event(task_id: str, event_type: str, actor: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "event_id": f"EV-{uuid.uuid4().hex[:12]}",
        "task_id": task_id,
        "event_type": event_type,
        "actor": actor,
        "created_at": _now(),
        "payload": _json_clone(payload),
    }


def _normalize_source(source: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, str):
        if not source.strip():
            raise ValueError("source must not be empty")
        return {"kind": "unspecified", "ref": source.strip()}
    if not isinstance(source, Mapping):
        raise TypeError("source must be a string or mapping")
    result = dict(source)
    if not isinstance(result.get("kind"), str) or not result["kind"].strip():
        raise ValueError("source.kind must be a non-empty string")
    if not isinstance(result.get("ref"), str) or not result["ref"].strip():
        raise ValueError("source.ref must be a non-empty string")
    return _json_clone(result)


def _normalize_list(value: Sequence[Any] | Any | None) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [_json_clone(value)]
    if isinstance(value, Sequence):
        return [_json_clone(item) for item in value]
    return [_json_clone(value)]


def _normalize_scope(scope: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if scope is None:
        return {}
    if isinstance(scope, str):
        return {"description": scope}
    if isinstance(scope, Mapping):
        return _json_clone(dict(scope))
    raise TypeError("scope must be a string, mapping, or None")


def _item_errors(item: Mapping[str, Any], now: datetime | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    item_id = item.get("id", "<unknown>")
    item_type = item.get("type")
    status = item.get("status")
    if item_type not in ITEM_TYPES:
        errors.append(f"{item_id}: invalid type {item_type!r}")
    if status not in ITEM_STATUSES:
        errors.append(f"{item_id}: invalid status {status!r}")
    if not isinstance(item.get("statement"), str) or not item["statement"].strip():
        errors.append(f"{item_id}: statement is required")
    source = item.get("source")
    if not isinstance(source, dict) or not source.get("kind") or not source.get("ref"):
        errors.append(f"{item_id}: source.kind and source.ref are required")
    if item_type == "verified-fact":
        if not item.get("evidence"):
            errors.append(f"{item_id}: verified-fact requires evidence")
        if not item.get("verification_method"):
            errors.append(f"{item_id}: verified-fact requires verification_method")
        if not item.get("scope"):
            errors.append(f"{item_id}: verified-fact requires scope")
        if not item.get("verified_at"):
            errors.append(f"{item_id}: verified-fact requires verified_at")
        if isinstance(source, dict) and source.get("kind") == "agent-inference":
            errors.append(f"{item_id}: verified-fact cannot use agent-inference as its primary source")
    if item_type in {"assumption", "question"} and status == "active":
        warnings.append(f"{item_id}: {item_type} should normally remain unverified until resolved")
    if status == "conflicted" and not item.get("conflict_reason"):
        errors.append(f"{item_id}: conflicted item requires conflict_reason")
    if status == "superseded" and not item.get("superseded_by"):
        warnings.append(f"{item_id}: superseded item has no superseded_by pointer")
    if item.get("mutable"):
        verified_at = _parse_time(item.get("verified_at"))
        ttl = item.get("ttl_hours")
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            warnings.append(f"{item_id}: mutable fact has no positive ttl_hours")
        elif verified_at is None:
            errors.append(f"{item_id}: mutable fact requires a valid verified_at")
        else:
            current = now or datetime.now(timezone.utc)
            if current > verified_at + timedelta(hours=float(ttl)):
                warnings.append(f"{item_id}: mutable fact is stale and must be re-observed")
    return errors, warnings


def _emit_report(report: Mapping[str, Any]) -> None:
    stats = report.get("stats", {}) if isinstance(report.get("stats"), dict) else {}
    checked = stats.get("checked", 0)
    errors = report.get("errors", []) if isinstance(report.get("errors"), list) else []
    warnings = report.get("warnings", []) if isinstance(report.get("warnings"), list) else []
    stage = report.get("stage", "audit")
    probe = stats.get("probe", "unknown")
    print(f"[{stage}] checked {checked}; errors {len(errors)}; warnings {len(warnings)}; probe {probe}")
    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARN: {message}")


def publish_contract(
    contract: Mapping[str, Any],
    *,
    confirmed_by: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Validate, seal, and publish a publisher-authored task contract.

    Updating an existing contract requires a greater version and a fresh seal.
    """

    value = deepcopy(dict(contract))
    value.setdefault("schema", SCHEMA_VERSION)
    value.setdefault("authorized_approvers", [])
    errors = _validate_contract_shape(value)
    if errors:
        raise ContextError("contract rejected: " + "; ".join(errors))
    try:
        value = _json_clone(value)
    except (TypeError, ValueError) as exc:
        raise ContextError(f"contract rejected: contract must be JSON-compatible: {exc}") from exc
    authorized = {str(value["issued_by"])} | {str(item) for item in value.get("authorized_approvers", [])}
    if confirmed_by not in authorized:
        raise ContextError("confirmed_by must be the task publisher or an authorized approver")

    task_id = str(value["task_id"])
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        if paths["contract"].exists():
            existing = _read_json(paths["contract"])
            existing_errors = _validate_sealed_contract(existing)
            if existing_errors:
                raise ContextError("existing contract is invalid: " + "; ".join(existing_errors))
            if _version_key(value["version"]) <= _version_key(existing.get("version")):
                raise ContextError("contract update requires a greater version")

        value.pop("seal", None)
        value["seal"] = {
            "confirmed_by": confirmed_by,
            "confirmed_at": _now(),
        }
        value["seal"]["integrity_digest"] = _contract_digest(value)
        _atomic_write_json(paths["contract"], value)
        snapshot = _load_snapshot(task_id, paths)
        event = _new_event(
            task_id,
            "contract-published",
            confirmed_by,
            {
                "task_id": task_id,
                "version": value["version"],
                "integrity_digest": value["seal"]["integrity_digest"],
                "confirmed_by": confirmed_by,
                "confirmed_at": value["seal"]["confirmed_at"],
            },
        )
        _append_event_locked(paths, snapshot, event)
    return value


def record(
    task_id: str,
    *,
    statement: str,
    item_type: str,
    actor: str,
    source: str | Mapping[str, Any],
    evidence: Sequence[Any] | Any | None = None,
    scope: str | Mapping[str, Any] | None = None,
    verification_method: str | None = None,
    mutable: bool = False,
    ttl_hours: float | None = None,
    item_id: str | None = None,
    supersedes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append one context item without overwriting prior history."""

    if item_type not in ITEM_TYPES:
        raise ValueError(f"item_type must be one of {sorted(ITEM_TYPES)}")
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("statement must be a non-empty string")
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        contract = _read_json(paths["contract"])
        contract_errors = _validate_sealed_contract(contract)
        if contract_errors:
            raise ContextError("release gate failed: " + "; ".join(contract_errors))
        snapshot = _load_snapshot(task_id, paths)
        items = snapshot.setdefault("items", {})
        identifier = item_id or f"C-{uuid.uuid4().hex[:10]}"
        if identifier in items:
            raise ContextError(f"context item already exists: {identifier}")
        now = _now()
        status = "active"
        if item_type in {"assumption", "question"}:
            status = "unverified"
        item = {
            "id": identifier,
            "statement": statement.strip(),
            "type": item_type,
            "status": status,
            "actor": actor,
            "source": _normalize_source(source),
            "evidence": _normalize_list(evidence),
            "scope": _normalize_scope(scope),
            "verification_method": verification_method,
            "mutable": bool(mutable),
            "ttl_hours": ttl_hours,
            "verified_at": now if item_type == "verified-fact" else None,
            "created_at": now,
            "updated_at": now,
            "supersedes": supersedes,
            "superseded_by": None,
            "conflicts_with": [],
            "conflict_reason": None,
            "metadata": _json_clone(dict(metadata or {})),
        }
        errors, _ = _item_errors(item)
        if errors:
            raise ContextError("context item rejected: " + "; ".join(errors))

        if supersedes:
            old = items.get(supersedes)
            if not isinstance(old, dict):
                raise ContextError(f"cannot supersede missing item: {supersedes}")
            old_updated = deepcopy(old)
            old_updated["status"] = "superseded"
            old_updated["superseded_by"] = identifier
            old_updated["updated_at"] = now
            old_event = _new_event(task_id, "item-updated", actor, {"item": old_updated})
            snapshot = _append_event_locked(paths, snapshot, old_event)

        event = _new_event(task_id, "item-recorded", actor, {"item": item})
        _append_event_locked(paths, snapshot, event)
    return item


def update_item(
    task_id: str,
    item_id: str,
    *,
    actor: str,
    promote_to: str | None = None,
    status: str | None = None,
    evidence: Sequence[Any] | Any | None = None,
    source: str | Mapping[str, Any] | None = None,
    verification_method: str | None = None,
    scope: str | Mapping[str, Any] | None = None,
    conflicts_with: Sequence[str] | None = None,
    conflict_reason: str | None = None,
    superseded_by: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and append a state transition for an existing item."""

    if promote_to is not None and promote_to not in ITEM_TYPES:
        raise ValueError(f"promote_to must be one of {sorted(ITEM_TYPES)}")
    if status is not None and status not in ITEM_STATUSES:
        raise ValueError(f"status must be one of {sorted(ITEM_STATUSES)}")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        contract = _read_json(paths["contract"])
        contract_errors = _validate_sealed_contract(contract)
        if contract_errors:
            raise ContextError("release gate failed: " + "; ".join(contract_errors))
        snapshot = _load_snapshot(task_id, paths)
        current = snapshot.get("items", {}).get(item_id)
        if not isinstance(current, dict):
            raise ContextError(f"unknown context item: {item_id}")
        updated = deepcopy(current)
        now = _now()
        if promote_to is not None:
            updated["type"] = promote_to
        if status is not None:
            updated["status"] = status
        if evidence is not None:
            updated["evidence"] = _normalize_list(evidence)
        if source is not None:
            updated["source"] = _normalize_source(source)
        if verification_method is not None:
            updated["verification_method"] = verification_method
        if scope is not None:
            updated["scope"] = _normalize_scope(scope)
        if conflicts_with is not None:
            updated["conflicts_with"] = list(conflicts_with)
        if conflict_reason is not None:
            updated["conflict_reason"] = conflict_reason
        if superseded_by is not None:
            updated["superseded_by"] = superseded_by
            updated["status"] = "superseded"
        if metadata is not None:
            merged = dict(updated.get("metadata") or {})
            merged.update(_json_clone(dict(metadata)))
            updated["metadata"] = merged
        if updated.get("type") == "verified-fact":
            if updated.get("status") not in {"conflicted", "superseded"}:
                updated["status"] = "active"
            updated["verified_at"] = now
        updated["actor"] = actor
        updated["updated_at"] = now
        errors, _ = _item_errors(updated)
        if errors:
            raise ContextError("context transition rejected: " + "; ".join(errors))
        event = _new_event(task_id, "item-updated", actor, {"item": updated})
        _append_event_locked(paths, snapshot, event)
    return updated


def checkpoint(
    task_id: str,
    *,
    phase: str,
    completed: Sequence[str],
    evidence_added: Sequence[Any],
    next_action: str,
    actor: str,
    blockers: Sequence[str] | None = None,
    related_item_ids: Sequence[str] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Record a concise delta checkpoint; do not rewrite the task history."""

    if not phase.strip() or not next_action.strip():
        raise ValueError("phase and next_action must be non-empty")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        contract = _read_json(paths["contract"])
        contract_errors = _validate_sealed_contract(contract)
        if contract_errors:
            raise ContextError("release gate failed: " + "; ".join(contract_errors))
        snapshot = _load_snapshot(task_id, paths)
        checkpoint_value = {
            "id": f"CP-{uuid.uuid4().hex[:10]}",
            "phase": phase.strip(),
            "completed": [str(item) for item in completed],
            "evidence_added": _normalize_list(evidence_added),
            "blockers": [str(item) for item in (blockers or [])],
            "related_item_ids": [str(item) for item in (related_item_ids or [])],
            "next_action": next_action.strip(),
            "based_on_context_version": snapshot.get("event_count", 0),
            "actor": actor,
            "created_at": _now(),
        }
        event = _new_event(task_id, "checkpoint-recorded", actor, {"checkpoint": checkpoint_value})
        _append_event_locked(paths, snapshot, event)
    return checkpoint_value


def _item_is_stale(item: Mapping[str, Any]) -> bool:
    if not item.get("mutable"):
        return False
    verified = _parse_time(item.get("verified_at"))
    ttl = item.get("ttl_hours")
    if verified is None or not isinstance(ttl, (int, float)) or ttl <= 0:
        return True
    return datetime.now(timezone.utc) > verified + timedelta(hours=float(ttl))


_BRIEF_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _brief_priority(item: Mapping[str, Any]) -> int:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if metadata.get("required") is True:
        return 0
    if item.get("status") == "conflicted":
        return 1
    if metadata.get("blocker") is True:
        return 2
    return {
        "decision": 3,
        "verified-fact": 4,
        "assumption": 5,
        "observation": 6,
        "question": 7,
    }.get(str(item.get("type")), 8)


def _brief_sort_key(item: Mapping[str, Any]) -> tuple[int, int, int, float, str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    severity = _BRIEF_SEVERITY.get(str(metadata.get("severity", "")).lower(), len(_BRIEF_SEVERITY))
    updated_at = item.get("updated_at")
    parsed = _parse_time(updated_at) if isinstance(updated_at, str) else None
    if parsed is None:
        return (_brief_priority(item), severity, 1, 0.0, str(item.get("id", "")))
    return (_brief_priority(item), severity, 0, -parsed.timestamp(), str(item.get("id", "")))


def _brief_selection_packet(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected = [dict(item) for item in items]
    return {
        "task_id": "",
        "contract_version": None,
        "objective": "",
        "scope": [],
        "out_of_scope": [],
        "constraints": [],
        "actor_roles": {},
        "acceptance_criteria": [],
        "phase": None,
        "facts": [item for item in selected if item.get("type") == "verified-fact"],
        "observations": [item for item in selected if item.get("type") == "observation"],
        "assumptions": [item for item in selected if item.get("type") == "assumption"],
        "decisions": [item for item in selected if item.get("type") == "decision"],
        "questions": [item for item in selected if item.get("type") == "question"],
        "conflicts": [item for item in selected if item.get("status") == "conflicted"],
        "latest_checkpoint": None,
    }


def _brief_is_mandatory(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return metadata.get("required") is True or item.get("status") == "conflicted"


def _select_brief_items(
    items: Sequence[Mapping[str, Any]], *, max_chars: int, max_items: int | None
) -> list[dict[str, Any]]:
    """Select ordered items only when the fully rendered candidate still fits."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be positive")

    ordered = sorted((dict(item) for item in items), key=_brief_sort_key)
    if max_items is not None:
        omitted = ordered[max_items:]
        if any(_brief_is_mandatory(item) for item in omitted):
            raise ContextError("BRIEF_REQUIRED_OVERFLOW: max_items would omit a mandatory item")
        ordered = ordered[:max_items]

    selected: list[dict[str, Any]] = []
    for item in ordered:
        mandatory = _brief_is_mandatory(item)
        candidate = [*selected, item]
        candidate_prompt = _brief_to_markdown(_brief_selection_packet(candidate))
        if len(candidate_prompt) <= max_chars:
            selected = candidate
        elif mandatory:
            raise ContextError("BRIEF_REQUIRED_OVERFLOW: mandatory items exceed max_chars")
    return selected


def brief(
    task_id: str,
    *,
    phase: str | None = None,
    include: Sequence[str] | None = None,
    max_items: int | None = None,
    max_chars: int = 8000,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a minimal active-context/handoff packet from controlled state."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be positive")
    paths = _paths(task_id, base_dir)
    contract = _read_json(paths["contract"])
    contract_errors = _validate_sealed_contract(contract)
    if contract_errors:
        raise ContextError("release gate failed: " + "; ".join(contract_errors))
    snapshot = _load_snapshot(task_id, paths)
    all_items = snapshot.get("items", {})
    if not isinstance(all_items, dict):
        all_items = {}
    candidates: list[dict[str, Any]] = []
    include_set = set(include or [])
    for identifier, raw in sorted(all_items.items()):
        if not isinstance(raw, dict):
            continue
        if include is not None and identifier not in include_set:
            continue
        if raw.get("status") == "superseded":
            continue
        candidates.append(deepcopy(raw))

    def build_packet(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        selected_items = [dict(item) for item in selected]
        return {
            "task_id": task_id,
            "contract_version": contract.get("version"),
            "contract_integrity_digest": contract.get("seal", {}).get("integrity_digest"),
            "objective": contract.get("objective"),
            "scope": contract.get("scope", []),
            "out_of_scope": contract.get("out_of_scope", []),
            "constraints": contract.get("constraints", []),
            "actor_roles": deepcopy(contract.get("actor_roles", {})),
            "acceptance_criteria": contract.get("acceptance_criteria", []),
            "phase": phase or (snapshot.get("latest_checkpoint") or {}).get("phase"),
            "facts": [item for item in selected_items if item.get("type") == "verified-fact"],
            "observations": [item for item in selected_items if item.get("type") == "observation"],
            "assumptions": [item for item in selected_items if item.get("type") == "assumption"],
            "decisions": [item for item in selected_items if item.get("type") == "decision"],
            "questions": [item for item in selected_items if item.get("type") == "question"],
            "conflicts": [item for item in selected_items if item.get("status") == "conflicted"],
            "stale_items": [item["id"] for item in selected_items if _item_is_stale(item)],
            "latest_checkpoint": snapshot.get("latest_checkpoint"),
            "context_version": snapshot.get("event_count", 0),
        }

    empty_packet = build_packet([])
    empty_selection_packet = _brief_selection_packet([])
    # Selection changes only the item sections.  Account for the real
    # contract/checkpoint wrapper once, while keeping candidate rendering in
    # _select_brief_items deterministic and independent of task I/O.
    fixed_length = len(_brief_to_markdown(empty_packet)) - len(_brief_to_markdown(empty_selection_packet))
    selection_budget = max_chars - fixed_length
    if selection_budget <= 0:
        raise ContextError("BRIEF_REQUIRED_OVERFLOW: fixed brief content exceeds max_chars")

    selected = _select_brief_items(
        candidates,
        max_chars=selection_budget,
        max_items=max_items,
    )
    packet = build_packet(selected)
    packet["prompt"] = _brief_to_markdown(packet)
    if len(packet["prompt"]) > max_chars:
        raise ContextError("BRIEF_REQUIRED_OVERFLOW: brief content exceeds max_chars")
    return packet


def _brief_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _brief_item_to_markdown(item: Mapping[str, Any]) -> str:
    statement = item.get("criterion") or item.get("statement") or _brief_json(dict(item))
    fields = [
        f"status={item.get('status')}",
        f"source={_brief_json(item.get('source'))}",
        f"evidence={_brief_json(item.get('evidence') or [])}",
        f"scope={_brief_json(item.get('scope') or {})}",
        f"verified_at={item.get('verified_at')}",
        f"updated_at={item.get('updated_at')}",
    ]
    if item.get("conflicts_with"):
        fields.append(f"conflicts_with={_brief_json(item['conflicts_with'])}")
    if item.get("conflict_reason") is not None:
        fields.append(f"conflict_reason={_brief_json(item['conflict_reason'])}")
    metadata = item.get("metadata")
    if isinstance(metadata, dict) and metadata:
        fields.append(f"metadata={_brief_json(metadata)}")
    return f"- {item.get('id', '')}: {statement} | " + " | ".join(fields)


def _brief_acceptance_to_markdown(criterion: Mapping[str, Any]) -> str:
    text = criterion.get("criterion") or criterion.get("statement") or _brief_json(dict(criterion))
    fields = [f"- {criterion.get('id', '')}: {text}"]
    for field in (
        "required_evidence_types",
        "required_evidence",
        "required_hops",
        "chain_hops",
        "required_delivery_types",
        "required_scope",
        "max_evidence_age_seconds",
        "evidence_freshness_by_type",
        "required_revision",
        "required_repo_revision",
        "revision_match",
        "revision_mode",
        "independent_validation_required",
    ):
        if field not in criterion:
            continue
        value = criterion[field]
        rendered = value if isinstance(value, str) else _brief_json(value)
        fields.append(f"{field}={rendered}")
    return " | ".join(fields)


def _brief_to_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        f"# Controlled Task Brief: {packet.get('task_id')}",
        f"Contract version: {packet.get('contract_version')}",
        f"Objective: {packet.get('objective')}",
        "",
        "## Rules",
        "Use only the facts and decisions below. Treat assumptions as unverified. Do not resolve conflicts silently.",
        "Do not add or reinterpret acceptance criteria. Return evidence pointers and proposed context changes.",
    ]
    actor_roles = packet.get("actor_roles")
    if isinstance(actor_roles, Mapping) and actor_roles:
        lines.extend(["", "## Actor Roles", f"- actor_roles={_brief_json(actor_roles)}"])
    for heading, key in (
        ("Scope", "scope"),
        ("Out of Scope", "out_of_scope"),
        ("Constraints", "constraints"),
    ):
        values = packet.get(key) or []
        lines.extend(["", f"## {heading}"])
        if not values:
            lines.append("- None")
            continue
        lines.extend(f"- {value}" for value in values)
    for heading, key in (
        ("Acceptance Criteria", "acceptance_criteria"),
        ("Verified Facts", "facts"),
        ("Observations", "observations"),
        ("Assumptions", "assumptions"),
        ("Decisions", "decisions"),
        ("Open Questions", "questions"),
        ("Conflicts", "conflicts"),
    ):
        values = packet.get(key) or []
        lines.extend(["", f"## {heading}"])
        if not values:
            lines.append("- None")
            continue
        for value in values:
            if isinstance(value, dict):
                if key == "acceptance_criteria":
                    lines.append(_brief_acceptance_to_markdown(value))
                else:
                    lines.append(_brief_item_to_markdown(value))
            else:
                lines.append(f"- {value}")
    checkpoint_value = packet.get("latest_checkpoint")
    lines.extend(["", "## Latest Checkpoint"])
    if isinstance(checkpoint_value, dict):
        lines.append(f"- Phase: {checkpoint_value.get('phase')}")
        lines.append(f"- Next action: {checkpoint_value.get('next_action')}")
        if checkpoint_value.get("blockers"):
            lines.append(f"- Blockers: {checkpoint_value.get('blockers')}")
    else:
        lines.append("- None")
    return "\n".join(lines)


def _audit_documents(documents: Sequence[str | Path], max_pointer_lag_seconds: float) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0
    for raw_path in documents:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            errors.append(f"document does not exist: {path}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read document {path}: {exc}")
            continue
        for match in _POINTER_RE.finditer(content):
            checked += 1
            target = (path.parent / match.group(1)).resolve()
            if not target.exists():
                errors.append(f"broken pointer in {path.name}: {match.group(1)}")
                continue
            lag = path.stat().st_mtime - target.stat().st_mtime
            if lag > max_pointer_lag_seconds:
                warnings.append(
                    f"stale pointer target: {path.name} is {int(lag)}s newer than {target.name}"
                )
    return errors, warnings, checked


def _run_bad_sample_probe() -> dict[str, Any]:
    """Verify that the production completion gate rejects empty required evidence."""

    probe_id = "PROBE-COMPLETION-EMPTY-EVIDENCE"
    with tempfile.TemporaryDirectory() as temporary_dir:
        probe_base_dir = Path(temporary_dir) / ".prime" / "context"
        contract = {
            "schema": SCHEMA_VERSION,
            "task_id": probe_id,
            "version": 1,
            "issued_by": "audit-probe",
            "issued_at": "2026-08-27T00:00:00+00:00",
            "authorized_approvers": [],
            "objective": "Reject empty completion evidence",
            "scope": ["audit probe"],
            "out_of_scope": [],
            "constraints": [],
            "acceptance_criteria": [
                {
                    "id": "AC-EMPTY-EVIDENCE",
                    "criterion": "Completion requires file evidence",
                    "required_evidence": ["file"],
                }
            ],
        }
        publish_contract(contract, confirmed_by="audit-probe", base_dir=probe_base_dir)
        report = _gate_core(
            probe_id,
            stage="completion",
            evidence_map={},
            emit=False,
            base_dir=probe_base_dir,
            run_probe=False,
        )
        scanned = int(report.get("stats", {}).get("criteria_checked", 0))
    return {
        "id": probe_id,
        "scanned": scanned,
        "expected": "reject",
        "actual": "reject" if not report["passed"] else "pass",
        "status": "pass" if not report["passed"] else "fail",
    }


def _audit_core(
    task_id: str,
    *,
    documents: Sequence[str | Path] | None = None,
    max_pointer_lag_seconds: float = 0,
    emit: bool = True,
    base_dir: str | Path | None = None,
    run_probe: bool,
) -> dict[str, Any]:
    """Audit contract, event/snapshot consistency, item quality, staleness, and pointers."""

    paths = _paths(task_id, base_dir)
    errors: list[str] = []
    warnings: list[str] = []
    scan_counts = {
        "contracts_checked": 0,
        "events_checked": 0,
        "items_checked": 0,
        "pointers_checked": 0,
        "probes_checked": 0,
    }
    probe = {
        "id": "PROBE-COMPLETION-EMPTY-EVIDENCE",
        "scanned": 0,
        "expected": "reject",
        "actual": "not-run",
        "status": "not-run",
    }
    if run_probe:
        try:
            probe = _run_bad_sample_probe()
        except Exception as exc:
            probe = {
                "id": "PROBE-COMPLETION-EMPTY-EVIDENCE",
                "scanned": 0,
                "expected": "reject",
                "actual": "error",
                "status": "fail",
            }
            errors.append(f"completion bad-sample probe raised {type(exc).__name__}")
        scan_counts["probes_checked"] = 1
        if probe["status"] != "pass":
            errors.append(
                f"completion bad-sample probe {probe['id']} failed: "
                f"expected {probe['expected']}, got {probe['actual']}"
            )

    scan_counts["contracts_checked"] = 1
    try:
        contract = _read_json(paths["contract"])
        errors.extend(_validate_sealed_contract(contract))
    except ContextError as exc:
        contract = {}
        errors.append(str(exc))

    events_valid = True
    try:
        events = _read_events(paths["events"])
        scan_counts["events_checked"] = len(events)
    except _EventReadError as exc:
        events_valid = False
        events = []
        scan_counts["events_checked"] = exc.attempted
        errors.append(str(exc))
    except ContextError as exc:
        events_valid = False
        events = []
        errors.append(str(exc))

    if events_valid:
        rebuilt = _empty_snapshot(task_id)
        for event in events:
            rebuilt = _apply_event(rebuilt, event)
        try:
            snapshot = _read_json(paths["snapshot"])
        except ContextError:
            snapshot = deepcopy(rebuilt)
        if snapshot != rebuilt:
            errors.append("snapshot differs from append-only event log; rebuild required")
    else:
        snapshot = _empty_snapshot(task_id)

    items = snapshot.get("items", {}) if isinstance(snapshot.get("items"), dict) else {}
    scan_counts["items_checked"] = len(items)
    counts = {item_type: 0 for item_type in ITEM_TYPES}
    stale_count = 0
    conflict_count = 0
    for identifier, item in items.items():
        if not isinstance(item, dict):
            errors.append(f"{identifier}: item is not an object")
            continue
        item_errors, item_warnings = _item_errors(item)
        errors.extend(item_errors)
        warnings.extend(item_warnings)
        if item.get("type") in counts:
            counts[item["type"]] += 1
        if item.get("status") == "conflicted":
            conflict_count += 1
        if _item_is_stale(item):
            stale_count += 1
        source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
        raw_evidence_refs = item.get("evidence")
        evidence_refs = raw_evidence_refs if isinstance(raw_evidence_refs, list) else []
        for ref in [source.get("ref"), *evidence_refs]:
            if isinstance(ref, str) and ref.startswith("file:"):
                file_path = Path(ref[5:]).expanduser()
                if not file_path.is_absolute():
                    file_path = Path.cwd() / file_path
                if not file_path.exists():
                    errors.append(f"{identifier}: missing file reference {ref}")

    pointer_checked = 0
    if documents:
        doc_errors, doc_warnings, pointer_checked = _audit_documents(documents, max_pointer_lag_seconds)
        errors.extend(doc_errors)
        warnings.extend(doc_warnings)
    scan_counts["pointers_checked"] = pointer_checked

    report = {
        "stage": "audit",
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "checked": scan_counts["items_checked"],
            "events": snapshot.get("event_count", 0),
            "probe": probe["status"],
            "probe_id": probe["id"],
            "probe_scanned": probe["scanned"],
            "probe_expected_rejection": probe["expected"],
            "stale": stale_count,
            "conflicts": conflict_count,
            **scan_counts,
            **counts,
        },
        "contract_version": contract.get("version"),
    }
    if emit:
        _emit_report(report)
    return report


def audit(
    task_id: str,
    *,
    documents: Sequence[str | Path] | None = None,
    max_pointer_lag_seconds: float = 0,
    emit: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Audit a task and always execute the isolated production-path probe."""

    return _audit_core(
        task_id,
        documents=documents,
        max_pointer_lag_seconds=max_pointer_lag_seconds,
        emit=emit,
        base_dir=base_dir,
        run_probe=True,
    )


def _gate_core(
    task_id: str,
    *,
    stage: str,
    evidence_map: Mapping[str, Mapping[str, Any]] | None = None,
    required_item_ids: Sequence[str] | None = None,
    documents: Sequence[str | Path] | None = None,
    resolvers: Mapping[str, Any] | None = None,
    verifiers: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    emit: bool = True,
    base_dir: str | Path | None = None,
    run_probe: bool,
) -> dict[str, Any]:
    """Run a release, resume, handoff, or completion quality gate."""

    if stage not in GATE_STAGES:
        raise ValueError(f"stage must be one of {sorted(GATE_STAGES)}")
    observed_now = (now or _trusted_utc_now()).astimezone(timezone.utc)
    paths = _paths(task_id, base_dir)
    report = _audit_core(
        task_id,
        documents=documents,
        emit=False,
        base_dir=base_dir,
        max_pointer_lag_seconds=0,
        run_probe=run_probe,
    )
    errors = list(report["errors"])
    warnings = list(report["warnings"])
    criterion_reports: dict[str, Any] = {}
    criteria_checked = 0
    evidence_attempts = 0
    contract: dict[str, Any] = {}
    snapshot = _empty_snapshot(task_id)
    try:
        contract = _read_json(paths["contract"])
        snapshot = _load_snapshot(task_id, paths)
    except ContextError as exc:
        if str(exc) not in errors:
            errors.append(str(exc))

    if stage in {"resume", "handoff", "completion"}:
        items = snapshot.get("items", {}) if isinstance(snapshot.get("items"), dict) else {}
        globally_blocked: set[str] = set()
        if stage == "completion":
            for identifier, item in sorted(items.items()):
                if not isinstance(item, Mapping) or item.get("status") == "superseded":
                    continue
                metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
                if item.get("status") == "conflicted":
                    errors.append(f"required context item is conflicted: {identifier}")
                    globally_blocked.add(identifier)
                if metadata.get("blocking") is True or metadata.get("blocker") is True:
                    errors.append(f"blocking context item remains: {identifier}")
                    globally_blocked.add(identifier)

        targets = (
            {
                identifier
                for identifier, item in items.items()
                if not isinstance(item, Mapping) or item.get("status") != "superseded"
            }
            if required_item_ids is None
            else set(required_item_ids)
        )
        for identifier in sorted(targets):
            item = items.get(identifier)
            if not isinstance(item, dict):
                errors.append(f"required context item missing: {identifier}")
                continue
            if item.get("status") == "superseded":
                errors.append(f"required context item is superseded: {identifier}")
                continue
            if item.get("status") == "conflicted" and identifier not in globally_blocked:
                errors.append(f"required context item is conflicted: {identifier}")
            if _item_is_stale(item):
                errors.append(f"required mutable fact is stale: {identifier}")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            if (
                identifier not in globally_blocked
                and (metadata.get("blocking") is True or metadata.get("blocker") is True)
            ):
                errors.append(f"blocking context item remains: {identifier}")

    if stage == "handoff":
        checkpoint_value = snapshot.get("latest_checkpoint")
        if not isinstance(checkpoint_value, dict):
            errors.append("handoff requires a checkpoint")
        elif not checkpoint_value.get("next_action"):
            errors.append("handoff checkpoint requires next_action")

    if stage == "completion":
        if not isinstance(evidence_map, Mapping):
            errors.append("completion gate requires evidence_map")
        else:
            criteria = deepcopy(contract.get("acceptance_criteria", []))
            contract_baseline = deepcopy(contract)
            for criterion in criteria if isinstance(criteria, list) else []:
                if not isinstance(criterion, dict):
                    continue
                criteria_checked += 1
                criterion_id = criterion.get("id")
                evidence_entry = (
                    deepcopy(evidence_map.get(criterion_id))
                    if isinstance(criterion_id, str)
                    else None
                )
                try:
                    criterion_report = _evaluate_completion_criterion(
                        deepcopy(criterion),
                        evidence_entry,
                        deepcopy(contract_baseline),
                        resolvers=resolvers,
                        verifiers=verifiers,
                        now=observed_now,
                    )
                except Exception as exc:
                    criterion_report = {
                        "status": "unknown",
                        "evidence_results": [],
                        "missing_evidence_types": [],
                        "missing_hops": [],
                        "missing_delivery_types": [],
                        "independent_validation": {
                            "status": "unknown",
                            "codes": ["CRITERION_EVALUATION_ERROR"],
                        },
                    }
                    warnings.append(
                        f"criterion {criterion_id} evaluation raised {type(exc).__name__}"
                    )
                evidence_attempts += len(criterion_report.get("evidence_results", []))
                criterion_reports[str(criterion_id)] = criterion_report
                if criterion_report.get("status") != "pass":
                    errors.append(
                        f"criterion {criterion_id} status is {criterion_report.get('status', 'unknown')}"
                    )
                    for evidence_result in criterion_report.get("evidence_results", []):
                        if evidence_result.get("status") == "pass":
                            continue
                        errors.append(
                            f"criterion {criterion_id} evidence "
                            f"{evidence_result.get('evidence_id')} is {evidence_result.get('status', 'unknown')}"
                        )
                    if criterion_report.get("missing_evidence_types"):
                        errors.append(
                            f"criterion {criterion_id} missing required evidence types: "
                            f"{criterion_report.get('missing_evidence_types')}"
                        )
                    if criterion_report.get("missing_hops"):
                        errors.append(
                            f"criterion {criterion_id} missing chain-hop coverage: "
                            f"{criterion_report.get('missing_hops')}"
                        )
                    if criterion_report.get("missing_delivery_types"):
                        errors.append(
                            f"criterion {criterion_id} missing required delivery types: "
                            f"{criterion_report.get('missing_delivery_types')}"
                        )
                    independence = criterion_report.get("independent_validation")
                    if isinstance(independence, Mapping) and independence.get("status") != "pass":
                        errors.append(
                            f"criterion {criterion_id} independent validation is "
                            f"{independence.get('status')}: {independence.get('codes', [])}"
                        )

    final = {
        "stage": stage,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "criteria": criterion_reports,
        "stats": {
            **report["stats"],
            "checked": report["stats"].get("checked", 0),
            "criteria_checked": criteria_checked,
            "evidence_attempts": evidence_attempts,
        },
        "contract_version": contract.get("version"),
    }
    if emit:
        _emit_report(final)
    return final


def _evaluate_completion_criterion(
    criterion: Mapping[str, Any],
    evidence_entry: Any,
    contract: Mapping[str, Any],
    *,
    resolvers: Mapping[str, Any] | None,
    verifiers: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Derive one criterion from an immutable requirements/evidence baseline."""

    criterion_baseline = deepcopy(dict(criterion))
    contract_baseline = deepcopy(dict(contract))
    criterion_id = str(criterion_baseline.get("id"))
    entry_is_malformed = evidence_entry is not None and not isinstance(evidence_entry, Mapping)
    entry = deepcopy(dict(evidence_entry)) if isinstance(evidence_entry, Mapping) else {}

    required_types = _criterion_string_set(
        criterion_baseline,
        "required_evidence_types",
        "required_evidence",
    )
    required_hops = _criterion_string_set(
        criterion_baseline,
        "required_hops",
        "chain_hops",
    )
    required_delivery_types = _criterion_string_set(
        criterion_baseline,
        "required_delivery_types",
        None,
    )
    independent_required = criterion_baseline.get("independent_validation_required") is True

    if entry_is_malformed:
        primary_candidates: list[Any] = [None]
        receipt_candidates: list[Any] = []
        entry_error_code = "MALFORMED_EVIDENCE_ENTRY"
    else:
        raw_primary = entry.get("evidence", [])
        raw_receipts = entry.get("delivery_receipts", [])
        primary_candidates = deepcopy(raw_primary) if isinstance(raw_primary, list) else [None]
        receipt_candidates = deepcopy(raw_receipts) if isinstance(raw_receipts, list) else [None]
        entry_error_code = "MALFORMED_EVIDENCE"

    records: list[tuple[str, int, Any]] = [
        *(('evidence', index, candidate) for index, candidate in enumerate(primary_candidates)),
        *(
            ('delivery_receipt', index, candidate)
            for index, candidate in enumerate(receipt_candidates)
        ),
    ]
    identifier_counts: dict[str, int] = {}
    invalid_identity = any(not isinstance(candidate, Mapping) for _, _, candidate in records)
    for _, _, candidate in records:
        if not isinstance(candidate, Mapping):
            continue
        identifier = candidate.get("evidence_id")
        if not isinstance(identifier, str) or not identifier.strip():
            invalid_identity = True
            continue
        identifier_counts[identifier] = identifier_counts.get(identifier, 0) + 1
    duplicate_ids = sorted(
        identifier for identifier, count in identifier_counts.items() if count > 1
    )
    identity_preflight_failed = invalid_identity or bool(duplicate_ids)

    primary_results: list[dict[str, Any]] = []
    primary_sources: list[Mapping[str, Any] | None] = []
    receipt_results: list[dict[str, Any]] = []
    receipt_sources: list[Mapping[str, Any] | None] = []

    for label, index, candidate in records:
        destination_results = primary_results if label == "evidence" else receipt_results
        destination_sources = primary_sources if label == "evidence" else receipt_sources
        if not isinstance(candidate, Mapping):
            destination_sources.append(None)
            destination_results.append(
                _malformed_completion_result(
                    criterion_id,
                    label,
                    index,
                    entry_error_code,
                )
            )
            continue

        source = deepcopy(dict(candidate))
        destination_sources.append(source)
        identifier = source.get("evidence_id")
        if identity_preflight_failed:
            if not isinstance(identifier, str) or not identifier.strip():
                code = "MALFORMED_EVIDENCE_ID"
            elif identifier in duplicate_ids:
                code = "DUPLICATE_EVIDENCE_ID"
            else:
                code = "EVIDENCE_ID_PREFLIGHT_FAILED"
            destination_results.append(
                _malformed_completion_result(
                    criterion_id,
                    label,
                    index,
                    code,
                    evidence_id=identifier,
                    kind=source.get("kind"),
                )
            )
            continue

        if label == "delivery_receipt":
            if not _valid_delivery_receipt(source):
                destination_results.append(
                    _malformed_completion_result(
                        criterion_id,
                        label,
                        index,
                        "MALFORMED_DELIVERY_RECEIPT",
                        evidence_id=identifier,
                        kind=source.get("kind"),
                    )
                )
                continue
            future_fields = (
                (field, _parse_explicit_utc_timestamp(source.get(field)))
                for field in _DELIVERY_RECEIPT_TIME_FIELDS
            )
            future_field = next(
                (
                    field
                    for field, timestamp in future_fields
                    if timestamp is not None
                    and timestamp > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
                ),
                None,
            )
            if future_field is not None:
                destination_results.append(
                    _malformed_completion_result(
                        criterion_id,
                        label,
                        index,
                        f"FUTURE_DELIVERY_{future_field.upper()}",
                        evidence_id=identifier,
                        kind=source.get("kind"),
                    )
                )
                continue

        result = evaluate_evidence(
            deepcopy(source),
            deepcopy(criterion_baseline),
            deepcopy(contract_baseline),
            resolvers=resolvers,
            verifiers=verifiers,
            now=now,
        )
        if label == "evidence" and "covered_hops" in source and not _valid_string_list(
            source.get("covered_hops"), allow_empty=True
        ):
            result = _fail_completion_result(result, "MALFORMED_HOP_BINDING")
        destination_results.append(result)

    evidence_results = [*primary_results, *receipt_results]
    supplied_types = {
        str(source.get("kind"))
        for source in primary_sources
        if isinstance(source, Mapping) and isinstance(source.get("kind"), str)
    }
    missing_types = sorted(required_types - supplied_types)

    verified_hops: set[str] = set()
    for source, result in zip(primary_sources, primary_results):
        if not isinstance(source, Mapping) or result.get("status") != "pass":
            continue
        bound_hops = source.get("covered_hops", [])
        if _valid_string_list(bound_hops, allow_empty=True):
            verified_hops.update(bound_hops)
    missing_hops = sorted(required_hops - verified_hops)

    verified_delivery_types = {
        str(source.get("delivery_type"))
        for source, result in zip(receipt_sources, receipt_results)
        if isinstance(source, Mapping)
        and source.get("kind") == "delivery-receipt"
        and result.get("status") == "pass"
        and source.get("delivery_type") in required_delivery_types
    }
    missing_delivery_types = sorted(required_delivery_types - verified_delivery_types)

    independence = _independent_validation_check(
        independent_required,
        entry,
        [*primary_sources, *receipt_sources],
        contract_baseline,
        now,
    )
    statuses = [result.get("status", "unknown") for result in evidence_results]
    if not primary_results:
        statuses.append("unknown")
    if missing_types or missing_hops or missing_delivery_types:
        statuses.append("unknown")
    if independence["status"] != "pass":
        statuses.append(independence["status"])
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return {
        "status": status,
        "evidence_results": evidence_results,
        "missing_evidence_types": missing_types,
        "missing_hops": missing_hops,
        "missing_delivery_types": missing_delivery_types,
        "independent_validation": independence,
        "duplicate_evidence_ids": duplicate_ids,
    }


def _criterion_string_set(
    criterion: Mapping[str, Any], canonical: str, compatibility: str | None
) -> set[str]:
    value = criterion.get(canonical)
    if value is None and compatibility is not None:
        value = criterion.get(compatibility)
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _malformed_completion_result(
    criterion_id: str,
    label: str,
    index: int,
    code: str,
    *,
    evidence_id: Any = None,
    kind: Any = "",
) -> dict[str, Any]:
    identifier = evidence_id if evidence_id is not None else f"{criterion_id}:{label}[{index}]"
    return {
        "evidence_id": identifier,
        "kind": kind if isinstance(kind, str) else "",
        "status": "fail",
        "checks": {
            "resolve": {"status": "fail", "codes": [code]},
            "integrity_and_freshness": {"status": "unknown", "codes": [code]},
            "scope": {"status": "unknown", "codes": [code]},
            "claim": {"status": "unknown", "codes": [code]},
        },
    }


def _fail_completion_result(result: Mapping[str, Any], code: str) -> dict[str, Any]:
    failed = deepcopy(dict(result))
    checks = failed.get("checks") if isinstance(failed.get("checks"), Mapping) else {}
    checks = deepcopy(dict(checks))
    resolution = checks.get("resolve") if isinstance(checks.get("resolve"), Mapping) else {}
    codes = list(resolution.get("codes", [])) if isinstance(resolution.get("codes"), list) else []
    if code not in codes:
        codes.append(code)
    checks["resolve"] = {"status": "fail", "codes": codes}
    failed["checks"] = checks
    failed["status"] = "fail"
    return failed


def _independent_validation_check(
    required: bool,
    entry: Mapping[str, Any],
    evidence_sources: Sequence[Mapping[str, Any] | None],
    contract: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    if not required:
        return {"status": "pass", "codes": []}
    validated_at_value = entry.get("validated_at")
    if validated_at_value is None:
        return {"status": "unknown", "codes": ["MISSING_VALIDATED_AT"]}
    validated_at = _parse_explicit_utc_timestamp(validated_at_value)
    if validated_at is None:
        return {"status": "fail", "codes": ["INVALID_VALIDATED_AT"]}
    if validated_at > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        return {"status": "fail", "codes": ["FUTURE_VALIDATED_AT"]}
    validator = entry.get("validated_by")
    if not isinstance(validator, str) or not validator.strip():
        return {"status": "unknown", "codes": ["MISSING_INDEPENDENT_VALIDATOR"]}

    actor_roles = contract.get("actor_roles")
    if not isinstance(actor_roles, Mapping):
        return {"status": "fail", "codes": ["VALIDATOR_ROLE_UNENFORCEABLE"]}
    validator_roles = actor_roles.get(validator)
    if not isinstance(validator_roles, list) or "validator" not in validator_roles:
        return {"status": "fail", "codes": ["VALIDATOR_ROLE_REQUIRED"]}

    producer_fields = ("produced_by", "submitted_by", "owner", "executor", "actor")
    producers: set[str] = set()
    missing_producer = False
    for source in evidence_sources:
        if not isinstance(source, Mapping):
            continue
        identities = {
            str(source.get(field))
            for field in producer_fields
            if isinstance(source.get(field), str) and str(source.get(field)).strip()
        }
        if not identities:
            missing_producer = True
        producers.update(identities)
    for field in ("producer", "owner", "executor"):
        if isinstance(entry.get(field), str) and str(entry.get(field)).strip():
            producers.add(str(entry.get(field)))

    if validator in producers:
        return {"status": "fail", "codes": ["VALIDATOR_NOT_INDEPENDENT"]}
    unknown_producers = [producer for producer in producers if producer not in actor_roles]
    if missing_producer:
        return {"status": "unknown", "codes": ["MISSING_EVIDENCE_PRODUCER"]}
    if unknown_producers:
        return {"status": "unknown", "codes": ["PRODUCER_ROLE_UNKNOWN"]}
    return {"status": "pass", "codes": []}


def gate(
    task_id: str,
    *,
    stage: str,
    evidence_map: Mapping[str, Mapping[str, Any]] | None = None,
    required_item_ids: Sequence[str] | None = None,
    documents: Sequence[str | Path] | None = None,
    resolvers: Mapping[str, Any] | None = None,
    verifiers: Mapping[str, Any] | None = None,
    emit: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run a public gate; callers cannot disable its isolated audit probe."""

    return _gate_core(
        task_id,
        stage=stage,
        evidence_map=evidence_map,
        required_item_ids=required_item_ids,
        documents=documents,
        resolvers=resolvers,
        verifiers=verifiers,
        now=_trusted_utc_now(),
        emit=emit,
        base_dir=base_dir,
        run_probe=True,
    )


def workspace_observation(path: str | Path = ".") -> dict[str, Any]:
    """Read current Git/filesystem state without trusting a handwritten status file."""

    root = Path(path).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(root),
        "observed_at": _now(),
        "exists": root.exists(),
        "git": None,
    }
    if not root.exists():
        return result
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
        result["git"] = {"head": head, "branch": branch, "status": status, "changed_files": len(status)}
    except (FileNotFoundError, subprocess.CalledProcessError):
        result["git"] = None
    return result


async def run(action: str, **kwargs: Any) -> Any:
    """Prime Agent callable dispatcher.

    Example: ``await managing_long_task_context("gate", task_id="TASK-001", stage="release")``.
    """

    actions = {
        "publish_contract": publish_contract,
        "record": record,
        "update_item": update_item,
        "checkpoint": checkpoint,
        "brief": brief,
        "audit": audit,
        "gate": gate,
        "workspace_observation": workspace_observation,
    }
    function = actions.get(action)
    if function is None:
        raise ValueError(f"unknown action {action!r}; expected one of {sorted(actions)}")
    result = function(**kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


__all__ = [
    "ContextError",
    "publish_contract",
    "record",
    "update_item",
    "checkpoint",
    "brief",
    "audit",
    "gate",
    "workspace_observation",
    "run",
]
