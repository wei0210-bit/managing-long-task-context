from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context
from managing_long_task_context import project_store


def _git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout or " ".join(args))
    return completed


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "store-test@example.com")
    _git(path, "config", "user.name", "Store Test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("repo\n", encoding="utf-8")
    (path / ".gitignore").write_text(".prime/context/\n.prime/experience/\n", encoding="utf-8")
    _git(path, "add", "README.md", ".gitignore")
    _git(path, "commit", "-m", "init")
    return path


def _with_remote(path: Path) -> Path:
    remote = path.parent / f"{path.name}-origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(path, "remote", "add", "origin", str(remote))
    branch = _git(path, "branch", "--show-current").stdout.strip() or "HEAD"
    _git(path, "push", "-u", "origin", f"HEAD:{branch}")
    return path


def _contract(task_id: str = "TASK-001", workspace_root: str = ".") -> dict[str, object]:
    return {
        "schema": 1,
        "task_id": task_id,
        "version": 1,
        "issued_by": "publisher",
        "issued_at": "2026-09-24T00:00:00Z",
        "authorized_approvers": [],
        "workspace_root": workspace_root,
        "objective": "share project context",
        "scope": ["store"],
        "out_of_scope": [],
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "AC-01",
                "criterion": "context stays in the worktree",
                "required_evidence_types": ["test-report"],
            }
        ],
    }


def _publish_local_task(repo: Path, task_id: str = "TASK-001") -> Path:
    base = repo / ".prime" / "context"
    context.publish_contract(_contract(task_id), confirmed_by="publisher", base_dir=base)
    return base


class ProjectStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_non_git_directory_is_not_a_repository(self) -> None:
        missing = self.root / "plain"
        missing.mkdir()
        with self.assertRaises(project_store.StoreNotWritable) as raised:
            project_store.resolve_worktree_root(missing)
        self.assertEqual(raised.exception.code, "NOT_A_REPOSITORY")
        previous = Path.cwd()
        os.chdir(missing)
        try:
            with self.assertRaises(context.ContextError) as blocked:
                context.publish_contract(_contract(), confirmed_by="publisher")
            self.assertIn("NOT_A_REPOSITORY", str(blocked.exception))
        finally:
            os.chdir(previous)
        self.assertFalse((missing / ".prime" / "context").exists())

    def test_default_base_dir_uses_worktree_prime_context(self) -> None:
        repo = _init_repo(self.root / "work")
        previous = Path.cwd()
        os.chdir(repo)
        try:
            resolved, source = context._resolve_base_dir()
        finally:
            os.chdir(previous)
        self.assertEqual(source, "worktree-default")
        self.assertEqual(resolved, (repo / ".prime" / "context").resolve())

    def test_relative_contract_and_union_and_migrate(self) -> None:
        repo = _init_repo(self.root / "rel")
        base = _publish_local_task(repo)
        checked = project_store.check_store("TASK-001", repo)
        self.assertEqual(checked["status"], "ok", checked)
        self.assertEqual(json.loads((base / "TASK-001" / "task-contract.json").read_text())["workspace_root"], ".")

        merged = project_store.union_events(
            ['{"event_id":"a","body":1}'],
            ['{"event_id":"b","body":2}'],
        )
        self.assertEqual(merged["status"], "merged")
        self.assertEqual(len(merged["lines"]), 2)
        conflict = project_store.union_events(
            ['{"event_id":"a","body":1}'],
            ['{"event_id":"a","body":2}'],
        )
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict["event_id"], "a")

        contract_path = base / "TASK-001" / "task-contract.json"
        absolute = json.loads(contract_path.read_text())
        objective = absolute["objective"]
        os.chmod(contract_path, 0o644)
        absolute["workspace_root"] = str(repo.resolve())
        contract_path.write_text(json.dumps(absolute, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(contract_path, 0o444)
        updated = project_store.migrate_contract("TASK-001", repo)
        self.assertEqual(updated["workspace_root"], ".")
        self.assertGreater(updated["version"], 1)
        self.assertTrue(str(updated["seal"]["integrity_digest"]).startswith("sha256:"))
        self.assertEqual(updated["objective"], objective)

    def test_hook_blocks_ordinary_context_commit(self) -> None:
        repo = _with_remote(_init_repo(self.root / "hook"))
        _publish_local_task(repo)
        published = project_store.publish_context("TASK-001", repo)
        self.assertEqual(published["status"], "ok")
        events = repo / ".prime" / "context" / "TASK-001" / "events.jsonl"
        events.write_text(events.read_text(encoding="utf-8") + '{"event_id":"EV-ordinary"}\n', encoding="utf-8")
        _git(repo, "add", "-f", "--", ".prime/context/TASK-001/events.jsonl")
        blocked = _git(repo, "commit", "-m", "should fail", check=False)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("publish_context", blocked.stderr)

    def test_publish_commit_excludes_other_dirty_files(self) -> None:
        repo = _with_remote(_init_repo(self.root / "dirty"))
        _publish_local_task(repo)
        project_store.publish_context("TASK-001", repo)
        context.record(
            "TASK-001",
            statement="local note",
            item_type="observation",
            actor="executor",
            source={"kind": "note", "ref": "local"},
            base_dir=repo / ".prime" / "context",
        )
        (repo / "README.md").write_text("dirty working tree\n", encoding="utf-8")
        project_store.publish_context("TASK-001", repo)
        names = _git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout.splitlines()
        self.assertTrue(any(name.startswith(".prime/") for name in names), names)
        self.assertNotIn("README.md", names)
        self.assertIn("dirty working tree", (repo / "README.md").read_text(encoding="utf-8"))

    def test_secret_marker_blocks_publish(self) -> None:
        repo = _with_remote(_init_repo(self.root / "secret"))
        _publish_local_task(repo)
        experience = repo / ".prime" / "experience"
        experience.mkdir(parents=True)
        (experience / "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\n", encoding="utf-8")
        with self.assertRaises(project_store.StoreNotWritable) as raised:
            project_store.publish_context("TASK-001", repo)
        self.assertEqual(raised.exception.code, "SECRETS_FOUND")

    def test_align_stops_when_local_events_are_ahead(self) -> None:
        repo = _with_remote(_init_repo(self.root / "ahead"))
        _publish_local_task(repo)
        project_store.publish_context("TASK-001", repo)
        events = repo / ".prime" / "context" / "TASK-001" / "events.jsonl"
        events.write_text(events.read_text(encoding="utf-8") + '{"event_id":"EV-local-only"}\n', encoding="utf-8")
        with self.assertRaises(project_store.StoreNotWritable) as raised:
            project_store.align_context("TASK-001", repo)
        self.assertEqual(raised.exception.code, "LOCAL_AHEAD")

    def test_detached_head_is_read_only_and_merge_allows_conflict_file(self) -> None:
        repo = _init_repo(self.root / "head")
        _publish_local_task(repo)
        branch = _git(repo, "branch", "--show-current").stdout.strip()
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "--detach", sha)
        with self.assertRaises(project_store.StoreNotWritable) as raised:
            project_store.assert_writable(repo)
        self.assertEqual(raised.exception.code, "DETACHED_HEAD")
        _git(repo, "checkout", branch)
        (repo / ".git" / "MERGE_HEAD").write_text(sha + "\n", encoding="utf-8")
        with self.assertRaises(project_store.StoreNotWritable) as raised:
            project_store.assert_writable(repo)
        self.assertEqual(raised.exception.code, "MERGE_IN_PROGRESS")
        path = project_store.write_conflict("TASK-001", "EV-1", '{"event_id":"EV-1"}', '{"event_id":"EV-1","x":1}', repo)
        self.assertTrue(path.is_file())

    def test_relative_identity_matches_worktree(self) -> None:
        repo = _init_repo(self.root / "bind")
        workspace = repo.resolve()
        context_root = workspace / ".prime" / "context"
        self.assertTrue(project_store.stored_workspace_matches(".", workspace))
        self.assertTrue(project_store.stored_context_matches(".prime/context", context_root))
        self.assertFalse(project_store.stored_workspace_matches(".", self.root / "other"))
        self.assertEqual(project_store.default_experience_root(workspace), workspace / ".prime" / "experience")

    def test_lite_package_does_not_ship_project_store(self) -> None:
        lite = ROOT / "skills" / "context-lite"
        self.assertEqual([path.name for path in lite.rglob("project_store.py")], [])
        self.assertNotIn("project_store", (ROOT / "scripts" / "sync_context_tools.py").read_text(encoding="utf-8"))
        self.assertIn("project_store.py", (ROOT / "scripts" / "sync_context_strict_skill.py").read_text(encoding="utf-8"))

    def test_experience_default_is_prime_experience(self) -> None:
        from managing_long_task_context._experience_store import _store_path
        workspace = self.root / "exp"
        workspace.mkdir()
        self.assertEqual(_store_path(workspace, None), workspace / ".prime" / "experience")

    def test_merge_script_writes_conflict_and_rebuild_marker(self) -> None:
        repo = _init_repo(self.root / "merge")
        base = _publish_local_task(repo)
        project_store._install_project_git_files(repo)
        script = repo / ".prime" / "scripts" / "merge-events.py"
        ours = base / "TASK-001" / "events.jsonl"
        theirs = self.root / "theirs.jsonl"
        snapshot = base / "TASK-001" / "snapshot.json"
        ours.write_text('{"event_id":"EV-1","body":1}\n', encoding="utf-8")
        theirs.write_text('{"event_id":"EV-1","body":2}\n', encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(script), "unused", str(ours), str(theirs)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        conflict = base / "TASK-001" / "conflict-EV-1.json"
        self.assertTrue(conflict.is_file(), conflict)
        self.assertEqual(json.loads(snapshot.read_text()), {"rebuild": "required"})


if __name__ == "__main__":
    unittest.main()
