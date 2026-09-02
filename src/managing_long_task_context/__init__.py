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
import threading
from typing import Any, Iterable, Mapping, Sequence

from .evidence import (
    BUILTIN_RESOLVER_CAPABILITIES,
    MAX_CLOCK_SKEW_SECONDS,
    canonical_json_bytes,
    evidence_handlers_enabled,
    evaluate_evidence,
    runtime_evidence_handler_errors,
    validate_evidence_handler_contract,
)
from .truth_sources import (
    CAPABILITY,
    VERIFICATION_REF_RE,
    evaluate_truth_sources,
    resolve_file_source,
    truth_sources_enabled,
    validate_truth_source_contract,
)

try:  # Prime Agent targets macOS/Linux; keep a safe fallback for other runtimes.
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

SCHEMA_VERSION = 1
ITEM_TYPES = {"observation", "verified-fact", "assumption", "decision", "question"}
ITEM_STATUSES = {"active", "unverified", "conflicted", "superseded"}
GATE_STAGES = {"release", "resume", "handoff", "completion"}
DEFAULT_BASE_DIR = Path(".prime/context")
BASE_DIR_ENV = "MLTC_BASE_DIR"
CONTRACT_FILE_PROTECTION = "read-only-advisory-v1"
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
_TRUTH_SOURCE_RESOLVER_FAILURES = {
    "TRUTH_SOURCE_NOT_FOUND": "fail",
    "TRUTH_SOURCE_PERMISSION_DENIED": "unknown",
    "TRUTH_SOURCE_TRANSIENT_IO": "unknown",
    "TRUTH_SOURCE_UNSAFE_PATH": "fail",
    "TRUTH_SOURCE_SYMLINK": "fail",
    "TRUTH_SOURCE_NOT_REGULAR_FILE": "fail",
    "TRUTH_SOURCE_TOO_LARGE": "fail",
    "TRUTH_SOURCE_CHANGED_DURING_READ": "unknown",
    "TRUTH_SOURCE_RESOLVER_UNKNOWN": "unknown",
}
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.Lock] = {}


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


def _resolve_base_dir(base_dir: str | Path | None = None) -> tuple[Path, str]:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve(), "explicit"
    configured = os.environ.get(BASE_DIR_ENV)
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            raise ContextError(f"{BASE_DIR_ENV}_INVALID: path must be absolute")
        return configured_path.resolve(), "environment"
    return (Path.cwd() / DEFAULT_BASE_DIR).resolve(), "cwd-default"


def _task_dir(task_id: str, base_dir: str | Path | None = None) -> Path:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id.strip()).strip("-")
    if not safe:
        raise ValueError("task_id contains no usable characters")
    resolved_base_dir, _ = _resolve_base_dir(base_dir)
    return resolved_base_dir / safe


def _storage_info(
    task_id: str,
    base_dir: str | Path | None = None,
    *,
    source: str | None = None,
) -> dict[str, str]:
    resolved_base_dir, inferred_source = _resolve_base_dir(base_dir)
    return {
        "resolved_base_dir": str(resolved_base_dir),
        "task_root": str(_task_dir(task_id, resolved_base_dir)),
        "base_dir_source": source or inferred_source,
    }


def _paths(task_id: str, base_dir: str | Path | None = None) -> dict[str, Path]:
    root = _task_dir(task_id, base_dir)
    return {
        "root": root,
        "contract": root / "task-contract.json",
        "events": root / "events.jsonl",
        "snapshot": root / "snapshot.json",
        "lock": root / ".lock",
    }


def _process_lock_guard(root: Path) -> threading.Lock:
    """Serialize local threads; ``flock`` alone is process-scoped on macOS."""

    key = str(root)
    with _PROCESS_LOCKS_GUARD:
        guard = _PROCESS_LOCKS.get(key)
        if guard is None:
            guard = threading.Lock()
            _PROCESS_LOCKS[key] = guard
        return guard


@contextmanager
def _locked(root: Path):
    with _process_lock_guard(root):
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


