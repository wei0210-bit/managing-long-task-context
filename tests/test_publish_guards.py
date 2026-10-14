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







if __name__ == "__main__":
    unittest.main()
