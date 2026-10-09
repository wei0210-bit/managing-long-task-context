"""Public CLI acceptance tests; all repositories and oracles are disposable.

The three independent expectations distinguish executed definitions from selected
entry files. The loader oracle and real discover command run in fresh interpreters;
neither imports the CLI. File identity is always a device/inode pair.
"""

import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import tokenize
import unittest


SCRIPT = Path(os.environ.get(
    "PRECHECK_SCRIPT_UNDER_TEST",
    str(Path(__file__).resolve().parents[1] / "scripts" / "contract_precheck.py"),
)).absolute()
HOOK_NAME = "load" + "_tests"

# This program records unittest's actual suites, including imported TestCases.
# It writes a separate result file because imported modules may print to stdout.
LOADER_ORACLE = r'''
import inspect, json, os, pathlib, unittest
records, modules = [], []
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item
class Loader(unittest.TestLoader):
    def loadTestsFromModule(self, module, *args, **kwargs):
        suite = super().loadTestsFromModule(module, *args, **kwargs)
        source = getattr(module, '__file__', None)
        if source:
            modules.append(os.path.realpath(source))
        for case in cases(suite):
            token = getattr(case, 'TOKEN', None)
            if token is not None:
                records.append({'token': token, 'loaded_from': source,
                                'loaded_name': module.__name__,
                                'defined_in': inspect.getsourcefile(type(case))})
        return suite
loader = Loader()
error = None
try:
    loader.discover('tests')
except ImportError as exc:
    error = str(exc)
pathlib.Path(os.environ['ORACLE_RESULT']).write_text(json.dumps(
    {'records': records, 'modules': modules, 'discover_error': error,
     'loader_errors': loader.errors}), encoding='utf-8')
'''


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="precheck-acceptance-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "Repo"
        self.repo.mkdir()
        self.trace = self.base / "trace"
        self.out = self.base / "logs"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        # Fixture controls explicitly choose their inherited search path. The CLI
        # must preserve this environment, rather than installing another model.
        self.env.pop("PYTHONPATH", None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["FIXTURE_TRACE"] = str(self.trace)
        self.command(["git", "init", "-q", str(self.repo)])

    def command(self, argv, env=None):
        return subprocess.run(argv, cwd=str(self.repo), env=env or self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="backslashreplace",
                              timeout=45)

    def write(self, relative, content=""):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        return target

    def source(self, fail=True, token="LOCAL", marker="NEEDLE", name="Case"):
        return textwrap.dedent('''\
            import os
            import unittest
            # {marker}
            # Attach the loader's actual entry to each case without changing the
            # suite. In particular, a helper's definition file is not its entry.
            if not getattr(unittest.TestLoader, '_fixture_entry_traced', False):
                original_load = unittest.TestLoader.loadTestsFromModule
                def traced_load(loader, module, *args, **kwargs):
                    suite = original_load(loader, module, *args, **kwargs)
                    def attach(items):
                        for item in items:
                            if isinstance(item, unittest.TestSuite):
                                attach(item)
                            else:
                                item._fixture_entry = module.__file__
                    attach(suite)
                    return suite
                unittest.TestLoader.loadTestsFromModule = traced_load
                unittest.TestLoader._fixture_entry_traced = True
            class {name}(unittest.TestCase):
                TOKEN = {token!r}
                def test_observed(self):
                    with open(os.environ['FIXTURE_TRACE'], 'a', encoding='utf-8') as stream:
                        stream.write(self.TOKEN + '\\t' + os.path.realpath(__file__) + '\\t'
                                     + self.id() + '@' + str(os.getpid()) + '\\t'
                                     + os.path.realpath(self._fixture_entry) + '\\n')
                    self.assertEqual({fail!r}, False)
        ''').format(marker=marker, name=name, token=token, fail=fail)

    def make_test(self, relative="tests/test_local.py", **kwargs):
        return self.write(relative, self.source(**kwargs))

    def identity(self, value):
        path = Path(value)
        if not path.is_absolute():
            path = self.repo / path
        info = path.stat()
        return info.st_dev, info.st_ino

    def identities(self, paths):
        return {self.identity(path) for path in paths}

    def rows(self):
        if not self.trace.exists():
            return []
        return [line.split("\t") for line in self.trace.read_text(encoding="utf-8").splitlines()]

    def reset_trace(self):
        self.trace.write_text("", encoding="utf-8")

    def git_status(self):
        result = self.command(["git", "status", "--porcelain", "--untracked-files=all"])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def cli(self, *args, run=False, default_out=False, raw=False, launcher=None):
        argv = [sys.executable, "-B", str(SCRIPT)]
        if launcher is not None:
            argv = [sys.executable, "-B", "-c", launcher, str(SCRIPT)]
        if not raw:
            argv += ["--repo", str(self.repo)]
            if not default_out:
                argv += ["--out-dir", str(self.out)]
        if run:
            argv.append("--run")
        argv += list(args)
        return self.command(argv)

    def output(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        self.assertEqual(list(value), sorted(value), "JSON keys must be sorted")
        return value

    def inventory(self, value, tests, support=()):
        entries = value["inventory"]
        self.assertEqual(set(entries), {"tests", "support"})
        for kind, expected in (("tests", tests), ("support", support)):
            self.relative_paths(entries[kind])
            self.assertEqual(entries[kind], sorted(entries[kind]))
            self.assertEqual(len(entries[kind]), len(expected))
            self.assertEqual(self.identities(entries[kind]), self.identities(expected))
        return self.identities(entries["tests"] + entries["support"])

    def selected(self, value, expected):
        self.relative_paths(value["test_files"])
        self.assertEqual(value["test_files"], sorted(value["test_files"]))
        self.assertEqual(len(value["test_files"]), len(expected))
        self.assertEqual(self.identities(value["test_files"]), self.identities(expected))

    def relative_paths(self, paths):
        for value in paths:
            self.assertIsInstance(value, str)
            path = Path(value)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertEqual(value, path.as_posix())

    def assert_fail_closed(self, result, before, out=None, trace_empty=True):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertRegex(result.stderr.rstrip("\n"),
                         r"^contract_precheck\.py: error: .+: .+$")
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((out or self.out).exists(), "failed validation created logs")
        if trace_empty:
            self.assertEqual(self.rows(), [], "validation executed a test")
        self.assertEqual(self.git_status(), before)
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def closed(self, *args, launcher=None, raw=False, out=None):
        self.reset_trace()
        before = self.git_status()
        result = self.cli(*args, run=True, raw=raw, launcher=launcher)
        self.assert_fail_closed(result, before, out=out)
        return result

    def oracles(self, definitions, loaded, error=False, should_fail=True):
        """O3 is the handwritten set supplied by each layout, never a walk."""
        self.reset_trace()
        real = self.command([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"])
        expected = {(token, self.identity(path)) for token, path in definitions}
        observed = {(row[0], self.identity(row[1])) for row in self.rows()}
        self.assertEqual(observed, expected, "O1 != O3: " + real.stderr)
        oracle_path = self.base / "oracle.json"
        oracle_env = dict(self.env, ORACLE_RESULT=str(oracle_path))
        probe = self.command([sys.executable, "-B", "-c", LOADER_ORACLE], oracle_env)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        actual = {(record["token"], self.identity(record["defined_in"]))
                  for record in oracle["records"]}
        self.assertEqual(actual, expected, "O2 != O3")
        self.assertEqual(self.identities(record["loaded_from"] for record in oracle["records"]),
                         self.identities(loaded), "O2 loaded_from != O3 entries")
        if error:
            self.assertIsNotNone(oracle["discover_error"], real.stderr)
            self.assertNotEqual(real.returncode, 0)
            self.assertIn("incorrectly imported", real.stderr)
        else:
            self.assertIsNone(oracle["discover_error"])
            self.assertEqual(oracle["loader_errors"], [])
            self.assertEqual(real.returncode != 0, bool(expected) and should_fail, real.stderr)
        self.reset_trace()
        return oracle

    def differential(self, selection, bindings, tests, support=(), fail=True, cli=None):
        definitions = sorted({(token, source) for values in bindings.values()
                              for token, source in values})
        oracle = self.oracles(definitions, selection, should_fail=fail)
        result = self.output((cli or self.cli)("--term", "NEEDLE", run=True))
        inventory = self.inventory(result, tests, support)
        for record in oracle["records"]:
            self.assertIn(self.identity(record["loaded_from"]), inventory)
            self.assertIn(self.identity(record["defined_in"]), inventory)
        self.selected(result, selection)
        executions = result["run"]
        self.assertEqual(len(executions), len(selection))
        self.relative_paths([item["file"] for item in executions])
        self.assertEqual(self.identities(item["file"] for item in executions), self.identities(selection))
        self.assertEqual([item["file"] for item in executions], sorted(item["file"] for item in executions))
        modules_by_entry = {self.identity(record["loaded_from"]): record["loaded_name"]
                            for record in oracle["records"]}
        # These two public arrays correspond by file; child scheduling does not.
        self.assertEqual(result["test_modules"],
                         [modules_by_entry[self.identity(path)] for path in result["test_files"]])
        # The trace records the actual loader entry as well as the definition and
        # PID. Neither JSON sorting nor child execution order establishes binding.
        groups = {}
        for row in self.rows():
            pid = row[2].rsplit("@", 1)[1]
            group = groups.setdefault(pid, {"entries": set(), "sources": set()})
            group["entries"].add(self.identity(row[3]))
            group["sources"].add((row[0], self.identity(row[1])))
        self.assertEqual(len(groups), len(selection), "one subprocess per selected file")
        # Consume exactly one PID group per entry; identical source sets from
        # shared helpers still belong to distinct entries and keep multiplicity.
        groups_by_entry = {}
        for group in groups.values():
            self.assertEqual(len(group["entries"]), 1, "one entry per subprocess")
            entry_id = next(iter(group["entries"]))
            self.assertNotIn(entry_id, groups_by_entry, "entry executed in multiple subprocesses")
            groups_by_entry[entry_id] = group["sources"]
        self.assertEqual(set(groups_by_entry), self.identities(selection))
        for entry in executions:
            entry_id = self.identity(entry["file"])
            sources = next(values for path, values in bindings.items() if self.identity(path) == entry_id)
            expected = {(token, self.identity(source)) for token, source in sources}
            self.assertEqual(groups_by_entry.pop(entry_id), expected, "execution escaped its selected entry")
            self.assertEqual(entry["exit_code"] != 0, fail)
            self.assertEqual(entry["module"], modules_by_entry[entry_id])
            self.assertTrue(Path(entry["log_file"]).is_absolute())
            self.assertTrue(Path(entry["log_file"]).is_file())
            self.assertEqual(self.identity(Path(entry["log_file"]).parent), self.identity(self.out))
        self.assertEqual(groups_by_entry, {}, "unmatched subprocess traces")
        self.assertEqual(result["status"], "failed" if fail else "ok")
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])
        return result

    def shadow_control(self, module, inject_src=False):
        self.reset_trace()
        if inject_src:
            code = "import sys,unittest;sys.path.insert(0,'src');unittest.main(module=None,argv=['control'," + repr(module) + "])"
            args = [sys.executable, "-B", "-c", code]
        else:
            args = [sys.executable, "-B", "-m", "unittest", module]
        result = self.command(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.rows(), "shadow control did not execute")
        self.assertEqual({row[0] for row in self.rows()}, {"SHADOW"})
        self.reset_trace()


class InterfaceTests(FixtureCase):
    def test_literal_hits_and_physical_line_numbers(self):
        self.write("tests/test_hits.py", "# Needle\n# Needle Needle\n# needle\n")
        value = self.output(self.cli("--term", "Needle"))
        hits = value["terms"][0]["hits"]
        self.assertEqual(value["terms"][0]["term"], "Needle")
        self.assertEqual([(h["line"], h["text"]) for h in hits], [(1, "# Needle"), (2, "# Needle Needle")])
        self.assertEqual(self.identities(h["file"] for h in hits), self.identities(["tests/test_hits.py"]))
        self.selected(value, ["tests/test_hits.py"])

    def test_path_mapping_import_and_text_whole_word(self):
        self.write("src/widget.py")
        self.write("tests/test_import.py", "from widget import Thing\n")
        self.write("tests/test_text.py", "# widget appears here\n")
        self.write("tests/test_other.py", "# widgetry _widget widget_\n")
        value = self.output(self.cli("--path", "src/widget.py"))
        self.selected(value, ["tests/test_import.py", "tests/test_text.py"])
        self.assertEqual(self.identities(value["paths"][0]["tests"]),
                         self.identities(["tests/test_import.py", "tests/test_text.py"]))

    def test_p11_test_path_selects_itself(self):
        target = self.make_test(marker="unrelated")
        self.oracles([("LOCAL", "tests/test_local.py")], ["tests/test_local.py"])
        value = self.output(self.cli("--path", "tests/test_local.py", run=True))
        self.inventory(value, [target])
        self.selected(value, [target])
        self.assertEqual(self.identities(item["file"] for item in value["run"]), {self.identity(target)})
        self.assertEqual(self.identities(row[1] for row in self.rows()), {self.identity(target)})
        self.assertNotEqual(value["run"][0]["exit_code"], 0)

    def test_scan_only_has_no_run_key_or_execution(self):
        self.make_test()
        value = self.output(self.cli("--term", "NEEDLE"))
        self.assertNotIn("run", value)
        self.assertEqual(self.rows(), [])
        self.assertFalse(self.out.exists())

    def test_run_success_is_bound_to_file(self):
        path = "tests/test_local.py"
        self.make_test(path, fail=False)
        self.differential([path], {path: [("LOCAL", path)]}, [path], fail=False)

    def test_run_failure_is_bound_to_file(self):
        path = "tests/test_local.py"
        self.make_test(path)
        self.differential([path], {path: [("LOCAL", path)]}, [path])

    def test_default_out_directory(self):
        self.make_test(fail=False)
        value = self.output(self.cli("--term", "NEEDLE", run=True, default_out=True))
        log = Path(value["run"][0]["log_file"])
        self.assertEqual(self.identity(log.parent), self.identity(".context-reports/contract-precheck"))
        self.assertEqual(value["run"][0]["exit_code"], 0)
        self.assertTrue(self.rows())

    def test_absent_tests_is_empty_success(self):
        value = self.output(self.cli("--term", "NEEDLE", run=True))
        self.assertEqual(value["status"], "ok")
        self.inventory(value, [])
        self.selected(value, [])
        self.assertEqual(value["test_modules"], [])
        self.assertEqual(value["run"], [])
        self.assertFalse(self.out.exists())

    def test_modules_use_discover_names(self):
        self.make_test("tests/test_flat.py")
        self.write("tests/pkg/__init__.py")
        self.make_test("tests/pkg/test_nested.py")
        value = self.output(self.cli("--term", "NEEDLE"))
        names = {self.identity("tests/pkg/test_nested.py"): "pkg.test_nested",
                 self.identity("tests/test_flat.py"): "test_flat"}
        self.selected(value, ["tests/pkg/test_nested.py", "tests/test_flat.py"])
        self.assertEqual(value["test_modules"], [names[self.identity(p)] for p in value["test_files"]])

    def test_inventory_includes_support_without_selecting_it(self):
        self.make_test()
        self.write("tests/helpers.py", "# NEEDLE\n")
        self.write("tests/unused.py", "# other\n")
        value = self.output(self.cli("--term", "NEEDLE"))
        self.inventory(value, ["tests/test_local.py"], ["tests/helpers.py", "tests/unused.py"])
        self.selected(value, ["tests/test_local.py"])
        self.assertEqual({h["line"] for h in value["terms"][0]["hits"] if self.identity(h["file"]) == self.identity("tests/helpers.py")}, {1})

    def test_import_error_in_test_is_run_failure(self):
        self.write("tests/test_broken.py", "# NEEDLE\nimport no_such_fixture_module_8371\n")
        value = self.output(self.cli("--term", "NEEDLE", run=True))
        self.selected(value, ["tests/test_broken.py"])
        self.assertEqual(value["status"], "failed")
        self.assertNotEqual(value["run"][0]["exit_code"], 0)
        self.assertTrue(Path(value["run"][0]["log_file"]).is_file())


class DifferentialOracleTests(FixtureCase):
    def reverse_cli(self, *args, **kwargs):
        """A fixture-only CLI shim: reverse children, sorted JSON metadata."""
        shim = r'''
import json, pathlib, subprocess, sys
config = json.loads(sys.argv[1])
child = r"""
import os, sys, unittest
target = os.stat(sys.argv[1])
class Loader(unittest.TestLoader):
    def _match_path(self, path, full_path, pattern):
        source = os.stat(full_path)
        return (source.st_dev, source.st_ino) == (target.st_dev, target.st_ino)
suite = Loader().discover('tests')
result = unittest.TextTestRunner().run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""
out = pathlib.Path(config['out'])
out.mkdir(parents=True, exist_ok=True)
runs = []
for entry in reversed(sorted(config['entries'])):
    completed = subprocess.run([sys.executable, '-B', '-c', child, entry],
                               capture_output=True)
    log = out / (str(len(runs)) + '.log')
    log.write_bytes(completed.stdout + completed.stderr)
    runs.append({'file': entry, 'module': config['entries'][entry],
                 'exit_code': completed.returncode, 'log_file': str(log)})
files = sorted(config['entries'])
print(json.dumps({'inventory': {'tests': sorted(config['tests']),
                               'support': sorted(config['support'])},
                  'test_files': files,
                  'test_modules': [config['entries'][path] for path in files],
                  'run': sorted(runs, key=lambda item: item['file']),
                  'status': 'failed' if any(item['exit_code'] for item in runs) else 'ok'},
                 sort_keys=True))
'''
        config = dict(self.reverse_fixture, out=str(self.out))
        return self.command([sys.executable, "-B", "-c", shim, json.dumps(config)])

    def test_reverse_child_execution_order(self):
        # Include distinct definition sources and two entries sharing a helper;
        # source equality alone cannot distinguish the latter's subprocesses.
        paths = ["tests/test_alpha.py", "tests/pkg/test_beta.py",
                 "tests/test_shared_one.py", "tests/test_shared_two.py"]
        support = ["tests/pkg/__init__.py", "tests/helpers.py"]
        self.write("tests/pkg/__init__.py")
        self.make_test(paths[0], token="ALPHA")
        self.make_test(paths[1], token="BETA")
        self.make_test("tests/helpers.py", token="SHARED")
        for path in paths[2:]:
            self.write(path, "from helpers import Case\n")
        bindings = {paths[0]: [("ALPHA", paths[0])],
                    paths[1]: [("BETA", paths[1])],
                    paths[2]: [("SHARED", "tests/helpers.py")],
                    paths[3]: [("SHARED", "tests/helpers.py")]}
        self.reverse_fixture = {"tests": paths, "support": support,
                                "entries": {paths[0]: "test_alpha", paths[1]: "pkg.test_beta",
                                            paths[2]: "test_shared_one", paths[3]: "test_shared_two"}}
        # Keep this acceptance method red when the product CLI is missing. The
        # shim independently exercises the same binding assertions afterwards.
        self.differential(paths, bindings, paths, support)
        self.differential(paths, bindings, paths, support, cli=self.reverse_cli)
        execution_order = []
        seen_pids = set()
        for row in self.rows():
            pid = row[2].rsplit("@", 1)[1]
            if pid not in seen_pids:
                seen_pids.add(pid)
                execution_order.append(self.identity(row[3]))
        self.assertEqual(execution_order, [self.identity(path) for path in reversed(sorted(paths))])

    def test_flat(self):
        path = "tests/test_flat.py"
        self.make_test(path)
        self.differential([path], {path: [("LOCAL", path)]}, [path])

    def test_f03_name_variants(self):
        selected = ["tests/test.py", "tests/testlegacy.py", "tests/testWidget.py"]
        support = ["tests/Test_x.py", "tests/helper.py"]
        for path in selected + support:
            self.make_test(path)
        self.differential(selected, {p: [("LOCAL", p)] for p in selected}, selected, support)

    def test_nested_packages(self):
        support = ["tests/pkg/__init__.py", "tests/pkg/deep/__init__.py"]
        for path in support:
            self.write(path)
        selected = ["tests/pkg/test_one.py", "tests/pkg/deep/test_two.py"]
        for path in selected:
            self.make_test(path)
        self.differential(selected, {p: [("LOCAL", p)] for p in selected}, selected, support)

    def test_orphan_subdirectory_fails_closed(self):
        self.make_test("tests/orphan/test_hidden.py")
        self.oracles([], [])
        self.closed("--term", "NEEDLE")

    def test_invalid_identifier_fails_closed(self):
        self.make_test("tests/test-bad.py")
        self.oracles([], [])
        self.closed("--term", "NEEDLE")

    def test_binding_failure_precedes_all_execution(self):
        self.make_test("tests/test_aaa.py")
        self.make_test("tests/orphan/test_hidden.py")
        self.oracles([("LOCAL", "tests/test_aaa.py")], ["tests/test_aaa.py"])
        self.closed("--term", "NEEDLE")

    def namespace_layout(self, with_path):
        path = "tests/test_local.py"
        self.make_test(path)
        self.write("src/tests/__init__.py")
        shadow = self.make_test("src/tests/test_local.py", fail=False, token="SHADOW")
        if with_path:
            self.env["PYTHONPATH"] = "src"
        self.shadow_control("tests.test_local", inject_src=not with_path)
        self.differential([path], {path: [("LOCAL", path)]}, [path])
        self.assertNotIn(self.identity(shadow), self.identities(row[1] for row in self.rows()))

    def test_f06_namespace_tests_without_pythonpath(self):
        self.namespace_layout(False)

    def test_f06_namespace_tests_with_src_pythonpath(self):
        self.namespace_layout(True)

    def test_top_level_pythonpath_shadow(self):
        path = "tests/test_flat.py"
        self.make_test(path)
        self.make_test("src/test_flat.py", fail=False, token="SHADOW")
        self.env["PYTHONPATH"] = "src"
        self.shadow_control("test_flat")
        self.differential([path], {path: [("LOCAL", path)]}, [path])

    def test_package_pythonpath_shadow(self):
        path = "tests/pkg/test_flat.py"
        self.write("tests/pkg/__init__.py")
        self.make_test(path)
        self.write("src/pkg/__init__.py")
        self.make_test("src/pkg/test_flat.py", fail=False, token="SHADOW")
        self.env["PYTHONPATH"] = "src"
        self.shadow_control("pkg.test_flat")
        self.differential([path], {path: [("LOCAL", path)]}, [path], ["tests/pkg/__init__.py"])

    def test_p12_package_preimport_shadow_fails_closed(self):
        self.make_test("tests/pkg/test_collision.py")
        self.make_test("src/test_collision.py", fail=False, token="SHADOW")
        self.write("tests/pkg/__init__.py", "import sys\nimport test_collision\nsys.modules[__name__ + '.test_collision'] = test_collision\n")
        self.env["PYTHONPATH"] = "src"
        self.shadow_control("test_collision")
        self.oracles([], [], error=True)
        self.closed("--term", "NEEDLE")

    def test_p08_case_defined_in_helper(self):
        self.make_test("tests/helpers.py")
        self.write("tests/test_wrapper.py", "from helpers import Case\n")
        self.differential(["tests/test_wrapper.py"],
                          {"tests/test_wrapper.py": [("LOCAL", "tests/helpers.py")]},
                          ["tests/test_wrapper.py"], ["tests/helpers.py"])

    def test_p08_support_literal_import_chain(self):
        self.write("tests/helpers.py", "# NEEDLE\nVALUE = 1\n")
        self.write("tests/bridge.py", "from helpers import VALUE\n")
        path = "tests/test_chain.py"
        self.write(path, "from bridge import VALUE\n" + self.source(marker="other"))
        self.differential([path], {path: [("LOCAL", path)]}, [path], ["tests/helpers.py", "tests/bridge.py"])

    def test_package_initialization_hit_selects_all_package_tests(self):
        self.write("tests/pkg/__init__.py", "# NEEDLE\n")
        paths = ["tests/pkg/test_one.py", "tests/pkg/deep/test_two.py"]
        self.write("tests/pkg/deep/__init__.py")
        for path in paths:
            self.make_test(path, marker="other")
        self.differential(paths, {p: [("LOCAL", p)] for p in paths}, paths,
                          ["tests/pkg/__init__.py", "tests/pkg/deep/__init__.py"])

    def test_p09_module_hook_redirect_fails_closed(self):
        self.make_test("tests/redirected.py")
        self.write("tests/test_redirect.py", "# NEEDLE\nimport redirected\ndef " + HOOK_NAME + "(loader, tests, pattern):\n    return loader.loadTestsFromModule(redirected)\n")
        self.oracles([("LOCAL", "tests/redirected.py")], ["tests/redirected.py", "tests/test_redirect.py"])
        self.closed("--term", "NEEDLE")

    def test_p09_package_hook_fails_closed(self):
        self.make_test("tests/pkg/redirected.py")
        self.write("tests/pkg/__init__.py", "# NEEDLE\nfrom . import redirected\ndef " + HOOK_NAME + "(loader, tests, pattern):\n    return loader.loadTestsFromModule(redirected)\n")
        self.oracles([("LOCAL", "tests/pkg/redirected.py")], ["tests/pkg/redirected.py", "tests/pkg/__init__.py"])
        self.closed("--term", "NEEDLE")

    def test_p09_unselected_support_hook_fails_closed(self):
        self.make_test()
        self.write("tests/helpers.py", "def " + HOOK_NAME + "(loader, tests, pattern):\n    return tests\n")
        self.oracles([("LOCAL", "tests/test_local.py")], ["tests/test_local.py"])
        self.closed("--term", "NEEDLE")


class FailClosedFilesystemTests(FixtureCase):
    def restrict(self, path, directory=False):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("ENV-SKIP: root bypasses permission controls")
        original = stat.S_IMODE(path.stat().st_mode)
        path.chmod(0)
        self.addCleanup(path.chmod, original)
        try:
            if directory:
                with os.scandir(path) as entries:
                    list(entries)
            else:
                path.read_bytes()
        except PermissionError:
            return
        self.skipTest("ENV-SKIP: chmod 000 still permits access")

    def test_f01_unreadable_tests_root(self):
        self.make_test()
        self.restrict(self.repo / "tests", directory=True)
        self.closed("--term", "NEEDLE")

    def test_f01_unreadable_nested_directory(self):
        self.make_test()
        self.write("tests/pkg/__init__.py")
        self.restrict(self.repo / "tests/pkg", directory=True)
        self.closed("--term", "NEEDLE")

    def test_f01_hidden_failing_module_has_readable_control(self):
        self.write("tests/pkg/__init__.py")
        self.make_test("tests/pkg/test_hidden.py")
        # Prove the hidden fixture really fails before hiding it.
        self.oracles([("LOCAL", "tests/pkg/test_hidden.py")], ["tests/pkg/test_hidden.py"])
        control = self.command([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"])
        self.assertNotEqual(control.returncode, 0, control.stderr)
        self.assertIn("FAILED", control.stderr)
        self.restrict(self.repo / "tests/pkg", directory=True)
        self.closed("--term", "NEEDLE")

    def test_f01_unreadable_test_file(self):
        path = self.make_test()
        self.restrict(path)
        self.closed("--term", "NEEDLE")

    def test_f01_unreadable_support_file(self):
        self.make_test()
        path = self.write("tests/helpers.py", "# NEEDLE\n")
        self.restrict(path)
        self.closed("--term", "NEEDLE")

    def test_f02_tests_root_directory_link(self):
        external = self.base / "external"
        external.mkdir()
        (external / "test_external.py").write_text(self.source(), encoding="utf-8")
        (self.repo / "tests").symlink_to(external, target_is_directory=True)
        self.closed("--term", "NEEDLE")

    def test_f02_nested_directory_link(self):
        self.make_test()
        self.write("real/test_target.py", self.source())
        (self.repo / "tests/linked").symlink_to(self.repo / "real", target_is_directory=True)
        self.closed("--term", "NEEDLE")

    def test_f02_test_file_link(self):
        self.make_test()
        target = self.write("real.py", self.source())
        (self.repo / "tests/test_link.py").symlink_to(target)
        self.closed("--term", "NEEDLE")

    def test_f02_support_file_link(self):
        self.make_test()
        target = self.write("real.py", "# NEEDLE\n")
        (self.repo / "tests/helpers.py").symlink_to(target)
        self.closed("--term", "NEEDLE")

    def test_f02_dangling_tests_root(self):
        (self.repo / "tests").symlink_to(self.base / "absent")
        self.closed("--term", "NEEDLE")

    def test_f02_dangling_nested_link(self):
        self.make_test()
        (self.repo / "tests/dangling").symlink_to(self.base / "absent")
        self.closed("--term", "NEEDLE")

    def test_f02_link_loop(self):
        self.make_test()
        (self.repo / "tests/loop").symlink_to("loop")
        self.closed("--term", "NEEDLE")

    def test_f02_link_leaves_repository(self):
        self.make_test()
        target = self.base / "outside.py"
        target.write_text(self.source(), encoding="utf-8")
        (self.repo / "tests/test_external.py").symlink_to(target)
        self.closed("--term", "NEEDLE")

    def test_non_utf8_test_content(self):
        self.write("tests/test_bad.py", b"# NEEDLE\n# \xff\n")
        self.closed("--term", "NEEDLE")

    def test_non_utf8_support_content(self):
        self.make_test()
        self.write("tests/helpers.py", b"# \xff\n")
        self.closed("--term", "NEEDLE")

    def test_latin1_coding_declaration_is_rejected(self):
        self.write("tests/test_latin.py", b"# coding: latin-1\n# NEEDLE \xe9\n")
        self.closed("--term", "NEEDLE")

    def test_non_utf8_filename(self):
        self.make_test()
        filename = os.fsencode(self.repo / "tests") + b"/helper_\xff.py"
        try:
            with open(filename, "wb") as stream:
                stream.write(b"# NEEDLE\n")
        except (OSError, UnicodeError) as exc:
            self.skipTest("ENV-SKIP: filesystem rejects non-UTF-8 filename: " + str(exc))
        self.closed("--term", "NEEDLE")

    def test_non_regular_fifo(self):
        self.make_test()
        if not hasattr(os, "mkfifo"):
            self.skipTest("ENV-SKIP: filesystem has no FIFO support")
        os.mkfifo(self.repo / "tests/helpers.py")
        self.closed("--term", "NEEDLE")

    def test_tests_root_regular_file(self):
        self.write("tests", "# NEEDLE\n")
        self.closed("--term", "NEEDLE")

    def vanished(self, event, relative, directory=False):
        self.make_test()
        target = self.repo / relative
        if directory:
            target.mkdir(parents=True)
            self.write(relative + "/.keep")
        else:
            self.write(relative, "# NEEDLE\n")
        pair = self.identity(target)
        marker = self.base / "audit-fired"
        launcher = textwrap.dedent('''\
            import json, os, pathlib, runpy, subprocess, sys
            target = {target!r}
            expected = {pair!r}
            marker = {marker!r}
            fired = False
            def hook(event, args):
                global fired
                if fired or event not in {events!r} or not args:
                    return
                try:
                    info = os.stat(args[0])
                except (OSError, TypeError, ValueError):
                    return
                if (info.st_dev, info.st_ino) != expected:
                    return
                fired = True
                if {directory!r}:
                    os.unlink(os.path.join(target, '.keep'))
                {remove}(target)
                status = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'],
                                        capture_output=True, text=True, check=True).stdout
                pathlib.Path(marker).write_text(json.dumps({{'status': status, 'event': event}}), encoding='utf-8')
            sys.addaudithook(hook)
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name='__main__')
        ''').format(target=str(target), pair=pair, marker=str(marker),
                    events=("os.scandir", "os.listdir") if directory else (event,), directory=directory,
                    remove="os.rmdir" if directory else "os.unlink")
        self.reset_trace()
        before = self.git_status()
        result = self.cli("--term", "NEEDLE", run=True, launcher=launcher)
        self.assertTrue(marker.exists(), "audit hook never fired: " + result.stderr)
        # The hook snapshots immediately after its deletion, before the CLI can
        # change anything; the only allowed status change is the injected loss.
        injected = json.loads(marker.read_text(encoding="utf-8"))
        self.assertNotEqual(before, injected["status"], "fixture deletion was not observable")
        self.assert_fail_closed(result, injected["status"])

    def test_vanish_before_open(self):
        self.vanished("open", "tests/helpers.py")

    def test_vanish_before_directory_listing(self):
        self.vanished("os.scandir", "tests/nested", directory=True)


class LineNumberTests(FixtureCase):
    def physical_lines(self, ending):
        # The separators below remain inside comments, never physical newlines.
        source = "# first\n# A\u2028B\u2029C\u0085D\vE\fF\x1cG\x1dH\x1eI\n# NEEDLE\n"
        payload = source.replace("\n", ending).encode("utf-8")
        self.write("tests/test_lines.py", payload)
        # tokenize sees source after universal-newline decoding, as Python does.
        decoded = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", newline=None).read()
        comments = [token for token in tokenize.generate_tokens(io.StringIO(decoded).readline)
                    if token.type == tokenize.COMMENT and "NEEDLE" in token.string]
        self.assertEqual([token.start[0] for token in comments], [3])
        value = self.output(self.cli("--term", "NEEDLE"))
        hits = value["terms"][0]["hits"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 3)
        self.assertEqual(hits[0]["text"], "# NEEDLE")
        self.assertEqual(self.identity(hits[0]["file"]), self.identity("tests/test_lines.py"))

    def test_f04_lf(self):
        self.physical_lines("\n")

    def test_f04_crlf(self):
        self.physical_lines("\r\n")

    def test_f04_cr(self):
        self.physical_lines("\r")


class ArgumentErrorTests(FixtureCase):
    def test_missing_repo(self):
        self.closed("--term", "NEEDLE", raw=True)

    def test_missing_selector(self):
        self.closed()

    def test_empty_term(self):
        self.closed("--term", "")

    def test_unknown_option(self):
        self.closed("--term", "NEEDLE", "--unknown-option")

    def test_relative_repo(self):
        self.closed("--repo", ".", "--term", "NEEDLE", raw=True)

    def test_repo_not_git_root(self):
        child = self.repo / "child"
        child.mkdir()
        self.closed("--repo", str(child), "--term", "NEEDLE", raw=True)

    def test_path_traversal(self):
        self.closed("--path", "../outside.py")

    def test_absolute_path_escape(self):
        self.closed("--path", str(self.base / "outside.py"))

    def test_empty_path(self):
        self.closed("--path", "")

    def test_relative_out_directory(self):
        self.closed("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir", "logs", raw=True)

    def test_out_directory_inside_source(self):
        self.closed("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir", str(self.repo / "src/logs"), raw=True,
                    out=self.repo / "src/logs")

    def test_out_directory_regular_file(self):
        target = self.base / "file-log"
        target.write_text("existing", encoding="utf-8")
        before = self.git_status()
        result = self.cli("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir", str(target), raw=True, run=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertRegex(result.stderr, r"^contract_precheck\.py: error: .+: .+\n$")
        self.assertEqual(target.read_text(encoding="utf-8"), "existing")
        self.assertEqual(self.git_status(), before)
        self.assertEqual(self.rows(), [])
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def loop(self):
        path = self.repo / "loop"
        path.symlink_to("loop")
        return path

    def test_f05_repo_path_loop(self):
        path = self.loop()
        self.closed("--repo", str(path), "--term", "NEEDLE", raw=True)

    def test_f05_selector_path_loop(self):
        self.loop()
        self.closed("--path", "loop/widget.py")

    def test_f05_out_directory_path_loop(self):
        path = self.loop() / "logs"
        self.closed("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir", str(path), raw=True)

    def test_out_directory_link_escape(self):
        self.make_test()
        self.write("src/.keep")
        (self.repo / ".context-reports").symlink_to("src", target_is_directory=True)
        self.closed("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir",
                    str(self.repo / ".context-reports/logs"), raw=True, out=self.repo / "src/logs")

    def require_case_aliases(self):
        if not (self.base / "rEPO").exists():
            self.skipTest("ENV-SKIP: filesystem is case-sensitive")
        self.assertEqual(self.identity(self.base / "rEPO"), self.identity(self.repo))

    def test_p07_out_directory_case_alias(self):
        self.require_case_aliases()
        self.make_test()
        self.closed("--repo", str(self.repo), "--term", "NEEDLE", "--out-dir",
                    str(self.base / "rEPO/src/logs"), raw=True, out=self.repo / "src/logs")

    def test_p10_selector_case_mismatch(self):
        self.require_case_aliases()
        self.write("src/widget.py")
        self.write("tests/test_widget.py", "# widget\n" + self.source(marker="other"))
        self.assertEqual(self.identity("src/widget.py"), self.identity("src/WIDGET.py"))
        self.closed("--path", "src/WIDGET.py")

    def test_repo_case_alias_is_rejected_or_canonical(self):
        self.require_case_aliases()
        self.make_test()
        before = self.git_status()
        correct = self.cli("--term", "NEEDLE")
        alias = self.cli("--repo", str(self.base / "rEPO"), "--term", "NEEDLE",
                         "--out-dir", str(self.out), raw=True)
        if alias.returncode == 2:
            self.assert_fail_closed(alias, before)
        else:
            self.output(correct)
            self.output(alias)
            self.assertEqual(alias.stdout.encode("utf-8"), correct.stdout.encode("utf-8"))
            self.assertEqual(self.git_status(), before)
            self.assertEqual(self.rows(), [])
            self.assertFalse(self.out.exists())
            self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def test_term_with_newline(self):
        self.make_test()
        self.closed("--term", "NEEDLE\nsecond")


if __name__ == "__main__":
    unittest.main()
