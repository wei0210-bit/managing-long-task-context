from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import managing_long_task_context as context


class BriefRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / ".prime" / "context"
        observed_at = datetime.now(timezone.utc) - timedelta(days=2)
        clock = patch.object(context, "_now", return_value=observed_at.isoformat())
        clock.start()
        self.addCleanup(clock.stop)
        context.publish_contract(
            {
                "schema": 1,
                "task_id": "RENDER",
                "version": 1,
                "issued_by": "publisher",
                "issued_at": observed_at.isoformat(),
                "authorized_approvers": [],
                "objective": "Render controlled context clearly",
                "scope": ["brief rendering"],
                "out_of_scope": [],
                "constraints": [],
                "acceptance_criteria": [
                    {"id": "AC-01", "criterion": "Render context", "required_evidence": ["test-report"]}
                ],
            },
            confirmed_by="publisher",
            base_dir=self.base,
        )

    def test_stale_mutable_fact_is_listed_in_reobservation_section(self) -> None:
        empty_prompt = context.brief("RENDER", base_dir=self.base)["prompt"]
        self.assertNotIn("已过期，需重新观察", empty_prompt)
        fact = context.record(
            "RENDER",
            item_id="FACT-STALE",
            statement="Service was healthy at observation time",
            item_type="verified-fact",
            actor="observer",
            source={"kind": "tool", "ref": "health-probe"},
            evidence=["probe:health"],
            verification_method="Read the health endpoint",
            scope={"service": "test-service"},
            mutable=True,
            ttl_hours=1,
            base_dir=self.base,
        )

        packet = context.brief("RENDER", base_dir=self.base)

        self.assertEqual(packet["stale_items"], [fact["id"]])
        self.assertIn("## 已过期，需重新观察", packet["prompt"])
        section = packet["prompt"].split("## 已过期，需重新观察\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"- {fact['id']}", section)

    def test_budget_omission_notice_matches_diagnostic_omitted_ids(self) -> None:
        unlimited = context.brief("RENDER", base_dir=self.base)
        self.assertNotIn("因预算省略了", unlimited["prompt"])
        self.assertNotIn("omitted_ids", unlimited)
        for index in range(3):
            context.record(
                "RENDER",
                item_id=f"OPTIONAL-{index}",
                statement=str(index) * 400,
                item_type="observation",
                actor="observer",
                source={"kind": "tool", "ref": f"probe-{index}"},
                base_dir=self.base,
            )
        full = context.brief_diagnostics("RENDER", base_dir=self.base)
        budget = full["budget"]["fixed_prompt_chars"] + 850
        diagnostics = context.brief_diagnostics("RENDER", max_chars=budget, base_dir=self.base)
        omitted = diagnostics["items"]["omitted_ids"]
        self.assertTrue(diagnostics["usable"])
        self.assertGreater(len(omitted), 0)
        self.assertGreater(diagnostics["items"]["selected_count"], 0)

        packet = context.brief("RENDER", max_chars=budget, base_dir=self.base)

        self.assertIn(f"因预算省略了 {len(omitted)} 条非必需条目", packet["prompt"])
        self.assertLessEqual(len(packet["prompt"]), budget)
        self.assertEqual(
            [item["id"] for item in packet["observations"]],
            diagnostics["items"]["selected_ids"],
        )
        unlimited = context.brief("RENDER", base_dir=self.base)
        self.assertNotIn("因预算省略了", unlimited["prompt"])
        self.assertNotIn("omitted_ids", unlimited)

    def test_blocking_and_blocker_have_same_markdown_position(self) -> None:
        target = context.record(
            "RENDER",
            item_id="SORT-TARGET",
            statement="Action is blocked",
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "blocking-probe"},
            metadata={"blocker": True, "severity": "low"},
            base_dir=self.base,
        )
        context.record(
            "RENDER",
            item_id="SORT-ORDINARY",
            statement="Ordinary observation",
            item_type="observation",
            actor="observer",
            source={"kind": "tool", "ref": "ordinary-probe"},
            metadata={"severity": "critical"},
            base_dir=self.base,
        )
        blocker_prompt = context.brief("RENDER", base_dir=self.base)["prompt"]
        context.update_item(
            "RENDER",
            target["id"],
            actor="observer",
            metadata={"blocker": False, "blocking": True, "severity": "low"},
            base_dir=self.base,
        )
        blocking_prompt = context.brief("RENDER", base_dir=self.base)["prompt"]

        def ordered_ids(prompt: str) -> list[str]:
            return [line.split(":", 1)[0][2:] for line in prompt.splitlines() if line.startswith("- SORT-")]

        self.assertEqual(ordered_ids(blocker_prompt), ["SORT-TARGET", "SORT-ORDINARY"])
        self.assertEqual(ordered_ids(blocking_prompt), ordered_ids(blocker_prompt))


if __name__ == "__main__":
    unittest.main()
