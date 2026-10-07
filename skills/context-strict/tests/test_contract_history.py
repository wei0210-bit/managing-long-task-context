from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context
from test_project_store import _contract, _init_repo


class ContractHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name) / 'context'
        self.contract = _contract()
        self.path = self.base / 'TASK-001' / 'task-contract.json'
        self.history = self.path.parent / 'contract-history'

    def publish(self, version=1, **updates):
        value = deepcopy(self.contract)
        value.update(version=version, **updates)
        return context.publish_contract(value, confirmed_by='publisher', base_dir=self.base)

    def archived_path(self, data):
        return self.history / (hashlib.sha256(data).hexdigest() + '.json')

    def diff(self, start=1, end=2):
        return context.contract_diff('TASK-001', start, end, base_dir=self.base)

    def test_publish_retains_exact_bytes_and_read_only_mode(self):
        self.publish()
        self.assertFalse(self.history.exists())
        # Preserve original formatting too, rather than reserializing the JSON.
        data = json.dumps(json.loads(self.path.read_bytes()), ensure_ascii=False).encode() + b'\n\n'
        self.path.chmod(0o644)
        self.path.write_bytes(data)
        self.path.chmod(0o444)
        self.publish(2)
        archived = self.archived_path(data)
        self.assertEqual(archived.read_bytes(), data)
        self.assertEqual(stat.S_IMODE(archived.stat().st_mode), 0o444)
        self.assertEqual(json.loads(self.path.read_bytes())['version'], 2)

    def test_malicious_version_never_enters_history_filename(self):
        # Construct a sealed legacy contract without using the publication API.
        legacy = deepcopy(self.contract)
        legacy['version'] = '1/../../../escape'
        legacy['seal'] = {'confirmed_by': 'publisher', 'confirmed_at': context._now()}
        legacy['seal']['integrity_digest'] = context._contract_digest(legacy)
        context._atomic_write_json(self.path, legacy, mode=0o444)
        data = self.path.read_bytes()
        self.publish(2)
        self.assertEqual(list(self.history.iterdir()), [self.archived_path(data)])
        self.assertEqual(self.archived_path(data).resolve().parent, self.history.resolve())

    def test_archive_failure_keeps_current_contract_unchanged(self):
        self.publish()
        data = self.path.read_bytes()
        self.history.write_bytes(b'not a directory')
        with self.assertRaises(context.ContextError):
            self.publish(2)
        self.assertEqual(self.path.read_bytes(), data)

    def test_unwritable_history_keeps_current_contract_unchanged(self):
        self.publish()
        data = self.path.read_bytes()
        self.history.mkdir()
        self.history.chmod(0o555)
        self.addCleanup(self.history.chmod, 0o755)
        with self.assertRaises(context.ContextError):
            self.publish(2)
        self.assertEqual(self.path.read_bytes(), data)

    def test_existing_identical_archive_is_skipped(self):
        self.publish()
        data = self.path.read_bytes()
        self.history.mkdir()
        archived = self.archived_path(data)
        archived.write_bytes(data)
        archived.chmod(0o444)
        before = archived.stat()
        self.publish(2)
        self.assertEqual(archived.read_bytes(), data)
        self.assertEqual((archived.stat().st_ino, archived.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))

    def test_existing_different_archive_blocks_publish(self):
        self.publish()
        data = self.path.read_bytes()
        self.history.mkdir()
        archived = self.archived_path(data)
        archived.write_bytes(b'collision or corruption')
        with self.assertRaises(context.ContextError):
            self.publish(2)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(archived.read_bytes(), b'collision or corruption')

    def test_rejected_version_does_not_archive(self):
        self.publish()
        with self.assertRaises(context.ContextError):
            self.publish(1)
        self.assertFalse(self.history.exists())
        self.assertTrue(callable(getattr(context, 'contract_diff', None)))

    def test_diff_reports_top_level_changes_additions_and_removals(self):
        first = self.publish(extra={'nested': 1}, removed='gone')
        second = self.publish(2, objective='changed', extra={'nested': 2}, added='new')
        result = self.diff()
        self.assertEqual(result['status'], 'ok')
        changes = result['changes']
        self.assertEqual(changes['objective'], {'from': first['objective'], 'to': 'changed'})
        self.assertEqual(changes['extra'], {'from': {'nested': 1}, 'to': {'nested': 2}})
        self.assertEqual(changes['added'], {'to': 'new'})
        self.assertEqual(changes['removed'], {'from': 'gone'})
        self.assertEqual(changes['version'], {'from': 1, 'to': 2})
        self.assertEqual(changes['seal'], {'from': first['seal'], 'to': second['seal']})
        self.assertNotIn('scope', changes)

    def test_diff_same_current_version_is_empty_and_read_only(self):
        self.publish()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.path.parent.iterdir()}
        self.assertEqual(self.diff(1, 1)['changes'], {})
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.path.parent.iterdir()}, before)

    def assert_policy_change(self, before, after):
        self.publish(audit_policy=before)
        self.publish(2, audit_policy=after)
        changes = self.diff()['changes']
        self.assertIn('audit_policy', changes)
        self.assertEqual(changes['audit_policy'], {'from': before, 'to': after})

    def test_diff_distinguishes_true_from_one(self):
        self.assert_policy_change(True, 1)

    def test_diff_distinguishes_false_from_zero(self):
        self.assert_policy_change(False, 0)

    def test_diff_distinguishes_boolean_from_number_in_object(self):
        self.assert_policy_change({'required': True}, {'required': 1})

    def test_diff_distinguishes_boolean_from_number_in_array(self):
        self.assert_policy_change([True], [1])

    def test_diff_distinguishes_null_from_missing_in_both_directions(self):
        self.publish(audit_policy=None)
        self.publish(2)
        self.assertEqual(self.diff()['changes']['audit_policy'], {'from': None})
        self.assertEqual(self.diff(2, 1)['changes']['audit_policy'], {'to': None})

    def test_fdopen_failure_closes_descriptor_and_preserves_contract(self):
        self.publish()
        data = self.path.read_bytes()
        descriptors = []
        mkstemp = tempfile.mkstemp

        def track_descriptor(*args, **kwargs):
            descriptor, name = mkstemp(*args, **kwargs)
            descriptors.append(descriptor)
            return descriptor, name

        def close_if_open():
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if exc.errno != errno.EBADF:
                        raise

        self.addCleanup(close_if_open)
        with patch('managing_long_task_context.contract_history.tempfile.mkstemp',
                   side_effect=track_descriptor), patch(
                       'managing_long_task_context.contract_history.os.fdopen',
                       side_effect=OSError('injected fdopen failure')):
            with self.assertRaises(context.ContextError):
                self.publish(2)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(list(self.history.iterdir()), [])
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError) as raised:
            os.fstat(descriptors[0])
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_missing_from_version_is_reported(self):
        self.publish(2)
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 1})

    def test_missing_to_version_is_reported(self):
        self.publish()
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 2})

    def test_missing_task_is_reported_without_creating_store(self):
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 1})
        self.assertFalse(self.base.exists())

    def assert_unreadable_history_raises(self, mode):
        self.publish()
        original = self.path.read_bytes()
        self.publish(2)
        current = self.path.read_bytes()
        self.history.chmod(mode)
        self.addCleanup(self.history.chmod, 0o755)
        # Establish the real filesystem failure independently of contract_diff.
        with self.assertRaises(PermissionError):
            list(self.history.iterdir())
        with self.assertRaises(context.ContextError):
            self.diff()
        self.history.chmod(0o755)
        self.assertEqual(self.archived_path(original).read_bytes(), original)
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(self.diff()['status'], 'ok')
        self.assertEqual(self.diff(99, 2), {'status': 'missing', 'version': 99})

    def test_diff_execute_only_history_directory_raises(self):
        self.assert_unreadable_history_raises(0o111)

    def test_diff_no_permission_history_directory_raises(self):
        self.assert_unreadable_history_raises(0o000)

    def test_diff_history_file_instead_of_directory_raises(self):
        self.publish()
        self.history.write_bytes(b'not a directory')
        with self.assertRaises(context.ContextError):
            self.diff()

    def test_diff_non_directory_task_root_raises(self):
        self.base.mkdir()
        self.path.parent.write_bytes(b'not a directory')
        with self.assertRaises(context.ContextError):
            self.diff()

    def test_diff_unsearchable_task_root_raises_context_error(self):
        self.publish()
        self.publish(2)
        self.path.parent.chmod(0o000)
        self.addCleanup(self.path.parent.chmod, 0o755)
        with self.assertRaises(context.ContextError):
            self.diff()

    def test_diff_unreadable_current_contract_raises(self):
        self.publish()
        self.path.chmod(0o000)
        self.addCleanup(self.path.chmod, 0o444)
        with self.assertRaises(context.ContextError):
            self.diff(1, 1)

    def test_diff_unreadable_archived_contract_raises(self):
        self.publish()
        archived = self.archived_path(self.path.read_bytes())
        self.publish(2)
        archived.chmod(0o000)
        self.addCleanup(archived.chmod, 0o444)
        with self.assertRaises(context.ContextError):
            self.diff()

    def test_retain_non_directory_contract_parent_raises(self):
        from managing_long_task_context.contract_history import retain_contract

        self.base.mkdir()
        self.path.parent.write_bytes(b'not a directory')
        with self.assertRaises(context.ContextError):
            retain_contract(self.path)

    def test_retain_truly_missing_contract_does_not_create_history(self):
        from managing_long_task_context.contract_history import retain_contract

        self.assertIsNone(retain_contract(self.path))
        self.assertFalse(self.base.exists())

    def test_diff_can_compare_two_archived_versions(self):
        self.publish()
        self.publish(2)
        self.publish(3)
        self.assertEqual(self.diff()['changes']['version'], {'from': 1, 'to': 2})

    def test_non_integer_history_versions_do_not_match(self):
        # Construct a sealed legacy contract without using the publication API.
        legacy = deepcopy(self.contract)
        legacy['version'] = '1/../../../escape'
        legacy['seal'] = {'confirmed_by': 'publisher', 'confirmed_at': context._now()}
        legacy['seal']['integrity_digest'] = context._contract_digest(legacy)
        context._atomic_write_json(self.path, legacy, mode=0o444)
        self.publish(2)
        self.assertEqual(self.diff('1/../../../escape', 2), {'status': 'missing', 'version': '1/../../../escape'})

    def test_negative_and_boolean_history_versions_do_not_match(self):
        self.publish(2)
        self.history.mkdir()
        for version in (-1, True, '1', 1.0):
            data = json.dumps({'version': version}).encode()
            self.archived_path(data).write_bytes(data)
        self.assertEqual(self.diff(1, 2), {'status': 'missing', 'version': 1})
        self.assertEqual(self.diff(-1, 2), {'status': 'missing', 'version': -1})

    def test_corrupt_archive_is_detected_on_read(self):
        self.publish()
        data = self.path.read_bytes()
        self.publish(2)
        archived = self.archived_path(data)
        archived.chmod(0o644)
        archived.write_bytes(b'{"version":1}')
        with self.assertRaises(context.ContextError):
            self.diff()

    def test_history_digest_is_checked_after_git_style_mode_loss(self):
        self.publish()
        data = self.path.read_bytes()
        self.publish(2)
        self.archived_path(data).chmod(0o644)
        self.assertEqual(self.diff()['changes']['version'], {'from': 1, 'to': 2})

    def test_migrate_retains_exact_bytes(self):
        repo = _init_repo(self.base.parent / 'repo')
        self.base = repo / '.prime' / 'context'
        self.path = self.base / 'TASK-001' / 'task-contract.json'
        self.history = self.path.parent / 'contract-history'
        self.publish(workspace_root=str(repo))
        data = self.path.read_bytes()
        updated = context.migrate_contract('TASK-001', repo)
        archived = self.archived_path(data)
        self.assertEqual(archived.read_bytes(), data)
        self.assertEqual(stat.S_IMODE(archived.stat().st_mode), 0o444)
        self.assertEqual(updated['workspace_root'], '.')
        self.assertEqual(updated['version'], 2)
        self.assertEqual(self.diff()['changes']['workspace_root'], {'from': str(repo), 'to': '.'})

    def test_migrate_archive_failure_keeps_bytes_and_mode(self):
        repo = _init_repo(self.base.parent / 'repo')
        self.base = repo / '.prime' / 'context'
        self.path = self.base / 'TASK-001' / 'task-contract.json'
        self.history = self.path.parent / 'contract-history'
        self.publish(workspace_root=str(repo))
        data = self.path.read_bytes()
        mode = self.path.stat().st_mode
        self.history.write_bytes(b'not a directory')
        with self.assertRaises(context.ContextError):
            context.migrate_contract('TASK-001', repo)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(self.path.stat().st_mode, mode)


if __name__ == '__main__':
    unittest.main()
