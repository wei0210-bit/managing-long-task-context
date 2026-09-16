from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"
STRICT_SOURCE = ROOT / "skills" / "context-strict"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeIdentityAcceptanceTests(unittest.TestCase):
    """Public Strict seams.  Cases cover AC 1--5, 7, 9--11 and 13."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        # This test is also copied into a Strict distribution.  In that case
        # exercise the package containing the test rather than reaching back
        # into the development checkout.
        if (ROOT / "skill-manifest.json").is_file():
            cls.package = ROOT
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts/skill_package.py"), "verify", "--package", str(ROOT)],
                cwd=cls.root, text=True, capture_output=True, timeout=30,
            )
        else:
            cls.package = cls.root / "strict-package"
            source = STRICT_SOURCE if STRICT_SOURCE.is_dir() else ROOT
            completed = subprocess.run(
                [sys.executable, str(PACKAGER), "build", "--source", str(source),
                 "--destination", str(cls.package), "--source-revision", "git:acceptance"],
                cwd=ROOT, text=True, capture_output=True, timeout=30,
            )
        if completed.returncode:
            raise AssertionError(completed.stdout + completed.stderr)
        verified = json.loads(completed.stdout)
        cls.manifest_sha256 = (
            verified["manifest_sha256"] if "manifest_sha256" in verified
            else verified["identity"]["manifest_sha256"]
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context_root = self.root / "context"
        self.workspace = self.root / "workspace"
        self.context_root.mkdir()
        self.workspace.mkdir()
        (self.context_root / "TASK-001").mkdir()

    def doctor(self, *args: str, expected: int = 0, env: dict[str, str] | None = None) -> dict:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.package / "src")
        if env:
            environment.update(env)
        completed = subprocess.run(
            [sys.executable, str(self.package / "scripts/context_doctor.py"), *args],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def binding_args(self, *, task_id: str = "TASK-001", workspace: Path | None = None,
                     context_root: Path | None = None) -> list[str]:
        return [
            "--package-root", str(self.package), "--expected-manifest-sha256", self.manifest_sha256,
            "--context-root", str(context_root or self.context_root),
            "--workspace-root", str(workspace or self.workspace), "--task-id", task_id,
        ]

    def init_binding(self, *, expected: int = 0, **kwargs: object) -> dict:
        return self.doctor("init-binding", *self.binding_args(**kwargs), expected=expected)

    def identity(self, *, expected: int = 0, env: dict[str, str] | None = None, **kwargs: object) -> dict:
        args = self.binding_args(**kwargs)
        # expected manifest belongs to the binding, not to the check invocation.
        check_args = ["--package-root", str(self.package)] + args[4:]
        return self.doctor("check", "--mode", "identity", *check_args, expected=expected, env=env)

    def identity_with_open_audit(self) -> tuple[dict, list[str]]:
        """Run the public CLI in-process with an audit hook around only the command."""
        runner = r'''
import importlib.util, json, os, sys
from pathlib import Path
script = Path(sys.argv[1])
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("identity_audited_doctor", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
opened = []
def audit(event, args):
    if event == "open" and args:
        try:
            opened.append(os.path.realpath(os.fspath(args[0])))
        except (TypeError, ValueError):
            pass
sys.addaudithook(audit)
code = module.main(sys.argv[2:])
print("__IDENTITY_OPEN_PATHS__" + json.dumps(opened), file=sys.stderr)
raise SystemExit(code)
'''
        arguments = [
            "check", "--mode", "identity", "--package-root", str(self.package),
            "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
            "--task-id", "TASK-001",
        ]
        completed = subprocess.run(
            [sys.executable, "-c", runner, str(self.package / "scripts/context_doctor.py"), *arguments],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.package / "src")},
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        marker = "__IDENTITY_OPEN_PATHS__"
        audit_line = next(line for line in completed.stderr.splitlines() if line.startswith(marker))
        return json.loads(completed.stdout), json.loads(audit_line.removeprefix(marker))

    def assert_report_shape(self, report: dict, *, mode: str, scope: str) -> None:
        self.assertEqual(set(report), {
            "schema", "mode", "scope", "status", "checked_at", "full_verification",
            "identity", "binding", "checks", "codes", "next_action",
        })
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["mode"], mode)
        self.assertEqual(report["scope"], scope)
        self.assertIn(report["status"], {"pass", "fail", "unknown"})
        checked_at = datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))
        self.assertEqual(checked_at.utcoffset(), timezone.utc.utcoffset(checked_at))
        self.assertEqual(report["codes"], sorted(set(report["codes"])))
        self.assertTrue(all({"name", "status", "code", "message"} == set(item) for item in report["checks"]))

    # Unit scenarios: report schema/aggregation, task-id input, binding parsing and path normalization.
    def test_identity_report_has_complete_schema_and_explicit_full_not_run(self) -> None:
        self.init_binding()
        report = self.identity()
        self.assert_report_shape(report, mode="identity", scope="task")
        self.assertEqual(report["full_verification"], "not_run")
        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(any(item["status"] == "not_run" for item in report["checks"]))

    def test_input_rejects_partial_task_triples_and_unsafe_task_ids(self) -> None:
        partial = self.doctor(
            "check", "--mode", "full", "--package-root", str(self.package),
            "--task-id", "TASK-001", expected=1,
        )
        self.assertEqual(partial["status"], "fail")
        self.assertIn("INPUT_INVALID", partial["codes"])
        for task_id in (".", "..", "../escape", "bad/slash", ""):
            with self.subTest(task_id=task_id):
                report = self.doctor("init-binding", *self.binding_args(task_id=task_id), expected=1)
                self.assertEqual(report["status"], "fail")
                self.assertIn("INPUT_INVALID", report["codes"])

    def test_unknown_or_incomplete_cli_arguments_are_json_input_failures(self) -> None:
        cases = [
            ("check", "--mode", "identity", "--unexpected", "value"),
            ("init-binding", "--package-root", str(self.package)),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                report = self.doctor(*arguments, expected=1)
                self.assertEqual(report["status"], "fail")
                self.assertIn("INPUT_INVALID", report["codes"])

    # Integration: AC3 idempotence and no-overwrite conflict.
    def test_identical_binding_is_byte_identical_and_conflict_preserves_original(self) -> None:
        self.init_binding()
        path = self.context_root / "TASK-001" / "context-binding.json"
        original = path.read_bytes()
        unchanged = self.init_binding()
        self.assertEqual(unchanged["status"], "pass")
        self.assertEqual(path.read_bytes(), original)

        other_workspace = self.root / "other-workspace"
        other_workspace.mkdir()
        conflict = self.init_binding(workspace=other_workspace, expected=1)
        self.assertEqual(conflict["status"], "fail")
        self.assertIn("BINDING_CONFLICT", conflict["codes"])
        self.assertEqual(path.read_bytes(), original)

    # Integration: AC2, including same task name in independent workspace/storage pairs.
    def test_workspace_and_storage_mismatches_never_pass_for_same_task_name(self) -> None:
        self.init_binding()
        other_workspace = self.root / "other-workspace"
        other_context = self.root / "other-context"
        other_workspace.mkdir()
        other_context.mkdir()
        (other_context / "TASK-001").mkdir()
        workspace_mismatch = self.identity(workspace=other_workspace, expected=1)
        self.assertEqual(workspace_mismatch["status"], "fail")
        self.assertIn("WORKSPACE_MISMATCH", workspace_mismatch["codes"])

        # A binding from another storage root with the same task id is not interchangeable.
        # Copying the on-disk record simulates a task directory accidentally
        # placed under a different storage root; its declared storage remains
        # the original root and must fail closed.
        original = self.context_root / "TASK-001/context-binding.json"
        (other_context / "TASK-001/context-binding.json").write_bytes(original.read_bytes())
        storage_mismatch = self.identity(context_root=other_context, expected=1)
        self.assertEqual(storage_mismatch["status"], "fail")
        self.assertIn("STORAGE_MISMATCH", storage_mismatch["codes"])

    # Integration: AC5.  Unknown conditions must neither recreate nor become pass.
    def test_missing_invalid_and_unreadable_bindings_are_unknown_without_rebuild(self) -> None:
        binding = self.context_root / "TASK-001" / "context-binding.json"
        missing = self.identity(expected=2)
        self.assertEqual(missing["status"], "unknown")
        self.assertIn("BINDING_MISSING", missing["codes"])
        self.assertFalse(binding.exists())

        binding.write_text("{not json", encoding="utf-8")
        invalid = self.identity(expected=2)
        self.assertEqual(invalid["status"], "unknown")
        self.assertIn("BINDING_INVALID", invalid["codes"])
        self.assertEqual(binding.read_text(encoding="utf-8"), "{not json")

        binding.unlink()
        binding.mkdir()
        unreadable = self.identity(expected=2)
        self.assertEqual(unreadable["status"], "unknown")
        self.assertTrue({"READ_FAILED", "BINDING_INVALID"}.intersection(unreadable["codes"]))

    # Unit cases for the frozen binding schema: extra fields and non-RFC3339
    # metadata are corrupt evidence, never a permissive migration opportunity.
    def test_binding_schema_rejects_extra_fields_and_invalid_created_at(self) -> None:
        self.init_binding()
        path = self.context_root / "TASK-001/context-binding.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        cases = {
            "extra": {**original, "unexpected": True},
            "created-at": {**original, "created_at": "tomorrow"},
            "schema": {**original, "schema": 2},
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                path.write_text(json.dumps(value), encoding="utf-8")
                report = self.identity(expected=2)
                self.assertEqual(report["status"], "unknown")
                self.assertIn("BINDING_INVALID", report["codes"])

    def test_binding_symlink_escaping_task_is_storage_mismatch_and_is_never_followed(self) -> None:
        outside = self.root / "outside-binding.json"
        outside.write_text("{}", encoding="utf-8")
        binding = self.context_root / "TASK-001/context-binding.json"
        binding.symlink_to(outside)
        report = self.identity(expected=1)
        self.assertEqual(report["status"], "fail")
        self.assertIn("STORAGE_MISMATCH", report["codes"])

    # Integration: AC3. Distinct concurrent requests have exactly one winner and never replace it.
    def test_concurrent_conflicting_initialization_has_one_winner_and_no_overwrite(self) -> None:
        workspaces = [self.root / "workspace-a", self.root / "workspace-b"]
        for workspace in workspaces:
            workspace.mkdir()

        def initialize(workspace: Path) -> tuple[int, dict]:
            args = self.binding_args(workspace=workspace)
            completed = subprocess.run(
                [sys.executable, str(self.package / "scripts/context_doctor.py"), "init-binding", *args],
                cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.package / "src")},
                text=True, capture_output=True, timeout=20,
            )
            return completed.returncode, json.loads(completed.stdout)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(initialize, workspaces))
        successful = [report for code, report in results if code == 0]
        failed = [report for code, report in results if code == 1]
        self.assertEqual(len(successful), 1, results)
        self.assertEqual(len(failed), 1, results)
        self.assertIn("BINDING_CONFLICT", failed[0]["codes"])
        binding = json.loads((self.context_root / "TASK-001" / "context-binding.json").read_text())
        self.assertIn(binding["workspace_root"], {str(path.resolve()) for path in workspaces})

    # Integration: AC4. Identity input is captured, never inferred from the process cwd.
    def test_binding_survives_chdir_and_branch_like_workspace_changes(self) -> None:
        self.init_binding()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            report = self.identity()
        finally:
            os.chdir(previous)
        self.assertEqual(report["status"], "pass", report)

    # Integration: AC9 and AC10.  The I/O audit asserts zero *attempted*
    # historical reads, not merely that an attempted read happened to fail.
    def test_identity_does_not_read_history_or_evidence_and_check_is_read_only(self) -> None:
        self.init_binding()
        task = self.context_root / "TASK-001"
        (task / "events.jsonl").write_text('{"old":"history"}\n', encoding="utf-8")
        (task / "evidence-original.txt").write_text("original evidence\n", encoding="utf-8")
        before = {path.name: sha256(path) for path in task.iterdir() if path.is_file()}
        report, opened = self.identity_with_open_audit()
        after = {path.name: sha256(path) for path in task.iterdir() if path.is_file()}
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(before, after)
        historical = {str((task / "events.jsonl").resolve()), str((task / "evidence-original.txt").resolve())}
        self.assertFalse(historical.intersection(opened), opened)
        checks = {item["name"]: item["status"] for item in report["checks"]}
        self.assertEqual(checks["full_verification"], "not_run")
        self.assertEqual(checks["smoke"], "not_run")

    # Package/runtime integration: AC7 wrong import path and post-load package change must hard-stop.
    def test_wrong_pythonpath_and_loaded_manifest_change_never_report_runtime_pass(self) -> None:
        self.init_binding()
        wrong = self.root / "wrong-pythonpath"
        (wrong / "managing_long_task_context").mkdir(parents=True)
        (wrong / "managing_long_task_context/__init__.py").write_text("", encoding="utf-8")
        report = self.identity(expected=2, env={"PYTHONPATH": str(wrong)})
        self.assertNotEqual(report["status"], "pass", report)
        self.assertTrue({"RUNTIME_PATH_MISMATCH", "RUNTIME_UNVERIFIED"}.intersection(report["codes"]))

        changed_package = self.root / "changed-strict-package"
        shutil.copytree(self.package, changed_package)
        script = (
            "import json, pathlib, managing_long_task_context as c; "
            "p=pathlib.Path(__import__('sys').argv[1])/'skill-manifest.json'; "
            "p.write_text(p.read_text()+'\\n', encoding='utf-8'); "
            "print(json.dumps(c.runtime_identity(package_root=__import__('sys').argv[1])))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(changed_package)], cwd=self.root,
            env={**os.environ, "PYTHONPATH": str(changed_package / "src")},
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        changed = json.loads(completed.stdout)
        self.assertNotEqual(changed["status"], "pass", changed)
        self.assertTrue({"PACKAGE_IDENTITY_MISMATCH", "RUNTIME_UNVERIFIED"}.intersection(changed["codes"]))

    # AC7: the baseline must be captured at import time, not lazily at first use.
    def test_manifest_change_during_controlled_module_import_never_reports_pass(self) -> None:
        changing_package = self.root / "changing-during-import"
        shutil.copytree(self.package, changing_package)
        runtime = changing_package / "src/managing_long_task_context/runtime_identity.py"
        source = runtime.read_text(encoding="utf-8")
        injection = (
            "from __future__ import annotations\n"
            "from pathlib import Path as _IdentityTestPath\n"
            "_identity_test_manifest = _IdentityTestPath(__file__).resolve().parents[2] / 'skill-manifest.json'\n"
            "_identity_test_manifest.write_text(_identity_test_manifest.read_text(encoding='utf-8') + '\\n', encoding='utf-8')\n"
        )
        self.assertIn("from __future__ import annotations\n", source)
        runtime.write_text(source.replace("from __future__ import annotations\n", injection, 1), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", "import json, managing_long_task_context as c; print(json.dumps(c.runtime_identity(package_root=__import__('sys').argv[1])))", str(changing_package)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(changing_package / "src")},
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertNotEqual(report["status"], "pass", report)
        self.assertIn("RUNTIME_UNVERIFIED", report["codes"])

    # AC7: an identity that did not exist when import began cannot become
    # trustworthy merely because a manifest appears before import completes.
    def test_manifest_appearing_during_controlled_module_import_remains_unverified(self) -> None:
        changing_package = self.root / "manifest-appears-during-import"
        shutil.copytree(self.package, changing_package)
        manifest = changing_package / "skill-manifest.json"
        staged = changing_package / "staged-manifest.json"
        manifest.replace(staged)
        runtime = changing_package / "src/managing_long_task_context/runtime_identity.py"
        source = runtime.read_text(encoding="utf-8")
        injection = (
            "from __future__ import annotations\n"
            "from pathlib import Path as _ManifestAppearsPath\n"
            f"_ManifestAppearsPath({str(staged)!r}).replace(_ManifestAppearsPath({str(manifest)!r}))\n"
        )
        runtime.write_text(source.replace("from __future__ import annotations\n", injection, 1), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", "import json, managing_long_task_context as c; print(json.dumps(c.runtime_identity(package_root=__import__('sys').argv[1])))", str(changing_package)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(changing_package / "src")},
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertNotEqual(report["status"], "pass", report)
        self.assertIn("RUNTIME_UNVERIFIED", report["codes"])

    def test_payload_tampered_before_first_import_never_reports_runtime_pass(self) -> None:
        tampered_package = self.root / "tampered-before-import"
        shutil.copytree(self.package, tampered_package)
        runtime = tampered_package / "src/managing_long_task_context/runtime_identity.py"
        shutil.copyfile(
            ROOT / "src/managing_long_task_context/runtime_identity.py", runtime
        )
        manifest_path = tampered_package / "skill-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runtime_entry = next(
            item for item in manifest["files"]
            if item["path"] == "src/managing_long_task_context/runtime_identity.py"
        )
        runtime_entry.update(sha256=sha256(runtime), size=runtime.stat().st_size)
        manifest["source_tree_sha256"] = hashlib.sha256(
            json.dumps(
                manifest["files"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ) + "\n",
            encoding="utf-8",
        )
        payload = tampered_package / "src/managing_long_task_context/host_codex_native.py"
        payload.write_bytes(payload.read_bytes() + b"\n# tampered before first import\n")
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, managing_long_task_context as c; "
                    "print(json.dumps(c.runtime_identity(package_root=__import__('sys').argv[1])))"
                ),
                str(tampered_package),
            ],
            cwd=self.root,
            env={**os.environ, "PYTHONPATH": str(tampered_package / "src")},
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertNotEqual(report["status"], "pass", report)
        self.assertIn("RUNTIME_UNVERIFIED", report["codes"])

    def test_bound_strict_resume_succeeds_from_another_cwd_and_preserves_sealed_errors(self) -> None:
        self.init_binding()
        script = '''
import hashlib, json, os, sys
from pathlib import Path
import managing_long_task_context as c
package, workspace, store, elsewhere = map(Path, sys.argv[1:])
c.publish_contract({"schema":1,"task_id":"TASK-001","version":1,
    "issued_by":"test","issued_at":"2026-09-05T00:00:00Z","authorized_approvers":[],
    "workspace_root":str(workspace),"objective":"Recover actual bound task","scope":["test"],
    "out_of_scope":[],"constraints":[],"acceptance_criteria":[{"id":"AC-1",
    "criterion":"file evidence","required_evidence_types":["file"],"required_hops":[],
    "required_delivery_types":[],"independent_validation_required":False}]},
    confirmed_by="test",base_dir=store)
client=c.bind(store, workspace_root=workspace, package_root=package)
def hashes():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob('*') if p.is_file()}
before=hashes()
os.chdir(elsewhere)
packet=client.checked_resume("TASK-001")
assert packet["diagnostic"]["status"]=="pass", packet
assert packet["context"]["task_id"]=="TASK-001", packet
assert before==hashes(), "checked resume changed real task bytes"
contract=store/"TASK-001/task-contract.json"
contract.chmod(0o600)
data=json.loads(contract.read_text()); data["objective"]="tampered"
contract.write_text(json.dumps(data))
try:
    client.checked_resume("TASK-001")
except c.ContextError:
    print("BOUND_RESUME_AND_ORIGINAL_GATE_PASSED")
else:
    raise AssertionError("modified sealed contract was accepted")
'''
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        result = subprocess.run([sys.executable, "-c", script, str(self.package),
                                 str(self.workspace), str(self.context_root), str(elsewhere)],
                                cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.package / "src")},
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOUND_RESUME_AND_ORIGINAL_GATE_PASSED", result.stdout)

    def test_doctor_from_other_package_cannot_borrow_matching_runtime_identity(self) -> None:
        self.init_binding()
        other = self.root / "other-package"
        shutil.copytree(self.package, other)
        completed = subprocess.run([
            sys.executable, str(other / "scripts/context_doctor.py"), "check", "--mode", "identity",
            "--package-root", str(self.package), "--context-root", str(self.context_root),
            "--workspace-root", str(self.workspace), "--task-id", "TASK-001"],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.package / "src")},
            text=True, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("RUNTIME_PATH_MISMATCH", json.loads(completed.stdout)["codes"])

    # Public Python contract: AC13 preserves legacy bind and blocks the newly guarded resume.
    def test_checked_resume_blocks_without_binding_while_legacy_bind_remains_compatible(self) -> None:
        module_path = self.package / "src/managing_long_task_context/__init__.py"
        spec = importlib.util.spec_from_file_location("packaged_context_for_identity_test", module_path,
                                                      submodule_search_locations=[str(module_path.parent)])
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            legacy = module.bind(self.context_root)
            self.assertTrue(callable(legacy.brief))
            old_guarded = legacy.checked_resume("TASK-001")
            with self.assertRaises(ValueError):
                module.bind(self.context_root, workspace_root="relative-workspace", package_root=self.package)
            with self.assertRaises(ValueError):
                module.bind(self.context_root, workspace_root=self.workspace, package_root="relative-package")
            guarded = module.bind(self.context_root, workspace_root=self.workspace, package_root=self.package)
            outcome = guarded.checked_resume("TASK-001")
        finally:
            sys.modules.pop(spec.name, None)
        self.assertIsNone(outcome["context"])
        self.assertEqual(outcome["diagnostic"]["status"], "unknown")
        self.assertIn("BINDING_MISSING", outcome["diagnostic"]["codes"])
        self.assertIsNone(old_guarded["context"])
        self.assertEqual(old_guarded["diagnostic"]["status"], "unknown")
        self.assertIn("BINDING_MISSING", old_guarded["diagnostic"]["codes"])


if __name__ == "__main__":
    unittest.main()
