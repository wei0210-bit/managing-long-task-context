"""Read-only freshness report for a task directory. Never writes files."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEDGER_FILE_NAMES = frozenset({
    "task-contract.json",
    "events.jsonl",
    "snapshot.json",
    ".lock",
})
STRAY_NAME = re.compile(r" 2(\.[^.]+)?$")
UNKNOWN_CODES = frozenset({
    "CHECKPOINT_GAP",
    "CHECKPOINT_MISSING",
    "LEDGER_UNREADABLE",
    "CONTRACT_VERSION_UNREADABLE",
})


def usage_freshness_report(
    task_root: str | Path,
    *,
    now: datetime,
    checkpoint_gap_hours: float = 72,
    contract_version_cap: int = 5,
) -> dict[str, Any]:
    _require_utc_now(now)
    root = Path(task_root)
    warnings: list[dict[str, str]] = []
    stats: dict[str, Any] = {
        "ledger_newer_files": 0,
        "checkpoint_age_hours": None,
        "contract_version": None,
    }

    if root.is_symlink() or not root.is_dir():
        warnings.extend(
            (
                _warning("LEDGER_UNREADABLE", "last event created_at is missing or unreadable"),
                _warning("CHECKPOINT_MISSING", "latest checkpoint created_at is missing or unreadable"),
                _warning("CONTRACT_VERSION_UNREADABLE", "contract version is missing or is not an int"),
            )
        )
        return _result(warnings, stats)

    last_event_at = _last_event_created_at(root / "events.jsonl")
    if last_event_at is None:
        warnings.append(_warning("LEDGER_UNREADABLE", "last event created_at is missing or unreadable"))

    checkpoint_at = _checkpoint_created_at(root / "snapshot.json")
    if checkpoint_at is None:
        warnings.append(_warning("CHECKPOINT_MISSING", "latest checkpoint created_at is missing or unreadable"))
    else:
        age_hours = (now - checkpoint_at).total_seconds() / 3600
        stats["checkpoint_age_hours"] = age_hours
        if age_hours > checkpoint_gap_hours:
            warnings.append(
                _warning("CHECKPOINT_GAP", f"latest checkpoint is {age_hours:.1f} hours old")
            )

    contract_version = _contract_version(root / "task-contract.json")
    if contract_version is None:
        warnings.append(_warning("CONTRACT_VERSION_UNREADABLE", "contract version is missing or is not an int"))
    else:
        stats["contract_version"] = contract_version
        if contract_version > contract_version_cap:
            warnings.append(
                _warning(
                    "CONTRACT_VERSION_CAP",
                    f"contract version {contract_version} exceeds {contract_version_cap}",
                )
            )

    newer_files = 0
    stray: list[str] = []
    for relative, entry in _iter_entries(root):
        name = entry.name
        if name == ".DS_Store" or STRAY_NAME.search(name):
            stray.append(relative.as_posix())
        if last_event_at is None:
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            if _is_ledger_path(relative):
                continue
            if entry.stat(follow_symlinks=False).st_mtime > last_event_at.timestamp():
                newer_files += 1
        except OSError:
            continue

    stats["ledger_newer_files"] = newer_files
    if last_event_at is not None and newer_files:
        warnings.append(
            _warning("LEDGER_ACTIVITY", f"{newer_files} non-ledger file(s) newer than the last event")
        )
    for path in stray:
        warnings.append(_warning("STRAY_NAME", f"stray name: {path}"))
    return _result(warnings, stats)


def _require_utc_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware UTC datetime")
    offset = now.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("now must be a timezone-aware UTC datetime")


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _result(warnings: list[dict[str, str]], stats: dict[str, Any]) -> dict[str, Any]:
    if any(item["code"] in UNKNOWN_CODES for item in warnings):
        status = "unknown"
    elif warnings:
        status = "warn"
    else:
        status = "pass"
    return {"status": status, "warnings": warnings, "stats": stats}


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read_text(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _load_object(path: Path) -> dict[str, Any] | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _last_event_created_at(path: Path) -> datetime | None:
    text = _read_text(path)
    if text is None:
        return None
    last = ""
    for line in text.splitlines():
        if line.strip():
            last = line
    if not last:
        return None
    try:
        payload = json.loads(last)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_utc(payload.get("created_at"))


def _checkpoint_created_at(path: Path) -> datetime | None:
    payload = _load_object(path)
    if payload is None:
        return None
    latest = payload.get("latest_checkpoint")
    if not isinstance(latest, dict):
        return None
    return _parse_utc(latest.get("created_at"))


def _contract_version(path: Path) -> int | None:
    payload = _load_object(path)
    if payload is None:
        return None
    version = payload.get("version")
    return version if type(version) is int else None


def _is_ledger_path(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if parts[0] == "handoff":
        return True
    return len(parts) == 1 and parts[0] in LEDGER_FILE_NAMES


def _iter_entries(task_root: Path):
    stack = [task_root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                children = list(iterator)
        except OSError:
            continue
        for entry in children:
            try:
                if entry.is_symlink():
                    continue
            except OSError:
                continue
            relative = Path(entry.path).relative_to(task_root)
            yield relative, entry
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                stack.append(Path(entry.path))
