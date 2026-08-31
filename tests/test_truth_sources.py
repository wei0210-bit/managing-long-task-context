from __future__ import annotations

import asyncio
import hashlib
import json
import errno
import multiprocessing
import os
import builtins
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context
import managing_long_task_context.truth_sources as truth_sources
from managing_long_task_context.truth_sources import (
    MAX_SOURCE_BYTES,
    resolve_file_source,
    validate_truth_source_contract,
)


LEGACY_HASHES = {
    "brief": "sha256:1017b34d7e09589d35c1d6535e7feaeba4d6d9b74706f535084ff355fb75bfd4",
    "contract_file": "sha256:c0fbeee12dcf8486d743c46465d38e91fd952b9ae93381c691282b39190d7892",
    "diagnostics": "sha256:ca9e69d280821cd39d127bfce0837e6909b57f5212f96fc52c86a93b1c2c188f",
    "events_file": "sha256:7d33c3fc8a0abd6cc7942420c3cf86cdf497bd5be1d0f7ae47a231c72f3e65d9",
    "gate_completion": "sha256:caa88b955439ca7e0a90bafdc2be4b6466bab8b795d7bd60cffaff2c9b3d111b",
    "gate_handoff": "sha256:a451310f64c7464896b06a5905e905c6080f300948c58830bd978968b7a5d242",
    "gate_release": "sha256:3d2ef964067cff8e4c50387108cc70e93d8f68caa036ddb9f6520abd409af895",
    "gate_resume": "sha256:533bb8cfcfc8e956141f84148f28e153cfeddfd99422bb6b83b5123e3a330282",
    "seal": "sha256:a80fcf6e033fbdcea3f96f8d12719b92405a9ec3cf203f70636bfef307ba0ab0",
    "snapshot_file": "sha256:1af1f6ee2f763cdb86901a9665b17be14f331669ffeac8db21d905753f3d72b9",
}

LEGACY_CONTRACT = {
    "schema": 1,
    "task_id": "LEGACY-GOLDEN",
    "version": 1,
    "issued_by": "publisher",
    "issued_at": "2026-08-31T02:00:00+00:00",
    "authorized_approvers": [],
    "objective": "Preserve legacy behavior",
    "scope": ["strict context"],
    "out_of_scope": [],
    "constraints": ["no truth sources"],
    "acceptance_criteria": [{
        "id": "AC-01",
        "criterion": "Legacy behavior stays exact",
        "required_evidence_types": ["test-report"],
    }],
}


def _hash_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _exclusive_lock_probe(lock_path: str, result_queue: object) -> None:
    """Independent process proof: only a nonblocking-lock failure is blocked."""
    import fcntl as child_fcntl

    try:
        with Path(lock_path).open("r", encoding="utf-8") as handle:
            try:
                child_fcntl.flock(handle.fileno(), child_fcntl.LOCK_EX | child_fcntl.LOCK_NB)
            except BlockingIOError:
                result_queue.put("blocked")
                return
            except OSError as exc:
                result_queue.put("blocked" if exc.errno in {errno.EACCES, errno.EAGAIN} else f"errno:{exc.errno}")
                return
            child_fcntl.flock(handle.fileno(), child_fcntl.LOCK_UN)
            result_queue.put("acquired")
    except Exception as exc:
        result_queue.put(f"error:{type(exc).__name__}")


class LegacyTruthSourceCompatibilityTests(unittest.TestCase):
    maxDiff = None

    def test_legacy_public_reports_and_ledgers_remain_exact(self) -> None:
        now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary_dir, \
             patch.object(context, "_now", return_value=now.isoformat()), \
             patch.object(context, "_trusted_utc_now", return_value=now), \
             patch.object(
                 context.uuid,
                 "uuid4",
                 return_value=uuid.UUID("01234567-89ab-cdef-0123-456789abcdef"),
             ):
            base = Path(temporary_dir) / ".prime" / "context"
            published = context.publish_contract(LEGACY_CONTRACT, confirmed_by="publisher", base_dir=base)
            task_dir = base / "LEGACY-GOLDEN"
            hashes = {
                "brief": _hash_json(context.brief("LEGACY-GOLDEN", base_dir=base)),
                "contract_file": _hash_file(task_dir / "task-contract.json"),
                "diagnostics": _hash_json(context.brief_diagnostics("LEGACY-GOLDEN", base_dir=base)),
                "events_file": _hash_file(task_dir / "events.jsonl"),
                "gate_completion": _hash_json(context.gate("LEGACY-GOLDEN", stage="completion", base_dir=base, emit=False)),
                "gate_handoff": _hash_json(context.gate("LEGACY-GOLDEN", stage="handoff", base_dir=base, emit=False)),
                "gate_release": _hash_json(context.gate("LEGACY-GOLDEN", stage="release", base_dir=base, emit=False)),
                "gate_resume": _hash_json(context.gate("LEGACY-GOLDEN", stage="resume", base_dir=base, emit=False)),
                "seal": published["seal"]["integrity_digest"],
                "snapshot_file": _hash_file(task_dir / "snapshot.json"),
            }

        self.assertEqual(hashes, LEGACY_HASHES)


class ReadOnlyLockingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.addCleanup(self.temp.cleanup)
        context.publish_contract(
            {
                "schema": 1,
                "task_id": "TASK-001",
                "version": 1,
                "issued_by": "publisher",
                "issued_at": "2026-08-31T02:00:00+00:00",
                "authorized_approvers": [],
                "objective": "Keep reads side-effect free",
                "scope": ["strict context"],
                "out_of_scope": [],
                "constraints": [],
                "acceptance_criteria": [{
                    "id": "AC-01",
                    "criterion": "Read behavior is preserved",
                    "required_evidence_types": ["test-report"],
                }],
            },
            confirmed_by="publisher",
            base_dir=self.base,
        )

    def _assert_read_lock_failure(self) -> None:
        for function in (context.audit,):
            report = function("TASK-001", base_dir=self.base, emit=False)
            self.assertFalse(report["passed"])
            self.assertTrue(any("READ_LOCK_UNAVAILABLE" in error for error in report["errors"]))
        for stage in ("release", "resume", "handoff", "completion"):
            report = context.gate("TASK-001", stage=stage, base_dir=self.base, emit=False)
            self.assertFalse(report["passed"])
            self.assertTrue(any("READ_LOCK_UNAVAILABLE" in error for error in report["errors"]))
        with self.assertRaisesRegex(context.ContextError, "READ_LOCK_UNAVAILABLE"):
            context.brief("TASK-001", base_dir=self.base)
        with self.assertRaisesRegex(context.ContextError, "READ_LOCK_UNAVAILABLE"):
            context.brief_diagnostics("TASK-001", base_dir=self.base)

    def test_bad_sample_probe_preserves_stats_without_filesystem_writes(self) -> None:
        with patch("tempfile.TemporaryDirectory", side_effect=AssertionError("probe wrote temp state")):
            report = context.audit("TASK-001", base_dir=self.base, emit=False)
        self.assertEqual(report["stats"]["probe_id"], "PROBE-COMPLETION-EMPTY-EVIDENCE")
        self.assertEqual(report["stats"]["probe_scanned"], 1)
        self.assertEqual(report["stats"]["probe"], "pass")

    def test_missing_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        (task_dir / ".lock").unlink()
        before = sorted(task_dir.iterdir())
        self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_unreadable_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        lock_path = task_dir / ".lock"
        before = sorted(task_dir.iterdir())
        original_open = Path.open

        def unreadable(path: Path, *args, **kwargs):
            if path == lock_path or path.name == ".lock":
                raise OSError("denied for test")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=unreadable):
            self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_unsupported_shared_lock_fails_without_creating_anything(self) -> None:
        task_dir = self.base / "TASK-001"
        before = sorted(task_dir.iterdir())
        with patch.object(context, "fcntl", None):
            self._assert_read_lock_failure()
        self.assertEqual(sorted(task_dir.iterdir()), before)

    def test_read_apis_make_no_write_calls(self) -> None:
        calls = (context.audit, context.brief, context.brief_diagnostics)
        with patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")), \
             patch.object(context, "_atomic_write_json", side_effect=AssertionError("write")), \
             patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temp")):
            for function in calls:
                if function is context.audit:
                    function("TASK-001", base_dir=self.base, emit=False)
                else:
                    function("TASK-001", base_dir=self.base)
            context.gate("TASK-001", stage="release", base_dir=self.base, emit=False)

    def test_exclusive_writer_cannot_finish_while_shared_lock_is_held(self) -> None:
        root = self.base / "TASK-001"
        writer_started = threading.Event()
        writer_finished = threading.Event()

        def writer() -> None:
            writer_started.set()
            with context._locked(root):
                writer_finished.set()

        with context._shared_locked_existing(root):
            thread = threading.Thread(target=writer)
            thread.start()
            self.assertTrue(writer_started.wait(2))
            self.assertFalse(writer_finished.wait(2))
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(writer_finished.is_set())


class TruthSourceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.addCleanup(self.temp.cleanup)

    def contract(self, **overrides: object) -> dict[str, object]:
        contract: dict[str, object] = {"workspace_root": str(self.workspace.resolve())}
        contract.update(overrides)
        return contract

    def valid_truth_sources(self) -> dict[str, object]:
        return {
            "schema": "truth-sources/v1",
            "items": [{
                "id": "TS-STATUS",
                "purpose": "Authoritative status source",
                "source_ref": {"kind": "file", "locator": "docs/status.md"},
                "owner": "project-lead",
                "max_age_seconds": 60,
                "validation_method": "owner-readback",
                "invalidate_on_change_kinds": ["implementation-change"],
            }],
        }

    def valid_contract(self) -> dict[str, object]:
        return self.contract(
            required_capabilities=["truth-sources/v1"],
            truth_sources=self.valid_truth_sources(),
        )

    def test_truth_sources_requires_exact_capability_pair(self) -> None:
        with_sources = self.contract(truth_sources=self.valid_truth_sources())
        self.assertIn(
            "contract.truth_sources requires required_capabilities truth-sources/v1",
            validate_truth_source_contract(with_sources),
        )
        capability_only = self.contract(required_capabilities=["truth-sources/v1"])
        self.assertIn(
            "contract.required_capabilities truth-sources/v1 requires truth_sources",
            validate_truth_source_contract(capability_only),
        )

    def test_undeclared_contract_does_no_truth_source_validation(self) -> None:
        self.assertEqual(validate_truth_source_contract({"workspace_root": "not-absolute"}), [])

    def test_required_capabilities_are_unique_non_empty_and_supported(self) -> None:
        cases = (
            ([], "contract.required_capabilities must be a non-empty list of unique non-empty strings"),
            (["truth-sources/v1", "truth-sources/v1"], "contract.required_capabilities must be a non-empty list of unique non-empty strings"),
            ([""], "contract.required_capabilities must be a non-empty list of unique non-empty strings"),
            (["other/v1"], "contract.required_capabilities has unsupported capability: other/v1"),
        )
        for capabilities, expected in cases:
            with self.subTest(capabilities=capabilities):
                errors = validate_truth_source_contract(self.contract(required_capabilities=capabilities))
                self.assertIn(expected, errors)

    def test_unknown_nested_fields_are_rejected(self) -> None:
        contract = self.valid_contract()
        truth = contract["truth_sources"]
        assert isinstance(truth, dict)
        items = truth["items"]
        assert isinstance(items, list)
        item = items[0]
        assert isinstance(item, dict)
        item["expected_digest"] = "sha256:" + "0" * 64
        errors = validate_truth_source_contract(contract)
        self.assertIn("contract.truth_sources.items[0] has unknown fields: ['expected_digest']", errors)

    def test_truth_source_and_item_allowlists(self) -> None:
        cases = (
            (lambda c: c["truth_sources"].update({"extra": True}), "contract.truth_sources has unknown fields: ['extra']"),
            (lambda c: c["truth_sources"]["items"][0]["source_ref"].update({"extra": True}), "contract.truth_sources.items[0].source_ref has unknown fields: ['extra']"),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                contract = self.valid_contract()
                mutate(contract)
                self.assertIn(expected, validate_truth_source_contract(contract))

    def test_item_schema_cases(self) -> None:
        cases = (
            ("id", "", "contract.truth_sources.items[0].id must match source ID pattern"),
            ("id", "x" * 129, "contract.truth_sources.items[0].id must match source ID pattern"),
            ("purpose", "x" * 161, "contract.truth_sources.items[0].purpose must be a non-empty single-line string of at most 160 characters"),
            ("owner", "x" * 129, "contract.truth_sources.items[0].owner must be a non-empty single-line string of at most 128 characters"),
            ("validation_method", "read-back", "contract.truth_sources.items[0].validation_method must equal owner-readback"),
            ("max_age_seconds", True, "contract.truth_sources.items[0].max_age_seconds must be a positive integer"),
            ("max_age_seconds", 0, "contract.truth_sources.items[0].max_age_seconds must be a positive integer"),
            ("invalidate_on_change_kinds", ["same", "same"], "contract.truth_sources.items[0].invalidate_on_change_kinds must be a non-empty list of unique non-empty single-line strings"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                contract = self.valid_contract()
                contract["truth_sources"]["items"][0][field] = value
                self.assertIn(expected, validate_truth_source_contract(contract))
        duplicate = self.valid_contract()
        duplicate["truth_sources"]["items"].append(dict(duplicate["truth_sources"]["items"][0]))
        self.assertIn("contract.truth_sources.items has duplicate id: TS-STATUS", validate_truth_source_contract(duplicate))

    def test_workspace_root_cases(self) -> None:
        cases = (
            ("relative", "contract.workspace_root must be an existing absolute non-symlink directory"),
            (str(self.workspace / "missing"), "contract.workspace_root must be an existing absolute non-symlink directory"),
        )
        for root, expected in cases:
            with self.subTest(root=root):
                contract = self.valid_contract()
                contract["workspace_root"] = root
                self.assertIn(expected, validate_truth_source_contract(contract))
        link = self.workspace.parent / "workspace-link"
        link.symlink_to(self.workspace, target_is_directory=True)
        contract = self.valid_contract()
        contract["workspace_root"] = str(link)
        self.assertIn("contract.workspace_root must be an existing absolute non-symlink directory", validate_truth_source_contract(contract))

    def test_locator_schema_cases(self) -> None:
        cases = (
            ({"kind": "url", "locator": "docs/status.md"}, "contract.truth_sources.items[0].source_ref.kind must equal file"),
            ({"kind": "file", "locator": ""}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "/etc/passwd"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "../status.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "docs//status.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "docs/ status.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "docs/#status.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "docs/~status.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
            ({"kind": "file", "locator": "docs/*.md"}, "contract.truth_sources.items[0].source_ref.locator must be a safe workspace-relative file path"),
        )
        for source_ref, expected in cases:
            with self.subTest(source_ref=source_ref):
                contract = self.valid_contract()
                contract["truth_sources"]["items"][0]["source_ref"] = source_ref
                self.assertIn(expected, validate_truth_source_contract(contract))


class SecureFileResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        (self.root / "docs").mkdir(parents=True)
        self.status = self.root / "docs" / "status.md"
        self.status.write_bytes(b"inside source")
        self.addCleanup(self.temp.cleanup)

    def resolve(self, locator: str = "docs/status.md") -> dict[str, object]:
        return resolve_file_source(self.root.resolve(), {"kind": "file", "locator": locator})

    def test_happy_path_returns_only_digest_metadata(self) -> None:
        result = self.resolve()
        self.assertEqual(result["status"], "pass")
        self.assertIsNone(result["code"])
        self.assertRegex(result["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(set(result), {"status", "code", "fingerprint"})

    def test_non_mapping_source_ref_fails_closed_with_exact_result_shape(self) -> None:
        for source_ref in (None, [], "not-a-mapping"):
            with self.subTest(source_ref=source_ref):
                result = resolve_file_source(self.root.resolve(), source_ref)
                self.assertEqual(result, {
                    "status": "fail",
                    "code": "TRUTH_SOURCE_UNSAFE_PATH",
                    "fingerprint": None,
                })

    def test_rejects_absolute_escape_glob_and_dot_segments_without_open(self) -> None:
        locators = (
            "/etc/passwd", "../escape", "docs/./status.md", "docs/../status.md",
            "docs/*.md", "docs/a?.md", "docs/a[0].md", "docs/a{b}.md",
        )
        with patch.object(truth_sources.os, "open", side_effect=AssertionError("must not open")):
            for locator in locators:
                with self.subTest(locator=locator):
                    self.assertEqual(self.resolve(locator), {"status": "fail", "code": "TRUTH_SOURCE_UNSAFE_PATH", "fingerprint": None})

    def test_rejects_empty_nul_hash_tilde_empty_segment_and_segment_whitespace_without_open(self) -> None:
        locators = ("", "docs/\x00status", "docs/#status", "docs/~status", "docs//status", " docs/status", "docs/status ")
        with patch.object(truth_sources.os, "open", side_effect=AssertionError("must not open")):
            for locator in locators:
                with self.subTest(locator=locator):
                    self.assertEqual(self.resolve(locator)["code"], "TRUTH_SOURCE_UNSAFE_PATH")

    def test_rejects_workspace_root_intermediate_and_final_symlinks(self) -> None:
        root_link = self.root.parent / "root-link"
        root_link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(resolve_file_source(root_link, {"kind": "file", "locator": "docs/status.md"})["code"], "TRUTH_SOURCE_SYMLINK")
        (self.root / "linked-docs").symlink_to(self.root / "docs", target_is_directory=True)
        self.assertEqual(self.resolve("linked-docs/status.md")["code"], "TRUTH_SOURCE_SYMLINK")
        (self.root / "docs" / "linked-status.md").symlink_to(self.status)
        self.assertEqual(self.resolve("docs/linked-status.md")["code"], "TRUTH_SOURCE_SYMLINK")

    def test_rejects_directory_and_non_regular_final_targets(self) -> None:
        self.assertEqual(self.resolve("docs")["code"], "TRUTH_SOURCE_NOT_REGULAR_FILE")
        fifo = self.root / "docs" / "pipe"
        os.mkfifo(fifo)
        self.assertEqual(self.resolve("docs/pipe")["code"], "TRUTH_SOURCE_NOT_REGULAR_FILE")

    def test_root_swap_cannot_redirect_resolution_outside_workspace(self) -> None:
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "docs").mkdir()
        (outside / "docs" / "status.md").write_text("ROOT_SWAP_CANARY", encoding="utf-8")
        first_read = threading.Event()
        proceed = threading.Event()
        original_read = truth_sources.os.read

        def barrier_read(fd: int, count: int) -> bytes:
            first_read.set()
            self.assertTrue(proceed.wait(2))
            return original_read(fd, count)

        with patch.object(truth_sources.os, "read", side_effect=barrier_read):
            result_box: dict[str, object] = {}
            thread = threading.Thread(target=lambda: result_box.setdefault("result", self.resolve()))
            thread.start()
            self.assertTrue(first_read.wait(2))
            held = self.root.parent / "held-root"
            self.root.rename(held)
            self.root.symlink_to(outside, target_is_directory=True)
            proceed.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_box["result"]["fingerprint"], "sha256:" + hashlib.sha256(b"inside source").hexdigest())

    def test_changed_during_read_returns_unknown(self) -> None:
        self.status.write_bytes(b"a" * (64 * 1024 + 1))
        read_once = threading.Event()
        proceed = threading.Event()
        original_read = truth_sources.os.read
        calls = 0

        def barrier_read(fd: int, count: int) -> bytes:
            nonlocal calls
            value = original_read(fd, count)
            calls += 1
            if calls == 1:
                read_once.set()
                self.assertTrue(proceed.wait(2))
            return value

        with patch.object(truth_sources.os, "read", side_effect=barrier_read):
            result_box: dict[str, object] = {}
            thread = threading.Thread(target=lambda: result_box.setdefault("result", self.resolve()))
            thread.start()
            self.assertTrue(read_once.wait(2))
            self.status.write_bytes(b"b" * (64 * 1024 + 2))
            proceed.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_box["result"], {"status": "unknown", "code": "TRUTH_SOURCE_CHANGED_DURING_READ", "fingerprint": None})

    def test_exactly_16_mib_passes_and_one_byte_more_fails(self) -> None:
        exact = self.root / "docs" / "exact.bin"
        exact.write_bytes(b"x" * MAX_SOURCE_BYTES)
        self.assertEqual(self.resolve("docs/exact.bin")["status"], "pass")
        too_large = self.root / "docs" / "too-large.bin"
        too_large.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
        self.assertEqual(self.resolve("docs/too-large.bin"), {"status": "fail", "code": "TRUTH_SOURCE_TOO_LARGE", "fingerprint": None})

    def test_every_success_and_failure_path_closes_all_fds(self) -> None:
        original_open, original_close = truth_sources.os.open, truth_sources.os.close
        opened: list[int] = []
        closed: list[int] = []

        def counting_open(*args: object, **kwargs: object) -> int:
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def counting_close(fd: int) -> None:
            closed.append(fd)
            original_close(fd)

        with patch.object(truth_sources.os, "open", side_effect=counting_open), \
             patch.object(truth_sources.os, "close", side_effect=counting_close):
            self.resolve()
            self.resolve("docs/missing.md")
            self.resolve("docs")
            (self.root / "docs" / "too-large.bin").write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
            self.resolve("docs/too-large.bin")
            (self.root / "docs" / "linked-status.md").symlink_to(self.status)
            self.resolve("docs/linked-status.md")
        self.assertEqual(sorted(opened), sorted(closed))

    def test_errno_and_unsupported_platform_map_to_all_stable_codes(self) -> None:
        cases = (
            (errno.ENOENT, "fail", "TRUTH_SOURCE_NOT_FOUND"),
            (errno.ELOOP, "fail", "TRUTH_SOURCE_SYMLINK"),
            (errno.ENOTDIR, "fail", "TRUTH_SOURCE_NOT_REGULAR_FILE"),
            (errno.EACCES, "unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
            (errno.EPERM, "unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
            (errno.EIO, "unknown", "TRUTH_SOURCE_TRANSIENT_IO"),
            (errno.EBUSY, "unknown", "TRUTH_SOURCE_TRANSIENT_IO"),
            (errno.EINTR, "unknown", "TRUTH_SOURCE_TRANSIENT_IO"),
        )
        if hasattr(errno, "ESTALE"):
            cases += ((errno.ESTALE, "unknown", "TRUTH_SOURCE_TRANSIENT_IO"),)
        for number, status, code in cases:
            with self.subTest(number=number):
                with patch.object(truth_sources.os, "open", side_effect=OSError(number, "test")):
                    self.assertEqual(self.resolve(), {"status": status, "code": code, "fingerprint": None})
        with patch.object(truth_sources.os, "O_NOFOLLOW", None):
            self.assertEqual(self.resolve(), {"status": "unknown", "code": "TRUTH_SOURCE_RESOLVER_UNKNOWN", "fingerprint": None})
        with patch.object(truth_sources.os, "read", return_value=b""):
            self.assertEqual(self.resolve(), {"status": "unknown", "code": "TRUTH_SOURCE_TRANSIENT_IO", "fingerprint": None})

    def test_missing_none_and_non_integer_nonblocking_flag_fail_closed(self) -> None:
        original_nonblocking = truth_sources.os.O_NONBLOCK
        delattr(truth_sources.os, "O_NONBLOCK")
        try:
            self.assertEqual(self.resolve(), {
                "status": "unknown",
                "code": "TRUTH_SOURCE_RESOLVER_UNKNOWN",
                "fingerprint": None,
            })
        finally:
            truth_sources.os.O_NONBLOCK = original_nonblocking
        for value in (None, "not-an-integer"):
            with self.subTest(value=value), patch.object(truth_sources.os, "O_NONBLOCK", value):
                self.assertEqual(self.resolve(), {
                    "status": "unknown",
                    "code": "TRUTH_SOURCE_RESOLVER_UNKNOWN",
                    "fingerprint": None,
                })

    def test_zero_or_false_safety_flags_fail_closed_before_open(self) -> None:
        for flag_name in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY", "O_NONBLOCK"):
            for value in (0, False):
                with self.subTest(flag_name=flag_name, value=value), \
                     patch.object(truth_sources.os, flag_name, value), \
                     patch.object(truth_sources.os, "open", side_effect=AssertionError("must not open")):
                    self.assertEqual(self.resolve(), {
                        "status": "unknown",
                        "code": "TRUTH_SOURCE_RESOLVER_UNKNOWN",
                        "fingerprint": None,
                    })

    def test_close_failure_returns_unknown_and_never_retries_a_descriptor(self) -> None:
        original_open, original_close = truth_sources.os.open, truth_sources.os.close
        opened: list[int] = []
        closed: list[int] = []

        def counting_open(*args: object, **kwargs: object) -> int:
            descriptor = original_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def close_once_then_fail(descriptor: int) -> None:
            closed.append(descriptor)
            original_close(descriptor)
            if len(closed) == 1:
                raise OSError(errno.EIO, "synthetic close failure")

        with patch.object(truth_sources.os, "open", side_effect=counting_open), \
             patch.object(truth_sources.os, "close", side_effect=close_once_then_fail):
            result = self.resolve()
        self.assertEqual(result, {
            "status": "unknown",
            "code": "TRUTH_SOURCE_RESOLVER_UNKNOWN",
            "fingerprint": None,
        })
        self.assertEqual(closed, list(reversed(opened)))
        self.assertEqual(len(closed), len(set(closed)))

    def test_result_and_exception_never_contain_file_canary(self) -> None:
        canary = "TRUTH_SOURCE_FILE_CANARY_DO_NOT_LEAK"
        self.status.write_text(canary, encoding="utf-8")
        self.assertNotIn(canary, repr(self.resolve()))
        with patch.object(truth_sources.os, "read", side_effect=OSError(errno.EIO, canary)):
            self.assertNotIn(canary, repr(self.resolve()))


class _TruthSourceContractFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.addCleanup(self.temp.cleanup)

    def contract(self, version: int = 1, ids: tuple[str, ...] = ("TS-STATUS",)) -> dict[str, object]:
        return {
            "schema": 1,
            "task_id": "TSC-03",
            "version": version,
            "issued_by": "publisher",
            "issued_at": "2026-08-31T02:00:00+00:00",
            "authorized_approvers": [],
            "objective": "Persist truth control state",
            "scope": ["strict context"],
            "out_of_scope": [],
            "constraints": [],
            "acceptance_criteria": [{
                "id": "AC-01",
                "criterion": "Truth control remains replayable",
                "required_evidence_types": ["test-report"],
            }],
            "workspace_root": str(self.workspace),
            "required_capabilities": ["truth-sources/v1"],
            "truth_sources": {
                "schema": "truth-sources/v1",
                "items": [{
                    "id": source_id,
                    "purpose": "Authoritative status",
                    "source_ref": {"kind": "file", "locator": f"docs/{source_id}.md"},
                    "owner": "publisher",
                    "max_age_seconds": 60,
                    "validation_method": "owner-readback",
                    "invalidate_on_change_kinds": ["implementation-change"],
                } for source_id in ids],
            },
        }

    def publish(self, version: int = 1, ids: tuple[str, ...] = ("TS-STATUS",)) -> dict[str, object]:
        return context.publish_contract(self.contract(version, ids), confirmed_by="publisher", base_dir=self.base)

    def legacy_contract(self, version: int) -> dict[str, object]:
        value = self.contract(version)
        value.pop("required_capabilities")
        value.pop("truth_sources")
        return value

    def events(self) -> list[dict[str, object]]:
        return context._read_events(context._paths("TSC-03", self.base)["events"])


class TruthSourceApiTests(_TruthSourceContractFixture):
    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.workspace.resolve()
        status_dir = self.workspace / "docs"
        status_dir.mkdir()
        self.status = status_dir / "TS-STATUS.md"
        self.status.write_text("initial authoritative status\n", encoding="utf-8")
        self.publish()
        self.task_id = "TSC-03"

    def paths(self) -> dict[str, Path]:
        return context._paths(self.task_id, self.base)

    def snapshot(self) -> dict[str, object]:
        return context._read_json(self.paths()["snapshot"])

    def events_bytes(self) -> bytes:
        return self.paths()["events"].read_bytes()

    def test_mark_dirty_updates_only_matching_sources_once(self) -> None:
        before = self.snapshot()["truth_sources"]["generation"]
        result = context.mark_truth_sources_dirty(
            self.task_id,
            change_kind="implementation-change",
            actor="executor-01",
            reason="authentication behavior changed",
            base_dir=self.base,
        )
        self.assertEqual(result["generation"], before + 1)
        self.assertEqual(result["affected_source_ids"], ["TS-STATUS"])
        self.assertEqual(set(result), {"event_id", "generation", "affected_source_ids"})
        self.assertEqual(self.snapshot()["truth_sources"]["generation"], before + 1)

    def test_public_dispatcher_and_exports_include_both_write_apis(self) -> None:
        self.assertIn("mark_truth_sources_dirty", context.__all__)
        self.assertIn("observe_truth_source", context.__all__)
        result = asyncio.run(context.run(
            "mark_truth_sources_dirty",
            task_id=self.task_id,
            change_kind="implementation-change",
            actor="executor-01",
            reason="dispatcher path",
            base_dir=self.base,
        ))
        self.assertEqual(result["affected_source_ids"], ["TS-STATUS"])

    def test_mark_dirty_without_matching_change_kind_writes_nothing(self) -> None:
        before = self.events_bytes()
        with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_CHANGE_KIND_UNDECLARED"):
            context.mark_truth_sources_dirty(
                self.task_id,
                change_kind="typo-change",
                actor="executor-01",
                reason="must not write",
                base_dir=self.base,
            )
        self.assertEqual(self.events_bytes(), before)

    def test_observe_requires_declared_owner_and_stable_refs(self) -> None:
        before = self.events_bytes()
        with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_OWNER_MISMATCH"):
            context.observe_truth_source(
                self.task_id,
                source_id="TS-STATUS",
                actor="executor-01",
                verification_refs=["review:1"],
                base_dir=self.base,
            )
        self.assertEqual(self.events_bytes(), before)
        with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_VERIFICATION_REFS_INVALID"):
            context.observe_truth_source(
                self.task_id,
                source_id="TS-STATUS",
                actor="publisher",
                verification_refs=["not a stable reference"],
                base_dir=self.base,
            )
        self.assertEqual(self.events_bytes(), before)

    def test_observe_binds_current_contract_generation_fingerprint_and_time(self) -> None:
        result = context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:initial"],
            base_dir=self.base,
        )
        event = self.events()[-1]
        self.assertEqual(set(result), {
            "event_id", "source_id", "observed_generation", "fingerprint", "observed_at",
        })
        self.assertEqual(result["event_id"], event["event_id"])
        self.assertEqual(result["source_id"], "TS-STATUS")
        self.assertEqual(result["observed_generation"], 1)
        self.assertEqual(result["fingerprint"], "sha256:" + hashlib.sha256(self.status.read_bytes()).hexdigest())
        self.assertEqual(result["observed_at"], event["created_at"])
        self.assertEqual(event["payload"]["observed_generation"], 1)
        self.assertNotIn("verification_refs", result)

    def test_observe_rejects_undeclared_file_change_until_marked_dirty(self) -> None:
        context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:baseline"],
            base_dir=self.base,
        )
        self.status.write_text("changed authoritative status\n", encoding="utf-8")
        before = self.events_bytes()
        with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_UNDECLARED_CHANGE"):
            context.observe_truth_source(
                self.task_id,
                source_id="TS-STATUS",
                actor="publisher",
                verification_refs=["review:changed"],
                base_dir=self.base,
            )
        self.assertEqual(self.events_bytes(), before)
        context.mark_truth_sources_dirty(
            self.task_id,
            change_kind="implementation-change",
            actor="executor-01",
            reason="status implementation changed",
            base_dir=self.base,
        )
        result = context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:changed"],
            base_dir=self.base,
        )
        self.assertEqual(result["observed_generation"], 2)

    def test_repeated_same_fingerprint_observe_refreshes_same_generation(self) -> None:
        first = context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:first"],
            base_dir=self.base,
        )
        second = context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:refresh"],
            base_dir=self.base,
        )
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["observed_generation"], second["observed_generation"])
        state = self.snapshot()["truth_sources"]["sources"]["TS-STATUS"]
        self.assertEqual(state["observed_generation"], 1)
        self.assertEqual(state["observation"]["verification_refs"], ["review:refresh"])

    def test_resolver_failure_writes_no_event(self) -> None:
        before = self.events_bytes()
        with patch.object(context, "resolve_file_source", return_value={
            "status": "unknown", "code": "TRUTH_SOURCE_TRANSIENT_IO", "fingerprint": None,
        }):
            with self.assertRaisesRegex(context.ContextError, "TRUTH_SOURCE_TRANSIENT_IO"):
                context.observe_truth_source(
                    self.task_id,
                    source_id="TS-STATUS",
                    actor="publisher",
                    verification_refs=["review:retry"],
                    base_dir=self.base,
                )
        self.assertEqual(self.events_bytes(), before)

    def test_observe_normalizes_unknown_or_malformed_resolver_results_without_writing(self) -> None:
        canary = "TRUTH_SOURCE_RESOLVER_CANARY_DO_NOT_LEAK"
        expected_fingerprint = "sha256:" + "a" * 64
        bad_results = (
            {"status": "fail", "code": canary, "fingerprint": None},
            {"status": "pass", "code": "TRUTH_SOURCE_NOT_FOUND", "fingerprint": expected_fingerprint},
            {"status": "unknown", "code": "TRUTH_SOURCE_TRANSIENT_IO", "fingerprint": expected_fingerprint},
            {"status": "invalid", "code": "TRUTH_SOURCE_NOT_FOUND", "fingerprint": None},
        )
        for result in bad_results:
            with self.subTest(result=result):
                before = self.events_bytes()
                with patch.object(context, "resolve_file_source", return_value=result):
                    with self.assertRaisesRegex(context.ContextError, "^TRUTH_SOURCE_RESOLVER_UNKNOWN$") as raised:
                        context.observe_truth_source(
                            self.task_id,
                            source_id="TS-STATUS",
                            actor="publisher",
                            verification_refs=["review:resolver"],
                            base_dir=self.base,
                        )
                self.assertNotIn(canary, str(raised.exception))
                self.assertEqual(self.events_bytes(), before)

    def test_uncommitted_contract_writes_no_event(self) -> None:
        uncommitted_base = Path(self.temp.name) / "uncommitted" / ".prime" / "context"
        with patch.object(context, "_append_event_locked", side_effect=OSError("event cut")):
            with self.assertRaises(OSError):
                context.publish_contract(self.contract(), confirmed_by="publisher", base_dir=uncommitted_base)
        paths = context._paths(self.task_id, uncommitted_base)
        before_exists = paths["events"].exists()
        with self.assertRaisesRegex(context.ContextError, "CONTRACT_COMMIT_MISSING_EVENT"):
            context.mark_truth_sources_dirty(
                self.task_id,
                change_kind="implementation-change",
                actor="executor-01",
                reason="must not repair an uncommitted contract",
                base_dir=uncommitted_base,
            )
        self.assertEqual(paths["events"].exists(), before_exists)


