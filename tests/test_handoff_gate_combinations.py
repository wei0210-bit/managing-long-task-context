"""E1-04 AC1--AC3: actual three-switch handoff and completion combinations."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from handoff_gate_fixtures import HandoffGateFixture


FROZEN_CASES_PATH = Path(__file__).parent / "fixtures" / "handoff" / "cases.json"


def frozen_matrix_cases() -> list[dict[str, object]]:
    """Load the frozen E0 stimulus; do not duplicate its switch mapping here."""
    catalog = json.loads(FROZEN_CASES_PATH.read_text(encoding="utf-8"))
    selected = [
        case for case in catalog["cases"]
        if 148 <= int(str(case.get("case_id", "E0-0")).removeprefix("E0-")) <= 171
    ]
    if len(selected) != 24:
        raise AssertionError(f"expected 24 frozen E0 rows, found {len(selected)}")
    return selected


class HandoffGateCombinationTests(unittest.TestCase):
    """Each frozen group has valid, missing-basis, and post-check-change cases."""

    def _fixture(self, truth: bool, rules: bool, independent: bool) -> HandoffGateFixture:
        fixture = HandoffGateFixture(
            truth_sources=truth, rule_execution=rules, independent_validation=independent,
        )
        self.addCleanup(fixture.close)
        return fixture

    def test_e0_148_to_171_all_three_switch_cases_run_real_handoff_and_gate(self) -> None:
        for frozen in frozen_matrix_cases():
            case_id = frozen["case_id"]
            stimulus = frozen["stimulus"]["value"]
            self.assertEqual(frozen["operation"]["entry_point"], "activate_handoff")
            self.assertIsInstance(stimulus, dict)
            truth = stimulus["truth_sources"]
            rules = stimulus["rule_execution"]
            independent = stimulus["independent_validation"]
            scenario = stimulus["scenario"]
            with self.subTest(case_id=case_id, scenario=scenario, truth=truth, rules=rules, independent=independent):
                fixture = self._fixture(truth, rules, independent)
                contract = fixture.published
                self.assertEqual("truth-sources/v1" in contract.get("required_capabilities", []), truth)
                self.assertEqual("rule-execution/v1" in contract.get("required_capabilities", []), rules)
                self.assertEqual(
                    contract["acceptance_criteria"][0].get("independent_validation_required") is True,
                    independent,
                )
                self.assertTrue(contract["seal"]["integrity_digest"].startswith("sha256:"))
                prepared = fixture.prepare()
                self.assertEqual(prepared["check_status"], "pass", prepared)
                # This is the producer's frozen evidence declaration.  The
                # invalid cases must not recompute it from changed state.
                frozen_evidence = fixture.evidence_map()
                if scenario == "invalid_basis":
                    fixture.basis_path.unlink()
                elif scenario == "changed_after_check":
                    fixture.verifier.change_after_read = True
                activated = fixture.activate()
                events = fixture.control_events()
                activation_events = [event for event in events if event["event_type"] == "handoff_activated"]
                if scenario == "valid":
                    self.assertEqual(activated["check_status"], frozen["expected_check"], activated)
                    self.assertEqual(activated["commit_status"], frozen["expected_commit"], activated)
                    self.assertEqual(activated["controller_generation"] - fixture.initial_generation, frozen["expected_generation_delta"], activated)
                    self.assertEqual(len(activation_events), 1)
                    completed = fixture.completion(evidence_map=frozen_evidence)
                    self.assertTrue(completed["passed"], completed)
                    self.assertEqual(completed["contract_version"], 1)
                    self.assertEqual(completed["criteria"]["AC-BUSINESS"]["status"], "pass")
                    if independent:
                        self.assertEqual(fixture.validation_reads, 1)
                        self.assertEqual(completed["criteria"]["AC-BUSINESS"]["independent_validation"]["assurance"], "verified")
                    if rules:
                        self.assertEqual(completed["rules"][0]["status"], "pass")
                    removed_business_evidence = fixture.completion(evidence_map={})
                    self.assertFalse(removed_business_evidence["passed"], removed_business_evidence)
                    self.assertIn("file", removed_business_evidence["criteria"]["AC-BUSINESS"]["missing_evidence_types"])
                else:
                    self.assertEqual(activated["check_status"], frozen["expected_check"], activated)
                    self.assertEqual(activated["commit_status"], frozen["expected_commit"], activated)
                    self.assertEqual(activation_events, [])
                    status = fixture.status()
                    self.assertEqual(status["controller_generation"] - fixture.initial_generation, frozen["expected_generation_delta"], status)
                    self.assertEqual(status["commit_status"], "confirmed_not_committed", status)
                    # Removing/changing the actual bearing basis also leaves the
                    # original completion gate closed, not merely a callback shape.
                    completed = fixture.completion(evidence_map=frozen_evidence)
                    self.assertFalse(completed["passed"], completed)

    def test_complete_handoff_can_activate_while_explicit_business_blocker_keeps_completion_closed(self) -> None:
        fixture = self._fixture(True, True, True)
        fixture.block_business_completion()
        self.assertEqual(fixture.prepare()["check_status"], "pass")
        activated = fixture.activate()
        self.assertEqual(activated["check_status"], "pass", activated)
        self.assertEqual(activated["controller_generation"], 1, activated)
        completion = fixture.completion()
        self.assertFalse(completion["passed"], completion)
        self.assertTrue(any("blocking context item remains" in error for error in completion["errors"]))

    def test_completion_rejects_self_report_forged_checker_old_receipt_and_same_subject(self) -> None:
        fixture = self._fixture(False, True, True)
        self.assertEqual(fixture.prepare()["check_status"], "pass")
        self.assertEqual(fixture.activate()["check_status"], "pass")
        entry = fixture.evidence_map()

        model_claim = deepcopy(entry)
        model_claim["AC-BUSINESS"].update({"result": "pass", "validated_by": "model", "validation_receipt": {"check_result": "pass"}})
        self_report = fixture.completion(evidence_map=model_claim, validation_resolver=None)
        self.assertFalse(self_report["passed"], self_report)
        self.assertNotEqual(self_report["criteria"]["AC-BUSINESS"]["independent_validation"]["assurance"], "verified")
        self.assertEqual(fixture.validation_reads, 0, "explicit None must not fall back to the fixture resolver")

        forged = fixture.completion(evidence_map=entry, validation_resolver=lambda _ref: {"status": "pass"})
        self.assertFalse(forged["passed"], forged)
        self.assertEqual(forged["criteria"]["AC-BUSINESS"]["independent_validation"]["assurance"], "unknown")

        same_subject = fixture.completion(
            evidence_map=entry,
            validation_resolver=lambda ref: {**fixture.validation_resolver(ref), "validator_principal": "executor-principal"},
        )
        self.assertFalse(same_subject["passed"], same_subject)
        self.assertEqual(same_subject["criteria"]["AC-BUSINESS"]["independent_validation"]["assurance"], "failed")

        old_receipt = fixture.completion(
            evidence_map=entry,
            validation_resolver=lambda ref: {**fixture.validation_resolver(ref), "expires_at": "2000-01-01T00:00:00Z"},
        )
        self.assertFalse(old_receipt["passed"], old_receipt)
        self.assertEqual(old_receipt["criteria"]["AC-BUSINESS"]["independent_validation"]["assurance"], "unknown")


if __name__ == "__main__":
    unittest.main()
