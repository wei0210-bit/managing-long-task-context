"""Explicit acceptance sidecars and read-only validity checks.

The coordinator is the sole writer. Gate runs outside the non-reentrant task
lock; every observation used for recording is checked again inside that lock.
Neither records nor retained evidence change the ledger or its projection.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from . import evidence as ev
from . import worker_report as wr
from .project_store import SECRET_MARKERS

RECORD_FILE = 'acceptance-records.jsonl'
SINGLE_FILE_LIMIT = 1024 * 1024
TOTAL_LIMIT = 20 * 1024 * 1024
_RECORD_LIMIT = ev.MAX_LOCAL_ARTIFACT_BYTES
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MANAGED = {'.prime', '.githooks', '.gitattributes'}
_HINT = '这是当时的结论；代码维度是否需重新验收，运行 context_status.py。'


def _core():
    # Respect package aliases used by the package/runtime identity tests.
    return importlib.import_module(__package__)


def _error(code):
    return _core().ContextError(code)


def _digest(value):
    return 'sha256:' + hashlib.sha256(ev.canonical_json_bytes(value)).hexdigest()


def _git(root, *args, optional=False):
    try:
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                timeout=ev.GIT_TIMEOUT_SECONDS)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _error('GIT_UNAVAILABLE') from exc
    if result.returncode and not optional:
        raise _error('GIT_UNAVAILABLE')
    return result


def _text(root, *args):
    return _git(root, *args).stdout.decode('utf-8', 'surrogateescape').strip()


def _preconditions(root):
    if Path.cwd().resolve() != root:
        raise _error('CWD_MISMATCH')
    if Path(_text(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise _error('WORKSPACE_INVALID')
    if _git(root, 'symbolic-ref', '-q', 'HEAD', optional=True).returncode:
        raise _error('DETACHED_HEAD')
    merge = Path(_text(root, 'rev-parse', '--git-path', 'MERGE_HEAD'))
    if not merge.is_absolute():
        merge = root / merge
    if merge.exists():
        raise _error('MERGE_IN_PROGRESS')
    if _git(root, 'rev-parse', '--verify', '@{upstream}', optional=True).returncode:
        raise _error('NO_UPSTREAM')


def _relative_path(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        return None
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return None
    return path.as_posix()


def _watched_paths(root, values):
    if not isinstance(values, (list, tuple)):
        raise _error('WATCHED_PATH_INVALID')
    paths = []
    for value in values:
        path = _relative_path(value)
        if path is None or any(part in _MANAGED for part in Path(path).parts):
            raise _error('WATCHED_PATH_INVALID')
        target = root
        for part in Path(path).parts:
            target = target / part
            if target.is_symlink():
                raise _error('WATCHED_PATH_INVALID')
        obj = _git(root, 'rev-parse', '--verify', 'HEAD:' + path, optional=True)
        if obj.returncode:
            raise _error('WATCHED_PATH_INVALID')
        descendants = _text(root, 'ls-tree', '-rz', '--name-only', 'HEAD', '--', path).split('\x00')
        if any(part in _MANAGED for child in descendants for part in Path(child).parts):
            raise _error('WATCHED_PATH_INVALID')
        paths.append(path)
    return sorted(set(paths))


def _status_paths(root):
    raw = _git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all').stdout
    records = raw.split(b'\x00')
    paths, index = [], 0
    while index < len(records) - 1:
        item = records[index]
        index += 1
        if len(item) < 4 or item[2:3] != b' ':
            raise _error('GIT_UNAVAILABLE')
        paths.append(item[3:].decode('utf-8', 'surrogateescape'))
        if b'R' in item[:2] or b'C' in item[:2]:
            if index >= len(records) - 1 or not records[index]:
                raise _error('GIT_UNAVAILABLE')
            paths.append(records[index].decode('utf-8', 'surrogateescape'))
            index += 1
    if records[-1]:
        raise _error('GIT_UNAVAILABLE')
    return sorted(set(paths))


def _under(path, watched):
    return path == watched or path.startswith(watched + '/')


def _worktree_fingerprint(root, watched):
    # Dirty booleans and HEAD object IDs alone cannot detect dirty->dirty edits.
    names = _git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').stdout
    fingerprints = []
    for raw in sorted(set(names.split(b'\x00')) - {b''}):
        path = raw.decode('utf-8', 'surrogateescape')
        if not any(_under(path, watch) for watch in watched):
            continue
        target = root / path
        try:
            info = target.lstat()
            if stat.S_ISLNK(info.st_mode):
                content = os.readlink(target).encode('utf-8', 'surrogateescape')
            elif stat.S_ISREG(info.st_mode):
                content, result = wr._read_bytes(root, target)
                if content is None:
                    raise _error('WATCHED_PATH_UNREADABLE')
            elif stat.S_ISDIR(info.st_mode):
                # Gitlinks are represented by directories; status and HEAD still bind them.
                content = b'directory'
            else:
                raise _error('WATCHED_PATH_UNREADABLE')
            fingerprints.append((path, info.st_mode, hashlib.sha256(content).hexdigest()))
        except FileNotFoundError:
            fingerprints.append((path, 'missing'))
        except OSError as exc:
            raise _error('WATCHED_PATH_UNREADABLE') from exc
    return fingerprints


def _observe(task_id, paths, root, watched):
    core = _core()
    view = core._load_committed_task_view_locked(task_id, paths)
    # The fast snapshot view can omit event tails; the cursor must bind the ledger itself.
    events = core._read_events(paths['events'])
    changes = _status_paths(root)
    return {'contract_digest': view['contract_digest'], 'contract_version': view['contract']['version'],
            'ledger_cursor': {'event_count': len(events),
                              'last_event_id': events[-1]['event_id'] if events else None},
            'ledger_digest': hashlib.sha256(paths['events'].read_bytes()).hexdigest(),
            'code_revision': {'commit': _text(root, 'rev-parse', '--verify', 'HEAD'),
                              'dirty': any(not wr._excluded(p) for p in changes), 'source': 'recorder-head'},
            'watched': [{'path': path, 'object_id': _text(root, 'rev-parse', '--verify', 'HEAD:' + path)}
                        for path in watched],
            'worktree': _worktree_fingerprint(root, watched)}, view['contract']


def _time(value):
    return ev._parse_utc_time(value) if isinstance(value, str) and value.endswith('Z') else None


def _shape(record):
    if not isinstance(record, dict):
        return False
    revision = record.get('code_revision')
    cursor = record.get('ledger_cursor')
    if ('contract_version' not in record
            or record.get('schema') != 'acceptance-record/v1' or record.get('stage') != 'completion'
            or not isinstance(record.get('record_id'), str)
            or re.fullmatch(r'AR-[0-9a-f]{16}', record['record_id']) is None
            or _time(record.get('recorded_at')) is None
            or not isinstance(record.get('recorded_by'), str) or not record['recorded_by']
            or not isinstance(record.get('contract_integrity_digest'), str)
            or ev._DIGEST_RE.fullmatch(record['contract_integrity_digest']) is None
            or not isinstance(cursor, dict) or type(cursor.get('event_count')) is not int
            or cursor['event_count'] < 0
            or not (cursor.get('last_event_id') is None or isinstance(cursor['last_event_id'], str))
            or not isinstance(revision, dict) or type(revision.get('dirty')) is not bool
            or not isinstance(revision.get('commit'), str)
            or ev._COMMIT_RE.fullmatch(revision['commit']) is None
            or record.get('decision') not in ('pass', 'fail', 'unknown')
            or type(record.get('passed')) is not bool or not isinstance(record.get('errors'), list)
            or type(record.get('reproducible')) is not bool
            or not isinstance(record.get('reproducible_reasons'), list)
            or not isinstance(record.get('watched'), list) or not isinstance(record.get('criteria'), list)):
        return False
    for watched in record['watched']:
        if (not isinstance(watched, dict) or _relative_path(watched.get('path')) is None
                or any(p in _MANAGED for p in Path(watched['path']).parts)
                or not isinstance(watched.get('object_id'), str)
                or re.fullmatch(r'[0-9a-f]{40,64}', watched['object_id']) is None):
            return False
    for criterion in record['criteria']:
        if (not isinstance(criterion, dict) or criterion.get('status') not in ('pass', 'fail', 'unknown')
                or not isinstance(criterion.get('evidence'), list)):
            return False
        for evidence in criterion['evidence']:
            if not isinstance(evidence, dict) or not _retained_shape(evidence.get('retained')):
                return False
    return True


def _retained_shape(retained):
    if not isinstance(retained, dict) or type(retained.get('copied')) is not bool:
        return False
    checksum = retained.get('sha256')
    if checksum is not None and (not isinstance(checksum, str) or not _HEX.fullmatch(checksum)):
        return False
    if retained['copied'] and checksum is None:
        return False
    if not retained['copied'] and (not isinstance(retained.get('reason'), str) or not retained['reason']):
        return False
    outputs = retained.get('outputs', [])
    return isinstance(outputs, list) and all(_retained_shape(item) for item in outputs)


def _read_records(paths):
    path = paths['root'] / RECORD_FILE
    if not path.exists() and not path.is_symlink():
        return [], None
    try:
        raw, result = wr._read_bytes(paths['root'], path)
        if raw is None or len(raw) > _RECORD_LIMIT:
            return [], 'record_integrity'
        if any(line.startswith((b'<<<<<<<', b'=======', b'>>>>>>>')) for line in raw.splitlines()):
            return [], 'record_integrity'
        if raw and not raw.endswith(b'\n'):
            return [], 'record_integrity'
        records, previous, identifiers = [], None, set()
        for line in raw.splitlines():
            record = _core()._strict_handoff_json_load(line)
            if not _shape(record):
                return [], 'record_integrity'
            expected = record.get('record_digest')
            if expected != _digest({k: v for k, v in record.items() if k != 'record_digest'}):
                return [], 'record_integrity'
            if record['record_id'] in identifiers:
                return [], 'record_integrity'
            identifiers.add(record['record_id'])
            if previous and (_time(record['recorded_at']) < _time(previous['recorded_at'])
                             or record['ledger_cursor']['event_count'] < previous['ledger_cursor']['event_count']):
                return [], 'record_order'
            records.append(record)
            previous = record
        return records, None
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return [], 'record_integrity'


def _retain(root, task_root, locator, expected, *, eligible):
    retained = {'copied': False, 'sha256': expected}
    if not eligible:
        retained['reason'] = 'NOT_VERIFIED'
        return retained, None
    path, result = wr._path(root, locator)
    if path is None:
        retained['reason'] = 'SOURCE_MISSING' if 'NOT_FOUND' in result['codes'] else 'INVALID_PATH'
        return retained, 'EVIDENCE_CHANGED' if retained['reason'] == 'SOURCE_MISSING' else None
    raw, result = wr._read_bytes(root, path)
    if raw is None:
        return {**retained, 'reason': 'SOURCE_MISSING'}, 'EVIDENCE_CHANGED'
    checksum = hashlib.sha256(raw).hexdigest()
    if expected != checksum:
        return retained, 'EVIDENCE_CHANGED'
    if any(marker.encode('ascii') in raw for marker in SECRET_MARKERS):
        return {**retained, 'reason': 'SECRET_MARKER'}, None
    if len(raw) > SINGLE_FILE_LIMIT:
        return {**retained, 'reason': 'SIZE_LIMIT'}, None
    directory = task_root / 'evidence'
    if directory.is_symlink():
        raise _error('EVIDENCE_COPY_INVALID')
    directory.mkdir(exist_ok=True)
    # Copying is outside the task lock. Serialize the quota and create through
    # a separate directory lock, including across processes, without new files.
    with _core()._process_lock_guard(directory):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if _core().fcntl is None:
                raise _error('EVIDENCE_LOCK_UNAVAILABLE')
            _core().fcntl.flock(descriptor, _core().fcntl.LOCK_EX)
            return _store_copy(directory, descriptor, checksum, raw, retained)
        finally:
            os.close(descriptor)


def _store_copy(directory, descriptor, checksum, raw, retained):
    # A no-follow directory fd also prevents substitution between checking and writing.
    try:
        fd = os.open(checksum, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    except FileNotFoundError:
        fd = None
    if fd is not None:
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise _error('EVIDENCE_COPY_INVALID')
            with os.fdopen(fd, 'rb', closefd=False) as handle:
                existing = handle.read(SINGLE_FILE_LIMIT + 1)
            if existing != raw:
                raise _error('EVIDENCE_COPY_INVALID')
        finally:
            os.close(fd)
    else:
        total = sum(p.lstat().st_size for p in directory.iterdir())
        if total + len(raw) > TOTAL_LIMIT:
            return {**retained, 'reason': 'TOTAL_LIMIT'}, None
        fd = os.open(checksum, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o444, dir_fd=descriptor)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
    retained['copied'] = True
    return retained, None


def _criteria(contract, gate_report, evidence_map, root, task_root):
    gate_criteria = gate_report.get('criteria', {})
    criteria, copy_error = [], None
    for criterion in contract.get('acceptance_criteria', []):
        identifier = criterion['id']
        result = gate_criteria.get(identifier, {}) if isinstance(gate_criteria, Mapping) else {}
        outcomes = {r.get('evidence_id'): r for r in result.get('evidence_results', []) if isinstance(r, Mapping)}
        summaries = []
        entry = evidence_map.get(identifier, {}) if isinstance(evidence_map, Mapping) else {}
        sources = entry.get('evidence', []) if isinstance(entry, Mapping) else []
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, Mapping):
                continue
            summary = {key: deepcopy(source.get(key)) for key in
                       ('evidence_id', 'kind', 'locator', 'generated_at', 'produced_by', 'code_revision')}
            expected = source.get('artifact_digest')
            checksum = expected[7:] if isinstance(expected, str) and ev._DIGEST_RE.fullmatch(expected) else None
            retained = {'copied': False, 'sha256': checksum, 'reason': 'SUMMARY_ONLY'}
            if source.get('kind') == 'worker-report':
                resolution = outcomes.get(source.get('evidence_id'), {})
                checks = resolution.get('checks', {})
                eligible = (checks.get('resolve', {}).get('status') == 'pass'
                            and all(value.get('status') == 'pass' for name, value in checks.items()
                                    if name != 'claim'))
                # Re-read the report even if it was not reproducible, to preserve its revision.
                report, read_result = wr._read_report(root, source)
                if eligible and report is None:
                    copy_error = 'EVIDENCE_CHANGED'
                if report is not None and summary['code_revision'] is None:
                    summary['code_revision'] = deepcopy(report['code_revision'])
                retained, error = _retain(root, task_root, source.get('locator'), checksum, eligible=eligible)
                copy_error = copy_error or error
                outputs = []
                claim = criterion.get('worker_report_claim', {})
                commands = claim.get('commands', []) if isinstance(claim, Mapping) else []
                if report is not None and isinstance(commands, list):
                    for check in report['checks']:
                        if check['command'] not in commands:
                            continue
                        output, error = _retain(root, task_root, check['output_file'], check['output_sha256'],
                            eligible=eligible and checks.get('claim', {}).get('status') == 'pass')
                        output['locator'] = check['output_file']
                        outputs.append(output)
                        copy_error = copy_error or error
                retained['outputs'] = outputs
            summary['retained'] = retained
            summaries.append(summary)
        criteria.append({'criterion_id': identifier, 'status': result.get('status', 'unknown'), 'evidence': summaries})
    return criteria, copy_error


def _decision(report):
    if report.get('decision') in ('pass', 'fail', 'unknown'):
        return report['decision']
    if report.get('passed'):
        return 'pass'
    criteria = report.get('criteria', {})
    values = criteria.values() if isinstance(criteria, Mapping) else criteria if isinstance(criteria, list) else []
    return 'fail' if any(isinstance(item, Mapping) and item.get('status') == 'fail' for item in values) else 'unknown'


def _reproducible(revision, criteria):
    reasons = ['recorded code is dirty'] if revision['dirty'] else []
    for criterion in criteria:
        for item in criterion['evidence']:
            other = item.get('code_revision')
            if other is None:
                continue
            label = str(item.get('evidence_id'))
            if not isinstance(other, Mapping) or other.get('commit') != revision['commit']:
                reasons.append(label + ': evidence commit differs')
            if not isinstance(other, Mapping) or other.get('dirty') is not False:
                reasons.append(label + ': evidence is dirty or dirty state is unknown')
    return not reasons, reasons


def record_acceptance(task_id, *, evidence_map, resolvers, verifiers, watched_paths,
                      recorded_by, base_dir, workspace_root, validation_resolver=None, rule_runtime=None):
    """Run completion and explicitly append its point-in-time result, or refuse a race."""
    core = _core()
    root = Path(workspace_root)
    if not root.is_absolute():
        raise _error('WORKSPACE_INVALID')
    root = root.resolve()
    if not isinstance(recorded_by, str) or not recorded_by.strip():
        raise _error('RECORDED_BY_INVALID')
    paths = core._paths(task_id, base_dir)
    _preconditions(root)
    watched = _watched_paths(root, watched_paths)
    _, integrity = _read_records(paths)
    if integrity:
        raise _error('RECORD_ORDER' if integrity == 'record_order' else 'RECORD_INTEGRITY')
    pre, contract = _observe(task_id, paths, root, watched)
    report = core.gate(task_id, stage='completion', emit=False, evidence_map=deepcopy(evidence_map),
        resolvers=resolvers, verifiers=verifiers, validation_resolver=validation_resolver,
        rule_runtime=rule_runtime, base_dir=base_dir)
    criteria, error = _criteria(contract, report, evidence_map, root, paths['root'])
    if error:
        return {'appended': False, 'reason': error}
    with core._locked(paths['root']):
        _preconditions(root)
        try:
            post, _ = _observe(task_id, paths, root, watched)
        except core.ContextError:
            return {'appended': False, 'reason': 'RECORD_RACE'}
        if post != pre:
            return {'appended': False, 'reason': 'RECORD_RACE'}
        records, integrity = _read_records(paths)
        if integrity:
            raise _error('RECORD_ORDER' if integrity == 'record_order' else 'RECORD_INTEGRITY')
        if records and pre['ledger_cursor']['event_count'] < records[-1]['ledger_cursor']['event_count']:
            raise _error('RECORD_ORDER')
        revision = pre['code_revision']
        decision = _decision(report)
        digests = []
        for criterion in criteria:
            for item in criterion['evidence']:
                retained = item['retained']
                digests.append(retained.get('sha256'))
                digests.extend(p.get('sha256') for p in retained.get('outputs', []))
        key = _digest([pre['contract_digest'], pre['ledger_cursor'], revision, watched, digests, decision])[7:]
        record_id = 'AR-' + key[:16]
        for previous in records:
            if previous['record_id'] == record_id:
                return {'appended': False, 'record': previous}
        now = core._trusted_utc_now().astimezone(timezone.utc)
        if records:
            now = max(now, _time(records[-1]['recorded_at']))
        reproducible, reasons = _reproducible(revision, criteria)
        record = {'schema': 'acceptance-record/v1', 'record_id': record_id, 'stage': 'completion',
            'recorded_at': now.isoformat().replace('+00:00', 'Z'), 'recorded_by': recorded_by,
            'contract_version': pre['contract_version'], 'contract_integrity_digest': pre['contract_digest'],
            'ledger_cursor': pre['ledger_cursor'], 'code_revision': revision, 'watched': pre['watched'],
            'decision': decision, 'passed': bool(report.get('passed')), 'errors': deepcopy(report.get('errors', [])),
            'criteria': criteria, 'reproducible': reproducible, 'reproducible_reasons': reasons}
        record['record_digest'] = _digest(record)
        raw = ev.canonical_json_bytes(record) + b'\n'
        record_path = paths['root'] / RECORD_FILE
        existing_size = record_path.stat().st_size if record_path.exists() else 0
        if existing_size + len(raw) > _RECORD_LIMIT:
            raise _error('RECORD_SIZE_LIMIT')
        fd = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'ab') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return {'appended': True, 'record': record}


def _evidence_integrity(paths, record):
    for criterion in record['criteria']:
        for evidence in criterion['evidence']:
            retained = evidence['retained']
            for item in [retained, *retained.get('outputs', [])]:
                if item['copied']:
                    path, _ = wr._path(paths['root'], 'evidence/' + item['sha256'])
                    raw, _ = wr._read_bytes(paths['root'], path) if path is not None else (None, None)
                    if raw is None or hashlib.sha256(raw).hexdigest() != item['sha256']:
                        return False
    return True


def _latest_from_paths(paths, contract):
    if not (paths['root'] / RECORD_FILE).exists() and not (paths['root'] / RECORD_FILE).is_symlink():
        return None
    records, error = _read_records(paths)
    if error:
        return {'record_integrity': False, 'evidence_integrity': None, 'reason': error}
    if not records:
        return None
    record = records[-1]
    summary = {key: deepcopy(record[key]) for key in ('record_id', 'recorded_at', 'decision', 'contract_version',
               'code_revision', 'reproducible')}
    seal = contract.get('seal')
    current_digest = _core()._contract_digest(contract)
    summary.update(contract_matches=(isinstance(seal, Mapping)
                   and record['contract_integrity_digest'] == seal.get('integrity_digest') == current_digest),
                   record_integrity=True, evidence_integrity=_evidence_integrity(paths, record))
    summary['retention_reasons'] = sorted({item.get('reason', 'UNKNOWN') for c in record['criteria'] for e in c['evidence']
        for item in [e['retained'], *e['retained'].get('outputs', [])] if not item['copied']})
    return summary


def latest_acceptance(task_id, *, base_dir):
    """File-only latest record summary; no Git and no task-store writes."""
    core = _core()
    paths = core._paths(task_id, base_dir)
    with core._shared_locked_existing(paths['root']):
        contract = core._read_json(paths['contract'])
        return _latest_from_paths(paths, contract)


def _summary_markdown(summary):
    if summary is None:
        return ''
    if not summary.get('record_integrity'):
        body = 'unknown: ' + summary['reason']
    else:
        revision = summary['code_revision']
        body = (f"{summary['record_id']} | {summary['recorded_at']} | {summary['decision']}\n"
                f"Contract v{summary['contract_version']} matches={summary['contract_matches']} | "
                f"commit={revision['commit']} dirty={revision['dirty']} reproducible={summary['reproducible']}\n"
                f"record_integrity={summary['record_integrity']} evidence_integrity={summary['evidence_integrity']}")
        if not summary['evidence_integrity']:
            body += '\n证据副本缺失/不符'
        if summary['retention_reasons']:
            body += '\n未留存（' + ', '.join(summary['retention_reasons']) + '）'
    # Reserve the hint even when hostile/free-form version values are very long.
    return '\n\n## Latest acceptance\n' + body[:480] + '\n' + _HINT


def _relation(root, commit):
    if _git(root, 'cat-file', '-e', commit + '^{commit}', optional=True).returncode:
        return 'missing'
    result = _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD', optional=True)
    if result.returncode not in (0, 1):
        raise _error('GIT_UNAVAILABLE')
    return 'ancestor' if result.returncode == 0 else 'not_ancestor'


def acceptance_status(task_id, *, base_dir, workspace_root):
    """Read current validity by watched object IDs, independent of commit ancestry."""
    core = _core()
    paths = core._paths(task_id, base_dir)
    result = {'status': 'never_accepted', 'reason': None, 'latest_acceptance': None,
              'commit_relation': None, 'events_since_acceptance': None, 'paths': [], 'message': '记录按分支存在'}
    with core._shared_locked_existing(paths['root']):
        records, error = _read_records(paths)
        if error:
            return {**result, 'status': 'unknown', 'reason': error}
        if not records:
            return result
        contract = core._read_json(paths['contract'])
        summary = _latest_from_paths(paths, contract)
        record = records[-1]
        result['latest_acceptance'] = summary
        events = core._read_events(paths['events'])
        result['events_since_acceptance'] = len(events) - record['ledger_cursor']['event_count']
        if result['events_since_acceptance']:
            result['message'] += '；验收后有新的上下文变化'
        # The ordered decision never depends on ancillary ancestry observations.
        if record['decision'] != 'pass':
            result.update(status='not_accepted', reason=record['decision'], errors=record['errors'])
        elif not summary['evidence_integrity']:
            result.update(status='unknown', reason='evidence_copy')
        elif not summary['contract_matches']:
            result.update(status='reaccept_required', reason='contract_changed')
        elif record['code_revision']['dirty']:
            result.update(status='unknown', reason='recorded_dirty')
        elif not record['watched']:
            result.update(status='unknown', reason='no_watched_paths')
        else:
            result['status'] = 'still_valid'
    root = Path(workspace_root).resolve()
    try:
        result['commit_relation'] = _relation(root, record['code_revision']['commit'])
        if result['commit_relation'] == 'not_ancestor':
            result['message'] += '；记录来自其他分支或已被改写的历史'
        elif result['commit_relation'] == 'missing':
            result['message'] += '；本地没有该提交'
        else:
            result['message'] += '；记录提交是当前 HEAD 的祖先'
        if result['status'] == 'still_valid':
            changed = _status_paths(root)
            dirty = sorted({watch['path'] for watch in record['watched']
                            if any(_under(path, watch['path']) for path in changed)})
            if dirty:
                result.update(status='unknown', reason='worktree_dirty', paths=dirty)
            else:
                different = []
                for watch in record['watched']:
                    obj = _git(root, 'rev-parse', '--verify', 'HEAD:' + watch['path'], optional=True)
                    if obj.returncode or obj.stdout.decode('ascii').strip() != watch['object_id']:
                        different.append(watch['path'])
                if different:
                    result.update(status='reaccept_required', reason='watched_paths_changed', paths=different)
    except (core.ContextError, OSError, ValueError, UnicodeError):
        result['commit_relation'] = 'unknown'
        if result['status'] == 'still_valid':
            result.update(status='unknown', reason='git_unavailable')
    return result
