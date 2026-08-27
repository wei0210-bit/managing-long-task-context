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
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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


class ContextError(RuntimeError):
    """Raised when a context quality rule blocks an operation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    value.pop("seal", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _contract_digest(contract: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_contract(contract)).hexdigest()


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
    criteria = contract.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("contract.acceptance_criteria must contain publisher-written criteria")
        return errors

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
        required_evidence = criterion.get("required_evidence")
        if not isinstance(required_evidence, list) or not required_evidence:
            errors.append(f"{prefix}.required_evidence must be a non-empty list")
        hops = criterion.get("chain_hops", [])
        if not isinstance(hops, list):
            errors.append(f"{prefix}.chain_hops must be a list when present")
    return errors


def _validate_sealed_contract(contract: Mapping[str, Any]) -> list[str]:
    errors = _validate_contract_shape(contract)
    seal = contract.get("seal")
    if not isinstance(seal, dict):
        errors.append("contract is not sealed by the task publisher")
        return errors
    for field in ("confirmed_by", "confirmed_at", "digest"):
        if not isinstance(seal.get(field), str) or not seal[field].strip():
            errors.append(f"contract.seal.{field} must be a non-empty string")
    digest = seal.get("digest")
    if isinstance(digest, str) and digest != _contract_digest(contract):
        errors.append("contract seal is invalid: contract changed after publisher confirmation")
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
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContextError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(event, dict):
                raise ContextError(f"event at {path}:{line_no} is not an object")
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


def _validator_probe() -> bool:
    bad_item = {
        "id": "PROBE",
        "statement": "known invalid verified fact",
        "type": "verified-fact",
        "status": "active",
        "source": {"kind": "agent-inference", "ref": "probe"},
        "evidence": [],
        "scope": {},
        "verified_at": None,
        "verification_method": None,
    }
    errors, _ = _item_errors(bad_item)
    return len(errors) >= 4


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

    value = _json_clone(dict(contract))
    value.setdefault("schema", SCHEMA_VERSION)
    value.setdefault("authorized_approvers", [])
    errors = _validate_contract_shape(value)
    if errors:
        raise ContextError("contract rejected: " + "; ".join(errors))
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
            "digest": _contract_digest(value),
        }
        _atomic_write_json(paths["contract"], value)
        snapshot = _load_snapshot(task_id, paths)
        event = _new_event(
            task_id,
            "contract-published",
            confirmed_by,
            {
                "task_id": task_id,
                "version": value["version"],
                "digest": value["seal"]["digest"],
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
            updated["status"] = "active" if updated.get("status") != "superseded" else "superseded"
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


def brief(
    task_id: str,
    *,
    phase: str | None = None,
    include: Sequence[str] | None = None,
    max_items: int = 50,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a minimal active-context/handoff packet from controlled state."""

    if max_items < 1:
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
    selected: list[dict[str, Any]] = []
    include_set = set(include or [])
    for identifier, raw in sorted(all_items.items()):
        if not isinstance(raw, dict):
            continue
        if include is not None and identifier not in include_set:
            continue
        if raw.get("status") == "superseded":
            continue
        selected.append(deepcopy(raw))
        if len(selected) >= max_items:
            break

    packet = {
        "task_id": task_id,
        "contract_version": contract.get("version"),
        "contract_digest": contract.get("seal", {}).get("digest"),
        "objective": contract.get("objective"),
        "scope": contract.get("scope", []),
        "out_of_scope": contract.get("out_of_scope", []),
        "constraints": contract.get("constraints", []),
        "acceptance_criteria": contract.get("acceptance_criteria", []),
        "phase": phase or (snapshot.get("latest_checkpoint") or {}).get("phase"),
        "facts": [item for item in selected if item.get("type") == "verified-fact"],
        "observations": [item for item in selected if item.get("type") == "observation"],
        "assumptions": [item for item in selected if item.get("type") == "assumption"],
        "decisions": [item for item in selected if item.get("type") == "decision"],
        "questions": [item for item in selected if item.get("type") == "question"],
        "conflicts": [item for item in selected if item.get("status") == "conflicted"],
        "stale_items": [item["id"] for item in selected if _item_is_stale(item)],
        "latest_checkpoint": snapshot.get("latest_checkpoint"),
        "context_version": snapshot.get("event_count", 0),
    }
    packet["prompt"] = _brief_to_markdown(packet)
    return packet


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
                identifier = value.get("id", "")
                text = value.get("criterion") or value.get("statement") or json.dumps(value, ensure_ascii=False)
                lines.append(f"- {identifier}: {text}".strip())
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


