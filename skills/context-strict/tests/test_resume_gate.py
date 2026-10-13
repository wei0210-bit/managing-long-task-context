from __future__ import annotations

import hashlib
import argparse
import contextlib
import io
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
sys.path.insert(0, str(ROOT / 'src'))


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
        self.assertEqual(len(r), 6)
        self.assertEqual(r['acceptance']['status'], 'never_accepted')
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
        for section in ['身份', '账本健康', '最近检查点', '已入账的 Orca 派单', 'brief 正文', '验收']:
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
                                     {'identity', 'resume_gate', 'checkpoint', 'dispatches', 'brief', 'acceptance'})
                    for key in ('checkpoint', 'dispatches'):
                        self.assertIsNone(sections[key]['data'])
                        self.assertEqual(sections[key]['message'], unavailable)
                else:
                    self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('## ')][:5],
                                     ['## 身份', '## 账本健康', '## 最近检查点',
                                      '## 已入账的 Orca 派单', '## brief 正文'])
                    self.assertEqual(result.stdout.count(unavailable), 2)


    def assert_status_keeps_diagnostics_with_invalid_event(self, *, json_output):
        # F-002: a selected default store must retain resume diagnostics even
        # when rebuilding its snapshot fails on an invalid event envelope.
        self.record('BEFORE-CORRUPTION')
        with (self.base / self.task / 'events.jsonl').open('a', encoding='utf-8') as events:
            events.write('{}\n')
        doctor = self.command(expected=2)
        self.assertIsNotNone(doctor['context'])
        self.assertEqual(doctor['diagnostic']['status'], 'unknown')
        self.assertIn('LEDGER_HEALTH_UNKNOWN', doctor['diagnostic']['codes'])
        output = self.command('context_status.py', expected=2, text=not json_output)
        titles = ['身份', '账本健康', '最近检查点', '已入账的 Orca 派单', 'brief 正文', '验收']
        keys = ['identity', 'resume_gate', 'checkpoint', 'dispatches', 'brief', 'acceptance']
        if json_output:
            sections = output
        else:
            self.assertTrue(output.startswith('## 身份\n'), output)
            sections = {}
            remaining = output
            for index, (title, key) in enumerate(zip(titles, keys)):
                prefix = '## ' + title + '\n'
                self.assertTrue(remaining.startswith(prefix), remaining)
                remaining = remaining[len(prefix):]
                if index < 4:
                    payload, remaining = remaining.split('## ' + titles[index + 1] + '\n', 1)
                    sections[key] = json.loads(payload)
                    remaining = '## ' + titles[index + 1] + '\n' + remaining
                elif key == 'brief':
                    payload, remaining = remaining.split('## 验收\n', 1)
                    sections[key] = {'markdown': payload.rstrip('\n')}
                    remaining = '## 验收\n' + remaining
                else:
                    sections[key] = json.loads(remaining)
        self.assertEqual(set(sections), set(keys))
        for key in ('checkpoint', 'dispatches'):
            self.assertIsNone(sections[key]['data'])
            self.assertIn('快照不可用', sections[key]['message'])
            self.assertTrue(sections[key]['identity_verified'])
        for field in ('status', 'codes', 'next_action'):
            self.assertEqual(sections['identity'][field], doctor['diagnostic'][field])
        self.assertEqual(sections['resume_gate']['status'], 'unknown')
        self.assertEqual(sections['resume_gate']['report'], doctor['resume_gate'])
        self.assertEqual(sections['resume_gate']['next_action'], doctor['diagnostic']['next_action'])
        self.assertEqual(sections['brief']['markdown'].rstrip('\n'), doctor['context']['prompt'].rstrip('\n'))

    def test_status_invalid_default_event_keeps_five_json_sections(self):
        self.assert_status_keeps_diagnostics_with_invalid_event(json_output=True)

    def test_status_invalid_default_event_keeps_five_text_sections(self):
        self.assert_status_keeps_diagnostics_with_invalid_event(json_output=False)



