"""Public Strict review lifecycle tests for verified experiences."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context


class ExperienceReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.store_root = self.workspace / ".context-experience"
        self.original = self.workspace / "original.txt"
        self.original.write_text("The local source supports this candidate.\n", encoding="utf-8")
        self._cli("init")
        candidate = self.workspace / "candidate.json"
        candidate.write_text(json.dumps({
            "schema": 1,
            "experience_id": "reviewable-001",
            "revision": 1,
            "claim": "Validate evidence before making a recommendation.",
            "tags": ["verification"],
            "applicability": ["A local original is available."],
            "exclusions": ["none-known"],
            "source_refs": [self._source_ref(self.original)],
            "supersedes": None,
        }), encoding="utf-8")
        self.assertEqual(self._cli("record", "--input", str(candidate))[0], 0)

    def _cli(self, command: str, *arguments: str) -> tuple[int, dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "context_experience.py"), command,
             "--workspace", str(self.workspace), "--store", str(self.store_root), *arguments],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def _source_ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _validation_refs(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        validated = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        materials = {
            "cross": "independent reviewer reproduced the claimed safety outcome\n",
            "counterexample": "counterexample protocol and observed outcomes\n",
            "effectiveness": "representative run completed and non-applicable run was rejected\n",
            "original-pass": "original candidate passes the host checker\n",
            "mutated-fail": "mutated candidate fails the host checker\n",
            "restored-pass": "restored candidate passes the host checker again\n",
            "mutation-hit": "the mutation exercised the intended checker condition\n",
            "representative-run": "representative applicable run avoided the documented failure\n",
            "non-applicable-run": "non-applicable run did not claim the experience applies\n",
        }
        paths: dict[str, Path] = {}
        for name, contents in materials.items():
            material = self.workspace / f"{name}.txt"
            material.write_text(contents, encoding="utf-8")
            paths[name] = material
        refs: dict[str, object] = {}
        for name in ("cross", "counterexample", "effectiveness"):
            refs[name] = {
                "source_refs": [self._source_ref(paths[name])],
                "checker_id": "host-review",
                "checker_version": "1",
                "validated_at": validated,
                "expires_at": expires,
            }
        refs["cross"]["independence_basis"] = "Independent reviewer checked a separate original."
        counterexample = refs["counterexample"]
        for field, name in (("original_pass_ref", "original-pass"), ("mutated_fail_ref", "mutated-fail"), ("restored_pass_ref", "restored-pass"), ("mutation_hit_ref", "mutation-hit")):
            counterexample[field] = self._source_ref(paths[name])
        effectiveness = refs["effectiveness"]
        for field, name in (("representative_run_ref", "representative-run"), ("non_applicable_run_ref", "non-applicable-run")):
            effectiveness[field] = self._source_ref(paths[name])
        return refs

    def _evidence_checker(self, record: dict[str, object], refs: dict[str, object]) -> dict[str, object]:
        if record.get("claim") != "Validate evidence before making a recommendation.":
            return {"status": "fail", "codes": ["HOST_EVIDENCE_REJECTED"]}
        expected = {
            "cross.txt": "independent reviewer reproduced the claimed safety outcome\n",
            "counterexample.txt": "counterexample protocol and observed outcomes\n",
            "effectiveness.txt": "representative run completed and non-applicable run was rejected\n",
            "original-pass.txt": "original candidate passes the host checker\n",
            "mutated-fail.txt": "mutated candidate fails the host checker\n",
            "restored-pass.txt": "restored candidate passes the host checker again\n",
            "mutation-hit.txt": "the mutation exercised the intended checker condition\n",
            "representative-run.txt": "representative applicable run avoided the documented failure\n",
            "non-applicable-run.txt": "non-applicable run did not claim the experience applies\n",
        }
        observed = {path.name: path.read_text(encoding="utf-8") for path in self.workspace.glob("*.txt") if path.name in expected}
        return {"status": "pass", "codes": []} if observed == expected else {"status": "fail", "codes": ["HOST_EVIDENCE_REJECTED"]}

    def _validated_store(self):
        store = context.bind_experience(self.workspace, self.store_root)
        result = store.review("reviewable-001", 1, self._validation_refs(), evidence_checker=self._evidence_checker)
        self.assertEqual(result["status"], "pass", result)
        return store

    def _approval_ref(self, store):
        grant = self.workspace / "approval-grant.txt"
        grant.write_text("review board approved reviewable-001 revision 1\n", encoding="utf-8")
        readback = store.get("reviewable-001", 1)
        self.assertEqual(readback["status"], "pass", readback)
        data = readback["data"]
        return {
            "workspace_id": data["workspace_id"],
            "experience_id": "reviewable-001",
            "revision": 1,
            "record_digest": data["record_digest"],
            "source_ref": self._source_ref(grant),
        }

    def test_review_records_declared_validation_with_original_references(self) -> None:
        store = context.bind_experience(self.workspace, self.store_root)
        validation_refs = self._validation_refs()

        result = store.review(
            "reviewable-001", 1, validation_refs,
            evidence_checker=self._evidence_checker,
        )

        self.assertEqual(result["status"], "pass", result)
        readback = store.get("reviewable-001", 1)
        self.assertEqual(readback["status"], "pass", readback)
        self.assertEqual(readback["data"]["status"], "validated")
        self.assertEqual(readback["data"]["provenance"]["validation_refs"], validation_refs)

    def test_approve_records_original_reference_and_validated_record_digest(self) -> None:
        store = self._validated_store()
        approval_ref = self._approval_ref(store)

        result = store.approve(
            "reviewable-001", 1, approval_ref,
            evidence_checker=self._evidence_checker,
            approval_checker=lambda record, ref: {"status": "pass", "codes": []}
            if record["record_digest"] == ref["record_digest"]
            and Path(ref["source_ref"]["path"]).read_text(encoding="utf-8") == "review board approved reviewable-001 revision 1\n"
            else {"status": "fail", "codes": ["HOST_APPROVAL_REJECTED"]},
        )

        self.assertEqual(result["status"], "pass", result)
        readback = store.get("reviewable-001", 1)
        self.assertEqual(readback["data"]["status"], "approved")
        self.assertEqual(readback["data"]["provenance"]["approval_ref"], approval_ref)



    def test_dispute_and_revoke_are_terminal_and_historical(self) -> None:
        store = self._validated_store()
        approval_ref = self._approval_ref(store)
        self.assertEqual(store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["status"], "pass")
        revocation = self._approval_ref(store)
        result = store.revoke("reviewable-001", 1, "approval withdrawn", revocation, approval_checker=lambda record, ref: {"status": "pass", "codes": []})
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "revoked")
        self.assertEqual(store.approve("reviewable-001", 1, revocation, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["codes"], ["INVALID_TRANSITION"])




if __name__ == "__main__":
    unittest.main(verbosity=2)
