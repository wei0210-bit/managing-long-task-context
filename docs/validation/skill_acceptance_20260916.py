"""Offline package acceptance; synthetic state only, no model or business calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]).resolve()
PACKAGES = Path(sys.argv[2]).resolve()
records = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(label, argv, cwd, env=None, expected=(0,)):
    start = time.monotonic()
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    records.append(dict(label=label, argv=list(map(str, argv)), cwd=str(cwd),
                        exit_code=result.returncode, seconds=round(time.monotonic()-start, 6),
                        stdout=result.stdout, stderr=result.stderr))
    assert result.returncode in expected, records[-1]
    return result.stdout


def main():
    identities = {}
    with tempfile.TemporaryDirectory(prefix="mltc-acceptance-") as tmp:
        work = Path(tmp)
        for name in ("strict", "lite"):
            pkg = PACKAGES / f"context-{name}"
            receipt = ROOT / f"docs/validation/upgrade-review-fix-{name}-manifest.json"
            assert (pkg / "skill-manifest.json").read_bytes() == receipt.read_bytes()
            manifest = json.loads(receipt.read_text())
            for entry in manifest["files"]:
                assert digest(pkg / entry["path"]) == digest(ROOT / "skills" / f"context-{name}" / entry["path"]), entry
            identities[name] = digest(receipt)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(pkg / "src") if name == "strict" else "")
            run(f"{name}-verify", [sys.executable, str(pkg / "scripts/skill_package.py"), "verify", "--package", str(pkg)], work, env)
            full = json.loads(run(f"{name}-doctor", [sys.executable, str(pkg / "scripts/context_doctor.py"), "check", "--mode", "full", "--package-root", str(pkg)], work, env))
            assert full["status"] == full["full_verification"] == "pass"
        pkg = PACKAGES / "context-lite"
        cli = [sys.executable, str(pkg / "scripts/context_lite.py")]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH="")
        original = work / "original.txt"
        original.write_text("baseline-v1\n")
        candidate = work / "candidate.md"
        candidate.write_text(f"""# QA-LOCAL: Resume a synthetic local task

Updated: 2026-09-16T00:00:00Z
Phase: implementation

## Acceptance
- Independently observe the current original before relying on it.

## Current State
- [STATE-01] baseline-v1 | mutable: true | source: {original} | refreshed_at: 2026-09-16T00:00:00Z | refresh_ref: read:{original}

## Decisions
- No business action | why: isolated acceptance | evidence: {original}

## In Flight
- [RUN-01] Synthetic unresolved action | owner: fixture | status: unknown | started_at: 2026-09-16T00:00:00Z | correlation_ref: tool:synthetic | recovery_ref: read:{work}/missing-result.txt

## Blockers
- RUN-01 outcome is unknown; do not retry.

## Next
1. First: independently read the original

## Refresh On Resume
- STATE-01 -> read:{original}
- RUN-01 -> read:{work}/missing-result.txt
""")
        flush = json.loads(run("lite-flush", cli + ["flush", "--candidate", str(candidate), "--base-dir", str(work), "--task-id", "QA-LOCAL"], work, env))
        now = work / ".context-lite/QA-LOCAL/NOW.md"
        now_hash = digest(now)
        assert flush["now_sha256"] == now_hash
        args = ["--package-root", str(pkg), "--context-root", str(work / ".context-lite"), "--workspace-root", str(work), "--task-id", "QA-LOCAL"]
        run("lite-bind", [sys.executable, str(pkg / "scripts/context_doctor.py"), "init-binding", *args, "--expected-manifest-sha256", identities["lite"]], work, env)
        material = []
        for n in range(3):
            report = json.loads(run(f"lite-cold-{n}", cli + ["cold-check", *args, "--expected-now-sha256", now_hash], work, env))
            assert report["semantic_verification"] == "pending" and report["archive_allowed"] is False
            assert report["history_inheritance"] == "unknown"
            material.append(report["material"])
        assert material[0] == material[1] == material[2]
        assert material[0]["first_action"] == "independently read the original"
        assert "unknown" in str(material[0]["in_flight"]) and "do not retry" in str(material[0]["blockers"])
        assert digest(now) == now_hash and not (work / "missing-result.txt").exists()
        for label, extra in [("bad-hash", ["--expected-now-sha256", "0"*64]), ("wrong-workspace", ["--workspace-root", str(pkg)])]:
            rejected = json.loads(run(f"lite-{label}", cli + ["cold-check", *args, *extra], work, env, (1, 2)))
            assert rejected["material"] is None
        original.write_text("baseline-v2\n")
        changed = json.loads(run("lite-original-changed", cli + ["cold-check", *args, "--expected-now-sha256", now_hash], work, env))
        assert changed["semantic_verification"] == "pending" and changed["archive_allowed"] is False
        assert changed["material"] == material[0]  # Deliberately NOT live truth verification.
        now.rename(now.with_suffix(".saved"))
        missing = json.loads(run("lite-missing-now", cli + ["cold-check", *args], work, env, (1, 2)))
        assert missing["material"] is None
        strict = PACKAGES / "context-strict"
        env["PYTHONPATH"] = str(strict / "src")
        run("strict-public-example", [sys.executable, str(strict / "examples/short_session_handoff.py")], work, env)
        for name, modules in [("strict", ["test_handoff_activation", "test_handoff_host_records", "test_handoff_codex_cli", "test_handoff_codex_native", "test_handoff_claude_native"]), ("lite", ["test_context_lite_handoff"])]:
            package = PACKAGES / f"context-{name}"
            env["PYTHONPATH"] = os.pathsep.join([str(package / "src"), str(package / "tests")])
            text = run(f"{name}-targeted-tests", [sys.executable, "-W", "always::ResourceWarning", "-m", "unittest", *modules, "-v"], work, env)
            assert "skipped=" not in records[-1]["stderr"] and "ResourceWarning:" not in records[-1]["stderr"]
    return identities


report = {"schema": 1, "kind": "synthetic-offline-package-acceptance", "model_calls": 0,
          "actual_model_tokens": None, "model_stability": "NOT_RUN", "records": records,
          "contract_sha256": digest(ROOT / "docs/validation/2026-09-16-skill-acceptance-contract.md")}
try:
    report["identities"] = main()
    report["status"] = "pass"
except Exception as error:
    report["status"] = "fail"
    report["error"] = repr(error)
    raise
finally:
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "commands": len(records), "output": str(OUT)}))
