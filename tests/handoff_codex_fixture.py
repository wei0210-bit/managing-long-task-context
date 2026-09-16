"""Fixed subprocess fixture for the Codex CLI transport tests.

It is deliberately not a Codex implementation.  It records argv/cwd/stdin EOF
and emits one bounded JSON observation so transport tests exercise a real child
process without contacting a model or host service.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess


def main() -> int:
    record_path = Path(os.environ["MLTC_CODEX_FIXTURE_RECORD"])
    count_path = os.environ.get("MLTC_CODEX_FIXTURE_COUNT")
    if count_path:
        counter = Path(count_path)
        prior = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
        counter.write_text(str(prior + 1), encoding="utf-8")
    stdin_text = sys.stdin.read()
    record_path.write_text(
        json.dumps(
            {
                "argv": sys.argv[1:],
                "cwd": os.getcwd(),
                "stdin_eof": True,
                "stdin_text": stdin_text,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    descendant_marker = os.environ.get("MLTC_CODEX_FIXTURE_DESCENDANT_MARKER")
    if descendant_marker:
        delay = os.environ.get("MLTC_CODEX_FIXTURE_DESCENDANT_DELAY", "1.5")
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,sys,time; "
                    "time.sleep(float(sys.argv[2])); "
                    "pathlib.Path(sys.argv[1]).write_text('survived', encoding='utf-8')"
                ),
                descendant_marker,
                delay,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if os.environ.get("MLTC_CODEX_FIXTURE_FLOOD") == "1":
        sys.stdout.write("x" * (9 * 1024 * 1024))
        sys.stdout.flush()
        return 0
    if os.environ.get("MLTC_CODEX_FIXTURE_EVENT_THEN_FLOOD") == "1":
        print(
            json.dumps(
                {
                    "type": "thread.started",
                    "thread_id": "11111111-1111-4111-8111-111111111111",
                }
            ),
            flush=True,
        )
        sys.stdout.write("x" * (9 * 1024 * 1024))
        sys.stdout.flush()
        return 0
    if "MLTC_CODEX_FIXTURE_EVENTS" in os.environ:
        sys.stdout.buffer.write(bytes.fromhex(os.environ["MLTC_CODEX_FIXTURE_EVENTS"]))
        return 0
    if os.environ.get("MLTC_CODEX_FIXTURE_GRANDCHILD") == "1":
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return 0
    if os.environ.get("MLTC_CODEX_FIXTURE_SLEEP") == "1":
        import time

        time.sleep(3)
        return 0
    if os.environ.get("MLTC_CODEX_FIXTURE_STDERR_FLOOD") == "1":
        sys.stderr.write("e" * (9 * 1024 * 1024))
        sys.stderr.flush()
        return 0
    print(
        json.dumps(
            {
                "type": "thread.started",
                "thread_id": "11111111-1111-4111-8111-111111111111",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
