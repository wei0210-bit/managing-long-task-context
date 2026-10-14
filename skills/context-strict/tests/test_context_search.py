"""Public searches return source locations and refresh their disposable cache."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import managing_long_task_context as context
from managing_long_task_context.project_store import CONTEXT_PATHS, RELATIVE_CONTEXT


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'docs').mkdir()
        self.doc = self.root / 'docs' / 'facts.md'
        self.doc.write_text('# Facts\n\n协调者租约 alpha\n\n证据位置 beta\n', encoding='utf-8')
        spec = importlib.util.spec_from_file_location('context_search_under_test', ROOT / 'scripts/context_search.py')
        self.search = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.search)

    def query(self, *words, **kwargs):
        return self.search.search(self.root, list(words), **kwargs)

    def test_refresh_locations_and_read_only_sources(self):
        before = self.doc.read_bytes()
        result = self.query('协调者租约')
        self.assertEqual(result['results'][0]['path'], 'docs/facts.md')
        self.assertEqual(result['results'][0]['line'], 3)
        self.assertEqual(self.doc.read_bytes(), before)
        self.doc.write_text('# Facts\n\n新增事实 gamma\n', encoding='utf-8')
        self.assertFalse(self.query('协调者租约')['results'])
        self.assertEqual(self.query('新增事实')['results'][0]['line'], 3)

    def test_short_and_mixed_words_literal_like_and_limits(self):
        self.assertEqual(self.query('租约')['results'][0]['line'], 3)
        self.assertEqual(self.query('协调者', '租约')['results'][0]['line'], 3)
        self.assertFalse(self.query('协调者', '证据')['results'])
        self.assertFalse(self.query('%')['results'])
        self.assertFalse(self.query('_')['results'])
        self.assertEqual(len(self.query('a', limit=1)['results']), 1)
        self.assertFalse(self.query('alpha', kind='fact')['results'])

    def test_unavailable_trigram_uses_explicit_degraded_scan(self):
        with patch.object(self.search, '_create_fts', side_effect=sqlite3.OperationalError('no such tokenizer: trigram')):
            result = self.query('协调者租约')
        self.assertEqual(result['degraded'], 'like-scan')
        self.assertEqual(result['results'][0]['degraded'], 'like-scan')
        self.assertEqual(self.query('租约')['results'][0]['line'], 3)

    def test_lock_conflict_returns_previous_index_with_stale_flag(self):
        self.query('alpha')
        connection = sqlite3.connect(self.root / self.search.INDEX_PATH)
        self.addCleanup(connection.close)
        connection.execute('BEGIN IMMEDIATE')
        self.doc.write_text('replacement gamma', encoding='utf-8')
        result = self.query('alpha')
        self.assertTrue(result['index_stale'])
        self.assertTrue(result['results'][0]['index_stale'])
        connection.rollback()
        self.assertFalse(self.query('alpha')['results'])
        self.assertFalse(self.query('gamma')['index_stale'])

    def test_corruption_rebuild_and_deleted_file(self):
        expected = self.query('alpha')['results'][0]
        (self.root / self.search.INDEX_PATH).write_bytes(b'broken index')
        actual = self.query('alpha')['results'][0]
        self.assertEqual((actual['path'], actual['line']), (expected['path'], expected['line']))
        self.doc.unlink()
        self.assertFalse(self.query('alpha')['results'])

    def test_non_utf8_source_is_skipped_and_recovers(self):
        invalid = self.root / 'docs' / 'invalid.md'
        invalid.write_bytes(b'invalid fact \xff')
        result = self.query('协调者租约')
        self.assertTrue(result['results'])
        self.assertEqual(result['skipped'], [
            {'path': 'docs/invalid.md', 'reason': 'invalid UTF-8 at byte 13: invalid start byte'},
        ])
        rebuilt = self.search.rebuild(self.root)
        self.assertFalse(rebuilt['index_stale'])
        self.assertEqual(rebuilt['skipped'], result['skipped'])

        invalid.write_text('recovered searchable fact', encoding='utf-8')
        recovered = self.query('recovered')
        self.assertTrue(recovered['results'])
        self.assertEqual(recovered['skipped'], [])

    def test_explicit_include_does_not_leak_into_default_query(self):
        memory = self.root / 'memory'
        memory.mkdir()
        (memory / 'entry.md').write_text('secret memory fact', encoding='utf-8')
        self.assertFalse(self.query('secret')['results'])
        self.assertEqual(self.query('secret', include=[memory])['results'][0]['path'], 'memory/entry.md')
        self.assertFalse(self.query('secret')['results'])

    def test_symlink_root_and_include_use_physical_paths_without_following_source_links(self):
        alias = self.root.with_name(self.root.name + '-alias')
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink)
        memory = self.root / 'memory'
        memory.mkdir()
        (memory / 'entry.md').write_text('secret memory fact', encoding='utf-8')
        hidden = self.root / 'private-source'
        hidden.mkdir()
        target = hidden / 'fact.md'
        target.write_text('excluded symlink fact', encoding='utf-8')
        (memory / 'linked').symlink_to(hidden, target_is_directory=True)
        (memory / 'file-link.md').symlink_to(target)
        result = self.search.search(alias, ['secret'], include=[alias / 'memory'])
        self.assertEqual(result['results'][0]['path'], 'memory/entry.md')
        self.assertFalse(self.search.search(alias, ['excluded'], include=[alias / 'memory'])['results'])
        self.assertFalse(self.search.search(alias, ['excluded'], include=[alias / 'memory' / 'linked'])['results'])
        self.assertFalse(self.search.search(alias, ['secret'])['results'])
        self.assertEqual(self.search.search(alias, ['alpha'])['results'][0]['path'], 'docs/facts.md')
        subprocess.run(['git', 'init', '-q', str(alias)], check=True)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/context_search.py'),
            'search', 'secret', '--include', str(alias / 'memory')], cwd=alias, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['results'][0]['path'], 'memory/entry.md')

    def test_index_is_ignored_and_outside_publish_paths(self):
        label = self.search.INDEX_PATH.as_posix()
        self.assertFalse(any(label == p or label.startswith(p + '/') for p in CONTEXT_PATHS))
        # Standalone packages deliberately have no Git metadata or root .gitignore.
        if (ROOT / '.git').exists():
            result = subprocess.run(['git', 'check-ignore', '.prime/search/index.sqlite'], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def publish(self, task_id='T1'):
        base = self.root / RELATIVE_CONTEXT
        context.publish_contract({'task_id': task_id, 'version': 1, 'issued_by': 'tester',
            'issued_at': '2026-10-14T00:00:00Z', 'objective': 'Record facts', 'scope': [],
            'out_of_scope': [], 'constraints': [], 'acceptance_criteria': [
                {'id': 'AC-1', 'criterion': 'Search source files', 'required_evidence': ['file']}]},
            confirmed_by='tester', base_dir=base)
        return base

    def test_rebuilt_current_facts_have_event_locations_and_history_isolation(self):
        base = self.publish()
        old = context.record('T1', statement='original conclusion', item_type='observation',
            actor='tester', source='file', base_dir=base)
        new = context.record('T1', statement='current conclusion', item_type='observation',
            actor='tester', source='file', metadata={'version': 'pending-version'}, supersedes=old['id'], base_dir=base)
        context.update_item('T1', new['id'], metadata={'version': 'updated conclusion'}, actor='tester', base_dir=base)
        paths = context._paths('T1', base_dir=base)
        normal_snapshot = paths['snapshot'].read_bytes()
        for state in ('marker', 'missing'):
            with self.subTest(snapshot=state):
                paths['snapshot'].write_bytes(normal_snapshot)
                self.assertTrue(self.query('updated')['results'])
                if state == 'marker':
                    paths['snapshot'].write_text('{"rebuild": "required"}\n', encoding='utf-8')
                else:
                    paths['snapshot'].unlink()
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                          for p in base.rglob('*') if p.is_file()}
                for rebuilt in (False, True):
                    if rebuilt:
                        self.assertFalse(self.search.rebuild(self.root)['index_stale'])
                    current = self.query('updated', task='T1')['results']
                    self.assertEqual(len(current), 1)
                    self.assertEqual(current[0]['item_id'], new['id'])
                    self.assertFalse(current[0]['history'])
                    self.assertEqual(current[0]['status'], 'active')
                    self.assertEqual(current[0]['path'], paths['events'].relative_to(self.root).as_posix())
                    event = json.loads(paths['events'].read_text(encoding='utf-8').splitlines()[current[0]['line'] - 1])
                    self.assertEqual(event['payload']['item']['metadata']['version'], 'updated conclusion')
                    for obsolete in ('original', 'pending-version'):
                        self.assertFalse(self.query(obsolete, task='T1')['results'])
                        historical = self.query(obsolete, task='T1', history=True)['results']
                        self.assertTrue(historical)
                        self.assertTrue(all(r['history'] and r['status'] == 'superseded' for r in historical))
                    self.assertTrue(self.query('updated', task='T1', history=True)['results'])
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                                         for p in base.rglob('*') if p.is_file()})

    def test_public_search_and_cli_accept_original_normalized_task_id(self):
        task_id = 'REVIEW / 1'
        base = self.publish(task_id)
        item = context.record(task_id, statement='normalized task fact', item_type='observation',
            actor='tester', source='file', base_dir=base)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for marker in (False, True):
            with self.subTest(marker=marker):
                if marker:
                    context._paths(task_id, base_dir=base)['snapshot'].write_text('{"rebuild":"required"}\n')
                self.assertEqual(self.query('normalized task fact', task=task_id)['results'][0]['item_id'], item['id'])
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/context_search.py'),
                    'search', 'normalized task fact', '--task', task_id], cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)['results'][0]['item_id'], item['id'])
                self.assertFalse(self.query('normalized task fact', task='REVIEW / 2')['results'])

    def test_cli_skips_non_utf8_ledger_sources_and_recovers(self):
        task_id = 'REVIEW / 1'
        base = self.publish(task_id)
        item = context.record(task_id, statement='healthy ledger fact', item_type='observation',
            actor='tester', source='file', base_dir=base)
        paths = context._paths(task_id, base_dir=base)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        command = [sys.executable, str(ROOT / 'scripts/context_search.py')]
        originals = {key: paths[key].read_bytes() for key in ('contract', 'snapshot', 'events')}
        for key, marker in (('contract', False), ('contract', True), ('snapshot', False),
                            ('events', False), ('events', True)):
            with self.subTest(source=key, marker=marker):
                for name, data in originals.items():
                    paths[name].chmod(0o600)
                    paths[name].write_bytes(data)
                if marker:
                    paths['snapshot'].write_text('{"rebuild":"required"}\n', encoding='utf-8')
                self.query('healthy')  # Also exercise invalidation of existing healthy chunks.
                paths[key].write_bytes(b'\xff')
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                          for p in base.rglob('*') if p.is_file()}
                for args in (['search', 'alpha'], ['rebuild'], ['search', 'alpha'],
                             ['search', 'healthy', '--task', task_id, '--history']):
                    result = subprocess.run([*command, *args], cwd=self.root, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    payload = json.loads(result.stdout)
                    self.assertFalse(payload['index_stale'])
                    self.assertEqual(payload['skipped'], [{
                        'path': paths[key].relative_to(self.root).as_posix(),
                        'reason': 'invalid UTF-8 at byte 0: invalid start byte',
                    }])
                    if args[:2] == ['search', 'alpha']:
                        self.assertEqual(payload['results'][0]['path'], 'docs/facts.md')
                    elif args[:2] == ['search', 'healthy'] and not (key == 'events' and marker):
                        self.assertTrue(any(row.get('item_id') == item['id'] for row in payload['results']))
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                                         for p in base.rglob('*') if p.is_file()})
                paths[key].write_bytes(originals[key])
                recovered = self.query('healthy', task=task_id)
                self.assertEqual(recovered['skipped'], [])
                self.assertEqual(recovered['results'][0]['item_id'], item['id'])

    def test_verified_then_overturned_fact_history_and_read_only_ledger(self):
        base = self.publish()
        old = context.record('T1', statement='先核实 旧事实已经成立', item_type='verified-fact',
            actor='tester', source={'kind': 'file', 'ref': 'original'}, evidence=['original'],
            scope='T1', verification_method='read original', base_dir=base)
        self.assertEqual(self.query('旧事实', task='T1')['results'][0]['item_id'], old['id'])
        new = context.record('T1', statement='后推翻 新事实取代原结论', item_type='verified-fact',
            actor='tester', source={'kind': 'file', 'ref': 'new original'}, evidence=['new original'],
            scope='T1', verification_method='read original', supersedes=old['id'], base_dir=base)
        before = {p: p.read_bytes() for p in base.rglob('*') if p.is_file()}
        self.assertFalse(self.query('旧事实', task='T1')['results'])
        current = self.query('新事实', task='T1', kind='fact')['results'][0]
        self.assertEqual(current['item_id'], new['id'])
        self.assertIn('verified_at', current)
        historical = self.query('旧事实', task='T1', history=True)['results']
        self.assertTrue(historical)
        for row in historical:
            self.assertTrue(row['history'])
            self.assertEqual(row['status'], 'superseded')
            self.assertEqual(row['superseded_by'], new['id'])
            raw = (self.root / row['path']).read_text(encoding='utf-8').splitlines()
            self.assertIn('旧事实', raw[row['line'] - 1])
        self.assertEqual(before, {p: p.read_bytes() for p in base.rglob('*') if p.is_file()})

    def test_stale_and_decision_filters(self):
        base = self.publish()
        with patch.object(context, '_now', return_value='2000-01-01T00:00:00Z'):
            context.record('T1', statement='mutable status fact', item_type='verified-fact',
                actor='tester', source='file', evidence=['file'], scope='T1',
                verification_method='read', mutable=True, ttl_hours=1, base_dir=base)
        context.record('T1', statement='decision search target', item_type='decision', actor='tester', source='file', base_dir=base)
        self.assertTrue(self.query('mutable', kind='fact')['results'][0]['stale'])
        self.assertEqual(len(self.query('decision', kind='decision')['results']), 1)
        self.assertFalse(self.query('mutable', task='T2')['results'])

    def test_cli_runs_from_project_and_rebuild_is_consistent(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        command = [sys.executable, str(ROOT / 'scripts/context_search.py')]
        def run(*args):
            result = subprocess.run([*command, *args], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        before = run('search', '协调者租约')['results'][0]
        (self.root / self.search.INDEX_PATH).unlink()
        self.assertFalse(run('rebuild')['index_stale'])
        after = run('search', '协调者租约')['results'][0]
        self.assertEqual((before['path'], before['line'], before['snippet'], before['score']),
                         (after['path'], after['line'], after['snippet'], after['score']))

    def test_unwritable_cache_returns_error_json_without_other_writes(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        cache = self.root / self.search.INDEX_PATH.parent
        cache.mkdir(parents=True)
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                  for p in self.root.rglob('*') if p.is_file()}
        cache.chmod(0o500)
        self.addCleanup(cache.chmod, 0o700)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/context_search.py'),
            'search', '协调者租约'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['error'])
        self.assertTrue(payload['index_stale'])
        self.assertEqual(list(cache.iterdir()), [])
        self.assertEqual(before, {
            p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in self.root.rglob('*') if p.is_file()
        })

    def _query_unwritable_existing_cache(self, changed):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        expected = self.query('alpha')
        if changed:
            self.doc.write_text('changed alpha fact', encoding='utf-8')
        cache = self.root / self.search.INDEX_PATH.parent
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                  for p in self.root.rglob('*') if p.is_file()}
        cache.chmod(0o500)
        self.addCleanup(cache.chmod, 0o700)
        self.assertFalse(os.access(cache, os.W_OK))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/context_search.py'),
            'search', 'alpha'], cwd=self.root, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        if changed:
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertTrue(payload['error'])
            self.assertTrue(payload['index_stale'])
        else:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(payload, expected)
        self.assertEqual(before, {
            p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in self.root.rglob('*') if p.is_file()
        })

    def test_cli_unwritable_existing_cache_with_changed_source_returns_error_json(self):
        self._query_unwritable_existing_cache(changed=True)

    def test_cli_unwritable_existing_cache_with_unchanged_source_returns_results(self):
        self._query_unwritable_existing_cache(changed=False)

    def test_cli_writes_only_its_index_with_bytecode_environment_unset(self):
        tools = self.root / 'tools'
        (tools / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'scripts/context_search.py', tools / 'scripts/context_search.py')
        shutil.copytree(ROOT / 'src', tools / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        before = {p.relative_to(tools): p.read_bytes() for p in tools.rglob('*') if p.is_file()}
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        env.pop('PYTHONPATH', None)
        # Apple Python has an implicit external pycache prefix. Force normal source-local
        # caching after interpreter startup so this oracle also catches writes on macOS.
        env['PYTHONPYCACHEPREFIX'] = str(self.root / 'interpreter-cache')
        bootstrap = ('import sys, runpy; sys.pycache_prefix=None; '
                     'sys.dont_write_bytecode=False; sys.argv=sys.argv[1:]; '
                     'runpy.run_path(sys.argv[0], run_name="__main__")')
        result = subprocess.run([sys.executable, '-c', bootstrap, str(tools / 'scripts/context_search.py'), 'search', '租约'],
            cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)['results'])
        self.assertEqual(before, {p.relative_to(tools): p.read_bytes() for p in tools.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
