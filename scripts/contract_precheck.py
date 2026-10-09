#!/usr/bin/env python3
"""Read-only impact scan, with file-bound unittest discovery on request.

Only explicit output directories receive writes. Discovery subprocesses inherit
the caller's import environment; this script never installs a PYTHONPATH.
"""

import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unittest
import uuid


class PrecheckError(Exception):
    def __init__(self, path, reason):
        self.path = str(path)
        self.reason = str(reason)


def fail(path, reason):
    raise PrecheckError(path, reason)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        fail("arguments", message)


def canonical(path):
    """Resolve aliases, but reject spelling aliases on case-insensitive disks.

    Existing ancestors are checked too, including for not-yet-created outputs.
    System aliases such as macOS /var are resolved before containment checks.
    """
    path = Path(path)
    try:
        path.as_posix().encode("utf-8")
        current = Path(path.anchor)
        for part in path.parts[1:]:
            if part == "..":
                fail(path, "parent traversal is not allowed")
            candidate = current / part
            if os.path.lexists(candidate):
                if part not in os.listdir(current):
                    fail(path, "path spelling differs from disk")
            current = candidate
        return path.resolve()
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        fail(path, exc)


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def arguments(argv):
    parser = Parser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--out-dir")
    args = parser.parse_args(argv)
    if not args.term and not args.path:
        fail("arguments", "at least one --term or --path is required")
    for term in args.term:
        if not term or "\n" in term or "\r" in term:
            fail("--term", "term must be nonempty and contain no newline")
        try:
            term.encode("utf-8")
        except UnicodeError as exc:
            fail("--term", exc)
    if not Path(args.repo).is_absolute():
        fail(args.repo, "repository must be absolute")
    repo = canonical(args.repo)
    if not repo.is_dir():
        fail(repo, "repository is not a directory")
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
    )
    if result.returncode or canonical(result.stdout.rstrip("\n")) != repo:
        fail(repo, "repository must be a Git worktree root")
    paths = []
    for value in args.path:
        if not value:
            fail("--path", "path must be nonempty")
        path = Path(value)
        if not path.is_absolute():
            path = repo / path
        path = canonical(path)
        if not within(path, repo):
            fail(value, "selector escapes repository")
        paths.append(path.relative_to(repo).as_posix())
    out = Path(args.out_dir) if args.out_dir is not None else repo / ".context-reports/contract-precheck"
    if not out.is_absolute():
        fail(out, "output directory must be absolute")
    # Containment is judged after resolution, so report-directory links cannot
    # turn an allowed report path into a source-directory write.
    out = canonical(out)
    reports = repo / ".context-reports"
    if within(out, repo) and not within(out, reports):
        fail(out, "in-repository outputs must be under .context-reports")
    if out.exists() and not out.is_dir():
        fail(out, "output path is not a directory")
    return args, repo, paths, out


def module_hook(tree):
    """Check bindings in module scope, including conditional definitions."""
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "load_tests":
                return True
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "load_tests":
            return True
        if isinstance(node, ast.alias) and (node.asname or node.name) == "load_tests":
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


def scan(repo):
    root = repo / "tests"
    texts = {}
    if not os.path.lexists(root):
        return texts

    def visit(path):
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                fail(path, "symbolic links are not allowed")
            path.as_posix().encode("utf-8")
            if stat.S_ISDIR(info.st_mode):
                # scandir/open must remain observable: disappearing entries and
                # unreadable directories cannot become an empty inventory.
                with os.scandir(path) as entries:
                    children = sorted((Path(entry.path) for entry in entries), key=str)
                for child in children:
                    visit(child)
            elif path == root:
                fail(path, "tests root is not a directory")
            elif path.suffix == ".py":
                if not stat.S_ISREG(info.st_mode):
                    fail(path, "Python source is not a regular file")
                with open(path, encoding="utf-8", newline=None) as stream:
                    # Recheck the opened source, rather than trusting an earlier
                    # stat if the entry changed during traversal.
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        fail(path, "source changed while opening")
                    source = stream.read()
                tree = ast.parse(source, filename=str(path))
                if module_hook(tree):
                    fail(path, "module-level load_tests is not supported")
                texts[path.relative_to(repo).as_posix()] = source
        except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError) as exc:
            fail(path, exc)

    visit(root)
    return texts


def stem(path):
    path = Path(path)
    return path.parent.name if path.name == "__init__.py" else path.stem


