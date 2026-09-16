"""Public Context Lite flush and cold-check handoff behavior."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LITE_SOURCE = ROOT if (ROOT / "scripts" / "context_lite.py").is_file() else ROOT / "skills" / "context-lite"
PACKAGER = LITE_SOURCE / "scripts" / "skill_package.py"


def valid_now(*, task_id: str = "TASK-001", goal: str = "Resume a low-risk local task", run_status: str = "unknown") -> str:
    return f"""# {task_id}: {goal}

Updated: 2026-09-01T02:00:00Z
Phase: implementation

## Acceptance
- Resume only from an identity-bound, validated record.

## Current State
- [STATE-01] Original exists | mutable: true | source: /tmp/original.txt | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: read:/tmp/original.txt

## Decisions
- Preserve the existing Blockers section | why: a cold read does not prove semantics | evidence: /tmp/design.txt

## In Flight
- [RUN-01] Resume safely | owner: agent | status: {run_status} | started_at: 2026-09-01T02:00:00Z | correlation_ref: tool:lite | recovery_ref: read:/tmp/result.txt

## Blockers
- Existing blocker remains authoritative.

## Next
1. First: inspect the local original

## Refresh On Resume
- STATE-01 -> read:/tmp/original.txt
- RUN-01 -> read:/tmp/result.txt
"""


class ContextLiteHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "context-lite"
        built = subprocess.run(
            [sys.executable, str(PACKAGER), "build", "--source", str(LITE_SOURCE),
             "--destination", str(self.package), "--source-revision", "git:e5-test"],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        self.manifest_sha256 = json.loads(built.stdout)["manifest_sha256"]
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.context_root = self.root / "context"
        self.task_dir = self.context_root / "TASK-001"
        self.task_dir.mkdir(parents=True)
        self.now = self.task_dir / "NOW.md"
        self.now.write_text(valid_now(), encoding="utf-8")
        initialized = self.doctor(
            "init-binding", "--package-root", str(self.package),
            "--expected-manifest-sha256", self.manifest_sha256,
            "--context-root", str(self.context_root), "--workspace-root", str(self.workspace),
            "--task-id", "TASK-001",
        )
        self.assertEqual(initialized[0], 0, initialized)
        self.assertEqual(initialized[1]["status"], "pass", initialized)

    def doctor(self, *arguments: str) -> tuple[int, dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(self.package / "scripts" / "context_doctor.py"), *arguments],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def cli(self, command: str, *arguments: str) -> tuple[int, dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(self.package / "scripts" / "context_lite.py"), command, *arguments],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def cold_check(self, *arguments: str) -> tuple[int, dict[str, object]]:
        return self.cli(
            "cold-check", "--package-root", str(self.package), "--context-root", str(self.context_root),
            "--workspace-root", str(self.workspace), "--task-id", "TASK-001", *arguments,
        )

    def test_flush_matches_atomic_write_and_is_idempotent(self) -> None:
        candidate = self.root / "candidate.md"
        candidate.write_text(valid_now(), encoding="utf-8")

        code, written = self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )

        target = self.workspace / ".context-lite" / "TASK-001" / "NOW.md"
        self.assertEqual(code, 0, written)
        self.assertEqual(written["status"], "written")
        self.assertEqual(written["now_sha256"], hashlib.sha256(valid_now().encode()).hexdigest())
        before = target.stat().st_mtime_ns
        original = target.read_text(encoding="utf-8")
        time.sleep(0.01)
        code, unchanged = self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )
        self.assertEqual(code, 0, unchanged)
        self.assertEqual(unchanged["status"], "unchanged")
        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(unchanged["now_sha256"], written["now_sha256"])

    def test_flush_digest_uses_the_written_bytes_without_a_post_write_read(self) -> None:
        candidate = self.root / "candidate.md"
        candidate.write_text(valid_now(), encoding="utf-8")
        program = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import context_lite
context_lite._read_bounded_bytes = lambda path: (_ for _ in ()).throw(AssertionError('post-write read'))
report, code = context_lite._flush(Path(sys.argv[2]), Path(sys.argv[3]), 'TASK-001')
print(json.dumps({'code': code, 'report': report}))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.package / "scripts"), str(candidate), str(self.workspace)],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        injected = json.loads(result.stdout)
        self.assertEqual(injected["code"], 0, injected)
        self.assertEqual(injected["report"]["now_sha256"], hashlib.sha256(valid_now().encode()).hexdigest())

    def test_unchanged_flush_hashes_existing_crlf_bytes(self) -> None:
        candidate = self.root / "candidate.md"
        candidate.write_text(valid_now(), encoding="utf-8")
        self.assertEqual(self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )[0], 0)
        target = self.workspace / ".context-lite" / "TASK-001" / "NOW.md"
        crlf = valid_now().replace("\n", "\r\n").encode("utf-8")
        target.write_bytes(crlf)

        code, report = self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )

        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(report["now_sha256"], hashlib.sha256(crlf).hexdigest())
        self.assertEqual(target.read_bytes(), crlf)

    def test_unchanged_flush_refuses_real_disk_replacement_between_source_and_digest_reads(self) -> None:
        candidate = self.root / "candidate.md"
        candidate.write_text(valid_now(), encoding="utf-8")
        self.assertEqual(self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )[0], 0)
        target = self.workspace / ".context-lite" / "TASK-001" / "NOW.md"
        replacements = (
            valid_now(goal="Replacement goal on disk"),
            valid_now().replace("Phase: implementation", "Phase: replacement state"),
        )
        program = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import context_lite
original_read = context_lite._read_bounded_bytes
def replace_before_digest(path):
    Path(path).write_bytes(Path(sys.argv[4]).read_bytes())
    return original_read(path)
context_lite._read_bounded_bytes = replace_before_digest
report, code = context_lite._flush(Path(sys.argv[2]), Path(sys.argv[3]), 'TASK-001')
print(json.dumps({'code': code, 'report': report}))
"""
        replacement_path = self.root / "replacement.md"
        for replacement in replacements:
            with self.subTest(replacement=replacement.splitlines()[0]):
                target.write_bytes(candidate.read_bytes())
                replacement_path.write_text(replacement, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-c", program, str(self.package / "scripts"), str(candidate),
                     str(self.workspace), str(replacement_path)],
                    cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
                )
                self.assertEqual(result.stderr, "", result.stdout + result.stderr)
                injected = json.loads(result.stdout)
                self.assertEqual(injected["code"], 2, injected)
                self.assertEqual(injected["report"]["status"], "unknown")
                self.assertIn("NOW_CHANGED_DURING_FLUSH", injected["report"]["codes"])
                self.assertNotIn("now_sha256", injected["report"])

    def test_flush_preserves_old_now_for_validation_goal_and_atomic_write_failures(self) -> None:
        candidate = self.root / "candidate.md"
        candidate.write_text(valid_now(), encoding="utf-8")
        self.assertEqual(self.cli(
            "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
        )[0], 0)
        target = self.workspace / ".context-lite" / "TASK-001" / "NOW.md"
        original = target.read_text(encoding="utf-8")
        invalid_cases = (
            valid_now().replace("## Decisions", "## Notes"),
            valid_now().replace("1. First:", "1. Then:"),
            valid_now() + "x" * 8001,
            valid_now(goal="A conflicting goal"),
        )
        for text in invalid_cases:
            candidate.write_text(text, encoding="utf-8")
            code, report = self.cli(
                "flush", "--candidate", str(candidate), "--base-dir", str(self.workspace), "--task-id", "TASK-001",
            )
            self.assertEqual(code, 1, report)
            self.assertEqual(target.read_text(encoding="utf-8"), original)

        candidate.write_text(valid_now().replace("Phase: implementation", "Phase: revised"), encoding="utf-8")
        program = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import context_lite
