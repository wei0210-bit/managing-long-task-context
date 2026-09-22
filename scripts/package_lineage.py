#!/usr/bin/env python3
"""Read-only package lineage report. Never writes files or changes build gates."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_REF = "origin/main"
GIT_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")


def package_lineage_report(
    repo: str | Path,
    source_revision: str,
    *,
    confirmed_local: bool = False,
) -> dict[str, Any]:
    text = "" if source_revision is None else str(source_revision).strip()
    if not text:
        return _result("fail", ["PACKAGE_LINEAGE_MISSING"], source_revision)
    if text.startswith("local:"):
        if confirmed_local:
            return _result("pass", [], source_revision)
        return _result("warn", ["PACKAGE_LINEAGE_LOCAL_UNCONFIRMED"], source_revision)
    sha = text[4:] if text.startswith("git:") else ""
    if GIT_SHA.fullmatch(sha):
        return _git_lineage(repo, sha, source_revision)
    return _result("unknown", ["PACKAGE_LINEAGE_UNRESOLVED"], source_revision)


def _git_lineage(repo: str | Path, sha: str, source_revision: str) -> dict[str, Any]:
    parsed = _run_git(repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
    if parsed is None or parsed.returncode != 0:
        return _result("unknown", ["PACKAGE_LINEAGE_UNRESOLVED"], source_revision)
    full_sha = parsed.stdout.strip()
    if not full_sha:
        return _result("unknown", ["PACKAGE_LINEAGE_UNRESOLVED"], source_revision)
    ancestry = _run_git(repo, ["merge-base", "--is-ancestor", full_sha, DEFAULT_REF])
    if ancestry is None or ancestry.returncode not in {0, 1}:
        return _result("unknown", ["PACKAGE_LINEAGE_UNRESOLVED"], source_revision)
    if ancestry.returncode == 0:
        return _result("pass", [], source_revision)
    return _result("fail", ["PACKAGE_LINEAGE_NOT_ON_DEFAULT"], source_revision)


def _run_git(repo: str | Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _result(status: str, codes: list[str], source_revision: str) -> dict[str, Any]:
    return {
        "status": status,
        "codes": list(codes),
        "source_revision": source_revision,
        "default_ref": DEFAULT_REF,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--confirm-local", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = package_lineage_report(
        args.repo,
        args.source_revision,
        confirmed_local=args.confirm_local,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
