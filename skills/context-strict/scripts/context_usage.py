#!/usr/bin/env python3
"""Read bounded, explicit local context-usage observations without taking action.

The module deliberately has no provider client, state file, polling loop, or
business action. Callers own any durable ``previous`` value used for local
notification deduplication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_INPUT_BYTES = 1024 * 1024
MAX_EVENTS = 1000
_USAGE_FIELDS = frozenset(
    {
        "event_id",
        "session_id",
        "task_id",
        "provider",
        "model",
        "mode",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cache_accounting",
        "source_ref",
        "observed_at",
    }
)
_PRESSURE_FIELDS = frozenset(
    {
        "session_id",
        "sample_id",
        "observed_at",
        "expires_at",
        "window_tokens",
        "used_tokens",
        "reserve_tokens",
        "growth_tokens",
        "basis",
        "safe_point",
        "task_complete",
        "execution_unknown",
        "milestone",
    }
)
_COUNT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
_SAFETY_FIELDS = ("safe_point", "task_complete", "execution_unknown", "milestone")
_PRESSURE_COUNT_FIELDS = (
    "window_tokens",
    "used_tokens",
    "reserve_tokens",
    "growth_tokens",
)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        if value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _canonical(value: object) -> bytes | None:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None


def _usage_unknown(*codes: str) -> dict[str, object]:
    return {
        "status": "unknown",
        "codes": sorted(set(codes)) or ["USAGE_UNKNOWN"],
        "total_tokens": None,
        "input_tokens": None,
        "normalized_input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "used_event_count": None,
        "observed_event_count": None,
        "session_count": None,
        "task_total_tokens": None,
        "cost": None,
        "skill_attribution": None,
        "measurement": "unknown",
    }


def _valid_usage_event(value: object) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, "USAGE_EVENT_INVALID"
    if _USAGE_FIELDS - set(value):
        return None, "USAGE_FIELD_MISSING"
    for key in ("event_id", "session_id", "task_id", "provider", "model", "source_ref"):
        if not isinstance(value[key], str) or not value[key]:
            return None, "USAGE_IDENTIFIER_INVALID"
    if not isinstance(value["mode"], str) or value["mode"] not in {
        "delta",
        "cumulative",
    }:
        return None, "USAGE_MODE_INVALID"
    if not isinstance(value["cache_accounting"], str) or value[
        "cache_accounting"
    ] not in {"included", "separate"}:
        return None, "CACHE_ACCOUNTING_INVALID"
    if any(not _is_count(value[key]) for key in _COUNT_FIELDS):
        return None, "USAGE_COUNT_INVALID"
    if (
        value["cache_accounting"] == "included"
        and value["cache_read_tokens"] + value["cache_write_tokens"]
        > value["input_tokens"]
    ):
        return None, "CACHE_INCLUDED_EXCEEDS_INPUT"
    observed = _parse_time(value["observed_at"])
    if observed is None:
        return None, "USAGE_TIME_INVALID"
    copied = dict(value)
    copied["_observed"] = observed
    return copied, None


def _event_total(item: Mapping[str, Any]) -> int:
    cache_total = item["cache_read_tokens"] + item["cache_write_tokens"]
    return (
        item["input_tokens"]
        + item["output_tokens"]
        + (cache_total if item["cache_accounting"] == "separate" else 0)
    )


def summarize_usage(events: Iterable[Mapping[str, Any]]) -> dict[str, object]:
    """Summarize complete normalized observations without claiming task coverage."""
    if isinstance(events, (str, bytes)):
        return _usage_unknown("USAGE_INPUT_INVALID")
    try:
        iterator = iter(events)
    except TypeError:
        return _usage_unknown("USAGE_INPUT_INVALID")
    supplied: list[Mapping[str, Any]] = []
    try:
        for raw in iterator:
            supplied.append(raw)
            if len(supplied) > MAX_EVENTS:
                return _usage_unknown("USAGE_RECORD_LIMIT")
    except (RuntimeError, TypeError):
        return _usage_unknown("USAGE_INPUT_INVALID")
    if not supplied:
        return _usage_unknown("USAGE_MISSING")
    unique: dict[str, dict[str, Any]] = {}
    for raw in supplied:
        canonical = _canonical(raw)
        if canonical is None:
            return _usage_unknown("USAGE_EVENT_NOT_JSON")
        item, error = _valid_usage_event(raw)
        if error is not None or item is None:
            return _usage_unknown(error or "USAGE_EVENT_INVALID")
        prior = unique.get(item["event_id"])
        if prior is not None:
            prior_canonical = _canonical(
                {key: value for key, value in prior.items() if key != "_observed"}
            )
            if canonical != prior_canonical:
                return _usage_unknown("EVENT_ID_CONFLICT")
            continue
        unique[item["event_id"]] = item
    sessions: dict[str, list[dict[str, Any]]] = {}
    for item in unique.values():
        sessions.setdefault(item["session_id"], []).append(item)
    used: list[dict[str, Any]] = []
    for records in sessions.values():
        signatures = {
            (
                item["mode"],
                item["provider"],
                item["model"],
                item["cache_accounting"],
                item["task_id"],
            )
            for item in records
        }
        if len(signatures) != 1:
            return _usage_unknown("SESSION_MEASUREMENT_CONFLICT")
        if records[0]["mode"] == "delta":
            used.extend(records)
            continue
        ordered = sorted(records, key=lambda item: item["_observed"])
        for before, after in zip(ordered, ordered[1:]):
            if before["_observed"] == after["_observed"]:
                return _usage_unknown("CUMULATIVE_TIME_CONFLICT")
            if any(after[field] < before[field] for field in _COUNT_FIELDS):
                return _usage_unknown("CUMULATIVE_ROLLBACK")
        used.append(ordered[-1])
    totals = {field: sum(item[field] for item in used) for field in _COUNT_FIELDS}
    normalized_input = sum(
        item["input_tokens"]
        + (
            item["cache_read_tokens"] + item["cache_write_tokens"]
            if item["cache_accounting"] == "separate"
            else 0
        )
        for item in used
    )
    return {
        "status": "ok",
        "codes": [],
        "total_tokens": sum(_event_total(item) for item in used),
        **totals,
        "normalized_input_tokens": normalized_input,
        "used_event_count": len(used),
        "observed_event_count": len(unique),
        "session_count": len(sessions),
        "task_total_tokens": None,
        "cost": None,
        "skill_attribution": None,
        "measurement": "observed",
    }


def _pressure_result(
    decision: str,
    reason: str,
    *,
    estimated: bool | None,
    dedup_key: str | None = None,
    notify: bool = False,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    return {
        "decision": decision,
        "reason": reason,
        "estimated": estimated,
        "dedup_key": dedup_key,
        "notify": notify,
        "automatic_action": False,
        "previous": copy.deepcopy(dict(previous)) if previous is not None else None,
    }


def _valid_pressure_sample(
    sample: object, now: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(sample, Mapping):
        return None, "PRESSURE_INPUT_INVALID"
    if _PRESSURE_FIELDS - set(sample):
        return None, "PRESSURE_FIELD_MISSING"
    for key in ("session_id", "sample_id"):
        if not isinstance(sample[key], str) or not sample[key]:
            return None, "PRESSURE_IDENTIFIER_INVALID"
    if any(not _is_count(sample[key]) for key in _PRESSURE_COUNT_FIELDS):
        return None, "PRESSURE_COUNT_INVALID"
    if sample["used_tokens"] > sample["window_tokens"]:
        return None, "PRESSURE_WINDOW_EXCEEDED"
    if not isinstance(sample["basis"], str) or sample["basis"] not in {
        "current-window",
        "estimate",
    }:
        return None, "PRESSURE_BASIS_INVALID"
    if sample.get("mode") == "cumulative" or sample.get("usage_mode") == "cumulative":
        return None, "CUMULATIVE_WINDOW_REJECTED"
    if any(not isinstance(sample[key], bool) for key in _SAFETY_FIELDS):
        return None, "PRESSURE_SAFETY_INVALID"
    observed = _parse_time(sample["observed_at"])
    expires = _parse_time(sample["expires_at"])
    if observed is None or expires is None:
        return None, "PRESSURE_TIME_INVALID"
    if observed > now:
        return None, "PRESSURE_OBSERVED_IN_FUTURE"
    if expires < observed:
        return None, "PRESSURE_TIME_ORDER_INVALID"
    copied = dict(sample)
    copied["_observed"] = observed
    copied["_expires"] = expires
    return copied, None


def _next_previous(
    sample: Mapping[str, Any], fingerprint: str, dedup_key: str, notified: bool
) -> dict[str, object]:
    return {
        "session_id": sample["session_id"],
        "sample_id": sample["sample_id"],
        "fingerprint": fingerprint,
        "dedup_key": dedup_key,
        "notified": notified,
        "observed_at": sample["observed_at"],
        "window_tokens": sample.get("window_tokens"),
    }


def _previous_conflict(
    previous: object, sample: Mapping[str, Any], fingerprint: str
) -> tuple[bool, str | None]:
    if previous is None:
        return False, None
    if not isinstance(previous, Mapping):
        return False, "PREVIOUS_INVALID"
    if (
        previous.get("session_id") != sample["session_id"]
        or previous.get("sample_id") != sample["sample_id"]
    ):
        return False, None
    old_fingerprint = previous.get("fingerprint")
    if not isinstance(old_fingerprint, str):
        return False, "PREVIOUS_INVALID"
    if old_fingerprint != fingerprint:
        return False, "SAMPLE_CONFLICT"
    notified = previous.get("notified")
    if not isinstance(notified, bool):
        return False, "PREVIOUS_INVALID"
    return notified, None


def _safe_milestone_fallback(
    sample: object, now: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate only the relation and safety fields for a missing-window advisory.

    This path deliberately cannot produce a percentage or a ``prepare`` result.
    It is available only when the numerical pressure fields are absent or invalid;
    cumulative claims and unsafe/incomplete observations remain unknown.
    """
    if not isinstance(sample, Mapping):
        return None, "PRESSURE_INPUT_INVALID"
    basis = sample.get("basis")
    if not isinstance(basis, str) or basis not in {"current-window", "estimate"}:
        return None, "PRESSURE_BASIS_INVALID"
    if sample.get("mode") == "cumulative" or sample.get("usage_mode") == "cumulative":
        return None, "CUMULATIVE_WINDOW_REJECTED"
    for key in ("session_id", "sample_id"):
        if not isinstance(sample.get(key), str) or not sample[key]:
            return None, "PRESSURE_IDENTIFIER_INVALID"
    if any(key not in sample or not isinstance(sample[key], bool) for key in _SAFETY_FIELDS):
        return None, "PRESSURE_SAFETY_INVALID"
    observed = _parse_time(sample.get("observed_at"))
    expires = _parse_time(sample.get("expires_at"))
    if observed is None or expires is None:
        return None, "PRESSURE_TIME_INVALID"
    if observed > now:
        return None, "PRESSURE_OBSERVED_IN_FUTURE"
    if expires < observed:
        return None, "PRESSURE_TIME_ORDER_INVALID"
    if sample["task_complete"]:
        return None, "TASK_COMPLETE"
    if sample["execution_unknown"]:
        return None, "EXECUTION_UNKNOWN"
    if not sample["safe_point"] or not sample["milestone"]:
        return None, "PRESSURE_MILESTONE_NOT_SAFE"
    return dict(sample), None


