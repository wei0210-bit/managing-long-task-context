#!/usr/bin/env python3
"""Create bounded, append-only material for later real-path validation.

This recorder stores observations.  It never upgrades material into a verified
native-takeover, natural-project-effect, or token/cost-benefit claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


MAX_INPUT_BYTES = 1024 * 1024
OBSERVATION_SCHEMA = "real-validation-observation/v1"
EVENT_SCHEMA = "real-validation-event/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
}
CLAIMS = {
    "native_host_takeover",
    "natural_project_effect",
    "token_cost_benefit",
}
BOUNDARY_STATES = {"UNKNOWN", "NOT_RUN", "BLOCKED"}


class ValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json_output(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _fail(code: str, message: str) -> None:
    raise ValidationError(code, message)


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        _fail("DOCUMENT_NOT_JSON", str(exc))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs_no_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    _fail("JSON_NON_FINITE", f"non-finite JSON value: {value}")


def _decode_json(data: bytes) -> dict[str, object]:
    if len(data) > MAX_INPUT_BYTES:
        _fail("INPUT_TOO_LARGE", f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("INPUT_NOT_UTF8", str(exc))
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except ValidationError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        _fail("INPUT_NOT_JSON", str(exc))
    if not isinstance(value, dict):
        _fail("DOCUMENT_NOT_OBJECT", "document must be a JSON object")
    return value


def _read_open_file(descriptor: int, *, label: str) -> dict[str, object]:
    try:
        info = os.fstat(descriptor)
    except OSError as exc:
        _fail("INPUT_UNREADABLE", f"{label}: {exc}")
    if not stat.S_ISREG(info.st_mode):
        _fail("INPUT_NOT_REGULAR", f"not a regular file: {label}")
    if info.st_size > MAX_INPUT_BYTES:
        _fail("INPUT_TOO_LARGE", f"input exceeds {MAX_INPUT_BYTES} bytes")
    data = os.read(descriptor, MAX_INPUT_BYTES + 1)
    return _decode_json(data)


def _read_json(path: Path) -> dict[str, object]:
    try:
        info = path.lstat()
    except OSError as exc:
        _fail("INPUT_UNREADABLE", str(exc))
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        _fail("INPUT_NOT_REGULAR", f"not a non-symlink regular file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            return _read_open_file(descriptor, label=str(path))
        finally:
            os.close(descriptor)
    except OSError as exc:
        _fail("INPUT_UNREADABLE", str(exc))


def _reject_sensitive_fields(value: object) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if key.lower() in SENSITIVE_KEYS:
                    _fail("SENSITIVE_FIELD", f"sensitive field is forbidden: {key}")
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)


def _exact_keys(value: Mapping[str, object], required: set[str], *, where: str) -> None:
    supplied = set(value)
    if supplied != required:
        missing = sorted(required - supplied)
        unknown = sorted(supplied - required)
        _fail("DOCUMENT_SHAPE", f"{where} missing={missing} unknown={unknown}")


def _nonempty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("FIELD_INVALID", f"{field} must be a non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        _fail("FIELD_INVALID", f"{field} is not valid UTF-8: {exc}")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field=field)


def _identifier(value: object, *, field: str) -> str:
    text = _nonempty_string(value, field=field)
    if IDENTIFIER.fullmatch(text) is None:
        _fail("FIELD_INVALID", f"{field} is not a safe identifier")
    return text


def _timestamp(value: object, *, field: str) -> str:
    text = _nonempty_string(value, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        _fail("FIELD_INVALID", f"{field} must be RFC3339: {exc}")
    if parsed.tzinfo is None:
        _fail("FIELD_INVALID", f"{field} must include a timezone")
    return text


def _string_list(value: object, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        _fail("FIELD_INVALID", f"{field} must be a list")
    result = [_nonempty_string(item, field=field) for item in value]
    if not allow_empty and not result:
        _fail("FIELD_INVALID", f"{field} must not be empty")
    if len(result) != len(set(result)):
        _fail("FIELD_INVALID", f"{field} must be unique")
    return result


def _nullable_nonnegative_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("FIELD_INVALID", f"{field} must be a non-negative integer or null")
    return value


def _nonnegative_integer(value: object, *, field: str) -> int:
    result = _nullable_nonnegative_integer(value, field=field)
    if result is None:
        _fail("FIELD_INVALID", f"{field} must be a non-negative integer")
    return result


def _enum(value: object, choices: set[str], *, field: str) -> str:
    text = _nonempty_string(value, field=field)
    if text not in choices:
        _fail("FIELD_INVALID", f"{field} must be one of {sorted(choices)}")
    return text


def _validate_claims(value: object, *, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail("FIELD_INVALID", f"{where} must be an object")
    _exact_keys(value, CLAIMS, where=where)
    for claim, state in value.items():
        _enum(state, BOUNDARY_STATES, field=f"{where}.{claim}")
    return value


def _validate_observation(value: dict[str, object]) -> None:
    _reject_sensitive_fields(value)
    _exact_keys(
        value,
        {
            "schema",
            "observation_id",
            "task_id",
            "started_at",
            "sampling",
            "project",
            "skill",
            "host",
            "execution",
            "comparison",
            "claims",
            "acceptance_refs",
            "privacy",
        },
        where="observation",
    )
    if value["schema"] != OBSERVATION_SCHEMA:
        _fail("SCHEMA_UNSUPPORTED", "unsupported observation schema")
    _identifier(value["observation_id"], field="observation_id")
    _identifier(value["task_id"], field="task_id")
    _timestamp(value["started_at"], field="started_at")
    _enum(value["sampling"], {"prospective", "retrospective"}, field="sampling")
    project = value["project"]
    if not isinstance(project, dict):
        _fail("FIELD_INVALID", "project must be an object")
    _exact_keys(project, {"root", "revision", "dirty"}, where="project")
    project_root = Path(_nonempty_string(project["root"], field="project.root"))
    if not project_root.is_absolute():
        _fail("FIELD_INVALID", "project.root must be absolute")
    _nonempty_string(project["revision"], field="project.revision")
    if not isinstance(project["dirty"], bool):
        _fail("FIELD_INVALID", "project.dirty must be boolean")
    skill = value["skill"]
    if not isinstance(skill, dict):
        _fail("FIELD_INVALID", "skill must be an object")
    _exact_keys(
        skill,
        {"selection", "package_root", "skill_version", "manifest_sha256"},
        where="skill",
    )
    selection = _enum(
        skill["selection"], {"strict", "lite", "none", "unknown"}, field="skill.selection"
    )
    for field in ("package_root", "skill_version", "manifest_sha256"):
        _optional_string(skill[field], field=f"skill.{field}")
    if selection in {"strict", "lite"}:
        package_root = Path(_nonempty_string(skill["package_root"], field="skill.package_root"))
        if not package_root.is_absolute():
            _fail("FIELD_INVALID", "skill.package_root must be absolute")
        _nonempty_string(skill["skill_version"], field="skill.skill_version")
        manifest = _nonempty_string(skill["manifest_sha256"], field="skill.manifest_sha256")
        if SHA256.fullmatch(manifest) is None:
            _fail("FIELD_INVALID", "skill.manifest_sha256 must be lowercase SHA-256")
    host = value["host"]
    if not isinstance(host, dict):
        _fail("FIELD_INVALID", "host must be an object")
    _exact_keys(
        host,
        {"provider", "interface", "session_id", "identity_evidence_ref"},
        where="host",
    )
    _nonempty_string(host["provider"], field="host.provider")
    _nonempty_string(host["interface"], field="host.interface")
    _optional_string(host["session_id"], field="host.session_id")
    _optional_string(host["identity_evidence_ref"], field="host.identity_evidence_ref")
    execution = value["execution"]
    if not isinstance(execution, dict):
        _fail("FIELD_INVALID", "execution must be an object")
    _exact_keys(
        execution,
        {"model", "reasoning_effort", "configuration_ref"},
        where="execution",
    )
    for field in ("model", "reasoning_effort", "configuration_ref"):
        _optional_string(execution[field], field=f"execution.{field}")
    comparison = value["comparison"]
    if not isinstance(comparison, dict):
        _fail("FIELD_INVALID", "comparison must be an object")
    _exact_keys(
        comparison,
        {"group_id", "task_definition_ref"},
        where="comparison",
    )
    if comparison["group_id"] is not None:
        _identifier(comparison["group_id"], field="comparison.group_id")
    _optional_string(
        comparison["task_definition_ref"], field="comparison.task_definition_ref"
    )
    _validate_claims(value["claims"], where="claims")
    _string_list(value["acceptance_refs"], field="acceptance_refs")
    privacy = value["privacy"]
    if not isinstance(privacy, dict):
        _fail("FIELD_INVALID", "privacy must be an object")
    _exact_keys(
        privacy, {"raw_content_retained", "secrets_retained"}, where="privacy"
    )
    if privacy != {"raw_content_retained": False, "secrets_retained": False}:
        _fail("PRIVACY_POLICY", "raw content and secrets must not be retained")


def _validate_boundary(payload: object) -> None:
    if not isinstance(payload, dict):
        _fail("FIELD_INVALID", "boundary payload must be an object")
    _exact_keys(payload, {"claim_status", "reason"}, where="boundary payload")
    _validate_claims(payload["claim_status"], where="payload.claim_status")
    _nonempty_string(payload["reason"], field="payload.reason")


def _validate_native(payload: object) -> None:
    if not isinstance(payload, dict):
        _fail("FIELD_INVALID", "native_control payload must be an object")
    fields = {
        "operation",
        "outcome",
        "trigger_mode",
        "trigger_evidence_ref",
        "source_session_ref",
        "target_session_ref",
        "identity_verified",
        "write_fencing_verified",
        "clean_history_verified",
        "parent_survival_verified",
        "cross_parent_continuation_verified",
        "predecessor_retained_until_success",
    }
    _exact_keys(payload, fields, where="native_control payload")
    _enum(
        payload["operation"],
        {
            "create_clean_session",
            "transfer_control",
            "continue_cross_parent",
            "archive_predecessor",
        },
        field="payload.operation",
    )
    outcome = _enum(
        payload["outcome"],
        {"not_run", "attempted", "succeeded", "failed", "blocked", "unknown"},
        field="payload.outcome",
    )
    trigger_mode = _enum(
        payload["trigger_mode"],
        {"automatic", "manual", "unknown"},
        field="payload.trigger_mode",
    )
    _optional_string(
        payload["trigger_evidence_ref"], field="payload.trigger_evidence_ref"
    )
    _optional_string(payload["source_session_ref"], field="payload.source_session_ref")
    _optional_string(payload["target_session_ref"], field="payload.target_session_ref")
    checks = fields - {
        "operation",
        "outcome",
        "trigger_mode",
        "trigger_evidence_ref",
        "source_session_ref",
        "target_session_ref",
    }
    for field in checks:
        if payload[field] is not None and not isinstance(payload[field], bool):
            _fail("FIELD_INVALID", f"payload.{field} must be boolean or null")
    if outcome == "succeeded":
        if any(payload[field] is not True for field in checks):
            _fail("NATIVE_SUCCESS_INCOMPLETE", "succeeded requires every native check true")
        _nonempty_string(payload["source_session_ref"], field="payload.source_session_ref")
        _nonempty_string(payload["target_session_ref"], field="payload.target_session_ref")
        if trigger_mode == "automatic":
            _nonempty_string(
                payload["trigger_evidence_ref"], field="payload.trigger_evidence_ref"
            )


def _validate_task_outcome(payload: object) -> None:
    if not isinstance(payload, dict):
        _fail("FIELD_INVALID", "task_outcome payload must be an object")
    _exact_keys(
        payload,
        {
            "natural_project",
            "skill_selection",
            "outcome",
            "acceptance",
            "extra_turns",
            "retries",
            "manual_corrections",
        },
        where="task_outcome payload",
    )
    if not isinstance(payload["natural_project"], bool):
        _fail("FIELD_INVALID", "payload.natural_project must be boolean")
    _enum(
        payload["skill_selection"],
        {"strict", "lite", "none", "unknown"},
        field="payload.skill_selection",
    )
    _enum(
        payload["outcome"],
        {"completed", "incomplete", "failed", "interrupted", "unknown"},
        field="payload.outcome",
    )
    _enum(
        payload["acceptance"],
        {"pass", "fail", "unknown", "not_run"},
        field="payload.acceptance",
    )
    for field in ("extra_turns", "retries", "manual_corrections"):
        _nullable_nonnegative_integer(payload[field], field=f"payload.{field}")


def _validate_usage(payload: object, *, task_id: str) -> None:
    if not isinstance(payload, dict):
        _fail("FIELD_INVALID", "usage payload must be an object")
    fields = {
        "event_id",
        "session_id",
        "task_id",
        "provider",
        "model",
        "reasoning_effort",
        "mode",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cache_accounting",
        "source_ref",
        "observed_at",
    }
    _exact_keys(payload, fields, where="usage payload")
    for field in (
        "event_id",
        "session_id",
        "provider",
        "model",
        "reasoning_effort",
        "source_ref",
    ):
        _nonempty_string(payload[field], field=f"payload.{field}")
    if payload["task_id"] != task_id:
        _fail("TASK_MISMATCH", "usage payload task_id does not match observation")
    _enum(payload["mode"], {"delta", "cumulative"}, field="payload.mode")
    cache_accounting = _enum(
        payload["cache_accounting"],
        {"included", "separate"},
        field="payload.cache_accounting",
    )
    numbers: dict[str, int] = {}
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        numbers[field] = _nonnegative_integer(payload[field], field=f"payload.{field}")
    if cache_accounting == "included" and (
        numbers["cache_read_tokens"] + numbers["cache_write_tokens"]
        > numbers["input_tokens"]
    ):
        _fail("USAGE_CACHE_EXCEEDS_INPUT", "included cache counts exceed input tokens")
    _timestamp(payload["observed_at"], field="payload.observed_at")


def _validate_cost(payload: object) -> None:
    if not isinstance(payload, dict):
        _fail("FIELD_INVALID", "cost payload must be an object")
    _exact_keys(
        payload,
        {
            "provider",
            "currency",
            "amount",
            "billing_scope",
            "includes_retries",
            "skill_attribution",
        },
        where="cost payload",
    )
    _nonempty_string(payload["provider"], field="payload.provider")
    currency = _nonempty_string(payload["currency"], field="payload.currency")
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        _fail("FIELD_INVALID", "payload.currency must be a three-letter uppercase code")
    amount = _nonempty_string(payload["amount"], field="payload.amount")
    if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", amount) is None:
        _fail("FIELD_INVALID", "payload.amount must be a non-negative decimal string")
    try:
        Decimal(amount)
    except InvalidOperation as exc:
        _fail("FIELD_INVALID", f"payload.amount is invalid: {exc}")
    _enum(
        payload["billing_scope"],
        {"full-task", "partial", "unknown"},
        field="payload.billing_scope",
    )
    if payload["includes_retries"] is not None and not isinstance(
        payload["includes_retries"], bool
    ):
        _fail("FIELD_INVALID", "payload.includes_retries must be boolean or null")
    _enum(
        payload["skill_attribution"],
        {"full", "partial", "unknown"},
        field="payload.skill_attribution",
    )


def _validate_event(value: dict[str, object], observation: Mapping[str, object]) -> None:
    _reject_sensitive_fields(value)
    _exact_keys(
        value,
        {
            "schema",
            "event_id",
            "observation_id",
            "task_id",
            "event_type",
            "observed_at",
            "actor",
            "source_refs",
            "payload",
        },
        where="event",
    )
    if value["schema"] != EVENT_SCHEMA:
        _fail("SCHEMA_UNSUPPORTED", "unsupported event schema")
    _identifier(value["event_id"], field="event_id")
    if value["observation_id"] != observation["observation_id"]:
        _fail("OBSERVATION_MISMATCH", "event observation_id does not match")
    if value["task_id"] != observation["task_id"]:
        _fail("TASK_MISMATCH", "event task_id does not match")
    event_type = _enum(
        value["event_type"],
        {"boundary", "native_control", "task_outcome", "usage", "cost"},
        field="event_type",
    )
    _timestamp(value["observed_at"], field="observed_at")
    _nonempty_string(value["actor"], field="actor")
    _string_list(value["source_refs"], field="source_refs")
    validators = {
        "boundary": _validate_boundary,
        "native_control": _validate_native,
        "task_outcome": _validate_task_outcome,
        "cost": _validate_cost,
    }
    if event_type == "usage":
        _validate_usage(value["payload"], task_id=str(observation["task_id"]))
    else:
        validators[event_type](value["payload"])


def _safe_root(root_text: str, *, create: bool) -> Path:
    supplied = Path(root_text)
    if not supplied.is_absolute():
        _fail("ROOT_NOT_ABSOLUTE", "--root must be absolute")
    if supplied.is_symlink():
        _fail("ROOT_SYMLINK", f"root is a symlink: {supplied}")
    root = supplied
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _fail("ROOT_UNWRITABLE", str(exc))
    if not root.is_dir() or root.is_symlink():
        _fail("ROOT_NOT_DIRECTORY", f"not a directory: {root}")
    return root


def _open_directory_fd(path: Path, *, code: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _fail(code, str(exc))
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        _fail(code, f"not a directory: {path}")
    return descriptor


def _open_child_directory_fd(parent: int, name: str, *, code: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as exc:
        _fail(code, f"{name}: {exc}")
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        _fail(code, f"not a directory: {name}")
    return descriptor


def _read_json_at(
    parent: int, name: str, *, missing_ok: bool = False
) -> dict[str, object] | None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except FileNotFoundError:
        if missing_ok:
            return None
        _fail("INPUT_UNREADABLE", f"missing file: {name}")
    except OSError as exc:
        _fail("INPUT_UNREADABLE", f"{name}: {exc}")
    try:
        return _read_open_file(descriptor, label=name)
    finally:
        os.close(descriptor)


def _atomic_create_at(
    temporary_parent: int, target_parent: int, name: str, data: bytes
) -> bool:
    temporary_name = f".real-validation-pending-{os.getpid()}-{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=temporary_parent)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o444)
        finally:
            os.close(descriptor)
            descriptor = None
        try:
            os.link(
                temporary_name,
                name,
                src_dir_fd=temporary_parent,
                dst_dir_fd=target_parent,
                follow_symlinks=False,
            )
        except FileExistsError:
            return False
        os.fsync(target_parent)
        return True
    except OSError as exc:
        _fail("WRITE_FAILED", f"{name}: {exc}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=temporary_parent)
            os.fsync(temporary_parent)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _observation_paths(root: Path, observation_id: str) -> tuple[Path, Path, Path]:
    identifier = _identifier(observation_id, field="observation_id")
    directory = root / identifier
    return directory, directory / "observation.json", directory / "events"


def start(root_text: str, input_text: str) -> dict[str, object]:
    supplied = _read_json(Path(input_text))
    _validate_observation(supplied)
    root = _safe_root(root_text, create=True)
    directory, metadata_path, _ = _observation_paths(
        root, str(supplied["observation_id"])
    )
    data = _canonical(supplied)
    root_fd = _open_directory_fd(root, code="ROOT_NOT_DIRECTORY")
    try:
        try:
            os.mkdir(str(supplied["observation_id"]), mode=0o755, dir_fd=root_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            _fail("WRITE_FAILED", str(exc))
        observation_fd = _open_child_directory_fd(
            root_fd,
            str(supplied["observation_id"]),
            code="OBSERVATION_STORE_NOT_DIRECTORY",
        )
        try:
            existing = _read_json_at(observation_fd, "observation.json", missing_ok=True)
            if existing is not None:
                if _canonical(existing) == data:
                    events_fd = _open_child_directory_fd(
                        observation_fd, "events", code="EVENT_STORE_NOT_DIRECTORY"
                    )
                    try:
                        for name in sorted(os.listdir(events_fd)):
                            if not name.endswith(".json"):
                                _fail(
                                    "EVENT_STORE_SHAPE",
                                    f"unexpected event store entry: {name}",
                                )
                            event = _read_json_at(events_fd, name)
                            if event is None:  # pragma: no cover - missing_ok is false
                                _fail("INPUT_UNREADABLE", f"missing event: {name}")
                            _validate_event(event, existing)
                            if name != f"{event['event_id']}.json":
                                _fail(
                                    "EVENT_STORE_SHAPE",
                                    f"event filename mismatch: {name}",
                                )
                    finally:
                        os.close(events_fd)
                    return {
                        "status": "duplicate",
                        "observation_id": supplied["observation_id"],
                        "sha256": _sha256(data),
                    }
                _fail(
                    "OBSERVATION_ID_CONFLICT",
                    "observation_id already has different content",
                )
            try:
                os.mkdir("events", mode=0o755, dir_fd=observation_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                _fail("WRITE_FAILED", f"events: {exc}")
            events_fd = _open_child_directory_fd(
                observation_fd, "events", code="EVENT_STORE_NOT_DIRECTORY"
            )
            try:
                if os.listdir(events_fd):
                    _fail(
                        "OBSERVATION_INCOMPLETE",
                        "observation metadata is missing but event store is not empty",
                    )
            finally:
                os.close(events_fd)
            if not _atomic_create_at(
                observation_fd, observation_fd, "observation.json", data
            ):
                existing = _read_json_at(observation_fd, "observation.json")
                if existing is not None and _canonical(existing) == data:
                    events_fd = _open_child_directory_fd(
                        observation_fd, "events", code="EVENT_STORE_NOT_DIRECTORY"
                    )
                    os.close(events_fd)
                    return {
                        "status": "duplicate",
                        "observation_id": supplied["observation_id"],
                        "sha256": _sha256(data),
                    }
                _fail(
                    "OBSERVATION_ID_CONFLICT",
                    "observation_id already has different content",
                )
        finally:
            os.close(observation_fd)
    finally:
        os.close(root_fd)
    return {
        "status": "ok",
        "observation_id": supplied["observation_id"],
        "sha256": _sha256(data),
        "path": str(metadata_path),
    }


def record(root_text: str, observation_id: str, input_text: str) -> dict[str, object]:
    root = _safe_root(root_text, create=False)
    _, metadata_path, events_path = _observation_paths(root, observation_id)
    root_fd = _open_directory_fd(root, code="ROOT_NOT_DIRECTORY")
    try:
        observation_fd = _open_child_directory_fd(
            root_fd, observation_id, code="OBSERVATION_STORE_NOT_DIRECTORY"
        )
        try:
            loaded = _read_json_at(observation_fd, "observation.json")
            if loaded is None:  # pragma: no cover - missing_ok is false
                _fail("INPUT_UNREADABLE", "missing observation.json")
            observation = loaded
            _validate_observation(observation)
            events_fd = _open_child_directory_fd(
                observation_fd, "events", code="EVENT_STORE_NOT_DIRECTORY"
            )
            try:
                supplied = _read_json(Path(input_text))
                _validate_event(supplied, observation)
                data = _canonical(supplied)
                filename = f"{supplied['event_id']}.json"
                existing = _read_json_at(events_fd, filename, missing_ok=True)
                if existing is not None:
                    if _canonical(existing) == data:
                        return {
                            "status": "duplicate",
                            "event_id": supplied["event_id"],
                            "sha256": _sha256(data),
                        }
                    _fail("EVENT_ID_CONFLICT", "event_id already has different content")
                if not _atomic_create_at(observation_fd, events_fd, filename, data):
                    existing = _read_json_at(events_fd, filename)
                    if existing is not None and _canonical(existing) == data:
                        return {
                            "status": "duplicate",
                            "event_id": supplied["event_id"],
                            "sha256": _sha256(data),
                        }
                    _fail("EVENT_ID_CONFLICT", "event_id already has different content")
            finally:
                os.close(events_fd)
        finally:
            os.close(observation_fd)
    finally:
        os.close(root_fd)
    target = events_path / f"{supplied['event_id']}.json"
    return {
        "status": "ok",
        "event_id": supplied["event_id"],
        "sha256": _sha256(data),
        "path": str(target),
    }


def status_report(root_text: str, observation_id: str) -> dict[str, object]:
    root = _safe_root(root_text, create=False)
    _observation_paths(root, observation_id)
    counts: Counter[str] = Counter()
    native_material = False
    natural_material = False
    usage_count = 0
    cost_count = 0
    event_receipts: list[dict[str, str]] = []
    root_fd = _open_directory_fd(root, code="ROOT_NOT_DIRECTORY")
    try:
        observation_fd = _open_child_directory_fd(
            root_fd, observation_id, code="OBSERVATION_STORE_NOT_DIRECTORY"
        )
        try:
            loaded = _read_json_at(observation_fd, "observation.json")
            if loaded is None:  # pragma: no cover - missing_ok is false
                _fail("INPUT_UNREADABLE", "missing observation.json")
            observation = loaded
            _validate_observation(observation)
            events_fd = _open_child_directory_fd(
                observation_fd, "events", code="EVENT_STORE_NOT_DIRECTORY"
            )
            try:
                entries = sorted(os.listdir(events_fd))
                for name in entries:
                    if not name.endswith(".json"):
                        _fail("EVENT_STORE_SHAPE", f"unexpected event store entry: {name}")
                    supplied = _read_json_at(events_fd, name)
                    if supplied is None:  # pragma: no cover - missing_ok is false
                        _fail("INPUT_UNREADABLE", f"missing event: {name}")
                    _validate_event(supplied, observation)
                    if name != f"{supplied['event_id']}.json":
                        _fail("EVENT_STORE_SHAPE", f"event filename mismatch: {name}")
                    event_type = str(supplied["event_type"])
                    payload = supplied["payload"]
                    counts[event_type] += 1
                    if event_type == "native_control" and isinstance(payload, dict):
                        native_material = native_material or (
                            payload.get("outcome") == "succeeded"
                            and payload.get("trigger_mode") == "automatic"
                            and isinstance(payload.get("trigger_evidence_ref"), str)
                        )
                    elif event_type == "task_outcome" and isinstance(payload, dict):
                        natural_material = natural_material or (
                            payload.get("natural_project") is True
                            and payload.get("outcome") != "unknown"
                            and payload.get("acceptance") in {"pass", "fail"}
                        )
                    elif event_type == "usage":
                        usage_count += 1
                    elif event_type == "cost":
                        cost_count += 1
                    event_receipts.append(
                        {
                            "event_id": str(supplied["event_id"]),
                            "sha256": _sha256(_canonical(supplied)),
                        }
                    )
            finally:
                os.close(events_fd)
        finally:
            os.close(observation_fd)
    finally:
        os.close(root_fd)
    return {
        "status": "ok",
        "observation_id": observation["observation_id"],
        "task_id": observation["task_id"],
        "observation_sha256": _sha256(_canonical(observation)),
        "event_counts": dict(sorted(counts.items())),
        "event_receipts": event_receipts,
        "starting_boundaries": observation["claims"],
        "claims": {
            "native_host_takeover": "UNKNOWN",
            "natural_project_effect": "UNKNOWN",
            "token_cost_benefit": "UNKNOWN",
        },
        "material_available": {
            "native_host_takeover": native_material,
            "natural_project_effect": natural_material,
            "token_cost_benefit": usage_count > 0 and cost_count > 0,
        },
        "automatic_validation": False,
        "next_action": "independent review across original evidence and comparable observations",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record bounded material for later real-path validation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--root", required=True)
    start_parser.add_argument("--input", required=True)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--root", required=True)
    record_parser.add_argument("--observation-id", required=True)
    record_parser.add_argument("--input", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--root", required=True)
    status_parser.add_argument("--observation-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.root, args.input)
        elif args.command == "record":
            result = record(args.root, args.observation_id, args.input)
        else:
            result = status_report(args.root, args.observation_id)
    except ValidationError as exc:
        _json_output({"status": "error", "code": exc.code, "message": exc.message})
        return 2
    _json_output(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
