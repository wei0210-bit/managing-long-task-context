from __future__ import annotations

import unittest

from managing_long_task_context.host_claude_native import capabilities, request_control


class ClaudeNativeBoundaryTests(unittest.TestCase):
    def test_capabilities_report_unavailable_native_path_and_are_detached(self) -> None:
        first = capabilities()
        self.assertEqual(first["schema"], "native-host-capabilities/v1")
        self.assertEqual(first["host"], "claude-native")
        self.assertEqual(first["evidence"]["level"], "tool-inventory")
        self.assertEqual(first["evidence"]["observed_at"], "2026-09-15")
        self.assertEqual(first["evidence"]["scope"], "snapshot of this call environment only; not runtime probing or end-to-end host validation")
        self.assertEqual(first["evidence"]["real_host_validation"], "NOT_RUN")
        self.assertEqual(first["capabilities"]["native_interface"]["status"], "unavailable")
        self.assertEqual(first["capabilities"]["trusted_identity"]["status"], "unknown")
        self.assertNotIn("codex", str(first).lower())
        self.assertFalse(first["side_effects"]["host_calls"])
        first["capabilities"]["native_interface"]["status"] = "pass"
        self.assertEqual(capabilities()["capabilities"]["native_interface"]["status"], "unavailable")
        baseline = capabilities()
        self.assertTrue(all(capabilities() == baseline for _ in range(20)))

    def test_control_operations_are_unsupported_without_borrowing_cli_evidence(self) -> None:
        for operation in ("start", "resume", "takeover", "archive"):
            result = request_control(operation)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["support_status"], "unsupported")
            self.assertFalse(result["launch_allowed"])
            self.assertFalse(result["control_granted"])
            self.assertIn("native_interface", result["missing_capabilities"])
            self.assertIn("trusted_identity", result["missing_capabilities"])

    def test_invalid_operation_is_rejected_without_execution(self) -> None:
        for operation in ("", "cli", "$(run)", None, ["start"]):
            result = request_control(operation)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["code"], "NATIVE_CONTROL_INVALID_OPERATION")
            self.assertFalse(result["launch_allowed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
