"""Independent synthetic checks; not model/host/billing evidence."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "controller_usage", ROOT / "scripts/context_usage.py"
)
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)
NOW = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)


def event(**changes):
    value = dict(
        event_id="one",
        session_id="s1",
        task_id="task",
        provider="synthetic",
        model="fixture",
        mode="delta",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=40,
        cache_write_tokens=10,
        cache_accounting="included",
        source_ref="synthetic:U01",
        observed_at="2026-09-15T13:00:00Z",
    )
    return {**value, **changes}


def sample(**changes):
    value = dict(
        session_id="s1",
        sample_id="p1",
        observed_at="2026-09-15T13:00:00Z",
        expires_at="2026-09-15T15:00:00Z",
        window_tokens=1000,
        used_tokens=700,
        reserve_tokens=200,
        growth_tokens=100,
        basis="current-window",
        safe_point=True,
        task_complete=False,
        execution_unknown=False,
        milestone=False,
    )
    return {**value, **changes}


class ControllerUsageTests(unittest.TestCase):
    def test_u01_u02_cache_total_literals(self):
        self.assertEqual(usage.summarize_usage([event()])["total_tokens"], 120)
        self.assertEqual(
            usage.summarize_usage([event(cache_accounting="separate")])["total_tokens"],
            170,
        )

    def test_u03_cumulative_and_repeat(self):
        rows = [
            event(mode="cumulative"),
            event(
                event_id="two",
                mode="cumulative",
                input_tokens=150,
                output_tokens=30,
                observed_at="2026-09-15T13:30:00Z",
            ),
        ]
        self.assertEqual(usage.summarize_usage(rows)["total_tokens"], 180)
        self.assertEqual(usage.summarize_usage([event()] * 20)["total_tokens"], 120)

    def test_u04_sessions_never_silently_collapse(self):
        result = usage.summarize_usage([event(), event(session_id="s2")])
        self.assertTrue(
            result.get("total_tokens") == 240
            or (
                result.get("status") == "unknown" and result.get("total_tokens") is None
            ),
            result,
        )

    def test_u05_conflicts_and_rollbacks(self):
        for rows in (
            [event(), event(output_tokens=21)],
            [
                event(mode="cumulative"),
                event(
                    event_id="two",
                    mode="cumulative",
                    input_tokens=90,
                    observed_at="2026-09-15T13:30:00Z",
                ),
            ],
        ):
            result = usage.summarize_usage(rows)
            self.assertEqual(result["status"], "unknown")
            self.assertIsNone(result["total_tokens"])

    def test_u06_zero_is_not_unknown_or_free_price(self):
        result = usage.summarize_usage(
            [
                event(
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                )
            ]
        )
        self.assertEqual(result["total_tokens"], 0)
        self.assertIsNone(result["cost"])
        self.assertIsNone(result["skill_attribution"])

    def test_no_observation_is_not_observed_zero(self):
        result = usage.summarize_usage([])
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["total_tokens"])

    def test_u07_malformed_fields_never_crash(self):
        for key in ("mode", "cache_accounting", "input_tokens", "observed_at"):
            for bad in ([], {}, True, None):
                with self.subTest(field=key, value=bad):
                    result = usage.summarize_usage([event(**{key: bad})])
                    self.assertEqual(result["status"], "unknown")
                    self.assertIsNone(result["total_tokens"])

    def test_p01_threshold_does_not_require_big_milestone(self):
        for used, expected in ((699, "defer"), (700, "prepare"), (701, "prepare")):
            result = usage.evaluate_pressure(sample(used_tokens=used), now=NOW)
            self.assertEqual(result["decision"], expected)
            self.assertFalse(result["automatic_action"])

    def test_p02_cumulative_cannot_be_window(self):
        result = usage.evaluate_pressure(
            sample(basis="cumulative", used_tokens=100000), now=NOW
        )
        self.assertNotEqual(result["decision"], "prepare")

    def test_p03_repeated_input_once_and_no_mutation(self):
        value = sample()
        original = copy.deepcopy(value)
        previous = None
        notifications = 0
        for _ in range(20):
            result = usage.evaluate_pressure(value, previous, now=NOW)
            notifications += result["notify"]
            previous = result["previous"]
        self.assertEqual(notifications, 1)
        self.assertEqual(value, original)

    def test_p04_p05_conflict_and_changed_sample(self):
        prior = usage.evaluate_pressure(sample(), now=NOW)["previous"]
        result = usage.evaluate_pressure(sample(used_tokens=800), prior, now=NOW)
        self.assertEqual(result["decision"], "unknown")
        result = usage.evaluate_pressure(
            sample(sample_id="p2", used_tokens=800), prior, now=NOW
        )
        self.assertEqual(result["decision"], "prepare")

    def test_p06_expired_complete_or_unknown_never_requests_rollover(self):
        for changes in ({"task_complete": True}, {"execution_unknown": True}):
            result = usage.evaluate_pressure(
                sample(expires_at="2026-09-15T13:30:00Z", milestone=True, **changes),
                now=NOW,
            )
            self.assertEqual(result["decision"], "defer")
            self.assertFalse(result["notify"])

    def test_p07_bad_basis_or_time_never_crashes_or_grants_action(self):
        for changes in (
            {"basis": []},
            {"basis": {}},
            {"observed_at": "2026-09-16T13:00:00Z"},
            {"observed_at": None},
            {"safe_point": None},
        ):
            result = usage.evaluate_pressure(sample(**changes), now=NOW)
            self.assertEqual(result["decision"], "unknown")
            self.assertFalse(result["automatic_action"])


if __name__ == "__main__":
    unittest.main()
