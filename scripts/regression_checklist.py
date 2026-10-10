#!/usr/bin/env python3
"""Run each repository regression entry with bash errexit and retain its result."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPECIAL_ENTRIES = {'R-001': 'empty-match', 'R-007': 'document-counts', 'R-026': 'zero-count'}


def entries(text):
    headings = list(re.finditer(r'^### (R-\d+)[^\n]*\n?', text, re.M))
    if not headings:
        raise ValueError('checklist has no entries')
    result = []
    for index, heading in enumerate(headings):
        body = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)]
        blocks, lines, fence, shell = [], [], None, False
        for line in body.splitlines():
            opening = re.match(r'^\s*(`{3,})([^`]*)$', line)
            if fence is None:
                if opening:
                    fence = opening.group(1)
                    shell = opening.group(2).strip() == 'sh'
                    lines = []
            elif re.fullmatch(r'\s*`{' + str(len(fence)) + r',}\s*', line):
                if shell:
                    blocks.append('\n'.join(lines) + '\n')
                fence = None
            else:
                lines.append(line)
        if fence is not None and shell:
            raise ValueError(heading.group(1) + ': unclosed sh code block')
        result.append((heading.group(1), bool(re.search(r'^Retired\b', body, re.M)), blocks))
    return result


def run_entry(rid, retired, blocks, root, timeout):
    row = {'id': rid, 'status': 'retired' if retired else 'manual', 'exit_code': 0, 'blocks': []}
    outputs = []
    if not retired and blocks:
        row['status'] = 'pass'
        for index, code in enumerate(blocks, 1):
            special = SPECIAL_ENTRIES.get(rid)
            commands = code.splitlines() if special == 'document-counts' else (
                code.strip().split('; ') if special == 'zero-count' else [code])
            if ((special == 'document-counts' and (len(commands) != 4 or not all(commands)))
                    or (special == 'zero-count' and (len(commands) != 2 or not all(commands)))):
                row.update(status='fail', exit_code=2, error='特殊条目形状已变')
                outputs.append((rid + ': 特殊条目形状已变\n').encode('utf-8'))
                continue
            for step, command in enumerate(commands, 1):
                try:
                    shell = ['bash', '-c'] if special in ('document-counts', 'zero-count') else ['bash', '-e', '-c']
                    process = subprocess.run(shell + [command], cwd=str(root),
                                             capture_output=True, timeout=timeout)
                    exit_code, stdout, stderr = process.returncode, process.stdout, process.stderr
                except subprocess.TimeoutExpired as exc:
                    exit_code, stdout, stderr = 124, exc.stdout or b'', exc.stderr or b''
                    stderr += b'\nchecklist command timed out\n'
                ok = exit_code == 0
                if special == 'empty-match' or (special == 'document-counts' and step == 1):
                    ok = exit_code == 1 and not stdout
                elif special == 'document-counts':
                    counts = re.findall(rb'^(CLAUDE\.md|AGENTS\.md):(\d+)\s*$', stdout, re.M)
                    ok = (exit_code == 0 and {name for name, count in counts} == {b'CLAUDE.md', b'AGENTS.md'}
                          and all(int(count) >= 1 for name, count in counts))
                elif special == 'zero-count' and step == 1:
                    ok = exit_code in (0, 1) and stdout.strip() == b'0'
                row['blocks'].append({'index': index, 'step': step, 'exit_code': exit_code, 'pass': ok})
                outputs.append(('block=' + str(index) + ' step=' + str(step) + ' exit=' + str(exit_code)
                                + '\nstdout:\n').encode() + stdout + b'\nstderr:\n' + stderr + b'\n')
                if not ok:
                    if row['status'] != 'fail':
                        row['exit_code'] = exit_code
                    row['status'] = 'fail'
                elif row['status'] != 'fail':
                    row['exit_code'] = exit_code
    return row, b''.join(outputs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checklist', default='docs/regression-checklist.md')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--log-dir', type=Path)
    parser.add_argument('--timeout', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError('timeout must be positive')
        root = args.root.resolve()
        checklist = Path(args.checklist)
        if not checklist.is_absolute():
            checklist = root / checklist
        parsed = entries(checklist.read_text(encoding='utf-8'))
        if args.log_dir:
            args.log_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for rid, retired, blocks in parsed:
            row, output = run_entry(rid, retired, blocks, root, args.timeout)
            if args.log_dir:
                row['output_file'] = rid + '.log'
                row['output_sha256'] = hashlib.sha256(output).hexdigest()
                (args.log_dir / row['output_file']).write_bytes(output)
            rows.append(row)
            if row.get('error'):
                print(rid + ': ' + row['error'], file=sys.stderr)
            print(rid + ' ' + row['status'] + ' exit=' + str(row['exit_code']), flush=True)
        failed = any(row['status'] == 'fail' for row in rows)
        if args.log_dir:
            (args.log_dir / 'summary.json').write_text(
                json.dumps({'entries': rows, 'exit_code': int(failed)}, indent=2) + '\n', encoding='utf-8')
        return int(failed)
    except (OSError, ValueError, UnicodeError) as exc:
        print(str(exc).replace('\n', ' ').replace('\r', ' '), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
