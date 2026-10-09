"""Preserve the baseline checklist and require complete, ordered additions."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


CHECKLIST = Path(__file__).resolve().parents[1] / "docs/regression-checklist.md"
# Baseline 3a7acba: R-016 was never allocated; do not derive this set from the file.
BASELINE_IDS = (
    "R-001", "R-002", "R-003", "R-004", "R-005", "R-006", "R-007", "R-008",
    "R-009", "R-010", "R-011", "R-012", "R-013", "R-014", "R-015",
    "R-017", "R-018", "R-019", "R-020", "R-021", "R-022", "R-023",
    "R-024", "R-025", "R-026", "R-027", "R-028", "R-029", "R-030", "R-031",
)
MANUAL_BASELINE_IDS = {"R-002", "R-008"}


class RegressionChecklistGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        text = CHECKLIST.read_text(encoding="utf-8")
        self.entries = re.findall(
            r"^### (R-\d+)[^\n]*\n(.*?)(?=^### R-|\Z)", text, re.M | re.S,
        )
        self.ids = [rid for rid, _ in self.entries]

    def test_all_baseline_entries_remain(self) -> None:
        self.assertEqual(set(BASELINE_IDS) - set(self.ids), set(), "baseline entries removed")

    def test_ids_are_unique_and_strictly_increasing(self) -> None:
        numbers = [int(rid[2:]) for rid in self.ids]
        self.assertEqual(len(numbers), len(set(numbers)), "duplicate checklist number")
        self.assertEqual(numbers, sorted(numbers), "checklist numbers must increase")
        for rid, number in zip(self.ids, numbers):
            self.assertEqual(rid, f"R-{number:03d}")
        self.assertNotIn("R-016", self.ids, "historical unallocated number is reserved")

    def test_new_entries_are_contiguous_from_r032(self) -> None:
        additions = [int(rid[2:]) for rid in self.ids if int(rid[2:]) > 31]
        self.assertEqual(additions, list(range(32, 32 + len(additions))))

    def test_each_entry_has_provenance_check_and_pass_condition(self) -> None:
        for rid, body in self.entries:
            with self.subTest(entry=rid):
                self.assertRegex(body, r"(?m)^Added: .+", "missing Added line")
                self.assertRegex(body, r"(?m)^Pass: .+", "missing Pass line")
                if rid not in MANUAL_BASELINE_IDS:
                    self.assertRegex(body, r"(?ms)^```sh\n.+?^```[ \t]*$", "missing shell check")


if __name__ == "__main__":
    unittest.main()
