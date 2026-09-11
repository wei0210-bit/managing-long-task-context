"""Public CLI tests for opt-in Context Lite experience recovery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "skill_package.py"
LITE_SOURCE = ROOT / "skills" / "context-lite"


def valid_now() -> str:
    return """# TASK-001: Resume a low-risk local task

Updated: 2026-09-01T02:00:00Z
Phase: implementation

## Acceptance
- Resume only from an identity-bound, validated record.

## Current State
- [STATE-01] Original exists | mutable: true | source: /tmp/original.txt | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: test -r /tmp/original.txt

## Decisions
- Preserve the existing Blockers section | why: experience is advice only | evidence: /tmp/design.txt

## In Flight
- [RUN-01] Resume safely | owner: agent | status: pending | started_at: 2026-09-01T02:00:00Z | correlation_ref: tool:lite | recovery_ref: test -r /tmp/result.txt

## Blockers
- Existing blocker remains authoritative.

## Next
1. First: inspect the local original

## Refresh On Resume
- STATE-01 -> test -r /tmp/original.txt
- RUN-01 -> test -r /tmp/result.txt
"""


class ContextLiteExperienceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "context-lite"
        built = subprocess.run(
            [sys.executable, str(PACKAGER), "build", "--source", str(LITE_SOURCE),
             "--destination", str(self.package), "--source-revision", "git:ticket-5-test"],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        self.manifest_sha256 = json.loads(built.stdout)["manifest_sha256"]
        self.workspace = self.root / "workspace"
        self.context_root = self.root / "context"
        self.workspace.mkdir()
        (self.context_root / "TASK-001").mkdir(parents=True)
        (self.context_root / "TASK-001" / "NOW.md").write_text(valid_now(), encoding="utf-8")
        initialized = self._doctor("init-binding", "--package-root", str(self.package),
                                   "--expected-manifest-sha256", self.manifest_sha256,
                                   "--context-root", str(self.context_root),
                                   "--workspace-root", str(self.workspace), "--task-id", "TASK-001")
        self.assertEqual(initialized["status"], "pass", initialized)

    def _doctor(self, *arguments: str) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(self.package / "scripts" / "context_doctor.py"), *arguments],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def resume(self, *arguments: str) -> tuple[int, dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(self.package / "scripts" / "context_lite.py"), "resume",
             "--package-root", str(self.package), "--context-root", str(self.context_root),
             "--workspace-root", str(self.workspace), "--task-id", "TASK-001", *arguments],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def _experience_cli(self, command: str, *arguments: str) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(self.package / "scripts" / "context_experience.py"), command,
             "--workspace", str(self.workspace), "--store", str(self.workspace / ".context-experience"), *arguments],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def _source_ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _seed_validated_experience(self, *, validate: bool = True) -> None:
        original = self.workspace / "experience-original.txt"
        original.write_text("A real workspace-local original supports this suggestion.\n", encoding="utf-8")
        candidate = self.workspace / "experience-candidate.json"
        candidate.write_text(json.dumps({
            "schema": 1,
            "experience_id": "verified-resume-001",
            "revision": 1,
            "claim": "Read the original before resuming the local task.",
            "tags": ["verification"],
            "applicability": ["The task has a readable local original."],
            "exclusions": ["none-known"],
            "source_refs": [self._source_ref(original)],
            "supersedes": None,
        }), encoding="utf-8")
        self.assertEqual(self._experience_cli("init")["status"], "pass")
        self.assertEqual(self._experience_cli("record", "--input", str(candidate))["status"], "pass")
        if not validate:
            return

        now = datetime.now(timezone.utc).replace(microsecond=0)
        material = self.workspace / "validation.txt"
        material.write_text("A real validation original was checked by the host boundary.\n", encoding="utf-8")
        source_ref = self._source_ref(material)
        current = now.isoformat().replace("+00:00", "Z")
        expires = (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        refs = {
            "cross": {"source_refs": [source_ref], "checker_id": "test-host", "checker_version": "1", "validated_at": current, "expires_at": expires, "independence_basis": "Separate host review."},
            "counterexample": {"source_refs": [source_ref], "checker_id": "test-host", "checker_version": "1", "validated_at": current, "expires_at": expires, "original_pass_ref": source_ref, "mutated_fail_ref": source_ref, "restored_pass_ref": source_ref, "mutation_hit_ref": source_ref},
            "effectiveness": {"source_refs": [source_ref], "checker_id": "test-host", "checker_version": "1", "validated_at": current, "expires_at": expires, "representative_run_ref": source_ref, "non_applicable_run_ref": source_ref},
        }
        program = """
