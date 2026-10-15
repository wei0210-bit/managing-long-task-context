"""The probe runner must reject deliberately broken CLI implementations."""
import contextlib
from dataclasses import replace
import fnmatch
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import failure_probes as probes

ROOT = Path(__file__).resolve().parents[1]


class FailureProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def fake_entry(self, body, timeout=3, pending=False):
        script = self.root / 'fake.py'
        script.write_text(body, encoding='utf-8')
        variant = probes.Variant('encoding', 'fake', 'file',
                                 lambda path: path.write_bytes(b'probetoken\xff'))

        def scaffold(root):
            (root / 'target').write_text('probetoken', encoding='utf-8')

        def place(variant, root):
            path = root / 'target'
            variant.make(path)
            return path

        return probes.Entry('fake', scaffold, place, probes.CliAdapter(
            lambda root: [sys.executable, str(script)], lambda root: root,
            {'PATH': os.defpath}, timeout), (), lambda *args: ('pass', 'handled'),
            {'encoding': [variant]}, pending={'fake'} if pending else set())

    def run_fake(self, body, **kwargs):
        entry = self.fake_entry(body, **kwargs)
        report = probes.run(entry, temp_dir=self.root)
        return report, report['results'][0]

    def test_import_and_discovery_identity(self):
        self.assertEqual(Path(probes.__file__).resolve(), ROOT / 'tests/failure_probes.py')
        self.assertFalse(fnmatch.fnmatch(Path(probes.__file__).name, 'test*.py'))
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='failure_probes.py')
        self.assertEqual(suite.countTestCases(), 0)
        self.assertFalse((ROOT / 'tests/__init__.py').exists())

    def test_encoding_snapshot_and_cleanup(self):
        for variant in probes.encoding_variants():
            with self.subTest(variant=variant.name):
                tree = self.root / variant.name
                tree.mkdir()
                probes.search_scaffold(tree)
                target = probes.search_place(variant, tree)
                before = probes.snapshot(tree)
                self.assertEqual(before, probes.snapshot(tree))
                self.assertIn('sha256', before[target.relative_to(tree).as_posix()])
                self.assertNotIn(probes.TRACEBACK.encode(), target.read_bytes())
                probes.cleanup(tree)
                self.assertFalse(tree.exists())

    def test_snapshot_records_mutations_without_following_links(self):
        tree = self.root / 'tree'
        tree.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('untouched', encoding='utf-8')
        (tree / 'loop').symlink_to('loop')
        (tree / 'broken').symlink_to('missing')
        (tree / 'external').symlink_to(outside, target_is_directory=True)
        locked = tree / 'locked'
        locked.mkdir()
        (locked / 'file').write_bytes(b'content')
        locked.chmod(0)
        before = probes.snapshot(tree)
        self.assertEqual(before['loop']['link'], 'loop')
        self.assertEqual(before['external']['link'], str(outside))
        self.assertTrue(before['locked']['unreadable'])
        self.assertNotIn('external/keep', before)
        self.assertNotIn('locked/file', before)
        probes.cleanup(tree)
        self.assertEqual((outside / 'keep').read_text(), 'untouched')

    def test_snapshot_unreadable_file_is_not_opened(self):
        path = self.root / 'locked'
        path.write_bytes(b'probetoken')
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('opened unreadable file')):
            row = probes.snapshot(self.root)['locked']
        self.assertTrue(row['unreadable'])
        self.assertNotIn('sha256', row)

    def test_traceback_is_failure_even_when_pending(self):
        report, row = self.run_fake("raise RuntimeError('broken')\n", pending=True)
        self.assertEqual(row['verdict'], 'fail')
        self.assertIn('baseline 1', row['reason'])
        self.assertIn('RuntimeError', row['stderr_excerpt'])
        self.assertFalse(row['baseline']['1'])
        self.assertEqual(probes.exit_code(report), 1)

    def test_timeout_is_failure_with_partial_output(self):
        report, row = self.run_fake("import time\nprint('started', flush=True)\ntime.sleep(10)\n", timeout=1)
        self.assertEqual(row['verdict'], 'fail')
        self.assertIn('baseline 2: timeout', row['reason'])
        self.assertTrue(row['timed_out'])
        self.assertIn('started', row['stdout_excerpt'])
        self.assertEqual(probes.exit_code(report), 1)

    def test_outside_writable_write_is_failure(self):
        report, row = self.run_fake("from pathlib import Path\nPath('target').write_text('changed')\n")
        self.assertEqual(row['verdict'], 'fail')
        self.assertIn('baseline 3', row['reason'])
        self.assertIn('target', row['reason'])
        self.assertEqual(probes.exit_code(report), 1)

    def test_writable_prefix_has_path_boundary_and_allows_sqlite_sidecars(self):
        before = {'docs/a.md': {'sha256': 'a'}}
        after = dict(before)
        for suffix in ('', '-journal', '-wal', '-shm'):
            after['.prime/search/index.sqlite' + suffix] = {'sha256': 'b'}
        self.assertEqual(probes.changed_paths(before, after, ('.prime/search/',)), [])
        after['.prime/search-other/index.sqlite'] = {}
        after['docs/a.md'] = {'sha256': 'b'}
        self.assertEqual(probes.changed_paths(before, after, ('.prime/search/',)),
                         ['.prime/search-other/index.sqlite', 'docs/a.md'])

    def test_adapter_error_missing_interpreter_and_cwd(self):
        entry = self.fake_entry('pass\n')
        for adapter in (
            replace(entry.adapter, build_argv=lambda root: [str(self.root / 'missing-python')]),
            replace(entry.adapter, cwd=lambda root: root / 'missing-directory'),
        ):
            with self.subTest(adapter=adapter):
                report = probes.run(replace(entry, adapter=adapter), temp_dir=self.root)
                row = report['results'][0]
                self.assertEqual(row['verdict'], 'adapter_error')
                self.assertTrue(row['reason'])
                self.assertIsNone(row['exit_code'])
                self.assertEqual(probes.exit_code(report), 1)

    def test_adapter_environment_is_explicit(self):
        adapter = probes.CliAdapter(lambda root: [sys.executable, '-c',
            "import os; print(os.environ.get('PYTHONPATH', 'absent'))"], lambda root: root, {})
        with patch.dict(os.environ, {'PYTHONPATH': 'untrusted-parent'}):
            result = adapter.run(self.root)
        self.assertEqual(result['stdout'].strip(), 'absent')
        self.assertIsNone(result['adapter_error'])
        entry = probes.context_search_entry()
        self.assertEqual(set(entry.adapter.env), {'PATH', 'HOME', 'PYTHONPATH'})
        self.assertEqual(entry.adapter.env['PYTHONPATH'], str(ROOT / 'src'))

    def test_unprocessed_target_is_vacuous(self):
        report, row = self.run_fake('print(\'{"results": []}\')\n')
        self.assertEqual(row['verdict'], 'vacuous')
        self.assertEqual(probes.exit_code(report), 1)

    def test_processed_accepts_skip_error_and_snapshot_fallback(self):
        target = self.root / '.prime/context/T/snapshot.json'
        result = {'cwd': str(self.root), 'stderr': ''}
        label = '.prime/context/T/snapshot.json'
        for payload in ({'skipped': [{'path': label, 'reason': 'bad'}]},
                        {'error': 'failed reading ' + label},
                        {'results': [{'path': '.prime/context/T/events.jsonl'}]}):
            with self.subTest(payload=payload):
                result['stdout'] = json.dumps(payload)
                self.assertTrue(probes.processed(target, result, 'malformed_json'))
        self.assertFalse(probes.processed(target, result, 'encoding'))

    def test_excluded_variant_does_not_run(self):
        entry = self.fake_entry("raise RuntimeError('must not run')\n")
        report = probes.run(replace(entry, exclude={'fake': 'not applicable'}), temp_dir=self.root)
        row = report['results'][0]
        self.assertEqual(row['verdict'], 'excluded')
        self.assertEqual(row['reason'], 'not applicable')
        self.assertIsNone(row['target'])
        self.assertEqual(probes.exit_code(report), 0)

    def test_pending_expect_failure_does_not_affect_exit_code(self):
        entry = self.fake_entry('print(\'{"results": [{"path": "target"}]}\')\n', pending=True)
        for verdict in ('pass', 'fail'):
            with self.subTest(verdict=verdict):
                report = probes.run(replace(entry, expect=lambda *args: (verdict, 'expect test')),
                                    temp_dir=self.root)
                self.assertEqual(report['results'][0]['verdict'], verdict)
                self.assertTrue(report['results'][0]['pending'])
                self.assertEqual(probes.exit_code(report), 0)

    def test_expect_failure_and_undecided_are_failures(self):
        entry = self.fake_entry('print(\'{"results": [{"path": "target"}]}\')\n')
        for verdict in ('fail', 'undecided'):
            with self.subTest(verdict=verdict):
                report = probes.run(replace(entry, expect=lambda *args: (verdict, 'expect test')),
                                    temp_dir=self.root)
                self.assertEqual(probes.exit_code(report), 1)

    def test_known_signature_mismatch_fails_and_match_is_exempt(self):
        body = 'print(\'{"results": [{"path": "target"}]}\')\n'
        mismatch = ('https://github.com/wei0210-bit/managing-long-task-context/issues/1',
                    'expect，exit 0，line 6 != newline line 5')
        entry = replace(self.fake_entry(body), known={'fake': mismatch},
                        expect=lambda *args: ('fail', 'expect: line 7 != newline line 5'))
        report = probes.run(entry, temp_dir=self.root)
        row = report['results'][0]
        self.assertEqual(row['verdict'], 'fail')
        self.assertFalse(row['known']['matched'])
        self.assertEqual(row['known']['signature'], mismatch[1])
        self.assertEqual(probes.exit_code(report), 1)

        matched = ('https://github.com/wei0210-bit/managing-long-task-context/issues/1',
                   "底线 1，AttributeError: 'list' object has no attribute 'items'")
        entry = replace(self.fake_entry(
            "raise AttributeError(\"'list' object has no attribute 'items'\")\n"), known={'fake': matched})
        report = probes.run(entry, temp_dir=self.root)
        row = report['results'][0]
        self.assertEqual(row['verdict'], 'fail')
        self.assertTrue(row['known']['matched'], row['stderr_excerpt'])
        self.assertEqual(probes.exit_code(report), 0)

        entry = replace(self.fake_entry(
            "from pathlib import Path\nPath('target').write_text('changed')\n"
            "raise AttributeError(\"'list' object has no attribute 'items'\")\n"), known={'fake': matched})
        report = probes.run(entry, temp_dir=self.root)
        self.assertFalse(report['results'][0]['known']['matched'])
        self.assertEqual(probes.exit_code(report), 1)

    def test_known_now_passing_exits_1_and_pending_does_not(self):
        known = ('https://github.com/wei0210-bit/managing-long-task-context/issues/1',
                 'expect，exit 1，surrogates not allowed')
        entry = replace(self.fake_entry('print(\'{"results": [{"path": "target"}]}\')\n'),
                        known={'fake': known})
        stream = io.StringIO()
        with patch.object(probes, 'ENTRIES', {'fake': entry}), contextlib.redirect_stdout(stream):
            code = probes.main(['--entry', 'fake', '--output', str(self.root / 'known-pass.json')])
        self.assertEqual(code, 1)
        self.assertIn('KNOWN-NOW-PASSING fake', stream.getvalue())

        pending = self.fake_entry('print(\'{"results": [{"path": "target"}]}\')\n', pending=True)
        stream = io.StringIO()
        with patch.object(probes, 'ENTRIES', {'fake': pending}), contextlib.redirect_stdout(stream):
            code = probes.main(['--entry', 'fake', '--output', str(self.root / 'pending-pass.json')])
        self.assertEqual(code, 0)
        self.assertNotIn('KNOWN-NOW-PASSING', stream.getvalue())

    def test_baseline_violation_cannot_be_pending(self):
        entry = self.fake_entry('pass\n')
        known = {'fake': ('https://github.com/wei0210-bit/managing-long-task-context/issues/1',
                          '底线 1，AttributeError')}
        with self.assertRaises(ValueError) as raised:
            replace(entry, known=known, pending={'fake'})
        self.assertIn('pending', str(raised.exception))

    def test_silent_ignore_of_malformed_json_and_deep_nesting_fails(self):
        script = self.root / 'silent.py'
        script.write_text('print(\'{"results": []}\')\n', encoding='utf-8')
        for category in ('malformed_json', 'deep_nesting'):
            with self.subTest(category=category):
                variant = probes.Variant(category, 'silent', 'file',
                                         lambda path: path.write_text('{"a":"probetoken"}', encoding='utf-8'))

                def place(ignored, root):
                    path = root / 'target'
                    variant.make(path)
                    return path

                entry = probes.Entry(
                    'fake', lambda root: (root / 'target').write_text('probetoken', encoding='utf-8'),
                    place, probes.CliAdapter(lambda root: [sys.executable, str(script)], lambda root: root,
                                             {'PATH': os.defpath}, 3), (),
                    lambda *args: ('pass', 'should not be reached'), {category: [variant]})
                report = probes.run(entry, temp_dir=self.root)
                row = report['results'][0]
                self.assertEqual(row['verdict'], 'vacuous')
                self.assertIn('target was not processed', row['reason'])
                self.assertEqual(probes.exit_code(report), 1)

    def test_expect_accepts_fallback_skip_and_rejects_shifted_lines(self):
        probes.search_scaffold(self.root)
        snapshot = self.root / '.prime/context/T/snapshot.json'
        label = '.prime/context/T/snapshot.json'
        others = [{'path': 'CONTEXT.md'}, {'path': 'docs/a.md'},
                  {'path': '.prime/context/T/task-contract.json'}]
        malformed = next(item for item in probes.malformed_json_variants() if item.name == 'truncated-snapshot')
        fallback = {'cwd': str(self.root), 'exit_code': 0, 'stdout': json.dumps({
            'results': others + [{'path': '.prime/context/T/events.jsonl'}], 'skipped': []})}
        self.assertEqual(probes.search_expect(malformed, snapshot, fallback)[0], 'pass')
        skipped = {'cwd': str(self.root), 'exit_code': 0, 'stdout': json.dumps({
            'results': others, 'skipped': [{'path': label, 'reason': 'bad json'}]})}
        self.assertEqual(probes.search_expect(malformed, snapshot, skipped)[0], 'pass')
        deep = next(item for item in probes.deep_nesting_variants() if item.name == 'array-snapshot')
        self.assertEqual(probes.search_expect(deep, snapshot, skipped)[0], 'pass')

        doc = self.root / 'docs/a.md'
        doc_rows = [{'path': 'CONTEXT.md'}, {'path': '.prime/context/T/task-contract.json'},
                    {'path': label}, {'path': 'docs/a.md', 'line': 6}]
        shifted = next(item for item in probes.special_chars_variants() if item.name == 'doc-u2028')
        shifted.make(doc)
        reported = {'cwd': str(self.root), 'exit_code': 0,
                    'stdout': json.dumps({'results': doc_rows, 'skipped': []})}
        verdict, reason = probes.search_expect(shifted, doc, reported)
        self.assertEqual(verdict, 'fail')
        self.assertIn('line 6 != newline line 5', reason)
        normal = next(item for item in probes.special_chars_variants() if item.name == 'newline-doc')
        normal.make(doc)
        self.assertEqual(probes.search_expect(normal, doc, reported)[0], 'pass')

    def test_new_category_snapshots_and_cleanup(self):
        groups = (probes.malformed_json_variants(), probes.deep_nesting_variants(),
                  probes.special_chars_variants())
        for variants in groups:
            for variant in variants:
                with self.subTest(variant=variant.name):
                    tree = self.root / variant.name
                    tree.mkdir()
                    probes.search_scaffold(tree)
                    target = probes.search_place(variant, tree)
                    before = probes.snapshot(tree)
                    self.assertEqual(before, probes.snapshot(tree))
                    relative = target.relative_to(tree).as_posix()
                    self.assertIn('sha256', before[relative])
                    self.assertNotIn(probes.TRACEBACK.encode(), target.read_bytes())
                    probes.cleanup(tree)
                    self.assertFalse(tree.exists())

    def test_four_categories_known_baseline_exits_zero(self):
        report = probes.run(probes.context_search_entry(),
                            ['encoding', 'malformed_json', 'deep_nesting', 'special_chars'],
                            temp_dir=self.root)
        self.assertEqual(probes.exit_code(report), 0, [
            (row['variant'], row['verdict'], row['reason'], row['known'])
            for row in report['results'] if probes.exit_code({'results': [row]})])
        by_name = {row['variant']: row for row in report['results']}
        self.assertTrue(by_name['bom-doc']['pending'])
        self.assertEqual(by_name['bom-doc']['verdict'], 'pass')
        self.assertFalse(by_name['bom-doc']['known'])
        for name in ('malformed-normal', 'nesting-normal', 'newline-doc'):
            self.assertEqual(by_name[name]['verdict'], 'pass', name)
            self.assertFalse(by_name[name]['known'])
            self.assertFalse(by_name[name]['pending'])
        entry = probes.context_search_entry()
        for name in ('items-list', 'item-string', 'array-events', 'object-events'):
            self.assertTrue(by_name[name]['known']['signature'].startswith('底线 1'), name)
            self.assertTrue(by_name[name]['known']['matched'], by_name[name])
            self.assertNotIn(name, entry.pending)
        for row in report['results']:
            if row['verdict'] == 'pass':
                continue
            self.assertTrue(row['known']['matched'], row)
            self.assertTrue(str(row['known']['issue']).startswith(
                'https://github.com/wei0210-bit/managing-long-task-context/issues/'))
            self.assertFalse(row['pending'])

    def test_real_encoding_entry_and_report_fields(self):
        report = probes.run(probes.context_search_entry(), ['encoding'], temp_dir=self.root)
        self.assertEqual(probes.exit_code(report), 0, report)
        self.assertEqual(report['counts']['pass'], 6)
        self.assertEqual(report['counts']['skipped'], 0)
        fields = {'category', 'variant', 'target', 'verdict', 'known', 'pending', 'reason',
                  'exit_code', 'timed_out', 'stdout_excerpt', 'stderr_excerpt', 'baseline'}
        for row in report['results']:
            self.assertTrue(fields.issubset(row))
            self.assertEqual(row['baseline'], {'1': True, '2': True, '3': True})
            self.assertEqual(row['pending'], row['variant'] == 'bom-doc')
            self.assertFalse(row['known'])

    def test_cli_output_default_path_and_argument_errors(self):
        output = self.root / 'reports/result.json'
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = probes.main(['--entry', 'context_search', '--category', 'encoding',
                                '--output', str(output)])
        self.assertEqual(code, 0)
        self.assertIn('REPORT ' + str(output), stream.getvalue())
        self.assertEqual(json.loads(output.read_text())['entry'], 'context_search')
        report = {'results': [], 'counts': {'skipped': 1}}
        with patch.object(probes, 'run', return_value=report), \
                patch.object(probes.tempfile, 'gettempdir', return_value=str(self.root)), \
                contextlib.redirect_stdout(stream):
            self.assertEqual(probes.main(['--entry', 'context_search']), 0)
        self.assertEqual(stream.getvalue().splitlines()[-1], 'SKIPPED 1')
        self.assertEqual(len(list((self.root / 'failure-probes').glob('context_search-*.json'))), 1)
        for argv in ([], ['--entry', 'missing'], ['--entry', 'context_search', '--category', 'missing']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    probes.main(argv)
                self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
