from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

import managing_long_task_context as context
import test_handoff_writes as write_fixtures


class HandoffConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = write_fixtures.HandoffWriteTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_concurrent_identical_prepare_commits_exactly_one_fact(self) -> None:
        gate = threading.Barrier(2)
        results: list[dict[str, object]] = []
        failures: list[BaseException] = []

        def invoke() -> None:
            try:
                gate.wait(timeout=1)
                results.append(self.fixture._prepare())
            except BaseException as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        second.start()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["check_status"] == "pass" for result in results), results)
        events = [json.loads(line) for line in (self.fixture.base_dir / self.fixture.task_id / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event_type"] for event in events].count("handoff_prepared"), 1)

    def test_dispatch_that_commits_first_makes_prepare_refuse_its_stale_capture(self) -> None:
        entered_authorizer = threading.Event()
        release_authorizer = threading.Event()
        result: list[dict[str, object]] = []
        original = write_fixtures.SyntheticWriteAuthorizer.authorize

        def hold_authorizer(
            authority: write_fixtures.SyntheticWriteAuthorizer,
            request: dict[str, object],
        ) -> dict[str, object]:
            entered_authorizer.set()
            self.assertTrue(release_authorizer.wait(1), "prepare authorizer was not released")
            return original(authority, request)

        with patch.object(write_fixtures.SyntheticWriteAuthorizer, "authorize", hold_authorizer):
            worker = threading.Thread(target=lambda: result.append(self.fixture._prepare()))
            worker.start()
            self.assertTrue(entered_authorizer.wait(1), "prepare did not reach its out-of-lock authorizer")
            dispatched = context.record(
                self.fixture.task_id, statement="dispatch registered before prepare",
                item_type="observation", actor="synthetic:controller", source="synthetic",
                base_dir=self.fixture.base_dir,
            )
            release_authorizer.set()
            worker.join(timeout=2)

        self.assertEqual(dispatched["statement"], "dispatch registered before prepare")
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0]["check_status"], "pass", result)
        events = [json.loads(line) for line in (self.fixture.base_dir / self.fixture.task_id / "events.jsonl").read_text().splitlines()]
        self.assertIn("item-recorded", [event["event_type"] for event in events])
        self.assertNotIn("handoff_prepared", [event["event_type"] for event in events])

    def test_prepare_between_legacy_fence_and_writer_lock_fences_dispatch(self) -> None:
        entered_validation = threading.Event()
        release_validation = threading.Event()
        writer_errors: list[BaseException] = []

        class BlockingStatement(str):
            def strip(self, chars: str | None = None) -> str:
                entered_validation.set()
                if not release_validation.wait(1):
                    raise RuntimeError("writer validation was not released")
                return super().strip(chars)

        def dispatch() -> None:
            try:
                context.record(
                    self.fixture.task_id, statement=BlockingStatement("dispatch raced with prepare"),
                    item_type="observation", actor="synthetic:controller", source="synthetic",
                    base_dir=self.fixture.base_dir,
                )
            except BaseException as exc:  # asserted below
                writer_errors.append(exc)

        dispatcher = threading.Thread(target=dispatch)
        dispatcher.start()
        self.assertTrue(entered_validation.wait(1), "writer did not pass its legacy fence")
        prepared = self.fixture._prepare()
        release_validation.set()
        dispatcher.join(timeout=2)

        self.assertFalse(dispatcher.is_alive(), "writer thread did not finish")
        self.assertEqual(prepared["check_status"], "pass", prepared)
        self.assertEqual(len(writer_errors), 1)
        self.assertIsInstance(writer_errors[0], context.ContextError)
        events = [json.loads(line) for line in (self.fixture.base_dir / self.fixture.task_id / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event_type"] for event in events].count("handoff_prepared"), 1)
        self.assertNotIn("item-recorded", [event["event_type"] for event in events])