import json
import sys
sys.path.insert(0, sys.argv[1])
import managing_long_task_context as context
result = context.bind_experience(sys.argv[2], sys.argv[3]).review(
    'verified-resume-001', 1, json.loads(sys.argv[4]),
    evidence_checker=lambda record, incoming: {'status': 'pass', 'codes': []},
)
print(json.dumps(result))
raise SystemExit(0 if result['status'] == 'pass' else 1)
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(ROOT / "src"), str(self.workspace),
             str(self.workspace / ".context-experience"), json.dumps(refs)],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "pass")

    def test_requires_rule_proof_blocks_valid_lite_resume_without_context(self) -> None:
        code, report = self.resume("--requires-rule-proof")

        self.assertEqual(code, 2, report)
        self.assertIsNone(report["context"])
        self.assertEqual(report["diagnostic"]["status"], "unknown")
        self.assertIn("STRICT_REQUIRED", report["diagnostic"]["codes"])

    def test_default_resume_is_unchanged_and_experience_arguments_are_paired(self) -> None:
        default_code, default = self.resume()

        self.assertEqual(default_code, 0, default)
        self.assertEqual(set(default), {"diagnostic", "context"})
        self.assertEqual(default["context"], valid_now())
        for arguments in (("--experience-store", str(self.workspace / ".context-experience")),
                          ("--experience-tags", "verification")):
            with self.subTest(arguments=arguments):
                code, report = self.resume(*arguments)
                self.assertEqual(code, 1, report)
                self.assertIsNone(report["context"])
                self.assertEqual(report["diagnostic"]["status"], "fail")
                self.assertIn("INPUT_INVALID", report["diagnostic"]["codes"])

    def test_unavailable_experience_store_is_unknown_without_polluting_valid_context(self) -> None:
        code, report = self.resume(
            "--experience-store", str(self.workspace / ".context-experience"),
            "--experience-tags", "verification",
        )

        self.assertEqual(code, 0, report)
        self.assertEqual(report["context"], valid_now())
        self.assertEqual(report["experience"]["status"], "unknown")
        self.assertEqual(report["experience"]["suggestions"], [])
        self.assertFalse(report["experience"]["requires_strict"])
        self.assertFalse((self.workspace / ".context-experience").exists())

    def test_candidate_experience_is_not_returned_as_an_approved_suggestion(self) -> None:
        self._seed_validated_experience(validate=False)

        code, report = self.resume(
            "--experience-store", str(self.workspace / ".context-experience"),
            "--experience-tags", "verification",
        )

        self.assertEqual(code, 0, report)
        self.assertEqual(report["experience"]["status"], "pass")
        self.assertEqual(report["experience"]["suggestions"], [])

    def test_validated_experience_is_a_bounded_suggestion_and_candidate_is_not_approved(self) -> None:
        self._seed_validated_experience()
        arguments = ("--experience-store", str(self.workspace / ".context-experience"),
                     "--experience-tags", "verification")

        code, report = self.resume(*arguments)

        self.assertEqual(code, 0, report)
        self.assertEqual(report["context"], valid_now())
        self.assertIn("Existing blocker remains authoritative.", report["context"])
        self.assertEqual(report["experience"]["status"], "pass")
        self.assertLessEqual(len(report["experience"]["suggestions"]), 3)
        self.assertEqual(report["experience"]["suggestions"], [{
            "experience_id": "verified-resume-001",
            "revision": 1,
            "status": "validated",
            "claim": "Read the original before resuming the local task.",
            "applicability": ["The task has a readable local original."],
            "exclusions": ["none-known"],
            "source_refs": [self._source_ref(self.workspace / "experience-original.txt")],
            "reliance": "reliable",
        }])

    def test_symlinked_experience_store_is_unknown_without_following_it(self) -> None:
        outside = self.root / "outside-store"
        outside.mkdir()
        store_link = self.workspace / "experience-link"
        store_link.symlink_to(outside, target_is_directory=True)

        code, report = self.resume(
            "--experience-store", str(store_link), "--experience-tags", "verification",
        )

        self.assertEqual(code, 0, report)
        self.assertEqual(report["context"], valid_now())
        self.assertEqual(report["experience"]["status"], "unknown")
        self.assertIn("INVALID_STORE", report["experience"]["codes"])


if __name__ == "__main__":
    unittest.main()
