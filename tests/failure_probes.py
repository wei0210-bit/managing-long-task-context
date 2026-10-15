"""Cold-start failure-path probes, with entry-specific expectations."""
import argparse
from dataclasses import dataclass, field, replace
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

    def __post_init__(self):
        self.pending = set(self.pending)
        blocked = sorted(name for name, spec in self.known.items()
                         if isinstance(spec, tuple) and len(spec) == 2
                         and str(spec[1]).startswith('底线') and name in self.pending)
        if blocked:
            raise ValueError('baseline violation cannot be pending: ' + ', '.join(blocked))
        for name, spec in self.known.items():
            if not (isinstance(spec, tuple) and len(spec) == 2 and spec[0] and spec[1]):
                raise ValueError('known entry must be (issue, signature): ' + name)
            if not str(spec[0]).startswith('https://'):
                raise ValueError('known issue must be an https link: ' + name)
        overlap = sorted(set(self.known) & self.pending)
        if overlap:
            raise ValueError('variant cannot be both known and pending: ' + ', '.join(overlap))


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


def _parse_signature(signature):
    if signature.startswith('底线 '):
        head, fragment = signature.split('，', 1)
        number = head[len('底线 '):].strip()
        if number not in ('1', '2', '3') or not fragment:
            return None
        return ('baseline', number, fragment)
    if not signature.startswith('expect，exit '):
        return None
    exit_text, fragment = signature[len('expect，'):].split('，', 1)
    number = exit_text[len('exit '):].strip()
    if not number.isdigit() or not fragment:
        return None
    return ('expect', int(number), fragment)


def _signature_matches(row, signature, stdout, stderr):
    """Exempt a known failure only when the registered baseline or expect fragment is the one observed."""
    parsed = _parse_signature(signature)
    if parsed is None or row['verdict'] == 'pass':
        return False
    corpus = '\n'.join((row.get('reason') or '', stdout or '', stderr or ''))
    if parsed[0] == 'baseline':
        number, fragment = parsed[1], parsed[2]
        baselines = row['baseline']
        others_ok = all(baselines.get(key) is True for key in ('1', '2', '3') if key != number)
        return (row['verdict'] == 'fail' and row['exit_code'] == 1 and fragment in corpus
                and baselines.get(number) is False and others_ok)
    exit_code, fragment = parsed[1], parsed[2]
    return (all(row['baseline'].values()) and row['exit_code'] == exit_code
            and row['verdict'] in ('fail', 'vacuous') and fragment in corpus)


def _known_view(entry, row, stdout, stderr):
    spec = entry.known.get(row['variant'])
    if spec is None:
        return False
    issue, signature = spec
    return {'issue': issue, 'signature': signature,
            'matched': _signature_matches(row, signature, stdout, stderr)}


def _apply_known(entry, row, stdout, stderr):
    row['known'] = _known_view(entry, row, stdout, stderr)
    known = row['known']
    if isinstance(known, dict) and row['verdict'] != 'pass' and not known['matched'] and row['verdict'] != 'fail':
        row['verdict'] = 'fail'
        row['reason'] = 'known signature mismatch: ' + row['reason']
    return row


