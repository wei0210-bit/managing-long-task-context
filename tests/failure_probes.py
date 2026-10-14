"""Cold-start failure-path probes, with entry-specific expectations."""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TRACEBACK = 'Traceback (most recent call last)'


@dataclass
class Variant:
    category: str
    name: str
    kind: str
    make: Callable


@dataclass
class CliAdapter:
    build_argv: Callable
    cwd: Callable
    env: dict
    timeout: float = 30

    def run(self, root):
        argv = [str(arg) for arg in self.build_argv(root)]
        cwd = str(self.cwd(root))
        result = dict(argv=argv, cwd=cwd, exit_code=None, stdout='', stderr='',
                      timed_out=False, adapter_error=None)
        try:
            process = subprocess.run(argv, cwd=cwd, env=dict(self.env),
                                     capture_output=True, timeout=self.timeout)
            result.update(exit_code=process.returncode, stdout=_text(process.stdout),
                          stderr=_text(process.stderr))
        except subprocess.TimeoutExpired as exc:
            result.update(timed_out=True, stdout=_text(exc.stdout), stderr=_text(exc.stderr))
        except OSError as exc:
            result['adapter_error'] = str(exc)
        return result


def _text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''


@dataclass
class Entry:
    name: str
    scaffold: Callable
    place: Callable
    adapter: CliAdapter
    writable: tuple
    expect: Callable
    categories: dict
    exclude: dict = field(default_factory=dict)
    known: dict = field(default_factory=dict)
    pending: set = field(default_factory=set)