def _can_fallback_to_milestone(sample: object, error: str | None) -> bool:
    if error in {"PRESSURE_COUNT_INVALID", "PRESSURE_WINDOW_EXCEEDED"}:
        return True
    if error != "PRESSURE_FIELD_MISSING" or not isinstance(sample, Mapping):
        return False
    missing = _PRESSURE_FIELDS - set(sample)
    return bool(missing) and missing.issubset(_PRESSURE_COUNT_FIELDS)


def _milestone_fallback_result(
    sample: object, previous: object, now: datetime
) -> dict[str, object] | None:
    fallback, error = _safe_milestone_fallback(sample, now)
    if error is not None or fallback is None:
        return None
    encoded = _canonical(fallback)
    if encoded is None:
        return _pressure_result("unknown", "PRESSURE_SAMPLE_NOT_JSON", estimated=None)
    fingerprint = hashlib.sha256(encoded).hexdigest()
    dedup_key = f"{fallback['session_id']}:{fallback['sample_id']}:{fingerprint}"
    already_notified, previous_error = _previous_conflict(previous, fallback, fingerprint)
    if previous_error is not None:
        return _pressure_result(
            "unknown", previous_error, estimated=None, dedup_key=dedup_key,
        )
    notify = not already_notified
    next_previous = _next_previous(fallback, fingerprint, dedup_key, already_notified or notify)
    return _pressure_result(
        "milestone",
        "PRESSURE_MILESTONE_FALLBACK",
        estimated=None,
        dedup_key=dedup_key,
        notify=notify,
        previous=next_previous,
    )


