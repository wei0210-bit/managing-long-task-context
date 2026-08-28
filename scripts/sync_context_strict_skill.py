#!/usr/bin/env python3
"""Build the installable Context Strict skill from the maintained root sources."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "skills" / "context-strict"

COPIED_FILES = (
    Path("pyproject.toml"),
    Path("assets/task-contract.example.json"),
    Path("examples/strict_completion.py"),
    Path("src/managing_long_task_context/__init__.py"),
    Path("src/managing_long_task_context/evidence.py"),
    Path("tests/test_context.py"),
    Path("tests/test_evidence.py"),
)


def distributed_skill_text() -> str:
    source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    expected = "name: managing-long-task-context"
    if expected not in source:
        raise RuntimeError(f"root SKILL.md is missing expected frontmatter: {expected}")
    return source.replace(expected, "name: context-strict", 1)


def sync() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "SKILL.md").write_text(distributed_skill_text(), encoding="utf-8")

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
