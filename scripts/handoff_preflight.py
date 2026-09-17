#!/usr/bin/env python3
"""Strict-only, read-only migration preflight for short-session handoff.

The exit code answers one question only: are the inputs of the selected mode
and stage safe, complete, and consistent?  It is not the migration result.

    AUTHORITATIVE_NOW plan + CONTEXT
                  |
                  v
       handoff_preflight.py --stage ...
          |       |          |
          |       |          +--> Git ancestry + allowlisted diff
          |       +-------------> bounded file/SHA/binding checks
          +---------------------> recovery checklist/readback comparison
                  |
                  v
           preflight_status  pass|fail|unknown  -> exit 0|1|2
                  |
           +------+------+
           v             v
     strict_protocol   manual_fallback
     prepare gate      recovery gate only
     activate gate     no control events
     status gate       material + semantic recovery only
           |             |
           +------+------+
                  v
           migration_outcome (three separate dimensions)
       information_recovery: pass|fail|unknown
       control_transfer:     pass|fail|unknown
       source_retirement:    not_allowed
       archive_allowed:      false

This script never calls a v1 write entry, never writes files, and never
archives a session.  A host that owns a trusted handoff verifier may call
``run_preflight(..., handoff_verifier=...)`` in-process; the CLI has none and
therefore reports Strict activation/status verification as unknown.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # A read-only preflight must not create __pycache__.

import argparse
import errno
import hashlib
import importlib
import json
import os
import re
import selectors
import stat
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "migration-preflight/v1"
CHECKLIST_SCHEMA = "recovery-checklist/v1"
READBACK_SCHEMA = "recovery-readback/v1"
CAPABILITY = "short-session-handoff/v1"
MODE_STAGES = {"strict_protocol": ("prepare", "activate", "status"), "manual_fallback": ("recovery",)}
CATEGORIES = ("objective", "current_state", "constraints", "next_action", "unresolved_risks")
MAX_FILE_BYTES = 1024 * 1024
MAX_FACTS = 64
GIT_CALL_SECONDS = 5.0
GIT_TOTAL_SECONDS = 15.0
GIT_STREAM_BYTES = 1024 * 1024
GIT_MAX_PATHS = 10_000
CONTEXT_FILE = "CONTEXT.md"
EVIDENCE_PREFIX = "docs/superpowers/evidence/context-strict-migration/"
PLANS_PREFIX = "docs/superpowers/plans/"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$")

# Every stable code has exactly one status class.  Messages are fixed text:
# no exception strings, material contents, user names, or absolute paths.
CODE_STATUS = {
    "PREFLIGHT_INPUT_INVALID": "fail",
    "PREFLIGHT_DIGEST_MISMATCH": "fail",
    "PREFLIGHT_BINDING_MISMATCH": "fail",
    "PREFLIGHT_PATH_ESCAPE": "fail",
    "PREFLIGHT_SYMLINK_REJECTED": "fail",
    "PREFLIGHT_NOT_REGULAR_FILE": "fail",
    "PREFLIGHT_OVERSIZE": "fail",
    "PREFLIGHT_READBACK_MISMATCH": "fail",
    "PREFLIGHT_AUTHORITY_CONFLICT": "fail",
    "PREFLIGHT_LINK_INVALID": "fail",
    "PREFLIGHT_LINK_MISSING": "fail",
    "PREFLIGHT_UNTRACKED_DEPENDENCY": "fail",
    "PREFLIGHT_CAPABILITY_MISSING": "fail",
    "PREFLIGHT_HANDOFF_NOT_PREPARED": "fail",
    "PREFLIGHT_VERIFIER_REJECTED": "fail",
    "PREFLIGHT_FILE_UNAVAILABLE": "unknown",
    "PREFLIGHT_READ_RACE": "unknown",
    "PREFLIGHT_GIT_UNAVAILABLE": "unknown",
    "PREFLIGHT_GIT_TIMEOUT": "unknown",
    "PREFLIGHT_GIT_OUTPUT_LIMIT": "unknown",
    "PREFLIGHT_WORKTREE_DIRTY": "unknown",
    "PREFLIGHT_REVISION_UNVERIFIED": "unknown",
    "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN": "unknown",
    "PREFLIGHT_PACKAGE_SHA_MISSING": "unknown",
    "PREFLIGHT_CONTRACT_UNAVAILABLE": "unknown",
    "PREFLIGHT_HANDOFF_STATE_UNAVAILABLE": "unknown",
    "PREFLIGHT_VERIFIER_UNAVAILABLE": "unknown",
    "PREFLIGHT_UNEXPECTED_ERROR": "unknown",
    "PREFLIGHT_DEPENDENCY_NOT_RUN": "not_run",
    "PREFLIGHT_REVISION_STALE": "stale",
    "PREFLIGHT_PLAN_STALE": "stale",
    "PREFLIGHT_PACKAGE_STALE": "stale",
}

NEXT_READONLY_ACTION = {
    "PREFLIGHT_INPUT_INVALID": "Correct the preflight arguments or the rejected input structure, then re-run preflight.",
    "PREFLIGHT_DIGEST_MISMATCH": "Re-read the bound material and supply the digest of the reviewed version; do not continue.",
    "PREFLIGHT_BINDING_MISMATCH": "Compare the task, plan, handoff, and workspace bindings; do not continue with mismatched material.",
    "PREFLIGHT_PATH_ESCAPE": "Supply material located inside the workspace root; do not follow the escaping path.",
    "PREFLIGHT_SYMLINK_REJECTED": "Replace the symbolic link with the reviewed regular file, then re-run preflight.",
    "PREFLIGHT_NOT_REGULAR_FILE": "Supply a regular file for the rejected input, then re-run preflight.",
    "PREFLIGHT_OVERSIZE": "Reduce the rejected input to the supported limits; do not truncate it silently.",
    "PREFLIGHT_READBACK_MISMATCH": "Have the target session re-read the handoff material and regenerate its readback.",
    "PREFLIGHT_AUTHORITY_CONFLICT": "Restore a single AUTHORITATIVE_NOW entry and label other material as historical.",
    "PREFLIGHT_LINK_INVALID": "Replace absolute or escaping links in the recovery entry with relative workspace links.",
    "PREFLIGHT_LINK_MISSING": "Restore or remove the missing linked file in the recovery entry.",
    "PREFLIGHT_UNTRACKED_DEPENDENCY": "Track the linked dependency in Git or remove the local-only link.",
    "PREFLIGHT_CAPABILITY_MISSING": "Use manual_fallback or publish a contract that explicitly enables short-session-handoff/v1.",
    "PREFLIGHT_HANDOFF_NOT_PREPARED": "Read handoff_status for this task; do not activate a handoff that is not currently prepared.",
    "PREFLIGHT_VERIFIER_REJECTED": "Keep the source session in control and inspect the rejected handoff evidence read-only.",
    "PREFLIGHT_FILE_UNAVAILABLE": "Make the required material readable, then re-run preflight.",
    "PREFLIGHT_READ_RACE": "Wait until the material stops changing, then re-run preflight; do not retry automatically.",
    "PREFLIGHT_GIT_UNAVAILABLE": "Inspect the Git workspace read-only; revision scope is unknown.",
    "PREFLIGHT_GIT_TIMEOUT": "Inspect the Git workspace read-only; revision checks exceeded their time budget.",
    "PREFLIGHT_GIT_OUTPUT_LIMIT": "Inspect the Git workspace read-only; revision output exceeded its limits.",
    "PREFLIGHT_WORKTREE_DIRTY": "Commit or remove uncommitted workspace changes, then re-run preflight.",
    "PREFLIGHT_REVISION_UNVERIFIED": "Run the complete verification on a commit and record it as verified_head.",
    "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN": "Run this script from one complete built package with PYTHONPATH set to that package's src.",
    "PREFLIGHT_PACKAGE_SHA_MISSING": "Record the verified package manifest SHA-256 in CONTEXT.md after complete package verification.",
    "PREFLIGHT_CONTRACT_UNAVAILABLE": "Read the sealed task contract and event log read-only; Strict prerequisites are unknown.",
    "PREFLIGHT_HANDOFF_STATE_UNAVAILABLE": "Read the handoff record and event log read-only; control state is unknown.",
    "PREFLIGHT_VERIFIER_UNAVAILABLE": "Keep the source session in control; obtain a trusted host verifier before any activation.",
    "PREFLIGHT_UNEXPECTED_ERROR": "Keep the source session in control and re-run preflight after inspecting inputs read-only.",
    "PREFLIGHT_DEPENDENCY_NOT_RUN": "Resolve the earlier blocking check first.",
    "PREFLIGHT_REVISION_STALE": "Re-run the complete verification on the current HEAD before relying on this entry.",
    "PREFLIGHT_PLAN_STALE": "Update CONTEXT.md to the reviewed plan digest after re-verification.",
    "PREFLIGHT_PACKAGE_STALE": "Rebuild and verify the package, then record its manifest SHA-256 after re-verification.",
}

PASS_ACTION = {
    ("strict_protocol", "prepare"): "Call the existing prepare_handoff; this preflight prepared nothing.",
    ("strict_protocol", "activate"): "Call the existing activate_handoff with the same trusted verifier; this preflight activated nothing.",
    ("strict_protocol", "status"): "Report the three migration dimensions separately; archive remains not allowed.",
    ("manual_fallback", "recovery"): "Report information recovery only; keep the source session and do not archive.",
}


def _manifest_observation(script: Path) -> tuple[Path, str | None]:
    manifest = script.parents[1] / "skill-manifest.json"
    try:
        with manifest.open("rb") as stream:
            return manifest, hashlib.sha256(stream.read()).hexdigest()
    except OSError:
        return manifest, None


_SCRIPT = Path(__file__).resolve()
_MANIFEST_AT_START = _manifest_observation(_SCRIPT)

try:  # Sibling tools must come from the same package; identity checks prove it.
    import context_identity_core as _core
    import skill_package as _skill_package
except ImportError:  # pragma: no cover - reported as unknown package identity
    _core = None
    _skill_package = None


def _check(name: str, status: str, code: str | None, message: str, refs: Sequence[str] = ()) -> dict[str, object]:
    if status == "pass":
        if code is not None:
            raise ValueError("a passing check has no code")
    elif CODE_STATUS.get(str(code)) != status:
        raise ValueError(f"code {code} is not registered for status {status}")
    return {"name": name, "status": status, "code": code, "message": message, "evidence_refs": list(refs)}


def _not_run(name: str, refs: Sequence[str] = ()) -> dict[str, object]:
    return _check(name, "not_run", "PREFLIGHT_DEPENDENCY_NOT_RUN", "a prerequisite check did not pass", refs)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(data)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401 - argparse hook
        raise ValueError("invalid arguments")


def parse_args(argv: Iterable[str] | None) -> argparse.Namespace | None:
    parser = _ArgumentParser(add_help=False)
    for option in (
        "mode", "stage", "package-root", "context-root", "workspace-root", "task-id", "handoff-id",
        "plan", "expected-plan-sha256", "expected-verified-head", "handoff-file",
        "expected-handoff-sha256", "recovery-checklist", "expected-checklist-sha256", "recovery-readback",
    ):
        parser.add_argument(f"--{option}")
    try:
        return parser.parse_args(list(argv) if argv is not None else None)
    except ValueError:
        return None


_RECOVERY_GROUP = ("handoff_file", "expected_handoff_sha256", "recovery_checklist", "expected_checklist_sha256")
_ALWAYS = ("mode", "stage", "package_root", "workspace_root", "task_id", "plan", "expected_plan_sha256", "expected_verified_head")


def _stage_arguments(mode: str, stage: str, args: argparse.Namespace) -> tuple[set[str], set[str]]:
    """Return (required, allowed) argument names for one mode/stage pair."""
    required = set(_ALWAYS)
    if mode == "manual_fallback":
        required.update(_RECOVERY_GROUP + ("recovery_readback",))
        return required, set(required)
    required.update(("context_root", "handoff_id"))
    if stage == "prepare":
        required.update(_RECOVERY_GROUP)
        return required, set(required)
    if stage == "activate":
        required.update(_RECOVERY_GROUP + ("recovery_readback",))
        return required, set(required)
    allowed = required | set(_RECOVERY_GROUP) | {"recovery_readback"}
    if any(getattr(args, name) is not None for name in _RECOVERY_GROUP + ("recovery_readback",)):
        required.update(_RECOVERY_GROUP + ("recovery_readback",))  # status material is all-or-none
    return required, allowed


def validate_inputs(args: argparse.Namespace | None) -> tuple[dict[str, Any] | None, dict[str, object]]:
    def invalid(message: str) -> tuple[None, dict[str, object]]:
        return None, _check("input", "fail", "PREFLIGHT_INPUT_INVALID", message, ["cli"])

    if args is None:
        return invalid("arguments could not be parsed")
    mode, stage = args.mode, args.stage
    if mode not in MODE_STAGES or stage not in MODE_STAGES[mode]:
        return invalid("mode and stage are not a supported combination")
    required, allowed = _stage_arguments(mode, stage, args)
    supplied = {name for name, value in vars(args).items() if value is not None}
    if required - supplied:
        return invalid("a required argument for this mode and stage is missing")
    if supplied - allowed:
        return invalid("an argument is not applicable to this mode and stage")
    for name in ("package_root", "context_root", "workspace_root", "handoff_file", "recovery_checklist", "recovery_readback"):
        value = getattr(args, name)
        if value is not None and (not value or not Path(value).is_absolute() or "\x00" in value):
            return invalid("a root or material path is not absolute")
    for name in ("task_id", "handoff_id"):
        value = getattr(args, name)
        if value is not None and _IDENTIFIER.fullmatch(value) is None:
            return invalid("a task or handoff identifier is invalid")
    for name in ("expected_plan_sha256", "expected_handoff_sha256", "expected_checklist_sha256"):
        value = getattr(args, name)
        if value is not None and _SHA256.fullmatch(value) is None:
            return invalid("an expected digest is not a lowercase SHA-256")
    head = args.expected_verified_head
    if head != "NONE" and _GIT_SHA.fullmatch(head) is None:
        return invalid("expected verified head must be a full Git SHA or NONE")
    plan = Path(args.plan)
    if not args.plan or plan.is_absolute() or ".." in plan.parts or "\\" in args.plan or plan.as_posix() != args.plan:
        return invalid("plan must be a normalized relative workspace path")
    inputs = dict(vars(args))
    inputs["expected_verified_head"] = None if head == "NONE" else head
    return inputs, _check("input", "pass", None, "arguments match the selected mode and stage", ["cli"])


def _file_sha256(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            return _sha256(stream.read())
    except OSError:
        return None


def verify_loaded_package_identity(package_root: str) -> tuple[dict[str, object], dict[str, Any] | None]:
    """Prove script, sibling tools, loaded runtime, and manifest are one complete package."""
    refs = ["package:skill-manifest.json"]

    def unknown(message: str) -> tuple[dict[str, object], None]:
        return _check("package_identity", "unknown", "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN", message, refs), None

    given = Path(package_root)
    try:
        root = given.resolve(strict=True)
    except (OSError, RuntimeError):
        return unknown("package root is unavailable")
    if root != given or not root.is_dir():
        return unknown("package root is not a canonical directory")
    try:
        _SCRIPT.relative_to(root)
    except ValueError:
        return unknown("preflight script is not loaded from package root")
    manifest_path, digest_at_start = _MANIFEST_AT_START
    if manifest_path != root / "skill-manifest.json" or digest_at_start is None:
        return unknown("package manifest was unavailable when preflight started")
    if _core is None or _skill_package is None:
        return unknown("package tools could not be imported")
    try:
        runtime = importlib.import_module("managing_long_task_context")
    except Exception:
        return unknown("Strict runtime could not be imported")
    loaded = {
        "scripts/handoff_preflight.py": _SCRIPT,
        "scripts/context_identity_core.py": Path(_core.__file__).resolve(),
        "scripts/skill_package.py": Path(_skill_package.__file__).resolve(),
        "src/managing_long_task_context/__init__.py": Path(str(runtime.__file__)).resolve(),
    }
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        entries = {str(item["path"]): str(item["sha256"]) for item in manifest["files"]}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return unknown("package manifest cannot be parsed")
    if _sha256(manifest_bytes) != digest_at_start:
        return unknown("package manifest changed after preflight started")
    for relative, path in loaded.items():
        if path != root / relative or entries.get(relative) != _file_sha256(path):
            return unknown("a loaded module does not belong to the package manifest")
    try:
        identity = runtime.runtime_identity(package_root=root)
        verification = _skill_package.verify_package(root)
    except Exception:
        return unknown("runtime identity or package verification could not complete")
    if not isinstance(identity, Mapping) or identity.get("status") != "pass":
        return unknown("loaded Strict runtime identity did not pass")
    if not isinstance(verification, Mapping) or verification.get("status") != "pass":
        return unknown("complete package verification did not pass")
    if _file_sha256(manifest_path) != digest_at_start:
        return unknown("package manifest changed during preflight")
    facts = {"root": root, "manifest_sha256": digest_at_start, "runtime": runtime}
    return _check("package_identity", "pass", None, "script, runtime, and manifest belong to one complete package", refs), facts


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def read_bounded_file(path: Path, *, limit: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Read one regular file once; parse and hash only these exact bytes."""

    def result(code: str, message: str) -> dict[str, Any]:
        return {"status": CODE_STATUS[code], "code": code, "message": message}

    try:
        before = os.lstat(path)
    except OSError:
        return result("PREFLIGHT_FILE_UNAVAILABLE", "input file is unavailable")
    if stat.S_ISLNK(before.st_mode):
        return result("PREFLIGHT_SYMLINK_REJECTED", "input file is a symbolic link")
    if not stat.S_ISREG(before.st_mode):
        return result("PREFLIGHT_NOT_REGULAR_FILE", "input file is not a regular file")
    if before.st_size > limit:
        return result("PREFLIGHT_OVERSIZE", "input file exceeds the byte limit")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return result("PREFLIGHT_SYMLINK_REJECTED", "input file became a symbolic link")
        return result("PREFLIGHT_READ_RACE", "input file changed before it was opened")
    chunks: list[bytes] = []
    total = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return result("PREFLIGHT_READ_RACE", "input file identity changed before reading")
        if opened.st_size > limit:
            return result("PREFLIGHT_OVERSIZE", "input file exceeds the byte limit")
        while True:
            chunk = os.read(descriptor, min(64 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:  # fstat already proved the size was within the limit
                return result("PREFLIGHT_READ_RACE", "input file grew while it was read")
        after = os.fstat(descriptor)
    except OSError:
        return result("PREFLIGHT_READ_RACE", "input file could not be read consistently")
    finally:
        os.close(descriptor)
    if _identity(after) != _identity(opened) or total != after.st_size:
        return result("PREFLIGHT_READ_RACE", "input file changed while it was read")
    try:
        final = os.lstat(path)
    except OSError:
        return result("PREFLIGHT_READ_RACE", "input file disappeared after reading")
    if stat.S_ISLNK(final.st_mode) or _identity(final) != _identity(opened):
        return result("PREFLIGHT_READ_RACE", "input file changed after reading")
    data = b"".join(chunks)
    return {"status": "pass", "data": data, "sha256": _sha256(data)}


def _workspace_file(workspace: Path, raw: str | Path) -> tuple[Path | None, dict[str, Any] | None]:
    """Keep a supplied path inside the workspace without following symbolic links."""
    candidate = Path(raw) if Path(raw).is_absolute() else workspace / raw
    try:
        candidate.relative_to(workspace)
    except ValueError:
        return None, {"status": "fail", "code": "PREFLIGHT_PATH_ESCAPE", "message": "input path is outside the workspace"}
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, {"status": "unknown", "code": "PREFLIGHT_FILE_UNAVAILABLE", "message": "input file is unavailable"}
    try:
        resolved.relative_to(workspace)
    except ValueError:
        return None, {"status": "fail", "code": "PREFLIGHT_PATH_ESCAPE", "message": "input path resolves outside the workspace"}
    if resolved != candidate:
        return None, {"status": "fail", "code": "PREFLIGHT_SYMLINK_REJECTED", "message": "input path contains a symbolic link"}
    return candidate, None


def _read_workspace_file(workspace: Path, raw: str | Path) -> dict[str, Any]:
    path, failure = _workspace_file(workspace, raw)
    if failure is not None or path is None:
        return failure or {"status": "unknown", "code": "PREFLIGHT_FILE_UNAVAILABLE", "message": "input file is unavailable"}
    outcome = read_bounded_file(path)
    outcome["path"] = path
    return outcome


def _from_read(name: str, outcome: Mapping[str, Any], refs: Sequence[str]) -> dict[str, object]:
    return _check(name, str(outcome["status"]), str(outcome["code"]), str(outcome["message"]), refs)


class _DuplicateKey(ValueError):
    pass


def strict_json_loads(data: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise _DuplicateKey("duplicate key")
            value[key] = item
        return value

    def constant(_: str) -> object:
        raise ValueError("non-finite number")

    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the flat ``key: value`` frontmatter; duplicates and nesting are rejected."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return None
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        matched = _FRONTMATTER_KEY.fullmatch(line)
        if matched is None or matched.group(1) in values:
            return None
        values[matched.group(1)] = (matched.group(2) or "").strip()
    return None


def _null(value: str | None) -> bool:
    return value in {None, "", "null", "~"}


def check_plan_digest(workspace: Path, inputs: Mapping[str, Any]) -> tuple[dict[str, object], dict[str, Any] | None]:
    refs = ["plan"]
    outcome = _read_workspace_file(workspace, inputs["plan"])
    if outcome["status"] != "pass":
        return _from_read("plan_digest", outcome, refs), None
    if outcome["sha256"] != inputs["expected_plan_sha256"]:
        return _check("plan_digest", "fail", "PREFLIGHT_DIGEST_MISMATCH", "plan digest differs from the expected digest", refs), None
    try:
        text = outcome["data"].decode("utf-8")
    except UnicodeError:
        return _check("plan_digest", "fail", "PREFLIGHT_INPUT_INVALID", "plan is not UTF-8", refs), None
    frontmatter = parse_frontmatter(text)
    if frontmatter is None:
        return _check("plan_digest", "fail", "PREFLIGHT_INPUT_INVALID", "plan frontmatter is invalid", refs), None
    if len(re.findall(r"(?m)^implementation_authorized:", text)) != 1 or "implementation_authorized" not in frontmatter:
        return _check("plan_digest", "fail", "PREFLIGHT_AUTHORITY_CONFLICT", "plan must define its authorization exactly once", refs), None
    if frontmatter.get("authority") in {"HISTORICAL_ONLY", "SUPERSEDED", "STALE", "UNKNOWN"}:
        return _check("plan_digest", "fail", "PREFLIGHT_AUTHORITY_CONFLICT", "plan is labelled as non-current", refs), None
    facts = {"sha256": outcome["sha256"], "text": text, "path": outcome["path"]}
    return _check("plan_digest", "pass", None, "plan digest and authorization definition are consistent", refs), facts


_CONTEXT_REQUIRED = (
    "authority", "plan_path", "plan_sha256", "package_manifest_sha256", "baseline_head",
    "implementation_head", "verified_head", "verified_at",
)


def check_context_authority(
    workspace: Path, inputs: Mapping[str, Any], plan: Mapping[str, Any] | None,
) -> tuple[dict[str, object], dict[str, Any] | None]:
    refs = [CONTEXT_FILE, "plan"]

    def fail(code: str, message: str) -> tuple[dict[str, object], None]:
        return _check("context_authority", CODE_STATUS[code], code, message, refs), None

    outcome = _read_workspace_file(workspace, CONTEXT_FILE)
    if outcome["status"] != "pass":
        return _from_read("context_authority", outcome, refs), None
    try:
        text = outcome["data"].decode("utf-8")
    except UnicodeError:
        return fail("PREFLIGHT_INPUT_INVALID", "recovery entry is not UTF-8")
    frontmatter = parse_frontmatter(text)
    if frontmatter is None or any(key not in frontmatter for key in _CONTEXT_REQUIRED):
        return fail("PREFLIGHT_INPUT_INVALID", "recovery entry frontmatter lacks required Git identity fields")
    if "observed_head" in frontmatter:
        return fail("PREFLIGHT_INPUT_INVALID", "recovery entry still uses the ambiguous observed_head field")
    if frontmatter["authority"] != "AUTHORITATIVE_NOW" or text.count("AUTHORITATIVE_NOW") != 1:
        return fail("PREFLIGHT_AUTHORITY_CONFLICT", "recovery entry must contain exactly one AUTHORITATIVE_NOW entry")
    if re.search(r"(?m)^implementation_authorized:", text):
        return fail("PREFLIGHT_AUTHORITY_CONFLICT", "authorization must be defined only by the plan")
    facts = {"text": text, "frontmatter": frontmatter}
    for line in text.split("\n"):
        for target in _LINK.findall(line):
            normalized = target.split("#", 1)[0]
            if (
                normalized.startswith(PLANS_PREFIX) and normalized != inputs["plan"]
                and "HISTORICAL_ONLY" not in line and "SUPERSEDED" not in line
            ):
                return fail("PREFLIGHT_AUTHORITY_CONFLICT", "another plan is linked without a historical label")
    if frontmatter["plan_path"] != inputs["plan"]:
        return fail("PREFLIGHT_BINDING_MISMATCH", "recovery entry names a different plan")
    expected_head = inputs["expected_verified_head"]
    recorded_head = None if _null(frontmatter["verified_head"]) else frontmatter["verified_head"]
    if recorded_head != expected_head:
        return fail("PREFLIGHT_BINDING_MISMATCH", "recovery entry verified_head differs from the expected value")
    if plan is None:
        return _not_run("context_authority", refs), facts
    if frontmatter["plan_sha256"] != plan["sha256"]:
        return fail("PREFLIGHT_PLAN_STALE", "recovery entry plan digest differs from the current plan")
    return _check("context_authority", "pass", None, "recovery entry has one current authority bound to this plan", refs), facts


def markdown_links(workspace: Path, documents: Iterable[tuple[str, str]]) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Resolve relative links once; return workspace-relative targets for one Git lookup."""
    targets: list[str] = []
    for relative_document, text in documents:
        base = (workspace / relative_document).parent
        for target in _LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            normalized = target.split("#", 1)[0]
            if not normalized or normalized.startswith(("/", "file:")) or "\\" in normalized:
                return None, {"code": "PREFLIGHT_LINK_INVALID", "message": "a link is absolute or local-only"}
            lexical = Path(os.path.normpath(base / normalized))
            try:
                relative = lexical.relative_to(workspace).as_posix()
            except ValueError:
                return None, {"code": "PREFLIGHT_LINK_INVALID", "message": "a link escapes the workspace"}
            path, failure = _workspace_file(workspace, relative)
            if failure is not None or path is None:
                code = "PREFLIGHT_LINK_INVALID" if failure and failure["status"] == "fail" else "PREFLIGHT_LINK_MISSING"
                return None, {"code": code, "message": "a linked file is missing or unsafe"}
            if not path.is_file():
                return None, {"code": "PREFLIGHT_LINK_MISSING", "message": "a link does not name a regular file"}
            targets.append(relative)
    return sorted(set(targets)), None


def _git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "PAGER": "cat", "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
    })
    return environment


def new_git_budget(*, total_seconds: float = GIT_TOTAL_SECONDS, git: str = "git") -> dict[str, Any]:
    return {"deadline": time.monotonic() + total_seconds, "calls": 0, "git": git}


def run_git(
    workspace: Path, arguments: Sequence[str], budget: dict[str, Any], *,
    call_seconds: float = GIT_CALL_SECONDS, stream_bytes: int = GIT_STREAM_BYTES,
) -> dict[str, Any]:
    """Run one fixed metadata command with bounded time and both streams bounded."""
    remaining = budget["deadline"] - time.monotonic()
    if remaining <= 0:
        return {"status": "unknown", "code": "PREFLIGHT_GIT_TIMEOUT"}
    timeout = min(call_seconds, remaining)
    command = [budget["git"], "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "--no-pager", *arguments]
    budget["calls"] += 1
    try:
        process = subprocess.Popen(
            command, cwd=workspace, env=_git_environment(), shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError:
        return {"status": "unknown", "code": "PREFLIGHT_GIT_UNAVAILABLE"}
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    outcome: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        assert process.stdout is not None and process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                outcome = {"status": "unknown", "code": "PREFLIGHT_GIT_TIMEOUT"}
                break
            for key, _ in selector.select(timeout=left):
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)  # type: ignore[union-attr]
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[key.data].extend(chunk)
                if len(buffers[key.data]) > stream_bytes:
                    outcome = {"status": "unknown", "code": "PREFLIGHT_GIT_OUTPUT_LIMIT"}
                    break
            if outcome is not None:
                break
        if outcome is None:
            try:
                returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                outcome = {"status": "unknown", "code": "PREFLIGHT_GIT_TIMEOUT"}
            else:
                outcome = {"status": "pass", "returncode": returncode, "stdout": bytes(buffers["stdout"])}
    except OSError:
        outcome = {"status": "unknown", "code": "PREFLIGHT_GIT_UNAVAILABLE"}
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()  # type: ignore[union-attr]
        process.stderr.close()  # type: ignore[union-attr]
    return outcome


def _split_z(data: bytes) -> list[str] | None:
    parts = data.split(b"\x00")
    if parts and parts[-1] == b"":
        parts.pop()
    if len(parts) > GIT_MAX_PATHS:
        return None
    return [os.fsdecode(part) for part in parts]


def _status_paths(data: bytes) -> list[str] | None:
    records = _split_z(data)
    if records is None:
        return None
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4 or record[2] != " ":
            return None
        paths.append(record[3:])
        if "R" in record[:2] or "C" in record[:2]:
            index += 1
            if index >= len(records):
                return None
            paths.append(records[index])
        index += 1
    return paths


def collect_git_facts(
    workspace: Path, verified_head: str | None, link_targets: Sequence[str], budget: dict[str, Any],
) -> dict[str, Any]:
    """Collect each Git fact once; every later check reads this immutable result."""
    facts: dict[str, Any] = {}

    def failed(result: Mapping[str, Any]) -> bool:
        return result["status"] != "pass" or result["returncode"] != 0

    top = run_git(workspace, ["rev-parse", "--show-toplevel"], budget)
    if top["status"] != "pass":
        facts["error"] = top["code"]
        return facts
    if top["returncode"] != 0:
        facts["error"] = "PREFLIGHT_GIT_UNAVAILABLE"
        return facts
    try:
        toplevel = Path(os.fsdecode(top["stdout"]).rstrip("\n")).resolve(strict=True)
    except (OSError, RuntimeError):
        facts["error"] = "PREFLIGHT_GIT_UNAVAILABLE"
        return facts
    if toplevel != workspace:
        facts["toplevel_mismatch"] = True
        return facts
    head = run_git(workspace, ["rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"], budget)
    if failed(head):
        facts["error"] = head.get("code", "PREFLIGHT_GIT_UNAVAILABLE")
        return facts
    facts["current_head"] = head["stdout"].decode("ascii", "replace").strip()
    if verified_head is not None:
        exists = run_git(workspace, ["rev-parse", "--verify", "--quiet", "--end-of-options", verified_head + "^{commit}"], budget)
        if exists["status"] != "pass":
            facts["revision_error"] = exists["code"]
        elif exists["returncode"] != 0:
            facts["verified_exists"] = False
        else:
            facts["verified_exists"] = True
            ancestor = run_git(workspace, ["merge-base", "--is-ancestor", verified_head, facts["current_head"]], budget)
            if ancestor["status"] != "pass":
                facts["revision_error"] = ancestor["code"]
            elif ancestor["returncode"] not in {0, 1}:
                facts["revision_error"] = "PREFLIGHT_GIT_UNAVAILABLE"
            else:
                facts["is_ancestor"] = ancestor["returncode"] == 0
                if facts["is_ancestor"]:
                    diff = run_git(
                        workspace,
                        ["diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", verified_head, facts["current_head"], "--"],
                        budget,
                    )
                    if failed(diff):
                        facts["revision_error"] = diff.get("code", "PREFLIGHT_GIT_UNAVAILABLE")
                    else:
                        changed = _split_z(diff["stdout"])
                        if changed is None:
                            facts["revision_error"] = "PREFLIGHT_GIT_OUTPUT_LIMIT"
                        else:
                            facts["changed_paths"] = tuple(changed)
    status = run_git(workspace, ["status", "--porcelain=v1", "-z", "--untracked-files=all"], budget)
    if failed(status):
        facts["status_error"] = status.get("code", "PREFLIGHT_GIT_UNAVAILABLE")
    else:
        dirty = _status_paths(status["stdout"])
        if dirty is None:
            facts["status_error"] = "PREFLIGHT_GIT_OUTPUT_LIMIT"
        else:
            facts["dirty_paths"] = tuple(dirty)
    if link_targets:
        tracked = run_git(workspace, ["ls-files", "-z", "--", *link_targets], budget)
        if failed(tracked):
            facts["tracked_error"] = tracked.get("code", "PREFLIGHT_GIT_UNAVAILABLE")
        else:
            listed = _split_z(tracked["stdout"])
            facts["tracked_error" if listed is None else "tracked_paths"] = (
                "PREFLIGHT_GIT_OUTPUT_LIMIT" if listed is None else frozenset(listed)
            )
    else:
        facts["tracked_paths"] = frozenset()
    return facts


def _allowlisted(path: str, plan: str) -> bool:
    if path in {plan, CONTEXT_FILE}:
        return True
    if not path.startswith(EVIDENCE_PREFIX):
        return False
    parts = path[len(EVIDENCE_PREFIX):].split("/")
    return len(parts) >= 2 and _IDENTIFIER.fullmatch(parts[0]) is not None and all(parts[1:])


def git_checks(
    facts: Mapping[str, Any], inputs: Mapping[str, Any], link_targets: Sequence[str] | None,
    bound_material: Iterable[str],
) -> list[dict[str, object]]:
    """Project collected Git facts into context_links, git_revision, and git_worktree checks."""
    revision_refs, worktree_refs, link_refs = ["git:verified_head..HEAD"], ["git:status"], [CONTEXT_FILE, "git:ls-files"]
    shared_error = facts.get("error")
    if shared_error is not None or facts.get("toplevel_mismatch"):
        if facts.get("toplevel_mismatch"):
            shared = ("fail", "PREFLIGHT_BINDING_MISMATCH", "workspace root is not the Git worktree root")
        else:
            shared = (CODE_STATUS[shared_error], shared_error, "Git metadata is unavailable")
        return [
            _check("context_links", *shared, link_refs) if link_targets is not None else _not_run("context_links", link_refs),
            _check("git_revision", *shared, revision_refs),
            _check("git_worktree", *shared, worktree_refs),
        ]
    checks: list[dict[str, object]] = []
    if link_targets is None:
        checks.append(_not_run("context_links", link_refs))
    elif "tracked_error" in facts:
        code = facts["tracked_error"]
        checks.append(_check("context_links", CODE_STATUS[code], code, "tracked link targets could not be listed", link_refs))
    elif set(link_targets) - set(facts["tracked_paths"]):
        checks.append(_check("context_links", "fail", "PREFLIGHT_UNTRACKED_DEPENDENCY", "a linked file is not tracked by Git", link_refs))
    else:
        checks.append(_check("context_links", "pass", None, "all relative links resolve to tracked workspace files", link_refs))

    verified = inputs["expected_verified_head"]
    if verified is None:
        checks.append(_check("git_revision", "unknown", "PREFLIGHT_REVISION_UNVERIFIED", "no complete verification commit is recorded", revision_refs))
    elif "revision_error" in facts:
        code = facts["revision_error"]
        checks.append(_check("git_revision", CODE_STATUS[code], code, "revision ancestry could not be established", revision_refs))
    elif not facts.get("verified_exists"):
        checks.append(_check("git_revision", "stale", "PREFLIGHT_REVISION_STALE", "verified_head is not a commit in this repository", revision_refs))
    elif not facts.get("is_ancestor"):
        checks.append(_check("git_revision", "stale", "PREFLIGHT_REVISION_STALE", "verified_head is not an ancestor of HEAD", revision_refs))
    elif any(not _allowlisted(path, inputs["plan"]) for path in facts["changed_paths"]):
        checks.append(_check("git_revision", "stale", "PREFLIGHT_REVISION_STALE", "non-allowlisted files changed after verified_head", revision_refs))
    else:
        checks.append(_check("git_revision", "pass", None, "verified_head is an ancestor and later changes are allowlisted", revision_refs))

    if "status_error" in facts:
        code = facts["status_error"]
        checks.append(_check("git_worktree", CODE_STATUS[code], code, "working tree status is unavailable", worktree_refs))
    elif set(facts["dirty_paths"]) - set(bound_material):
        checks.append(_check("git_worktree", "unknown", "PREFLIGHT_WORKTREE_DIRTY", "uncommitted or untracked files may affect preflight", worktree_refs))
    else:
        checks.append(_check("git_worktree", "pass", None, "working tree has no unbound uncommitted changes", worktree_refs))
    return checks


_DOCUMENT_FIELDS = {
    CHECKLIST_SCHEMA: frozenset({"schema", "task_id", "handoff_sha256", "plan_sha256", "facts"}),
    READBACK_SCHEMA: frozenset({"schema", "task_id", "handoff_sha256", "plan_sha256", "checklist_sha256", "facts"}),
}
_FACT_FIELDS = frozenset({"fact_id", "category", "value", "source_ref"})


def _canonical_text(value: object) -> bool:
    return (
        isinstance(value, str) and bool(value) and "\r" not in value
        and unicodedata.is_normalized("NFC", value)
    )


def validate_recovery_document(value: object, *, schema: str) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """Validate one checklist/readback without trimming, folding, or rewriting any text."""
    fields = _DOCUMENT_FIELDS[schema]
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != schema:
        return None, ("PREFLIGHT_INPUT_INVALID", "recovery document fields or schema are not exact")
    if not isinstance(value.get("task_id"), str) or _IDENTIFIER.fullmatch(value["task_id"]) is None:
        return None, ("PREFLIGHT_INPUT_INVALID", "recovery document task_id is invalid")
    for field in fields & {"handoff_sha256", "plan_sha256", "checklist_sha256"}:
        if not isinstance(value.get(field), str) or _SHA256.fullmatch(value[field]) is None:
            return None, ("PREFLIGHT_INPUT_INVALID", "recovery document digest field is invalid")
    facts = value.get("facts")
    if not isinstance(facts, list) or not facts:
        return None, ("PREFLIGHT_INPUT_INVALID", "recovery document has no facts array")
    if len(facts) > MAX_FACTS:
        return None, ("PREFLIGHT_OVERSIZE", "recovery document has more than 64 facts")
    by_id: dict[str, tuple[str, str, str]] = {}
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != _FACT_FIELDS:
            return None, ("PREFLIGHT_INPUT_INVALID", "a fact does not have exactly the required fields")
        fact_id, category = fact["fact_id"], fact["category"]
        if not isinstance(fact_id, str) or _IDENTIFIER.fullmatch(fact_id) is None or category not in CATEGORIES:
            return None, ("PREFLIGHT_INPUT_INVALID", "a fact identifier or category is invalid")
        if not _canonical_text(fact["value"]) or not _canonical_text(fact["source_ref"]):
            return None, ("PREFLIGHT_INPUT_INVALID", "a fact value is empty, non-NFC, or not LF-only")
        if fact_id in by_id:
            return None, ("PREFLIGHT_INPUT_INVALID", "a fact identifier is duplicated")
        by_id[fact_id] = (category, fact["value"], fact["source_ref"])
    if {entry[0] for entry in by_id.values()} != set(CATEGORIES):
        return None, ("PREFLIGHT_INPUT_INVALID", "a required fact category is missing")
    canonical = dict(value)
    canonical["facts"] = sorted((dict(fact) for fact in facts), key=lambda item: item["fact_id"])
    normalized = {key: value[key] for key in fields - {"facts", "schema"}}
    normalized.update({"facts": by_id, "canonical_sha256": canonical_sha256(canonical)})
    return normalized, None


def _read_recovery_document(workspace: Path, raw: str, *, schema: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    outcome = _read_workspace_file(workspace, raw)
    if outcome["status"] != "pass":
        return outcome, None
    try:
        parsed = strict_json_loads(outcome["data"])
    except (UnicodeError, ValueError, RecursionError):
        return {"status": "fail", "code": "PREFLIGHT_INPUT_INVALID", "message": "recovery document is not strict UTF-8 JSON", "bytes": len(outcome["data"])}, None
    document, error = validate_recovery_document(parsed, schema=schema)
    if error is not None or document is None:
        code, message = error or ("PREFLIGHT_INPUT_INVALID", "recovery document is invalid")
        return {"status": CODE_STATUS[code], "code": code, "message": message, "bytes": len(outcome["data"])}, None
    return {"status": "pass", "bytes": len(outcome["data"])}, document


def recovery_checks(
    workspace: Path, inputs: Mapping[str, Any], plan: Mapping[str, Any] | None, stats: dict[str, int],
) -> tuple[list[dict[str, object]], dict[str, Any] | None]:
    """Material integrity first; only an exact readback may establish information recovery."""
    checks: list[dict[str, object]] = []
    if inputs.get("handoff_file") is None:
        return checks, None
    handoff_refs, checklist_refs = ["handoff_file"], ["recovery_checklist", "handoff_file", "plan"]
    readback_refs, compare_refs = ["recovery_readback", "recovery_checklist"], ["recovery_checklist", "recovery_readback"]
    handoff = _read_workspace_file(workspace, inputs["handoff_file"])
    handoff_sha = None
    if handoff["status"] != "pass":
        checks.append(_from_read("handoff_material", handoff, handoff_refs))
    elif handoff["sha256"] != inputs["expected_handoff_sha256"]:
        checks.append(_check("handoff_material", "fail", "PREFLIGHT_DIGEST_MISMATCH", "handoff file digest differs from the expected digest", handoff_refs))
    else:
        stats["input_bytes"] += len(handoff["data"])
        handoff_sha = handoff["sha256"]
        checks.append(_check("handoff_material", "pass", None, "handoff file digest matches", handoff_refs))

    outcome, checklist = _read_recovery_document(workspace, inputs["recovery_checklist"], schema=CHECKLIST_SCHEMA)
    stats["input_bytes"] += int(outcome.get("bytes", 0))
    if checklist is None:
        checks.append(_from_read("recovery_checklist", outcome, checklist_refs))
    elif checklist["canonical_sha256"] != inputs["expected_checklist_sha256"]:
        checks.append(_check("recovery_checklist", "fail", "PREFLIGHT_DIGEST_MISMATCH", "checklist canonical digest differs from the expected digest", checklist_refs))
        checklist = None
    elif handoff_sha is None or plan is None:
        checks.append(_not_run("recovery_checklist", checklist_refs))
        checklist = None
    elif (checklist["task_id"], checklist["handoff_sha256"], checklist["plan_sha256"]) != (inputs["task_id"], handoff_sha, plan["sha256"]):
        checks.append(_check("recovery_checklist", "fail", "PREFLIGHT_BINDING_MISMATCH", "checklist is not bound to this task, handoff, and plan", checklist_refs))
        checklist = None
    else:
        checks.append(_check("recovery_checklist", "pass", None, "checklist structure, digest, and bindings match", checklist_refs))

    if inputs.get("recovery_readback") is None:
        return checks, checklist
    outcome, readback = _read_recovery_document(workspace, inputs["recovery_readback"], schema=READBACK_SCHEMA)
    stats["input_bytes"] += int(outcome.get("bytes", 0))
    if readback is None:
        checks.append(_from_read("recovery_readback", outcome, readback_refs))
    elif checklist is None:
        checks.append(_not_run("recovery_readback", readback_refs))
        readback = None
    elif (readback["task_id"], readback["handoff_sha256"], readback["plan_sha256"], readback["checklist_sha256"]) != (
        checklist["task_id"], checklist["handoff_sha256"], checklist["plan_sha256"], checklist["canonical_sha256"],
    ):
        checks.append(_check("recovery_readback", "fail", "PREFLIGHT_BINDING_MISMATCH", "readback is not bound to this checklist", readback_refs))
        readback = None
    else:
        checks.append(_check("recovery_readback", "pass", None, "readback structure and bindings match", readback_refs))
    if readback is None or checklist is None:
        checks.append(_not_run("readback_comparison", compare_refs))
    elif readback["facts"] != checklist["facts"]:
        checks.append(_check("readback_comparison", "fail", "PREFLIGHT_READBACK_MISMATCH", "readback facts differ from the checklist", compare_refs))
    else:
        checks.append(_check("readback_comparison", "pass", None, "every checklist fact was read back exactly", compare_refs))
    return checks, checklist


def strict_contract_check(inputs: Mapping[str, Any], package: Mapping[str, Any]) -> tuple[dict[str, object], dict[str, Any] | None]:
    refs = ["context:task-contract.json", "context:events.jsonl"]
    given = Path(inputs["context_root"])
    try:
        base = given.resolve(strict=True)
        if base != given:
            return _check("strict_contract", "fail", "PREFLIGHT_SYMLINK_REJECTED", "context root is not canonical", refs), None
        handoff = importlib.import_module("managing_long_task_context.handoff")
        capture = handoff._capture_prepare_inputs(inputs["task_id"], base_dir=base)
    except Exception:
        return _check("strict_contract", "unknown", "PREFLIGHT_CONTRACT_UNAVAILABLE", "sealed contract or event log is unavailable", refs), None
    capabilities = capture["contract"].get("required_capabilities")
    if not isinstance(capabilities, list) or CAPABILITY not in capabilities:
        return _check("strict_contract", "fail", "PREFLIGHT_CAPABILITY_MISSING", "sealed contract does not enable short-session-handoff/v1", refs), None
    return _check("strict_contract", "pass", None, "sealed contract enables short-session-handoff/v1", refs), {"base": base, "capture": capture, "handoff": handoff}


def strict_handoff_state_check(
    stage: str, inputs: Mapping[str, Any], workspace: Path, package: Mapping[str, Any],
    contract: Mapping[str, Any], handoff_verifier: Any,
) -> tuple[dict[str, object], dict[str, Any] | None]:
    refs = ["context:handoff-record", "context:events.jsonl", "host:handoff_verifier"]
    runtime, handoff, base = package["runtime"], contract["handoff"], contract["base"]
    task_id, handoff_id = inputs["task_id"], inputs["handoff_id"]
    common = {"base_dir": base, "workspace_root": workspace, "package_root": package["root"], "handoff_id": handoff_id}

    def verdict(result: Mapping[str, Any]) -> dict[str, object]:
        status = result.get("check_status")
        if status == "pass":
            return _check("strict_handoff_state", "pass", None, "current v1 verification passed with a trusted host verifier", refs)
        if handoff_verifier is None:
            return _check("strict_handoff_state", "unknown", "PREFLIGHT_VERIFIER_UNAVAILABLE", "no trusted host handoff verifier was supplied", refs)
        if status == "fail":
            return _check("strict_handoff_state", "fail", "PREFLIGHT_VERIFIER_REJECTED", "the host verifier rejected current handoff evidence", refs)
        return _check("strict_handoff_state", "unknown", "PREFLIGHT_VERIFIER_UNAVAILABLE", "current handoff verification is unknown", refs)

    if stage == "status":
        try:
            result = runtime.handoff_status(task_id, handoff_verifier=handoff_verifier, **common)
        except Exception:
            return _check("strict_handoff_state", "unknown", "PREFLIGHT_HANDOFF_STATE_UNAVAILABLE", "handoff status could not be read", refs), None
        return verdict(result), {"check_status": result.get("check_status"), "commit_status": result.get("commit_status"),
                                 "controller_generation": result.get("controller_generation")}
    try:
        raw, digest = runtime._read_handoff_json(runtime._paths(task_id, base)["handoff_root"] / f"{handoff_id}.json")
        record, record_error = handoff.validate_record(raw)
        projection, projection_error = handoff._control_projection(contract["capture"]["events"], task_id=task_id)
    except Exception:
        return _check("strict_handoff_state", "unknown", "PREFLIGHT_HANDOFF_STATE_UNAVAILABLE", "prepared handoff record is unavailable", refs), None
    if record_error is not None or record is None or projection_error is not None:
        return _check("strict_handoff_state", "unknown", "PREFLIGHT_HANDOFF_STATE_UNAVAILABLE", "prepared handoff record or events are invalid", refs), None
    pending = projection.get("pending")
    if not isinstance(pending, Mapping) or pending.get("handoff_id") != handoff_id or pending.get("record_sha256") != digest:
        return _check("strict_handoff_state", "fail", "PREFLIGHT_HANDOFF_NOT_PREPARED", "handoff is not the currently prepared record", refs), None
    if (
        record["task_id"], record["handoff_id"], record["workspace_root"], record["package_manifest_sha256"],
    ) != (task_id, handoff_id, str(workspace), package["manifest_sha256"]):
        return _check("strict_handoff_state", "fail", "PREFLIGHT_BINDING_MISMATCH", "prepared record is bound to another workspace or package", refs), None
    if handoff_verifier is None:
        return _check("strict_handoff_state", "unknown", "PREFLIGHT_VERIFIER_UNAVAILABLE", "no trusted host handoff verifier was supplied", refs), None
    try:
        result = runtime.validate_handoff(task_id, handoff_verifier=handoff_verifier, **common)
    except Exception:
        return _check("strict_handoff_state", "unknown", "PREFLIGHT_VERIFIER_UNAVAILABLE", "current handoff verification failed to run", refs), None
    return verdict(result), None


def _aggregate(statuses: Sequence[str]) -> str:
    if "fail" in statuses:
        return "fail"
    if any(status != "pass" for status in statuses):
        return "unknown"
    return "pass"


def migration_outcome(mode: str | None, stage: str | None, checks: Sequence[Mapping[str, object]], state: Mapping[str, Any] | None) -> dict[str, object]:
    by_name = {str(check["name"]): check for check in checks}
    comparison = by_name.get("readback_comparison")
    information = str(comparison["status"]) if comparison and comparison["status"] in {"pass", "fail"} else "unknown"
    control: dict[str, object] = {"status": "unknown", "commit_status": "not_attempted", "controller_generation": None}
    if mode == "strict_protocol" and stage == "status":
        commit = state.get("commit_status") if state else "unknown"
        control["commit_status"] = commit if commit in {"confirmed_committed", "confirmed_not_committed"} else "unknown"
        if commit == "confirmed_committed":
            control["controller_generation"] = state.get("controller_generation") if state else None
            control["status"] = "pass" if state and state.get("check_status") == "pass" else "unknown"
        elif commit == "confirmed_not_committed":
            control["status"] = "fail"
    return {
        "information_recovery": {
            "status": information,
            "evidence_refs": ["handoff_file", "recovery_checklist", "recovery_readback"] if information != "unknown" else [],
        },
        "control_transfer": control,
        "source_retirement": {"status": "not_allowed", "archive_allowed": False, "evidence_refs": []},
    }


def emit_report(
    inputs: Mapping[str, Any] | None, checks: Sequence[dict[str, object]], *, state: Mapping[str, Any] | None,
    checklist: Mapping[str, Any] | None, revisions: Mapping[str, Any], stats: Mapping[str, int],
) -> tuple[dict[str, object], int]:
    mode = inputs["mode"] if inputs else None
    stage = inputs["stage"] if inputs else None
    statuses = [str(check["status"]) for check in checks]
    preflight_status = _aggregate(statuses)
    material = [str(check["status"]) for check in checks if check["name"] in {"handoff_material", "recovery_checklist", "recovery_readback"}]
    blocking = [{"check": check["name"], "status": check["status"], "code": check["code"]} for check in checks if check["status"] != "pass"]
    primary = next((item for item in blocking if item["code"] != "PREFLIGHT_DEPENDENCY_NOT_RUN"), blocking[0] if blocking else None)
    coverage = None
    if checklist is not None:
        categories = {category: 0 for category in CATEGORIES}
        for category, _, _ in checklist["facts"].values():
            categories[category] += 1
        coverage = {"fact_count": len(checklist["facts"]), "categories": categories}
    report: dict[str, object] = {
        "schema": SCHEMA,
        "migration_mode": mode,
        "stage": stage,
        "preflight_status": preflight_status,
        "material_integrity": _aggregate(material) if material else "not_run",
        "migration_outcome": migration_outcome(mode, stage, checks, state),
        "archive_allowed": False,
        "checks": list(checks),
        "blocking_reasons": blocking,
        "next_readonly_action": NEXT_READONLY_ACTION[str(primary["code"])] if primary else PASS_ACTION[(str(mode), str(stage))],
        "recovery_coverage": coverage,
        "revisions": dict(revisions),
        "stats": dict(stats),
    }
    return report, {"pass": 0, "fail": 1, "unknown": 2}[preflight_status]


def _relative_material(workspace: Path, inputs: Mapping[str, Any]) -> list[str]:
    paths = []
    for name in ("handoff_file", "recovery_checklist", "recovery_readback"):
        if inputs.get(name) is not None:
            try:
                paths.append(Path(inputs[name]).relative_to(workspace).as_posix())
            except ValueError:
                continue
    return paths


def run_preflight(argv: Iterable[str] | None, *, handoff_verifier: Any = None, git: str = "git") -> tuple[dict[str, object], int]:
    """Evaluate the selected mode and stage; a host may inject its trusted verifier."""
    stats = {"git_calls": 0, "input_bytes": 0}
    revisions: dict[str, Any] = {"current_head": None, "verified_head": None}
    inputs, input_check = validate_inputs(parse_args(argv))
    checks = [input_check]
    if inputs is None:
        return emit_report(None, checks, state=None, checklist=None, revisions=revisions, stats=stats)
    revisions["verified_head"] = inputs["expected_verified_head"]
    downstream = [
        "plan_digest", "context_authority", "context_links", "package_binding", "git_revision", "git_worktree",
        *(["handoff_material", "recovery_checklist"] if inputs.get("handoff_file") else []),
        *(["recovery_readback", "readback_comparison"] if inputs.get("recovery_readback") else []),
        *(["strict_contract"] if inputs["mode"] == "strict_protocol" else []),
        *(["strict_handoff_state"] if inputs["mode"] == "strict_protocol" and inputs["stage"] != "prepare" else []),
    ]
    state: dict[str, Any] | None = None
    checklist: dict[str, Any] | None = None
    try:
        package_check, package = verify_loaded_package_identity(inputs["package_root"])
        checks.append(package_check)
        if package is None:
            checks.extend(_not_run(name) for name in downstream)
            return emit_report(inputs, checks, state=None, checklist=None, revisions=revisions, stats=stats)
        given = Path(inputs["workspace_root"])
        try:
            workspace = given.resolve(strict=True)
        except (OSError, RuntimeError):
            workspace = None
        if workspace is None or workspace != given or not workspace.is_dir():
            code = "PREFLIGHT_FILE_UNAVAILABLE" if workspace is None else "PREFLIGHT_SYMLINK_REJECTED"
            checks.append(_check("plan_digest", CODE_STATUS[code], code, "workspace root is unavailable or not canonical", ["workspace"]))
            checks.extend(_not_run(name) for name in downstream[1:])
            return emit_report(inputs, checks, state=None, checklist=None, revisions=revisions, stats=stats)
        plan_check, plan = check_plan_digest(workspace, inputs)
        context_check, context = check_context_authority(workspace, inputs, plan)
        checks.extend((plan_check, context_check))
        documents = ([(CONTEXT_FILE, context["text"])] if context else []) + ([(inputs["plan"], plan["text"])] if plan else [])
        stats["input_bytes"] += sum(len(text.encode("utf-8")) for _, text in documents)
        link_targets, link_failure = markdown_links(workspace, documents) if context else (None, None)
        budget = new_git_budget(git=git)
        git_facts = collect_git_facts(workspace, inputs["expected_verified_head"], link_targets or [], budget)
        stats["git_calls"] = budget["calls"]
        revisions["current_head"] = git_facts.get("current_head")
        links, revision, worktree = git_checks(git_facts, inputs, link_targets if link_failure is None else [], _relative_material(workspace, inputs))
        if link_failure is not None:
            links = _check("context_links", "fail", link_failure["code"], link_failure["message"], [CONTEXT_FILE])
        if context is None:
            package_binding = _not_run("package_binding", [CONTEXT_FILE, "package:skill-manifest.json"])
        else:
            recorded = context["frontmatter"]["package_manifest_sha256"]
            refs = [CONTEXT_FILE, "package:skill-manifest.json"]
            if _null(recorded):
                package_binding = _check("package_binding", "unknown", "PREFLIGHT_PACKAGE_SHA_MISSING", "recovery entry has no verified package digest", refs)
            elif _SHA256.fullmatch(recorded) is None:
                package_binding = _check("package_binding", "fail", "PREFLIGHT_INPUT_INVALID", "recovery entry package digest is invalid", refs)
            elif recorded != package["manifest_sha256"]:
                package_binding = _check("package_binding", "stale", "PREFLIGHT_PACKAGE_STALE", "loaded package differs from the verified package", refs)
            else:
                package_binding = _check("package_binding", "pass", None, "loaded package is the verified package", refs)
        checks.extend((links, package_binding, revision, worktree))
        material_checks, checklist = recovery_checks(workspace, inputs, plan, stats)
        checks.extend(material_checks)
        if inputs["mode"] == "strict_protocol":
            contract_check, contract = strict_contract_check(inputs, package)
            checks.append(contract_check)
            if inputs["stage"] != "prepare":
                if contract is None:
                    checks.append(_not_run("strict_handoff_state"))
                else:
                    state_check, state = strict_handoff_state_check(inputs["stage"], inputs, workspace, package, contract, handoff_verifier)
                    checks.append(state_check)
    except Exception:
        present = {check["name"] for check in checks}
        checks.append(_check("unexpected", "unknown", "PREFLIGHT_UNEXPECTED_ERROR", "preflight could not complete deterministically"))
        checks.extend(_not_run(name) for name in downstream if name not in present)
    return emit_report(inputs, checks, state=state, checklist=checklist, revisions=revisions, stats=stats)


def main(argv: Iterable[str] | None = None) -> int:
    report, code = run_preflight(argv)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
