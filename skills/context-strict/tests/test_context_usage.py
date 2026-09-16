"""Synthetic seam tests for bounded local context-usage observations."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "context_usage.py"
SPEC = importlib.util.spec_from_file_location("context_usage_under_test", SOURCE)
if (
    SPEC is None or SPEC.loader is None
):  # pragma: no cover - import failure is a test setup error
    raise RuntimeError(f"cannot load {SOURCE}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
evaluate_pressure = MODULE.evaluate_pressure
summarize_usage = MODULE.summarize_usage


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
OBSERVED = "2026-09-15T11:00:00Z"
EXPIRES = "2026-09-15T13:00:00Z"


def event(
    event_id: str,
    *,
    session_id: str = "S-1",
    mode: str = "delta",
    provider: str = "synthetic-provider",
    model: str = "synthetic-model",
    cache_accounting: str = "included",
    input_tokens: int = 100,
    output_tokens: int = 10,
    cache_read_tokens: int = 20,
    cache_write_tokens: int = 10,
    observed_at: str = OBSERVED,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "session_id": session_id,
        "task_id": "TASK-SYNTHETIC",
        "provider": provider,
        "model": model,
        "mode": mode,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_accounting": cache_accounting,
        "source_ref": "synthetic://unit-test",
        "observed_at": observed_at,
    }


def sample(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "session_id": "S-1",
        "sample_id": "P-1",
        "observed_at": OBSERVED,
        "expires_at": EXPIRES,
        "window_tokens": 100,
        "used_tokens": 85,
        "reserve_tokens": 10,
        "growth_tokens": 5,
        "basis": "current-window",
        "safe_point": True,
        "task_complete": False,
        "execution_unknown": False,
        "milestone": True,
    }
    value.update(changes)
    return value


class SummarizeUsageTests(unittest.TestCase):
    def test_no_usage_is_unknown_but_explicit_zero_event_remains_a_zero_observation(
        self,
    ) -> None:
        no_usage = summarize_usage([])
        zero_usage = summarize_usage(
            [
                event(
                    "Z-1",
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                )
            ]
        )
        self.assertEqual(no_usage["status"], "unknown")
        self.assertIsNone(no_usage["total_tokens"])
        self.assertEqual(zero_usage["status"], "ok")
        self.assertEqual(zero_usage["total_tokens"], 0)

    def test_sums_delta_and_last_cumulative_without_double_counting_cache(self) -> None:
        events = [
            event("D-1"),
            event(
                "D-2",
                session_id="S-3",
                cache_accounting="separate",
                cache_read_tokens=10,
                cache_write_tokens=5,
                output_tokens=20,
            ),
            event(
                "C-1",
                session_id="S-2",
                mode="cumulative",
                input_tokens=50,
                output_tokens=5,
                cache_read_tokens=20,
                cache_write_tokens=10,
                observed_at="2026-09-15T10:00:00Z",
            ),
            event(
                "C-2",
                session_id="S-2",
                mode="cumulative",
                input_tokens=70,
                output_tokens=7,
                cache_read_tokens=30,
                cache_write_tokens=10,
                observed_at=OBSERVED,
            ),
        ]
        report = summarize_usage(events)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["total_tokens"], 322)
        self.assertEqual(report["input_tokens"], 270)
        self.assertEqual(report["normalized_input_tokens"], 285)
        self.assertEqual(report["output_tokens"], 37)
        self.assertEqual(report["cache_read_tokens"], 60)
        self.assertEqual(report["cache_write_tokens"], 25)
        self.assertEqual(report["used_event_count"], 3)
        self.assertIsNone(report["task_total_tokens"])
        self.assertIsNone(report["cost"])
        self.assertIsNone(report["skill_attribution"])

    def test_duplicate_identical_event_is_counted_once_and_sessions_are_not_task_merged(
        self,
    ) -> None:
        repeated = event("D-1")
        report = summarize_usage(
            [repeated, dict(repeated), event("D-2", session_id="S-2")]
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["total_tokens"], 220)
        self.assertEqual(report["session_count"], 2)
        self.assertEqual(report["used_event_count"], 2)

    def test_invalid_or_conflicting_usage_is_unknown_without_partial_total(
        self,
    ) -> None:
        cases = [
            [dict(event("D-1"), input_tokens=None)],
            [dict(event("D-1"), input_tokens=-1)],
            [dict(event("D-1"), input_tokens=True)],
            [dict(event("D-1"), cache_read_tokens=90, cache_write_tokens=20)],
            [event("D-1"), dict(event("D-1"), output_tokens=11)],
            [
                event(
                    "C-1",
                    mode="cumulative",
                    observed_at="2026-09-15T10:00:00Z",
                    input_tokens=70,
                ),
                event("C-2", mode="cumulative", input_tokens=60),
            ],
            [event("D-1"), event("C-1", mode="cumulative")],
            [event("D-1"), event("D-2", cache_accounting="separate")],
            [event("D-1"), event("D-2", provider="other")],
            [event("D-1", observed_at="not-a-time")],
            [event("D-1", mode="estimate")],
            [dict(event("D-1"), mode=[])],
            [dict(event("D-1"), cache_accounting={})],
        ]
        for events in cases:
            with self.subTest(events=events):
                report = summarize_usage(events)
                self.assertEqual(report["status"], "unknown")
                self.assertIsNone(report["total_tokens"])
                self.assertTrue(report["codes"])

    def test_twenty_identical_records_never_accumulate(self) -> None:
        report = summarize_usage([event("D-1")] * 20)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["total_tokens"], 110)
        self.assertEqual(report["used_event_count"], 1)

    def test_more_than_one_thousand_records_is_unknown_even_when_they_repeat(
        self,
    ) -> None:
        report = summarize_usage([event("D-1")] * 1001)
        self.assertEqual(report["status"], "unknown")
        self.assertIsNone(report["total_tokens"])

    def test_unbounded_generator_stops_after_the_record_limit(self) -> None:
        seen = 0

        def records():
            nonlocal seen
            while True:
                seen += 1
                yield event(f"D-{seen}")

        report = summarize_usage(records())
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(seen, 1001)


class PressureTests(unittest.TestCase):
    def test_non_utf8_sample_is_unknown_in_both_pressure_paths(self) -> None:
        for field in ("session_id", "sample_id", "extra"):
            for value in ("\ud800", "\udfff"):
                for missing_window in (False, True):
                    with self.subTest(field=field, value=repr(value), missing=missing_window):
                        supplied = sample(**{field: value})
                        if missing_window:
                            supplied.pop("window_tokens")
                        report = evaluate_pressure(supplied, now=NOW)
                        self.assertEqual(report["decision"], "unknown")
                        self.assertEqual(report["reason"], "PRESSURE_SAMPLE_NOT_JSON")
                        self.assertFalse(report["notify"])
                        self.assertFalse(report["automatic_action"])

    def test_valid_unicode_pressure_preserves_recommendation_and_deduplication(self) -> None:
        for missing_window in (False, True):
            with self.subTest(missing=missing_window):
                supplied = sample(session_id="主控😀", sample_id="采样一", extra="证据")
                if missing_window:
                    supplied.pop("window_tokens")
                first = evaluate_pressure(supplied, now=NOW)
                self.assertEqual(first["decision"], "milestone" if missing_window else "prepare")
                self.assertTrue(first["notify"])
                repeated = evaluate_pressure(supplied, previous=first["previous"], now=NOW)
                self.assertEqual(repeated["decision"], first["decision"])
                self.assertFalse(repeated["notify"])

    def test_boundary_recommends_prepare_but_lower_usage_defers(self) -> None:
        low = evaluate_pressure(sample(used_tokens=84), now=NOW)
        boundary = evaluate_pressure(sample(), now=NOW)
        high = evaluate_pressure(sample(used_tokens=86, sample_id="P-2"), now=NOW)
        self.assertEqual(low["decision"], "defer")
        self.assertEqual(boundary["decision"], "prepare")
        self.assertTrue(boundary["notify"])
        self.assertEqual(high["decision"], "prepare")
        self.assertTrue(high["notify"])
        self.assertFalse(boundary["automatic_action"])

    def test_estimate_is_labeled_and_cumulative_cannot_be_current_window(self) -> None:
        estimated = evaluate_pressure(sample(basis="estimate"), now=NOW)
        forged = evaluate_pressure(sample(mode="cumulative"), now=NOW)
        self.assertTrue(estimated["estimated"])
        self.assertEqual(forged["decision"], "unknown")

    def test_safe_point_can_prepare_without_milestone(self) -> None:
        report = evaluate_pressure(sample(milestone=False), now=NOW)
        self.assertEqual(report["decision"], "prepare")
        self.assertTrue(report["notify"])

    def test_impossible_window_count_uses_only_the_explicit_safe_milestone_fallback(self) -> None:
        safe = evaluate_pressure(sample(used_tokens=101), now=NOW)
        unsafe = evaluate_pressure(
            sample(used_tokens=101, milestone=False), now=NOW,
        )
        self.assertEqual(safe["decision"], "milestone")
        self.assertTrue(safe["notify"])
        self.assertEqual(unsafe["decision"], "unknown")
        self.assertFalse(unsafe["notify"])

    def test_missing_or_invalid_window_numbers_can_only_advise_one_safe_milestone(self) -> None:
        cases = (
            {"window_tokens": None},
            {"used_tokens": "unknown"},
            {"used_tokens": 101},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                initial = evaluate_pressure(sample(**changes), now=NOW)
                self.assertEqual(initial["decision"], "milestone")
                self.assertTrue(initial["notify"])
                previous = initial["previous"]
                for _ in range(20):
                    repeated = evaluate_pressure(
                        sample(**changes), previous=previous, now=NOW,
                    )
                    self.assertEqual(repeated["decision"], "milestone")
                    self.assertFalse(repeated["notify"])
                    previous = repeated["previous"]

    def test_missing_or_invalid_window_numbers_do_not_bypass_identity_time_or_safety(self) -> None:
        no_numbers = {"window_tokens": None}
        negative_cases = (
            {"session_id": ""},
            {"sample_id": None},
            {"observed_at": "not-a-time"},
            {"expires_at": "not-a-time"},
            {"observed_at": "2026-09-15T12:30:00Z"},
            {"safe_point": None},
            {"milestone": "true"},
            {"task_complete": True},
            {"execution_unknown": True},
            {"mode": "cumulative"},
            {"basis": "cumulative"},
            {"basis": "delta"},
            {"basis": "invalid"},
            {"basis": []},
            {"basis": None},
        )
        for changes in negative_cases:
            with self.subTest(changes=changes):
                report = evaluate_pressure(sample(**no_numbers, **changes), now=NOW)
                self.assertNotEqual(report["decision"], "prepare")
                self.assertNotEqual(report["decision"], "milestone")
                self.assertFalse(report["notify"])

    def test_deferred_low_sample_can_notify_once_when_it_later_expires_at_a_safe_milestone(self) -> None:
        low = sample(used_tokens=20, expires_at="2026-09-15T12:01:00Z")
        deferred = evaluate_pressure(low, now=NOW)
        self.assertEqual(deferred["decision"], "defer")
        self.assertFalse(deferred["notify"])

        notified = evaluate_pressure(
            low, previous=deferred["previous"], now=datetime(2026, 9, 15, 12, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(notified["decision"], "milestone")
        self.assertTrue(notified["notify"])
        previous = notified["previous"]
        for _ in range(20):
            repeated = evaluate_pressure(
                low, previous=previous, now=datetime(2026, 9, 15, 12, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(repeated["decision"], "milestone")
            self.assertFalse(repeated["notify"])
            previous = repeated["previous"]

    def test_utc_overflow_is_unknown_for_usage_pressure_and_direct_now(self) -> None:
        for bad_time in (
            "0001-01-01T00:00:00+23:59",
            "9999-12-31T23:59:59-23:59",
        ):
            with self.subTest(bad_time=bad_time):
                usage = summarize_usage([event("D-1", observed_at=bad_time)])
                self.assertEqual(usage["status"], "unknown")
                self.assertIsNone(usage["total_tokens"])
                pressure = evaluate_pressure(sample(observed_at=bad_time), now=NOW)
                self.assertEqual(pressure["decision"], "unknown")
                self.assertFalse(pressure["notify"])
        direct_now = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=23, minutes=59)))
        report = evaluate_pressure(sample(), now=direct_now)
        self.assertEqual(report["decision"], "unknown")
        self.assertFalse(report["notify"])

    def test_valid_cross_timezone_observations_remain_usable(self) -> None:
        cross_zone = sample(
            observed_at="2026-09-15T18:00:00+07:00",
            expires_at="2026-09-15T20:00:00+07:00",
        )
        report = evaluate_pressure(cross_zone, now=NOW)
        self.assertEqual(report["decision"], "prepare")
        self.assertTrue(report["notify"])

    def test_expired_future_and_missing_safety_fields_do_not_become_low_pressure(
        self,
    ) -> None:
        expired_safe = evaluate_pressure(
            sample(expires_at="2026-09-15T11:30:00Z"), now=NOW
        )
        expired_unsafe = evaluate_pressure(
            sample(expires_at="2026-09-15T11:30:00Z", safe_point=False), now=NOW
        )
        future = evaluate_pressure(sample(observed_at="2026-09-15T12:30:00Z"), now=NOW)
        missing = evaluate_pressure(
            {key: value for key, value in sample().items() if key != "milestone"},
            now=NOW,
        )
        self.assertEqual(expired_safe["decision"], "milestone")
        self.assertEqual(expired_unsafe["decision"], "defer")
        self.assertEqual(future["decision"], "unknown")
        self.assertEqual(missing["decision"], "unknown")

    def test_complete_unknown_execution_and_non_safe_points_only_defer(self) -> None:
        for changes in (
            {"task_complete": True},
            {"execution_unknown": True},
            {"safe_point": False},
        ):
            with self.subTest(changes=changes):
                report = evaluate_pressure(sample(**changes), now=NOW)
                self.assertEqual(report["decision"], "defer")
                self.assertFalse(report["notify"])

    def test_completion_and_unknown_execution_override_expired_milestone_notification(
        self,
    ) -> None:
        for changes in ({"task_complete": True}, {"execution_unknown": True}):
            with self.subTest(changes=changes):
                report = evaluate_pressure(
                    sample(expires_at="2026-09-15T11:30:00Z", **changes), now=NOW
                )
                self.assertEqual(report["decision"], "defer")
                self.assertFalse(report["notify"])

    def test_non_string_basis_is_unknown_not_an_exception(self) -> None:
        report = evaluate_pressure(sample(basis=[]), now=NOW)
        self.assertEqual(report["decision"], "unknown")

    def test_previous_only_deduplicates_identical_same_session_sample(self) -> None:
        first = evaluate_pressure(sample(), now=NOW)
        repeated = evaluate_pressure(sample(), previous=first["previous"], now=NOW)
        changed = evaluate_pressure(
            sample(used_tokens=86), previous=first["previous"], now=NOW
        )
        other_session = evaluate_pressure(
            sample(session_id="S-2"), previous=first["previous"], now=NOW
        )
        self.assertTrue(first["notify"])
        self.assertFalse(repeated["notify"])
        self.assertEqual(repeated["decision"], "prepare")
        self.assertEqual(changed["decision"], "unknown")
        self.assertTrue(other_session["notify"])
        self.assertNotEqual(first["dedup_key"], other_session["dedup_key"])


class ContextUsageCliTests(unittest.TestCase):
    script = SOURCE

    def run_cli(self, command: str, path: Path) -> tuple[int, dict[str, object]]:
        completed = subprocess.run(
            [sys.executable, str(self.script), command, "--input", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout)

    def run_pressure_cli(self, path: Path, now: str) -> tuple[int, dict[str, object], str]:
        completed = subprocess.run(
            [sys.executable, str(self.script), "pressure", "--input", str(path), "--now", now],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout), completed.stderr

    def test_cli_utc_overflow_is_structured_unknown_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pressure.json"
            path.write_text(json.dumps({"sample": sample()}), encoding="utf-8")
            for bad_now in (
                "0001-01-01T00:00:00+23:59",
                "9999-12-31T23:59:59-23:59",
            ):
                with self.subTest(bad_now=bad_now):
                    code, report, stderr = self.run_pressure_cli(path, bad_now)
                    self.assertEqual(code, 2)
                    self.assertEqual(report["status"], "unknown")
                    self.assertEqual(report["codes"], ["CLI_NOW_INVALID"])
                    self.assertNotIn("Traceback", stderr)

    def test_cli_surrogate_samples_are_structured_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pressure.json"
            for field in ("session_id", "sample_id", "extra"):
                for missing_window in (False, True):
                    with self.subTest(field=field, missing=missing_window):
                        supplied = sample(**{field: "\ud800"})
                        if missing_window:
                            supplied.pop("window_tokens")
                        path.write_text(json.dumps({"sample": supplied}, ensure_ascii=True), encoding="ascii")
                        code, report, stderr = self.run_pressure_cli(path, "2026-09-15T12:00:00Z")
                        self.assertEqual(code, 2)
                        self.assertEqual(report["decision"], "unknown")
                        self.assertEqual(report["reason"], "PRESSURE_SAMPLE_NOT_JSON")
                        self.assertNotIn("Traceback", stderr)

    def test_cli_reads_only_a_bounded_regular_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "usage.json"
            good.write_text(json.dumps({"events": [event("D-1")]}), encoding="utf-8")
            code, report = self.run_cli("summarize", good)
            self.assertEqual(code, 0)
            self.assertEqual(report["total_tokens"], 110)

            duplicate_keys = root / "duplicate.json"
            duplicate_keys.write_text('{"events":[],"events":[]}', encoding="utf-8")
            nan = root / "nan.json"
            nan.write_text('{"events":[NaN]}', encoding="utf-8")
            huge = root / "huge.json"
            huge.write_bytes(b" " * (1024 * 1024 + 1))
            for bad in (duplicate_keys, nan, huge, root):
                with self.subTest(path=bad):
                    code, report = self.run_cli("summarize", bad)
                    self.assertEqual(code, 2)
                    self.assertEqual(report["status"], "unknown")
                    self.assertTrue(report["codes"])
