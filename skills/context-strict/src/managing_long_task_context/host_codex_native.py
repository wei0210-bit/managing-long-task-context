"""Conservative boundary for the 2026-09-15 native Codex schema snapshot."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_CONTROL_OPERATIONS = frozenset({"start", "resume", "takeover", "archive"})
_CAPABILITIES = {
    "schema": "native-host-capabilities/v1",
    "host": "codex-native",
    "evidence": {
        "source": "2026-09-15 native collaboration tool-schema snapshot",
        "level": "schema-declared",
        "observed_at": "2026-09-15",
        "scope": "snapshot of this call environment only; not runtime probing or end-to-end host validation",
        "real_host_validation": "NOT_RUN",
    },
    "capabilities": {
        "same_parent_tree_addressing": {
            "status": "declared",
            "detail": "The schema declares spawn, list, message, wait, and interrupt within one parent tree.",
        },
        "history_mode": {
            "status": "declared",
            "detail": "fork_turns controls whether surrounding turns are passed to a child.",
        },
        "clean_history": {
            "status": "unknown",
            "detail": "A fork setting is not proof of a clean host session.",
        },
        "trusted_identity": {
            "status": "unknown",
            "detail": "No registered host identity receipt is exposed by the schema.",
        },
        "write_exclusivity": {
            "status": "unknown",
            "detail": "No global write-fencing receipt is exposed by the schema.",
        },
        "parent_survival": {
            "status": "unknown",
            "detail": "Parent exit effects are not exposed by the schema.",
        },
        "cross_parent_continue": {
            "status": "unknown",
            "detail": "No cross-parent resume or takeover interface is exposed by the schema.",
        },
    },
    "side_effects": {"host_calls": False, "task_writes": False, "model_calls": False},
}


def capabilities() -> dict[str, Any]:
    """Return a side-effect-free native-host capability inventory."""
    return deepcopy(_CAPABILITIES)


def request_control(operation: object) -> dict[str, Any]:
    """Refuse to claim native control without a trusted host bridge."""
    if not isinstance(operation, str) or operation not in _CONTROL_OPERATIONS:
        return {
            "status": "fail",
            "code": "NATIVE_CONTROL_INVALID_OPERATION",
            "launch_allowed": False,
            "control_granted": False,
            "next_readonly_action": "Read capabilities; do not execute the requested value.",
        }
    return {
        "status": "unknown",
        "support_status": "unsupported",
        "code": "NATIVE_TRUSTED_BRIDGE_UNAVAILABLE",
        "operation": operation,
        "launch_allowed": False,
        "control_granted": False,
        "missing_capabilities": [
            "trusted_identity",
            "write_exclusivity",
            "clean_history",
            "parent_survival",
            "cross_parent_continue",
        ],
        "next_readonly_action": "Preserve the current session and inspect durable handoff records.",
    }
