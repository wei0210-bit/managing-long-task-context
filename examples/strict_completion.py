"""Demonstrate shared ledger reporting without executing evidence handlers."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import managing_long_task_context as context


def run_example():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory) / "context"
        context.publish_contract({"task_id": "DOC-EXAMPLE", "version": 1,
            "issued_by": "publisher", "issued_at": "2026-10-14T00:00:00Z",
            "objective": "Record the agreement", "scope": [], "out_of_scope": [], "constraints": [],
            "acceptance_criteria": [{"id": "AC-01", "criterion": "Observe the result",
                "required_evidence": ["file"]}]}, confirmed_by="publisher", base_dir=base)
        context.checkpoint("DOC-EXAMPLE", phase="review", completed=["agreement recorded"],
            evidence_added=[], next_action="consult original evidence", actor="worker", base_dir=base)
        report = context.gate("DOC-EXAMPLE", stage="completion", base_dir=base, emit=False)
        assert report["read_only"] and not report["blocking"]
        assert report["decision"] == "unknown"
        return report


if __name__ == "__main__":
    print(json.dumps(run_example(), ensure_ascii=False))