def evaluate_pressure(
    sample: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    *,
    now: datetime,
) -> dict[str, object]:
    """Evaluate one current-window sample and return only a recommendation."""
    now_utc = _utc_datetime(now)
    if now_utc is None:
        return _pressure_result("unknown", "NOW_INVALID", estimated=None)
    normalized, error = _valid_pressure_sample(sample, now_utc)
    if error is not None or normalized is None:
        if _can_fallback_to_milestone(sample, error):
            fallback = _milestone_fallback_result(sample, previous, now_utc)
            if fallback is not None:
                return fallback
        return _pressure_result(
            "unknown", error or "PRESSURE_INPUT_INVALID", estimated=None
        )
    fingerprint_source = {
        key: value for key, value in normalized.items() if not key.startswith("_")
    }
    encoded = _canonical(fingerprint_source)
    if encoded is None:
        return _pressure_result("unknown", "PRESSURE_SAMPLE_NOT_JSON", estimated=None)
    fingerprint = hashlib.sha256(encoded).hexdigest()
    dedup_key = f"{normalized['session_id']}:{normalized['sample_id']}:{fingerprint}"
    already_notified, previous_error = _previous_conflict(previous, normalized, fingerprint)
    if previous_error is not None:
        return _pressure_result(
            "unknown",
            previous_error,
            estimated=normalized["basis"] == "estimate",
            dedup_key=dedup_key,
        )
    next_previous = _next_previous(normalized, fingerprint, dedup_key, already_notified)
    estimated = normalized["basis"] == "estimate"
    if normalized["task_complete"]:
        return _pressure_result(
            "defer",
            "TASK_COMPLETE",
            estimated=estimated,
            dedup_key=dedup_key,
            previous=next_previous,
        )
    if normalized["execution_unknown"]:
        return _pressure_result(
            "defer",
            "EXECUTION_UNKNOWN",
            estimated=estimated,
            dedup_key=dedup_key,
            previous=next_previous,
        )
    if now_utc > normalized["_expires"]:
        if normalized["safe_point"] and normalized["milestone"]:
            notify = not already_notified
            next_previous["notified"] = already_notified or notify
            return _pressure_result(
                "milestone",
                "PRESSURE_EXPIRED_SAFE_MILESTONE",
                estimated=estimated,
                dedup_key=dedup_key,
                notify=notify,
                previous=next_previous,
            )
        return _pressure_result(
            "defer",
            "PRESSURE_EXPIRED_NOT_SAFE",
            estimated=estimated,
            dedup_key=dedup_key,
            previous=next_previous,
        )
    if not normalized["safe_point"]:
        return _pressure_result(
            "defer",
            "NOT_SAFE_POINT",
            estimated=estimated,
            dedup_key=dedup_key,
            previous=next_previous,
        )
    remaining = normalized["window_tokens"] - normalized["used_tokens"]
    if remaining <= normalized["reserve_tokens"] + normalized["growth_tokens"]:
        notify = not already_notified
        next_previous["notified"] = already_notified or notify
        return _pressure_result(
            "prepare",
            "RESERVE_OR_GROWTH_THRESHOLD",
            estimated=estimated,
            dedup_key=dedup_key,
            notify=notify,
            previous=next_previous,
        )
    return _pressure_result(
        "defer",
        "PRESSURE_BELOW_THRESHOLD",
        estimated=estimated,
        dedup_key=dedup_key,
        previous=next_previous,
    )