class TruthSourceReducerTests(_TruthSourceContractFixture):
    maxDiff = None

    def test_first_truth_enabled_publish_creates_generation_one_reset(self) -> None:
        self.publish()
        snapshot = context._rebuild_snapshot("TSC-03", self.events())
        self.assertEqual(snapshot["truth_sources"], {
            "generation": 1,
            "sources": {
                "TS-STATUS": {
                    "required_generation": 1,
                    "observed_generation": None,
                    "observation": None,
                    "status": "unobserved",
                }
            },
        })

    def test_repeated_dirty_increments_once_per_event_and_preserves_unaffected_sources(self) -> None:
        self.publish(ids=("TS-A", "TS-B"))
        events = self.events()
        digest = events[0]["payload"]["integrity_digest"]
        events.extend([
            context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
                "contract_digest": digest, "generation": 2, "change_kind": "implementation-change",
                "reason": "changed", "affected_source_ids": ["TS-A"],
            }),
            context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
                "contract_digest": digest, "generation": 3, "change_kind": "implementation-change",
                "reason": "changed again", "affected_source_ids": ["TS-A"],
            }),
        ])
        snapshot = context._rebuild_snapshot("TSC-03", events)
        self.assertEqual(snapshot["truth_sources"]["generation"], 3)
        self.assertEqual(snapshot["truth_sources"]["sources"]["TS-A"]["required_generation"], 3)
        self.assertEqual(snapshot["truth_sources"]["sources"]["TS-B"]["required_generation"], 1)

    def test_contract_update_atomically_replaces_sources_and_removes_deleted_ids(self) -> None:
        self.publish(ids=("TS-A", "TS-B"))
        self.publish(version=2, ids=("TS-B", "TS-C"))
        snapshot = context._rebuild_snapshot("TSC-03", self.events())
        self.assertEqual(snapshot["truth_sources"]["generation"], 2)
        self.assertEqual(set(snapshot["truth_sources"]["sources"]), {"TS-B", "TS-C"})

    def test_capability_removal_and_later_no_truth_versions_keep_empty_resets_monotonic(self) -> None:
        self.publish()
        removed = self.contract(2)
        removed.pop("required_capabilities")
        removed.pop("truth_sources")
        context.publish_contract(removed, confirmed_by="publisher", base_dir=self.base)
        later = dict(removed)
        later["version"] = 3
        context.publish_contract(later, confirmed_by="publisher", base_dir=self.base)
        snapshot = context._rebuild_snapshot("TSC-03", self.events())
        self.assertEqual(snapshot["truth_sources"], {"generation": 3, "sources": {}})

    def test_rebuild_rejects_jump_unknown_source_and_malformed_control_event(self) -> None:
        self.publish()
        event = context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
            "contract_digest": "sha256:" + "0" * 64, "generation": 3,
            "change_kind": "implementation-change", "reason": "bad", "affected_source_ids": ["MISSING"],
        })
        with self.assertRaisesRegex(context.ContextError, "truth-source-dirtied"):
            context._rebuild_snapshot("TSC-03", [*self.events(), event])

    def test_poisoned_event_cannot_be_healed_by_later_observation(self) -> None:
        self.publish()
        events = self.events()
        digest = events[0]["payload"]["integrity_digest"]
        events.append(context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
            "contract_digest": digest, "generation": 4, "change_kind": "implementation-change",
            "reason": "poison", "affected_source_ids": ["TS-STATUS"],
        }))
        events.append(context._new_event("TSC-03", "truth-source-observed", "publisher", {
            "contract_digest": digest, "observed_generation": 1, "source_id": "TS-STATUS",
            "fingerprint": "sha256:" + "1" * 64, "verification_refs": ["review:1"],
        }))
        with self.assertRaisesRegex(context.ContextError, "generation"):
            context._rebuild_snapshot("TSC-03", events)

    def test_replay_preserves_observer_actor_for_later_owner_validation(self) -> None:
        self.publish()
        digest = self.events()[0]["payload"]["integrity_digest"]
        event = context._new_event("TSC-03", "truth-source-observed", "other-actor", {
            "contract_digest": digest,
            "observed_generation": 1,
            "source_id": "TS-STATUS",
            "fingerprint": "sha256:" + "2" * 64,
            "verification_refs": ["review:owner-check-later"],
        })
        snapshot = context._rebuild_snapshot("TSC-03", [*self.events(), event])
        observation = snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"]
        self.assertEqual(observation["actor"], "other-actor")
        self.assertNotEqual(observation["actor"], self.contract()["truth_sources"]["items"][0]["owner"])

    def test_replay_rejects_invalid_verification_refs_and_later_event_cannot_heal(self) -> None:
        self.publish()
        digest = self.events()[0]["payload"]["integrity_digest"]
        for invalid_ref in ("review:line\nbreak", "not a stable reference"):
            with self.subTest(invalid_ref=invalid_ref):
                malformed = context._new_event("TSC-03", "truth-source-observed", "publisher", {
                    "contract_digest": digest,
                    "observed_generation": 1,
                    "source_id": "TS-STATUS",
                    "fingerprint": "sha256:" + "3" * 64,
                    "verification_refs": [invalid_ref],
                })
                later_valid = context._new_event("TSC-03", "truth-source-observed", "publisher", {
                    "contract_digest": digest,
                    "observed_generation": 1,
                    "source_id": "TS-STATUS",
                    "fingerprint": "sha256:" + "3" * 64,
                    "verification_refs": ["review:valid-later"],
                })
                with self.assertRaisesRegex(context.ContextError, "verification_refs"):
                    context._rebuild_snapshot("TSC-03", [*self.events(), malformed, later_valid])