class StatusIsolationTests(ResumeFixture):
    keys = ['identity', 'resume_gate', 'checkpoint', 'dispatches', 'brief', 'acceptance']
    titles = ['身份', '账本健康', '最近检查点', '已入账的 Orca 派单', 'brief 正文', '验收']

    def sections(self, output, json_output):
        if json_output:
            result = json.loads(output)
        else:
            result = {}
            for index, (key, title) in enumerate(zip(self.keys, self.titles)):
                prefix = '## ' + title + '\n'
                self.assertTrue(output.startswith(prefix), output)
                output = output[len(prefix):]
                if index < 4:
                    payload, output = output.split('## ' + self.titles[index + 1] + '\n', 1)
                    result[key] = json.loads(payload)
                    output = '## ' + self.titles[index + 1] + '\n' + output
                elif key == 'brief':
                    payload, output = output.split('## 验收\n', 1)
                    result[key] = {'markdown': payload.rstrip('\n')}
                    output = '## 验收\n' + output
                else:
                    result[key] = json.loads(output)
        self.assertEqual(set(result), set(self.keys))
        return result

    def inputs(self):
        return ['--package-root', str(self.package), '--context-root', str(self.base),
                '--workspace-root', str(self.workspace), '--task-id', self.task]

    def assert_real_case(self, *, metadata=None, dispatch=None, mixed=False, ledger=None):
        if ledger is not None:
            with (self.base / self.task / 'events.jsonl').open('a') as stream:
                stream.write(ledger + '\n')
        elif dispatch is not None:
            self.record('BAD', metadata={'orca_dispatch_id': dispatch})
            if mixed:
                self.record('GOOD', metadata={'orca_dispatch_id': 'ctx-good'})
        else:
            self.record('BAD')
            path = self.base / self.task / 'events.jsonl'
            events = [json.loads(line) for line in path.read_text().splitlines()]
            events[-1]['payload']['item']['metadata'] = metadata
            path.write_text(''.join(json.dumps(event) + '\n' for event in events))
            (self.base / self.task / 'snapshot.json').write_text(
                json.dumps(self.module._rebuild_snapshot(self.task, events)))
        env = {**os.environ, 'PYTHONPATH': str(self.package / 'src')}
        before = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        doctor = subprocess.run([sys.executable, str(self.package / 'scripts/context_doctor.py'),
                                 'resume', *self.inputs()], env=env, capture_output=True, text=True)
        diagnostic = json.loads(doctor.stdout)['diagnostic']
        for json_output in (False, True):
            with self.subTest(json_output=json_output):
                proc = subprocess.run([sys.executable, str(self.package / 'scripts/context_status.py'),
                                       *self.inputs(), *(['--json'] if json_output else [])],
                                      env=env, capture_output=True, text=True)
                sections = self.sections(proc.stdout, json_output)
                self.assertEqual(proc.returncode, doctor.returncode, proc.stderr)
                self.assertEqual(sections['identity']['status'], diagnostic['status'])
                self.assertEqual(sections['identity']['codes'], diagnostic['codes'])
                self.assertEqual(sections['resume_gate']['report'], json.loads(doctor.stdout)['resume_gate'])
                context_packet = json.loads(doctor.stdout)['context']
                if context_packet is None:
                    self.assertIsNone(sections['brief']['markdown'])
                else:
                    self.assertEqual(sections['brief']['markdown'].rstrip('\n'), context_packet['prompt'].rstrip('\n'))
                self.assertEqual(sections['dispatches']['status'], 'unavailable')
                self.assertIn('不可用', sections['dispatches']['message'])
                if ledger is not None:
                    self.assertEqual(sections['checkpoint']['status'], 'unavailable')
                    if ledger.startswith('[[['):
                        self.assertIsInstance(sections['checkpoint']['exception_type'], str)
                        self.assertTrue(sections['checkpoint']['exception_type'])
                    else:
                        self.assertEqual(sections['checkpoint']['exception_type'], 'AttributeError')
                else:
                    self.assertEqual(sections['dispatches']['skipped_count'], 1)
                    self.assertNotEqual(sections['checkpoint'].get('status'), 'unavailable')
                    self.assertEqual(sections['dispatches']['data'],
                                     [{'orca_dispatch_id': 'ctx-good', 'main_item_ids': ['GOOD'],
                                       'suggestion_count': 0}] if mixed else [])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_f003_dispatch_list(self):
        self.assert_real_case(dispatch=['ctx-bad'])

    def test_f004_dispatch_dict(self):
        self.assert_real_case(dispatch={'id': 'ctx-bad'})

    def test_f005_dispatch_mixed_types(self):
        self.assert_real_case(dispatch=7, mixed=True)

    def test_f006_metadata_null(self):
        self.assert_real_case(metadata=None)

    def test_f007_metadata_list(self):
        self.assert_real_case(metadata=[])

    def test_f008_metadata_string(self):
        self.assert_real_case(metadata='wrong')

    def test_f009_metadata_integer(self):
        self.assert_real_case(metadata=7)

    def test_f010_metadata_boolean(self):
        self.assert_real_case(metadata=True)

    def test_f011_ledger_array_fields(self):
        self.assert_real_case(ledger=json.dumps(
            ['schema', 'event_id', 'task_id', 'event_type', 'actor', 'created_at', 'payload']))

    def test_f012_deep_ledger_json(self):
        self.assert_real_case(ledger='[' * 1100 + '0' + ']' * 1100)

    def status_module(self):
        with patch.dict(sys.modules):
            sys.path.insert(0, str(ROOT / 'scripts'))
            try:
                spec = importlib.util.spec_from_file_location('isolated_status', ROOT / 'scripts/context_status.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            finally:
                sys.path.pop(0)

    def assert_stub(self, result=None, exception=None, expected=2):
        module = self.status_module()
        for json_output in (False, True):
            with self.subTest(json_output=json_output), patch.object(
                    module, 'resume', return_value=result, side_effect=exception):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = module.main([*self.inputs(), *(['--json'] if json_output else [])])
                sections = self.sections(output.getvalue(), json_output)
                self.assertEqual(code, expected)
                if expected == 2:
                    self.assertEqual(sections['identity']['status'], 'unavailable')
                    self.assertIn('身份诊断不可用', sections['identity']['message'])
                return_sections = sections
        return return_sections

    def test_resume_raises_keeps_snapshot_sections(self):
        for error in (OSError, RuntimeError, AttributeError, RecursionError, TypeError, ValueError):
            with self.subTest(error=error):
                sections = self.assert_stub(exception=error('probe'))
                self.assertEqual(sections['identity']['exception_type'], error.__name__)
                self.assertNotEqual(sections['checkpoint'].get('status'), 'unavailable')

    def test_resume_missing_diagnostic_is_unknown(self):
        self.assert_stub(result={'context': None})

    def test_nonserializable_resume_values_keep_json(self):
        result = self.command()
        result['resume_gate']['unsupported'] = Path('/probe')
        circular = []
        circular.append(circular)
        result['resume_gate']['circular'] = circular
        sections = self.assert_stub(result=result, expected=0)
        self.assertIn('unavailable', sections['resume_gate']['report']['unsupported'])
        self.assertIn('unavailable', sections['resume_gate']['report']['circular'][0])


class ReadOnlyEntryTests(ResumeFixture):
    def hashes(self):
        return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.base.rglob('*') if p.is_file()}


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


