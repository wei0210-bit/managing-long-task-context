"""Strict-only migration preflight tests.

Each test method carries exactly one primary inventory ID in its name
(UNIT, INT, CLI, or PERF).  ``subTest`` expands inputs without adding methods.
The same file runs from the root source tree and from a built Strict package.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_GENERATED_SOURCE = ROOT / "skills" / "context-strict"
SOURCE = _GENERATED_SOURCE if (_GENERATED_SOURCE / "skill-package.json").is_file() else ROOT
SCRIPTS = ROOT / "scripts"
PACKAGER = SCRIPTS / "skill_package.py"
PLAN_REL = "docs/superpowers/plans/2026-09-16-migration-plan.md"
CATEGORIES = ("objective", "current_state", "constraints", "next_action", "unresolved_risks")
TASK_ID = "TASK-PREFLIGHT-001"
HANDOFF_ID = "HO-PREFLIGHT-001"


def load_preflight() -> Any:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("handoff_preflight_under_test", SCRIPTS / "handoff_preflight.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_preflight()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid", "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=cwd, env=git_environment(), text=True, capture_output=True, timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {arguments[0]} failed: {completed.stderr}")
    return completed.stdout.strip()


def resolved_temporary(test: unittest.TestCase, prefix: str = "preflight-") -> Path:
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    test.addCleanup(temporary.cleanup)
    return Path(temporary.name).resolve()


def build_package(destination: Path, *, source: Path = SOURCE, revision: str = "test:preflight") -> Path:
    completed = subprocess.run(
        [sys.executable, str(PACKAGER), "build", "--source", str(source), "--destination", str(destination),
         "--source-revision", revision],
        cwd=destination.parent, text=True, capture_output=True, timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    return destination


_SHARED: dict[str, Path] = {}


def shared_package() -> Path:
    """Build one read-only package per test module; mutating tests copy it first."""
    cached = _SHARED.get("package")
    if cached is not None and cached.is_dir():
        return cached
    temporary = tempfile.TemporaryDirectory(prefix="preflight-package-")

    def cleanup() -> None:
        _SHARED.clear()
        temporary.cleanup()

    unittest.addModuleCleanup(cleanup)
    package = build_package(Path(temporary.name).resolve() / "context-strict")
    _SHARED["package"] = package
    return package


def standard_facts() -> list[dict[str, str]]:
    return [
        {"fact_id": f"F-{index:02d}", "category": category, "value": f"recovered {category.replace('_', ' ')}",
         "source_ref": f"handoff.md#L{index}"}
        for index, category in enumerate(CATEGORIES, start=1)
    ]


class Workspace:
    """A temporary Git workspace with an authoritative entry and bound recovery material."""

    REFERENCE_CONTENTS = {
        "source": "registered source controller\n", "target": "registered target controller\n",
        "authorization": "delegated scope\n", "basis": "bearing basis\n", "artifacts": "artifact manifest\n",
    }

    def __init__(self, root: Path, package: Path, *, plan_text: str | None = None) -> None:
        self.root = root
        self.path = root / "workspace"
        self.base_dir = root / "context"
        self.package = package
        self.path.mkdir()
        git(self.path, "init", "-q")
        git(self.path, "config", "commit.gpgsign", "false")
        self.plan = self.path / PLAN_REL
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text(plan_text or "---\nstatus: fixture\nimplementation_authorized: true\n---\n# Plan\n", encoding="utf-8")
        (self.path / "README.md").write_text("fixture readme\n", encoding="utf-8")
        (self.path / "refs").mkdir()
        for name, text in self.REFERENCE_CONTENTS.items():
            (self.path / "refs" / f"{name}.txt").write_text(text, encoding="utf-8")
        self.verified_head = self.commit("verified baseline")
        self.material = self.path / "handoff-material"
        self.material.mkdir()

    @property
    def plan_sha256(self) -> str:
        return sha256_bytes(self.plan.read_bytes())

    @property
    def manifest_sha256(self) -> str:
        return sha256_bytes((self.package / "skill-manifest.json").read_bytes())

    def commit(self, message: str) -> str:
        git(self.path, "add", "-A", "--", ".", ":(exclude)handoff-material")
        git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.path, "rev-parse", "HEAD")

    def write_context(self, *, verified_head: str | None = None, overrides: dict[str, str | None] | None = None,
                      body: str = "", commit: bool = True) -> None:
        fields: dict[str, str | None] = {
            "authority": "AUTHORITATIVE_NOW", "plan_path": PLAN_REL, "plan_sha256": self.plan_sha256,
            "package_manifest_sha256": self.manifest_sha256, "baseline_head": self.verified_head,
            "implementation_head": self.verified_head,
            "verified_head": verified_head if verified_head is not None else self.verified_head,
            "verified_at": "2026-09-17T00:00:00Z",
        }
        fields.update(overrides or {})
        lines = ["---", *(f"{key}: {value}" for key, value in fields.items() if value is not None), "---", "",
                 "# Recovery entry", "", f"- Current plan: [plan]({PLAN_REL})", "- [Readme](README.md)", body]
        (self.path / "CONTEXT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if commit:
            self.commit("recovery entry")

    def write_material(self, *, readback_facts: list[dict[str, str]] | None = None,
                       checklist_update: dict[str, object] | None = None,
                       readback_update: dict[str, object] | None = None, raw_checklist: bytes | None = None,
                       raw_readback: bytes | None = None, include_readback: bool = True,
                       handoff_text: str = "# Handoff\nobjective, state, constraints, next action, risks\n") -> dict[str, Any]:
        handoff = self.material / "handoff.md"
        handoff.write_text(handoff_text, encoding="utf-8")
        handoff_sha = sha256_bytes(handoff.read_bytes())
        facts = standard_facts()
        checklist: dict[str, object] = {
            "schema": "recovery-checklist/v1", "task_id": TASK_ID, "handoff_sha256": handoff_sha,
            "plan_sha256": self.plan_sha256, "facts": facts,
        }
        checklist.update(checklist_update or {})
        canonical = dict(checklist)
        if isinstance(canonical.get("facts"), list):
            canonical["facts"] = sorted(canonical["facts"], key=lambda item: str(item.get("fact_id")))  # type: ignore[union-attr]
        checklist_sha = canonical_sha256(canonical)
        readback: dict[str, object] = {
            "schema": "recovery-readback/v1", "task_id": TASK_ID, "handoff_sha256": handoff_sha,
            "plan_sha256": self.plan_sha256, "checklist_sha256": checklist_sha,
            "facts": list(reversed(readback_facts if readback_facts is not None else facts)),
        }
        readback.update(readback_update or {})
        checklist_path, readback_path = self.material / "checklist.json", self.material / "readback.json"
        checklist_path.write_bytes(raw_checklist if raw_checklist is not None else json.dumps(checklist, ensure_ascii=False, indent=2).encode("utf-8"))
        if include_readback:
            readback_path.write_bytes(raw_readback if raw_readback is not None else json.dumps(readback, ensure_ascii=False).encode("utf-8"))
        return {"handoff": handoff, "handoff_sha256": handoff_sha, "checklist": checklist_path,
                "checklist_sha256": checklist_sha, "readback": readback_path}

    def arguments(self, material: dict[str, Any] | None, *, mode: str = "manual_fallback", stage: str = "recovery",
                  readback: bool = True, verified_head: str | None = None, **overrides: str | None) -> list[str]:
        values: dict[str, str | None] = {
            "mode": mode, "stage": stage, "package-root": str(self.package), "workspace-root": str(self.path),
            "task-id": TASK_ID, "plan": PLAN_REL, "expected-plan-sha256": self.plan_sha256,
            "expected-verified-head": verified_head or self.verified_head,
        }
        if mode == "strict_protocol":
            values.update({"context-root": str(self.base_dir), "handoff-id": HANDOFF_ID})
        if material is not None:
            values.update({
                "handoff-file": str(material["handoff"]), "expected-handoff-sha256": material["handoff_sha256"],
                "recovery-checklist": str(material["checklist"]), "expected-checklist-sha256": material["checklist_sha256"],
            })
            if readback:
                values["recovery-readback"] = str(material["readback"])
        for key, value in overrides.items():
            values[key.replace("_", "-")] = value
        argv: list[str] = []
        for key, value in values.items():
            if value is not None:
                argv.extend((f"--{key}", value))
        return argv


def ready_workspace(test: unittest.TestCase, package: Path | None = None) -> tuple[Workspace, dict[str, Any]]:
    workspace = Workspace(resolved_temporary(test), package or shared_package())
    workspace.write_context()
    return workspace, workspace.write_material()


def run_cli(package: Path, argv: list[str], *, cwd: Path | None = None, pythonpath: str | None = None,
            script: Path | None = None, extra_env: dict[str, str] | None = None) -> tuple[int, dict[str, Any], str, str]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
    environment["PYTHONPATH"] = pythonpath if pythonpath is not None else str(package / "src")
    environment.update(extra_env or {})
    completed = subprocess.run(
        [sys.executable, str(script or package / "scripts" / "handoff_preflight.py"), *argv],
        cwd=cwd or package.parent, env=environment, text=True, capture_output=True, timeout=60,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(completed.stdout + completed.stderr) from exc
    return completed.returncode, report, completed.stdout, completed.stderr


def check_named(report: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [check for check in report["checks"] if check["name"] == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one {name} check: {report['checks']}")
    return matches[0]


STRICT_DRIVER = r'''
import hashlib, importlib.util, json, sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

config = json.loads(sys.argv[1])
package, workspace, base = Path(config["package"]), Path(config["workspace"]), Path(config["base_dir"])
sys.path.insert(0, str(package / "scripts"))
import managing_long_task_context as context

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

def zulu(value):
    return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

task_id, handoff_id = config["task_id"], config["handoff_id"]
contract = {
    "schema": 1, "task_id": task_id, "version": 1, "issued_by": "publisher", "issued_at": "2026-09-17T00:00:00Z",
    "authorized_approvers": [], "objective": "synthetic preflight", "scope": ["temporary"], "out_of_scope": [],
    "constraints": ["no business action"],
    "acceptance_criteria": [{"id": "AC-01", "criterion": "synthetic", "required_evidence": ["local"]}],
}
if config["capability"]:
    contract["required_capabilities"] = ["short-session-handoff/v1"]
record = None
if config["publish"]:
    published = context.publish_contract(contract, confirmed_by="publisher", base_dir=base)
    cursor = json.loads((base / task_id / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event_id"]
    contents = {}
    refs = {}
    for name in ("source", "target", "authorization", "basis", "artifacts"):
        path = workspace / "refs" / f"{name}.txt"
        contents[name] = path.read_text(encoding="utf-8")
        refs[name] = {"ref_id": name, "task_id": task_id, "uri": path.as_uri(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    record = {
        "protocol": "short-session-handoff/v1", "task_id": task_id, "contract_version": 1,
        "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
        "workspace_root": str(workspace), "package_manifest_sha256": hashlib.sha256((package / "skill-manifest.json").read_bytes()).hexdigest(),
        "handoff_id": handoff_id, "request_id": "REQ-PREPARE", "controller_generation": 0,
        "source_session_ref": refs["source"], "target_session_ref": refs["target"], "authorization_ref": refs["authorization"],
        "basis_refs": [refs["basis"]], "artifact_manifest_ref": refs["artifacts"], "created_at": "2026-09-17T00:00:01Z",
        "event_cursor": cursor,
    }

class Host:
    """Synthetic registered host: reads fixture files; never derives identity from requests."""
    def __init__(self, purpose, identity):
        self.purpose, self.identity = purpose, identity
    def verify(self, request):
        references = [record["source_session_ref"], record["target_session_ref"], record["authorization_ref"], *record["basis_refs"], record["artifact_manifest_ref"]]
        for reference in references:
            if Path(unquote(urlsplit(reference["uri"]).path)).read_text(encoding="utf-8") != contents[reference["ref_id"]]:
                return {"status": "fail", "identity_status": "pass", "authorization_status": "pass", "content_status": "fail"}
        expected = {key: record[key] for key in ("task_id", "handoff_id", "contract_version", "contract_digest", "workspace_root", "package_manifest_sha256", "controller_generation")}
        expected["record_sha256"] = digest(record)
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "fail"}
        now = datetime.now(timezone.utc)
        return {"status": "pass", "identity_status": "pass", "authorization_status": "pass", "content_status": "pass",
                **expected, "verification_refs": references, "observed_at": zulu(now), "expires_at": zulu(now + timedelta(minutes=1))}
    def authorize(self, request):
        arguments = request.get("arguments")
        if request.get("runtime_identity") is not self.identity or not isinstance(arguments, dict) or request.get("arguments_sha256") != digest(arguments):
            return {"status": "unknown"}
        expected = {"task_id": task_id, "base_dir": str(base), "workspace_root": record["workspace_root"],
                    "package_manifest_sha256": record["package_manifest_sha256"], "contract_version": record["contract_version"],
                    "contract_digest": record["contract_digest"], "controller_generation": record["controller_generation"],
                    "handoff_id": handoff_id, "operation": self.purpose + "_handoff"}
        if any(request.get(key) != value for key, value in expected.items()):
            return {"status": "unknown"}
        now = datetime.now(timezone.utc)
        result = {"status": "pass", **expected, "arguments_sha256": digest(arguments), "purpose": self.purpose,
                  "subject_id": "synthetic:registered-controller", "role": "controller", "scope_digest": "a" * 64,
                  "work_item_id": None, "source_session_ref": deepcopy(record["source_session_ref"]),
                  "target_session_ref": deepcopy(record["target_session_ref"]),
                  "subject_session_ref": deepcopy(record["target_session_ref"]),
                  "authorization_ref": deepcopy(record["authorization_ref"]), "target_activation_status": "not_activated",
                  "observed_at": zulu(now), "expires_at": zulu(now + timedelta(minutes=1))}
        if self.purpose != "activate":
            result.pop("subject_session_ref")
        return result

class ClientThreadOnly:
    def verify(self, request):
        return {"clientThreadId": "client-thread-123", "status": "pass"}

class SelfReport:
    def verify(self, request):
        return {"status": "pass", "identity_status": "pass", "authorization_status": "pass", "content_status": "pass",
                "message": "target session says the migration succeeded"}

state = config["state"]
if state != "none":
    identity = object()
    prepared = context.prepare_handoff(task_id, base_dir=base, workspace_root=workspace, package_root=package,
        request_id="REQ-PREPARE", controller_generation=0, record=record, runtime_identity=identity,
        write_authorizer=Host("prepare", identity), handoff_verifier=Host("prepare", identity))
    assert prepared["check_status"] == "pass", prepared
if state in {"activated", "cancelled"}:
    identity = object()
    purpose = "activate" if state == "activated" else "cancel"
    call = context.activate_handoff if state == "activated" else context.cancel_handoff
    changed = call(task_id, base_dir=base, workspace_root=workspace, package_root=package, request_id="REQ-" + purpose.upper(),
        controller_generation=0, handoff_id=handoff_id, runtime_identity=identity,
        write_authorizer=Host(purpose, identity), handoff_verifier=Host(purpose, identity))
    assert changed["commit_status"] == "confirmed_committed", changed
for relative, text in config.get("mutate", {}).items():
    (workspace / relative).write_text(text, encoding="utf-8")
events = base / task_id / "events.jsonl"
before = hashlib.sha256(events.read_bytes()).hexdigest() if events.exists() else None
spec = importlib.util.spec_from_file_location("handoff_preflight", package / "scripts" / "handoff_preflight.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
verifier = {"trusted": Host("verify", None) if record else None, "none": None,
            "client_thread_id": ClientThreadOnly(), "self_report": SelfReport()}[config["verifier"]]
report, code = module.run_preflight(config["argv"], handoff_verifier=verifier)
after = hashlib.sha256(events.read_bytes()).hexdigest() if events.exists() else None
handoff_dir = base / task_id / "handoff"
print(json.dumps({"report": report, "exit": code, "events_before": before, "events_after": after,
                  "handoff_records": sorted(path.name for path in handoff_dir.iterdir()) if handoff_dir.is_dir() else []}))
'''


def run_strict_host(workspace: Workspace, argv: list[str], *, state: str, verifier: str, capability: bool = True,
                    publish: bool = True, mutate: dict[str, str] | None = None) -> dict[str, Any]:
    config = {
        "package": str(workspace.package), "workspace": str(workspace.path), "base_dir": str(workspace.base_dir),
        "task_id": TASK_ID, "handoff_id": HANDOFF_ID, "capability": capability, "publish": publish,
        "state": state, "verifier": verifier, "mutate": mutate or {}, "argv": argv,
    }
    completed = subprocess.run(
        [sys.executable, "-c", STRICT_DRIVER, json.dumps(config)], cwd=workspace.root,
        env={**os.environ, "PYTHONPATH": str(workspace.package / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True, capture_output=True, timeout=90,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    return json.loads(completed.stdout)


def open_descriptor_count() -> int:
    return len(os.listdir("/dev/fd"))


def recovery_document(schema: str = "recovery-checklist/v1", facts: list[dict[str, str]] | None = None) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": schema, "task_id": TASK_ID, "handoff_sha256": "a" * 64, "plan_sha256": "b" * 64,
        "facts": facts if facts is not None else standard_facts(),
    }
    if schema == "recovery-readback/v1":
        document["checklist_sha256"] = "c" * 64
    return document


def repository(test: unittest.TestCase) -> Path:
    path = resolved_temporary(test, "preflight-git-") / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "commit.gpgsign", "false")
    (path / "code.py").write_text("print('v1')\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "code")
    return path


def commit_all(path: Path, message: str) -> str:
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


class PreflightUnitTests(unittest.TestCase):
    maxDiff = None

    def test_unit_01_package_root_missing_or_not_canonical_is_unknown(self) -> None:
        root = resolved_temporary(self)
        (root / "alias").symlink_to(root, target_is_directory=True)
        for raw in (root / "missing", root / "alias"):
            with self.subTest(root=raw.name):
                check, facts = PREFLIGHT.verify_loaded_package_identity(str(raw))
                self.assertEqual((check["status"], check["code"]), ("unknown", "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))
                self.assertIsNone(facts)

    def test_unit_02_script_outside_package_root_is_unknown(self) -> None:
        check, facts = PREFLIGHT.verify_loaded_package_identity(str(shared_package()))
        self.assertEqual((check["status"], check["code"]), ("unknown", "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))
        self.assertEqual(check["message"], "preflight script is not loaded from package root")
        self.assertIsNone(facts)

    def test_unit_03_manifest_changed_after_preflight_start_is_unknown(self) -> None:
        package = shared_package()
        manifest = package / "skill-manifest.json"
        with unittest.mock.patch.object(PREFLIGHT, "_SCRIPT", package / "scripts" / "handoff_preflight.py"), \
                unittest.mock.patch.object(PREFLIGHT, "_MANIFEST_AT_START", (manifest, "0" * 64)):
            check, facts = PREFLIGHT.verify_loaded_package_identity(str(package))
        self.assertEqual((check["status"], check["code"]), ("unknown", "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))
        self.assertEqual(check["message"], "package manifest changed after preflight started")
        self.assertIsNone(facts)

    def test_unit_04_tools_or_runtime_loaded_from_another_tree_are_unknown(self) -> None:
        package = shared_package()
        manifest = package / "skill-manifest.json"
        observed = (manifest, sha256_bytes(manifest.read_bytes()))
        with unittest.mock.patch.object(PREFLIGHT, "_SCRIPT", package / "scripts" / "handoff_preflight.py"), \
                unittest.mock.patch.object(PREFLIGHT, "_MANIFEST_AT_START", observed):
            check, facts = PREFLIGHT.verify_loaded_package_identity(str(package))
        self.assertEqual((check["status"], check["code"]), ("unknown", "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))
        self.assertEqual(check["message"], "a loaded module does not belong to the package manifest")
        self.assertIsNone(facts)

    def test_unit_05_regular_file_is_hashed_from_the_same_bytes_and_closed(self) -> None:
        path = resolved_temporary(self) / "material.json"
        payload = "{\"value\": \"objective\"}\n".encode("utf-8")
        path.write_bytes(payload)
        before = open_descriptor_count()
        outcome = PREFLIGHT.read_bounded_file(path)
        self.assertEqual(open_descriptor_count(), before)
        self.assertEqual(outcome["status"], "pass")
        self.assertEqual(outcome["data"], payload)
        self.assertEqual(outcome["sha256"], sha256_bytes(payload))

    def test_unit_06_symbolic_links_are_rejected_at_file_and_directory_level(self) -> None:
        root = resolved_temporary(self)
        (root / "real").mkdir()
        (root / "real" / "file.txt").write_text("x\n", encoding="utf-8")
        (root / "link.txt").symlink_to(root / "real" / "file.txt")
        (root / "linked-dir").symlink_to(root / "real", target_is_directory=True)
        outcome = PREFLIGHT.read_bounded_file(root / "link.txt")
        self.assertEqual((outcome["status"], outcome["code"]), ("fail", "PREFLIGHT_SYMLINK_REJECTED"))
        _, failure = PREFLIGHT._workspace_file(root, "linked-dir/file.txt")
        self.assertEqual((failure["status"], failure["code"]), ("fail", "PREFLIGHT_SYMLINK_REJECTED"))

    def test_unit_07_fifo_and_directory_are_rejected_without_blocking(self) -> None:
        root = resolved_temporary(self)
        os.mkfifo(root / "pipe")
        (root / "directory").mkdir()
        before = open_descriptor_count()
        for name in ("pipe", "directory"):
            with self.subTest(kind=name):
                outcome = PREFLIGHT.read_bounded_file(root / name)
                self.assertEqual((outcome["status"], outcome["code"]), ("fail", "PREFLIGHT_NOT_REGULAR_FILE"))
        self.assertEqual(open_descriptor_count(), before)

    def test_unit_08_one_mebibyte_passes_and_one_more_byte_is_oversize(self) -> None:
        root = resolved_temporary(self)
        (root / "limit").write_bytes(b"x" * PREFLIGHT.MAX_FILE_BYTES)
        (root / "over").write_bytes(b"x" * (PREFLIGHT.MAX_FILE_BYTES + 1))
        self.assertEqual(PREFLIGHT.MAX_FILE_BYTES, 1024 * 1024)
        self.assertEqual(PREFLIGHT.read_bounded_file(root / "limit")["status"], "pass")
        outcome = PREFLIGHT.read_bounded_file(root / "over")
        self.assertEqual((outcome["status"], outcome["code"]), ("fail", "PREFLIGHT_OVERSIZE"))

    def test_unit_09_change_or_replacement_during_read_is_a_read_race(self) -> None:
        root = resolved_temporary(self)
        original_read = os.read

        calls: list[int] = []

        def appending(descriptor: int, size: int) -> bytes:
            if not calls:
                with (root / "append.txt").open("ab") as stream:
                    stream.write(b"late write\n")
            calls.append(size)
            return original_read(descriptor, size)

        def replacing(descriptor: int, size: int) -> bytes:
            (root / "replacement.tmp").write_bytes(b"replacement\n")
            os.replace(root / "replacement.tmp", root / "replace.txt")
            return original_read(descriptor, size)

        for name, hook in (("append.txt", appending), ("replace.txt", replacing)):
            with self.subTest(race=name):
                (root / name).write_bytes(b"original\n")
                before = open_descriptor_count()
                with unittest.mock.patch.object(PREFLIGHT.os, "read", side_effect=hook):
                    outcome = PREFLIGHT.read_bounded_file(root / name)
                self.assertEqual(open_descriptor_count(), before)
                self.assertEqual((outcome["status"], outcome["code"]), ("unknown", "PREFLIGHT_READ_RACE"))
                self.assertNotIn("data", outcome)

    def test_unit_10_missing_input_is_unknown_and_escaping_path_fails(self) -> None:
        root = resolved_temporary(self)
        workspace = root / "workspace"
        workspace.mkdir()
        (root / "outside.txt").write_text("outside\n", encoding="utf-8")
        (workspace / "escape.txt").symlink_to(root / "outside.txt")
        missing = PREFLIGHT.read_bounded_file(workspace / "missing.txt")
        self.assertEqual((missing["status"], missing["code"]), ("unknown", "PREFLIGHT_FILE_UNAVAILABLE"))
        for raw in (str(root / "outside.txt"), "../outside.txt", "escape.txt"):
            with self.subTest(path=raw):
                _, failure = PREFLIGHT._workspace_file(workspace, raw)
                self.assertEqual((failure["status"], failure["code"]), ("fail", "PREFLIGHT_PATH_ESCAPE"))

    def test_unit_11_allowlist_accepts_only_plan_context_and_evidence_runs(self) -> None:
        cases = {
            PLAN_REL: True, "CONTEXT.md": True,
            "docs/superpowers/evidence/context-strict-migration/RUN-20260917/report.json": True,
            "docs/superpowers/evidence/context-strict-migration/RUN-1/nested/file.txt": True,
            "docs/superpowers/evidence/context-strict-migration/report.json": False,
            "docs/superpowers/evidence/other/RUN-1/report.json": False,
            "docs/superpowers/plans/other-plan.md": False, "scripts/handoff_preflight.py": False,
            "skills/context-strict/SKILL.md": False, "tests/test_handoff_preflight.py": False,
            "skill-package.json": False, "src/managing_long_task_context/handoff.py": False,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertIs(PREFLIGHT._allowlisted(path, PLAN_REL), expected)

    def test_unit_12_nul_separated_git_output_is_bounded_and_rename_aware(self) -> None:
        self.assertEqual(PREFLIGHT.GIT_MAX_PATHS, 10_000)
        self.assertEqual(len(PREFLIGHT._split_z(b"p\x00" * 10_000)), 10_000)
        self.assertIsNone(PREFLIGHT._split_z(b"p\x00" * 10_001))
        self.assertEqual(
            PREFLIGHT._status_paths(b"R  new name.md\x00old name.md\x00?? untracked.txt\x00 M code.py\x00"),
            ["new name.md", "old name.md", "untracked.txt", "code.py"],
        )
        for malformed in (b"R  missing-original\x00", b"XYpath\x00", b"M\x00"):
            with self.subTest(data=malformed):
                self.assertIsNone(PREFLIGHT._status_paths(malformed))

    def test_unit_13_ancestor_with_only_allowlisted_later_changes_passes(self) -> None:
        repo = repository(self)
        verified = git(repo, "rev-parse", "HEAD")
        (repo / "CONTEXT.md").write_text("entry\n", encoding="utf-8")
        (repo / PLAN_REL).parent.mkdir(parents=True)
        (repo / PLAN_REL).write_text("plan\n", encoding="utf-8")
        evidence = repo / "docs/superpowers/evidence/context-strict-migration/RUN-1"
        evidence.mkdir(parents=True)
        (evidence / "verification-report.json").write_text("{}\n", encoding="utf-8")
        commit_all(repo, "docs only")
        budget = PREFLIGHT.new_git_budget()
        facts = PREFLIGHT.collect_git_facts(repo, verified, [], budget)
        inputs = {"expected_verified_head": verified, "plan": PLAN_REL}
        links, revision, worktree = PREFLIGHT.git_checks(facts, inputs, [], [])
        self.assertEqual([links["status"], revision["status"], worktree["status"]], ["pass", "pass", "pass"])
        self.assertEqual(budget["calls"], 6)

    def test_unit_14_missing_non_ancestor_or_code_change_is_stale(self) -> None:
        repo = repository(self)
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "-b", "side")
        (repo / "side.txt").write_text("side\n", encoding="utf-8")
        side = commit_all(repo, "side")
        git(repo, "checkout", "-q", "-")
        (repo / "code.py").write_text("print('v2')\n", encoding="utf-8")
        commit_all(repo, "code change")
        for name, verified, status, code in (
            ("missing", "a" * 40, "stale", "PREFLIGHT_REVISION_STALE"),
            ("not-ancestor", side, "stale", "PREFLIGHT_REVISION_STALE"),
            ("code-changed", base, "stale", "PREFLIGHT_REVISION_STALE"),
            ("never-verified", None, "unknown", "PREFLIGHT_REVISION_UNVERIFIED"),
        ):
            with self.subTest(case=name):
                facts = PREFLIGHT.collect_git_facts(repo, verified, [], PREFLIGHT.new_git_budget())
                _, revision, _ = PREFLIGHT.git_checks(facts, {"expected_verified_head": verified, "plan": PLAN_REL}, [], [])
                self.assertEqual((revision["status"], revision["code"]), (status, code))

    def test_unit_15_uncommitted_or_untracked_files_are_unknown_unless_bound(self) -> None:
        repo = repository(self)
        head = git(repo, "rev-parse", "HEAD")
        inputs = {"expected_verified_head": head, "plan": PLAN_REL}
        (repo / "handoff.md").write_text("bound material\n", encoding="utf-8")
        facts = PREFLIGHT.collect_git_facts(repo, head, [], PREFLIGHT.new_git_budget())
        self.assertEqual(PREFLIGHT.git_checks(facts, inputs, [], ["handoff.md"])[2]["status"], "pass")
        unbound = PREFLIGHT.git_checks(facts, inputs, [], [])[2]
        self.assertEqual((unbound["status"], unbound["code"]), ("unknown", "PREFLIGHT_WORKTREE_DIRTY"))
        (repo / "code.py").write_text("print('dirty')\n", encoding="utf-8")
        facts = PREFLIGHT.collect_git_facts(repo, head, [], PREFLIGHT.new_git_budget())
        modified = PREFLIGHT.git_checks(facts, inputs, [], ["handoff.md"])[2]
        self.assertEqual((modified["status"], modified["code"]), ("unknown", "PREFLIGHT_WORKTREE_DIRTY"))

    def test_unit_16_recovery_entry_has_one_current_authority_and_split_git_fields(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        inputs = {"plan": PLAN_REL, "expected_verified_head": workspace.verified_head}
        plan = {"sha256": workspace.plan_sha256}
        other_plan = "docs/superpowers/plans/short-session-handoff.md"
        (workspace.path / other_plan).write_text("old\n", encoding="utf-8")
        cases = [
            ("current", {}, "", ("pass", None)),
            ("duplicate-current", {}, "- AUTHORITATIVE_NOW: old checkpoint", ("fail", "PREFLIGHT_AUTHORITY_CONFLICT")),
            ("observed-head", {"observed_head": "b" * 40}, "", ("fail", "PREFLIGHT_INPUT_INVALID")),
            ("missing-verified-at", {"verified_at": None}, "", ("fail", "PREFLIGHT_INPUT_INVALID")),
            ("unlabelled-old-plan", {}, f"- [old plan]({other_plan})", ("fail", "PREFLIGHT_AUTHORITY_CONFLICT")),
            ("labelled-old-plan", {}, f"- HISTORICAL_ONLY: [old plan]({other_plan})", ("pass", None)),
            ("authorization-copy", {}, "implementation_authorized: true", ("fail", "PREFLIGHT_AUTHORITY_CONFLICT")),
            ("other-plan-path", {"plan_path": other_plan}, "", ("fail", "PREFLIGHT_BINDING_MISMATCH")),
            ("stale-plan-digest", {"plan_sha256": "d" * 64}, "", ("stale", "PREFLIGHT_PLAN_STALE")),
            ("other-verified-head", {"verified_head": "e" * 40}, "", ("fail", "PREFLIGHT_BINDING_MISMATCH")),
        ]
        for name, overrides, body, expected in cases:
            with self.subTest(case=name):
                workspace.write_context(overrides=overrides, body=body, commit=False)
                check, _ = PREFLIGHT.check_context_authority(workspace.path, inputs, plan)
                self.assertEqual((check["status"], check["code"]), expected)

    def test_unit_17_checklist_digest_is_canonical_and_ignores_fact_order(self) -> None:
        document = recovery_document()
        reordered = dict(document, facts=list(reversed(standard_facts())))
        first, error = PREFLIGHT.validate_recovery_document(json.loads(json.dumps(document, indent=4)), schema="recovery-checklist/v1")
        second, second_error = PREFLIGHT.validate_recovery_document(reordered, schema="recovery-checklist/v1")
        self.assertIsNone(error)
        self.assertIsNone(second_error)
        self.assertEqual(first["canonical_sha256"], second["canonical_sha256"])
        self.assertEqual(first["facts"], second["facts"])
        expected = dict(document, facts=sorted(standard_facts(), key=lambda item: item["fact_id"]))
        self.assertEqual(first["canonical_sha256"], canonical_sha256(expected))

    def test_unit_18_non_nfc_text_is_rejected_without_normalization(self) -> None:
        for field in ("value", "source_ref"):
            with self.subTest(field=field):
                facts = standard_facts()
                facts[0][field] = "Café"
                document, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts), schema="recovery-checklist/v1")
                self.assertIsNone(document)
                self.assertEqual(error[0], "PREFLIGHT_INPUT_INVALID")

    def test_unit_19_carriage_returns_are_rejected(self) -> None:
        for text in ("line one\r\nline two", "line one\rline two"):
            with self.subTest(text=repr(text)):
                facts = standard_facts()
                facts[1]["value"] = text
                document, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts), schema="recovery-checklist/v1")
                self.assertIsNone(document)
                self.assertEqual(error[0], "PREFLIGHT_INPUT_INVALID")

    def test_unit_20_unknown_missing_or_wrong_schema_fields_are_rejected(self) -> None:
        extra_fact = standard_facts()
        extra_fact[0]["confidence"] = "high"
        missing_ref = standard_facts()
        del missing_ref[0]["source_ref"]
        cases = {
            "extra-top-level": dict(recovery_document(), note="free text"),
            "missing-top-level": {key: value for key, value in recovery_document().items() if key != "plan_sha256"},
            "wrong-schema": dict(recovery_document(), schema="recovery-checklist/v2"),
            "readback-without-checklist-digest": recovery_document("recovery-checklist/v1") | {"schema": "recovery-readback/v1"},
            "extra-fact-field": recovery_document(facts=extra_fact),
            "missing-fact-field": recovery_document(facts=missing_ref),
            "empty-value": recovery_document(facts=[dict(item, value="") for item in standard_facts()]),
        }
        for name, document in cases.items():
            schema = "recovery-readback/v1" if name.startswith("readback") else "recovery-checklist/v1"
            with self.subTest(case=name):
                normalized, error = PREFLIGHT.validate_recovery_document(document, schema=schema)
                self.assertIsNone(normalized)
                self.assertEqual(error[0], "PREFLIGHT_INPUT_INVALID")

    def test_unit_21_duplicate_fact_ids_and_duplicate_json_keys_are_rejected(self) -> None:
        facts = standard_facts()
        facts.append(dict(facts[0], value="same id, different value"))
        normalized, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts), schema="recovery-checklist/v1")
        self.assertIsNone(normalized)
        self.assertEqual(error[0], "PREFLIGHT_INPUT_INVALID")
        with self.assertRaises(ValueError):
            PREFLIGHT.strict_json_loads(b'{"task_id": "A", "task_id": "B"}')

    def test_unit_22_each_of_the_five_categories_is_required(self) -> None:
        self.assertEqual(PREFLIGHT.CATEGORIES, CATEGORIES)
        for category in CATEGORIES:
            with self.subTest(missing=category):
                facts = [item for item in standard_facts() if item["category"] != category]
                normalized, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts), schema="recovery-checklist/v1")
                self.assertIsNone(normalized)
                self.assertEqual(error, ("PREFLIGHT_INPUT_INVALID", "a required fact category is missing"))

    def test_unit_23_sixty_four_facts_pass_and_sixty_five_are_oversize(self) -> None:
        def facts(count: int) -> list[dict[str, str]]:
            return [
                {"fact_id": f"F-{index:03d}", "category": CATEGORIES[index % 5], "value": f"fact {index}", "source_ref": "handoff.md"}
                for index in range(count)
            ]

        accepted, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts(64)), schema="recovery-checklist/v1")
        self.assertIsNone(error)
        self.assertEqual(len(accepted["facts"]), 64)
        rejected, error = PREFLIGHT.validate_recovery_document(recovery_document(facts=facts(65)), schema="recovery-checklist/v1")
        self.assertIsNone(rejected)
        self.assertEqual(error[0], "PREFLIGHT_OVERSIZE")

    def test_unit_24_strict_json_rejects_non_finite_invalid_utf8_and_bom(self) -> None:
        for data in (b'{"value": NaN}', b'{"value": Infinity}', b'{"value": "\xff"}', b'\xef\xbb\xbf{"value": 1}'):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    PREFLIGHT.strict_json_loads(data)

    def test_unit_25_every_stable_code_has_one_status_and_one_readonly_action(self) -> None:
        self.assertEqual(set(PREFLIGHT.CODE_STATUS), set(PREFLIGHT.NEXT_READONLY_ACTION))
        self.assertTrue(set(PREFLIGHT.CODE_STATUS.values()) <= {"fail", "unknown", "not_run", "stale"})
        for code in ("PREFLIGHT_INPUT_INVALID", "PREFLIGHT_READ_RACE", "PREFLIGHT_DEPENDENCY_NOT_RUN", "PREFLIGHT_PLAN_STALE"):
            self.assertIn(code, PREFLIGHT.CODE_STATUS)
        with self.assertRaises(ValueError):
            PREFLIGHT._check("x", "fail", "PREFLIGHT_READ_RACE", "wrong class")
        with self.assertRaises(ValueError):
            PREFLIGHT._check("x", "pass", "PREFLIGHT_INPUT_INVALID", "pass has no code")
        with self.assertRaises(ValueError):
            PREFLIGHT._check("x", "unknown", "NOT_A_REGISTERED_CODE", "unregistered")

    def test_unit_26_preflight_status_aggregation_maps_to_exit_codes(self) -> None:
        inputs = {"mode": "manual_fallback", "stage": "recovery"}
        passed = PREFLIGHT._check("a", "pass", None, "ok")
        cases = [
            ([passed], "pass", 0),
            ([passed, PREFLIGHT._check("b", "unknown", "PREFLIGHT_READ_RACE", "x"), PREFLIGHT._check("c", "fail", "PREFLIGHT_OVERSIZE", "x")], "fail", 1),
            ([passed, PREFLIGHT._check("b", "stale", "PREFLIGHT_PLAN_STALE", "x")], "unknown", 2),
            ([passed, PREFLIGHT._not_run("b")], "unknown", 2),
            ([passed, PREFLIGHT._check("b", "unknown", "PREFLIGHT_GIT_TIMEOUT", "x")], "unknown", 2),
        ]
        for checks, status, code in cases:
            with self.subTest(status=status, checks=[item["status"] for item in checks]):
                report, exit_code = PREFLIGHT.emit_report(inputs, checks, state=None, checklist=None, revisions={}, stats={})
                self.assertEqual((report["preflight_status"], exit_code), (status, code))

    def test_unit_27_blocking_reasons_keep_check_order_and_one_next_action(self) -> None:
        checks = [
            PREFLIGHT._check("input", "pass", None, "ok"),
            PREFLIGHT._not_run("package_binding"),
            PREFLIGHT._check("git_revision", "stale", "PREFLIGHT_REVISION_STALE", "x"),
            PREFLIGHT._check("readback_comparison", "fail", "PREFLIGHT_READBACK_MISMATCH", "x"),
        ]
        report, _ = PREFLIGHT.emit_report({"mode": "manual_fallback", "stage": "recovery"}, checks, state=None,
                                          checklist=None, revisions={}, stats={})
        self.assertEqual([item["check"] for item in report["blocking_reasons"]], ["package_binding", "git_revision", "readback_comparison"])
        self.assertIsInstance(report["next_readonly_action"], str)
        self.assertEqual(report["next_readonly_action"], PREFLIGHT.NEXT_READONLY_ACTION["PREFLIGHT_REVISION_STALE"])

    def test_unit_28_unexpected_exception_is_projected_without_exception_text(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        material = workspace.write_material()
        canary = "CANARY-SECRET-7f3a /Users/private-name/secret-path"
        identity = PREFLIGHT._check("package_identity", "pass", None, "ok")
        facts = {"root": workspace.package, "manifest_sha256": workspace.manifest_sha256, "runtime": None}
        with unittest.mock.patch.object(PREFLIGHT, "verify_loaded_package_identity", return_value=(identity, facts)), \
                unittest.mock.patch.object(PREFLIGHT, "check_plan_digest", side_effect=RuntimeError(canary)):
            report, code = PREFLIGHT.run_preflight(workspace.arguments(material))
        encoded = json.dumps(report, ensure_ascii=False)
        self.assertEqual(code, 2)
        self.assertEqual(check_named(report, "unexpected")["code"], "PREFLIGHT_UNEXPECTED_ERROR")
        self.assertNotIn("CANARY-SECRET", encoded)
        self.assertNotIn("RuntimeError", encoded)
        self.assertNotIn(str(workspace.path), encoded)
        self.assertFalse(report["archive_allowed"])


def outcome_of(report: dict[str, Any]) -> tuple[str, str, str, object, bool]:
    outcome = report["migration_outcome"]
    return (
        outcome["information_recovery"]["status"], outcome["control_transfer"]["status"],
        outcome["control_transfer"]["commit_status"], outcome["control_transfer"]["controller_generation"],
        outcome["source_retirement"]["archive_allowed"],
    )


class PreflightIntegrationTests(unittest.TestCase):
    maxDiff = None

    def strict_workspace(self) -> Workspace:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        return workspace

    def assert_retirement_closed(self, report: dict[str, Any]) -> None:
        self.assertIs(report["archive_allowed"], False)
        self.assertEqual(report["migration_outcome"]["source_retirement"], {"status": "not_allowed", "archive_allowed": False, "evidence_refs": []})

    def test_int_01_strict_prepare_passes_without_an_existing_handoff_record(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material(include_readback=False)
        argv = workspace.arguments(material, mode="strict_protocol", stage="prepare", readback=False)
        result = run_strict_host(workspace, argv, state="none", verifier="none")
        report = result["report"]
        self.assertEqual((result["exit"], report["preflight_status"]), (0, "pass"), report)
        self.assertEqual(check_named(report, "strict_contract")["status"], "pass")
        self.assertNotIn("strict_handoff_state", [check["name"] for check in report["checks"]])
        self.assertEqual(result["handoff_records"], [])
        self.assertEqual(result["events_before"], result["events_after"])
        self.assertEqual(report["material_integrity"], "pass")
        self.assertEqual(outcome_of(report), ("unknown", "unknown", "not_attempted", None, False))
        self.assert_retirement_closed(report)

    def test_int_02_strict_prepare_requires_explicit_contract_capability(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material(include_readback=False)
        argv = workspace.arguments(material, mode="strict_protocol", stage="prepare", readback=False)
        result = run_strict_host(workspace, argv, state="none", verifier="none", capability=False)
        check = check_named(result["report"], "strict_contract")
        self.assertEqual((result["exit"], check["status"], check["code"]), (1, "fail", "PREFLIGHT_CAPABILITY_MISSING"))
        self.assertEqual(result["handoff_records"], [])

    def test_int_03_strict_prepare_with_unavailable_contract_store_is_unknown(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material(include_readback=False)
        argv = workspace.arguments(material, mode="strict_protocol", stage="prepare", readback=False)
        result = run_strict_host(workspace, argv, state="none", verifier="none", publish=False)
        check = check_named(result["report"], "strict_contract")
        self.assertEqual((result["exit"], check["status"], check["code"]), (2, "unknown", "PREFLIGHT_CONTRACT_UNAVAILABLE"))
        self.assertFalse(workspace.base_dir.exists())

    def test_int_04_strict_activate_passes_only_with_trusted_verifier_and_exact_readback(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material()
        result = run_strict_host(workspace, workspace.arguments(material, mode="strict_protocol", stage="activate"),
                                 state="prepared", verifier="trusted")
        report = result["report"]
        self.assertEqual((result["exit"], report["preflight_status"]), (0, "pass"), report)
        self.assertEqual(check_named(report, "strict_handoff_state")["status"], "pass")
        self.assertEqual(result["events_before"], result["events_after"])
        self.assertEqual(outcome_of(report), ("pass", "unknown", "not_attempted", None, False))
        self.assert_retirement_closed(report)

    def test_int_05_strict_activate_without_trusted_verifier_stays_unknown(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material()
        argv = workspace.arguments(material, mode="strict_protocol", stage="activate")
        for verifier in ("none", "self_report"):
            with self.subTest(verifier=verifier):
                shutil.rmtree(workspace.base_dir, ignore_errors=True)
                result = run_strict_host(workspace, argv, state="prepared", verifier=verifier)
                check = check_named(result["report"], "strict_handoff_state")
                self.assertEqual((result["exit"], check["status"], check["code"]), (2, "unknown", "PREFLIGHT_VERIFIER_UNAVAILABLE"))
                self.assertEqual(result["events_before"], result["events_after"])
                self.assertEqual(outcome_of(result["report"])[1:], ("unknown", "not_attempted", None, False))

    def test_int_06_strict_activate_with_changed_bearing_evidence_fails_closed(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material()
        result = run_strict_host(workspace, workspace.arguments(material, mode="strict_protocol", stage="activate"),
                                 state="prepared", verifier="trusted", mutate={"refs/basis.txt": "changed basis\n"})
        report = result["report"]
        check = check_named(report, "strict_handoff_state")
        self.assertNotEqual(result["exit"], 0, report)
        self.assertNotEqual(check["status"], "pass")
        self.assertEqual(check_named(report, "git_worktree")["code"], "PREFLIGHT_WORKTREE_DIRTY")
        self.assertEqual(result["events_before"], result["events_after"])
        self.assertEqual(outcome_of(report)[1:], ("unknown", "not_attempted", None, False))

    def test_int_07_strict_status_reports_committed_control_with_current_verification(self) -> None:
        workspace = self.strict_workspace()
        material = workspace.write_material()
        result = run_strict_host(workspace, workspace.arguments(material, mode="strict_protocol", stage="status"),
                                 state="activated", verifier="trusted")
        report = result["report"]
        self.assertEqual((result["exit"], report["preflight_status"]), (0, "pass"), report)
        self.assertEqual(outcome_of(report), ("pass", "pass", "confirmed_committed", 1, False))
        self.assert_retirement_closed(report)

    def test_int_08_strict_status_keeps_history_visible_when_current_verifier_is_missing(self) -> None:
        workspace = self.strict_workspace()
        result = run_strict_host(workspace, workspace.arguments(None, mode="strict_protocol", stage="status"),
                                 state="activated", verifier="none")
        report = result["report"]
        check = check_named(report, "strict_handoff_state")
        self.assertEqual((result["exit"], check["code"]), (2, "PREFLIGHT_VERIFIER_UNAVAILABLE"))
        self.assertEqual(report["material_integrity"], "not_run")
        self.assertEqual(outcome_of(report), ("unknown", "unknown", "confirmed_committed", 1, False))

    def test_int_09_strict_status_for_pending_or_cancelled_handoff_is_not_a_transfer(self) -> None:
        workspace = self.strict_workspace()
        argv = workspace.arguments(None, mode="strict_protocol", stage="status")
        for state in ("prepared", "cancelled"):
            with self.subTest(state=state):
                shutil.rmtree(workspace.base_dir, ignore_errors=True)
                result = run_strict_host(workspace, argv, state=state, verifier="trusted")
                self.assertEqual(outcome_of(result["report"])[1:], ("fail", "confirmed_not_committed", None, False))
                self.assert_retirement_closed(result["report"])

    def test_int_10_manual_recovery_reports_information_recovery_only(self) -> None:
        workspace, material = ready_workspace(self)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, report["preflight_status"], report["material_integrity"]), (0, "pass", "pass"), report)
        self.assertEqual(outcome_of(report), ("pass", "unknown", "not_attempted", None, False))
        self.assertEqual(report["recovery_coverage"], {"fact_count": 5, "categories": {category: 1 for category in CATEGORIES}})
        self.assertNotIn("strict_contract", [check["name"] for check in report["checks"]])
        self.assertFalse(workspace.base_dir.exists())
        self.assert_retirement_closed(report)

    def test_int_11_manual_material_pass_with_wrong_readback_fails_information_recovery(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        altered = standard_facts()
        altered[3]["value"] = "a different next action"
        material = workspace.write_material(readback_facts=altered)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, report["material_integrity"]), (1, "pass"), report)
        self.assertEqual(check_named(report, "readback_comparison")["code"], "PREFLIGHT_READBACK_MISMATCH")
        self.assertEqual(outcome_of(report), ("fail", "unknown", "not_attempted", None, False))

    def test_int_12_manual_readback_bound_to_another_checklist_is_a_material_failure(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        material = workspace.write_material(readback_update={"checklist_sha256": "f" * 64})
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, report["material_integrity"]), (1, "fail"), report)
        self.assertEqual(check_named(report, "recovery_readback")["code"], "PREFLIGHT_BINDING_MISMATCH")
        self.assertEqual(check_named(report, "readback_comparison")["status"], "not_run")
        self.assertEqual(outcome_of(report)[0], "unknown")


REPORT_KEYS = {
    "schema", "migration_mode", "stage", "preflight_status", "material_integrity", "migration_outcome",
    "archive_allowed", "checks", "blocking_reasons", "next_readonly_action", "recovery_coverage", "revisions", "stats",
}


def tree_snapshot(*roots: Path) -> dict[str, tuple[str, int]]:
    snapshot: dict[str, tuple[str, int]] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".git" not in path.relative_to(root).parts:
                snapshot[str(path)] = (sha256_bytes(path.read_bytes()), path.stat().st_mtime_ns)
            elif path.is_dir() and path.name == "__pycache__":
                snapshot[str(path)] = ("directory", 0)
    return snapshot


class PreflightCliTests(unittest.TestCase):
    maxDiff = None

    def test_cli_01_passing_manual_report_has_stable_keys_and_identical_output(self) -> None:
        workspace, material = ready_workspace(self)
        first = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        second = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((first[0], first[1]["preflight_status"]), (0, "pass"), first[1])
        self.assertEqual(first[2], second[2])
        self.assertEqual(set(first[1]), REPORT_KEYS)
        self.assertEqual(first[1]["schema"], "migration-preflight/v1")
        for check in first[1]["checks"]:
            self.assertEqual(set(check), {"name", "status", "code", "message", "evidence_refs"})
        self.assertEqual(set(first[1]["migration_outcome"]), {"information_recovery", "control_transfer", "source_retirement"})
        self.assertNotIn("migration_success", first[2])

    def test_cli_02_invalid_mode_stage_or_argument_matrix_fails_before_reading(self) -> None:
        workspace, material = ready_workspace(self)
        base = workspace.arguments(material)
        strict_prepare = workspace.arguments(material, mode="strict_protocol", stage="prepare", readback=False)
        cases = {
            "manual-prepare": workspace.arguments(material, stage="prepare"),
            "strict-recovery": workspace.arguments(material, mode="strict_protocol", stage="recovery"),
            "ambiguous-mode": workspace.arguments(material, mode="automatic"),
            "strict-prepare-with-readback": strict_prepare + ["--recovery-readback", str(material["readback"])],
            "manual-with-context-root": base + ["--context-root", str(workspace.base_dir)],
            "missing-verified-head": workspace.arguments(material, expected_verified_head=None),
            "relative-material": workspace.arguments(material, handoff_file="handoff-material/handoff.md"),
            "short-verified-head": workspace.arguments(material, verified_head=workspace.verified_head[:12]),
            "escaping-plan": workspace.arguments(material, plan="../plan.md"),
            "unknown-option": base + ["--force", "true"],
        }
        code, report, _, _ = run_cli(workspace.package, cases["ambiguous-mode"], cwd=workspace.root)
        self.assertEqual(code, 1)
        for name, argv in cases.items():
            with self.subTest(case=name):
                report, exit_code = PREFLIGHT.run_preflight(argv)
                self.assertEqual(exit_code, 1)
                self.assertEqual([(check["name"], check["code"]) for check in report["checks"]], [("input", "PREFLIGHT_INPUT_INVALID")])
                self.assertIsNone(report["migration_mode"])
                self.assertIs(report["archive_allowed"], False)

    def test_cli_03_wrong_expected_plan_digest_exits_one(self) -> None:
        workspace, material = ready_workspace(self)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material, expected_plan_sha256="0" * 64), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "plan_digest")["code"]), (1, "PREFLIGHT_DIGEST_MISMATCH"))
        self.assertEqual(check_named(report, "context_authority")["status"], "not_run")

    def test_cli_04_recovery_entry_bound_to_an_older_plan_digest_is_stale(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        workspace.plan.write_text(workspace.plan.read_text(encoding="utf-8") + "\nLater reviewed change.\n", encoding="utf-8")
        workspace.commit("plan revision without re-verification")
        material = workspace.write_material()
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        check = check_named(report, "context_authority")
        self.assertEqual((code, check["status"], check["code"]), (2, "stale", "PREFLIGHT_PLAN_STALE"))
        self.assertEqual(check_named(report, "git_revision")["status"], "pass")

    def test_cli_05_old_verified_head_after_code_change_is_stale(self) -> None:
        workspace, material = ready_workspace(self)
        (workspace.path / "scripts").mkdir()
        (workspace.path / "scripts" / "real_validation.py").write_text("print('new tool')\n", encoding="utf-8")
        workspace.commit("code landed after verification")
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        check = check_named(report, "git_revision")
        self.assertEqual((code, check["status"], check["code"]), (2, "stale", "PREFLIGHT_REVISION_STALE"))
        self.assertEqual(report["preflight_status"], "unknown")

    def test_cli_06_missing_or_different_package_digest_is_not_current(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        material = workspace.write_material()
        for recorded, status, expected_code in (("null", "unknown", "PREFLIGHT_PACKAGE_SHA_MISSING"), ("9" * 64, "stale", "PREFLIGHT_PACKAGE_STALE")):
            with self.subTest(recorded=recorded[:4]):
                workspace.write_context(overrides={"package_manifest_sha256": recorded})
                code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
                check = check_named(report, "package_binding")
                self.assertEqual((code, check["status"], check["code"]), (2, status, expected_code))

    def test_cli_07_multiple_current_entries_or_unlabelled_old_plan_exit_one(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        old_plan = "docs/superpowers/plans/short-session-handoff.md"
        (workspace.path / old_plan).write_text("old plan\n", encoding="utf-8")
        workspace.commit("old plan")
        material = workspace.write_material()
        for body in ("Old checkpoint: AUTHORITATIVE_NOW", f"- Main plan: [old]({old_plan})"):
            with self.subTest(body=body):
                workspace.write_context(verified_head=workspace.verified_head, body=body)
                code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
                self.assertEqual((code, check_named(report, "context_authority")["code"]), (1, "PREFLIGHT_AUTHORITY_CONFLICT"))

    def test_cli_08_missing_untracked_or_absolute_links_exit_one(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        (workspace.path / ".gitignore").write_text("private-notes/\n", encoding="utf-8")
        workspace.commit("ignore private notes")
        (workspace.path / "private-notes").mkdir()
        (workspace.path / "private-notes" / "方案对话内容.txt").write_text("local only\n", encoding="utf-8")
        material = workspace.write_material()
        cases = (
            ("[gone](docs/validation/missing.md)", "PREFLIGHT_LINK_MISSING"),
            ("[raw](private-notes/方案对话内容.txt)", "PREFLIGHT_UNTRACKED_DEPENDENCY"),
            (f"[absolute]({workspace.path / 'README.md'})", "PREFLIGHT_LINK_INVALID"),
        )
        for body, expected_code in cases:
            with self.subTest(code=expected_code):
                workspace.write_context(verified_head=workspace.verified_head, body=body)
                code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
                self.assertEqual((code, check_named(report, "context_links")["code"]), (1, expected_code))

    def test_cli_09_missing_material_is_unknown_not_a_pass(self) -> None:
        workspace, material = ready_workspace(self)
        material["readback"].unlink()
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "recovery_readback")["code"]), (2, "PREFLIGHT_FILE_UNAVAILABLE"))
        self.assertEqual(check_named(report, "readback_comparison")["status"], "not_run")
        self.assertEqual(report["migration_outcome"]["information_recovery"]["status"], "unknown")
        material["handoff"].unlink()
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "handoff_material")["code"]), (2, "PREFLIGHT_FILE_UNAVAILABLE"))

    def test_cli_10_symlinked_or_escaping_material_is_rejected(self) -> None:
        workspace, material = ready_workspace(self)
        real = workspace.material / "checklist-real.json"
        material["checklist"].rename(real)
        material["checklist"].symlink_to(real)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "recovery_checklist")["code"]), (1, "PREFLIGHT_SYMLINK_REJECTED"))
        outside = workspace.root / "readback.json"
        shutil.copyfile(material["readback"], outside)
        material["checklist"].unlink()
        real.rename(material["checklist"])
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material, recovery_readback=str(outside)), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "recovery_readback")["code"]), (1, "PREFLIGHT_PATH_ESCAPE"))

    def test_cli_11_expected_handoff_digest_mismatch_blocks_material_integrity(self) -> None:
        workspace, material = ready_workspace(self)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material, expected_handoff_sha256="1" * 64), cwd=workspace.root)
        self.assertEqual((code, check_named(report, "handoff_material")["code"]), (1, "PREFLIGHT_DIGEST_MISMATCH"))
        self.assertEqual(check_named(report, "recovery_checklist")["status"], "not_run")
        self.assertEqual((report["material_integrity"], report["migration_outcome"]["information_recovery"]["status"]), ("fail", "unknown"))

    def test_cli_12_stable_output_redacts_material_paths_users_and_exception_text(self) -> None:
        root = resolved_temporary(self) / "secret-user-name-CANARY-PATH"
        root.mkdir()
        workspace = Workspace(root, shared_package())
        workspace.write_context()
        canary = "CANARY-MATERIAL-9d41"
        facts = standard_facts()
        facts[0]["value"] = canary
        material = workspace.write_material(
            checklist_update={"facts": facts},
            raw_readback=f'{{"schema": "recovery-readback/v1", "note": "{canary}", '.encode("utf-8"),
        )
        material["handoff"].write_text(f"{canary}\n", encoding="utf-8")
        code, report, stdout, stderr = run_cli(workspace.package, workspace.arguments(material), cwd=root)
        self.assertEqual(code, 1, report)
        for forbidden in (canary, "CANARY-PATH", str(workspace.package), str(Path.home()), "Traceback", "JSONDecodeError", "Exception"):
            with self.subTest(forbidden=forbidden[:24]):
                self.assertNotIn(forbidden, stdout)
        self.assertEqual(stderr, "")

    def test_cli_13_clean_clone_needs_no_untracked_local_source_file(self) -> None:
        origin, _ = ready_workspace(self)
        (origin.path / "方案对话内容.txt").write_text("local private conversation copy\n", encoding="utf-8")
        clone = origin.root / "clone"
        git(origin.root, "clone", "-q", str(origin.path), str(clone))
        clone_workspace = Workspace.__new__(Workspace)
        clone_workspace.__dict__.update(origin.__dict__)
        clone_workspace.path, clone_workspace.plan = clone, clone / PLAN_REL
        clone_workspace.material = clone / "handoff-material"
        clone_workspace.material.mkdir()
        material = clone_workspace.write_material()
        code, report, _, _ = run_cli(origin.package, clone_workspace.arguments(material), cwd=origin.root)
        self.assertEqual((code, report["preflight_status"]), (0, "pass"), report)
        origin_material = origin.write_material()
        code, report, _, _ = run_cli(origin.package, origin.arguments(origin_material), cwd=origin.root)
        self.assertEqual((code, check_named(report, "git_worktree")["code"]), (2, "PREFLIGHT_WORKTREE_DIRTY"))

    def test_cli_14_script_outside_a_built_package_is_package_identity_unknown(self) -> None:
        workspace, material = ready_workspace(self)
        loose = workspace.root / "loose" / "scripts"
        loose.mkdir(parents=True)
        for name in ("handoff_preflight.py", "context_identity_core.py", "skill_package.py"):
            shutil.copyfile(workspace.package / "scripts" / name, loose / name)
        code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root,
                                     script=loose / "handoff_preflight.py")
        self.assertEqual((code, check_named(report, "package_identity")["code"]), (2, "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))
        self.assertTrue(all(check["status"] == "not_run" for check in report["checks"][2:]))
        self.assertEqual(report["material_integrity"], "unknown")

    def test_cli_15_mixed_runtime_or_missing_pythonpath_is_unknown(self) -> None:
        workspace, material = ready_workspace(self)
        for name, pythonpath in (("source-runtime", str(ROOT / "src")), ("no-runtime", "")):
            with self.subTest(case=name):
                code, report, _, _ = run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root, pythonpath=pythonpath)
                self.assertEqual((code, check_named(report, "package_identity")["code"]), (2, "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))

    def test_cli_16_tampered_package_file_is_unknown(self) -> None:
        root = resolved_temporary(self)
        package = root / "tampered-package"
        shutil.copytree(shared_package(), package)
        with (package / "src" / "managing_long_task_context" / "handoff.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# tampered\n")
        workspace = Workspace(root, package)
        workspace.write_context()
        material = workspace.write_material()
        code, report, _, _ = run_cli(package, workspace.arguments(material), cwd=root)
        self.assertEqual((code, check_named(report, "package_identity")["code"]), (2, "PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN"))

    def test_cli_17_preflight_writes_nothing_even_without_bytecode_suppression(self) -> None:
        workspace, material = ready_workspace(self)
        before = tree_snapshot(workspace.package, workspace.path)
        for argv in (workspace.arguments(material), workspace.arguments(material, expected_plan_sha256="0" * 64)):
            run_cli(workspace.package, argv, cwd=workspace.root)
        self.assertEqual(tree_snapshot(workspace.package, workspace.path), before)
        self.assertFalse(workspace.base_dir.exists())

    def test_cli_18_cli_has_no_host_verifier_so_strict_activation_cannot_pass(self) -> None:
        workspace = Workspace(resolved_temporary(self), shared_package())
        workspace.write_context()
        material = workspace.write_material()
        argv = workspace.arguments(material, mode="strict_protocol", stage="activate")
        prepared = run_strict_host(workspace, argv, state="prepared", verifier="none")
        events = workspace.base_dir / TASK_ID / "events.jsonl"
        before = events.read_bytes()
        code, report, _, _ = run_cli(workspace.package, argv, cwd=workspace.root)
        self.assertEqual(prepared["handoff_records"], [f"{HANDOFF_ID}.json"])
        self.assertEqual((code, check_named(report, "strict_handoff_state")["code"]), (2, "PREFLIGHT_VERIFIER_UNAVAILABLE"))
        self.assertEqual(events.read_bytes(), before)
        self.assertEqual(report["migration_outcome"]["control_transfer"], {"status": "unknown", "commit_status": "not_attempted", "controller_generation": None})


FAKE_GIT = """#!{python}
import os, sys, time
arguments = sys.argv[1:]
mode = os.environ.get("FAKE_GIT_MODE", "")
if mode == "sleep":
    time.sleep(float(os.environ.get("FAKE_GIT_SECONDS", "30")))
