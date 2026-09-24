#!/usr/bin/env python3
"""Build and verify complete, versioned Context skill packages."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping


MANIFEST_NAME = "skill-manifest.json"
DECLARATION_NAME = "skill-package.json"
TRANSIENT_NAMES = {".DS_Store", MANIFEST_NAME}
TRANSIENT_DIR_NAMES = {"__pycache__", "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DOCUMENTED_PATH = re.compile(r"(?P<path>(?:assets|examples|scripts|src|tests)/[A-Za-z0-9_.\-/]+)")
CONTEXT_API = re.compile(r"\bcontext\.([a-z][a-z0-9_]*)\s*\(")
TABLE_API = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)\(", re.MULTILINE)
DUPLICATE_COPY_NAME = re.compile(r" 2(\.[^.]+)?$")


class PackageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _emit(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _is_transient(relative: Path) -> bool:
    if relative.name in TRANSIENT_NAMES or relative.suffix in {".pyc", ".pyo"}:
        return True
    return any(part in TRANSIENT_DIR_NAMES or part.endswith(".egg-info") for part in relative.parts)


def _load_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(code, f"cannot read valid JSON from {path}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise PackageError(code, f"{path} must contain a JSON object")
    return value


def _validate_declaration(value: Mapping[str, Any]) -> None:
    allowed = {
        "schema", "skill_name", "skill_version", "package_name", "package_version",
        "python_module", "payload_roots", "required_paths", "capabilities",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PackageError("PACKAGE_DECLARATION_INVALID", f"unknown declaration fields: {unknown}")
    if value.get("schema") != 1:
        raise PackageError("PACKAGE_DECLARATION_INVALID", "schema must equal 1")
    if not isinstance(value.get("skill_name"), str) or not value["skill_name"]:
        raise PackageError("PACKAGE_DECLARATION_INVALID", "skill_name must be non-empty")
    if not isinstance(value.get("skill_version"), str) or not SEMVER.fullmatch(value["skill_version"]):
        raise PackageError("PACKAGE_DECLARATION_INVALID", "skill_version must be semantic x.y.z")
    roots = value.get("payload_roots")
    if not isinstance(roots, list) or not roots or not all(isinstance(item, str) and item for item in roots):
        raise PackageError("PACKAGE_DECLARATION_INVALID", "payload_roots must be non-empty strings")
    if len(set(roots)) != len(roots):
        raise PackageError("PACKAGE_DECLARATION_INVALID", "payload_roots must be unique")
    required_paths = value.get("required_paths")
    if not isinstance(required_paths, list) or not required_paths or not all(
        isinstance(item, str) and item for item in required_paths
    ):
        raise PackageError("PACKAGE_DECLARATION_INVALID", "required_paths must be non-empty strings")
    if len(set(required_paths)) != len(required_paths):
        raise PackageError("PACKAGE_DECLARATION_INVALID", "required_paths must be unique")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        raise PackageError("PACKAGE_DECLARATION_INVALID", "capabilities must be a non-empty object")
    for name, capability in capabilities.items():
        if not isinstance(name, str) or not name or not isinstance(capability, dict):
            raise PackageError("PACKAGE_DECLARATION_INVALID", "capability entries must be named objects")
        exports = capability.get("python_exports", [])
        if not isinstance(exports, list) or not all(isinstance(item, str) and item for item in exports):
            raise PackageError("PACKAGE_DECLARATION_INVALID", f"{name}.python_exports must be strings")


def load_declaration(source: Path) -> dict[str, Any]:
    declaration = _load_json(source / DECLARATION_NAME, code="PACKAGE_DECLARATION_MISSING")
    _validate_declaration(declaration)
    return declaration


def _payload_paths(source: Path, declaration: Mapping[str, Any]) -> list[Path]:
    selected: set[Path] = {Path(DECLARATION_NAME)}
    for raw_root in declaration["payload_roots"]:
        root = Path(raw_root)
        if root.is_absolute() or ".." in root.parts:
            raise PackageError("PACKAGE_DECLARATION_INVALID", f"unsafe payload root: {raw_root}")
        absolute = source / root
        if not absolute.exists():
            raise PackageError("PACKAGE_ROOT_MISSING", f"payload root is missing: {raw_root}")
        if absolute.is_symlink():
            raise PackageError("PACKAGE_SYMLINK_UNSUPPORTED", f"payload root is a symlink: {raw_root}")
        if absolute.is_file():
            selected.add(root)
            continue
        for path in absolute.rglob("*"):
            relative = path.relative_to(source)
            if _is_transient(relative):
                continue
            if path.is_symlink():
                raise PackageError("PACKAGE_SYMLINK_UNSUPPORTED", f"payload file is a symlink: {relative}")
            if path.is_file():
                selected.add(relative)
    for raw_required in declaration["required_paths"]:
        required = Path(raw_required)
        if required.is_absolute() or ".." in required.parts:
            raise PackageError("PACKAGE_DECLARATION_INVALID", f"unsafe required path: {raw_required}")
        if not (source / required).is_file():
            raise PackageError("PACKAGE_REQUIRED_PATH_MISSING", raw_required)
        if required not in selected:
            raise PackageError("PACKAGE_REQUIRED_PATH_OUTSIDE_PAYLOAD", raw_required)
    return sorted(selected, key=lambda item: item.as_posix())


def _file_entries(source: Path, declaration: Mapping[str, Any]) -> list[dict[str, object]]:
    return [
        {"path": relative.as_posix(), "sha256": _sha256(source / relative), "size": (source / relative).stat().st_size}
        for relative in _payload_paths(source, declaration)
    ]


def _read_project_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section == "[project]":
            matched = re.fullmatch(r'version\s*=\s*"([^"]+)"', stripped)
            if matched:
                return matched.group(1)
    return None


def _documented_paths(skill_text: str) -> list[str]:
    return sorted({match.group("path").rstrip(".,;:)") for match in DOCUMENTED_PATH.finditer(skill_text)})


def _documented_apis(skill_text: str) -> list[str]:
    candidates = {match.group(1) for match in CONTEXT_API.finditer(skill_text)}
    candidates.update(match.group(1) for match in TABLE_API.finditer(skill_text))
    return sorted(candidates)


def _static_python_exports(source: Path, module_name: str) -> set[str]:
    module_path = source / "src" / Path(*module_name.split(".")) / "__init__.py"
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PackageError("PACKAGE_IMPORT_SURFACE_INVALID", type(exc).__name__) from exc
    discovered: set[str] = set()
    explicit_all: set[str] | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            discovered.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            discovered.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    discovered.add(target.id)
                    if target.id == "__all__":
                        try:
                            value = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            value = None
                        if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                            explicit_all = set(value)
    return explicit_all if explicit_all is not None else discovered


def check_source(source: Path) -> dict[str, object]:
    errors: list[dict[str, str]] = []
    try:
        declaration = load_declaration(source)
        entries = _file_entries(source, declaration)
    except PackageError as exc:
        return {
            "status": "fail", "codes": [exc.code],
            "errors": [{"code": exc.code, "message": exc.message}],
            "stats": {"files_checked": 0, "documented_paths_checked": 0, "python_exports_checked": 0},
        }

    skill_path = source / "SKILL.md"
    if not skill_path.is_file():
        errors.append({"code": "PACKAGE_SKILL_MISSING", "message": "SKILL.md is missing"})
        skill_text = ""
    else:
        skill_text = skill_path.read_text(encoding="utf-8")
        if f"name: {declaration['skill_name']}" not in skill_text:
            errors.append({"code": "PACKAGE_SKILL_NAME_MISMATCH", "message": "SKILL.md name differs from declaration"})

    documented_paths = _documented_paths(skill_text)
    for relative in documented_paths:
        if not (source / relative).is_file():
            errors.append({"code": "DOCUMENTED_PATH_MISSING", "message": relative})

    project_version = _read_project_version(source / "pyproject.toml")
    declared_package_version = declaration.get("package_version")
    if declared_package_version is not None and project_version != declared_package_version:
        errors.append({
            "code": "PACKAGE_VERSION_MISMATCH",
            "message": f"declaration={declared_package_version!r} pyproject={project_version!r}",
        })

    for entry in entries:
        name = Path(str(entry["path"])).name
        if name == ".DS_Store":
            continue
        if DUPLICATE_COPY_NAME.search(name):
            errors.append({
                "code": "PACKAGE_DUPLICATE_COPY",
                "message": str(entry["path"]),
            })

    declared_exports = {
        export
        for capability in declaration["capabilities"].values()
        for export in capability.get("python_exports", [])
    }
    documented_apis = _documented_apis(skill_text)
    exports_to_check = sorted(declared_exports | set(documented_apis))
    module_name = declaration.get("python_module")
    if exports_to_check and not isinstance(module_name, str):
        errors.append({"code": "PACKAGE_PYTHON_MODULE_MISSING", "message": "python_module is required for exports"})
    elif isinstance(module_name, str):
        try:
            available_exports = _static_python_exports(source, module_name)
            for api in exports_to_check:
                if api not in available_exports:
                    errors.append({"code": "DOCUMENTED_API_MISSING", "message": api})
        except PackageError as exc:
            errors.append({"code": exc.code, "message": exc.message})

    codes = sorted({item["code"] for item in errors})
    return {
        "status": "pass" if not errors else "fail",
        "codes": codes,
        "errors": errors,
        "stats": {
            "files_checked": len(entries),
            "documented_paths_checked": len(documented_paths),
            "python_exports_checked": len(exports_to_check),
        },
    }


def build_package(source: Path, destination: Path, source_revision: str) -> dict[str, object]:
    if not source_revision.strip():
        raise PackageError("PACKAGE_SOURCE_REVISION_MISSING", "source_revision must be non-empty")
    if destination.exists():
        raise PackageError("PACKAGE_DESTINATION_EXISTS", f"destination already exists: {destination}")
    source_report = check_source(source)
    if source_report["status"] != "pass":
        first = source_report["errors"][0]
        raise PackageError(str(first["code"]), str(first["message"]))
    declaration = load_declaration(source)
    entries = _file_entries(source, declaration)
    destination.mkdir(parents=True)
    try:
        for entry in entries:
            relative = Path(str(entry["path"]))
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        manifest = {
            "manifest_schema": 1,
            "skill_name": declaration["skill_name"],
            "skill_version": declaration["skill_version"],
            "package_name": declaration.get("package_name"),
            "package_version": declaration.get("package_version"),
            "capabilities": declaration["capabilities"],
            "source_revision": source_revision,
            "source_tree_sha256": _json_digest(entries),
            "files": entries,
        }
        (destination / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_sha256 = _sha256(destination / MANIFEST_NAME)
    except Exception:
        shutil.rmtree(destination)
        raise
    return {
        "status": "pass",
        "codes": [],
        "package": str(destination.resolve()),
        "skill_name": declaration["skill_name"],
        "skill_version": declaration["skill_version"],
        "source_revision": source_revision,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "manifest_sha256": manifest_sha256,
        "stats": {"files_written": len(entries)},
    }


def _actual_package_files(package: Path) -> list[str]:
    result = []
    for path in package.rglob("*"):
        relative = path.relative_to(package)
        if _is_transient(relative):
            continue
        if path.is_symlink():
            result.append(relative.as_posix())
        elif path.is_file():
            result.append(relative.as_posix())
    return sorted(result)


def verify_package(
    package: Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_source_revision: str | None = None,
) -> dict[str, object]:
    errors: list[dict[str, str]] = []
    try:
        manifest = _load_json(package / MANIFEST_NAME, code="PACKAGE_MANIFEST_MISSING")
    except PackageError as exc:
        return {
            "status": "fail", "codes": [exc.code],
            "errors": [{"code": exc.code, "message": exc.message}],
            "stats": {"files_checked": 0},
        }
    if manifest.get("manifest_schema") != 1:
        errors.append({"code": "PACKAGE_MANIFEST_INVALID", "message": "manifest_schema must equal 1"})
    actual_manifest_sha256 = _sha256(package / MANIFEST_NAME)
    if expected_manifest_sha256 is not None and actual_manifest_sha256 != expected_manifest_sha256:
        errors.append({"code": "PACKAGE_MANIFEST_HASH_MISMATCH", "message": actual_manifest_sha256})
    if expected_source_revision is not None and manifest.get("source_revision") != expected_source_revision:
        errors.append({"code": "PACKAGE_SOURCE_REVISION_MISMATCH", "message": str(manifest.get("source_revision"))})
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append({"code": "PACKAGE_MANIFEST_INVALID", "message": "files must be a list"})
        files = []
    expected: dict[str, Mapping[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append({"code": "PACKAGE_MANIFEST_INVALID", "message": "file entry is invalid"})
            continue
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or entry["path"] in expected:
            errors.append({"code": "PACKAGE_MANIFEST_INVALID", "message": f"unsafe or duplicate path: {relative}"})
            continue
        expected[entry["path"]] = entry
    actual = set(_actual_package_files(package))
    expected_paths = set(expected)
    for missing in sorted(expected_paths - actual):
        errors.append({"code": "PACKAGE_FILE_MISSING", "message": missing})
    for extra in sorted(actual - expected_paths):
        errors.append({"code": "PACKAGE_FILE_UNEXPECTED", "message": extra})
    checked = 0
    for relative in sorted(expected_paths & actual):
        path = package / relative
        entry = expected[relative]
        if path.is_symlink():
            errors.append({"code": "PACKAGE_SYMLINK_UNSUPPORTED", "message": relative})
            continue
        checked += 1
        if _sha256(path) != entry.get("sha256") or path.stat().st_size != entry.get("size"):
            errors.append({"code": "PACKAGE_HASH_MISMATCH", "message": relative})
    if _json_digest(files) != manifest.get("source_tree_sha256"):
        errors.append({"code": "PACKAGE_TREE_DIGEST_MISMATCH", "message": "files do not match source_tree_sha256"})
    if not isinstance(manifest.get("source_revision"), str) or not manifest["source_revision"]:
        errors.append({"code": "PACKAGE_SOURCE_REVISION_MISSING", "message": "source_revision must be non-empty"})
    source_report = check_source(package)
    errors.extend(source_report["errors"])
    try:
        declaration = load_declaration(package)
    except PackageError as exc:
        errors.append({"code": exc.code, "message": exc.message})
        declaration = {}
    for field in ("skill_name", "skill_version", "package_name", "package_version", "capabilities"):
        if manifest.get(field) != declaration.get(field):
            errors.append({"code": "PACKAGE_IDENTITY_MISMATCH", "message": field})
    codes = sorted({item["code"] for item in errors})
    return {
        "status": "pass" if not errors else "fail",
        "codes": codes,
        "errors": errors,
        "identity": {
            "skill_name": manifest.get("skill_name"),
            "skill_version": manifest.get("skill_version"),
            "package_version": manifest.get("package_version"),
            "source_revision": manifest.get("source_revision"),
            "source_tree_sha256": manifest.get("source_tree_sha256"),
            "manifest_sha256": actual_manifest_sha256,
        },
        "stats": {
            "files_checked": checked,
            "documented_paths_checked": source_report["stats"]["documented_paths_checked"],
            "python_exports_checked": source_report["stats"]["python_exports_checked"],
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check-source")
    check.add_argument("--source", type=Path, required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--destination", type=Path, required=True)
    build.add_argument("--source-revision", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256")
    verify.add_argument("--expected-source-revision")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check-source":
            report = check_source(args.source.resolve())
        elif args.command == "build":
            report = build_package(args.source.resolve(), args.destination.resolve(), args.source_revision)
        else:
            report = verify_package(
                args.package.resolve(),
                expected_manifest_sha256=args.expected_manifest_sha256,
                expected_source_revision=args.expected_source_revision,
            )
    except PackageError as exc:
        report = {
            "status": "fail", "codes": [exc.code],
            "errors": [{"code": exc.code, "message": exc.message}], "stats": {},
        }
    _emit(report)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
