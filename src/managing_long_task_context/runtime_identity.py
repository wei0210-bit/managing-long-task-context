"""Process-local identity baseline and guarded Context Strict recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from . import _identity_core as core


def _manifest_for(path: Path) -> Path | None:
    for parent in (path, *path.parents):
        candidate = parent / "skill-manifest.json"
        if candidate.is_file():
            return candidate
    return None


def _digest(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


_MANIFEST_AT_IMPORT = _manifest_for(Path(__file__).resolve())
_DIGEST_AT_IMPORT = _digest(_MANIFEST_AT_IMPORT)
_BASELINE_PATHS: tuple[Path, ...] = (Path(__file__).resolve(), Path(core.__file__).resolve())
_LOADED_MANIFEST_SHA256: str | None = None
_BASELINE_FINALIZED = False


def _runtime_payload_matches_manifest(
    manifest_path: Path | None, module_paths: Iterable[Path]
) -> bool:
    if manifest_path is None:
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
        expected = {
            str(item["path"]): str(item["sha256"])
            for item in entries
            if isinstance(item, dict)
        }
        package_root = manifest_path.parent.resolve(strict=True)
        for path in module_paths:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(package_root).as_posix()
            if expected.get(relative) != _digest(resolved):
                return False
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


def _capture_baseline(
    module_paths: Iterable[str | Path], *, initial_manifest_path: Path | None = None,
    initial_manifest_sha256: str | None = None,
) -> None:
    """Finalize the import-time baseline; called by package ``__init__`` only."""
    global _BASELINE_PATHS, _LOADED_MANIFEST_SHA256, _BASELINE_FINALIZED
    paths = tuple(Path(item).resolve() for item in module_paths)
    after_manifest = _manifest_for(Path(__file__).resolve())
    after_digest = _digest(after_manifest)
    _BASELINE_PATHS = paths
    # The package initializer always supplies its observation from before any
    # controlled sibling import.  Absence at that point is deliberately not
    # replaced with this module's later observation.
    before_manifest = initial_manifest_path
    before_digest = initial_manifest_sha256
    if (
        before_manifest is not None
        and after_manifest == before_manifest
        and before_digest == after_digest
        and _runtime_payload_matches_manifest(after_manifest, paths)
    ):
        _LOADED_MANIFEST_SHA256 = before_digest
    else:
        _LOADED_MANIFEST_SHA256 = None
    _BASELINE_FINALIZED = True


def runtime_identity(*, package_root: str | Path) -> dict[str, object]:
    """Report this process's loaded Strict runtime identity without task I/O."""
    return core.identity_diagnostic(
        package_root=package_root,
        runtime_paths=_BASELINE_PATHS,
        loaded_manifest_sha256=_LOADED_MANIFEST_SHA256 if _BASELINE_FINALIZED else None,
        capabilities=("runtime-identity/v1", "workspace-binding/v1", "checked-resume/v1", "short-session-handoff/v1"),
    )


def checked_resume(
    task_id: str, *, package_root: str | Path, workspace_root: str | Path, base_dir: str | Path,
) -> dict[str, object]:
    """Run identity checks before delegating to the existing, unchanged ``brief`` API."""
    diagnostic = core.identity_diagnostic(
        package_root=package_root,
        runtime_paths=_BASELINE_PATHS,
        loaded_manifest_sha256=_LOADED_MANIFEST_SHA256 if _BASELINE_FINALIZED else None,
        capabilities=("runtime-identity/v1", "workspace-binding/v1", "checked-resume/v1", "short-session-handoff/v1"),
        binding_context_root=base_dir,
        workspace_root=workspace_root,
        task_id=task_id,
    )
    if diagnostic["status"] != "pass":
        return {"diagnostic": diagnostic, "context": None}
    # This intentionally keeps ContextError visible to Python callers.  The CLI
    # converts it to RESUME_BLOCKED but must not replace Strict's old gate.
    from . import brief

    return {"diagnostic": diagnostic, "context": brief(task_id, base_dir=base_dir)}
