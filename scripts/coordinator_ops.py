#!/usr/bin/env python3
"""Coordinator ledger and acceptance operations; PYTHONPATH selects the package.

Only the coordinator should run these writes against a shared store. Check
commands are labels for previously captured logs, never executed by this CLI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

import managing_long_task_context as context
import managing_long_task_context.worker_report as worker_report
from managing_long_task_context.worker_report import worker_report_handlers


ACTOR = 'coordinator'


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
    updated = []
    for item in items(args.store, args.task):
        metadata = item.get('metadata', {})
        if metadata.get('role') == 'report-ingest' and metadata.get('blocking') is True:
            context.update_item(args.task, item['id'], actor=args.actor,
                metadata={**metadata, 'blocking': False, 'resolved_by': args.resolved_by}, base_dir=args.store)
            updated.append(item['id'])
    return {'command': 'settle', 'updated_item_ids': updated}


def checkpoint(args):
    value = context.checkpoint(args.task, phase=args.phase, completed=args.completed,
        evidence_added=args.evidence, blockers=args.blocker, next_action=args.next_action,
        actor=args.actor, base_dir=args.store)
    return {'command': 'checkpoint', 'checkpoint': value}


def git(root, *arguments):
    return subprocess.run(['git', '-C', str(root), *arguments], capture_output=True,
                          check=True, timeout=20).stdout


def accept(args):
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
    try:
        args = parser().parse_args(argv)
        result = args.function(args)
        status = 1 if args.command == 'accept' and result['decision'] != 'pass' else 0
    except (ValueError, TypeError, KeyError, OSError, argparse.ArgumentTypeError,
            context.ContextError, subprocess.SubprocessError) as exc:
        result = {'error': str(exc), 'exception_type': type(exc).__name__}
        status = 2
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
