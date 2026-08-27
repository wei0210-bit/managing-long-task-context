"""Deterministic, layered evidence resolution and independent claim verification."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

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


def check(status: str, *codes: str) -> dict[str, Any]:
    return {"status": status, "codes": list(codes)}


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
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    kind = str(evidence.get("kind") or "")
    resolver = dict(default_resolvers() if resolvers is None else resolvers).get(kind)
    if resolver is None:
        checks = {
            "resolve": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "integrity_and_freshness": check(UNKNOWN, "UNSUPPORTED_KIND"),
            "scope": check(UNKNOWN, "UNSUPPORTED_KIND"),
        }
    else:
        checks = normalize_resolver_checks(resolver(evidence, criterion, contract, observed_now))
    verifier = dict(verifiers or {}).get(kind)
    checks["claim"] = (
        normalize_check(verifier(evidence, criterion, checks))
        if verifier is not None and all(value["status"] == PASS for value in checks.values())
        else check(UNKNOWN, "CLAIM_NOT_VERIFIED")
    )
    statuses = [value["status"] for value in checks.values()]
    status = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else PASS
    return {"evidence_id": evidence.get("evidence_id"), "kind": kind, "status": status, "checks": checks}


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


def _resolve_file(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    path, path_check = _local_path(evidence, contract)
    integrity = _freshness_check(evidence, contract, now)
    if path_check["status"] == PASS and path is not None:
        expected = evidence.get("artifact_digest")
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if not isinstance(expected, str) or not _DIGEST_RE.fullmatch(expected) or expected != actual:
            integrity = _merge_fail(integrity, "DIGEST_MISMATCH")
    return {
        "resolve": path_check,
        "integrity_and_freshness": integrity,
        "scope": _scope_check(evidence, criterion),
    }


def _resolve_test_report(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    path, path_check = _local_path(evidence, contract)
    integrity = _freshness_check(evidence, contract, now)
    if path_check["status"] == PASS and path is not None:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            integrity = _merge_fail(integrity, "DIGEST_MISMATCH")
        else:
            if not isinstance(report, dict):
                integrity = _merge_fail(integrity, "DIGEST_MISMATCH")
            else:
                expected = report.get("artifact_digest")
                payload = dict(report)
                payload.pop("artifact_digest", None)
                try:
                    actual = f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"
                except TypeError:
                    actual = ""
                if not isinstance(expected, str) or not _DIGEST_RE.fullmatch(expected) or expected != actual:
                    integrity = _merge_fail(integrity, "DIGEST_MISMATCH")
    return {
        "resolve": path_check,
        "integrity_and_freshness": integrity,
        "scope": _scope_check(evidence, criterion),
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
        resolution = check(FAIL, "INVALID_LOCATOR")
    elif not isinstance(workspace, (str, Path)):
        resolution = check(FAIL, "INVALID_WORKSPACE_ROOT")
    else:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "-e", f"{locator}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        resolution = check(PASS) if completed.returncode == 0 else check(FAIL, "NOT_FOUND")
    return {
        "resolve": resolution,
        "integrity_and_freshness": _freshness_check(evidence, contract, now),
        "scope": _scope_check(evidence, criterion),
    }


def _resolve_url(
    evidence: Mapping[str, Any],
    criterion: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    locator = evidence.get("locator")
    resolution = _url_syntax_check(locator)
    return {
        "resolve": resolution,
        "integrity_and_freshness": _freshness_check(evidence, contract, now),
        "scope": _scope_check(evidence, criterion),
    }


def _local_path(
    evidence: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[Path | None, dict[str, Any]]:
    workspace_value = contract.get("workspace_root")
    locator = evidence.get("locator")
    if not isinstance(workspace_value, (str, Path)) or not isinstance(locator, str) or not locator:
        return None, check(FAIL, "INVALID_LOCATOR")
    workspace = Path(workspace_value).expanduser().resolve()
    candidate = Path(locator).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    target = candidate.resolve()
    roots = [workspace]
    evidence_roots = contract.get("evidence_roots", [])
    if isinstance(evidence_roots, list):
        roots.extend(Path(root).expanduser().resolve() for root in evidence_roots if isinstance(root, (str, Path)))
    if not any(target == root or root in target.parents for root in roots):
        return None, check(FAIL, "OUTSIDE_ALLOWED_ROOT")
    if not target.is_file():
        return None, check(FAIL, "NOT_FOUND")
    return target, check(PASS)


def _scope_check(evidence: Mapping[str, Any], criterion: Mapping[str, Any]) -> dict[str, Any]:
    required = criterion.get("required_scope", {})
    actual = evidence.get("scope")
    if not isinstance(required, Mapping) or not isinstance(actual, Mapping):
        return check(FAIL, "SCOPE_MISMATCH")
    if any(key not in actual or actual[key] != value for key, value in required.items()):
        return check(FAIL, "SCOPE_MISMATCH")
    return check(PASS)


def _freshness_check(
    evidence: Mapping[str, Any], contract: Mapping[str, Any], now: datetime
) -> dict[str, Any]:
    generated_at = _parse_time(evidence.get("generated_at"))
    expires_at = _parse_time(evidence.get("expires_at"))
    if expires_at is not None and now >= expires_at:
        return check(FAIL, "STALE")
    kind = str(evidence.get("kind") or "")
    maximum = contract.get("max_evidence_age_seconds")
    overrides = contract.get("evidence_freshness_by_type")
    if isinstance(overrides, Mapping) and kind in overrides:
        maximum = overrides[kind]
    if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) and generated_at is not None:
        if (now - generated_at).total_seconds() > maximum:
            return check(FAIL, "STALE")
    return check(PASS)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _merge_fail(existing: Mapping[str, Any], code: str) -> dict[str, Any]:
    codes = list(existing.get("codes", []))
    if code not in codes:
        codes.append(code)
    return check(FAIL, *codes)


def _url_syntax_check(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, str) or not locator:
        return check(FAIL, "INVALID_LOCATOR")
    try:
        parsed = urlsplit(locator)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return check(FAIL, "INVALID_LOCATOR")
    if parsed.scheme != "https":
        return check(FAIL, "HTTPS_REQUIRED")
    if parsed.username is not None or parsed.password is not None:
        return check(FAIL, "CREDENTIALS_FORBIDDEN")
    if host is None or not parsed.netloc or port is not None and not 1 <= port <= 65535:
        return check(FAIL, "INVALID_LOCATOR")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return check(FAIL, "NON_PUBLIC_ADDRESS")
    return check(UNKNOWN, "NETWORK_BLOCKED")
