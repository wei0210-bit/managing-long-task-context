from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import managing_long_task_context as context

BASELINE = '457391beb58880c5cfcc8b83a978e4aff8797208'
COMMAND = 'python3 -m unittest fixture'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tree_bytes(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


class AcceptanceFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.container = Path(temp.name).resolve()
        self.root = self.container / 'repo'
        self.root.mkdir()
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.original_cwd)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Tests')
        self.git('config', 'user.email', 'tests@example.invalid')
        (self.root / '.gitignore').write_text('.prime/\n.context-reports/\n.githooks/\n.gitattributes\n')
        (self.root / 'src').mkdir()
        (self.root / 'src/code.py').write_text('print(1)\n')
        (self.root / 'other').write_text('unrelated\n')
        self.git('add', '.gitignore', 'src', 'other')
        self.git('commit', '-qm', 'fixture')
        self.remote = self.container / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(self.remote)], check=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        self.base = self.root / '.prime/context'
        self.task = 'ACCEPT'
        self.task_root = self.base / self.task
        self.contract = {'schema': 1, 'task_id': self.task, 'version': 1, 'issued_by': 'publisher',
            'issued_at': '2026-10-07T00:00:00Z', 'authorized_approvers': [], 'workspace_root': '.',
            'objective': 'Accept the sealed work', 'scope': ['src'], 'out_of_scope': [], 'constraints': [],
            'required_capabilities': ['evidence-handlers/v1'],
            'evidence_handlers': {'schema': 'evidence-handlers/v1', 'types': {'worker-report': {
                'resolver_capability': 'project:worker-report/v1',
                'verifier_capability': 'project:worker-report-claim/v1'}}},
            'acceptance_criteria': [{'id': 'AC-01', 'criterion': 'Outputs verified',
                'required_evidence_types': ['worker-report'], 'worker_report_claim': {'commands': [COMMAND]},
                'required_scope': {}, 'required_hops': [], 'required_delivery_types': [],
                'independent_validation_required': False}]}
        self.published = context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
        self.output = self.root / '.context-reports/output.log'
        self.output.parent.mkdir()
        self.output.write_bytes(b'OK\n')
        self.report_path = self.output.parent / 'report.json'
        self.report = {'schema': 1, 'task_id': self.task, 'orca_task_id': 'task_fixture',
            'orca_dispatch_id': 'ctx_fixture', 'contract_digest': self.published['seal']['integrity_digest'],
            'loaded_module_file': '/pinned/src/managing_long_task_context/__init__.py',
            'loaded_manifest_sha256': 'b' * 64, 'code_revision': {'commit': self.head(), 'dirty': False},
            'checks': [{'command': COMMAND, 'exit_code': 0, 'output_file': '.context-reports/output.log',
                        'output_sha256': sha(self.output.read_bytes()), 'output_summary': 'OK'}],
            'files_modified': [], 'deferred_suggestions': [], 'outcome_claim': 'succeeded',
            'written_at': self.now()}
        self.evidence = {'evidence_id': 'EV-01', 'kind': 'worker-report', 'locator': '.context-reports/report.json',
            'generated_at': self.now(), 'produced_by': 'coordinator', 'scope': {}, 'contract_version': 1}
        self.write_report()
        self.resolvers, self.verifiers = context.worker_report_handlers(self.root)
        self.records = self.task_root / 'acceptance-records.jsonl'

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def git(self, *args, root=None, check=True):
        result = subprocess.run(['git', '-C', str(root or self.root), *args], capture_output=True,
                                text=True, check=check, timeout=20)
        return result.stdout if check else result

    def head(self):
        return self.git('rev-parse', 'HEAD').strip()

    def write_report(self):
        self.report_path.write_text(json.dumps(self.report))
        self.evidence['artifact_digest'] = 'sha256:' + sha(self.report_path.read_bytes())

    def record(self, **kwargs):
        api = getattr(context, 'record_acceptance', None)
        self.assertTrue(callable(api), 'record_acceptance API is missing')
        return api(self.task, evidence_map={'AC-01': {'evidence': [self.evidence], 'delivery_receipts': []}},
            resolvers=self.resolvers, verifiers=self.verifiers, watched_paths=kwargs.pop('watched_paths', ['src']),
            recorded_by='coordinator', base_dir=self.base, workspace_root=self.root, **kwargs)

    def status(self):
        api = getattr(context, 'acceptance_status', None)
        self.assertTrue(callable(api), 'acceptance_status API is missing')
        return api(self.task, base_dir=self.base, workspace_root=self.root)

    def latest(self):
        api = getattr(context, 'latest_acceptance', None)
        self.assertTrue(callable(api), 'latest_acceptance API is missing')
        return api(self.task, base_dir=self.base)

    def use_file_evidence(self):
        self.contract['evidence_handlers']['types']['file'] = {'resolver_capability': 'builtin:file/v1',
            'verifier_capability': 'project:file-claim/v1'}
        self.contract['acceptance_criteria'][0]['required_evidence_types'] = ['file']
        self.contract['version'] += 1
        context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
        self.evidence.update(kind='file', contract_version=self.contract['version'], locator='src/code.py',
            artifact_digest='sha256:' + sha((self.root / 'src/code.py').read_bytes()))
        self.verifiers['file'] = {'capability': 'project:file-claim/v1',
            'handler': lambda *args: {'status': 'pass', 'codes': []}}

    def append_event(self):
        context.record(self.task, statement='new observation', item_type='observation', actor='coordinator',
                       source={'kind': 'tool', 'ref': 'fixture'}, base_dir=self.base)

    def resign(self, records):
        # Independent standard-json fixture encoder, not the production digest helper.
        for item in records:
            item.pop('record_digest', None)
            raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            item['record_digest'] = 'sha256:' + sha(raw)
        self.records.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in records))

    def lines(self):
        return [json.loads(line) for line in self.records.read_text().splitlines()]


