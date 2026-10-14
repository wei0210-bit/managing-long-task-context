"""Observe original files in the shared ledger and report their currency."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import managing_long_task_context as context


def run_example():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "STATUS.md").write_text("original observation\n")
        contract = json.loads((Path(__file__).resolve().parents[1] / "assets/truth-source-contract.example.json").read_text())
        contract["workspace_root"] = str(root)
        base = root / "context"
        context.publish_contract(contract, confirmed_by="task-publisher", base_dir=base)
        context.observe_truth_source("TASK-001", source_id="TS-STATUS", actor="project-lead",
            verification_refs=["readback:original"], base_dir=base)
        return context.gate("TASK-001", stage="handoff", emit=False, base_dir=base)


if __name__ == "__main__":
    print(json.dumps(run_example(), ensure_ascii=False))
