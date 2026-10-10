"""Exercise the repository-only checklist runner through its CLI."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/regression_checklist.py'


class RegressionChecklistRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checklist = self.root / 'checklist.md'

    def run_checklist(self, content, *args):
        if content is not None:
            self.checklist.write_text(content, encoding='utf-8')
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root),
                               '--checklist', str(self.checklist), *args],
                              capture_output=True, text=True)

    def test_earlier_failure_cannot_be_hidden_by_later_success(self):
        result = self.run_checklist('### R-002 failure\n```sh\nfalse\necho hidden > marker\n```\n'
                                    '### R-003 success\n```sh\necho success\n```\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('R-002 fail exit=1', result.stdout)
        self.assertIn('R-003 pass exit=0', result.stdout)
        self.assertFalse((self.root / 'marker').exists())

    def test_r001_requires_exit_one_and_empty_stdout(self):
        for code, expected in [('exit 1', 'pass'), ('true', 'fail'),
                               ('echo unexpected; exit 1', 'fail'), ('exit 2', 'fail')]:
            with self.subTest(code=code):
                result = self.run_checklist('### R-001 rule\n```sh\n' + code + '\n```\n')
                self.assertEqual(result.returncode, int(expected == 'fail'), result.stderr)
                self.assertIn('R-001 ' + expected, result.stdout)

    def test_retired_and_manual_entries_do_not_execute(self):
        result = self.run_checklist('### R-002 retired\nRetired (obsolete)\n```sh\nfalse\n```\n'
                                    '### R-003 manual\nWalkthrough: read the rules.\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['R-002 retired exit=0', 'R-003 manual exit=0'])

    def test_every_block_runs_and_failure_is_retained(self):
        result = self.run_checklist('### R-002 two blocks\n```sh\nfalse\n```\n'
                                    '```sh\necho second > second\n```\n')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('R-002 fail exit=1', result.stdout)
        self.assertEqual((self.root / 'second').read_text().strip(), 'second')

    def test_log_directory_retains_streams_and_sha256(self):
        logs = self.root / 'logs'
        result = self.run_checklist('### R-002 output\n```sh\necho hello; echo diagnostic >&2\n```\n',
                                    '--log-dir', str(logs))
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((logs / 'summary.json').read_text())
        row = summary['entries'][0]
        self.assertEqual(row['id'], 'R-002')
        self.assertEqual(row['status'], 'pass')
        raw = (logs / row['output_file']).read_bytes()
        self.assertIn(b'hello', raw)
        self.assertIn(b'diagnostic', raw)
        self.assertEqual(row['output_sha256'], hashlib.sha256(raw).hexdigest())

    def test_invalid_checklist_is_exit_two_without_traceback(self):
        for content in [None, 'no entries', '### R-002 bad\n```sh\ntrue\n']:
            with self.subTest(content=content):
                result = self.run_checklist(content)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_timeout_is_reported_as_failure(self):
        result = self.run_checklist('### R-002 timeout\n```sh\nexec sleep 5\n```\n',
                                    '--timeout', '0.05')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('R-002 fail exit=124', result.stdout)

    def test_r007_checks_each_expected_exit_and_both_counts(self):
        good = "exit 1\nprintf 'CLAUDE.md:1\\nAGENTS.md:2\\n'\nprintf 'CLAUDE.md:1\\nAGENTS.md:1\\n'\nprintf 'CLAUDE.md:2\\nAGENTS.md:1\\n'\n"
        for code, expected in [(good, 0), (good.replace('exit 1', 'echo forbidden; exit 1'), 1),
                               (good.replace('CLAUDE.md:1', 'CLAUDE.md:0'), 1),
                               (good.replace('AGENTS.md:2', 'OTHER.md:2'), 1),
                               (good.replace('exit 1', 'exit 0'), 1),
                               (good.replace("printf 'CLAUDE.md:1\\nAGENTS.md:2\\n'", 'exit 2'), 1)]:
            with self.subTest(code=code):
                result = self.run_checklist('### R-007 counts\n```sh\n' + code + '```\n')
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_r026_requires_zero_count_even_when_second_command_passes(self):
        for code, expected in [('printf 0; true', 0), ('printf 0; exit 1; true', 0),
                               ('printf 2; true', 1), ('printf 0; false', 1)]:
            # The first command may return 1 for the zero-match grep case.
            if code == 'printf 0; exit 1; true':
                code = "bash -c 'printf 0;exit 1'; true"
            with self.subTest(code=code):
                result = self.run_checklist('### R-026 counts\n```sh\n' + code + '\n```\n')
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_special_entry_shape_change_fails_closed(self):
        for rid, code in [('R-007', 'exit 1\ntrue\ntrue'), ('R-007', 'exit 1\ntrue\ntrue\ntrue\ntrue'),
                          ('R-026', 'true'), ('R-026', 'printf 0; true; true')]:
            with self.subTest(rid=rid, code=code):
                logs = self.root / 'logs'
                result = self.run_checklist('### ' + rid + '\n```sh\n' + code + '\n```\n',
                                            '--log-dir', str(logs))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('特殊条目形状已变', (logs / (rid + '.log')).read_text())


if __name__ == '__main__':
    unittest.main()
