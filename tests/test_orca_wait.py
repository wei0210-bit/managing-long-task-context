"""Wait protocol and power checks with fake external commands and a virtual clock."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/orca_wait.py'
AC = "Now drawing from 'AC Power'\n -InternalBattery-0 100%; charged;\n"
BATTERY = "Now drawing from 'Battery Power'\n -InternalBattery-0 80%; discharging;\n"
BATCH = {'deliveryId': 'delivery-work', 'messages': [
    {'id': 'msg-work', 'type': 'worker_done', 'body': '工作完成'}], 'dispatchIds': ['ctx_work']}


def receipt(result):
    return subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'result': result}), '')


class OrcaWaitTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'orca_wait.py must exist before the wait protocol can run')
        spec = importlib.util.spec_from_file_location('orca_wait_under_test', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = 0.0
        self.sleeps = []
        self.calls = []
        self.process = Mock()
        self.process.poll.return_value = None

    def execute(self, responses, *args, power=AC):
        pending = iter(responses)
        out, err = io.StringIO(), io.StringIO()

        def run(command, **kwargs):
            if command[0] == 'fake-pmset':
                self.assertEqual(command, ['fake-pmset', '-g', 'batt'])
                if isinstance(power, Exception):
                    raise power
                return subprocess.CompletedProcess(command, 0, power, '')
            self.assertEqual(command[0], 'fake-orca')
            self.calls.append((command, kwargs))
            response = next(pending)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response()
            return response

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        with patch.object(self.module.subprocess, 'run', side_effect=run), \
                patch.object(self.module.subprocess, 'Popen', return_value=self.process) as caffeine, \
                patch.object(self.module.time, 'monotonic', side_effect=lambda: self.now), \
                patch.object(self.module.time, 'sleep', side_effect=sleep), \
                redirect_stdout(out), redirect_stderr(err):
            code = self.module.main(['--run', 'run-test', '--orca', 'fake-orca',
                '--pmset', 'fake-pmset', '--caffeinate', 'fake-caffeinate', *args])
        return code, out.getvalue(), err.getvalue(), caffeine

    def test_heartbeat_and_status_ack_only_with_next_wait(self):
        beat = {'deliveryId': 'delivery-heartbeat', 'messages': [
            {'type': 'heartbeat'}, {'type': 'status'}], 'dispatchIds': ['ctx_beat']}
        log = self.root / 'wait.jsonl'
        code, out, _, _ = self.execute([receipt(beat), receipt(BATCH)], '--ack', 'delivery-previous', '--log', str(log))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), BATCH)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0], ['fake-orca', 'orchestration', 'check', '--run', 'run-test',
            '--ack', 'delivery-previous', '--wait', '--timeout-ms', '3600000', '--json'])
        self.assertEqual(self.calls[1][0], ['fake-orca', 'orchestration', 'check', '--run', 'run-test',
            '--ack', 'delivery-heartbeat', '--wait', '--timeout-ms', '3600000', '--json'])
        self.assertTrue(any(row.get('deliveryId') == 'delivery-heartbeat'
            for row in map(json.loads, log.read_text().splitlines())))

    def test_mixed_batch_prints_whole_batch_without_ack(self):
        batch = {**BATCH, 'messages': [{'type': 'heartbeat'}, *BATCH['messages']]}
        code, out, _, _ = self.execute([receipt(batch)])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(json.loads(out), batch)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('--ack', self.calls[0][0])

    def test_timeouts_rehang_immediately_without_ack(self):
        code, _, _, _ = self.execute([receipt({'timedOut': True, 'messages': []}), receipt(BATCH)], '--ack', 'prior')
        self.assertEqual(code, 0)
        self.assertNotIn('--ack', self.calls[1][0])
        self.assertEqual(self.sleeps, [])

    def test_retryable_errors_back_off_then_recover(self):
        responses = [subprocess.CompletedProcess([], 0, 'not json', ''),
            subprocess.CompletedProcess([], 1, '', 'offline'),
            receipt({'connectionLost': True}), receipt({'cancelled': True}),
            subprocess.CompletedProcess([], 0, json.dumps({'ok': False, 'error': {'code': 'runtime_unavailable'}}), ''),
            OSError('disconnected'), receipt(BATCH)]
        code, out, _, _ = self.execute(responses)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), BATCH)
        self.assertEqual(self.sleeps, [1, 2, 4, 8, 15, 15])
        self.assertEqual(len(self.calls), 7)

    def test_fatal_errors_exit_four_immediately(self):
        for error in ('consumer_fenced', 'run_not_found', 'stable_pane_required', 'invalid_argument'):
            with self.subTest(error=error):
                self.calls.clear()
                self.sleeps.clear()
                code, out, _, _ = self.execute([subprocess.CompletedProcess([], 1,
                    json.dumps({'ok': False, 'error': {'code': error}}), '')])
                self.assertEqual(code, 4)
                self.assertEqual(out, '')
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.sleeps, [])

    def test_twenty_failures_stop_with_capped_backoff(self):
        code, out, _, _ = self.execute([receipt({'connectionLost': True})] * 20)
        self.assertEqual(code, 4)
        self.assertEqual(out, '')
        self.assertEqual(len(self.calls), 20)
        self.assertEqual(self.sleeps, [1, 2, 4, 8] + [15] * 15)

    def test_successful_timeout_resets_failure_streak(self):
        code, _, _, _ = self.execute([receipt({'cancelled': True})] * 19 +
            [receipt({'timedOut': True, 'messages': []}), receipt({'cancelled': True}), receipt(BATCH)])
        self.assertEqual(code, 0)
        self.assertEqual(self.sleeps[-1], 1)

    def test_waiter_exists_only_retries_once(self):
        error = subprocess.CompletedProcess([], 0, json.dumps({'ok': False, 'error': {'code': 'waiter_exists'}}), '')
        code, _, _, _ = self.execute([error, error])
        self.assertEqual(code, 4)
        self.assertEqual(self.sleeps, [1])
        self.assertEqual(len(self.calls), 2)

    def test_waiter_exists_can_recover(self):
        error = subprocess.CompletedProcess([], 0, json.dumps({'ok': False, 'error': 'waiter_exists'}), '')
        code, _, _, _ = self.execute([error, receipt(BATCH)])
        self.assertEqual(code, 0)
        self.assertEqual(self.sleeps, [1])

    def test_total_deadline_caps_wait_and_backoff(self):
        code, out, _, _ = self.execute([receipt({'connectionLost': True})] * 3, '--max-minutes', '0.05')
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertEqual(self.sleeps, [1, 2])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0][-2], '3000')
        self.assertEqual(self.calls[1][0][-2], '2000')

    def test_process_timeout_at_deadline_returns_two(self):
        def expire():
            self.now = 3
            raise subprocess.TimeoutExpired('fake-orca', 3)
        code, _, _, _ = self.execute([expire], '--max-minutes', '0.05')
        self.assertEqual(code, 2)
        self.assertEqual(len(self.calls), 1)

    def test_power_parser_covers_sources_and_malformed_output(self):
        for raw, expected in [
            (AC, ('AC Power', 100)), (BATTERY.replace('80%', '31%'), ('Battery Power', 31)),
            (BATTERY, ('Battery Power', 80)),
            ("Now drawing from 'UPS Power'\n -UPS 75%; discharging;", ('UPS Power', 75)),
            ("Now drawing from 'AC Power'\n", ('AC Power', None)),
            ('乱码\n unknown 80%', (None, None)),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(self.module.parse_power(raw), expected)

    def test_low_battery_blocks_before_orca(self):
        code, out, err, caffeine = self.execute([], power=BATTERY.replace('80%', '31%'))
        self.assertEqual(code, 3)
        self.assertEqual(out, '')
        self.assertEqual(self.calls, [])
        self.assertEqual(caffeine.call_count, 0)
        self.assertIn('合盖', err)

    def test_override_allows_low_battery_and_warns(self):
        code, _, err, caffeine = self.execute([receipt(BATCH)], '--allow-battery', power=BATTERY.replace('80%', '31%'))
        self.assertEqual(code, 0)
        self.assertIn('31', err)
        self.assertEqual(caffeine.call_args.args[0], ['fake-caffeinate', '-i', '-w', str(os.getpid())])

    def test_caffeinate_arguments_and_cleanup(self):
        for power, expected in [(AC, ['-i', '-s', '-w']), (BATTERY, ['-i', '-w'])]:
            with self.subTest(power=power):
                code, _, err, caffeine = self.execute([receipt(BATCH)], power=power)
                self.assertEqual(code, 0)
                self.assertEqual(caffeine.call_args.args[0], ['fake-caffeinate', *expected, str(os.getpid())])
                self.assertIn('合盖', err)
                self.assertTrue(self.process.terminate.called)

    def test_unknown_power_warns_and_does_not_block(self):
        for power in ('乱码', OSError('pmset unavailable')):
            with self.subTest(power=power):
                code, _, err, _ = self.execute([receipt(BATCH)], power=power)
                self.assertEqual(code, 0)
                self.assertIn('警告', err)
                self.assertIn('合盖', err)

    def test_real_cli_with_fake_executables_and_power_check_subcommand(self):
        def executable(name, body):
            path = self.root / name
            path.write_text('#!' + sys.executable + '\n' + body)
            path.chmod(0o755)
            return str(path)
        power = executable('pmset-fake', 'print(' + repr(AC) + ')\n')
        caffeine = executable('caffeine-fake', 'pass\n')
        orca = executable('orca-fake', 'import json, sys\nassert sys.argv[1:5] == ["orchestration", "check", "--run", "run-test"]\nprint(' + repr(json.dumps({'ok': True, 'result': BATCH})) + ')\n')
        result = subprocess.run([sys.executable, str(SCRIPT), '--run', 'run-test', '--orca', orca,
            '--pmset', power, '--caffeinate', caffeine], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), BATCH)
        result = subprocess.run([sys.executable, str(SCRIPT), 'power-check', '--pmset', power],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('合盖', result.stderr)

    def test_invalid_arguments_rejected_without_external_commands(self):
        for args in ([], ['--run', ' '], ['--run', 'R', '--timeout-ms', '0'],
                     ['--run', 'R', '--max-minutes', 'nan'], ['--run', 'R', '--min-battery', '101']):
            with self.subTest(args=args), patch.object(self.module.subprocess, 'run') as run, redirect_stderr(io.StringIO()):
                self.assertEqual(self.module.main(args), 2)
                self.assertFalse(run.called)


if __name__ == '__main__':
    unittest.main()
