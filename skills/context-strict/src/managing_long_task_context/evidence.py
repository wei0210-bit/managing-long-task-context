"""Deterministic, layered evidence resolution and independent claim verification."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

EVIDENCE_HANDLERS_CAPABILITY = "evidence-handlers/v1"
BUILTIN_RESOLVER_CAPABILITIES = {
    "file": "builtin:file/v1",
    "git-commit": "builtin:git-commit/v1",
    "test-report": "builtin:test-report/v1",
    "url": "builtin:url/v1",
}
_HANDLER_ROOT_FIELDS = frozenset({"schema", "types"})
_HANDLER_FIELDS = frozenset({"resolver_capability", "verifier_capability"})
_HANDLER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}\Z")

# Local evidence is deliberately bounded. The limit applies to both regular
# file hashing and test-report parsing, and hashing itself is incremental.
MAX_LOCAL_ARTIFACT_BYTES = 16 * 1024 * 1024
LOCAL_READ_CHUNK_BYTES = 64 * 1024
GIT_TIMEOUT_SECONDS = 5
MAX_CLOCK_SKEW_SECONDS = 300

Resolver = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], datetime],
    Mapping[str, Any],
]
Verifier = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]

_RESOLVER_LAYERS = ("resolve", "integrity_and_freshness", "scope")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
_URI_CHARS_RE = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+\Z")
_BAD_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_AMBIGUOUS_NUMERIC_HOST_RE = re.compile(
    r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*\Z",
    re.IGNORECASE,
)
_UTC_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z"
)


def check(status: str, *codes: str) -> dict[str, Any]:
    return {"status": status, "codes": list(codes)}


def evidence_handlers_enabled(contract: Mapping[str, Any]) -> bool:
    capabilities = contract.get("required_capabilities")
    return (
        "evidence_handlers" in contract
        and isinstance(capabilities, list)
        and EVIDENCE_HANDLERS_CAPABILITY in capabilities
    )


def evidence_handler_specs(contract: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    root = contract.get("evidence_handlers")
    types = root.get("types") if isinstance(root, Mapping) else None
    if not isinstance(types, Mapping):
        return {}
    return {
        str(kind): {
            "resolver_capability": str(spec.get("resolver_capability")),
            "verifier_capability": str(spec.get("verifier_capability")),
        }
        for kind, spec in types.items()
        if isinstance(kind, str) and isinstance(spec, Mapping)
    }


def validate_evidence_handler_contract(contract: Mapping[str, Any]) -> list[str]:
    """Validate the opt-in, publisher-sealed evidence handler declaration."""

    capabilities = contract.get("required_capabilities")
    has_capability = (
        isinstance(capabilities, list)
        and EVIDENCE_HANDLERS_CAPABILITY in capabilities
    )
    has_handlers = "evidence_handlers" in contract
    if not has_capability and not has_handlers:
        return []

    errors: list[str] = []
    if has_handlers and not has_capability:
        errors.append(
            "contract.evidence_handlers requires required_capabilities evidence-handlers/v1"
        )
    if has_capability and not has_handlers:
        errors.append(
            "contract.required_capabilities evidence-handlers/v1 requires evidence_handlers"
        )
        return errors

    root = contract.get("evidence_handlers")
    if not isinstance(root, Mapping):
        errors.append("contract.evidence_handlers must be an object")
        return errors
    unknown_root = sorted(set(root) - _HANDLER_ROOT_FIELDS)
    if unknown_root:
        errors.append(f"contract.evidence_handlers has unknown fields: {unknown_root}")
    if root.get("schema") != EVIDENCE_HANDLERS_CAPABILITY:
        errors.append("contract.evidence_handlers.schema must equal evidence-handlers/v1")

    types = root.get("types")
    if not isinstance(types, Mapping):
        errors.append("contract.evidence_handlers.types must be an object")
        return errors

    for kind, spec in types.items():
        path = f"contract.evidence_handlers.types[{kind!r}]"
        if not isinstance(kind, str) or _HANDLER_ID_RE.fullmatch(kind) is None:
            errors.append(f"{path} kind must be a stable non-empty handler ID")
            continue
        if not isinstance(spec, Mapping):
            errors.append(f"{path} must be an object")
            continue
        unknown = sorted(set(spec) - _HANDLER_FIELDS)
        if unknown:
            errors.append(f"{path} has unknown fields: {unknown}")
        resolver = spec.get("resolver_capability")
        verifier = spec.get("verifier_capability")
        if not isinstance(resolver, str) or _HANDLER_ID_RE.fullmatch(resolver) is None:
            errors.append(f"{path}.resolver_capability must be a stable non-empty handler ID")
        if not isinstance(verifier, str) or _HANDLER_ID_RE.fullmatch(verifier) is None:
            errors.append(f"{path}.verifier_capability must be a stable non-empty handler ID")
        expected_builtin = BUILTIN_RESOLVER_CAPABILITIES.get(kind)
        if expected_builtin is not None and resolver != expected_builtin:
            errors.append(
                f"{path}.resolver_capability must equal {expected_builtin}"
            )
        if expected_builtin is None and isinstance(resolver, str) and resolver.startswith("builtin:"):
            errors.append(
                f"{path}.resolver_capability cannot use reserved builtin namespace"
            )

    required_kinds: set[str] = set()
    criteria = contract.get("acceptance_criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if not isinstance(criterion, Mapping):
                continue
            required = criterion.get("required_evidence_types")
            if required is None:
                required = criterion.get("required_evidence")
            if isinstance(required, list):
                required_kinds.update(item for item in required if isinstance(item, str))
    for kind in sorted(required_kinds):
        if kind not in types:
            errors.append(
                f"required evidence type {kind!r} has no handler declaration"
            )
    return errors


def _runtime_handler(
    value: Any,
    *,
    implicit_capability: str | None = None,
) -> tuple[str | None, Callable[..., Mapping[str, Any]] | None]:
    if callable(value):
        return implicit_capability, value
    if not isinstance(value, Mapping):
        return None, None
    capability = value.get("capability")
    handler = value.get("handler")
    return (
        capability if isinstance(capability, str) else None,
        handler if callable(handler) else None,
    )


def runtime_evidence_handler_errors(
    contract: Mapping[str, Any],
    *,
    resolvers: Mapping[str, Any] | None,
    verifiers: Mapping[str, Any] | None,
) -> tuple[list[str], int]:
    """Check sealed handler identities against handlers available in this runtime."""

    if not evidence_handlers_enabled(contract):
        return [], 0
    specs = evidence_handler_specs(contract)
    required_kinds: set[str] = set()
    criteria = contract.get("acceptance_criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if not isinstance(criterion, Mapping):
                continue
            required = criterion.get("required_evidence_types")
            if required is None:
                required = criterion.get("required_evidence")
            if isinstance(required, list):
                required_kinds.update(item for item in required if isinstance(item, str))

    resolver_values = dict(default_resolvers() if resolvers is None else resolvers)
    verifier_values = dict(verifiers or {})
    errors: list[str] = []
    for kind in sorted(required_kinds):
        spec = specs.get(kind, {})
        expected_resolver = spec.get("resolver_capability")
        expected_verifier = spec.get("verifier_capability")
        implicit = BUILTIN_RESOLVER_CAPABILITIES.get(kind) if resolvers is None else None
        actual_resolver, resolver_handler = _runtime_handler(
            resolver_values.get(kind),
            implicit_capability=implicit,
        )
        actual_verifier, verifier_handler = _runtime_handler(verifier_values.get(kind))
        if resolver_handler is None or actual_resolver is None:
            errors.append(
                f"evidence type {kind!r} runtime resolver capability unavailable: "
                f"expected {expected_resolver}"
            )
        elif actual_resolver != expected_resolver:
            errors.append(
                f"evidence type {kind!r} runtime resolver capability mismatch: "
                f"expected {expected_resolver}, got {actual_resolver}"
            )
        if verifier_handler is None or actual_verifier is None:
            errors.append(
                f"evidence type {kind!r} runtime verifier capability unavailable: "
                f"expected {expected_verifier}"
            )
        elif actual_verifier != expected_verifier:
            errors.append(
                f"evidence type {kind!r} runtime verifier capability mismatch: "
                f"expected {expected_verifier}, got {actual_verifier}"
            )
    return errors, len(required_kinds)


def normalize_check(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return check(UNKNOWN, "INVALID_CHECK")
    status = value.get("status")
    codes = value.get("codes")
    if status not in {PASS, FAIL, UNKNOWN} or not isinstance(codes, list) or not all(
        isinstance(code, str) for code in codes
    ):
        return check(UNKNOWN, "INVALID_CHECK")
    return {"status": status, "codes": list(codes)}


def normalize_resolver_checks(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, Mapping) else {}
    return {name: normalize_check(source.get(name)) for name in _RESOLVER_LAYERS}


def evaluate_evidence(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    resolvers: Mapping[str, Resolver] | None = None,
    verifiers: Mapping[str, Verifier] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve and verify one evidence object without exposing trusted inputs."""

    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)

    baseline_evidence = deepcopy(dict(evidence))
    baseline_criterion = deepcopy(dict(criterion))
    baseline_contract = deepcopy(dict(contract))
    evidence_id = baseline_evidence.get("evidence_id")
    kind_value = baseline_evidence.get("kind")
    kind = kind_value if isinstance(kind_value, str) else ""

    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return _malformed_evidence_result(evidence_id, kind, "MALFORMED_EVIDENCE_ID")
    if not isinstance(kind_value, str) or not kind_value.strip():
        return _malformed_evidence_result(
            evidence_id,
            kind,
            "MALFORMED_EVIDENCE_KIND",
        )

    resolver_value = dict(default_resolvers() if resolvers is None else resolvers).get(kind)
    _, resolver = _runtime_handler(resolver_value)
    if resolver is None:
        checks = {
            "resolve": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "integrity_and_freshness": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "scope": check(UNKNOWN, "UNSUPPORTED_KIND"),
        }
    else:
        try:
            resolver_output = resolver(
                deepcopy(baseline_evidence),
                deepcopy(baseline_criterion),
                deepcopy(baseline_contract),
                observed_now,
            )
        except Exception as exc:
            failure = _callback_exception_check(exc, phase="resolver")
            checks = {name: deepcopy(failure) for name in _RESOLVER_LAYERS}
        else:
            checks = normalize_resolver_checks(resolver_output)

    _, verifier = _runtime_handler(dict(verifiers or {}).get(kind))
    if verifier is None or not all(value["status"] == PASS for value in checks.values()):
        checks["claim"] = check(UNKNOWN, "CLAIM_NOT_VERIFIED")
    else:
        try:
            verifier_output = verifier(
                deepcopy(baseline_evidence),
                deepcopy(baseline_criterion),
                deepcopy(checks),
            )
        except Exception as exc:
            checks["claim"] = _callback_exception_check(exc, phase="verifier")
        else:
            checks["claim"] = normalize_check(verifier_output)

    status = _aggregate_status(value["status"] for value in checks.values())
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "status": status,
        "checks": checks,
    }


