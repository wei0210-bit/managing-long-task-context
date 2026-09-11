"""Public-process tests for the S1 experience candidate CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "context_experience.py"


class ContextExperienceCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str, fail_atomic_replace: bool = False) -> tuple[int, dict[str, object]]:
        command = [sys.executable, str(SCRIPT), *arguments]
        if fail_atomic_replace:
            command = [
                sys.executable,
                "-c",
                "import runpy, sys; from unittest.mock import patch; module = runpy.run_path(sys.argv[1]); patch('os.replace', side_effect=OSError('injected filesystem failure')).start(); raise SystemExit(module['main'](sys.argv[2:]))",
                str(SCRIPT),
                *arguments,
            ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.stderr, "")
        return completed.returncode, json.loads(completed.stdout)

    def write_candidate(self, workspace: Path, *, revision: int = 1, claim: str = "Hash the local evidence before recording its candidate.") -> Path:
        source = workspace / "evidence.txt"
        source.write_text("known source evidence\n", encoding="utf-8")
        candidate = workspace / "candidate.json"
        candidate.write_text(json.dumps({
            "schema": 1,
            "experience_id": "safe-read-001",
            "revision": revision,
            "claim": claim,
            "tags": ["storage", "safety"],
            "applicability": ["A workspace-local original file is available."],
            "exclusions": ["none-known"],
            "source_refs": [{
                "path": str(source.resolve()),
                "sha256": "7c4cca45733426521b7b57bbaec344466dd0e32d873e88c2f9478ac5d66b64ce",
            }],
            "supersedes": None if revision == 1 else {"experience_id": "safe-read-001", "revision": revision - 1},
        }), encoding="utf-8")
        return candidate

    def test_init_binds_a_normalized_workspace_for_later_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"

            code, report = self.run_cli("init", "--workspace", str(workspace), "--store", str(store))

            self.assertEqual(code, 0, report)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["codes"], [])
            self.assertEqual(report["data"], {
                "workspace": str(workspace.resolve()),
                "store": str(store.resolve()),
            })

    def test_record_persists_a_candidate_with_a_verified_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)

            code, report = self.run_cli(
                "record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate),
            )

            self.assertEqual(code, 0, report)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["codes"], [])
            self.assertEqual(report["data"], {
                "experience_id": "safe-read-001",
                "revision": 1,
                "status": "candidate",
            })

    def test_get_reads_a_complete_record_in_a_later_cli_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)

            code, report = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual(code, 0, report)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["codes"], [])
            data = report["data"]
            self.assertEqual({key: data[key] for key in (
                "experience_id", "revision", "status", "claim", "applicability", "exclusions", "source_refs",
            )}, {
                "experience_id": "safe-read-001",
                "revision": 1,
                "status": "candidate",
                "claim": "Hash the local evidence before recording its candidate.",
                "applicability": ["A workspace-local original file is available."],
                "exclusions": ["none-known"],
                "source_refs": [{
                    "path": str((workspace / "evidence.txt").resolve()),
                    "sha256": "7c4cca45733426521b7b57bbaec344466dd0e32d873e88c2f9478ac5d66b64ce",
                }],
            })
            self.assertEqual(data["tags"], ["storage", "safety"])
            self.assertIsNone(data["supersedes"])
            self.assertRegex(data["created_at"], r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
            self.assertRegex(data["workspace_id"], r"\A[0-9a-f]{64}\Z")

    def test_query_requires_explicit_candidate_selection_and_tag_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)

            default_code, default_report = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage,safety")
            code, report = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage,unrelated", "--include-candidates")

            self.assertEqual(default_code, 0, default_report)
            self.assertEqual(default_report["data"], {"items": [], "omitted_count": 0})
            self.assertEqual(code, 0, report)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["codes"], [])
            self.assertEqual(report["data"], {
                "items": [{
                    "experience_id": "safe-read-001",
                    "revision": 1,
                    "status": "candidate",
                    "claim": "Hash the local evidence before recording its candidate.",
                    "applicability": ["A workspace-local original file is available."],
                    "exclusions": ["none-known"],
                    "source_refs": [{
                        "path": str((workspace / "evidence.txt").resolve()),
                        "sha256": "7c4cca45733426521b7b57bbaec344466dd0e32d873e88c2f9478ac5d66b64ce",
                    }],
                    "reliance": "not-reliable",
                }],
                "omitted_count": 0,
            })

    def test_get_rejects_a_corrupt_record_store_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            (store / "records.json").write_text('{"schema":1,"records":[{}]}', encoding="utf-8")

            code, report = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual(code, 1, report)
            self.assertEqual(report, {"status": "fail", "codes": ["STORE_CORRUPT"], "data": None})

    def test_store_rejects_an_unproven_status_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)
            records = json.loads((store / "records.json").read_text(encoding="utf-8"))
            records["records"][0]["status"] = "approved"
            (store / "records.json").write_text(json.dumps(records), encoding="utf-8")

            code, report = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual((code, report), (1, {"status": "fail", "codes": ["STORE_CORRUPT"], "data": None}))

    def test_concurrent_init_binds_only_one_workspace_to_a_shared_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            store = root / "store"
            commands = [
                [sys.executable, str(SCRIPT), "init", "--workspace", str(first), "--store", str(store)],
                [sys.executable, str(SCRIPT), "init", "--workspace", str(second), "--store", str(store)],
            ]
            processes = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
            results = [process.communicate() for process in processes]
            envelopes = [(process.returncode, json.loads(stdout)) for process, (stdout, stderr) in zip(processes, results)]

            self.assertTrue(all(stderr == "" for stdout, stderr in results))
            self.assertEqual(sorted(code for code, report in envelopes), [0, 1])
            self.assertEqual(sorted(report["status"] for code, report in envelopes), ["fail", "pass"])

    def test_missing_records_is_unknown_not_an_empty_initialized_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            empty_code, empty = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage")
            self.assertEqual((empty_code, empty), (0, {"status": "pass", "codes": [], "data": {"items": [], "omitted_count": 0}}))
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)
            (store / "records.json").unlink()

            query = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage")
            get = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")
            reinit = self.run_cli("init", "--workspace", str(workspace), "--store", str(store))

            expected = (2, {"status": "unknown", "codes": ["STORE_UNAVAILABLE"], "data": None})
            self.assertEqual(query, expected)
            self.assertEqual(get, expected)
            self.assertEqual(reinit, expected)

    def test_record_rejects_too_large_and_unreadable_original_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            source = workspace / "evidence.txt"
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            source.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            large = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))
            source.write_text("known source evidence\n", encoding="utf-8")
            os.chmod(source, 0)
            try:
                unreadable = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))
            finally:
                os.chmod(source, 0o600)

            self.assertEqual(large, (1, {"status": "fail", "codes": ["SOURCE_TOO_LARGE"], "data": None}))
            self.assertEqual(unreadable[0], 2, unreadable[1])
            self.assertEqual(unreadable[1]["status"], "unknown")

    def test_schema_rejects_boolean_and_query_orders_equal_revisions_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            raw["schema"] = True
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            invalid = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))
            raw["schema"] = 1
            raw["experience_id"] = "beta-001"
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)
            raw["experience_id"] = "alpha-001"
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)

            code, queried = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage", "--include-candidates", "--limit", "20", "--max-chars", "10000")

            self.assertEqual(invalid, (1, {"status": "fail", "codes": ["INVALID_INPUT"], "data": None}))
            self.assertEqual(code, 0, queried)
            self.assertEqual([item["experience_id"] for item in queried["data"]["items"]], ["alpha-001", "beta-001"])

    def test_record_requires_a_matching_initialized_workspace_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            store = root / "store"
            candidate = self.write_candidate(second)

            uninitialized_code, uninitialized = self.run_cli("record", "--workspace", str(second), "--store", str(store), "--input", str(candidate))
            self.assertEqual(self.run_cli("init", "--workspace", str(first), "--store", str(store))[0], 0)
            cross_code, cross = self.run_cli("record", "--workspace", str(second), "--store", str(store), "--input", str(candidate))

            self.assertEqual((uninitialized_code, uninitialized), (1, {"status": "fail", "codes": ["STORE_NOT_INITIALIZED"], "data": None}))
            self.assertEqual((cross_code, cross), (1, {"status": "fail", "codes": ["WORKSPACE_MISMATCH"], "data": None}))

    def test_record_rejects_outside_symlink_and_changed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)

            raw["source_refs"][0]["path"] = str((workspace.parent / "outside.txt").resolve())
            (workspace.parent / "outside.txt").write_text("outside\n", encoding="utf-8")
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            outside_code, outside = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            link = workspace / "linked.txt"
            link.symlink_to(workspace / "evidence.txt")
            raw["source_refs"][0]["path"] = str(link)
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            link_code, link_result = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            raw["source_refs"][0]["path"] = str((workspace / "evidence.txt").resolve())
            raw["source_refs"][0]["sha256"] = "0" * 64
            candidate.write_text(json.dumps(raw), encoding="utf-8")
            changed_code, changed = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            self.assertEqual((outside_code, outside["status"]), (1, "fail"))
            self.assertEqual((link_code, link_result["status"]), (1, "fail"))
            self.assertEqual((changed_code, changed), (1, {"status": "fail", "codes": ["SOURCE_DIGEST_MISMATCH"], "data": None}))

    def test_record_is_idempotent_rejects_conflict_and_requires_prior_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            first = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))
            replay = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            conflict = json.loads(candidate.read_text(encoding="utf-8"))
            conflict["claim"] = "A different same-version claim."
            candidate.write_text(json.dumps(conflict), encoding="utf-8")
            conflict_result = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            ahead = conflict | {"revision": 3, "supersedes": {"experience_id": "safe-read-001", "revision": 2}}
            candidate.write_text(json.dumps(ahead), encoding="utf-8")
            ahead_result = self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))

            self.assertEqual(first[0], 0, first[1])
            self.assertEqual(replay, first)
            self.assertEqual(conflict_result, (1, {"status": "fail", "codes": ["REVISION_CONFLICT"], "data": None}))
            self.assertEqual(ahead_result, (1, {"status": "fail", "codes": ["INVALID_INPUT"], "data": None}))

    def test_filesystem_write_failure_keeps_the_previous_revision_retrievable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)
            candidate = self.write_candidate(workspace, revision=2, claim="A later revision must not replace old data after disk failure.")

            failed_code, failed = self.run_cli(
                "record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate),
                fail_atomic_replace=True,
            )
            get_code, old = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual((failed_code, failed), (1, {"status": "fail", "codes": ["STORE_UNAVAILABLE"], "data": None}))
            self.assertEqual(get_code, 0, old)
            self.assertEqual(old["data"]["revision"], 1)

    def test_get_fails_when_a_recorded_source_has_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)
            (workspace / "evidence.txt").write_text("tampered after record\n", encoding="utf-8")

            code, report = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual((code, report), (1, {"status": "fail", "codes": ["SOURCE_DIGEST_MISMATCH"], "data": report["data"]}))
            self.assertEqual(report["data"]["status"], "candidate")
            self.assertEqual(report["data"]["validity"], {"status": "fail", "codes": ["SOURCE_DIGEST_MISMATCH"]})

    def test_query_returns_budget_failure_when_an_envelope_cannot_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            candidate = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(candidate))[0], 0)

            code, report = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage", "--include-candidates", "--max-chars", "1")

            self.assertEqual((code, report), (1, {"status": "fail", "codes": ["BUDGET_UNSATISFIABLE"], "data": None}))

    def test_query_prefers_current_revision_and_get_keeps_old_revision_traceable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            store = workspace / ".context-experience"
            first = self.write_candidate(workspace)
            self.assertEqual(self.run_cli("init", "--workspace", str(workspace), "--store", str(store))[0], 0)
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(first))[0], 0)
            second = self.write_candidate(workspace, revision=2, claim="The revised candidate is current.")
            self.assertEqual(self.run_cli("record", "--workspace", str(workspace), "--store", str(store), "--input", str(second))[0], 0)

            query_code, queried = self.run_cli("query", "--workspace", str(workspace), "--store", str(store), "--tags", "storage", "--include-candidates", "--limit", "20", "--max-chars", "10000")
            get_code, old = self.run_cli("get", "--workspace", str(workspace), "--store", str(store), "--id", "safe-read-001", "--revision", "1")

            self.assertEqual(query_code, 0, queried)
            self.assertEqual([item["revision"] for item in queried["data"]["items"]], [2])
            self.assertEqual(get_code, 2, old)
            self.assertEqual(old["status"], "unknown")
            self.assertEqual(old["codes"], ["RULE_VERSION_SUPERSEDED"])
            self.assertEqual(old["data"]["latest_revision"], 2)
            self.assertEqual(old["data"]["claim"], "Hash the local evidence before recording its candidate.")


if __name__ == "__main__":
    unittest.main()