context_lite.os.replace = lambda source, target: (_ for _ in ()).throw(OSError('injected'))
report, code = context_lite._flush(Path(sys.argv[2]), Path(sys.argv[3]), 'TASK-001')
print(json.dumps({'code': code, 'report': report}))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.package / "scripts"), str(candidate), str(self.workspace)],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        injected = json.loads(result.stdout)
        self.assertEqual(injected["code"], 1, injected)
        self.assertIn("NOW_ATOMIC_WRITE_FAILED", injected["report"]["codes"])
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_cold_check_returns_material_only_after_identity_bound_resume(self) -> None:
        code, report = self.cold_check()

        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["history_inheritance"], "unknown")
        self.assertEqual(report["semantic_verification"], "pending")
        self.assertFalse(report["archive_allowed"])
        self.assertNotIn("context", report)
        material = report["material"]
        self.assertEqual(material["task_id"], "TASK-001")
        self.assertEqual(material["now_sha256"], hashlib.sha256(valid_now().encode()).hexdigest())
        self.assertEqual(material["goal"], "Resume a low-risk local task")
        self.assertEqual(material["acceptance"], ["- Resume only from an identity-bound, validated record."])
        self.assertEqual(material["current_state"], [
            "- [STATE-01] Original exists | mutable: true | source: /tmp/original.txt | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: read:/tmp/original.txt",
        ])
        self.assertEqual(material["first_action"], "inspect the local original")
        self.assertEqual(material["next"], ["1. First: inspect the local original"])
        self.assertEqual(material["refresh_mappings"], {
            "STATE-01": "read:/tmp/original.txt", "RUN-01": "read:/tmp/result.txt",
        })
        self.assertEqual(material["semantic_verification"], "pending")

    def test_cold_check_rejects_now_symlink_outside_bound_task_directory(self) -> None:
        outside = self.root / "outside-NOW.md"
        outside.write_text(valid_now(goal="External material must not escape"), encoding="utf-8")
        self.now.unlink()
        self.now.symlink_to(outside)

        code, report = self.cold_check()

        self.assertEqual(code, 2, report)
        self.assertEqual(report["status"], "unknown")
        self.assertIsNone(report["material"])
        self.assertNotIn("External material must not escape", json.dumps(report))

    def test_cold_check_keeps_crlf_bytes_as_the_handoff_version(self) -> None:
        crlf = valid_now().replace("\n", "\r\n")
        self.now.write_bytes(crlf.encode("utf-8"))

        code, report = self.cold_check("--expected-now-sha256", hashlib.sha256(crlf.encode()).hexdigest())

        self.assertEqual(code, 0, report)
        self.assertEqual(report["material"]["now_sha256"], hashlib.sha256(crlf.encode()).hexdigest())
        self.assertEqual(report["material"]["first_action"], "inspect the local original")

    def test_cold_check_extracts_the_unique_first_action_and_all_next_items(self) -> None:
        text = valid_now().replace(
            "1. First: inspect the local original",
            "1.  First:    inspect the local original\n2. preserve the record\n3. independently observe state",
        )
        self.now.write_text(text, encoding="utf-8")

        code, report = self.cold_check()

        self.assertEqual(code, 0, report)
        self.assertEqual(report["material"]["first_action"], "inspect the local original")
        self.assertEqual(report["material"]["next"], [
            "1.  First:    inspect the local original", "2. preserve the record", "3. independently observe state",
        ])

    def test_cold_check_refuses_bad_or_changed_handoff_hash_without_material(self) -> None:
        current = hashlib.sha256(self.now.read_bytes()).hexdigest()
        for expected in ("not-a-hash", "0" * 64 if current != "0" * 64 else "1" * 64):
            with self.subTest(expected=expected):
                code, report = self.cold_check("--expected-now-sha256", expected)
                self.assertEqual(code, 2, report)
                self.assertEqual(report["status"], "unknown")
                self.assertIsNone(report["material"])
                self.assertEqual(report["semantic_verification"], "pending")

    def test_cold_check_refuses_a_now_change_after_identity_and_first_read(self) -> None:
        program = """
import json, sys
from argparse import Namespace
sys.path.insert(0, sys.argv[1])
import context_lite
original_read_bytes = context_lite._read_bound_now_bytes
reads = 0
def changed_on_second_read(context_root, task_id):
    global reads
    reads += 1
    return original_read_bytes(context_root, task_id) if reads == 1 else (b'changed-after-first-read', None)
context_lite._read_bound_now_bytes = changed_on_second_read
report, code = context_lite._cold_check(Namespace(
    package_root=sys.argv[2], context_root=sys.argv[3], workspace_root=sys.argv[4], task_id='TASK-001',
    requires_rule_proof=False, experience_store=None, experience_tags=None, expected_now_sha256=None,
))
print(json.dumps({'code': code, 'report': report}))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.package / "scripts"), str(self.package),
             str(self.context_root), str(self.workspace)],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        injected = json.loads(result.stdout)
        self.assertEqual(injected["code"], 2, injected)
        self.assertEqual(injected["report"]["status"], "unknown")
        self.assertIn("NOW_CHANGED_DURING_COLD_CHECK", injected["report"]["codes"])
        self.assertIsNone(injected["report"]["material"])

    def test_cold_check_refuses_real_disk_goal_change_between_its_two_reads(self) -> None:
        replacement = valid_now(goal="A different disk-backed goal").encode("utf-8")
        program = """