if mode == "stdout-flood":
    sys.stdout.buffer.write(b"x" * (1024 * 1024 + 1))
if mode == "stderr-flood":
    sys.stderr.buffer.write(b"x" * (1024 * 1024 + 1))
if mode == "many-status-paths" and "status" in arguments:
    sys.stdout.buffer.write(b"?? p\\x00" * 10_001)
    raise SystemExit(0)
real = os.environ.get("FAKE_GIT_REAL")
if real and mode in {"many-status-paths", ""}:
    os.execv(real, [real, *arguments])
raise SystemExit(0)
"""

METRIC_WRAPPER = r'''
import json, resource, subprocess, sys, time
started = time.monotonic()
completed = subprocess.run(sys.argv[1:], capture_output=True, text=True)
wall = time.monotonic() - started
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
scale = 1 if sys.platform == "darwin" else 1024
print(json.dumps({"exit": completed.returncode, "wall_seconds": wall, "cpu_seconds": usage.ru_utime + usage.ru_stime,
                  "peak_rss_bytes": usage.ru_maxrss * scale, "report": json.loads(completed.stdout)}))
'''


class PreflightPerformanceTests(unittest.TestCase):
    maxDiff = None

    def fake_git(self) -> Path:
        path = resolved_temporary(self, "preflight-fake-git-") / "git"
        path.write_text(FAKE_GIT.replace("{python}", sys.executable), encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_perf_01_single_git_call_timeout_kills_the_process_and_is_unknown(self) -> None:
        self.assertEqual((PREFLIGHT.GIT_CALL_SECONDS, PREFLIGHT.GIT_TOTAL_SECONDS), (5.0, 15.0))
        fake = self.fake_git()
        before = open_descriptor_count()
        started = time.monotonic()
        with unittest.mock.patch.dict(os.environ, {"FAKE_GIT_MODE": "sleep", "FAKE_GIT_SECONDS": "30"}):
            outcome = PREFLIGHT.run_git(fake.parent, ["status"], PREFLIGHT.new_git_budget(git=str(fake)), call_seconds=0.5)
        elapsed = time.monotonic() - started
        self.assertEqual((outcome["status"], outcome["code"]), ("unknown", "PREFLIGHT_GIT_TIMEOUT"))
        self.assertNotIn("stdout", outcome)
        self.assertLess(elapsed, 5.0)
        self.assertEqual(open_descriptor_count(), before)

    def test_perf_02_cumulative_budget_stops_launching_git_after_the_deadline(self) -> None:
        fake = self.fake_git()
        budget = PREFLIGHT.new_git_budget(total_seconds=0.6, git=str(fake))
        with unittest.mock.patch.dict(os.environ, {"FAKE_GIT_MODE": "sleep", "FAKE_GIT_SECONDS": "30"}):
            first = PREFLIGHT.run_git(fake.parent, ["status"], budget, call_seconds=5.0)
            second = PREFLIGHT.run_git(fake.parent, ["status"], budget, call_seconds=5.0)
        self.assertEqual(first["code"], "PREFLIGHT_GIT_TIMEOUT")
        self.assertEqual(second["code"], "PREFLIGHT_GIT_TIMEOUT")
        self.assertEqual(budget["calls"], 1, "no Git process may start after the cumulative budget is spent")

    def test_perf_03_stream_and_path_count_limits_are_unknown_without_raw_output(self) -> None:
        self.assertEqual((PREFLIGHT.GIT_STREAM_BYTES, PREFLIGHT.GIT_MAX_PATHS), (1024 * 1024, 10_000))
        fake = self.fake_git()
        for mode in ("stdout-flood", "stderr-flood"):
            with self.subTest(mode=mode), unittest.mock.patch.dict(os.environ, {"FAKE_GIT_MODE": mode}):
                outcome = PREFLIGHT.run_git(fake.parent, ["diff"], PREFLIGHT.new_git_budget(git=str(fake)))
                self.assertEqual(outcome, {"status": "unknown", "code": "PREFLIGHT_GIT_OUTPUT_LIMIT"})
        repo = repository(self)
        head = git(repo, "rev-parse", "HEAD")
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        with unittest.mock.patch.dict(os.environ, {"FAKE_GIT_MODE": "many-status-paths", "FAKE_GIT_REAL": str(real_git)}):
            facts = PREFLIGHT.collect_git_facts(repo, head, [], PREFLIGHT.new_git_budget(git=str(fake)))
        worktree = PREFLIGHT.git_checks(facts, {"expected_verified_head": head, "plan": PLAN_REL}, [], [])[2]
        self.assertEqual((worktree["status"], worktree["code"]), ("unknown", "PREFLIGHT_GIT_OUTPUT_LIMIT"))

    def test_perf_04_git_calls_cpu_time_and_peak_rss_stay_bounded_as_inputs_grow(self) -> None:
        metrics: dict[str, dict[str, object]] = {}
        for label, extra_links, extra_files in (("small", 0, 0), ("grown", 40, 300)):
            workspace = Workspace(resolved_temporary(self), shared_package())
            bulk = workspace.path / "docs" / "bulk"
            bulk.mkdir(parents=True)
            for index in range(extra_files):
                (bulk / f"file-{index:03d}.md").write_text(f"file {index}\n", encoding="utf-8")
            workspace.verified_head = workspace.commit("bulk files")
            links = "\n".join(f"- [bulk {index}](docs/bulk/file-{index:03d}.md)" for index in range(extra_links))
            workspace.write_context(body=links)
            material = workspace.write_material()
            runs = []
            for _ in range(3):
                completed = subprocess.run(
                    [sys.executable, "-c", METRIC_WRAPPER, sys.executable, str(workspace.package / "scripts" / "handoff_preflight.py"),
                     *workspace.arguments(material)],
                    cwd=workspace.root, env={**os.environ, "PYTHONPATH": str(workspace.package / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True, capture_output=True, timeout=180,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                runs.append(json.loads(completed.stdout))
            for run in runs:
                self.assertEqual((run["exit"], run["report"]["preflight_status"]), (0, "pass"), run["report"])
            cpu = sorted(run["cpu_seconds"] for run in runs)[1]
            wall = sorted(run["wall_seconds"] for run in runs)[1]
            metrics[label] = {
                "git_calls": runs[0]["report"]["stats"]["git_calls"], "input_bytes": runs[0]["report"]["stats"]["input_bytes"],
                "median_cpu_seconds": round(cpu, 3), "median_wall_seconds": round(wall, 3),
                "peak_rss_bytes": max(run["peak_rss_bytes"] for run in runs), "links": extra_links + 2, "files": extra_files,
            }
        print("PERF-04 metrics: " + json.dumps(metrics, sort_keys=True), file=sys.stderr)
        self.assertEqual(metrics["small"]["git_calls"], metrics["grown"]["git_calls"])
        self.assertLessEqual(int(metrics["grown"]["git_calls"]), 7)
        for label, values in metrics.items():
            with self.subTest(workspace=label):
                self.assertLess(float(values["median_cpu_seconds"]), 2.0)
                self.assertLess(int(values["peak_rss_bytes"]), 64 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