def snapshot(root):
    """Observe final state without traversing links or opening unreadable paths."""
    root = Path(root)
    records = {}

    def record(path):
        info = path.lstat()
        row = dict(type=stat.S_IFMT(info.st_mode), mode=stat.S_IMODE(info.st_mode),
                   size=info.st_size)
        if stat.S_ISLNK(info.st_mode):
            row['link'] = os.readlink(str(path))
        elif stat.S_ISREG(info.st_mode):
            if not info.st_mode & 0o444:
                row['unreadable'] = True
            else:
                try:
                    row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                except PermissionError:
                    row['unreadable'] = True
        elif stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o444:
            row['unreadable'] = True
        records[path.relative_to(root).as_posix()] = row
        return row

    record(root)

    def walk_error(exc):
        path = Path(exc.filename)
        records[path.relative_to(root).as_posix()]['unreadable'] = True

    for directory, dirs, files in os.walk(str(root), followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(directory) / name
            row = record(path)
            if name in dirs and (row.get('unreadable') or stat.S_ISLNK(row['type'])):
                dirs.remove(name)
    return records


def restore_permissions(root):
    root = Path(root)
    if root.is_symlink():
        return
    root.chmod(0o700)
    for directory, dirs, files in os.walk(str(root), followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if not stat.S_ISLNK(mode):
                path.chmod(0o700 if stat.S_ISDIR(mode) else 0o600)


def cleanup(root):
    restore_permissions(root)
    shutil.rmtree(str(root))


def changed_paths(before, after, writable):
    def allowed(path):
        return any(path == prefix.rstrip('/') or path.startswith(prefix.rstrip('/') + '/')
                   for prefix in writable)
    return sorted(path for path in before.keys() | after.keys()
                  if not allowed(path) and before.get(path) != after.get(path))


def processed(target, result, category):
    label = target.relative_to(Path(result['cwd'])).as_posix()
    try:
        payload = json.loads(result['stdout'])
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    paths = {row.get('path') for key in ('results', 'skipped')
             for row in payload.get(key, []) if isinstance(row, dict)}
    if label in paths:
        return True
    if category == 'malformed_json' and (target.parent / 'events.jsonl').relative_to(
            Path(result['cwd'])).as_posix() in paths:
        return True
    error = str(payload.get('error', '')) + result['stderr']
    return label in error or str(target) in error


def run_variant(entry, variant, temp_dir=None):
    row = dict(category=variant.category, variant=variant.name, target=None,
               verdict='excluded', known=False, pending=variant.name in entry.pending,
               reason=entry.exclude.get(variant.name, ''), exit_code=None, timed_out=False,
               stdout_excerpt='', stderr_excerpt='', baseline={}, argv=[], cwd=None)
    if variant.name in entry.exclude:
        return row
    root = Path(tempfile.mkdtemp(prefix='failure-probe-', dir=temp_dir)).resolve()
    try:
        entry.scaffold(root)
        target = entry.place(variant, root)
        row['target'] = str(target)
        # scaffold -> place -> snapshot -> run -> baselines -> processed -> expect
        before = snapshot(root)
        result = entry.adapter.run(root)
        after = snapshot(root)
        changes = changed_paths(before, after, entry.writable)
        baseline = {'1': TRACEBACK not in result['stdout'] + result['stderr'],
                    '2': not result['timed_out'], '3': not changes}
        row.update(exit_code=result['exit_code'], timed_out=result['timed_out'],
                   stdout_excerpt=result['stdout'][:4000], stderr_excerpt=result['stderr'][:4000],
                   baseline=baseline, argv=result['argv'], cwd=result['cwd'])
        if result['adapter_error']:
            row.update(verdict='adapter_error', reason=result['adapter_error'])
        elif not all(baseline.values()):
            reasons = []
            if not baseline['1']:
                reasons.append('baseline 1: uncaught traceback')
            if not baseline['2']:
                reasons.append('baseline 2: timeout')
            if not baseline['3']:
                reasons.append('baseline 3: changed paths: ' + ', '.join(changes))
            row.update(verdict='fail', reason='; '.join(reasons))
        elif not processed(target, result, variant.category):
            row.update(verdict='vacuous', reason='target was not processed')
        else:
            verdict, reason = entry.expect(variant, target, result)
            row.update(verdict=verdict, reason=reason)
        return row
    finally:
        cleanup(root)


def run(entry, categories=None, temp_dir=None):
    selected = categories or list(entry.categories)
    rows = [run_variant(entry, variant, temp_dir) for category in selected
            for variant in entry.categories[category]]
    return dict(entry=entry.name, created_at=datetime.now(timezone.utc).isoformat(),
                observation_scope='probe tree final state; external and unreadable contents deferred',
                results=rows, counts={verdict: sum(row['verdict'] == verdict for row in rows)
                                    for verdict in ('pass', 'fail', 'vacuous', 'undecided',
                                                    'adapter_error', 'excluded', 'skipped')})


def exit_code(report):
    return int(any(row['verdict'] in ('fail', 'vacuous', 'undecided', 'adapter_error')
                   and (not row['pending'] or row['verdict'] == 'adapter_error'
                        or not all(row['baseline'].values())) for row in report['results']))


def encoding_variants():
    def content(data):
        return lambda path: path.write_bytes(data)
    return [
        Variant('encoding', 'normal-doc', 'file', content(b'probetoken normal\n')),
        Variant('encoding', 'normal-contract', 'file', content(b'{"objective":"probetoken"}\n')),
        Variant('encoding', 'invalid-utf8-contract', 'file', content(b'{"objective":"probetoken \xff"}\n')),
        Variant('encoding', 'invalid-utf8-doc', 'file', content(b'probetoken \xff\xfe\n')),
        Variant('encoding', 'cp1252-doc', 'file', content('probetoken \u20ac \u201cquote\u201d\n'.encode('cp1252'))),
        Variant('encoding', 'bom-doc', 'file', content(b'\xef\xbb\xbfprobetoken BOM\n')),
    ]


def search_scaffold(root):
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    ledger = root / '.prime/context/T'
    ledger.mkdir(parents=True)
    (root / '.prime/search').mkdir()
    (root / 'docs').mkdir()
    (root / 'CONTEXT.md').write_text('probetoken context\n', encoding='utf-8')
    (root / 'docs/a.md').write_text('probetoken document\n', encoding='utf-8')
    (ledger / 'task-contract.json').write_text('{"objective":"probetoken"}\n', encoding='utf-8')
    (ledger / 'snapshot.json').write_text(json.dumps({'items': {'I1': {
        'id': 'I1', 'type': 'observation', 'status': 'active', 'statement': 'probetoken fact'}}}),
        encoding='utf-8')


def search_place(variant, root):
    target = root / ('.prime/context/T/task-contract.json' if variant.name.endswith('contract')
                     else 'docs/a.md')
    variant.make(target)
    return target


def search_expect(variant, target, result):
    try:
        payload = json.loads(result['stdout'])
    except ValueError:
        return 'fail', 'expect: output is not JSON'
    if not isinstance(payload, dict) or result['exit_code'] != 0:
        return 'fail', 'expect: search must return exit 0 and JSON object'
    label = target.relative_to(Path(result['cwd'])).as_posix()
    results = payload.get('results', [])
    paths = {row['path'] for row in results}
    skipped = {row.get('path'): row.get('reason') for row in payload.get('skipped', [])}
    if variant.name.startswith('invalid-utf8') or variant.name == 'cp1252-doc':
        if not skipped.get(label):
            return 'fail', 'expect: invalid UTF-8 target must be skipped with reason'
    elif label not in paths:
        return 'fail', 'expect: normal or BOM target must be searchable'
    controls = {'CONTEXT.md', 'docs/a.md', '.prime/context/T/task-contract.json',
                '.prime/context/T/snapshot.json'} - {label}
    if not controls.issubset(paths):
        return 'fail', 'expect: other readable files must remain searchable'
    return 'pass', 'expect: target handled and other files searchable'


def context_search_entry(repo=ROOT):
    return Entry('context_search', search_scaffold, search_place,
                 CliAdapter(lambda root: [sys.executable, str(repo / 'scripts/context_search.py'),
                                          'search', 'probetoken'], lambda root: root,
                            {
                                'PATH': os.environ.get('PATH', os.defpath),
                                'HOME': os.environ.get('HOME', str(Path.home())),
                                'PYTHONPATH': str(repo / 'src')}),
                 ('.prime/search/',), search_expect, {'encoding': encoding_variants()},
                 pending={'bom-doc'})


ENTRIES = {'context_search': context_search_entry()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', required=True, choices=sorted(ENTRIES))
    parser.add_argument('--category', action='append')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    entry = ENTRIES[args.entry]
    if args.category and any(category not in entry.categories for category in args.category):
        parser.error('unknown category for ' + entry.name)
    report = run(entry, args.category)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output or Path(tempfile.gettempdir()) / 'failure-probes' / (entry.name + '-' + stamp + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print('REPORT ' + str(output))
    print(json.dumps(report['counts'], sort_keys=True))
    skipped = report['counts']['skipped']
    if skipped:
        print('SKIPPED ' + str(skipped))
    return exit_code(report)


if __name__ == '__main__':
    sys.exit(main())