@contextmanager
def _shared_locked_existing(root: Path):
    if fcntl is None:
        raise ContextError(
            f"READ_LOCK_UNAVAILABLE: shared locking is unsupported for {root / '.lock'}"
        )
    with _process_lock_guard(root):
        lock_path = root / ".lock"
        try:
            handle = lock_path.open("r", encoding="utf-8")
        except OSError as exc:
            raise ContextError(
                f"READ_LOCK_UNAVAILABLE: existing task lock is unreadable: {lock_path}"
            ) from exc
        with handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            except OSError as exc:
                raise ContextError(
                    f"READ_LOCK_UNAVAILABLE: shared lock acquisition failed: {lock_path}"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _atomic_write_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    mode: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            if mode is not None:
                os.fchmod(handle.fileno(), mode)
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


def _canonical_contract_input(contract: Mapping[str, Any]) -> bytes:
    """Canonicalize only publisher supplied contract fields, never a seal."""
    value = deepcopy(dict(contract))
    value.pop("seal", None)
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
        errors.extend(validate_truth_source_contract(contract))
        errors.extend(validate_evidence_handler_contract(contract))
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
        hops_mode = criterion.get("required_hops_mode")
        if hops_mode is not None and hops_mode not in {"aggregate", "single-evidence-ordered"}:
            errors.append(
                f"{prefix}.required_hops_mode must be aggregate or single-evidence-ordered"
            )
        if hops_mode == "single-evidence-ordered":
            if not isinstance(hops_value, list) or not hops_value:
                errors.append(
                    f"{prefix}.single-evidence-ordered requires non-empty required_hops"
                )
            if not evidence_handlers_enabled(contract):
                errors.append(
                    f"{prefix}.single-evidence-ordered requires evidence-handlers/v1"
                )

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
    errors.extend(validate_truth_source_contract(contract))
    errors.extend(validate_evidence_handler_contract(contract))
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
    protection = seal.get("file_protection")
    if protection is not None and protection not in {CONTRACT_FILE_PROTECTION, "none"}:
        errors.append(
            "contract.seal.file_protection must be read-only-advisory-v1 or none"
        )
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


def _contract_file_protection_errors(
    contract: Mapping[str, Any], contract_path: Path,
) -> list[str]:
    """Check the sealed advisory guard without changing legacy contracts."""

    seal = contract.get("seal")
    if not isinstance(seal, Mapping) or seal.get("file_protection") != CONTRACT_FILE_PROTECTION:
        return []
    try:
        mode = contract_path.stat().st_mode
    except OSError:
        return []  # The ordinary contract read path reports missing/unreadable files.
    if mode & 0o222:
        return ["CONTRACT_FILE_PROTECTION_MISSING"]
    return []


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


def _truth_source_reset_payload(
    contract: Mapping[str, Any], snapshot: Mapping[str, Any],
) -> dict[str, Any] | None:
    current = snapshot.get("truth_sources")
    history_enabled = isinstance(current, Mapping)
    if not history_enabled and not truth_sources_enabled(contract):
        return None
    previous = current.get("generation", 0) if isinstance(current, Mapping) else 0
    if type(previous) is not int or previous < 0:
        raise ContextError("truth source reset has invalid previous generation")
    truth = contract.get("truth_sources")
    items = truth.get("items", []) if isinstance(truth, Mapping) else []
    source_ids = [item["id"] for item in items if isinstance(item, Mapping) and isinstance(item.get("id"), str)]
    return {"schema": CAPABILITY, "generation": previous + 1, "source_ids": source_ids}


def _truth_event_error(event_type: object, message: str) -> ContextError:
    return ContextError(f"{event_type}: {message}")


def _validate_truth_event_envelope(event: Mapping[str, Any], event_type: str) -> None:
    if not _truth_single_line(event.get("actor")):
        raise _truth_event_error(event_type, "actor must be a non-empty string")
    if not _valid_explicit_utc_timestamp(event.get("created_at")):
        raise _truth_event_error(event_type, "created_at must be an explicit UTC timestamp")


def _truth_single_line(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _apply_truth_control_event(snapshot: dict[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one validated strict control event or fail before exposing a projection."""
    result = deepcopy(snapshot)
    event_type = event.get("event_type")
    payload = event.get("payload")
    if event_type not in {"truth-source-dirtied", "truth-source-observed"}:
        raise _truth_event_error(event_type, "unknown truth control event")
    if not isinstance(payload, Mapping):
        raise _truth_event_error(event_type, "payload must be an object")
    _validate_truth_event_envelope(event, event_type)
    truth = result.get("truth_sources")
    if not isinstance(truth, Mapping) or type(truth.get("generation")) is not int:
        raise _truth_event_error(event_type, "requires a preceding truth source reset")
    sources = truth.get("sources")
    contract_payload = result.get("contract")
    digest = contract_payload.get("integrity_digest") if isinstance(contract_payload, Mapping) else None
    if not isinstance(sources, Mapping) or not isinstance(digest, str):
        raise _truth_event_error(event_type, "has no active truth source contract")
    if payload.get("contract_digest") != digest:
        raise _truth_event_error(event_type, "contract_digest does not match active contract")

    if event_type == "truth-source-dirtied":
        allowed = {"contract_digest", "generation", "change_kind", "reason", "affected_source_ids"}
        if set(payload) != allowed:
            raise _truth_event_error(event_type, "payload fields are invalid")
        generation = payload.get("generation")
        if type(generation) is not int or generation < 1:
            raise _truth_event_error(event_type, "generation must be a positive integer")
        if generation != truth["generation"] + 1:
            raise _truth_event_error(event_type, "generation must increment current generation once")
        if not _truth_single_line(payload.get("change_kind")):
            raise _truth_event_error(event_type, "change_kind must be a non-empty string")
        if not _truth_single_line(payload.get("reason")):
            raise _truth_event_error(event_type, "reason must be a non-empty string")
        source_ids = payload.get("affected_source_ids")
        if not isinstance(source_ids, list) or not source_ids or not all(isinstance(item, str) for item in source_ids) or len(set(source_ids)) != len(source_ids):
            raise _truth_event_error(event_type, "affected_source_ids must be a unique non-empty list")
        if any(source_id not in sources for source_id in source_ids):
            raise _truth_event_error(event_type, "affected_source_ids contains an unknown source")
        next_generation = generation
        updated_sources = deepcopy(dict(sources))
        for source_id in source_ids:
            source = updated_sources[source_id]
            source["required_generation"] = next_generation
            source["observed_generation"] = None
            source["observation"] = None
            source["status"] = "dirty"
        result["truth_sources"] = {"generation": next_generation, "sources": updated_sources}
        return result

    allowed = {"contract_digest", "observed_generation", "source_id", "fingerprint", "verification_refs"}
    if set(payload) != allowed:
        raise _truth_event_error(event_type, "payload fields are invalid")
    source_id = payload.get("source_id")
    if not isinstance(source_id, str) or source_id not in sources:
        raise _truth_event_error(event_type, "source_id must name an active source")
    source = sources[source_id]
    required = source.get("required_generation") if isinstance(source, Mapping) else None
    observed_generation = payload.get("observed_generation")
    if type(observed_generation) is not int or observed_generation != required:
        raise _truth_event_error(event_type, "observed_generation must equal source required_generation")
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint) is None:
        raise _truth_event_error(event_type, "fingerprint must be sha256:<64 lowercase hex>")
    refs = payload.get("verification_refs")
    if (
        not isinstance(refs, list)
        or not refs
        or not all(isinstance(item, str) and VERIFICATION_REF_RE.fullmatch(item) for item in refs)
        or len(set(refs)) != len(refs)
    ):
        raise _truth_event_error(event_type, "verification_refs must be a unique non-empty list")
    updated_sources = deepcopy(dict(sources))
    updated_sources[source_id] = {
        "required_generation": required,
        "observed_generation": observed_generation,
        "observation": {
            "fingerprint": fingerprint,
            "verification_refs": deepcopy(refs),
            "observed_at": event["created_at"],
            "actor": event["actor"],
        },
        "status": "observed",
    }
    result["truth_sources"] = {"generation": truth["generation"], "sources": updated_sources}
    return result


_EVENT_FIELDS = frozenset({"schema", "event_id", "task_id", "event_type", "actor", "created_at", "payload"})
_EVENT_TYPES = frozenset({
    "contract-published", "item-recorded", "item-updated", "item-externalized",
    "checkpoint-recorded",
    "truth-source-dirtied", "truth-source-observed",
})
_CONTRACT_PUBLISH_FIELDS = frozenset({
    "task_id", "version", "integrity_digest", "confirmed_by", "confirmed_at",
})


def _validate_event_envelope(task_id: str, event: Mapping[str, Any]) -> None:
    if set(event) != _EVENT_FIELDS:
        raise ContextError("event envelope fields are invalid")
    if event.get("schema") != SCHEMA_VERSION:
        raise ContextError("event schema is invalid")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or re.fullmatch(r"EV-[0-9a-f]{12}", event_id) is None:
        raise ContextError("event_id is invalid")
    if event.get("task_id") != task_id:
        raise ContextError("event task_id does not match task")
    if event.get("event_type") not in _EVENT_TYPES:
        raise ContextError("event_type is invalid")
    if not isinstance(event.get("actor"), str) or not event["actor"].strip():
        raise ContextError("event actor is invalid")
    if not _valid_explicit_utc_timestamp(event.get("created_at")):
        raise ContextError("event created_at is invalid")
    if not isinstance(event.get("payload"), Mapping):
        raise ContextError("event payload must be an object")


def _validate_contract_publish_event(event: Mapping[str, Any], *, task_id: str) -> None:
    _validate_event_envelope(task_id, event)
    payload = event["payload"]
    assert isinstance(payload, Mapping)
    allowed = _CONTRACT_PUBLISH_FIELDS | ({"truth_source_reset"} if "truth_source_reset" in payload else set())
    if event.get("event_type") != "contract-published" or set(payload) != allowed:
        raise ContextError("contract-published payload fields are invalid")
    if payload.get("task_id") != task_id:
        raise ContextError("contract-published payload task_id is invalid")
    if not isinstance(payload.get("version"), (int, float, str)) or isinstance(payload.get("version"), bool):
        raise ContextError("contract-published payload version is invalid")
    if not isinstance(payload.get("integrity_digest"), str) or re.fullmatch(r"sha256:[0-9a-f]{64}", payload["integrity_digest"]) is None:
        raise ContextError("contract-published payload integrity_digest is invalid")
    if not isinstance(payload.get("confirmed_by"), str) or not payload["confirmed_by"].strip() or event.get("actor") != payload["confirmed_by"]:
        raise ContextError("contract-published actor must equal confirmed_by")
    if not _valid_explicit_utc_timestamp(payload.get("confirmed_at")):
        raise ContextError("contract-published payload confirmed_at is invalid")


def _apply_event(snapshot: dict[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    task_id = snapshot.get("task_id")
    if not isinstance(task_id, str):
        raise ContextError("snapshot task_id is invalid")
    _validate_event_envelope(task_id, event)
    result = deepcopy(snapshot)
    event_type = event.get("event_type")
    payload = event.get("payload")
    assert isinstance(payload, Mapping)
    if event_type == "contract-published":
        _validate_contract_publish_event(event, task_id=task_id)
        result["contract"] = deepcopy(payload)
        reset = payload.get("truth_source_reset") if isinstance(payload, Mapping) else None
        if reset is not None:
            if not isinstance(reset, Mapping) or set(reset) != {"schema", "generation", "source_ids"}:
                raise _truth_event_error(event_type, "truth_source_reset fields are invalid")
            if reset.get("schema") != CAPABILITY:
                raise _truth_event_error(event_type, "truth_source_reset.schema is invalid")
            previous = result.get("truth_sources")
            previous_generation = previous.get("generation", 0) if isinstance(previous, Mapping) else 0
            if type(previous_generation) is not int or reset.get("generation") != previous_generation + 1:
                raise _truth_event_error(event_type, "truth_source_reset generation is not monotonic")
            source_ids = reset.get("source_ids")
            if not isinstance(source_ids, list) or not all(isinstance(item, str) and item for item in source_ids) or len(set(source_ids)) != len(source_ids):
                raise _truth_event_error(event_type, "truth_source_reset source_ids are invalid")
            result["truth_sources"] = {
                "generation": reset["generation"],
                "sources": {
                    source_id: {
                        "required_generation": reset["generation"],
                        "observed_generation": None,
                        "observation": None,
                        "status": "unobserved",
                    }
                    for source_id in source_ids
                },
            }
    elif event_type in {"truth-source-dirtied", "truth-source-observed"}:
        result = _apply_truth_control_event(result, event)
    elif event_type in {"item-recorded", "item-updated", "item-externalized"}:
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


def _rebuild_snapshot(task_id: str, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    snapshot = _empty_snapshot(task_id)
    for event in events:
        snapshot = _apply_event(snapshot, event)
    return snapshot


def _load_snapshot(task_id: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    try:
        snapshot = _read_json(paths["snapshot"])
    except ContextError:
        return _rebuild_snapshot(task_id, _read_events(paths["events"]))
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


def _matching_contract_publish_events(
    contract: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    seal = contract.get("seal")
    if not isinstance(seal, Mapping):
        return []
    expected = {
        "task_id": contract.get("task_id"),
        "version": contract.get("version"),
        "integrity_digest": seal.get("integrity_digest"),
        "confirmed_by": seal.get("confirmed_by"),
        "confirmed_at": seal.get("confirmed_at"),
    }
    matches: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") if isinstance(event, Mapping) else None
        try:
            _validate_contract_publish_event(event, task_id=str(contract.get("task_id")))
        except ContextError:
            continue
        if isinstance(payload, Mapping) and all(payload.get(field) == value for field, value in expected.items()):
            matches.append(dict(event))
    return matches


def _has_truth_reset(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        event.get("event_type") == "contract-published"
        and isinstance(event.get("payload"), Mapping)
        and "truth_source_reset" in event["payload"]
        for event in events
    )


def _snapshot_matches_sealed_contract(snapshot: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    """Whether a cached projection can prove it belongs to this sealed contract."""
    projection = snapshot.get("contract")
    seal = contract.get("seal")
    if not isinstance(projection, Mapping) or not isinstance(seal, Mapping):
        return False
    expected = {
        "task_id": contract.get("task_id"),
        "version": contract.get("version"),
        "integrity_digest": seal.get("integrity_digest"),
        "confirmed_by": seal.get("confirmed_by"),
        "confirmed_at": seal.get("confirmed_at"),
    }
    return all(projection.get(field) == value for field, value in expected.items())


def _committed_contract_errors(
    contract: Mapping[str, Any], events: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any],
) -> list[str]:
    """Return one stable commit code for a truth-enabled sealed contract."""
    matching = _matching_contract_publish_events(contract, events)
    published = [event for event in events if event.get("event_type") == "contract-published"]
    latest = published[-1] if published else None
    if len(matching) > 1:
        return ["CONTRACT_COMMIT_DUPLICATE_EVENT"]
    if len(matching) == 0:
        if not published:
            return ["CONTRACT_COMMIT_MISSING_EVENT"]
        same_version = [
            event for event in published
            if isinstance(event.get("payload"), Mapping)
            and event["payload"].get("version") == contract.get("version")
        ]
        latest_payload = latest.get("payload") if isinstance(latest, Mapping) else None
        latest_version = latest_payload.get("version") if isinstance(latest_payload, Mapping) else None
        if same_version or _version_key(latest_version) >= _version_key(contract.get("version")):
            return ["CONTRACT_COMMIT_MISMATCH"]
        return ["CONTRACT_COMMIT_MISSING_EVENT"]
    if latest != matching[0]:
        return ["CONTRACT_COMMIT_MISMATCH"]
    reset = matching[0].get("payload", {}).get("truth_source_reset")
    if not isinstance(reset, Mapping):
        return ["CONTRACT_COMMIT_MISMATCH"]
    source_ids = [item.get("id") for item in contract.get("truth_sources", {}).get("items", []) if isinstance(item, Mapping)] if isinstance(contract.get("truth_sources"), Mapping) else []
    if reset.get("source_ids") != source_ids:
        return ["CONTRACT_COMMIT_MISMATCH"]
    truth = snapshot.get("truth_sources")
    if (
        not isinstance(truth, Mapping)
        or type(truth.get("generation")) is not int
        or truth["generation"] < reset.get("generation")
        or set(truth.get("sources", {})) != set(source_ids)
    ):
        return ["CONTRACT_COMMIT_MISMATCH"]
    return []


def _load_committed_task_view_locked(task_id: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    contract = _read_json(paths["contract"])
    errors = _validate_sealed_contract(contract)
    if errors:
        raise ContextError("release gate failed: " + "; ".join(errors))
    try:
        snapshot = _read_json(paths["snapshot"])
    except ContextError:
        snapshot = None
    truth_history_enabled = truth_sources_enabled(contract) or (
        isinstance(snapshot, Mapping) and isinstance(snapshot.get("truth_sources"), Mapping)
    )
    trusted_never_enabled_snapshot = (
        isinstance(snapshot, Mapping)
        and not truth_history_enabled
        and _snapshot_matches_sealed_contract(snapshot, contract)
    )
    if trusted_never_enabled_snapshot:
        return {
            "contract": contract,
            "snapshot": snapshot,
            "events": [],
            "contract_digest": contract["seal"]["integrity_digest"],
            "event_tail_id": None,
            "event_count": snapshot.get("event_count", 0),
            "truth_history_enabled": False,
        }
    events = _read_events(paths["events"])
    if not truth_history_enabled:
        truth_history_enabled = _has_truth_reset(events)
    rebuilt = _rebuild_snapshot(task_id, events)
    if truth_history_enabled:
        committed = _committed_contract_errors(contract, events, rebuilt)
        if committed:
            raise ContextError(committed[0])
        # A strict projection is authoritative even if a stale snapshot has the
        # same event count; the snapshot is only a write-through cache.
        snapshot = rebuilt
    elif snapshot is None:
        snapshot = rebuilt
    return {
        "contract": contract,
        "snapshot": snapshot,
        "events": events,
        "contract_digest": contract["seal"]["integrity_digest"],
        "event_tail_id": events[-1].get("event_id") if events else None,
        "event_count": len(events),
        "truth_history_enabled": truth_history_enabled,
    }


def _append_missing_publish_event_locked(
    contract: Mapping[str, Any], paths: Mapping[str, Path], *, events: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    seal = contract.get("seal")
    if not isinstance(seal, Mapping):
        raise ContextError("cannot repair an unsealed contract")
    payload: dict[str, Any] = {
        "task_id": contract.get("task_id"),
        "version": contract.get("version"),
        "integrity_digest": seal.get("integrity_digest"),
        "confirmed_by": seal.get("confirmed_by"),
        "confirmed_at": seal.get("confirmed_at"),
    }
    reset = _truth_source_reset_payload(contract, snapshot)
    if reset is not None:
        payload["truth_source_reset"] = reset
    event = _new_event(str(contract.get("task_id")), "contract-published", str(seal.get("confirmed_by")), payload)
    _append_event_locked(paths, deepcopy(dict(snapshot)), event)
    return event


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
    protect_contract: bool = True,
) -> dict[str, Any]:
    """Validate, seal, and publish a publisher-authored task contract.

    Updating an existing contract requires a greater version and a fresh seal.
    """

    if not isinstance(protect_contract, bool):
        raise TypeError("protect_contract must be a boolean")

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
        existing_truth_history = False
        existing_events: list[dict[str, Any]] | None = None
        if paths["contract"].exists():
            existing = _read_json(paths["contract"])
            existing_errors = _validate_sealed_contract(existing)
            if existing_errors:
                raise ContextError("existing contract is invalid: " + "; ".join(existing_errors))
            try:
                existing_snapshot = _read_json(paths["snapshot"])
            except ContextError:
                existing_snapshot = None
            existing_truth_history = truth_sources_enabled(existing) or (
                isinstance(existing_snapshot, Mapping)
                and isinstance(existing_snapshot.get("truth_sources"), Mapping)
            )
            trusted_never_enabled_snapshot = (
                isinstance(existing_snapshot, Mapping)
                and not existing_truth_history
                and _snapshot_matches_sealed_contract(existing_snapshot, existing)
            )
            if not existing_truth_history and not trusted_never_enabled_snapshot:
                existing_events = _read_events(paths["events"])
                existing_truth_history = _has_truth_reset(existing_events)
            if existing_truth_history:
                if existing_events is None:
                    existing_events = _read_events(paths["events"])
                if not truth_sources_enabled(existing):
                    existing_truth_history = _has_truth_reset(existing_events)
                existing_rebuilt = _rebuild_snapshot(task_id, existing_events)
                commit_errors = _committed_contract_errors(existing, existing_events, existing_rebuilt)
                same_publisher_fields = _canonical_contract_input(value) == _canonical_contract_input(existing)
                matching_events = _matching_contract_publish_events(existing, existing_events)
                seal = existing.get("seal")
                confirmed_matches = isinstance(seal, Mapping) and confirmed_by == seal.get("confirmed_by")
                if (
                    same_publisher_fields
                    and confirmed_matches
                    and not matching_events
                    and commit_errors == ["CONTRACT_COMMIT_MISSING_EVENT"]
                ):
                    _append_missing_publish_event_locked(
                        existing, paths, events=existing_events, snapshot=existing_rebuilt,
                    )
                    return existing
                if commit_errors:
                    raise ContextError(commit_errors[0])
            if _version_key(value["version"]) <= _version_key(existing.get("version")):
                raise ContextError("contract update requires a greater version")

        value.pop("seal", None)
        value["seal"] = {
            "confirmed_by": confirmed_by,
            "confirmed_at": _now(),
            "file_protection": CONTRACT_FILE_PROTECTION if protect_contract else "none",
        }
        value["seal"]["integrity_digest"] = _contract_digest(value)
        _atomic_write_json(
            paths["contract"],
            value,
            mode=0o444 if protect_contract else None,
        )
        strict_rebuild = truth_sources_enabled(value) or existing_truth_history
        if strict_rebuild:
            events = _read_events(paths["events"])
            snapshot = _rebuild_snapshot(task_id, events)
        else:
            snapshot = _load_snapshot(task_id, paths)
        payload: dict[str, Any] = {
            "task_id": task_id,
            "version": value["version"],
            "integrity_digest": value["seal"]["integrity_digest"],
            "confirmed_by": confirmed_by,
            "confirmed_at": value["seal"]["confirmed_at"],
        }
        reset = _truth_source_reset_payload(value, snapshot)
        if reset is not None:
            payload["truth_source_reset"] = reset
        event = _new_event(task_id, "contract-published", confirmed_by, payload)
        _append_event_locked(paths, snapshot, event)
    return value


def mark_truth_sources_dirty(
    task_id: str,
    *,
    change_kind: str,
    actor: str,
    reason: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Record one declared change that invalidates matching truth sources."""

    if not _truth_single_line(actor):
        raise ContextError("TRUTH_SOURCE_ACTOR_INVALID")
    if not _truth_single_line(change_kind):
        raise ContextError("TRUTH_SOURCE_CHANGE_KIND_INVALID")
    if not _truth_single_line(reason):
        raise ContextError("TRUTH_SOURCE_REASON_INVALID")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        truth = view["contract"].get("truth_sources")
        items = truth.get("items") if isinstance(truth, Mapping) else None
        if not isinstance(items, list):
            raise ContextError("TRUTH_SOURCE_CHANGE_KIND_UNDECLARED")
        affected_source_ids = sorted(
            item["id"]
            for item in items
            if isinstance(item, Mapping)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("invalidate_on_change_kinds"), list)
            and change_kind in item["invalidate_on_change_kinds"]
        )
        if not affected_source_ids:
            raise ContextError("TRUTH_SOURCE_CHANGE_KIND_UNDECLARED")
        generation = view["snapshot"]["truth_sources"]["generation"] + 1
        payload = {
            "contract_digest": view["contract_digest"],
            "generation": generation,
            "change_kind": change_kind,
            "reason": reason,
            "affected_source_ids": affected_source_ids,
        }
        event = _new_event(task_id, "truth-source-dirtied", actor, payload)
        _append_event_locked(paths, view["snapshot"], event)
    return {
        "event_id": event["event_id"],
        "generation": generation,
        "affected_source_ids": affected_source_ids,
    }


def observe_truth_source(
    task_id: str,
    *,
    source_id: str,
    actor: str,
    verification_refs: Sequence[str],
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Bind one owner readback to the current sealed source generation."""

    if not isinstance(source_id, str) or not source_id:
        raise ContextError("TRUTH_SOURCE_NOT_DECLARED")
    if not _truth_single_line(actor):
        raise ContextError("TRUTH_SOURCE_ACTOR_INVALID")
    if (
        isinstance(verification_refs, (str, bytes))
        or not isinstance(verification_refs, Sequence)
        or not verification_refs
        or not all(isinstance(ref, str) and VERIFICATION_REF_RE.fullmatch(ref) for ref in verification_refs)
        or len(set(verification_refs)) != len(verification_refs)
    ):
        raise ContextError("TRUTH_SOURCE_VERIFICATION_REFS_INVALID")
    refs = list(verification_refs)
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        truth = view["contract"].get("truth_sources")
        items = truth.get("items") if isinstance(truth, Mapping) else None
        source = next(
            (
                item for item in items
                if isinstance(item, Mapping) and item.get("id") == source_id
            ),
            None,
        ) if isinstance(items, list) else None
        if not isinstance(source, Mapping):
            raise ContextError("TRUTH_SOURCE_NOT_DECLARED")
        if actor != source.get("owner"):
            raise ContextError("TRUTH_SOURCE_OWNER_MISMATCH")
        sources = view["snapshot"].get("truth_sources", {}).get("sources", {})
        source_state = sources.get(source_id) if isinstance(sources, Mapping) else None
        if not isinstance(source_state, Mapping) or type(source_state.get("required_generation")) is not int:
            raise ContextError("TRUTH_SOURCE_STATE_INVALID")
        resolution = resolve_file_source(view["contract"]["workspace_root"], source["source_ref"])
        if not isinstance(resolution, Mapping):
            raise ContextError("TRUTH_SOURCE_RESOLVER_UNKNOWN")
        fingerprint = resolution.get("fingerprint")
        status = resolution.get("status")
        code = resolution.get("code")
        if status == "pass" and code is None and isinstance(fingerprint, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
            pass
        elif (
            isinstance(code, str)
            and _TRUTH_SOURCE_RESOLVER_FAILURES.get(code) == status
            and fingerprint is None
        ):
            raise ContextError(code)
        else:
            raise ContextError("TRUTH_SOURCE_RESOLVER_UNKNOWN")
        previous = source_state.get("observation")
        if source_state.get("status") == "observed":
            if not isinstance(previous, Mapping) or not isinstance(previous.get("fingerprint"), str):
                raise ContextError("TRUTH_SOURCE_STATE_INVALID")
            if previous["fingerprint"] != fingerprint:
                raise ContextError("TRUTH_SOURCE_UNDECLARED_CHANGE")
        elif source_state.get("status") not in {"unobserved", "dirty"}:
            raise ContextError("TRUTH_SOURCE_STATE_INVALID")
        observed_generation = source_state["required_generation"]
        payload = {
            "source_id": source_id,
            "contract_digest": view["contract_digest"],
            "observed_generation": observed_generation,
            "fingerprint": fingerprint,
            "verification_refs": refs,
        }
        event = _new_event(task_id, "truth-source-observed", actor, payload)
        _append_event_locked(paths, view["snapshot"], event)
    return {
        "event_id": event["event_id"],
        "source_id": source_id,
        "observed_generation": observed_generation,
        "fingerprint": fingerprint,
        "observed_at": event["created_at"],
    }


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


def externalize_item(
    task_id: str,
    item_id: str,
    *,
    summary: str,
    external_ref: str,
    actor: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Replace bulky wording with a pointer without changing fact identity or controls."""

    if not _truth_single_line(summary):
        raise ValueError("summary must be a non-empty single line")
    if not _truth_single_line(external_ref):
        raise ValueError("external_ref must be a non-empty single line")
    if not _truth_single_line(actor):
        raise ValueError("actor must be a non-empty single line")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        current = view["snapshot"].get("items", {}).get(item_id)
        if not isinstance(current, dict):
            raise ContextError(f"unknown context item: {item_id}")
        if current.get("status") == "superseded":
            raise ContextError(f"cannot externalize superseded item: {item_id}")
        updated = deepcopy(current)
        previous_statement = str(current.get("statement", ""))
        now = _now()
        updated["statement"] = summary.strip()
        metadata = dict(updated.get("metadata") or {})
        metadata.update({
            "externalized_by": actor,
            "externalized_at": now,
            "externalized_ref": external_ref.strip(),
            "externalized_from_digest": (
                "sha256:" + hashlib.sha256(previous_statement.encode("utf-8")).hexdigest()
            ),
        })
        updated["metadata"] = _json_clone(metadata)
        updated["updated_at"] = now
        errors, _ = _item_errors(updated)
        if errors:
            raise ContextError("context externalization rejected: " + "; ".join(errors))
        event = _new_event(
            task_id,
            "item-externalized",
            actor,
            {
                "item": updated,
                "previous_statement_digest": metadata["externalized_from_digest"],
                "external_ref": metadata["externalized_ref"],
            },
        )
        _append_event_locked(paths, view["snapshot"], event)
    return updated


def restore_externalization_controls(
    task_id: str,
    item_id: str,
    *,
    from_item_id: str,
    actor: str,
    reason: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Repair required/severity lost by a legacy supersede-based externalization."""

    if not _truth_single_line(actor):
        raise ValueError("actor must be a non-empty single line")
    if not _truth_single_line(reason):
        raise ValueError("reason must be a non-empty single line")
    paths = _paths(task_id, base_dir)
    with _locked(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        items = view["snapshot"].get("items", {})
        target = items.get(item_id) if isinstance(items, Mapping) else None
        source = items.get(from_item_id) if isinstance(items, Mapping) else None
        if not isinstance(target, dict) or not isinstance(source, dict):
            raise ContextError("CONTROL_RESTORATION_ITEM_MISSING")
        if (
            source.get("status") != "superseded"
            or source.get("superseded_by") != item_id
            or target.get("supersedes") != from_item_id
        ):
            raise ContextError("CONTROL_RESTORATION_LINEAGE_MISMATCH")
        source_metadata = source.get("metadata")
        if not isinstance(source_metadata, Mapping):
            raise ContextError("CONTROL_RESTORATION_SOURCE_CONTROLS_MISSING")
        controls = {
            field: deepcopy(source_metadata[field])
            for field in ("required", "severity")
            if field in source_metadata
        }
        if not controls:
            raise ContextError("CONTROL_RESTORATION_SOURCE_CONTROLS_MISSING")
        target_metadata = dict(target.get("metadata") or {})
        conflicts = [
            field for field, value in controls.items()
            if field in target_metadata and target_metadata[field] != value
        ]
        if conflicts:
            raise ContextError(
                f"CONTROL_RESTORATION_CONFLICT: {sorted(conflicts)}"
            )
        if all(target_metadata.get(field) == value for field, value in controls.items()):
            return deepcopy(target)
        updated = deepcopy(target)
        target_metadata.update(controls)
        updated["metadata"] = _json_clone(target_metadata)
        event = _new_event(
            task_id,
            "item-updated",
            actor,
            {
                "item": updated,
                "control_restoration": {
                    "from_item_id": from_item_id,
                    "fields": sorted(controls),
                    "reason": reason.strip(),
                },
            },
        )
        _append_event_locked(paths, view["snapshot"], event)
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


def _validate_brief_limits(*, max_chars: int, max_items: int | None) -> None:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be positive")


def _brief_candidates(
    snapshot: Mapping[str, Any], include: Sequence[str] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    all_items = snapshot.get("items", {})
    if not isinstance(all_items, dict):
        return [], []
    include_set = set(include or [])
    candidates: list[dict[str, Any]] = []
    filtered_mandatory_ids: list[str] = []
    for identifier, raw in sorted(all_items.items()):
        if not isinstance(raw, dict) or raw.get("status") == "superseded":
            continue
        if include is not None and identifier not in include_set:
            if _brief_is_mandatory(raw):
                filtered_mandatory_ids.append(str(identifier))
            continue
        candidates.append(deepcopy(raw))
    return candidates, filtered_mandatory_ids


def _build_brief_packet(
    task_id: str,
    contract: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    phase: str | None,
    selected: Sequence[Mapping[str, Any]],
    truth_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_items = [dict(item) for item in selected]
    packet = {
        "task_id": task_id,
        "contract_version": contract.get("version"),
        "contract_integrity_digest": (contract.get("seal") or {}).get("integrity_digest"),
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
    if truth_evaluation is not None:
        packet["truth_sources"] = {
            "schema": CAPABILITY,
            "items": _truth_brief_items(truth_evaluation),
        }
    return packet


def _truth_brief_items(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]:
    allowed = (
        "id", "purpose", "source_ref", "owner", "status", "required_generation",
        "observed_generation", "observed_at", "fingerprint",
    )
    results = evaluation.get("results")
    if not isinstance(results, list):
        return []
    return [
        {field: deepcopy(item.get(field)) for field in allowed}
        for item in results
        if isinstance(item, Mapping)
    ]


_BRIEF_ITEM_SECTION_BY_TYPE = {
    "verified-fact": "facts",
    "observation": "observations",
    "assumption": "assumptions",
    "decision": "decisions",
    "question": "questions",
}


def _brief_item_sections(item: Mapping[str, Any]) -> tuple[str, ...]:
    sections: list[str] = []
    section = _BRIEF_ITEM_SECTION_BY_TYPE.get(str(item.get("type")))
    if section is not None:
        sections.append(section)
    if item.get("status") == "conflicted":
        sections.append("conflicts")
    return tuple(sections)


def _brief_selection_delta(
    rendered_line_chars: int,
    sections: Sequence[str],
    section_counts: Mapping[str, int],
) -> int:
    return sum(
        rendered_line_chars - len("- None")
        if section_counts.get(section, 0) == 0
        else rendered_line_chars + 1
        for section in sections
    )


def _select_brief_items_plan(
    items: Sequence[Mapping[str, Any]], *, max_chars: int, max_items: int | None
) -> dict[str, Any]:
    """Plan deterministic selection while preserving structured overflow details."""

    _validate_brief_limits(max_chars=max_chars, max_items=max_items)
    ordered = sorted((dict(item) for item in items), key=_brief_sort_key)
    mandatory_items = [item for item in ordered if _brief_is_mandatory(item)]
    empty_selection_chars = len(_brief_to_markdown(_brief_selection_packet([])))
    item_profiles: dict[str, tuple[int, tuple[str, ...]]] = {}
    for item in ordered:
        identifier = str(item.get("id", ""))
        item_profiles[identifier] = (
            len(_brief_item_to_markdown(item)),
            _brief_item_sections(item),
        )
    mandatory_item_sizes = []
    mandatory_selection_chars = empty_selection_chars
    mandatory_section_counts: dict[str, int] = {}
    for item in mandatory_items:
        identifier = str(item.get("id", ""))
        rendered_line_chars, sections = item_profiles[identifier]
        mandatory_item_sizes.append(
            {
                "id": identifier,
                "rendered_chars": _brief_selection_delta(rendered_line_chars, sections, {}),
            }
        )
        mandatory_selection_chars += _brief_selection_delta(
            rendered_line_chars,
            sections,
            mandatory_section_counts,
        )
        for section in sections:
            mandatory_section_counts[section] = mandatory_section_counts.get(section, 0) + 1
    overflow: dict[str, Any] | None = None
    if max_items is not None:
        omitted = ordered[max_items:]
        omitted_mandatory = [item for item in omitted if _brief_is_mandatory(item)]
        if omitted_mandatory:
            overflow = {
                "code": "BRIEF_REQUIRED_OVERFLOW",
                "kind": "max_items",
                "message": "BRIEF_REQUIRED_OVERFLOW: max_items would omit a mandatory item",
                "item_ids": [str(item.get("id", "")) for item in omitted_mandatory],
            }
        ordered = ordered[:max_items]

    selected: list[dict[str, Any]] = []
    selected_selection_chars = empty_selection_chars
    selected_section_counts: dict[str, int] = {}
    for item in ordered:
        identifier = str(item.get("id", ""))
        rendered_line_chars, sections = item_profiles[identifier]
        candidate_chars = selected_selection_chars + _brief_selection_delta(
            rendered_line_chars,
            sections,
            selected_section_counts,
        )
        if candidate_chars <= max_chars:
            selected.append(item)
            selected_selection_chars = candidate_chars
            for section in sections:
                selected_section_counts[section] = selected_section_counts.get(section, 0) + 1
    selected_ids = {str(item.get("id", "")) for item in selected}
    omitted_items = [
        dict(item) for item in sorted((dict(item) for item in items), key=_brief_sort_key)
        if str(item.get("id", "")) not in selected_ids
    ]
    omitted_mandatory_ids = [
        str(item.get("id", ""))
        for item in omitted_items
        if _brief_is_mandatory(item)
    ]
    if omitted_mandatory_ids and overflow is None:
        overflow = {
            "code": "BRIEF_REQUIRED_OVERFLOW",
            "kind": "mandatory",
            "message": "BRIEF_REQUIRED_OVERFLOW: mandatory items exceed max_chars",
            "item_ids": omitted_mandatory_ids,
        }
    if overflow is not None:
        overflow["omitted_mandatory_ids"] = omitted_mandatory_ids
    return {
        "selected": selected,
        "overflow": overflow,
        "mandatory": [dict(item) for item in mandatory_items],
        "mandatory_item_sizes": mandatory_item_sizes,
        "mandatory_selection_chars": mandatory_selection_chars,
        "selected_selection_chars": selected_selection_chars,
        "omitted": omitted_items,
    }


def _select_brief_items(
    items: Sequence[Mapping[str, Any]], *, max_chars: int, max_items: int | None
) -> list[dict[str, Any]]:
    """Select ordered items only when the fully rendered candidate still fits."""

    plan = _select_brief_items_plan(items, max_chars=max_chars, max_items=max_items)
    if plan["overflow"] is not None:
        raise ContextError(plan["overflow"]["message"])
    return plan["selected"]


def _is_cjk(character: str) -> bool:
    value = ord(character)
    return (
        0x3400 <= value <= 0x4DBF
        or 0x4E00 <= value <= 0x9FFF
        or 0xF900 <= value <= 0xFAFF
        or 0x20000 <= value <= 0x2EBEF
    )


def _brief_text_metrics(text: str, *, basis: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ascii_chars = sum(ord(character) < 128 for character in text)
    cjk_chars = sum(_is_cjk(character) for character in text)
    other_chars = len(text) - ascii_chars - cjk_chars
    lower_bound = (ascii_chars + 3) // 4 + cjk_chars + (other_chars + 1) // 2
    upper_bound = (ascii_chars + 2) // 3 + 2 * cjk_chars + other_chars
    return (
        {
            "basis": basis,
            "ascii_chars": ascii_chars,
            "cjk_chars": cjk_chars,
            "other_chars": other_chars,
        },
        {
            "range_low": lower_bound,
            "range_high": upper_bound,
            "method": "portable-heuristic-v1",
            "semantics": "heuristic-not-guaranteed",
            "advisory": True,
        },
    )


def _brief_text_metrics_from_lines(
    lines: Iterable[str], *, basis: str
) -> tuple[dict[str, Any], dict[str, Any], int]:
    ascii_chars = 0
    cjk_chars = 0
    other_chars = 0
    line_count = 0
    for line in lines:
        if line_count:
            ascii_chars += 1  # The rendered separator is one ASCII newline.
        line_ascii_chars = sum(ord(character) < 128 for character in line)
        line_cjk_chars = sum(_is_cjk(character) for character in line)
        ascii_chars += line_ascii_chars
        cjk_chars += line_cjk_chars
        other_chars += len(line) - line_ascii_chars - line_cjk_chars
        line_count += 1
    total_chars = ascii_chars + cjk_chars + other_chars
    lower_bound = (ascii_chars + 3) // 4 + cjk_chars + (other_chars + 1) // 2
    upper_bound = (ascii_chars + 2) // 3 + 2 * cjk_chars + other_chars
    return (
        {
            "basis": basis,
            "ascii_chars": ascii_chars,
            "cjk_chars": cjk_chars,
            "other_chars": other_chars,
        },
        {
            "range_low": lower_bound,
            "range_high": upper_bound,
            "method": "portable-heuristic-v1",
            "semantics": "heuristic-not-guaranteed",
            "advisory": True,
        },
        total_chars,
    )


def _plan_brief_from_view(
    task_id: str,
    *,
    contract: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    truth_evaluation: Mapping[str, Any] | None,
    phase: str | None,
    include: Sequence[str] | None,
    max_items: int | None,
    max_chars: int,
) -> dict[str, Any]:
    _validate_brief_limits(max_chars=max_chars, max_items=max_items)
    candidates, filtered_mandatory_ids = _brief_candidates(snapshot, include)
    empty_packet = _build_brief_packet(task_id, contract, snapshot, phase, [], truth_evaluation)
    empty_prompt = _brief_to_markdown(empty_packet)
    empty_selection_prompt = _brief_to_markdown(_brief_selection_packet([]))
    prompt_adjustment_chars = len(empty_prompt) - len(empty_selection_prompt)
    selection_prompt_budget_chars = max_chars - prompt_adjustment_chars

    mandatory = [item for item in candidates if _brief_is_mandatory(item)]
    if selection_prompt_budget_chars <= 0:
        measured_selection = _select_brief_items_plan(
            candidates,
            max_chars=1,
            max_items=max_items,
        )
        selection_plan = {
            "selected": [],
            "mandatory": mandatory,
            "mandatory_item_sizes": measured_selection["mandatory_item_sizes"],
            "mandatory_selection_chars": measured_selection["mandatory_selection_chars"],
            "selected_selection_chars": len(empty_selection_prompt),
            "omitted": candidates,
            "overflow": {
                "code": "BRIEF_REQUIRED_OVERFLOW",
                "kind": "fixed",
                "message": "BRIEF_REQUIRED_OVERFLOW: fixed brief content exceeds max_chars",
                "item_ids": [],
            },
        }
    else:
        selection_plan = _select_brief_items_plan(
            candidates,
            max_chars=selection_prompt_budget_chars,
            max_items=max_items,
        )

    selected = selection_plan["selected"]
    packet = _build_brief_packet(task_id, contract, snapshot, phase, selected, truth_evaluation)
    selected_prompt = _brief_to_markdown(packet)
    brief_overflow = selection_plan["overflow"]
    if brief_overflow is None and len(selected_prompt) > max_chars:
        brief_overflow = {
            "code": "BRIEF_REQUIRED_OVERFLOW",
            "kind": "final_render",
            "message": "BRIEF_REQUIRED_OVERFLOW: brief content exceeds max_chars",
            "item_ids": [],
        }
    packet["prompt"] = selected_prompt

    largest_items = sorted(
        selection_plan["mandatory_item_sizes"],
        key=lambda item: (-item["rendered_chars"], item["id"]),
    )[:5]
    diagnostic_overflow = brief_overflow
    if len(empty_prompt) > max_chars:
        diagnostic_overflow = {
            "code": "BRIEF_REQUIRED_OVERFLOW",
            "kind": "fixed",
            "message": "BRIEF_REQUIRED_OVERFLOW: fixed brief content exceeds max_chars",
            "item_ids": [],
        }
    if diagnostic_overflow is not None:
        omitted_mandatory_ids = [
            str(item.get("id", ""))
            for item in selection_plan["omitted"]
            if _brief_is_mandatory(item)
        ]
        diagnostic_overflow = {
            **diagnostic_overflow,
            "item_ids": omitted_mandatory_ids,
            "omitted_mandatory_ids": omitted_mandatory_ids,
            "largest_items": largest_items,
        }
    if diagnostic_overflow is None:
        text_metrics, token_estimate = _brief_text_metrics(
            selected_prompt,
            basis="selected_prompt",
        )
    elif diagnostic_overflow["kind"] != "fixed" and mandatory:
        mandatory_packet = _build_brief_packet(task_id, contract, snapshot, phase, mandatory, truth_evaluation)
        text_metrics, token_estimate, measured_prompt_chars = _brief_text_metrics_from_lines(
            _brief_markdown_lines(mandatory_packet),
            basis="mandatory_prompt",
        )
    else:
        text_metrics, token_estimate = _brief_text_metrics(
            empty_prompt,
            basis="empty_prompt",
        )
    mandatory_selection_chars = selection_plan["mandatory_selection_chars"]
    mandatory_prompt_chars = prompt_adjustment_chars + mandatory_selection_chars
    if diagnostic_overflow is not None and diagnostic_overflow["kind"] != "fixed" and mandatory:
        mandatory_prompt_chars = measured_prompt_chars
    selected_selection_chars = selection_plan["selected_selection_chars"]
    selected_ids = [str(item.get("id", "")) for item in selected]
    omitted_ids = [str(item.get("id", "")) for item in selection_plan["omitted"]]
    diagnostics = {
        "status": "ready" if diagnostic_overflow is None else "overflow",
        "fits": diagnostic_overflow is None,
        "usable": diagnostic_overflow is None,
        "overflow": diagnostic_overflow,
        "budget": {
            "max_chars": max_chars,
            "max_items": max_items,
            "fixed_prompt_chars": len(empty_prompt),
            "selection_wrapper_chars": len(empty_selection_prompt),
            "prompt_adjustment_chars": prompt_adjustment_chars,
            "selection_prompt_budget_chars": selection_prompt_budget_chars,
            "selection_prompt_chars": selected_selection_chars,
            "item_contribution_chars": selected_selection_chars - len(empty_selection_prompt),
            "prompt_chars": len(selected_prompt) if diagnostic_overflow is None else None,
            "selected_prompt_chars": len(selected_prompt),
            "mandatory_selection_chars": mandatory_selection_chars,
            "mandatory_prompt_chars": mandatory_prompt_chars,
        },
        "items": {
            "candidate_count": len(candidates),
            "mandatory_count": len(mandatory),
            "selected_count": len(selected),
            "omitted_count": len(selection_plan["omitted"]),
            "selected_ids": selected_ids,
            "omitted_ids": omitted_ids,
            "filtered_mandatory_ids": filtered_mandatory_ids,
        },
        "text": text_metrics,
        "token_estimate": token_estimate,
    }
    return {"packet": packet, "diagnostics": diagnostics, "brief_overflow": brief_overflow}


def _plan_brief(
    task_id: str,
    *,
    phase: str | None,
    include: Sequence[str] | None,
    max_items: int | None,
    max_chars: int,
    base_dir: str | Path | None,
) -> dict[str, Any]:
    """Legacy/gate planner; public brief readers provide live truth evaluation."""
    paths = _paths(task_id, base_dir)
    view = _load_committed_task_view_locked(task_id, paths)
    return _plan_brief_from_view(
        task_id, contract=view["contract"], snapshot=view["snapshot"], truth_evaluation=None,
        phase=phase, include=include, max_items=max_items, max_chars=max_chars,
    )


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
    paths = _paths(task_id, base_dir)
    with _shared_locked_existing(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        evaluation = (
            evaluate_truth_sources(
                view["contract"], view["snapshot"], now=_trusted_utc_now(), resolver=resolve_file_source,
            )
            if truth_sources_enabled(view["contract"])
            else None
        )
        plan = _plan_brief_from_view(
            task_id, contract=view["contract"], snapshot=view["snapshot"], truth_evaluation=evaluation,
            phase=phase, include=include, max_items=max_items, max_chars=max_chars,
        )
    diagnostics = _brief_diagnostics_from_plan(plan)
    overflow = diagnostics["overflow"]
    if overflow is not None:
        raise ContextError(overflow["message"])
    return plan["packet"]


def _brief_diagnostics_from_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = deepcopy(plan["diagnostics"])
    filtered = diagnostics["items"]["filtered_mandatory_ids"]
    if filtered and diagnostics["overflow"] is None:
        diagnostics["status"] = "overflow"
        diagnostics["fits"] = False
        diagnostics["usable"] = False
        diagnostics["overflow"] = {
            "code": "BRIEF_REQUIRED_OVERFLOW",
            "kind": "include",
            "message": "BRIEF_REQUIRED_OVERFLOW: include would omit a mandatory item",
            "item_ids": filtered,
            "omitted_mandatory_ids": filtered,
            "largest_items": [],
        }
    return diagnostics


def brief_diagnostics(
    task_id: str,
    *,
    phase: str | None = None,
    include: Sequence[str] | None = None,
    max_items: int | None = None,
    max_chars: int = 8000,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Measure brief fit without weakening or suppressing required-content overflow."""
    paths = _paths(task_id, base_dir)
    with _shared_locked_existing(paths["root"]):
        view = _load_committed_task_view_locked(task_id, paths)
        evaluation = (
            evaluate_truth_sources(
                view["contract"], view["snapshot"], now=_trusted_utc_now(), resolver=resolve_file_source,
            )
            if truth_sources_enabled(view["contract"])
            else None
        )
        plan = _plan_brief_from_view(
            task_id, contract=view["contract"], snapshot=view["snapshot"], truth_evaluation=evaluation,
            phase=phase, include=include, max_items=max_items, max_chars=max_chars,
        )
    diagnostics = _brief_diagnostics_from_plan(plan)
    diagnostics["storage"] = _storage_info(task_id, base_dir)
    return diagnostics


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
        "required_hops_mode",
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


def _brief_markdown_lines(packet: Mapping[str, Any]) -> Iterable[str]:
    yield f"# Controlled Task Brief: {packet.get('task_id')}"
    yield f"Contract version: {packet.get('contract_version')}"
    yield f"Objective: {packet.get('objective')}"
    yield ""
    yield "## Rules"
    yield "Use only the facts and decisions below. Treat assumptions as unverified. Do not resolve conflicts silently."
    yield "Do not add or reinterpret acceptance criteria. Return evidence pointers and proposed context changes."
    truth_sources = packet.get("truth_sources")
    if isinstance(truth_sources, Mapping):
        yield ""
        yield "## Truth Source Controls"
        for item in truth_sources.get("items", []):
            yield f"- {_brief_json(item)}"
    actor_roles = packet.get("actor_roles")
    if isinstance(actor_roles, Mapping) and actor_roles:
        yield ""
        yield "## Actor Roles"
        yield f"- actor_roles={_brief_json(actor_roles)}"
    for heading, key in (
        ("Scope", "scope"),
        ("Out of Scope", "out_of_scope"),
        ("Constraints", "constraints"),
    ):
        values = packet.get(key) or []
        yield ""
        yield f"## {heading}"
        if not values:
            yield "- None"
            continue
        for value in values:
            yield f"- {value}"
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
        yield ""
        yield f"## {heading}"
        if not values:
            yield "- None"
            continue
        for value in values:
            if isinstance(value, dict):
                if key == "acceptance_criteria":
                    yield _brief_acceptance_to_markdown(value)
                else:
                    yield _brief_item_to_markdown(value)
            else:
                yield f"- {value}"
    checkpoint_value = packet.get("latest_checkpoint")
    yield ""
    yield "## Latest Checkpoint"
    if isinstance(checkpoint_value, dict):
        yield f"- Phase: {checkpoint_value.get('phase')}"
        yield f"- Next action: {checkpoint_value.get('next_action')}"
        if checkpoint_value.get("blockers"):
            yield f"- Blockers: {checkpoint_value.get('blockers')}"
    else:
        yield "- None"


def _brief_to_markdown(packet: Mapping[str, Any]) -> str:
    return "\n".join(_brief_markdown_lines(packet))


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


def _run_bad_sample_probe(now: datetime) -> dict[str, Any]:
    """Verify that the production completion gate rejects empty required evidence."""

    probe_id = "PROBE-COMPLETION-EMPTY-EVIDENCE"
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
    }
    criterion = {
        "id": "AC-EMPTY-EVIDENCE",
        "criterion": "Completion requires file evidence",
        "required_evidence": ["file"],
    }
    report = _evaluate_completion_criterion(
        criterion,
        None,
        contract,
        resolvers=None,
        verifiers=None,
        now=now,
    )
    rejected = report.get("status") != "pass"
    return {
        "id": probe_id,
        "scanned": 1,
        "expected": "reject",
        "actual": "reject" if rejected else "accept",
        "status": "pass" if rejected else "fail",
    }


def _audit_core(
    task_id: str,
    *,
    documents: Sequence[str | Path] | None = None,
    max_pointer_lag_seconds: float = 0,
    emit: bool = True,
    base_dir: str | Path | None = None,
    now: datetime,
    run_probe: bool,
) -> dict[str, Any]:
    """Audit contract, event/snapshot consistency, item quality, staleness, and pointers."""

    paths = _paths(task_id, base_dir)
    # Truth-enabled reads consume one committed view.  The structural audit is
    # deliberately separate from live source evaluation.
    try:
        view = _load_committed_task_view_locked(task_id, paths)
    except ContextError:
        view = None
    if isinstance(view, Mapping) and truth_sources_enabled(view["contract"]):
        report = _audit_from_view(
            task_id, contract=view["contract"], snapshot=view["snapshot"],
            events=view["events"], documents=documents,
            max_pointer_lag_seconds=max_pointer_lag_seconds, now=now, run_probe=run_probe,
        )
        protection_errors = _contract_file_protection_errors(
            view["contract"], paths["contract"],
        )
        if protection_errors:
            report["errors"].extend(protection_errors)
            report["passed"] = False
        if emit:
            _emit_report(report)
        return report
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
            probe = _run_bad_sample_probe(now)
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
        errors.extend(_contract_file_protection_errors(contract, paths["contract"]))
        try:
            stored_snapshot = _read_json(paths["snapshot"])
        except ContextError:
            stored_snapshot = None
    except ContextError as exc:
        contract = {}
        stored_snapshot = None
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
        truth_history_enabled = truth_sources_enabled(contract) or (
            isinstance(stored_snapshot, Mapping)
            and isinstance(stored_snapshot.get("truth_sources"), Mapping)
        )
        try:
            if truth_history_enabled:
                rebuilt = _rebuild_snapshot(task_id, events)
            else:
                rebuilt = _empty_snapshot(task_id)
                for event in events:
                    rebuilt = _apply_event(rebuilt, event)
        except ContextError as exc:
            events_valid = False
            rebuilt = _empty_snapshot(task_id)
            errors.append(str(exc))
    if events_valid:
        if not truth_history_enabled:
            truth_history_enabled = _has_truth_reset(events)
        if truth_history_enabled:
            commit_errors = _committed_contract_errors(contract, events, rebuilt)
            errors.extend(commit_errors)
        snapshot = deepcopy(stored_snapshot) if isinstance(stored_snapshot, Mapping) else deepcopy(rebuilt)
        if truth_history_enabled and snapshot.get("event_count") != len(events):
            snapshot = deepcopy(rebuilt)
        elif snapshot != rebuilt:
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


def _read_lock_unavailable_audit(task_id: str, error: ContextError, *, emit: bool) -> dict[str, Any]:
    report = {
        "stage": "audit",
        "passed": False,
        "errors": [str(error)],
        "warnings": [],
        "stats": {
            "checked": 0,
            "events": 0,
            "probe": "unknown",
            "probe_id": "PROBE-COMPLETION-EMPTY-EVIDENCE",
            "probe_scanned": 0,
            "probe_expected_rejection": "reject",
            "stale": 0,
            "conflicts": 0,
            "contracts_checked": 0,
            "events_checked": 0,
            "items_checked": 0,
            "pointers_checked": 0,
            "probes_checked": 0,
            **{item_type: 0 for item_type in ITEM_TYPES},
        },
        "contract_version": None,
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
    paths = _paths(task_id, base_dir)
    try:
        with _shared_locked_existing(paths["root"]):
            report = _audit_core(
                task_id,
                documents=documents,
                max_pointer_lag_seconds=max_pointer_lag_seconds,
                emit=emit,
                base_dir=base_dir,
                now=_trusted_utc_now(),
                run_probe=True,
            )
    except ContextError as exc:
        report = _read_lock_unavailable_audit(task_id, exc, emit=emit)
    report["storage"] = _storage_info(task_id, base_dir)
    return report


def _evaluate_truth_phase_locked(
    view: Mapping[str, Any], *, now: datetime,
) -> dict[str, Any] | None:
    """Evaluate declared sources from one already-locked committed view."""

    contract = view.get("contract")
    snapshot = view.get("snapshot")
    if not isinstance(contract, Mapping) or not isinstance(snapshot, Mapping):
        return {
            "status": "unknown",
            "passed": False,
            "results": [],
            "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0},
        }
    if not truth_sources_enabled(contract):
        return None
    return evaluate_truth_sources(
        contract, snapshot, now=now, resolver=resolve_file_source,
    )


def _truth_entry_token(view: Mapping[str, Any]) -> dict[str, Any]:
    """Return only control-plane fields that must remain stable across completion."""

    contract = view.get("contract") if isinstance(view.get("contract"), Mapping) else {}
    snapshot = view.get("snapshot") if isinstance(view.get("snapshot"), Mapping) else {}
    truth = snapshot.get("truth_sources") if isinstance(snapshot.get("truth_sources"), Mapping) else {}
    sources = truth.get("sources") if isinstance(truth.get("sources"), Mapping) else {}
    declared = contract.get("truth_sources") if isinstance(contract.get("truth_sources"), Mapping) else {}
    source_items = declared.get("items") if isinstance(declared.get("items"), list) else []
    required_generations: list[tuple[str, Any]] = []
    for item in source_items:
        source_id = item.get("id") if isinstance(item, Mapping) else None
        state = sources.get(source_id) if isinstance(source_id, str) and isinstance(sources, Mapping) else None
        required_generations.append((source_id if isinstance(source_id, str) else "", state.get("required_generation") if isinstance(state, Mapping) else None))
    return {
        "contract_digest": view.get("contract_digest"),
        "event_tail_id": view.get("event_tail_id"),
        "event_count": view.get("event_count"),
        "truth_generation": truth.get("generation") if isinstance(truth, Mapping) else None,
        "required_generations": required_generations,
    }


def _audit_from_view(
    task_id: str,
    *,
    contract: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    documents: Sequence[str | Path] | None,
    max_pointer_lag_seconds: float,
    now: datetime,
    run_probe: bool,
) -> dict[str, Any]:
    """Audit an already-loaded committed view without truth-source I/O."""

    errors = list(_validate_sealed_contract(contract))
    warnings: list[str] = []
    probe = {
        "id": "PROBE-COMPLETION-EMPTY-EVIDENCE", "scanned": 0,
        "expected": "reject", "actual": "not-run", "status": "not-run",
    }
    if run_probe:
        try:
            probe = _run_bad_sample_probe(now)
        except Exception as exc:
            probe = {
                "id": "PROBE-COMPLETION-EMPTY-EVIDENCE", "scanned": 0,
                "expected": "reject", "actual": "error", "status": "fail",
            }
            errors.append(f"completion bad-sample probe raised {type(exc).__name__}")
        if probe["status"] != "pass":
            errors.append(
                f"completion bad-sample probe {probe['id']} failed: "
                f"expected {probe['expected']}, got {probe['actual']}"
            )
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
        source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
        evidence_refs = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        for ref in [source.get("ref"), *evidence_refs]:
            if isinstance(ref, str) and ref.startswith("file:"):
                file_path = Path(ref[5:]).expanduser()
                if not file_path.is_absolute():
                    file_path = Path.cwd() / file_path
                if not file_path.exists():
                    errors.append(f"{identifier}: missing file reference {ref}")
    pointer_checked = 0
    if documents:
        document_errors, document_warnings, pointer_checked = _audit_documents(
            documents, max_pointer_lag_seconds,
        )
        errors.extend(document_errors)
        warnings.extend(document_warnings)
    return {
        "stage": "audit", "passed": not errors, "errors": errors, "warnings": warnings,
        "stats": {
            "checked": len(items), "events": snapshot.get("event_count", 0),
            "probe": probe["status"], "probe_id": probe["id"],
            "probe_scanned": probe["scanned"], "probe_expected_rejection": probe["expected"],
            "stale": stale_count, "conflicts": conflict_count,
            "contracts_checked": 1, "events_checked": len(events), "items_checked": len(items),
            "pointers_checked": pointer_checked, "probes_checked": 1 if run_probe else 0,
            **counts,
        },
        "contract_version": contract.get("version"),
    }


def _truth_gate_errors(evaluation: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for result in evaluation.get("results", []):
        if not isinstance(result, Mapping) or result.get("status") == "pass":
            continue
        source_id = result.get("id", "unknown")
        codes = result.get("codes") if isinstance(result.get("codes"), list) else ["TRUTH_SOURCE_RESOLVER_UNKNOWN"]
        errors.append(f"truth source {source_id} is {result.get('status', 'unknown')}: {codes}")
    if not errors and not evaluation.get("passed"):
        errors.append("truth source evaluation is unknown: ['TRUTH_SOURCE_RESOLVER_UNKNOWN']")
    return errors


def _truth_gate_base_checks(
    stage: str, snapshot: Mapping[str, Any], required_item_ids: Sequence[str] | None,
    errors: list[str],
) -> None:
    if stage not in {"resume", "handoff", "completion"}:
        return
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
    targets = ({identifier for identifier, item in items.items() if not isinstance(item, Mapping) or item.get("status") != "superseded"}
               if required_item_ids is None else set(required_item_ids))
    for identifier in sorted(targets):
        item = items.get(identifier)
        if not isinstance(item, dict):
            errors.append(f"required context item missing: {identifier}")
        elif item.get("status") == "superseded":
            errors.append(f"required context item is superseded: {identifier}")
        elif item.get("status") == "conflicted" and identifier not in globally_blocked:
            errors.append(f"required context item is conflicted: {identifier}")
        elif _item_is_stale(item):
            errors.append(f"required mutable fact is stale: {identifier}")
        else:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            if identifier not in globally_blocked and (metadata.get("blocking") is True or metadata.get("blocker") is True):
                errors.append(f"blocking context item remains: {identifier}")
    if stage == "handoff":
        checkpoint_value = snapshot.get("latest_checkpoint")
        if not isinstance(checkpoint_value, dict):
            errors.append("handoff requires a checkpoint")
        elif not checkpoint_value.get("next_action"):
            errors.append("handoff checkpoint requires next_action")


def _truth_gate_final(
    *, stage: str, report: Mapping[str, Any], errors: list[str], warnings: list[str],
    criteria: Mapping[str, Any], criteria_checked: int, evidence_attempts: int,
    brief_report: Mapping[str, Any] | None, contract: Mapping[str, Any],
    evaluation: Mapping[str, Any], emit: bool,
) -> dict[str, Any]:
    final = {
        "stage": stage, "passed": not errors, "errors": errors, "warnings": warnings,
        "criteria": dict(criteria), "truth_source_results": deepcopy(evaluation.get("results", [])),
        "stats": {
            **report["stats"], "criteria_checked": criteria_checked,
            "evidence_attempts": evidence_attempts,
            "truth_sources_checked": evaluation.get("stats", {}).get("truth_sources_checked", 0),
            "truth_source_resolution_attempts": evaluation.get("stats", {}).get("truth_source_resolution_attempts", 0),
            "brief_status": (brief_report or {}).get("status", "unavailable"),
            "brief_overflow_kind": ((brief_report or {}).get("overflow") or {}).get("kind"),
            "brief_fixed_prompt_chars": (brief_report or {}).get("budget", {}).get("fixed_prompt_chars"),
            "brief_mandatory_prompt_chars": (brief_report or {}).get("budget", {}).get("mandatory_prompt_chars"),
        },
        "contract_version": contract.get("version"),
    }
    if emit:
        _emit_report(final)
    return final


def _truth_unknown_gate_report(
    *, task_id: str, stage: str, contract: Mapping[str, Any], error: ContextError,
    emit: bool,
) -> dict[str, Any]:
    declared = contract.get("truth_sources") if isinstance(contract.get("truth_sources"), Mapping) else {}
    items = declared.get("items") if isinstance(declared.get("items"), list) else []
    results = [
        {"id": item.get("id"), "status": "unknown", "codes": ["TRUTH_SOURCE_RESOLVER_UNKNOWN"]}
        for item in items if isinstance(item, Mapping)
    ]
    report = _read_lock_unavailable_audit(task_id, error, emit=False)
    report.update({
        "stage": stage,
        "criteria": {},
        "truth_source_results": results,
        "contract_version": contract.get("version"),
    })
    report["stats"].update({
        "criteria_checked": 0, "evidence_attempts": 0,
        "truth_sources_checked": 0, "truth_source_resolution_attempts": 0,
        "brief_status": "unavailable", "brief_overflow_kind": None,
        "brief_fixed_prompt_chars": None, "brief_mandatory_prompt_chars": None,
    })
    if emit:
        _emit_report(report)
    return report


def _truth_gate_entry_locked(
    task_id: str, *, view: Mapping[str, Any], stage: str,
    required_item_ids: Sequence[str] | None, documents: Sequence[str | Path] | None,
    resolvers: Mapping[str, Any] | None, verifiers: Mapping[str, Any] | None,
    clock: Any, run_probe: bool, base_dir: str | Path | None,
) -> dict[str, Any]:
    """Build all entry verdict inputs while the caller holds the shared lock."""
    entry_now = clock().astimezone(timezone.utc)
    report = _audit_from_view(
        task_id, contract=view["contract"], snapshot=view["snapshot"], events=view["events"],
        documents=documents, max_pointer_lag_seconds=0, now=entry_now, run_probe=run_probe,
    )
    truth = _evaluate_truth_phase_locked(view, now=entry_now)
    if truth is None:
        truth = {"status": "unknown", "passed": False, "results": [],
                 "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0}}
    errors = list(report["errors"])
    errors.extend(
        _contract_file_protection_errors(
            view["contract"], _paths(task_id, base_dir)["contract"],
        )
    )
    warnings = list(report["warnings"])
    handler_errors, handlers_checked = runtime_evidence_handler_errors(
        view["contract"], resolvers=resolvers, verifiers=verifiers,
    )
    errors.extend(handler_errors)
    if evidence_handlers_enabled(view["contract"]):
        report["stats"]["evidence_handlers_checked"] = handlers_checked
    if not truth["passed"]:
        errors.extend(_truth_gate_errors(truth))
    brief_report: dict[str, Any] | None = None
    if stage in {"release", "resume", "handoff"}:
        plan = _plan_brief_from_view(
            task_id, contract=view["contract"], snapshot=view["snapshot"], truth_evaluation=truth,
            phase=None, include=None, max_items=None, max_chars=8000,
        )
        brief_report = _brief_diagnostics_from_plan(plan)
        overflow = brief_report.get("overflow")
        if isinstance(overflow, Mapping):
            message = str(overflow.get("message", "BRIEF_REQUIRED_OVERFLOW"))
            errors.append(message)
        filtered = brief_report.get("items", {}).get("filtered_mandatory_ids", [])
        if filtered:
            warnings.append(f"brief preflight filtered mandatory items: {filtered}")
    _truth_gate_base_checks(stage, view["snapshot"], required_item_ids, errors)
    return {"view": view, "now": entry_now, "report": report, "truth": truth,
            "token": _truth_entry_token(view), "errors": errors, "warnings": warnings,
            "brief_report": brief_report, "handler_errors": handler_errors}


def _append_completion_errors(errors: list[str], criterion_id: Any, result: Mapping[str, Any]) -> None:
    if result.get("status") == "pass":
        return
    errors.append(f"criterion {criterion_id} status is {result.get('status', 'unknown')}")
    for evidence_result in result.get("evidence_results", []):
        if isinstance(evidence_result, Mapping) and evidence_result.get("status") != "pass":
            errors.append(f"criterion {criterion_id} evidence {evidence_result.get('evidence_id')} is {evidence_result.get('status', 'unknown')}")
    missing_evidence = result.get("missing_evidence_types")
    if missing_evidence:
        _append_missing_evidence_type_errors(errors, criterion_id, missing_evidence)
    for field, label in (("missing_hops", "missing chain-hop coverage"),
                         ("missing_delivery_types", "missing required delivery types")):
        if result.get(field):
            errors.append(f"criterion {criterion_id} {label}: {result[field]}")
    independence = result.get("independent_validation")
    if isinstance(independence, Mapping) and independence.get("status") != "pass":
        errors.append(f"criterion {criterion_id} independent validation is {independence.get('status')}: {independence.get('codes', [])}")


def _append_missing_evidence_type_errors(
    errors: list[str], criterion_id: Any, missing: Any,
) -> None:
    builtins = sorted(BUILTIN_RESOLVER_CAPABILITIES)
    errors.append(f"criterion {criterion_id} missing required evidence types: {missing}")
    errors.append(
        f"built-in evidence types: {builtins}; "
        "custom types require declared resolver and verifier capabilities"
    )


def _gate_truth_enabled(
    task_id: str, *, entry: Mapping[str, Any], evidence_map: Mapping[str, Mapping[str, Any]] | None,
    resolvers: Mapping[str, Any] | None, verifiers: Mapping[str, Any] | None,
    emit: bool, base_dir: str | Path | None, clock: Any,
) -> dict[str, Any]:
    """Run completion callbacks outside the entry lock, then fix its tail verdict under lock."""
    entry_view = entry["view"]
    errors = list(entry["errors"])
    warnings = list(entry["warnings"])
    entry_truth = entry["truth"]
    criterion_reports: dict[str, Any] = {}
    criteria_checked = 0
    evidence_attempts = 0
    if entry_truth["passed"] and not entry.get("handler_errors"):
        if not isinstance(evidence_map, Mapping):
            errors.append("completion gate requires evidence_map")
        else:
            criteria = deepcopy(entry_view["contract"].get("acceptance_criteria", []))
            for criterion in criteria if isinstance(criteria, list) else []:
                if not isinstance(criterion, dict):
                    continue
                criteria_checked += 1
                criterion_id = criterion.get("id")
                evidence_entry = deepcopy(evidence_map.get(criterion_id)) if isinstance(criterion_id, str) else None
                try:
                    criterion_report = _evaluate_completion_criterion(
                        deepcopy(criterion), evidence_entry, deepcopy(entry_view["contract"]),
                        resolvers=resolvers, verifiers=verifiers, now=entry["now"],
                    )
                except Exception as exc:
                    criterion_report = {"status": "unknown", "evidence_results": [], "missing_evidence_types": [], "missing_hops": [], "missing_delivery_types": [], "independent_validation": {"status": "unknown", "codes": ["CRITERION_EVALUATION_ERROR"]}}
                    warnings.append(f"criterion {criterion_id} evaluation raised {type(exc).__name__}")
                evidence_attempts += len(criterion_report.get("evidence_results", []))
                criterion_reports[str(criterion_id)] = criterion_report
                _append_completion_errors(errors, criterion_id, criterion_report)
    final_truth = entry_truth
    paths = _paths(task_id, base_dir)
    tail_lock_acquired = False
    try:
        with _shared_locked_existing(paths["root"]):
            tail_lock_acquired = True
            tail_evaluated = False
            if not errors:
                try:
                    tail_view = _load_committed_task_view_locked(task_id, paths)
                except ContextError as exc:
                    errors.append(f"truth source tail unavailable: {type(exc).__name__}")
                    tail_truth = deepcopy(entry_truth)
                    for item in tail_truth.get("results", []):
                        if isinstance(item, dict):
                            item["status"] = "unknown"
                            item["codes"] = ["TRUTH_SOURCE_RESOLVER_UNKNOWN"]
                else:
                    tail_now = clock().astimezone(timezone.utc)
                    tail_truth = _evaluate_truth_phase_locked(tail_view, now=tail_now)
                    if tail_truth is None:
                        errors.append("truth source tail unavailable: ContextError")
                        tail_truth = deepcopy(entry_truth)
                        for item in tail_truth.get("results", []):
                            if isinstance(item, dict):
                                item["status"] = "unknown"
                                item["codes"] = ["TRUTH_SOURCE_RESOLVER_UNKNOWN"]
                    else:
                        tail_evaluated = True
                        if _truth_entry_token(tail_view) != entry["token"]:
                            errors.append("truth source control changed during completion")
                        if not tail_truth["passed"]:
                            errors.extend(_truth_gate_errors(tail_truth))
                final_truth = tail_truth
                entry_stats = entry_truth.get("stats", {})
                tail_stats = tail_truth.get("stats", {}) if tail_evaluated else {}
                final_truth = deepcopy(tail_truth)
                final_truth["stats"] = {
                    "truth_sources_checked": entry_stats.get("truth_sources_checked", 0) + tail_stats.get("truth_sources_checked", 0),
                    "truth_source_resolution_attempts": entry_stats.get("truth_source_resolution_attempts", 0) + tail_stats.get("truth_source_resolution_attempts", 0),
                }
            return _truth_gate_final(
                stage="completion", report=entry["report"], errors=errors, warnings=warnings,
                criteria=criterion_reports, criteria_checked=criteria_checked,
                evidence_attempts=evidence_attempts, brief_report=entry["brief_report"],
                contract=entry_view["contract"], evaluation=final_truth, emit=emit,
            )
    except ContextError as exc:
        if tail_lock_acquired:
            raise
        errors.append(f"truth source tail unavailable: {type(exc).__name__}")
        final_truth = deepcopy(entry_truth)
        for item in final_truth.get("results", []):
            if isinstance(item, dict):
                item["status"] = "unknown"
                item["codes"] = ["TRUTH_SOURCE_RESOLVER_UNKNOWN"]
        final_truth["stats"] = deepcopy(entry_truth.get("stats", {}))
        return _truth_gate_final(
            stage="completion", report=entry["report"], errors=errors, warnings=warnings,
            criteria=criterion_reports, criteria_checked=criteria_checked,
            evidence_attempts=evidence_attempts, brief_report=entry["brief_report"],
            contract=entry_view["contract"], evaluation=final_truth, emit=emit,
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
    clock: Any = _trusted_utc_now,
    emit: bool = True,
    base_dir: str | Path | None = None,
    run_probe: bool,
) -> dict[str, Any]:
    """Run a release, resume, handoff, or completion quality gate."""

    if stage not in GATE_STAGES:
        raise ValueError(f"stage must be one of {sorted(GATE_STAGES)}")
    observed_now = clock().astimezone(timezone.utc)
    paths = _paths(task_id, base_dir)
    report = _audit_core(
        task_id,
        documents=documents,
        emit=False,
        base_dir=base_dir,
        max_pointer_lag_seconds=0,
        now=observed_now,
        run_probe=run_probe,
    )
    errors = list(report["errors"])
    warnings = list(report["warnings"])
    criterion_reports: dict[str, Any] = {}
    criteria_checked = 0
    evidence_attempts = 0
    handlers_checked = 0
    handler_errors: list[str] = []
    contract: dict[str, Any] = {}
    snapshot = _empty_snapshot(task_id)
    brief_report: dict[str, Any] | None = None
    try:
        view = _load_committed_task_view_locked(task_id, paths)
        contract = view["contract"]
        snapshot = view["snapshot"]
    except ContextError as exc:
        if str(exc) not in errors:
            errors.append(str(exc))

    if contract:
        handler_errors, handlers_checked = runtime_evidence_handler_errors(
            contract, resolvers=resolvers, verifiers=verifiers,
        )
        errors.extend(handler_errors)

    if contract and stage in {"release", "resume", "handoff"}:
        try:
            brief_plan = _plan_brief(
                task_id,
                phase=None,
                include=None,
                max_items=None,
                max_chars=8000,
                base_dir=base_dir,
            )
            brief_report = _brief_diagnostics_from_plan(brief_plan)
        except (ContextError, ValueError) as exc:
            message = f"brief preflight unavailable: {exc}"
            errors.append(message)
        else:
            overflow = brief_report.get("overflow")
            if isinstance(overflow, Mapping):
                message = str(overflow.get("message", "BRIEF_REQUIRED_OVERFLOW"))
                if message not in errors:
                    errors.append(message)
            filtered = brief_report.get("items", {}).get("filtered_mandatory_ids", [])
            if filtered:
                warnings.append(f"brief preflight filtered mandatory items: {filtered}")

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

    if stage == "completion" and not handler_errors:
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
                        _append_missing_evidence_type_errors(
                            errors,
                            criterion_id,
                            criterion_report.get("missing_evidence_types"),
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

    final_stats = {
        **report["stats"],
        "checked": report["stats"].get("checked", 0),
        "criteria_checked": criteria_checked,
        "evidence_attempts": evidence_attempts,
        "brief_status": (brief_report or {}).get("status", "unavailable"),
        "brief_overflow_kind": ((brief_report or {}).get("overflow") or {}).get("kind"),
        "brief_fixed_prompt_chars": (
            (brief_report or {}).get("budget", {}).get("fixed_prompt_chars")
        ),
        "brief_mandatory_prompt_chars": (
            (brief_report or {}).get("budget", {}).get("mandatory_prompt_chars")
        ),
    }
    if evidence_handlers_enabled(contract):
        final_stats["evidence_handlers_checked"] = handlers_checked
    final = {
        "stage": stage,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "criteria": criterion_reports,
        "stats": final_stats,
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
    raw_required_hops = criterion_baseline.get("required_hops")
    if raw_required_hops is None:
        raw_required_hops = criterion_baseline.get("chain_hops")
    required_hop_sequence = (
        [item for item in raw_required_hops if isinstance(item, str)]
        if isinstance(raw_required_hops, list)
        else []
    )
    required_hops = set(required_hop_sequence)
    required_hops_mode = criterion_baseline.get("required_hops_mode", "aggregate")
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
    hop_validation: dict[str, Any] | None = None
    if required_hops_mode == "single-evidence-ordered":
        matching_evidence_id = None
        for source, result in zip(primary_sources, primary_results):
            if not isinstance(source, Mapping) or result.get("status") != "pass":
                continue
            bound_hops = source.get("covered_hops", [])
            if (
                _valid_string_list(bound_hops, allow_empty=True)
                and _contains_ordered_subsequence(bound_hops, required_hop_sequence)
            ):
                matching_evidence_id = source.get("evidence_id")
                break
        matched = isinstance(matching_evidence_id, str)
        missing_hops = [] if matched else list(required_hop_sequence)
        hop_validation = {
            "mode": "single-evidence-ordered",
            "status": "pass" if matched else "unknown",
            "code": None if matched else "SINGLE_EVIDENCE_ORDERED_HOPS_MISSING",
            "evidence_id": matching_evidence_id,
        }
    else:
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
    result = {
        "status": status,
        "evidence_results": evidence_results,
        "missing_evidence_types": missing_types,
        "missing_hops": missing_hops,
        "missing_delivery_types": missing_delivery_types,
        "independent_validation": independence,
        "duplicate_evidence_ids": duplicate_ids,
    }
    if hop_validation is not None:
        result["hop_validation"] = hop_validation
    return result


def _contains_ordered_subsequence(
    supplied: Sequence[str], required: Sequence[str],
) -> bool:
    if not required:
        return True
    position = 0
    for hop in supplied:
        if hop == required[position]:
            position += 1
            if position == len(required):
                return True
    return False


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
    if stage not in GATE_STAGES:
        raise ValueError(f"stage must be one of {sorted(GATE_STAGES)}")
    paths = _paths(task_id, base_dir)
    def with_storage(report: dict[str, Any]) -> dict[str, Any]:
        report["storage"] = _storage_info(task_id, base_dir)
        return report

    truth_contract: Mapping[str, Any] | None = None
    initial_route_pending = True
    try:
        with _shared_locked_existing(paths["root"]):
            contract_hint = _read_json(paths["contract"])
            if truth_sources_enabled(contract_hint):
                truth_contract = contract_hint
            try:
                view = _load_committed_task_view_locked(task_id, paths)
            except ContextError:
                if truth_contract is not None:
                    raise
                return with_storage(_gate_core(
                    task_id, stage=stage, evidence_map=evidence_map,
                    required_item_ids=required_item_ids, documents=documents,
                    resolvers=resolvers, verifiers=verifiers, clock=_trusted_utc_now,
                    emit=emit, base_dir=base_dir, run_probe=True,
                ))
            initial_route_pending = False
            if truth_sources_enabled(view["contract"]):
                truth_contract = view["contract"]
                entry = _truth_gate_entry_locked(
                    task_id, view=view, stage=stage, required_item_ids=required_item_ids,
                    documents=documents, resolvers=resolvers, verifiers=verifiers,
                    clock=_trusted_utc_now, run_probe=True, base_dir=base_dir,
                )
                if stage != "completion" or not entry["truth"]["passed"]:
                    return with_storage(_truth_gate_final(
                        stage=stage, report=entry["report"], errors=entry["errors"],
                        warnings=entry["warnings"], criteria={}, criteria_checked=0,
                        evidence_attempts=0, brief_report=entry["brief_report"],
                        contract=view["contract"], evaluation=entry["truth"], emit=emit,
                    ))
            else:
                # The route and legacy verdict are both protected by this lock.
                return with_storage(_gate_core(
                    task_id, stage=stage, evidence_map=evidence_map,
                    required_item_ids=required_item_ids, documents=documents,
                    resolvers=resolvers, verifiers=verifiers, clock=_trusted_utc_now,
                    emit=emit, base_dir=base_dir, run_probe=True,
                ))
    except ContextError as exc:
        if not initial_route_pending:
            raise
        if truth_contract is not None:
            return with_storage(_truth_unknown_gate_report(
                task_id=task_id, stage=stage, contract=truth_contract, error=exc, emit=emit,
            ))
        audit_report = _read_lock_unavailable_audit(task_id, exc, emit=False)
        report = {
            "stage": stage,
            "passed": False,
            "errors": audit_report["errors"],
            "warnings": [],
            "criteria": {},
            "stats": {
                **audit_report["stats"],
                "criteria_checked": 0,
                "evidence_attempts": 0,
                "brief_status": "unavailable",
                "brief_overflow_kind": None,
                "brief_fixed_prompt_chars": None,
                "brief_mandatory_prompt_chars": None,
            },
            "contract_version": None,
        }
        if emit:
            _emit_report(report)
        return with_storage(report)
    return with_storage(_gate_truth_enabled(
        task_id, entry=entry, evidence_map=evidence_map,
        resolvers=resolvers, verifiers=verifiers, emit=emit,
        base_dir=base_dir, clock=_trusted_utc_now,
    ))


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


_BOUND_ACTIONS = frozenset({
    "publish_contract",
    "mark_truth_sources_dirty",
    "observe_truth_source",
    "record",
    "update_item",
    "externalize_item",
    "restore_externalization_controls",
    "checkpoint",
    "brief",
    "brief_diagnostics",
    "audit",
    "gate",
})


class BoundContext:
    """Bind all task operations to one explicit, absolute context directory."""

    def __init__(self, base_dir: str | Path) -> None:
        resolved, _ = _resolve_base_dir(base_dir)
        self.base_dir = resolved

    def __getattr__(self, name: str) -> Any:
        if name not in _BOUND_ACTIONS:
            raise AttributeError(name)
        function = globals()[name]

        def bound_call(*args: Any, **kwargs: Any) -> Any:
            if "base_dir" in kwargs:
                raise TypeError("bound context calls do not accept base_dir")
            result = function(*args, **kwargs, base_dir=self.base_dir)
            if (
                name in {"brief_diagnostics", "audit", "gate"}
                and isinstance(result, dict)
            ):
                task_id = args[0] if args and isinstance(args[0], str) else kwargs.get("task_id")
                if not isinstance(task_id, str):
                    return result
                result["storage"] = _storage_info(
                    task_id, self.base_dir, source="bound",
                )
            return result

        return bound_call


def bind(base_dir: str | Path) -> BoundContext:
    """Return a client whose calls cannot drift with the process working directory."""

    return BoundContext(base_dir)


async def run(action: str, **kwargs: Any) -> Any:
    """Prime Agent callable dispatcher.

    Example: ``await managing_long_task_context("gate", task_id="TASK-001", stage="release")``.
    """

    actions = {
        "publish_contract": publish_contract,
        "mark_truth_sources_dirty": mark_truth_sources_dirty,
        "observe_truth_source": observe_truth_source,
        "record": record,
        "update_item": update_item,
        "externalize_item": externalize_item,
        "restore_externalization_controls": restore_externalization_controls,
        "checkpoint": checkpoint,
        "brief": brief,
        "brief_diagnostics": brief_diagnostics,
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
    "mark_truth_sources_dirty",
    "observe_truth_source",
    "record",
    "update_item",
    "externalize_item",
    "restore_externalization_controls",
    "checkpoint",
    "brief",
    "brief_diagnostics",
    "audit",
    "gate",
    "workspace_observation",
    "BoundContext",
    "bind",
    "run",
]