def run_variant(entry, variant, temp_dir=None):
    row = dict(category=variant.category, variant=variant.name, target=None,
               verdict='excluded', known=False, pending=variant.name in entry.pending,
               reason=entry.exclude.get(variant.name, ''), exit_code=None, timed_out=False,
               stdout_excerpt='', stderr_excerpt='', baseline={}, argv=[], cwd=None)
    if variant.name in entry.exclude:
        return row
    restricted = variant.category == 'unreadable' and not variant.name.startswith('normal-')
    if restricted and os.geteuid() == 0:
        row.update(verdict='fail' if os.environ.get('CI') == 'true' else 'skipped',
                   reason='root-can-read-0000')
        return row
    workspace = Path(tempfile.mkdtemp(prefix='failure-probe-', dir=temp_dir)).resolve()
    root = workspace / 'tree'
    try:
        root.mkdir()
        decoy = workspace / 'decoy'
        decoy.mkdir()
        (decoy / 'hidden.md').write_text('probetoken external\n', encoding='utf-8')
        entry.scaffold(root)
        # Place the readable fixture first so the snapshot includes locked descendants.
        target = entry.place(replace(variant, make=lambda path: None) if restricted else variant, root)
        row['target'] = str(target)
        before = snapshot(workspace)
        mode_changed = False
        if restricted:
            original_mode = stat.S_IMODE(target.lstat().st_mode)
            variant.make(target)
        # snapshot -> restrict -> run -> restore -> snapshot -> baselines -> expect -> known
        try:
            result = entry.adapter.run(root)
        finally:
            if restricted and target.exists() and not target.is_symlink():
                mode_changed = stat.S_IMODE(target.lstat().st_mode) != 0
                target.chmod(original_mode)
        after = snapshot(workspace)
        changes = changed_paths(before, after, tuple('tree/' + path for path in entry.writable))
        if mode_changed:
            changes.append(target.relative_to(workspace).as_posix() + ' (permissions)')
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
        elif not (variant.category == 'symlink' and variant.kind == 'link' and target.is_symlink()) \
                and not processed(target, result, variant.category):
            row.update(verdict='vacuous', reason='target was not processed')
        else:
            verdict, reason = entry.expect(variant, target, result)
            row.update(verdict=verdict, reason=reason)
        return _apply_known(entry, row, result['stdout'], result['stderr'])
    finally:
        cleanup(workspace)


def run(entry, categories=None, temp_dir=None):
    selected = categories or list(entry.categories)
    rows = [run_variant(entry, variant, temp_dir) for category in selected
            for variant in entry.categories[category]]
    return dict(entry=entry.name, created_at=datetime.now(timezone.utc).isoformat(),
                observation_scope=('Final state of entire probe tree except declared writable paths, '
                                   'external decoy contents, and unreadable contents captured before '
                                   'restriction and checked after restoring permissions; paths outside '
                                   'this scope and intermediate writes are not observed.'),
                results=rows, counts={verdict: sum(row['verdict'] == verdict for row in rows)
                                    for verdict in ('pass', 'fail', 'vacuous', 'undecided',
                                                    'adapter_error', 'excluded', 'skipped')})


def _affects_exit(row):
    known = row['known']
    if isinstance(known, dict):
        return row['verdict'] == 'pass' or not known['matched']
    if row['verdict'] not in ('fail', 'vacuous', 'undecided', 'adapter_error'):
        return False
    if not row['pending']:
        return True
    return row['verdict'] == 'adapter_error' or not all(row['baseline'].values())


def exit_code(report):
    return int(any(_affects_exit(row) for row in report['results']))


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


def _bytes(data):
    def make(path):
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    return make


def _nested(kind, depth=100000):
    if kind == 'array':
        return '[' * depth + '"probetoken"' + ']' * depth
    return '{"k":' * depth + '"probetoken"' + '}' * depth


def _write_nested(kind, newline=False):
    def make(path):
        text = _nested(kind) + ('\n' if newline else '')
        path.write_text(text, encoding='utf-8')
    return make


_NORMAL_SNAPSHOT = json.dumps({'items': {'I1': {
    'id': 'I1', 'type': 'observation', 'status': 'active', 'statement': 'probetoken fact'}}})


def malformed_json_variants():
    return [
        Variant('malformed_json', 'malformed-normal', 'file', _bytes(_NORMAL_SNAPSHOT)),
        Variant('malformed_json', 'truncated-snapshot', 'file', _bytes(
            '{"items": {"I1": {"id": "I1", "type": "observation", "status": "active", "statement": "probetoken"')),
        Variant('malformed_json', 'toplevel-array', 'file', _bytes('["probetoken"]')),
        Variant('malformed_json', 'items-list', 'file', _bytes(json.dumps({'items': [{
            'id': 'I1', 'type': 'observation', 'status': 'active', 'statement': 'probetoken'}]}))),
        Variant('malformed_json', 'item-string', 'file', _bytes(json.dumps({'items': {'I1': 'probetoken'}}))),
        Variant('malformed_json', 'empty-snapshot', 'file', _bytes(b'')),
    ]


