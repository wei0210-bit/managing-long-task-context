from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LITE_SOURCE = ROOT if (ROOT / "scripts" / "context_lite.py").is_file() else ROOT / "skills" / "context-lite"
TOOL = LITE_SOURCE / "scripts" / "context_lite.py"


def valid_now(task_id: str = "TASK-001", goal: str = "Implement deterministic validation") -> str:
    return f"""# {task_id}: {goal}

Updated: 2026-09-01T02:00:00Z
Phase: implementation

## Acceptance
- Validator tests pass.

## Current State
- [STATE-01] Source is present | mutable: true | source: /tmp/source.json | refreshed_at: 2026-09-01T02:00:00Z | refresh_ref: test -r /tmp/source.json

## Decisions
- Use the standard library | why: keep Lite portable | evidence: /tmp/design.md

## In Flight
- [RUN-01] Validate candidate | owner: agent | status: pending | started_at: 2026-09-01T02:00:00+00:00 | correlation_ref: tool:validator-01 | recovery_ref: test -r /tmp/result.json

## Blockers
- none

## Next
1. First: run the focused validator tests
2. review the result

## Refresh On Resume
- STATE-01 -> test -r /tmp/source.json
- RUN-01 -> test -r /tmp/result.json
"""


class ContextLiteValidatorTests(unittest.TestCase):
    def run_tool(self, *args: str, expected: int = 0) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=LITE_SOURCE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_validate_accepts_fixed_document_and_reports_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "NOW.md"
            candidate.write_text(valid_now(), encoding="utf-8")
            report = self.run_tool("validate", "--file", str(candidate), "--task-id", "TASK-001")
            self.assertEqual(report["status"], "valid")
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["stats"]["first_actions"], 1)
            self.assertEqual(report["stats"]["next_items"], 2)

    def test_validate_returns_stable_codes_for_structural_and_safety_failures(self) -> None:
        cases = {
            "heading": valid_now().replace("## Decisions", "## Notes"),
            "timestamp": valid_now().replace("2026-09-01T02:00:00Z", "yesterday", 1),
            "first-action": valid_now().replace("1. First:", "1. Then:"),
            "mutating-ref": valid_now().replace("test -r /tmp/result.json", "rm /tmp/result.json", 1),
            "absolute-mutating-ref": valid_now().replace("test -r /tmp/result.json", "/bin/rm /tmp/result.json", 1),
            "sed-in-place-ref": valid_now().replace("test -r /tmp/result.json", "sed -i backup /tmp/result.json", 1),
            "git-reset-ref": valid_now().replace("test -r /tmp/result.json", "git -C /tmp reset --hard", 1),
        }
        expected_codes = {
            "heading": "NOW_HEADING_ORDER_INVALID",
            "timestamp": "NOW_TIMESTAMP_NOT_UTC",
            "first-action": "NOW_FIRST_ACTION_INVALID",
            "mutating-ref": "NOW_REFERENCE_NOT_READ_ONLY",
            "absolute-mutating-ref": "NOW_REFERENCE_NOT_READ_ONLY",
            "sed-in-place-ref": "NOW_REFERENCE_NOT_READ_ONLY",
            "git-reset-ref": "NOW_REFERENCE_NOT_READ_ONLY",
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, text in cases.items():
                with self.subTest(name=name):
                    candidate = Path(directory) / f"{name}.md"
                    candidate.write_text(text, encoding="utf-8")
                    report = self.run_tool(
                        "validate", "--file", str(candidate), "--task-id", "TASK-001", expected=1,
                    )
                    self.assertIn(expected_codes[name], report["codes"])

    def test_validate_enforces_all_size_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            samples = {
                "lines": valid_now() + "\n".join(f"extra {index}" for index in range(100)),
                "chars": valid_now() + ("x" * 8001),
                "line": valid_now().replace("- Validator tests pass.", "- " + ("x" * 501)),
                "next": valid_now().replace(
                    "2. review the result", "2. review the result\n3. document it\n4. ship it",
                ),
            }
            expected_codes = {
                "lines": "NOW_LINE_LIMIT_EXCEEDED",
                "chars": "NOW_CHARACTER_LIMIT_EXCEEDED",
                "line": "NOW_SINGLE_LINE_LIMIT_EXCEEDED",
                "next": "NOW_NEXT_LIMIT_EXCEEDED",
            }
            for name, text in samples.items():
                with self.subTest(name=name):
                    path = directory_path / f"{name}.md"
                    path.write_text(text, encoding="utf-8")
                    report = self.run_tool("validate", "--file", str(path), expected=1)
                    self.assertIn(expected_codes[name], report["codes"])

    def test_atomic_write_is_idempotent_and_preserves_old_file_on_failure_or_goal_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            candidate = base / "candidate.md"
            candidate.write_text(valid_now(), encoding="utf-8")
            report = self.run_tool(
                "write", "--candidate", str(candidate), "--base-dir", str(base), "--task-id", "TASK-001",
            )
            target = base / ".context-lite/TASK-001/NOW.md"
            self.assertEqual(report["status"], "written")
            original = target.read_text(encoding="utf-8")

            self.assertEqual(
                self.run_tool(
                    "write", "--candidate", str(candidate), "--base-dir", str(base), "--task-id", "TASK-001",
                )["status"],
                "unchanged",
            )

            candidate.write_text(valid_now(goal="Different goal"), encoding="utf-8")
            conflict = self.run_tool(
                "write", "--candidate", str(candidate), "--base-dir", str(base), "--task-id", "TASK-001",
                expected=1,
            )
            self.assertIn("NOW_GOAL_CONFLICT", conflict["codes"])
            self.assertEqual(target.read_text(encoding="utf-8"), original)

            candidate.write_text(valid_now().replace("## Decisions", "## Notes"), encoding="utf-8")
            invalid = self.run_tool(
                "write", "--candidate", str(candidate), "--base-dir", str(base), "--task-id", "TASK-001",
                expected=1,
            )
            self.assertIn("NOW_HEADING_ORDER_INVALID", invalid["codes"])
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_unreadable_path_observation_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            report = self.run_tool("observe-path", "--state-id", "STATE-01", "--path", str(missing))
            self.assertEqual(report["status"], "unknown")
            self.assertEqual(report["code"], "OBSERVATION_UNREADABLE")

    def test_refresh_mapping_must_match_each_stable_state_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "NOW.md"
            candidate.write_text(
                valid_now().replace("- RUN-01 -> test -r /tmp/result.json\n", ""),
                encoding="utf-8",
            )
            report = self.run_tool("validate", "--file", str(candidate), expected=1)
            self.assertIn("NOW_REFRESH_MAPPING_MISSING", report["codes"])


if __name__ == "__main__":
    unittest.main()