class PreservationChecks:
    """Preservation checks: expected to pass before implementing new behavior."""
    def test_archive_baseline_reads_new_sidecars_without_behavior_change(self):
        if not (ROOT / '.git').exists():
            self.skipTest('packaged copy has no Git history; git archive baseline cannot be generated')
        archive = subprocess.run(['git', '-C', str(ROOT), 'archive', BASELINE], capture_output=True)
        self.assertEqual(archive.returncode, 0, archive.stderr.decode())
        old = self.container / 'old-package'
        old.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(old)
        script = '''import json,sys,managing_long_task_context as m
from pathlib import Path
root=Path(sys.argv[1]);base=root/'.prime/context';task='ACCEPT'
r={'audit':m.audit(task,base_dir=base,emit=False), 'brief':m.brief(task,base_dir=base),
'gate':m.gate(task,stage='completion',base_dir=base,emit=False),
'check_store':m.check_store(task,root), 'read_task':m.read_task(task,root)}
print(json.dumps(r,sort_keys=True))'''
        def probe():
            result = subprocess.run([sys.executable, '-c', script, str(self.root)],
                env={**os.environ, 'PYTHONPATH': str(old / 'src')}, cwd=self.root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        before = probe()
        self.records.write_text('{"sidecar": true}\n')
        (self.task_root / 'evidence').mkdir()
        (self.task_root / 'evidence/fixture').write_bytes(b'old reader ignores sidecars')
        (self.task_root / 'contract-history').mkdir()
        (self.task_root / 'contract-history/fixture.json').write_text('{}')
        self.assertEqual(before, probe())
        # Current brief with no record file remains byte-for-byte baseline compatible.
        self.records.unlink()
        current = subprocess.run([sys.executable, '-c', script, str(self.root)],
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(before, current.stdout)



class RecordStorageTests(PreservationChecks, AcceptanceFixture):
    def test_real_gate_record_is_pass_and_separate_from_ledger(self):
        before = tree_bytes(self.task_root)
        attributes = (self.root / '.gitattributes').read_bytes()
        result = self.record()
        self.assertTrue(result['appended'])
        item = result['record']
        self.assertEqual(item['schema'], 'acceptance-record/v1')
        self.assertEqual(item['decision'], 'pass')
        self.assertEqual(item['stage'], 'completion')
        self.assertEqual(item['watched'], [{'path': 'src', 'object_id': self.git('rev-parse', 'HEAD:src').strip()}])
        self.assertTrue(item['reproducible'])
        self.assertEqual(item['code_revision'], {'commit': self.head(), 'dirty': False, 'source': 'recorder-head'})
        after = tree_bytes(self.task_root)
        for name in ('events.jsonl', 'snapshot.json', 'task-contract.json'):
            self.assertEqual(before[name], after[name])
        self.assertEqual(attributes, (self.root / '.gitattributes').read_bytes())

    def test_idempotent_key_and_different_watched_set(self):
        first = self.record()
        duplicate = self.record()
        self.assertFalse(duplicate['appended'])
        self.assertEqual(first['record'], duplicate['record'])
        other = self.record(watched_paths=['src/code.py'])
        self.assertTrue(other['appended'])
        self.assertEqual(len(self.lines()), 2)

    def test_pass_fail_and_unknown_are_all_recorded(self):
        self.assertEqual(self.record()['record']['decision'], 'pass')
        self.report['checks'][0]['exit_code'] = 1
        self.write_report()
        self.assertEqual(self.record()['record']['decision'], 'fail')
        self.report['checks'][0]['exit_code'] = 0
        self.report['code_revision']['commit'] = 'f' * 40
        self.write_report()
        result = self.record()['record']
        self.assertEqual(result['decision'], 'unknown')
        self.assertFalse(result['reproducible'])
        self.assertTrue(result['reproducible_reasons'])
        self.assertEqual(len(self.lines()), 3)

    def test_legacy_decision_fallback_fail_precedes_unknown(self):
        with patch.object(context, 'gate', return_value={'passed': False, 'errors': [],
                          'criteria': [{'status': 'unknown'}, {'status': 'fail'}]}):
            self.assertEqual(self.record()['record']['decision'], 'fail')

    def test_gate_is_called_outside_writer_lock_with_completion_and_emit_false(self):
        original = context.gate
        def probe(*args, **kwargs):
            self.assertEqual(kwargs['stage'], 'completion')
            self.assertFalse(kwargs['emit'])
            self.assertFalse(context._process_lock_guard(self.task_root).locked())
            return original(*args, **kwargs)
        with patch.object(context, 'gate', side_effect=probe):
            self.assertEqual(self.record()['record']['decision'], 'pass')

    def test_locked_reread_never_calls_shared_entry(self):
        original = context._shared_locked_existing
        @contextlib.contextmanager
        def guard(root):
            self.assertFalse(context._process_lock_guard(root).locked(), 'nested shared lock')
            with original(root):
                yield
        with patch.object(context, '_shared_locked_existing', side_effect=guard):
            self.assertTrue(self.record()['appended'])

    def test_cwd_mismatch_refuses_before_writing(self):
        os.chdir(self.container)
        with self.assertRaisesRegex(context.ContextError, 'CWD_MISMATCH'):
            self.record()
        self.assertFalse(self.records.exists())

    def test_detached_head_no_upstream_and_merge_refuse(self):
        self.assertTrue(callable(getattr(context, 'record_acceptance', None)), 'recorder missing')
        branch = self.git('branch', '--show-current').strip()
        cases = [('detach', 'DETACHED_HEAD'), ('upstream', 'NO_UPSTREAM'), ('merge', 'MERGE_IN_PROGRESS')]
        for case, code in cases:
            with self.subTest(case=case):
                if case == 'detach':
                    self.git('checkout', '--detach', '-q')
                elif case == 'upstream':
                    self.git('branch', '--unset-upstream')
                else:
                    git_path = Path(self.git('rev-parse', '--git-path', 'MERGE_HEAD').strip())
                    git_path.write_text(self.head())
                with self.assertRaisesRegex(context.ContextError, code):
                    self.record()
                self.assertFalse(self.records.exists())
                if case == 'detach':
                    self.git('checkout', '-q', branch)
                elif case == 'upstream':
                    self.git('branch', '--set-upstream-to', 'origin/' + branch)
                else:
                    git_path.unlink()

    def test_invalid_watched_paths_and_managed_subtrees_refuse(self):
        (self.root / 'nested').mkdir()
        (self.root / 'nested/.prime').mkdir()
        (self.root / 'nested/.prime/tracked').write_text('managed')
        (self.root / 'hooks').mkdir()
        (self.root / 'hooks/.githooks').mkdir()
        (self.root / 'hooks/.githooks/tracked').write_text('managed')
        (self.root / 'attrs').mkdir()
        (self.root / 'attrs/.gitattributes').write_text('managed')
        self.git('add', '-f', 'nested', 'hooks', 'attrs')
        self.git('commit', '-qm', 'subtrees')
        for path in ('.', './', '', str(self.root), '../repo/src', 'src/../src', 'missing',
                     '.prime', '.githooks', '.gitattributes', 'nested', 'hooks', 'attrs', 'x\x00y', None, 1):
            with self.subTest(path=path), self.assertRaisesRegex(context.ContextError, 'WATCHED_PATH_INVALID'):
                self.record(watched_paths=[path])
            self.assertFalse(self.records.exists())
        for value in (None, 'src', [False]):
            with self.subTest(value=value), self.assertRaisesRegex(context.ContextError, 'WATCHED_PATH_INVALID'):
                self.record(watched_paths=value)

    def test_race_ledger_head_and_dirty_watched_content(self):
        original = context.gate
        def race(change):
            def run(*args, **kwargs):
                result = original(*args, **kwargs)
                change()
                return result
            with patch.object(context, 'gate', side_effect=run):
                self.assertEqual(self.record()['reason'], 'RECORD_RACE')
            self.assertFalse(self.records.exists())
        race(self.append_event)
        race(lambda: self.git('commit', '--allow-empty', '-qm', 'changed HEAD'))
        # Already dirty before gate: a boolean dirty flag alone misses this race.
        (self.root / 'src/code.py').write_text('dirty before\n')
        race(lambda: (self.root / 'src/code.py').write_text('dirty after\n'))

    def test_contract_race_is_detected(self):
        original = context.gate
        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            self.contract['version'] = 2
            context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
            return result
        with patch.object(context, 'gate', side_effect=change):
            self.assertEqual(self.record()['reason'], 'RECORD_RACE')
        self.assertFalse(self.records.exists())

    def test_gate_to_copy_report_and_output_race_refuses(self):
        original = context.gate
        for target in (self.report_path, self.output):
            old = target.read_bytes()
            def mutate(*args, **kwargs):
                result = original(*args, **kwargs)
                target.write_bytes(old + b' ')
                return result
            with patch.object(context, 'gate', side_effect=mutate):
                self.assertEqual(self.record()['reason'], 'EVIDENCE_CHANGED')
            self.assertFalse(self.records.exists())
            target.write_bytes(old)

    def test_corrupt_conflicted_and_out_of_order_file_is_not_appended(self):
        self.record()
        original = self.records.read_bytes()
        for raw, code in ((b'<<<<<<< HEAD\n', 'RECORD_INTEGRITY'), (b'{\n', 'RECORD_INTEGRITY'),
                          (original.replace(b'"pass"', b'"fail"'), 'RECORD_INTEGRITY')):
            self.records.write_bytes(raw)
            with self.assertRaisesRegex(context.ContextError, code):
                self.record()
            self.assertEqual(self.records.read_bytes(), raw)
        self.records.write_bytes(original)
        self.append_event()
        self.record()
        entries = self.lines()
        self.resign(list(reversed(entries)))
        before = self.records.read_bytes()
        with self.assertRaisesRegex(context.ContextError, 'RECORD_ORDER'):
            self.record()
        self.assertEqual(self.records.read_bytes(), before)

    def test_record_clock_generated_inside_lock_and_clamped_to_previous(self):
        first = self.record()['record']
        first['recorded_at'] = '2099-01-01T00:00:00Z'
        self.resign([first])
        self.append_event()
        second = self.record()['record']
        self.assertEqual(second['recorded_at'], first['recorded_at'])

    def test_concurrent_sessions_serialize_monotonic_records(self):
        self.assertTrue(callable(getattr(context, 'record_acceptance', None)), 'recorder missing')
        barrier = threading.Barrier(2)
        original = context.gate
        errors, results = [], []
        def gate(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=10)
            return result
        def run(paths):
            try:
                results.append(self.record(watched_paths=paths))
            except Exception as exc:
                errors.append(exc)
        with patch.object(context, 'gate', side_effect=gate):
            threads = [threading.Thread(target=run, args=(paths,)) for paths in (['src'], ['other'])]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertFalse(any(t.is_alive() for t in threads), 'writer deadlock')
        self.assertEqual(errors, [])
        self.assertTrue(all(r['appended'] for r in results))
        entries = self.lines()
        self.assertEqual(len(entries), 2)
        self.assertLessEqual(entries[0]['recorded_at'], entries[1]['recorded_at'])
        self.assertLessEqual(entries[0]['ledger_cursor']['event_count'], entries[1]['ledger_cursor']['event_count'])

    def test_retains_only_report_and_required_outputs_as_read_only(self):
        unused = self.output.parent / 'unused.log'
        unused.write_bytes(b'unrequired')
        self.report['checks'].append({'command': 'unsealed', 'exit_code': 0,
            'output_file': '.context-reports/unused.log', 'output_sha256': sha(unused.read_bytes()), 'output_summary': ''})
        self.write_report()
        item = self.record()['record']
        files = list((self.task_root / 'evidence').iterdir())
        self.assertEqual({p.name for p in files}, {sha(self.report_path.read_bytes()), sha(self.output.read_bytes())})
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o444 for p in files))
        retained = item['criteria'][0]['evidence'][0]['retained']
        self.assertTrue(retained['copied'])
        self.assertEqual(len(retained['outputs']), 1)

    def test_other_evidence_types_are_summarized_without_copy(self):
        self.contract['evidence_handlers']['types']['file'] = {'resolver_capability': 'builtin:file/v1',
            'verifier_capability': 'project:file-claim/v1'}
        self.contract['acceptance_criteria'][0].update(required_evidence_types=['file'])
        self.contract['version'] = 2
        context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
        self.evidence.update(kind='file', contract_version=2, locator='src/code.py',
            artifact_digest='sha256:' + sha((self.root / 'src/code.py').read_bytes()))
        self.verifiers['file'] = {'capability': 'project:file-claim/v1', 'handler': lambda *args: {'status': 'pass', 'codes': []}}
        record = self.record()['record']
        self.assertEqual(record['decision'], 'pass')
        retained = record['criteria'][0]['evidence'][0]['retained']
        self.assertFalse(retained['copied'])
        self.assertEqual(retained['sha256'], self.evidence['artifact_digest'].removeprefix('sha256:'))
        self.assertFalse((self.task_root / 'evidence').exists())

    def test_secret_and_size_limits_do_not_create_missing_copy(self):
        for data, reason in ((b'AKIA secret fixture\n', 'SECRET_MARKER'), (b'x' * (1024 * 1024 + 1), 'SIZE_LIMIT')):
            with self.subTest(reason=reason):
                self.output.write_bytes(data)
                self.report['checks'][0]['output_sha256'] = sha(data)
                self.write_report()
                record = self.record()['record']
                retained = record['criteria'][0]['evidence'][0]['retained']['outputs'][0]
                self.assertFalse(retained['copied'])
                self.assertEqual(retained['reason'], reason)
                self.assertFalse((self.task_root / 'evidence' / sha(data)).exists())
                self.assertNotEqual(context.check_store(self.task, self.root).get('code'), 'SECRETS_FOUND')
                self.assertEqual(self.status()['status'], 'still_valid')

    def test_task_total_limit_and_deduplicated_copies(self):
        self.record()
        directory = self.task_root / 'evidence'
        # Existing retained material counts towards task cap, without allocating huge RAM.
        filler = directory / ('0' * 64)
        with filler.open('wb') as handle:
            handle.truncate(20 * 1024 * 1024)
        self.output.write_bytes(b'new output')
        self.report['checks'][0]['output_sha256'] = sha(self.output.read_bytes())
        self.write_report()
        result = self.record()['record']
        retained = result['criteria'][0]['evidence'][0]['retained']
        self.assertEqual(retained['reason'], 'TOTAL_LIMIT')
        self.assertEqual(retained['outputs'][0]['reason'], 'TOTAL_LIMIT')
        self.assertEqual(self.status()['status'], 'still_valid')

    def test_dirty_and_each_evidence_revision_mismatch_are_explained(self):
        self.evidence['code_revision'] = {'commit': 'f' * 40, 'dirty': True}
        self.report['code_revision']['dirty'] = True
        self.write_report()
        (self.root / 'other').write_text('dirty')
        record = self.record()['record']
        self.assertFalse(record['reproducible'])
        self.assertGreaterEqual(len(record['reproducible_reasons']), 3)
        self.assertTrue(record['code_revision']['dirty'])

    def test_attributes_change_is_not_code_dirty(self):
        (self.root / '.gitattributes').write_text('')
        record = self.record()['record']
        self.assertFalse(record['code_revision']['dirty'])
        self.assertTrue(record['reproducible'])

    def test_align_refuses_unpublished_and_unparseable_records_in_any_task(self):
        # New align behavior must protect every task before checking out the whole context tree.
        context.publish_context(self.task, self.root)
        self.record()
        for raw in (self.records.read_bytes(), b'{\n', b'{"no_id": 1}\n'):
            self.records.write_bytes(raw)
            before = tree_bytes(self.base)
            with self.assertRaises(context.StoreNotWritable) as caught:
                context.align_context('OTHER', self.root)
            self.assertEqual(caught.exception.code, 'LOCAL_AHEAD')
            self.assertEqual(before, tree_bytes(self.base))

    def test_align_accepts_published_record(self):
        self.record()
        context.publish_context(self.task, self.root)
        before = self.records.read_bytes()
        self.assertEqual(context.align_context(self.task, self.root)['status'], 'ok')
        self.assertEqual(before, self.records.read_bytes())

    def test_two_checkouts_conflict_safely(self):
        self.record()
        context.publish_context(self.task, self.root)
        clone = self.container / 'clone'
        self.git('clone', '-q', str(self.root), str(clone), root=self.container)
        self.git('config', 'user.name', 'Tests', root=clone)
        self.git('config', 'user.email', 'tests@example.invalid', root=clone)
        self.git('checkout', '-qb', 'second', root=clone)
        self.git('remote', 'set-url', 'origin', str(self.remote), root=clone)
        self.git('push', '-qu', 'origin', 'HEAD', root=clone)
        os.chdir(clone)
        context.record(self.task, statement='second checkout', item_type='observation', actor='coordinator',
                       source={'kind': 'tool', 'ref': 'clone'}, base_dir=clone / '.prime/context')
        context.record_acceptance(self.task, evidence_map={}, resolvers={}, verifiers={}, watched_paths=['src'],
            recorded_by='other', base_dir=clone / '.prime/context', workspace_root=clone)
        context.publish_context(self.task, clone)
        os.chdir(self.root)
        self.append_event()
        self.record()
        context.publish_context(self.task, self.root)
        self.git('fetch', '-q', str(clone), 'second')
        merged = self.git('merge', '--no-edit', 'FETCH_HEAD', check=False)
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn('<<<<<<<', self.records.read_text())
        before = self.records.read_bytes()
        with self.assertRaisesRegex(context.ContextError, 'MERGE_IN_PROGRESS|RECORD_INTEGRITY'):
            self.record()
        self.assertEqual(before, self.records.read_bytes())
        self.assertEqual(self.status()['reason'], 'record_integrity')


    def test_two_python_sessions_write_monotonically_under_process_lock(self):
        script = """import json,sys,time
from pathlib import Path
import managing_long_task_context as m
root=Path.cwd();task='ACCEPT';base=root/'.prime/context';token=sys.argv[1]
e=json.loads((root/'.context-reports/envelope.json').read_bytes())
r,v=m.worker_report_handlers(root);original=m.gate
def gate(*args,**kwargs):
 result=original(*args,**kwargs)
 (root/('.context-reports/ready-'+token)).write_text('ready')
 deadline=time.monotonic()+15
 while len(list((root/'.context-reports').glob('ready-*')))<2:
  if time.monotonic()>deadline:raise RuntimeError('barrier timed out')
  time.sleep(.01)
 return result
m.gate=gate
result=m.record_acceptance(task,evidence_map={'AC-01':{'evidence':[e],'delivery_receipts':[]}},
 resolvers=r,verifiers=v,watched_paths=[sys.argv[2]],recorded_by=token,base_dir=base,workspace_root=root)
assert result['appended'],result
print(json.dumps(result))
"""
        (self.output.parent / 'envelope.json').write_text(json.dumps(self.evidence))
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        processes = [subprocess.Popen([sys.executable, '-c', script, token, path], cwd=self.root,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for token, path in (('one', 'src'), ('two', 'other'))]
        try:
            for process in processes:
                output, error = process.communicate(timeout=25)
                self.assertEqual(process.returncode, 0, error + output)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        entries = self.lines()
        self.assertEqual(len(entries), 2)
        self.assertLessEqual(entries[0]['recorded_at'], entries[1]['recorded_at'])
        self.assertEqual(entries[0]['ledger_cursor'], entries[1]['ledger_cursor'])

    def test_conflict_inserted_after_gate_refuses_inside_lock(self):
        original = context.gate
        def corrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            self.records.write_bytes(b'<<<<<<< HEAD\n')
            return result
        with patch.object(context, 'gate', side_effect=corrupt):
            with self.assertRaisesRegex(context.ContextError, 'RECORD_INTEGRITY'):
                self.record()
        self.assertEqual(self.records.read_bytes(), b'<<<<<<< HEAD\n')

    def test_resolver_freshness_failure_does_not_copy_report(self):
        self.contract['acceptance_criteria'][0]['max_evidence_age_seconds'] = 1
        self.contract['version'] = 2
        published = context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
        self.report['contract_digest'] = published['seal']['integrity_digest']
        self.write_report()
        self.evidence.update(contract_version=2, generated_at='2020-01-01T00:00:00Z')
        retained = self.record()['record']['criteria'][0]['evidence'][0]['retained']
        self.assertFalse(retained['copied'])
        self.assertFalse((self.task_root / 'evidence' / sha(self.report_path.read_bytes())).exists())

    def test_new_apis_are_exported_to_star_import_consumers(self):
        self.assertTrue({'record_acceptance', 'latest_acceptance', 'acceptance_status'}.issubset(context.__all__))

    def test_new_cursor_cannot_move_backwards_from_existing_record(self):
        self.record()
        records = self.lines()
        records[0]['ledger_cursor']['event_count'] += 10
        self.resign(records)
        before = self.records.read_bytes()
        with self.assertRaisesRegex(context.ContextError, 'RECORD_ORDER'):
            self.record(watched_paths=['other'])
        self.assertEqual(before, self.records.read_bytes())

    def test_concurrent_retention_cannot_exceed_task_total_limit(self):
        from managing_long_task_context import acceptance as module
        directory = self.task_root / 'evidence'
        directory.mkdir()
        with (directory / ('0' * 64)).open('wb') as handle:
            handle.truncate(18 * 1024 * 1024)
        sources = []
        for number in range(4):
            path = self.output.parent / ('large-' + str(number))
            path.write_bytes(bytes([number]) * (1024 * 1024))
            sources.append((str(path.relative_to(self.root)), sha(path.read_bytes())))
        original = os.open
        barrier = threading.Barrier(4)
        results, errors = [], []
        def slow_create(*args, **kwargs):
            if args[1] & os.O_CREAT:
                time.sleep(.1)  # Widen a check/create race without touching lock acquisition.
            return original(*args, **kwargs)
        def retain(source):
            try:
                barrier.wait(timeout=10)
                results.append(module._retain(self.root, self.task_root, *source, eligible=True)[0])
            except Exception as exc:
                errors.append(exc)
        with patch('os.open', side_effect=slow_create):
            threads = [threading.Thread(target=retain, args=(source,)) for source in sources]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
        self.assertEqual(errors, [])
        self.assertEqual(sum(item['copied'] for item in results), 2)
        self.assertEqual(sum(p.stat().st_size for p in directory.iterdir()), 20 * 1024 * 1024)

    def test_remaining_guard_failures_stop_without_record_or_overwriting_data(self):
        from managing_long_task_context import acceptance as module
        with self.assertRaisesRegex(context.ContextError, 'RECORDED_BY_INVALID'):
            context.record_acceptance(self.task, evidence_map={}, resolvers={}, verifiers={}, watched_paths=[],
                recorded_by='', base_dir=self.base, workspace_root=self.root)
        with self.assertRaisesRegex(context.ContextError, 'WORKSPACE_INVALID'):
            context.record_acceptance(self.task, evidence_map={}, resolvers={}, verifiers={}, watched_paths=[],
                recorded_by='coordinator', base_dir=self.base, workspace_root=Path('.'))
        with patch.object(module, '_RECORD_LIMIT', 1):
            with self.assertRaisesRegex(context.ContextError, 'RECORD_SIZE_LIMIT'):
                self.record()
        self.assertFalse(self.records.exists())
        with patch.object(context, 'fcntl', None):
            with self.assertRaisesRegex(context.ContextError, 'EVIDENCE_LOCK_UNAVAILABLE'):
                module._retain(self.root, self.task_root, '.context-reports/output.log',
                               sha(self.output.read_bytes()), eligible=True)
        self.assertFalse(self.records.exists())

    def test_git_errors_and_lock_failure_never_write_a_record(self):
        from managing_long_task_context import acceptance as module
        for error in (OSError(), subprocess.TimeoutExpired('git', 1)):
            with self.subTest(error=type(error).__name__), patch.object(module, '_git', side_effect=error):
                with self.assertRaises((context.ContextError, OSError, subprocess.TimeoutExpired)):
                    self.record()
                self.assertFalse(self.records.exists())
        with patch.object(context, '_locked', side_effect=context.ContextError('LOCK_UNAVAILABLE')):
            with self.assertRaisesRegex(context.ContextError, 'LOCK_UNAVAILABLE'):
                self.record()
            self.assertFalse(self.records.exists())

    def test_missing_source_invalid_path_and_symlink_are_not_copied(self):
        original = self.report_path.read_bytes()
        (self.output.parent / 'linked').symlink_to(self.report_path)
        for locator in ('../outside', str(self.report_path), '.context-reports/linked',
                        '.context-reports/missing', '.context-reports'):
            with self.subTest(locator=locator):
                self.evidence['locator'] = locator
                item = self.record()['record']['criteria'][0]['evidence'][0]
                self.assertFalse(item['retained']['copied'])
                self.assertFalse((self.task_root / 'evidence' / sha(original)).exists())
                self.append_event()

    def test_copy_destination_symlinks_or_changed_bytes_are_rejected(self):
        directory = self.task_root / 'evidence'
        directory.mkdir()
        destination = directory / sha(self.report_path.read_bytes())
        destination.symlink_to(self.report_path)
        with self.assertRaises((context.ContextError, OSError)):
            self.record()
        self.assertFalse(self.records.exists())
        destination.unlink()
        destination.write_bytes(b'corrupt content addressed copy')
        with self.assertRaisesRegex(context.ContextError, 'EVIDENCE_COPY_INVALID'):
            self.record()
        self.assertFalse(self.records.exists())

    def test_record_symlink_and_fifo_are_refused_without_following(self):
        outside = self.container / 'outside'
        outside.write_bytes(b'untouched')
        self.records.symlink_to(outside)
        with self.assertRaisesRegex(context.ContextError, 'RECORD_INTEGRITY'):
            self.record()
        self.assertEqual(outside.read_bytes(), b'untouched')
        self.records.unlink()
        os.mkfifo(self.records)
        with self.assertRaisesRegex(context.ContextError, 'RECORD_INTEGRITY'):
            self.record()

    def test_every_retention_secret_marker_is_screened_and_boundary_file_copies(self):
        from managing_long_task_context.project_store import SECRET_MARKERS
        for marker in SECRET_MARKERS:
            self.output.write_bytes(marker.encode())
            self.report['checks'][0]['output_sha256'] = sha(self.output.read_bytes())
            self.write_report()
            retained = self.record()['record']['criteria'][0]['evidence'][0]['retained']['outputs'][0]
            self.assertEqual(retained['reason'], 'SECRET_MARKER')
            self.assertFalse((self.task_root / 'evidence' / retained['sha256']).exists())
        self.output.write_bytes(b'x' * (1024 * 1024))
        self.report['checks'][0]['output_sha256'] = sha(self.output.read_bytes())
        self.write_report()
        retained = self.record()['record']['criteria'][0]['evidence'][0]['retained']['outputs'][0]
        self.assertTrue(retained['copied'])

    def test_secret_in_report_blocks_report_copy_but_not_safe_output(self):
        self.report['deferred_suggestions'] = ['AKIA fixture']
        self.write_report()
        item = self.record()['record']['criteria'][0]['evidence'][0]['retained']
        self.assertEqual(item['reason'], 'SECRET_MARKER')
        self.assertTrue(item['outputs'][0]['copied'])
        self.assertEqual(self.status()['status'], 'still_valid')
        self.assertNotEqual(context.check_store(self.task, self.root).get('code'), 'SECRETS_FOUND')

    def test_evidence_missing_after_gate_and_retention_write_failure(self):
        original = context.gate
        raw = self.report_path.read_bytes()
        def missing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.report_path.unlink()
            return result
        with patch.object(context, 'gate', side_effect=missing):
            self.assertEqual(self.record()['reason'], 'EVIDENCE_CHANGED')
        self.report_path.write_bytes(raw)
        def failed(fd):
            raise OSError('retention disk failure')
        with patch('os.fsync', side_effect=failed):
            with self.assertRaises(OSError):
                self.record()
        self.assertFalse(self.records.exists())

    def test_recorded_at_clock_observation_is_inside_exclusive_lock(self):
        original = context._trusted_utc_now
        original_gate = context.gate
        inside_gate = [False]
        def gate(*args, **kwargs):
            inside_gate[0] = True
            try:
                return original_gate(*args, **kwargs)
            finally:
                inside_gate[0] = False
        def now():
            if not inside_gate[0]:
                self.assertTrue(context._process_lock_guard(self.task_root).locked())
            return original()
        with patch.object(context, '_trusted_utc_now', side_effect=now), patch.object(context, 'gate', side_effect=gate):
            self.assertTrue(self.record()['appended'])



class ReacceptanceTests(AcceptanceFixture):
    def test_never_and_last_nonpass(self):
        self.assertEqual(self.status()['status'], 'never_accepted')
        self.report['checks'][0]['exit_code'] = 1
        self.write_report()
        self.record()
        self.assertEqual(self.status()['status'], 'not_accepted')

    def test_publish_and_unrelated_commits_are_still_valid(self):
        self.record()
        context.publish_context(self.task, self.root)
        self.assertEqual(self.status()['status'], 'still_valid')
        (self.root / 'other').write_text('changed unrelated\n')
        self.git('add', 'other')
        self.git('commit', '-qm', 'unrelated')
        self.assertEqual(self.status()['status'], 'still_valid')

    def test_watched_change_or_move_requires_reacceptance(self):
        self.record()
        (self.root / 'src/code.py').write_text('print(2)\n')
        self.git('add', 'src')
        self.git('commit', '-qm', 'watched change')
        result = self.status()
        self.assertEqual((result['status'], result['reason']), ('reaccept_required', 'watched_paths_changed'))
        self.assertIn('src', result['paths'])
        self.git('mv', 'src', 'moved')
        self.git('commit', '-qm', 'move watched')
        self.assertEqual(self.status()['reason'], 'watched_paths_changed')

    def test_squashed_history_fresh_no_local_clone_is_valid(self):
        self.record()
        context.publish_context(self.task, self.root)
        old = self.lines()[0]['code_revision']['commit']
        self.git('checkout', '--orphan', 'squashed')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'squashed tree')
        clone = self.container / 'fresh'
        self.git('clone', '--no-local', '--single-branch', '--branch', 'squashed', '-q', str(self.root), str(clone), root=self.container)
        self.assertNotEqual(self.git('cat-file', '-e', old, root=clone, check=False).returncode, 0)
        result = context.acceptance_status(self.task, base_dir=clone / '.prime/context', workspace_root=clone)
        self.assertEqual(result['status'], 'still_valid')
        self.assertEqual(result['commit_relation'], 'missing')

    def test_contract_dirty_and_empty_watch_have_ordered_reasons(self):
        self.record(watched_paths=[])
        self.assertEqual(self.status()['reason'], 'no_watched_paths')
        self.append_event()
        self.use_file_evidence()
        (self.root / 'other').write_text('dirty')
        self.record()
        self.assertEqual(self.status()['reason'], 'recorded_dirty')
        self.contract['version'] += 1
        context.publish_contract(self.contract, confirmed_by='publisher', base_dir=self.base)
        self.assertEqual(self.status()['reason'], 'contract_changed')

    def test_current_watched_dirty_is_unknown_including_rename_source(self):
        self.record()
        (self.root / 'src/code.py').write_text('dirty')
        self.assertEqual(self.status()['reason'], 'worktree_dirty')
        self.git('mv', 'src/code.py', 'outside.py')
        self.assertEqual(self.status()['reason'], 'worktree_dirty')

    def test_deleted_or_modified_copied_evidence_is_unknown(self):
        self.record()
        output_copy = self.task_root / 'evidence' / sha(self.output.read_bytes())
        output_copy.chmod(0o644)
        output_copy.write_bytes(b'tampered')
        self.assertEqual(self.status()['reason'], 'evidence_copy')
        self.assertFalse(self.latest()['evidence_integrity'])
        output_copy.unlink()
        self.assertEqual(self.status()['reason'], 'evidence_copy')

    def test_bad_line_and_order_do_not_skip_to_last_good_pass(self):
        self.record()
        raw = self.records.read_bytes()
        for bad in (b'bad\n', b'<<<<<<< HEAD\n', b'null\n', b'[]\n', b'{}\n', b'\xff\n'):
            with self.subTest(bad=bad):
                self.records.write_bytes(bad + raw)
                self.assertEqual(self.status()['reason'], 'record_integrity')
        self.records.write_bytes(raw)
        self.append_event()
        self.record()
        records = self.lines()
        self.resign(list(reversed(records)))
        self.assertEqual(self.status()['reason'], 'record_order')

    def test_status_tracks_ancestry_and_new_ledger_events(self):
        self.record()
        self.append_event()
        result = self.status()
        self.assertEqual(result['events_since_acceptance'], 1)
        self.assertEqual(result['commit_relation'], 'ancestor')
        self.assertIn('验收后有新的上下文变化', result['message'])
        records = self.lines()
        # Existing side-branch commit with identical watched content is not ancestor.
        self.git('checkout', '-qb', 'side')
        self.git('commit', '--allow-empty', '-qm', 'side commit')
        side = self.head()
        self.git('checkout', '-q', '-')
        records[-1]['code_revision']['commit'] = side
        self.resign(records)
        result = self.status()
        self.assertEqual(result['commit_relation'], 'not_ancestor')
        self.assertIn('记录来自其他分支或已被改写的历史', result['message'])


    def test_missing_record_fields_and_malformed_retention_reason_are_unknown(self):
        self.record()
        original = self.lines()[0]
        for field in original:
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed.pop(field)
                if field == 'record_digest':
                    self.records.write_text(json.dumps(changed) + '\n')
                else:
                    self.resign([changed])
                self.assertEqual(self.status()['reason'], 'record_integrity')
        for reason in (None, [], {}):
            changed = copy.deepcopy(original)
            retained = changed['criteria'][0]['evidence'][0]['retained']
            retained.update(copied=False, reason=reason)
            self.resign([changed])
            self.assertEqual(self.status()['reason'], 'record_integrity')

    def test_actual_contract_content_change_is_detected_despite_old_seal(self):
        self.record()
        path = self.task_root / 'task-contract.json'
        current = json.loads(path.read_bytes())
        current['objective'] = 'Changed without refreshing the old seal'
        path.chmod(0o644)
        path.write_text(json.dumps(current))
        self.assertFalse(self.latest()['contract_matches'])
        self.assertEqual(self.status()['reason'], 'contract_changed')

    def test_malformed_but_redigested_fields_and_duplicate_keys_are_unknown(self):
        self.record()
        original = self.lines()[0]
        for field, value in (('recorded_at', 'bad'), ('ledger_cursor', {'event_count': -1}),
            ('code_revision', {'commit': 'x', 'dirty': False}), ('watched', [{}]),
            ('criteria', [{'status': 'pass', 'evidence': [{'retained': {'copied': True, 'sha256': '../outside'}}]}]),
            ('passed', 'yes'), ('reproducible', 'yes')):
            with self.subTest(field=field):
                record = copy.deepcopy(original)
                record[field] = value
                self.resign([record])
                self.assertEqual(self.status()['reason'], 'record_integrity')
        self.resign([original])
        raw = self.records.read_bytes()
        self.records.write_bytes(raw.replace(b'{', b'{"decision":"fail",', 1))
        self.assertEqual(self.status()['reason'], 'record_integrity')

    def test_only_clock_disorder_also_reports_record_order(self):
        self.record()
        self.append_event()
        self.record()
        records = self.lines()
        records[0]['recorded_at'] = '2099-01-01T00:00:00Z'
        self.resign(records)
        self.assertEqual(self.status()['reason'], 'record_order')

    def test_unavailable_git_is_unknown_without_writing(self):
        self.record()
        before = tree_bytes(self.task_root)
        with patch('subprocess.run', side_effect=FileNotFoundError('git')):
            self.assertEqual(self.status()['reason'], 'git_unavailable')
        self.assertEqual(before, tree_bytes(self.task_root))