def deep_nesting_variants():
    return [
        Variant('deep_nesting', 'nesting-normal', 'file', _bytes(_NORMAL_SNAPSHOT)),
        Variant('deep_nesting', 'array-snapshot', 'file', _write_nested('array')),
        Variant('deep_nesting', 'object-snapshot', 'file', _write_nested('object')),
        Variant('deep_nesting', 'array-events', 'file', _write_nested('array', newline=True)),
        Variant('deep_nesting', 'object-events', 'file', _write_nested('object', newline=True)),
    ]


def _marked_doc(mark):
    return ('alpha' + mark + 'ALPHA\n\nbeta\n\nprobetoken\n').encode('utf-8')


def special_chars_variants():
    return [
        Variant('special_chars', 'newline-doc', 'file', _bytes(_marked_doc('\n'))),
        Variant('special_chars', 'doc-u2028', 'file', _bytes(_marked_doc('\u2028'))),
        Variant('special_chars', 'doc-u0085', 'file', _bytes(_marked_doc('\u0085'))),
        Variant('special_chars', 'doc-cr', 'file', _bytes(_marked_doc('\r'))),
        Variant('special_chars', 'json-surrogate', 'file', _bytes(
            '{"items": {"I1": {"id": "I1", "type": "observation", "status": "active", '
            '"statement": "probetoken \\ud800"}}}')),
    ]


def unreadable_variants():
    return [
        Variant('unreadable', 'normal-unreadable', 'file', _bytes(b'probetoken document\n')),
        Variant('unreadable', 'unreadable-contract', 'file', lambda path: path.chmod(0)),
        Variant('unreadable', 'unreadable-doc', 'file', lambda path: path.chmod(0)),
        Variant('unreadable', 'unreadable-subdir', 'dir', lambda path: path.chmod(0)),
        Variant('unreadable', 'unreadable-root', 'dir', lambda path: path.chmod(0)),
    ]


