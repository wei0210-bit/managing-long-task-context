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

    def test_review_promotes_a_candidate_only_after_real_structured_evidence_check(self) -> None:
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

    def test_approve_rechecks_real_evidence_and_binds_the_validated_record_digest(self) -> None:
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

    def test_callback_errors_and_mutation_do_not_change_a_candidate(self) -> None:
        store = context.bind_experience(self.workspace, self.store_root)
        refs = self._validation_refs()
        for bad in (None, True, {}, {"status": "other", "codes": []}):
            with self.subTest(bad=bad):
                result = store.review("reviewable-001", 1, refs, evidence_checker=lambda record, incoming, value=bad: value)
                self.assertEqual(result, {"status": "unknown", "codes": ["CALLBACK_INVALID_RESULT"], "data": None})
                self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "candidate")
        def raises(record, incoming):
            raise RuntimeError("do not leak this")
        self.assertEqual(store.review("reviewable-001", 1, refs, evidence_checker=raises)["codes"], ["CALLBACK_ERROR"])
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "candidate")
        def mutate(record, incoming):
            checked = self._evidence_checker(record, incoming)
            record["claim"] = "attacker mutation"
            incoming["cross"]["checker_id"] = "attacker mutation"
            return checked
        result = store.review("reviewable-001", 1, refs, evidence_checker=mutate)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(store.get("reviewable-001", 1)["data"]["provenance"]["validation_refs"], refs)

    def test_callback_version_or_source_change_blocks_old_approval_without_deadlock(self) -> None:
        store = self._validated_store()
        approval_ref = self._approval_ref(store)
        def changes_grant(record, ref):
            Path(ref["source_ref"]["path"]).write_text("changed after checker read\n", encoding="utf-8")
            return {"status": "pass", "codes": []}
        result = store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=changes_grant)
        self.assertEqual((result["status"], result["codes"]), ("fail", ["SOURCE_DIGEST_MISMATCH"]))
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "validated")
        dispute_material = self.workspace / "dispute.txt"
        dispute_material.write_text("contradictory independent evidence\n", encoding="utf-8")
        refs = self._validation_refs()
        store2 = context.bind_experience(self.workspace, self.store_root)
        # This separate candidate is needed because the first version is already validated.
        candidate = self.workspace / "candidate-2.json"
        raw = json.loads((self.workspace / "candidate.json").read_text(encoding="utf-8"))
        raw.update({"revision": 2, "supersedes": {"experience_id": "reviewable-001", "revision": 1}})
        candidate.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(self._cli("record", "--input", str(candidate))[0], 0)
        old = store2.get("reviewable-001", 1)
        self.assertEqual((old["status"], old["codes"], old["data"]["latest_revision"], old["data"]["status"]), ("unknown", ["RULE_VERSION_SUPERSEDED"], 2, "validated"))
        def disputes_during_callback(record, incoming):
            self.assertEqual(store2.dispute("reviewable-001", 2, "new contradictory material", self._source_ref(dispute_material))["status"], "pass")
            return {"status": "pass", "codes": []}
        changed = store2.review("reviewable-001", 2, refs, evidence_checker=disputes_during_callback)
        self.assertEqual(changed, {"status": "unknown", "codes": ["INPUT_CHANGED"], "data": None})
        self.assertEqual(store2.get("reviewable-001", 2)["data"]["status"], "disputed")

    def test_dispute_and_revoke_are_terminal_and_historical(self) -> None:
        store = self._validated_store()
        approval_ref = self._approval_ref(store)
        self.assertEqual(store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["status"], "pass")
        revocation = self._approval_ref(store)
        result = store.revoke("reviewable-001", 1, "approval withdrawn", revocation, approval_checker=lambda record, ref: {"status": "pass", "codes": []})
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "revoked")
        self.assertEqual(store.approve("reviewable-001", 1, revocation, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["codes"], ["INVALID_TRANSITION"])

    def test_approval_and_revocation_callback_boundaries_preserve_state_on_failure(self) -> None:
        store = self._validated_store()
        approval_ref = self._approval_ref(store)
        invalid = store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": [], "codes": []})
        self.assertEqual(invalid["codes"], ["CALLBACK_INVALID_RESULT"])
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "validated")
        timeout = store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(timeout["codes"], ["CALLBACK_TIMEOUT"])
        self.assertEqual(store.approve("reviewable-001", 1, approval_ref, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["status"], "pass")
        revocation = self._approval_ref(store)
        invalid_revoke = store.revoke("reviewable-001", 1, "withdrawn", revocation, approval_checker=lambda record, ref: True)
        self.assertEqual(invalid_revoke["codes"], ["CALLBACK_INVALID_RESULT"])
        self.assertEqual(store.get("reviewable-001", 1)["data"]["status"], "approved")
        self.assertEqual(store.revoke("reviewable-001", 1, "withdrawn", revocation, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["status"], "pass")

    def test_query_expiry_semantic_rejection_and_binding_negatives(self) -> None:
        store = context.bind_experience(self.workspace, self.store_root)
        refs = self._validation_refs()
        self.assertEqual(store.review("reviewable-001", 1, refs, evidence_checker=None)["codes"], ["CHECKER_REQUIRED"])
        expired = self._validation_refs()
        for group in expired.values():
            group["validated_at"] = "1999-01-01T00:00:00Z"
            group["expires_at"] = "2000-01-01T00:00:00Z"
        self.assertEqual(store.review("reviewable-001", 1, expired, evidence_checker=self._evidence_checker)["codes"], ["VALIDATION_EXPIRED"])
        (self.workspace / "cross.txt").write_text("semantic lie\n", encoding="utf-8")
        altered = self._validation_refs()
        (self.workspace / "cross.txt").write_text("semantic lie\n", encoding="utf-8")
        altered["cross"]["source_refs"] = [self._source_ref(self.workspace / "cross.txt")]
        self.assertEqual(store.review("reviewable-001", 1, altered, evidence_checker=self._evidence_checker)["codes"], ["HOST_EVIDENCE_REJECTED"])
        valid = self._validation_refs()
        self.assertEqual(store.review("reviewable-001", 1, valid, evidence_checker=self._evidence_checker)["status"], "pass")
        bad = self._approval_ref(store)
        bad["record_digest"] = "0" * 64
        self.assertEqual(store.approve("reviewable-001", 1, bad, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["codes"], ["INVALID_INPUT"])
        good = self._approval_ref(store)
        self.assertEqual(store.approve("reviewable-001", 1, good, evidence_checker=self._evidence_checker, approval_checker=lambda record, ref: {"status": "pass", "codes": []})["status"], "pass")
        code, queried = self._cli("query", "--tags", "verification")
        self.assertEqual((code, queried["data"]["items"][0]["status"]), (0, "approved"))
        challenge = self.workspace / "challenge.txt"
        challenge.write_text("contradiction\n", encoding="utf-8")
        self.assertEqual(store.dispute("reviewable-001", 1, "contradicted", self._source_ref(challenge))["status"], "pass")
        self.assertEqual(self._cli("query", "--tags", "verification")[1]["data"]["items"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
