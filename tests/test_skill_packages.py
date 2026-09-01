from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "skill_package.py"


class SkillPackageTests(unittest.TestCase):
    def run_tool(self, *args: str, expected: int = 0) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_strict_source_declaration_exposes_version_and_truth_capability(self) -> None:
        declaration = json.loads((ROOT / "skills/context-strict/skill-package.json").read_text())
        self.assertEqual(declaration["skill_name"], "context-strict")
        self.assertRegex(declaration["skill_version"], r"^\d+\.\d+\.\d+$")
        self.assertIn("truth-sources/v1", declaration["capabilities"])
        self.assertIn("observe_truth_source", declaration["capabilities"]["truth-sources/v1"]["python_exports"])

    def test_build_and_verify_full_strict_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "context-strict"
            built = self.run_tool(
                "build",
                "--source", str(ROOT / "skills/context-strict"),
                "--destination", str(destination),
                "--source-revision", "git:test-revision",
            )
            self.assertEqual(built["status"], "pass")
            manifest = json.loads((destination / "skill-manifest.json").read_text())
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertIn("SKILL.md", paths)
            self.assertIn("assets/truth-source-contract.example.json", paths)
            self.assertIn("examples/truth_source_contract.py", paths)
            self.assertIn("src/managing_long_task_context/truth_sources.py", paths)
            self.assertIn("tests/test_truth_sources.py", paths)
            self.assertEqual(manifest["source_revision"], "git:test-revision")
            self.assertRegex(built["manifest_sha256"], r"^[0-9a-f]{64}$")
            verified = self.run_tool("verify", "--package", str(destination))
            self.assertEqual(verified["status"], "pass")
            self.assertGreater(verified["stats"]["files_checked"], 5)
            pinned = self.run_tool(
                "verify", "--package", str(destination),
                "--expected-manifest-sha256", built["manifest_sha256"],
                "--expected-source-revision", "git:test-revision",
            )
            self.assertEqual(pinned["status"], "pass")

    def test_verify_fails_closed_for_tamper_missing_and_extra_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "context-strict"
            self.run_tool(
                "build", "--source", str(ROOT / "skills/context-strict"),
                "--destination", str(destination), "--source-revision", "git:test",
            )
            (destination / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            report = self.run_tool("verify", "--package", str(destination), expected=1)
            self.assertIn("PACKAGE_HASH_MISMATCH", report["codes"])

            shutil.copy2(ROOT / "skills/context-strict/SKILL.md", destination / "SKILL.md")
            (destination / "examples/strict_completion.py").unlink()
            report = self.run_tool("verify", "--package", str(destination), expected=1)
            self.assertIn("PACKAGE_FILE_MISSING", report["codes"])

            shutil.copy2(
                ROOT / "skills/context-strict/examples/strict_completion.py",
                destination / "examples/strict_completion.py",
            )
            (destination / "unexpected.py").write_text("pass\n", encoding="utf-8")
            report = self.run_tool("verify", "--package", str(destination), expected=1)
            self.assertIn("PACKAGE_FILE_UNEXPECTED", report["codes"])

    def test_verify_rejects_manifest_identity_different_from_packaged_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "context-strict"
            self.run_tool(
                "build", "--source", str(ROOT / "skills/context-strict"),
                "--destination", str(destination), "--source-revision", "git:test",
            )
            manifest_path = destination / "skill-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["skill_version"] = "9.9.9"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = self.run_tool("verify", "--package", str(destination), expected=1)
            self.assertIn("PACKAGE_IDENTITY_MISMATCH", report["codes"])

    def test_check_source_verifies_documented_paths_and_python_exports(self) -> None:
        report = self.run_tool("check-source", "--source", str(ROOT / "skills/context-strict"))
        self.assertEqual(report["status"], "pass")
        self.assertGreaterEqual(report["stats"]["documented_paths_checked"], 3)
        self.assertGreaterEqual(report["stats"]["python_exports_checked"], 8)

    def test_check_source_rejects_documented_api_without_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "context-strict"
            shutil.copytree(ROOT / "skills/context-strict", copied)
            skill = copied / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\n```python\ncontext.missing_documented_api(\"TASK-001\")\n```\n",
                encoding="utf-8",
            )
            report = self.run_tool("check-source", "--source", str(copied), expected=1)
            self.assertIn("DOCUMENTED_API_MISSING", report["codes"])

    def test_check_source_rejects_missing_required_package_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "context-strict"
            shutil.copytree(ROOT / "skills/context-strict", copied)
            (copied / "tests/test_truth_sources.py").unlink()
            report = self.run_tool("check-source", "--source", str(copied), expected=1)
            self.assertIn("PACKAGE_REQUIRED_PATH_MISSING", report["codes"])

    def test_verify_checks_external_manifest_hash_and_source_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "context-lite"
            built = self.run_tool(
                "build", "--source", str(ROOT / "skills/context-lite"),
                "--destination", str(destination), "--source-revision", "git:expected",
            )
            wrong_hash = "0" * 64 if built["manifest_sha256"] != "0" * 64 else "1" * 64
            report = self.run_tool(
                "verify", "--package", str(destination),
                "--expected-manifest-sha256", wrong_hash,
                "--expected-source-revision", "git:wrong",
                expected=1,
            )
            self.assertIn("PACKAGE_MANIFEST_HASH_MISMATCH", report["codes"])
            self.assertIn("PACKAGE_SOURCE_REVISION_MISMATCH", report["codes"])

    def test_lite_package_build_includes_validator_and_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "context-lite"
            self.run_tool(
                "build", "--source", str(ROOT / "skills/context-lite"),
                "--destination", str(destination), "--source-revision", "git:test",
            )
            manifest = json.loads((destination / "skill-manifest.json").read_text())
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertIn("assets/NOW.template.md", paths)
            self.assertIn("scripts/context_lite.py", paths)
            self.assertEqual(self.run_tool("verify", "--package", str(destination))["status"], "pass")


if __name__ == "__main__":
    unittest.main()
