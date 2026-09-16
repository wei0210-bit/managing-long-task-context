from __future__ import annotations

import unittest

from managing_long_task_context.host_codex_native import capabilities, request_control


class CodexNativeBoundaryTests(unittest.TestCase):
    def test_capabilities_are_schema_declared_and_detached(self) -> None:
        first = capabilities()
        self.assertEqual(first["schema"], "native-host-capabilities/v1")
        self.assertEqual(first["host"], "codex-native")
        self.assertEqual(first["evidence"]["level"], "schema-declared")
        self.assertEqual(first["evidence"]["observed_at"], "2026-09-15")
        self.assertEqual(first["evidence"]["scope"], "snapshot of this call environment only; not runtime probing or end-to-end host validation")
        self.assertEqual(first["evidence"]["real_host_validation"], "NOT_RUN")
        self.assertEqual(first["capabilities"]["same_parent_tree_addressing"]["status"], "declared")
        self.assertEqual(first["capabilities"]["clean_history"]["status"], "unknown")
        self.assertEqual(first["capabilities"]["trusted_identity"]["status"], "unknown")
        self.assertFalse(first["side_effects"]["host_calls"])
        first["capabilities"]["trusted_identity"]["status"] = "pass"
        self.assertEqual(capabilities()["capabilities"]["trusted_identity"]["status"], "unknown")
        baseline = capabilities()
        self.assertTrue(all(capabilities() == baseline for _ in range(20)))

    def test_known_control_operations_are_unknown_and_never_granted(self) -> None:
        for operation in ("start", "resume", "takeover", "archive"):
            result = request_control(operation)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["support_status"], "unsupported")
            self.assertFalse(result["launch_allowed"])
            self.assertFalse(result["control_granted"])
            self.assertEqual(result["operation"], operation)
            self.assertIn("trusted_identity", result["missing_capabilities"])
            self.assertIn("parent_survival", result["missing_capabilities"])

    def test_invalid_or_untrusted_operation_is_rejected_without_execution(self) -> None:
        for operation in ("", "delete", "; touch unsafe", None, {"operation": "start"}):
            result = request_control(operation)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["code"], "NATIVE_CONTROL_INVALID_OPERATION")
            self.assertFalse(result["launch_allowed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
