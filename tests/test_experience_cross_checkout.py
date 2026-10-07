"""Portable experience lifecycle and real two-checkout publication tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context
from managing_long_task_context import project_store


def paths(value):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value["path"]
        else:
            for item in value.values():
                yield from paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from paths(item)


class PortableLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "A"
        self.workspace.mkdir()
        self.git(self.workspace, "init", "-q", "-b", "main")
        self.configure(self.workspace)
        (self.workspace / ".gitignore").write_text(".prime/context/\n.prime/experience/\n")
        self.git(self.workspace, "add", ".gitignore")
        self.git(self.workspace, "commit", "-q", "-m", "root")
        self.store_root = self.workspace / ".prime/experience"
        self.cli("init")
        self.candidate()
        self.store = context.bind_experience(self.workspace, self.store_root)

    def git(self, workspace, *args):
        result = subprocess.run(["git", "-C", str(workspace), *args], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def configure(self, workspace):
        self.git(workspace, "config", "user.email", "experience@example.invalid")
        self.git(workspace, "config", "user.name", "Experience Test")
        self.git(workspace, "config", "commit.gpgsign", "false")

    def cli(self, command, *args, workspace=None):
        workspace = workspace or self.workspace
        result = subprocess.run([sys.executable, str(ROOT / "scripts/context_experience.py"), command,
                                 "--workspace", str(workspace), *args], capture_output=True, text=True)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)

    def source(self, name):
        file = self.workspace / name
        file.write_text("Verified local material: " + name + "\n")
        return {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}

    def candidate(self, experience_id="portable"):
        raw = {"schema": 1, "experience_id": experience_id, "revision": 1, "claim": "Check original evidence.",
               "tags": ["verification"], "applicability": ["original available"], "exclusions": ["none-known"],
               "source_refs": [self.source("original.txt")], "supersedes": None}
        candidate = self.workspace / "candidate.json"
        candidate.write_text(json.dumps(raw))
        self.cli("record", "--input", str(candidate))

    def validation(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        refs = {}
        for name in ("cross", "counterexample", "effectiveness"):
            refs[name] = {"source_refs": [self.source(name + ".txt")], "checker_id": "host", "checker_version": "1",
                          "validated_at": now.isoformat().replace("+00:00", "Z"),
                          "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")}
        refs["cross"]["independence_basis"] = "separate independent check"
        for field in ("original_pass_ref", "mutated_fail_ref", "restored_pass_ref", "mutation_hit_ref"):
            refs["counterexample"][field] = self.source(field + ".txt")
        for field in ("representative_run_ref", "non_applicable_run_ref"):
            refs["effectiveness"][field] = self.source(field + ".txt")
        return refs

    def approval(self, experience_id="portable"):
        data = self.store.get(experience_id, 1)["data"]
        return {key: data[key] for key in ("workspace_id", "experience_id", "revision", "record_digest")} | {
            "source_ref": self.source("approval.txt")}

    def allow(self, *args):
        return {"status": "pass", "codes": []}

    def assert_absolute(self, value, workspace=None):
        observed = list(paths(value))
        self.assertTrue(observed)
        for path in observed:
            self.assertTrue(Path(path).is_absolute(), path)
            self.assertTrue(Path(path).is_relative_to(workspace or self.workspace), path)
            self.assertTrue(Path(path).is_file(), path)

    def test_two_forms_callbacks_and_complete_lifecycle_provenance(self):
        self.assertEqual(json.loads((self.store_root / "binding.json").read_text())["schema"], 2)
        refs = self.validation()
        relative = copy.deepcopy(refs)
        def relativize(value):
            if isinstance(value, dict):
                if set(value) == {"path", "sha256"}:
                    value["path"] = str(Path(value["path"]).relative_to(self.workspace))
                else:
                    for item in value.values():
                        relativize(item)
            elif isinstance(value, list):
                for item in value:
                    relativize(item)
        relativize(relative)
        self.assertEqual(self.store.review("portable", 1, relative, evidence_checker=self.allow)["codes"], ["INVALID_INPUT"])
        callbacks = []
        def observe(*args):
            callbacks.append(copy.deepcopy(args))
            return self.allow()
        reviewed = self.store.review("portable", 1, refs, evidence_checker=observe)
        self.assertEqual(reviewed["status"], "pass", reviewed)
        approval = self.approval()
        relative_approval = copy.deepcopy(approval)
        relativize(relative_approval)
        self.assertEqual(self.store.approve("portable", 1, relative_approval, evidence_checker=observe, approval_checker=observe)["codes"], ["INVALID_INPUT"])
        approved = self.store.approve("portable", 1, approval, evidence_checker=observe, approval_checker=observe)
        self.assertEqual(approved["status"], "pass", approved)
        self.assertEqual(len(callbacks), 3)
        for args in callbacks:
            self.assert_absolute(args[0])
            self.assert_absolute(args[1])
        self.assert_absolute(approved["data"])
        self.assertEqual(approved["data"]["provenance"]["approval_ref"], approval)
        stored = json.loads((self.store_root / "records.json").read_text())
        self.assertEqual(stored["schema"], 2)
        self.assertTrue(all(not Path(path).is_absolute() for path in paths(stored)))
        stable = stored["records"][0]
        expected_digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(approved["data"]["record_digest"], expected_digest)
        revocation = self.approval()
        relative_revocation = copy.deepcopy(revocation)
        relativize(relative_revocation)
        self.assertEqual(self.store.revoke("portable", 1, "withdrawn", relative_revocation, approval_checker=observe)["codes"], ["INVALID_INPUT"])
        revoked = self.store.revoke("portable", 1, "withdrawn", revocation, approval_checker=observe)
        self.assertEqual(revoked["status"], "pass", revoked)
        self.assert_absolute(callbacks[-1][0])
        self.assert_absolute(revoked["data"])
        self.candidate("challenge")
        source = self.source("dispute.txt")
        self.assertEqual(self.store.dispute("challenge", 1, "contradicted", {**source, "path": "dispute.txt"})["codes"], ["SOURCE_UNSAFE_PATH"])
        disputed = self.store.dispute("challenge", 1, "contradicted", source)
        self.assertEqual(disputed["status"], "pass", disputed)
        self.assert_absolute(disputed["data"])
        self.assertTrue(all(not Path(path).is_absolute() for path in paths(json.loads((self.store_root / "records.json").read_text()))))


    def publish_and_receive(self, *, receiver_has_library=False):
        remote = self.root / "origin.git"
        self.git(self.workspace, "init", "-q", "--bare", str(remote))
        self.git(self.workspace, "remote", "add", "origin", str(remote))
        self.git(self.workspace, "push", "-q", "-u", "origin", "main")
        receiver = self.root / "B"
        self.git(self.workspace, "clone", "-q", str(remote), str(receiver))
        # Explicit branch avoids the global default branch of the bare repository.
        self.git(receiver, "checkout", "-q", "main")
        self.configure(receiver)
        old_binding = None
        if receiver_has_library:
            self.cli("init", workspace=receiver)
            old_binding = (receiver / ".prime/experience/binding.json").read_bytes()
        contract = {"schema": 1, "task_id": "PORTABLE", "version": 1, "issued_by": "test",
                    "issued_at": "2026-10-06T00:00:00Z", "authorized_approvers": [], "workspace_root": ".",
                    "objective": "Share portable evidence", "scope": ["temporary project"],
                    "out_of_scope": [], "constraints": [], "acceptance_criteria": [
                        {"id": "AC-01", "criterion": "read shared evidence", "required_evidence_types": ["test-report"]}]}
        context.publish_contract(contract, confirmed_by="test", base_dir=self.workspace / ".prime/context")
        self.git(self.workspace, "add", "--", *[path.name for path in self.workspace.glob("*.txt")])
        self.git(self.workspace, "commit", "-q", "-m", "evidence originals")
        published = project_store.publish_context("PORTABLE", self.workspace)
        self.assertEqual(published["status"], "ok", published)
        self.git(receiver, "fetch", "-q", "origin")
        self.git(receiver, "merge", "-q", "--ff-only", "origin/main")
        self.git(receiver, "config", "core.hooksPath", ".githooks")
        self.assertEqual(project_store.align_context("PORTABLE", receiver)["status"], "ok")
        return receiver, old_binding

    def test_published_approval_survives_checkout_and_shared_root_fork(self):
        reviewed = self.store.review("portable", 1, self.validation(), evidence_checker=self.allow)
        self.assertEqual(reviewed["status"], "pass", reviewed)
        approved = self.store.approve("portable", 1, self.approval(), evidence_checker=self.allow, approval_checker=self.allow)
        self.assertEqual(approved["status"], "pass", approved)
        receiver, _ = self.publish_and_receive()
        bound = context.bind_experience(receiver, receiver / ".prime/experience")
        received = bound.get("portable", 1)
        self.assertEqual(received["status"], "pass", received)
        self.assertEqual(received["data"]["status"], "approved")
        self.assertEqual(received["data"]["record_digest"], approved["data"]["record_digest"])
        self.assert_absolute(received["data"], receiver)
        queried = self.cli("query", "--tags", "verification", "--max-chars", "10000", workspace=receiver)
        self.assert_absolute(queried["data"], receiver)
        self.git(receiver, "checkout", "-q", "-b", "fork")
        self.git(receiver, "commit", "-q", "--allow-empty", "-m", "fork changes")
        self.git(receiver, "remote", "remove", "origin")
        self.assertEqual(bound.get("portable", 1)["status"], "pass")
        (receiver / "original.txt").write_text("source drift")
        self.assertEqual(bound.get("portable", 1)["codes"], ["SOURCE_DIGEST_MISMATCH"])
        (receiver / "original.txt").write_bytes((self.workspace / "original.txt").read_bytes())
        (receiver / "original_pass_ref.txt").write_text("validation drift")
        self.assertEqual(bound.get("portable", 1)["codes"], ["SOURCE_DIGEST_MISMATCH"])

    def test_preservation_merge_silently_overwrites_receiver_library(self):
        receiver, old_binding = self.publish_and_receive(receiver_has_library=True)
        new_binding = (receiver / ".prime/experience/binding.json").read_bytes()
        self.assertNotEqual(new_binding, old_binding)
        self.assertEqual(new_binding, (self.store_root / "binding.json").read_bytes())
        self.assertEqual((receiver / ".prime/experience/records.json").read_bytes(),
                         (self.store_root / "records.json").read_bytes())


    def test_all_validation_input_fields_and_stored_events_enforce_their_form(self):
        refs = self.validation()
        targets = [(group, "source_refs", 0) for group in refs]
        targets += [("counterexample", field, None) for field in ("original_pass_ref", "mutated_fail_ref", "restored_pass_ref", "mutation_hit_ref")]
        targets += [("effectiveness", field, None) for field in ("representative_run_ref", "non_applicable_run_ref")]
        for group, field, index in targets:
            with self.subTest(group=group, field=field):
                changed = copy.deepcopy(refs)
                ref = changed[group][field] if index is None else changed[group][field][index]
                ref["path"] = str(Path(ref["path"]).relative_to(self.workspace))
                rejected = self.store.review("portable", 1, changed, evidence_checker=self.allow)
                self.assertEqual(rejected["codes"], ["INVALID_INPUT"])
        self.assertEqual(self.store.review("portable", 1, refs, evidence_checker=self.allow)["status"], "pass")
        baseline = json.loads((self.store_root / "records.json").read_text())
        for group, field, index in targets:
            with self.subTest(stored_group=group, stored_field=field):
                changed = copy.deepcopy(baseline)
                ref = changed["records"][0]["lifecycle"][0]["validation_refs"][group][field]
                if index is not None:
                    ref = ref[index]
                ref["path"] = str(self.workspace / ref["path"])
                (self.store_root / "records.json").write_text(json.dumps(changed))
                self.assertEqual(self.store.get("portable", 1)["codes"], ["STORE_CORRUPT"])
        (self.store_root / "records.json").write_text(json.dumps(baseline))
        self.assertEqual(self.store.approve("portable", 1, self.approval(), evidence_checker=self.allow, approval_checker=self.allow)["status"], "pass")
        baseline = json.loads((self.store_root / "records.json").read_text())
        baseline["records"][0]["lifecycle"][-1]["approval_ref"]["source_ref"]["path"] = str(self.workspace / "approval.txt")
        (self.store_root / "records.json").write_text(json.dumps(baseline))
        self.assertEqual(self.store.get("portable", 1)["codes"], ["STORE_CORRUPT"])

    def test_schema2_callback_races_reverify_originals_without_deadlocking(self):
        refs = self.validation()
        def mutate_original(record, incoming):
            (self.workspace / "original.txt").write_text("changed during callback")
            return self.allow()
        result = self.store.review("portable", 1, refs, evidence_checker=mutate_original)
        self.assertEqual(result["codes"], ["SOURCE_DIGEST_MISMATCH"])
        self.source("original.txt")
        def dispute_in_callback(record, incoming):
            self.assertEqual(self.store.dispute("portable", 1, "race", self.source("race.txt"))["status"], "pass")
            return self.allow()
        result = self.store.review("portable", 1, refs, evidence_checker=dispute_in_callback)
        self.assertEqual(result["codes"], ["INPUT_CHANGED"])
        self.assertEqual(self.store.get("portable", 1)["data"]["status"], "disputed")

    def test_schema2_multiple_root_commits_are_sorted_and_allow_shared_history(self):
        other = self.root / "other"
        other.mkdir()
        self.git(other, "init", "-q", "-b", "main")
        self.configure(other)
        self.git(other, "commit", "-q", "--allow-empty", "-m", "unrelated root")
        other_root = self.git(other, "rev-parse", "HEAD")
        original_root = self.git(self.workspace, "rev-list", "--max-parents=0", "HEAD")
        self.git(self.workspace, "fetch", "-q", str(other), "main")
        self.git(self.workspace, "merge", "-q", "--allow-unrelated-histories", "--no-edit", "FETCH_HEAD")
        self.assertEqual(self.store.get("portable", 1)["status"], "pass")
        fresh = self.workspace / "multi-root-store"
        self.cli("init", "--store", str(fresh))
        binding = json.loads((fresh / "binding.json").read_text())
        self.assertEqual(binding["project_roots"], sorted([original_root, other_root]))


if __name__ == "__main__":
    unittest.main()