import json, sys
from argparse import Namespace
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import context_lite
original_read_bytes = context_lite._read_bound_now_bytes
reads = 0
def changed_on_second_read(context_root, task_id):
    global reads
    reads += 1
    if reads == 2:
        (Path(context_root) / task_id / 'NOW.md').write_bytes(Path(sys.argv[5]).read_bytes())
    return original_read_bytes(context_root, task_id)
context_lite._read_bound_now_bytes = changed_on_second_read
report, code = context_lite._cold_check(Namespace(
    package_root=sys.argv[2], context_root=sys.argv[3], workspace_root=sys.argv[4], task_id='TASK-001',
    requires_rule_proof=False, experience_store=None, experience_tags=None, expected_now_sha256=None,
))
print(json.dumps({'code': code, 'report': report}))
"""
        replacement_path = self.root / "replacement.md"
        replacement_path.write_bytes(replacement)
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.package / "scripts"), str(self.package),
             str(self.context_root), str(self.workspace), str(replacement_path)],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        injected = json.loads(result.stdout)
        self.assertEqual(injected["code"], 2, injected)
        self.assertEqual(injected["report"]["status"], "unknown")
        self.assertIn("NOW_CHANGED_DURING_COLD_CHECK", injected["report"]["codes"])
        self.assertIsNone(injected["report"]["material"])

    def test_cold_check_preserves_resume_hard_stops(self) -> None:
        cases = (
            ("requires-rule-proof", ["--requires-rule-proof"]),
            ("wrong-workspace", ["--workspace-root", str(self.root)]),
            ("wrong-package", ["--package-root", str(self.root)]),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                code, report = self.cold_check(*arguments)
                self.assertIn(code, {1, 2}, report)
                self.assertIn(report["status"], {"fail", "unknown"})
                self.assertIsNone(report["material"])
                self.assertNotIn("context", report)

    def test_cold_checks_are_repeatable_read_only_and_never_execute_refresh_refs(self) -> None:
        before = self.now.stat().st_mtime_ns
        expected = hashlib.sha256(self.now.read_bytes()).hexdigest()
        observed: list[dict[str, object]] = []
        for _ in range(20):
            code, report = self.cold_check("--expected-now-sha256", expected)
            self.assertEqual(code, 0, report)
            observed.append(report["material"])
        self.assertEqual(self.now.stat().st_mtime_ns, before)
        self.assertEqual(observed, [observed[0]] * 20)
        self.assertFalse(Path("/tmp/original.txt").exists())
        self.assertFalse(Path("/tmp/result.txt").exists())
        self.assertEqual(observed[0]["in_flight"], [
            "- [RUN-01] Resume safely | owner: agent | status: unknown | started_at: 2026-09-01T02:00:00Z | correlation_ref: tool:lite | recovery_ref: read:/tmp/result.txt",
        ])

    def test_short_workflow_reference_keeps_semantics_pending(self) -> None:
        reference = LITE_SOURCE / "references/short-session.md"
        skill = (LITE_SOURCE / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(reference.is_file())
        text = reference.read_text(encoding="utf-8")
        self.assertIn("semantic_verification: pending", text)
        self.assertIn("cold-check", skill)
        self.assertIn("references/short-session.md", skill)


if __name__ == "__main__":
    unittest.main()
