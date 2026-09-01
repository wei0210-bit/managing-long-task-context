#!/usr/bin/env python3
"""Recommend a Context mode without loading one or authorizing any action."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FIELDS = {
    "risk_facts_complete",
    "multi_turn",
    "single_primary_agent",
    "high_risk",
    "auditability_required",
    "frozen_acceptance",
    "independent_validation",
    "external_side_effects",
    "multiple_state_writers",
}
STRICT_TRIGGERS = (
    "high_risk",
    "auditability_required",
    "frozen_acceptance",
    "independent_validation",
    "external_side_effects",
    "multiple_state_writers",
)


def route(value: Mapping[str, Any]) -> dict[str, object]:
    errors: list[dict[str, str]] = []
    unknown = sorted(set(value) - FIELDS)
    if unknown:
        errors.append({"code": "ROUTE_UNKNOWN_FIELD", "message": ",".join(unknown)})
    missing = sorted(FIELDS - set(value))
    if missing:
        errors.append({"code": "ROUTE_MISSING_FIELD", "message": ",".join(missing)})
    invalid = sorted(key for key in FIELDS & set(value) if not isinstance(value[key], bool))
    if invalid:
        errors.append({"code": "ROUTE_FIELD_NOT_BOOLEAN", "message": ",".join(invalid)})
    if errors:
        return {
            "status": "invalid",
            "codes": sorted({item["code"] for item in errors}),
            "errors": errors,
            "automatic_injection": False,
            "external_action_authorized": False,
            "selection_authority": "user",
        }

    reasons: list[str] = []
    if not value["risk_facts_complete"]:
        recommendation = "STRICT_REQUIRED"
        reasons.append("risk_facts_incomplete")
    else:
        reasons.extend(trigger for trigger in STRICT_TRIGGERS if value[trigger])
        if not value["single_primary_agent"]:
            reasons.append("single_primary_agent_false")
        if reasons:
            recommendation = "STRICT_REQUIRED"
        elif value["multi_turn"]:
            recommendation = "LITE_RECOMMENDED"
            reasons.append("low_risk_single_agent_multi_turn")
        else:
            recommendation = "NO_SKILL"
            reasons.append("single_turn_static")
    return {
        "status": "ready",
        "recommendation": recommendation,
        "reasons": reasons,
        "automatic_injection": False,
        "human_confirmation_required": recommendation != "NO_SKILL",
        "external_action_authorized": False,
        "selection_authority": "user",
        "reroute_on_scope_change": True,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("input must be a JSON object")
        report = route(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "status": "invalid",
            "codes": ["ROUTE_INPUT_INVALID"],
            "errors": [{"code": "ROUTE_INPUT_INVALID", "message": type(exc).__name__}],
            "automatic_injection": False,
            "external_action_authorized": False,
            "selection_authority": "user",
        }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
