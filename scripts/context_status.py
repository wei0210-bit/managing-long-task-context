#!/usr/bin/env python3
"""Read six task-status sections without contacting Orca or writing the stores."""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Iterable

from context_doctor import resume
from managing_long_task_context.project_store import (
    StoreNotWritable, context_root, read_task, resolve_worktree_root,
)


def _unavailable(label: str, exc: Exception | None = None, **fields) -> dict:
    name = type(exc).__name__ if exc is not None else None
    return {**fields, 'status': 'unavailable', 'exception_type': name,
            'message': label + '不可用' + (f'（{name}）' if name else '')}


def _safe_json(value, active=None, depth=0):
    """Keep valid values; mark unsupported, cyclic or overly deep values explicitly."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        import math
        return value if math.isfinite(value) else '<unavailable: non-finite float>'
    if not isinstance(value, (dict, list, tuple)):
        return '<unavailable: non-serializable ' + type(value).__name__ + '>'
    if depth >= 80:
        return '<unavailable: RecursionError depth limit>'
    active = set() if active is None else active
    if id(value) in active:
        return '<unavailable: ValueError circular reference>'
    active.add(id(value))
    try:
        if isinstance(value, dict):
            return {key if isinstance(key, str) else
                    '<unavailable: non-string key ' + type(key).__name__ + '>':
                    _safe_json(item, active, depth + 1) for key, item in value.items()}
        return [_safe_json(item, active, depth + 1) for item in value]
    finally:
        active.remove(id(value))


def _section(builder, label: str, **fallback) -> dict:
    # Each section owns both construction and serialization failures. Never let
    # ancillary snapshot/rendering failures replace the resume exit code.
    try:
        return _safe_json(builder())
    except Exception as exc:
        return _unavailable(label, exc, **fallback)


def _resume_result(args):
    result = resume(args)
    if not isinstance(result, dict):
        raise TypeError('resume result must be a dict')
    diagnostic = result['diagnostic']
    if not isinstance(diagnostic, dict):
        raise TypeError('diagnostic must be a dict')
    if diagnostic['status'] not in ('pass', 'fail', 'unknown'):
        raise ValueError('invalid diagnostic status')
    if (not isinstance(diagnostic['codes'], list) or
            diagnostic['next_action'] is not None and not isinstance(diagnostic['next_action'], str)):
        raise TypeError('invalid diagnostic fields')
    checks = diagnostic['checks']
    if not isinstance(checks, list):
        raise TypeError('checks must be a list')
    for check in checks:
        if (not isinstance(check, dict) or not isinstance(check['name'], str)
                or check['status'] not in ('pass', 'fail', 'unknown', 'not_run')):
            raise TypeError('invalid diagnostic check')
    if result['context'] is not None and not isinstance(result['context'], dict):
        raise TypeError('context must be a dict or null')
    return result


def _identity(args, diagnostic):
    identity = {key: diagnostic[key] for key in ('status', 'codes', 'next_action')}
    if 'BINDING_MISSING' in diagnostic['codes']:
        command = shlex.join(['python3', str(Path(args.package_root) / 'scripts/context_doctor.py'),
                            'init-binding', '--package-root', args.package_root,
                            '--context-root', args.context_root, '--workspace-root', args.workspace_root,
                            '--task-id', args.task_id])
        identity['next_action'] = (command + ' --expected-manifest-sha256 '
            '<从派工说明或接手文档取得的独立留存摘要>\n仅协调者执行，执行前先核对摘要。')
    return identity


def _gate(result, verified):
    diagnostic = result['diagnostic']
    checks = {c['name']: c for c in diagnostic['checks']}
    gate_checks = [c for c in diagnostic['checks'] if c['name'].startswith('resume_')]
    gate_status = ('fail' if any(c['status'] == 'fail' for c in gate_checks) else
                   'unknown' if any(c['status'] == 'unknown' for c in gate_checks) else 'pass')
    gate = {'status': gate_status if verified else 'not_run', 'report': result.get('resume_gate'),
            'checks': gate_checks, 'next_action': diagnostic['next_action'],
            'message': '' if verified else '未运行（身份未通过）'}
    if checks.get('resume_handlers', {}).get('status') == 'not_run':
        gate['message'] = '完成门需要宿主提供处理器'
    return gate


def _snapshot(args):
    # read_task only knows the default store. Check the selected root before
    # touching it, and let each consuming section isolate read/rebuild errors.
    try:
        workspace = resolve_worktree_root(Path(args.workspace_root))
    except StoreNotWritable:
        return None, '快照不可用'
    if Path(args.context_root).resolve() != context_root(workspace):
        return None, '快照不可用（context root 不是工作区默认位置）'
    data = read_task(args.task_id, workspace)
    if not isinstance(data, dict):
        raise TypeError('read_task must return a dict')
    snapshot = data['snapshot']
    if snapshot is not None and not isinstance(snapshot, dict):
        raise TypeError('snapshot must be a dict')
    return data if snapshot is not None else None, '快照不可用'


def _checkpoint(args, verified):
    data, message = _snapshot(args)
    if data is None:
        return {'identity_verified': verified, 'data': None, 'message': message}
    latest = data['latest_checkpoint']
    if latest is not None and not isinstance(latest, dict):
        raise TypeError('checkpoint must be a dict')
    return {'identity_verified': verified,
            'data': {key: latest.get(key) for key in
                     ('phase', 'completed', 'next_action', 'blockers')} if latest else None,
            'message': ('' if latest else '无检查点') + ('' if verified else '（未经身份校验）')}


def _dispatches(args, verified):
    data, message = _snapshot(args)
    if data is None:
        return {'identity_verified': verified, 'data': None, 'message': message}
    grouped = {}
    skipped = 0
    items = data['snapshot'].get('items', {})
    if not isinstance(items, dict):
        raise TypeError('snapshot items must be a dict')
    for identifier, item in items.items():
        metadata = item.get('metadata') if isinstance(item, dict) else None
        dispatch_id = metadata.get('orca_dispatch_id') if isinstance(metadata, dict) else None
        if not isinstance(dispatch_id, str) or not dispatch_id:
            skipped += 1
            continue
        entry = grouped.setdefault(dispatch_id, {'orca_dispatch_id': dispatch_id,
                                   'main_item_ids': [], 'suggestion_count': 0})
        if 'report_item' in metadata:
            entry['suggestion_count'] += 1
        else:
            entry['main_item_ids'].append(identifier)
    for entry in grouped.values():
        entry['main_item_ids'].sort(key=lambda identifier: (type(identifier).__name__, str(identifier)))
    return {'identity_verified': verified, 'data': [grouped[key] for key in sorted(grouped)],
            'skipped_count': skipped, 'status': 'unavailable' if skipped else 'available',
            'message': (f'部分派单数据不可用（跳过 {skipped} 个条目）' if skipped else '')
                       + ('' if verified else '未经身份校验')}


def _brief(result, verified):
    if not verified:
        return {'markdown': None, 'message': '不可用（身份未通过）'}
    prompt = result['context']['prompt']
    if not isinstance(prompt, str):
        raise TypeError('brief prompt must be a string')
    return {'markdown': prompt, 'message': ''}


def status(args: argparse.Namespace) -> tuple[dict, int]:
    try:
        result = _resume_result(args)
    except Exception as exc:
        result = None
        identity = _unavailable('身份诊断', exc)
        code = 2
    else:
        identity = _section(lambda: _identity(args, result['diagnostic']), '身份诊断')
        code = {'pass': 0, 'fail': 1, 'unknown': 2}.get(result['diagnostic']['status'], 2)
    verified = result is not None and result['context'] is not None
    gate = (_section(lambda: _gate(result, verified), '恢复门禁') if result is not None
            else _unavailable('恢复门禁', message='未运行（身份诊断不可用）'))
    checkpoint = _section(lambda: _checkpoint(args, verified), '快照',
                          identity_verified=verified, data=None)
    dispatches = _section(lambda: _dispatches(args, verified), '快照',
                          identity_verified=verified, data=None)
    brief = _section(lambda: _brief(result, verified), 'brief', markdown=None)
    from managing_long_task_context.acceptance import acceptance_status
    acceptance = _section(lambda: acceptance_status(args.task_id, base_dir=args.context_root,
                          workspace_root=args.workspace_root), '验收')
    return {'identity': identity, 'resume_gate': gate, 'checkpoint': checkpoint,
            'dispatches': dispatches, 'brief': brief, 'acceptance': acceptance}, code


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package-root', 'context-root', 'workspace-root', 'task-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result, code = status(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        for title, key in [('身份', 'identity'), ('恢复门禁', 'resume_gate'), ('最近检查点', 'checkpoint'),
                           ('已入账的 Orca 派单', 'dispatches'), ('brief 正文', 'brief'), ('验收', 'acceptance')]:
            print('## ' + title)
            value = result[key]
            if key == 'brief':
                print(value['markdown'] or value['message'])
            else:
                print(json.dumps(value, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
