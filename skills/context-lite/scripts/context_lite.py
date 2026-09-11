#!/usr/bin/env python3
"""Deterministically validate and atomically replace Context Lite NOW.md files."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


def _manifest_identity() -> tuple[Path | None, str | None]:
    for parent in Path(__file__).resolve().parents:
        manifest = parent / "skill-manifest.json"
        try:
            raw = manifest.read_bytes()
        except FileNotFoundError:
            continue
        except OSError:
            return manifest, None
        return manifest, hashlib.sha256(raw).hexdigest()
    return None, None


_MANIFEST_BEFORE, _MANIFEST_DIGEST_BEFORE = _manifest_identity()

import context_identity_core as identity_core


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


_MANIFEST_AFTER, _MANIFEST_DIGEST_AFTER = _manifest_identity()
_LOADED_MANIFEST_SHA256 = (
    _MANIFEST_DIGEST_BEFORE
    if _MANIFEST_BEFORE is not None and _MANIFEST_AFTER == _MANIFEST_BEFORE
    and _MANIFEST_DIGEST_BEFORE == _MANIFEST_DIGEST_AFTER else None
)


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


def _unknown_experience(codes: object) -> dict[str, object]:
    stable_codes = codes if isinstance(codes, list) and codes and all(isinstance(code, str) and code for code in codes) else ["EXPERIENCE_QUERY_UNAVAILABLE"]
    return {"status": "unknown", "codes": stable_codes, "suggestions": [], "requires_strict": False}


def _query_experience(workspace_root: str, store_root: str, tags: str) -> dict[str, object]:
    manifest_before, digest_before = _manifest_identity()
    if (
        manifest_before != _MANIFEST_BEFORE
        or digest_before != _LOADED_MANIFEST_SHA256
        or _LOADED_MANIFEST_SHA256 is None
    ):
        return _unknown_experience(["RUNTIME_UNVERIFIED"])
    try:
        experience = importlib.import_module("context_experience")
    except Exception:
        return _unknown_experience(["EXPERIENCE_QUERY_UNAVAILABLE"])
    manifest_after, digest_after = _manifest_identity()
    expected_module = Path(__file__).resolve().with_name("context_experience.py")
    try:
        module_path = Path(experience.__file__).resolve()
    except (AttributeError, TypeError, OSError):
        return _unknown_experience(["RUNTIME_PATH_MISMATCH"])
    if (
        module_path != expected_module
        or manifest_after != manifest_before
        or digest_after != digest_before
    ):
        return _unknown_experience(["PACKAGE_IDENTITY_MISMATCH"])
    try:
        workspace = Path(workspace_root).resolve()
        store = experience._store_path(workspace, store_root)
        result = experience.query_records(
            workspace, store, tags, False, 3, 2000,
        )
    except Exception as exc:
        code = getattr(exc, "code", "EXPERIENCE_QUERY_UNAVAILABLE")
        return _unknown_experience([code] if isinstance(code, str) else ["EXPERIENCE_QUERY_UNAVAILABLE"])
    if not isinstance(result, dict):
        return _unknown_experience(["EXPERIENCE_QUERY_INVALID"])
    status, codes, data = result.get("status"), result.get("codes"), result.get("data")
    if status != "pass":
        return _unknown_experience(codes)
    if not isinstance(codes, list) or not all(isinstance(code, str) and code for code in codes):
        return _unknown_experience(["EXPERIENCE_QUERY_INVALID"])
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) > 3:
        return _unknown_experience(["EXPERIENCE_QUERY_INVALID"])
    suggestions = data["items"]
    if any(not isinstance(item, dict) or item.get("status") not in {"validated", "approved"} for item in suggestions):
        return _unknown_experience(["EXPERIENCE_QUERY_INVALID"])
    return {"status": "pass", "codes": codes, "suggestions": suggestions, "requires_strict": False}


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
    resume = subparsers.add_parser("resume")
    resume.add_argument("--package-root")
    resume.add_argument("--context-root")
    resume.add_argument("--workspace-root")
    resume.add_argument("--task-id")
    resume.add_argument("--requires-rule-proof", action="store_true")
    resume.add_argument("--experience-store")
    resume.add_argument("--experience-tags")
    return parser


def _resume(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    required = (args.package_root, args.context_root, args.workspace_root, args.task_id)
    if not all(required):
        report = identity_core.input_failure("identity", "task", "all resume arguments are required")
        return {"diagnostic": report, "context": None}, 1
    experience_store = getattr(args, "experience_store", None)
    experience_tags = getattr(args, "experience_tags", None)
    if bool(experience_store) != bool(experience_tags):
        report = identity_core.input_failure("identity", "task", "experience-store and experience-tags must be supplied together")
        return {"diagnostic": report, "context": None}, 1
    diagnostic = identity_core.identity_diagnostic(
        package_root=args.package_root,
        runtime_paths=(Path(__file__).resolve(), Path(identity_core.__file__).resolve()),
        loaded_manifest_sha256=_LOADED_MANIFEST_SHA256,
        capabilities=("runtime-identity/v1", "workspace-binding/v1", "checked-resume/v1"),
        binding_context_root=args.context_root,
        workspace_root=args.workspace_root,
        task_id=args.task_id,
    )
    if diagnostic["status"] != "pass":
        return {"diagnostic": diagnostic, "context": None}, {"fail": 1, "unknown": 2}.get(diagnostic["status"], 2)
    target = Path(args.context_root).resolve() / args.task_id / "NOW.md"
    text, failure = _read(target)
    if failure is not None or text is None:
        diagnostic = identity_core._report(
            mode="identity", scope="task", identity=diagnostic["identity"], binding=diagnostic["binding"],
            checks=list(diagnostic["checks"]) + [identity_core._check("resume", "unknown", "READ_FAILED", "cannot read NOW.md")],
        )
        return {"diagnostic": diagnostic, "context": None}, 2
    validation = validate_text(text, args.task_id)
    if validation["status"] != "valid":
        diagnostic = identity_core._report(
            mode="identity", scope="task", identity=diagnostic["identity"], binding=diagnostic["binding"],
            checks=list(diagnostic["checks"]) + [identity_core._check("resume", "fail", "RESUME_BLOCKED", "Lite NOW validation failed")],
        )
        return {"diagnostic": diagnostic, "context": None}, 1
    if getattr(args, "requires_rule_proof", False):
        diagnostic = identity_core._report(
            mode="identity", scope="task", identity=diagnostic["identity"], binding=diagnostic["binding"],
            checks=list(diagnostic["checks"]) + [identity_core._check(
                "resume", "unknown", "STRICT_REQUIRED", "Lite cannot prove selected rules",
            )],
        )
        return {
            "diagnostic": diagnostic,
            "context": None,
            "experience": {
                "status": "unknown", "codes": ["STRICT_REQUIRED"], "suggestions": [], "requires_strict": True,
            },
        }, 2
    if experience_store is not None:
        return {
            "diagnostic": diagnostic,
            "context": text,
            "experience": _query_experience(args.workspace_root, experience_store, experience_tags),
        }, 0
    return {"diagnostic": diagnostic, "context": text}, 0


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        text, failure = _read(args.file)
        report = failure if failure is not None else validate_text(text or "", args.task_id)
        code = 0 if report["status"] == "valid" else 1
    elif args.command == "write":
        report, code = _write(args.candidate, args.base_dir.resolve(), args.task_id)
    elif args.command == "resume":
        report, code = _resume(args)
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
