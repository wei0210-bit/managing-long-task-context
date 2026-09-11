"""Create and query a project-local experience candidate through the public CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_example() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        original = workspace / "original.txt"
        original.write_text("Read the original before recording a candidate.\n", encoding="utf-8")
        candidate = workspace / "candidate.json"
        candidate.write_text(json.dumps({
            "schema": 1,
            "experience_id": "candidate-example-001",
            "revision": 1,
            "claim": "Read the local original before relying on this candidate.",
            "tags": ["example"],
            "applicability": ["A local original is available."],
            "exclusions": ["none-known"],
            "source_refs": [{
                "path": str(original.resolve()),
                "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            }],
            "supersedes": None,
        }), encoding="utf-8")
        store = workspace / ".context-experience"
        for command in (("init",), ("record", "--input", str(candidate)), ("query", "--tags", "example", "--include-candidates")):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "context_experience.py"), *command,
                 "--workspace", str(workspace), "--store", str(store)],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode:
                raise RuntimeError(completed.stdout)
        return json.loads(completed.stdout)


if __name__ == "__main__":
    result = run_example()
    item = result["data"]["items"][0]
    print(json.dumps({"status": result["status"], "experience_id": item["experience_id"], "revision": item["revision"]}))
