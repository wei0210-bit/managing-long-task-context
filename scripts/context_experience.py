#!/usr/bin/env python3
"""Persist and retrieve project-scoped experience candidates through a JSON CLI."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

import fcntl


STORE_BINDING = "binding.json"
STORE_RECORDS = "records.json"
STORE_LOCK = "store.lock"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
CANDIDATE_FIELDS = frozenset({
    "schema", "experience_id", "revision", "claim", "tags", "applicability", "exclusions", "source_refs", "supersedes",
})
LIFECYCLE_STATUSES = frozenset({"candidate", "validated", "approved", "disputed", "revoked"})
VALIDATION_KEYS = frozenset({"cross", "counterexample", "effectiveness"})
VALIDATION_COMMON_KEYS = frozenset({"source_refs", "checker_id", "checker_version", "validated_at", "expires_at"})


class InputError(Exception):
    """A user-visible input failure with a stable, non-sensitive code."""

    def __init__(self, code: str = "INVALID_INPUT", status: str = "fail") -> None:
        self.code = code
        self.status = status


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise InputError()


def report(status: str, codes: list[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": status, "codes": codes, "data": data}


def _write_report(result: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"pass": 0, "fail": 1, "unknown": 2}[result["status"]]


def _workspace_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = path.absolute()
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise InputError("WORKSPACE_UNAVAILABLE") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise InputError("INVALID_WORKSPACE")
    return path.resolve(strict=True)


def _store_path(workspace: Path, value: str | None) -> Path:
    raw_path = Path(value) if value else workspace / ".context-experience"
    if not raw_path.is_absolute():
        raw_path = raw_path.absolute()
    if raw_path.exists() and raw_path.is_symlink():
        raise InputError("INVALID_STORE")
    return raw_path.resolve(strict=False)


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".context-experience-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _safe_open_flags() -> tuple[int, int] | None:
    required = ("O_RDONLY", "O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY", "O_NONBLOCK")
    values = tuple(getattr(os, name, None) for name in required)
    if type(values[0]) is not int or any(type(value) is not int or value == 0 for value in values[1:]):
        return None
    readonly, nofollow, cloexec, directory, nonblocking = values
    return readonly | nofollow | cloexec | directory, readonly | nofollow | cloexec | nonblocking


def _metadata_token(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns


def _open_child(parent_fd: int, name: str, flags: int) -> int:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode):
        raise OSError(errno.ELOOP, "symlink")
    return os.open(name, flags, dir_fd=parent_fd)


def _source_result(status: str, code: str, digest: str | None = None) -> tuple[str, str, str | None]:
    return status, code, digest


def _hash_source(workspace: Path, source_path: str) -> tuple[str, str, str | None]:
    if not isinstance(source_path, str) or not source_path or "\x00" in source_path:
        return _source_result("fail", "SOURCE_UNSAFE_PATH")
    path = Path(source_path)
    if not path.is_absolute() or str(path) != source_path:
        return _source_result("fail", "SOURCE_UNSAFE_PATH")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return _source_result("unknown", "SOURCE_UNAVAILABLE")
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        return _source_result("fail", "SOURCE_UNSAFE_PATH")
    if resolved != path or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return _source_result("fail", "SOURCE_UNSAFE_PATH")
    flags = _safe_open_flags()
    if flags is None:
        return _source_result("unknown", "SOURCE_RESOLVER_UNAVAILABLE")
    directory_flags, file_flags = flags
    opened: list[int] = []
    try:
        current = os.open(os.sep, directory_flags)
        opened.append(current)
        for part in workspace.parts[1:]:
            current = _open_child(current, part, directory_flags)
            opened.append(current)
        for part in relative.parts[:-1]:
            current = _open_child(current, part, directory_flags)
            opened.append(current)
        descriptor = _open_child(current, relative.parts[-1], file_flags)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return _source_result("fail", "SOURCE_NOT_REGULAR_FILE")
        if before.st_size > MAX_SOURCE_BYTES:
            return _source_result("fail", "SOURCE_TOO_LARGE")
        digest = hashlib.sha256()
        bytes_read = 0
        while True:
            chunk = os.read(descriptor, READ_CHUNK_BYTES)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > MAX_SOURCE_BYTES:
                return _source_result("fail", "SOURCE_TOO_LARGE")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _metadata_token(before) != _metadata_token(after) or bytes_read != before.st_size:
            return _source_result("unknown", "SOURCE_CHANGED_DURING_READ")
        return _source_result("pass", "", digest.hexdigest())
    except OSError as error:
        if error.errno == errno.ELOOP:
            return _source_result("fail", "SOURCE_SYMLINK")
        return _source_result("unknown", "SOURCE_UNAVAILABLE")
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _nonempty_strings(value: object, minimum: int, maximum: int | None = None) -> bool:
    return (
        isinstance(value, list)
        and minimum <= len(value)
        and (maximum is None or len(value) <= maximum)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _valid_source_ref(value: object, workspace: Path) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        return None, report("fail", ["INVALID_INPUT"])
    path, digest = value.get("path"), value.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        return None, report("fail", ["INVALID_INPUT"])
    status, code, actual = _hash_source(workspace, path)
    if status != "pass":
        return None, report(status, [code])
    if actual != digest:
        return None, report("fail", ["SOURCE_DIGEST_MISMATCH"])
    return {"path": path, "sha256": digest}, None


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed.astimezone(timezone.utc)


def _stored_source_ref_shape(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"path", "sha256"}
        and isinstance(value.get("path"), str)
        and Path(value["path"]).is_absolute()
        and isinstance(value.get("sha256"), str)
        and SHA256_RE.fullmatch(value["sha256"]) is not None
    )


def _source_refs_shape(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_stored_source_ref_shape(item) for item in value)


def _validation_refs_shape(value: object, workspace: Path) -> bool:
    del workspace
    if not isinstance(value, dict) or set(value) != VALIDATION_KEYS:
        return False
    expected = {
        "cross": VALIDATION_COMMON_KEYS | {"independence_basis"},
        "counterexample": VALIDATION_COMMON_KEYS | {"original_pass_ref", "mutated_fail_ref", "restored_pass_ref", "mutation_hit_ref"},
        "effectiveness": VALIDATION_COMMON_KEYS | {"representative_run_ref", "non_applicable_run_ref"},
    }
    for name, item in value.items():
        if not isinstance(item, dict) or set(item) != expected[name]:
            return False
        if not _source_refs_shape(item.get("source_refs")) or not isinstance(item.get("checker_id"), str) or not item["checker_id"] or not isinstance(item.get("checker_version"), str) or not item["checker_version"]:
            return False
        validated_at, expires_at = _parse_utc(item.get("validated_at")), _parse_utc(item.get("expires_at"))
        if validated_at is None or expires_at is None or expires_at <= validated_at:
            return False
        if name == "cross":
            if not isinstance(item.get("independence_basis"), str) or not item["independence_basis"]:
                return False
        else:
            ref_keys = expected[name] - VALIDATION_COMMON_KEYS
            if not all(_stored_source_ref_shape(item.get(key)) for key in ref_keys):
                return False
    return True


def _reason_shape(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 2000


def _record_digest(record: dict[str, Any]) -> str:
    stable = deepcopy(record)
    stable.pop("record_digest", None)
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _approval_ref_shape(value: object, record: dict[str, Any]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"workspace_id", "experience_id", "revision", "record_digest", "source_ref"}
        and value.get("workspace_id") == record.get("workspace_id")
        and value.get("experience_id") == record.get("experience_id")
        and type(value.get("revision")) is int
        and value.get("revision") == record.get("revision")
        and value.get("record_digest") == _record_digest(record)
        and _stored_source_ref_shape(value.get("source_ref"))
    )


def _validate_candidate(raw: object, workspace: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(raw, dict) or set(raw) != CANDIDATE_FIELDS:
        return None, report("fail", ["INVALID_INPUT"])
    if type(raw.get("schema")) is not int or raw.get("schema") != 1 or not isinstance(raw.get("experience_id"), str) or ID_RE.fullmatch(raw["experience_id"]) is None:
        return None, report("fail", ["INVALID_INPUT"])
    revision = raw.get("revision")
    if type(revision) is not int or revision <= 0:
        return None, report("fail", ["INVALID_INPUT"])
    claim = raw.get("claim")
    if not isinstance(claim, str) or not claim or len(claim) > 2000:
        return None, report("fail", ["INVALID_INPUT"])
    if not _nonempty_strings(raw.get("tags"), 1, 10) or not _nonempty_strings(raw.get("applicability"), 1) or not _nonempty_strings(raw.get("exclusions"), 1):
        return None, report("fail", ["INVALID_INPUT"])
    supersedes = raw.get("supersedes")
    if revision == 1:
        if supersedes is not None:
            return None, report("fail", ["INVALID_INPUT"])
    elif not isinstance(supersedes, dict) or set(supersedes) != {"experience_id", "revision"} or supersedes.get("experience_id") != raw["experience_id"] or type(supersedes.get("revision")) is not int or supersedes["revision"] != revision - 1:
        return None, report("fail", ["INVALID_INPUT"])
    source_refs = raw.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        return None, report("fail", ["INVALID_INPUT"])
    normalized_refs: list[dict[str, str]] = []
    for source_ref in source_refs:
        if not isinstance(source_ref, dict) or set(source_ref) != {"path", "sha256"} or not isinstance(source_ref.get("sha256"), str) or SHA256_RE.fullmatch(source_ref["sha256"]) is None:
            return None, report("fail", ["INVALID_INPUT"])
        status, code, digest = _hash_source(workspace, source_ref.get("path"))
        if status != "pass":
            return None, report(status, [code])
        if digest != source_ref["sha256"]:
            return None, report("fail", ["SOURCE_DIGEST_MISMATCH"])
        normalized_refs.append({"path": source_ref["path"], "sha256": digest})
    return {
        "schema": 1,
        "experience_id": raw["experience_id"],
        "revision": revision,
        "claim": claim,
        "tags": list(raw["tags"]),
        "applicability": list(raw["applicability"]),
        "exclusions": list(raw["exclusions"]),
        "source_refs": normalized_refs,
        "supersedes": supersedes,
    }, None


def _read_binding(store: Path, workspace: Path) -> dict[str, Any]:
    binding_path = store / STORE_BINDING
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InputError("STORE_NOT_INITIALIZED") from error
    except (OSError, ValueError, UnicodeError) as error:
        raise InputError("STORE_CORRUPT") from error
    if binding != {"schema": 1, "workspace": str(workspace)}:
        raise InputError("WORKSPACE_MISMATCH")
    return binding


def _valid_stored_record(record: dict[str, Any], workspace: Path) -> bool:
    expected = CANDIDATE_FIELDS | {"candidate_digest", "created_at", "workspace_id", "status", "lifecycle"}
    if set(record) != expected or type(record.get("schema")) is not int or record.get("schema") != 1:
        return False
    if not isinstance(record.get("experience_id"), str) or ID_RE.fullmatch(record["experience_id"]) is None:
        return False
    revision = record.get("revision")
    if type(revision) is not int or revision <= 0:
        return False
    if not isinstance(record.get("claim"), str) or not record["claim"] or len(record["claim"]) > 2000:
        return False
    if not _nonempty_strings(record.get("tags"), 1, 10) or not _nonempty_strings(record.get("applicability"), 1) or not _nonempty_strings(record.get("exclusions"), 1):
        return False
    supersedes = record.get("supersedes")
    if (revision == 1 and supersedes is not None) or (revision > 1 and (not isinstance(supersedes, dict) or set(supersedes) != {"experience_id", "revision"} or supersedes.get("experience_id") != record["experience_id"] or type(supersedes.get("revision")) is not int or supersedes["revision"] != revision - 1)):
        return False
    source_refs = record.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        return False
    for source_ref in source_refs:
        if not isinstance(source_ref, dict) or set(source_ref) != {"path", "sha256"} or not isinstance(source_ref.get("path"), str) or not Path(source_ref["path"]).is_absolute() or not isinstance(source_ref.get("sha256"), str) or SHA256_RE.fullmatch(source_ref["sha256"]) is None:
            return False
    candidate = {field: record[field] for field in CANDIDATE_FIELDS}
    digest = hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if record.get("status") not in LIFECYCLE_STATUSES or not isinstance(record.get("lifecycle"), list):
        return False
    lifecycle = record["lifecycle"]
    prior = "candidate"
    for index, event in enumerate(lifecycle):
        if not isinstance(event, dict) or set(event) - {"status", "validation_refs", "approval_ref", "reason", "source_ref"}:
            return False
        status = event.get("status")
        if status not in LIFECYCLE_STATUSES - {"candidate"}:
            return False
        if status == "validated":
            if not _validation_refs_shape(event.get("validation_refs"), workspace):
                return False
        elif status == "approved":
            snapshot = deepcopy(record)
            snapshot["lifecycle"] = lifecycle[:index]
            snapshot["status"] = prior
            if not _approval_ref_shape(event.get("approval_ref"), snapshot):
                return False
        elif status == "disputed":
            if not _reason_shape(event.get("reason")) or not _stored_source_ref_shape(event.get("source_ref")):
                return False
        elif status == "revoked":
            snapshot = deepcopy(record)
            snapshot["lifecycle"] = lifecycle[:index]
            snapshot["status"] = prior
            if not _reason_shape(event.get("reason")) or not _approval_ref_shape(event.get("approval_ref"), snapshot):
                return False
        else:
            return False
        if status == "validated" and prior != "candidate":
            return False
        if status == "approved" and prior != "validated":
            return False
        if status in {"disputed", "revoked"} and prior not in {"candidate", "validated", "approved"}:
            return False
        prior = status
    return (
        record.get("candidate_digest") == digest
        and isinstance(record.get("created_at"), str)
        and UTC_RE.fullmatch(record["created_at"]) is not None
        and record.get("workspace_id") == hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()
        and record.get("status") == prior
    )


def _read_records(store: Path, workspace: Path) -> list[dict[str, Any]]:
    path = store / STORE_RECORDS
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InputError("STORE_UNAVAILABLE", "unknown") from error
    except (OSError, ValueError, UnicodeError) as error:
        raise InputError("STORE_CORRUPT") from error
    if not isinstance(loaded, dict) or type(loaded.get("schema")) is not int or loaded.get("schema") != 1 or not isinstance(loaded.get("records"), list) or set(loaded) != {"schema", "records"} or not all(isinstance(item, dict) and _valid_stored_record(item, workspace) for item in loaded["records"]):
        raise InputError("STORE_CORRUPT")
    return loaded["records"]


@contextmanager
def _store_lock(store: Path):
    try:
        with (store / STORE_LOCK).open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise InputError("STORE_UNAVAILABLE") from error


def record_candidate(workspace: Path, store: Path, input_path: str) -> dict[str, Any]:
    _read_binding(store, workspace)
    try:
        raw = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise InputError("INVALID_INPUT") from error
    candidate, failure = _validate_candidate(raw, workspace)
    if failure is not None:
        return failure
    assert candidate is not None
    canonical = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    candidate_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with _store_lock(store):
        _read_binding(store, workspace)
        records = _read_records(store, workspace)
        existing = next((item for item in records if item.get("experience_id") == candidate["experience_id"] and item.get("revision") == candidate["revision"]), None)
        if existing is not None:
            if existing.get("candidate_digest") == candidate_digest:
                return report("pass", [], {"experience_id": candidate["experience_id"], "revision": candidate["revision"], "status": existing.get("status")})
            return report("fail", ["REVISION_CONFLICT"])
        if candidate["revision"] > 1 and not any(item.get("experience_id") == candidate["experience_id"] and item.get("revision") == candidate["revision"] - 1 for item in records):
            return report("fail", ["INVALID_INPUT"])
        record = dict(candidate)
        record.update({
            "candidate_digest": candidate_digest,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "workspace_id": hashlib.sha256(str(workspace).encode("utf-8")).hexdigest(),
            "status": "candidate",
            "lifecycle": [],
        })
        records.append(record)
        try:
            _atomic_json_write(store / STORE_RECORDS, {"schema": 1, "records": records})
        except OSError as error:
            raise InputError("STORE_UNAVAILABLE") from error
    return report("pass", [], {"experience_id": candidate["experience_id"], "revision": candidate["revision"], "status": "candidate"})


def _verify_source_ref(source_ref: object, workspace: Path) -> dict[str, Any] | None:
    _, failure = _valid_source_ref(source_ref, workspace)
    return failure


def _validation_source_refs(validation_refs: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for name, item in validation_refs.items():
        references.extend(item["source_refs"])
        if name == "counterexample":
            references.extend(item[field] for field in ("original_pass_ref", "mutated_fail_ref", "restored_pass_ref", "mutation_hit_ref"))
        elif name == "effectiveness":
            references.extend(item[field] for field in ("representative_run_ref", "non_applicable_run_ref"))
    return references


def _verify_validation_refs(validation_refs: object, workspace: Path, *, require_current: bool) -> dict[str, Any] | None:
    if not _validation_refs_shape(validation_refs, workspace):
        return report("fail", ["INVALID_INPUT"])
    assert isinstance(validation_refs, dict)
    now = datetime.now(timezone.utc)
    for item in validation_refs.values():
        validated_at, expires_at = _parse_utc(item["validated_at"]), _parse_utc(item["expires_at"])
        assert validated_at is not None and expires_at is not None
        if validated_at > now or (require_current and expires_at <= now):
            return report("unknown", ["VALIDATION_EXPIRED"])
    for source_ref in _validation_source_refs(validation_refs):
        failure = _verify_source_ref(source_ref, workspace)
        if failure is not None:
            return failure
    return None


def _latest_lifecycle_event(record: dict[str, Any], status: str) -> dict[str, Any] | None:
    events = record.get("lifecycle", [])
    return next((event for event in reversed(events) if event.get("status") == status), None)


def _record_validity(record: dict[str, Any], workspace: Path, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if records is not None and any(item["experience_id"] == record["experience_id"] and item["revision"] > record["revision"] for item in records):
        return {"status": "unknown", "codes": ["RULE_VERSION_SUPERSEDED"]}
    source_failure = _verify_record_sources(record, workspace)
    if source_failure is not None:
        return {"status": source_failure["status"], "codes": source_failure["codes"]}
    validated = _latest_lifecycle_event(record, "validated")
    if validated is not None:
        failure = _verify_validation_refs(validated["validation_refs"], workspace, require_current=True)
        if failure is not None:
            return {"status": failure["status"], "codes": failure["codes"]}
    for event in record.get("lifecycle", []):
        approval_ref = event.get("approval_ref")
        if approval_ref is not None:
            failure = _verify_source_ref(approval_ref["source_ref"], workspace)
            if failure is not None:
                return {"status": failure["status"], "codes": failure["codes"]}
        source_ref = event.get("source_ref")
        if source_ref is not None:
            failure = _verify_source_ref(source_ref, workspace)
            if failure is not None:
                return {"status": failure["status"], "codes": failure["codes"]}
    return {"status": "pass", "codes": []}


def _get_data(record: dict[str, Any], validity: dict[str, Any], latest_revision: int | None = None) -> dict[str, Any]:
    return {
        "experience_id": record["experience_id"],
        "revision": record["revision"],
        "latest_revision": latest_revision if latest_revision is not None else record["revision"],
        "status": record["status"],
        "claim": record["claim"],
        "tags": record["tags"],
        "applicability": record["applicability"],
        "exclusions": record["exclusions"],
        "source_refs": record["source_refs"],
        "supersedes": record["supersedes"],
        "created_at": record["created_at"],
        "workspace_id": record["workspace_id"],
        "record_digest": _record_digest(record),
        "provenance": {
            "lifecycle": deepcopy(record["lifecycle"]),
            "validation_refs": deepcopy(_latest_lifecycle_event(record, "validated")["validation_refs"]) if _latest_lifecycle_event(record, "validated") is not None else None,
            "approval_ref": deepcopy(_latest_lifecycle_event(record, "approved")["approval_ref"]) if _latest_lifecycle_event(record, "approved") is not None else None,
        },
        "validity": validity,
    }


def get_record(workspace: Path, store: Path, experience_id: str, revision: int) -> dict[str, Any]:
    if not isinstance(experience_id, str) or ID_RE.fullmatch(experience_id) is None or type(revision) is not int or revision <= 0:
        return report("fail", ["INVALID_INPUT"])
    _read_binding(store, workspace)
    records = _read_records(store, workspace)
    record = next((item for item in records if item.get("experience_id") == experience_id and item.get("revision") == revision), None)
    if record is None:
        return report("fail", ["EXPERIENCE_NOT_FOUND"])
    latest_revision = max(item["revision"] for item in records if item["experience_id"] == experience_id)
    validity = _record_validity(record, workspace, records)
    return report(validity["status"], validity["codes"], _get_data(record, validity, latest_revision))


def _query_item(record: dict[str, Any]) -> dict[str, Any]:
    item = {
        "experience_id": record["experience_id"],
        "revision": record["revision"],
        "status": record["status"],
        "claim": record["claim"],
        "applicability": record["applicability"],
        "exclusions": record["exclusions"],
        "source_refs": record["source_refs"],
    }
    if record["status"] == "candidate":
        item["reliance"] = "not-reliable"
    else:
        item["reliance"] = "reliable"
    return item


def _current_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        experience_id = record.get("experience_id")
        revision = record.get("revision")
        if isinstance(experience_id, str) and type(revision) is int and (experience_id not in latest or revision > latest[experience_id].get("revision", 0)):
            latest[experience_id] = record
    return list(latest.values())


def _verify_record_sources(record: dict[str, Any], workspace: Path) -> dict[str, Any] | None:
    for source_ref in record["source_refs"]:
        status, code, digest = _hash_source(workspace, source_ref["path"])
        if status != "pass":
            return report(status, [code])
        if digest != source_ref["sha256"]:
            return report("fail", ["SOURCE_DIGEST_MISMATCH"])
    return None


def query_records(workspace: Path, store: Path, tags_value: str, include_candidates: bool, limit: int, max_chars: int) -> dict[str, Any]:
    tags = tags_value.split(",") if isinstance(tags_value, str) else []
    if not tags or any(not tag for tag in tags) or len(set(tags)) != len(tags) or type(limit) is not int or limit <= 0 or type(max_chars) is not int or max_chars <= 0:
        return report("fail", ["INVALID_INPUT"])
    _read_binding(store, workspace)
    statuses = {"validated", "approved"}
    if include_candidates:
        statuses.add("candidate")
    matching = [
        record for record in _current_records(_read_records(store, workspace))
        if record.get("status") in statuses and bool(set(tags) & set(record.get("tags", [])))
    ]
    matching.sort(key=lambda record: (-record["revision"], record["experience_id"]))
    selected: list[dict[str, Any]] = []
    for record in matching:
        validity = _record_validity(record, workspace)
        if validity["status"] != "pass":
            return report(validity["status"], validity["codes"])
        item = _query_item(record)
        proposed = {"items": selected + [item], "omitted_count": len(matching) - len(selected) - 1}
        if len(selected) >= limit or len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":"))) > max_chars:
            continue
        selected.append(item)
    omitted_count = len(matching) - len(selected)
    data = {"items": selected, "omitted_count": omitted_count}
    if len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))) > max_chars:
        return report("fail", ["BUDGET_UNSATISFIABLE"])
    codes = ["BUDGET_OMITTED"] if omitted_count else []
    return report("pass", codes, data)


def init_store(workspace: Path, store: Path) -> dict[str, Any]:
    try:
        store.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = os.lstat(store)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InputError("INVALID_STORE")
        binding = {"schema": 1, "workspace": str(workspace)}
        with _store_lock(store):
            binding_path = store / STORE_BINDING
            if binding_path.exists():
                try:
                    existing = json.loads(binding_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeError) as error:
                    raise InputError("STORE_CORRUPT") from error
                if existing != binding:
                    raise InputError("WORKSPACE_MISMATCH")
                _read_records(store, workspace)
            else:
                records_path = store / STORE_RECORDS
                if records_path.exists():
                    raise InputError("STORE_UNAVAILABLE", "unknown")
                _atomic_json_write(records_path, {"schema": 1, "records": []})
                _atomic_json_write(binding_path, binding)
    except InputError:
        raise
    except OSError as error:
        raise InputError("STORE_UNAVAILABLE") from error
    return report("pass", [], {"workspace": str(workspace), "store": str(store)})


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest="command")
    init = commands.add_parser("init", add_help=False)
    init.add_argument("--workspace", required=True)
    init.add_argument("--store")
    record = commands.add_parser("record", add_help=False)
    record.add_argument("--workspace", required=True)
    record.add_argument("--store")
    record.add_argument("--input", required=True)
    get = commands.add_parser("get", add_help=False)
    get.add_argument("--workspace", required=True)
    get.add_argument("--store")
    get.add_argument("--id", required=True)
    get.add_argument("--revision", required=True, type=int)
    query = commands.add_parser("query", add_help=False)
    query.add_argument("--workspace", required=True)
    query.add_argument("--store")
    query.add_argument("--tags", required=True)
    query.add_argument("--include-candidates", action="store_true")
    query.add_argument("--limit", type=int, default=3)
    query.add_argument("--max-chars", type=int, default=2000)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        if arguments.command not in {"init", "record", "get", "query"}:
            raise InputError()
        workspace = _workspace_path(arguments.workspace)
        store = _store_path(workspace, arguments.store)
        if arguments.command == "init":
            return _write_report(init_store(workspace, store))
        if arguments.command == "get":
            return _write_report(get_record(workspace, store, arguments.id, arguments.revision))
        if arguments.command == "query":
            return _write_report(query_records(workspace, store, arguments.tags, arguments.include_candidates, arguments.limit, arguments.max_chars))
        return _write_report(record_candidate(workspace, store, arguments.input))
    except InputError as error:
        return _write_report(report(error.status, [error.code]))
    except (OSError, ValueError, TypeError):
        return _write_report(report("unknown", ["STORE_UNAVAILABLE"]))


if __name__ == "__main__":
    raise SystemExit(main())
