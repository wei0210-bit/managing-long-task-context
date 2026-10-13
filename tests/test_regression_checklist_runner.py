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


class R001WholeBlockTests(unittest.TestCase):
    setUp = RegressionChecklistRunnerTests.setUp
    run_checklist = RegressionChecklistRunnerTests.run_checklist

    def test_later_success_makes_whole_block_fail_r001_acceptance(self):
        result = self.run_checklist('### R-001 whole block\n```sh\nfalse\ntrue\n```\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('R-001 fail exit=0', result.stdout)

    def test_single_no_match_grep_passes(self):
        result = self.run_checklist("### R-001 grep\n```sh\nprintf '' | grep absent\n```\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('R-001 pass exit=1', result.stdout)

    def test_continued_command_runs_as_whole_block(self):
        code = "false\nprintf '%s' \\\n  '' | grep absent"
        result = self.run_checklist('### R-001 continued\n```sh\n' + code + '\n```\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('R-001 pass exit=1', result.stdout)


class OnlyAndBlankTests(unittest.TestCase):
    setUp = RegressionChecklistRunnerTests.setUp
    run_checklist = RegressionChecklistRunnerTests.run_checklist

    def test_only_runs_selected_entries_in_checklist_order_once_and_logs_them(self):
        logs = self.root / 'logs'
        content = ('### R-100 first\n```sh\necho first >> order\n```\n'
                   '### R-101 second\n```sh\necho second >> order; false\n```\n'
                   '### R-102 excluded\n```sh\ntouch excluded\n```\n')
        result = self.run_checklist(content, '--only', 'R-101', '--only', 'R-100',
                                    '--only', 'R-100', '--log-dir', str(logs))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, 'R-100 pass exit=0\nR-101 fail exit=1\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual((self.root / 'order').read_text(), 'first\nsecond\n')
        self.assertFalse((self.root / 'excluded').exists())
        summary = json.loads((logs / 'summary.json').read_text())
        self.assertEqual([row['id'] for row in summary['entries']], ['R-100', 'R-101'])
        self.assertEqual(summary['exit_code'], 1)
        self.assertEqual({path.name for path in logs.iterdir()},
                         {'R-100.log', 'R-101.log', 'summary.json'})

    def test_only_single_entry_passes(self):
        result = self.run_checklist('### R-100 first\n```sh\ntouch selected\n```\n'
                                    '### R-101 excluded\n```sh\nfalse\n```\n',
                                    '--only', 'R-100')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'R-100 pass exit=0\n')
        self.assertEqual(result.stderr, '')
        self.assertTrue((self.root / 'selected').exists())

    def test_only_reports_all_invalid_ids_before_running_or_writing_summary(self):
        content = ('### R-100 valid\n```sh\ntouch ran\n```\n'
                   '### R-102 retired\nAdded: x\nRetired (#1, obsolete)\n'
                   '```sh\ntouch retired\n```\n'
                   '### R-103 manual\nWalkthrough: read it.\n')
        bad = [('R-999', '条目不存在'), ('R-102', '条目已退役'),
               ('R-103', '没有 sh 命令块')]
        for selection in [[item] for item in bad] + [bad]:
            with self.subTest(selection=selection):
                args = ['--only', 'R-100']
                for rid, reason in selection:
                    args.extend(['--only', rid, '--only', rid])
                logs = self.root / 'logs'
                result = self.run_checklist(content, *args, '--log-dir', str(logs))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, ''.join(
                    rid + ': ' + reason + '\n' for rid, reason in selection))
                self.assertFalse((self.root / 'ran').exists())
                self.assertFalse((self.root / 'retired').exists())
                self.assertFalse((logs / 'summary.json').exists())

    def test_only_matches_ids_literally_without_padding_or_case_changes(self):
        for rid in ['R-40', 'r-040', 'R-040 ']:
            with self.subTest(rid=rid):
                result = self.run_checklist('### R-040 valid\n```sh\ntouch ran\n```\n',
                                            '--only', rid)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, rid + ': 条目不存在\n')
                self.assertFalse((self.root / 'ran').exists())

    def test_blank_blocks_fail_in_full_and_only_runs_including_mixed_blocks(self):
        for code in ['', '  \t', '\n \t\n']:
            for selected in [False, True]:
                with self.subTest(code=code, selected=selected):
                    logs = self.root / 'logs'
                    args = ['--only', 'R-100'] if selected else []
                    result = self.run_checklist('### R-100 blank\n```sh\n' + code + '\n```\n',
                                                *args, '--log-dir', str(logs))
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, 'R-100 fail exit=2\n')
                    self.assertEqual(result.stderr, 'R-100: 空白命令块\n')
                    row = json.loads((logs / 'summary.json').read_text())['entries'][0]
                    self.assertEqual(row['blocks'],
                                     [{'index': 1, 'step': 1, 'exit_code': 2, 'pass': False}])
        for blocks in [('false', ' ', 'touch after'), (' ', 'touch after', 'false')]:
            for selected in [False, True]:
                with self.subTest(blocks=blocks, selected=selected):
                    content = '### R-100 mixed\n' + ''.join(
                        '```sh\n' + code + '\n```\n' for code in blocks)
                    args = ['--only', 'R-100'] if selected else []
                    result = self.run_checklist(content, *args)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, 'R-100 fail exit=2\n')
                    self.assertEqual(result.stderr, 'R-100: 空白命令块\n')
                    self.assertTrue((self.root / 'after').exists())

    def test_blank_blocks_do_not_call_bash_and_precede_special_rules(self):
        import runpy
        from unittest.mock import patch
        run_entry = runpy.run_path(str(SCRIPT))['run_entry']
        for rid in ['R-100', 'R-001', 'R-007', 'R-026']:
            with self.subTest(rid=rid), patch('subprocess.run') as bash:
                bash.return_value = subprocess.CompletedProcess([], 0, b'', b'')
                row, output = run_entry(rid, False, [' \t\n'], self.root, 1)
                bash.assert_not_called()
                self.assertEqual(row['status'], 'fail')
                self.assertEqual(row['exit_code'], 2)
                self.assertEqual(row['error'], '空白命令块')
                self.assertEqual(output, (rid + ': 空白命令块\n').encode('utf-8'))


if __name__ == '__main__':
    unittest.main()
