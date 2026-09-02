from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from managing_long_task_context.evidence import (  # noqa: E402
    canonical_json_bytes,
    default_resolvers,
    evaluate_evidence,
)


NOW = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)


def passing_resolver(evidence, criterion, contract, now):
    return {
        "resolve": {"status": "pass", "codes": []},
        "integrity_and_freshness": {"status": "pass", "codes": []},
        "scope": {"status": "pass", "codes": []},
        "claim": {"status": "pass", "codes": []},
    }


def passing_verifier(evidence, criterion, resolution):
    return {"status": "pass", "codes": []}


class EvidenceEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.contract = {
            "workspace_root": str(self.root),
            "evidence_roots": [],
        }
        self.criterion = {
            "required_scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            "max_evidence_age_seconds": 3600,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_resolver_cannot_forge_claim_and_verifier_is_independent(self) -> None:
        evidence = {"evidence_id": "EV-1", "kind": "file"}

        unresolved_claim = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            resolvers={"file": passing_resolver},
            now=NOW,
        )
        self.assertEqual(unresolved_claim["status"], "unknown")
        self.assertEqual(
            unresolved_claim["checks"],
            {
                "resolve": {"status": "pass", "codes": []},
                "integrity_and_freshness": {"status": "pass", "codes": []},
                "scope": {"status": "pass", "codes": []},
                "claim": {"status": "unknown", "codes": ["CLAIM_NOT_VERIFIED"]},
            },
        )

        verified = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            resolvers={"file": passing_resolver},
            verifiers={"file": passing_verifier},
            now=NOW,
        )
        self.assertEqual(verified["status"], "pass")
        self.assertEqual(
            verified["checks"],
            {
                "resolve": {"status": "pass", "codes": []},
                "integrity_and_freshness": {"status": "pass", "codes": []},
                "scope": {"status": "pass", "codes": []},
                "claim": {"status": "pass", "codes": []},
            },
        )

    def test_capability_wrapped_handlers_execute_real_resolution_and_verification(self) -> None:
        evidence = {"evidence_id": "EV-CUSTOM", "kind": "custom"}

        result = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            resolvers={
                "custom": {
                    "capability": "project:custom-resolver/v1",
                    "handler": passing_resolver,
                }
            },
            verifiers={
                "custom": {
                    "capability": "project:custom-verifier/v1",
                    "handler": passing_verifier,
                }
            },
            now=NOW,
        )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(value["status"] == "pass" for value in result["checks"].values()))

    def test_file_resolver_accepts_literal_digest_and_required_scope_subset(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
            scope={"task_id": "TASK-1", "criterion_id": "AC-1", "run": "18"},
        )

        result = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            verifiers={"file": passing_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(check["status"] == "pass" for check in result["checks"].values()))

    def test_missing_file_fails_not_found(self) -> None:
        evidence = self._file_evidence(locator="missing.txt")

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["resolve"], {"status": "fail", "codes": ["NOT_FOUND"]})

    def test_symlink_escape_fails_outside_allowed_root(self) -> None:
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (self.root / "escape.txt").symlink_to(outside)
        evidence = self._file_evidence(locator="escape.txt")

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["resolve"],
            {"status": "fail", "codes": ["OUTSIDE_ALLOWED_ROOT"]},
        )

    def test_evidence_root_allows_a_realpath_outside_workspace(self) -> None:
        evidence_root = Path(self.temp.name) / "evidence"
        evidence_root.mkdir()
        artifact = evidence_root / "external.txt"
        artifact.write_bytes(b"external")
        self.contract["evidence_roots"] = [str(evidence_root)]
        evidence = self._file_evidence(
            locator=str(artifact),
            digest="sha256:3c4623849a49a53911c4a3e48d8cead8a1858960bccdea7a1b978d73ec2f06d7",
        )

        result = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            verifiers={"file": passing_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "pass")

    def test_wrong_file_digest_fails(self) -> None:
        (self.root / "artifact.txt").write_text("actual", encoding="utf-8")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["DIGEST_MISMATCH"]},
        )

    def test_expiration_and_type_age_override_each_make_evidence_stale(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        base = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
        )
        expired = dict(base, expires_at="2026-08-27T04:59:59Z")
        old = dict(base, generated_at="2026-08-27T04:50:00Z")
        self.criterion["evidence_freshness_by_type"] = {"file": 300}

        for evidence in (expired, old):
            with self.subTest(evidence=evidence):
                result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(
                    result["checks"]["integrity_and_freshness"],
                    {"status": "fail", "codes": ["STALE"]},
                )

    def test_freshness_windows_come_from_criterion_when_contract_has_none(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
        )
        criterion = {
            "required_scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            "max_evidence_age_seconds": 3600,
            "evidence_freshness_by_type": {"file": 60},
        }

        result = evaluate_evidence(evidence, criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["STALE"]},
        )

    def test_scope_mismatch_fails(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
            scope={"task_id": "TASK-1"},
        )

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["scope"], {"status": "fail", "codes": ["SCOPE_MISMATCH"]})

    def test_git_commit_resolves_real_commit_and_rejects_nonexistent_commit(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Strict Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "strict@example.invalid"],
            check=True,
        )
        (self.root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        common = {
            "evidence_id": "EV-GIT",
            "kind": "git-commit",
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }

        found = evaluate_evidence(dict(common, locator=sha), self.criterion, self.contract, now=NOW)
        missing = evaluate_evidence(
            dict(common, locator="0000000000000000000000000000000000000000"),
            self.criterion,
            self.contract,
            now=NOW,
        )

        self.assertEqual(
            [found["checks"][name]["status"] for name in ("resolve", "integrity_and_freshness", "scope")],
            ["pass", "pass", "pass"],
        )
        self.assertEqual(found["status"], "unknown")
        self.assertEqual(missing["status"], "fail")
        self.assertEqual(missing["checks"]["resolve"], {"status": "fail", "codes": ["NOT_FOUND"]})

    def test_git_commit_requires_exact_40_hex_locator(self) -> None:
        evidence = {
            "evidence_id": "EV-GIT",
            "kind": "git-commit",
            "locator": "HEAD",
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["resolve"],
            {"status": "fail", "codes": ["MALFORMED_LOCATOR"]},
        )

    def test_test_report_digest_uses_canonical_json_without_artifact_digest(self) -> None:
        report = {
            "artifact_digest": "sha256:f577fedf5c684bd3b3fc09dbac9c60be842b8a86641f23e4d1af37d1a921972d",
            "schema": "context-test-report/v1",
            "command": "python3 -m unittest",
            "exit_status": 0,
            "generated_at": "2026-08-27T04:30:00Z",
            "repo_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            "summary": {"failed": 0, "passed": 3},
        }
        path = self.root / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        evidence = self._test_report_evidence()

        result = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            verifiers={"test-report": passing_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "pass")

        report["artifact_digest"] = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        path.write_text(json.dumps(report), encoding="utf-8")
        wrong = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
        self.assertEqual(wrong["status"], "fail")
        self.assertEqual(
            wrong["checks"]["integrity_and_freshness"],
            {"status": "fail", "codes": ["DIGEST_MISMATCH"]},
        )

    def test_test_report_rejects_nonzero_exit_status(self) -> None:
        report = self._valid_test_report()
        report.update(
            artifact_digest="sha256:2d7665803e03fbdc7f17250b11810d4930b03e3b676a675508148949cadf21cb",
            exit_status=1,
        )
        self._write_report(report)

        result = evaluate_evidence(self._test_report_evidence(), self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertIn("NONZERO_EXIT_STATUS", result["checks"]["integrity_and_freshness"]["codes"])

    def test_test_report_rejects_wrong_schema(self) -> None:
        report = self._valid_test_report()
        report.update(
            artifact_digest="sha256:5e3dd80d43f47ae4c1d441cf8946bfb4c053ba1058ff31db473bcef948c34675",
            schema="context-test-report/v2",
        )
        self._write_report(report)

        result = evaluate_evidence(self._test_report_evidence(), self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertIn("INVALID_TEST_REPORT", result["checks"]["integrity_and_freshness"]["codes"])

    def test_test_report_rejects_revision_mismatch(self) -> None:
        report = self._valid_test_report()
        report.update(
            artifact_digest="sha256:272d5c5f3c14546cf9c7c6a360b85ffbf2b3e3e91fa7ab07dedce95075bf0b33",
            repo_revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        self._write_report(report)

        result = evaluate_evidence(self._test_report_evidence(), self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertIn("REVISION_MISMATCH", result["checks"]["scope"]["codes"])

    def test_test_report_rejects_internal_scope_mismatch(self) -> None:
        report = self._valid_test_report()
        report.update(
            artifact_digest="sha256:a6004c61c6c60c16b72095c781aa404d7a703d2f175df897c138250cae283cd0",
            scope={"task_id": "TASK-1"},
        )
        self._write_report(report)

        result = evaluate_evidence(self._test_report_evidence(), self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["scope"], {"status": "fail", "codes": ["SCOPE_MISMATCH"]})

    def test_test_report_requires_command_generated_at_and_revision_shape(self) -> None:
        fixtures = [
            (
                {"command": ""},
                "sha256:77fcaaef08e8cb4a1e1e08f82312b25474820e829fd8badfe01a97966a4fe7d2",
            ),
            (
                {"generated_at": "not-a-time"},
                "sha256:315a01909ddb7fba1c0f051b0cdedd1c32277627c9c0f21c7939d47bd40e76dd",
            ),
            (
                {"repo_revision": ""},
                "sha256:88ce9b8f1076eae3da35785f2aabbd5c46c52abffd3be0f1e24c82f89a0ab636",
            ),
        ]
        for changes, digest in fixtures:
            with self.subTest(changes=changes):
                report = self._valid_test_report()
                report.update(changes)
                report["artifact_digest"] = digest
                self._write_report(report)

                result = evaluate_evidence(
                    self._test_report_evidence(), self.criterion, self.contract, now=NOW
                )

                self.assertEqual(result["status"], "fail")
                self.assertIn("INVALID_TEST_REPORT", result["checks"]["integrity_and_freshness"]["codes"])

    def test_test_report_uses_internal_generated_at_for_freshness(self) -> None:
        report = self._valid_test_report()
        report.update(
            artifact_digest="sha256:e648ac264d0aa93bdc86fa6e7ecf415dd58cfe99c9f55dbdf4af2c1958d634d5",
            generated_at="2026-08-27T03:00:00Z",
        )
        self._write_report(report)

        result = evaluate_evidence(self._test_report_evidence(), self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertIn("STALE", result["checks"]["integrity_and_freshness"]["codes"])

    def test_url_is_syntax_only_and_valid_https_stays_unknown(self) -> None:
        evidence = {
            "evidence_id": "EV-URL",
            "kind": "url",
            "locator": "https://evidence.example.test/reports/18?format=json",
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["checks"]["resolve"], {"status": "unknown", "codes": ["NETWORK_BLOCKED"]})

    def test_url_rejects_insecure_credentials_malformed_and_nonpublic_literals(self) -> None:
        invalid = [
            "http://example.test/report",
            "https://user:secret@example.test/report",
            "https:///missing-host",
            "https://127.0.0.1/report",
            "https://10.1.2.3/report",
            "https://169.254.1.2/report",
            "https://[::1]/report",
            "https://[fe80::1]/report",
        ]

        for locator in invalid:
            with self.subTest(locator=locator):
                evidence = {
                    "evidence_id": "EV-URL",
                    "kind": "url",
                    "locator": locator,
                    "generated_at": "2026-08-27T04:30:00Z",
                    "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
                }
                result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["checks"]["resolve"]["status"], "fail")

    def test_url_rejects_whitespace_backslash_bad_percent_and_invalid_dns_hosts(self) -> None:
        invalid = [
            "https://example.test/has space",
            "https://example.test/has\ttab",
            "https://example.test/has\nnewline",
            "https:\\example.test\\report",
            "https://example.test/%ZZ",
            "https://example.test/%",
            "https://-bad.example/report",
            "https://bad-.example/report",
            "https://bad_label.example/report",
            "https://double..example/report",
            f"https://{'a' * 64}.example/report",
            "https://999.1.1.1/report",
            "https://éxample.test/report",
        ]

        for locator in invalid:
            with self.subTest(locator=locator):
                evidence = {
                    "evidence_id": "EV-URL-STRICT",
                    "kind": "url",
                    "locator": locator,
                    "generated_at": "2026-08-27T04:30:00Z",
                    "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
                }
                result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["checks"]["resolve"]["status"], "fail")

    def test_default_resolvers_exposes_only_the_four_builtin_kinds(self) -> None:
        self.assertEqual(set(default_resolvers()), {"file", "git-commit", "test-report", "url"})

    def test_malformed_evidence_kind_is_fail_not_unknown(self) -> None:
        for malformed_kind in (None, "", "   ", 7):
            with self.subTest(kind=malformed_kind):
                evidence = {"evidence_id": "EV-MALFORMED-KIND"}
                if malformed_kind is not None:
                    evidence["kind"] = malformed_kind

                result = evaluate_evidence(
                    evidence,
                    self.criterion,
                    self.contract,
                    now=NOW,
                )

                self.assertEqual(result["status"], "fail")
                self.assertEqual(
                    result["checks"]["resolve"],
                    {"status": "fail", "codes": ["MALFORMED_EVIDENCE_KIND"]},
                )

    def test_freshness_rejects_non_integer_negative_and_nonfinite_windows(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
        )
        invalid = [True, "3600", 3600.5, float("nan"), float("inf"), -1]

        for maximum in invalid:
            with self.subTest(maximum=maximum):
                criterion = dict(self.criterion, max_evidence_age_seconds=maximum)
                result = evaluate_evidence(
                    evidence,
                    criterion,
                    self.contract,
                    verifiers={"file": passing_verifier},
                    now=NOW,
                )
                self.assertEqual(result["status"], "fail")
                self.assertIn(
                    "INVALID_FRESHNESS_WINDOW",
                    result["checks"]["integrity_and_freshness"]["codes"],
                )

    def test_stale_evidence_cannot_escape_through_invalid_type_override(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
        )
        evidence["generated_at"] = "2026-08-27T01:00:00Z"
        criterion = dict(
            self.criterion,
            evidence_freshness_by_type={"file": "unbounded"},
        )

        result = evaluate_evidence(
            evidence,
            criterion,
            self.contract,
            verifiers={"file": passing_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn(
            "INVALID_FRESHNESS_WINDOW",
            result["checks"]["integrity_and_freshness"]["codes"],
        )

    def test_file_locator_fragment_is_not_part_of_filesystem_path(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_bytes(b"strict evidence\n")
        evidence = self._file_evidence(
            locator="artifact.txt#L1",
            digest="sha256:b188fa1315c608900d360bb4d67356e1ac2fc71c5930b92b9007fd6b10588311",
        )
        verifier_locators: list[str] = []

        def fragment_verifier(callback_evidence, callback_criterion, resolution):
            verifier_locators.append(callback_evidence["locator"])
            return {"status": "pass", "codes": []}

        result = evaluate_evidence(
            evidence,
            self.criterion,
            self.contract,
            verifiers={"file": fragment_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(verifier_locators, ["artifact.txt#L1"])

    def test_test_report_permission_error_is_unknown_not_digest_mismatch(self) -> None:
        self._write_report(self._valid_test_report())

        with patch("pathlib.Path.open", side_effect=PermissionError("denied")):
            result = evaluate_evidence(
                self._test_report_evidence(),
                self.criterion,
                self.contract,
                now=NOW,
            )

        self.assertEqual(result["status"], "unknown")
        codes = result["checks"]["integrity_and_freshness"]["codes"]
        self.assertIn("PERMISSION_DENIED", codes)
        self.assertNotIn("DIGEST_MISMATCH", codes)

    def test_file_hashing_enforces_documented_size_ceiling(self) -> None:
        artifact = self.root / "oversized.bin"
        with artifact.open("wb") as handle:
            handle.truncate(16 * 1024 * 1024 + 1)
        evidence = self._file_evidence(locator="oversized.bin")

        result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)

        self.assertEqual(result["status"], "fail")
        self.assertIn(
            "ARTIFACT_TOO_LARGE",
            result["checks"]["integrity_and_freshness"]["codes"],
        )

    def test_git_launch_and_timeout_errors_are_deterministic_unknowns(self) -> None:
        evidence = {
            "evidence_id": "EV-GIT-ERROR",
            "kind": "git-commit",
            "locator": "a" * 40,
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }
        failures = (
            (FileNotFoundError("git missing"), "TOOL_UNAVAILABLE"),
            (subprocess.TimeoutExpired(cmd="git", timeout=5), "GIT_TIMEOUT"),
        )

        for error, expected_code in failures:
            with self.subTest(error=type(error).__name__):
                with patch("managing_long_task_context.evidence.subprocess.run", side_effect=error):
                    result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(
                    result["checks"]["resolve"],
                    {"status": "unknown", "codes": [expected_code]},
                )

    def test_git_revision_exact_and_ancestor_modes_use_criterion_requirement(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Strict Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "strict@example.invalid"],
            check=True,
        )
        tracked = self.root / "tracked.txt"
        tracked.write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "old"], check=True)
        old_revision = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tracked.write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "commit", "-qam", "new"], check=True)
        new_revision = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        evidence = {
            "evidence_id": "EV-OLD-COMMIT",
            "kind": "git-commit",
            "locator": old_revision,
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }

        exact = evaluate_evidence(
            evidence,
            dict(self.criterion, required_revision=new_revision, revision_match="exact"),
            self.contract,
            verifiers={"git-commit": passing_verifier},
            now=NOW,
        )
        ancestor = evaluate_evidence(
            evidence,
            dict(self.criterion, required_revision=new_revision, revision_match="ancestor"),
            self.contract,
            verifiers={"git-commit": passing_verifier},
            now=NOW,
        )
        reverse_ancestor = evaluate_evidence(
            dict(evidence, evidence_id="EV-NEW-COMMIT", locator=new_revision),
            dict(self.criterion, required_revision=old_revision, revision_match="ancestor"),
            self.contract,
            verifiers={"git-commit": passing_verifier},
            now=NOW,
        )

        self.assertEqual(exact["status"], "fail")
        self.assertIn("REVISION_MISMATCH", exact["checks"]["scope"]["codes"])
        self.assertEqual(ancestor["status"], "pass")
        self.assertEqual(reverse_ancestor["status"], "fail")
        self.assertIn(
            "REVISION_MISMATCH",
            reverse_ancestor["checks"]["scope"]["codes"],
        )

    def test_test_report_revision_is_anchored_to_criterion_not_caller_envelope(self) -> None:
        old_revision = "a" * 40
        required_revision = "b" * 40
        report = self._valid_test_report()
        report["repo_revision"] = old_revision
        payload = dict(report)
        payload.pop("artifact_digest")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        report["artifact_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
        self._write_report(report)
        evidence = self._test_report_evidence()
        evidence["repo_revision"] = old_revision

        result = evaluate_evidence(
            evidence,
            dict(
                self.criterion,
                required_revision=required_revision,
                revision_match="exact",
            ),
            self.contract,
            verifiers={"test-report": passing_verifier},
            now=NOW,
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("REVISION_MISMATCH", result["checks"]["scope"]["codes"])

    def test_url_normalizes_host_before_rejecting_local_and_ambiguous_numeric_hosts(self) -> None:
        for locator in (
            "https://localhost./report",
            "https://service.localhost./report",
            "https://0x7f000001/report",
        ):
            with self.subTest(locator=locator):
                evidence = {
                    "evidence_id": "EV-URL-LOCAL",
                    "kind": "url",
                    "locator": locator,
                    "generated_at": "2026-08-27T04:30:00Z",
                    "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
                }
                result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["checks"]["resolve"]["status"], "fail")

    def test_malformed_locators_use_public_malformed_locator_code(self) -> None:
        fixtures = (
            self._file_evidence(locator=""),
            {
                "evidence_id": "EV-GIT-MALFORMED",
                "kind": "git-commit",
                "locator": "HEAD",
                "generated_at": "2026-08-27T04:30:00Z",
                "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            },
            {
                "evidence_id": "EV-URL-MALFORMED",
                "kind": "url",
                "locator": "https:///missing-host",
                "generated_at": "2026-08-27T04:30:00Z",
                "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            },
        )

        for evidence in fixtures:
            with self.subTest(kind=evidence["kind"]):
                result = evaluate_evidence(evidence, self.criterion, self.contract, now=NOW)
                self.assertEqual(
                    result["checks"]["resolve"],
                    {"status": "fail", "codes": ["MALFORMED_LOCATOR"]},
                )

    def _file_evidence(
        self,
        *,
        locator: str,
        digest: str = "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        scope: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "evidence_id": "EV-FILE",
            "kind": "file",
            "locator": locator,
            "artifact_digest": digest,
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": scope or {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }

    def _valid_test_report(self) -> dict[str, object]:
        return {
            "artifact_digest": "sha256:f577fedf5c684bd3b3fc09dbac9c60be842b8a86641f23e4d1af37d1a921972d",
            "schema": "context-test-report/v1",
            "command": "python3 -m unittest",
            "exit_status": 0,
            "generated_at": "2026-08-27T04:30:00Z",
            "repo_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
            "summary": {"failed": 0, "passed": 3},
        }

    def _write_report(self, report: dict[str, object]) -> None:
        (self.root / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def _test_report_evidence(self) -> dict[str, object]:
        return {
            "evidence_id": "EV-REPORT",
            "kind": "test-report",
            "locator": "report.json",
            "repo_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "generated_at": "2026-08-27T04:30:00Z",
            "scope": {"task_id": "TASK-1", "criterion_id": "AC-1"},
        }


class CanonicalJsonTests(unittest.TestCase):
    def test_utf16_key_order_and_minimal_string_escaping(self) -> None:
        expected = b'{"a":"\\n","\xf0\x9f\x98\x80":1,"\xee\x80\x80":2}'
        self.assertEqual(canonical_json_bytes({"\ue000": 2, "😀": 1, "a": "\n"}), expected)

    def test_supported_values_preserve_array_order(self) -> None:
        self.assertEqual(
            canonical_json_bytes({"z": [None, True, False, -12, "é"]}),
            b'{"z":[null,true,false,-12,"\xc3\xa9"]}',
        )

    def test_float_non_string_keys_and_unsupported_values_are_rejected(self) -> None:
        for value in (1.0, {1: "not a string key"}, {"value": object()}):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    canonical_json_bytes(value)


if __name__ == "__main__":
    unittest.main()
