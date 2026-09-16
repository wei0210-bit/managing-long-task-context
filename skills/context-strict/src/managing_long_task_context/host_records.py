"""Bounded, event-backed E3 host attempt records."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, re, stat
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "host-task-ledger/v1"
EVENT_TYPES = frozenset(
    {
        "host-attempt-reserved",
        "host-attempt-observed",
        "host-result-published",
        "host-result-processed",
        "host-business-action-observed",
    }
)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I
)
_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_OPS = {"start_child", "resume_child"}


def _d(x: object) -> str:
    return hashlib.sha256(
        json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _okid(x: object) -> bool:
    return isinstance(x, str) and _ID.fullmatch(x) != None


def _oksha(x: object) -> bool:
    return isinstance(x, str) and _SHA.fullmatch(x) != None


def _reservation_id(attempt_id: str) -> str:
    return (
        "resv." + attempt_id
        if len(attempt_id) <= 91
        else "resv." + hashlib.sha256(attempt_id.encode("ascii")).hexdigest()
    )


def _utc(x: object) -> bool:
    try:
        return (
            isinstance(x, str)
            and _UTC.fullmatch(x) != None
            and datetime.fromisoformat(x.replace("Z", "+00:00")) is not None
        )
    except ValueError:
        return False


def _zulu() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _reply(
    status: str, code: str, attempt: str | None = None, **extra: Any
) -> dict[str, Any]:
    r = {
        "status": status,
        "launch_allowed": False,
        "reason_code": code,
        "current_state": "unknown",
        "readonly_action": "Read durable records; do not start or retry.",
    }
    r.update(extra)
    if attempt is not None:
        r["attempt_id"] = attempt
    return r


def _request(raw: object, op: str) -> tuple[dict[str, Any] | None, str | None]:
    if op not in _OPS:
        return None, "INVALID_OPERATION"
    if not isinstance(raw, Mapping):
        return None, "INVALID_REQUEST"
    r = dict(raw)
    need = {
        "task_id",
        "attempt_id",
        "contract_version",
        "contract_digest",
        "baseline",
        "workspace_root",
        "controller_generation",
        "thread_id",
        "argv_sha256",
        "config_digest",
        "prompt_sha256",
        "authorization_digest",
    }
    if set(r) != need or not _okid(r.get("task_id")) or not _okid(r.get("attempt_id")):
        return None, "INVALID_REQUEST"
    if (
        type(r.get("contract_version")) not in {int, float, str}
        or isinstance(r.get("contract_version"), bool)
        or not all(
            _oksha(r.get(k))
            for k in (
                "contract_digest",
                "argv_sha256",
                "config_digest",
                "prompt_sha256",
                "authorization_digest",
            )
        )
    ):
        return None, "INVALID_REQUEST"
    try:
        text_ok = (
            isinstance(r.get("baseline"), str)
            and isinstance(r.get("workspace_root"), str)
            and r["baseline"].encode("utf-8")
            and r["workspace_root"].encode("utf-8")
        )
    except UnicodeEncodeError:
        text_ok = False
    if (
        not text_ok
        or not (1 <= len(r["baseline"]) <= 128)
        or any(ord(c) < 32 for c in r["baseline"])
        or not r["workspace_root"].startswith("/")
        or type(r.get("controller_generation")) is not int
        or r["controller_generation"] < 0
    ):
        return None, "INVALID_REQUEST"
    if (op == "start_child" and r["thread_id"] is not None) or (
        op == "resume_child"
        and (
            not isinstance(r["thread_id"], str)
            or _UUID.fullmatch(r["thread_id"]) is None
        )
    ):
        return None, "THREAD_BINDING_INVALID"
    return r, None


def _host(
    raw: object, r: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, Mapping):
        return None, "HOST_OBSERVATION_UNAVAILABLE"
    h = dict(raw)
    need = {
        "status",
        "task_id",
        "attempt_id",
        "thread_id",
        "workspace_root",
        "baseline",
        "controller_generation",
        "identity_status",
        "authorization_status",
        "host_identity_ref",
        "exclusivity_status",
        "thread_state",
        "observed_at",
        "expires_at",
        "observation_ref",
        "request_binding_sha256",
    }
    if (
        set(h) != need
        or h.get("status") != "pass"
        or any(
            h.get(k) != r.get(k)
            for k in (
                "task_id",
                "attempt_id",
                "thread_id",
                "workspace_root",
                "baseline",
                "controller_generation",
            )
        )
        or h.get("request_binding_sha256")
        != _d(
            {k: r[k] for k in ("task_id", "attempt_id", "thread_id", "workspace_root")}
        )
    ):
        return None, "HOST_OBSERVATION_BINDING_MISMATCH"
    ident, ref = h.get("host_identity_ref"), h.get("observation_ref")
    if h.get("identity_status") != "pass" or h.get("authorization_status") != "pass":
        return None, "HOST_AUTHORIZATION_DENIED"
    if (
        not isinstance(ident, Mapping)
        or set(ident) != {"registered_identity_id", "sha256"}
        or not _okid(ident.get("registered_identity_id"))
        or not _oksha(ident.get("sha256"))
    ):
        return None, "HOST_IDENTITY_INVALID"
    if (
        not isinstance(ref, Mapping)
        or set(ref) != {"ref_id", "uri", "sha256"}
        or not _okid(ref.get("ref_id"))
        or not isinstance(ref.get("uri"), str)
        or not _oksha(ref.get("sha256"))
    ):
        return None, "HOST_OBSERVATION_INVALID"
    if (
        h.get("exclusivity_status") != "exclusive"
        or h.get("thread_state") not in {"idle", "not_found"}
        or not _utc(h.get("observed_at"))
        or not _utc(h.get("expires_at"))
    ):
        return None, "HOST_NOT_IDLE_OR_EXCLUSIVE"
    return h, None


def _observation_matches_reservation(
    observation: Mapping[str, Any], reservation: Mapping[str, Any]
) -> bool:
    request = reservation.get("request")
    if not isinstance(request, Mapping):
        return False
    operation = reservation.get("operation")
    observed_thread = observation.get("thread_id")
    if operation == "start_child":
        thread_matches = observed_thread is None or (
            isinstance(observed_thread, str)
            and _UUID.fullmatch(observed_thread) is not None
        )
    else:
        thread_matches = observed_thread is None or observed_thread == request.get(
            "thread_id"
        )
    try:
        return (
            observation.get("task_id") == request.get("task_id")
            and observation.get("attempt_id") == request.get("attempt_id")
            and observation.get("reservation_id") == reservation.get("reservation_id")
            and observation.get("operation") == reservation.get("operation")
            and observation.get("argv_sha256") == request.get("argv_sha256")
            and thread_matches
            and Path(str(observation.get("cwd"))).resolve(strict=True)
            == Path(str(request.get("workspace_root"))).resolve(strict=True)
        )
    except (OSError, RuntimeError):
        return False


def _result_bindings_match_request(
    bindings: object, request: Mapping[str, Any]
) -> bool:
    keys = {"contract_version", "contract_digest", "baseline", "workspace_root"}
    return (
        isinstance(bindings, Mapping)
        and set(bindings) == keys
        and all(bindings.get(key) == request.get(key) for key in keys)
    )


def _observation_proves_ended(
    observation: Mapping[str, Any], reservation: Mapping[str, Any]
) -> bool:
    if (
        observation.get("exit_status") != 0
        or observation.get("timeout") is not None
        or observation.get("stdout_utf8") is not True
        or observation.get("output_over_limit") is not False
    ):
        return False
    thread_id = observation.get("thread_id")
    if reservation.get("operation") == "start_child":
        return isinstance(thread_id, str) and _UUID.fullmatch(thread_id) is not None
    return thread_id == reservation.get("request", {}).get("thread_id")


def _attempt_is_superseded(
    events: Sequence[Mapping[str, Any]], attempt_id: str
) -> bool:
    """Later reservations make earlier attempt output historical, never current."""
    seen = False
    for event in events:
        if event.get("event_type") != "host-attempt-reserved":
            continue
        candidate = event.get("payload", {}).get("attempt_id")
        if candidate == attempt_id:
            seen = True
        elif seen:
            return True
    return False


def _child_owns_attempt(fence: object, attempt_id: str) -> bool:
    if fence is None:
        return True
    authorization = fence.get("authorization") if isinstance(fence, Mapping) else None
    return (
        not isinstance(authorization, Mapping)
        or authorization.get("role") != "child"
        or authorization.get("work_item_id") == attempt_id
    )


def _event_actor(fence: object, fallback: object) -> str:
    authorization = fence.get("authorization") if isinstance(fence, Mapping) else None
    subject = (
        authorization.get("subject_id") if isinstance(authorization, Mapping) else None
    )
    return subject if isinstance(subject, str) and subject.strip() else str(fallback)


def validate_host_event_history(
    events: Sequence[Mapping[str, Any]], *, task_id: str
) -> str | None:
    """Reject event combinations that a per-record schema cannot establish."""
    reservations: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if (
            event.get("task_id") != task_id
            or event.get("event_type") not in EVENT_TYPES
        ):
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            return "host event history payload is invalid"
        kind = event.get("event_type")
        attempt = payload.get("attempt_id")
        if not isinstance(attempt, str):
            return "host event history attempt is invalid"
        if kind == "host-attempt-reserved":
            previous = reservations.get(attempt)
            if previous is not None and previous.get("request_sha256") != payload.get(
                "request_sha256"
            ):
                return "host attempt reservation conflicts in authoritative events"
            reservations[attempt] = payload
        elif kind == "host-attempt-observed":
            reservation = reservations.get(attempt)
            observation = payload.get("observation")
            if not isinstance(reservation, Mapping) or not isinstance(
                observation, Mapping
            ):
                return "host observation has no authoritative reservation"
            if not _observation_matches_reservation(observation, reservation):
                return "host observation binding differs from reservation"
        elif kind == "host-result-published":
            reservation = reservations.get(attempt)
            if not isinstance(reservation, Mapping):
                return "host result has no authoritative reservation"
            matches = _result_bindings_match_request(
                payload.get("bindings"), reservation.get("request", {})
            )
            if not payload.get("late") and not matches:
                return "host result late flag differs from reservation binding"
    return None


def validate_host_event(p: object, *, task_id: str) -> str | None:
    if (
        not isinstance(p, Mapping)
        or p.get("type") not in EVENT_TYPES
        or p.get("task_id") != task_id
    ):
        return "host event identity invalid"
    x = dict(p)
    typ = x["type"]
    if typ == "host-attempt-reserved":
        need = {
            "schema",
            "type",
            "task_id",
            "attempt_id",
            "reservation_id",
            "operation",
            "request",
            "request_sha256",
            "host_observation",
            "created_at",
        }
        r, e = _request(x.get("request"), str(x.get("operation")))
        h, he = _host(x.get("host_observation"), r) if r else (None, "bad")
        if (
            set(x) != need
            or x.get("schema") != SCHEMA
            or not r
            or e
            or x.get("attempt_id") != r["attempt_id"]
            or x.get("reservation_id") != _reservation_id(r["attempt_id"])
            or x.get("request_sha256") != _d(r)
            or not h
            or he
            or not _utc(x.get("created_at"))
        ):
            return "host reservation payload invalid"
        return None
    if typ == "host-attempt-observed":
        need = {
            "schema",
            "type",
            "task_id",
            "attempt_id",
            "reservation_id",
            "observation",
            "observation_sha256",
            "archive_ref",
            "created_at",
        }
        ref = x.get("archive_ref")
        return (
            None
            if set(x) == need
            and x.get("schema") == SCHEMA
            and _okid(x.get("attempt_id"))
            and _okid(x.get("reservation_id"))
            and isinstance(x.get("observation"), Mapping)
            and x.get("observation_sha256") == _d(x["observation"])
            and isinstance(ref, Mapping)
            and set(ref) == {"uri", "sha256"}
            and isinstance(ref.get("uri"), str)
            and _oksha(ref.get("sha256"))
            and _utc(x.get("created_at"))
            else "host observation payload invalid"
        )
    if typ == "host-result-published":
        need = {
            "schema",
            "type",
            "task_id",
            "attempt_id",
            "result_version",
            "result_digest",
            "archive_ref",
            "bindings",
            "late",
            "created_at",
        }
        return (
            None
            if set(x) == need
            and x.get("schema") == SCHEMA
            and _okid(x.get("attempt_id"))
            and _okid(x.get("result_version"))
            and _oksha(x.get("result_digest"))
            and isinstance(x.get("archive_ref"), Mapping)
            and set(x["archive_ref"]) == {"uri", "sha256"}
            and isinstance(x["archive_ref"].get("uri"), str)
            and _oksha(x["archive_ref"].get("sha256"))
            and isinstance(x.get("bindings"), Mapping)
            and set(x["bindings"])
            == {"contract_version", "contract_digest", "baseline", "workspace_root"}
            and type(x.get("late")) is bool
            and _utc(x.get("created_at"))
            else "host result payload invalid"
        )
    if typ == "host-result-processed":
        need = {
            "schema",
            "type",
            "task_id",
            "attempt_id",
            "result_version",
            "result_digest",
            "basis_digest",
            "processing_status",
            "verdict",
            "created_at",
        }
        return (
            None
            if set(x) == need
            and x.get("schema") == SCHEMA
            and all(_oksha(x.get(k)) for k in ("result_digest", "basis_digest"))
            and x.get("processing_status") == "submitted"
            and x.get("verdict") in {"pass", "fail", "unknown"}
            and _utc(x.get("created_at"))
            else "host processing payload invalid"
        )
    need = {
        "schema",
        "type",
        "task_id",
        "attempt_id",
        "action_id",
        "action_status",
        "created_at",
    }
    return (
        None
        if set(x) == need
        and x.get("schema") == SCHEMA
        and _okid(x.get("attempt_id"))
        and _okid(x.get("action_id"))
        and x.get("action_status") in {"not_started", "executed", "execution_unknown"}
        and _utc(x.get("created_at"))
        else "host action payload invalid"
    )


def apply_host_event(
    snapshot: dict[str, Any], event: Mapping[str, Any]
) -> dict[str, Any]:
    records = snapshot.setdefault(
        "host_records", {"attempts": {}, "results": {}, "actions": {}}
    )
    p = event["payload"]
    kind = event["event_type"]
    if kind == "host-attempt-reserved":
        records["attempts"][p["attempt_id"]] = {
            "reservation": dict(p),
            "observations": [],
        }
    elif kind == "host-attempt-observed":
        records["attempts"].setdefault(
            p["attempt_id"], {"reservation": None, "observations": []}
        )["observations"].append(dict(p))
    elif kind.startswith("host-result"):
        s = records["results"].setdefault(
            p["attempt_id"] + ":" + p["result_version"],
            {"published": [], "processed": []},
        )
        s["published" if kind == "host-result-published" else "processed"].append(
            dict(p)
        )
    else:
        records["actions"][p["action_id"]] = dict(p)
    return snapshot


def _safe_archive(
    root: Path, relative: object, expected_sha: object, expected_content: object
) -> dict[str, Any] | None:
    """Read one archive without following links, blocking FIFOs, or unbounded input."""
    if (
        not isinstance(relative, str)
        or not _oksha(expected_sha)
        or not _oksha(expected_content)
    ):
        return None
    path = root / relative
    try:
        parent = path.parent.resolve(strict=True)
        if not parent.is_relative_to(root.resolve(strict=True)) or path.is_symlink():
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
                return None
            raw = stream.read(1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > 1024 * 1024 or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return None
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            return None
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"content"}
            or not isinstance(value["content"], str)
        ):
            return None
        if (
            hashlib.sha256(value["content"].encode("utf-8")).hexdigest()
            != expected_content
        ):
            return None
        return value
    except (
        OSError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        ValueError,
    ):
        return None


def _atomic_archive_json(
    root: Path,
    path: Path,
    value: Mapping[str, Any],
    *,
    mode: int | None = None,
) -> str:
    """Atomically persist one archive through no-follow directory descriptors."""
    relative = path.relative_to(root)
    parts = relative.parts
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or any("/" in part or "\x00" in part for part in parts)
    ):
        raise OSError("unsafe archive path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(root, directory_flags)
    temporary: str | None = None
    data = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        for part in parts[:-1]:
            try:
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                os.fsync(directory_fd)
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        target = parts[-1]
        try:
            existing = os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(existing.st_mode):
                raise OSError("archive target is not a regular file")
        temporary = f".{target}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o666 if mode is None else mode,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            target,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary = None
        os.fsync(directory_fd)
        return hashlib.sha256(data).hexdigest()
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


class HostTaskLedger:
    def __init__(
        self,
        base_dir: str | Path,
        host_observer: object,
        runtime_identity: object,
        write_authorizer: object,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.host_observer = host_observer
        self.runtime_identity = runtime_identity
        self.write_authorizer = write_authorizer
        self.task_id = getattr(host_observer, "task_id", None)

    def _capture(self, task: str):
        import managing_long_task_context as c

        paths = c._paths(task, self.base_dir)
        with c._shared_locked_existing(paths["root"]):
            return c, paths, c._handoff_strict_task_view_locked(task, paths)

    @staticmethod
    def _attempts(events: Sequence[Mapping[str, Any]]):
        out = {}
        for e in events:
            if e.get("event_type") == "host-attempt-reserved":
                out[e["payload"]["attempt_id"]] = e["payload"]
        return out

    @staticmethod
    def _unsafe_prior_attempt(
        events: Sequence[Mapping[str, Any]], current: str
    ) -> bool:
        """A replacement cannot bypass a running/unknown prior work unit."""
        reservations = HostTaskLedger._attempts(events)
        ended: set[str] = set()
        for event in events:
            payload = event.get("payload", {})
            if event.get("event_type") == "host-attempt-observed" and isinstance(
                payload, Mapping
            ):
                observation = payload.get("observation", {})
                reservation = reservations.get(str(payload.get("attempt_id")))
                if (
                    isinstance(observation, Mapping)
                    and isinstance(reservation, Mapping)
                    and _observation_matches_reservation(observation, reservation)
                    and _observation_proves_ended(observation, reservation)
                ):
                    ended.add(str(payload.get("attempt_id")))
            if (
                event.get("event_type") == "host-business-action-observed"
                and isinstance(payload, Mapping)
                and payload.get("action_status") == "execution_unknown"
            ):
                return True
        return any(
            attempt != current and attempt not in ended for attempt in reservations
        )

    def reserve(self, raw: object, op: str) -> dict[str, Any]:
        r, err = _request(raw, op)
        if not r:
            return _reply("fail", err or "INVALID_REQUEST")
        try:
            c, paths, v = self._capture(r["task_id"])
            if (
                v["contract_version"] != r["contract_version"]
                or v["contract_digest"] != r["contract_digest"]
                or Path(r["workspace_root"]).resolve(strict=True)
                != Path(v["contract"]["workspace_root"]).resolve(strict=True)
            ):
                return _reply("fail", "CONTRACT_OR_WORKSPACE_MISMATCH", r["attempt_id"])
            projection, projection_error = c._handoff_module._control_projection(
                v["events"], task_id=r["task_id"]
            )
            if projection_error is not None:
                return _reply("unknown", "HANDOFF_CONTROL_UNAVAILABLE", r["attempt_id"])
            if (
                projection["controls"]
                and r["controller_generation"] != projection["generation"]
            ):
                return _reply(
                    "unknown", "CONTROLLER_GENERATION_MISMATCH", r["attempt_id"]
                )
            old = self._attempts(v["events"]).get(r["attempt_id"])
            if old:
                return _reply(
                    "fail" if old["request_sha256"] != _d(r) else "pass",
                    (
                        "RESERVATION_IDENTITY_CONFLICT"
                        if old["request_sha256"] != _d(r)
                        else "ALREADY_RESERVED"
                    ),
                    r["attempt_id"],
                    reservation_id=old["reservation_id"],
                    current_state="reserved",
                )
            if self._unsafe_prior_attempt(v["events"], r["attempt_id"]):
                return _reply(
                    "unknown",
                    "PRIOR_ATTEMPT_IN_FLIGHT_OR_UNKNOWN",
                    r["attempt_id"],
                    current_state="in_flight",
                )
        except Exception:
            return _reply("unknown", "EVENT_UNAVAILABLE", r["attempt_id"])
        if (
            getattr(self.host_observer, "registered_runtime_identity", None)
            is not self.runtime_identity
        ):
            return _reply("unknown", "HOST_RUNTIME_IDENTITY_MISMATCH", r["attempt_id"])
        cb = getattr(self.host_observer, "observe_execution_state", None)
        try:
            h, he = _host(cb(dict(r), op) if callable(cb) else None, r)
        except Exception:
            h, he = None, "HOST_OBSERVATION_UNAVAILABLE"
        if not h:
            return _reply(
                "unknown", he or "HOST_OBSERVATION_UNAVAILABLE", r["attempt_id"]
            )
        if datetime.fromisoformat(
            h["expires_at"].replace("Z", "+00:00")
        ) < datetime.now(timezone.utc):
            return _reply("unknown", "HOST_OBSERVATION_EXPIRED", r["attempt_id"])
        try:
            try:
                fence = c._require_handoff_write_authorization(
                    r["task_id"],
                    base_dir=self.base_dir,
                    operation="host_reserve",
                    arguments={
                        "attempt_id": r["attempt_id"],
                        "operation": op,
                        "request_sha256": _d(r),
                    },
                    runtime_identity=self.runtime_identity,
                    write_authorizer=self.write_authorizer,
                )
            except Exception:
                if projection.get("pending") is not None:
                    return _reply(
                        "unknown",
                        "HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED",
                        r["attempt_id"],
                    )
                raise
            controls, control_error = c._handoff_module._control_events(
                v["events"], task_id=r["task_id"]
            )
            if control_error is not None:
                return _reply("unknown", "HANDOFF_CONTROL_UNAVAILABLE", r["attempt_id"])
            if controls and (
                not isinstance(fence, Mapping)
                or fence.get("controller_generation") != r["controller_generation"]
            ):
                return _reply(
                    "unknown", "CONTROLLER_GENERATION_MISMATCH", r["attempt_id"]
                )
            if controls and (
                not isinstance(fence, Mapping)
                or fence.get("phase") not in {"activated", "cancelled"}
                or fence.get("authorization", {}).get("role") != "controller"
            ):
                return _reply(
                    "unknown",
                    "HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED",
                    r["attempt_id"],
                )
            with c._locked(paths["root"]):
                v = c._handoff_strict_task_view_locked(r["task_id"], paths)
                old = self._attempts(v["events"]).get(r["attempt_id"])
                if (
                    v["contract_version"] != r["contract_version"]
                    or v["contract_digest"] != r["contract_digest"]
                    or Path(r["workspace_root"]).resolve(strict=True)
                    != Path(v["contract"]["workspace_root"]).resolve(strict=True)
                ):
                    return _reply(
                        "unknown", "BASIS_CHANGED_BEFORE_RESERVE", r["attempt_id"]
                    )
                if datetime.fromisoformat(
                    h["expires_at"].replace("Z", "+00:00")
                ) < datetime.now(timezone.utc):
                    return _reply(
                        "unknown",
                        "HOST_OBSERVATION_EXPIRED_BEFORE_RESERVE",
                        r["attempt_id"],
                    )
                c._recheck_handoff_write_authorization_locked(
                    r["task_id"], base_dir=self.base_dir, fence=fence
                )
                final_controls, final_error = c._handoff_module._control_events(
                    v["events"], task_id=r["task_id"]
                )
                final_projection, final_projection_error = (
                    c._handoff_module._control_projection(
                        v["events"], task_id=r["task_id"]
                    )
                )
                if final_projection_error is not None or (
                    final_projection["controls"]
                    and r["controller_generation"] != final_projection["generation"]
                ):
                    return _reply(
                        "unknown", "CONTROLLER_GENERATION_MISMATCH", r["attempt_id"]
                    )
                if final_error is not None or (
                    final_controls
                    and (
                        not isinstance(fence, Mapping)
                        or fence.get("phase") not in {"activated", "cancelled"}
                        or fence.get("authorization", {}).get("role") != "controller"
                    )
                ):
                    return _reply(
                        "unknown",
                        "HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED",
                        r["attempt_id"],
                    )
                if old:
                    return _reply(
                        "pass",
                        "ALREADY_RESERVED",
                        r["attempt_id"],
                        reservation_id=old["reservation_id"],
                        current_state="reserved",
                    )
                if self._unsafe_prior_attempt(v["events"], r["attempt_id"]):
                    return _reply(
                        "unknown",
                        "PRIOR_ATTEMPT_IN_FLIGHT_OR_UNKNOWN",
                        r["attempt_id"],
                        current_state="in_flight",
                    )
                p = {
                    "schema": SCHEMA,
                    "type": "host-attempt-reserved",
                    "task_id": r["task_id"],
                    "attempt_id": r["attempt_id"],
                    "reservation_id": _reservation_id(r["attempt_id"]),
                    "operation": op,
                    "request": r,
                    "request_sha256": _d(r),
                    "host_observation": h,
                    "created_at": _zulu(),
                }
                e = c._new_event(
                    r["task_id"],
                    "host-attempt-reserved",
                    h["host_identity_ref"]["registered_identity_id"],
                    p,
                )
                c._publish_handoff_event_locked(r["task_id"], paths, v["snapshot"], e)
        except Exception:
            return _reply("unknown", "RESERVATION_COMMIT_UNKNOWN", r["attempt_id"])
        return _reply(
            "pass",
            "RESERVED",
            r["attempt_id"],
            reservation_id=_reservation_id(r["attempt_id"]),
            launch_allowed=True,
            current_state="reserved",
            readonly_action="Start once, then record observation.",
        )

    def record_observation(
        self, attempt_id: str, observation: object
    ) -> dict[str, Any]:
        if not _okid(attempt_id) or not isinstance(observation, Mapping):
            return _reply(
                "fail",
                "INVALID_OBSERVATION",
                attempt_id if isinstance(attempt_id, str) else None,
            )
        o = dict(observation)
        need = {
            "task_id",
            "attempt_id",
            "reservation_id",
            "operation",
            "argv_sha256",
            "cwd",
            "thread_id",
            "exit_status",
            "timeout",
            "observed_at",
            "stdout",
            "stdout_digest",
            "stdout_bytes",
            "stdout_utf8",
            "host_identity_ref",
            "host_exclusivity_status",
            "host_observed_at",
            "host_observation_ref",
            "stderr_digest",
            "stderr_bytes",
            "output_over_limit",
        }
        identity_ref, observation_ref = o.get("host_identity_ref"), o.get(
            "host_observation_ref"
        )
        try:
            stdout_raw = (
                o.get("stdout").encode("utf-8")
                if isinstance(o.get("stdout"), str)
                else None
            )
        except UnicodeEncodeError:
            stdout_raw = None
        if (
            set(o) != need
            or o.get("attempt_id") != attempt_id
            or o.get("operation") not in _OPS
            or not _oksha(o.get("argv_sha256"))
            or not _oksha(o.get("stdout_digest"))
            or not isinstance(o.get("cwd"), str)
            or not o["cwd"].startswith("/")
            or not _utc(o.get("observed_at"))
            or (o.get("exit_status") is None) == (o.get("timeout") is None)
            or o.get("timeout") not in {None, True}
            or stdout_raw is None
            or type(o.get("stdout_bytes")) is not int
            or o["stdout_bytes"] < 0
            or type(o.get("stdout_utf8")) is not bool
            or len(stdout_raw) > 8 * 1024 * 1024
            or (
                o["stdout_utf8"]
                and (
                    o["stdout_bytes"] != len(stdout_raw)
                    or o["stdout_digest"] != hashlib.sha256(stdout_raw).hexdigest()
                )
            )
            or not isinstance(identity_ref, Mapping)
            or set(identity_ref) != {"registered_identity_id", "sha256"}
            or not _okid(identity_ref.get("registered_identity_id"))
            or not _oksha(identity_ref.get("sha256"))
            or o.get("host_exclusivity_status") != "exclusive"
            or not _utc(o.get("host_observed_at"))
            or not isinstance(observation_ref, Mapping)
            or set(observation_ref) != {"ref_id", "uri", "sha256"}
            or not _okid(observation_ref.get("ref_id"))
            or not isinstance(observation_ref.get("uri"), str)
            or not _oksha(observation_ref.get("sha256"))
            or not _oksha(o.get("stderr_digest"))
            or type(o.get("stderr_bytes")) is not int
            or o["stderr_bytes"] < 0
            or type(o.get("output_over_limit")) is not bool
        ):
            return _reply("fail", "INVALID_OBSERVATION", attempt_id)
        if (
            getattr(self.host_observer, "registered_runtime_identity", None)
            is not self.runtime_identity
        ):
            return _reply("unknown", "HOST_RUNTIME_IDENTITY_MISMATCH", attempt_id)
        try:
            task = str(o["task_id"])
            c, paths, v = self._capture(task)
            reservation = self._attempts(v["events"]).get(attempt_id)
            if not reservation or o.get("reservation_id") != reservation.get(
                "reservation_id"
            ):
                return _reply("fail", "OBSERVATION_IDENTITY_CONFLICT", attempt_id)
            if not _observation_matches_reservation(o, reservation):
                return _reply("fail", "OBSERVATION_BINDING_MISMATCH", attempt_id)
            fence = c._require_handoff_write_authorization(
                task,
                base_dir=self.base_dir,
                operation="host_observe",
                arguments={"attempt_id": attempt_id, "observation_sha256": _d(o)},
                runtime_identity=self.runtime_identity,
                write_authorizer=self.write_authorizer,
            )
            if not _child_owns_attempt(fence, attempt_id):
                return _reply(
                    "unknown", "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH", attempt_id
                )
            with c._locked(paths["root"]):
                v = c._handoff_strict_task_view_locked(task, paths)
                reservation = self._attempts(v["events"]).get(attempt_id)
                if not reservation:
                    return _reply("unknown", "ATTEMPT_NOT_RESERVED", attempt_id)
                if not _observation_matches_reservation(o, reservation):
                    return _reply("unknown", "OBSERVATION_BINDING_CHANGED", attempt_id)
                c._recheck_handoff_write_authorization_locked(
                    task, base_dir=self.base_dir, fence=fence
                )
                if not _child_owns_attempt(fence, attempt_id):
                    return _reply(
                        "unknown", "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH", attempt_id
                    )
                stdout_digest = (
                    o["stdout_digest"]
                    if not o["stdout_utf8"]
                    else hashlib.sha256(stdout_raw).hexdigest()
                )
                summary = {key: value for key, value in o.items() if key != "stdout"}
                summary["stdout_digest"] = stdout_digest
                observation_digest = _d(summary)
                archive = (
                    paths["root"]
                    / "attempts"
                    / attempt_id
                    / "observations"
                    / (observation_digest + ".json")
                )
                existing = [
                    event
                    for event in v["events"]
                    if event.get("event_type") == "host-attempt-observed"
                    and event.get("payload", {}).get("observation_sha256")
                    == observation_digest
                ]
                if existing:
                    return _reply(
                        "pass",
                        "ALREADY_OBSERVED",
                        attempt_id,
                        recorded=False,
                        current_state="observed",
                    )
                archive_sha256 = _atomic_archive_json(
                    paths["root"],
                    archive,
                    {
                        "stdout": o["stdout"] if o["stdout_utf8"] else None,
                        "stdout_archived": o["stdout_utf8"],
                        "stdout_digest": stdout_digest,
                        "stdout_bytes": o["stdout_bytes"],
                        "exit_status": o["exit_status"],
                        "timeout": o["timeout"],
                        "observed_at": o["observed_at"],
                    },
                    mode=0o600,
                )
                p = {
                    "schema": SCHEMA,
                    "type": "host-attempt-observed",
                    "task_id": task,
                    "attempt_id": attempt_id,
                    "reservation_id": reservation["reservation_id"],
                    "observation": summary,
                    "observation_sha256": observation_digest,
                    "archive_ref": {
                        "uri": archive.relative_to(paths["root"]).as_posix(),
                        "sha256": archive_sha256,
                    },
                    "created_at": _zulu(),
                }
                e = c._new_event(
                    task,
                    "host-attempt-observed",
                    _event_actor(fence, identity_ref["registered_identity_id"]),
                    p,
                )
                c._publish_handoff_event_locked(task, paths, v["snapshot"], e)
        except Exception:
            return _reply("unknown", "OBSERVATION_COMMIT_UNKNOWN", attempt_id)
        return _reply(
            "pass", "OBSERVED", attempt_id, recorded=True, current_state="observed"
        )

    def observe(self, attempt_id: str) -> dict[str, Any]:
        task = self.task_id
        if not _okid(task):
            return _reply("unknown", "TASK_ID_REQUIRED", attempt_id)
        try:
            _, _, v = self._capture(task)
            p = self._attempts(v["events"]).get(attempt_id)
            observed = any(
                e.get("event_type") == "host-attempt-observed"
                and e.get("payload", {}).get("attempt_id") == attempt_id
                for e in v["events"]
            )
            results = [
                e["payload"]
                for e in v["events"]
                if e.get("event_type") == "host-result-published"
                and e.get("payload", {}).get("attempt_id") == attempt_id
            ]
            processed = [
                e["payload"]
                for e in v["events"]
                if e.get("event_type") == "host-result-processed"
                and e.get("payload", {}).get("attempt_id") == attempt_id
            ]
            actions = [
                e["payload"]
                for e in v["events"]
                if e.get("event_type") == "host-business-action-observed"
                and e.get("payload", {}).get("attempt_id") == attempt_id
            ]
            summary_limit = 64
            result_summary = [
                {
                    key: item.get(key)
                    for key in (
                        "result_version",
                        "result_digest",
                        "archive_ref",
                        "late",
                    )
                }
                for item in results[-summary_limit:]
            ]
            processed_summary = [
                {
                    key: item.get(key)
                    for key in (
                        "result_version",
                        "result_digest",
                        "basis_digest",
                        "verdict",
                    )
                }
                for item in processed[-summary_limit:]
            ]
            action_summary = [
                {key: item.get(key) for key in ("action_id", "action_status")}
                for item in actions[-summary_limit:]
            ]
            summary_truncated = any(
                len(items) > summary_limit for items in (results, processed, actions)
            )
            common = {
                "reservation": p,
                "results": result_summary,
                "processed": processed_summary,
                "actions": action_summary,
                "result_total": len(results),
                "processed_total": len(processed),
                "action_total": len(actions),
                "summary_truncated": summary_truncated,
                "current_state": (
                    "observed" if observed else "reserved" if p else "unknown"
                ),
            }
            result_identities: dict[object, set[object]] = {}
            for item in results:
                result_identities.setdefault(item.get("result_version"), set()).add(
                    item.get("result_digest")
                )
            conflicting = any(
                len(digests) > 1 for digests in result_identities.values()
            )
            if results and (conflicting or any(item.get("late") for item in results)):
                return _reply(
                    "unknown", "RESULT_CONFLICT_OR_LATE", attempt_id, **common
                )
            if summary_truncated:
                return _reply("unknown", "SUMMARY_LIMIT", attempt_id, **common)
            if processed:
                if processed[-1].get("verdict") != "pass":
                    return _reply(
                        "unknown", "RESULT_VERDICT_NOT_PASS", attempt_id, **common
                    )
                return _reply(
                    "unknown", "RESULT_REVALIDATION_REQUIRED", attempt_id, **common
                )
            if results and not processed:
                return _reply("unknown", "RESULT_UNPROCESSED", attempt_id, **common)
            return _reply(
                "pass" if p else "unknown",
                "OBSERVED" if observed else "RESERVED" if p else "ATTEMPT_NOT_FOUND",
                attempt_id,
                **common,
            )
        except Exception:
            return _reply("unknown", "EVENT_UNAVAILABLE", attempt_id)

    def publish_result(self, result: object) -> dict[str, Any]:
        """Archive actual bounded result text before publishing its event reference."""
        if not isinstance(result, Mapping):
            return _reply("fail", "INVALID_RESULT")
        value = dict(result)
        required = {
            "task_id",
            "attempt_id",
            "result_version",
            "contract_version",
            "contract_digest",
            "baseline",
            "workspace_root",
            "content",
        }
        try:
            content_bytes = (
                value.get("content").encode("utf-8")
                if isinstance(value.get("content"), str)
                else None
            )
        except UnicodeEncodeError:
            content_bytes = None
        if (
            set(value) != required
            or not _okid(value.get("task_id"))
            or not _okid(value.get("attempt_id"))
            or not _okid(value.get("result_version"))
            or not isinstance(value.get("content"), str)
            or not value["content"].strip()
            or content_bytes is None
            or len(content_bytes) > 1024 * 1024
        ):
            return _reply(
                "fail",
                "INVALID_RESULT",
                (
                    value.get("attempt_id")
                    if isinstance(value.get("attempt_id"), str)
                    else None
                ),
            )
        if (
            getattr(self.host_observer, "registered_runtime_identity", None)
            is not self.runtime_identity
        ):
            return _reply(
                "unknown",
                "HOST_RUNTIME_IDENTITY_MISMATCH",
                (
                    value.get("attempt_id")
                    if isinstance(value.get("attempt_id"), str)
                    else None
                ),
            )
        content_digest = hashlib.sha256(content_bytes).hexdigest()
        try:
            core, paths, view = self._capture(value["task_id"])
            reservation = self._attempts(view["events"]).get(value["attempt_id"])
            if not reservation:
                return _reply("fail", "ATTEMPT_NOT_RESERVED", value["attempt_id"])
            request = reservation["request"]
            bindings = {
                key: value[key]
                for key in (
                    "contract_version",
                    "contract_digest",
                    "baseline",
                    "workspace_root",
                )
            }
            late = any(bindings[key] != request[key] for key in bindings)
            callback = getattr(self.host_observer, "observe_execution_state", None)
            try:
                host, host_error = _host(
                    (
                        callback(dict(request), reservation.get("operation"))
                        if callable(callback)
                        else None
                    ),
                    request,
                )
            except Exception:
                host, host_error = None, "HOST_OBSERVATION_UNAVAILABLE"
            if host is None:
                return _reply(
                    "unknown",
                    host_error or "HOST_OBSERVATION_UNAVAILABLE",
                    value["attempt_id"],
                )
            if datetime.fromisoformat(
                host["expires_at"].replace("Z", "+00:00")
            ) < datetime.now(timezone.utc):
                return _reply(
                    "unknown", "HOST_OBSERVATION_EXPIRED", value["attempt_id"]
                )
            if host["host_identity_ref"] != reservation.get("host_observation", {}).get(
                "host_identity_ref"
            ):
                return _reply("unknown", "HOST_IDENTITY_CHANGED", value["attempt_id"])
            archive = (
                paths["root"]
                / "results"
                / value["attempt_id"]
                / value["result_version"]
                / (content_digest + ".json")
            )
            fence = core._require_handoff_write_authorization(
                value["task_id"],
                base_dir=self.base_dir,
                operation="host_result_publish",
                arguments={
                    "attempt_id": value["attempt_id"],
                    "result_version": value["result_version"],
                    "result_digest": content_digest,
                },
                runtime_identity=self.runtime_identity,
                write_authorizer=self.write_authorizer,
            )
            if not _child_owns_attempt(fence, value["attempt_id"]):
                return _reply(
                    "unknown",
                    "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH",
                    value["attempt_id"],
                )
            with core._locked(paths["root"]):
                view = core._handoff_strict_task_view_locked(value["task_id"], paths)
                core._recheck_handoff_write_authorization_locked(
                    value["task_id"], base_dir=self.base_dir, fence=fence
                )
                if not _child_owns_attempt(fence, value["attempt_id"]):
                    return _reply(
                        "unknown",
                        "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH",
                        value["attempt_id"],
                    )
                try:
                    refreshed_host, refreshed_error = _host(
                        (
                            callback(dict(request), reservation.get("operation"))
                            if callable(callback)
                            else None
                        ),
                        request,
                    )
                except Exception:
                    refreshed_host, refreshed_error = (
                        None,
                        "HOST_OBSERVATION_UNAVAILABLE",
                    )
                if refreshed_host is None:
                    return _reply(
                        "unknown",
                        refreshed_error or "HOST_OBSERVATION_UNAVAILABLE",
                        value["attempt_id"],
                    )
                if datetime.fromisoformat(
                    refreshed_host["expires_at"].replace("Z", "+00:00")
                ) < datetime.now(timezone.utc):
                    return _reply(
                        "unknown",
                        "HOST_OBSERVATION_EXPIRED_BEFORE_PUBLISH",
                        value["attempt_id"],
                    )
                if (
                    refreshed_host["host_identity_ref"] != host["host_identity_ref"]
                    or refreshed_host["observation_ref"] != host["observation_ref"]
                ):
                    return _reply(
                        "unknown",
                        "HOST_OBSERVATION_CHANGED_BEFORE_PUBLISH",
                        value["attempt_id"],
                    )
                same_identity = [
                    event["payload"]
                    for event in view["events"]
                    if event.get("event_type") == "host-result-published"
                    and event.get("payload", {}).get("attempt_id")
                    == value["attempt_id"]
                    and event.get("payload", {}).get("result_version")
                    == value["result_version"]
                ]
                conflict_exists = any(
                    item.get("result_digest") != content_digest
                    for item in same_identity
                )
                if (
                    any(
                        item.get("result_digest") == content_digest
                        for item in same_identity
                    )
                    and conflict_exists
                ):
                    return _reply(
                        "unknown",
                        "RESULT_IDENTITY_CONFLICT",
                        value["attempt_id"],
                        result_digest=content_digest,
                        current_state="result_published",
                    )
                if any(
                    item.get("result_digest") == content_digest
                    for item in same_identity
                ):
                    return _reply(
                        "pass",
                        "ALREADY_PUBLISHED",
                        value["attempt_id"],
                        result_digest=content_digest,
                        current_state="result_published",
                    )
                late = late or _attempt_is_superseded(
                    view["events"], value["attempt_id"]
                )
                archive_sha256 = _atomic_archive_json(
                    paths["root"], archive, {"content": value["content"]}
                )
                payload = {
                    "schema": SCHEMA,
                    "type": "host-result-published",
                    "task_id": value["task_id"],
                    "attempt_id": value["attempt_id"],
                    "result_version": value["result_version"],
                    "result_digest": content_digest,
                    "archive_ref": {
                        "uri": archive.relative_to(paths["root"]).as_posix(),
                        "sha256": archive_sha256,
                    },
                    "bindings": bindings,
                    "late": late,
                    "created_at": _zulu(),
                }
                event = core._new_event(
                    value["task_id"],
                    "host-result-published",
                    _event_actor(
                        fence, host["host_identity_ref"]["registered_identity_id"]
                    ),
                    payload,
                )
                core._publish_handoff_event_locked(
                    value["task_id"], paths, view["snapshot"], event
                )
        except Exception:
            return _reply(
                "unknown",
                "RESULT_PUBLICATION_UNKNOWN",
                (
                    value.get("attempt_id")
                    if isinstance(value.get("attempt_id"), str)
                    else None
                ),
            )
        if same_identity:
            return _reply(
                "unknown",
                "RESULT_IDENTITY_CONFLICT",
                value["attempt_id"],
                result_digest=content_digest,
                current_state="result_published",
            )
        return _reply(
            "unknown" if late else "pass",
            "LATE_RESULT_REQUIRES_REVIEW" if late else "RESULT_PUBLISHED",
            value["attempt_id"],
            result_digest=content_digest,
            current_state="result_published",
        )

    def reconcile_result(
        self, attempt_id: str, result_version: str, verifier: object
    ) -> dict[str, Any]:
        """Read a sealed archive out of lock; commit a processing conclusion only after recheck."""
        if (
            not _okid(attempt_id)
            or not _okid(result_version)
            or not _okid(self.task_id)
        ):
            return _reply(
                "fail",
                "INVALID_RECONCILIATION",
                attempt_id if isinstance(attempt_id, str) else None,
            )
        if (
            getattr(self.host_observer, "registered_runtime_identity", None)
            is not self.runtime_identity
        ):
            return _reply("unknown", "HOST_RUNTIME_IDENTITY_MISMATCH", attempt_id)
        try:
            core, paths, before = self._capture(self.task_id)
            published = [
                e["payload"]
                for e in before["events"]
                if e.get("event_type") == "host-result-published"
                and e.get("payload", {}).get("attempt_id") == attempt_id
                and e.get("payload", {}).get("result_version") == result_version
            ]
            if len(published) != 1:
                return _reply("unknown", "RESULT_CONFLICT_OR_LATE", attempt_id)
            item = published[0]
            reservation = self._attempts(before["events"]).get(attempt_id)
            if _attempt_is_superseded(before["events"], attempt_id):
                return _reply(
                    "unknown", "ATTEMPT_SUPERSEDED_BY_REPLACEMENT", attempt_id
                )
            if item.get("late"):
                return _reply("unknown", "RESULT_CONFLICT_OR_LATE", attempt_id)
            if (
                not isinstance(reservation, Mapping)
                or not _result_bindings_match_request(
                    item.get("bindings"), reservation.get("request", {})
                )
                or item["bindings"].get("contract_version")
                != before["contract_version"]
                or item["bindings"].get("contract_digest") != before["contract_digest"]
                or Path(str(item["bindings"].get("workspace_root"))).resolve(
                    strict=True
                )
                != Path(str(before["contract"].get("workspace_root"))).resolve(
                    strict=True
                )
            ):
                return _reply("unknown", "RESULT_BINDING_STALE", attempt_id)
            request = reservation.get("request")
            callback = getattr(self.host_observer, "observe_execution_state", None)
            try:
                host, host_error = _host(
                    (
                        callback(dict(request), reservation.get("operation"))
                        if callable(callback) and isinstance(request, Mapping)
                        else None
                    ),
                    request if isinstance(request, Mapping) else {},
                )
            except Exception:
                host, host_error = None, "HOST_OBSERVATION_UNAVAILABLE"
            if host is None:
                return _reply(
                    "unknown", host_error or "HOST_OBSERVATION_UNAVAILABLE", attempt_id
                )
            if datetime.fromisoformat(
                host["expires_at"].replace("Z", "+00:00")
            ) < datetime.now(timezone.utc):
                return _reply("unknown", "HOST_OBSERVATION_EXPIRED", attempt_id)
            if host["host_identity_ref"] != reservation.get("host_observation", {}).get(
                "host_identity_ref"
            ):
                return _reply("unknown", "HOST_IDENTITY_CHANGED", attempt_id)
            archive = paths["root"] / str(item["archive_ref"]["uri"])
            raw = _safe_archive(
                paths["root"],
                item["archive_ref"]["uri"],
                item["archive_ref"]["sha256"],
                item["result_digest"],
            )
            if raw is None or not raw["content"].strip():
                return _reply("unknown", "RESULT_ARCHIVE_UNREADABLE", attempt_id)
            verify = getattr(verifier, "verify", None)
            verdict = (
                verify(
                    {
                        "task_id": self.task_id,
                        "attempt_id": attempt_id,
                        "result_version": result_version,
                        "content": raw["content"],
                        "result_digest": item["result_digest"],
                    }
                )
                if callable(verify)
                else None
            )
            if not isinstance(verdict, Mapping) or verdict.get("status") not in {
                "pass",
                "fail",
                "unknown",
            }:
                return _reply("unknown", "RESULT_VERIFIER_UNAVAILABLE", attempt_id)
            basis = _d(
                {
                    "contract_digest": before["contract_digest"],
                    "result_digest": item["result_digest"],
                    "verdict": verdict["status"],
                }
            )
            fence = core._require_handoff_write_authorization(
                self.task_id,
                base_dir=self.base_dir,
                operation="host_result_process",
                arguments={
                    "attempt_id": attempt_id,
                    "result_version": result_version,
                    "result_digest": item["result_digest"],
                },
                runtime_identity=self.runtime_identity,
                write_authorizer=self.write_authorizer,
            )
            with core._locked(paths["root"]):
                after = core._handoff_strict_task_view_locked(self.task_id, paths)
                core._recheck_handoff_write_authorization_locked(
                    self.task_id, base_dir=self.base_dir, fence=fence
                )
                if _attempt_is_superseded(after["events"], attempt_id):
                    return _reply(
                        "unknown", "ATTEMPT_SUPERSEDED_BY_REPLACEMENT", attempt_id
                    )
                try:
                    refreshed_host, refreshed_error = _host(
                        (
                            callback(dict(request), reservation.get("operation"))
                            if callable(callback)
                            else None
                        ),
                        request,
                    )
                except Exception:
                    refreshed_host, refreshed_error = (
                        None,
                        "HOST_OBSERVATION_UNAVAILABLE",
                    )
                if refreshed_host is None:
                    return _reply(
                        "unknown",
                        refreshed_error or "HOST_OBSERVATION_UNAVAILABLE",
                        attempt_id,
                    )
                if datetime.fromisoformat(
                    refreshed_host["expires_at"].replace("Z", "+00:00")
                ) < datetime.now(timezone.utc):
                    return _reply(
                        "unknown", "HOST_OBSERVATION_EXPIRED_BEFORE_PROCESS", attempt_id
                    )
                if (
                    refreshed_host["host_identity_ref"] != host["host_identity_ref"]
                    or refreshed_host["observation_ref"] != host["observation_ref"]
                ):
                    return _reply(
                        "unknown", "HOST_OBSERVATION_CHANGED_BEFORE_PROCESS", attempt_id
                    )
                if datetime.fromisoformat(
                    host["expires_at"].replace("Z", "+00:00")
                ) < datetime.now(timezone.utc):
                    return _reply(
                        "unknown", "HOST_OBSERVATION_EXPIRED_BEFORE_PROCESS", attempt_id
                    )
                if (
                    after["contract_digest"] != before["contract_digest"]
                    or after["events_digest"] != before["events_digest"]
                ):
                    return _reply("unknown", "BASIS_CHANGED_BEFORE_PROCESS", attempt_id)
                reread = _safe_archive(
                    paths["root"],
                    item["archive_ref"]["uri"],
                    item["archive_ref"]["sha256"],
                    item["result_digest"],
                )
                if reread != raw:
                    return _reply(
                        "unknown", "RESULT_ARCHIVE_CHANGED_BEFORE_PROCESS", attempt_id
                    )
                duplicates = [
                    e
                    for e in after["events"]
                    if e.get("event_type") == "host-result-processed"
                    and e.get("payload", {}).get("attempt_id") == attempt_id
                    and e.get("payload", {}).get("result_version") == result_version
                    and e.get("payload", {}).get("basis_digest") == basis
                ]
                if duplicates:
                    return _reply(
                        "pass",
                        "ALREADY_PROCESSED",
                        attempt_id,
                        current_state="processed",
                        verdict=duplicates[-1].get("payload", {}).get("verdict"),
                        action_state="not_started",
                    )
                payload = {
                    "schema": SCHEMA,
                    "type": "host-result-processed",
                    "task_id": self.task_id,
                    "attempt_id": attempt_id,
                    "result_version": result_version,
                    "result_digest": item["result_digest"],
                    "basis_digest": basis,
                    "processing_status": "submitted",
                    "verdict": verdict["status"],
                    "created_at": _zulu(),
                }
                event = core._new_event(
                    self.task_id,
                    "host-result-processed",
                    _event_actor(
                        fence, host["host_identity_ref"]["registered_identity_id"]
                    ),
                    payload,
                )
                core._publish_handoff_event_locked(
                    self.task_id, paths, after["snapshot"], event
                )
        except Exception:
            return _reply("unknown", "PROCESSING_COMMIT_UNKNOWN", attempt_id)
        return _reply(
            "pass",
            "PROCESSED",
            attempt_id,
            current_state="processed",
            verdict=verdict["status"],
            action_state="not_started",
        )

    def record_action_outcome(
        self, action_id: str, attempt_id: str, status: str
    ) -> dict[str, Any]:
        if (
            not _okid(action_id)
            or not _okid(attempt_id)
            or status not in {"not_started", "executed", "execution_unknown"}
            or not _okid(self.task_id)
        ):
            return _reply(
                "fail",
                "INVALID_ACTION_OUTCOME",
                attempt_id if isinstance(attempt_id, str) else None,
            )
        if (
            getattr(self.host_observer, "registered_runtime_identity", None)
            is not self.runtime_identity
        ):
            return _reply("unknown", "HOST_RUNTIME_IDENTITY_MISMATCH", attempt_id)
        try:
            core, paths, view = self._capture(self.task_id)
            reservation = self._attempts(view["events"]).get(attempt_id)
            if not reservation:
                return _reply("fail", "ATTEMPT_NOT_RESERVED", attempt_id)
            existing = [
                e["payload"]
                for e in view["events"]
                if e.get("event_type") == "host-business-action-observed"
                and e.get("payload", {}).get("action_id") == action_id
            ]
            if existing:
                if any(
                    item.get("attempt_id") != attempt_id
                    or item.get("action_status") != status
                    for item in existing
                ):
                    return _reply(
                        "unknown", "ACTION_OUTCOME_CONFLICT_REQUIRES_REVIEW", attempt_id
                    )
                return _reply(
                    "pass", "ALREADY_ACTION_OUTCOME", attempt_id, action_state=status
                )
            fence = core._require_handoff_write_authorization(
                self.task_id,
                base_dir=self.base_dir,
                operation="host_action_observe",
                arguments={
                    "attempt_id": attempt_id,
                    "action_id": action_id,
                    "status": status,
                },
                runtime_identity=self.runtime_identity,
                write_authorizer=self.write_authorizer,
            )
            if not _child_owns_attempt(fence, attempt_id):
                return _reply(
                    "unknown", "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH", attempt_id
                )
            with core._locked(paths["root"]):
                view = core._handoff_strict_task_view_locked(self.task_id, paths)
                core._recheck_handoff_write_authorization_locked(
                    self.task_id, base_dir=self.base_dir, fence=fence
                )
                if not _child_owns_attempt(fence, attempt_id):
                    return _reply(
                        "unknown", "CHILD_ATTEMPT_AUTHORIZATION_MISMATCH", attempt_id
                    )
                if not self._attempts(view["events"]).get(attempt_id):
                    return _reply("unknown", "ATTEMPT_NOT_RESERVED", attempt_id)
                existing = [
                    e["payload"]
                    for e in view["events"]
                    if e.get("event_type") == "host-business-action-observed"
                    and e.get("payload", {}).get("action_id") == action_id
                ]
                if existing:
                    if any(
                        item.get("attempt_id") != attempt_id
                        or item.get("action_status") != status
                        for item in existing
                    ):
                        return _reply(
                            "unknown",
                            "ACTION_OUTCOME_CONFLICT_REQUIRES_REVIEW",
                            attempt_id,
                        )
                    return _reply(
                        "pass",
                        "ALREADY_ACTION_OUTCOME",
                        attempt_id,
                        action_state=status,
                    )
                payload = {
                    "schema": SCHEMA,
                    "type": "host-business-action-observed",
                    "task_id": self.task_id,
                    "attempt_id": attempt_id,
                    "action_id": action_id,
                    "action_status": status,
                    "created_at": _zulu(),
                }
                event = core._new_event(
                    self.task_id,
                    "host-business-action-observed",
                    _event_actor(
                        fence,
                        reservation["host_observation"]["host_identity_ref"][
                            "registered_identity_id"
                        ],
                    ),
                    payload,
                )
                core._publish_handoff_event_locked(
                    self.task_id, paths, view["snapshot"], event
                )
        except Exception:
            return _reply("unknown", "ACTION_OUTCOME_COMMIT_UNKNOWN", attempt_id)
        return _reply(
            "pass", "ACTION_OUTCOME_RECORDED", attempt_id, action_state=status
        )
