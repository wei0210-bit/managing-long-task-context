"""Post-fix safety assertions derived from the preserved R1 reproduction; all task files are confined to /private/tmp.

No product functions, projections, locks, or ledger methods are mocked.
Host identity/authorization are synthetic, registered fixture callbacks.
"""
import sys
import json
import hashlib
import tempfile
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timedelta, timezone

ROOT = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
tempfile.tempdir = "/private/tmp"
import managing_long_task_context as context
from managing_long_task_context.host_records import HostTaskLedger
from handoff_host_records_fixture import LedgerFixture, digest
from test_handoff_activation import ActivationAuthority, ActivationVerifier, _ref


class InitialAuthority(ActivationAuthority):
    def authorize(self, request):
        response = super().authorize(request)
        response.pop("subject_session_ref", None)
        return response


fixture = LedgerFixture()
try:
    package = fixture.workspace.parent / "package"
    package.mkdir()
    (package / "skill-manifest.json").write_text("synthetic fixture package\n")
    contents = {
        "source": "synthetic source controller\n",
        "target": "synthetic target controller\n",
        "authorization": "synthetic source may prepare, cancel and reserve attempt-001; no process launch\n",
        "basis": "frozen synthetic baseline\n",
        "artifacts": "synthetic handoff materials\n",
    }
    refs = {}
    for key, content in contents.items():
        path = fixture.workspace / (key + ".txt")
        path.write_text(content)
        refs[key] = _ref(fixture.task_id, key, path)
    events_path = fixture.base_dir / fixture.task_id / "events.jsonl"
    cursor = json.loads(events_path.read_text().splitlines()[-1])["event_id"]
    request = fixture.request()
    record = {
        "protocol": "short-session-handoff/v1", "task_id": fixture.task_id,
        "contract_version": request["contract_version"], "contract_digest": request["contract_digest"],
        "workspace_root": str(fixture.workspace.resolve()),
        "package_manifest_sha256": hashlib.sha256((package / "skill-manifest.json").read_bytes()).hexdigest(),
        "handoff_id": "HO-CANCEL-PROBE", "request_id": "REQ-PREPARE-PROBE", "controller_generation": 0,
        "source_session_ref": refs["source"], "target_session_ref": refs["target"],
        "authorization_ref": refs["authorization"], "basis_refs": [refs["basis"]],
        "artifact_manifest_ref": refs["artifacts"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event_cursor": cursor,
    }
    identity = fixture.host.identity
    verifier = ActivationVerifier(record, contents)
    common = dict(base_dir=fixture.base_dir, workspace_root=fixture.workspace,
                  package_root=package, controller_generation=0, runtime_identity=identity,
                  handoff_verifier=verifier)
    prepared = context.prepare_handoff(
        fixture.task_id, **common, request_id=record["request_id"], record=record,
        write_authorizer=InitialAuthority(record, identity, purpose="prepare"))
    assert prepared["check_status"] == "pass", prepared
    cancelled = context.cancel_handoff(
        fixture.task_id, **common, request_id="REQ-CANCEL-PROBE", handoff_id=record["handoff_id"],
        write_authorizer=InitialAuthority(record, identity, purpose="cancel"))
    assert cancelled["check_status"] == "pass", cancelled

    arguments = {"operation": "host_reserve", "task_id": fixture.task_id,
                 "base_dir": str(fixture.base_dir.resolve()), "attempt_id": request["attempt_id"],
                 "request_sha256": digest(request)}
    # authorize_direct_write merges the actual operation argument over its outer
    # operation key; freeze the exact currently emitted request before invocation.
    arguments["operation"] = "start_child"
    expected = {
        "operation": "host_reserve", "task_id": fixture.task_id,
        "base_dir": str(fixture.base_dir.resolve()), "workspace_root": str(fixture.workspace.resolve()),
        "package_manifest_sha256": record["package_manifest_sha256"], "contract_version": 1,
        "contract_digest": record["contract_digest"], "controller_generation": 0,
        "handoff_id": record["handoff_id"], "arguments_sha256": digest(arguments),
    }

    class SourceAuthority:
        def authorize(self, incoming):
            if incoming.get("runtime_identity") is not identity:
                return {"status": "unknown"}
            if any(incoming.get(k) != v for k, v in expected.items()) or incoming.get("arguments") != arguments:
                return {"status": "unknown"}
            if any((fixture.workspace / (k + ".txt")).read_text() != v for k, v in contents.items()):
                return {"status": "unknown"}
            now = datetime.now(timezone.utc).replace(microsecond=0)
            return {
                "status": "pass", **expected, "purpose": "dispatch", "subject_id": "registered-source",
                "role": "controller", "scope_digest": digest(contents["authorization"]), "work_item_id": None,
                "subject_session_ref": deepcopy(refs["source"]),
                "source_session_ref": deepcopy(refs["source"]), "target_session_ref": deepcopy(refs["target"]),
                "authorization_ref": deepcopy(refs["authorization"]), "target_activation_status": "not_activated",
                "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "expires_at": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    authority = SourceAuthority()
    # Check the real authority path explicitly; do not assume a cancelled fence.
    fence = context._require_handoff_write_authorization(
        fixture.task_id, base_dir=fixture.base_dir, operation="host_reserve",
        arguments={"attempt_id": request["attempt_id"], "operation": "start_child", "request_sha256": digest(request)},
        runtime_identity=identity, write_authorizer=authority)
    before = events_path.read_bytes()
    ledger = HostTaskLedger(fixture.base_dir, fixture.host, identity, authority)
    result = ledger.reserve(request, "start_child")
    after = events_path.read_bytes()
    output = {"prepare": prepared, "cancel": cancelled,
              "actual_authorization_phase": fence["phase"], "actual_authorization_role": fence["authorization"]["role"],
              "reserve": result, "reserve_changed_event_log": before != after,
              "persisted_control_events": [e["event_type"] for e in map(json.loads, after.splitlines()) if e["event_type"].startswith("handoff_")],
              "mocked_product_functions": [], "real_host_validation": "NOT_RUN"}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    assert fence["phase"] == "cancelled" and fence["authorization"]["role"] == "controller"
    assert result["status"] == "pass" and result["reason_code"] == "RESERVED", result
    assert result["launch_allowed"] is True and before != after
    repeated = ledger.reserve(request, "start_child")
    assert repeated["reason_code"] == "ALREADY_RESERVED" and not repeated["launch_allowed"], repeated
    assert events_path.read_bytes() == after
    assert len(after.splitlines()) == len(before.splitlines()) + 1
finally:
    fixture.close()