def symlink_variants():
    def directory(path):
        target = path.parent.parent / 'linked-target'
        target.mkdir()
        (target / 'hidden.md').write_text('probetoken linked\n', encoding='utf-8')
        path.symlink_to('../linked-target', target_is_directory=True)

    return [
        Variant('symlink', 'normal-symlink', 'file', _bytes(b'probetoken document\n')),
        Variant('symlink', 'symlink-directory', 'link', directory),
        Variant('symlink', 'symlink-loop', 'link', lambda path: path.symlink_to(path.name)),
        Variant('symlink', 'symlink-broken', 'link', lambda path: path.symlink_to('missing')),
        Variant('symlink', 'symlink-external', 'link',
                lambda path: path.symlink_to('../../decoy', target_is_directory=True)),
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
    ledger = root / '.prime/context/T'
    if variant.category == 'encoding':
        target = ledger / 'task-contract.json' if variant.name.endswith('contract') else root / 'docs/a.md'
    elif variant.category == 'malformed_json':
        target = ledger / 'snapshot.json'
    elif variant.category == 'deep_nesting':
        target = ledger / ('events.jsonl' if variant.name.endswith('events') else 'snapshot.json')
    elif variant.category == 'special_chars':
        target = ledger / 'snapshot.json' if variant.name == 'json-surrogate' else root / 'docs/a.md'
    elif variant.category == 'unreadable':
        if variant.name == 'unreadable-contract':
            target = ledger / 'task-contract.json'
        elif variant.name == 'unreadable-subdir':
            target = root / 'docs/sub'
            target.mkdir()
            (target / 'a.md').write_text('probetoken hidden\n', encoding='utf-8')
        elif variant.name == 'unreadable-root':
            target = root
        else:
            target = root / 'docs/a.md'
    elif variant.category == 'symlink':
        target = root / ('docs/probe.md' if variant.kind == 'link' else 'docs/a.md')
    else:
        raise ValueError('no place for ' + variant.category)
    variant.make(target)
    return target


_SEARCH_CONTROLS = ('CONTEXT.md', 'docs/a.md', '.prime/context/T/task-contract.json',
                    '.prime/context/T/snapshot.json')


def _search_payload(result):
    try:
        payload = json.loads(result['stdout'])
    except ValueError:
        return None, 'expect: output is not JSON'
    if not isinstance(payload, dict) or result['exit_code'] != 0:
        return None, 'expect: search must return exit 0 and JSON object'
    return payload, None


def _result_paths(payload):
    return {row['path'] for row in payload.get('results', []) if isinstance(row, dict) and 'path' in row}


def _skipped_reasons(payload):
    return {row.get('path'): row.get('reason') for row in payload.get('skipped', []) if isinstance(row, dict)}


def _others_searchable(paths, label):
    return set(_SEARCH_CONTROLS).difference((label,)).issubset(paths)


def _newline_line(text, needle='probetoken'):
    for number, line in enumerate(text.split('\n'), 1):
        if needle in line:
            return number
    return None


def _expect_encoding(variant, label, paths, skipped):
    if variant.name.startswith('invalid-utf8') or variant.name == 'cp1252-doc':
        if not skipped.get(label):
            return 'fail', 'expect: invalid UTF-8 target must be skipped with reason'
    elif label not in paths:
        return 'fail', 'expect: normal or BOM target must be searchable'
    if not _others_searchable(paths, label):
        return 'fail', 'expect: other readable files must remain searchable'
    return 'pass', 'expect: target handled and other files searchable'


def _expect_malformed(variant, label, paths, skipped):
    if variant.name == 'malformed-normal':
        if label not in paths:
            return 'fail', 'expect: normal snapshot must be searchable'
    else:
        events = Path(label).with_name('events.jsonl').as_posix()
        if not (skipped.get(label) or events in paths or label in paths):
            return 'fail', 'expect: malformed target must be skipped or rebuilt from events.jsonl'
    if not _others_searchable(paths, label):
        return 'fail', 'expect: other readable files must remain searchable'
    return 'pass', 'expect: target handled and other files searchable'


def _expect_deep(variant, label, paths, skipped):
    if variant.name == 'nesting-normal':
        if label not in paths:
            return 'fail', 'expect: normal snapshot must be searchable'
    elif label not in paths and not skipped.get(label):
        return 'fail', 'expect: deep target must be indexed or skipped'
    if not _others_searchable(paths, label):
        return 'fail', 'expect: other readable files must remain searchable'
    return 'pass', 'expect: target handled and other files searchable'


def _expect_special(variant, target, label, paths, skipped, payload):
    if variant.name == 'json-surrogate':
        if label not in paths and not skipped.get(label):
            return 'fail', 'expect: surrogate JSON must be indexed or skipped without UnicodeEncodeError'
    else:
        # Text mode translates lone CR, which would hide the off-by-one under test.
        expected = _newline_line(target.read_bytes().decode('utf-8'))
        reported = [row.get('line') for row in payload.get('results', [])
                    if isinstance(row, dict) and row.get('path') == label]
        if reported != [expected]:
            shown = reported[0] if len(reported) == 1 else reported
            return 'fail', 'expect: line %s != newline line %s' % (shown, expected)
    if not _others_searchable(paths, label):
        return 'fail', 'expect: other readable files must remain searchable'
    if variant.name == 'json-surrogate':
        return 'pass', 'expect: surrogate JSON output parsed'
    return 'pass', 'expect: line number follows newline splits'


def search_expect(variant, target, result):
    payload, failure = _search_payload(result)
    if payload is None:
        return 'fail', failure
    label = target.relative_to(Path(result['cwd'])).as_posix()
    paths = _result_paths(payload)
    skipped = _skipped_reasons(payload)
    if variant.category == 'unreadable':
        if variant.name == 'normal-unreadable':
            if label not in paths:
                return 'fail', 'expect: readable target must be searchable'
        elif not skipped.get(label):
            return 'fail', 'expect: unreadable target must be skipped with reason'
        if not _others_searchable(paths, label):
            return 'fail', 'expect: other readable files must remain searchable'
        return 'pass', 'expect: target handled and other files searchable'
    if variant.category == 'symlink':
        if variant.kind == 'link' and any(path == label or path.startswith(label + '/')
                                          or path not in _SEARCH_CONTROLS for path in paths):
            return 'fail', 'expect: links and linked contents must not be indexed'
        if not set(_SEARCH_CONTROLS).issubset(paths):
            return 'fail', 'expect: other readable files must remain searchable'
        return 'pass', 'expect: links are not followed; readable controls searchable'
    if variant.category == 'encoding':
        return _expect_encoding(variant, label, paths, skipped)
    if variant.category == 'malformed_json':
        return _expect_malformed(variant, label, paths, skipped)
    if variant.category == 'deep_nesting':
        return _expect_deep(variant, label, paths, skipped)
    if variant.category == 'special_chars':
        return _expect_special(variant, target, label, paths, skipped, payload)
    return 'undecided', 'expect: no contract for ' + variant.name


_ISSUE = 'https://github.com/wei0210-bit/managing-long-task-context/issues/'


def context_search_entry(repo=ROOT):
    known = {
        'unreadable-contract': (_ISSUE + '111', 'expect，exit 1，Permission denied'),
        'unreadable-doc': (_ISSUE + '112', 'expect，exit 1，Permission denied'),
        'unreadable-subdir': (_ISSUE + '113', 'expect，exit 0，target was not processed'),
        'truncated-snapshot': (_ISSUE + '98', "expect，exit 1，Expecting ',' delimiter"),
        'toplevel-array': (_ISSUE + '99', 'expect，exit 0，target was not processed'),
        'items-list': (_ISSUE + '100', "底线 1，AttributeError: 'list' object has no attribute 'items'"),
        'item-string': (_ISSUE + '101', "底线 1，AttributeError: 'str' object has no attribute 'get'"),
        'empty-snapshot': (_ISSUE + '102', 'expect，exit 0，target was not processed'),
        'array-snapshot': (_ISSUE + '103', 'expect，exit 0，target was not processed'),
        'object-snapshot': (_ISSUE + '104', 'expect，exit 0，target was not processed'),
        'array-events': (_ISSUE + '105',
                         '底线 1，RecursionError: maximum recursion depth exceeded while decoding a JSON array'),
        'object-events': (_ISSUE + '106',
                          '底线 1，RecursionError: maximum recursion depth exceeded while decoding a JSON object'),
        'doc-u2028': (_ISSUE + '107', 'expect，exit 0，line 6 != newline line 5'),
        'doc-u0085': (_ISSUE + '108', 'expect，exit 0，line 6 != newline line 5'),
        'doc-cr': (_ISSUE + '109', 'expect，exit 0，line 6 != newline line 5'),
        'json-surrogate': (_ISSUE + '110', 'expect，exit 1，surrogates not allowed'),
    }
    return Entry('context_search', search_scaffold, search_place,
                 CliAdapter(lambda root: [sys.executable, str(repo / 'scripts/context_search.py'),
                                          'search', 'probetoken'], lambda root: root,
                            {
                                'PATH': os.environ.get('PATH', os.defpath),
                                'HOME': os.environ.get('HOME', str(Path.home())),
                                'PYTHONPATH': str(repo / 'src')}),
                 ('.prime/search/',), search_expect, {
                     'encoding': encoding_variants(),
                     'malformed_json': malformed_json_variants(),
                     'deep_nesting': deep_nesting_variants(),
                     'special_chars': special_chars_variants(),
                     'unreadable': unreadable_variants(),
                     'symlink': symlink_variants(),
                 }, exclude={'unreadable-root': '入口形状：根来自工作目录的 git rev-parse；'
                             '0000 仓库根使子进程无法进入工作目录，入口没有根参数'},
                 known=known, pending={'bom-doc'})


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
    for row in report['results']:
        if isinstance(row['known'], dict) and row['verdict'] == 'pass':
            print('KNOWN-NOW-PASSING ' + row['variant'])
    skipped = report['counts']['skipped']
    if skipped:
        print('SKIPPED ' + str(skipped))
    return exit_code(report)


if __name__ == '__main__':
    sys.exit(main())
