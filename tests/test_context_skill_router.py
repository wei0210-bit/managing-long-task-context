from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts/context_skill_router.py"


def base_characteristics(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "risk_facts_complete": True,
        "multi_turn": False,
        "single_primary_agent": True,
        "high_risk": False,
        "auditability_required": False,
        "frozen_acceptance": False,
        "independent_validation": False,
        "external_side_effects": False,
        "multiple_state_writers": False,
    }
    value.update(overrides)
    return value


class ContextSkillRouterTests(unittest.TestCase):
    def route(self, characteristics: dict[str, object], expected: int = 0) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            input_path.write_text(json.dumps(characteristics), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(TOOL), "--input", str(input_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_single_turn_static_task_uses_no_skill(self) -> None:
        report = self.route(base_characteristics())
        self.assertEqual(report["recommendation"], "NO_SKILL")

    def test_low_risk_single_agent_multiturn_task_recommends_lite(self) -> None:
        report = self.route(base_characteristics(multi_turn=True))
        self.assertEqual(report["recommendation"], "LITE_RECOMMENDED")
        self.assertTrue(report["human_confirmation_required"])

    def test_each_strict_trigger_dominates(self) -> None:
        for field in (
            "high_risk",
            "auditability_required",
            "frozen_acceptance",
            "independent_validation",
            "external_side_effects",
            "multiple_state_writers",
        ):
            with self.subTest(field=field):
                report = self.route(base_characteristics(multi_turn=True, **{field: True}))
                self.assertEqual(report["recommendation"], "STRICT_REQUIRED")
                self.assertIn(field, report["reasons"])

    def test_incomplete_risk_facts_fail_closed_to_strict(self) -> None:
        report = self.route(base_characteristics(risk_facts_complete=False))
        self.assertEqual(report["recommendation"], "STRICT_REQUIRED")
        self.assertIn("risk_facts_incomplete", report["reasons"])

    def test_multi_agent_cannot_route_to_lite(self) -> None:
        report = self.route(base_characteristics(multi_turn=True, single_primary_agent=False))
        self.assertEqual(report["recommendation"], "STRICT_REQUIRED")
        self.assertIn("single_primary_agent_false", report["reasons"])

    def test_router_never_injects_or_authorizes_actions(self) -> None:
        for characteristics in (
            base_characteristics(),
            base_characteristics(multi_turn=True),
            base_characteristics(external_side_effects=True),
        ):
            report = self.route(characteristics)
            self.assertFalse(report["automatic_injection"])
            self.assertFalse(report["external_action_authorized"])
            self.assertEqual(report["selection_authority"], "user")

    def test_unknown_fields_are_rejected(self) -> None:
        report = self.route(base_characteristics(unknown_flag=True), expected=2)
        self.assertEqual(report["status"], "invalid")
        self.assertIn("ROUTE_UNKNOWN_FIELD", report["codes"])


if __name__ == "__main__":
    unittest.main()
