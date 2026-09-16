"""Independent synthetic host fixtures for E3 record seams; never production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import managing_long_task_context as context


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class RegisteredHost:
    """Reads fixed fixture state; it does not derive authority from requests."""

    def __init__(self, fixture: "LedgerFixture") -> None:
        self.fixture = fixture
        self.task_id = fixture.task_id
        self.identity = object()
        self.registered_runtime_identity = self.identity
        self.state_path = fixture.workspace / "host-state.json"
        self.state_path.write_text(
            json.dumps(
                {
                    "identity": "registered-host-1",
                    "exclusive": True,
                    "authorized": True,
                    "thread_state": "idle",
                }
            ),
            encoding="utf-8",
        )
        self.registered_attempts = {"attempt-001", "attempt-002"}
        self.registered_requests = {
            attempt: fixture.request(attempt_id=attempt)
            for attempt in self.registered_attempts
        }

    def observe_execution_state(
        self, request: dict[str, object], operation: str
    ) -> dict[str, object]:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if request.get(
            "attempt_id"
        ) not in self.registered_attempts or request != self.registered_requests.get(
            request.get("attempt_id")
        ):
            return {"status": "unknown"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "status": "pass",
            "task_id": self.fixture.task_id,
            "attempt_id": request.get("attempt_id"),
            "thread_id": request.get("thread_id"),
            "workspace_root": str(self.fixture.workspace.resolve()),
            "baseline": self.fixture.baseline,
            "controller_generation": 0,
            "identity_status": "pass",
            "authorization_status": "pass" if state.get("authorized", True) else "fail",
            "host_identity_ref": {
                "registered_identity_id": state["identity"],
                "sha256": digest(state["identity"]),
            },
            "exclusivity_status": "exclusive" if state["exclusive"] else "busy",
            "thread_state": state["thread_state"],
            "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (
                now + timedelta(seconds=state.get("ttl_seconds", 60))
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "observation_ref": {
                "ref_id": "host-state",
                "uri": self.state_path.as_uri(),
                "sha256": hashlib.sha256(self.state_path.read_bytes()).hexdigest(),
            },
            "request_binding_sha256": digest(
                {
                    key: request[key]
                    for key in ("task_id", "attempt_id", "thread_id", "workspace_root")
                }
            ),
        }


class LedgerFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.base_dir, self.workspace = root / "context", root / "workspace"
        self.workspace.mkdir()
        self.task_id, self.baseline = "E3-LEDGER", "baseline-e3"
        now = datetime.now(timezone.utc).replace(microsecond=0)
        context.publish_contract(
            {
                "schema": 1,
                "task_id": self.task_id,
                "version": 1,
                "issued_by": "publisher",
                "issued_at": (now - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "authorized_approvers": [],
                "objective": "E3 synthetic ledger",
                "scope": ["synthetic"],
                "out_of_scope": ["business"],
                "constraints": ["no business action"],
                "workspace_root": str(self.workspace.resolve()),
                "acceptance_criteria": [
                    {
                        "id": "AC-E3",
                        "criterion": "synthetic",
                        "required_evidence_types": ["file"],
                        "required_scope": {
                            "task_id": self.task_id,
                            "criterion_id": "AC-E3",
                        },
                    }
                ],
                "actor_roles": {"controller": ["executor"]},
            },
            confirmed_by="publisher",
            base_dir=self.base_dir,
        )
        self.host = RegisteredHost(self)

    def close(self) -> None:
        self.tmp.cleanup()

    def request(
        self, *, attempt_id: str = "attempt-001", thread_id: str | None = None
    ) -> dict[str, object]:
        contract = json.loads(
            (self.base_dir / self.task_id / "task-contract.json").read_text(
                encoding="utf-8"
            )
        )
        return {
            "task_id": self.task_id,
            "attempt_id": attempt_id,
            "contract_version": 1,
            "contract_digest": contract["seal"]["integrity_digest"].removeprefix(
                "sha256:"
            ),
            "baseline": self.baseline,
            "workspace_root": str(self.workspace.resolve()),
            "controller_generation": 0,
            "thread_id": thread_id,
            "argv_sha256": "a" * 64,
            "config_digest": "b" * 64,
            "prompt_sha256": "c" * 64,
            "authorization_digest": "d" * 64,
        }

    def observation(self, attempt_id: str = "attempt-001") -> dict[str, object]:
        state = json.loads(self.host.state_path.read_text(encoding="utf-8"))
        observed_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        return {
            "task_id": self.task_id,
            "attempt_id": attempt_id,
            "reservation_id": "resv." + attempt_id,
            "operation": "start_child",
            "argv_sha256": "a" * 64,
            "cwd": str(self.workspace.resolve()),
            "thread_id": None,
            "exit_status": 0,
            "timeout": None,
            "observed_at": observed_at,
            "stdout": "synthetic controlled stdout\n",
            "stdout_digest": hashlib.sha256(
                b"synthetic controlled stdout\n"
            ).hexdigest(),
            "stdout_bytes": len(b"synthetic controlled stdout\n"),
            "stdout_utf8": True,
            "host_identity_ref": {
                "registered_identity_id": state["identity"],
                "sha256": digest(state["identity"]),
            },
            "host_exclusivity_status": "exclusive",
            "host_observed_at": observed_at,
            "host_observation_ref": {
                "ref_id": "host-state",
                "uri": self.host.state_path.as_uri(),
                "sha256": hashlib.sha256(self.host.state_path.read_bytes()).hexdigest(),
            },
            "stderr_digest": hashlib.sha256(b"").hexdigest(),
            "stderr_bytes": 0,
            "output_over_limit": False,
        }
