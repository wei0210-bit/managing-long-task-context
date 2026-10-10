#!/usr/bin/env python3
"""Coordinator ledger and acceptance operations; PYTHONPATH selects the package.

Only the coordinator should run these writes against a shared store. Check
commands are labels for previously captured logs, never executed by this CLI.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import uuid


ACTOR = 'coordinator'
LEASE_FILE = 'COORDINATOR-LEASE.json'
LEASE_TTL_SECONDS = 7200


class CoordinatorLeaseError(ValueError):
    """A coordinator lease denial, including unreadable or invalid state."""


def lease_time(value, field):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value):
        raise CoordinatorLeaseError('coordinator lease: invalid UTC timestamp ' + field)
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        raise CoordinatorLeaseError('coordinator lease: invalid UTC timestamp ' + field) from exc


def lease_now():
    # Production uses the real UTC clock; isolated tests may inject a clock.
    injected = os.environ.get('COORDINATOR_LEASE_NOW')
    return (lease_time(injected, 'COORDINATOR_LEASE_NOW') if injected is not None
            else datetime.now(timezone.utc))


def utc_text(value):
    return value.isoformat().replace('+00:00', 'Z')


def coordinator_identity():
    try:
        pid = int(os.environ.get('CLAUDE_PID', str(os.getppid())))
    except ValueError as exc:
        raise CoordinatorLeaseError('coordinator lease: invalid CLAUDE_PID') from exc
    if pid <= 0:
        raise CoordinatorLeaseError('coordinator lease: CLAUDE_PID must be positive')
    return {'session_id': os.environ.get('CLAUDE_CODE_SESSION_ID')
            or os.environ.get('CODEX_SESSION_ID') or 'unknown', 'pid': pid,
            'terminal_handle': os.environ.get('ORCA_TERMINAL_HANDLE') or None,
            'host': socket.gethostname()}


def same_coordinator(lease, identity):
    if any(lease[key] != identity[key] for key in ('host', 'session_id')):
        return False
    old_terminal, new_terminal = lease['terminal_handle'], identity['terminal_handle']
    if old_terminal and new_terminal:
        return old_terminal == new_terminal
    return lease['pid'] == identity['pid']


def read_coordinator_lease(store):
    path = Path(store) / LEASE_FILE
    try:
        path.lstat()  # A dangling link is invalid, never an absent lease.
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CoordinatorLeaseError('coordinator lease: unreadable file: ' + str(exc)) from exc
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CoordinatorLeaseError('coordinator lease: unreadable file: ' + str(exc)) from exc
    def reject_constant(value):
        raise ValueError('non-JSON constant ' + value)
    try:
        value = json.loads(raw, parse_constant=reject_constant)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise ValueError('JSON nesting is too deep')
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CoordinatorLeaseError('coordinator lease: invalid JSON: ' + str(exc)) from exc
    if not isinstance(value, dict):
        raise CoordinatorLeaseError('coordinator lease: expected JSON object')
    required = ('schema', 'session_id', 'pid', 'terminal_handle', 'host',
                'acquired_at', 'heartbeat_at', 'ttl_seconds')
    missing = [key for key in required if key not in value]
    if missing:
        raise CoordinatorLeaseError('coordinator lease: missing fields: ' + ', '.join(missing))
    if value['schema'] != 'coordinator-lease/v1':
        raise CoordinatorLeaseError('coordinator lease: invalid schema')
    for key in ('session_id', 'host'):
        if not isinstance(value[key], str) or not value[key].strip():
            raise CoordinatorLeaseError('coordinator lease: invalid field ' + key)
    if type(value['pid']) is not int or value['pid'] <= 0:
        raise CoordinatorLeaseError('coordinator lease: pid must be a positive integer')
    if value['terminal_handle'] is not None and not isinstance(value['terminal_handle'], str):
        raise CoordinatorLeaseError('coordinator lease: invalid terminal_handle')
    if type(value['ttl_seconds']) is not int or value['ttl_seconds'] != LEASE_TTL_SECONDS:
        raise CoordinatorLeaseError('coordinator lease: ttl_seconds must equal 7200')
    for key in ('acquired_at', 'heartbeat_at', 'released_at'):
        if key in value:
            lease_time(value[key], key)
    try:
        lease_expiry(value)
    except OverflowError as exc:
        raise CoordinatorLeaseError('coordinator lease: expiration timestamp is out of range') from exc
    return value


def lease_expiry(lease):
    return lease_time(lease['heartbeat_at'], 'heartbeat_at') + timedelta(seconds=lease['ttl_seconds'])


def lease_expired(lease, now):
    return now > lease_expiry(lease)


def coordinator_denial(lease, now):
    holder = json.dumps({key: lease[key] for key in ('host', 'session_id', 'terminal_handle', 'pid')},
                        ensure_ascii=False, separators=(',', ':'))
    return ('coordinator lease held by ' + holder + '; expires_at=' + utc_text(lease_expiry(lease))
            + ('; expired: use lease takeover --reason to record takeover'
               if lease_expired(lease, now) else '; use lease takeover with David instruction to take over'))


def check_coordinator_lease(store):
    """Read-only dispatch guard: absent, released, own and expired leases pass."""
    lease = read_coordinator_lease(store)
    now = lease_now()
    if (lease is not None and 'released_at' not in lease and not lease_expired(lease, now)
            and not same_coordinator(lease, coordinator_identity())):
        raise CoordinatorLeaseError(coordinator_denial(lease, now))
    return lease


@contextmanager
def coordinator_lease_lock(store):
    store = Path(store).resolve()
    lock = store / 'COORDINATOR-LEASE.lock'
    owned = False
    try:
        store.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        owned = True
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            row = {'schema': 'coordinator-lease-lock/v1', **coordinator_identity(),
                   'created_at': utc_text(lease_now())}
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        yield
    except FileExistsError as exc:
        if owned:
            raise CoordinatorLeaseError('coordinator lease: lock/write unavailable: ' + str(exc)) from exc
        holder = read_coordinator_lock(lock)
        detail = (json.dumps(holder, ensure_ascii=False, separators=(',', ':'))
                  if holder is not None else 'unreadable lock')
        raise CoordinatorLeaseError('coordinator lease: lock exists at ' + str(lock) + '; holder=' + detail
                                    + '; 核实持有进程已停止后，经 David 指示用 lease clear-lock') from exc
    except OSError as exc:
        raise CoordinatorLeaseError('coordinator lease: lock/write unavailable: ' + str(exc)) from exc
    finally:
        if owned:
            lock.unlink()


def parse_coordinator_lock(raw):
    """Invalid or legacy lock bytes have no trustworthy holder identity."""
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('schema') != 'coordinator-lease-lock/v1':
            return None
        if any(not isinstance(value.get(key), str) or not value[key].strip()
               for key in ('session_id', 'host')):
            return None
        if type(value.get('pid')) is not int or value['pid'] <= 0:
            return None
        if 'terminal_handle' not in value or (value['terminal_handle'] is not None
                                              and not isinstance(value['terminal_handle'], str)):
            return None
        lease_time(value.get('created_at'), 'created_at')
        return value
    except (ValueError, UnicodeError, RecursionError):
        return None


def read_coordinator_lock(lock):
    try:
        return parse_coordinator_lock(lock.read_bytes())
    except OSError:
        return None


def clear_coordinator_lease_lock(store, reason, david_instruction):
    if not reason or not reason.strip() or not david_instruction or not david_instruction.strip():
        raise CoordinatorLeaseError('coordinator lease: clear-lock requires reason and David instruction')
    lock = Path(store).resolve() / 'COORDINATOR-LEASE.lock'
    try:
        raw = lock.read_bytes()
        holder = parse_coordinator_lock(raw)
        alive = 'unknown'
        if holder is not None and holder['host'] == socket.gethostname():
            try:
                os.kill(holder['pid'], 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
            except OverflowError:
                # An out-of-range PID cannot describe a local OS process.
                holder = None
        if alive is True:
            raise CoordinatorLeaseError('coordinator lease: clear-lock refused: local holder is alive at ' + str(lock))
        row = {'event': 'clear-lock', 'lock_path': str(lock),
               'lock_sha256': hashlib.sha256(raw).hexdigest(), 'lock_content': holder,
               'holder_alive': alive, 'reason': reason, 'david_instruction': david_instruction,
               'cleared_by': coordinator_identity(), 'cleared_at': utc_text(lease_now())}
        with (lock.parent / 'COORDINATOR-LEASE.log').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        lock.unlink()
        return row
    except OSError as exc:
        raise CoordinatorLeaseError('coordinator lease: clear-lock unavailable at ' + str(lock) + ': ' + str(exc)) from exc


def write_coordinator_lease(store, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(store),
                                         prefix='COORDINATOR-LEASE.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(Path(store) / LEASE_FILE))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def mutate_coordinator_lease(store, action='acquire', reason=None, david_instruction=None):
    now = lease_now()
    identity = coordinator_identity()
    authorized_repair = action == 'takeover' and bool(david_instruction and david_instruction.strip())

    def preflight():
        try:
            lease = read_coordinator_lease(store)
        except CoordinatorLeaseError:
            if not authorized_repair:
                raise
            # Even an authorized repair must retain an actual digest of old bytes.
            try:
                raw = (Path(store) / LEASE_FILE).read_bytes()
            except OSError as exc:
                raise CoordinatorLeaseError('coordinator lease: unreadable old file for repair: ' + str(exc)) from exc
            return None, hashlib.sha256(raw).hexdigest()
        if action in ('renew', 'release'):
            if lease is None or 'released_at' in lease:
                raise CoordinatorLeaseError('coordinator lease: no active lease to ' + action)
            if not same_coordinator(lease, identity):
                raise CoordinatorLeaseError(coordinator_denial(lease, now))
        elif action == 'takeover':
            if not reason or not reason.strip():
                raise CoordinatorLeaseError('coordinator lease: takeover requires a nonempty reason')
            if not authorized_repair and (lease is None or not lease_expired(lease, now)):
                raise CoordinatorLeaseError('coordinator lease: takeover requires expiration or David instruction'
                                            + ('; ' + coordinator_denial(lease, now) if lease else ''))
        elif lease is not None and 'released_at' not in lease and not same_coordinator(lease, identity):
            # Expiration never silently transfers ownership; takeover records the transition.
            raise CoordinatorLeaseError(coordinator_denial(lease, now))
        return lease, None

    preflight()  # Conflicts/invalid files cause no lock creation or task-store writes.
    with coordinator_lease_lock(store):
        lease, old_digest = preflight()  # Recheck after the exclusive lock to close the read/write race.
        if action == 'release':
            value = {**lease, **identity, 'released_at': utc_text(now)}
        elif lease is not None and 'released_at' not in lease and action != 'takeover':
            value = {**lease, **identity, 'heartbeat_at': utc_text(now)}
        else:
            value = {'schema': 'coordinator-lease/v1', **identity, 'acquired_at': utc_text(now),
                     'heartbeat_at': utc_text(now), 'ttl_seconds': LEASE_TTL_SECONDS}
        if action == 'takeover':
            row = {'old_holder': lease, 'new_holder': value, 'reason': reason,
                   'expired': lease_expired(lease, now) if lease else (None if old_digest else False),
                   'david_instruction': david_instruction, 'taken_over_at': utc_text(now)}
            if old_digest is not None:
                row['old_file_sha256'] = old_digest
            # Persist the audit record before changing ownership; log failure denies takeover.
            with (Path(store) / 'COORDINATOR-LEASE.log').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        write_coordinator_lease(store, value)
    return value


def lease_command(args):
    if args.lease_action == 'clear-lock':
        return {'command': 'lease', 'action': 'clear-lock',
                'record': clear_coordinator_lease_lock(args.store, args.reason, args.david_instruction)}
    if args.lease_action == 'status':
        value = read_coordinator_lease(args.store)
        now = lease_now()
        return {'command': 'lease', 'action': 'status', 'lease': value,
                'expired': lease_expired(value, now) if value else False}
    return {'command': 'lease', 'action': args.lease_action,
            'lease': mutate_coordinator_lease(args.store, args.lease_action,
                                              args.reason, args.david_instruction)}


def load_context():
    # Lease helpers also serve standalone wait/spec scripts, without a package import.
    global context, worker_report, worker_report_handlers
    import managing_long_task_context as context
    import managing_long_task_context.worker_report as worker_report
    from managing_long_task_context.worker_report import worker_report_handlers


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError('value must not be empty')
    return value


def absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError('path must be absolute')
    return path


def task_id(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value) or value in ('.', '..'):
        raise argparse.ArgumentTypeError('invalid task id')
    return value


def check_spec(value):
    name, separator, command = value.partition('=')
    if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name) or not command.strip():
        raise argparse.ArgumentTypeError('check must be NAME=COMMAND with a filename-safe NAME')
    return name, command


def read_json(path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object: {path}')
    return value


def items(store, task):
    value = read_json(store / task / 'snapshot.json')['items']
    if not isinstance(value, dict) or any(not isinstance(i, dict) for i in value.values()):
        raise ValueError('invalid snapshot items')
    return list(value.values())


def ingest(args):
    load_context()
    raw = args.report.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or report.get('orca_dispatch_id') != args.dispatch:
        raise ValueError('report dispatch does not match --dispatch')
    suggestions = report.get('deferred_suggestions')
    if not isinstance(suggestions, list):
        raise ValueError('deferred_suggestions must be a list')
    digest = hashlib.sha256(raw).hexdigest()
    common = {'orca_dispatch_id': args.dispatch, 'report_sha256': digest}
    # Preflight every target before appending the main item, so a bad task does
    # not leave a half-ingested report. Reads never modify the snapshot cache.
    targets = []
    cache = {args.task: items(args.store, args.task)}
    for number, suggestion in enumerate(suggestions, 1):
        if not isinstance(suggestion, (str, dict)):
            raise ValueError('suggestion must be a string or JSON object')
        specified = isinstance(suggestion, dict) and bool(suggestion.get('task_id'))
        target = task_id(suggestion['task_id']) if specified else args.task
        if target not in cache:
            cache[target] = items(args.store, target)
        statement = suggestion if isinstance(suggestion, str) else json.dumps(suggestion, ensure_ascii=False, sort_keys=True)
        if not statement.strip():
            raise ValueError('empty suggestion')
        targets.append((number, target, statement, specified))
    source = {'kind': 'worker-report', 'ref': str(args.report)}
    created = []
    main = next((i for i in cache[args.task] if i.get('metadata', {}).get('role') == 'report-ingest'
                 and i.get('metadata', {}).get('orca_dispatch_id') == args.dispatch), None)
    if main is None:
        metadata = {**common, 'role': 'report-ingest', 'blocking': args.blocking}
        if args.verdict is not None:
            metadata['verdict'] = args.verdict
        main = context.record(args.task, statement=args.statement, item_type='observation', actor=args.actor,
            source=source, metadata=metadata, base_dir=args.store)
        created.append(main['id'])
    for number, target, statement, specified in targets:
        if any(i.get('metadata', {}).get('orca_dispatch_id') == args.dispatch
               and i.get('metadata', {}).get('report_item') == number for i in cache[target]):
            continue
        metadata = {**common, 'report_item': number, 'deferred': True}
        if not specified:
            metadata['report_task_unspecified'] = True
        item = context.record(target, statement=statement, item_type='observation', actor=args.actor,
            source=source, metadata=metadata, base_dir=args.store)
        created.append(item['id'])
    return {'command': 'ingest', 'main_item_id': main['id'], 'created_item_ids': created}


def settle(args):
    load_context()
    updated = []
    for item in items(args.store, args.task):
        metadata = item.get('metadata', {})
        if metadata.get('role') == 'report-ingest' and metadata.get('blocking') is True:
            context.update_item(args.task, item['id'], actor=args.actor,
                metadata={**metadata, 'blocking': False, 'resolved_by': args.resolved_by}, base_dir=args.store)
            updated.append(item['id'])
    return {'command': 'settle', 'updated_item_ids': updated}


def checkpoint(args):
    load_context()
    value = context.checkpoint(args.task, phase=args.phase, completed=args.completed,
        evidence_added=args.evidence, blockers=args.blocker, next_action=args.next_action,
        actor=args.actor, base_dir=args.store)
    return {'command': 'checkpoint', 'checkpoint': value}


def git(root, *arguments):
    return subprocess.run(['git', '-C', str(root), *arguments], capture_output=True,
                          check=True, timeout=20).stdout


def accept(args):
    load_context()
    clean_validator = getattr(worker_report, '_revision_is_clean', None)
    if not callable(clean_validator):
        raise ValueError('loaded package has no revision clean validator')
    workspace = args.workspace.resolve()
    if Path(git(workspace, 'rev-parse', '--show-toplevel').decode().rstrip('\n')).resolve() != workspace:
        raise ValueError('--workspace must be the Git top-level directory')
    logs = args.logs_dir.resolve()
    logs.relative_to(workspace)
    contract = read_json(args.store / args.task / 'task-contract.json')
    checks = []
    names = set()
    for name, command in args.check:
        if name in names:
            raise ValueError('duplicate check NAME')
        names.add(name)
        output = logs / (name + '.log')
        raw = output.read_bytes()
        exit_code = int((logs / (name + '.exit')).read_text().strip())
        checks.append({'command': command, 'exit_code': exit_code,
            'output_file': output.relative_to(workspace).as_posix(),
            'output_sha256': hashlib.sha256(raw).hexdigest(),
            'output_summary': raw.decode('utf-8', 'replace')[-2000:]})
    runtime = context.runtime_identity(package_root=args.package_root)
    identity = runtime['identity']
    manifest = identity.get('loaded_manifest_sha256')
    module = identity.get('runtime_path')
    if runtime.get('status') != 'pass' or not isinstance(manifest, str) or not re.fullmatch(r'[0-9a-f]{64}', manifest):
        raise ValueError('loaded package has no verified manifest identity')
    if not module or not Path(module).resolve().is_relative_to(args.package_root.resolve()):
        raise ValueError('PYTHONPATH loaded a different package')
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    run_id = 'coordinator-' + uuid.uuid4().hex
    revision = {'commit': git(workspace, 'rev-parse', '--verify', 'HEAD').decode().strip(),
                'dirty': False}
    revision['dirty'] = not clean_validator(workspace, revision)
    good = not revision['dirty'] and all(c['exit_code'] == 0 for c in checks)
    report = {'schema': 1, 'task_id': args.task, 'orca_task_id': args.task, 'orca_dispatch_id': run_id,
        'contract_digest': contract['seal']['integrity_digest'], 'loaded_module_file': module,
        'loaded_manifest_sha256': manifest, 'code_revision': revision, 'checks': checks,
        'files_modified': [], 'deferred_suggestions': [],
        'outcome_claim': 'succeeded' if good else 'failed', 'written_at': now}
    report_path = logs / (run_id + '.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    locator = report_path.relative_to(workspace).as_posix()
    artifact_digest = 'sha256:' + hashlib.sha256(report_path.read_bytes()).hexdigest()
    evidence_map = {}
    for criterion in contract['acceptance_criteria']:
        evidence_map[criterion['id']] = {'evidence': [{
            'evidence_id': run_id + '-' + criterion['id'], 'kind': 'worker-report', 'locator': locator,
            'generated_at': now, 'produced_by': args.recorded_by, 'artifact_digest': artifact_digest,
            'contract_version': contract['version'], 'scope': criterion.get('required_scope', {}),
            'covered_hops': criterion.get('required_hops', []), 'code_revision': revision,
        }], 'delivery_receipts': []}
    resolvers, verifiers = worker_report_handlers(workspace)
    previous_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        result = context.record_acceptance(args.task, evidence_map=evidence_map, resolvers=resolvers,
            verifiers=verifiers, watched_paths=args.watched_path, recorded_by=args.recorded_by,
            base_dir=args.store, workspace_root=workspace)
    finally:
        os.chdir(previous_cwd)
    decision = result.get('record', {}).get('decision', 'unknown')
    value = context.checkpoint(args.task, phase='acceptance',
        completed=[f'acceptance decision: {decision}'], evidence_added=['file:' + str(report_path)],
        next_action='publish acceptance record' if decision == 'pass' else 'resolve acceptance findings',
        blockers=[] if decision == 'pass' else [result.get('reason', decision)],
        actor=args.recorded_by, base_dir=args.store)
    return {'command': 'accept', 'decision': decision, 'report_path': str(report_path),
            'acceptance': result, 'checkpoint': value}


def parser():
    cli = JsonParser(description=__doc__)
    commands = cli.add_subparsers(dest='command', required=True)
    lease = commands.add_parser('lease')
    actions = lease.add_subparsers(dest='lease_action', required=True)
    for action in ('status', 'acquire', 'renew', 'release', 'takeover', 'clear-lock'):
        sub = actions.add_parser(action)
        sub.add_argument('--store', type=absolute, required=True)
        sub.set_defaults(function=lease_command, reason=None, david_instruction=None)
        if action in ('takeover', 'clear-lock'):
            sub.add_argument('--reason', type=nonempty, required=True)
            sub.add_argument('--david-instruction', type=nonempty, required=action == 'clear-lock')
    for name, function in [('ingest', ingest), ('settle', settle), ('checkpoint', checkpoint), ('accept', accept)]:
        sub = commands.add_parser(name)
        sub.add_argument('--store', type=absolute, required=True)
        sub.add_argument('--task', type=task_id, required=True)
        sub.set_defaults(function=function)
        if name != 'accept':
            sub.add_argument('--actor', type=nonempty, default=ACTOR)
        if name == 'ingest':
            sub.add_argument('--report', type=absolute, required=True)
            sub.add_argument('--dispatch', type=nonempty, required=True)
            sub.add_argument('--statement', type=nonempty, required=True)
            sub.add_argument('--verdict', type=nonempty)
            sub.add_argument('--blocking', action='store_true')
        elif name == 'settle':
            sub.add_argument('--resolved-by', type=nonempty, required=True)
        elif name == 'checkpoint':
            for field in ('phase', 'next-action'):
                sub.add_argument('--' + field, type=nonempty, required=True)
            for field in ('completed', 'evidence'):
                sub.add_argument('--' + field, action='append', type=nonempty, required=True)
            sub.add_argument('--blocker', action='append', type=nonempty, default=[])
        else:
            for field in ('workspace', 'package-root', 'logs-dir'):
                sub.add_argument('--' + field, type=absolute, required=True)
            sub.add_argument('--check', action='append', type=check_spec, required=True)
            sub.add_argument('--watched-path', action='append', type=nonempty, default=[])
            sub.add_argument('--recorded-by', type=nonempty, required=True)
    return cli


def main(argv=None):
    errors = (ValueError, TypeError, KeyError, OSError, argparse.ArgumentTypeError,
              subprocess.SubprocessError)
    try:
        args = parser().parse_args(argv)
        if args.command != 'lease':
            mutate_coordinator_lease(args.store)
            load_context()
            errors += (context.ContextError,)
        result = args.function(args)
        status = 1 if args.command == 'accept' and result['decision'] != 'pass' else 0
    except CoordinatorLeaseError as exc:
        message = str(exc).replace('\n', ' ').replace('\r', ' ')
        print(message, file=sys.stderr)
        result = {'error': message, 'exception_type': type(exc).__name__}
        status = 3
    except errors as exc:
        result = {'error': str(exc), 'exception_type': type(exc).__name__}
        status = 2
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