class _DuplicateKey(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _load_input(path: Path) -> tuple[object | None, str | None]:
    try:
        metadata = os.lstat(path)
    except OSError:
        return None, "INPUT_READ_FAILED"
    if not stat.S_ISREG(metadata.st_mode):
        return None, "INPUT_NOT_REGULAR"
    if metadata.st_size > MAX_INPUT_BYTES:
        return None, "INPUT_TOO_LARGE"
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        )
    except OSError:
        return None, "INPUT_READ_FAILED"
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None, "INPUT_NOT_REGULAR"
        chunks: list[bytes] = []
        remaining = MAX_INPUT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_INPUT_BYTES:
            return None, "INPUT_TOO_LARGE"
    except OSError:
        return None, "INPUT_READ_FAILED"
    finally:
        os.close(descriptor)
    try:
        return (
            json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_no_duplicate_keys,
                parse_constant=_reject_constant,
            ),
            None,
        )
    except UnicodeDecodeError:
        return None, "INPUT_UTF8_INVALID"
    except _DuplicateKey:
        return None, "INPUT_DUPLICATE_KEY"
    except (json.JSONDecodeError, ValueError):
        return None, "INPUT_JSON_INVALID"


def _cli_unknown(code: str) -> dict[str, object]:
    return {"status": "unknown", "codes": [code], "automatic_action": False}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("summarize", "pressure"))
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="explicit regular JSON file (maximum 1 MiB)",
    )
    parser.add_argument(
        "--now",
        help="RFC3339 evaluation time for pressure; defaults to current UTC time",
    )
    args = parser.parse_args(argv)
    document, error = _load_input(args.input)
    if error is not None:
        report = _cli_unknown(error)
    elif not isinstance(document, dict):
        report = _cli_unknown("INPUT_DOCUMENT_INVALID")
    elif args.command == "summarize":
        report = (
            summarize_usage(document["events"])
            if set(document) == {"events"} and isinstance(document.get("events"), list)
            else _cli_unknown("SUMMARIZE_DOCUMENT_INVALID")
        )
    else:
        if (
            not set(document).issubset({"sample", "previous"})
            or "sample" not in document
        ):
            report = _cli_unknown("PRESSURE_DOCUMENT_INVALID")
        else:
            now = _parse_time(args.now) if args.now else datetime.now(timezone.utc)
            report = (
                _cli_unknown("CLI_NOW_INVALID")
                if now is None
                else evaluate_pressure(
                    document["sample"], document.get("previous"), now=now
                )
            )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return (
        2
        if report.get("status") == "unknown" or report.get("decision") == "unknown"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
