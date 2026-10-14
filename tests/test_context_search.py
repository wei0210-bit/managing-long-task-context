"""Public searches return source locations and refresh their disposable cache."""
import importlib.util
import json
from pathlib import Path
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
        self.root = Path(self.temp.name)
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

    def test_explicit_include_does_not_leak_into_default_query(self):
        memory = self.root / 'memory'
        memory.mkdir()
        (memory / 'entry.md').write_text('secret memory fact', encoding='utf-8')
        self.assertFalse(self.query('secret')['results'])
        self.assertEqual(self.query('secret', include=[memory])['results'][0]['path'], 'memory/entry.md')
        self.assertFalse(self.query('secret')['results'])

    def test_index_is_ignored_and_outside_publish_paths(self):
        label = self.search.INDEX_PATH.as_posix()
        self.assertFalse(any(label == p or label.startswith(p + '/') for p in CONTEXT_PATHS))
        # Standalone packages deliberately have no Git metadata or root .gitignore.
        if (ROOT / '.git').exists():
            result = subprocess.run(['git', 'check-ignore', '.prime/search/index.sqlite'], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def publish(self):
        base = self.root / RELATIVE_CONTEXT
        context.publish_contract({'task_id': 'T1', 'version': 1, 'issued_by': 'tester',
            'issued_at': '2026-10-14T00:00:00Z', 'objective': 'Record facts', 'scope': [],
            'out_of_scope': [], 'constraints': [], 'acceptance_criteria': [
                {'id': 'AC-1', 'criterion': 'Search source files', 'required_evidence': ['file']}]},
            confirmed_by='tester', base_dir=base)
        return base

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


if __name__ == '__main__':
    unittest.main()
