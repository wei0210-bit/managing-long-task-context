"""Synchronize the generated doctor tools from their maintained root sources."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = (
    "context_doctor.py",
    "context_experience.py",
    "context_identity_core.py",
    "skill_package.py",
    "context_usage.py",
)


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def sync() -> None:
    strict = ROOT / "skills" / "context-strict"
    lite = ROOT / "skills" / "context-lite"
    for name in TOOLS:
        source = ROOT / "scripts" / name
        _copy(source, strict / "scripts" / name)
        _copy(source, lite / "scripts" / name)
    _copy(ROOT / "scripts" / "context_identity_core.py", ROOT / "src" / "managing_long_task_context" / "_identity_core.py")
    _copy(ROOT / "scripts" / "context_identity_core.py", strict / "src" / "managing_long_task_context" / "_identity_core.py")
    _copy(ROOT / "scripts" / "context_experience.py", ROOT / "src" / "managing_long_task_context" / "_experience_store.py")
    _copy(ROOT / "scripts" / "context_experience.py", strict / "src" / "managing_long_task_context" / "_experience_store.py")
    _copy(ROOT / "assets" / "experience-candidate.schema.json", lite / "assets" / "experience-candidate.schema.json")
    _copy(ROOT / "examples" / "experience_candidates.py", lite / "examples" / "experience_candidates.py")
    _copy(ROOT / "tests" / "test_context_experience_cli.py", lite / "tests" / "test_context_experience_cli.py")
    _copy(ROOT / "tests" / "test_context_lite_handoff.py", lite / "tests" / "test_context_lite_handoff.py")
    _copy(ROOT / "tests" / "test_context_lite_validator.py", lite / "tests" / "test_context_lite_validator.py")
    for package in (lite, strict):
        _copy(ROOT / "tests/test_context_usage.py", package / "tests/test_context_usage.py")
        _copy(ROOT / "references/context-usage.md", package / "references/context-usage.md")


if __name__ == "__main__":
    sync()
