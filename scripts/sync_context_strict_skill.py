#!/usr/bin/env python3
"""Build the installable Context Strict skill from the maintained root sources."""

from __future__ import annotations

import json
import shutil
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "skills" / "context-strict"

COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("assets/truth-source-contract.example.json"),
    Path("assets/experience-candidate.schema.json"),
    Path("assets/experience-validation.schema.json"),
    Path("examples/strict_completion.py"),
    Path("examples/truth_source_contract.py"),
    Path("examples/experience_review.py"),
    Path("examples/experience_candidates.py"),
    Path("references/production-failure-patterns.md"),
    Path("references/runtime-identity.md"),
    Path("references/bot-pipeline-handoff.md"),
    Path("references/agent-role-handoff.md"),
    Path("scripts/coordinator_ops.py"),
    Path("tests/test_coordinator_ops.py"),
    Path("scripts/context_skill_router.py"),
    Path("tests/test_context_skill_router.py"),
    Path("scripts/context_status.py"), Path("tests/test_resume_gate.py"),
    Path("tests/test_ledger_reports.py"),
    Path("scripts/context_search.py"),
    Path("tests/test_context_search.py"),
    Path("tests/test_update_item_verified_at.py"),
    Path("tests/test_brief_rendering.py"),
    Path("scripts/package_lineage.py"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("src/managing_long_task_context/usage_freshness.py"),
    Path("src/managing_long_task_context/project_store.py"),
    Path("src/managing_long_task_context/acceptance.py"),
    Path("tests/test_acceptance_records.py"),
    Path("src/managing_long_task_context/worker_report.py"),
    Path("tests/test_worker_report.py"),
    Path("src/managing_long_task_context/contract_history.py"),
    Path("tests/test_contract_history.py"),
    Path("src/managing_long_task_context/truth_sources.py"),
    Path("src/managing_long_task_context/runtime_identity.py"),
    Path("src/managing_long_task_context/_identity_core.py"),
    Path("src/managing_long_task_context/_experience_store.py"),
    Path("src/managing_long_task_context/experience.py"),
    Path("tests/test_context.py"),
    Path("tests/test_evidence.py"),
    Path("tests/test_production_feedback.py"),
    Path("tests/test_truth_sources.py"),
    Path("tests/test_runtime_identity.py"),
    Path("tests/test_project_store.py"),
    Path("tests/test_context_experience_cli.py"),
    Path("tests/test_experience_review.py"),
    Path("tests/test_experience_cross_checkout.py"),
    Path("tests/fixtures/truth_source_pilot.md"),
)

# Root-only integration tests depend on sibling skill source trees and must not
# remain in the self-contained Strict package after a source-list change.
# Historical package paths removed by STRICT-LEDGER; cleanup of generated copies only.
REMOVED_FILES = (
    'references/orca.md',
    'tests/test_dynamic_context_scenario.py',
    'src/managing_long_task_context/handoff.py',
    'src/managing_long_task_context/host_claude_native.py',
    'src/managing_long_task_context/host_records.py',
    'src/managing_long_task_context/host_codex_native.py',
    'src/managing_long_task_context/host_codex_cli.py',
    'src/managing_long_task_context/rule_execution.py',
    'scripts/handoff_preflight.py',
    'scripts/dispatch_spec.py',
    'scripts/orca_wait.py',
    'scripts/context_usage.py',
    'scripts/contract_precheck.py',
    'references/handoff.md',
    'references/host-codex-cli.md',
    'references/host-native.md',
    'references/context-usage.md',
    'references/preseal-checks.md',
    'references/independent-validation.md',
    'docs/agents/standing-authorizations.json',
    'tests/test_handoff_activation.py',
    'tests/test_handoff_codex_cli.py',
    'tests/test_handoff_host_distribution.py',
    'tests/test_handoff_writes.py',
    'tests/test_handoff_protocol.py',
    'tests/test_handoff_spec.py',
    'tests/test_handoff_distribution.py',
    'tests/test_handoff_claude_native.py',
    'tests/test_handoff_preflight.py',
    'tests/test_handoff_gate_combinations.py',
    'tests/test_handoff_codex_native.py',
    'tests/test_handoff_host_records.py',
    'tests/test_handoff_process_recovery.py',
    'tests/test_handoff_migration.py',
    'tests/test_handoff_concurrency.py',
    'tests/handoff_process_fixture.py',
    'tests/handoff_gate_fixtures.py',
    'tests/handoff_codex_fixture.py',
    'tests/handoff_test_authority.py',
    'tests/handoff_spec.py',
    'tests/handoff_migration_fixture.py',
    'tests/handoff_host_records_fixture.py',
    'tests/test_real_migration_regression.py',
    'tests/test_rule_execution.py',
    'tests/test_experience_rule_gate.py',
    'tests/test_independent_validation.py',
    'tests/test_contract_precheck_outdir.py',
    'tests/test_contract_precheck.py',
    'tests/test_dispatch_spec.py',
    'tests/test_orca_wait.py',
    'tests/test_context_usage.py',
    'tests/test_coordinator_lease.py',
    'tests/test_completion_upgrade.py',
    'tests/test_real_validation.py',
    'scripts/real_validation.py',
    'examples/rule_execution.py',
    'examples/experience_rule_gate.py',
    'examples/independent_validation.py',
    'examples/short_session_handoff.py',
    'assets/rule-execution.schema.json',
    'tests/test_context_doctor.py',
    'tests/test_experience_distribution.py',
)



def distributed_skill_text() -> str:
    source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    expected = "name: managing-long-task-context"
    if expected not in source:
        raise RuntimeError(f"root SKILL.md is missing expected frontmatter: {expected}")
    return source.replace(expected, "name: context-strict", 1)


def distributed_package_declaration() -> dict[str, object]:
    source = json.loads((ROOT / "skill-package.json").read_text(encoding="utf-8"))
    if source.get("skill_name") != "managing-long-task-context":
        raise RuntimeError("root skill-package.json has an unexpected skill_name")
    source["skill_name"] = "context-strict"
    return source


def sync() -> None:
    runpy.run_path(str(ROOT / "scripts/sync_context_tools.py"))["sync"]()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "SKILL.md").write_text(distributed_skill_text(), encoding="utf-8")
    (DESTINATION / "skill-package.json").write_text(
        json.dumps(distributed_package_declaration(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for relative_path in COPIED_FILES:
        source = ROOT / relative_path
        destination = DESTINATION / relative_path
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for relative_path in REMOVED_FILES:
        stale = DESTINATION / relative_path
        if stale.exists() or stale.is_symlink():
            stale.unlink()

    print(f"Synchronized Context Strict to {DESTINATION}")


if __name__ == "__main__":
    sync()
