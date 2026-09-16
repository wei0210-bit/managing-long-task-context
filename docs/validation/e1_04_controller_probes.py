"""Independent public-gate calls after handoff; frozen C01-C04 expectations."""
import unittest

import managing_long_task_context as context
from handoff_gate_fixtures import HandoffGateFixture


class ControllerGateProbes(unittest.TestCase):
    def fixture(self):
        fixture = HandoffGateFixture(truth_sources=True, rule_execution=True,
                                     independent_validation=True)
        self.addCleanup(fixture.close)
        return fixture

    def activate(self, fixture):
        self.assertEqual(fixture.prepare()["check_status"], "pass")
        report = fixture.activate()
        self.assertEqual(report["check_status"], "pass", report)
        self.assertEqual(report["controller_generation"], 1)
        return fixture.control_events()

    def gate(self, fixture, **overrides):
        options = dict(stage="completion", base_dir=fixture.base_dir, emit=False,
                       evidence_map=fixture.evidence_map(),
                       verifiers={"file": fixture.file_verifier},
                       rule_runtime=fixture.rule_runtime(),
                       validation_resolver=fixture.validation_resolver,
                       independent_validation_required=True)
        options.update(overrides)
        return context.gate(fixture.task_id, **options)

    def unchanged(self, fixture, before):
        self.assertEqual(fixture.control_events(), before)
        self.assertEqual(sum(event["event_type"] == "handoff_activated"
                             for event in before), 1)

    def test_c01_no_independent_resolver_blocks_after_successful_handoff(self):
        fixture = self.fixture()
        before = self.activate(fixture)
        self.assertTrue(self.gate(fixture)["passed"])
        result = self.gate(fixture, validation_resolver=None)
        self.assertFalse(result["passed"], result)
        self.unchanged(fixture, before)

    def test_c02_no_rule_runtime_blocks_and_restoration_passes(self):
        fixture = self.fixture()
        before = self.activate(fixture)
        result = self.gate(fixture, rule_runtime=None)
        self.assertFalse(result["passed"], result)
        self.assertTrue(self.gate(fixture)["passed"])
        self.unchanged(fixture, before)

    def test_c03_empty_evidence_is_not_replaced_with_default(self):
        fixture = self.fixture()
        before = self.activate(fixture)
        result = self.gate(fixture, evidence_map={})
        self.assertFalse(result["passed"], result)
        self.assertTrue(self.gate(fixture)["passed"])
        self.unchanged(fixture, before)

    def test_c04_dirty_truth_survives_handoff(self):
        fixture = self.fixture()
        context.mark_truth_sources_dirty(
            fixture.task_id, change_kind="implementation-change", actor="publisher",
            reason="known source needs readback; handoff preserves this blocker",
            base_dir=fixture.base_dir)
        fixture.record["event_cursor"] = fixture.control_events()[-1]["event_id"]
        before = self.activate(fixture)
        result = self.gate(fixture)
        self.assertFalse(result["passed"], result)
        self.unchanged(fixture, before)


if __name__ == "__main__":
    unittest.main()
