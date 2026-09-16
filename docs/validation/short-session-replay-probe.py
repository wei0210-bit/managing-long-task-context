"""Read-only structural workload probe; never calls a gate, resolver, or business tool."""
from __future__ import annotations

import hashlib
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import managing_long_task_context as context


def child(kind: str, locator: str) -> None:
    start = time.perf_counter()
    if kind == "real":
        target = Path(locator)
        raw = target.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("PROBE_INPUT_TOO_LARGE")
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        fingerprint = hashlib.sha256(raw).hexdigest()
        task_id = target.parent.name
    else:
        n = int(locator)
        if n not in (1000, 2000):
            raise ValueError("UNFROZEN_SYNTHETIC_SIZE")
        task_id = "SYNTHETIC-REPLAY"
        events = [context._new_event(task_id, "item-recorded", "synthetic", {
            "item": {"id": f"C-{i}", "statement": "x" * 2048}
        }) for i in range(n)]
        raw = b"\n".join(json.dumps(e).encode() for e in events)
        fingerprint = None  # random event IDs: generated shape is fixed, not immutable history
    read_seconds = time.perf_counter() - start
    start = time.perf_counter()
    result = context._rebuild_snapshot(task_id, events)
    elapsed = time.perf_counter() - start
    assert result["event_count"] == len(events)
    if kind == "synthetic":
        assert len(result["items"]) == int(locator)
    unchanged = kind != "real" or hashlib.sha256(Path(locator).read_bytes()).hexdigest() == fingerprint
    assert unchanged, "SOURCE_CHANGED_DURING_PROBE"
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({"kind": kind, "events": len(events), "bytes": len(raw),
        "source_sha256": fingerprint, "read_or_generation_seconds": read_seconds,
        "rebuild_seconds": elapsed, "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
        "items": len(result["items"]), "source_unchanged": unchanged}))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2:
        manifest = json.loads(Path(sys.argv[1]).read_text())
        workloads = [("real", str(Path(next(s["root"] for s in manifest["scope"] if s["name"] == t["project"])) / t["task"] / "events.jsonl")) for t in manifest["tasks"]]
        workloads += [("synthetic", "1000"), ("synthetic", "2000")]
        rows = []
        for kind, locator in workloads:
            runs = []
            for _ in range(5):
                try:
                    p = subprocess.run([sys.executable, __file__, "--child", kind, locator],
                        capture_output=True, text=True, timeout=30, check=False)
                    value = json.loads(p.stdout) if p.returncode == 0 else {"status": "probe_failed", "returncode": p.returncode}
                    if kind == "real" and p.returncode == 0:
                        sample = next(t for t in manifest["tasks"] if t["task"] == Path(locator).parent.name)
                        if value["source_sha256"] != sample["files"]["events.jsonl"]["sha256"]:
                            value = {"status": "source_differs_from_frozen_sample"}
                    runs.append(value)
                except subprocess.TimeoutExpired:
                    runs.append({"status": "probe_timeout", "seconds": 30})
            rows.append({"kind": kind, "locator": locator, "runs": runs})
        print(json.dumps({"schema": "replay-probe/v1", "runs_per_workload": 5,
            "business_validation": "not_run", "token_cost": "unknown", "workloads": rows}, indent=2))
    else:
        raise SystemExit("Pass the approved structural-sample JSON manifest.")
