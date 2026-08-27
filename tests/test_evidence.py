from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


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
        self.assertEqual(result["checks"]["resolve"], {"status": "fail", "codes": ["INVALID_LOCATOR"]})

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
        self.assertIn("REVISION_MISMATCH", result["checks"]["integrity_and_freshness"]["codes"])

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
