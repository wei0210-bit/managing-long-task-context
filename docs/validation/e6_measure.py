"""Fresh-process synthetic local cost; no model call or business action."""
import hashlib
import json
import resource
import sys
import time

from e6_controller_probes import ROOT, NOW, event, sample, usage

rows = [event(event_id=f"synthetic-{i}") for i in range(1000)]
started = time.perf_counter()
summary = usage.summarize_usage(rows)
usage_seconds = time.perf_counter() - started
assert summary["total_tokens"] == 120000
previous = None
notifications = 0
started = time.perf_counter()
for _ in range(20):
    result = usage.evaluate_pressure(sample(), previous, now=NOW)
    notifications += result["notify"]
    previous = result["previous"]
pressure_seconds = time.perf_counter() - started
assert notifications == 1
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({
    "source_kind": "synthetic", "measurement_scope": "local_program_only",
    "tool_sha256": hashlib.sha256((ROOT / "scripts/context_usage.py").read_bytes()).hexdigest(),
    "usage_events": 1000, "usage_seconds": usage_seconds,
    "pressure_calls": 20, "pressure_seconds": pressure_seconds, "notifications": notifications,
    "whole_process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
    "real_model_tokens": None, "actual_fees": None, "skill_token_benefit": None,
}, sort_keys=True))
