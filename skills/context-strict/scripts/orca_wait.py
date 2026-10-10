#!/usr/bin/env python3
"""Wait for an actionable whole Orca delivery, with power checks and bounded retries.

Run power-check before dispatching workers. Waiting checks power automatically;
only heartbeat/status deliveries are acknowledged on the following wait call.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


_lease_spec = importlib.util.spec_from_file_location(
    'orca_wait_coordinator_lease', Path(__file__).with_name('coordinator_ops.py'))
coordinator_lease = importlib.util.module_from_spec(_lease_spec)
_lease_spec.loader.exec_module(coordinator_lease)


FATAL = {'consumer_fenced', 'run_not_found', 'stable_pane_required', 'invalid_argument'}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError('value must not be blank')
    return value


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('value must be positive and finite')
    return number


def milliseconds(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('timeout must be positive')
    return number


def battery_percent(value):
    number = int(value)
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError('battery threshold must be between 0 and 100')
    return number


def parser():
    cli = Parser(description=__doc__)
    cli.add_argument('command', nargs='?', choices=['power-check'])
    cli.add_argument('--run', type=nonempty)
    cli.add_argument('--store', type=coordinator_lease.absolute)
    cli.add_argument('--ack', type=nonempty)
    cli.add_argument('--timeout-ms', type=milliseconds, default=3600000)
    cli.add_argument('--max-minutes', type=positive)
    cli.add_argument('--log')
    cli.add_argument('--orca', type=nonempty, default='orca')
    cli.add_argument('--pmset', type=nonempty, default='pmset')
    cli.add_argument('--caffeinate', type=nonempty, default='caffeinate')
    cli.add_argument('--min-battery', type=battery_percent, default=40)
    cli.add_argument('--allow-battery', action='store_true')
    return cli


def warning(message):
    print('警告：' + message, file=sys.stderr)


def parse_power(raw):
    """Return the first-line power source and second-line battery percentage."""
    lines = raw.splitlines()
    source = None
    if lines:
        match = re.search(r"Now drawing from '(AC Power|Battery Power|UPS Power)'", lines[0])
        if match:
            source = match.group(1)
    percentage = None
    if source and len(lines) > 1:
        match = re.search(r'(?<!\d)(\d{1,3})%', lines[1])
        if match and 0 <= int(match.group(1)) <= 100:
            percentage = int(match.group(1))
    return source, percentage


def power_check(args):
    """Return exit status and power source; unknown observations remain warnings."""
    warning('合盖会休眠；caffeinate 无法阻止合盖休眠。')
    try:
        result = subprocess.run([args.pmset, '-g', 'batt'], capture_output=True,
                                text=True, errors='replace', timeout=10)
        source, percentage = parse_power(result.stdout) if result.returncode == 0 else (None, None)
    except (OSError, subprocess.SubprocessError):
        source, percentage = None, None
    if source is None or percentage is None:
        warning('无法完整解析电源或电量，请检查电源状态。')
    if source == 'Battery Power':
        warning(f'正在使用电池，电量 {percentage if percentage is not None else "未知"}%。')
        if percentage is not None and percentage < args.min_battery:
            warning(f'电量低于 {args.min_battery}% 阈值。')
            if not args.allow_battery:
                return 3, source
    if source == 'UPS Power':
        warning('正在使用 UPS 电源。')
    return 0, source


def log_entry(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
    stream.flush()


def coordinator_store(explicit=None):
    if explicit is not None:
        return explicit
    # Walk to the nearest Git top level without invoking an external process.
    # A worktree has a .git file; an ordinary checkout has a .git directory.
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        if (directory / '.git').exists():
            store = directory / '.prime/context'
            return store if store.is_dir() else None
    return None


def decode_receipt(result):
    """Normalize CLI envelopes and direct payloads without losing delivery fields."""
    try:
        raw = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None, 'non_json_output'
    if not isinstance(raw, dict):
        return None, 'invalid_receipt'
    error = raw.get('error')
    code = error.get('code') if isinstance(error, dict) else error
    if isinstance(code, str) and code:
        return None, code
    if result.returncode != 0:
        return None, 'nonzero_exit'
    if raw.get('ok') is False:
        return None, 'invalid_receipt'
    payload = raw.get('result', raw)
    if not isinstance(payload, dict):
        return None, 'invalid_receipt'
    for field in ('connectionLost', 'cancelled'):
        if payload.get(field):
            return None, field
    return payload, None


def wait(args, deadline, log):
    ack = args.ack
    failures = 0
    previous_waiter_exists = False
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return 2
        if args.store is not None:
            coordinator_lease.mutate_coordinator_lease(args.store)
        timeout_ms = args.timeout_ms
        if remaining is not None:
            timeout_ms = min(timeout_ms, max(1, int(remaining * 1000)))
        command = [args.orca, 'orchestration', 'check', '--run', args.run]
        if ack:
            command += ['--ack', ack]
        command += ['--wait', '--timeout-ms', str(timeout_ms), '--json']
        # Leave room for CLI shutdown, but never exceed the total deadline.
        process_timeout = timeout_ms / 1000 + 5
        if remaining is not None:
            process_timeout = min(process_timeout, remaining)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    errors='replace', timeout=process_timeout)
            payload, error = decode_receipt(result)
        except (OSError, subprocess.SubprocessError) as exc:
            payload, error = None, type(exc).__name__
        if deadline is not None and time.monotonic() >= deadline:
            return 2
        if error is None:
            messages = payload.get('messages', [])
            if not isinstance(messages, list) or any(not isinstance(m, dict) for m in messages):
                error = 'invalid_messages'
            elif messages and not payload.get('deliveryId'):
                error = 'missing_delivery_id'
        if error is not None:
            log_entry(log, {'event': 'retry_error', 'error': error, 'failures': failures + 1})
            if error in FATAL or (error == 'waiter_exists' and previous_waiter_exists):
                warning('Orca 等待失败：' + error)
                return 4
            previous_waiter_exists = error == 'waiter_exists'
            failures += 1
            if failures >= 20:
                warning('Orca 等待连续失败 20 次。')
                return 4
            delay = min(2 ** (failures - 1), 15)
            if deadline is not None:
                delay = min(delay, max(0, deadline - time.monotonic()))
            time.sleep(delay)
            continue
        failures = 0
        previous_waiter_exists = False
        ack = None  # The previous ack was consumed by this successful call.
        if messages:
            if any(m.get('type') not in ('heartbeat', 'status') for m in messages):
                print(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
                return 0
            log_entry(log, payload)
            ack = payload['deliveryId']
        else:
            log_entry(log, payload)
            # Timeout/empty responses immediately rehang without acknowledgement.


def main(argv=None):
    caffeine = None
    log = None
    try:
        args = parser().parse_args(argv)
        if args.command != 'power-check' and args.run is None:
            raise ValueError('--run is required for waiting')
        if args.command != 'power-check':
            args.store = coordinator_store(args.store)
            if args.store is not None:
                coordinator_lease.mutate_coordinator_lease(args.store)
    except coordinator_lease.CoordinatorLeaseError as exc:
        print(str(exc).replace('\n', ' ').replace('\r', ' '), file=sys.stderr)
        return 3
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    deadline = None if args.max_minutes is None else time.monotonic() + args.max_minutes * 60
    status, source = power_check(args)
    if status or args.command == 'power-check':
        return status
    try:
        options = ['-i', '-s', '-w'] if source == 'AC Power' else ['-i', '-w']
        try:
            caffeine = subprocess.Popen([args.caffeinate, *options, str(os.getpid())],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            warning('无法启动 caffeinate：' + str(exc))
        log = open(args.log, 'a', encoding='utf-8') if args.log else sys.stderr
        return wait(args, deadline, log)
    except coordinator_lease.CoordinatorLeaseError as exc:
        print(str(exc).replace('\n', ' ').replace('\r', ' '), file=sys.stderr)
        return 3
    except OSError as exc:
        warning(str(exc))
        return 4
    finally:
        if log is not None and log is not sys.stderr:
            log.close()
        if caffeine is not None and caffeine.poll() is None:
            try:
                caffeine.terminate()
                caffeine.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass


if __name__ == '__main__':
    raise SystemExit(main())
