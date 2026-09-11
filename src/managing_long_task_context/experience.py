"""Strict-only lifecycle mutation facade for verified experiences."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from . import _experience_store as _core


def _result(callback: Any, *arguments: object) -> dict[str, Any]:
    if not callable(callback):
        return _core.report("unknown", ["CHECKER_REQUIRED"])
    try:
        value = callback(*deepcopy(arguments))
    except TimeoutError:
        return _core.report("unknown", ["CALLBACK_TIMEOUT"])
    except Exception:
        return _core.report("unknown", ["CALLBACK_ERROR"])
    if not isinstance(value, dict) or set(value) != {"status", "codes"}:
        return _core.report("unknown", ["CALLBACK_INVALID_RESULT"])
    status, codes = value.get("status"), value.get("codes")
    if not isinstance(status, str) or status not in {"pass", "fail", "unknown"} or not isinstance(codes, list) or not all(isinstance(code, str) and code for code in codes):
        return _core.report("unknown", ["CALLBACK_INVALID_RESULT"])
    return _core.report(status, list(codes))


class ExperienceStore:
    """Strict public API. Every external callback runs after releasing the lock."""

    def __init__(self, workspace: Path, store: Path) -> None:
        self.workspace, self.store = workspace, store

    def _snapshot(self, experience_id: str, revision: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not isinstance(experience_id, str) or _core.ID_RE.fullmatch(experience_id) is None or type(revision) is not int or revision <= 0:
            return None, _core.report("fail", ["INVALID_INPUT"])
        _core._read_binding(self.store, self.workspace)
        with _core._store_lock(self.store):
            records = _core._read_records(self.store, self.workspace)
            record = next((item for item in records if item["experience_id"] == experience_id and item["revision"] == revision), None)
            if record is None:
                return None, _core.report("fail", ["EXPERIENCE_NOT_FOUND"])
            return deepcopy(record), None

    def _append(self, snapshot: dict[str, Any], expected: str, event: dict[str, Any], *, validation_refs: object | None = None, approval_ref: object | None = None, verify_originals: bool, require_latest: bool) -> dict[str, Any]:
        with _core._store_lock(self.store):
            _core._read_binding(self.store, self.workspace)
            records = _core._read_records(self.store, self.workspace)
            current = next((item for item in records if item["experience_id"] == snapshot["experience_id"] and item["revision"] == snapshot["revision"]), None)
            latest = max((item["revision"] for item in records if item["experience_id"] == snapshot["experience_id"]), default=0)
            if current is None or (require_latest and latest != snapshot["revision"]) or current["status"] != expected or _core._record_digest(current) != _core._record_digest(snapshot):
                return _core.report("unknown", ["INPUT_CHANGED"])
            if verify_originals:
                validity = _core._record_validity(current, self.workspace)
                if validity["status"] != "pass":
                    return _core.report(validity["status"], validity["codes"])
            if validation_refs is not None:
                failure = _core._verify_validation_refs(validation_refs, self.workspace, require_current=True)
                if failure is not None:
                    return failure
            if approval_ref is not None:
                failure = _core._verify_source_ref(approval_ref["source_ref"], self.workspace)
                if failure is not None:
                    return failure
            current["lifecycle"].append(deepcopy(event))
            current["status"] = event["status"]
            try:
                _core._atomic_json_write(self.store / _core.STORE_RECORDS, {"schema": 1, "records": records})
            except OSError as error:
                raise _core.InputError("STORE_UNAVAILABLE") from error
            validity = _core._record_validity(current, self.workspace)
            data = _core._get_data(current, validity)
            return _core.report(validity["status"] if verify_originals else "pass", validity["codes"] if verify_originals else [], data)

    def get(self, experience_id: str, revision: int) -> dict[str, Any]:
        try:
            return _core.get_record(self.workspace, self.store, experience_id, revision)
        except _core.InputError as error:
            return _core.report(error.status, [error.code])

    def review(self, experience_id: str, revision: int, validation_refs: object, *, evidence_checker: Any = None) -> dict[str, Any]:
        try:
            refs = deepcopy(validation_refs)
            snapshot, failure = self._snapshot(experience_id, revision)
            if failure is not None:
                return failure
            assert snapshot is not None
            if snapshot["status"] != "candidate":
                return _core.report("fail", ["INVALID_TRANSITION"])
            failure = _core._verify_validation_refs(refs, self.workspace, require_current=True)
            if failure is not None:
                return failure
            callback_record = deepcopy(snapshot)
            callback_record["record_digest"] = _core._record_digest(snapshot)
            checked = _result(evidence_checker, callback_record, refs)
            if checked["status"] != "pass":
                return checked
            return self._append(snapshot, "candidate", {"status": "validated", "validation_refs": refs}, validation_refs=refs, verify_originals=True, require_latest=True)
        except _core.InputError as error:
            return _core.report(error.status, [error.code])

    def approve(self, experience_id: str, revision: int, approval_ref: object, *, approval_checker: Any = None, evidence_checker: Any = None) -> dict[str, Any]:
        try:
            frozen_approval = deepcopy(approval_ref)
            snapshot, failure = self._snapshot(experience_id, revision)
            if failure is not None:
                return failure
            assert snapshot is not None
            if snapshot["status"] != "validated":
                return _core.report("fail", ["INVALID_TRANSITION"])
            validated = _core._latest_lifecycle_event(snapshot, "validated")
            assert validated is not None
            refs = deepcopy(validated["validation_refs"])
            failure = _core._verify_validation_refs(refs, self.workspace, require_current=True)
            if failure is not None:
                return failure
            if not _core._approval_ref_shape(frozen_approval, snapshot):
                return _core.report("fail", ["INVALID_INPUT"])
            failure = _core._verify_source_ref(frozen_approval["source_ref"], self.workspace)
            if failure is not None:
                return failure
            checked_evidence = _result(evidence_checker, deepcopy(snapshot), refs)
            if checked_evidence["status"] != "pass":
                return checked_evidence
            callback_record = deepcopy(snapshot)
            callback_record["record_digest"] = _core._record_digest(snapshot)
            checked_approval = _result(approval_checker, callback_record, frozen_approval)
            if checked_approval["status"] != "pass":
                return checked_approval
            return self._append(snapshot, "validated", {"status": "approved", "approval_ref": frozen_approval}, validation_refs=refs, approval_ref=frozen_approval, verify_originals=True, require_latest=True)
        except _core.InputError as error:
            return _core.report(error.status, [error.code])

    def dispute(self, experience_id: str, revision: int, reason: object, source_ref: object) -> dict[str, Any]:
        try:
            frozen_source = deepcopy(source_ref)
            snapshot, failure = self._snapshot(experience_id, revision)
            if failure is not None:
                return failure
            assert snapshot is not None
            if snapshot["status"] not in {"candidate", "validated", "approved"} or not _core._reason_shape(reason):
                return _core.report("fail", ["INVALID_INPUT"])
            failure = _core._verify_source_ref(frozen_source, self.workspace)
            if failure is not None:
                return failure
            return self._append(snapshot, snapshot["status"], {"status": "disputed", "reason": reason, "source_ref": frozen_source}, verify_originals=False, require_latest=False)
        except _core.InputError as error:
            return _core.report(error.status, [error.code])

    def revoke(self, experience_id: str, revision: int, reason: object, approval_ref: object, *, approval_checker: Any = None) -> dict[str, Any]:
        try:
            frozen_approval = deepcopy(approval_ref)
            snapshot, failure = self._snapshot(experience_id, revision)
            if failure is not None:
                return failure
            assert snapshot is not None
            if snapshot["status"] in {"disputed", "revoked"} or not _core._reason_shape(reason):
                return _core.report("fail", ["INVALID_INPUT"])
            if not _core._approval_ref_shape(frozen_approval, snapshot):
                return _core.report("fail", ["INVALID_INPUT"])
            failure = _core._verify_source_ref(frozen_approval["source_ref"], self.workspace)
            if failure is not None:
                return failure
            callback_record = deepcopy(snapshot)
            callback_record["record_digest"] = _core._record_digest(snapshot)
            checked = _result(approval_checker, callback_record, frozen_approval)
            if checked["status"] != "pass":
                return checked
            return self._append(snapshot, snapshot["status"], {"status": "revoked", "reason": reason, "approval_ref": frozen_approval}, approval_ref=frozen_approval, verify_originals=False, require_latest=False)
        except _core.InputError as error:
            return _core.report(error.status, [error.code])


def bind_experience(workspace_root: str | Path, store_root: str | Path) -> ExperienceStore:
    workspace = _core._workspace_path(str(workspace_root))
    return ExperienceStore(workspace, _core._store_path(workspace, str(store_root)))


__all__ = ["bind_experience"]
