"""Replay the five historical failures against complete, isolated source trees."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import failure_probes as probes

ROOT = Path(__file__).resolve().parents[1]


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix='failure-replay-')).resolve()
        self.addCleanup(probes.cleanup, self.workspace)

    def unavailable(self, reason):
        if os.environ.get('CI') == 'true':
            self.fail('historical replay unavailable in CI: ' + reason)
        self.skipTest(reason)

    def require_commit(self, revision):
        result = subprocess.run(['git', 'cat-file', '-e', revision + '^{commit}'],
                                cwd=ROOT, capture_output=True, timeout=30)
        if result.returncode:
            self.unavailable('missing historical commit (possibly shallow clone): ' + revision)

    def require_nonroot(self):
        if os.geteuid() == 0:
            self.unavailable('root can read 0000 directories; unreadable replay is invalid')

    def export_pair(self, broken, fixed):
        for revision in (broken, fixed):
            self.require_commit(revision)
        trees = []
        for revision in (broken, fixed):
            tree = self.workspace / revision
            tree.mkdir()
            archive = self.workspace / (revision + '.tar')
            subprocess.run(['git', 'archive', '--format=tar', '--output', str(archive), revision],
                           cwd=ROOT, check=True, capture_output=True, timeout=30)
            subprocess.run(['tar', '-xf', str(archive), '-C', str(tree)],
                           check=True, capture_output=True, timeout=30)
            trees.append(tree)
        return trees

    def environment(self, tree):
        return {'PATH': os.defpath, 'HOME': str(self.workspace),
                'PYTHONPATH': str(tree / 'src'), 'TMPDIR': str(self.workspace)}

    def fixture(self):
        root = self.workspace / 'fixture'
        root.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(root)], check=True,
                       env={'PATH': os.defpath, 'HOME': str(self.workspace)},
                       capture_output=True, timeout=30)
        (root / 'tests').mkdir()
        (root / 'tests/test_visible.py').write_text('# probetoken control\n', encoding='utf-8')
        return root

    def run_precheck(self, tree, root, *arguments):
        result = probes.CliAdapter(
            lambda _: [sys.executable, '-B', tree / 'scripts/contract_precheck.py',
                       '--repo', root, *arguments],
            lambda _: tree, self.environment(tree)).run(root)
        self.assertIsNone(result['adapter_error'], result)
        self.assertFalse(result['timed_out'], result)
        return result

    def ok_precheck(self, result):
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(result['stderr'], '', result)
        payload = json.loads(result['stdout'])
        self.assertEqual(payload['status'], 'ok', result)
        return payload

    def rejected_precheck(self, result, path, message):
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(result['stdout'], '', result)
        self.assertIn(str(path), result['stderr'], result)
        self.assertIn(message, result['stderr'], result)
        self.assertNotIn(probes.TRACEBACK, result['stderr'], result)

    def test_unreadable_tests_subdirectory(self):
        self.require_nonroot()
        broken, fixed = self.export_pair('18f5d27', '08fe6ac')
        root = self.fixture()
        locked = root / 'tests/locked'
        locked.mkdir()
        (locked / 'test_hidden.py').write_text('# probetoken hidden\n', encoding='utf-8')
        locked.chmod(0)
        with self.assertRaises(PermissionError):
            os.listdir(str(locked))
        before = self.ok_precheck(self.run_precheck(broken, root, '--term', 'probetoken'))
        self.assertEqual(before['test_modules'], ['tests.test_visible'])
        self.assertEqual([hit['file'] for hit in before['terms'][0]['hits']],
                         ['tests/test_visible.py'])
        after = self.run_precheck(fixed, root, '--term', 'probetoken')
        self.rejected_precheck(after, locked, 'Permission denied')

    def test_directory_symlink_under_tests(self):
        broken, fixed = self.export_pair('08fe6ac', '6452fc8')
        root = self.fixture()
        target = root / 'modules'
        target.mkdir()
        (target / 'test_hidden.py').write_text('# probetoken hidden\n', encoding='utf-8')
        link = root / 'tests/linked'
        link.symlink_to(target, target_is_directory=True)
        before = self.ok_precheck(self.run_precheck(broken, root, '--term', 'probetoken'))
        self.assertEqual(before['test_modules'], ['tests.test_visible'])
        self.assertEqual([hit['file'] for hit in before['terms'][0]['hits']],
                         ['tests/test_visible.py'])
        self.rejected_precheck(self.run_precheck(fixed, root, '--term', 'probetoken'),
                               link, 'symlink is not allowed')

    def test_unicode_separator_preserves_physical_line_number(self):
        broken, fixed = self.export_pair('6452fc8', '07ed704')
        root = self.fixture()
        source = '# separator\u2028still the first line\n# probetoken target\n'
        (root / 'tests/test_lines.py').write_text(source, encoding='utf-8')
        expected = source.split('\n').index('# probetoken target') + 1
        for tree, line in ((broken, expected + 1), (fixed, expected)):
            payload = self.ok_precheck(self.run_precheck(tree, root, '--term', 'probetoken'))
            hits = [hit for hit in payload['terms'][0]['hits']
                    if hit['file'] == 'tests/test_lines.py']
            self.assertEqual(hits, [{'file': 'tests/test_lines.py', 'line': line,
                                     'text': '# probetoken target'}])

    def test_argument_symlink_loop(self):
        broken, fixed = self.export_pair('6452fc8', '07ed704')
        root = self.fixture()
        loop = root / 'loop.py'
        loop.symlink_to('loop.py')
        before = self.run_precheck(broken, root, '--path', 'loop.py')
        self.assertEqual(before['exit_code'], 1, before)
        self.assertEqual(before['stdout'], '', before)
        self.assertIn(probes.TRACEBACK, before['stderr'], before)
        self.assertIn('RuntimeError: Symlink loop', before['stderr'], before)
        self.assertIn(str(loop), before['stderr'], before)
        self.rejected_precheck(self.run_precheck(fixed, root, '--path', 'loop.py'),
                               loop, 'cannot resolve --path')

    def test_bad_contract_with_valid_snapshot(self):
        trees = self.export_pair('ec376bd', '4d63796')
        root = self.fixture()
        task = root / '.prime/context/T'
        task.mkdir(parents=True)
        contract = task / 'task-contract.json'
        contract.write_bytes(b'\xff\xfeprobetoken invalid contract\n')
        (task / 'snapshot.json').write_text(json.dumps({'task_id': 'T', 'items': {
            'I1': {'id': 'I1', 'kind': 'fact', 'status': 'active',
                   'text': 'probetoken item'}}}), encoding='utf-8')
        for tree, exit_code in zip(trees, (1, 0)):
            # Each historical version starts cold and must import its own src/.
            cache = root / '.prime/search'
            if cache.exists():
                probes.cleanup(cache)
            result = probes.CliAdapter(
                lambda _: [sys.executable, '-B', tree / 'scripts/context_search.py',
                           'search', 'probetoken'],
                lambda _: root, self.environment(tree)).run(root)
            self.assertIsNone(result['adapter_error'], result)
            self.assertFalse(result['timed_out'], result)
            self.assertEqual(result['exit_code'], exit_code, result)
            self.assertEqual(result['stderr'], '', result)
            payload = json.loads(result['stdout'])
            if exit_code:
                self.assertIn('cannot read valid JSON', payload['error'])
                self.assertIn(str(contract), payload['error'])
                self.assertIn('utf-8', payload['error'])
                self.assertNotIn('results', payload)
            else:
                self.assertNotIn('error', payload)
                self.assertTrue(any(row.get('item_id') == 'I1'
                                    and row['path'] == '.prime/context/T/snapshot.json'
                                    and 'probetoken' in row['snippet']
                                    for row in payload['results']), payload)
                self.assertTrue(any(row['path'] == '.prime/context/T/task-contract.json'
                                    for row in payload['skipped']), payload)

    def test_missing_commit_is_failure_in_ci(self):
        missing = subprocess.CompletedProcess([], 1, b'', b'missing commit')
        with patch.dict(os.environ, {'CI': 'true'}), \
                patch.object(subprocess, 'run', return_value=missing):
            with self.assertRaisesRegex(AssertionError, 'missing historical commit'):
                self.require_commit('18f5d27')

    def test_missing_commit_is_explicit_local_skip(self):
        missing = subprocess.CompletedProcess([], 1, b'', b'missing commit')
        with patch.dict(os.environ, {'CI': ''}), \
                patch.object(subprocess, 'run', return_value=missing):
            with self.assertRaisesRegex(unittest.SkipTest, 'missing historical commit'):
                self.require_commit('18f5d27')

    def test_root_is_failure_in_ci_and_explicit_local_skip(self):
        with patch.object(os, 'geteuid', return_value=0):
            with patch.dict(os.environ, {'CI': 'true'}):
                with self.assertRaisesRegex(AssertionError, 'root can read 0000'):
                    self.require_nonroot()
            with patch.dict(os.environ, {'CI': ''}):
                with self.assertRaisesRegex(unittest.SkipTest, 'root can read 0000'):
                    self.require_nonroot()


if __name__ == '__main__':
    unittest.main()
