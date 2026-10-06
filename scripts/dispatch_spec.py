#!/usr/bin/env python3
"""Render an Orca dispatch spec from a sealed contract without task-store writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path


def _canonical(value: object) -> bytes:
    """Match the contract's integer-only, UTF-16-key-ordered JSON seal format."""
    def ordered(item: object) -> object:
        if isinstance(item, float):
            raise ValueError("contract seal does not support floating-point values")
        if isinstance(item, dict):
            return {key: ordered(item[key]) for key in sorted(
                item, key=lambda key: key.encode("utf-16-be", "surrogatepass")
            )}
        if isinstance(item, list):
            return [ordered(child) for child in item]
        return item

    return json.dumps(ordered(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_contract(store: Path, task_id: str) -> tuple[Path, dict]:
    """Read only the original contract; never bind, resume, or load a brief."""
    if not task_id or task_id in {".", ".."} or "/" in task_id or "\\" in task_id:
        raise ValueError("task-id must be a single directory name")
    store = store.expanduser().resolve()
    path = (store / task_id / "task-contract.json").resolve()
    if not path.is_relative_to(store):
        raise ValueError("contract must be inside the task store")
    contract = json.loads(path.read_bytes())
    if not isinstance(contract, dict) or contract.get("task_id") != task_id:
        raise ValueError("contract task_id does not match --task-id")
    seal = contract.get("seal")
    if not isinstance(seal, dict):
        raise ValueError("contract is not sealed")
    digest = seal.get("integrity_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("contract seal.integrity_digest is missing or invalid")
    unsigned = {**contract, "seal": {key: value for key, value in seal.items()
                                    if key != "integrity_digest"}}
    if digest != "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest():
        raise ValueError("contract seal.integrity_digest does not match the contract")
    criteria = contract.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("contract acceptance_criteria must be a nonempty list")
    for criterion in criteria:
        if not isinstance(criterion, dict) or any(
            not isinstance(criterion.get(key), str) or not criterion[key]
            for key in ("id", "criterion")
        ):
            raise ValueError("each acceptance criterion needs string id and criterion")
    if not isinstance(contract.get("objective"), str) or not contract["objective"]:
        raise ValueError("contract objective must be a nonempty string")
    for field in ("scope", "constraints", "out_of_scope"):
        if not isinstance(contract.get(field, []), list) or any(
            not isinstance(item, str) for item in contract.get(field, [])
        ):
            raise ValueError(f"contract {field} must be a list of strings")
    return path, contract


def version_proof_command(package_root: Path) -> str:
    """Use the public keyword-only runtime_identity(package_root=...) signature."""
    package_root = package_root.expanduser().resolve()
    code = (
        "import json, sys, managing_long_task_context as m; "
        "r = m.runtime_identity(package_root=sys.argv[1]); "
        'print(json.dumps({"loaded_module_file": m.__file__, '
        '"loaded_manifest_sha256": r["identity"]["loaded_manifest_sha256"]}))'
    )
    return (f"PYTHONPATH={shlex.quote(str(package_root / 'src'))} "
            f"python3 -c {shlex.quote(code)} {shlex.quote(str(package_root))}")


def render_spec(args: argparse.Namespace) -> str:
    path, contract = read_contract(Path(args.store), args.task_id)
    coordinator = Path(args.coordinator_workspace).expanduser().resolve()
    package = Path(args.package_root).expanduser().resolve()
    worker = (str(Path(args.worker_workspace).expanduser().resolve())
              if args.worker_workspace else "<worker-workspace-root>")
    owned = args.owned_paths if args.owned_paths is not None else contract.get("scope", [])
    if args.role == "reviewer":
        ownership = "Read-only review; no implementation paths may be edited."
        change = "Review the sealed scope against the baseline and original evidence."
    else:
        ownership = "\n".join(f"  - {item}" for item in owned) or "  - None declared."
        change = "Implement only the sealed scope:\n" + "\n".join(
            f"  - {item}" for item in contract.get("scope", [])
        )
    constraints = "\n".join(f"  - {item}" for item in contract.get("constraints", []))
    excluded = "\n".join(f"  - {item}" for item in contract.get("out_of_scope", []))
    # Do not strip, normalize, escape, or paraphrase either criterion field.
    criteria = "\n".join(f"- {item['id']}: {item['criterion']}"
                         for item in contract["acceptance_criteria"])
    report_root = f"{worker}/.context-reports/{args.task_id}"
    return f"""# {args.role.capitalize()} dispatch spec

## Objective, change, constraints, ownership

- Objective: {contract['objective']}
- Concrete change: {change}
- Constraints:
{constraints}
- Out of scope:
{excluded}
- Owned editable paths: {ownership}
- Allowed report/log paths: {report_root}/
- Baseline commit: {args.baseline_commit}

Keep the coordinator workspace read-only. The coordinator alone writes the task
and experience stores. 可调用 `brief()`、`checked_resume()` 与状态命令只读查看，
不得写任务库与经验库。 An owned path never expands the sealed scope.

## Task and acceptance

- Skill task_id: {args.task_id}
- Coordinator workspace (absolute): {coordinator}
- Worker workspace (absolute): {worker}
- Sealed contract (absolute): {path}
- Contract seal.integrity_digest: {contract['seal']['integrity_digest']}

Acceptance criteria, copied verbatim from the sealed contract:

{criteria}

Open and read the original contract before acting; it remains authoritative.
Verify the seal against the supplied digest. Stop and ask the coordinator if
the contract is missing, unreadable, unsealed, stale, or mismatched.

## Pinned runtime

- Package (absolute): {package}
- Expected manifest SHA-256: {args.expected_manifest}
- Version proof command:

```sh
{version_proof_command(package)}
```

Save the actual output. Require loaded_module_file to resolve under the pinned
package and loaded_manifest_sha256 to be nonempty and equal to the expected
digest. If either check fails, stop and ask the coordinator.

## Durable report and settlement

- Report path template (absolute): {report_root}/<dispatch-id>.json
- Check output path template (absolute): {report_root}/<dispatch-id>-<check-name>.log

Take the Orca Task and Dispatch ids from the live preamble, distinct from the
skill task_id above. Substitute its Dispatch id for the literal <dispatch-id>.
The worker resolves <worker-workspace-root> using git rev-parse --show-toplevel
unless --worker-workspace supplied the absolute root when generating this spec.
Write the JSON report immediately after checks and before worker_done; keep it
out of Git. Required fields: schema, task_id, orca_task_id, orca_dispatch_id,
contract_digest, loaded_module_file, loaded_manifest_sha256, code_revision,
checks, files_modified, deferred_suggestions, outcome_claim, written_at (UTC).
Each check records its command, exit code, output file, and output summary.
Report actual observations and unrun checks; deferred suggestions stay outside
this acceptance. A reviewer also records findings. Follow the live preamble's
heartbeat/check/worker_done commands and send worker_done exactly once with the
report path, both lifecycle ids, explicit outcome, and a three-sentence summary.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--role", required=True, choices=("executor", "reviewer"))
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--expected-manifest", required=True)
    parser.add_argument("--coordinator-workspace", required=True)
    parser.add_argument("--worker-workspace", help="Explicit worker root; otherwise leave a literal placeholder")
    parser.add_argument("--baseline-commit", required=True)
    parser.add_argument("--owned-paths", nargs="+", default=None)
    args = parser.parse_args(argv)
    try:
        output = render_spec(args)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        print(f"dispatch_spec: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(output.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
