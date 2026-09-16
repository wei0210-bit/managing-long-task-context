"""F1/F5 original-entry synthetic counterexamples; no business or model calls."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from e6_controller_probes import ROOT, NOW, sample, usage

sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "skills/context-lite/scripts"))
from test_context_lite_handoff import valid_now
import context_lite


class FinalControllerProbes(unittest.TestCase):
    def test_f1_unchanged_flush_never_pairs_old_report_with_replaced_bytes(self):
        for replacement in (
            valid_now(goal="A different task goal"),
            valid_now().replace("Phase: implementation", "Phase: changed"),
        ):
            with self.subTest(replacement=replacement[:65]), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                candidate = base / "candidate.md"
                target = base / ".context-lite/TASK-001/NOW.md"
                target.parent.mkdir(parents=True)
                candidate.write_text(valid_now(), encoding="utf-8")
                target.write_text(valid_now(), encoding="utf-8")
                original_read = context_lite._read
                observed = False

                def read_then_replace(path):
                    nonlocal observed
                    result = original_read(path)
                    if path == target and not observed:
                        observed = True
                        target.write_text(replacement, encoding="utf-8")
                    return result

                with patch.object(context_lite, "_read", side_effect=read_then_replace):
                    report, code = context_lite._flush(candidate, base, "TASK-001")
                self.assertTrue(observed, "probe must enter the original unchanged-flush read")
                self.assertNotEqual(code, 0, report)
                self.assertEqual(report["status"], "unknown", report)
                self.assertNotIn("now_sha256", report)
                self.assertEqual(target.read_text(encoding="utf-8"), replacement)

    def test_f5_bad_basis_cannot_use_missing_count_fallback(self):
        for basis in ("cumulative", "delta", "invalid", [], None):
            with self.subTest(basis=basis):
                result = usage.evaluate_pressure(
                    sample(window_tokens=None, milestone=True, basis=basis), now=NOW
                )
                self.assertEqual(result["decision"], "unknown", result)
                self.assertFalse(result["notify"], result)
                self.assertFalse(result["automatic_action"], result)


if __name__ == "__main__":
    unittest.main()