class PresentationTests(AcceptanceFixture):
    def test_brief_latest_is_bounded_without_git_and_counts_budget(self):
        self.record()
        before = tree_bytes(self.task_root)
        with patch('subprocess.run', side_effect=AssertionError('brief must not run Git')):
            packet = context.brief(self.task, base_dir=self.base)
        self.assertIn('latest_acceptance', packet)
        section = packet['prompt'].split('## Latest acceptance')[1]
        self.assertLessEqual(len('## Latest acceptance' + section), 600)
        self.assertIn('context_status.py', section)
        self.assertEqual(before, tree_bytes(self.task_root))
        with self.assertRaisesRegex(context.ContextError, 'BRIEF_REQUIRED_OVERFLOW'):
            context.brief(self.task, base_dir=self.base, max_chars=len(packet['prompt']) - 1)

    def test_acceptance_fixed_section_overflow_for_tiny_budget(self):
        self.record()
        with self.assertRaisesRegex(context.ContextError, 'BRIEF_REQUIRED_OVERFLOW'):
            context.brief(self.task, base_dir=self.base, max_chars=10)

    def test_sixth_status_section_is_readonly_and_json_structured(self):
        self.record()
        self.append_event()
        sys.path.insert(0, str(ROOT / 'scripts'))
        self.addCleanup(sys.path.remove, str(ROOT / 'scripts'))
        module = importlib.import_module('context_status')
        args = type('Args', (), {'package_root': str(ROOT), 'context_root': str(self.base),
                               'workspace_root': str(self.root), 'task_id': self.task})()
        before = tree_bytes(self.task_root)
        result, _ = module.status(args)
        self.assertIn('acceptance', result)
        self.assertEqual(result['acceptance']['status'], 'still_valid')
        self.assertEqual(result['acceptance']['events_since_acceptance'], 1)
        self.assertEqual(before, tree_bytes(self.task_root))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            module.main(['--package-root', str(ROOT), '--context-root', str(self.base),
                         '--workspace-root', str(self.root), '--task-id', self.task])
        self.assertIn('## 验收', out.getvalue())
        self.assertIn('记录按分支存在', out.getvalue())




if __name__ == '__main__':
    unittest.main()
