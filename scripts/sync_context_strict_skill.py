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
    Path("assets/rule-execution.schema.json"),
    Path("examples/strict_completion.py"),
    Path("examples/truth_source_contract.py"),
    Path("examples/experience_review.py"),
    Path("examples/experience_candidates.py"),
    Path("examples/rule_execution.py"),
    Path("examples/experience_rule_gate.py"),
    Path("examples/independent_validation.py"),
    Path("references/production-failure-patterns.md"),
    Path("references/independent-validation.md"),
    Path("references/runtime-identity.md"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("src/managing_long_task_context/truth_sources.py"),
    Path("src/managing_long_task_context/runtime_identity.py"),
    Path("src/managing_long_task_context/_identity_core.py"),
    Path("src/managing_long_task_context/_experience_store.py"),
    Path("src/managing_long_task_context/experience.py"),
    Path("src/managing_long_task_context/rule_execution.py"),
    Path("tests/test_context.py"),
    Path("tests/test_completion_upgrade.py"),
    Path("tests/test_dynamic_context_scenario.py"),
    Path("tests/test_evidence.py"),
    Path("tests/test_production_feedback.py"),
    Path("tests/test_truth_sources.py"),
    Path("tests/test_runtime_identity.py"),
    Path("tests/test_context_doctor.py"),
    Path("tests/test_context_experience_cli.py"),
    Path("tests/test_experience_review.py"),
    Path("tests/test_rule_execution.py"),
    Path("tests/test_experience_rule_gate.py"),
    Path("tests/test_independent_validation.py"),
    Path("tests/fixtures/truth_source_pilot.md"),
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

    print(f"Synchronized Context Strict to {DESTINATION}")


if __name__ == "__main__":
    sync()
