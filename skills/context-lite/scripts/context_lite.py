#!/usr/bin/env python3
"""Deterministically validate and atomically replace Context Lite NOW.md files."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TITLE = re.compile(r"^# ([A-Za-z0-9][A-Za-z0-9._-]{0,63}): (.+)$")
HEADINGS = (
    "## Acceptance",
    "## Current State",
    "## Decisions",
    "## In Flight",
    "## Blockers",
    "## Next",
    "## Refresh On Resume",
)
MUTATING_COMMANDS = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir", "install", "tee",
    "truncate", "chmod", "chown", "kill", "pkill", "launchctl",
}
MUTATING_GIT = {"add", "am", "branch", "checkout", "cherry-pick", "clean", "commit", "merge", "pull", "push", "rebase", "reset", "restore", "revert", "switch", "tag"}
MUTATING_GH = {"issue edit", "issue close", "issue create", "pr merge", "pr close", "pr create", "run rerun", "workflow run"}
VAGUE_REFERENCE = re.compile(r"^(?:here|there|above|earlier|previous|当前|这里|那里|上面|刚才|之前)$", re.IGNORECASE)


def _error(code: str, message: str, **details: object) -> dict[str, object]:
    value: dict[str, object] = {"code": code, "message": message}
    value.update(details)
    return value


def _utc(value: str) -> bool:
    if not (value.endswith("Z") or value.endswith("+00:00")):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if line in HEADINGS:
            current = line
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return result


def _reference_is_read_only(reference: str) -> bool:
    value = reference.strip()
    if not value or VAGUE_REFERENCE.fullmatch(value) or any(token in value for token in (">", "&&", ";", "||", "`", "$(")):
        return False
    if value.startswith(("https://", "http://", "file:", "job:", "tool:", "message:")):
        return True
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    if not tokens:
        return False
    command = Path(tokens[0]).name
    if command in MUTATING_COMMANDS:
        return False
    if value.startswith("/") and len(tokens) == 1:
        return True
    if command == "git":
        safe_git = {"status", "diff", "log", "show", "rev-parse", "ls-files", "cat-file"}
        if not any(token in safe_git for token in tokens[1:]):
            return False
        if any(token in MUTATING_GIT for token in tokens[1:]):
            return False
    if command == "gh":
        if len(tokens) < 3 or tokens[2] not in {"view", "list", "status"}:
            return False
        if f"{tokens[1]} {tokens[2]}" in MUTATING_GH:
            return False
    if command == "curl" and any(token in {"-X", "--request", "-d", "--data", "--upload-file"} for token in tokens[1:]):
        return False
    if command == "sed" and any(token == "-i" or token.startswith("-i") for token in tokens[1:]):
        return False
    if command == "find" and any(token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for token in tokens[1:]):
        return False
    if command in {"test", "cat", "rg", "grep", "sed", "git", "ls", "find", "stat", "shasum", "sha256sum", "curl", "gh"}:
        return True
    return value.startswith(("observe:", "read:"))


def _field_values(lines: list[str], field: str) -> list[str]:
    pattern = re.compile(rf"(?:^|\|\s*){re.escape(field)}:\s*([^|]+)")
    values: list[str] = []
    for line in lines:
        values.extend(match.group(1).strip() for match in pattern.finditer(line))
    return values


def _identity(text: str) -> tuple[str | None, str | None]:
    first = text.splitlines()[0] if text.splitlines() else ""
    match = TITLE.fullmatch(first)
    return (match.group(1), match.group(2).strip()) if match else (None, None)


def validate_text(text: str, expected_task_id: str | None = None) -> dict[str, object]:
    lines = text.splitlines()
    errors: list[dict[str, object]] = []
    task_id, goal = _identity(text)
    if task_id is None or goal is None:
        errors.append(_error("NOW_TITLE_INVALID", "title must be '# <task-id>: <goal>'"))
    elif expected_task_id is not None and task_id != expected_task_id:
        errors.append(_error("NOW_TASK_ID_MISMATCH", "title task ID differs from requested task ID"))
    if expected_task_id is not None and not TASK_ID.fullmatch(expected_task_id):
        errors.append(_error("NOW_TASK_ID_INVALID", "requested task ID is invalid"))

    if len(lines) > 80:
        errors.append(_error("NOW_LINE_LIMIT_EXCEEDED", f"{len(lines)}/80 lines", actual=len(lines), limit=80))
    if len(text) > 8000:
        errors.append(_error("NOW_CHARACTER_LIMIT_EXCEEDED", f"{len(text)}/8000 characters", actual=len(text), limit=8000))
    for index, line in enumerate(lines, start=1):
        if len(line) > 500:
            errors.append(_error("NOW_SINGLE_LINE_LIMIT_EXCEEDED", f"line {index}: {len(line)}/500 characters", line=index, actual=len(line), limit=500))

    actual_headings = [line for line in lines if line.startswith("## ")]
    if actual_headings != list(HEADINGS):
        errors.append(_error("NOW_HEADING_ORDER_INVALID", "fixed heading order differs", actual=actual_headings))

    updated = [line.removeprefix("Updated: ").strip() for line in lines if line.startswith("Updated: ")]
    if len(updated) != 1 or not _utc(updated[0]):
        errors.append(_error("NOW_TIMESTAMP_NOT_UTC", "Updated must be one explicit UTC RFC3339 timestamp"))
    for field in ("refreshed_at", "started_at"):
        for value in _field_values(lines, field):
            if not _utc(value):
                errors.append(_error("NOW_TIMESTAMP_NOT_UTC", f"{field} must be UTC RFC3339", field=field))

    sections = _sections(lines)
    next_lines = sections.get("## Next", [])
    next_items = [line for line in next_lines if re.match(r"^[0-9]+\.\s+", line)]
    first_actions = [line for line in next_items if re.match(r"^1\.\s+First:\s+\S", line)]
    if len(next_items) > 3:
        errors.append(_error("NOW_NEXT_LIMIT_EXCEEDED", f"Next: {len(next_items)}/3 items", actual=len(next_items), limit=3))
    if [int(line.split(".", 1)[0]) for line in next_items] != list(range(1, len(next_items) + 1)):
        errors.append(_error("NOW_NEXT_SEQUENCE_INVALID", "Next numbering must start at 1 and be contiguous"))
    if len(first_actions) != 1:
        errors.append(_error("NOW_FIRST_ACTION_INVALID", "Next item 1 must be the unique 'First:' action", actual=len(first_actions)))

    observation_refs = _field_values(lines, "refresh_ref") + _field_values(lines, "recovery_ref")
    for line in sections.get("## Refresh On Resume", []):
        if "->" in line:
            observation_refs.append(line.split("->", 1)[1].strip())
    for reference in observation_refs:
        if not _reference_is_read_only(reference):
            errors.append(_error("NOW_REFERENCE_NOT_READ_ONLY", "refresh/recovery reference is not deterministically read-only", reference=reference))

    for field in ("source", "evidence", "correlation_ref"):
        for reference in _field_values(lines, field):
            if VAGUE_REFERENCE.fullmatch(reference.strip()) or "<" in reference or ">" in reference:
                errors.append(_error("NOW_REFERENCE_UNSTABLE", f"{field} is not a stable reference", field=field))

    state_ids = re.findall(r"\[(STATE-[A-Za-z0-9._-]+)\]", text)
    run_ids = re.findall(r"\[(RUN-[A-Za-z0-9._-]+)\]", text)
    for ids, kind in ((state_ids, "STATE"), (run_ids, "RUN")):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            errors.append(_error("NOW_STABLE_ID_DUPLICATE", f"duplicate {kind} IDs", ids=duplicates))
    refresh_ids = [
        matched.group(1)
        for line in sections.get("## Refresh On Resume", [])
        for matched in [re.match(r"^-\s+(STATE-[A-Za-z0-9._-]+|RUN-[A-Za-z0-9._-]+)\s+->\s+", line)]
        if matched is not None
    ]
    expected_refresh_ids = set(state_ids) | set(run_ids)
    missing_refresh = sorted(expected_refresh_ids - set(refresh_ids))
    unknown_refresh = sorted(set(refresh_ids) - expected_refresh_ids)
    duplicate_refresh = sorted({item for item in refresh_ids if refresh_ids.count(item) > 1})
    if missing_refresh:
        errors.append(_error("NOW_REFRESH_MAPPING_MISSING", "state/run has no refresh mapping", ids=missing_refresh))
    if unknown_refresh:
        errors.append(_error("NOW_REFRESH_MAPPING_UNKNOWN", "refresh mapping has no matching state/run", ids=unknown_refresh))
    if duplicate_refresh:
        errors.append(_error("NOW_REFRESH_MAPPING_DUPLICATE", "refresh mapping is duplicated", ids=duplicate_refresh))

    codes = sorted({str(item["code"]) for item in errors})
    return {
        "status": "valid" if not errors else "invalid",
        "task_id": task_id,
        "goal": goal,
        "codes": codes,
        "errors": errors,
        "stats": {
            "lines": len(lines),
            "characters": len(text),
            "headings": len(actual_headings),
            "next_items": len(next_items),
            "first_actions": len(first_actions),
            "references_checked": len(observation_refs),
            "refresh_mappings": len(refresh_ids),
        },
    }


def _emit(report: Mapping[str, object]) -> None:
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _read(path: Path) -> tuple[str | None, dict[str, object] | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return None, {
            "status": "invalid",
            "codes": ["NOW_READ_FAILED"],
            "errors": [_error("NOW_READ_FAILED", type(exc).__name__)],
            "stats": {},
        }


def _write(candidate: Path, base_dir: Path, task_id: str) -> tuple[dict[str, object], int]:
    text, failure = _read(candidate)
    if failure is not None or text is None:
        return failure or {}, 1
    report = validate_text(text, task_id)
    if report["status"] != "valid":
        return report, 1
    target_dir = base_dir / ".context-lite" / task_id
    target = target_dir / "NOW.md"
    if target.exists():
        old_text, old_failure = _read(target)
        if old_failure is not None or old_text is None:
            return {
                "status": "invalid", "codes": ["NOW_EXISTING_READ_FAILED"],
                "errors": [_error("NOW_EXISTING_READ_FAILED", "existing NOW.md cannot be read")], "stats": {},
            }, 1
        old_report = validate_text(old_text, task_id)
        if old_report["status"] != "valid":
            return {
                "status": "invalid", "codes": ["NOW_EXISTING_INVALID"],
                "errors": [_error("NOW_EXISTING_INVALID", "existing NOW.md is invalid and was preserved")], "stats": {},
            }, 1
        if old_report["goal"] != report["goal"]:
            return {
                "status": "invalid", "codes": ["NOW_GOAL_CONFLICT"],
                "errors": [_error("NOW_GOAL_CONFLICT", "same task ID has a different exact goal")], "stats": {},
            }, 1
        if old_text == text:
            return {**report, "status": "unchanged", "path": str(target.resolve())}, 0

    target_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target_dir, prefix=".NOW.md.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        persisted = temporary_path.read_text(encoding="utf-8")
        persisted_report = validate_text(persisted, task_id)
        if persisted_report["status"] != "valid":
            return persisted_report, 1
        os.replace(temporary_path, target)
        temporary_path = None
        directory_fd = os.open(str(target_dir), os.O_RDONLY)
        try:
            try:
                os.fsync(directory_fd)
            except OSError:
                # Replacement already succeeded atomically. Do not report a
                # failure that would imply the old file is still active.
                report = {**report, "warnings": ["NOW_DIRECTORY_FSYNC_UNAVAILABLE"]}
        finally:
            os.close(directory_fd)
    except OSError as exc:
        return {
            "status": "invalid", "codes": ["NOW_ATOMIC_WRITE_FAILED"],
            "errors": [_error("NOW_ATOMIC_WRITE_FAILED", type(exc).__name__)], "stats": {},
        }, 1
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return {**report, "status": "written", "path": str(target.resolve())}, 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--file", type=Path, required=True)
    validate.add_argument("--task-id")
    write = subparsers.add_parser("write")
    write.add_argument("--candidate", type=Path, required=True)
    write.add_argument("--base-dir", type=Path, required=True)
    write.add_argument("--task-id", required=True)
    observe = subparsers.add_parser("observe-path")
    observe.add_argument("--state-id", required=True)
    observe.add_argument("--path", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        text, failure = _read(args.file)
        report = failure if failure is not None else validate_text(text or "", args.task_id)
        code = 0 if report["status"] == "valid" else 1
    elif args.command == "write":
        report, code = _write(args.candidate, args.base_dir.resolve(), args.task_id)
    else:
        readable = args.path.is_file() and os.access(args.path, os.R_OK)
        report = {
            "state_id": args.state_id,
            "status": "verified" if readable else "unknown",
            "code": "OBSERVATION_READABLE" if readable else "OBSERVATION_UNREADABLE",
            "reference": str(args.path.resolve()),
        }
        code = 0
    _emit(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
