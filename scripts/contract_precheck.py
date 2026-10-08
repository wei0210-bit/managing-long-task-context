#!/usr/bin/env python3
"""Read test references before sealing a contract; optionally run affected modules.

Terms are literal, case-sensitive substrings. Paths map through their filename
stem as a whole word, including imports, comments and string mentions. Results
are sorted and repository-relative; line numbers are one-based. No matches is
an ordinary successful scan. A failed test is recorded in JSON (status=failed),
while the command still exits zero; invalid inputs exit 2 without JSON.

--run defaults to .context-reports/contract-precheck for logs and disables Python
bytecode writes. Executed tests retain their own behavior and permissions; this
tool does not sandbox test code or undo writes performed by the tests themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    if not args.repo.is_absolute():
        parser.error("--repo must be absolute")
    if not args.term and not args.path:
        parser.error("at least one --term or --path is required")
    if any(not term for term in args.term):
        parser.error("--term must not be empty")
    args.repo = args.repo.resolve()
    git_env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_")}
    try:
        check = subprocess.run(["git", "-C", str(args.repo), "rev-parse", "--show-toplevel"],
                               env=git_env, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        parser.error(f"cannot inspect Git repository: {exc}")
    if check.returncode or Path(check.stdout.strip()).resolve() != args.repo:
        parser.error("--repo must be the root of a Git working tree")
    for raw in args.path:
        path = Path(raw)
        if not raw or ".." in path.parts:
            parser.error("--path must be a nonempty repository-local file path")
        resolved = (args.repo / path).resolve()
        if not resolved.is_relative_to(args.repo) or not path.stem:
            parser.error("--path must stay inside --repo and name a file")
    if args.out_dir is None:
        args.out_dir = args.repo / ".context-reports/contract-precheck"
    elif not args.out_dir.is_absolute():
        parser.error("--out-dir must be absolute")
    args.out_dir = args.out_dir.resolve()
    if args.out_dir.is_relative_to(args.repo):
        relative = args.out_dir.relative_to(args.repo)
        if not relative.parts or relative.parts[0] != ".context-reports":
            parser.error("--out-dir inside the repository must be under .context-reports/")
    if args.out_dir.exists() and not args.out_dir.is_dir():
        parser.error("--out-dir must be a directory")
    return parser, args


def test_files(repo):
    """Inventory tests explicitly: never silently skip links or listing errors."""
    tests_dir = repo / "tests"
    try:
        root_mode = tests_dir.lstat().st_mode
    except FileNotFoundError:
        return []  # An absent tests directory remains an ordinary empty scan.
    if stat.S_ISLNK(root_mode):
        raise ValueError(f"{tests_dir}: symlink is not allowed")
    if not stat.S_ISDIR(root_mode):
        raise ValueError(f"{tests_dir}: tests root must be a directory")
    pending = [tests_dir]
    candidates = []
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            paths = sorted(directory / entry.name for entry in entries)
        for path in paths:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"{path}: symlink is not allowed")
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif path.name.startswith("test_") and path.suffix == ".py":
                if not stat.S_ISREG(mode):
                    raise ValueError(f"{path}: test must be a regular file")
                candidates.append(path)
    return sorted(candidates)


def scan(repo, terms, paths):
    """Collect literal lines and the union of affected test modules."""
    files = []
    for path in test_files(repo):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        files.append((path.relative_to(repo).as_posix(), lines))
    term_results = []
    path_results = []
    affected = set()
    for term in terms:
        hits = []
        for filename, lines in files:
            for number, line in enumerate(lines, start=1):
                if term in line:
                    hits.append({"file": filename, "line": number, "text": line})
                    affected.add(filename)
        term_results.append({"term": term, "hits": hits})
    for raw in paths:
        name = re.compile(r"(?<!\w)" + re.escape(Path(raw).stem) + r"(?!\w)")
        tests = [filename for filename, lines in files
                 if any(name.search(line) for line in lines)]
        affected.update(tests)
        path_results.append({"path": raw, "tests": tests})
    return {"status": "ok", "terms": term_results, "paths": path_results,
            "test_modules": [Path(filename).with_suffix("").as_posix().replace("/", ".")
                             for filename in sorted(affected)]}


def run_modules(repo, modules, out_dir):
    results = []
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo), str(repo / "src"), str(repo / "tests"), env.get("PYTHONPATH", "")])
    for module in modules:
        out_dir.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix=module + "-", suffix=".log", dir=out_dir)
        with os.fdopen(fd, "wb") as stream:
            completed = subprocess.run([sys.executable, "-B", "-m", "unittest", module],
                                       cwd=repo, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT)
        results.append({"module": module, "exit_code": completed.returncode,
                        "log_file": filename})
    return results


def main(argv=None):
    parser, args = parse_arguments(argv)
    try:
        result = scan(args.repo, args.term, args.path)
        if args.run:
            result["run"] = run_modules(args.repo, result["test_modules"], args.out_dir)
            if any(entry["exit_code"] != 0 for entry in result["run"]):
                result["status"] = "failed"
    except (OSError, UnicodeError, ValueError) as exc:
        # Operational failures must name the affected path on one stderr line,
        # without argparse's usage banner or any partial JSON on stdout.
        message = str(exc).replace("\r", "\\r").replace("\n", "\\n")
        print(f"contract_precheck.py: error: {message}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
