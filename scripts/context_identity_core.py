"""Shared, standard-library-only identity and workspace binding primitives.

This module deliberately does not import either Context implementation.  It is
copied into both distributable skills and into Context Strict's package so a
diagnostic never gets its answer from an incidental development checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SCHEMA = 1
BINDING_FILE = "context-binding.json"
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
STATUSES = {"pass", "fail", "unknown", "not_run"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(name: str, status: str, code: str | None, message: str) -> dict[str, object]:
    if status not in STATUSES:
        raise ValueError(f"invalid diagnostic status: {status}")
    return {"name": name, "status": status, "code": code, "message": message}


def _report(
    *, mode: str, scope: str, checks: Iterable[Mapping[str, object]], identity: Mapping[str, object] | None = None,
    binding: Mapping[str, object] | None = None, full_verification: str = "not_run",
) -> dict[str, object]:
    checks_list = [dict(item) for item in checks]
    considered = [str(item["status"]) for item in checks_list if item.get("status") != "not_run"]
    status = "fail" if "fail" in considered else "unknown" if "unknown" in considered else "pass"
    codes = sorted({str(item["code"]) for item in checks_list if item.get("code")})
    next_action = None
    if status == "fail":
        next_action = "Correct the reported mismatch; do not resume until identity passes."
    elif status == "unknown":
        next_action = "Resolve the unavailable identity evidence explicitly; do not resume."
    return {
        "schema": SCHEMA,
        "mode": mode,
        "scope": scope,
        "status": status,
        "checked_at": utc_now(),
        "full_verification": full_verification,
        "identity": dict(identity) if identity is not None else None,
        "binding": dict(binding) if binding is not None else None,
        "checks": checks_list,
        "codes": codes,
        "next_action": next_action,
    }


def input_failure(mode: str, scope: str, message: str) -> dict[str, object]:
    return _report(mode=mode, scope=scope, checks=[_check("input", "fail", "INPUT_INVALID", message)])


def binding_missing_report(message: str = "task has no explicit binding") -> dict[str, object]:
    return _report(mode="identity", scope="task", checks=[_check("binding", "unknown", "BINDING_MISSING", message)])


def _absolute_existing(raw: str | Path, *, kind: str) -> tuple[Path | None, dict[str, object] | None]:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return None, _check(kind, "fail", "INPUT_INVALID", f"{kind} must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, _check(kind, "unknown", "READ_FAILED", f"cannot resolve {kind}")
    if not resolved.is_dir():
        return None, _check(kind, "fail", "INPUT_INVALID", f"{kind} must be an existing directory")
    return resolved, None


def normalize_workspace(raw: str | Path) -> tuple[Path | None, dict[str, object] | None]:
    root, failure = _absolute_existing(raw, kind="workspace_root")
    if failure is not None or root is None:
        return root, failure
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True, capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, _check("workspace", "unknown", "READ_FAILED", "cannot inspect Git workspace identity")
    if completed.returncode != 0:
        if "not a git repository" in completed.stderr.lower():
            return root, None  # Explicit existing non-Git directories are supported.
        return None, _check("workspace", "unknown", "READ_FAILED", "Git workspace inspection failed")
    try:
        git_root = Path(completed.stdout.strip()).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, _check("workspace", "unknown", "READ_FAILED", "cannot resolve Git workspace root")
    if git_root != root:
        return None, _check("workspace", "fail", "WORKSPACE_MISMATCH", "workspace_root is not the Git worktree root")
    return root, None


def _valid_task_id(task_id: str) -> bool:
    return isinstance(task_id, str) and TASK_ID.fullmatch(task_id) is not None and task_id not in {".", ".."}


def _valid_utc(value: object) -> bool:
    if not isinstance(value, str) or not (value.endswith("Z") or value.endswith("+00:00")):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _binding_is_valid(value: object) -> bool:
    required = {"schema", "task_id", "skill_name", "expected_manifest_sha256", "workspace_root", "context_root", "created_at"}
    return (
        isinstance(value, dict) and set(value) == required and type(value.get("schema")) is int
        and value.get("schema") == SCHEMA and all(isinstance(value.get(key), str) for key in required - {"schema"})
        and _valid_utc(value.get("created_at"))
    )


def _task_path(context_root: Path, task_id: str) -> tuple[Path | None, dict[str, object] | None]:
    if not _valid_task_id(task_id):
        return None, _check("task", "fail", "INPUT_INVALID", "task_id is invalid")
    lexical = context_root / task_id
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, _check("storage", "unknown", "READ_FAILED", "cannot resolve task directory")
    if not resolved.is_dir():
        return None, _check("storage", "unknown", "BINDING_MISSING", "task directory does not exist")
    try:
        resolved.relative_to(context_root)
    except ValueError:
        return None, _check("storage", "fail", "STORAGE_MISMATCH", "task directory escapes context_root")
    return resolved, None


def _manifest(package_root: Path) -> tuple[dict[str, object] | None, str | None, dict[str, object] | None]:
    path = package_root / "skill-manifest.json"
    try:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None, None, _check("package_manifest", "unknown", "RUNTIME_UNVERIFIED", "skill-manifest.json is missing; build a package first")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, _check("package_manifest", "unknown", "READ_FAILED", "cannot read package manifest")
    if not isinstance(value, dict) or not isinstance(value.get("skill_name"), str) or not isinstance(value.get("skill_version"), str):
        return None, None, _check("package_manifest", "unknown", "READ_FAILED", "package manifest has no usable identity")
    return value, digest, None


def _binding_file(task_dir: Path) -> tuple[Path | None, dict[str, object] | None]:
    """Return a binding path only when it cannot escape the real task directory."""
    candidate = task_dir / BINDING_FILE
    if not candidate.exists() and not candidate.is_symlink():
        return candidate, None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(task_dir)
    except (OSError, RuntimeError, ValueError):
        return None, _check("storage", "fail", "STORAGE_MISMATCH", "binding file escapes task directory")
    if resolved != candidate:
        return None, _check("storage", "fail", "STORAGE_MISMATCH", "binding file must not be a symlink")
    return candidate, None


def package_identity(package_root: str | Path) -> tuple[Path | None, dict[str, object] | None, str | None, dict[str, object] | None]:
    root, failure = _absolute_existing(package_root, kind="package_root")
    if failure is not None or root is None:
        return root, None, None, failure
    manifest, digest, failure = _manifest(root)
    return root, manifest, digest, failure


def _identity_value(
    *, package_root: Path | None, manifest: Mapping[str, object] | None, actual_hash: str | None,
    runtime_paths: Iterable[str | Path], loaded_manifest_sha256: str | None, capabilities: Iterable[str],
) -> dict[str, object]:
    paths = [str(Path(item).resolve()) for item in runtime_paths]
    return {
        "skill_name": manifest.get("skill_name") if manifest else None,
        "skill_version": manifest.get("skill_version") if manifest else None,
        "package_root": str(package_root) if package_root else None,
        "runtime_path": paths[0] if paths else None,
        "process_id": os.getpid(),
        "observation_source": "current_process",
        "expected_manifest_sha256": None,
        "actual_manifest_sha256": actual_hash,
        "loaded_manifest_sha256": loaded_manifest_sha256,
        "capabilities": sorted(str(item) for item in capabilities),
    }


def identity_diagnostic(
    *, package_root: str | Path, runtime_paths: Iterable[str | Path], loaded_manifest_sha256: str | None,
    capabilities: Iterable[str] = (), binding_context_root: str | Path | None = None,
    workspace_root: str | Path | None = None, task_id: str | None = None,
) -> dict[str, object]:
    """Read only manifest/binding/process identity; never scans a package or history."""
    task_scope = binding_context_root is not None or workspace_root is not None or task_id is not None
    if task_scope and (binding_context_root is None or workspace_root is None or task_id is None):
        return input_failure("identity", "task", "context_root, workspace_root and task_id must be supplied together")
    root, manifest, actual_hash, manifest_failure = package_identity(package_root)
    identity = _identity_value(
        package_root=root, manifest=manifest, actual_hash=actual_hash, runtime_paths=runtime_paths,
        loaded_manifest_sha256=loaded_manifest_sha256, capabilities=capabilities,
    )
    checks: list[dict[str, object]] = []
    if manifest_failure is not None:
        checks.append(manifest_failure)
    else:
        checks.append(_check("package_manifest", "pass", None, "package manifest was read"))
    if root is not None:
        outside = []
        for raw_path in runtime_paths:
            try:
                Path(raw_path).resolve().relative_to(root)
            except (OSError, RuntimeError, ValueError):
                outside.append(str(raw_path))
        if outside:
            checks.append(_check("runtime_path", "fail", "RUNTIME_PATH_MISMATCH", "loaded runtime path is outside package_root"))
        elif loaded_manifest_sha256 is None:
            checks.append(_check("runtime_baseline", "unknown", "RUNTIME_UNVERIFIED", "process loading baseline is unavailable"))
        elif actual_hash is None:
            checks.append(_check("runtime_baseline", "unknown", "RUNTIME_UNVERIFIED", "current package manifest is unavailable"))
        elif loaded_manifest_sha256 != actual_hash:
            checks.append(_check("runtime_baseline", "fail", "PACKAGE_IDENTITY_MISMATCH", "manifest changed after this process loaded"))
        else:
            checks.append(_check("runtime_baseline", "pass", None, "loaded manifest matches current package manifest"))
    if not task_scope:
        checks.extend([
            _check("binding", "not_run", None, "no task identity was requested"),
            _check("full_verification", "not_run", None, "identity mode does not scan package files"),
            _check("smoke", "not_run", None, "identity mode does not run smoke tests"),
        ])
        return _report(mode="identity", scope="runtime", checks=checks, identity=identity)

    context_root, context_failure = _absolute_existing(binding_context_root, kind="context_root")
    workspace, workspace_failure = normalize_workspace(workspace_root)
    if context_failure is not None:
        checks.append(context_failure)
        binding = None
    elif workspace_failure is not None:
        checks.append(workspace_failure)
        binding = None
    elif context_root is None or workspace is None:
        checks.append(_check("binding", "unknown", "READ_FAILED", "cannot resolve binding inputs"))
        binding = None
    else:
        task_dir, task_failure = _task_path(context_root, task_id)
        if task_failure is not None or task_dir is None:
            checks.append(task_failure or _check("binding", "unknown", "READ_FAILED", "task path unavailable"))
            binding = None
        else:
            binding_path, binding_path_failure = _binding_file(task_dir)
            if binding_path_failure is not None or binding_path is None:
                checks.append(binding_path_failure or _check("binding", "unknown", "READ_FAILED", "binding path unavailable"))
                binding = None
            else:
                try:
                    binding_value = json.loads(binding_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    checks.append(_check("binding", "unknown", "BINDING_MISSING", "task has no explicit binding"))
                    binding = None
                except (OSError, UnicodeError, json.JSONDecodeError):
                    checks.append(_check("binding", "unknown", "BINDING_INVALID", "binding cannot be read as valid JSON"))
                    binding = None
                else:
                    binding = binding_value if isinstance(binding_value, dict) else None
                    if not _binding_is_valid(binding):
                        checks.append(_check("binding", "unknown", "BINDING_INVALID", "binding fields are invalid"))
                        binding = None
                    elif binding["task_id"] != task_id:
                        checks.append(_check("binding", "fail", "BINDING_CONFLICT", "binding task_id differs"))
                    elif binding["workspace_root"] != str(workspace):
                        checks.append(_check("workspace", "fail", "WORKSPACE_MISMATCH", "binding workspace_root differs"))
                    elif binding["context_root"] != str(context_root):
                        checks.append(_check("storage", "fail", "STORAGE_MISMATCH", "binding context_root differs"))
                    elif manifest is None or actual_hash is None:
                        checks.append(_check("package_identity", "unknown", "RUNTIME_UNVERIFIED", "package identity is unavailable"))
                    elif binding["expected_manifest_sha256"] != actual_hash or binding["skill_name"] != manifest.get("skill_name"):
                        checks.append(_check("package_identity", "fail", "PACKAGE_IDENTITY_MISMATCH", "binding expects a different package identity"))
                    else:
                        identity["expected_manifest_sha256"] = binding["expected_manifest_sha256"]
                        checks.append(_check("binding", "pass", None, "binding matches supplied task and workspace"))
    checks.extend([
        _check("full_verification", "not_run", None, "identity mode does not scan package files"),
        _check("smoke", "not_run", None, "identity mode does not run smoke tests"),
    ])
    return _report(mode="identity", scope="task", checks=checks, identity=identity, binding=binding)


def init_binding(
    *, package_root: str | Path, expected_manifest_sha256: str, context_root: str | Path,
    workspace_root: str | Path, task_id: str,
) -> dict[str, object]:
    if not isinstance(expected_manifest_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None:
        return input_failure("init", "task", "expected_manifest_sha256 must be a lowercase SHA-256")
    root, manifest, actual_hash, manifest_failure = package_identity(package_root)
    checks: list[dict[str, object]] = [manifest_failure] if manifest_failure is not None else []
    context, context_failure = _absolute_existing(context_root, kind="context_root")
    workspace, workspace_failure = normalize_workspace(workspace_root)
    for failure in (context_failure, workspace_failure):
        if failure is not None:
            checks.append(failure)
    if manifest is None or actual_hash is None:
        return _report(mode="init", scope="task", checks=checks or [_check("package_manifest", "unknown", "RUNTIME_UNVERIFIED", "package is unverified")])
    if actual_hash != expected_manifest_sha256:
        checks.append(_check("package_identity", "fail", "PACKAGE_IDENTITY_MISMATCH", "expected manifest hash differs from package"))
        return _report(mode="init", scope="task", checks=checks)
    if context is None or workspace is None:
        return _report(mode="init", scope="task", checks=checks)
    task_dir, task_failure = _task_path(context, task_id)
    if task_failure is not None or task_dir is None:
        return _report(mode="init", scope="task", checks=checks + [task_failure or _check("binding", "unknown", "READ_FAILED", "task unavailable")])
    binding: dict[str, object] = {
        "schema": SCHEMA, "task_id": task_id, "skill_name": manifest["skill_name"],
        "expected_manifest_sha256": expected_manifest_sha256, "workspace_root": str(workspace),
        "context_root": str(context), "created_at": utc_now(),
    }
    target, target_failure = _binding_file(task_dir)
    if target_failure is not None or target is None:
        return _report(mode="init", scope="task", checks=checks + [target_failure or _check("binding", "unknown", "READ_FAILED", "binding path unavailable")])
    payload = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    def existing_result() -> dict[str, object]:
        try:
            existing_text = target.read_text(encoding="utf-8")
            existing = json.loads(existing_text)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _report(mode="init", scope="task", checks=checks + [_check("binding", "unknown", "BINDING_INVALID", "existing binding cannot be read")])
        comparable = dict(binding)
        comparable.pop("created_at")
        if _binding_is_valid(existing) and {key: existing.get(key) for key in comparable} == comparable:
            return _report(mode="init", scope="task", checks=checks + [_check("binding", "pass", None, "identical binding already exists")], binding=existing)
        return _report(mode="init", scope="task", checks=checks + [_check("binding", "fail", "BINDING_CONFLICT", "different binding already exists")], binding=existing if isinstance(existing, dict) else None)
    temporary: Path | None = None
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=".context-binding.", suffix=".tmp", dir=task_dir)
        temporary = Path(raw_temp)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            return existing_result()
        directory_fd = os.open(task_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        return _report(mode="init", scope="task", checks=checks + [_check("binding", "unknown", "READ_FAILED", "binding write durability is unknown")])
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return _report(mode="init", scope="task", checks=checks + [_check("binding", "unknown", "READ_FAILED", "temporary binding cleanup failed")])
    return _report(mode="init", scope="task", checks=checks + [_check("binding", "pass", None, "binding created atomically")], binding=binding)


def merge_full(identity: Mapping[str, object], verification: Mapping[str, object], smoke: Mapping[str, object] | None = None) -> dict[str, object]:
    """Return a full report while preserving package verifier error codes verbatim."""
    checks = [dict(item) for item in identity.get("checks", []) if item.get("name") not in {"full_verification", "smoke"}]
    verify_codes = verification.get("codes") if isinstance(verification.get("codes"), list) else []
    missing_manifest = "PACKAGE_MANIFEST_MISSING" in verify_codes
    verify_status = "pass" if verification.get("status") == "pass" else "unknown" if missing_manifest or verification.get("status") == "unknown" else "fail"
    if verify_codes:
        checks.extend(_check("full_verification", verify_status, str(code), "complete package verification") for code in verify_codes)
    else:
        checks.append(_check("full_verification", verify_status, None, "complete package verification"))
    if smoke is None:
        checks.append(_check("smoke", "unknown", "SMOKE_FAILED", "smoke runner was unavailable"))
    else:
        checks.append(dict(smoke))
    return _report(
        mode="full", scope=str(identity.get("scope", "package")), checks=checks,
        identity=identity.get("identity") if isinstance(identity.get("identity"), Mapping) else None,
        binding=identity.get("binding") if isinstance(identity.get("binding"), Mapping) else None,
        full_verification=verify_status,
    )
