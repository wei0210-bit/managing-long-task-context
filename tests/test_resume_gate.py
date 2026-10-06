from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ResumeFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_package = tempfile.TemporaryDirectory()
        cls.package = ROOT if (ROOT / 'skill-manifest.json').exists() else Path(cls.temp_package.name) / 'package'
        if cls.package != ROOT:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/skill_package.py'), 'build',
                                     '--source', str(ROOT / 'skills/context-strict' if (ROOT / 'skills/context-strict').is_dir() else ROOT), '--destination', str(cls.package),
                                     '--source-revision', 'local:resume-tests'], capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.digest = hashlib.sha256((cls.package / 'skill-manifest.json').read_bytes()).hexdigest()
        name = 'resume_fixture_' + cls.__name__
        spec = importlib.util.spec_from_file_location(name, cls.package / 'src/managing_long_task_context/__init__.py',
                            submodule_search_locations=[str(cls.package / 'src/managing_long_task_context')])
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[name] = cls.module
        spec.loader.exec_module(cls.module)
        cls.runtime = sys.modules[name + '.runtime_identity']
        cls.core = sys.modules[name + '._identity_core']
        cls.addClassCleanup(cls.temp_package.cleanup)
        cls.addClassCleanup(lambda: [sys.modules.pop(key, None) for key in list(sys.modules) if key == name or key.startswith(name + '.')])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name) / 'workspace'
        self.workspace.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.workspace)], check=True)
        self.base = self.workspace / '.prime/context'
        self.task = 'RESUME'
        self.contract = {'schema': 1, 'task_id': self.task, 'version': 1, 'issued_by': 'publisher',
                         'issued_at': '2026-10-06T00:00:00Z', 'authorized_approvers': [],
                         'workspace_root': '.', 'objective': 'Resume guarded work', 'scope': ['resume'],
                         'out_of_scope': [], 'constraints': [],
                         'acceptance_criteria': [{'id': 'AC-01', 'criterion': 'Gate works', 'required_evidence_types': ['file']}]}
        self.publish()
        self.bind()

    def publish(self):
        self.module.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)

    def bind(self):
        report = self.core.init_binding(package_root=self.package, expected_manifest_sha256=self.digest,
                                       context_root=self.base, workspace_root=self.workspace, task_id=self.task)
        self.assertEqual(report['status'], 'pass', report)

    def resume(self, **kwargs):
        return self.module.checked_resume(self.task, package_root=self.package,
                    workspace_root=self.workspace, base_dir=self.base, **kwargs)

    def record(self, identifier='ITEM', **kwargs):
        return self.module.record(self.task, item_id=identifier, statement='Observed ' + identifier,
                item_type=kwargs.pop('item_type', 'observation'), actor='observer',
                source={'kind': 'tool', 'ref': 'probe'}, base_dir=self.base, **kwargs)

    def command(self, script='context_doctor.py', expected=0, text=False):
        argv = [sys.executable, str(self.package / 'scripts' / script)]
        if script == 'context_doctor.py':
            argv += ['resume']
        argv += ['--package-root', str(self.package), '--context-root', str(self.base),
                 '--workspace-root', str(self.workspace), '--task-id', self.task]
        if script == 'context_status.py' and not text:
            argv += ['--json']
        result = subprocess.run(argv, env={**os.environ, 'PYTHONPATH': str(self.package / 'src')},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout if text else json.loads(result.stdout)

    def handler_contract(self):
        self.contract.update(version=2, required_capabilities=['evidence-handlers/v1'], evidence_handlers={
            'schema': 'evidence-handlers/v1', 'types': {'file': {
                'resolver_capability': 'builtin:file/v1', 'verifier_capability': 'project:file-claim/v1'}}})
        self.publish()

    def check_status(self, result, name):
        return next(c['status'] for c in result['diagnostic']['checks'] if c['name'] == name)


class ResumeGateTests(ResumeFixture):
    def test_blocker_returns_context_and_failed_gate(self):
        self.record(metadata={'blocking': True})
        r = self.resume()
        self.assertIsNotNone(r['context'])
        self.assertIn('ITEM', r['context']['prompt'])
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertIn('RESUME_GATE_FAILED', r['diagnostic']['codes'])
        self.assertIn('blocking context item remains: ITEM', r['resume_gate']['errors'])
        self.assertIn('解除该阻塞', r['diagnostic']['next_action'])
        self.assertIsNotNone(self.command(expected=1)['context'])

    def test_stale_ttl_fact_returns_context(self):
        with patch.object(self.module, '_now', return_value=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()):
            self.record(item_type='verified-fact', evidence=['probe:fact'], verification_method='probe',
                        scope={'service': 'test'}, mutable=True, ttl_hours=1)
        r = self.resume()
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertIn('RESUME_GATE_FAILED', r['diagnostic']['codes'])
        self.assertIn('ITEM', r['context']['stale_items'])
        self.assertIn('re-observe', r['context']['prompt'])
        self.assertIn('update_item', r['diagnostic']['next_action'])

    def test_stale_without_ttl_requires_superseding(self):
        self.record(item_type='verified-fact', evidence=['probe:fact'], verification_method='probe',
                    scope={'service': 'test'}, mutable=True)
        r = self.resume()
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertIn('supersedes', r['diagnostic']['next_action'])
        self.assertIn('ttl_hours', r['diagnostic']['next_action'])

    def test_clean_task_and_cli_pass(self):
        r = self.resume()
        self.assertEqual(r['diagnostic']['status'], 'pass')
        self.assertTrue(r['resume_gate']['passed'])
        self.assertIn('resume_gate', self.command())

    def test_absent_handlers_are_not_run_and_raw_report_preserved(self):
        self.handler_contract()
        r = self.resume()
        self.assertEqual(self.check_status(r, 'resume_handlers'), 'not_run')
        self.assertEqual(r['diagnostic']['status'], 'pass')
        self.assertTrue(any('capability unavailable: expected ' in e for e in r['resume_gate']['errors']))
        self.assertFalse(r['resume_gate']['passed'])

    def test_capability_mismatch_is_failure(self):
        self.handler_contract()
        def resolver(*args, **kwargs):
            return {}
        r = self.resume(resolvers={'file': {'capability': 'builtin:file/v2', 'handler': resolver}})
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertTrue(any('capability mismatch' in e for e in r['resume_gate']['errors']))

    def test_unavailable_exemption_never_removes_mismatch(self):
        unavailable = "evidence type 'file' runtime verifier capability unavailable: expected X"
        mismatch = "evidence type 'file' runtime resolver capability mismatch: expected X, got Y"
        checks = self.runtime._resume_error_checks(
            [unavailable, mismatch], [unavailable, mismatch], handlers_supplied=False)
        report = self.core._report(mode='identity', scope='task', checks=checks)
        self.assertEqual(report['status'], 'fail')
        handlers = next(c for c in checks if c['name'] == 'resume_handlers')
        gate = next(c for c in checks if c['name'] == 'resume_gate')
        self.assertEqual(handlers['status'], 'not_run')
        self.assertIn(unavailable, handlers['message'])
        self.assertNotIn(mismatch, handlers['message'])
        self.assertEqual(gate['status'], 'fail')
        self.assertIn(mismatch, gate['message'])

    def test_explicit_missing_handlers_are_failure(self):
        self.handler_contract()
        r = self.resume(verifiers={})
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertEqual(self.check_status(r, 'resume_gate'), 'fail')

    def test_missing_rule_runtime_is_unknown_and_cli_two(self):
        self.contract.update(version=2, required_capabilities=['rule-execution/v1'], rule_execution={
            'schema': 1, 'rules': [{'rule_id': 'dispatch-required', 'experience_ref': None,
            'severity': 'load-bearing', 'applies_at': ['resume'], 'trigger_id': 'modification',
            'checker_id': 'proof', 'checker_version': '1', 'observation_source_id': 'observer'}]})
        self.publish()
        r = self.resume()
        self.assertEqual(self.check_status(r, 'resume_rules'), 'unknown')
        self.assertEqual(r['diagnostic']['status'], 'unknown')
        self.assertIn('rule_runtime', r['diagnostic']['next_action'])
        self.assertEqual(self.command(expected=2)['diagnostic']['status'], 'unknown')

    def test_race_is_separate_and_does_not_downgrade_failure(self):
        original = self.module.gate
        def write_then_gate(*args, **kwargs):
            self.record()
            return original(*args, **kwargs)
        with patch.object(self.module, 'gate', side_effect=write_then_gate):
            r = self.resume()
        self.assertEqual(self.check_status(r, 'resume_race'), 'unknown')
        self.assertEqual(self.check_status(r, 'resume_gate'), 'pass')
        self.assertIn('RESUME_GATE_RACE', r['diagnostic']['codes'])
        def broken_snapshot(*args, **kwargs):
            self.record('SECOND')
            self.record('THIRD')
            p = self.base / self.task / 'snapshot.json'
            value = json.loads(p.read_text()); value['event_count'] -= 1
            p.write_text(json.dumps(value))
            return original(*args, **kwargs)
        with patch.object(self.module, 'gate', side_effect=broken_snapshot):
            r = self.resume()
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertEqual(self.check_status(r, 'resume_gate'), 'fail')
        self.assertEqual(self.check_status(r, 'resume_race'), 'unknown')

    def test_gate_exception_and_missing_events_are_unknown(self):
        with patch.object(self.module, 'gate', side_effect=OSError('unavailable')):
            r = self.resume()
        self.assertIsNotNone(r['context'])
        self.assertIn('RESUME_GATE_UNAVAILABLE', r['diagnostic']['codes'])
        with patch.object(self.module, 'gate', return_value={'passed': True, 'errors': [], 'warnings': [],
                                                           'contract_version': 1}):
            r = self.resume()
        self.assertIn('RESUME_RACE_UNCHECKED', r['diagnostic']['codes'])

    def test_status_missing_binding_shows_snapshot_and_independent_digest_placeholder(self):
        self.module.checkpoint(self.task, phase='review', completed=['done'], evidence_added=[],
                               next_action='review originals', actor='publisher', base_dir=self.base)
        for index in range(30):
            self.module.record(
                        self.task, item_id='LONG-'+str(index), item_type='observation', statement='x'*400,
                        actor='observer', source={'kind': 'tool', 'ref': 'probe'},
                        metadata={'orca_dispatch_id': 'ctx_a', 'report_item': index, 'deferred': True}, base_dir=self.base)
        self.record('MAIN', metadata={'orca_dispatch_id': 'ctx_a', 'role': 'report-ingest'})
        self.assertIn('omitted_ids', self.module.brief(self.task, base_dir=self.base))
        (self.base / self.task / 'context-binding.json').unlink()
        r = self.command('context_status.py', expected=2)
        self.assertEqual(len(r), 5)
        self.assertIn('init-binding', r['identity']['next_action'])
        self.assertIn('<从派工说明或接手文档取得的独立留存摘要>', r['identity']['next_action'])
        self.assertNotIn(self.digest, r['identity']['next_action'])
        self.assertEqual(r['checkpoint']['data']['phase'], 'review')
        self.assertEqual(r['dispatches']['data'], [{'orca_dispatch_id': 'ctx_a', 'main_item_ids': ['MAIN'], 'suggestion_count': 30}])
        self.assertFalse(r['checkpoint']['identity_verified'])
        self.assertIn('不可用', r['brief']['message'])

    def test_status_nondefault_root_and_text_five_sections(self):
        self.base = self.workspace / 'other-context'
        self.publish(); self.bind()
        r = self.command('context_status.py')
        self.assertIn('不是工作区默认位置', r['checkpoint']['message'])
        self.assertIn('不是工作区默认位置', r['dispatches']['message'])
        text = self.command('context_status.py', text=True)
        for section in ['身份', '恢复门禁', '最近检查点', '已入账的 Orca 派单', 'brief 正文']:
            self.assertIn(section, text)

    def test_status_nondefault_root_ignores_malformed_default_task(self):
        default_task = self.base / self.task
        self.base = self.workspace / 'other-context'
        self.publish(); self.bind()
        (default_task / 'events.jsonl').write_text('{}\n', encoding='utf-8')
        inputs = ['--package-root', str(self.package), '--context-root', str(self.base),
                  '--workspace-root', str(self.workspace), '--task-id', self.task]
        env = {**os.environ, 'PYTHONPATH': str(self.package / 'src')}
        doctor = subprocess.run(
            [sys.executable, str(self.package / 'scripts/context_doctor.py'), 'resume', *inputs],
            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)['diagnostic']['status'], 'pass')
        unavailable = '快照不可用（context root 不是工作区默认位置）'
        for json_output in (True, False):
            with self.subTest(json_output=json_output):
                result = subprocess.run(
                    [sys.executable, str(self.package / 'scripts/context_status.py'), *inputs,
                     *(['--json'] if json_output else [])],
                    env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, doctor.returncode, result.stdout + result.stderr)
                if json_output:
                    sections = json.loads(result.stdout)
                    self.assertEqual(set(sections),
                                     {'identity', 'resume_gate', 'checkpoint', 'dispatches', 'brief'})
                    for key in ('checkpoint', 'dispatches'):
                        self.assertIsNone(sections[key]['data'])
                        self.assertEqual(sections[key]['message'], unavailable)
                else:
                    self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('## ')][:5],
                                     ['## 身份', '## 恢复门禁', '## 最近检查点',
                                      '## 已入账的 Orca 派单', '## brief 正文'])
                    self.assertEqual(result.stdout.count(unavailable), 2)

    def test_capability_registered_in_identity_resume_and_package(self):
        self.assertIn('checked-resume-gate/v1', self.module.runtime_identity(package_root=self.package)['identity']['capabilities'])
        self.assertIn('checked-resume-gate/v1', self.resume()['diagnostic']['identity']['capabilities'])
        self.assertIn('checked-resume-gate/v1', json.loads((ROOT/'skill-package.json').read_text())['capabilities'])

    def test_conflict_winner_reactivated_then_passes(self):
        self.record('WINNER'); self.record('LOSER')
        self.module.update_item(self.task, 'WINNER', status='conflicted', conflict_reason='Probe disagreement', actor='publisher', base_dir=self.base)
        self.module.update_item(self.task, 'LOSER', status='conflicted', conflict_reason='Probe disagreement', actor='publisher', base_dir=self.base)
        r = self.resume()
        self.assertEqual(r['diagnostic']['status'], 'fail')
        self.assertIn('status="active"', r['diagnostic']['next_action'])
        self.module.update_item(self.task, 'LOSER', status='superseded', actor='publisher', base_dir=self.base)
        self.module.update_item(self.task, 'WINNER', status='active', actor='publisher', base_dir=self.base)
        self.assertEqual(self.resume()['diagnostic']['status'], 'pass')


