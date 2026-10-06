from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from runpy import run_path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dispatch_spec.py"
STRICT = ROOT / "skills/context-strict"
if not STRICT.is_dir():
    STRICT = ROOT
GENERATOR = run_path(str(SCRIPT))


class DispatchSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "store"
        self.path = self.store / "STEP4-58" / "task-contract.json"
        self.path.parent.mkdir(parents=True)
        self.contract = {
            "schema": 1, "task_id": "STEP4-58", "version": 1,
            "workspace_root": ".",
            "objective": "Generate the executor dispatch from a sealed contract.",
            "scope": ["scripts/dispatch_spec.py", "tests/test_dispatch_spec.py"],
            "out_of_scope": ["src/managing_long_task_context/", "brief()"],
            "constraints": ["Read only; do not write the task store."],
            "acceptance_criteria": [
                {"id": "AC-01", "criterion": "六项输出逐项可定位。"},
                {"id": "AC-02", "criterion": "  原文 é / e\u0301\r\n  第二行\t末尾空白  "},
                {"id": "AC-03", "criterion": "Proof uses runtime_identity(*, package_root)."},
            ],
            "seal": {"confirmed_by": "coordinator", "confirmed_at": "2026-10-06T00:00:00Z"},
        }
        self.write_contract()

    def write_contract(self) -> None:
        unsigned = copy.deepcopy(self.contract)
        unsigned["seal"].pop("integrity_digest", None)
        payload = json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        self.contract["seal"]["integrity_digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.path.write_text(json.dumps(self.contract, ensure_ascii=False), encoding="utf-8")

    def argv(self, role: str = "executor") -> list[str]:
        return ["--store", str(self.store), "--task-id", "STEP4-58", "--role", role,
                "--package-root", str(STRICT), "--expected-manifest", "a" * 64,
                "--coordinator-workspace", str(self.root / "coordinator"),
                "--baseline-commit", "fce3c53"]

    def run_cli(self, *extra: str, role: str = "executor", cwd: Path | None = None):
        return subprocess.run([sys.executable, str(SCRIPT), *self.argv(role), *extra],
                              cwd=cwd or self.root, capture_output=True, timeout=30)

    def output(self, *extra: str, role: str = "executor") -> bytes:
        result = self.run_cli(*extra, role=role)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout

    def test_executor_output_has_all_six_dispatch_fields(self) -> None:
        output = self.output().decode()
        for keyword in ("Objective, change, constraints, ownership", "Skill task_id",
                        "Acceptance criteria", "Coordinator workspace (absolute)",
                        "Report path template", "Pinned runtime"):
            self.assertIn(keyword, output)
        for item in (self.contract["objective"], *self.contract["scope"],
                     *self.contract["constraints"], *self.contract["out_of_scope"], "fce3c53"):
            self.assertIn(item, output)

    def test_readonly_entry_text_replaces_old_prohibition(self) -> None:
        output = self.output().decode()
        self.assertIn("可调用 `brief()`、`checked_resume()` 与状态命令只读查看", output)
        self.assertIn("不得写任务库与经验库", output)
        self.assertNotIn("Do not call checked_resume(), depend on brief()", output)

    def test_sealed_worker_report_claim_is_copied_without_command_changes(self) -> None:
        claim = {"commands": ["  PYTHONPATH=src:tests python3 -m unittest tests.test_worker_report  ",
                              "printf '原文\\n'", "echo \"$literal\""], "extra": "preserved"}
        self.contract["acceptance_criteria"][0]["worker_report_claim"] = claim
        self.write_contract()
        for role in ("executor", "reviewer"):
            output = self.output(role=role).decode()
            self.assertIn(json.dumps(claim, ensure_ascii=False), output)
            observed = output.split("worker_report_claim: ", 1)[1].split("\n", 1)[0]
            self.assertEqual(json.loads(observed), claim)

    def test_acceptance_id_and_criterion_bytes_are_verbatim(self) -> None:
        output = self.output()
        expected = "\n".join(f"- {item['id']}: {item['criterion']}"
                             for item in self.contract["acceptance_criteria"]).encode("utf-8")
        observed = output.split(b"Acceptance criteria, copied verbatim from the sealed contract:\n\n", 1)[1]
        observed = observed.split(b"\n\nOpen and read the original contract", 1)[0]
        self.assertEqual(observed, expected)
        for item in self.contract["acceptance_criteria"]:
            self.assertIn(item["id"].encode(), observed)
            self.assertIn(item["criterion"].encode(), observed)
        self.assertIn(self.contract["seal"]["integrity_digest"].encode(), output)
        self.assertIn(str(self.path.resolve()).encode(), output)

    def test_report_template_keeps_unknown_worker_root_and_dispatch_placeholder(self) -> None:
        output = self.output().decode()
        self.assertIn("<worker-workspace-root>/.context-reports/STEP4-58/<dispatch-id>.json", output)
        self.assertIn("git rev-parse --show-toplevel", output)
        self.assertNotIn(str(self.root / ".context-reports"), output)

    def test_explicit_worker_workspace_is_resolved(self) -> None:
        worker = self.root / "worker" / ".." / "actual-worker"
        output = self.output("--worker-workspace", str(worker)).decode()
        self.assertIn(f"Report path template (absolute): {worker.resolve()}/.context-reports/STEP4-58/<dispatch-id>.json", output)

    def test_coordinator_and_package_paths_are_absolute(self) -> None:
        output = self.output().decode()
        self.assertIn(f"Coordinator workspace (absolute): {(self.root / 'coordinator').resolve()}", output)
        self.assertIn(f"Package (absolute): {STRICT.resolve()}", output)
        self.assertIn("Expected manifest SHA-256: " + "a" * 64, output)

    def test_explicit_owned_paths_replace_default_ownership(self) -> None:
        output = self.output("--owned-paths", "scripts/dispatch_spec.py").decode()
        ownership = output.split("- Owned editable paths:", 1)[1].split("- Allowed report/log paths:", 1)[0]
        self.assertIn("scripts/dispatch_spec.py", ownership)
        self.assertNotIn("tests/test_dispatch_spec.py", ownership)
        self.assertIn("An owned path never expands the sealed scope", output)

    def test_reviewer_is_read_only_and_uses_same_acceptance(self) -> None:
        output = self.output("--owned-paths", "ignored.py", role="reviewer").decode()
        self.assertIn("# Reviewer dispatch spec", output)
        self.assertIn("Read-only review; no implementation paths may be edited", output)
        self.assertNotIn("ignored.py", output)
        for item in self.contract["acceptance_criteria"]:
            self.assertIn(item["criterion"], output)
        self.assertIn("A reviewer also records findings", output)

    def test_generation_does_not_change_or_create_task_store_files(self) -> None:
        events = self.path.parent / "events.jsonl"
        events.write_bytes(b"not parsed by generator\n")
        self.path.chmod(0o444)
        def snapshot():
            return {str(path.relative_to(self.store)): (path.read_bytes(), path.stat().st_mtime_ns,
                                                        path.stat().st_mode)
                    for path in self.store.rglob("*") if path.is_file()}
        before = snapshot()
        self.output()
        self.assertEqual(snapshot(), before)

    def test_missing_contract_fails_without_creating_store(self) -> None:
        missing = self.root / "missing"
        result = self.run_cli("--store", str(missing))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertFalse(missing.exists())

    def test_unsealed_and_tampered_contracts_fail_without_partial_output(self) -> None:
        for kind in ("unsealed", "tampered"):
            with self.subTest(kind=kind):
                altered = copy.deepcopy(self.contract)
                if kind == "unsealed":
                    altered.pop("seal")
                else:
                    altered["acceptance_criteria"][0]["criterion"] = "weakened"
                self.path.write_text(json.dumps(altered), encoding="utf-8")
                result = self.run_cli()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")

    def test_mismatched_task_and_traversal_fail(self) -> None:
        self.contract["task_id"] = "another-task"
        self.write_contract()
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        for task_id in ("../STEP4-58", "/absolute", ".", "..", "nested\\task"):
            with self.subTest(task_id=task_id):
                result = self.run_cli("--task-id", task_id)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")

    def test_invalid_criterion_is_not_silently_rewritten(self) -> None:
        self.contract["acceptance_criteria"][0]["criterion"] = None
        self.write_contract()
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"string id and criterion", result.stderr)

    def test_invalid_role_is_rejected(self) -> None:
        result = self.run_cli(role="publisher")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_unicode_key_order_matches_contract_seal_format(self) -> None:
        # UTF-16 orders the supplementary key before the private-use key.
        self.assertEqual(GENERATOR["_canonical"]({"\ue000": 2, "😀": 1}),
                         '{"😀":1,"\ue000":2}'.encode())

    def test_generated_version_proof_executes_against_strict_source(self) -> None:
        output = self.output().decode()
        command = output.split("```sh\n", 1)[1].split("\n```", 1)[0]
        result = subprocess.run(command, shell=True, cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads(result.stdout)
        self.assertEqual(Path(proof["loaded_module_file"]).resolve(),
                         (STRICT / "src/managing_long_task_context/__init__.py").resolve())
        self.assertIn("loaded_manifest_sha256", proof)

    def test_built_package_proof_has_digest_and_shell_safe_path(self) -> None:
        package = self.root / "package with 'quotes' $(touch SHOULD_NOT_EXIST) `echo nope`; end"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/skill_package.py"), "build", "--source", str(STRICT),
             "--destination", str(package), "--source-revision", "test:dispatch-spec"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = json.loads(result.stdout)["manifest_sha256"]
        command = GENERATOR["version_proof_command"](package)
        # A hostile PYTHONPATH must be replaced by the generated command's root.
        env = {**os.environ, "PYTHONPATH": str(self.root / "wrong-runtime")}
        result = subprocess.run(command, shell=True, cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads(result.stdout)
        self.assertEqual(proof["loaded_manifest_sha256"], expected)
        self.assertTrue(Path(proof["loaded_module_file"]).is_relative_to(package.resolve()))
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_three_distribution_registrations_and_generated_bytes(self) -> None:
        paths = ("scripts/dispatch_spec.py", "tests/test_dispatch_spec.py")
        declaration = json.loads((ROOT / "skill-package.json").read_bytes())
        for relative in paths:
            self.assertEqual(declaration["required_paths"].count(relative), 1)
            if STRICT != ROOT:
                self.assertEqual((ROOT / relative).read_bytes(), (STRICT / relative).read_bytes())
        if (ROOT / "scripts/sync_context_strict_skill.py").is_file():
            copied = run_path(str(ROOT / "scripts/sync_context_strict_skill.py"))["COPIED_FILES"]
            independent = run_path(str(ROOT / "tests/test_distribution.py"))["COPIED_FILES"]
            for relative in paths:
                self.assertEqual(copied.count(Path(relative)), 1)
                self.assertEqual(independent.count(Path(relative)), 1)


if __name__ == "__main__":
    unittest.main()
