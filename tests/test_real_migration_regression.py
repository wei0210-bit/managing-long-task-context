"""Deterministic regression suite for the first real long-session migration incident.

Root-only: it reads maintained documents and Git history.  Method names carry
exactly one REG or SCN inventory ID.  ``build_inventory`` is the single source
of ``test-inventory.json`` and ``REG-14`` rejects duplicates, gaps, multiple
primary categories, and unbound failure modes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

import managing_long_task_context as context
from managing_long_task_context import handoff as handoff_module
from managing_long_task_context import host_claude_native, host_codex_native

import test_handoff_preflight as preflight_tests
from test_handoff_activation import ActivationAuthority, ActivationVerifier, _ref


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = preflight_tests.PREFLIGHT
V1_BASELINE_COMMIT = "097c952e37e7f971274e70579c33c2727cc67fb0"
PLAN = ROOT / "docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md"

FAILURE_MODES = {
    "FM-01": "package identity: script imports another install or manifest changes during import",
    "FM-02": "bounded read: symlink, FIFO/directory, inode change during read, or oversize input",
    "FM-03": "Git: verified_head missing or not an ancestor, timeout, or output overflow",
    "FM-04": "allowlist: non-allowlisted change after verification or relevant uncommitted file",
    "FM-05": "checklist/readback: Unicode, CRLF, duplicate ID, unknown field, missing category, same ID different value",
    "FM-06": "Strict prepare: handoff record not yet created",
    "FM-07": "Strict activate: client ID only, self-report, or evidence changed during the call",
    "FM-08": "Strict status: historical commit while current verifier or package is invalid",
    "FM-09": "Manual recovery: material SHA correct but facts mismatched",
    "FM-10": "Distribution: root fixed but Strict copy stale, or script leaks into Lite",
    "FM-11": "Stable output: material text, user names, temporary paths, or exception text leak",
    "FM-12": "Skill behaviour: directive present but the agent reports overall success or archives",
}

CATEGORY_BY_PREFIX = {
    "UNIT": "unit", "INT": "integration", "CLI": "cli", "DIST": "distribution",
    "REG": "regression_scenario", "SCN": "regression_scenario", "PERF": "performance",
}
MINIMUM_METHODS = {"unit": 28, "integration": 12, "cli": 18, "distribution": 4, "regression_scenario": 19, "performance": 4}
TEST_FILES = {
    "tests/test_handoff_preflight.py": ("UNIT", "INT", "CLI", "PERF"),
    "tests/test_real_migration_regression.py": ("REG", "SCN"),
    "tests/test_distribution.py": ("DIST",),
}

# ID -> (acceptance criteria, failure modes).  Method names are discovered from the files.
INVENTORY = {
    "UNIT-01": ([24], ["FM-01"]), "UNIT-02": ([24], ["FM-01"]), "UNIT-03": ([24], ["FM-01"]), "UNIT-04": ([24], ["FM-01"]),
    "UNIT-05": ([21], ["FM-02"]), "UNIT-06": ([21], ["FM-02"]), "UNIT-07": ([21], ["FM-02"]), "UNIT-08": ([21, 23], ["FM-02"]),
    "UNIT-09": ([21], ["FM-02"]), "UNIT-10": ([21], ["FM-02"]),
    "UNIT-11": ([20], ["FM-04"]), "UNIT-12": ([27], ["FM-03"]), "UNIT-13": ([20, 22], ["FM-04"]),
    "UNIT-14": ([2, 20], ["FM-03"]), "UNIT-15": ([20], ["FM-04"]), "UNIT-16": ([2, 9, 10, 22], ["FM-04"]),
    "UNIT-17": ([4, 23], ["FM-05"]), "UNIT-18": ([23], ["FM-05"]), "UNIT-19": ([23], ["FM-05"]), "UNIT-20": ([23], ["FM-05"]),
    "UNIT-21": ([23], ["FM-05"]), "UNIT-22": ([23], ["FM-05"]), "UNIT-23": ([23], ["FM-05"]), "UNIT-24": ([23], ["FM-05"]),
    "UNIT-25": ([11, 25], ["FM-11"]), "UNIT-26": ([18], ["FM-11"]), "UNIT-27": ([25], ["FM-11"]), "UNIT-28": ([25], ["FM-11"]),
    "INT-01": ([26], ["FM-06"]), "INT-02": ([6, 26], ["FM-06"]), "INT-03": ([6, 26], ["FM-06"]),
    "INT-04": ([6, 26], ["FM-07"]), "INT-05": ([6, 7], ["FM-07"]), "INT-06": ([6, 7], ["FM-07"]),
    "INT-07": ([8, 12], ["FM-08"]), "INT-08": ([8, 12], ["FM-08"]), "INT-09": ([8, 16], ["FM-08"]),
    "INT-10": ([5, 8], ["FM-09"]), "INT-11": ([4, 5], ["FM-09"]), "INT-12": ([4, 5], ["FM-09"]),
    "CLI-01": ([8, 18], ["FM-11"]), "CLI-02": ([3, 26], ["FM-11"]), "CLI-03": ([2], ["FM-04"]), "CLI-04": ([2, 10], ["FM-04"]),
    "CLI-05": ([2, 20], ["FM-03"]), "CLI-06": ([2], ["FM-01"]), "CLI-07": ([2, 9], ["FM-04"]), "CLI-08": ([1, 2], ["FM-04"]),
    "CLI-09": ([4, 21], ["FM-02"]), "CLI-10": ([21], ["FM-02"]), "CLI-11": ([4], ["FM-09"]), "CLI-12": ([25], ["FM-11"]),
    "CLI-13": ([1, 22], ["FM-04"]), "CLI-14": ([24], ["FM-01"]), "CLI-15": ([24], ["FM-01"]), "CLI-16": ([24], ["FM-01"]),
    "CLI-17": ([14, 18], ["FM-11"]), "CLI-18": ([6, 7], ["FM-07"]),
    "PERF-01": ([27], ["FM-03"]), "PERF-02": ([27], ["FM-03"]), "PERF-03": ([27], ["FM-03"]), "PERF-04": ([28], ["FM-03"]),
    "DIST-01": ([13], ["FM-10"]), "DIST-02": ([13], ["FM-10"]), "DIST-03": ([13], ["FM-10"]), "DIST-04": ([13, 14], ["FM-10"]),
    "REG-01": ([12, 16], ["FM-07"]), "REG-02": ([12, 16], ["FM-07"]), "REG-03": ([12], ["FM-08"]), "REG-04": ([12], ["FM-08"]),
    "REG-05": ([12], ["FM-07"]), "REG-06": ([12], ["FM-10"]), "REG-07": ([5, 16], ["FM-09"]), "REG-08": ([7, 12], ["FM-07"]),
    "REG-09": ([16, 17, 19], ["FM-12"]), "REG-10": ([8, 16], ["FM-12"]), "REG-11": ([3, 8, 11], ["FM-12"]),
    "REG-12": ([3, 5, 11], ["FM-12"]), "REG-13": ([8], ["FM-12"]), "REG-14": ([29], ["FM-12"]),
    "SCN-01": ([2, 9, 15, 20], ["FM-03", "FM-04"]), "SCN-02": ([1, 9, 15], ["FM-04"]), "SCN-03": ([7, 15], ["FM-07"]),
    "SCN-04": ([4, 15], ["FM-05", "FM-09"]), "SCN-05": ([5, 15], ["FM-09"]), "SCN-06": ([15, 16], ["FM-08", "FM-12"]),
}

NOT_RUN = {
    "NAT-01": {"category": "natural", "status": "NOT_RUN", "reason": "manual fallback cold recovery requires separate user authorization",
               "acceptance_criteria": [15], "failure_modes": ["FM-09"]},
    "EVAL-01": {"category": "behaviour_eval", "status": "NOT_RUN", "reason": "no isolated LLM behaviour eval harness was authorized",
                "acceptance_criteria": [29], "failure_modes": ["FM-12"]},
}


def discover_methods() -> dict[str, list[tuple[str, str]]]:
    """Return inventory ID -> [(dotted test name, file)] from test method names."""
    found: dict[str, list[tuple[str, str]]] = {}
    for relative, prefixes in TEST_FILES.items():
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        module = Path(relative).stem
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef) or not item.name.startswith("test_"):
                    continue
                matched = re.match(r"^test_([a-z]+)_(\d{2})_", item.name)
                prefix = matched.group(1).upper() if matched else None
                if relative != "tests/test_distribution.py" or prefix == "DIST":
                    identifier = f"{prefix}-{matched.group(2)}" if matched and prefix in prefixes else f"UNREGISTERED:{item.name}"
                    found.setdefault(identifier, []).append((f"{module}.{node.name}.{item.name}", relative))
    return found


def validate_inventory() -> list[str]:
    errors: list[str] = []
    found = discover_methods()
    for identifier, methods in sorted(found.items()):
        if identifier.startswith("UNREGISTERED:"):
            errors.append(f"method without exactly one inventory ID: {identifier}")
        elif len(methods) != 1:
            errors.append(f"duplicate test ID {identifier}: {methods}")
        elif identifier not in INVENTORY:
            errors.append(f"test ID missing from inventory: {identifier}")
    for identifier in INVENTORY:
        if identifier not in found:
            errors.append(f"inventory ID has no test method: {identifier}")
    for prefix in CATEGORY_BY_PREFIX:
        numbers = sorted(int(key.split("-")[1]) for key in INVENTORY if key.split("-")[0] == prefix)
        if numbers != list(range(1, len(numbers) + 1)):
            errors.append(f"{prefix} numbering has gaps or duplicates: {numbers}")
    counts: dict[str, int] = {}
    for identifier in INVENTORY:
        category = CATEGORY_BY_PREFIX[identifier.split("-")[0]]
        counts[category] = counts.get(category, 0) + 1
    for category, minimum in MINIMUM_METHODS.items():
        if counts.get(category, 0) < minimum:
            errors.append(f"{category} has {counts.get(category, 0)} methods; minimum {minimum}")
    bound = {mode for _, modes in INVENTORY.values() for mode in modes}
    for mode in FAILURE_MODES:
        if mode not in bound:
            errors.append(f"failure mode without automated test binding: {mode}")
    covered = {criterion for criteria, _ in INVENTORY.values() for criterion in criteria}
    missing = sorted(set(range(1, 30)) - covered)
    if missing:
        errors.append(f"acceptance criteria without a test binding: {missing}")
    for identifier, (criteria, modes) in INVENTORY.items():
        if not criteria or not modes or any(mode not in FAILURE_MODES for mode in modes):
            errors.append(f"inventory entry lacks valid bindings: {identifier}")
    return errors


def build_inventory() -> dict[str, object]:
    found = discover_methods()
    tests = []
    for identifier, (criteria, modes) in INVENTORY.items():
        methods = found.get(identifier, [])
        tests.append({
            "id": identifier, "primary_category": CATEGORY_BY_PREFIX[identifier.split("-")[0]],
            "test": methods[0][0] if len(methods) == 1 else None, "file": methods[0][1] if len(methods) == 1 else None,
            "acceptance_criteria": criteria, "failure_modes": modes,
        })
    counts: dict[str, int] = {}
    for entry in tests:
        counts[str(entry["primary_category"])] = counts.get(str(entry["primary_category"]), 0) + 1
    return {
        "schema": "migration-test-inventory/v1",
        "counting_rule": "one unittest.TestCase method per ID; subTest does not add methods",
        "minimum_methods": MINIMUM_METHODS, "method_counts": counts,
        "failure_modes": FAILURE_MODES, "tests": tests, "not_run": NOT_RUN,
        "validation_errors": validate_inventory(),
    }


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True, timeout=30,
                          env=preflight_tests.git_environment())


class RealMigrationRegressionTests(unittest.TestCase):
    maxDiff = None

    def v1_fixture(self) -> dict[str, object]:
        root = preflight_tests.resolved_temporary(self, "v1-baseline-")
        base, workspace, package = root / "context", root / "workspace", root / "package"
        workspace.mkdir()
        package.mkdir()
        (package / "skill-manifest.json").write_text("synthetic package\n", encoding="utf-8")
        task_id, handoff_id = "TASK-V1-BASELINE", "HO-V1-BASELINE"
        published = context.publish_contract({
            "schema": 1, "task_id": task_id, "version": 1, "issued_by": "publisher", "issued_at": "2026-09-15T00:00:00Z",
            "authorized_approvers": [], "objective": "v1 baseline", "scope": ["isolated"], "out_of_scope": [],
            "constraints": ["no business action"],
            "acceptance_criteria": [{"id": "AC-01", "criterion": "baseline", "required_evidence": ["synthetic"]}],
        }, confirmed_by="publisher", base_dir=base)
        cursor = json.loads((base / task_id / "events.jsonl").read_text().splitlines()[-1])["event_id"]
        contents = {"source": "source\n", "target": "target\n", "authorization": "scope\n", "basis": "basis\n", "artifacts": "artifacts\n"}
        refs = {}
        for ref_id, text in contents.items():
            (workspace / f"{ref_id}.txt").write_text(text, encoding="utf-8")
            refs[ref_id] = _ref(task_id, ref_id, workspace / f"{ref_id}.txt")
        record = {
            "protocol": "short-session-handoff/v1", "task_id": task_id, "contract_version": 1,
            "contract_digest": published["seal"]["integrity_digest"].removeprefix("sha256:"),
            "workspace_root": str(workspace.resolve()),
            "package_manifest_sha256": hashlib.sha256((package / "skill-manifest.json").read_bytes()).hexdigest(),
            "handoff_id": handoff_id, "request_id": "REQ-V1-PREPARE", "controller_generation": 0,
            "source_session_ref": refs["source"], "target_session_ref": refs["target"], "authorization_ref": refs["authorization"],
            "basis_refs": [refs["basis"]], "artifact_manifest_ref": refs["artifacts"], "created_at": "2026-09-15T00:00:01Z",
            "event_cursor": cursor,
        }
        verifier = ActivationVerifier(record, contents)
        common = {"base_dir": base, "workspace_root": workspace, "package_root": package}
        identity = object()

        class PrepareAuthority(ActivationAuthority):
            def authorize(authority, request):  # type: ignore[no-untyped-def]
                response = super().authorize(request)
                response.pop("subject_session_ref", None)
                return response

        prepared = context.prepare_handoff(task_id, request_id="REQ-V1-PREPARE", controller_generation=0, record=record,
                                           runtime_identity=identity, write_authorizer=PrepareAuthority(record, identity, purpose="prepare"),
                                           handoff_verifier=verifier, **common)
        return {"task_id": task_id, "handoff_id": handoff_id, "record": record, "verifier": verifier,
                "common": common, "prepared": prepared, "events": base / task_id / "events.jsonl"}

    def activate(self, fixture: dict[str, object], *, request_id: str = "REQ-V1-ACTIVATE", generation: int = 0) -> dict[str, object]:
        identity = object()
        return context.activate_handoff(
            fixture["task_id"], request_id=request_id, controller_generation=generation, handoff_id=fixture["handoff_id"],
            runtime_identity=identity, write_authorizer=ActivationAuthority(fixture["record"], identity, purpose="activate"),
            handoff_verifier=fixture["verifier"], **fixture["common"],
        )

    def test_reg_01_v1_capability_and_public_exports_are_unchanged(self) -> None:
        expected = ["prepare_handoff", "validate_handoff", "activate_handoff", "cancel_handoff", "handoff_status"]
        for declaration_path in (ROOT / "skill-package.json", ROOT / "skills/context-strict/skill-package.json"):
            with self.subTest(declaration=declaration_path.parent.name):
                capabilities = json.loads(declaration_path.read_text(encoding="utf-8"))["capabilities"]
                self.assertEqual(capabilities["short-session-handoff/v1"]["python_exports"], expected)
                self.assertEqual([name for name in capabilities if name.startswith("short-session-handoff/")], ["short-session-handoff/v1"])
        self.assertEqual(handoff_module.CAPABILITY, "short-session-handoff/v1")
        self.assertTrue(set(expected) <= set(context.__all__))

    def test_reg_02_v1_event_record_and_result_fields_match_the_097c952_baseline(self) -> None:
        names = ("_EVENT_TYPES", "_EVENT_FIELDS", "_RECORD_FIELDS", "_RESULT_REQUIRED", "CAPABILITY")
        shown = _git("show", f"{V1_BASELINE_COMMIT}:src/managing_long_task_context/handoff.py")
        self.assertEqual(shown.returncode, 0, "the v1 baseline commit must be available; fetch full history")
        baseline: dict[str, object] = {}
        for node in ast.parse(shown.stdout).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
                value = node.value.args[0] if isinstance(node.value, ast.Call) else node.value
                baseline[node.targets[0].id] = ast.literal_eval(value)
        for name in names:
            with self.subTest(name=name):
                current = getattr(handoff_module, name)
                self.assertEqual(current if isinstance(current, str) else set(current), baseline[name] if isinstance(baseline[name], str) else set(baseline[name]))

    def test_reg_03_v1_return_keys_and_statuses_are_unchanged(self) -> None:
        fixture = self.v1_fixture()
        keys = {"check_status", "commit_status", "controller_generation", "blocking_reasons", "verification_refs", "next_readonly_action"}
        validated = context.validate_handoff(fixture["task_id"], handoff_id=fixture["handoff_id"], handoff_verifier=fixture["verifier"], **fixture["common"])
        activated = self.activate(fixture)
        status = context.handoff_status(fixture["task_id"], handoff_id=fixture["handoff_id"], handoff_verifier=fixture["verifier"], **fixture["common"])
        unverified = context.handoff_status(fixture["task_id"], handoff_id=fixture["handoff_id"], **fixture["common"])
        for name, result, expected in (
            ("prepare", fixture["prepared"], ("pass", "confirmed_committed", 0)),
            ("validate", validated, ("pass", "not_attempted", 0)),
            ("activate", activated, ("pass", "confirmed_committed", 1)),
            ("status", status, ("pass", "confirmed_committed", 1)),
            ("status-without-verifier", unverified, ("unknown", "confirmed_committed", 1)),
        ):
            with self.subTest(call=name):
                self.assertEqual(set(result), keys)
                self.assertEqual((result["check_status"], result["commit_status"], result["controller_generation"]), expected)

    def test_reg_04_repeated_activation_request_is_idempotent(self) -> None:
        fixture = self.v1_fixture()
        first = self.activate(fixture)
        log = fixture["events"].read_bytes()
        repeated = self.activate(fixture)
        self.assertEqual((first["commit_status"], repeated["commit_status"]), ("confirmed_committed", "confirmed_committed"))
        self.assertEqual(repeated["controller_generation"], 1)
        self.assertEqual(fixture["events"].read_bytes(), log)
        events = [json.loads(line)["event_type"] for line in log.decode("utf-8").splitlines()]
        self.assertEqual(sorted({event for event in events if event.startswith("handoff_")}), ["handoff_activated", "handoff_prepared"])

    def test_reg_05_controller_generation_mismatch_writes_no_control_event(self) -> None:
        fixture = self.v1_fixture()
        log = fixture["events"].read_bytes()
        rejected = self.activate(fixture, request_id="REQ-V1-WRONG-GENERATION", generation=1)
        self.assertNotEqual(rejected["check_status"], "pass")
        self.assertEqual(rejected["commit_status"], "not_attempted")
        self.assertEqual(fixture["events"].read_bytes(), log)

    def test_reg_06_v1_runtime_shared_doctor_and_lite_are_unchanged_since_097c952(self) -> None:
        protected = [
            "src/managing_long_task_context/handoff.py", "src/managing_long_task_context/__init__.py",
            "src/managing_long_task_context/runtime_identity.py", "src/managing_long_task_context/host_codex_native.py",
            "src/managing_long_task_context/host_claude_native.py", "tests/test_handoff_protocol.py",
            "tests/test_handoff_activation.py", "tests/test_handoff_migration.py", "scripts/context_doctor.py",
            "scripts/context_identity_core.py", "skills/context-lite",
        ]
        completed = _git("diff", "--name-only", V1_BASELINE_COMMIT, "--", *protected)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        allowed_lite_copy = "skills/context-lite/scripts/skill_package.py"
        changed = [path for path in completed.stdout.splitlines() if path]
        self.assertEqual([path for path in changed if path != allowed_lite_copy], [])
        self.assertEqual(
            (ROOT / allowed_lite_copy).read_bytes(),
            (ROOT / "scripts/skill_package.py").read_bytes(),
        )

    def test_reg_07_preflight_source_never_calls_v1_writers_or_writes_files(self) -> None:
        tree = ast.parse((ROOT / "scripts/handoff_preflight.py").read_text(encoding="utf-8"))
        forbidden_calls = {
            "prepare_handoff", "activate_handoff", "cancel_handoff", "publish_contract", "record", "update_item",
            "checkpoint", "externalize_item", "write_text", "write_bytes", "mkdir", "makedirs", "unlink", "rename",
            "replace", "rmtree", "remove", "symlink_to", "touch", "init_binding", "copyfile", "copy2",
        }
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""
                called.add(name)
                is_os_open = isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "os"
                if name == "open" and not is_os_open:
                    mode = node.args[-1] if node.args else next((item.value for item in node.keywords if item.arg == "mode"), None)
                    self.assertIsInstance(mode, ast.Constant)
                    self.assertIn(mode.value, {"r", "rb"})
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"})
        self.assertEqual(called & forbidden_calls, set())
        self.assertNotIn("archive", {name.lower() for name in called})

    def test_reg_08_native_adapters_still_refuse_control_and_archive(self) -> None:
        for adapter in (host_codex_native, host_claude_native):
            self.assertEqual(adapter.capabilities()["evidence"]["real_host_validation"], "NOT_RUN")
            for operation in ("start", "resume", "takeover", "archive"):
                with self.subTest(host=adapter.__name__, operation=operation):
                    result = adapter.request_control(operation)
                    self.assertEqual(result["status"], "unknown")
                    self.assertIs(result["control_granted"], False)
                    self.assertIs(result["launch_allowed"], False)

    def test_reg_09_no_v2_receipt_or_control_event_and_phase2_stays_gated(self) -> None:
        forbidden = ("short-session-handoff/v2", "successor_receipt", "successor-receipt", "source_retirement_receipt",
                     "source-retirement-receipt", "authority-state/v1", "handoff_archived", "handoff_retired")
        sources = [ROOT / "SKILL.md", ROOT / "skill-package.json", ROOT / "scripts/handoff_preflight.py",
                   ROOT / "examples/short_session_handoff.py", *sorted((ROOT / "references").glob("*.md")),
                   *sorted((ROOT / "src/managing_long_task_context").glob("*.py")),
                   *sorted(path for path in (ROOT / "skills/context-strict").rglob("*") if path.is_file() and "__pycache__" not in path.parts)]
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=path.relative_to(ROOT).as_posix(), token=token):
                    self.assertNotIn(token, text)
        self.assertEqual(handoff_module._EVENT_TYPES, frozenset({"handoff_prepared", "handoff_activated", "handoff_cancelled"}))
        plan = PLAN.read_text(encoding="utf-8")
        phase2 = plan.split("### Deferred Phase 2", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(len(re.findall(r"(?m)^[1-5]\. ", phase2)), 5)
        self.assertIn("NOT_RUN/UNKNOWN", (ROOT / "CONTEXT.md").read_text(encoding="utf-8"))

    def test_reg_10_every_outcome_projection_keeps_three_axes_and_archive_closed(self) -> None:
        pairs = [("strict_protocol", "prepare"), ("strict_protocol", "activate"), ("strict_protocol", "status"), ("manual_fallback", "recovery"), (None, None)]
        states = [None, {"check_status": "pass", "commit_status": "confirmed_committed", "controller_generation": 1},
                  {"check_status": "unknown", "commit_status": "confirmed_committed", "controller_generation": 1},
                  {"check_status": "pass", "commit_status": "confirmed_not_committed", "controller_generation": 0},
                  {"check_status": "unknown", "commit_status": "unknown", "controller_generation": None}]
        comparisons = [[], [PREFLIGHT._check("readback_comparison", "pass", None, "x")],
                       [PREFLIGHT._check("readback_comparison", "fail", "PREFLIGHT_READBACK_MISMATCH", "x")],
                       [PREFLIGHT._not_run("readback_comparison")]]
        for mode, stage in pairs:
            for state in states:
                for checks in comparisons:
                    outcome = PREFLIGHT.migration_outcome(mode, stage, checks, state)
                    self.assertEqual(set(outcome), {"information_recovery", "control_transfer", "source_retirement"})
                    self.assertEqual(outcome["source_retirement"], {"status": "not_allowed", "archive_allowed": False, "evidence_refs": []})
                    if (mode, stage) != ("strict_protocol", "status"):
                        self.assertEqual(outcome["control_transfer"], {"status": "unknown", "commit_status": "not_attempted", "controller_generation": None})
                    if outcome["control_transfer"]["status"] == "pass":
                        self.assertEqual((state["check_status"], state["commit_status"]), ("pass", "confirmed_committed"))
                    self.assertNotIn("migration_success", json.dumps(outcome))

    def test_reg_11_skill_requires_mode_three_results_and_no_archive(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for directive in (
            "`migration_mode: strict_protocol`", "`migration_mode: manual_fallback`", "never switch modes silently",
            "`scripts/handoff_preflight.py`", "never\nthat migration, takeover, or archive finished",
            "`information_recovery`, `control_transfer`, and `source_retirement` separately", "never a\nsingle `migration_success`",
            "prove only `material_integrity`", "`objective`,\n`current_state`, `constraints`, `next_action`, and `unresolved_risks`",
            "never proves `control_transfer`", "`control_transfer=unknown` and `source_retirement=not_allowed`",
            "`archive_allowed=false`: never archive the source session", "keep the source session",
            "do not blindly retry", "BLOCKED is only for a concrete external blocker",
        ):
            with self.subTest(directive=directive[:40]):
                self.assertIn(directive, text)
        self.assertEqual((ROOT / "skills/context-strict/SKILL.md").read_text(encoding="utf-8"),
                         text.replace("name: managing-long-task-context", "name: context-strict", 1))

    def test_reg_12_handoff_reference_fixes_strict_and_manual_flows(self) -> None:
        text = (ROOT / "references/handoff.md").read_text(encoding="utf-8")
        for directive in (
            "preflight --stage prepare  -> prepare_handoff", "obtain a real, re-readable thread ID",
            "preflight --stage activate (trusted host verifier) -> activate_handoff", "preflight --stage status -> report three results",
            "never calls a v1 write entry", "| `strict_protocol` | `prepare` |", "| `manual_fallback` | `recovery` |",
            "A Strict step that is UNKNOWN never turns into `manual_fallback`", "Text must be NFC with LF only",
            "`facts` holds 1–64 objects", "`archive_allowed=false` in every mode of this phase",
            "keep the source session", "never blindly retry creation, activation, or archive",
        ):
            with self.subTest(directive=directive[:40]):
                self.assertIn(directive, text)

    def test_reg_13_packaged_example_reports_three_results_without_success_flag(self) -> None:
        package = preflight_tests.shared_package()
        completed = subprocess.run(
            [sys.executable, str(package / "examples/short_session_handoff.py")], cwd=package.parent,
            env={**preflight_tests.os.environ, "PYTHONPATH": str(package / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            text=True, capture_output=True, timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["strict_preflight"], {"prepare": "pass", "activate": "pass", "status": "pass"})
        self.assertEqual(report["strict_migration_results"]["archive_allowed"], False)
        self.assertEqual(report["manual_fallback_results"]["control_transfer"], "unknown")
        self.assertEqual(report["manual_fallback_results"]["source_retirement"], "not_allowed")
        self.assertNotIn("migration_success", completed.stdout)

    def test_reg_14_test_inventory_has_unique_ids_no_gaps_and_bound_failure_modes(self) -> None:
        self.assertEqual(validate_inventory(), [])
        inventory = build_inventory()
        self.assertEqual(inventory["validation_errors"], [])
        self.assertEqual({entry["id"] for entry in inventory["tests"] if entry["test"] is None}, set())
        self.assertEqual({key: value["status"] for key, value in inventory["not_run"].items()}, {"NAT-01": "NOT_RUN", "EVAL-01": "NOT_RUN"})
        broken = dict(INVENTORY)
        broken.pop("UNIT-05")
        with unittest.mock.patch.dict(INVENTORY, clear=True):
            INVENTORY.update(broken)
            self.assertTrue(any("gaps" in error or "has no test" in error or "missing from inventory" in error for error in validate_inventory()))


class RealMigrationScenarioTests(unittest.TestCase):
    maxDiff = None

    def test_scn_01_stale_recovery_entry_after_later_code_commit_is_not_current(self) -> None:
        workspace, material = preflight_tests.ready_workspace(self)
        (workspace.path / "scripts").mkdir()
        (workspace.path / "scripts" / "real_validation.py").write_text("print('landed after verification')\n", encoding="utf-8")
        workspace.commit("merge a later implementation")
        code, report, _, _ = preflight_tests.run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, preflight_tests.check_named(report, "git_revision")["status"]), (2, "stale"))
        workspace.write_context(overrides={"observed_head": workspace.verified_head})
        code, report, _, _ = preflight_tests.run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual((code, preflight_tests.check_named(report, "context_authority")["code"]), (1, "PREFLIGHT_INPUT_INVALID"))

    def test_scn_02_current_repository_entry_needs_no_untracked_validator_input(self) -> None:
        context_text = (ROOT / "CONTEXT.md").read_text(encoding="utf-8")
        frontmatter = PREFLIGHT.parse_frontmatter(context_text)
        plan_relative = PLAN.relative_to(ROOT).as_posix()
        recorded_head = None if PREFLIGHT._null(frontmatter["verified_head"]) else frontmatter["verified_head"]
        check, _ = PREFLIGHT.check_context_authority(
            ROOT, {"plan": plan_relative, "expected_verified_head": recorded_head},
            {"sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest()},
        )
        self.assertEqual((check["status"], check["code"]), ("pass", None), check)
        targets, failure = PREFLIGHT.markdown_links(ROOT, [("CONTEXT.md", context_text)])
        self.assertIsNone(failure)
        tracked = set(_git("ls-files", "--", *targets).stdout.splitlines())
        self.assertEqual(set(targets) - tracked, set())
        self.assertNotIn("方案对话内容.txt", context_text)
        old_plan = PREFLIGHT.parse_frontmatter((ROOT / "docs/superpowers/plans/short-session-handoff.md").read_text(encoding="utf-8"))
        self.assertEqual((old_plan["authority"], old_plan["superseded_by"]), ("SUPERSEDED", plan_relative))

    def test_scn_03_client_thread_id_only_never_transfers_control(self) -> None:
        workspace = preflight_tests.Workspace(preflight_tests.resolved_temporary(self), preflight_tests.shared_package())
        workspace.write_context()
        material = workspace.write_material()
        argv = workspace.arguments(material, mode="strict_protocol", stage="activate")
        result = preflight_tests.run_strict_host(workspace, argv, state="prepared", verifier="client_thread_id")
        check = preflight_tests.check_named(result["report"], "strict_handoff_state")
        self.assertEqual((result["exit"], check["status"]), (2, "unknown"))
        self.assertEqual(result["report"]["migration_outcome"]["control_transfer"]["status"], "unknown")
        self.assertEqual(result["events_before"], result["events_after"])
        self.assertIs(host_codex_native.request_control("takeover")["control_granted"], False)

    def test_scn_04_material_intact_but_readback_rewritten_fails_information_recovery(self) -> None:
        workspace = preflight_tests.Workspace(preflight_tests.resolved_temporary(self), preflight_tests.shared_package())
        workspace.write_context()
        for name, change in (("trailing-space", lambda value: value + " "), ("case-folded", str.upper)):
            with self.subTest(rewrite=name):
                facts = preflight_tests.standard_facts()
                facts[2]["value"] = change(facts[2]["value"])
                material = workspace.write_material(readback_facts=facts)
                code, report, _, _ = preflight_tests.run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
                self.assertEqual((code, report["material_integrity"]), (1, "pass"))
                self.assertEqual(report["migration_outcome"]["information_recovery"]["status"], "fail")
                self.assertEqual(report["migration_outcome"]["control_transfer"]["status"], "unknown")

    def test_scn_05_manual_recovery_success_leaves_control_unknown_and_source_kept(self) -> None:
        workspace = preflight_tests.Workspace(preflight_tests.resolved_temporary(self), preflight_tests.shared_package())
        workspace.write_context()
        lines = "".join(f"line {index}: recovered context\n" for index in range(1, 26))
        material = workspace.write_material(handoff_text=lines)
        code, report, _, _ = preflight_tests.run_cli(workspace.package, workspace.arguments(material), cwd=workspace.root)
        self.assertEqual(material["handoff"].read_text(encoding="utf-8").count("\n"), 25)
        self.assertEqual((code, report["preflight_status"]), (0, "pass"), report)
        self.assertEqual(preflight_tests.outcome_of(report), ("pass", "unknown", "not_attempted", None, False))
        self.assertEqual(report["migration_outcome"]["source_retirement"]["status"], "not_allowed")
        self.assertIn("keep the source session and do not archive", report["next_readonly_action"])

    def test_scn_06_archive_stays_forbidden_even_after_confirmed_strict_activation(self) -> None:
        workspace = preflight_tests.Workspace(preflight_tests.resolved_temporary(self), preflight_tests.shared_package())
        workspace.write_context()
        material = workspace.write_material()
        result = preflight_tests.run_strict_host(workspace, workspace.arguments(material, mode="strict_protocol", stage="status"),
                                                 state="activated", verifier="trusted")
        report = result["report"]
        self.assertEqual(report["migration_outcome"]["control_transfer"]["status"], "pass")
        self.assertIs(report["archive_allowed"], False)
        self.assertEqual(report["migration_outcome"]["source_retirement"]["status"], "not_allowed")
        self.assertNotIn('"archive_allowed": true', json.dumps(report))
        self.assertIs(host_claude_native.request_control("archive")["control_granted"], False)


if __name__ == "__main__":
    unittest.main()