class ReadOnlyEntryTests(ResumeFixture):
    def hashes(self):
        return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.base.rglob('*') if p.is_file()}

    def test_contract_tampering_still_raises_and_cli_blocks(self):
        p = self.base / self.task / 'task-contract.json'
        value = json.loads(p.read_text()); value['objective'] = 'tampered'
        p.chmod(0o644); p.write_text(json.dumps(value))
        with self.assertRaises(self.module.ContextError):
            self.resume()
        self.assertIn('RESUME_BLOCKED', self.command(expected=1)['diagnostic']['codes'])

    def test_brief_and_resume_preserve_files_on_readonly_store(self):
        self.record(metadata={'blocking': True})
        before = self.hashes()
        paths = list(self.base.rglob('*')) + [self.base]
        modes = {p: p.stat().st_mode & 0o777 for p in paths}
        try:
            for p in paths:
                p.chmod(0o555 if p.is_dir() else 0o444)
            self.assertIsNotNone(self.module.brief(self.task, base_dir=self.base))
            self.assertEqual(before, self.hashes())
            self.assertIsNotNone(self.resume()['context'])
            self.assertEqual(before, self.hashes())
        finally:
            for p, mode in modes.items(): p.chmod(mode)

    def test_status_preserves_files_on_readonly_store(self):
        before = self.hashes()
        paths = list(self.base.rglob('*')) + [self.base]
        modes = {p: p.stat().st_mode & 0o777 for p in paths}
        try:
            for p in paths: p.chmod(0o555 if p.is_dir() else 0o444)
            self.command('context_status.py')
            self.assertEqual(before, self.hashes())
        finally:
            for p, mode in modes.items(): p.chmod(mode)