def canonical_json_bytes(value: Any) -> bytes:
    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            return str(item)
        if isinstance(item, float):
            raise TypeError("floats are not supported")
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("object keys must be strings")
            keys = sorted(item, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
            return "{" + ",".join(f"{encode(key)}:{encode(item[key])}" for key in keys) + "}"
        raise TypeError(f"unsupported JSON value: {type(item).__name__}")

    return encode(value).encode("utf-8")


def default_resolvers() -> dict[str, Resolver]:
    return {
        "file": _resolve_file,
        "git-commit": _resolve_git_commit,
        "test-report": _resolve_test_report,
        "url": _resolve_url,
    }


def _aggregate_status(statuses: Any) -> str:
    values = list(statuses)
    return FAIL if FAIL in values else UNKNOWN if UNKNOWN in values else PASS


def _malformed_evidence_result(evidence_id: Any, kind: str, code: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "status": FAIL,
        "checks": {
            "resolve": check(FAIL, code),
            "integrity_and_freshness": check(UNKNOWN, code),
            "scope": check(UNKNOWN, code),
            "claim": check(UNKNOWN, code),
        },
    }


def _callback_exception_check(exc: Exception, *, phase: str) -> dict[str, Any]:
    if isinstance(exc, PermissionError):
        return check(UNKNOWN, "PERMISSION_DENIED")
    if isinstance(exc, FileNotFoundError):
        return check(FAIL, "NOT_FOUND")
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return check(UNKNOWN, "RESOLVER_TIMEOUT" if phase == "resolver" else "VERIFIER_TIMEOUT")
    if isinstance(exc, OSError):
        return check(UNKNOWN, "TRANSIENT_IO")
    return check(UNKNOWN, "RESOLVER_ERROR" if phase == "resolver" else "VERIFIER_ERROR")


def _resolve_file(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    path, path_check = _local_path(evidence, contract)
    integrity = _freshness_check(evidence, criterion, now)
    if path_check["status"] == PASS and path is not None:
        actual, digest_check = _bounded_file_digest(path)
        integrity = _merge_checks(integrity, digest_check)
        if digest_check["status"] == PASS:
            expected = evidence.get("artifact_digest")
            if not isinstance(expected, str) or not _DIGEST_RE.fullmatch(expected) or expected != actual:
                integrity = _merge_checks(integrity, check(FAIL, "DIGEST_MISMATCH"))
    return {
        "resolve": path_check,
        "integrity_and_freshness": integrity,
        "scope": _merge_checks(
            _scope_check(evidence, criterion),
            _envelope_revision_check(evidence, criterion, contract),
        ),
    }


def _resolve_test_report(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    path, path_check = _local_path(evidence, contract)
    integrity = _freshness_check(evidence, criterion, now)
    scope = _scope_check(evidence, criterion)
    report: Mapping[str, Any] | None = None

    if path_check["status"] == PASS and path is not None:
        raw, read_check = _bounded_file_bytes(path)
        integrity = _merge_checks(integrity, read_check)
        if read_check["status"] != PASS:
            scope = _merge_checks(scope, read_check)
        elif raw is not None:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                integrity = _merge_checks(integrity, check(FAIL, "INVALID_TEST_REPORT"))
                scope = _merge_checks(scope, check(UNKNOWN, "INVALID_TEST_REPORT"))
            else:
                if isinstance(parsed, Mapping):
                    report = parsed
                else:
                    integrity = _merge_checks(integrity, check(FAIL, "INVALID_TEST_REPORT"))
                    scope = _merge_checks(scope, check(UNKNOWN, "INVALID_TEST_REPORT"))

    if report is not None:
        report_scope = report.get("scope")
        report_time = _parse_utc_time(report.get("generated_at"))
        report_revision = report.get("repo_revision")
        valid_shape = (
            report.get("schema") == "context-test-report/v1"
            and isinstance(report.get("command"), str)
            and bool(str(report["command"]).strip())
            and isinstance(report.get("exit_status"), int)
            and not isinstance(report.get("exit_status"), bool)
            and report_time is not None
            and "repo_revision" in report
            and (
                report_revision is None
                or isinstance(report_revision, str)
                and _COMMIT_RE.fullmatch(report_revision) is not None
            )
            and isinstance(report_scope, Mapping)
        )
        if not valid_shape:
            integrity = _merge_checks(integrity, check(FAIL, "INVALID_TEST_REPORT"))
        if report.get("exit_status") != 0:
            integrity = _merge_checks(integrity, check(FAIL, "NONZERO_EXIT_STATUS"))

        if report_time is not None:
            report_evidence = dict(evidence)
            report_evidence["generated_at"] = report.get("generated_at")
            integrity = _merge_checks(integrity, _freshness_check(report_evidence, criterion, now))

        if isinstance(report_scope, Mapping):
            scope = _merge_checks(scope, _scope_check({"scope": report_scope}, criterion))
        else:
            scope = _merge_checks(scope, check(FAIL, "SCOPE_MISMATCH"))

        if isinstance(report_revision, str):
            scope = _merge_checks(scope, _revision_relation_check(report_revision, criterion, contract))
        else:
            required_revision, _, revision_error = _revision_requirement(criterion)
            if revision_error is not None:
                scope = _merge_checks(scope, revision_error)
            elif required_revision is not None:
                scope = _merge_checks(scope, check(FAIL, "REVISION_MISMATCH"))

        envelope_revision = evidence.get("repo_revision")
        if envelope_revision is not None and envelope_revision != report_revision:
            scope = _merge_checks(scope, check(FAIL, "REVISION_MISMATCH"))

        expected = report.get("artifact_digest")
        payload = dict(report)
        payload.pop("artifact_digest", None)
        try:
            actual = f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"
        except TypeError:
            actual = ""
        if not isinstance(expected, str) or not _DIGEST_RE.fullmatch(expected) or expected != actual:
            integrity = _merge_checks(integrity, check(FAIL, "DIGEST_MISMATCH"))

    return {
        "resolve": path_check,
        "integrity_and_freshness": integrity,
        "scope": scope,
    }


def _resolve_git_commit(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    locator = evidence.get("locator")
    workspace = contract.get("workspace_root")
    if not isinstance(locator, str) or not _COMMIT_RE.fullmatch(locator):
        resolution = check(FAIL, "MALFORMED_LOCATOR")
    elif not isinstance(workspace, (str, Path)):
        resolution = check(FAIL, "INVALID_WORKSPACE_ROOT")
    else:
        completed, launch_check = _run_git(
            ["git", "-C", str(workspace), "cat-file", "-e", f"{locator}^{{commit}}"]
        )
        if launch_check is not None:
            resolution = launch_check
        elif completed is not None and completed.returncode == 0:
            resolution = check(PASS)
        elif completed is not None and completed.returncode in {1, 128}:
            resolution = check(FAIL, "NOT_FOUND")
        else:
            resolution = check(UNKNOWN, "GIT_ERROR")

    scope = _scope_check(evidence, criterion)
    if isinstance(locator, str) and _COMMIT_RE.fullmatch(locator):
        scope = _merge_checks(scope, _revision_relation_check(locator, criterion, contract))
    return {
        "resolve": resolution,
        "integrity_and_freshness": _freshness_check(evidence, criterion, now),
        "scope": scope,
    }


def _resolve_url(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    return {
        "resolve": _url_syntax_check(evidence.get("locator")),
        "integrity_and_freshness": _freshness_check(evidence, criterion, now),
        "scope": _merge_checks(
            _scope_check(evidence, criterion),
            _envelope_revision_check(evidence, criterion, contract),
        ),
    }


def _local_path(
    evidence: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[Path | None, dict[str, Any]]:
    workspace_value = contract.get("workspace_root")
    locator = evidence.get("locator")
    if not isinstance(workspace_value, (str, Path)) or not isinstance(locator, str) or not locator:
        return None, check(FAIL, "MALFORMED_LOCATOR")
    path_text = locator.split("#", 1)[0]
    if not path_text or "\x00" in path_text:
        return None, check(FAIL, "MALFORMED_LOCATOR")
    try:
        workspace = Path(workspace_value).expanduser().resolve()
        candidate = Path(path_text).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        target = candidate.resolve()
        roots = [workspace]
        evidence_roots = contract.get("evidence_roots", [])
        if isinstance(evidence_roots, list):
            roots.extend(
                Path(root).expanduser().resolve()
                for root in evidence_roots
                if isinstance(root, (str, Path))
            )
    except PermissionError:
        return None, check(UNKNOWN, "PERMISSION_DENIED")
    except FileNotFoundError:
        return None, check(FAIL, "NOT_FOUND")
    except (OSError, RuntimeError):
        return None, check(UNKNOWN, "TRANSIENT_IO")
    if not any(target == root or root in target.parents for root in roots):
        return None, check(FAIL, "OUTSIDE_ALLOWED_ROOT")
    try:
        if not target.is_file():
            return None, check(FAIL, "NOT_FOUND")
    except PermissionError:
        return None, check(UNKNOWN, "PERMISSION_DENIED")
    except FileNotFoundError:
        return None, check(FAIL, "NOT_FOUND")
    except OSError:
        return None, check(UNKNOWN, "TRANSIENT_IO")
    return target, check(PASS)


def _bounded_file_bytes(path: Path) -> tuple[bytes | None, dict[str, Any]]:
    chunks: list[bytes] = []
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(LOCAL_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_LOCAL_ARTIFACT_BYTES:
                    return None, check(FAIL, "ARTIFACT_TOO_LARGE")
                chunks.append(chunk)
    except PermissionError:
        return None, check(UNKNOWN, "PERMISSION_DENIED")
    except FileNotFoundError:
        return None, check(FAIL, "NOT_FOUND")
    except OSError:
        return None, check(UNKNOWN, "TRANSIENT_IO")
    return b"".join(chunks), check(PASS)


def _bounded_file_digest(path: Path) -> tuple[str | None, dict[str, Any]]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(LOCAL_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_LOCAL_ARTIFACT_BYTES:
                    return None, check(FAIL, "ARTIFACT_TOO_LARGE")
                digest.update(chunk)
    except PermissionError:
        return None, check(UNKNOWN, "PERMISSION_DENIED")
    except FileNotFoundError:
        return None, check(FAIL, "NOT_FOUND")
    except OSError:
        return None, check(UNKNOWN, "TRANSIENT_IO")
    return f"sha256:{digest.hexdigest()}", check(PASS)


def _scope_check(evidence: Mapping[str, Any], criterion: Mapping[str, Any]) -> dict[str, Any]:
    required_value = criterion.get("required_scope", {})
    if not isinstance(required_value, Mapping):
        return check(FAIL, "SCOPE_MISMATCH")
    control_keys = {"repo_revision", "revision", "revision_match", "revision_mode"}
    required = {key: value for key, value in required_value.items() if key not in control_keys}
    if not required:
        return check(PASS)
    actual = evidence.get("scope")
    if not isinstance(actual, Mapping):
        return check(FAIL, "SCOPE_MISMATCH")
    if any(key not in actual or actual[key] != value for key, value in required.items()):
        return check(FAIL, "SCOPE_MISMATCH")
    return check(PASS)


def _freshness_check(
    evidence: Mapping[str, Any], criterion: Mapping[str, Any], now: datetime
) -> dict[str, Any]:
    result = check(PASS)
    kind = str(evidence.get("kind") or "")
    maximum = criterion.get("max_evidence_age_seconds")
    overrides = criterion.get("evidence_freshness_by_type")
    if overrides is not None and not isinstance(overrides, Mapping):
        result = _merge_checks(result, check(FAIL, "INVALID_FRESHNESS_WINDOW"))
    elif isinstance(overrides, Mapping) and kind in overrides:
        maximum = overrides[kind]
    if maximum is not None and (type(maximum) is not int or maximum < 0):
        result = _merge_checks(result, check(FAIL, "INVALID_FRESHNESS_WINDOW"))

    generated_value = evidence.get("generated_at")
    generated_at = _parse_utc_time(generated_value)
    if generated_value is not None and generated_at is None:
        result = _merge_checks(result, check(FAIL, "INVALID_GENERATED_AT"))
    elif generated_at is not None and generated_at > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        result = _merge_checks(result, check(FAIL, "FUTURE_GENERATED_AT"))

    expires_value = evidence.get("expires_at")
    expires_at = _parse_utc_time(expires_value)
    if expires_value is not None:
        if expires_at is None:
            result = _merge_checks(result, check(FAIL, "INVALID_EXPIRES_AT"))
        elif now >= expires_at:
            result = _merge_checks(result, check(FAIL, "STALE"))

    if maximum is not None and type(maximum) is int and maximum >= 0:
        if generated_value is None:
            result = _merge_checks(result, check(FAIL, "MISSING_GENERATED_AT"))
        elif generated_at is not None:
            age_seconds = max(0.0, (now - generated_at).total_seconds())
            if age_seconds > maximum:
                result = _merge_checks(result, check(FAIL, "STALE"))
    return result


def _parse_utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _UTC_RFC3339_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _merge_checks(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    left = normalize_check(first)
    right = normalize_check(second)
    status = _aggregate_status((left["status"], right["status"]))
    codes: list[str] = []
    for code in [*left["codes"], *right["codes"]]:
        if code not in codes:
            codes.append(code)
    return check(status, *codes)


def _revision_requirement(
    criterion: Mapping[str, Any],
) -> tuple[str | None, str, dict[str, Any] | None]:
    scope = criterion.get("required_scope")
    scope_mapping = scope if isinstance(scope, Mapping) else {}
    revision_values = [
        value
        for value in (
            criterion.get("required_revision"),
            criterion.get("required_repo_revision"),
            scope_mapping.get("repo_revision"),
            scope_mapping.get("revision"),
        )
        if value is not None
    ]
    unique_revisions = {str(value) for value in revision_values}
    if len(unique_revisions) > 1:
        return None, "exact", check(FAIL, "INVALID_REVISION_REQUIREMENT")
    required = next(iter(unique_revisions), None)
    if required is not None and _COMMIT_RE.fullmatch(required) is None:
        return None, "exact", check(FAIL, "INVALID_REVISION_REQUIREMENT")

    mode_values = [
        value
        for value in (
            criterion.get("revision_match"),
            criterion.get("revision_mode"),
            scope_mapping.get("revision_match"),
            scope_mapping.get("revision_mode"),
        )
        if value is not None
    ]
    unique_modes = {str(value) for value in mode_values}
    if len(unique_modes) > 1:
        return required, "exact", check(FAIL, "INVALID_REVISION_REQUIREMENT")
    mode = next(iter(unique_modes), "exact")
    if mode not in {"exact", "ancestor"}:
        return required, mode, check(FAIL, "INVALID_REVISION_REQUIREMENT")
    if required is None and mode_values:
        return None, mode, check(FAIL, "INVALID_REVISION_REQUIREMENT")
    return required, mode, None


def _revision_relation_check(
    actual_revision: str,
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    required, mode, error = _revision_requirement(criterion)
    if error is not None:
        return error
    if required is None:
        return check(PASS)
    if _COMMIT_RE.fullmatch(actual_revision) is None:
        return check(FAIL, "REVISION_MISMATCH")
    if mode == "exact":
        return (
            check(PASS)
            if actual_revision.lower() == required.lower()
            else check(FAIL, "REVISION_MISMATCH")
        )

    workspace = contract.get("workspace_root")
    if not isinstance(workspace, (str, Path)):
        return check(FAIL, "INVALID_WORKSPACE_ROOT")
    completed, launch_check = _run_git(
        [
            "git",
            "-C",
            str(workspace),
            "merge-base",
            "--is-ancestor",
            actual_revision,
            required,
        ]
    )
    if launch_check is not None:
        return launch_check
    if completed is not None and completed.returncode == 0:
        return check(PASS)
    if completed is not None and completed.returncode == 1:
        return check(FAIL, "REVISION_MISMATCH")
    return check(UNKNOWN, "GIT_ERROR")


def _envelope_revision_check(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    required, _, error = _revision_requirement(criterion)
    if error is not None:
        return error
    if required is None:
        return check(PASS)
    actual = evidence.get("repo_revision")
    if not isinstance(actual, str):
        return check(FAIL, "REVISION_MISMATCH")
    return _revision_relation_check(actual, criterion, contract)


def _run_git(arguments: list[str]) -> tuple[subprocess.CompletedProcess[Any] | None, dict[str, Any] | None]:
    try:
        completed = subprocess.run(
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, check(UNKNOWN, "TOOL_UNAVAILABLE")
    except PermissionError:
        return None, check(UNKNOWN, "PERMISSION_DENIED")
    except subprocess.TimeoutExpired:
        return None, check(UNKNOWN, "GIT_TIMEOUT")
    except OSError:
        return None, check(UNKNOWN, "GIT_LAUNCH_ERROR")
    return completed, None


def _url_syntax_check(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, str) or not locator:
        return check(FAIL, "MALFORMED_LOCATOR")
    if not _URI_CHARS_RE.fullmatch(locator) or _BAD_PERCENT_ESCAPE_RE.search(locator):
        return check(FAIL, "MALFORMED_LOCATOR")
    try:
        parsed = urlsplit(locator)
        raw_host = parsed.hostname
        port = parsed.port
    except ValueError:
        return check(FAIL, "MALFORMED_LOCATOR")
    if parsed.scheme != "https":
        return check(FAIL, "HTTPS_REQUIRED")
    if parsed.username is not None or parsed.password is not None:
        return check(FAIL, "CREDENTIALS_FORBIDDEN")
    if raw_host is None or not parsed.netloc or port is not None and not 1 <= port <= 65535:
        return check(FAIL, "MALFORMED_LOCATOR")

    host = raw_host.rstrip(".").lower()
    if not host:
        return check(FAIL, "MALFORMED_LOCATOR")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return check(FAIL, "NON_PUBLIC_ADDRESS")
    if address is None:
        if host == "localhost" or host.endswith(".localhost"):
            return check(FAIL, "NON_PUBLIC_ADDRESS")
        if _AMBIGUOUS_NUMERIC_HOST_RE.fullmatch(host):
            return check(FAIL, "NON_PUBLIC_ADDRESS")
        if not _valid_dns_host(host):
            return check(FAIL, "MALFORMED_LOCATOR")
    return check(UNKNOWN, "NETWORK_BLOCKED")


def _valid_dns_host(host: str) -> bool:
    if not host.isascii() or not host or len(host) > 253:
        return False
    return all(_DNS_LABEL_RE.fullmatch(label) is not None for label in host.split("."))
