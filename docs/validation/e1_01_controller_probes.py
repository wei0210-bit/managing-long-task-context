"""Controller-owned synthetic regressions; no production files or host actions.

Run from repository root:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_01_controller_probes.py -v
"""

import json
import unittest

import managing_long_task_context as context
import test_handoff_protocol as fixtures


class ControllerReadOnlyRegressions(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HandoffProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.verifier, self.task_root = self.fixture._materialize_prepared_handoff()

    def observe(self):
        f = self.fixture
        return context.validate_handoff(
            f.task_id, base_dir=f.base_dir, workspace_root=f.workspace,
            package_root=f.package, handoff_id=f.handoff_id,
            handoff_verifier=self.verifier,
        )

    def replace_events(self, mutate):
        path = self.task_root / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        mutate(events)
        path.write_text("".join(json.dumps(event) + "\n" for event in events))

    def test_contract_version_type_is_not_coerced(self):
        path = self.task_root / "handoff" / f"{self.fixture.handoff_id}.json"
        record = json.loads(path.read_text())
        record["contract_version"] = 1.0
        digest = fixtures._canonical_sha256(record)
        path.write_text(json.dumps(record))
        self.replace_events(lambda events: events[-1]["payload"].update(record_sha256=digest))
        self.verifier.expected.update(contract_version=1.0, record_sha256=digest)
        report = self.observe()
        self.assertNotEqual(report["check_status"], "pass", report)

    def test_final_callback_cannot_leave_changed_evidence_passing(self):
        original = self.verifier.verify
        def mutate_after_verifying(request):
            result = original(request)
            self.verifier.content_path.write_text("changed during final check\n")
            return result

        self.verifier.verify = mutate_after_verifying
        report = self.observe()
        self.assertNotEqual(report["check_status"], "pass", report)

    def test_event_envelope_and_payload_types_must_agree(self):
        self.replace_events(lambda events: events[-1].update(event_type="handoff_activated"))
        report = self.observe()
        self.assertNotEqual(report["check_status"], "pass", report)

    def test_current_contract_must_match_its_published_event(self):
        self.replace_events(lambda events: events[0]["payload"].update(integrity_digest="sha256:" + "0" * 64))
        report = self.observe()
        self.assertNotEqual(report["check_status"], "pass", report)

    def test_unknown_authorization_stays_unknown(self):
        original = self.verifier.verify

        def unknown_authorization(request):
            result = original(request)
            result["authorization_status"] = "unknown"
            return result

        self.verifier.verify = unknown_authorization
        report = self.observe()
        self.assertEqual(report["check_status"], "unknown", report)

    def test_malformed_verifier_reference_returns_unknown_not_exception(self):
        original = self.verifier.verify

        def malformed_result(request):
            result = original(request)
            result["verification_refs"] = [{"ref_id": []}]
            return result

        self.verifier.verify = malformed_result
        report = self.observe()
        self.assertEqual(report["check_status"], "unknown", report)

    def test_prepare_cannot_claim_a_different_expected_generation(self):
        self.replace_events(lambda events: events[-1]["payload"].update(expected_controller_generation=900))
        report = self.observe()
        self.assertNotEqual(report["check_status"], "pass", report)

    def test_duplicate_event_fields_cannot_choose_the_last_claim(self):
        path = self.task_root / "events.jsonl"
        lines = path.read_text().splitlines()
        event = json.loads(lines[-1])
        line = json.dumps(event, separators=(",", ":"))
        needle = '"controller_generation":7'
        self.assertEqual(line.count(needle), 1, "fault injection prerequisite")
        lines[-1] = line.replace(needle, '"controller_generation":900,"controller_generation":7')
        path.write_text("\n".join(lines) + "\n")
        report = self.observe()
        self.assertEqual(report["check_status"], "unknown", report)

    def test_another_activation_cannot_leave_old_generation_passing(self):
        path = self.task_root / "events.jsonl"
        event = json.loads(path.read_text().splitlines()[-1])
        event.update(event_id="EV-000000000099", event_type="handoff_activated")
        event["payload"].update(type="handoff_activated", handoff_id="HO-OTHER", request_id="REQ-OTHER", controller_generation=8)
        with path.open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        report = self.observe()
        self.assertEqual(report["check_status"], "unknown", report)

    def test_local_file_uri_with_encoded_space_is_readable(self):
        new_path = self.verifier.content_path.with_name("basis evidence.txt")
        new_path.write_text(self.verifier.content_path.read_text())
        self.verifier.content_path = new_path
        path = self.task_root / "handoff" / f"{self.fixture.handoff_id}.json"
        record = json.loads(path.read_text())
        basis_id = record["basis_refs"][0]["ref_id"]
        record["basis_refs"][0]["uri"] = new_path.as_uri()
        digest = _canonical_sha256_for_probe(record)
        path.write_text(json.dumps(record))

        def update_event(events):
            events[-1]["payload"]["record_sha256"] = digest
            for ref in events[-1]["payload"]["verification_refs"]:
                if ref["ref_id"] == basis_id:
                    ref["uri"] = new_path.as_uri()

        self.replace_events(update_event)
        self.verifier.expected["record_sha256"] = digest
        for ref in self.verifier.verification_refs:
            if ref["ref_id"] == basis_id:
                ref["uri"] = new_path.as_uri()
        report = self.observe()
        self.assertEqual(report["check_status"], "pass", report)


def _canonical_sha256_for_probe(record):
    return fixtures._canonical_sha256(record)


if __name__ == "__main__":
    unittest.main()
