"""Project-rooted Context Strict store: relative paths, upload gate, align."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


CONTEXT_PATHS = (
    ".prime/CONTEXT.md",
    ".prime/context",
    ".prime/experience",
)
LOCK_NAME = ".lock"
TMP_SUFFIX = ".tmp"
RELATIVE_WORKSPACE = "."
RELATIVE_CONTEXT = ".prime/context"
RELATIVE_EXPERIENCE = ".prime/experience"
HOOKS_PATH = ".githooks"
HOOK_FILE = ".githooks/pre-commit"
MERGE_SCRIPT = ".prime/scripts/merge-events.py"
ATTRIBUTES_FILE = ".gitattributes"
PUBLISH_ENV = "MLTC_PUBLISH_CONTEXT"
PUBLISH_MARKER = f"{PUBLISH_ENV}=1"
REBUILD_MARKER = {"rebuild": "required"}

SECRET_MARKERS = (
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "AKIA",
    "ASIA",
)

LEGEND = """# Context Strict 项目上下文

task-contract.json：发布者封印的目标、范围、验收标准。动手前先读。摘要对不上就停下，不另写一套验收标准。
events.jsonl：发生过的记录，只追加。以它为历史。不改旧行，新事实追加新事件。
snapshot.json：由事件重建的当前上下文。看现在有哪些事实。有疑问就按事件重建，不把快照当另一份历史。
快照里的条目：观察、已核实事实、假设、决定、问题，以及有效、未核实、冲突、被取代。假设不当成已核实事实。冲突或过期的条目不拿来交接。
latest_checkpoint：这一阶段完成了什么、阻塞、下一步。交接从最新检查点继续。
真源指纹：某份项目文件当时的内容。文件字节变了就标脏，重新核对后再交接。
证据与 gate 结果：验收项有没有被原件支持。完成以门禁结论为准。证据信封本身不算证明。
经验库：经审核才能选用的项目规则。不自动变成任务事实。合同点名之后才在门禁里生效。放在 `.prime/experience/`。
checked_resume：确认读到的是这个项目、这个任务、这版技能包。对不上就不返回上下文。

