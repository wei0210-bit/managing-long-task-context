"""Run the public truth-source lifecycle without persisting source bytes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import managing_long_task_context as context


SPEC_CANARY = "协调删除、截断事件并重建 snapshot 的行为不可检测"
FIXTURE_CANARY_PREFIX = "TRUTH_SOURCE_PILOT_CANARY_"
TASK_ID = "TRUTH-SOURCE-PILOT"
OWNER = "pilot-owner"


def _relative_locator(path: Path, workspace_root: Path) -> str:
    return path.relative_to(workspace_root).as_posix()


def _failure_codes(report: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for result in report.get("truth_source_results", []):
        if result.get("status") != "pass":
            codes.extend(code for code in result.get("codes", []) if isinstance(code, str))
    return codes


def _json_artifacts(base_dir: Path, contract: dict[str, Any], reports: list[dict[str, Any]], errors: list[str]) -> str:
    task_dir = base_dir / TASK_ID
    events = [
        json.loads(line)
        for line in (task_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    snapshot = json.loads((task_dir / "snapshot.json").read_text(encoding="utf-8"))
    brief = context.brief(TASK_ID, base_dir=base_dir)
    return json.dumps(
        {
            "contract": contract,
            "events": events,
            "snapshot": snapshot,
            "brief": brief,
            "report": reports,
            "errors": errors,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def run_pilot(*, base_dir: Path, spec_path: Path, fixture_path: Path) -> dict[str, Any]:
    """Exercise dirty, undeclared-change, and recovery paths through public APIs."""

    base_dir = Path(base_dir)
    spec_path = Path(spec_path).resolve()
    fixture_path = Path(fixture_path).resolve()
    workspace_root = Path(os.path.commonpath((str(spec_path.parent), str(fixture_path.parent)))).resolve()
    original_fixture = fixture_path.read_bytes()
    fixture_canary = FIXTURE_CANARY_PREFIX + "MUTATION"
    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    contract = {
        "schema": 1,
        "task_id": TASK_ID,
        "version": 1,
        "issued_by": OWNER,
        "issued_at": "2026-08-31T03:00:00Z",
        "authorized_approvers": [],
        "workspace_root": str(workspace_root),
        "required_capabilities": ["truth-sources/v1"],
        "objective": "Exercise truth-source controls through public APIs",
        "scope": ["truth-source example"],
        "out_of_scope": [],
        "constraints": ["offline only"],
        "acceptance_criteria": [{
            "id": "AC-01",
            "criterion": "Truth-source handoff controls are exercised",
            "required_evidence_types": ["test-report"],
        }],
        "truth_sources": {
            "schema": "truth-sources/v1",
            "items": [
                {
                    "id": "TS-SPEC",
                    "purpose": "Design specification source",
                    "source_ref": {"kind": "file", "locator": _relative_locator(spec_path, workspace_root)},
                    "owner": OWNER,
                    "max_age_seconds": 3600,
                    "validation_method": "owner-readback",
                    "invalidate_on_change_kinds": ["specification-change"],
                },
                {
                    "id": "TS-FIXTURE",
                    "purpose": "Controlled pilot source",
                    "source_ref": {"kind": "file", "locator": _relative_locator(fixture_path, workspace_root)},
                    "owner": OWNER,
                    "max_age_seconds": 3600,
                    "validation_method": "owner-readback",
                    "invalidate_on_change_kinds": ["implementation-change"],
                },
            ],
        },
    }

    try:
        context.publish_contract(contract, confirmed_by=OWNER, base_dir=base_dir)
        for source_id in ("TS-SPEC", "TS-FIXTURE"):
            context.observe_truth_source(
                TASK_ID, source_id=source_id, actor=OWNER,
                verification_refs=[f"example:{source_id.lower()}"], base_dir=base_dir,
            )
        release = context.gate(TASK_ID, stage="release", base_dir=base_dir, emit=False)
        reports.append(release)
        context.checkpoint(
            TASK_ID, phase="truth-source-pilot", completed=["initial observation completed"],
            evidence_added=["example:truth-source-pilot"], next_action="exercise handoff controls",
            actor=OWNER, base_dir=base_dir,
        )

        context.mark_truth_sources_dirty(
            TASK_ID, change_kind="implementation-change", actor=OWNER,
            reason="controlled implementation changed", base_dir=base_dir,
        )
        dirty_handoff = context.gate(TASK_ID, stage="handoff", base_dir=base_dir, emit=False)
        reports.append(dirty_handoff)
        context.observe_truth_source(
            TASK_ID, source_id="TS-FIXTURE", actor=OWNER,
            verification_refs=["example:fixture-reobserved"], base_dir=base_dir,
        )
        reobserved_handoff = context.gate(TASK_ID, stage="handoff", base_dir=base_dir, emit=False)
        reports.append(reobserved_handoff)

        fixture_path.write_bytes(original_fixture + b"\n" + fixture_canary.encode("utf-8") + b"\n")
        try:
            context.observe_truth_source(
                TASK_ID, source_id="TS-FIXTURE", actor=OWNER,
                verification_refs=["example:undeclared-change"], base_dir=base_dir,
            )
        except context.ContextError as exc:
            undeclared_change_code = str(exc)
            errors.append(undeclared_change_code)
        else:
            raise RuntimeError("undeclared source change was accepted")
        changed_handoff = context.gate(TASK_ID, stage="handoff", base_dir=base_dir, emit=False)
        reports.append(changed_handoff)
        context.mark_truth_sources_dirty(
            TASK_ID, change_kind="implementation-change", actor=OWNER,
            reason="controlled source changed", base_dir=base_dir,
        )
        context.observe_truth_source(
            TASK_ID, source_id="TS-FIXTURE", actor=OWNER,
            verification_refs=["example:fixture-recovered"], base_dir=base_dir,
        )
        recovered_handoff = context.gate(TASK_ID, stage="handoff", base_dir=base_dir, emit=False)
        reports.append(recovered_handoff)
    finally:
        fixture_path.write_bytes(original_fixture)

    context.mark_truth_sources_dirty(
        TASK_ID, change_kind="implementation-change", actor=OWNER,
        reason="controlled source restored", base_dir=base_dir,
    )
    context.observe_truth_source(
        TASK_ID, source_id="TS-FIXTURE", actor=OWNER,
        verification_refs=["example:fixture-restored"], base_dir=base_dir,
    )
    restored_handoff = context.gate(TASK_ID, stage="handoff", base_dir=base_dir, emit=False)
    reports.append(restored_handoff)
    if not restored_handoff["passed"]:
        raise RuntimeError("restored source handoff did not pass")

    serialized = _json_artifacts(base_dir, contract, reports, errors)
    result = {
        "explicit_dirty_release_passed": release["passed"],
        "dirty_handoff_codes": _failure_codes(dirty_handoff),
        "reobserved_handoff_passed": reobserved_handoff["passed"],
        "undeclared_change_code": undeclared_change_code,
        "changed_handoff_codes": _failure_codes(changed_handoff),
        "recovered_handoff_passed": recovered_handoff["passed"],
        "canary_leaked": SPEC_CANARY in serialized or fixture_canary in serialized,
        "fixture_restored": fixture_path.read_bytes() == original_fixture,
    }
    expected = {
        "explicit_dirty_release_passed": True,
        "dirty_handoff_codes": ["TRUTH_SOURCE_DIRTY"],
        "reobserved_handoff_passed": True,
        "undeclared_change_code": "TRUTH_SOURCE_UNDECLARED_CHANGE",
        "changed_handoff_codes": ["TRUTH_SOURCE_CHANGED"],
        "recovered_handoff_passed": True,
        "canary_leaked": False,
        "fixture_restored": True,
    }
    if result != expected:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    if args.spec is not None or args.fixture is not None:
        if args.spec is None or args.fixture is None:
            parser.error("--spec and --fixture must be supplied together")
        if args.base_dir is None:
            parser.error("--base-dir is required with --spec and --fixture")
        result = run_pilot(base_dir=args.base_dir, spec_path=args.spec, fixture_path=args.fixture)
    else:
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_root = Path(temporary_dir)
            workspace = temporary_root / "workspace"
            workspace.mkdir()
            spec_path = workspace / "design-spec.md"
            spec_path.write_text(SPEC_CANARY + "\n", encoding="utf-8")
            fixture_path = workspace / "truth_source_pilot.md"
            fixture_path.write_bytes((REPOSITORY_ROOT / "tests/fixtures/truth_source_pilot.md").read_bytes())
            result = run_pilot(
                base_dir=temporary_root / ".prime" / "context",
                spec_path=spec_path,
                fixture_path=fixture_path,
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
