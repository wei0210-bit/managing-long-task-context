#!/usr/bin/env python3
"""Reproduce three local review findings; never invokes a real Codex host/model.

Only the repository's fixed Python fake-CLI subprocess and FakeLedger are used.
Temporary fixture outputs are isolated and removed by TemporaryDirectory.
Exit 0 means all three previously observed findings remain reproducible.

Version audit, without changing sys.getrecursionlimit() (1000 on both):
* Python 3.9.6: depth 1100 fails through public resume_child.
* Python 3.12.13: depth 1100 parses through public resume_child.
* Both versions: depth 10000 / 20087 bytes fails through public resume_child.
A separate top-level json.loads binary probe using {"extra": nested_array}
found first RecursionError at 995 / 9997 array levels respectively. Exact
thresholds depend on interpreter implementation and call-stack depth; these
measurements are not asserted as universal thresholds.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


def emit(case: str, reproduced: bool, **details: object) -> bool:
    print(json.dumps({"case": case, "reproduced": reproduced, **details}, ensure_ascii=True))
    return reproduced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root / "src"), str(root / "tests")]

    from test_handoff_codex_cli import CodexCliHostTests, FakeLedger, THREAD_ID
    from test_context_usage import sample

    print(json.dumps({"scope": "local fixed Python fixture + FakeLedger only", "real_host": "NOT_RUN", "repository": str(root), "python_version": sys.version, "recursion_limit": sys.getrecursionlimit(), "depth_note": "Original depth 1100 failed on Python 3.9.6 but parsed on Python 3.12.13. Depth 10000 remains below 64 KiB and is the cross-version repro; no recursion limit is changed."}))
    test_fixture = CodexCliHostTests()
    results: list[bool] = []
    streams = {
        "duplicate_thread_id": b'{"type":"thread.started","thread_id":"22222222-2222-4222-8222-222222222222","thread_id":"11111111-1111-4111-8111-111111111111"}\n',
        "deep_json_original_1100": ('{"type":"thread.started","thread_id":"' + THREAD_ID + '","extra":' + '[' * 1100 + '0' + ']' * 1100 + '}\n').encode(),
        "deep_json": ('{"type":"thread.started","thread_id":"' + THREAD_ID + '","extra":' + '[' * 10000 + '0' + ']' * 10000 + '}\n').encode(),
    }

    for case, stream in streams.items():
        with tempfile.TemporaryDirectory(prefix="mltc-review-fixture-", dir="/private/tmp") as directory:
            workspace = Path(directory).resolve()
            ledger = FakeLedger()
            host = test_fixture._host(workspace, ledger)
            request = test_fixture._request(workspace, thread_id=THREAD_ID)
            environment = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "MLTC_CODEX_FIXTURE_RECORD": str(workspace / "fixture.json"),
                "MLTC_CODEX_FIXTURE_EVENTS": stream.hex(),
            }
            for flag in (
                "MLTC_CODEX_FIXTURE_COUNT", "MLTC_CODEX_FIXTURE_FLOOD",
                "MLTC_CODEX_FIXTURE_EVENT_THEN_FLOOD", "MLTC_CODEX_FIXTURE_GRANDCHILD",
                "MLTC_CODEX_FIXTURE_SLEEP", "MLTC_CODEX_FIXTURE_STDERR_FLOOD",
            ):
                environment[flag] = ""
            with patch.dict(os.environ, environment):
                try:
                    report = host.resume_child(request, "local review fixture only")
                except Exception as exc:
                    if case == "deep_json_original_1100":
                        emit(case, isinstance(exc, RecursionError), informational_only=True,
                             exception=type(exc).__name__, message=str(exc),
                             reservations=len(ledger.reservations), observations=len(ledger.observations),
                             stdout_bytes=len(stream))
                        continue
                    results.append(emit(
                        case,
                        case == "deep_json" and isinstance(exc, RecursionError)
                        and len(ledger.reservations) == 1 and len(ledger.observations) == 0,
                        exception=type(exc).__name__, message=str(exc),
                        reservations=len(ledger.reservations), observations=len(ledger.observations),
                        stdout_bytes=len(stream),
                    ))
                else:
                    if case == "deep_json_original_1100":
                        emit(case, False, informational_only=True, report=report,
                             reservations=len(ledger.reservations), observations=len(ledger.observations),
                             stdout_bytes=len(stream))
                        continue
                    results.append(emit(
                        case,
                        case == "duplicate_thread_id" and report.get("launch_status") == "exited"
                        and report.get("commit_status") == "confirmed_committed",
                        report=report, reservations=len(ledger.reservations),
                        observations=len(ledger.observations), stdout_bytes=len(stream),
                    ))

    with tempfile.TemporaryDirectory(prefix="mltc-review-pressure-", dir="/private/tmp") as directory:
        input_file = Path(directory) / "pressure.json"
        input_file.write_text(json.dumps({"sample": sample(session_id="\ud800")}, ensure_ascii=True), encoding="ascii")
        completed = subprocess.run(
            [sys.executable, str(root / "scripts" / "context_usage.py"), "pressure",
             "--input", str(input_file), "--now", "2026-09-15T12:00:00Z"],
            cwd=directory, text=True, capture_output=True, check=False, timeout=10,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        results.append(emit(
            "pressure_unicode",
            completed.returncode == 1 and not completed.stdout.strip()
            and "UnicodeEncodeError" in completed.stderr,
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr,
        ))
    return 0 if all(results) and len(results) == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
