from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context
import managing_long_task_context.rule_execution as rule_execution


def _contract(workspace: Path) -> dict[str, object]:
    return {
        "schema": 1,
        "task_id": "RULE-001",
        "version": 1,
        "issued_by": "publisher",
        "issued_at": "2026-09-07T00:00:00+00:00",
        "authorized_approvers": [],
        "objective": "Execute the selected load-bearing rule",
        "scope": ["strict context"],
        "out_of_scope": [],
        "constraints": [],
        "acceptance_criteria": [{
            "id": "AC-01",
            "criterion": "Gate can run",
            "required_evidence_types": ["test-report"],
        }],
        "workspace_root": str(workspace),
        "required_capabilities": ["rule-execution/v1"],
        "rule_execution": {
            "schema": 1,
            "rules": [{
                "rule_id": "dispatch-required",
                "experience_ref": None,
                "severity": "load-bearing",
                "applies_at": ["handoff"],
                "trigger_id": "controlled-modification",
                "checker_id": "dispatch-proof",
                "checker_version": "1",
                "observation_source_id": "workspace-observer",
            }],
        },
    }


def _real_source_ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _runtime_for(path: Path, source_ref: dict[str, str], *, applies_status: str = "applicable", check_status: str = "pass") -> dict[str, object]:
    def observe(task: str, stage: str, source_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return {
            "status": "pass", "codes": [], "coverage": "complete",
            "scope": "controlled modification", "observed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "source_refs": [source_ref], "payload": {"controlled_modification": True},
        }

    def applies(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
        return {"status": applies_status, "codes": [], "source_refs": [source_ref]}

    def check(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
        status = check_status if path.read_text(encoding="utf-8") == "controlled change was dispatched\n" else "fail"
        return {"status": status, "codes": ["DISPATCH_MISSING"] if status == "fail" else []}

    return {"observe": observe, "applies": applies, "check": check}


class RuleExecutionGateTests(unittest.TestCase):
    def test_schema_and_example_expose_rule_execution_v1(self) -> None:
        schema = json.loads((ROOT / "assets" / "rule-execution.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["rule_execution"]["properties"]["schema"], {"const": 1})
        spec = importlib.util.spec_from_file_location("rule_execution_example", ROOT / "examples" / "rule_execution.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.run_example()
        self.assertTrue(report["passed"], report)

    def test_handoff_blocks_selected_load_bearing_rule_without_execution_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint(
                "RULE-001", phase="handoff", completed=[], evidence_added=[],
                next_action="validator review", actor="publisher", base_dir=base_dir,
            )

            report = context.gate(
                "RULE-001", stage="handoff", base_dir=base_dir, emit=False,
            )

        self.assertFalse(report["passed"])
        self.assertEqual(report["rules"][0]["status"], "unknown")
        self.assertEqual(report["rules"][0]["codes"], ["RULE_RUNTIME_UNAVAILABLE"])

    def test_handoff_allows_selected_rule_with_complete_real_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            evidence = workspace / "dispatch-proof.txt"
            evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
            source_ref = _real_source_ref(evidence)
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint(
                "RULE-001", phase="handoff", completed=[], evidence_added=[],
                next_action="validator review", actor="publisher", base_dir=base_dir,
            )

            report = context.gate(
                "RULE-001",
                stage="handoff",
                base_dir=base_dir,
                emit=False,
                rule_runtime=_runtime_for(evidence, source_ref),
            )

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["rules"], [{
            "rule_id": "dispatch-required", "status": "pass", "codes": [],
            "source_refs": [source_ref],
        }])

    def test_handoff_blocks_unknown_applicability_and_allows_complete_non_applicability(self) -> None:
        for applies_status, expected_passed, expected_status in (
            ("unknown", False, "unknown"),
            ("not_applicable", True, "not_applicable"),
        ):
            with self.subTest(applies_status=applies_status), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                evidence = workspace / "dispatch-proof.txt"
                evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
                source_ref = _real_source_ref(evidence)
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime_for(evidence, source_ref, applies_status=applies_status))
                self.assertEqual(report["passed"], expected_passed)
                self.assertEqual(report["rules"][0]["status"], expected_status)

    def test_handoff_normalizes_invalid_exceptional_and_timeout_observers(self) -> None:
        cases = (
            ("none", lambda: None, "CALLBACK_INVALID_RESULT"),
            ("bool", lambda: True, "CALLBACK_INVALID_RESULT"),
            ("missing", lambda: {"status": "pass"}, "CALLBACK_INVALID_RESULT"),
            ("bad-status", lambda: {"status": [], "codes": [], "coverage": "complete", "scope": "scope", "observed_at": "2026-09-07T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z", "source_refs": [], "payload": {}}, "CALLBACK_INVALID_RESULT"),
            ("error", lambda: (_ for _ in ()).throw(RuntimeError("sensitive detail")), "CALLBACK_ERROR"),
            ("timeout", lambda: (_ for _ in ()).throw(TimeoutError()), "CALLBACK_TIMEOUT"),
        )
        for name, produce, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime={"observe": lambda *args: produce()})
                self.assertFalse(report["passed"])
                self.assertEqual(report["rules"][0]["codes"], [expected_code])
                self.assertNotIn("sensitive detail", str(report))

    def test_handoff_rejects_rule_when_checker_changes_observed_original_before_verdict(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            evidence = workspace / "dispatch-proof.txt"
            evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
            source_ref = _real_source_ref(evidence)
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
            runtime = _runtime_for(evidence, source_ref)

            def mutate_after_check(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
                self.assertEqual(evidence.read_text(encoding="utf-8"), "controlled change was dispatched\n")
                evidence.write_text("changed after check\n", encoding="utf-8")
                return {"status": "pass", "codes": []}

            runtime["check"] = mutate_after_check
            report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

        self.assertFalse(report["passed"])
        self.assertEqual(report["rules"][0]["status"], "unknown")
        self.assertEqual(report["rules"][0]["codes"], ["INPUT_CHANGED"])

    def test_explicit_dispatch_failure_blocks_but_advisory_failure_does_not_replace_base_verdict(self) -> None:
        for severity, expected_passed in (("load-bearing", False), ("advisory", True)):
            with self.subTest(severity=severity), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                evidence = workspace / "dispatch-proof.txt"
                evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
                source_ref = _real_source_ref(evidence)
                contract = _contract(workspace)
                contract["rule_execution"]["rules"][0]["severity"] = severity
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(contract, confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=_runtime_for(evidence, source_ref, check_status="fail"))
                self.assertEqual(report["passed"], expected_passed)
                self.assertEqual(report["rules"][0]["status"], "fail")
                self.assertEqual(report["rules"][0]["codes"], ["DISPATCH_MISSING"])

    def test_unselected_stage_does_not_call_rule_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            report = context.gate("RULE-001", stage="release", base_dir=base_dir, emit=False, rule_runtime={"observe": lambda *args: (_ for _ in ()).throw(AssertionError("must not run"))})

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["rules"], [])

    def test_partial_or_noncanonical_observation_cannot_become_not_applicable(self) -> None:
        for kind in ("partial", "relative", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                evidence = workspace / "dispatch-proof.txt"
                evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
                source_ref = _real_source_ref(evidence)
                if kind == "relative":
                    source_ref = {"path": "dispatch-proof.txt", "sha256": source_ref["sha256"]}
                elif kind == "symlink":
                    linked = workspace / "proof-link.txt"
                    linked.symlink_to(evidence.name)
                    source_ref = {"path": str(linked), "sha256": source_ref["sha256"]}
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
                runtime = _runtime_for(evidence, source_ref, applies_status="not_applicable")
                if kind == "partial":
                    original_observe = runtime["observe"]

                    def partial_observe(*args: object) -> dict[str, object]:
                        observation = original_observe(*args)
                        observation["coverage"] = "partial"
                        return observation

                    runtime["observe"] = partial_observe
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)
                self.assertFalse(report["passed"])
                self.assertEqual(report["rules"][0]["status"], "unknown")
                expected = "OBSERVATION_COVERAGE_PARTIAL" if kind == "partial" else "CALLBACK_INVALID_RESULT"
                self.assertEqual(report["rules"][0]["codes"], [expected])

    def test_handoff_normalizes_invalid_applies_and_check_callbacks(self) -> None:
        cases = (
            ("applies", "none", lambda: None, "CALLBACK_INVALID_RESULT"),
            ("applies", "bool", lambda: False, "CALLBACK_INVALID_RESULT"),
            ("applies", "missing", lambda: {"status": "applicable", "codes": []}, "CALLBACK_INVALID_RESULT"),
            ("applies", "bad-status", lambda: {"status": {}, "codes": [], "source_refs": []}, "CALLBACK_INVALID_RESULT"),
            ("applies", "error", lambda: (_ for _ in ()).throw(RuntimeError("sensitive applies")), "CALLBACK_ERROR"),
            ("applies", "timeout", lambda: (_ for _ in ()).throw(TimeoutError()), "CALLBACK_TIMEOUT"),
            ("check", "none", lambda: None, "CALLBACK_INVALID_RESULT"),
            ("check", "bool", lambda: True, "CALLBACK_INVALID_RESULT"),
            ("check", "missing", lambda: {"status": "pass"}, "CALLBACK_INVALID_RESULT"),
            ("check", "bad-status", lambda: {"status": [], "codes": []}, "CALLBACK_INVALID_RESULT"),
            ("check", "error", lambda: (_ for _ in ()).throw(RuntimeError("sensitive check")), "CALLBACK_ERROR"),
            ("check", "timeout", lambda: (_ for _ in ()).throw(TimeoutError()), "CALLBACK_TIMEOUT"),
        )
        for boundary, name, produce, expected_code in cases:
            with self.subTest(boundary=boundary, name=name), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                evidence = workspace / "dispatch-proof.txt"
                evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
                source_ref = _real_source_ref(evidence)
                base_dir = temporary_root / ".prime" / "context"
                context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
                context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
                runtime = _runtime_for(evidence, source_ref)
                if boundary == "applies":
                    runtime["applies"] = lambda *args: produce()
                else:
                    runtime["check"] = lambda *args: produce()
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)
                self.assertFalse(report["passed"])
                self.assertEqual(report["rules"][0]["codes"], [expected_code])
                self.assertNotIn("sensitive", str(report))

    def test_contract_rejects_boolean_schema_and_missing_required_rule_fields(self) -> None:
        for mutate, expected in (
            (lambda contract: contract["rule_execution"].update({"schema": True}), "schema must equal 1"),
            (lambda contract: contract["rule_execution"]["rules"][0].pop("experience_ref"), "missing required fields"),
            (lambda contract: contract["rule_execution"]["rules"][0].update({"severity": []}), "severity must be advisory or load-bearing"),
            (lambda contract: contract["rule_execution"]["rules"][0].update({"applies_at": [{}]}), "applies_at must be a non-empty unique list"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
                temporary_root = Path(temporary_dir)
                workspace = temporary_root / "workspace"
                workspace.mkdir()
                contract = _contract(workspace)
                mutate(contract)
                with self.assertRaisesRegex(context.ContextError, expected):
                    context.publish_contract(contract, confirmed_by="publisher", base_dir=temporary_root / ".prime" / "context")

    def test_checker_cannot_extend_locked_observation_expiry(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            evidence = workspace / "dispatch-proof.txt"
            evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
            source_ref = _real_source_ref(evidence)
            base = datetime(2030, 1, 1, tzinfo=timezone.utc)
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)

            def observe(task: str, stage: str, source_id: str) -> dict[str, object]:
                return {"status": "pass", "codes": [], "coverage": "complete", "scope": "controlled modification", "observed_at": base.isoformat(), "expires_at": (base + timedelta(seconds=1)).isoformat(), "source_refs": [source_ref], "payload": {}}

            def applies(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
                return {"status": "applicable", "codes": [], "source_refs": [source_ref]}

            def check(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
                observation["expires_at"] = (base + timedelta(hours=1)).isoformat()
                return {"status": "pass", "codes": []}

            class FixedDateTime(datetime):
                @classmethod
                def now(cls, tz: timezone | None = None) -> datetime:
                    return base if tz is not None else base.replace(tzinfo=None)

            with patch.object(rule_execution, "datetime", FixedDateTime), patch.object(context, "_trusted_utc_now", return_value=base + timedelta(seconds=2)):
                report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime={"observe": observe, "applies": applies, "check": check})

        self.assertFalse(report["passed"], report)
        self.assertEqual(report["rules"][0]["codes"], ["INPUT_CHANGED"])

    def test_checker_contract_change_blocks_without_deadlock(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            evidence = workspace / "dispatch-proof.txt"
            evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
            source_ref = _real_source_ref(evidence)
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(_contract(workspace), confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
            runtime = _runtime_for(evidence, source_ref)

            def republish(rule: dict[str, object], observation: dict[str, object]) -> dict[str, object]:
                revised = _contract(workspace)
                revised["version"] = 2
                revised["objective"] = "Changed during validation"
                context.publish_contract(revised, confirmed_by="publisher", base_dir=base_dir)
                return {"status": "pass", "codes": []}

            runtime["check"] = republish
            report = context.gate("RULE-001", stage="handoff", base_dir=base_dir, emit=False, rule_runtime=runtime)

        self.assertFalse(report["passed"], report)
        self.assertEqual(report["rules"][0]["codes"], ["INPUT_CHANGED"])

    def test_all_gate_stages_evaluate_selected_rules_and_keep_existing_verdict(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            evidence = workspace / "dispatch-proof.txt"
            evidence.write_text("controlled change was dispatched\n", encoding="utf-8")
            source_ref = _real_source_ref(evidence)
            contract = _contract(workspace)
            contract["rule_execution"]["rules"][0]["applies_at"] = ["release", "resume", "handoff", "completion"]
            base_dir = temporary_root / ".prime" / "context"
            context.publish_contract(contract, confirmed_by="publisher", base_dir=base_dir)
            context.checkpoint("RULE-001", phase="handoff", completed=[], evidence_added=[], next_action="validator review", actor="publisher", base_dir=base_dir)
            seen: list[str] = []
            runtime = _runtime_for(evidence, source_ref)
            original_observe = runtime["observe"]

            def observe(task: str, stage: str, source_id: str) -> dict[str, object]:
                seen.append(stage)
                return original_observe(task, stage, source_id)

            runtime["observe"] = observe
            reports = {stage: context.gate("RULE-001", stage=stage, base_dir=base_dir, emit=False, rule_runtime=runtime) for stage in ("release", "resume", "handoff", "completion")}

        self.assertEqual(seen, ["release", "resume", "handoff", "completion"])
        for report in reports.values():
            self.assertEqual(report["rules"][0]["status"], "pass")
        self.assertFalse(reports["completion"]["passed"])
        self.assertIn("completion gate requires evidence_map", reports["completion"]["errors"])