不要把密钥、令牌或私钥放进这些文件。
"""


class StoreNotWritable(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _run_git(root: Path, *args: str, check: bool = False, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def resolve_worktree_root(cwd: str | Path | None = None) -> Path:
    start = Path(cwd or Path.cwd()).resolve()
    try:
        completed = _run_git(start, "rev-parse", "--show-toplevel", timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreNotWritable("NOT_A_REPOSITORY", "cannot inspect Git worktree") from exc
    if completed.returncode != 0:
        raise StoreNotWritable("NOT_A_REPOSITORY", completed.stderr.strip() or "not a git repository")
    return Path(completed.stdout.strip()).resolve()


def context_root(worktree: Path | None = None) -> Path:
    root = worktree or resolve_worktree_root()
    return (root / RELATIVE_CONTEXT).resolve()


def task_dir(task_id: str, worktree: Path | None = None) -> Path:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id.strip()).strip("-")
    if not safe:
        raise ValueError("task_id contains no usable characters")
    return context_root(worktree) / safe


def _head_kind(root: Path) -> str:
    detached = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if detached.returncode != 0:
        raise StoreNotWritable("NOT_A_REPOSITORY", detached.stderr.strip() or "HEAD unavailable")
    if detached.stdout.strip() == "HEAD":
        return "detached"
    return "branch"


def _merge_in_progress(root: Path) -> bool:
    completed = _run_git(root, "rev-parse", "--git-path", "MERGE_HEAD")
    if completed.returncode != 0:
        return (root / ".git" / "MERGE_HEAD").exists()
    path = Path(completed.stdout.strip())
    if not path.is_absolute():
        path = root / path
    return path.exists()


def assert_writable(worktree: Path | None = None) -> Path:
    root = worktree or resolve_worktree_root()
    if _head_kind(root) == "detached":
        raise StoreNotWritable("DETACHED_HEAD", "detached HEAD is read-only")
    if _merge_in_progress(root):
        raise StoreNotWritable("MERGE_IN_PROGRESS", "merge in progress")
    return root


def assert_publishable(worktree: Path | None = None) -> Path:
    root = assert_writable(worktree)
    if _run_git(root, "config", "--get", "core.hooksPath").stdout.strip() != HOOKS_PATH:
        raise StoreNotWritable("HOOKS_NOT_INSTALLED", "core.hooksPath must be .githooks")
    upstream = _run_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode != 0:
        return root
    fetched = _run_git(root, "fetch", upstream.stdout.strip().split("/", 1)[0], timeout=60)
    if fetched.returncode != 0:
        raise StoreNotWritable("FETCH_FAILED", fetched.stderr.strip() or "git fetch failed")
    behind = _run_git(root, "rev-list", "--count", "HEAD..@{upstream}")
    if behind.returncode != 0:
        raise StoreNotWritable("FETCH_FAILED", behind.stderr.strip() or "cannot compare upstream")
    if behind.stdout.strip() not in {"", "0"}:
        raise StoreNotWritable("BEHIND_UPSTREAM", "local branch is behind upstream")
    return root


def ensure_legend(worktree: Path | None = None) -> Path:
    root = assert_writable(worktree)
    path = root / ".prime" / "CONTEXT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(LEGEND, encoding="utf-8")
    return path


def _event_id(line: str) -> str | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("event_id")
    return value if isinstance(value, str) and value else None


def _has_conflict_markers(text: str) -> bool:
    return "<<<<<<<" in text or "=======" in text or ">>>>>>>" in text


def union_events(ours_lines: Iterable[str], other_lines: Iterable[str]) -> dict[str, Any]:
    ours = [line.rstrip("\n") for line in ours_lines if line.strip()]
    other = [line.rstrip("\n") for line in other_lines if line.strip()]
    if any(_has_conflict_markers(line) for line in ours + other):
        raise StoreNotWritable("CONFLICT_MARKERS", "events.jsonl has Git conflict markers")
    ours_by_id: dict[str, str] = {}
    order: list[str] = []
    unidentified: list[str] = []
    for line in ours:
        event_id = _event_id(line)
        if event_id is None:
            unidentified.append(line)
            continue
        if event_id in ours_by_id and ours_by_id[event_id] != line:
            return {"status": "conflict", "event_id": event_id, "left": ours_by_id[event_id], "right": line}
        if event_id not in ours_by_id:
            ours_by_id[event_id] = line
            order.append(event_id)
    for line in other:
        event_id = _event_id(line)
        if event_id is None:
            if line not in unidentified:
                unidentified.append(line)
            continue
        if event_id in ours_by_id and ours_by_id[event_id] != line:
            return {"status": "conflict", "event_id": event_id, "left": ours_by_id[event_id], "right": line}
        if event_id not in ours_by_id:
            ours_by_id[event_id] = line
            order.append(event_id)
    return {"status": "merged", "lines": unidentified + [ours_by_id[event_id] for event_id in order]}


def write_conflict(task_id: str, event_id: str, left: str, right: str, worktree: Path | None = None) -> Path:
    root = worktree or resolve_worktree_root()
    if _head_kind(root) == "detached":
        raise StoreNotWritable("DETACHED_HEAD", "detached HEAD is read-only")
    path = task_dir(task_id, root) / f"conflict-{event_id}.json"
    payload = {"event_id": event_id, "left": left, "right": right}
    if path.exists() and path.read_text(encoding="utf-8") != json.dumps(payload, ensure_ascii=False, indent=2) + "\n":
        raise StoreNotWritable("CONFLICT_EXISTS", f"conflict file already exists for {event_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _is_absolute_path_string(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value) is not None


def _walk_absolute(value: object, prefix: str, found: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _walk_absolute(item, f"{prefix}.{key}", found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_absolute(item, f"{prefix}[{index}]", found)
    elif _is_absolute_path_string(value):
        found.append(prefix)


def _contains_secrets(text: str) -> bool:
    return any(marker in text for marker in SECRET_MARKERS)


def _rebuild_snapshot_from_events(task_id: str, lines: list[str]) -> dict[str, Any]:
    items: dict[str, Any] = {}
    checkpoint = None
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            continue
        if event.get("event_type") == "checkpoint":
            checkpoint = event.get("checkpoint") or event.get("latest_checkpoint")
        item_id = event.get("item_id")
        if isinstance(item_id, str) and item_id:
            items[item_id] = event
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            item = payload.get("item")
            if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                items[item["id"]] = item
            if event.get("event_type") == "checkpoint-recorded" and isinstance(payload.get("checkpoint"), Mapping):
                checkpoint = payload.get("checkpoint")
    return {"task_id": task_id, "items": items, "latest_checkpoint": checkpoint}


def _rebuilt_snapshot(task_id: str, lines: list[str]) -> dict[str, Any]:
    events = [json.loads(line) for line in lines]
    from managing_long_task_context import _rebuild_snapshot
    return _rebuild_snapshot(task_id, events)


def _snapshot_fields_match(snapshot: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> bool:
    return json.dumps(snapshot, sort_keys=True) == json.dumps(rebuilt, sort_keys=True)


def _scan_secrets(root: Path) -> list[str]:
    found: list[str] = []
    for relative in CONTEXT_PATHS:
        path = root / relative
        if not path.exists():
            continue
        files = [path] if path.is_file() else [child for child in path.rglob("*") if child.is_file()]
        for child in files:
            try:
                data = child.read_bytes()
            except OSError:
                found.append(child.relative_to(root).as_posix())
                continue
            text = data.decode("utf-8", errors="replace")
            if _contains_secrets(text) or any(marker.encode("ascii") in data for marker in SECRET_MARKERS):
                found.append(child.relative_to(root).as_posix())
    return found


def check_store(task_id: str, worktree: Path | None = None) -> dict[str, Any]:
    try:
        root = resolve_worktree_root(worktree)
    except StoreNotWritable as exc:
        return {"status": "missing", "report": str(exc), "code": exc.code}
    prime = root / ".prime"
    if not prime.exists():
        return {"status": "missing", "report": "没有上下文", "code": "NO_PRIME"}
    directory = task_dir(task_id, root)
    if not directory.exists():
        return {"status": "missing", "report": "没有上下文", "code": "NO_TASK"}
    contract_path = directory / "task-contract.json"
    events_path = directory / "events.jsonl"
    snapshot_path = directory / "snapshot.json"
    missing = [name for name, path in (("task-contract.json", contract_path), ("events.jsonl", events_path), ("snapshot.json", snapshot_path)) if not path.exists()]
    if missing:
        return {"status": "invalid", "report": "missing " + ", ".join(missing), "code": "MISSING_FILE"}
    events_text = events_path.read_text(encoding="utf-8")
    if _has_conflict_markers(events_text):
        return {"status": "invalid", "report": "events.jsonl has conflict markers", "code": "CONFLICT_MARKERS", "file": str(events_path.relative_to(root))}
    leaked = _scan_secrets(root)
    if leaked:
        return {"status": "invalid", "report": "known secret marker found", "code": "SECRETS_FOUND", "files": leaked}
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "report": f"json: {exc}", "code": "JSON_INVALID"}
    if snapshot == REBUILD_MARKER:
        return {"status": "invalid", "report": "snapshot requires rebuild", "code": "SNAPSHOT_REBUILD", "file": "snapshot.json"}
    lines = [line for line in events_text.splitlines() if line.strip()]
    try:
        rebuilt = _rebuilt_snapshot(task_id, lines)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"status": "invalid", "report": "snapshot cannot be rebuilt from events", "code": "SNAPSHOT_DRIFT"}
    if not _snapshot_fields_match(snapshot, rebuilt):
        return {"status": "invalid", "report": "snapshot cannot be rebuilt from events", "code": "SNAPSHOT_DRIFT"}
    found: list[str] = []
    _walk_absolute(contract, "task-contract", found)
    binding_path = directory / "context-binding.json"
    if binding_path.exists():
        try:
            _walk_absolute(json.loads(binding_path.read_text(encoding="utf-8")), "context-binding", found)
        except json.JSONDecodeError:
            return {"status": "invalid", "report": "binding json invalid", "code": "JSON_INVALID", "file": "context-binding.json"}
    if found:
        return {"status": "invalid", "report": "absolute path " + ", ".join(found), "code": "ABSOLUTE_PATH", "fields": found}
    return {"status": "ok", "report": "store is consistent"}


def read_task(task_id: str, worktree: Path | None = None) -> dict[str, Any]:
    result = {"seal_digest": None, "snapshot": None, "latest_checkpoint": None}
    try:
        root = resolve_worktree_root(worktree)
    except StoreNotWritable:
        return result
    directory = task_dir(task_id, root)
    if not directory.exists():
        return result
    contract_path = directory / "task-contract.json"
    snapshot_path = directory / "snapshot.json"
    events_path = directory / "events.jsonl"
    if contract_path.exists():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            seal = contract.get("seal") if isinstance(contract, dict) else None
            digest = seal.get("integrity_digest") if isinstance(seal, dict) else None
            result["seal_digest"] = digest if isinstance(digest, str) else None
        except (OSError, json.JSONDecodeError):
            result["seal_digest"] = None
    if snapshot_path.exists() and events_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rebuilt = _rebuilt_snapshot(task_id, lines)
            if isinstance(snapshot, dict) and _snapshot_fields_match(snapshot, rebuilt):
                result["snapshot"] = snapshot
                checkpoint = snapshot.get("latest_checkpoint")
                result["latest_checkpoint"] = checkpoint if checkpoint is not None else None
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _relativize(value: Any, worktree: Path) -> Any:
    if isinstance(value, Mapping):
        return {key: _relativize(item, worktree) for key, item in value.items()}
    if isinstance(value, list):
        return [_relativize(item, worktree) for item in value]
    if isinstance(value, str) and _is_absolute_path_string(value):
        path = Path(value)
        try:
            relative = path.resolve().relative_to(worktree)
        except ValueError:
            return value
        return "." if relative == Path(".") else relative.as_posix()
    return value


def migrate_contract(task_id: str, worktree: Path | None = None) -> dict[str, Any]:
    root = assert_writable(worktree)
    directory = task_dir(task_id, root)
    contract_path = directory / "task-contract.json"
    if not contract_path.exists():
        raise StoreNotWritable("NO_TASK", "task contract is missing")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise StoreNotWritable("CONTRACT_INVALID", "contract is not an object")
    updated = _relativize(contract, root)
    updated["workspace_root"] = RELATIVE_WORKSPACE
    version = updated.get("version")
    updated["version"] = int(version) + 1 if isinstance(version, int) else 1
    previous_seal = updated.get("seal") if isinstance(updated.get("seal"), Mapping) else {}
    updated.pop("seal", None)
    from managing_long_task_context import (
        _append_event_locked,
        _contract_digest,
        _load_snapshot,
        _locked,
        _new_event,
        _now,
        _paths,
    )
    confirmed_by = previous_seal.get("confirmed_by") or "publisher"
    updated["seal"] = {
        "confirmed_by": confirmed_by,
        "confirmed_at": _now(),
        "file_protection": previous_seal.get("file_protection") or "read-only-advisory-v1",
    }
    updated["seal"]["integrity_digest"] = _contract_digest(updated)
    if contract_path.exists():
        contract_path.chmod(stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    contract_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if updated["seal"].get("file_protection") == "read-only-advisory-v1":
        contract_path.chmod(0o444)
    paths = _paths(task_id, context_root(root))
    with _locked(paths["root"]):
        snapshot = _load_snapshot(task_id, paths)
        event = _new_event(
            task_id,
            "contract-published",
            str(confirmed_by),
            {
                "task_id": task_id,
                "version": updated["version"],
                "integrity_digest": updated["seal"]["integrity_digest"],
                "confirmed_by": confirmed_by,
                "confirmed_at": updated["seal"]["confirmed_at"],
            },
        )
        _append_event_locked(paths, snapshot, event)
    binding_path = directory / "context-binding.json"
    if binding_path.exists():
        try:
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            binding = {}
        if isinstance(binding, dict):
            binding["workspace_root"] = RELATIVE_WORKSPACE
            binding["context_root"] = RELATIVE_CONTEXT
            binding_path.write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updated


def hook_script() -> str:
    paths = " ".join(CONTEXT_PATHS)
    return f"""#!/bin/sh
