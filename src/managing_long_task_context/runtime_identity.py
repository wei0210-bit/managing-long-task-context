"""Process-local identity baseline and guarded Context Strict recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

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
        capabilities=("runtime-identity/v1", "workspace-binding/v1", "checked-resume/v1", "checked-resume-gate/v1", "short-session-handoff/v1"),
    )


def _resume_error_checks(
    errors: Iterable[str], unavailable_candidates: Iterable[str], *, handlers_supplied: bool,
) -> list[dict[str, object]]:
    """Partition exact handler-unavailable matches, unavailable rules and failures."""
    exempt = set() if handlers_supplied else {
        error for error in unavailable_candidates if "capability unavailable: expected " in error
    }
    handlers, rules, failures = [], [], []
    for error in errors:
        if error in exempt:
            handlers.append(error)
        elif "RULE_RUNTIME_UNAVAILABLE" in error:
            rules.append(error)
        else:
            failures.append(error)
    checks = []
    if handlers:
        checks.append(core._check("resume_handlers", "not_run", None, "\n".join(handlers)))
    if rules:
        checks.append(core._check("resume_rules", "unknown", "RESUME_RULE_RUNTIME_UNAVAILABLE", "\n".join(rules)))
    checks.append(core._check("resume_gate", "fail" if failures else "pass",
                             "RESUME_GATE_FAILED" if failures else None,
                             "\n".join(failures) if failures else "恢复门禁其余检查通过"))
    return checks


def _resume_next_action(context: Mapping[str, Any], checks: Iterable[Mapping[str, Any]]) -> str:
    messages = "\n".join(str(check.get("message", "")) for check in checks)
    codes = {check.get("code") for check in checks}
    actions = []
    facts = {item["id"]: item for item in context.get("facts", [])}
    for line in messages.splitlines():
        prefix = "required mutable fact is stale: "
        if line.startswith(prefix):
            identifier = line[len(prefix):]
            if facts.get(identifier, {}).get("ttl_hours") is None:
                actions.append(f"{identifier}: 用 record(..., supersedes={identifier!r}) 带 ttl_hours 重记。")
            else:
                actions.append(f"{identifier}: 重新观察后用 update_item 刷新。")
    if "required context item is conflicted:" in messages:
        actions.append('裁决冲突后把输掉的一方改为 superseded；胜出方若也为 conflicted，再 update_item(status="active")。')
    if "blocking context item remains:" in messages:
        actions.append("可以派发以解除该阻塞为目标的工作；其他新的执行工作等门禁通过后再派。")
    if "RULE_RUNTIME_UNAVAILABLE" in messages:
        actions.append("在 Python 宿主里传 rule_runtime 重跑。")
    if codes & {"RESUME_GATE_RACE", "RESUME_RACE_UNCHECKED", "RESUME_GATE_UNAVAILABLE"}:
        actions.append("重跑一次；重跑仍不一致时按门禁错误处理，不反复重跑。")
    if not actions:
        actions.append("按恢复门禁错误核对原始证据并修复；diagnostic.status 为 pass 后再继续。")
    return "\n".join(actions)


def checked_resume(
    task_id: str, *, package_root: str | Path, workspace_root: str | Path, base_dir: str | Path,
    resolvers: Mapping[str, Any] | None = None, verifiers: Mapping[str, Any] | None = None,
    rule_runtime: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Check Strict identity, then read the brief and run the read-only resume gate.

    Nonempty context does not authorize continuation: diagnostic.status must be
    pass. Identity failure still returns null; gate failure/unknown retains context.
    Lite resume is unchanged (failure returns null). Brief ContextError, including
    tampered contracts and overflow, remains visible to callers.

    BoundContext.checked_resume does not forward host handlers; use this module-level
    API for resolvers/verifiers/rule_runtime. Unlike BoundContext.gate it does not
    inject independent_validation_required, so those policies can differ. Experience
    unknowns without RULE_RUNTIME_UNAVAILABLE remain conservative gate failures.
    """
    diagnostic = core.identity_diagnostic(
        package_root=package_root,
        runtime_paths=_BASELINE_PATHS,
        loaded_manifest_sha256=_LOADED_MANIFEST_SHA256 if _BASELINE_FINALIZED else None,
        capabilities=("runtime-identity/v1", "workspace-binding/v1", "checked-resume/v1", "checked-resume-gate/v1", "short-session-handoff/v1"),
        binding_context_root=base_dir,
        workspace_root=workspace_root,
        task_id=task_id,
    )
    if diagnostic["status"] != "pass":
        return {"diagnostic": diagnostic, "context": None}
    from . import brief, gate
    from .evidence import runtime_evidence_handler_errors

    context = brief(task_id, base_dir=base_dir)
    checks = list(diagnostic["checks"])
    resume_checks = []
    report = None
    try:
        report = gate(task_id, stage="resume", emit=False, base_dir=base_dir,
                      resolvers=resolvers, verifiers=verifiers, rule_runtime=rule_runtime)
    except Exception as exc:
        resume_checks.append(core._check("resume_gate", "unknown", "RESUME_GATE_UNAVAILABLE",
                                         f"恢复门禁不可用: {type(exc).__name__}"))
    else:
        events = report.get("stats", {}).get("events")
        if events is None:
            resume_checks.append(core._check("resume_race", "unknown", "RESUME_RACE_UNCHECKED",
                                             "恢复门禁未提供 stats.events"))
        elif context.get("context_version") != events:
            resume_checks.append(core._check("resume_race", "unknown", "RESUME_GATE_RACE",
                                             "brief 与门禁读取之间事件版本不一致"))
        candidates = []
        if resolvers is None and verifiers is None:
            try:
                contract = json.loads((Path(base_dir) / task_id / "task-contract.json").read_text(encoding="utf-8"))
                if contract.get("version") != report.get("contract_version"):
                    resume_checks.append(core._check("resume_race", "unknown", "RESUME_GATE_RACE",
                                                     "处理器分类读取的合同版本与门禁不一致"))
                else:
                    candidates, _ = runtime_evidence_handler_errors(contract, resolvers=None, verifiers=None)
            except (OSError, ValueError, TypeError) as exc:
                resume_checks.append(core._check("resume_race", "unknown", "RESUME_RACE_UNCHECKED",
                                                 f"处理器分类合同不可读: {type(exc).__name__}"))
        resume_checks.extend(_resume_error_checks(report.get("errors", []), candidates,
                          handlers_supplied=resolvers is not None or verifiers is not None))
    diagnostic = core._report(mode=diagnostic["mode"], scope=diagnostic["scope"],
                              identity=diagnostic["identity"], binding=diagnostic["binding"],
                              checks=checks + resume_checks,
                              full_verification=diagnostic["full_verification"])
    if diagnostic["status"] != "pass":
        diagnostic["next_action"] = _resume_next_action(context, resume_checks)
    return {"diagnostic": diagnostic, "context": context, "resume_gate": report}
