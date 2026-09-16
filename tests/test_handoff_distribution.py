from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"
STRICT_SOURCE = ROOT / "skills" / "context-strict"


class HandoffDistributionTests(unittest.TestCase):
    def build_package(self, root: Path, name: str, revision: str) -> Path:
        package = root / name
        completed = subprocess.run(
            [
                sys.executable, str(PACKAGER), "build", "--source", str(STRICT_SOURCE),
                "--destination", str(package), "--source-revision", revision,
            ],
            cwd=root, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return package

    def doctor(self, root: Path, package: Path, *, expected: int) -> dict[str, object]:
        completed = subprocess.run(
            [
                sys.executable, str(package / "scripts" / "context_doctor.py"),
                "check", "--mode", "full", "--package-root", str(package),
            ],
            cwd=root, env={**os.environ, "PYTHONPATH": str(package / "src")},
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_built_package_bound_handoff_never_guesses_missing_identity_paths(self) -> None:
        """All five public handoff calls fail closed before touching task state."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "context-strict"
            build = subprocess.run(
                [
                    sys.executable, str(PACKAGER), "build", "--source", str(STRICT_SOURCE),
                    "--destination", str(package), "--source-revision", "candidate:dirty-e2-red",
                ],
                cwd=root, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            receipt = json.loads(build.stdout)
            script = r'''
import json
import managing_long_task_context as context

bound = context.bind("{base}")
calls = [
    ("prepare_handoff", ("TASK-E2-001",), {{"request_id": "REQ-1", "controller_generation": 0, "record": {{}}}}),
    ("validate_handoff", ("TASK-E2-001",), {{"handoff_id": "HO-1"}}),
    ("activate_handoff", ("TASK-E2-001",), {{"request_id": "REQ-2", "controller_generation": 0, "handoff_id": "HO-1"}}),
    ("cancel_handoff", ("TASK-E2-001",), {{"request_id": "REQ-3", "controller_generation": 0, "handoff_id": "HO-1"}}),
    ("handoff_status", ("TASK-E2-001",), {{"handoff_id": "HO-1"}}),
]
for name, args, kwargs in calls:
    result = getattr(bound, name)(*args, **kwargs)
    assert result["check_status"] == "unknown", (name, result)
    assert result["commit_status"] == "not_attempted", (name, result)
    assert result["blocking_reasons"][0]["code"] == "HANDOFF_BINDING_REQUIRED", (name, result)
print(json.dumps({{"manifest": "{manifest}", "calls": len(calls)}}))
'''.format(base=str(root / "context"), manifest=receipt["manifest_sha256"])
            environment = {**os.environ, "PYTHONPATH": str(package / "src")}
            completed = subprocess.run(
                [sys.executable, "-c", script], cwd=root, env=environment,
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["calls"], 5)

    def test_built_package_example_exercises_synthetic_handoff_without_source_tree(self) -> None:
        """The packaged example performs the guarded handoff lifecycle in a fresh process."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "context-strict"
            build = subprocess.run(
                [
                    sys.executable, str(PACKAGER), "build", "--source", str(STRICT_SOURCE),
                    "--destination", str(package), "--source-revision", "candidate:dirty-e2-example-red",
                ],
                cwd=root, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            doctor = subprocess.run(
                [
                    sys.executable, str(package / "scripts" / "context_doctor.py"),
                    "check", "--mode", "full", "--package-root", str(package),
                ],
                cwd=root, env={**os.environ, "PYTHONPATH": str(package / "src")},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            completed = subprocess.run(
                [sys.executable, str(package / "examples" / "short_session_handoff.py")],
                cwd=root, env={**os.environ, "PYTHONPATH": str(package / "src")},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["identity"], "pass", report)
            self.assertEqual(report["prepare"], "pass", report)
            self.assertEqual(report["validate"], "pass", report)
            self.assertEqual(report["activate"], "confirmed_committed", report)
            self.assertEqual(report["repeat_activate_generation"], 1, report)
            self.assertTrue(report["repeat_activate_same_event_log"], report)
            self.assertEqual(report["activation_events"], 1, report)
            self.assertEqual(report["status"], "confirmed_committed", report)
            self.assertEqual(report["cancel"], "confirmed_committed", report)

    def test_built_package_accepts_only_explicit_short_session_capability_declaration(self) -> None:
        """Capability support is opt-in contract data, not an implicit legacy upgrade."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.build_package(root, "context-strict", "candidate:dirty-e2-capability")
            script = r'''
import json
import managing_long_task_context as context
from pathlib import Path

contract = {{
  "schema": 1, "task_id": "TASK-CAPABILITY-001", "version": 1, "issued_by": "publisher",
  "issued_at": "2026-09-15T00:00:00Z", "authorized_approvers": [],
  "objective": "synthetic explicit capability", "scope": ["temporary"], "out_of_scope": [],
  "constraints": ["no business action"], "required_capabilities": ["short-session-handoff/v1"],
  "acceptance_criteria": [{{"id": "AC-01", "criterion": "synthetic", "required_evidence": ["local"]}}],
}}
result = context.publish_contract(contract, confirmed_by="publisher", base_dir=r"{base}")
sealed = json.loads((Path(r"{base}") / "TASK-CAPABILITY-001" / "task-contract.json").read_text())
assert "integrity_digest" in result["seal"], result
assert sealed["required_capabilities"] == ["short-session-handoff/v1"], sealed
legacy = dict(contract)
legacy.pop("required_capabilities")
legacy["task_id"] = "TASK-CAPABILITY-LEGACY"
context.publish_contract(legacy, confirmed_by="publisher", base_dir=r"{base}")
old_sealed = json.loads((Path(r"{base}") / "TASK-CAPABILITY-LEGACY" / "task-contract.json").read_text())
assert "required_capabilities" not in old_sealed, old_sealed
print(json.dumps({{"explicit": sealed["required_capabilities"], "legacy": old_sealed.get("required_capabilities")}}))
'''.format(base=root / "context")
            completed = subprocess.run(
                [sys.executable, "-c", script], cwd=root,
                env={**os.environ, "PYTHONPATH": str(package / "src")},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_complete_package_rejects_handoff_removal_or_tamper_and_runtime_identity_swaps(self) -> None:
        """Full doctor verifies content; lightweight identity catches process/package swaps only."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_a = self.build_package(root, "package-a", "candidate:dirty-e2-a")
            package_b = self.build_package(root, "package-b", "candidate:dirty-e2-b")
            for name, mutate in (("tampered", lambda path: path.write_text("# tampered\n", encoding="utf-8")),
                                 ("removed", lambda path: path.unlink())):
                copied = root / name
                shutil.copytree(package_a, copied)
                target = copied / "src" / "managing_long_task_context" / "handoff.py"
                mutate(target)
                report = self.doctor(root, copied, expected=1)
                self.assertEqual(report["status"], "fail", report)
                self.assertTrue(
                    {"PACKAGE_HASH_MISMATCH", "PACKAGE_FILE_MISSING"}.intersection(report["codes"]),
                    report,
                )
            wrong_root = r'''
import json
import managing_long_task_context as context
report = context.runtime_identity(package_root=r"{package_b}")
assert report["status"] == "fail", report
assert "RUNTIME_PATH_MISMATCH" in report["codes"], report
print(json.dumps(report))
'''.format(package_b=package_b)
            wrong = subprocess.run(
                [sys.executable, "-c", wrong_root], cwd=root,
                env={**os.environ, "PYTHONPATH": str(package_a / "src")},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(wrong.returncode, 0, wrong.stdout + wrong.stderr)
            swapped_manifest = r'''
import json
import shutil
import managing_long_task_context as context
shutil.copyfile(r"{other_manifest}", r"{loaded_manifest}")
report = context.runtime_identity(package_root=r"{package_a}")
assert report["status"] == "fail", report
assert "PACKAGE_IDENTITY_MISMATCH" in report["codes"], report
print(json.dumps(report))
'''.format(other_manifest=package_b / "skill-manifest.json", loaded_manifest=package_a / "skill-manifest.json", package_a=package_a)
            swapped = subprocess.run(
                [sys.executable, "-c", swapped_manifest], cwd=root,
                env={**os.environ, "PYTHONPATH": str(package_a / "src")},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(swapped.returncode, 0, swapped.stdout + swapped.stderr)

    def test_complete_package_runs_self_contained_host_and_basis_rejection_cases(self) -> None:
        """The distributed protocol tests reject missing, forged, and changed host evidence."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.build_package(root, "context-strict", "candidate:dirty-e2-host-rejections")
            completed = subprocess.run(
                [
                    sys.executable, "-m", "unittest", "-v",
                    "test_handoff_protocol.HandoffProtocolTests.test_missing_runtime_verifier_and_missing_authoritative_log_remain_unknown",
                    "test_handoff_protocol.HandoffProtocolTests.test_verifier_reference_with_matching_id_but_wrong_digest_cannot_pass",
                    "test_handoff_protocol.HandoffProtocolTests.test_changed_host_evidence_before_callback_return_cannot_pass",
                ],
                cwd=package / "tests",
                env={**os.environ, "PYTHONPATH": os.pathsep.join((str(package / "src"), str(package / "tests")))},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Ran 3 tests", completed.stderr, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