if [ "${PUBLISH_ENV}" = "1" ]; then
  exit 0
fi
if git diff --cached --name-only -- {paths} | grep -q .; then
  echo "CONTEXT_PATHS must be committed by publish_context only" >&2
  exit 1
fi
exit 0
"""


def merge_script() -> str:
    return r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

REBUILD_MARKER = {"rebuild": "required"}

def event_id(line):
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("event_id")
    return value if isinstance(value, str) and value else None

def has_conflict_markers(text):
    return "<<<<<<<" in text or "=======" in text or ">>>>>>>" in text

def union_events(ours_lines, other_lines):
    ours = [line.rstrip("\n") for line in ours_lines if line.strip()]
    other = [line.rstrip("\n") for line in other_lines if line.strip()]
    if any(has_conflict_markers(line) for line in ours + other):
        sys.stderr.write("events.jsonl has Git conflict markers\n")
        sys.exit(1)
    ours_by_id = {}
    order = []
    unidentified = []
    for line in ours:
        eid = event_id(line)
        if eid is None:
            unidentified.append(line)
            continue
        if eid in ours_by_id and ours_by_id[eid] != line:
            sys.stderr.write("duplicate event_id with different lines\n")
            sys.exit(1)
        if eid not in ours_by_id:
            ours_by_id[eid] = line
            order.append(eid)
    for line in other:
        eid = event_id(line)
        if eid is None:
            if line not in unidentified:
                unidentified.append(line)
            continue
        if eid in ours_by_id and ours_by_id[eid] != line:
            path = Path(sys.argv[2]).parent / ("conflict-%s.json" % eid)
            path.write_text(json.dumps({"event_id": eid, "left": ours_by_id[eid], "right": line}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            snapshot = Path(sys.argv[2]).with_name("snapshot.json")
            if snapshot.exists():
                snapshot.write_text(json.dumps(REBUILD_MARKER) + "\n", encoding="utf-8")
            sys.exit(1)
        if eid not in ours_by_id:
            ours_by_id[eid] = line
            order.append(eid)
    return unidentified + [ours_by_id[eid] for eid in order]

ours = Path(sys.argv[2])
theirs = Path(sys.argv[3])
lines = union_events(ours.read_text(encoding="utf-8").splitlines(), theirs.read_text(encoding="utf-8").splitlines())
ours.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
snapshot = ours.with_name("snapshot.json")
if snapshot.exists():
    snapshot.write_text(json.dumps(REBUILD_MARKER) + "\n", encoding="utf-8")
sys.exit(0)
'''


def attributes_text() -> str:
    return """.prime/context/**/events.jsonl merge=mltc-events
