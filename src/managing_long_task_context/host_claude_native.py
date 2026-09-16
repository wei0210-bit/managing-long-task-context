"""Conservative boundary for the 2026-09-15 native Claude inventory snapshot."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_CONTROL_OPERATIONS = frozenset({"start", "resume", "takeover", "archive"})
_CAPABILITIES = {
    "schema": "native-host-capabilities/v1",
    "host": "claude-native",
    "evidence": {
        "source": "2026-09-15 native tool-inventory snapshot",
        "level": "tool-inventory",
        "observed_at": "2026-09-15",
        "scope": "snapshot of this call environment only; not runtime probing or end-to-end host validation",
        "real_host_validation": "NOT_RUN",
    },
    "capabilities": {
        "native_interface": {
            "status": "unavailable",
            "detail": "No native Claude sub-agent interface is exposed by the current host.",
        },
        "trusted_identity": {
            "status": "unknown",
            "detail": "No registered host identity receipt is available.",
        },
        "write_exclusivity": {
            "status": "unknown",
            "detail": "No global write-fencing receipt is available.",
        },
        "clean_history": {
            "status": "unknown",
            "detail": "No clean-session proof is available.",
        },
        "parent_survival": {
            "status": "unknown",
            "detail": "No parent exit behavior is available.",
        },
        "cross_parent_continue": {
            "status": "unknown",
            "detail": "No cross-parent resume or takeover interface is available.",
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
        "code": "NATIVE_NATIVE_INTERFACE_UNAVAILABLE",
        "operation": operation,
        "launch_allowed": False,
        "control_granted": False,
        "missing_capabilities": [
            "native_interface",
            "trusted_identity",
            "write_exclusivity",
            "clean_history",
            "parent_survival",
            "cross_parent_continue",
        ],
        "next_readonly_action": "Preserve the current session and inspect durable handoff records.",
    }
