"""Coordinator lease contention and fail-closed CLI scenarios in isolated stores."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/coordinator_ops.py'
NOW = '2026-10-10T12:00:00Z'


def lease_fixture(**overrides):
    return dict({'schema': 'coordinator-lease/v1', 'session_id': 'owner',
                 'pid': 101, 'terminal_handle': 'terminal-owner', 'host': socket.gethostname(),
                 'acquired_at': NOW, 'heartbeat_at': NOW, 'ttl_seconds': 7200}, **overrides)


def store_snapshot(store):
    return {p.relative_to(store).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in store.rglob('*') if p.is_file()}


class LeaseTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name) / 'store'
        self.store.mkdir()
        self.path = self.store / 'COORDINATOR-LEASE.json'
        self.log = self.store / 'COORDINATOR-LEASE.log'
        self.env = {**os.environ, 'CLAUDE_CODE_SESSION_ID': 'owner', 'CLAUDE_PID': '101',
                    'ORCA_TERMINAL_HANDLE': 'terminal-owner', 'COORDINATOR_LEASE_NOW': NOW}
        self.env['PYTHONPATH'] = str(ROOT / 'src')

    def cli(self, action, *extra, expected=0, env=None):
        result = subprocess.run([sys.executable, str(SCRIPT), 'lease', action,
                                 '--store', str(self.store), *extra],
                                env={**self.env, **(env or {})}, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        if expected == 3:
            self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
        return result

    def read(self):
        return json.loads(self.path.read_bytes())

    def write(self, **overrides):
        self.path.write_text(json.dumps(lease_fixture(**overrides)))


class CoordinatorLeaseTests(LeaseTestCase):
    def test_status_is_read_only_including_absent_store(self):
        self.cli('status')
        self.assertEqual(store_snapshot(self.store), {})
        missing = self.store / 'absent'
        self.cli('status', '--store', str(missing))
        self.assertFalse(missing.exists())
        self.write()
        before = store_snapshot(self.store)
        self.cli('status')
        self.assertEqual(store_snapshot(self.store), before)

    def test_different_sessions_cannot_acquire_or_renew_or_release(self):
        self.cli('acquire')
        before = store_snapshot(self.store)
        for action in ('acquire', 'renew', 'release'):
            self.cli(action, expected=3, env={'CLAUDE_CODE_SESSION_ID': 'other'})
            self.assertEqual(store_snapshot(self.store), before)

    def test_same_session_two_terminals_contend(self):
        self.cli('acquire')
        before = store_snapshot(self.store)
        result = self.cli('acquire', expected=3, env={'ORCA_TERMINAL_HANDLE': 'second-window'})
        self.assertIn('owner', result.stderr)
        self.assertIn('terminal-owner', result.stderr)
        self.assertIn('2026-10-10T14:00:00Z', result.stderr)
        self.assertEqual(store_snapshot(self.store), before)

    def test_same_session_same_terminal_new_pid_renews(self):
        self.cli('acquire')
        self.cli('renew', env={'CLAUDE_PID': '202', 'COORDINATOR_LEASE_NOW': '2026-10-10T12:30:00Z'})
        value = self.read()
        self.assertEqual(value['pid'], 202)
        self.assertEqual(value['heartbeat_at'], '2026-10-10T12:30:00Z')
        self.assertEqual(value['acquired_at'], NOW)
        self.assertEqual(value['ttl_seconds'], 7200)

    def test_missing_terminal_uses_pid_and_host_is_part_of_owner(self):
        self.cli('acquire', env={'ORCA_TERMINAL_HANDLE': ''})
        self.cli('renew', env={'ORCA_TERMINAL_HANDLE': ''})
        self.cli('renew', expected=3, env={'ORCA_TERMINAL_HANDLE': '', 'CLAUDE_PID': '202'})
        self.write(host='different-host')
        self.cli('renew', expected=3)

    def test_codex_and_unknown_session_and_parent_pid_fallback(self):
        env = {**self.env, 'CODEX_SESSION_ID': 'codex-owner'}
        for name in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_PID'):
            env.pop(name, None)
        result = subprocess.run([sys.executable, str(SCRIPT), 'lease', 'acquire', '--store', str(self.store)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read()['session_id'], 'codex-owner')
        self.assertEqual(self.read()['pid'], os.getpid())
        self.cli('release', env={'CLAUDE_CODE_SESSION_ID': 'codex-owner'})
        env.pop('CODEX_SESSION_ID', None)
        result = subprocess.run([sys.executable, str(SCRIPT), 'lease', 'acquire', '--store', str(self.store)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read()['session_id'], 'unknown')

    def test_expiry_is_strictly_greater_than_ttl(self):
        self.cli('acquire')
        other = {'CLAUDE_CODE_SESSION_ID': 'other', 'COORDINATOR_LEASE_NOW': '2026-10-10T14:00:00Z'}
        before = store_snapshot(self.store)
        self.cli('takeover', '--reason', 'expired recovery', expected=3, env=other)
        self.assertEqual(store_snapshot(self.store), before)
        other['COORDINATOR_LEASE_NOW'] = '2026-10-10T14:00:01Z'
        self.cli('takeover', '--reason', 'expired recovery', env=other)
        row = json.loads(self.log.read_text())
        self.assertTrue(row['expired'])
        self.assertEqual(row['old_holder']['session_id'], 'owner')
        self.assertEqual(row['new_holder']['session_id'], 'other')
        self.assertEqual(row['reason'], 'expired recovery')
        self.assertEqual(self.read()['session_id'], 'other')

    def test_takeover_on_david_instruction_records_exact_words_and_appends(self):
        self.cli('acquire')
        words = 'David: 请让第二个窗口接手。'
        self.cli('takeover', '--reason', 'explicit instruction', '--david-instruction', words,
                 env={'CLAUDE_CODE_SESSION_ID': 'other'})
        first = self.log.read_bytes()
        row = json.loads(first)
        self.assertFalse(row['expired'])
        self.assertEqual(row['david_instruction'], words)
        self.cli('takeover', '--reason', 'return', '--david-instruction', 'David: 交回原窗口')
        self.assertTrue(self.log.read_bytes().startswith(first))
        self.assertEqual(len(self.log.read_text().splitlines()), 2)

    def test_blank_takeover_reason_or_instruction_never_changes_store(self):
        self.cli('acquire')
        before = store_snapshot(self.store)
        self.cli('takeover', '--reason', ' ', '--david-instruction', 'David says yes', expected=2)
        self.cli('takeover', '--reason', 'reason', '--david-instruction', ' ', expected=2)
        self.assertEqual(store_snapshot(self.store), before)

    def test_release_preserves_file_and_allows_other_holder_to_acquire(self):
        self.cli('acquire')
        self.cli('release')
        self.assertEqual(self.read()['released_at'], NOW)
        self.cli('acquire', env={'CLAUDE_CODE_SESSION_ID': 'other'})
        self.assertEqual(self.read()['session_id'], 'other')
        self.assertNotIn('released_at', self.read())

    def test_exclusive_lock_denies_mutation_and_is_not_removed(self):
        lock = self.store / 'COORDINATOR-LEASE.lock'
        lock.write_bytes(b'other mutation')
        before = store_snapshot(self.store)
        self.cli('acquire', expected=3)
        self.assertEqual(store_snapshot(self.store), before)

    def test_concurrent_acquirers_have_one_winner(self):
        processes = [subprocess.Popen([sys.executable, str(SCRIPT), 'lease', 'acquire', '--store', str(self.store)],
                     env={**self.env, 'CLAUDE_CODE_SESSION_ID': name}, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True) for name in ('one', 'two')]
        for process in processes:
            process.communicate(timeout=20)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 3])
        self.assertIn(self.read()['session_id'], ('one', 'two'))
        self.assertFalse((self.store / 'COORDINATOR-LEASE.lock').exists())
        self.assertEqual(set(store_snapshot(self.store)), {'COORDINATOR-LEASE.json'})


class LeaseRobustnessTests(LeaseTestCase):
    def test_expired_foreign_lease_requires_explicit_recorded_takeover(self):
        self.write(session_id='other')
        before = store_snapshot(self.store)
        result = self.cli('acquire', expected=3, env={'COORDINATOR_LEASE_NOW': '2026-10-10T15:00:00Z'})
        self.assertIn('takeover', result.stderr)
        self.assertEqual(store_snapshot(self.store), before)

    def test_invalid_injected_clock_does_not_fall_back_to_real_time(self):
        self.cli('acquire', expected=3, env={'COORDINATOR_LEASE_NOW': 'invalid'})
        self.assertEqual(store_snapshot(self.store), {})
    def test_invalid_files_fail_closed_for_all_lease_actions(self):
        malformed = [b'{bad json', b'[]', b'null', b'{}',
                     b'[' * 2000 + b'0' + b']' * 2000]
        for constant in (float('nan'), float('inf'), -float('inf')):
            malformed.append(json.dumps({**lease_fixture(), 'extra': constant}).encode())
        for key in lease_fixture():
            value = lease_fixture()
            value.pop(key)
            malformed.append(json.dumps(value).encode())
        for key, values in {
            'schema': ['wrong', None], 'session_id': [0, None, ''],
            'pid': ['1', True, 0], 'terminal_handle': [1, False], 'host': [None, 1, ''],
            'acquired_at': [0, 'yesterday', '2026-10-10T12:00:00+00:00'],
            'heartbeat_at': [None, '2026-10-10T25:00:00Z'],
            'ttl_seconds': [0, -1, True, '7200', 7200.0], 'released_at': [None, 'bad'],
        }.items():
            malformed.extend(json.dumps(lease_fixture(**{key: value})).encode() for value in values)
        for raw in malformed:
            with self.subTest(raw=raw[:150]):
                self.path.write_bytes(raw)
                before = store_snapshot(self.store)
                for action in ('status', 'acquire', 'renew', 'release', 'takeover'):
                    extra = ('--reason', 'recovery') if action == 'takeover' else ()
                    result = self.cli(action, *extra, expected=3)
                    self.assertIn('coordinator lease', result.stderr)
                    self.assertEqual(store_snapshot(self.store), before)

    def test_authorized_invalid_replacement_retains_old_sha256(self):
        raw = b'{broken coordinator lease'
        self.path.write_bytes(raw)
        self.cli('takeover', '--reason', 'repair corrupt lease', '--david-instruction', 'David: 修复租约')
        row = json.loads(self.log.read_text())
        self.assertEqual(row['old_file_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(row['david_instruction'], 'David: 修复租约')
        self.assertIsNone(row['expired'])  # Corrupt old state cannot prove an expiration time.
        self.assertEqual(self.read()['session_id'], 'owner')

    def test_unreadable_file_is_not_overwritten(self):
        self.write()
        self.path.chmod(0)
        try:
            result = self.cli('acquire', expected=3)
            self.assertIn('unreadable', result.stderr)
        finally:
            self.path.chmod(0o600)
        self.assertEqual(self.read(), lease_fixture())


def lock_fixture(**overrides):
    return dict({'schema': 'coordinator-lease-lock/v1', 'session_id': 'lock-owner',
                 'pid': 101, 'terminal_handle': 'lock-terminal', 'host': socket.gethostname(),
                 'created_at': NOW}, **overrides)


class StaleLockRecoveryTests(LeaseTestCase):
    def lock_path(self):
        return self.store / 'COORDINATOR-LEASE.lock'

    def write_lock(self, **overrides):
        self.lock_path().write_text(json.dumps(lock_fixture(**overrides)) + '\n')

    def clear(self, expected=0):
        return self.cli('clear-lock', '--reason', 'stopped holder',
                        '--david-instruction', 'David: 清除此测试锁', expected=expected)

    def operations(self):
        import runpy
        return runpy.run_path(str(SCRIPT))

    def test_lock_records_holder_and_fsyncs_before_yield(self):
        from unittest import mock
        ops = self.operations()
        with mock.patch.dict(os.environ, self.env), mock.patch('os.fsync', wraps=os.fsync) as fsync:
            with ops['coordinator_lease_lock'](self.store):
                raw = self.lock_path().read_text()
                self.assertEqual(len(raw.splitlines()), 1)
                record = json.loads(raw)
                self.assertEqual(record, lock_fixture(session_id='owner', terminal_handle='terminal-owner'))
                self.assertTrue(fsync.called)
        self.assertFalse(self.lock_path().exists())

    def test_conflict_names_absolute_path_holder_and_recovery(self):
        self.write_lock()
        before = store_snapshot(self.store)
        result = self.cli('acquire', expected=3)
        for value in (str(self.lock_path().resolve()), 'lock-owner', 'lock-terminal', NOW,
                      '核实持有进程已停止后，经 David 指示用 lease clear-lock'):
            self.assertIn(value, result.stderr)
        self.assertEqual(store_snapshot(self.store), before)

    def test_unreadable_lock_conflict_is_not_removed(self):
        self.lock_path().write_bytes(b'{broken')
        before = store_snapshot(self.store)
        result = self.cli('acquire', expected=3)
        self.assertIn('unreadable lock', result.stderr)
        self.assertEqual(store_snapshot(self.store), before)

    def test_clear_requires_both_nonempty_parameters(self):
        self.write_lock()
        before = store_snapshot(self.store)
        for extra in [(), ('--reason', 'why'), ('--david-instruction', 'David: yes'),
                      ('--reason', ' ', '--david-instruction', 'David: yes'),
                      ('--reason', 'why', '--david-instruction', ' ')]:
            self.cli('clear-lock', *extra, expected=2)
            self.assertEqual(store_snapshot(self.store), before)

    def test_absent_lock_is_exit_three_and_writes_nothing(self):
        self.clear(expected=3)
        self.assertEqual(store_snapshot(self.store), {})

    def test_live_local_pid_is_refused_and_lock_unchanged(self):
        self.write_lock(pid=os.getpid())
        before = store_snapshot(self.store)
        self.clear(expected=3)
        self.assertEqual(store_snapshot(self.store), before)

    def test_permission_error_means_live_holder(self):
        from unittest import mock
        self.write_lock(pid=os.getpid())
        ops = self.operations()
        before = store_snapshot(self.store)
        with mock.patch('os.kill', side_effect=PermissionError):
            with self.assertRaises(ops['CoordinatorLeaseError']):
                ops['clear_coordinator_lease_lock'](self.store, 'why', 'David: yes')
        self.assertEqual(store_snapshot(self.store), before)

    def test_stopped_holder_is_audited_before_unlink_and_lease_unchanged(self):
        from unittest import mock
        child = subprocess.Popen([sys.executable, '-c', 'pass'])
        child.wait()
        self.write_lock(pid=child.pid)
        self.write()
        lease_before = (self.path.read_bytes(), self.path.stat().st_mtime_ns)
        raw = self.lock_path().read_bytes()
        self.log.write_text('{"earlier":true}\n')
        unlink = Path.unlink
        ops = self.operations()
        with mock.patch.dict(os.environ, self.env), mock.patch('os.fsync', wraps=os.fsync) as fsync:
            def observed_unlink(path, *args, **kwargs):
                if path.resolve() == self.lock_path().resolve():
                    self.assertTrue(fsync.called)
                    self.assertEqual(len(self.log.read_text().splitlines()), 2)
                return unlink(path, *args, **kwargs)
            with mock.patch.object(Path, 'unlink', observed_unlink):
                ops['clear_coordinator_lease_lock'](self.store, 'stopped holder', 'David: 清除此测试锁')
        self.assertFalse(self.lock_path().exists())
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), lease_before)
        row = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual(row['event'], 'clear-lock')
        self.assertEqual(row['lock_path'], str(self.lock_path().resolve()))
        self.assertEqual(row['lock_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(row['lock_content'], json.loads(raw))
        self.assertIs(row['holder_alive'], False)
        self.assertEqual(row['reason'], 'stopped holder')
        self.assertEqual(row['david_instruction'], 'David: 清除此测试锁')
        self.assertEqual(row['cleared_by']['session_id'], 'owner')
        self.assertEqual(row['cleared_at'], NOW)

    def test_failed_audit_write_or_fsync_preserves_lock(self):
        from unittest import mock
        ops = self.operations()
        self.write_lock(host='other-host')
        raw = self.lock_path().read_bytes()
        self.log.mkdir()
        self.clear(expected=3)
        self.assertEqual(self.lock_path().read_bytes(), raw)
        self.log.rmdir()
        with mock.patch('os.fsync', side_effect=OSError('audit fsync failed')):
            with self.assertRaises(ops['CoordinatorLeaseError']):
                ops['clear_coordinator_lease_lock'](self.store, 'why', 'David: yes')
        self.assertEqual(self.lock_path().read_bytes(), raw)

    def test_cross_host_and_invalid_records_are_unknown_and_do_not_change_lease(self):
        self.write()
        lease_before = self.path.read_bytes()
        for record in [lock_fixture(host='other-host'), None, [],
                       lock_fixture(pid=True), lock_fixture(pid=2 ** 64), lock_fixture(created_at='bad')]:
            with self.subTest(record=record):
                self.lock_path().write_text(json.dumps(record))
                self.clear()
                row = json.loads(self.log.read_text().splitlines()[-1])
                self.assertEqual(row['holder_alive'], 'unknown')
                self.assertEqual(row['lock_content'], record if isinstance(record, dict)
                                 and record.get('host') == 'other-host' else None)
                self.assertEqual(self.path.read_bytes(), lease_before)
        self.lock_path().write_bytes(b'{invalid json')
        self.clear()
        row = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual(row['holder_alive'], 'unknown')
        self.assertIsNone(row['lock_content'])


if __name__ == '__main__':
    unittest.main()
