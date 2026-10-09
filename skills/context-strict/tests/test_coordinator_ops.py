"""CLI scenarios using real sealed contracts and isolated Git repositories."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import managing_long_task_context as context

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/coordinator_ops.py'
COMMAND = 'python3 -m unittest fixture'


class CoordinatorOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package_temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.package_temp.cleanup)
        cls.package = Path(cls.package_temp.name) / 'strict'
        subprocess.run([sys.executable, str(ROOT / 'scripts/skill_package.py'), 'build',
            '--source', str(ROOT), '--destination', str(cls.package), '--source-revision', 'test:ops'],
            check=True, capture_output=True, text=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Tests')
        self.git('config', 'user.email', 'tests@example.invalid')
        (self.root / '.gitignore').write_text('.prime/\n.context-reports/\n.githooks/\n.gitattributes\n')
        (self.root / 'code.py').write_text('print(1)\n')
        self.git('add', '.gitignore', 'code.py')
        self.git('commit', '-qm', 'fixture')
        branch = self.git('symbolic-ref', '--short', 'HEAD').strip()
        self.git('branch', 'fixture-upstream')
        self.git('config', 'branch.' + branch + '.remote', '.')
        self.git('config', 'branch.' + branch + '.merge', 'refs/heads/fixture-upstream')
        self.store = self.root / '.prime/context'
        self.task = 'OPS'
        self.publish(self.task)
        self.logs = self.root / '.context-reports/logs'
        self.logs.mkdir(parents=True)
        (self.logs / 'unit.log').write_text('OK\n')
        (self.logs / 'unit.exit').write_text('0\n')
        self.report = self.logs / 'worker.json'
        self.report.write_text(json.dumps({'orca_dispatch_id': 'ctx_test', 'deferred_suggestions': [
            {'statement': 'later one'}, {'statement': 'later two'}]}))

    def git(self, *arguments):
        return subprocess.run(['git', '-C', str(self.root), *arguments], check=True,
                              capture_output=True, text=True).stdout

    def publish(self, task):
        return context.publish_contract({
            'schema': 1, 'task_id': task, 'version': 1, 'issued_by': 'publisher',
            'issued_at': '2026-10-08T00:00:00Z', 'authorized_approvers': [], 'workspace_root': '.',
            'objective': 'Exercise coordinator operations', 'scope': ['code.py'],
            'out_of_scope': [], 'constraints': [], 'required_capabilities': ['evidence-handlers/v1'],
            'evidence_handlers': {'schema': 'evidence-handlers/v1', 'types': {'worker-report': {
                'resolver_capability': 'project:worker-report/v1',
                'verifier_capability': 'project:worker-report-claim/v1'}}},
            'acceptance_criteria': [{
                'id': name, 'criterion': 'Outputs verified', 'required_evidence_types': ['worker-report'],
                'worker_report_claim': {'commands': [COMMAND]}, 'required_scope': {}, 'required_hops': [],
                'required_delivery_types': [], 'independent_validation_required': False,
            } for name in ('AC-01', 'AC-02')],
        }, confirmed_by='publisher', base_dir=self.store)

    def run_cli(self, command, *arguments, expected=0, cwd=None):
        result = subprocess.run([sys.executable, str(SCRIPT), command, '--store', str(self.store),
            '--task', self.task, *map(str, arguments)], cwd=cwd or self.root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(self.package / 'src')})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        return json.loads(result.stdout)

    def items(self, task=None):
        return json.loads((self.store / (task or self.task) / 'snapshot.json').read_text())['items']

    def ingest(self, **kwargs):
        return self.run_cli('ingest', '--report', self.report, '--dispatch', 'ctx_test',
                            '--statement', 'worker report received', **kwargs)

    def accept(self, *extra, expected=0):
        return self.run_cli('accept', '--workspace', self.root, '--package-root', self.package,
            '--logs-dir', self.logs, '--check', 'unit=' + COMMAND, '--watched-path', 'code.py',
            '--recorded-by', 'coordinator', *extra, expected=expected)

    def test_ingest_twice_deduplicates_main_and_suggestions(self):
        self.ingest()
        before = (self.store / self.task / 'events.jsonl').read_bytes()
        self.ingest()
        self.assertEqual(before, (self.store / self.task / 'events.jsonl').read_bytes())
        items = list(self.items().values())
        self.assertEqual(sum(i['metadata'].get('role') == 'report-ingest' for i in items), 1)
        self.assertEqual(sorted(i['metadata']['report_item'] for i in items if 'report_item' in i['metadata']), [1, 2])
        digest = hashlib.sha256(self.report.read_bytes()).hexdigest()
        self.assertTrue(all(i['metadata']['report_sha256'] == digest for i in items))

    def test_ingest_repairs_missing_sequence_without_repeating_existing(self):
        context.record(self.task, statement='existing main', item_type='observation', actor='coordinator',
            source='fixture', metadata={'role': 'report-ingest', 'orca_dispatch_id': 'ctx_test'}, base_dir=self.store)
        context.record(self.task, statement='existing second', item_type='observation', actor='coordinator',
            source='fixture', metadata={'deferred': True, 'orca_dispatch_id': 'ctx_test', 'report_item': 2}, base_dir=self.store)
        self.ingest()
        self.assertEqual(len(self.items()), 3)
        self.assertEqual(sum(i['statement'] == 'existing second' for i in self.items().values()), 1)

    def test_suggestions_route_to_explicit_task_and_mark_unspecified(self):
        self.publish('OTHER')
        self.report.write_text(json.dumps({'orca_dispatch_id': 'ctx_test', 'deferred_suggestions': [
            {'task_id': 'OTHER', 'statement': 'other task'}, 'current task']}))
        self.ingest()
        self.ingest()
        self.assertEqual(len(self.items('OTHER')), 1)
        item = next(iter(self.items('OTHER').values()))
        self.assertTrue(item['metadata']['deferred'])
        self.assertEqual(item['metadata']['report_item'], 1)
        item = next(i for i in self.items().values() if i['metadata'].get('deferred'))
        self.assertTrue(item['metadata']['report_task_unspecified'])

    def test_settle_updates_only_blocking_report_ingest_and_preserves_metadata(self):
        self.run_cli('ingest', '--report', self.report, '--dispatch', 'ctx_test', '--statement', 'blocked',
                     '--blocking', '--verdict', 'fail')
        unrelated = context.record(self.task, statement='unrelated blocker', item_type='observation', actor='coordinator',
            source='fixture', metadata={'blocking': True, 'role': 'other'}, base_dir=self.store)
        self.run_cli('settle', '--resolved-by', 'review-verified')
        items = list(self.items().values())
        main = next(i for i in items if i['metadata'].get('role') == 'report-ingest')
        self.assertFalse(main['metadata']['blocking'])
        self.assertEqual(main['metadata']['resolved_by'], 'review-verified')
        self.assertEqual(main['metadata']['verdict'], 'fail')
        self.assertTrue(self.items()[unrelated['id']]['metadata']['blocking'])
        before = (self.store / self.task / 'events.jsonl').read_bytes()
        self.run_cli('settle', '--resolved-by', 'review-verified')
        self.assertEqual(before, (self.store / self.task / 'events.jsonl').read_bytes())

    def test_checkpoint_requires_evidence(self):
        self.run_cli('checkpoint', '--phase', 'review', '--completed', 'reviewed', '--next-action', 'accept', expected=2)

    def test_checkpoint_records_repeated_evidence_and_blockers(self):
        self.run_cli('checkpoint', '--phase', 'review', '--completed', 'reviewed', '--evidence', 'file:one',
            '--evidence', 'file:two', '--blocker', 'pending', '--next-action', 'accept')
        snapshot = json.loads((self.store / self.task / 'snapshot.json').read_text())
        checkpoint = snapshot['latest_checkpoint']
        self.assertEqual(checkpoint['evidence_added'], ['file:one', 'file:two'])
        self.assertEqual(checkpoint['blockers'], ['pending'])

    def test_accept_real_gate_passes_and_covers_every_criterion(self):
        result = self.accept()
        self.assertEqual(result['decision'], 'pass', result)
        records = (self.store / self.task / 'acceptance-records.jsonl').read_text().splitlines()
        self.assertEqual(len(records), 1)
        record = json.loads(records[0])
        self.assertEqual(record['decision'], 'pass')
        self.assertEqual([c['criterion_id'] for c in record['criteria']], ['AC-01', 'AC-02'])
        report = json.loads(Path(result['report_path']).read_text())
        self.assertEqual(report['checks'][0]['output_sha256'], hashlib.sha256(b'OK\n').hexdigest())
        self.assertEqual(report['code_revision']['commit'], self.git('rev-parse', 'HEAD').strip())
        snapshot = json.loads((self.store / self.task / 'snapshot.json').read_text())
        self.assertEqual(snapshot['latest_checkpoint']['phase'], 'acceptance')

    def test_accept_failed_check_cannot_pass(self):
        (self.logs / 'unit.exit').write_text('1\n')
        result = self.accept(expected=1)
        self.assertNotEqual(result['decision'], 'pass')
        self.assertNotEqual(json.loads((self.store / self.task / 'acceptance-records.jsonl').read_text())['decision'], 'pass')

    def test_accept_uses_explicit_workspace_from_another_cwd(self):
        result = self.run_cli('accept', '--workspace', self.root, '--package-root', self.package,
            '--logs-dir', self.logs, '--check', 'unit=' + COMMAND, '--watched-path', 'code.py',
            '--recorded-by', 'coordinator', cwd=self.package)
        self.assertEqual(result['decision'], 'pass')

    def test_accept_failed_extra_unsealed_check_cannot_pass(self):
        (self.logs / 'extra.log').write_text('failed\n')
        (self.logs / 'extra.exit').write_text('2\n')
        result = self.accept('--check', 'extra=unsealed command', expected=1)
        self.assertNotEqual(result['decision'], 'pass')
        self.assertNotEqual(json.loads((self.store / self.task / 'acceptance-records.jsonl').read_text())['decision'], 'pass')

    def test_accept_dirty_tracked_or_untracked_workspace_cannot_pass(self):
        for path in ('code.py', 'untracked.txt'):
            with self.subTest(path=path):
                (self.root / path).write_text('dirty\n')
                self.assertNotEqual(self.accept(expected=1)['decision'], 'pass')
                records = (self.store / self.task / 'acceptance-records.jsonl').read_text().splitlines()
                self.assertTrue(all(json.loads(r)['decision'] != 'pass' for r in records))

    def test_accept_missing_command_cannot_pass(self):
        result = self.run_cli('accept', '--workspace', self.root, '--package-root', self.package, '--logs-dir', self.logs,
            '--check', 'unit=different command', '--watched-path', 'code.py', '--recorded-by', 'coordinator', expected=1)
        self.assertNotEqual(result['decision'], 'pass')

    def test_invalid_arguments_and_logs_exit_two_without_acceptance_write(self):
        for check in ('../unit=' + COMMAND, 'unit', '=command'):
            self.accept('--check', check, expected=2)
        (self.logs / 'unit.exit').write_text('not-an-exit-code\n')
        self.accept(expected=2)
        self.assertFalse((self.store / self.task / 'acceptance-records.jsonl').exists())

    def test_relative_report_and_mismatched_dispatch_rejected(self):
        self.run_cli('ingest', '--report', 'worker.json', '--dispatch', 'ctx_test', '--statement', 'report', expected=2)
        self.run_cli('ingest', '--report', self.report, '--dispatch', 'different', '--statement', 'report', expected=2)
        self.assertEqual(len(self.items()), 0)



    def expose_validator_exclusions(self):
        # Keep only report evidence ignored; do not hide the validator's exclusions.
        (self.root / '.gitignore').write_text('.context-reports/\n')
        self.git('add', '.gitignore')
        self.git('commit', '-qm', 'expose validator exclusions')

    def test_accept_unignored_validator_exclusions_can_pass(self):
        self.expose_validator_exclusions()
        self.assertIn('.prime/', self.git('status', '--porcelain'))
        result = self.accept()
        self.assertEqual(result['decision'], 'pass', result)
        self.assertFalse(json.loads(Path(result['report_path']).read_text())['code_revision']['dirty'])

    def test_accept_unignored_near_exclusion_paths_cannot_pass(self):
        self.expose_validator_exclusions()
        for path in ('.githooks/other', '.gitattributes.bak'):
            with self.subTest(path=path):
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('dirty\n')
                self.assertNotEqual(self.accept(expected=1)['decision'], 'pass')
                # Track this probe before the next iteration, so it cannot mask
                # an incorrect exclusion of the second path.
                self.git('add', path)
                self.git('commit', '-qm', 'track completed dirty probe')

    def test_actor_written_to_ingest_settle_and_checkpoint_events(self):
        self.run_cli('ingest', '--report', self.report, '--dispatch', 'ctx_test',
            '--statement', 'blocked', '--blocking', '--actor', 'executor-alice')
        self.assertTrue(all(i['actor'] == 'executor-alice' for i in self.items().values()))
        self.run_cli('settle', '--resolved-by', 'review', '--actor', 'reviewer-bob')
        self.run_cli('checkpoint', '--phase', 'review', '--completed', 'done',
            '--evidence', 'file:one', '--next-action', 'accept', '--actor', 'coordinator-carol')
        snapshot = json.loads((self.store / self.task / 'snapshot.json').read_text())
        self.assertEqual(snapshot['latest_checkpoint']['actor'], 'coordinator-carol')
        events = [json.loads(line) for line in (self.store / self.task / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(events[-2]['actor'], 'reviewer-bob')
        self.assertEqual(events[-1]['actor'], 'coordinator-carol')

    def test_blank_actor_rejected_without_writing_events(self):
        before = (self.store / self.task / 'events.jsonl').read_bytes()
        for command, arguments in [
            ('ingest', ['--report', self.report, '--dispatch', 'ctx_test', '--statement', 'report']),
            ('settle', ['--resolved-by', 'review']),
            ('checkpoint', ['--phase', 'review', '--completed', 'done', '--evidence', 'file:one', '--next-action', 'accept']),
        ]:
            with self.subTest(command=command):
                self.run_cli(command, *arguments, '--actor', ' \t ', expected=2)
        self.assertEqual(before, (self.store / self.task / 'events.jsonl').read_bytes())

    def test_accept_top_level_with_trailing_space_reaches_next_validation(self):
        # v2 checks this script's boundary; the underlying API still strips paths.
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('coordinator_ops_path_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = self.root / 'workspace '
        root.mkdir()
        subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True, capture_output=True)
        args = module.parser().parse_args(['accept', '--store', str(self.store), '--task', self.task,
            '--workspace', str(root), '--package-root', str(self.package), '--logs-dir', str(root),
            '--check', 'unit=' + COMMAND, '--recorded-by', 'coordinator'])
        class ReachedContractRead(Exception):
            pass
        with patch.object(module, 'read_json', side_effect=ReachedContractRead):
            with self.assertRaises(ReachedContractRead):
                module.accept(args)

    def test_accept_subdirectory_workspace_rejected(self):
        child = self.root / 'subdirectory'
        child.mkdir()
        self.run_cli('accept', '--workspace', child, '--package-root', self.package,
            '--logs-dir', self.logs, '--check', 'unit=' + COMMAND,
            '--recorded-by', 'coordinator', expected=2)
        self.assertFalse((self.store / self.task / 'acceptance-records.jsonl').exists())

    def test_accept_missing_clean_validator_exits_two(self):
        # Load the actual built package, then simulate an older package API.
        bootstrap = ('import runpy, sys; '
            'import managing_long_task_context.worker_report as w; '
            'del w._revision_is_clean; '
            'sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")')
        result = subprocess.run([sys.executable, '-c', bootstrap, str(SCRIPT), 'accept',
            '--store', str(self.store), '--task', self.task, '--workspace', str(self.root),
            '--package-root', str(self.package), '--logs-dir', str(self.logs),
            '--check', 'unit=' + COMMAND, '--recorded-by', 'coordinator'],
            capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(self.package / 'src')})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('clean', json.loads(result.stdout)['error'])
        self.assertFalse((self.store / self.task / 'acceptance-records.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
