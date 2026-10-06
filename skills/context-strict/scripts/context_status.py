#!/usr/bin/env python3
"""Read five task-status sections without contacting Orca or writing the stores."""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Iterable

from context_doctor import resume
from managing_long_task_context import ContextError
from managing_long_task_context.project_store import (
    StoreNotWritable, context_root, read_task, resolve_worktree_root,
)


def status(args: argparse.Namespace) -> tuple[dict, int]:
    result = resume(args)
    diagnostic = result['diagnostic']
    context = result['context']
    verified = context is not None
    identity = {'status': diagnostic['status'], 'codes': diagnostic['codes'],
                'next_action': diagnostic['next_action']}
    if 'BINDING_MISSING' in diagnostic['codes']:
        command = shlex.join(['python3', str(Path(args.package_root) / 'scripts/context_doctor.py'),
                            'init-binding', '--package-root', args.package_root,
                            '--context-root', args.context_root, '--workspace-root', args.workspace_root,
                            '--task-id', args.task_id])
        identity['next_action'] = (command + ' --expected-manifest-sha256 '
            '<从派工说明或接手文档取得的独立留存摘要>\n仅协调者执行，执行前先核对摘要。')
    checks = {c['name']: c for c in diagnostic['checks']}
    gate_checks = [c for c in diagnostic['checks'] if c['name'].startswith('resume_')]
    gate_status = ('fail' if any(c['status'] == 'fail' for c in gate_checks) else
                   'unknown' if any(c['status'] == 'unknown' for c in gate_checks) else 'pass')
    gate = {'status': gate_status if verified else 'not_run', 'report': result.get('resume_gate'),
            'checks': gate_checks, 'next_action': diagnostic['next_action'],
            'message': '' if verified else '未运行（身份未通过）'}
    if checks.get('resume_handlers', {}).get('status') == 'not_run':
        gate['message'] = '完成门需要宿主提供处理器'
    # read_task uses the Git worktree's default store; never substitute another
    # root's snapshot merely because it happens to contain a task with this ID.
    try:
        workspace = resolve_worktree_root(Path(args.workspace_root))
    except StoreNotWritable:
        data = {'snapshot': None, 'latest_checkpoint': None}
        unavailable = '快照不可用'
    else:
        unavailable = '快照不可用'
        if Path(args.context_root).resolve() != context_root(workspace):
            data = {'snapshot': None, 'latest_checkpoint': None}
            unavailable = '快照不可用（context root 不是工作区默认位置）'
        else:
            try:
                data = read_task(args.task_id, workspace)
            except (ContextError, OSError, ValueError, TypeError):
                # An unreadable snapshot must not discard resume diagnostics.
                data = {'snapshot': None, 'latest_checkpoint': None}
    snapshot = data['snapshot']
    checkpoint = {'identity_verified': verified, 'data': None, 'message': unavailable}
    dispatches = {'identity_verified': verified, 'data': None, 'message': unavailable}
    if snapshot is not None:
        latest = data['latest_checkpoint']
        checkpoint['data'] = ({key: latest.get(key) for key in
                              ('phase', 'completed', 'next_action', 'blockers')} if latest else None)
        checkpoint['message'] = ('' if latest else '无检查点') + ('' if verified else '（未经身份校验）')
        grouped = {}
        for identifier, item in snapshot.get('items', {}).items():
            metadata = item.get('metadata', {})
            dispatch_id = metadata.get('orca_dispatch_id')
            if not dispatch_id:
                continue
            entry = grouped.setdefault(dispatch_id, {'orca_dispatch_id': dispatch_id,
                                        'main_item_ids': [], 'suggestion_count': 0})
            if 'report_item' in metadata:
                entry['suggestion_count'] += 1
            else:
                entry['main_item_ids'].append(identifier)
        for entry in grouped.values():
            entry['main_item_ids'].sort()
        dispatches['data'] = [grouped[key] for key in sorted(grouped)]
        dispatches['message'] = '' if verified else '未经身份校验'
    brief = {'markdown': context['prompt'] if verified else None,
             'message': '' if verified else '不可用（身份未通过）'}
    return {'identity': identity, 'resume_gate': gate, 'checkpoint': checkpoint,
            'dispatches': dispatches, 'brief': brief}, {'pass': 0, 'fail': 1, 'unknown': 2}[diagnostic['status']]


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
                           ('已入账的 Orca 派单', 'dispatches'), ('brief 正文', 'brief')]:
            print('## ' + title)
            value = result[key]
            if key == 'brief':
                print(value['markdown'] or value['message'])
            else:
                print(json.dumps(value, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
