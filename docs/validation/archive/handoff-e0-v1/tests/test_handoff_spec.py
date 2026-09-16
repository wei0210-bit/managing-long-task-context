"""Tests at the approved E0 fixture-bundle seam, not at product internals."""

import tempfile
import json
import shutil
import subprocess
import sys
import hashlib
import unittest
from pathlib import Path

from handoff_spec import validate_bundle

BUNDLE = Path(__file__).parent / "fixtures" / "handoff"


class HandoffSpecTests(unittest.TestCase):
    def copy_bundle(self, root):
        shutil.copytree(BUNDLE, root, dirs_exist_ok=True)

    def mutated(self, name, change):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_bundle(root)
            value = json.loads((root / name).read_text(encoding="utf-8"))
            change(value)
            (root / name).write_text(json.dumps(value), encoding="utf-8")
            return validate_bundle(root)

    def test_frozen_bundle_is_valid(self):
        self.assertEqual(validate_bundle(BUNDLE), [])

    def test_absent_bundle_is_rejected_instead_of_silently_passing(self):
        with tempfile.TemporaryDirectory() as directory:
            issues = validate_bundle(Path(directory))
        self.assertIn("E0_READ", [issue["code"] for issue in issues])

    def test_json_object_alone_is_not_a_valid_case_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps({}), encoding="utf-8")
            issues = validate_bundle(root)
        self.assertIn("E0_SCHEMA", [issue["code"] for issue in issues])

    def test_boolean_generation_is_not_an_integer(self):
        issues = self.mutated("cases.json", lambda b: b["cases"][0]["initial_state"].update(controller_generation=True))
        self.assertIn("E0_SCHEMA", [issue["code"] for issue in issues])

    def test_removing_a_catalog_group_cannot_be_called_complete(self):
        issues = self.mutated("cases.json", lambda b: b.update(cases=[c for c in b["cases"] if "H01" not in c["catalog_ids"]]))
        self.assertIn("E0_COVERAGE", [issue["code"] for issue in issues])

    def test_unknown_activation_cannot_expect_a_successful_transfer(self):
        issues = self.mutated("cases.json", lambda b: b["cases"][0].update(expected_check="unknown"))
        self.assertIn("E0_EXPECTATION", [issue["code"] for issue in issues])

    def test_cross_task_reference_cannot_supply_handoff_basis(self):
        issues = self.mutated("ready-state.json", lambda b: b["record"]["basis_refs"][0].update(task_id="TASK-OTHER"))
        self.assertIn("E0_BINDING", [issue["code"] for issue in issues])

    def test_modified_golden_assertion_is_reported_as_package_drift(self):
        issues = self.mutated("cases.json", lambda b: b["cases"][0]["assertions"][0].update(value="host:impostor"))
        self.assertIn("E0_HASH", [issue["code"] for issue in issues])

    def test_manifest_cannot_drop_a_required_file(self):
        issues = self.mutated("manifest.json", lambda b: b["files"].pop("cases.json"))
        self.assertIn("E0_MANIFEST", [issue["code"] for issue in issues])

    def test_duplicate_json_keys_are_not_last_writer_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_bundle(root)
            text = (root / "cases.json").read_text(encoding="utf-8")
            (root / "cases.json").write_text(text.replace('"fixture_version": 1', '"fixture_version": 1, "fixture_version": 1'), encoding="utf-8")
            issues = validate_bundle(root)
        self.assertIn("E0_READ", [issue["code"] for issue in issues])

    def test_fixture_file_symlink_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundle"
            self.copy_bundle(root)
            original = root / "ready-state.json"
            outside = Path(directory) / "outside.json"
            original.rename(outside)
            original.symlink_to(outside)
            issues = validate_bundle(root)
        self.assertIn("E0_READ", [issue["code"] for issue in issues])

    def test_inline_evidence_content_must_match_its_reference(self):
        issues = self.mutated("ready-state.json", lambda b: b["filesystem"].update({"AC-1": "unrelated content"}))
        self.assertIn("E0_BINDING", [issue["code"] for issue in issues])

    def test_cli_reports_fixture_validation_not_product_success(self):
        run = subprocess.run([sys.executable, str(Path(__file__).with_name("handoff_spec.py")), str(BUNDLE)], capture_output=True, text=True, check=False)
        self.assertIn('"product_execution": "NOT_RUN"', run.stdout)
        self.assertEqual(run.returncode, 0)

    def test_resource_budget_change_has_an_explicit_error(self):
        issues = self.mutated("budget-profile.json", lambda b: b["limits"].update(max_events=999999))
        self.assertIn("E0_BUDGET", [issue["code"] for issue in issues])

    def test_response_cannot_claim_completed_instead_of_check_status(self):
        issues = self.mutated("ready-state.json", lambda b: b["response"].update(check_status="completed"))
        self.assertIn("E0_SCHEMA", [issue["code"] for issue in issues])

    def test_prepared_event_must_not_transfer_controller_generation(self):
        issues = self.mutated("ready-state.json", lambda b: b["events"][0].update(controller_generation=8))
        self.assertIn("E0_EXPECTATION", [issue["code"] for issue in issues])

    def test_unknown_schema_pattern_is_rejected_without_interpreting_it(self):
        issues = self.mutated("cases.schema.json", lambda s: s["properties"]["cases"]["items"]["properties"]["case_id"].update(pattern="["))
        self.assertIn("E0_SCHEMA", [issue["code"] for issue in issues])

    def test_schema_negative_matrix(self):
        mutations = [
            ("missing_required", "cases.json", lambda b: b["cases"][0].pop("expected_check")),
            ("extra_field", "cases.json", lambda b: b["cases"][0].update(model_pass=True)),
            ("empty_assertions", "cases.json", lambda b: b["cases"][0].update(assertions=[])),
            ("wrong_status", "cases.json", lambda b: b["cases"][0].update(expected_check="done")),
            ("boolean_delta", "cases.json", lambda b: b["cases"][0].update(expected_generation_delta=True)),
            ("empty_source", "cases.json", lambda b: b["cases"][0].update(source_ref="")),
            ("path_traversal", "cases.json", lambda b: b["cases"][0].update(source_ref="../../secret")),
            ("fake_product_run", "cases.json", lambda b: b["cases"][0].update(run_status="PASS")),
            ("fake_actions", "cases.json", lambda b: b["cases"][0].update(fake_action_count=1)),
            ("boolean_action_count", "cases.json", lambda b: b["cases"][0].update(fake_action_count=False)),
            ("invalid_date", "ready-state.json", lambda b: b["record"].update(created_at="2026-02-30T00:00:00Z")),
            ("non_utc", "ready-state.json", lambda b: b["record"].update(created_at="2026-09-15T07:00:00+07:00")),
            ("relative_workspace", "ready-state.json", lambda b: b["record"].update(workspace_root="relative/path")),
            ("boolean_version", "ready-state.json", lambda b: b["record"].update(contract_version=True)),
            ("unknown_record_field", "ready-state.json", lambda b: b["record"].update(done=True)),
            ("missing_basis", "ready-state.json", lambda b: b["record"].update(basis_refs=[])),
            ("invalid_hash", "ready-state.json", lambda b: b["record"].update(contract_digest="not-a-hash")),
            ("negative_generation", "ready-state.json", lambda b: b["record"].update(controller_generation=-1)),
        ]
        for name, filename, change in mutations:
            with self.subTest(name=name):
                self.assertIn("E0_SCHEMA", [i["code"] for i in self.mutated(filename, change)])

    def test_semantic_negative_matrix(self):
        mutations = [
            ("duplicate_id", "E0_DUPLICATE", lambda b: b["cases"].append(b["cases"][0].copy())),
            ("wrong_revision", "E0_BASELINE", lambda b: b["cases"][0].update(baseline_revision="a" * 40)),
            ("wrong_package", "E0_BASELINE", lambda b: b["cases"][0].update(baseline_package_hash="a" * 64)),
            ("source_hash", "E0_SOURCE", lambda b: b["cases"][0].update(source_sha256="a" * 64)),
            ("history_claim", "E0_SOURCE", lambda b: b["cases"][0].update(source_kind="redacted-history")),
            ("wrong_test_level", "E0_LEVEL", lambda b: b["cases"][0].update(required_test_level="model")),
            ("missing_side_effect_guard", "E0_EXPECTATION", lambda b: b["cases"][0].update(forbidden_writes=["production"])),
            ("wrong_task", "E0_BINDING", lambda b: b["cases"][0]["initial_state"].update(task_id="TASK-OTHER")),
            ("commit_unknown_delta_known", "E0_EXPECTATION", lambda b: b["cases"][0].update(expected_commit="unknown")),
            ("request_wrong_operation", "E0_BINDING", lambda b: b["cases"][0]["operation"].update(request_fixture="cancel_handoff")),
        ]
        for name, code, change in mutations:
            with self.subTest(name=name):
                self.assertIn(code, [i["code"] for i in self.mutated("cases.json", change)])

    def test_malformed_inputs_fail_closed(self):
        for payload in [b"\xff", b'{"cases":', b'{"a": NaN}', b"[]", b"null", b"x" * (1024 * 1024 + 1)]:
            with self.subTest(prefix=payload[:20]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "cases.json").write_bytes(payload)
                self.assertTrue(validate_bundle(root))

    def test_malformed_schema_does_not_raise_or_pass(self):
        for value in [None, [], {"unsupported": True}, {"$ref": "https://invalid.test/schema"}]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.copy_bundle(root)
                (root / "cases.schema.json").write_text(json.dumps(value), encoding="utf-8")
                self.assertTrue(validate_bundle(root))

    def test_cli_wrong_external_manifest_pin_exits_nonzero(self):
        run = subprocess.run([sys.executable, str(Path(__file__).with_name("handoff_spec.py")), str(BUNDLE), "--expected-manifest-sha256", "0" * 64], capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 1)
        self.assertIn("E0_HASH", run.stdout)

    def test_readonly_validation_is_repeatable_and_leaves_package_unchanged(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in BUNDLE.iterdir() if p.is_file()}
        for _ in range(20):
            self.assertEqual(validate_bundle(BUNDLE), [])
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in BUNDLE.iterdir() if p.is_file()}
        self.assertEqual(before, after)
