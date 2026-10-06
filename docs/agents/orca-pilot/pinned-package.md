# Pinned Context Strict package for the Orca pilot

Built from the merged `main` baseline, before pilot work. The repository root is
the maintained source; `skills/context-strict/` is its generated installable source.
This package is outside the repository and does not update global installations.

| Identity | Fixed value |
|---|---|
| Package path | `/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012` |
| Source revision in manifest | `git:00ec012` |
| Resolved source commit | `00ec0127711080e13079fc3a39d5a634f4386576` |
| Skill/package version | `0.8.8` |
| Manifest SHA-256 | `9c74752b2d0bc446be4586ac28a8a2be0ab4b0dbfa6fa372728585f1ef1fc913` |
| Source tree SHA-256 | `affd0030f8623f69eb9f4cba295aeeaac09e6a8906d7de5a5dc886506bb04041` |
| Payload file count | `74` |

The worker checkout initially pointed at `e9a22d5`; the coordinator explicitly
approved a fast-forward to the resolved source commit before this build. No source
files were edited to correct the baseline.

## Build and verification

Run from the worker repository root. These are the commands actually executed:

```sh
python3 scripts/package_lineage.py --repo /Users/zhaowei/orca/workspaces/managing-long-task-context/issue-40-pinned-build --source-revision git:00ec012
python3 scripts/skill_package.py build --source skills/context-strict --destination /Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012 --source-revision git:00ec012
python3 scripts/skill_package.py verify --package /Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012
```

Lineage, build, and verification each exited `0` with `status: pass`. Verification
checked 74 payload files, 13 documented paths, and 24 Python exports. The manifest
hash above is the SHA-256 of `skill-manifest.json`, not a hash of `SKILL.md` alone.
Build requires an absent destination; preserve this frozen package and verify it
instead of rebuilding over it.

## Version proof

The maintained `src/managing_long_task_context/runtime_identity.py` declares
`runtime_identity(*, package_root: str | Path) -> dict[str, object]`. The public
export is `managing_long_task_context.runtime_identity`. The loaded digest is at
`result["identity"]["loaded_manifest_sha256"]`; it is observed from the importing
process. The command below matches `references/orca.md` and was actually run:

```sh
PYTHONPATH=/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012/src python3 -c 'import json, sys, managing_long_task_context as m; r = m.runtime_identity(package_root=sys.argv[1]); print(json.dumps({"loaded_module_file": m.__file__, "loaded_manifest_sha256": r["identity"]["loaded_manifest_sha256"]}))' /Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012
```

Actual output (exit `0`):

```json
{"loaded_module_file": "/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012/src/managing_long_task_context/__init__.py", "loaded_manifest_sha256": "9c74752b2d0bc446be4586ac28a8a2be0ab4b0dbfa6fa372728585f1ef1fc913"}
```

The resolved module file is under the fixed package directory. The loaded digest
is nonempty and equals the manifest SHA-256 above. Both assertions passed. Workers
must re-run this proof with the same `PYTHONPATH` used for their checks and record
their actual output; this build's output does not prove a later worker's imports.

Full package diagnosis also passed (exit `0`, runtime baseline, full verification,
and smoke checks all `pass`):

```sh
PYTHONPATH=/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012/src python3 /Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012/scripts/context_doctor.py check --mode full --package-root /Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012
```

## Fill a dispatch

Choose the executor, reviewer, or cold-reader template in this directory. Replace
its task-specific angle-bracket placeholders, using the package path, manifest
SHA-256, and source revision above. Copy acceptance criteria verbatim from the
sealed contract and supply its absolute path and seal digest; the contract remains
authoritative. Leave `<dispatch-id>` in the report path for the worker to fill from
the live Orca preamble. `report-example.json` contains only synthetic values.

Issue #40 preparation itself uses the issue as its contract, with report digest
`none: issue #40 is the contract`, as explicitly specified by the coordinator.
This preparation exception does not replace the sealed contract required for
subsequent pilot dispatches.