def mentions(source, word):
    return bool(word and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", source))


def impact(seeds, texts, tests):
    """Support hits propagate through textual references until a fixed point."""
    affected = set(seeds)
    pending = list(seeds)
    while pending:
        origin = pending.pop()
        if origin in tests:
            continue
        word = stem(origin)
        package = Path(origin).parent if Path(origin).name == "__init__.py" else None
        for path, source in texts.items():
            in_package = package is not None and within(Path(path), package)
            if path not in affected and (in_package or mentions(source, word)):
                affected.add(path)
                pending.append(path)
    return affected & tests


# This code is run with -c so sys.path starts with the repository, exactly like
# `python -m unittest discover -s tests`, rather than the scripts directory.
# Package initializers retain discovery's imports/recursion but contribute no
# tests: they are outside T. See the W1-P2 coordinator's specification ruling.
DISCOVER_CHILD = r'''
import contextlib, io, json, os, sys, unittest
target, phase, marker = sys.argv[1:]
target = os.path.realpath(target)
expected = os.stat(target)
identity = (expected.st_dev, expected.st_ino)
loaded = []
attempted = []
problem = None
class Loader(unittest.TestLoader):
    def _match_path(self, path, full_path, pattern):
        return os.path.realpath(full_path) == target
    def _get_module_from_name(self, name):
        source = self._get_name_from_path(target)
        if name == source:
            attempted.append(name)
        return super()._get_module_from_name(name)
    def loadTestsFromModule(self, module, *args, **kwargs):
        global problem
        source = getattr(module, '__file__', None)
        if source and os.path.basename(source) == '__init__.py':
            return self.suiteClass()
        try:
            actual = os.stat(source)
            pair = (actual.st_dev, actual.st_ino)
        except (OSError, TypeError) as exc:
            problem = str(exc)
            return self.suiteClass()
        loaded.append((os.path.realpath(source), module.__name__))
        if pair != identity:
            problem = 'discovery loaded a different source'
            return self.suiteClass()
        return super().loadTestsFromModule(module, *args, **kwargs)
loader = Loader()
captured = io.StringIO()
with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
    try:
        suite = loader.discover('tests')
        # 3.12 restores _top_level_dir when discover returns. Keep the name
        # observed during discovery, not a name recomputed from restored state.
        module = loaded[0][1] if loaded else (attempted[0] if attempted else None)
        # Failed import of the selected entry becomes unittest's failed test;
        # an unreachable entry or a failure importing its package is a binding
        # failure. Never run a suite before the source binding is established.
        if problem is None:
            if loaded:
                if len(loaded) != 1 or loaded[0][0] != target:
                    problem = 'discovery loaded extra or different sources'
            elif attempted != [module]:
                problem = 'selected source was not discoverable'
        exit_code = 0
        if problem is None and phase == 'run':
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            exit_code = 0 if result.wasSuccessful() else 1
    except BaseException as exc:
        problem = str(exc) or type(exc).__name__
        module = None
        exit_code = 2
if phase == 'run':
    print(captured.getvalue(), end='')
print(marker + json.dumps({'error': problem, 'module': module, 'exit_code': exit_code}))
'''


def discover(repo, path, phase):
    marker = "PRECHECK-" + uuid.uuid4().hex + ":"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", DISCOVER_CHILD, path, phase, marker],
        cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="backslashreplace",
    )
    output, separator, metadata = result.stdout.rpartition(marker)
    if result.returncode or not separator:
        fail(path, "discovery subprocess failed: " + result.stderr)
    try:
        value = json.loads(metadata)
    except ValueError:
        fail(path, "invalid discovery result")
    if value["error"] is not None:
        fail(path, value["error"])
    return value, output + result.stderr


def precheck(argv):
    args, repo, paths, out = arguments(argv)
    texts = scan(repo)
    tests = {path for path in texts if fnmatch.fnmatchcase(Path(path).name, "test*.py")}
    terms = []
    selected = set()
    for term in sorted(set(args.term)):
        hits = []
        seeds = set()
        for path, source in sorted(texts.items()):
            for line, text in enumerate(source.split("\n"), 1):
                if term in text:
                    seeds.add(path)
                    hits.append({"file": path, "line": line, "text": text})
        selected.update(impact(seeds, texts, tests))
        terms.append({"term": term, "hits": hits})
    path_results = []
    for path in sorted(set(paths)):
        seeds = {path} if path in texts else set()
        seeds.update(p for p, source in texts.items() if mentions(source, stem(path)))
        affected = impact(seeds, texts, tests)
        selected.update(affected)
        path_results.append({"path": path, "tests": sorted(affected)})
    files = sorted(selected)
    loader = unittest.TestLoader()
    loader._top_level_dir = str(repo / "tests")
    modules = [loader._get_name_from_path(str(repo / path)) for path in files]
    value = {"status": "ok", "terms": terms, "paths": path_results,
             "inventory": {"tests": sorted(tests), "support": sorted(set(texts) - tests)},
             "test_files": files, "test_modules": modules}
    if args.run:
        # Complete every preflight before any log directory creation or test run.
        bindings = [discover(repo, path, "bind")[0] for path in files]
        value["test_modules"] = [binding["module"] for binding in bindings]
        runs = []
        if files:
            out.mkdir(parents=True, exist_ok=True)
        for index, (path, binding) in enumerate(zip(files, bindings)):
            execution, log = discover(repo, path, "run")
            log_path = out / ("%04d.log" % index)
            log_path.write_text(log, encoding="utf-8")
            runs.append({"file": path, "module": binding["module"],
                         "exit_code": execution["exit_code"], "log_file": str(log_path)})
        value["run"] = runs
        if any(run["exit_code"] for run in runs):
            value["status"] = "failed"
    return value


def main(argv=None):
    try:
        value = precheck(sys.argv[1:] if argv is None else argv)
    except PrecheckError as exc:
        # Escaping all separators also protects the one-line diagnostic against
        # unusual filenames, multiline parser messages and discovery tracebacks.
        path = ascii(exc.path)[1:-1]
        reason = ascii(exc.reason)[1:-1]
        print("contract_precheck.py: error: %s: %s" % (path, reason), file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, UnicodeError, RecursionError) as exc:
        print("contract_precheck.py: error: inputs: " + ascii(str(exc))[1:-1], file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
