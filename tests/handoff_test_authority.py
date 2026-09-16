"""Synthetic authority for existing read-path integration tests; never production."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class SyntheticChildAuthority:
    """Permit only the explicit old read-tests' child observations and updates.

    Identity is an independently registered in-process token. Policy constants
    and expected file contents are not obtained from the authorization request.
    """

    def __init__(self, *, base_dir, workspace, record):
        self.identity = object()
        self.base_dir = str(Path(base_dir).resolve())
        self.workspace = Path(workspace).resolve()
        self.record = deepcopy(record)
        self.allowed_items = set()

    def authorize(self, request):
        if request.get("runtime_identity") is not self.identity:
            return {"status": "unknown"}
        expected = {
            "task_id": self.record["task_id"], "base_dir": self.base_dir,
            "workspace_root": str(self.workspace),
            **{key: self.record[key] for key in (
                "contract_version", "contract_digest", "controller_generation",
                "handoff_id", "package_manifest_sha256")},
        }
        if any(type(request.get(key)) is not type(value) or request.get(key) != value
               for key, value in expected.items()):
            return {"status": "unknown"}
        for filename, content in {"source.txt": "source identity",
                                  "target.txt": "target identity",
                                  "authorization.txt": "delegated scope"}.items():
            if (self.workspace / filename).read_text(encoding="utf-8") != content:
                return {"status": "unknown"}
        arguments = request.get("arguments")
        if not isinstance(arguments, dict) or request.get("arguments_sha256") != _digest(arguments):
            return {"status": "unknown"}
        operation = request.get("operation")
        if operation == "record":
            allowed = arguments.get("statement") in {
                "handoff replayed observation", "writer progressed during verification"}
            allowed = allowed and arguments.get("item_type") == "observation"
        elif operation == "update_item":
            allowed = (arguments.get("item_id") in self.allowed_items
                       and arguments.get("metadata") == {"reviewed": True})
        elif operation == "checkpoint":
            allowed = (arguments.get("phase") == "handoff-check"
                       and set(arguments.get("related_item_ids", [])) <= self.allowed_items)
        else:
            allowed = False
        if not allowed:
            return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "status": "pass", **expected, "operation": operation,
            "arguments_sha256": _digest(arguments), "purpose": "progress",
            "subject_id": "synthetic:registered-child", "role": "child",
            "scope_digest": _digest({"work_item": "read-path-regression",
                                     "allowed": ["record", "update_item", "checkpoint"]}),
            "work_item_id": "read-path-regression",
            **{key: deepcopy(self.record[key]) for key in (
                "source_session_ref", "target_session_ref", "authorization_ref")},
            "target_activation_status": "not_activated",
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
