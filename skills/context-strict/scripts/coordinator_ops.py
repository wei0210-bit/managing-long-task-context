#!/usr/bin/env python3
"""Shared ledger recording operations; PYTHONPATH selects the package.

Record reports, metadata changes and checkpoints in the selected store.
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


def parser():
    cli = JsonParser(description=__doc__)
    commands = cli.add_subparsers(dest='command', required=True)
    for name, function in [('ingest', ingest), ('settle', settle), ('checkpoint', checkpoint)]:
        sub = commands.add_parser(name)
        sub.add_argument('--store', type=absolute, required=True)
        sub.add_argument('--task', type=task_id, required=True)
        sub.set_defaults(function=function)
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
    return cli


def main(argv=None):
    errors = (ValueError, TypeError, KeyError, OSError, argparse.ArgumentTypeError,
              subprocess.SubprocessError)
    try:
        args = parser().parse_args(argv)
        load_context()
        errors += (context.ContextError,)
        result = args.function(args)
        status = 0
    except errors as exc:
        result = {'error': str(exc), 'exception_type': type(exc).__name__}
        status = 2
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