.prime/context/**/snapshot.json merge=mltc-snapshot
"""


def _install_project_git_files(root: Path) -> None:
    ensure_legend(root)
    hooks = root / HOOKS_PATH
    hooks.mkdir(parents=True, exist_ok=True)
    hook = root / HOOK_FILE
    hook.write_text(hook_script(), encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    script = root / MERGE_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(merge_script(), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    attributes = root / ATTRIBUTES_FILE
    extra = attributes_text()
    current = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
    head = _run_git(root, "show", f"HEAD:{ATTRIBUTES_FILE}")
    head_text = head.stdout if head.returncode == 0 else ""
    desired = head_text if extra in head_text else head_text + extra
    if current not in {"", head_text, desired}:
        raise StoreNotWritable("ATTRIBUTES_DIRTY", ".gitattributes has unrelated edits")
    if extra not in current:
        attributes.write_text(desired, encoding="utf-8")
    _run_git(root, "config", "core.hooksPath", HOOKS_PATH)
    _run_git(root, "config", "merge.mltc-events.driver", f"python3 {MERGE_SCRIPT} %O %A %B")
    _run_git(root, "config", "merge.mltc-snapshot.driver", f"python3 -c 'import json,sys; from pathlib import Path; Path(sys.argv[2]).write_text(json.dumps({{\"rebuild\":\"required\"}})+chr(10))' %O %A %B")


def _force_add(root: Path) -> None:
    for relative in CONTEXT_PATHS:
        path = root / relative
        if path.exists():
            _run_git(root, "add", "-f", "--", relative)
    for relative in (HOOK_FILE, MERGE_SCRIPT, ATTRIBUTES_FILE):
        if (root / relative).exists():
            _run_git(root, "add", "-f", "--", relative)


def publish_context(task_id: str, worktree: Path | None = None) -> dict[str, Any]:
    root = resolve_worktree_root(worktree)
    _install_project_git_files(root)
    checked = check_store(task_id, root)
    if checked["status"] != "ok":
        if checked.get("code") == "SECRETS_FOUND":
            raise StoreNotWritable("SECRETS_FOUND", checked["report"])
        raise StoreNotWritable(str(checked.get("code") or "STORE_INVALID"), checked["report"])
    assert_publishable(root)
    env = os.environ.copy()
    env[PUBLISH_ENV] = "1"
    _force_add(root)
    leaked = _scan_secrets(root)
    if leaked:
        _run_git(root, "reset", "-q", "HEAD", "--", *CONTEXT_PATHS, HOOK_FILE, MERGE_SCRIPT, ATTRIBUTES_FILE)
        raise StoreNotWritable("SECRETS_FOUND", "known secret marker found")
    commit_paths = [relative for relative in CONTEXT_PATHS if (root / relative).exists()]
    commit_paths.extend(relative for relative in (HOOK_FILE, MERGE_SCRIPT, ATTRIBUTES_FILE) if (root / relative).exists())
    commit = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", f"context: publish {task_id}", "--", *commit_paths],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=30,
    )
    if commit.returncode != 0:
        _run_git(root, "reset", "-q", "HEAD", "--", *commit_paths)
        raise StoreNotWritable("COMMIT_FAILED", commit.stderr.strip() or commit.stdout.strip() or "commit failed")
    upstream = _run_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode == 0:
        remote, branch = upstream.stdout.strip().split("/", 1)
        pushed = _run_git(root, "push", remote, f"HEAD:{branch}")
        if pushed.returncode != 0:
            raise StoreNotWritable("PUSH_FAILED", pushed.stderr.strip() or "push failed")
    else:
        pushed = _run_git(root, "push", "-u", "origin", "HEAD")
        if pushed.returncode != 0:
            raise StoreNotWritable("PUSH_FAILED", pushed.stderr.strip() or "first push failed")
    return {"status": "ok", "task_id": task_id}


def _local_event_ids(directory: Path) -> set[str]:
    path = directory / "events.jsonl"
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        event_id = _event_id(line)
        if event_id:
            ids.add(event_id)
    return ids


def _head_event_ids(root: Path, task_id: str) -> set[str]:
    relative = f"{RELATIVE_CONTEXT}/{task_id}/events.jsonl"
    completed = _run_git(root, "show", f"HEAD:{relative}")
    if completed.returncode != 0:
        return set()
    ids: set[str] = set()
    for line in completed.stdout.splitlines():
        event_id = _event_id(line)
        if event_id:
            ids.add(event_id)
    return ids


def align_context(task_id: str, worktree: Path | None = None) -> dict[str, Any]:
    root = resolve_worktree_root(worktree)
    if _head_kind(root) == "detached":
        raise StoreNotWritable("DETACHED_HEAD", "detached HEAD is read-only")
    if _merge_in_progress(root):
        raise StoreNotWritable("MERGE_IN_PROGRESS", "merge in progress")
    if _run_git(root, "config", "--get", "core.hooksPath").stdout.strip() != HOOKS_PATH:
        raise StoreNotWritable("HOOKS_NOT_INSTALLED", "core.hooksPath must be .githooks")
    tracked = _run_git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", *CONTEXT_PATHS)
    names = {line for line in tracked.stdout.splitlines() if line.strip()}
    if tracked.returncode != 0 or not any(name.startswith(RELATIVE_CONTEXT + "/") or name == RELATIVE_CONTEXT for name in names):
        return {"status": "missing", "report": "没有可对齐的上下文"}
    directory = task_dir(task_id, root)
    local_ids = _local_event_ids(directory)
    head_ids = _head_event_ids(root, task_id)
    extra = local_ids - head_ids
    if extra:
        raise StoreNotWritable("LOCAL_AHEAD", "local events are not in HEAD: " + ", ".join(sorted(extra)))
    checkout_paths = [relative for relative in CONTEXT_PATHS if any(name == relative or name.startswith(relative + "/") for name in names)]
    checkout = _run_git(root, "checkout", "HEAD", "--", *checkout_paths)
    if checkout.returncode != 0:
        raise StoreNotWritable("ALIGN_FAILED", checkout.stderr.strip() or "checkout failed")
    return {"status": "ok", "task_id": task_id}


def stored_workspace_matches(stored: object, workspace: Path) -> bool:
    if stored == str(workspace):
        return True
    if stored == RELATIVE_WORKSPACE:
        try:
            return workspace.resolve() == resolve_worktree_root(workspace)
        except StoreNotWritable:
            return False
    return False


def stored_context_matches(stored: object, context: Path) -> bool:
    if stored == str(context):
        return True
    if stored not in {RELATIVE_CONTEXT, f"./{RELATIVE_CONTEXT}"}:
        return False
    start = context
    for _ in range(6):
        try:
            return context.resolve() == context_root(resolve_worktree_root(start))
        except StoreNotWritable:
            if start.parent == start:
                return False
            start = start.parent
    return False


def default_experience_root(workspace: Path) -> Path:
    return workspace / RELATIVE_EXPERIENCE
