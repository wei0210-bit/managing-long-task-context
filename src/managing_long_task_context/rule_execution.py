"""Opt-in execution of publisher-selected strict rules."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from ._experience_store import InputError as ExperienceInputError
from .experience import bind_experience
from .truth_sources import _safe_locator, _valid_workspace_root, resolve_file_source


CAPABILITY = "rule-execution/v1"
_ROOT_FIELDS = frozenset({"schema", "rules"})
_RULE_FIELDS = frozenset({
    "rule_id", "experience_ref", "severity", "applies_at", "trigger_id",
    "checker_id", "checker_version", "observation_source_id",
})
_REF_FIELDS = frozenset({"experience_id", "revision", "store_root"})
_SOURCE_REF_FIELDS = frozenset({"path", "sha256"})
_STAGES = frozenset({"release", "resume", "handoff", "completion"})
_EXPLICIT_UTC_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z"
)


def rule_execution_enabled(contract: Mapping[str, Any]) -> bool:
    capabilities = contract.get("required_capabilities")
    return (
        "rule_execution" in contract
        and isinstance(capabilities, list)
        and CAPABILITY in capabilities
    )


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown_fields(value: Mapping[str, Any], allowed: frozenset[str]) -> list[str]:
    return sorted(set(value) - allowed)


def _valid_experience_ref(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping) or _unknown_fields(value, _REF_FIELDS):
        return False
    return (
        _non_empty_string(value.get("experience_id"))
        and type(value.get("revision")) is int and value["revision"] > 0
        and _non_empty_string(value.get("store_root"))
    )


def validate_rule_execution_contract(contract: Mapping[str, Any]) -> list[str]:
    """Return deterministic errors for the sealed opt-in rule declaration."""
    has_rules = "rule_execution" in contract
    capabilities = contract.get("required_capabilities")
    has_capability = isinstance(capabilities, list) and CAPABILITY in capabilities
    if not has_rules and not has_capability:
        return []

    errors: list[str] = []
    if has_rules and not has_capability:
        errors.append("contract.rule_execution requires required_capabilities rule-execution/v1")
    if has_capability and not has_rules:
        errors.append("contract.required_capabilities rule-execution/v1 requires rule_execution")
        return errors
    if not _valid_workspace_root(contract.get("workspace_root")):
        errors.append("contract.workspace_root must be an existing absolute non-symlink directory")

    root = contract.get("rule_execution")
    if not isinstance(root, Mapping):
        errors.append("contract.rule_execution must be an object")
        return errors
    unknown = _unknown_fields(root, _ROOT_FIELDS)
    if unknown:
        errors.append(f"contract.rule_execution has unknown fields: {unknown}")
    if type(root.get("schema")) is not int or root.get("schema") != 1:
        errors.append("contract.rule_execution.schema must equal 1")
    rules = root.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("contract.rule_execution.rules must be a non-empty list")
        return errors
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        path = f"contract.rule_execution.rules[{index}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{path} must be an object")
            continue
        unknown = _unknown_fields(rule, _RULE_FIELDS)
        if unknown:
            errors.append(f"{path} has unknown fields: {unknown}")
        missing = sorted(_RULE_FIELDS - set(rule))
        if missing:
            errors.append(f"{path} is missing required fields: {missing}")
        rule_id = rule.get("rule_id")
        if not _non_empty_string(rule_id):
            errors.append(f"{path}.rule_id must be a non-empty string")
        elif rule_id in seen:
            errors.append(f"contract.rule_execution.rules has duplicate rule_id: {rule_id}")
        else:
            seen.add(rule_id)
        if not _valid_experience_ref(rule.get("experience_ref")):
            errors.append(f"{path}.experience_ref must be null or a complete experience reference")
        severity = rule.get("severity")
        if not isinstance(severity, str) or severity not in {"advisory", "load-bearing"}:
            errors.append(f"{path}.severity must be advisory or load-bearing")
        applies_at = rule.get("applies_at")
        if (
            not isinstance(applies_at, list) or not applies_at
            or any(not isinstance(item, str) or item not in _STAGES for item in applies_at)
            or len(applies_at) != len(set(applies_at))
        ):
            errors.append(f"{path}.applies_at must be a non-empty unique list of gate stages")
        for field in ("trigger_id", "checker_id", "checker_version", "observation_source_id"):
            if not _non_empty_string(rule.get(field)):
                errors.append(f"{path}.{field} must be a non-empty string")
    return errors


def _result(status: str, *codes: str) -> dict[str, Any]:
    return {"status": status, "codes": list(codes)}


def _callback(runtime: object, name: str) -> Callable[..., Any] | None:
    candidate = runtime.get(name) if isinstance(runtime, Mapping) else getattr(runtime, name, None)
    return candidate if callable(candidate) else None


def _call(callback: Callable[..., Any] | None, *args: Any) -> dict[str, Any]:
    if callback is None:
        return _result("unknown", "RULE_RUNTIME_UNAVAILABLE")
    try:
        value = callback(*args)
    except TimeoutError:
        return _result("unknown", "CALLBACK_TIMEOUT")
    except Exception:
        return _result("unknown", "CALLBACK_ERROR")
    if not isinstance(value, Mapping):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    status = value.get("status")
    codes = value.get("codes")
    if not isinstance(status, str) or status not in {"pass", "fail", "unknown"} or not isinstance(codes, list) or not all(
        isinstance(code, str) for code in codes
    ):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    return {"status": status, "codes": list(codes)}


def _call_observe(callback: Callable[..., Any] | None, task_id: str, stage: str, source_id: str) -> dict[str, Any]:
    if callback is None:
        return _result("unknown", "RULE_RUNTIME_UNAVAILABLE")
    try:
        value = callback(task_id, stage, source_id)
    except TimeoutError:
        return _result("unknown", "CALLBACK_TIMEOUT")
    except Exception:
        return _result("unknown", "CALLBACK_ERROR")
    if not isinstance(value, Mapping):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    required = {"status", "codes", "coverage", "scope", "observed_at", "expires_at", "source_refs", "payload"}
    if set(value) != required or not isinstance(value.get("status"), str) or value.get("status") not in {"pass", "fail", "unknown"}:
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("codes"), list) or not all(isinstance(code, str) for code in value["codes"]):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("coverage"), str) or value.get("coverage") not in {"complete", "partial", "unknown"} or not _non_empty_string(value.get("scope")):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("source_refs"), list) or not isinstance(value.get("payload"), Mapping):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    return deepcopy(dict(value))


def _call_applies(callback: Callable[..., Any] | None, rule: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    if callback is None:
        return _result("unknown", "RULE_RUNTIME_UNAVAILABLE")
    try:
        value = callback(deepcopy(dict(rule)), deepcopy(dict(observation)))
    except TimeoutError:
        return _result("unknown", "CALLBACK_TIMEOUT")
    except Exception:
        return _result("unknown", "CALLBACK_ERROR")
    if not isinstance(value, Mapping) or set(value) != {"status", "codes", "source_refs"}:
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("status"), str) or value.get("status") not in {"applicable", "not_applicable", "unknown"}:
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("codes"), list) or not all(isinstance(code, str) for code in value["codes"]):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    if not isinstance(value.get("source_refs"), list):
        return _result("unknown", "CALLBACK_INVALID_RESULT")
    return deepcopy(dict(value))


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or _EXPLICIT_UTC_RFC3339_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _sources_status(workspace_root: str | Path, refs: object) -> tuple[str, list[str], list[dict[str, str]]]:
    if not isinstance(refs, list) or not refs:
        return "unknown", ["OBSERVATION_SOURCE_MISSING"], []
    public_refs: list[dict[str, str]] = []
    for ref in refs:
        if not isinstance(ref, Mapping) or set(ref) != _SOURCE_REF_FIELDS:
            return "unknown", ["CALLBACK_INVALID_RESULT"], []
        path = ref.get("path")
        sha256 = ref.get("sha256")
        if not isinstance(path, str) or not isinstance(sha256, str) or len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            return "unknown", ["CALLBACK_INVALID_RESULT"], []
        try:
            raw_path = Path(path)
            resolved_path = raw_path.resolve(strict=True)
            if not raw_path.is_absolute() or str(raw_path) != str(resolved_path):
                return "unknown", ["CALLBACK_INVALID_RESULT"], []
            locator = resolved_path.relative_to(Path(workspace_root).resolve()).as_posix()
        except (OSError, ValueError):
            return "unknown", ["CALLBACK_INVALID_RESULT"], []
        if not _safe_locator(locator):
            return "unknown", ["CALLBACK_INVALID_RESULT"], []
        outcome = resolve_file_source(workspace_root, {"kind": "file", "locator": locator})
        if outcome.get("status") == "fail":
            return "fail", [str(outcome.get("code") or "OBSERVATION_SOURCE_INVALID")], []
        if outcome.get("status") != "pass":
            return "unknown", [str(outcome.get("code") or "OBSERVATION_SOURCE_INVALID")], []
        if outcome.get("fingerprint") != "sha256:" + sha256:
            return "fail", ["OBSERVATION_SOURCE_CHANGED"], []
        public_refs.append({"path": str(resolved_path), "sha256": sha256})
    return "pass", [], public_refs


def _rule_report(rule_id: str, status: str, codes: list[str], refs: list[dict[str, str]]) -> dict[str, Any]:
    return {"rule_id": rule_id, "status": status, "codes": codes, "source_refs": refs}


def _experience_reference(
    workspace_root: object, reference: object,
) -> tuple[dict[str, Any], str | None]:
    """Read the current selected experience without trusting a host callback."""
    if not isinstance(workspace_root, str) or not _valid_experience_ref(reference):
        return _result("unknown", "EXPERIENCE_REFERENCE_UNAVAILABLE"), None
    assert isinstance(reference, Mapping)
    store_root = Path(str(reference["store_root"]))
    if not store_root.is_absolute():
        return _result("unknown", "EXPERIENCE_REFERENCE_UNAVAILABLE"), None
    try:
        result = bind_experience(workspace_root, store_root).get(
            str(reference["experience_id"]), int(reference["revision"]),
        )
    except (ExperienceInputError, OSError, ValueError, TypeError):
        return _result("unknown", "EXPERIENCE_REFERENCE_UNAVAILABLE"), None
    if not isinstance(result, Mapping):
        return _result("unknown", "EXPERIENCE_REFERENCE_UNAVAILABLE"), None
    status, codes, data = result.get("status"), result.get("codes"), result.get("data")
    if status != "pass" or not isinstance(codes, list) or not isinstance(data, Mapping):
        safe_codes = [code for code in codes if isinstance(code, str) and code] if isinstance(codes, list) else []
        return _result("unknown", *(safe_codes or ["EXPERIENCE_REFERENCE_UNAVAILABLE"])), None
    validity = data.get("validity")
    if (
        data.get("experience_id") != reference["experience_id"]
        or data.get("revision") != reference["revision"]
        or data.get("latest_revision") != reference["revision"]
        or data.get("status") != "approved"
        or not isinstance(data.get("record_digest"), str)
        or not isinstance(validity, Mapping)
        or validity.get("status") != "pass"
    ):
        return _result("unknown", "EXPERIENCE_NOT_CURRENT_APPROVED"), None
    return _result("pass"), str(data["record_digest"])


def evaluate_rule_execution(
    contract: Mapping[str, Any], task_id: str, stage: str, rule_runtime: object,
    *, now: datetime,
) -> dict[str, Any]:
    """Evaluate selected rules outside the task lock using a sealed contract copy."""
    declared = contract.get("rule_execution")
    rules = declared.get("rules") if isinstance(declared, Mapping) else []
    selected = [deepcopy(rule) for rule in rules if isinstance(rule, Mapping) and stage in rule.get("applies_at", [])]
    reports: list[dict[str, Any]] = []
    recheck_refs: list[dict[str, Any]] = []
    experience_rechecks: dict[str, tuple[object, str]] = {}
    all_complete = True
    workspace_root = contract.get("workspace_root")
    for rule in selected:
        rule_id = str(rule.get("rule_id"))
        experience_ref = rule.get("experience_ref")
        experience_digest: str | None = None
        if experience_ref is not None:
            experience, experience_digest = _experience_reference(workspace_root, experience_ref)
            if experience["status"] != "pass":
                reports.append(_rule_report(rule_id, experience["status"], list(experience["codes"]), []))
                all_complete = False
                continue
            assert experience_digest is not None
            experience_rechecks[rule_id] = (deepcopy(experience_ref), experience_digest)
            verified = _call(_callback(rule_runtime, "verify_experience"), deepcopy(experience_ref))
            if verified["status"] != "pass":
                reports.append(_rule_report(rule_id, verified["status"], list(verified["codes"]), []))
                all_complete = False
                continue
        observation = _call_observe(_callback(rule_runtime, "observe"), task_id, stage, str(rule["observation_source_id"]))
        if observation.get("status") == "fail":
            reports.append(_rule_report(rule_id, "fail", list(observation["codes"]), []))
            all_complete = False
            continue
        if observation.get("status") != "pass":
            reports.append(_rule_report(rule_id, "unknown", list(observation["codes"]), []))
            all_complete = False
            continue
        if observation.get("coverage") != "complete":
            code = "OBSERVATION_COVERAGE_PARTIAL" if observation.get("coverage") == "partial" else "OBSERVATION_COVERAGE_UNKNOWN"
            reports.append(_rule_report(rule_id, "unknown", [code], []))
            all_complete = False
            continue
        observed_at = _parse_time(observation.get("observed_at"))
        expires_at = _parse_time(observation.get("expires_at"))
        observed_now = datetime.now(timezone.utc)
        if observed_at is None or expires_at is None or observed_at > expires_at or observed_at > observed_now or expires_at < observed_now:
            reports.append(_rule_report(rule_id, "unknown", ["OBSERVATION_EXPIRED"], []))
            all_complete = False
            continue
        source_status, source_codes, source_refs = _sources_status(workspace_root, observation.get("source_refs"))
        if source_status != "pass":
            reports.append(_rule_report(rule_id, source_status, source_codes, source_refs))
            all_complete = False
            continue
        applies = _call_applies(_callback(rule_runtime, "applies"), rule, observation)
        if applies.get("status") == "unknown":
            reports.append(_rule_report(rule_id, "unknown", list(applies["codes"]), source_refs))
            all_complete = False
            continue
        applies_status, applies_codes, applies_refs = _sources_status(workspace_root, applies.get("source_refs"))
        if applies_status != "pass":
            reports.append(_rule_report(rule_id, applies_status, applies_codes, source_refs))
            all_complete = False
            continue
        locked_recheck = {
            "rule_id": rule_id,
            "source_refs": deepcopy(source_refs + applies_refs),
            "expires_at": expires_at.isoformat(),
        }
        if applies["status"] == "not_applicable":
            reports.append(_rule_report(rule_id, "not_applicable", list(applies["codes"]), applies_refs))
            recheck_refs.append(locked_recheck)
            continue
        checked = _call(
            _callback(rule_runtime, "check"), deepcopy(rule), deepcopy(observation),
        )
        if experience_ref is not None:
            current_experience, current_digest = _experience_reference(workspace_root, experience_ref)
            if current_experience["status"] != "pass" or current_digest != experience_digest:
                reports.append(_rule_report(rule_id, "unknown", ["INPUT_CHANGED"], source_refs))
                all_complete = False
                continue
        reports.append(_rule_report(rule_id, checked["status"], list(checked["codes"]), source_refs))
        recheck_refs.append(locked_recheck)
        if checked["status"] != "pass":
            all_complete = False
    for index, report in enumerate(reports):
        recheck = experience_rechecks.get(report["rule_id"])
        if recheck is None:
            continue
        reference, expected_digest = recheck
        current_experience, current_digest = _experience_reference(workspace_root, reference)
        if current_experience["status"] != "pass" or current_digest != expected_digest:
            reports[index] = _rule_report(report["rule_id"], "unknown", ["INPUT_CHANGED"], report["source_refs"])
            all_complete = False
    return {"rules": reports, "coverage": "complete" if all_complete else "unknown", "recheck_refs": recheck_refs}


def recheck_rule_sources(contract: Mapping[str, Any], recheck_refs: object, *, now: datetime) -> set[str]:
    """Return rule IDs whose trusted source material changed before final verdict."""
    changed: set[str] = set()
    workspace_root = contract.get("workspace_root")
    if not isinstance(recheck_refs, list):
        return changed
    for entry in recheck_refs:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("rule_id"), str):
            continue
        expires_at = _parse_time(entry.get("expires_at"))
        source_status, _, _ = _sources_status(workspace_root, entry.get("source_refs"))
        if expires_at is None or expires_at < now or source_status != "pass":
            changed.add(entry["rule_id"])
    return changed
