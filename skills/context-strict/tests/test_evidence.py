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
