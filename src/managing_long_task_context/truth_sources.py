"""Optional truth-source schema validation and safe local-file fingerprinting."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import AbstractSet, Any, Callable, Mapping, Union


CAPABILITY = "truth-sources/v1"
SUPPORTED_CAPABILITIES = frozenset({CAPABILITY})
TRUTH_ROOT_FIELDS = frozenset({"schema", "items"})
TRUTH_ITEM_FIELDS = frozenset({
    "id", "purpose", "source_ref", "owner", "max_age_seconds",
    "validation_method", "invalidate_on_change_kinds",
})
SOURCE_REF_FIELDS = frozenset({"kind", "locator"})
SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
VERIFICATION_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}\Z")
MAX_SOURCE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

TruthResolver = Callable[[Union[str, Path], Mapping[str, Any]], Mapping[str, Any]]

ERRNO_CODES = {
    errno.ENOENT: ("fail", "TRUTH_SOURCE_NOT_FOUND"),
    errno.ELOOP: ("fail", "TRUTH_SOURCE_SYMLINK"),
    errno.ENOTDIR: ("fail", "TRUTH_SOURCE_NOT_REGULAR_FILE"),
    errno.EACCES: ("unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
    errno.EPERM: ("unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
}
_TRANSIENT_ERRNOS = {errno.EIO, errno.EBUSY, errno.EINTR}
if hasattr(errno, "ESTALE"):
    _TRANSIENT_ERRNOS.add(errno.ESTALE)
_UNSAFE_LOCATOR_CHARS = frozenset("*?[]{}#~")


def _result(status: str, code: str | None, fingerprint: str | None = None) -> dict[str, Any]:
    return {"status": status, "code": code, "fingerprint": fingerprint}


def _unknown_fields(value: Mapping[str, Any], allowed: AbstractSet[str]) -> list[str]:
    return [key for key in value if key not in allowed]


def _single_line(value: object, maximum: int) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= maximum and "\n" not in value and "\r" not in value


def _safe_locator(locator: object) -> bool:
    if not isinstance(locator, str) or not locator or "\x00" in locator:
        return False
    if os.path.isabs(locator) or any(char in locator for char in _UNSAFE_LOCATOR_CHARS):
        return False
    # A backslash is a path separator on Windows and must not permit a segment
    # the slash-based checks below did not inspect.
    if os.sep != "/" and "\\" in locator:
        return False
    for segment in locator.split("/"):
        if not segment or segment in {".", ".."} or segment != segment.strip():
            return False
    return True


def truth_sources_enabled(contract: Mapping[str, Any]) -> bool:
    capabilities = contract.get("required_capabilities")
    return "truth_sources" in contract and isinstance(capabilities, list) and CAPABILITY in capabilities


def validate_truth_source_contract(
    contract: Mapping[str, Any], *, supported_capabilities: AbstractSet[str] = SUPPORTED_CAPABILITIES,
) -> list[str]:
    """Return deterministic, field-qualified errors for the optional extension."""
    has_sources = "truth_sources" in contract
    has_capabilities = "required_capabilities" in contract
    if not has_sources and not has_capabilities:
        return []

    errors: list[str] = []
    capabilities = contract.get("required_capabilities")
    valid_capabilities = isinstance(capabilities, list) and bool(capabilities) and all(
        isinstance(item, str) and bool(item) for item in capabilities
    ) and len(set(capabilities)) == len(capabilities) if isinstance(capabilities, list) else False
    if has_capabilities and not valid_capabilities:
        errors.append("contract.required_capabilities must be a non-empty list of unique non-empty strings")
    if valid_capabilities:
        assert isinstance(capabilities, list)
        for capability in capabilities:
            if capability not in supported_capabilities:
                errors.append(f"contract.required_capabilities has unsupported capability: {capability}")

    has_truth_capability = valid_capabilities and CAPABILITY in capabilities
    if has_sources and not has_truth_capability:
        errors.append("contract.truth_sources requires required_capabilities truth-sources/v1")
    if has_truth_capability and not has_sources:
        errors.append("contract.required_capabilities truth-sources/v1 requires truth_sources")
    if not has_sources:
        return errors

    workspace_root = contract.get("workspace_root")
    if not _valid_workspace_root(workspace_root):
        errors.append("contract.workspace_root must be an existing absolute non-symlink directory")

    truth_root = contract.get("truth_sources")
    if not isinstance(truth_root, Mapping):
        errors.append("contract.truth_sources must be an object")
        return errors
    unknown = _unknown_fields(truth_root, TRUTH_ROOT_FIELDS)
    if unknown:
        errors.append(f"contract.truth_sources has unknown fields: {unknown}")
    if truth_root.get("schema") != CAPABILITY:
        errors.append("contract.truth_sources.schema must equal truth-sources/v1")
    items = truth_root.get("items")
    if not isinstance(items, list) or not items:
        errors.append("contract.truth_sources.items must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        path = f"contract.truth_sources.items[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path} must be an object")
            continue
        unknown = _unknown_fields(item, TRUTH_ITEM_FIELDS)
        if unknown:
            errors.append(f"{path} has unknown fields: {unknown}")
        source_id = item.get("id")
        if not isinstance(source_id, str) or SOURCE_ID_RE.fullmatch(source_id) is None:
            errors.append(f"{path}.id must match source ID pattern")
        elif source_id in seen_ids:
            errors.append(f"contract.truth_sources.items has duplicate id: {source_id}")
        else:
            seen_ids.add(source_id)
        if not _single_line(item.get("purpose"), 160):
            errors.append(f"{path}.purpose must be a non-empty single-line string of at most 160 characters")
        if not _single_line(item.get("owner"), 128):
            errors.append(f"{path}.owner must be a non-empty single-line string of at most 128 characters")
        if item.get("validation_method") != "owner-readback":
            errors.append(f"{path}.validation_method must equal owner-readback")
        max_age = item.get("max_age_seconds")
        if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age <= 0:
            errors.append(f"{path}.max_age_seconds must be a positive integer")
        _validate_change_kinds(item.get("invalidate_on_change_kinds"), path, errors)
        _validate_source_ref(item.get("source_ref"), path, errors)
    return errors


def _valid_workspace_root(value: object) -> bool:
    if not isinstance(value, (str, Path)):
        return False
    value_string = os.fspath(value)
    if "\x00" in value_string or not os.path.isabs(value_string):
        return False
    try:
        root_stat = os.lstat(value_string)
    except OSError:
        return False
    return stat.S_ISDIR(root_stat.st_mode) and not stat.S_ISLNK(root_stat.st_mode)


def _validate_change_kinds(value: object, path: str, errors: list[str]) -> None:
    valid = isinstance(value, list) and bool(value) and all(_single_line(item, 2**31 - 1) for item in value)
    if not valid or len(set(value)) != len(value):
        errors.append(f"{path}.invalidate_on_change_kinds must be a non-empty list of unique non-empty single-line strings")


def _validate_source_ref(value: object, path: str, errors: list[str]) -> None:
    ref_path = f"{path}.source_ref"
    if not isinstance(value, Mapping):
        errors.append(f"{ref_path} must be an object")
        return
    unknown = _unknown_fields(value, SOURCE_REF_FIELDS)
    if unknown:
        errors.append(f"{ref_path} has unknown fields: {unknown}")
    if value.get("kind") != "file":
        errors.append(f"{ref_path}.kind must equal file")
    if not _safe_locator(value.get("locator")):
        errors.append(f"{ref_path}.locator must be a safe workspace-relative file path")


def _required_flags() -> tuple[int, int] | None:
    readonly = getattr(os, "O_RDONLY", None)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    directory = getattr(os, "O_DIRECTORY", None)
    # Non-blocking is mandatory: without it, a FIFO/device final target can
    # hang before fstat has a chance to reject it as non-regular.
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if not all(isinstance(flag, int) for flag in (readonly, nofollow, cloexec, directory, nonblocking)):
        return None
    return readonly | nofollow | cloexec | directory, readonly | nofollow | cloexec | nonblocking


def _map_os_error(error: OSError) -> dict[str, Any]:
    if error.errno in ERRNO_CODES:
        status, code = ERRNO_CODES[error.errno]
        return _result(status, code)
    if error.errno in _TRANSIENT_ERRNOS:
        return _result("unknown", "TRUTH_SOURCE_TRANSIENT_IO")
    return _result("unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN")


def _metadata_token(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _openat_without_symlink(parent_fd: int, component: str, flags: int) -> int:
    """Open one named child only after a no-follow directory-FD lstat."""
    entry_stat = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(entry_stat.st_mode):
        raise OSError(errno.ELOOP, "symlink")
    return os.open(component, flags, dir_fd=parent_fd)


def _fingerprint_open_file(file_descriptor: int) -> dict[str, Any]:
    before = os.fstat(file_descriptor)
    if not stat.S_ISREG(before.st_mode):
        return _result("fail", "TRUTH_SOURCE_NOT_REGULAR_FILE")
    if before.st_size > MAX_SOURCE_BYTES:
        return _result("fail", "TRUTH_SOURCE_TOO_LARGE")
    digest = hashlib.sha256()
    bytes_read = 0
    while True:
        chunk = os.read(file_descriptor, READ_CHUNK_BYTES)
        if not chunk:
            break
        bytes_read += len(chunk)
        if bytes_read > MAX_SOURCE_BYTES:
            return _result("fail", "TRUTH_SOURCE_TOO_LARGE")
        digest.update(chunk)
    after = os.fstat(file_descriptor)
    if _metadata_token(before) != _metadata_token(after):
        return _result("unknown", "TRUTH_SOURCE_CHANGED_DURING_READ")
    if bytes_read != before.st_size:
        return _result("unknown", "TRUTH_SOURCE_TRANSIENT_IO")
    return _result("pass", None, "sha256:" + digest.hexdigest())


def resolve_file_source(workspace_root: str | Path, source_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Hash one safe, regular workspace-relative file without exposing its contents."""
    if not isinstance(source_ref, Mapping):
        return _result("fail", "TRUTH_SOURCE_UNSAFE_PATH")
    if not _safe_locator(source_ref.get("locator")) or source_ref.get("kind") != "file":
        return _result("fail", "TRUTH_SOURCE_UNSAFE_PATH")
    if not isinstance(workspace_root, (str, Path)):
        return _result("fail", "TRUTH_SOURCE_UNSAFE_PATH")
    root_string = os.fspath(workspace_root)
    if "\x00" in root_string or not os.path.isabs(root_string):
        return _result("fail", "TRUTH_SOURCE_UNSAFE_PATH")
    flags = _required_flags()
    if flags is None:
        return _result("unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN")
    directory_flags, file_flags = flags
    owned_fds: list[int] = []
    outcome = _result("unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN")
    try:
        current_fd = os.open(os.sep, directory_flags)
        owned_fds.append(current_fd)
        for component in Path(root_string).parts[1:]:
            current_fd = _openat_without_symlink(current_fd, component, directory_flags)
            owned_fds.append(current_fd)
        locator = source_ref["locator"]
        assert isinstance(locator, str)  # guarded by _safe_locator above
        segments = locator.split("/")
        for component in segments[:-1]:
            current_fd = _openat_without_symlink(current_fd, component, directory_flags)
            owned_fds.append(current_fd)
        file_fd = _openat_without_symlink(current_fd, segments[-1], file_flags)
        owned_fds.append(file_fd)
        outcome = _fingerprint_open_file(file_fd)
    except OSError as error:
        outcome = _map_os_error(error)
    except (AttributeError, TypeError, ValueError):
        outcome = _result("unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN")
    finally:
        cleanup_failed = False
        for file_descriptor in reversed(owned_fds):
            try:
                os.close(file_descriptor)
            except (AttributeError, OSError, TypeError, ValueError):
                cleanup_failed = True
        if cleanup_failed:
            outcome = _result("unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN")
    return outcome
