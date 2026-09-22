from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import managing_long_task_context as context
from managing_long_task_context.evidence import contract_compat_report, evaluate_evidence


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
EXAMPLE_CONTRACT = ROOT / "assets" / "task-contract.example.json"


def _load_skill_package():
    spec = importlib.util.spec_from_file_location(
        "skill_package", ROOT / "scripts" / "skill_package.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class PublishGuardsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.base = self.root / ".prime" / "context"
        self.criterion = {
            "required_scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            "max_evidence_age_seconds": 3600,
        }

    def _contract(self, *, workspace_root: object | None = ..., evidence: list[str] | None = None) -> dict:
        value: dict[str, object] = {
            "schema": 1,
            "task_id": "H2-TASK",
            "version": 1,
            "issued_by": "publisher",
            "issued_at": "2026-09-22T09:00:00Z",
            "authorized_approvers": [],
            "objective": "Exercise publish guards",
            "scope": ["guards"],
            "out_of_scope": [],
            "constraints": [],
            "acceptance_criteria": [
                {
                    "id": "AC-01",
                    "criterion": "Compat and evidence kinds",
                    "required_evidence": evidence or ["file"],
                }
            ],
        }
        if workspace_root is not ...:
            value["workspace_root"] = workspace_root
        return value

    def _evidence(self, kind: str, locator: str, **extra: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "evidence_id": f"EV-{kind}",
            "kind": kind,
            "locator": locator,
            "generated_at": "2026-09-22T09:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }
        payload.update(extra)
        return payload

    def test_compat_report_passes_existing_absolute_dir_and_file_kind(self) -> None:
        report = contract_compat_report(
            self._contract(workspace_root=str(self.workspace), evidence=["file"])
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["warnings"], [])

    def test_compat_report_warns_invalid_workspaces_without_raising(self) -> None:
        regular = self.workspace / "plain.txt"
        regular.write_text("x", encoding="utf-8")
        missing = self.workspace / "missing-dir"
        cases = {
            "missing": self._contract(evidence=["file"]),
            "relative": self._contract(workspace_root="workspace", evidence=["file"]),
            "nonexistent": self._contract(workspace_root=str(missing), evidence=["file"]),
            "file": self._contract(workspace_root=str(regular), evidence=["file"]),
            "number": self._contract(workspace_root=7, evidence=["file"]),
        }
        for label, contract in cases.items():
            with self.subTest(label=label):
                report = contract_compat_report(contract)
                self.assertGreaterEqual(len(report["warnings"]), 1)
                self.assertEqual(report["status"], "warn")

    def test_invalid_workspaces_still_publish(self) -> None:
        regular = self.workspace / "plain.txt"
        regular.write_text("x", encoding="utf-8")
        missing = self.workspace / "missing-dir"
        cases = {
            "missing": self._contract(evidence=["file"]),
            "relative": self._contract(workspace_root="workspace", evidence=["file"]),
            "nonexistent": self._contract(workspace_root=str(missing), evidence=["file"]),
            "file": self._contract(workspace_root=str(regular), evidence=["file"]),
            "number": self._contract(workspace_root=7, evidence=["file"]),
        }
        for index, (label, contract) in enumerate(cases.items(), start=1):
            with self.subTest(label=label):
                contract["task_id"] = f"H2-TASK-{index}"
                published = context.publish_contract(
                    contract, confirmed_by="publisher", base_dir=self.base
                )
                self.assertEqual(published["task_id"], contract["task_id"])
                self.assertIn("seal", published)

    def test_example_contract_warns_only_for_missing_example_workspace(self) -> None:
        example = json.loads(EXAMPLE_CONTRACT.read_text(encoding="utf-8"))
        report = contract_compat_report(example)
        self.assertIn(report["status"], {"pass", "warn"})
        if report["status"] == "warn":
            self.assertTrue(
                all("workspace_root" in item for item in report["warnings"]),
                report["warnings"],
            )

    def test_unmapped_free_text_evidence_type_warns_without_raising(self) -> None:
        report = contract_compat_report(
            self._contract(workspace_root=str(self.workspace), evidence=["合并提交号"])
        )
        self.assertGreaterEqual(len(report["warnings"]), 1)
        self.assertEqual(report["status"], "warn")

    def test_command_output_pass_and_empty_fail(self) -> None:
        contract = {"workspace_root": str(self.workspace), "evidence_roots": []}
        (self.workspace / "cmd.txt").write_text("ok: tests passed\n", encoding="utf-8")
        passed = evaluate_evidence(
            self._evidence(
                "command-output",
                "cmd.txt",
                must_contain=["tests passed"],
                must_not_contain=["FAILED"],
            ),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(passed["status"], "pass")
        self.assertEqual(passed["checks"]["claim"]["status"], "pass")

        (self.workspace / "empty.txt").write_bytes(b"")
        empty = evaluate_evidence(
            self._evidence("command-output", "empty.txt"),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(empty["status"], "fail")
        self.assertIn("EMPTY_COMMAND_OUTPUT", empty["checks"]["integrity_and_freshness"]["codes"])

    def test_screenshot_magic_pass_and_fail(self) -> None:
        contract = {"workspace_root": str(self.workspace), "evidence_roots": []}
        png = b"\x89PNG\r\n\x1a\n" + b"payload"
        jpeg = b"\xff\xd8\xff" + b"jpeg-payload"
        (self.workspace / "ok.png").write_bytes(png)
        (self.workspace / "ok.jpg").write_bytes(jpeg)
        (self.workspace / "bad.png").write_bytes(b"not-a-png")
        png_result = evaluate_evidence(
            self._evidence("screenshot", "ok.png", artifact_digest=_sha256(png)),
            self.criterion,
            contract,
            now=NOW,
        )
        jpeg_result = evaluate_evidence(
            self._evidence("screenshot", "ok.jpg"),
            self.criterion,
            contract,
            now=NOW,
        )
        bad = evaluate_evidence(
            self._evidence("screenshot", "bad.png"),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(png_result["checks"]["claim"]["status"], "pass")
        self.assertEqual(jpeg_result["checks"]["claim"]["status"], "pass")
        self.assertEqual(bad["status"], "fail")
        self.assertIn("INVALID_SCREENSHOT_MAGIC", bad["checks"]["integrity_and_freshness"]["codes"])

    def test_manifest_digest_mismatch_and_outside_root_fail(self) -> None:
        contract = {"workspace_root": str(self.workspace), "evidence_roots": []}
        artifact = self.workspace / "artifact.txt"
        artifact.write_bytes(b"manifest-body\n")
        digest = hashlib.sha256(b"manifest-body\n").hexdigest()
        (self.workspace / "good.sha256").write_text(
            f"{digest}  artifact.txt\n", encoding="utf-8"
        )
        good = evaluate_evidence(
            self._evidence("evidence-manifest", "good.sha256"),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(good["checks"]["claim"]["status"], "pass")

        (self.workspace / "bad.sha256").write_text(
            f"{'0' * 64}  artifact.txt\n", encoding="utf-8"
        )
        mismatch = evaluate_evidence(
            self._evidence("evidence-manifest", "bad.sha256"),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(mismatch["status"], "fail")
        self.assertIn("DIGEST_MISMATCH", mismatch["checks"]["integrity_and_freshness"]["codes"])

        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (self.workspace / "escape.sha256").write_text(
            f"{hashlib.sha256(b'secret').hexdigest()}  ../outside.txt\n",
            encoding="utf-8",
        )
        escaped = evaluate_evidence(
            self._evidence("evidence-manifest", "escape.sha256"),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(escaped["status"], "fail")
        self.assertIn("OUTSIDE_ALLOWED_ROOT", escaped["checks"]["integrity_and_freshness"]["codes"])

        locator_escape = evaluate_evidence(
            self._evidence("command-output", str(outside)),
            self.criterion,
            contract,
            now=NOW,
        )
        self.assertEqual(locator_escape["status"], "fail")
        self.assertEqual(
            locator_escape["checks"]["resolve"],
            {"status": "fail", "codes": ["OUTSIDE_ALLOWED_ROOT"]},
        )

    def test_file_kind_without_verifier_is_not_pass(self) -> None:
        (self.workspace / "artifact.txt").write_bytes(b"strict evidence\n")
        result = evaluate_evidence(
            self._evidence(
                "file",
                "artifact.txt",
                artifact_digest=_sha256(b"strict evidence\n"),
            ),
            self.criterion,
            {"workspace_root": str(self.workspace), "evidence_roots": []},
            now=NOW,
        )
        self.assertNotEqual(result["checks"]["claim"]["status"], "pass")
        self.assertEqual(result["checks"]["claim"]["codes"], ["CLAIM_NOT_VERIFIED"])

    def test_check_source_rejects_duplicate_copy_and_repo_still_passes(self) -> None:
        skill_package = _load_skill_package()
        repo_report = skill_package.check_source(ROOT)
        self.assertEqual(repo_report["status"], "pass")
        self.assertNotIn("PACKAGE_DUPLICATE_COPY", repo_report["codes"])

        copied = self.root / "context-strict"
        shutil.copytree(ROOT / "skills" / "context-strict", copied)
        (copied / "src" / "experience 2.py").write_text("# duplicate copy\n", encoding="utf-8")
        failed = skill_package.check_source(copied)
        self.assertEqual(failed["status"], "fail")
        self.assertIn("PACKAGE_DUPLICATE_COPY", failed["codes"])


if __name__ == "__main__":
    unittest.main()
