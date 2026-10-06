from __future__ import annotations

import hashlib
import json
import stat
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

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
        self.publish('1/../../../escape')
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

    def test_missing_from_version_is_reported(self):
        self.publish(2)
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 1})

    def test_missing_to_version_is_reported(self):
        self.publish()
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 2})

    def test_missing_task_is_reported_without_creating_store(self):
        self.assertEqual(self.diff(), {'status': 'missing', 'version': 1})
        self.assertFalse(self.base.exists())

    def test_diff_can_compare_two_archived_versions(self):
        self.publish()
        self.publish(2)
        self.publish(3)
        self.assertEqual(self.diff()['changes']['version'], {'from': 1, 'to': 2})

    def test_non_integer_history_versions_do_not_match(self):
        self.publish('1/../../../escape')
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