class DispatchOrdinaryItemTests(ResumeFixture):
    def test_only_ordinary_items_leave_dispatches_available_without_skips(self):
        self.record('ORDINARY')
        self.record('OTHER', metadata={'role': 'observation', 'report_item': 0})
        section = self.command('context_status.py')['dispatches']
        self.assertEqual(section['skipped_count'], 0)
        self.assertEqual(section['status'], 'available')
        self.assertEqual(section['data'], [])
        self.assertEqual(section['message'], '')

    def test_invalid_dispatch_ids_are_skipped_without_counting_ordinary_items(self):
        self.record('ORDINARY', metadata={'role': 'observation'})
        for index, value in enumerate((None, '', [], {}, 7, True)):
            self.record('INVALID-' + str(index), metadata={'orca_dispatch_id': value})
        self.record('MAIN', metadata={'orca_dispatch_id': 'ctx-a'})
        self.record('SUGGESTION', metadata={'orca_dispatch_id': 'ctx-a', 'report_item': 0})
        self.record('OTHER-MAIN', metadata={'orca_dispatch_id': 'ctx-b'})
        section = self.command('context_status.py')['dispatches']
        self.assertEqual(section['skipped_count'], 6)
        self.assertEqual(section['status'], 'unavailable')
        self.assertIn('跳过 6 个', section['message'])
        self.assertEqual(section['data'], [
            {'orca_dispatch_id': 'ctx-a', 'main_item_ids': ['MAIN'], 'suggestion_count': 1},
            {'orca_dispatch_id': 'ctx-b', 'main_item_ids': ['OTHER-MAIN'], 'suggestion_count': 0},
        ])

    def test_valid_dispatch_list_is_unchanged_by_ordinary_items(self):
        self.record('MAIN-Z', metadata={'orca_dispatch_id': 'ctx-a'})
        self.record('MAIN-A', metadata={'orca_dispatch_id': 'ctx-a'})
        self.record('SUGGESTION', metadata={'orca_dispatch_id': 'ctx-a', 'report_item': 0})
        before = self.command('context_status.py')['dispatches']
        self.record('ORDINARY')
        self.record('OTHER', metadata={'report_item': 1})
        after = self.command('context_status.py')['dispatches']
        self.assertEqual(after, before)
        self.assertEqual(after['data'], [
            {'orca_dispatch_id': 'ctx-a', 'main_item_ids': ['MAIN-A', 'MAIN-Z'], 'suggestion_count': 1},
        ])