def audit(
    task_id: str,
    *,
    documents: Sequence[str | Path] | None = None,
    max_pointer_lag_seconds: float = 0,
    emit: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Audit contract, event/snapshot consistency, item quality, staleness, and pointers."""

    paths = _paths(task_id, base_dir)
    errors: list[str] = []
    warnings: list[str] = []
    probe_ok = _validator_probe()
    if not probe_ok:
        errors.append("validator self-probe failed; the checker cannot prove it detects known-bad input")

    try:
        contract = _read_json(paths["contract"])
        errors.extend(_validate_sealed_contract(contract))
    except ContextError as exc:
        contract = {}
        errors.append(str(exc))

    try:
        snapshot = _load_snapshot(task_id, paths)
        rebuilt = _rebuild_snapshot(task_id, paths["events"])
        if snapshot != rebuilt:
            errors.append("snapshot differs from append-only event log; rebuild required")
    except ContextError as exc:
        snapshot = _empty_snapshot(task_id)
        errors.append(str(exc))

    items = snapshot.get("items", {}) if isinstance(snapshot.get("items"), dict) else {}
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
        for ref in [item.get("source", {}).get("ref")] + list(item.get("evidence") or []):
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

    report = {
        "stage": "audit",
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "checked": len(items),
            "events": snapshot.get("event_count", 0),
            "probe": "pass" if probe_ok else "fail",
            "stale": stale_count,
            "conflicts": conflict_count,
            "pointers_checked": pointer_checked,
            **counts,
        },
        "contract_version": contract.get("version"),
    }
    if emit:
        _emit_report(report)
    return report


def gate(
    task_id: str,
    *,
    stage: str,
    evidence_map: Mapping[str, Mapping[str, Any]] | None = None,
    required_item_ids: Sequence[str] | None = None,
    documents: Sequence[str | Path] | None = None,
    emit: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run a release, resume, handoff, or completion quality gate."""

    if stage not in GATE_STAGES:
        raise ValueError(f"stage must be one of {sorted(GATE_STAGES)}")
    paths = _paths(task_id, base_dir)
    report = audit(task_id, documents=documents, emit=False, base_dir=base_dir)
    errors = list(report["errors"])
    warnings = list(report["warnings"])
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
        targets = set(required_item_ids or items.keys())
        for identifier in sorted(targets):
            item = items.get(identifier)
            if not isinstance(item, dict):
                errors.append(f"required context item missing: {identifier}")
                continue
            if item.get("status") == "conflicted":
                errors.append(f"required context item is conflicted: {identifier}")
            if _item_is_stale(item):
                errors.append(f"required mutable fact is stale: {identifier}")
            if item.get("metadata", {}).get("blocking") and item.get("type") in {"assumption", "question"}:
                errors.append(f"blocking unverified item remains: {identifier}")

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
            criteria = contract.get("acceptance_criteria", [])
            for criterion in criteria if isinstance(criteria, list) else []:
                if not isinstance(criterion, dict):
                    continue
                criterion_id = criterion.get("id")
                evidence_entry = evidence_map.get(criterion_id) if isinstance(criterion_id, str) else None
                if not isinstance(evidence_entry, Mapping):
                    errors.append(f"missing completion evidence for {criterion_id}")
                    continue
                if evidence_entry.get("result") != "pass":
                    errors.append(f"criterion {criterion_id} is not passed")
                if not evidence_entry.get("evidence"):
                    errors.append(f"criterion {criterion_id} has no evidence pointers")
                required_types = set(str(item) for item in criterion.get("required_evidence", []))
                supplied_types = set(str(item) for item in evidence_entry.get("evidence_types", []))
                missing_types = required_types - supplied_types
                if missing_types:
                    errors.append(
                        f"criterion {criterion_id} missing required evidence types: {sorted(missing_types)}"
                    )
                required_hops = set(str(item) for item in criterion.get("chain_hops", []))
                covered_hops = set(str(item) for item in evidence_entry.get("covered_hops", []))
                missing_hops = required_hops - covered_hops
                if missing_hops:
                    errors.append(f"criterion {criterion_id} missing chain-hop coverage: {sorted(missing_hops)}")

    final = {
        "stage": stage,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            **report["stats"],
            "checked": report["stats"].get("checked", 0),
        },
        "contract_version": contract.get("version"),
    }
    if emit:
        _emit_report(final)
    return final


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
