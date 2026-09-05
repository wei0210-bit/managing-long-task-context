#!/usr/bin/env python3
"""Diagnose package, process and task binding identity without repairing it."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

def _digest_near(path: Path) -> str | None:
    for parent in path.resolve().parents:
        manifest = parent / "skill-manifest.json"
        try:
            return hashlib.sha256(manifest.read_bytes()).hexdigest()
        except FileNotFoundError:
            continue
        except OSError:
            return None
    return None


_MANIFEST_BEFORE_TOOLS = _digest_near(Path(__file__))

import context_identity_core as core
from skill_package import verify_package

_MANIFEST_AFTER_TOOLS = _digest_near(Path(__file__))
_LOADED_MANIFEST_SHA256 = (
    _MANIFEST_BEFORE_TOOLS if _MANIFEST_BEFORE_TOOLS == _MANIFEST_AFTER_TOOLS else None
)


def _emit(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _triple(args: argparse.Namespace) -> tuple[str, str, str] | None:
    values = (args.context_root, args.workspace_root, args.task_id)
    if not any(values):
        return None
    if not all(values):
        return None
    return values  # type: ignore[return-value]


def _runtime_paths(skill_name: str | None) -> tuple[list[Path], str | None, object | None]:
    paths = [Path(__file__).resolve(), Path(core.__file__).resolve()]
    if skill_name == "context-lite":
        try:
            lite = importlib.import_module("context_lite")
            paths.append(Path(lite.__file__).resolve())
            loaded = lite._LOADED_MANIFEST_SHA256
            return paths, loaded if loaded == _LOADED_MANIFEST_SHA256 else None, lite
        except (ImportError, AttributeError):
            return paths, None, None
    if skill_name == "context-strict":
        try:
            strict = importlib.import_module("managing_long_task_context")
            strict_runtime = importlib.import_module("managing_long_task_context.runtime_identity")
            loaded = strict_runtime._LOADED_MANIFEST_SHA256
            return paths + list(strict_runtime._BASELINE_PATHS), loaded if loaded == _LOADED_MANIFEST_SHA256 else None, strict
        except (ImportError, AttributeError):
            return paths, None, None
    return paths, _LOADED_MANIFEST_SHA256, None


def _valid_now() -> str:
    return """# DOCTOR: deterministic smoke

Updated: 2026-09-01T02:00:00Z
Phase: smoke

## Acceptance
- Validator tests pass.

## Current State
- [STATE-01] Source | mutable: true | source: /tmp/source.json | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: test -r /tmp/source.json

## Decisions
- Use standard library | why: portable | evidence: /tmp/design.md

## In Flight
- [RUN-01] Validate | owner: doctor | status: pending | started_at: 2026-09-01T02:00:00+00:00 | correlation_ref: tool:doctor | recovery_ref: test -r /tmp/result.json

## Blockers
- none

## Next
1. First: validate the smoke input

