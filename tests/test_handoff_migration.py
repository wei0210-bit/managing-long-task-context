"""E1-04 isolated real-0.7.0 migration boundary tests.

These are deliberately a local process mechanism analogy, not a Codex/Claude
host migration claim.  Every prepare attempt uses the public current API and
its authorizer re-observes parent-owned process state at authorization time.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote, urlsplit

import managing_long_task_context as context


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
FIXTURE = ROOT / "tests" / "handoff_migration_fixture.py"
OLD_MANIFEST_SHA256 = "3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reference(task_id: str, ref_id: str, path: Path) -> dict[str, str]:
    return {"ref_id": ref_id, "task_id": task_id, "uri": path.as_uri(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class ControlledLegacyLauncher:
    """Test-only launcher registry; refusal is observable, not self-reported."""

    def __init__(self) -> None:
        self._sealed: set[str] = set()
        self.started: list[int] = []
        self.refused: list[str] = []

    def start(self, identity: str, command: list[str], *, env: dict[str, str]) -> subprocess.Popen[str] | None:
        if identity in self._sealed:
            self.refused.append(identity)
            return None
        process = subprocess.Popen(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
        self.started.append(process.pid)
        return process

    def seal_after_exit(self, identity: str, process: subprocess.Popen[str]) -> bool:
        if process.poll() != 0:
            return False
        self._sealed.add(identity)
        return True

    def restart_blocked(self, identity: str) -> bool:
        return identity in self._sealed


class MigrationVerifier:
    """Reads fixture files and validates a fixed record; it never reflects pass."""

    def __init__(self, record: dict[str, object], contents: dict[str, str]) -> None:
        self.record = deepcopy(record)
        self.contents = dict(contents)

    def verify(self, request: dict[str, object]) -> dict[str, object]:
        refs = [self.record["source_session_ref"], self.record["target_session_ref"], self.record["authorization_ref"], *self.record["basis_refs"], self.record["artifact_manifest_ref"]]
        for reference in refs:
            assert isinstance(reference, dict)
            path = Path(unquote(urlsplit(str(reference["uri"])).path))
            if path.read_text(encoding="utf-8") != self.contents[reference["ref_id"]]:
                return {"status": "fail"}
        expected = {key: self.record[key] for key in ("task_id", "handoff_id", "contract_version", "contract_digest", "workspace_root", "package_manifest_sha256", "controller_generation")}
        expected["record_sha256"] = _digest(self.record)
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {"status": "pass", "identity_status": "pass", "authorization_status": "pass", "content_status": "pass", **expected, "verification_refs": refs, "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}


class ObservingMigrationAuthorizer:
    """Authorization is granted only from an independent parent process observation."""

    def __init__(self, record: dict[str, object], identity: object, observation: callable) -> None:
        self.record, self.identity, self.observation = deepcopy(record), identity, observation
        self.observations: list[dict[str, object]] = []
        self.decisions: list[str] = []

    def authorize(self, request: dict[str, object]) -> dict[str, object]:
        observed = dict(self.observation())
        self.observations.append(observed)
        # This is intentionally calculated at the authorization callback.  A
        # stale earlier observation cannot be promoted to a grant.
        if not observed.get("process_observation_complete"):
            self.decisions.append("unknown:exit-not-observed")
            return {"status": "unknown"}
        if observed.get("poll") != 0 or not observed.get("restart_blocked"):
            self.decisions.append("fail:legacy-process-not-retired")
            return {"status": "fail"}
        if observed.get("registered_identity") is not self.identity:
            self.decisions.append("fail:registered-identity-mismatch")
            return {"status": "fail"}
        if request.get("runtime_identity") is not self.identity:
            self.decisions.append("fail:runtime-identity")
            return {"status": "fail"}
        expected = {"operation": "prepare_handoff", "task_id": self.record["task_id"], "base_dir": observed["base_dir"], "workspace_root": self.record["workspace_root"], **{key: self.record[key] for key in ("package_manifest_sha256", "contract_version", "contract_digest", "controller_generation", "handoff_id")}}
        if any(request.get(key) != value for key, value in expected.items()):
            self.decisions.append("unknown:request-binding")
            return {"status": "unknown"}
        arguments = request.get("arguments")
        if not isinstance(arguments, dict) or request.get("arguments_sha256") != _digest(arguments):
            self.decisions.append("unknown:arguments-binding")
            return {"status": "unknown"}
        self.decisions.append("pass")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {"status": "pass", **expected, "arguments_sha256": _digest(arguments), "purpose": "prepare", "subject_id": "synthetic:observed-controller", "role": "controller", "scope_digest": "a" * 64, "work_item_id": None, "source_session_ref": deepcopy(self.record["source_session_ref"]), "target_session_ref": deepcopy(self.record["target_session_ref"]), "authorization_ref": deepcopy(self.record["authorization_ref"]), "target_activation_status": "not_activated", "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}


class HandoffMigrationTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        configured_package = os.environ.get("MLTC_LEGACY_PACKAGE")
        if configured_package is None:
            raise unittest.SkipTest("MLTC_LEGACY_PACKAGE is required for real-old-package migration tests")
        cls.old_package = Path(configured_package)
        if not cls.old_package.is_dir():
            raise AssertionError("MLTC_LEGACY_PACKAGE does not name a readable package directory")
        manifest = cls.old_package / "skill-manifest.json"
        if not manifest.is_file():
            raise AssertionError("MLTC_LEGACY_PACKAGE has no skill-manifest.json")
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != OLD_MANIFEST_SHA256:
            raise AssertionError("MLTC_LEGACY_PACKAGE manifest SHA256 differs from frozen 0.7.0 baseline")
        verified = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "skill_package.py"), "verify", "--package", str(cls.old_package), "--expected-manifest-sha256", OLD_MANIFEST_SHA256],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if verified.returncode != 0:
            raise AssertionError(f"frozen old package verification failed: {verified.stderr or verified.stdout}")
        try:
            result = json.loads(verified.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError("frozen old package verifier returned non-JSON output") from exc
        if result.get("status") != "pass" or result.get("stats", {}).get("files_checked") != 45:
            raise AssertionError(f"frozen old package verifier did not validate complete baseline: {result}")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.base, self.workspace, self.package = root / "context", root / "workspace", root / "package"
        self.workspace.mkdir()
        self.package.mkdir()
        (self.package / "skill-manifest.json").write_text("isolated migration package\n", encoding="utf-8")
        self.task_id, self.handoff_id = "TASK-MIGRATION-001", "HO-MIGRATION-001"
        published = context.publish_contract({"schema": 1, "task_id": self.task_id, "version": 1, "issued_by": "fixture", "issued_at": "2026-09-15T00:00:00Z", "authorized_approvers": [], "objective": "isolated migration", "scope": ["synthetic"], "out_of_scope": [], "constraints": ["no business action"], "acceptance_criteria": [{"id": "AC-01", "criterion": "local mechanism", "required_evidence": ["fixture"]}]}, confirmed_by="fixture", base_dir=self.base)
        cursor = json.loads((self.base / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
        self.contents = {"source": "registered old controller\n", "target": "registered candidate\n", "authorization": "local delegated scope\n", "basis": "local bearing evidence\n", "artifacts": "local artifact manifest\n"}
        refs = {}
        for ref_id, content in self.contents.items():
            path = self.workspace / f"{ref_id}.txt"
            path.write_text(content, encoding="utf-8")
            refs[ref_id] = _reference(self.task_id, ref_id, path)
        self.record: dict[str, object] = {"protocol": "short-session-handoff/v1", "task_id": self.task_id, "contract_version": 1, "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"), "workspace_root": str(self.workspace.resolve()), "package_manifest_sha256": hashlib.sha256((self.package / "skill-manifest.json").read_bytes()).hexdigest(), "handoff_id": self.handoff_id, "request_id": "REQ-MIGRATION-001", "controller_generation": 0, "source_session_ref": refs["source"], "target_session_ref": refs["target"], "authorization_ref": refs["authorization"], "basis_refs": [refs["basis"]], "artifact_manifest_ref": refs["artifacts"], "created_at": "2026-09-15T00:00:01Z", "event_cursor": cursor}
        self.launcher = ControlledLegacyLauncher()
        self._children: dict[int, tuple[subprocess.Popen[str], queue.Queue[str | None], threading.Thread]] = {}

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(self.old_package / "src")})
        return environment

    def _spawn_old(self, *, gate: Path | None = None, through_launcher: bool = True) -> subprocess.Popen[str]:
        self.assertTrue((self.old_package / "skill-manifest.json").is_file())
        config = Path(self.temporary.name) / f"legacy-{len(self._children)}.json"
        value: dict[str, object] = {"task_id": self.task_id, "base_dir": str(self.base.resolve())}
        if gate is not None:
            value["gate_path"] = str(gate)
        config.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        command = [PYTHON, str(FIXTURE), "legacy_writer", str(config)]
        child = (self.launcher.start("legacy:0.7.0", command, env=self._environment()) if through_launcher
                 else subprocess.Popen(command, cwd=ROOT, env=self._environment(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1))
        self.assertIsNotNone(child, "launcher unexpectedly refused initial old identity")
        assert child is not None and child.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()
        def collect() -> None:
            assert child.stdout is not None
            for line in child.stdout:
                lines.put(line)
            lines.put(None)
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        self._children[id(child)] = (child, lines, reader)
        self.addCleanup(self._cleanup_child, child)
        return child

    def _cleanup_child(self, child: subprocess.Popen[str]) -> None:
        state = self._children.get(id(child))
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.fail("old child did not exit after cleanup kill")
        if state is not None:
            _, _lines, reader = state
            reader.join(timeout=5)
            self.assertFalse(reader.is_alive(), "old child stdout reader did not exit")
        for stream in (child.stdout, child.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _phase(self, child: subprocess.Popen[str]) -> dict[str, object]:
        _process, lines, _reader = self._children[id(child)]
        try:
            raw = lines.get(timeout=5)
        except queue.Empty:
            self.fail(f"old child did not emit phase; rc={child.poll()}")
        self.assertIsNotNone(raw, f"old child closed stdout; rc={child.poll()}")
        return json.loads(str(raw))

    def _finish(self, child: subprocess.Popen[str]) -> tuple[int, list[dict[str, object]], str]:
        self.assertIsNotNone(child.stdout)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
            self.fail("old child deadlocked")
        _process, lines, reader = self._children[id(child)]
        reader.join(timeout=5)
        self.assertFalse(reader.is_alive(), "old child stdout reader did not finish")
        raw: list[str] = []
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                raw.append(line)
        stderr = child.stderr.read() if child.stderr is not None else ""
        return child.returncode, [json.loads(line) for line in raw if line.strip()], stderr

    def _prepared_count(self) -> int:
        event_path = self.base / self.task_id / "events.jsonl"
        return sum(json.loads(line)["event_type"] == "handoff_prepared" for line in event_path.read_text(encoding="utf-8").splitlines())

    def _prepare(self, authorizer: ObservingMigrationAuthorizer, *, identity: object) -> dict[str, object]:
        return context.prepare_handoff(self.task_id, base_dir=self.base, workspace_root=self.workspace, package_root=self.package, request_id=str(self.record["request_id"]), controller_generation=0, record=self.record, runtime_identity=identity, write_authorizer=authorizer, handoff_verifier=MigrationVerifier(self.record, self.contents))

    def _old_identity(self, child: subprocess.Popen[str]) -> None:
        loaded = self._phase(child)
        self.assertEqual(loaded["stage"], "legacy_loaded", loaded)
        self.assertEqual(loaded["pid"], child.pid, loaded)
        self.assertEqual(loaded["manifest_sha256"], OLD_MANIFEST_SHA256, loaded)
        self.assertTrue(str(loaded["module_file"]).startswith(str(self.old_package / "src")), loaded)

    def test_writer_active_authorizer_denies_current_prepare_before_old_write(self) -> None:
        gate = Path(self.temporary.name) / "active-gate"
        os.mkfifo(gate)
        child = self._spawn_old(gate=gate)
        self._old_identity(child)
        identity = object()
        def active() -> dict[str, object]:
            return {"pid": child.pid, "poll": child.poll(), "process_observation_complete": True, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": identity}
        authorizer = ObservingMigrationAuthorizer(self.record, identity, active)
        result = self._prepare(authorizer, identity=identity)
        self.assertEqual(result["check_status"], "unknown", result)
        self.assertEqual(len(authorizer.observations), 1)
        self.assertIsNone(authorizer.observations[0]["poll"])
        self.assertEqual(authorizer.decisions, ["fail:legacy-process-not-retired"])
        self.assertEqual(self._prepared_count(), 0)
        with gate.open("wb", buffering=0) as release:
            release.write(b"G")
        rc, lines, stderr = self._finish(child)
        self.assertEqual(rc, 0, (lines, stderr))
        self.assertEqual(lines[-1]["status"], "pass", lines)

    def test_exit_unknown_authorizer_denies_current_prepare(self) -> None:
        child = self._spawn_old()
        self._old_identity(child)
        rc, lines, stderr = self._finish(child)
        self.assertEqual(rc, 0, (lines, stderr))
        identity = object()
        def unknown_exit() -> dict[str, object]:
            # The parent did observe rc=0 above, but this host callback is
            # deliberately denied that trusted exit observation.
            return {"pid": child.pid, "poll": None, "process_observation_complete": False, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": identity}
        authorizer = ObservingMigrationAuthorizer(self.record, identity, unknown_exit)
        result = self._prepare(authorizer, identity=identity)
        self.assertEqual(result["check_status"], "unknown", result)
        self.assertIsNone(authorizer.observations[0]["poll"])
        self.assertFalse(authorizer.observations[0]["restart_blocked"])
        self.assertEqual(authorizer.decisions, ["unknown:exit-not-observed"])
        self.assertEqual(self._prepared_count(), 0)

    def test_observed_exit_then_actual_restart_denies_current_prepare(self) -> None:
        first = self._spawn_old()
        self._old_identity(first)
        self.assertEqual(self._finish(first)[0], 0)
        gate = Path(self.temporary.name) / "restart-gate"
        os.mkfifo(gate)
        second = self._spawn_old(gate=gate)
        self._old_identity(second)
        self.assertNotEqual(first.pid, second.pid)
        identity = object()
        def restarted() -> dict[str, object]:
            return {"first_pid": first.pid, "pid": second.pid, "poll": second.poll(), "process_observation_complete": True, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": identity}
        authorizer = ObservingMigrationAuthorizer(self.record, identity, restarted)
        result = self._prepare(authorizer, identity=identity)
        self.assertEqual(result["check_status"], "unknown", result)
        self.assertIsNone(authorizer.observations[0]["poll"])
        self.assertEqual(authorizer.decisions, ["fail:legacy-process-not-retired"])
        self.assertEqual(self._prepared_count(), 0)
        with gate.open("wb", buffering=0) as release:
            release.write(b"G")
        self.assertEqual(self._finish(second)[0], 0)

    def test_invalid_runtime_identity_does_not_turn_safe_exit_into_a_prepare(self) -> None:
        child = self._spawn_old()
        self._old_identity(child)
        self.assertEqual(self._finish(child)[0], 0)
        self.assertTrue(self.launcher.seal_after_exit("legacy:0.7.0", child))
        registered = object()
        def safe() -> dict[str, object]:
            return {"pid": child.pid, "poll": child.poll(), "process_observation_complete": True, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": registered}
        authorizer = ObservingMigrationAuthorizer(self.record, registered, safe)
        result = self._prepare(authorizer, identity=object())
        self.assertEqual(result["check_status"], "unknown", result)
        self.assertEqual(authorizer.observations[0]["poll"], 0)
        self.assertTrue(authorizer.observations[0]["restart_blocked"])
        self.assertEqual(authorizer.decisions, ["fail:runtime-identity"])
        self.assertEqual(self._prepared_count(), 0)

    def test_verified_exit_and_launcher_refusal_prepare_once_without_generation_increase(self) -> None:
        child = self._spawn_old()
        self._old_identity(child)
        self.assertEqual(self._finish(child)[0], 0)
        self.assertTrue(self.launcher.seal_after_exit("legacy:0.7.0", child))
        identity = object()
        def safe() -> dict[str, object]:
            return {"pid": child.pid, "poll": child.poll(), "process_observation_complete": True, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": identity}
        authorizer = ObservingMigrationAuthorizer(self.record, identity, safe)
        first = self._prepare(authorizer, identity=identity)
        self.assertEqual(first["check_status"], "pass", first)
        self.assertEqual(first["commit_status"], "confirmed_committed", first)
        self.assertEqual(first["controller_generation"], 0, first)
        self.assertEqual(self._prepared_count(), 1)
        self.assertEqual(authorizer.decisions, ["pass"])
        retry = self._prepare(authorizer, identity=identity)
        self.assertEqual(retry["check_status"], "pass", retry)
        self.assertEqual(retry["controller_generation"], 0, retry)
        self.assertEqual(self._prepared_count(), 1)
        refused = self.launcher.start("legacy:0.7.0", [PYTHON, str(FIXTURE), "legacy_writer", "unused"], env=self._environment())
        self.assertIsNone(refused)
        self.assertEqual(self.launcher.refused, ["legacy:0.7.0"])

    def test_real_old_writer_can_bypass_current_fence_after_prepare(self) -> None:
        child = self._spawn_old()
        self._old_identity(child)
        self.assertEqual(self._finish(child)[0], 0)
        self.assertTrue(self.launcher.seal_after_exit("legacy:0.7.0", child))
        identity = object()
        def safe() -> dict[str, object]:
            return {"pid": child.pid, "poll": child.poll(), "process_observation_complete": True, "base_dir": str(self.base.resolve()), "restart_blocked": self.launcher.restart_blocked("legacy:0.7.0"), "registered_identity": identity}
        prepared = self._prepare(ObservingMigrationAuthorizer(self.record, identity, safe), identity=identity)
        self.assertEqual(prepared["check_status"], "pass", prepared)
        before_events = [json.loads(line) for line in (self.base / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        before_ids = {event["event_id"] for event in before_events}
        # The launcher refuses only identities started through it.  A separately
        # started real-old process is the exact residual risk: it knows no new
        # fence and can still call the old public writer.
        bypass = self._spawn_old(through_launcher=False)
        self._old_identity(bypass)
        rc, lines, stderr = self._finish(bypass)
        self.assertEqual(rc, 0, (lines, stderr))
        self.assertEqual(lines[-1]["status"], "pass", lines)
        events = [json.loads(line) for line in (self.base / self.task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        new_events = [event for event in events if event["event_id"] not in before_ids]
        self.assertEqual([event["event_type"] for event in new_events], ["item-recorded"], new_events)
        self.assertEqual(new_events[0]["payload"]["item"]["id"], lines[-1]["item_id"], new_events)


if __name__ == "__main__":
    unittest.main()
