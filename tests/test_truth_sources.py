from __future__ import annotations

import hashlib
import json
import errno
import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


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
                "contract_digest": digest, "generation": 1, "change_kind": "implementation-change",
                "reason": "changed", "source_ids": ["TS-A"],
            }),
            context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
                "contract_digest": digest, "generation": 2, "change_kind": "implementation-change",
                "reason": "changed again", "source_ids": ["TS-A"],
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
            "change_kind": "implementation-change", "reason": "bad", "source_ids": ["MISSING"],
        })
        with self.assertRaisesRegex(context.ContextError, "truth-source-dirtied"):
            context._rebuild_snapshot("TSC-03", [*self.events(), event])

    def test_poisoned_event_cannot_be_healed_by_later_observation(self) -> None:
        self.publish()
        events = self.events()
        digest = events[0]["payload"]["integrity_digest"]
        events.append(context._new_event("TSC-03", "truth-source-dirtied", "publisher", {
            "contract_digest": digest, "generation": 4, "change_kind": "implementation-change",
            "reason": "poison", "source_ids": ["TS-STATUS"],
        }))
        events.append(context._new_event("TSC-03", "truth-source-observed", "publisher", {
            "contract_digest": digest, "generation": 1, "source_id": "TS-STATUS",
            "fingerprint": "sha256:" + "1" * 64, "verification_refs": ["review:1"],
            "observed_at": "2026-08-31T03:00:00+00:00",
        }))
        with self.assertRaisesRegex(context.ContextError, "generation"):
            context._rebuild_snapshot("TSC-03", events)


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


if __name__ == "__main__":
    unittest.main()
