"""Narrow, fail-closed transport for an already-authorized Codex CLI attempt.

This module deliberately does not decide business completion, own a task ledger,
or treat CLI output as authority.  Those facts belong to the core protocol and
the trusted host integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading
from typing import Any, Callable, Mapping, Protocol
import uuid


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_PROMPT_CHARS = 8000
_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
_APPROVAL_POLICIES = frozenset({"untrusted", "on-failure", "on-request", "never"})


class HostTaskLedger(Protocol):
    """The core-owned, append-only attempt ledger required by this transport."""

    def reserve(
        self, request: Mapping[str, Any], operation: str
    ) -> Mapping[str, Any]: ...
    def record_observation(
        self, attempt_id: str, observation: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...
    def observe(self, attempt_id: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class CodexCliConfig:
    executable_argv_prefix: tuple[str, ...]
    workspace_root: str
    model: str
    reasoning_effort: str
    sandbox_mode: str
    approval_policy: str
    timeout_seconds: int = 10
    _path_fingerprints: tuple[tuple[int, int, int, int, int, str], ...] = field(
        init=False, repr=False
    )
    _workspace_fingerprint: tuple[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.executable_argv_prefix or not all(
            isinstance(part, str) and part for part in self.executable_argv_prefix
        ):
            raise ValueError(
                "executable_argv_prefix must be a non-empty fixed argv prefix"
            )
        if not Path(self.executable_argv_prefix[0]).is_absolute():
            raise ValueError(
                "executable_argv_prefix must start with an absolute executable path"
            )
        workspace = Path(self.workspace_root)
        if not workspace.is_absolute() or not workspace.is_dir():
            raise ValueError("workspace_root must name an existing absolute directory")
        values = (
            self.model,
            self.reasoning_effort,
            self.sandbox_mode,
            self.approval_policy,
        )
        if not all(
            isinstance(value, str) and value and "\x00" not in value for value in values
        ):
            raise ValueError("trusted CLI configuration is incomplete")
        try:
            for value in values:
                value.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError("trusted CLI configuration must be UTF-8") from exc
        if (
            self.sandbox_mode not in _SANDBOX_MODES
            or self.approval_policy not in _APPROVAL_POLICIES
        ):
            raise ValueError("trusted CLI sandbox or approval policy is unsupported")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be an integer from 1 through 60")
        object.__setattr__(self, "workspace_root", str(workspace.resolve(strict=True)))
        fixed_paths = tuple(
            Path(item)
            for item in self.executable_argv_prefix
            if Path(item).is_absolute()
        )
        try:
            object.__setattr__(
                self,
                "_path_fingerprints",
                tuple(_executable_fingerprint(path) for path in fixed_paths),
            )
            stat_result = Path(self.workspace_root).stat()
            object.__setattr__(
                self, "_workspace_fingerprint", (stat_result.st_dev, stat_result.st_ino)
            )
        except OSError as exc:
            raise ValueError("trusted executable or workspace is unavailable") from exc


@dataclass(frozen=True)
class CodexCliHost:
    """Transport seam; authorization and persistence are injected, never inferred."""

    config: CodexCliConfig
    ledger: HostTaskLedger
    observe_host: Callable[[Mapping[str, Any]], Mapping[str, Any]]

    def start_child(self, request: Mapping[str, Any], prompt: str) -> dict[str, Any]:
        return self._launch(request, prompt, operation="start_child")

    def resume_child(self, request: Mapping[str, Any], prompt: str) -> dict[str, Any]:
        return self._launch(request, prompt, operation="resume_child")

    def observe_attempt(self, attempt_id: str) -> dict[str, Any]:
        if not _identifier(attempt_id):
            return _unavailable("HOST_ATTEMPT_ID_INVALID")
        try:
            observed = self.ledger.observe(attempt_id)
        except Exception:
            return _unavailable("HOST_LEDGER_OBSERVE_UNAVAILABLE")
        if not isinstance(observed, Mapping):
            return _unavailable("HOST_LEDGER_OBSERVE_MALFORMED")
        return {
            "check_status": "unknown",
            "commit_status": "not_attempted",
            "launch_status": "observed",
            "attempt_id": attempt_id,
            "observation": dict(observed),
            "real_host_status": "NOT_RUN",
        }

    def verify_host(self) -> dict[str, Any]:
        # Configuration is necessary transport input, not proof that the actual
        # Codex host is controllable, exclusive, or able to create a clean run.
        return {
            "check_status": "unknown",
            "commit_status": "not_attempted",
            "local_transport_status": "pass",
            "real_host_status": "NOT_RUN",
            "capabilities": {
                "trusted_identity": "unknown",
                "single_writer": "unknown",
                "clean_session": "unknown",
                "automatic_rollover": "unknown",
                "parent_exit_effect": "unknown",
            },
            "reason_code": "HOST_REAL_CAPABILITIES_NOT_RUN",
        }

    def _launch(
        self, raw_request: Mapping[str, Any], prompt: str, *, operation: str
    ) -> dict[str, Any]:
        if not _config_paths_current(self.config):
            return _unavailable("HOST_CONFIG_PATH_CHANGED")
        request, error = _validated_request(
            raw_request, prompt=prompt, config=self.config, operation=operation
        )
        if error is not None or request is None:
            return _unavailable(error or "HOST_REQUEST_INVALID")
        argv, error = _argv_for(self.config, request, prompt, operation=operation)
        if error is not None or argv is None:
            return _unavailable(error or "HOST_COMMAND_UNAVAILABLE")
        request["argv_sha256"] = _digest(argv)
        request["config_digest"] = _digest(_config_binding(self.config))
        request["prompt_sha256"] = _sha256_text(prompt)

        # This observation is only a UX preflight.  The core-owned ledger has
        # its own registered observer and repeats the authoritative check under
        # its reservation protocol before making launch_allowed true.
        host_observation, host_error = _observe_host(self.observe_host, request)
        if host_error is not None:
            return _unavailable(host_error)
        try:
            reservation = self.ledger.reserve(request, operation)
        except Exception:
            return _unavailable("HOST_LEDGER_RESERVE_UNAVAILABLE")
        if not _launch_permitted(reservation):
            return _reservation_response(reservation)
        # A reservation is durable, but the receipt observed for it is not a
        # permanent launch permit. Its original expiry must still hold here;
        # obtaining a fresh callback would mask the P07 expiry race instead.
        if not _observation_current(host_observation):
            return _unavailable("HOST_OBSERVATION_EXPIRED")
        # The durable reservation may have taken arbitrary time.  Recheck the
        # fixed executable prefix and canonical workspace immediately before
        # Popen so a replaced symlink/target cannot inherit the reservation.
        if not _config_paths_current(self.config):
            return _unavailable("HOST_CONFIG_PATH_CHANGED")

        try:
            return_code, timed_out, stdout, stderr, output_over_limit = _run_bounded(
                argv,
                cwd=self.config.workspace_root,
                timeout_seconds=self.config.timeout_seconds,
            )
        except OSError:
            return _unavailable("HOST_PROCESS_START_FAILED")

        observation = _observation(
            operation=operation,
            argv=argv,
            request=request,
            host_observation=host_observation,
            return_code=return_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            output_over_limit=output_over_limit,
            reservation_id=str(reservation["reservation_id"]),
        )
        try:
            recorded = self.ledger.record_observation(
                str(request["attempt_id"]), observation
            )
        except Exception:
            return {
                "check_status": "unknown",
                "commit_status": "unknown",
                "launch_status": "execution_unknown",
                "reason_code": "HOST_OBSERVATION_PERSISTENCE_UNKNOWN",
                "real_host_status": "NOT_RUN",
            }
        if (
            not isinstance(recorded, Mapping)
            or recorded.get("status") != "pass"
            or recorded.get("recorded") is not True
        ):
            return {
                "check_status": "unknown",
                "commit_status": "unknown",
                "launch_status": "execution_unknown",
                "reason_code": "HOST_OBSERVATION_PERSISTENCE_UNKNOWN",
                "real_host_status": "NOT_RUN",
            }
        return {
            "check_status": "unknown",
            "commit_status": "confirmed_committed",
            "launch_status": (
                "timeout"
                if timed_out
                else (
                    "execution_unknown"
                    if output_over_limit
                    or not observation.get("stdout_utf8")
                    or observation.get("thread_id") is None
                    else "exited"
                )
            ),
            "attempt_id": request["attempt_id"],
            "thread_id": observation.get("thread_id"),
            "exit_status": return_code,
            "reason_code": "HOST_EXECUTION_OBSERVED",
            "real_host_status": "NOT_RUN",
        }


def _unavailable(code: str) -> dict[str, Any]:
    return {
        "check_status": "unknown",
        "commit_status": "not_attempted",
        "launch_status": "not_attempted",
        "reason_code": code,
        "real_host_status": "NOT_RUN",
    }


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _config_binding(config: CodexCliConfig) -> dict[str, object]:
    return {
        "executable_argv_prefix": list(config.executable_argv_prefix),
        "workspace_root": config.workspace_root,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "sandbox_mode": config.sandbox_mode,
        "approval_policy": config.approval_policy,
        "timeout_seconds": config.timeout_seconds,
    }


def _config_paths_current(config: CodexCliConfig) -> bool:
    paths = tuple(
        Path(item) for item in config.executable_argv_prefix if Path(item).is_absolute()
    )
    try:
        return (
            tuple(_executable_fingerprint(path) for path in paths)
            == config._path_fingerprints
            and (
                Path(config.workspace_root).stat().st_dev,
                Path(config.workspace_root).stat().st_ino,
            )
            == config._workspace_fingerprint
        )
    except OSError:
        return False


def _executable_fingerprint(path: Path) -> tuple[int, int, int, int, int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError("trusted executable path is not a regular file")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = path.stat()
    fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_size")
    before_identity = tuple(getattr(before, field) for field in fields)
    if (
        before_identity != tuple(getattr(after, field) for field in fields)
        or before_identity != tuple(getattr(current, field) for field in fields)
        or not stat.S_ISREG(current.st_mode)
    ):
        raise OSError("trusted executable changed while fingerprinting")
    return (*before_identity, digest.hexdigest())


def _validated_request(
    raw_request: Mapping[str, Any],
    *,
    prompt: str,
    config: CodexCliConfig,
    operation: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if (
        not isinstance(raw_request, Mapping)
        or not isinstance(prompt, str)
        or len(prompt) > _MAX_PROMPT_CHARS
        or "\x00" in prompt
    ):
        return None, "HOST_REQUEST_INVALID"
    try:
        prompt.encode("utf-8", "strict")
    except UnicodeEncodeError:
        return None, "HOST_PROMPT_ENCODING_INVALID"
    required = {
        "task_id",
        "attempt_id",
        "contract_version",
        "contract_digest",
        "baseline",
        "workspace_root",
        "controller_generation",
        "thread_id",
        "authorization_digest",
    }
    if set(raw_request) != required:
        return None, "HOST_REQUEST_FIELDS_INVALID"
    request = dict(raw_request)
    if not _identifier(request["task_id"]) or not _identifier(request["attempt_id"]):
        return None, "HOST_REQUEST_ID_INVALID"
    if (
        type(request["controller_generation"]) is not int
        or request["controller_generation"] < 0
    ):
        return None, "HOST_CONTROLLER_GENERATION_INVALID"
    if type(request["contract_version"]) not in {int, float, str} or isinstance(
        request["contract_version"], bool
    ):
        return None, "HOST_CONTRACT_VERSION_INVALID"
    if not all(
        isinstance(request[key], str) and _SHA256.fullmatch(request[key])
        for key in ("contract_digest", "authorization_digest")
    ):
        return None, "HOST_REQUEST_DIGEST_INVALID"
    if (
        not isinstance(request["baseline"], str)
        or not 1 <= len(request["baseline"]) <= 128
        or any(ord(char) < 32 or ord(char) == 127 for char in request["baseline"])
    ):
        return None, "HOST_BASELINE_INVALID"
    try:
        request["baseline"].encode("utf-8", "strict")
    except UnicodeEncodeError:
        return None, "HOST_BASELINE_INVALID"
    try:
        workspace = Path(str(request["workspace_root"])).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None, "HOST_WORKSPACE_UNAVAILABLE"
    if not workspace.is_dir() or str(workspace) != config.workspace_root:
        return None, "HOST_WORKSPACE_MISMATCH"
    if operation == "start_child" and request["thread_id"] is not None:
        return None, "HOST_START_THREAD_INVALID"
    if operation == "resume_child" and not _uuid(request["thread_id"]):
        return None, "HOST_RESUME_THREAD_INVALID"
    return request, None


def _argv_for(
    config: CodexCliConfig, request: Mapping[str, Any], prompt: str, *, operation: str
) -> tuple[list[str] | None, str | None]:
    # Codex 0.154.0 exposes -C/-s/--approve-for-me only for `exec`, not
    # `exec resume`.  Do not invent resume flags or imply the same isolation.
    overrides = [
        "-c",
        "model_reasoning_effort=" + json.dumps(config.reasoning_effort),
        "-c",
        "sandbox_mode=" + json.dumps(config.sandbox_mode),
        "-c",
        "approval_policy=" + json.dumps(config.approval_policy),
    ]
    if operation == "resume_child":
        # `resume` help intentionally has no -C/-s/approval flag.  Its process
        # cwd is exact, the model/config are fixed by trusted configuration, and
        # real enforcement remains an explicit host-level NOT_RUN claim.
        return [
            *config.executable_argv_prefix,
            "exec",
            "resume",
            str(request["thread_id"]),
            "-m",
            config.model,
            *overrides,
            "--json",
            "--",
            prompt,
        ], None
    if operation != "start_child":
        return None, "HOST_OPERATION_INVALID"
    argv = [
        *config.executable_argv_prefix,
        "exec",
        "-C",
        config.workspace_root,
        "-m",
        config.model,
        *overrides,
        "--json",
        "--",
        prompt,
    ]
    return argv, None


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _observe_host(
    callback: Callable[
        [Mapping[str, Any]],
        Mapping[str, Any],
    ],
    request: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    query = dict(request)
    try:
        observation = callback(query)
    except Exception:
        return None, "HOST_OBSERVATION_UNAVAILABLE"
    if not isinstance(observation, Mapping):
        return None, "HOST_OBSERVATION_MALFORMED"
    value = dict(observation)
    required = {
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
    identity, ref = value.get("host_identity_ref"), value.get("observation_ref")
    now = datetime.now(timezone.utc)
    valid = (
        set(value) == required
        and value.get("status") == "pass"
        and value.get("identity_status") == "pass"
        and value.get("authorization_status") == "pass"
        and value.get("exclusivity_status") == "exclusive"
        and value.get("thread_state") == "idle"
        and isinstance(identity, Mapping)
        and isinstance(identity.get("registered_identity_id"), str)
        and _SHA256.fullmatch(str(identity.get("sha256", "")))
        and isinstance(ref, Mapping)
        and isinstance(ref.get("ref_id"), str)
        and isinstance(ref.get("uri"), str)
        and _SHA256.fullmatch(str(ref.get("sha256", "")))
    )
    binding = {
        key: request[key]
        for key in ("task_id", "attempt_id", "thread_id", "workspace_root")
    }
    matches = all(
        value.get(key) == request.get(key)
        for key in (
            "task_id",
            "attempt_id",
            "thread_id",
            "workspace_root",
            "baseline",
            "controller_generation",
        )
    ) and value.get("request_binding_sha256") == _digest(binding)
    observed_at, expires_at = _parse_utc(value.get("observed_at")), _parse_utc(
        value.get("expires_at")
    )
    if (
        not valid
        or not matches
        or observed_at is None
        or expires_at is None
        or observed_at > now
        or expires_at < now
    ):
        return None, "HOST_OBSERVATION_UNVERIFIED"
    return value, None


def _launch_permitted(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("status") == "pass"
        and value.get("launch_allowed") is True
        and isinstance(value.get("reservation_id"), str)
        and bool(value["reservation_id"])
    )


def _observation_current(value: Mapping[str, Any] | None) -> bool:
    return value is not None and (
        _parse_utc(value.get("expires_at")) or datetime.min.replace(tzinfo=timezone.utc)
    ) >= datetime.now(timezone.utc)


def _reservation_response(value: object) -> dict[str, Any]:
    code = (
        value.get("reason_code")
        if isinstance(value, Mapping)
        else "HOST_LEDGER_RESERVE_MALFORMED"
    )
    return {
        "check_status": "unknown",
        "commit_status": "not_attempted",
        "launch_status": "not_attempted",
        "reason_code": (
            code if isinstance(code, str) else "HOST_LEDGER_RESERVE_MALFORMED"
        ),
        "real_host_status": "NOT_RUN",
    }


def _bounded_stdout(value: bytes) -> tuple[str, str, int, bool]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        # No UTF-8 archive can truthfully represent these bytes. Keep their
        # actual digest/size for audit, but leave the archive body empty and
        # force execution_unknown at the caller.
        return "", hashlib.sha256(value).hexdigest(), len(value), False
    return text, _sha256_text(text), len(value), True


def _observed_thread(
    stdout: bytes, *, event_type: str, expected_thread_id: str | None = None
) -> str | None:
    from . import _strict_handoff_json_load

    observed: str | None = None
    for raw_line in stdout.splitlines():
        if len(raw_line) > 64 * 1024:
            return None
        try:
            event = _strict_handoff_json_load(raw_line)
        except (UnicodeDecodeError, ValueError, RecursionError):
            # Invalid observations must still reach the ledger's raw-output
            # archive; parsing failure is not proof that execution did not run.
            return None
        if not isinstance(event, Mapping):
            return None
        if event.get("type") != event_type:
            continue
        if not _uuid(event.get("thread_id")):
            return None
        thread_id = str(event["thread_id"])
        if (expected_thread_id is not None and thread_id != expected_thread_id) or (
            observed is not None and observed != thread_id
        ):
            return None
        observed = thread_id
    return observed


def _observation(
    *,
    operation: str,
    argv: list[str],
    request: Mapping[str, Any],
    host_observation: Mapping[str, Any],
    return_code: int | None,
    timed_out: bool,
    stdout: bytes,
    stderr: bytes,
    output_over_limit: bool,
    reservation_id: str,
) -> dict[str, Any]:
    stdout_text, stdout_digest, stdout_bytes, stdout_utf8 = _bounded_stdout(stdout)
    stderr_digest = hashlib.sha256(stderr).hexdigest()
    stderr_bytes = len(stderr)
    observation: dict[str, Any] = {
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "reservation_id": reservation_id,
        "operation": operation,
        "argv_sha256": _digest(argv),
        "cwd": request["workspace_root"],
        # Codex CLI 0.154.0 exec JSONL emits `thread.started` for both a new
        # exec and resume; no `thread.resumed` event exists in that version.
        "thread_id": _observed_thread(
            stdout,
            event_type="thread.started",
            expected_thread_id=(
                request["thread_id"] if operation == "resume_child" else None
            ),
        ),
        "observed_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "host_identity_ref": dict(host_observation["host_identity_ref"]),
        "host_exclusivity_status": host_observation["exclusivity_status"],
        "host_observed_at": host_observation["observed_at"],
        "host_observation_ref": dict(host_observation["observation_ref"]),
        "stdout": stdout_text,
        "stdout_digest": stdout_digest,
        "stdout_bytes": stdout_bytes,
        "stdout_utf8": stdout_utf8,
        "stderr_digest": stderr_digest,
        "stderr_bytes": stderr_bytes,
        "output_over_limit": output_over_limit,
    }
    observation["timeout"] = True if timed_out else None
    observation["exit_status"] = None if timed_out else return_code
    return observation


def _run_bounded(
    argv: list[str], *, cwd: str, timeout_seconds: int
) -> tuple[int | None, bool, bytes, bytes, bool]:
    """Read both child streams incrementally and kill on the fixed output budget."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=os.name == "posix",
    )
    captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()

    def read_stream(name: str, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                remaining = _MAX_OUTPUT_BYTES - len(captured[name])
                if remaining > 0:
                    captured[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    _terminate_process_tree(process)
        finally:
            # The reader owns this BufferedReader.  A descendant may retain
            # its pipe beyond the direct child; do not make the main thread
            # close a stream that is still blocked in read().
            try:
                stream.close()
            except OSError:
                pass

    threads = [
        threading.Thread(
            target=read_stream, args=("stdout", process.stdout), daemon=True
        ),
        threading.Thread(
            target=read_stream, args=("stderr", process.stderr), daemon=True
        ),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        process.wait()
    for thread in threads:
        thread.join(timeout=1)
    # A descendant may deliberately retain the inherited pipe after a normal
    # direct-child exit.  Without a timeout or exceeded budget, do not kill that
    # process family; bounded daemon readers close descriptors after draining.
    incomplete = any(thread.is_alive() for thread in threads)
    return (
        process.returncode,
        timed_out,
        bytes(captured["stdout"]),
        bytes(captured["stderr"]),
        exceeded.is_set() or incomplete,
    )


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - Prime Agent targets POSIX hosts.
            process.kill()
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
