"""Read-only E0 fixture validation. Not a product handoff implementation."""

from pathlib import Path
import json
import math
import re
import hashlib
import os
import stat
from itertools import product
from datetime import datetime

FILES = {"README.md", "protocol.md", "cases.json", "cases.schema.json", "catalog.json",
         "budget-profile.json", "ready-state.json", "interface.schema.json"}
PATTERNS = {"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", "^[a-f0-9]{64}$", "^HANDOFF_[A-Z_]+$",
            "^E0-[0-9]{3}$", "^[a-f0-9]{40}$", "^[a-z][a-z0-9_]+$"}


def _read(path):
    # Fixed local inventory only; never resolve fixture URIs or source_ref strings.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("fixture must be a regular file")
        data = stream.read(1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    if len(data) > 1024 * 1024:
        raise ValueError("fixture exceeds 1 MiB read limit")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("fixture changed during read")
    return data


def _json(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("non-finite JSON number")

    return json.loads(content, object_pairs_hook=unique, parse_constant=invalid_constant)


def _check(value, schema, definitions, at, issues):
    """Small, closed JSON Schema subset for this fixture package, not general JSON Schema."""
    supported = {"$schema", "$defs", "$ref", "title", "description", "type", "const", "enum",
                 "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
                 "uniqueItems", "minLength", "maxLength", "minimum", "maximum", "pattern", "format"}

    def error(message):
        issues.append({"code": "E0_SCHEMA", "path": at, "message": message})

    if not isinstance(schema, dict) or set(schema) - supported:
        error("unsupported schema keyword or shape")
        return
    if "$ref" in schema:
        key = schema["$ref"]
        if not isinstance(key, str) or not key.startswith("#/$defs/") or key[8:] not in definitions:
            error("only declared local definitions are supported")
            return
        return _check(value, definitions[key[8:]], definitions, at, issues)
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {"object": type(value) is dict, "array": type(value) is list,
               "string": type(value) is str, "integer": type(value) is int,
               "number": type(value) in (int, float) and math.isfinite(value),
               "boolean": type(value) is bool, "null": value is None}
    if types and not any(matches.get(t, False) for t in types):
        error("expected " + str(types))
        return
    # bool and int compare equal in Python; JSON enum/const must not alias them.
    exact = lambda a, b: type(a) is type(b) and a == b
    if "const" in schema and not exact(value, schema["const"]):
        error("unexpected constant")
    if "enum" in schema and not any(exact(value, x) for x in schema["enum"]):
        error("value outside allowed enum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                error("missing field: " + key)
        if schema.get("additionalProperties") is False and set(value) - set(props):
            error("unknown fields: " + ",".join(sorted(set(value) - set(props))))
        for key in sorted(value.keys() & props.keys()):
            _check(value[key], props[key], definitions, at + "." + key, issues)
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            error("array length outside bounds")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            error("duplicate array entries")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], definitions, f"{at}[{i}]", issues)
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", math.inf):
            error("string length outside bounds")
        if "pattern" in schema:
            if schema["pattern"] not in PATTERNS:
                error("pattern outside frozen safe subset")
            elif not re.fullmatch(schema["pattern"], value):
                error("string does not match pattern")
        if schema.get("format") == "utc":
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
                    raise ValueError()
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                error("expected real UTC timestamp YYYY-MM-DDTHH:MM:SSZ")
        elif schema.get("format") == "absolute-path":
            if not value.startswith("/") or "\x00" in value or ".." in value.split("/"):
                error("expected absolute lexical POSIX path without traversal")
        elif "format" in schema:
            error("unsupported format")
    if type(value) in (int, float):
        if not math.isfinite(value) or not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            error("number outside bounds")


def _validate_bundle(path):
    cache = {}

    def read(name):
        if name not in cache:
            cache[name] = _read(path / name)
        return cache[name]

    try:
        bundle = _json(read("cases.json").decode("utf-8"))
    except (OSError, ValueError) as exc:
        return [{"code": "E0_READ", "path": "cases.json", "message": str(exc)}]
    if not isinstance(bundle, dict) or not isinstance(bundle.get("cases"), list) or not bundle["cases"]:
        return [{"code": "E0_SCHEMA", "path": "cases.json", "message": "nonempty cases required"}]
    try:
        schema = _json(read("cases.schema.json").decode("utf-8"))
    except (OSError, ValueError) as exc:
        return [{"code": "E0_READ", "path": "cases.schema.json", "message": str(exc)}]
    issues = []
    _check(bundle, schema, {}, "cases.json", issues)
    if issues:
        return issues
    try:
        catalog = _json(read("catalog.json").decode("utf-8"))
        interface = _json(read("interface.schema.json").decode("utf-8"))
        ready = _json(read("ready-state.json").decode("utf-8"))
        budget = _json(read("budget-profile.json").decode("utf-8"))
    except (OSError, ValueError) as exc:
        return [{"code": "E0_READ", "path": "catalog.json", "message": str(exc)}]
    expected = {c["case_id"] for c in catalog["cases"]}
    limits = {"max_events": 2000, "max_log_bytes": 8388608, "max_event_bytes": 65536,
              "max_snapshot_items": 2000, "read_parse_rebuild_seconds": 5,
              "process_peak_rss_bytes": 134217728}
    if budget.get("limits") != limits or any(type(v) is not int for v in budget.get("limits", {}).values()) or budget.get("status") != "frozen_trial_acceptance_only":
        issues.append({"code": "E0_BUDGET", "path": "budget-profile.json", "message": "approved local replay trial budget differs"})
    covered = {tag for c in bundle["cases"] for tag in c["catalog_ids"]}
    if expected != covered:
        issues.append({"code": "E0_COVERAGE", "path": "cases.json", "message": "catalog coverage differs"})
    definitions = interface["$defs"]
    _check(ready["record"], definitions["record"], definitions, "ready-state.record", issues)
    version = ready["record"]["contract_version"]
    if isinstance(version, str) and not version.strip():
        issues.append({"code": "E0_SCHEMA", "path": "ready-state.record.contract_version", "message": "contract version must not be blank"})
    _check(ready["response"], definitions["response"], definitions, "ready-state.response", issues)
    for i, event in enumerate(ready["events"]):
        _check(event, definitions["event"], definitions, f"ready-state.events[{i}]", issues)
    for op, request in ready["requests"].items():
        if op not in {"prepare_handoff", "validate_handoff", "activate_handoff", "cancel_handoff", "handoff_status"}:
            issues.append({"code": "E0_SCHEMA", "path": op, "message": "unknown planned entry point"})
        else:
            _check(request, definitions[op], definitions, "ready-state.requests." + op, issues)
    if issues:
        return issues
    record = ready["record"]
    for event in ready["events"]:
        delta = 1 if event["type"] == "handoff_activated" else 0
        if event["controller_generation"] != event["expected_controller_generation"] + delta:
            issues.append({"code": "E0_EXPECTATION", "path": event["type"], "message": "event generation change contradicts protocol"})
    refs = record["basis_refs"] + [record[k] for k in ("source_session_ref", "target_session_ref", "authorization_ref", "artifact_manifest_ref")]
    if any(ref["task_id"] != record["task_id"] for ref in refs) or len({ref["ref_id"] for ref in refs}) != len(refs):
        issues.append({"code": "E0_BINDING", "path": "ready-state.record", "message": "cross-task or duplicate references"})
    for ref in refs:
        content = ready["filesystem"].get(ref["ref_id"])
        if not isinstance(content, str) or not content or ref["uri"] != "fixture:" + ref["ref_id"] or hashlib.sha256(content.encode()).hexdigest() != ref["sha256"]:
            issues.append({"code": "E0_BINDING", "path": ref["ref_id"], "message": "inline fixture content and reference differ"})
    api_names = {"prepare_handoff", "validate_handoff", "activate_handoff", "cancel_handoff", "handoff_status"}
    if set(ready["requests"]) != api_names:
        issues.append({"code": "E0_BINDING", "path": "ready-state.requests", "message": "five planned request fixtures required"})
    for op, request in ready["requests"].items():
        if request["task_id"] != record["task_id"] or request["workspace_root"] != record["workspace_root"]:
            issues.append({"code": "E0_BINDING", "path": op, "message": "request and record binding differ"})
        if op == "prepare_handoff":
            wanted = dict(record, request_id=request["request_id"])
            if request["record"] != wanted:
                issues.append({"code": "E0_BINDING", "path": op, "message": "prepare record differs from frozen initial basis"})
    if record["package_manifest_sha256"] != catalog["baseline_package_manifest_sha256"]:
        issues.append({"code": "E0_BASELINE", "path": "ready-state.record", "message": "package binding differs"})
    seen = set()
    combinations = set()
    migrations = set()
    log_boundaries = set()
    migration_expected = {
        "writer_active": ("running", "fail", "not_attempted"),
        "exit_unknown": ("unknown", "unknown", "not_attempted"),
        "writer_restarted": ("restarted", "fail", "not_attempted"),
        "direct_api_invalid_identity": ("exited", "fail", "not_attempted"),
        "verified_safe_migration": ("exited", "pass", "confirmed_committed"),
        "duplicate_migration": ("exited", "pass", "confirmed_committed"),
    }
    catalog_hash = hashlib.sha256(read("catalog.json")).hexdigest()
    methods = {"mechanism": "protocol_fixture", "process": "isolated_process_fault",
               "host": "host_adapter_then_live", "lite": "existing_lite_public_cli",
               "measurement": "fixed_usage_fixture", "model": "budgeted_fresh_model"}
    for case in bundle["cases"]:
        def error(code, message):
            issues.append({"code": code, "path": case["case_id"], "message": message})
        if case["case_id"] in seen:
            error("E0_DUPLICATE", "duplicate case identity")
        seen.add(case["case_id"])
        if case["baseline_revision"] != catalog["baseline_revision"] or case["baseline_package_hash"] != catalog["baseline_package_manifest_sha256"]:
            error("E0_BASELINE", "case and catalog baselines differ")
        if case["initial_state"]["task_id"] != record["task_id"] or case["initial_state"]["controller_generation"] != record["controller_generation"]:
            error("E0_BINDING", "case initial state does not match its named fixture")
        if op_name := case["operation"]["request_fixture"]:
            if op_name != case["operation"]["entry_point"]:
                error("E0_BINDING", "wrong request fixture for entry point")
        if methods[case["required_test_level"]] != case["test_method"]:
            error("E0_LEVEL", "method cannot prove declared test level")
        if set(case["forbidden_writes"]) != {"production", "global_install", "business_action", "legacy_contract"}:
            error("E0_EXPECTATION", "E0 side-effect boundary cannot be weakened")
        op = case["operation"]["entry_point"]
        if case["stimulus"]["kind"] == "mandatory_bytes":
            value = case["stimulus"]["value"]
            if value != {"budget_scope": "synthetic-flush-packet", "unit": "utf8-bytes", "limit": 64, "observed": 65} or op != "prepare_handoff":
                error("E0_BUDGET", "flush needs its own explicit synthetic packet budget, not the event-log budget")
        if case["stimulus"]["kind"] == "log_read_bytes":
            value = case["stimulus"]["value"]
            observed = value["observed"]
            if type(observed) is not int or observed in log_boundaries:
                error("E0_BUDGET", "invalid or duplicate log boundary")
            log_boundaries.add(observed)
            expected_check = "pass" if observed <= limits["max_log_bytes"] else "unknown"
            if (op != "validate_handoff" or case["injection_point"] != "during_read"
                    or value["budget_scope"] != "event-log-read" or value["unit"] != "bytes"
                    or value["limit"] != limits["max_log_bytes"]
                    or (case["expected_check"], case["expected_commit"], case["expected_generation_delta"]) != (expected_check, "not_attempted", 0)):
                error("E0_BUDGET", "log byte limit must be checked during event reading without writes")
        if case["stimulus"]["kind"] == "legacy_migration":
            value = case["stimulus"]["value"]
            scenario = value["scenario"]
            if scenario in migrations:
                error("E0_COVERAGE", "duplicate migration scenario")
            migrations.add(scenario)
            if (value["old_package_manifest_sha256"] != catalog["baseline_package_manifest_sha256"]
                    or case["required_test_level"] != "host"):
                error("E0_BASELINE", "migration needs pinned real old package and separate host verification")
            if (op != "migrate_task" or case["expected_generation_delta"] != 0
                    or (value["old_writer_state"], case["expected_check"], case["expected_commit"]) != migration_expected.get(scenario)):
                error("E0_EXPECTATION", "migration stimulus or expected outcome differs")
        if case["stimulus"]["kind"] == "feature_combination":
            value = case["stimulus"]["value"]
            flags = tuple(value[k] for k in ("truth_sources", "rule_execution", "independent_validation"))
            scenario = value["scenario"]
            key = flags + (scenario,)
            if any(type(flag) is not bool for flag in flags) or key in combinations:
                error("E0_COVERAGE", "invalid or duplicate feature combination")
            combinations.add(key)
            expected_basis = {"valid": "verified", "invalid_basis": "unknown", "changed_after_check": "changed"}.get(scenario)
            expected_result = ("pass", "confirmed_committed", 1) if scenario == "valid" else ("unknown", "not_attempted", 0)
            if (op != "activate_handoff" or value["handoff_basis"] != expected_basis
                    or (case["expected_check"], case["expected_commit"], case["expected_generation_delta"]) != expected_result
                    or case["injection_point"] != ("after_check" if scenario == "changed_after_check" else "before_check")):
                error("E0_EXPECTATION", "combination stimulus and expected handoff behavior differ")
        if (op == "handoff_status" and case["injection_point"] == "after_fsync"
                and case["stimulus"] == {"kind": "interrupt", "value": "kill"}
                and case["setup_actions"] == ["activate_until_injection"]):
            if (case["expected_check"], case["expected_commit"], case["expected_generation_delta"]) != ("pass", "confirmed_committed", 1):
                error("E0_EXPECTATION", "durable event plus process exit must be recoverable as committed")
        if op in {"activate_handoff", "auto_rollover"}:
            if case["expected_check"] in {"fail", "unknown"} and (case["expected_commit"] == "confirmed_committed" or case["expected_generation_delta"] != 0):
                error("E0_EXPECTATION", "failed/unknown activation must not transfer control")
        if case["expected_commit"] == "unknown" and case["expected_generation_delta"] is not None:
            error("E0_EXPECTATION", "unknown durable state cannot assert a generation delta")
        if case["source_kind"] != "synthetic":
            error("E0_SOURCE", "this catalog supplies synthetic behavior, not a historical execution")
        if case["source_sha256"] != catalog_hash:
            error("E0_SOURCE", "source fingerprint differs")
    wanted_combinations = set(product((False, True), (False, True), (False, True),
                                      ("valid", "invalid_basis", "changed_after_check")))
    if combinations != wanted_combinations:
        issues.append({"code": "E0_COVERAGE", "path": "cases.json", "message": "eight configurations each require three handoff scenarios"})
    if migrations != set(migration_expected):
        issues.append({"code": "E0_COVERAGE", "path": "cases.json", "message": "six legacy migration paths required"})
    if log_boundaries != {8388607, 8388608, 8388609}:
        issues.append({"code": "E0_COVERAGE", "path": "cases.json", "message": "log byte limit requires below/equal/above cases"})
    try:
        manifest = _json(read("manifest.json").decode("utf-8"))
        if set(manifest["files"]) != FILES:
            issues.append({"code": "E0_MANIFEST", "path": "manifest.json", "message": "incomplete or expanded file inventory"})
        if manifest["schema"] != "handoff-e0-manifest/v1" or type(manifest["fixture_version"]) is not int or manifest["fixture_version"] != bundle["fixture_version"] or manifest["baseline_revision"] != catalog["baseline_revision"] or manifest["baseline_package_manifest_sha256"] != catalog["baseline_package_manifest_sha256"]:
            issues.append({"code": "E0_MANIFEST", "path": "manifest.json", "message": "version or baseline differs"})
        for name, expected_file in manifest["files"].items():
            if name not in FILES:
                issues.append({"code": "E0_PATH", "path": "manifest.json", "message": "unexpected file path"})
                continue
            content = read(name)
            if hashlib.sha256(content).hexdigest() != expected_file["sha256"] or len(content) != expected_file["bytes"]:
                issues.append({"code": "E0_HASH", "path": name, "message": "frozen file fingerprint differs"})
    except (OSError, ValueError) as exc:
        issues.append({"code": "E0_READ", "path": "manifest.json", "message": str(exc)})
    return issues


def validate_bundle(path: Path) -> list[dict[str, str]]:
    """Return fixture errors; never execute the described scenarios."""
    try:
        return _validate_bundle(Path(path))
    except (TypeError, KeyError, AttributeError, RecursionError, OverflowError, ValueError) as exc:
        return [{"code": "E0_SCHEMA", "path": "bundle", "message": "malformed fixture metadata: " + type(exc).__name__}]


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Validate frozen E0 test specifications; execute no handoff.")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--expected-manifest-sha256", help="Previously approved external pin, not a self-authenticating signature")
    args = parser.parse_args()
    started = time.perf_counter()
    errors = validate_bundle(args.bundle)
    if args.expected_manifest_sha256:
        try:
            actual = hashlib.sha256(_read(args.bundle / "manifest.json")).hexdigest()
            if actual != args.expected_manifest_sha256:
                errors.append({"code": "E0_HASH", "path": "manifest.json", "message": "external approved pin differs"})
        except (OSError, ValueError) as exc:
            errors.append({"code": "E0_READ", "path": "manifest.json", "message": str(exc)})
    print(json.dumps({"fixture_validation": "fail" if errors else "pass", "issues": errors,
                      "product_execution": "NOT_RUN", "model_execution": "NOT_RUN",
                      "natural_usage": "NOT_RUN", "token_cost": None,
                      "elapsed_seconds": time.perf_counter() - started}, ensure_ascii=False))
    raise SystemExit(1 if errors else 0)
