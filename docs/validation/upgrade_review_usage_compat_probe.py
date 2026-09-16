"""Compare public usage/pressure results with the preserved pre-fix package."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


root = Path(sys.argv[1]).resolve()
baseline = module("usage_before_fix", Path(sys.argv[2]).resolve())
current = module("usage_after_fix", root / "scripts/context_usage.py")
sys.path.insert(0, str(root / "tests"))
from test_context_usage import NOW, sample, event

comparisons = 0
for label in ("ASCII", "中文", "emoji-😀"):
    for changes in ({}, {"window_tokens": None}, {"used_tokens": 20},
                    {"expires_at": "2026-09-15T11:59:59Z"}):
        value = sample(session_id=label, sample_id=label, **changes)
        old = baseline.evaluate_pressure(value, now=NOW)
        new = current.evaluate_pressure(value, now=NOW)
        assert new == old, (label, changes, old, new)
        assert current.evaluate_pressure(value, previous=old["previous"], now=NOW) == baseline.evaluate_pressure(
            value, previous=old["previous"], now=NOW
        )
        comparisons += 2
    values = [event("one", session_id=label), event("two", session_id=label)]
    assert current.summarize_usage(values) == baseline.summarize_usage(values)
    comparisons += 1
print(json.dumps({"public_result_comparisons": comparisons, "status": "pass",
                  "includes_old_previous": True, "real_model": "NOT_RUN"}))