class TruthSourceRecoveryTests(_TruthSourceContractFixture):
    def test_stale_pretruth_snapshot_forces_history_rebuild_and_v3_empty_reset(self) -> None:
        context.publish_contract(self.legacy_contract(0), confirmed_by="publisher", base_dir=self.base)
        paths = context._paths("TSC-03", self.base)
        pre_truth_snapshot = context._read_json(paths["snapshot"])
        self.publish(version=1)
        context.publish_contract(self.legacy_contract(2), confirmed_by="publisher", base_dir=self.base)
        context._atomic_write_json(paths["snapshot"], pre_truth_snapshot)

        published = context.publish_contract(self.legacy_contract(3), confirmed_by="publisher", base_dir=self.base)

        events = self.events()
        matching = context._matching_contract_publish_events(published, events)
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["payload"]["truth_source_reset"], {
            "schema": "truth-sources/v1", "generation": 3, "source_ids": [],
        })
        self.assertTrue(context.audit("TSC-03", base_dir=self.base, emit=False)["passed"])

    def test_committed_view_rejects_stale_pretruth_fast_path_and_rebuilds_history(self) -> None:
        context.publish_contract(self.legacy_contract(0), confirmed_by="publisher", base_dir=self.base)
        paths = context._paths("TSC-03", self.base)
        pre_truth_snapshot = context._read_json(paths["snapshot"])
        self.publish(version=1)
        removed = context.publish_contract(self.legacy_contract(2), confirmed_by="publisher", base_dir=self.base)
        context._atomic_write_json(paths["snapshot"], pre_truth_snapshot)

        view = context._load_committed_task_view_locked("TSC-03", paths)

        self.assertTrue(view["truth_history_enabled"])
        self.assertEqual(view["contract"], removed)
        self.assertEqual(view["snapshot"], context._rebuild_snapshot("TSC-03", view["events"]))

    def test_missing_publish_event_same_version_retry_repairs_without_reseal(self) -> None:
        original_write = context._append_event_locked
        with patch.object(context, "_append_event_locked", side_effect=OSError("event cut")):
            with self.assertRaises(OSError):
                self.publish()
        contract_path = context._paths("TSC-03", self.base)["contract"]
        sealed = json.loads(contract_path.read_text(encoding="utf-8"))
        repaired = self.publish()
        self.assertEqual(repaired["seal"], sealed["seal"])
        matching = context._matching_contract_publish_events(repaired, self.events())
        self.assertEqual(len(matching), 1)

    def test_duplicate_or_mismatched_latest_publish_event_fails_closed(self) -> None:
        sealed = self.publish()
        paths = context._paths("TSC-03", self.base)
        snapshot = context._rebuild_snapshot("TSC-03", self.events())
        duplicate = context._new_event("TSC-03", "contract-published", "publisher", {
            "task_id": "TSC-03", "version": 1,
            "integrity_digest": sealed["seal"]["integrity_digest"],
            "confirmed_by": sealed["seal"]["confirmed_by"],
            "confirmed_at": sealed["seal"]["confirmed_at"],
            "truth_source_reset": {"schema": "truth-sources/v1", "generation": 2, "source_ids": ["TS-STATUS"]},
        })
        self.assertEqual(
            context._committed_contract_errors(sealed, [*self.events(), duplicate], snapshot),
            ["CONTRACT_COMMIT_DUPLICATE_EVENT"],
        )

    def test_snapshot_write_failure_rebuilds_from_complete_event_log(self) -> None:
        original = context._atomic_write_json
        def write_contract_only(path: Path, value: object) -> None:
            if path.name == "task-contract.json":
                original(path, value)
                return
            raise OSError("snapshot cut")
        with patch.object(context, "_atomic_write_json", side_effect=write_contract_only):
            with self.assertRaises(OSError):
                self.publish()
        view = context._load_committed_task_view_locked("TSC-03", context._paths("TSC-03", self.base))
        self.assertEqual(view["snapshot"], context._rebuild_snapshot("TSC-03", view["events"]))

    def test_capability_add_modify_remove_fail_closed_at_every_publish_write_cut(self) -> None:
        # The four write cuts leave either no sealed replacement, a recoverable
        # missing-event contract, or one event-backed committed view.
        for phase in ("contract", "event", "snapshot"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary_dir:
                self.base = Path(temporary_dir) / ".prime" / "context"
                if phase == "contract":
                    with patch.object(context, "_atomic_write_json", side_effect=OSError("contract cut")):
                        with self.assertRaises(OSError):
                            self.publish()
                elif phase == "event":
                    with patch.object(context, "_append_event_locked", side_effect=OSError("event cut")):
                        with self.assertRaises(OSError):
                            self.publish()
                    self.publish()
                else:
                    original = context._atomic_write_json
                    def write_contract_only(path: Path, value: object) -> None:
                        if path.name == "task-contract.json":
                            original(path, value)
                            return
                        raise OSError("snapshot cut")
                    with patch.object(context, "_atomic_write_json", side_effect=write_contract_only):
                        with self.assertRaises(OSError):
                            self.publish()
                    self.assertEqual(
                        context._load_committed_task_view_locked("TSC-03", context._paths("TSC-03", self.base))["event_count"],
                        1,
                    )

    def test_add_modify_remove_cover_every_publish_cut(self) -> None:
        def legacy(version: int) -> dict[str, object]:
            value = self.contract(version)
            value.pop("required_capabilities")
            value.pop("truth_sources")
            return value

        for operation in ("add", "modify", "remove"):
            for cut in ("contract-write", "contract-replace", "event-append", "snapshot-write"):
                with self.subTest(operation=operation, cut=cut), tempfile.TemporaryDirectory() as temporary_dir:
                    self.base = Path(temporary_dir) / ".prime" / "context"
                    if operation == "add":
                        context.publish_contract(legacy(1), confirmed_by="publisher", base_dir=self.base)
                        candidate = self.contract(2, ("TS-A",))
                    elif operation == "modify":
                        self.publish(ids=("TS-A",))
                        candidate = self.contract(2, ("TS-B",))
                    else:
                        self.publish(ids=("TS-A",))
                        candidate = legacy(2)
                    paths = context._paths("TSC-03", self.base)
                    if cut == "event-append":
                        failure = patch.object(context, "_append_event_locked", side_effect=OSError("event cut"))
                    elif cut == "snapshot-write":
                        original = context._atomic_write_json
                        def write_contract_only(path: Path, value: object) -> None:
                            if path.name == "task-contract.json":
                                original(path, value)
                                return
                            raise OSError("snapshot cut")
                        failure = patch.object(context, "_atomic_write_json", side_effect=write_contract_only)
                    elif cut == "contract-replace":
                        original_replace = context.os.replace
                        failure = patch.object(
                            context.os,
                            "replace",
                            side_effect=lambda source, destination: (_ for _ in ()).throw(OSError("replace cut")) if Path(destination) == paths["contract"] else original_replace(source, destination),
                        )
                    else:
                        failure = patch.object(context, "_atomic_write_json", side_effect=OSError("write cut"))
                    with failure:
                        with self.assertRaises(OSError):
                            context.publish_contract(candidate, confirmed_by="publisher", base_dir=self.base)
                    if cut in {"contract-write", "contract-replace"}:
                        self.assertTrue(context.audit("TSC-03", base_dir=self.base, emit=False)["passed"])
                    elif cut == "event-append":
                        report = context.audit("TSC-03", base_dir=self.base, emit=False)
                        self.assertEqual(report["errors"], ["CONTRACT_COMMIT_MISSING_EVENT"])
                        repaired = context.publish_contract(candidate, confirmed_by="publisher", base_dir=self.base)
                        self.assertEqual(len(context._matching_contract_publish_events(repaired, self.events())), 1)
                    else:
                        view = context._load_committed_task_view_locked("TSC-03", paths)
                        self.assertEqual(view["snapshot"], context._rebuild_snapshot("TSC-03", view["events"]))

    def test_rebuild_and_matching_reject_extra_or_forged_publish_envelopes(self) -> None:
        sealed = self.publish()
        original = self.events()[0]
        for mutation in (
            lambda event: event.update({"extra": True}),
            lambda event: event.update({"schema": 99}),
            lambda event: event.update({"task_id": "OTHER"}),
            lambda event: event.update({"event_id": "forged"}),
            lambda event: event["payload"].update({"extra": True}),
            lambda event: event.update({"actor": "other"}),
        ):
            with self.subTest(mutation=mutation):
                event = json.loads(json.dumps(original))
                mutation(event)
                with self.assertRaises(context.ContextError):
                    context._rebuild_snapshot("TSC-03", [event])
                self.assertEqual(context._matching_contract_publish_events(sealed, [event]), [])

    def test_latest_publish_conflicts_never_repair(self) -> None:
        sealed = self.publish()
        for field, value in (
            ("version", 2),
            ("integrity_digest", "sha256:" + "f" * 64),
            ("confirmed_by", "other"),
            ("confirmed_at", "2026-08-31T04:00:00+00:00"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary_dir:
                self.base = Path(temporary_dir) / ".prime" / "context"
                sealed = self.publish()
                event = context._new_event("TSC-03", "contract-published", "publisher", {
                    "task_id": "TSC-03", "version": 2,
                    "integrity_digest": sealed["seal"]["integrity_digest"],
                    "confirmed_by": sealed["seal"]["confirmed_by"],
                    "confirmed_at": sealed["seal"]["confirmed_at"],
                    "truth_source_reset": {"schema": "truth-sources/v1", "generation": 2, "source_ids": ["TS-STATUS"]},
                })
                event["payload"][field] = value
                if field == "confirmed_by":
                    event["actor"] = value
                paths = context._paths("TSC-03", self.base)
                with paths["events"].open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event) + "\n")
                with self.assertRaisesRegex(context.ContextError, "CONTRACT_COMMIT_MISMATCH"):
                    self.publish()

    def test_no_matching_publish_with_newer_latest_event_never_repairs(self) -> None:
        with patch.object(context, "_append_event_locked", side_effect=OSError("event cut")):
            with self.assertRaises(OSError):
                self.publish()
        sealed = context._read_json(context._paths("TSC-03", self.base)["contract"])
        conflicting = context._new_event("TSC-03", "contract-published", "publisher", {
            "task_id": "TSC-03", "version": 2,
            "integrity_digest": "sha256:" + "f" * 64,
            "confirmed_by": "publisher",
            "confirmed_at": "2026-08-31T04:00:00+00:00",
            "truth_source_reset": {"schema": "truth-sources/v1", "generation": 1, "source_ids": ["TS-STATUS"]},
        })
        paths = context._paths("TSC-03", self.base)
        with paths["events"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(conflicting) + "\n")
        with self.assertRaisesRegex(context.ContextError, "CONTRACT_COMMIT_MISMATCH"):
            self.publish()
        self.assertEqual(context._matching_contract_publish_events(sealed, self.events()), [])

    def test_committed_view_uses_rebuilt_snapshot_when_same_count_content_differs(self) -> None:
        self.publish()
        paths = context._paths("TSC-03", self.base)
        stale = context._read_json(paths["snapshot"])
        stale["truth_sources"]["sources"]["TS-STATUS"]["status"] = "observed"
        context._atomic_write_json(paths["snapshot"], stale)
        view = context._load_committed_task_view_locked("TSC-03", paths)
        self.assertEqual(view["snapshot"], context._rebuild_snapshot("TSC-03", view["events"]))


class LegacyTruthSourceFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / ".prime" / "context"
        self.addCleanup(self.temp.cleanup)
        context.publish_contract(LEGACY_CONTRACT, confirmed_by="publisher", base_dir=self.base)

    def test_corrupt_legacy_events_do_not_trigger_truth_recovery_for_brief_or_gate(self) -> None:
        paths = context._paths("LEGACY-GOLDEN", self.base)
        with paths["events"].open("ab") as handle:
            handle.write(b"{corrupt\n")
        with patch.object(context, "_rebuild_snapshot", side_effect=AssertionError("truth recovery")):
            packet = context.brief("LEGACY-GOLDEN", base_dir=self.base)
            report = context.gate("LEGACY-GOLDEN", stage="release", base_dir=self.base, emit=False)
        self.assertEqual(packet["task_id"], "LEGACY-GOLDEN")
        self.assertFalse(report["passed"])
        self.assertTrue(any("invalid JSONL" in error for error in report["errors"]))
        self.assertFalse(any("brief preflight unavailable" in error for error in report["errors"]))

    def test_matching_never_enabled_snapshot_keeps_brief_and_greater_publish_fast(self) -> None:
        next_contract = dict(LEGACY_CONTRACT)
        next_contract["version"] = 2
        with patch.object(context, "_read_events", side_effect=AssertionError("event scan")), \
             patch.object(context, "_rebuild_snapshot", side_effect=AssertionError("event rebuild")):
            packet = context.brief("LEGACY-GOLDEN", base_dir=self.base)
            published = context.publish_contract(next_contract, confirmed_by="publisher", base_dir=self.base)
        self.assertEqual(packet["task_id"], "LEGACY-GOLDEN")
        self.assertEqual(published["version"], 2)


class TruthSourceEvaluationTests(_TruthSourceContractFixture):
    """The public evaluator fails closed before it performs live file I/O."""

    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.workspace.resolve()
        documents = self.workspace / "docs"
        documents.mkdir()
        self.status = documents / "TS-STATUS.md"
        self.status.write_text("authoritative state\n", encoding="utf-8")
        self.publish()
        context.observe_truth_source(
            "TSC-03", source_id="TS-STATUS", actor="publisher",
            verification_refs=["review:baseline"], base_dir=self.base,
        )
        observed_at = context._read_json(context._paths("TSC-03", self.base)["snapshot"])["truth_sources"]["sources"]["TS-STATUS"]["observation"]["observed_at"]
        self.now = datetime.fromisoformat(observed_at.replace("Z", "+00:00")) + timedelta(seconds=1)

    def current_contract(self) -> dict[str, object]:
        return context._read_json(context._paths("TSC-03", self.base)["contract"])

    def current_snapshot(self) -> dict[str, object]:
        return context._read_json(context._paths("TSC-03", self.base)["snapshot"])

    def evaluate(self, snapshot: dict[str, object] | None = None, resolver: Mock | None = None) -> dict[str, object] | None:
        return truth_sources.evaluate_truth_sources(
            self.current_contract(), snapshot or self.current_snapshot(), now=self.now, resolver=resolver,
        )

    def test_undeclared_contract_returns_none_without_resolver(self) -> None:
        resolver = Mock(side_effect=AssertionError("legacy must not resolve"))
        contract = self.current_contract()
        contract.pop("required_capabilities")
        contract.pop("truth_sources")
        self.assertIsNone(truth_sources.evaluate_truth_sources(
            contract, self.current_snapshot(), now=self.now, resolver=resolver,
        ))
        resolver.assert_not_called()

    def test_result_shape_and_control_invalid_precedence_skip_resolver(self) -> None:
        cases = (
            ("unobserved", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({
                "status": "unobserved", "observed_generation": None, "observation": None,
            }), "TRUTH_SOURCE_UNOBSERVED"),
            ("contract", lambda snapshot: snapshot["contract"].update({
                "integrity_digest": "sha256:" + "0" * 64,
            }), "TRUTH_SOURCE_CONTRACT_MISMATCH"),
            ("observation-contract", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                "contract_digest": "sha256:" + "0" * 64,
            }), "TRUTH_SOURCE_CONTRACT_MISMATCH"),
            ("owner", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                "actor": "other-owner",
            }), "TRUTH_SOURCE_OWNER_MISMATCH"),
            ("dirty", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({
                "status": "dirty", "observed_generation": None, "observation": None,
            }), "TRUTH_SOURCE_DIRTY"),
            ("generation", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({
                "observed_generation": 999,
            }), "TRUTH_SOURCE_GENERATION_MISMATCH"),
            ("malformed-time", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                "observed_at": "not-a-time",
            }), "TRUTH_SOURCE_RESOLVER_UNKNOWN"),
            ("future-time", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                "observed_at": (self.now + timedelta(seconds=301)).isoformat().replace("+00:00", "Z"),
            }), "TRUTH_SOURCE_RESOLVER_UNKNOWN"),
            ("stale-time", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                "observed_at": (self.now - timedelta(seconds=61)).isoformat().replace("+00:00", "Z"),
            }), "TRUTH_SOURCE_STALE"),
        )
        expected_fields = {
            "id", "purpose", "source_ref", "owner", "status", "codes",
            "required_generation", "observed_generation", "observed_at", "fingerprint",
        }
        for name, mutate, expected_code in cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(self.current_snapshot()))
                mutate(snapshot)
                resolver = Mock(side_effect=AssertionError("control-invalid must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                assert evaluation is not None
                self.assertEqual(evaluation["status"], "fail" if expected_code != "TRUTH_SOURCE_RESOLVER_UNKNOWN" else "unknown")
                self.assertEqual(set(evaluation["results"][0]), expected_fields)
                self.assertIn(expected_code, evaluation["results"][0]["codes"])
                self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
                resolver.assert_not_called()

    def test_resolver_stable_results_and_changed_fingerprint(self) -> None:
        expected = "sha256:" + "a" * 64
        cases = (
            ({"status": "fail", "code": "TRUTH_SOURCE_NOT_FOUND", "fingerprint": None}, "fail", "TRUTH_SOURCE_NOT_FOUND"),
            ({"status": "unknown", "code": "TRUTH_SOURCE_PERMISSION_DENIED", "fingerprint": None}, "unknown", "TRUTH_SOURCE_PERMISSION_DENIED"),
            ({"status": "pass", "code": None, "fingerprint": expected}, "fail", "TRUTH_SOURCE_CHANGED"),
            ({"status": "pass", "code": None, "fingerprint": self.current_snapshot()["truth_sources"]["sources"]["TS-STATUS"]["observation"]["fingerprint"]}, "pass", None),
            ({"status": "fail", "code": "TRUTH_SOURCE_FILE_CANARY_DO_NOT_LEAK", "fingerprint": None}, "unknown", "TRUTH_SOURCE_RESOLVER_UNKNOWN"),
        )
        for resolution, status, code in cases:
            with self.subTest(resolution=resolution):
                resolver = Mock(return_value=resolution)
                evaluation = self.evaluate(resolver=resolver)
                assert evaluation is not None
                self.assertEqual(evaluation["status"], status)
                self.assertEqual(evaluation["results"][0]["status"], status)
                if code is not None:
                    self.assertEqual(evaluation["results"][0]["codes"], [code])
                self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 1)
                resolver.assert_called_once()
                self.assertNotIn("TRUTH_SOURCE_FILE_CANARY_DO_NOT_LEAK", repr(evaluation))
        resolver = Mock(side_effect=RuntimeError("TRUTH_SOURCE_EXCEPTION_CANARY_DO_NOT_LEAK"))
        evaluation = self.evaluate(resolver=resolver)
        assert evaluation is not None
        self.assertEqual(evaluation["results"][0]["codes"], ["TRUTH_SOURCE_RESOLVER_UNKNOWN"])
        self.assertNotIn("TRUTH_SOURCE_EXCEPTION_CANARY_DO_NOT_LEAK", repr(evaluation))

    def test_malformed_controls_are_unknown_without_resolution(self) -> None:
        contract_cases = (
            ("truth-not-mapping", lambda contract: contract.update({"truth_sources": []})),
            ("items-not-list", lambda contract: contract["truth_sources"].update({"items": {}})),
            ("items-empty", lambda contract: contract["truth_sources"].update({"items": []})),
            ("item-not-mapping", lambda contract: contract["truth_sources"].update({"items": [None]})),
            ("duplicate-id", lambda contract: contract["truth_sources"].update({"items": [
                contract["truth_sources"]["items"][0], contract["truth_sources"]["items"][0],
            ]})),
            ("invalid-id", lambda contract: contract["truth_sources"]["items"][0].update({"id": "bad id"})),
        )
        for name, mutate in contract_cases:
            with self.subTest(name=name):
                contract = json.loads(json.dumps(self.current_contract()))
                mutate(contract)
                resolver = Mock(side_effect=AssertionError("malformed control must not resolve"))
                evaluation = truth_sources.evaluate_truth_sources(
                    contract, self.current_snapshot(), now=self.now, resolver=resolver,
                )
                self.assertEqual(evaluation, {
                    "status": "unknown", "passed": False, "results": [],
                    "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0},
                })
                resolver.assert_not_called()

        snapshot_cases = (
            ("truth-not-mapping", lambda snapshot: snapshot.update({"truth_sources": []})),
            ("sources-not-mapping", lambda snapshot: snapshot["truth_sources"].update({"sources": []})),
        )
        for name, mutate in snapshot_cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(self.current_snapshot()))
                mutate(snapshot)
                resolver = Mock(side_effect=AssertionError("malformed snapshot must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                self.assertEqual(evaluation, {
                    "status": "unknown", "passed": False, "results": [],
                    "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0},
                })
                resolver.assert_not_called()

        state_cases = (
            ("bad-status", lambda state: state.update({"status": "forged"})),
            ("required-bool", lambda state: state.update({"required_generation": True})),
            ("observed-bool", lambda state: state.update({"observed_generation": True})),
            ("required-zero", lambda state: state.update({"required_generation": 0})),
            ("observed-zero", lambda state: state.update({"observed_generation": 0})),
            ("observed-missing-observation", lambda state: state.pop("observation")),
            ("observed-bad-observation", lambda state: state.update({"observation": []})),
        )
        for name, mutate in state_cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(self.current_snapshot()))
                state = snapshot["truth_sources"]["sources"]["TS-STATUS"]
                mutate(state)
                resolver = Mock(side_effect=AssertionError("malformed state must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                assert evaluation is not None
                self.assertEqual(evaluation["status"], "unknown")
                self.assertFalse(evaluation["passed"])
                self.assertEqual(evaluation["results"][0]["codes"], ["TRUTH_SOURCE_RESOLVER_UNKNOWN"])
                self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
                resolver.assert_not_called()

    def test_hostile_mappings_never_leak_or_escape_normalization(self) -> None:
        canary = "TSC05_HOSTILE_MAPPING_CANARY"

        class HostileMapping(dict):
            def get(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError(canary)

        class IterationHostileMapping(dict):
            def items(self) -> object:
                raise RuntimeError(canary)

        hostile_contract = HostileMapping(self.current_contract())
        resolver = Mock(side_effect=AssertionError("hostile contract must not resolve"))
        evaluation = truth_sources.evaluate_truth_sources(
            hostile_contract, self.current_snapshot(), now=self.now, resolver=resolver,
        )
        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["status"], "unknown")
        self.assertNotIn(canary, repr(evaluation))
        resolver.assert_not_called()

        contract = self.current_contract()
        contract["truth_sources"]["items"][0]["source_ref"] = IterationHostileMapping(
            contract["truth_sources"]["items"][0]["source_ref"]
        )
        evaluation = truth_sources.evaluate_truth_sources(
            contract, self.current_snapshot(), now=self.now, resolver=resolver,
        )
        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["results"], [])
        self.assertNotIn(canary, repr(evaluation))
        resolver.assert_not_called()

        contract = self.current_contract()
        contract["truth_sources"] = HostileMapping(contract["truth_sources"])
        evaluation = truth_sources.evaluate_truth_sources(
            contract, self.current_snapshot(), now=self.now, resolver=resolver,
        )
        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["status"], "unknown")
        self.assertNotIn(canary, repr(evaluation))
        resolver.assert_not_called()

        contract = self.current_contract()
        contract["truth_sources"]["items"][0] = HostileMapping(contract["truth_sources"]["items"][0])
        evaluation = truth_sources.evaluate_truth_sources(
            contract, self.current_snapshot(), now=self.now, resolver=resolver,
        )
        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["results"], [])
        self.assertNotIn(canary, repr(evaluation))
        resolver.assert_not_called()

        snapshot = self.current_snapshot()
        snapshot["truth_sources"] = HostileMapping(snapshot["truth_sources"])
        evaluation = self.evaluate(snapshot, resolver)
        self.assertFalse(evaluation["passed"])
        self.assertNotIn(canary, repr(evaluation))
        resolver.assert_not_called()

        hostile_resolver = Mock(return_value=HostileMapping())
        evaluation = self.evaluate(resolver=hostile_resolver)
        assert evaluation is not None
        self.assertEqual(evaluation["results"][0]["codes"], ["TRUTH_SOURCE_RESOLVER_UNKNOWN"])
        self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 1)
        self.assertNotIn(canary, repr(evaluation))
        with patch.object(context, "resolve_file_source", return_value=HostileMapping()):
            packet = context.brief("TSC-03", base_dir=self.base)
            diagnostics = context.brief_diagnostics("TSC-03", base_dir=self.base)
        self.assertNotIn(canary, repr(packet))
        self.assertNotIn(canary, repr(diagnostics))

    def test_control_precedence_is_missing_then_digest_owner_generation_dirty(self) -> None:
        cases = (
            ("digest-before-owner", lambda snapshot: None, lambda snapshot: (
                snapshot["contract"].update({"integrity_digest": "sha256:" + "0" * 64}),
                snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({"actor": "other"}),
            ), "TRUTH_SOURCE_CONTRACT_MISMATCH"),
            ("owner-after-digest", lambda snapshot: None, lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({"actor": "other"}), "TRUTH_SOURCE_OWNER_MISMATCH"),
            ("generation-after-owner", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"observed_generation": 2}), lambda snapshot: None, "TRUTH_SOURCE_GENERATION_MISMATCH"),
            ("malformed-dirty-is-unknown", lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"status": "dirty"}), lambda snapshot: None, "TRUTH_SOURCE_RESOLVER_UNKNOWN"),
        )
        for name, first, second, expected_code in cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(self.current_snapshot()))
                first(snapshot)
                second(snapshot)
                resolver = Mock(side_effect=AssertionError("precedence failure must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                assert evaluation is not None
                self.assertEqual(evaluation["results"][0]["codes"], [expected_code])
                self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
                resolver.assert_not_called()

    def test_global_digest_precedes_state_and_observed_controls(self) -> None:
        observed_snapshot = json.loads(json.dumps(self.current_snapshot()))
        contract_mismatch = "sha256:" + "0" * 64
        cases = (
            (
                "projected-before-owner-and-generation",
                lambda snapshot: (
                    snapshot["contract"].update({"integrity_digest": contract_mismatch}),
                    snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"observed_generation": 2}),
                    snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({"actor": "other"}),
                ),
                "TRUTH_SOURCE_CONTRACT_MISMATCH",
            ),
            (
                "observation-digest-before-owner-and-generation",
                lambda snapshot: (
                    snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"observed_generation": 2}),
                    snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({
                        "actor": "other", "contract_digest": contract_mismatch,
                    }),
                ),
                "TRUTH_SOURCE_CONTRACT_MISMATCH",
            ),
            (
                "owner-before-generation",
                lambda snapshot: (
                    snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"observed_generation": 2}),
                    snapshot["truth_sources"]["sources"]["TS-STATUS"]["observation"].update({"actor": "other"}),
                ),
                "TRUTH_SOURCE_OWNER_MISMATCH",
            ),
            (
                "generation-after-digests-and-owner",
                lambda snapshot: snapshot["truth_sources"]["sources"]["TS-STATUS"].update({"observed_generation": 2}),
                "TRUTH_SOURCE_GENERATION_MISMATCH",
            ),
        )
        for name, mutate, expected_code in cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(observed_snapshot))
                mutate(snapshot)
                resolver = Mock(side_effect=AssertionError("control precedence must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                assert evaluation is not None
                self.assertEqual(evaluation["results"][0]["codes"], [expected_code])
                self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
                resolver.assert_not_called()

        context.mark_truth_sources_dirty(
            "TSC-03", change_kind="implementation-change", actor="executor-01",
            reason="authoritative implementation changed", base_dir=self.base,
        )
        dirty_snapshot = self.current_snapshot()
        dirty_snapshot["contract"]["integrity_digest"] = contract_mismatch
        resolver = Mock(side_effect=AssertionError("global contract mismatch must not resolve"))
        evaluation = self.evaluate(dirty_snapshot, resolver)
        assert evaluation is not None
        self.assertEqual(evaluation["results"][0]["codes"], ["TRUTH_SOURCE_CONTRACT_MISMATCH"])
        self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
        resolver.assert_not_called()

    def test_incomplete_schema_and_snapshot_envelope_are_unknown_without_resolution(self) -> None:
        contract_cases = (
            ("capability-only", lambda contract: contract.pop("truth_sources")),
            ("truth-only", lambda contract: contract.pop("required_capabilities")),
            ("schema", lambda contract: contract["truth_sources"].update({"schema": "wrong/v1"})),
            ("validation-method", lambda contract: contract["truth_sources"]["items"][0].update({"validation_method": "forged"})),
            ("change-kinds", lambda contract: contract["truth_sources"]["items"][0].update({"invalidate_on_change_kinds": []})),
            ("unknown-field", lambda contract: contract["truth_sources"]["items"][0].update({"extra": True})),
            ("bad-owner", lambda contract: contract["truth_sources"]["items"][0].update({"owner": ""})),
            ("bad-source-ref", lambda contract: contract["truth_sources"]["items"][0].update({"source_ref": {"kind": "file", "locator": "../escape"}})),
            ("bad-age", lambda contract: contract["truth_sources"]["items"][0].update({"max_age_seconds": False})),
        )
        for name, mutate in contract_cases:
            with self.subTest(name=name):
                contract = json.loads(json.dumps(self.current_contract()))
                mutate(contract)
                resolver = Mock(side_effect=AssertionError("incomplete declaration must not resolve"))
                evaluation = truth_sources.evaluate_truth_sources(
                    contract, self.current_snapshot(), now=self.now, resolver=resolver,
                )
                self.assertEqual(evaluation, {
                    "status": "unknown", "passed": False, "results": [],
                    "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0},
                })
                resolver.assert_not_called()

        legacy = self.current_contract()
        legacy.pop("truth_sources")
        legacy.pop("required_capabilities")
        self.assertIsNone(truth_sources.evaluate_truth_sources(
            legacy, self.current_snapshot(), now=self.now, resolver=Mock(),
        ))

        snapshot_cases = (
            ("generation-missing", lambda snapshot: snapshot["truth_sources"].pop("generation")),
            ("generation-zero", lambda snapshot: snapshot["truth_sources"].update({"generation": 0})),
            ("generation-bool", lambda snapshot: snapshot["truth_sources"].update({"generation": True})),
            ("source-missing", lambda snapshot: snapshot["truth_sources"]["sources"].pop("TS-STATUS")),
            ("source-extra", lambda snapshot: snapshot["truth_sources"]["sources"].update({"EXTRA": {}})),
        )
        for name, mutate in snapshot_cases:
            with self.subTest(name=name):
                snapshot = json.loads(json.dumps(self.current_snapshot()))
                mutate(snapshot)
                resolver = Mock(side_effect=AssertionError("bad projection must not resolve"))
                evaluation = self.evaluate(snapshot, resolver)
                self.assertEqual(evaluation, {
                    "status": "unknown", "passed": False, "results": [],
                    "stats": {"truth_sources_checked": 0, "truth_source_resolution_attempts": 0},
                })
                resolver.assert_not_called()

    def test_public_dirty_sequence_projects_canonical_dirty_control(self) -> None:
        result = context.mark_truth_sources_dirty(
            "TSC-03", change_kind="implementation-change", actor="executor-01",
            reason="authoritative implementation changed", base_dir=self.base,
        )
        snapshot = self.current_snapshot()
        state = snapshot["truth_sources"]["sources"]["TS-STATUS"]
        self.assertEqual(state, {
            "required_generation": result["generation"], "observed_generation": None,
            "observation": None, "status": "dirty",
        })
        resolver = Mock(side_effect=AssertionError("canonical dirty must not resolve"))
        evaluation = self.evaluate(snapshot, resolver)
        assert evaluation is not None
        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["results"][0]["codes"], ["TRUTH_SOURCE_DIRTY"])
        self.assertEqual(evaluation["stats"]["truth_source_resolution_attempts"], 0)
        resolver.assert_not_called()


class TruthSourceBriefTests(_TruthSourceContractFixture):
    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.workspace.resolve()
        documents = self.workspace / "docs"
        documents.mkdir()
        self.status = documents / "TS-STATUS.md"
        self.status.write_text("brief baseline\n", encoding="utf-8")
        self.publish()
        self.task_id = "TSC-03"
        context.observe_truth_source(
            self.task_id, source_id="TS-STATUS", actor="publisher",
            verification_refs=["review:brief"], base_dir=self.base,
        )

    def test_brief_uses_live_evaluator_not_cached_pass_and_resolves_once(self) -> None:
        self.status.write_text("brief changed without dirty mark\n", encoding="utf-8")
        with patch.object(context, "resolve_file_source", wraps=truth_sources.resolve_file_source) as resolver:
            packet = context.brief(self.task_id, base_dir=self.base)
        self.assertEqual(packet["truth_sources"]["items"][0]["status"], "fail")
        self.assertEqual(resolver.call_count, 1)
        with patch.object(context, "resolve_file_source", wraps=truth_sources.resolve_file_source) as resolver:
            diagnostics = context.brief_diagnostics(self.task_id, base_dir=self.base)
        self.assertTrue(diagnostics["fits"])
        self.assertEqual(resolver.call_count, 1)

    def test_truth_brief_allowlist_mandatory_overflow_and_fixed_budget(self) -> None:
        packet = context.brief(self.task_id, max_items=1, base_dir=self.base)
        item = packet["truth_sources"]["items"][0]
        self.assertEqual(set(item), {
            "id", "purpose", "source_ref", "owner", "status", "required_generation",
            "observed_generation", "observed_at", "fingerprint",
        })
        self.assertNotIn("codes", item)
        self.assertNotIn("verification_refs", item)
        diagnostics = context.brief_diagnostics(self.task_id, max_items=1, max_chars=1, base_dir=self.base)
        self.assertEqual(diagnostics["overflow"]["code"], "BRIEF_REQUIRED_OVERFLOW")
        self.assertGreater(diagnostics["budget"]["fixed_prompt_chars"], 0)

    def test_truth_block_never_contains_file_canary_or_verification_refs(self) -> None:
        canary = "TRUTH_SOURCE_BRIEF_FILE_CANARY_DO_NOT_LEAK"
        self.status.write_text(canary, encoding="utf-8")
        packet = context.brief(self.task_id, base_dir=self.base)
        diagnostics = context.brief_diagnostics(self.task_id, base_dir=self.base)
        self.assertNotIn(canary, repr(packet))
        self.assertNotIn(canary, repr(diagnostics))
        self.assertNotIn("review:brief", repr(packet))
        self.assertNotIn("review:brief", repr(diagnostics))

    def test_precomputed_evaluation_reuses_no_resolution_and_legacy_stays_exact(self) -> None:
        paths = context._paths(self.task_id, self.base)
        with context._shared_locked_existing(paths["root"]):
            view = context._load_committed_task_view_locked(self.task_id, paths)
            evaluation = truth_sources.evaluate_truth_sources(
                view["contract"], view["snapshot"], now=datetime.now(timezone.utc),
                resolver=truth_sources.resolve_file_source,
            )
            with patch.object(context, "resolve_file_source", side_effect=AssertionError("must reuse evaluation")):
                plan = context._plan_brief_from_view(
                    self.task_id, contract=view["contract"], snapshot=view["snapshot"],
                    truth_evaluation=evaluation, phase="handoff", include=None, max_items=None, max_chars=8000,
                )
        self.assertIn("truth_sources", plan["packet"])
        legacy_base = Path(self.temp.name) / "legacy" / ".prime" / "context"
        context.publish_contract(LEGACY_CONTRACT, confirmed_by="publisher", base_dir=legacy_base)
        with patch.object(context, "evaluate_truth_sources", side_effect=AssertionError("legacy evaluator")):
            legacy_packet = context.brief("LEGACY-GOLDEN", base_dir=legacy_base)
            legacy_diagnostics = context.brief_diagnostics("LEGACY-GOLDEN", base_dir=legacy_base)
        self.assertNotIn("truth_sources", legacy_packet)
        self.assertNotIn("truth_sources", legacy_diagnostics)


class TruthSourceGateTests(_TruthSourceContractFixture):
    """Four gates must consume the committed truth-source projection."""

    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.workspace.resolve()
        documents = self.workspace / "docs"
        documents.mkdir()
        self.status = documents / "TS-STATUS.md"
        self.status.write_text("gate baseline\n", encoding="utf-8")
        self.publish()
        self.task_id = "TSC-03"

    def _observe(self) -> None:
        context.observe_truth_source(
            self.task_id,
            source_id="TS-STATUS",
            actor="publisher",
            verification_refs=["review:gate-baseline"],
            base_dir=self.base,
        )

    def _prepare_passing_completion(self) -> None:
        contract = self.contract(2)
        contract["acceptance_criteria"] = [{
            "id": "AC-01", "criterion": "Tail validation requires one callback",
            "required_evidence_types": ["custom"],
        }]
        context.publish_contract(contract, confirmed_by="publisher", base_dir=self.base)
        self._observe()

    @staticmethod
    def _passing_resolver(evidence, criterion, contract, now):
        return {
            "resolve": {"status": "pass", "codes": []},
            "integrity_and_freshness": {"status": "pass", "codes": []},
            "scope": {"status": "pass", "codes": []},
            "claim": {"status": "pass", "codes": []},
        }

    def _passing_evidence_map(self) -> dict[str, object]:
        return {"AC-01": {"evidence": [{"evidence_id": "EV-GATE", "kind": "custom"}]}}

    def _invalid_state(self, state: str) -> str:
        if state == "unobserved":
            return "TRUTH_SOURCE_UNOBSERVED"
        self._observe()
        if state == "dirty":
            context.mark_truth_sources_dirty(
                self.task_id,
                change_kind="implementation-change",
                actor="executor-01",
                reason="gate test dirty state",
                base_dir=self.base,
            )
            return "TRUTH_SOURCE_DIRTY"
        if state == "changed":
            self.status.write_text("gate source changed\n", encoding="utf-8")
            return "TRUTH_SOURCE_CHANGED"
        if state == "missing":
            self.status.unlink()
            return "TRUTH_SOURCE_NOT_FOUND"
        raise AssertionError(f"unknown test state: {state}")

    def test_all_four_stages_fail_closed_for_every_invalid_truth_state(self) -> None:
        for state in ("unobserved", "dirty", "stale", "changed", "missing", "permission", "malformed"):
            for stage in ("release", "resume", "handoff", "completion"):
                with self.subTest(state=state, stage=stage):
                    self.temp.cleanup()
                    self.setUp()
                    if state == "stale":
                        self._observe()
                        observed_at = context._read_json(context._paths(self.task_id, self.base)["snapshot"])["truth_sources"]["sources"]["TS-STATUS"]["observation"]["observed_at"]
                        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                        expected = "TRUTH_SOURCE_STALE"
                        with patch.object(context, "_trusted_utc_now", return_value=observed + timedelta(seconds=61)):
                            report = context.gate(self.task_id, stage=stage, evidence_map={} if stage == "completion" else None, base_dir=self.base, emit=False)
                    elif state == "permission":
                        self._observe()
                        expected = "TRUTH_SOURCE_PERMISSION_DENIED"
                        with patch.object(context, "resolve_file_source", return_value={
                            "status": "unknown", "code": expected, "fingerprint": None,
                        }):
                            report = context.gate(self.task_id, stage=stage, evidence_map={} if stage == "completion" else None, base_dir=self.base, emit=False)
                    elif state == "malformed":
                        self._observe()
                        expected = "TRUTH_SOURCE_RESOLVER_UNKNOWN"
                        with context._locked(context._paths(self.task_id, self.base)["root"]):
                            with context._paths(self.task_id, self.base)["events"].open("ab") as handle:
                                handle.write(b"{malformed-event\n")
                        report = context.gate(self.task_id, stage=stage, evidence_map={} if stage == "completion" else None, base_dir=self.base, emit=False)
                    else:
                        expected = self._invalid_state(state)
                        report = context.gate(
                            self.task_id, stage=stage,
                            evidence_map={} if stage == "completion" else None,
                            base_dir=self.base, emit=False,
                        )
                    self.assertFalse(report["passed"])
                    self.assertIn("truth_source_results", report)
                    results = report["truth_source_results"]
                    self.assertTrue(any(expected in item["codes"] for item in results))

    def test_completion_entry_invalid_calls_zero_evidence_resolvers_and_verifiers(self) -> None:
        calls: list[str] = []

        def resolver(*args):
            calls.append("resolver")
            return self._passing_resolver(*args)

        def verifier(*args):
            calls.append("verifier")
            return {"status": "pass", "codes": []}

        report = context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": resolver}, verifiers={"custom": verifier},
            base_dir=self.base, emit=False,
        )
        self.assertFalse(report["passed"])
        self.assertEqual(calls, [])
        self.assertEqual(report["stats"]["criteria_checked"], 0)
        self.assertEqual(report["stats"]["evidence_attempts"], 0)
        self.assertIn("TRUTH_SOURCE_UNOBSERVED", report["truth_source_results"][0]["codes"])

    def test_completion_tail_detects_mark_during_evidence_callback(self) -> None:
        self._prepare_passing_completion()
        callback_entered = threading.Event()
        allow_callback_return = threading.Event()

        def blocking_resolver(evidence, criterion, contract, now):
            callback_entered.set()
            self.assertTrue(allow_callback_return.wait(2))
            return self._passing_resolver(evidence, criterion, contract, now)

        result: dict[str, object] = {}
        thread = threading.Thread(target=lambda: result.update(context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": blocking_resolver},
            verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
            base_dir=self.base, emit=False,
        )))
        thread.start()
        self.assertTrue(callback_entered.wait(2))
        context.mark_truth_sources_dirty(
            self.task_id, change_kind="implementation-change", actor="executor-01",
            reason="changed during completion", base_dir=self.base,
        )
        allow_callback_return.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["passed"])
        self.assertEqual(result["stats"]["truth_source_resolution_attempts"], 1)
        self.assertIn("TRUTH_SOURCE_DIRTY", result["truth_source_results"][0]["codes"])

    def test_completion_tail_detects_contract_update_during_callback(self) -> None:
        self._prepare_passing_completion()
        callback_entered = threading.Event()
        allow_callback_return = threading.Event()

        def blocking_resolver(evidence, criterion, contract, now):
            callback_entered.set()
            self.assertTrue(allow_callback_return.wait(2))
            return self._passing_resolver(evidence, criterion, contract, now)

        result: dict[str, object] = {}
        thread = threading.Thread(target=lambda: result.update(context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": blocking_resolver},
            verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
            base_dir=self.base, emit=False,
        )))
        thread.start()
        self.assertTrue(callback_entered.wait(2))
        next_contract = self.contract(3)
        next_contract["acceptance_criteria"] = [{
            "id": "AC-01", "criterion": "Updated contract", "required_evidence_types": ["custom"],
        }]
        context.publish_contract(next_contract, confirmed_by="publisher", base_dir=self.base)
        allow_callback_return.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["passed"])
        self.assertIn("truth source control changed during completion", result["errors"])

    def test_completion_tail_detects_file_change_during_callback(self) -> None:
        self._prepare_passing_completion()
        callback_entered = threading.Event()
        allow_callback_return = threading.Event()

        def blocking_resolver(evidence, criterion, contract, now):
            callback_entered.set()
            self.assertTrue(allow_callback_return.wait(2))
            return self._passing_resolver(evidence, criterion, contract, now)

        result: dict[str, object] = {}
        thread = threading.Thread(target=lambda: result.update(context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": blocking_resolver},
            verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
            base_dir=self.base, emit=False,
        )))
        thread.start()
        self.assertTrue(callback_entered.wait(2))
        self.status.write_text("tail changed source\n", encoding="utf-8")
        allow_callback_return.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["passed"])
        self.assertIn("TRUTH_SOURCE_CHANGED", result["truth_source_results"][0]["codes"])

    def test_completion_tail_uses_new_clock_and_detects_freshness_expiry(self) -> None:
        self._prepare_passing_completion()
        observed_at = context._read_json(context._paths(self.task_id, self.base)["snapshot"])["truth_sources"]["sources"]["TS-STATUS"]["observation"]["observed_at"]
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        with patch.object(context, "_trusted_utc_now", side_effect=[
            observed + timedelta(seconds=1), observed + timedelta(seconds=61),
        ]) as clock:
            report = context.gate(
                self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
                resolvers={"custom": self._passing_resolver},
                verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
                base_dir=self.base, emit=False,
            )
        self.assertFalse(report["passed"])
        self.assertEqual(clock.call_count, 2)
        self.assertIn("TRUTH_SOURCE_STALE", report["truth_source_results"][0]["codes"])

    def _assert_child_sees_shared_lock(self, gate_thread: threading.Thread) -> None:
        queue = multiprocessing.Queue()
        child = multiprocessing.Process(
            target=_exclusive_lock_probe,
            args=(str(context._paths(self.task_id, self.base)["lock"]), queue),
        )
        child.start()
        child.join(2)
        self.assertFalse(child.is_alive())
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(queue.get(timeout=2), "blocked")
        self.assertTrue(gate_thread.is_alive())

    def test_release_resume_handoff_hold_shared_lock_until_verdict_is_fixed(self) -> None:
        for stage in ("release", "resume", "handoff"):
            with self.subTest(stage=stage):
                self.temp.cleanup()
                self.setUp()
                self._observe()
                resolver_entered = threading.Event()
                allow_resolver_return = threading.Event()

                def blocking_resolver(*args):
                    resolver_entered.set()
                    self.assertTrue(allow_resolver_return.wait(2))
                    return truth_sources.resolve_file_source(*args)

                result: dict[str, object] = {}
                with patch.object(context, "resolve_file_source", side_effect=blocking_resolver):
                    thread = threading.Thread(target=lambda: result.update(context.gate(
                        self.task_id, stage=stage, base_dir=self.base, emit=False,
                    )))
                    thread.start()
                    self.assertTrue(resolver_entered.wait(2))
                    self._assert_child_sees_shared_lock(thread)
                    allow_resolver_return.set()
                    thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertIn("truth_source_results", result)

    def test_mark_cannot_enter_tail_control_file_verdict_critical_section(self) -> None:
        self._prepare_passing_completion()
        tail_entered = threading.Event()
        allow_tail_return = threading.Event()
        resolver_calls = 0

        def tail_blocking_resolver(*args):
            nonlocal resolver_calls
            resolver_calls += 1
            if resolver_calls == 2:
                tail_entered.set()
                self.assertTrue(allow_tail_return.wait(2))
            return truth_sources.resolve_file_source(*args)

        writer_attempting = threading.Event()
        writer_finished = threading.Event()

        def writer() -> None:
            writer_attempting.set()
            context.mark_truth_sources_dirty(
                self.task_id, change_kind="implementation-change", actor="executor-01",
                reason="writer waits for tail verdict", base_dir=self.base,
            )
            writer_finished.set()

        result: dict[str, object] = {}
        with patch.object(context, "resolve_file_source", side_effect=tail_blocking_resolver):
            gate_thread = threading.Thread(target=lambda: result.update(context.gate(
                self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
                resolvers={"custom": self._passing_resolver},
                verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
                base_dir=self.base, emit=False,
            )))
            gate_thread.start()
            self.assertTrue(tail_entered.wait(2))
            self._assert_child_sees_shared_lock(gate_thread)
            writer_thread = threading.Thread(target=writer)
            writer_thread.start()
            self.assertTrue(writer_attempting.wait(2))
            self.assertFalse(writer_finished.is_set())
            allow_tail_return.set()
            gate_thread.join(2)
            writer_thread.join(2)
        self.assertFalse(gate_thread.is_alive())
        self.assertFalse(writer_thread.is_alive())
        self.assertTrue(writer_finished.is_set())
        self.assertTrue(result["passed"])

    def test_truth_enabled_read_apis_preserve_tree_bytes_and_reject_every_write_primitive(self) -> None:
        self._observe()
        task_root = context._paths(self.task_id, self.base)["root"]

        def tree_map() -> dict[str, tuple[str, bytes | None]]:
            return {
                str(path.relative_to(task_root)): (
                    "file", path.read_bytes()) if path.is_file() else ("directory", None)
                for path in sorted(task_root.rglob("*"))
            }

        before = tree_map()
        original_open = builtins.open
        original_path_open = Path.open
        original_os_open = os.open
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

        def guarded_open(*args, **kwargs):
            mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
            if any(flag in mode for flag in "wax+"):
                raise AssertionError("builtins.open write")
            return original_open(*args, **kwargs)

        def guarded_path_open(path, *args, **kwargs):
            mode = kwargs.get("mode", args[0] if args else "r")
            if any(flag in mode for flag in "wax+"):
                raise AssertionError("Path.open write")
            return original_path_open(path, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & write_flags:
                raise AssertionError("os.open write")
            return original_os_open(path, flags, *args, **kwargs)

        with patch("builtins.open", side_effect=guarded_open), \
             patch.object(Path, "open", new=guarded_path_open), \
             patch.object(os, "open", side_effect=guarded_os_open), \
             patch.object(context, "_append_event_locked", side_effect=AssertionError("event write")), \
             patch.object(context, "_atomic_write_json", side_effect=AssertionError("json write")), \
             patch.object(context.os, "replace", side_effect=AssertionError("replace")), \
             patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temporary directory")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("Path.mkdir")), \
             patch.object(os, "mkdir", side_effect=AssertionError("os.mkdir")), \
             patch.object(os, "makedirs", side_effect=AssertionError("os.makedirs")):
            context.audit(self.task_id, base_dir=self.base, emit=False)
            context.brief(self.task_id, base_dir=self.base)
            context.brief_diagnostics(self.task_id, base_dir=self.base)
            for stage in ("release", "resume", "handoff", "completion"):
                context.gate(
                    self.task_id, stage=stage, evidence_map={} if stage == "completion" else None,
                    base_dir=self.base, emit=False,
                )
        self.assertEqual(tree_map(), before)

    def test_legacy_gate_has_zero_truth_io_and_unchanged_shape(self) -> None:
        legacy_base = Path(self.temp.name) / "legacy" / ".prime" / "context"
        context.publish_contract(LEGACY_CONTRACT, confirmed_by="publisher", base_dir=legacy_base)
        with patch.object(context, "evaluate_truth_sources", side_effect=AssertionError("legacy evaluator")), \
             patch.object(context, "resolve_file_source", side_effect=AssertionError("legacy resolver")):
            for stage in ("release", "resume", "handoff", "completion"):
                report = context.gate(
                    "LEGACY-GOLDEN", stage=stage,
                    evidence_map={} if stage == "completion" else None,
                    base_dir=legacy_base, emit=False,
                )
                self.assertNotIn("truth_source_results", report)
                self.assertNotIn("truth_sources_checked", report["stats"])
                self.assertNotIn("truth_source_resolution_attempts", report["stats"])

    def test_truth_audit_and_release_retain_missing_file_reference_checks(self) -> None:
        self._observe()
        context.record(
            self.task_id, statement="missing source pointer", item_type="observation", actor="publisher",
            source={"kind": "file", "ref": "file:does-not-exist.txt"},
            evidence=["file:also-does-not-exist.txt"], base_dir=self.base,
        )
        for report in (
            context.audit(self.task_id, base_dir=self.base, emit=False),
            context.gate(self.task_id, stage="release", base_dir=self.base, emit=False),
        ):
            self.assertFalse(report["passed"])
            self.assertTrue(any("missing file reference file:does-not-exist.txt" in error for error in report["errors"]))
            self.assertTrue(any("missing file reference file:also-does-not-exist.txt" in error for error in report["errors"]))

    def test_truth_completion_preserves_detailed_criterion_errors(self) -> None:
        self._prepare_passing_completion()
        failing = {
            "status": "fail", "evidence_results": [{"evidence_id": "EV-FAIL", "status": "fail"}],
            "missing_evidence_types": ["custom"], "missing_hops": ["build"],
            "missing_delivery_types": ["receipt"],
            "independent_validation": {"status": "unknown", "codes": ["MISSING_VALIDATED_AT"]},
        }
        with patch.object(context, "_evaluate_completion_criterion", return_value=failing):
            report = context.gate(
                self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
                base_dir=self.base, emit=False,
            )
        self.assertFalse(report["passed"])
        self.assertIn("criterion AC-01 status is fail", report["errors"])
        self.assertIn("criterion AC-01 evidence EV-FAIL is fail", report["errors"])
        self.assertIn("criterion AC-01 missing required evidence types: ['custom']", report["errors"])
        self.assertIn("criterion AC-01 missing chain-hop coverage: ['build']", report["errors"])
        self.assertIn("criterion AC-01 missing required delivery types: ['receipt']", report["errors"])
        self.assertIn("criterion AC-01 independent validation is unknown: ['MISSING_VALIDATED_AT']", report["errors"])

    def test_release_verdict_is_fixed_before_writer_can_finish(self) -> None:
        self._observe()
        entered = threading.Event()
        allow_return = threading.Event()
        writer_finished = threading.Event()
        original = context._truth_gate_base_checks

        def blocking_checks(*args):
            entered.set()
            self.assertTrue(allow_return.wait(2))
            return original(*args)

        def writer() -> None:
            context.mark_truth_sources_dirty(
                self.task_id, change_kind="implementation-change", actor="executor-01",
                reason="must wait for verdict", base_dir=self.base,
            )
            writer_finished.set()

        result: dict[str, object] = {}
        with patch.object(context, "_truth_gate_base_checks", side_effect=blocking_checks):
            thread = threading.Thread(target=lambda: result.update(context.gate(
                self.task_id, stage="release", base_dir=self.base, emit=False,
            )))
            thread.start()
            self.assertTrue(entered.wait(2))
            writer_thread = threading.Thread(target=writer)
            writer_thread.start()
            self.assertFalse(writer_finished.is_set())
            allow_return.set()
            thread.join(2)
            writer_thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result["passed"])
        self.assertTrue(writer_finished.is_set())

    def test_completion_tail_capability_removal_returns_truth_shaped_failure(self) -> None:
        self._prepare_passing_completion()
        entered = threading.Event()
        allow_return = threading.Event()
        resolver_calls = 0

        def blocking_resolver(evidence, criterion, contract, now):
            nonlocal resolver_calls
            resolver_calls += 1
            entered.set()
            self.assertTrue(allow_return.wait(2))
            return self._passing_resolver(evidence, criterion, contract, now)

        result: dict[str, object] = {}
        thread = threading.Thread(target=lambda: result.update(context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": blocking_resolver},
            verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
            base_dir=self.base, emit=False,
        )))
        thread.start()
        self.assertTrue(entered.wait(2))
        legacy = self.legacy_contract(3)
        legacy["acceptance_criteria"] = [{"id": "AC-01", "criterion": "legacy", "required_evidence_types": ["custom"]}]
        context.publish_contract(legacy, confirmed_by="publisher", base_dir=self.base)
        allow_return.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_version"], 2)
        self.assertIn("truth_source_results", result)
        self.assertEqual(resolver_calls, 1)
        self.assertIn("truth_source_resolution_attempts", result["stats"])
        self.assertEqual(result["stats"]["truth_source_resolution_attempts"], 1)
        self.assertEqual(result["stats"]["truth_sources_checked"], 1)

    def test_completion_tail_malformed_event_reports_only_entry_resolution_attempt(self) -> None:
        self._prepare_passing_completion()
        entered = threading.Event()
        allow_return = threading.Event()
        resolver_calls = 0

        def blocking_resolver(evidence, criterion, contract, now):
            nonlocal resolver_calls
            resolver_calls += 1
            entered.set()
            self.assertTrue(allow_return.wait(2))
            return self._passing_resolver(evidence, criterion, contract, now)

        result: dict[str, object] = {}
        thread = threading.Thread(target=lambda: result.update(context.gate(
            self.task_id, stage="completion", evidence_map=self._passing_evidence_map(),
            resolvers={"custom": blocking_resolver},
            verifiers={"custom": lambda *args: {"status": "pass", "codes": []}},
            base_dir=self.base, emit=False,
        )))
        thread.start()
        self.assertTrue(entered.wait(2))
        paths = context._paths(self.task_id, self.base)
        with context._locked(paths["root"]):
            with paths["events"].open("ab") as handle:
                handle.write(b"{malformed-tail\n")
        allow_return.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_version"], 2)
        self.assertIn("truth_source_results", result)
        self.assertEqual(resolver_calls, 1)
        self.assertEqual(result["stats"]["truth_source_resolution_attempts"], 1)
        self.assertEqual(result["stats"]["truth_sources_checked"], 1)

    def test_gate_route_is_linearized_for_legacy_to_truth_and_truth_to_legacy(self) -> None:
        for direction in ("legacy-to-truth", "truth-to-legacy"):
            with self.subTest(direction=direction):
                self.temp.cleanup()
                self.setUp()
                if direction == "legacy-to-truth":
                    context.publish_contract(self.legacy_contract(2), confirmed_by="publisher", base_dir=self.base)
                    replacement = self.contract(3)
                    expects_truth = False
                    expected_version = 2
                else:
                    context.publish_contract(self.contract(2), confirmed_by="publisher", base_dir=self.base)
                    self._observe()
                    replacement = self.legacy_contract(3)
                    expects_truth = True
                    expected_version = 2
                load_entered = threading.Event()
                allow_load = threading.Event()
                writer_attempting = threading.Event()
                writer_finished = threading.Event()
                original_load = context._load_committed_task_view_locked

                def blocking_load(*args):
                    load_entered.set()
                    self.assertTrue(allow_load.wait(2))
                    return original_load(*args)

                def writer() -> None:
                    writer_attempting.set()
                    context.publish_contract(replacement, confirmed_by="publisher", base_dir=self.base)
                    writer_finished.set()

                result: dict[str, object] = {}
                with patch.object(context, "_load_committed_task_view_locked", side_effect=blocking_load):
                    gate_thread = threading.Thread(target=lambda: result.update(context.gate(
                        self.task_id, stage="release", base_dir=self.base, emit=False,
                    )))
                    gate_thread.start()
                    self.assertTrue(load_entered.wait(2))
                    writer_thread = threading.Thread(target=writer)
                    writer_thread.start()
                    self.assertTrue(writer_attempting.wait(2))
                    self._assert_child_sees_shared_lock(gate_thread)
                    self.assertFalse(writer_finished.is_set())
                    allow_load.set()
                    gate_thread.join(2)
                    writer_thread.join(2)
                self.assertFalse(gate_thread.is_alive())
                self.assertFalse(writer_thread.is_alive())
                self.assertTrue(writer_finished.is_set())
                self.assertEqual(result["contract_version"], expected_version)
                self.assertEqual("truth_source_results" in result, expects_truth)
                self.assertTrue(result["passed"])

    def test_truth_final_construction_holds_lock_for_all_stages(self) -> None:
        for stage in ("release", "resume", "handoff", "completion"):
            with self.subTest(stage=stage):
                self.temp.cleanup()
                self.setUp()
                if stage == "completion":
                    self._prepare_passing_completion()
                    gate_kwargs = {
                        "evidence_map": self._passing_evidence_map(),
                        "resolvers": {"custom": self._passing_resolver},
                        "verifiers": {"custom": lambda *args: {"status": "pass", "codes": []}},
                    }
                else:
                    self._observe()
                    gate_kwargs = {}
                    if stage == "handoff":
                        context.checkpoint(self.task_id, phase="handoff", completed=[], evidence_added=[], next_action="continue", actor="publisher", base_dir=self.base)
                entered = threading.Event()
                allow_final = threading.Event()
                writer_attempting = threading.Event()
                writer_finished = threading.Event()
                original_final = context._truth_gate_final

                def blocking_final(*args, **kwargs):
                    entered.set()
                    self.assertTrue(allow_final.wait(2))
                    return original_final(*args, **kwargs)

                def writer() -> None:
                    writer_attempting.set()
                    context.mark_truth_sources_dirty(self.task_id, change_kind="implementation-change", actor="executor-01", reason="final lock probe", base_dir=self.base)
                    writer_finished.set()

                result: dict[str, object] = {}
                with patch.object(context, "_truth_gate_final", side_effect=blocking_final):
                    gate_thread = threading.Thread(target=lambda: result.update(context.gate(
                        self.task_id, stage=stage, base_dir=self.base, emit=False, **gate_kwargs,
                    )))
                    gate_thread.start()
                    self.assertTrue(entered.wait(2))
                    writer_thread = threading.Thread(target=writer)
                    writer_thread.start()
                    self.assertTrue(writer_attempting.wait(2))
                    self._assert_child_sees_shared_lock(gate_thread)
                    self.assertFalse(writer_finished.is_set())
                    allow_final.set()
                    gate_thread.join(2)
                    writer_thread.join(2)
                self.assertFalse(gate_thread.is_alive())
                self.assertFalse(writer_thread.is_alive())
                self.assertTrue(writer_finished.is_set())
                self.assertTrue(result["passed"])

    def test_filtered_mandatory_warning_matches_truth_and_legacy_release(self) -> None:
        expected = "brief preflight filtered mandatory items: ['REQ']"
        diagnostics = {"status": "ready", "overflow": None, "items": {"filtered_mandatory_ids": ["REQ"]}, "budget": {}}
        for declared in (True, False):
            with self.subTest(declared=declared):
                self.temp.cleanup()
                self.setUp()
                if declared:
                    self._observe()
                else:
                    context.publish_contract(self.legacy_contract(2), confirmed_by="publisher", base_dir=self.base)
                with patch.object(context, "_brief_diagnostics_from_plan", return_value=diagnostics):
                    report = context.gate(self.task_id, stage="release", base_dir=self.base, emit=False)
                self.assertIn(expected, report["warnings"])


if __name__ == "__main__":
    unittest.main()