## Refresh On Resume
- STATE-01 -> test -r /tmp/source.json
- RUN-01 -> test -r /tmp/result.json
"""


def _smoke(skill_name: str | None, module: object | None) -> dict[str, object]:
    try:
        temporary = tempfile.TemporaryDirectory(prefix="context-doctor-")
    except OSError as exc:
        return core._check("smoke", "fail", "SMOKE_FAILED", f"temporary storage unavailable: {type(exc).__name__}")
    try:
        if skill_name == "context-lite":
            if module is None:
                return core._check("smoke", "unknown", "RUNTIME_UNVERIFIED", "Lite validator was not imported")
            valid = module.validate_text(_valid_now(), "DOCTOR")  # type: ignore[attr-defined]
            invalid = module.validate_text(_valid_now().replace("## Decisions", "## Notes"), "DOCTOR")  # type: ignore[attr-defined]
            if (valid.get("status") == "valid" and invalid.get("status") == "invalid"
                    and "NOW_HEADING_ORDER_INVALID" in invalid.get("codes", [])):
                return core._check("smoke", "pass", None, "Lite valid and blocked-invalid samples behaved as expected")
            return core._check("smoke", "fail", "SMOKE_FAILED", "Lite smoke result was unexpected")
        if skill_name == "context-strict":
            if module is None:
                return core._check("smoke", "unknown", "RUNTIME_UNVERIFIED", "Strict runtime was not imported")
            directory = temporary.name
            base = Path(directory) / "context"
            task = "DOCTOR"
            contract = {
                "schema": 1, "task_id": task, "version": 1, "issued_by": "doctor",
                "issued_at": "2026-09-01T02:00:00Z", "authorized_approvers": [],
                "workspace_root": directory, "objective": "Doctor smoke", "scope": ["smoke"],
                "out_of_scope": [], "constraints": [], "acceptance_criteria": [{
                    "id": "AC-DOCTOR", "criterion": "requires evidence", "required_evidence_types": ["file"],
                    "required_hops": [], "required_delivery_types": [], "independent_validation_required": False,
                }],
            }
            module.publish_contract(contract, confirmed_by="doctor", base_dir=base)  # type: ignore[attr-defined]
            normal = module.brief(task, base_dir=base)  # type: ignore[attr-defined]
            blocked = module.gate(task, stage="completion", evidence_map={}, base_dir=base, emit=False)  # type: ignore[attr-defined]
            missing_evidence = "criterion AC-DOCTOR missing required evidence types: ['file']" in blocked.get("errors", [])
            if normal.get("task_id") == task and not blocked.get("passed", True) and missing_evidence:
                return core._check("smoke", "pass", None, "Strict normal brief and expected completion block behaved as expected")
            return core._check("smoke", "fail", "SMOKE_FAILED", "Strict smoke result was unexpected")
        return core._check("smoke", "unknown", "RUNTIME_UNVERIFIED", "unknown skill type has no smoke runner")
    except Exception as exc:
        return core._check("smoke", "fail", "SMOKE_FAILED", f"smoke raised {type(exc).__name__}")
    finally:
        try:
            temporary.cleanup()
        except OSError:
            return core._check("cleanup", "fail", "CLEANUP_FAILED", f"temporary smoke directory cleanup failed: {temporary.name}")


def check(args: argparse.Namespace) -> dict[str, object]:
    if args.mode not in {"identity", "full"}:
        return core.input_failure("identity", "package", "mode must be full or identity")
    triple = _triple(args)
    if any((args.context_root, args.workspace_root, args.task_id)) and triple is None:
        return core.input_failure(args.mode, "task", "context_root, workspace_root and task_id must be supplied together")
    if args.mode == "identity" and triple is None:
        return core.input_failure("identity", "task", "identity checks require context_root, workspace_root and task_id")
    root, manifest, _, _ = core.package_identity(args.package_root)
    skill_name = manifest.get("skill_name") if manifest else None
    paths, loaded_hash, module = _runtime_paths(skill_name if isinstance(skill_name, str) else None)
    kwargs: dict[str, object] = {}
    if triple is not None:
        kwargs = {"binding_context_root": triple[0], "workspace_root": triple[1], "task_id": triple[2]}
    identity = core.identity_diagnostic(
        package_root=args.package_root, runtime_paths=paths, loaded_manifest_sha256=loaded_hash,
        capabilities=("context-doctor/v1",), **kwargs,
    )
    if triple is None:
        identity["scope"] = "package"
    if args.mode == "identity":
        return identity
    try:
        verification = verify_package(Path(args.package_root)) if root is not None else {"status": "unknown", "codes": ["READ_FAILED"]}
    except (OSError, UnicodeError, ValueError) as exc:
        verification = {"status": "unknown", "codes": ["READ_FAILED"]}
    smoke = (
        _smoke(skill_name if isinstance(skill_name, str) else None, module)
        if verification["status"] == "pass" and identity["status"] == "pass"
        else core._check("smoke", "not_run", None, "package and runtime must pass before smoke execution")
    )
    return core.merge_full(identity, verification, smoke)


def resume(args: argparse.Namespace) -> dict[str, object]:
    # The CLI's own source and loading baseline matter too; the library then
    # independently checks the process performing the actual recovery.
    preflight = check(argparse.Namespace(**{**vars(args), "mode": "identity"}))
    if preflight["status"] != "pass":
        return {"diagnostic": preflight, "context": None}
    root, manifest, _, failure = core.package_identity(args.package_root)
    if failure is not None or manifest is None:
        diagnostic = core.identity_diagnostic(
            package_root=args.package_root, runtime_paths=(Path(__file__).resolve(), Path(core.__file__).resolve()),
            loaded_manifest_sha256=_LOADED_MANIFEST_SHA256, binding_context_root=args.context_root,
            workspace_root=args.workspace_root, task_id=args.task_id,
        )
        return {"diagnostic": diagnostic, "context": None}
    if manifest.get("skill_name") == "context-lite":
        _, _, lite = _runtime_paths("context-lite")
        if lite is None:
            diagnostic = core.identity_diagnostic(package_root=args.package_root, runtime_paths=[Path(__file__)], loaded_manifest_sha256=None, binding_context_root=args.context_root, workspace_root=args.workspace_root, task_id=args.task_id)
            return {"diagnostic": diagnostic, "context": None}
        return lite._resume(args)[0]
    if manifest.get("skill_name") == "context-strict":
        try:
            strict = importlib.import_module("managing_long_task_context")
            return strict.checked_resume(args.task_id, package_root=args.package_root, workspace_root=args.workspace_root, base_dir=args.context_root)
        except ImportError:
            diagnostic = core.identity_diagnostic(package_root=args.package_root, runtime_paths=[Path(__file__)], loaded_manifest_sha256=None, binding_context_root=args.context_root, workspace_root=args.workspace_root, task_id=args.task_id)
            return {"diagnostic": diagnostic, "context": None}
        except Exception as exc:
            diagnostic = core.identity_diagnostic(package_root=args.package_root, runtime_paths=[Path(__file__)], loaded_manifest_sha256=None, binding_context_root=args.context_root, workspace_root=args.workspace_root, task_id=args.task_id)
            diagnostic = core._report(mode="identity", scope="task", identity=diagnostic["identity"], binding=diagnostic["binding"], checks=list(diagnostic["checks"]) + [core._check("resume", "fail", "RESUME_BLOCKED", type(exc).__name__)])
            return {"diagnostic": diagnostic, "context": None}
    return {"diagnostic": core.input_failure("identity", "task", "package skill_name is unsupported"), "context": None}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parser() -> argparse.ArgumentParser:
    value = _ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--mode")
    check_parser.add_argument("--package-root")
    check_parser.add_argument("--context-root")
    check_parser.add_argument("--workspace-root")
    check_parser.add_argument("--task-id")
    init = sub.add_parser("init-binding")
    init.add_argument("--package-root")
    init.add_argument("--expected-manifest-sha256")
    init.add_argument("--context-root")
    init.add_argument("--workspace-root")
    init.add_argument("--task-id")
    resume_parser = sub.add_parser("resume")
    resume_parser.add_argument("--package-root")
    resume_parser.add_argument("--context-root")
    resume_parser.add_argument("--workspace-root")
    resume_parser.add_argument("--task-id")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except ValueError as exc:
        report = core.input_failure("identity", "package", f"invalid arguments: {type(exc).__name__}")
        _emit(report)
        return 1
    if args.command is None:
        report = core.input_failure("identity", "package", "a command is required")
    elif args.command == "check":
        report = core.input_failure("identity", "package", "package_root is required") if not args.package_root else check(args)
    elif args.command == "init-binding":
        required = (args.package_root, args.expected_manifest_sha256, args.context_root, args.workspace_root, args.task_id)
        report = core.input_failure("init", "task", "all init-binding arguments are required") if not all(required) else core.init_binding(package_root=args.package_root, expected_manifest_sha256=args.expected_manifest_sha256, context_root=args.context_root, workspace_root=args.workspace_root, task_id=args.task_id)
    else:
        required = (args.package_root, args.context_root, args.workspace_root, args.task_id)
        report = {"diagnostic": core.input_failure("identity", "task", "all resume arguments are required"), "context": None} if not all(required) else resume(args)
    _emit(report)
    status = report.get("status") if isinstance(report, Mapping) else None
    if status is None and isinstance(report, Mapping):
        diagnostic = report.get("diagnostic")
        status = diagnostic.get("status") if isinstance(diagnostic, Mapping) else None
    return {"pass": 0, "fail": 1, "unknown": 2}.get(status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
