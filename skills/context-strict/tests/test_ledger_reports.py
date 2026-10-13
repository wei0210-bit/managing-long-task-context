"""The shared ledger reports uncertainty without taking control of execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import managing_long_task_context as context


class LedgerReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name) / 'context'
        self.contract = {'task_id': 'LEDGER', 'version': 1, 'issued_by': 'publisher',
            'issued_at': '2026-10-14T00:00:00Z', 'objective': 'Record the agreement',
            'scope': [], 'out_of_scope': [], 'constraints': [],
            'acceptance_criteria': [{'id': 'AC-1', 'criterion': 'Check the result',
                'required_evidence': ['file'], 'independent_validation_required': True}]}

    def publish(self):
        return context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)

    def test_old_independence_requirement_is_recorded_without_enforcement(self):
        sealed = self.publish()
        self.assertTrue(sealed['acceptance_criteria'][0]['independent_validation_required'])

    def test_all_stages_report_missing_evidence_without_callbacks_or_writes(self):
        self.publish()
        before = {p.name: p.read_bytes() for p in (self.base / 'LEDGER').iterdir() if p.is_file()}
        handler = Mock(side_effect=AssertionError('execution callback must not run'))
        for stage in ('release', 'resume', 'handoff', 'completion'):
            report = context.gate('LEDGER', stage=stage, base_dir=self.base, emit=False,
                resolvers={'file': handler}, verifiers={'file': handler})
            self.assertTrue(report['read_only'])
            self.assertFalse(report['blocking'])
            self.assertEqual(report['decision'], 'unknown')
            self.assertIn('file', report['criteria']['AC-1']['missing_evidence_types'])
        handler.assert_not_called()
        after = {p.name: p.read_bytes() for p in (self.base / 'LEDGER').iterdir() if p.is_file()}
        self.assertEqual(before, after)
        item = context.record('LEDGER', statement='Work may continue', item_type='observation',
            actor='worker', source='original', base_dir=self.base)
        self.assertEqual(item['statement'], 'Work may continue')

    def test_missing_store_is_diagnostic_and_does_not_create_it(self):
        report = context.gate('MISSING', stage='completion', base_dir=self.base, emit=False)
        self.assertEqual(report['decision'], 'unknown')
        self.assertFalse(report['blocking'])
        self.assertTrue(report['errors'])
        self.assertFalse(self.base.exists())

    def test_overflow_returns_packet_and_diagnostics(self):
        self.publish()
        context.record('LEDGER', statement='detail' * 2000, item_type='observation', actor='worker',
            source='original', metadata={'required': True}, base_dir=self.base)
        packet = context.brief('LEDGER', max_chars=100, base_dir=self.base)
        self.assertIsNotNone(packet['diagnostics']['overflow'])
        self.assertEqual(packet['task_id'], 'LEDGER')

    def test_control_apis_are_absent(self):
        for name in ('prepare_handoff', 'activate_handoff', 'cancel_handoff', 'handoff_status'):
            self.assertFalse(hasattr(context, name), name)

    def test_bound_resume_without_identity_returns_available_ledger(self):
        self.publish()
        result = context.bind(self.base).checked_resume('LEDGER')
        self.assertEqual(result['diagnostic']['status'], 'unknown')
        self.assertIn('BINDING_MISSING', result['diagnostic']['codes'])
        self.assertEqual(result['context']['task_id'], 'LEDGER')
        self.assertFalse(result['resume_gate']['blocking'])
        self.assert_observational_next_action(result['diagnostic'])

    def assert_observational_next_action(self, diagnostic):
        action = diagnostic['next_action']
        self.assertIsInstance(action, str)
        self.assertTrue(action.strip())
        self.assertNotRegex(action.lower(), r'\b(resume|continue|stop|block|proceed|allow|permit)\b')

    def test_public_resume_reports_identity_mismatch_with_available_ledger(self):
        self.publish()
        # This existing directory is outside the loaded package: a real identity
        # mismatch, independent of whether these tests run in a built package.
        workspace = Path(self.temporary.name)
        client = context.bind(self.base, package_root=workspace, workspace_root=workspace)
        results = {
            'bound': client.checked_resume('LEDGER'),
            'module': context.checked_resume('LEDGER', package_root=workspace,
                workspace_root=workspace, base_dir=self.base),
        }
        for entry, result in results.items():
            with self.subTest(entry=entry):
                self.assertEqual(result['diagnostic']['status'], 'fail')
                self.assertIn('RUNTIME_PATH_MISMATCH', result['diagnostic']['codes'])
                self.assertEqual(result['context']['task_id'], 'LEDGER')
                self.assertFalse(result['resume_gate']['blocking'])
                self.assert_observational_next_action(result['diagnostic'])

    def test_module_resume_without_binding_reports_unknown_with_available_ledger(self):
        self.publish()
        result = context.checked_resume('LEDGER', package_root=Path(__file__).resolve().parents[1],
            workspace_root=Path(self.temporary.name), base_dir=self.base)
        self.assertEqual(result['diagnostic']['status'], 'unknown')
        self.assertIn('BINDING_MISSING', result['diagnostic']['codes'])
        self.assertEqual(result['context']['task_id'], 'LEDGER')
        self.assertFalse(result['resume_gate']['blocking'])
        self.assert_observational_next_action(result['diagnostic'])

    def test_expired_evidence_is_reported_and_remains_unverified(self):
        self.publish()
        evidence = {'evidence_id': 'OLD', 'kind': 'file', 'locator': 'original.json',
                    'generated_at': '2000-01-01T00:00:00Z', 'expires_at': '2000-01-02T00:00:00Z'}
        report = context.gate('LEDGER', stage='completion', base_dir=self.base, emit=False,
                              evidence_map={'AC-1': {'evidence': [evidence]}})
        observed = report['criteria']['AC-1']['evidence_results'][0]
        self.assertEqual(observed['status'], 'unknown')
        self.assertNotEqual(observed['checks']['integrity_and_freshness']['status'], 'pass')
        self.assertFalse(report['blocking'])


if __name__ == '__main__':
    unittest.main()
