"""Read-only registration helpers for worker-report artifacts.

These helpers report file metadata and preserve declarations; they do not verify execution.
Only trusted host code constructs them; report JSON never supplies a handler.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from contextlib import ExitStack
from collections.abc import Mapping
from pathlib import Path

from . import evidence as ev

RESOLVER_CAPABILITY = "project:worker-report/v1"
VERIFIER_CAPABILITY = "project:worker-report-claim/v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_EXCLUDED = {".githooks/pre-commit", ".prime/scripts/merge-events.py", ".gitattributes"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _path(root, locator):
    if not _text(locator) or "\x00" in locator:
        return None, ev.check(ev.FAIL, "INVALID_PATH")
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return None, ev.check(ev.FAIL, "INVALID_PATH")
    target = root
    try:
        for component in relative.parts:
            target = target / component
            if target.is_symlink():
                return None, ev.check(ev.FAIL, "SYMLINK_NOT_ALLOWED")
        if not target.resolve().is_relative_to(root):
            return None, ev.check(ev.FAIL, "OUTSIDE_WORKSPACE")
        if not target.is_file():
            return None, ev.check(ev.FAIL, "NOT_FOUND")
    except (OSError, RuntimeError, ValueError):
        return None, ev.check(ev.UNKNOWN, "PATH_UNREADABLE")
    return target, ev.check(ev.PASS)


def _report_shape(report):
    if not isinstance(report, Mapping):
        return False
    schema = report.get("schema")
    if not (type(schema) is int and schema > 0 or _text(schema)):
        return False
    for field in ("task_id", "orca_task_id", "orca_dispatch_id", "loaded_module_file", "outcome_claim"):
        if not _text(report.get(field)):
            return False
    if not isinstance(report.get("contract_digest"), str) or not ev._DIGEST_RE.fullmatch(report["contract_digest"]):
        return False
    if not isinstance(report.get("loaded_manifest_sha256"), str) or not _HEX.fullmatch(report["loaded_manifest_sha256"]):
        return False
    if ev._parse_utc_time(report.get("written_at")) is None:
        return False
    revision = report.get("code_revision")
    if (not isinstance(revision, Mapping) or not isinstance(revision.get("commit"), str)
            or not ev._COMMIT_RE.fullmatch(revision["commit"]) or type(revision.get("dirty")) is not bool):
        return False
    if not isinstance(report.get("files_modified"), list) or any(not _text(p) for p in report["files_modified"]):
        return False
    if not isinstance(report.get("deferred_suggestions"), list) or not isinstance(report.get("checks"), list):
        return False
    for item in report["checks"]:
        if (not isinstance(item, Mapping) or not _text(item.get("command"))
                or type(item.get("exit_code")) is not int or not _text(item.get("output_file"))
                or not isinstance(item.get("output_sha256"), str)
                or not _HEX.fullmatch(item["output_sha256"]) or not isinstance(item.get("output_summary"), str)):
            return False
    return True


def _read_bytes(root, path):
    """Open every component relative to a directory fd, without following links."""
    try:
        parts = path.relative_to(root).parts
        with ExitStack() as stack:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, directory)
            for part in parts[:-1]:
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                stack.callback(os.close, directory)
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            stack.callback(os.close, descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return None, ev.check(ev.FAIL, "NOT_REGULAR_FILE")
            chunks = []
            total = 0
            while True:
                chunk = os.read(descriptor, ev.LOCAL_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > ev.MAX_LOCAL_ARTIFACT_BYTES:
                    return None, ev.check(ev.FAIL, "ARTIFACT_TOO_LARGE")
                chunks.append(chunk)
            return b"".join(chunks), ev.check(ev.PASS)
    except (OSError, ValueError):
        return None, ev.check(ev.UNKNOWN, "ARTIFACT_UNREADABLE")


def _read_report(root, evidence):
    path, result = _path(root, evidence.get("locator"))
    if path is None:
        return None, result
    raw, result = _read_bytes(root, path)
    if raw is None:
        return None, result
    expected = evidence.get("artifact_digest")
    if (not isinstance(expected, str) or not ev._DIGEST_RE.fullmatch(expected)
            or "sha256:" + hashlib.sha256(raw).hexdigest() != expected):
        return None, ev.check(ev.FAIL, "DIGEST_MISMATCH")
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None, ev.check(ev.FAIL, "INVALID_WORKER_REPORT")
    if not _report_shape(report):
        return None, ev.check(ev.FAIL, "INVALID_WORKER_REPORT")
    return report, ev.check(ev.PASS)


def _excluded(path):
    """Classify ledger metadata when observing a recorded Git revision."""
    return path.startswith(".prime/") or path in _EXCLUDED


def worker_report_handlers(workspace_root):
    """Return capability-wrapped resolvers and verifiers bound to an absolute root.

    Includes all built-in resolvers. The host still supplies any project-specific
    verifiers required by other evidence kinds in its contract.
    """
    root = Path(workspace_root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("workspace_root must be an existing absolute directory")
    root = root.resolve()

    def resolve(evidence, criterion, contract, now):
        report, result = _read_report(root, evidence)
        integrity = ev._freshness_check(evidence, criterion, now)
        bound_contract = {**contract, "workspace_root": str(root)}
        scope = ev._merge_checks(ev._scope_check(evidence, criterion),
                                ev._envelope_revision_check(evidence, criterion, bound_contract))
        if report is not None:
            seal = contract.get("seal")
            if not isinstance(seal, Mapping) or report["contract_digest"] != seal.get("integrity_digest"):
                integrity = ev._merge_checks(integrity, ev.check(ev.FAIL, "CONTRACT_DIGEST_MISMATCH"))
        return {"resolve": result, "integrity_and_freshness": integrity, "scope": scope}

    def verify(evidence, criterion, resolution):
        # Compatibility report: artifact integrity does not verify execution.
        return ev.check(ev.UNKNOWN, "EXECUTION_NOT_VERIFIED")

    resolvers = {kind: {"capability": ev.BUILTIN_RESOLVER_CAPABILITIES[kind], "handler": handler}
                 for kind, handler in ev.default_resolvers().items()}
    resolvers["worker-report"] = {"capability": RESOLVER_CAPABILITY, "handler": resolve}
    verifiers = {"worker-report": {"capability": VERIFIER_CAPABILITY, "handler": verify}}
    return resolvers, verifiers
