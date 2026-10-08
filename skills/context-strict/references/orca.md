# Orca dispatch and handoff

## Why

Orca records who owns work and when a worker has settled. It does not know the task's
acceptance criteria, it does not verify success, and it does not stop two workers from
writing the same files. Context Strict holds the sealed contract, facts, and evidence.
This reference is the collaboration procedure for the points where work changes hands:
a supervised dispatch, a review, a coordinator takeover, and an unsupervised handoff.

Orca commands and flags are defined by the installed Orca build, not here. `<orca>`
below stands for the exact executable a worker's live preamble uses, or that a
coordinator used to run `skills get`; do not hard-code another name. Load Orca's own
guides with `<orca> skills get orchestration` (supervised work) or
`<orca> skills get orca-cli` (handoffs).

## Boundary: Orca settlement is not acceptance

| Question | Authority |
|---|---|
| Which attempt is active, has the worker settled, who owns the terminal | Orca Run / Task / Dispatch |
| Objective, scope, constraints, acceptance criteria | Sealed contract in `.prime/context/<task-id>/` |
| Whether a criterion is met | Strict completion gate over resolved evidence |

A valid `worker_done` settles the Orca Task and Dispatch automatically and releases
downstream Orca work. Orca has no separate review or acceptance status, and the
coordinator does not settle the Task a second time. Acceptance is an independent
conclusion on the Strict side: a worker's `--outcome succeeded` is a lifecycle fact
and a lead, never evidence that a criterion is met. The coordinator reports the
completion gate result (`pass`, `fail`, or `unknown`) whatever outcome the worker sent.

For a Task whose worker was stopped with `worker-stop`, ingest the worker's report
first, then use `task-update --status completed --result` to record the Task's
conclusion. The result must explicitly say "lifecycle conclusion, not acceptance"
and state the Strict acceptance result separately.

## Where a worker reads the task store

The coordinator is the only writer of the task store and the experience store.
Workers and reviewers only read.

| Placement | How the worker reads |
|---|---|
| Same workspace (Orca `--worktree current`) | Read the task store and the sealed contract file directly in that workspace. |
| New worktree on the same machine (Orca `new-child`) | The new checkout has no task store, because `.prime/context/` is gitignored. The dispatch spec gives the absolute path of the coordinator's workspace. Read the sealed contract file under that path, and call `read_task(task_id, Path("<coordinator workspace>"))` with that path as the root. Read-only entries below may use the coordinator workspace and context root; do not write to either store. |
| Remote host | Not supported. |

Read-only roles (workers, reviewers, and cold readers) may use:

| Entry | Writes files? | Basis |
|---|---|---|
| Dispatch spec and sealed contract file | No | Direct read |
| `read_task(task_id, Path(<coordinator workspace>))` | No | Existing project-store read |
| `brief(task_id, base_dir=<coordinator workspace>/.prime/context)` / `brief_diagnostics(...)` | No | Shared lock on the existing `.lock`; read-only tests |
| `checked_resume(...)`, with coordinator workspace/context root and no handlers | No | Includes read-only resume gate; hash and permission tests |
| `scripts/context_status.py` | No | Five-section read-only wrapper |

Do not call writing entries: `record`, `update_item`, `checkpoint`,
`publish_contract`, `init-binding`, `publish_context`, `align_context`, or
`record_acceptance` (#46). `gate()` is not a separate entry for read-only roles.
Acceptance conclusions are read through `brief()` and the status command;
#46 defines their presentation, and is outside this implementation scope.

## Dispatch spec

Every dispatch spec is self-contained and contains:

1. Objective, the concrete change, constraints, and file ownership (which paths this
   worker may edit). Parallel executors each use their own worktree; the coordinator
   integrates their branches one at a time, and conflicts or out-of-scope edits found
   during integration show whether ownership held.
2. The skill `task_id`, fixed before dispatch.
3. Acceptance criteria copied verbatim from the sealed contract, with the absolute
   contract file path and the seal digest attached. The contract is authoritative;
   never paraphrase, summarize, or weaken the criteria. This matches item 5 of the
   handoff pack in `SKILL.md`.
4. The absolute path of the coordinator's workspace (needed for a new worktree).
5. The report path template from the worker report contract below, with the literal
   placeholder `<dispatch-id>`.
6. The pinned package path, its expected manifest digest, and the version-proof command.

Choose any further context from the role whitelist in `agent-role-handoff.md`.

Immediately after publishing a contract, run `context_doctor.py init-binding` for
that task. Publishing does not initialize the binding; without this step,
`checked_resume()` returns `BINDING_MISSING`. See
[#55](https://github.com/wei0210-bit/managing-long-task-context/issues/55); this is
a procedure requirement only.

Follow the complete `init-binding` command in SKILL.md section 1, immediately
between publication and release. Use the independently retained manifest digest
from the dispatch or handoff material, never an automatically derived expected
value. Only the coordinator initializes binding; without it recovery returns
`BINDING_MISSING` and null context.

## Worker report contract

A worker report is a durable evidence source that the coordinator checks before
ingesting it. It is not a handoff receipt, it does not transfer control, and it is
not a verified fact until the coordinator has ingested and checked it.

**Path:** `<worker workspace root>/.context-reports/<task_id>/<dispatch-id>.json`.
`task_id` is the skill task id from the dispatch spec. The worker takes the dispatch
id from the `--dispatch-id` value that Orca already filled in under the preamble's
`=== CLI COMMANDS ===` section. The coordinator learns the dispatch id and workspace
from the `worker-start` receipt, so it can derive the path even when no `worker_done`
arrives. Projects keep `.context-reports/` out of Git; never commit a report.

**Timing:** write the report as soon as the checks finish and before `worker_done`.
Pass the same path as `worker_done --report-path`.

**Required fields:**

| Field | Content |
|---|---|
| `schema` | Report schema version |
| `task_id` | Skill task id |
| `orca_task_id` | Orca Task id from the preamble |
| `orca_dispatch_id` | Orca Dispatch id from the preamble |
| `contract_digest` | Seal digest of the contract the worker read |
| `loaded_module_file` | From the version proof below |
| `loaded_manifest_sha256` | From the version proof below |
| `code_revision` | Commit id and whether the tree had uncommitted changes |
| `checks` | Per check: command, integer exit_code, workspace-relative output_file, output_sha256, and string output_summary |
| `checks[].output_sha256` | SHA-256 of the output file bytes, 64 lowercase hex characters |
| `files_modified` | Files the worker changed |
| `deferred_suggestions` | Out-of-scope findings, one entry each; not acted on |
| `outcome_claim` | The worker's own claim; a lead, not a verdict |
| `written_at` | UTC timestamp |

For `worker-report` evidence, the host explicitly constructs
`resolvers, verifiers = worker_report_handlers(absolute_workspace_root)` and passes
them to the gate. The envelope binds the report bytes with `artifact_digest`
(`sha256:<64 lowercase hex>`), and the report's `contract_digest` matches the seal.
Paths for the report locator and every output_file are relative to the bound root;
absolute paths, parent traversal, and symlinks are rejected. code_revision is
`{"commit": "<40-character HEAD>", "dirty": false}`. Required fields are typed as
strings (including a 64-character loaded_manifest_sha256), arrays for checks,
files_modified and deferred_suggestions, and a positive integer or nonempty string
schema version; written_at is a UTC RFC3339 timestamp.

The completion gate's evidence must be a report produced by the coordinator
rerunning the sealed worker_report_claim.commands in its own workspace on the
integration commit. The coordinator binds that workspace, and the verifier checks
the current HEAD and computes dirty itself, excluding .prime/,
.githooks/pre-commit, .prime/scripts/merge-events.py and .gitattributes. Untracked,
unignored files count as dirty. A worker's own report remains a review lead.
This verifies sealed-command coverage, zero exit codes and intact local output
files; it does not prove the commands actually executed or replace independent
validation.

**Version proof:** run this with the same `PYTHONPATH` the checks use, so it reports
the module that process actually imports:

```sh
PYTHONPATH=<pinned-package>/src python3 -c 'import json, sys, managing_long_task_context as m; r = m.runtime_identity(package_root=sys.argv[1]); print(json.dumps({"loaded_module_file": m.__file__, "loaded_manifest_sha256": r["identity"]["loaded_manifest_sha256"]}))' <pinned-package>
```

`<pinned-package>` is the absolute package path from the dispatch spec. If
`loaded_module_file` is not under the pinned package, or the digest differs from the
expected value, that worker's result is void.

**When blocked:** if the contract is missing, unreadable, unsealed, or stale, first ask
the coordinator with the preamble's `ask` command. If that does not resolve it, send
`worker_done` once with `--outcome failed` and state the reason. Never exit silently,
never report success, and never invent or infer acceptance criteria.

**Heartbeats:** a long gate or test run must not stop heartbeats. Keep sending them at
the preamble's cadence while it runs, for example by running it in the background. A
heartbeat proves liveness only.

## Reviewer task

The coordinator creates the reviewer task only after it has collected the executor
reports and integrated their branches. It does not use an Orca DAG dependency for this.

The reviewer receives: the contract path and seal digest, the base commit, the
coordinator's integrated branch, every executor report path, and the coordinator's own
check log. It only reads. It writes its own report under the same report contract;
`checks` records the commands it actually ran, `outcome_claim` is its review verdict,
and it adds a `findings` list.

Base drift: if the base branch moves after the reviewer task is created, the base
commit the review relied on is no longer current. Record the base commit in the
reviewer task, and if it changes, re-run the review against the new base instead of
reusing the old findings.

The coordinator ingests the reviewer report as one piece of evidence and then runs the
completion gate. This procedure does not enable the contract's
`independent_validation_required`.

## Coordinator: ingest and deduplicate

This is a manual procedure for the coordinator, not enforced by code.

1. Before ingesting a report, look in the snapshot for a main item with that report's
   `orca_dispatch_id`.
2. If there is none, record one main item:
   `record(task_id, item_type="observation", metadata={"orca_dispatch_id": ..., "report_sha256": ..., "role": "report-ingest"}, ...)`.
3. Then record each entry of `deferred_suggestions` as its own item, in report order.
   Its metadata carries the same `orca_dispatch_id` and a `report_item` sequence number,
   and its content is marked `{"deferred": true}`.
4. If the main item exists but there are fewer suggestion items than the report has,
   record only the missing sequence numbers. If all are present, write nothing.

When a review report covers multiple tasks, record each suggestion under the
`task_id` marked for that entry in the report. If an entry has no `task_id`, record
it under the coordinator's current task and add `{"report_task_unspecified": true}`
to its metadata.

Pass condition: each dispatch id has exactly one main item, and its number of
suggestion items equals the number in the report.

Re-check every load-bearing claim in a report against originals (Git state, test logs,
the output files) before relying on it, then run the completion gate.

## Coordinator takeover

If the coordinator exits mid-run, a new session rebinds the Run with Orca's `run-use`
(exact flags from Orca's guide for the installed build; Orca fences the old
coordinator), then runs `checked_resume()` for the task. Only the session bound to the
Run may write to the task store. This is a convention, not enforced by code. Then apply
the ingest procedure above; it does not re-dispatch work that already has a report.

When `checked_resume()` or the status command reports a non-pass resume gate,
keep the returned context for diagnosis and use `diagnostic.status`, not its
presence, to decide whether to continue. Re-observe expired facts with `ttl_hours`
and refresh via `update_item`; facts without a TTL need
`record(..., supersedes=<old id>)` with `ttl_hours`. Resolve conflicts by
superseding the losing side and reactivating any conflicted winner with
`update_item(status="active")`. Blocking items allow dispatch only of work to
解除该阻塞; other new execution waits for the gate to pass. Supply `rule_runtime`
in the Python host when unavailable. For a read race or gate exception, rerun
once; a persistent discrepancy is handled as a gate error, never repeated blindly.

After `run-use`, do not acknowledge a delivery batch id copied from the takeover
document. Run `check` after takeover and use the delivery batch id it returns for
the acknowledgment; rebinding the Run can change that id.

## Unsupervised handoff (orca-cli)

A handoff to another agent or worktree creates no Run, Task, or Dispatch, so Orca
reports nothing about completion. The handoff message is the only carrier:

1. It includes the same handoff pack from `SKILL.md`, with the absolute Strict path
   and the acceptance criteria copied verbatim with contract path and seal digest.
2. Pass the handoff gate and produce a usable `brief()` first when the runtime is
   available.
3. Orca's handoff ends with the original agent stopping once the prompt send is
   confirmed. That is Orca's ownership rule; it says nothing about whether the receiver
   read the material or took control. On the Strict side, under the session-migration
   rules in `SKILL.md`, `control_transfer` stays `unknown` until proven by readback,
   and the source session and its records are kept, not archived. The original agent
   stopping work and the source session being retired are different things.

## Out of scope

This reference does not define Orca commands or flags, routing, retries, or
escalation, and it does not replace `brief()`, `gate()`, or `short-session-handoff/v1`.
Keep these rules in this package; do not write them into Orca's own skill directories.

## Coordinator: acceptance-record workflow (Strict 0.12.0)

1. Keep the worker worktrees for comparison. On the integration commit, rerun
   the sealed commands in the coordinator workspace and write a fresh report
   with output files and hashes there; a worker report is only a review lead.
2. Construct the host-bound `worker_report_handlers` for that workspace. Call
   `record_acceptance` there with the sealed evidence map, `recorded_by`, and
   `watched_paths` from the dispatch's `owned_paths`. Natural-language scope
   text is not a path list. Completion runs inside the recorder before its
   writer lock, then it checks contract, ledger, HEAD, dirty state and watched
   content again; `RECORD_RACE` or `EVIDENCE_CHANGED` means no record was appended.
3. Immediately publish the completed record and retained evidence with
   `publish_context` under the existing publication authorization. Publish
   before a handoff or branch switch; the receiving branch records its own
   acceptance. `acceptance-records.jsonl` is a sidecar, with no merge attribute,
   ledger event or snapshot field. Records exist per branch.
4. Read `brief()` for the then-current conclusion and `context_status.py`
   section 6 for validity now, commit ancestry and ledger advancement. A pass
   record means completion only while that status is `still_valid`. Evidence
   skipped for SECRET_MARKER, SIZE_LIMIT or TOTAL_LIMIT is shown as unretained,
   and is not treated as a missing copy. Retained copies that are missing or
   changed yield unknown. Copies are read-only and never automatically cleaned.

Only the coordinator writes records. Local unpublished or malformed record lines
block new `align_context` with LOCAL_AHEAD. Two checkouts writing and merging
records can produce conflict markers: the recorder then refuses and validity is
unknown; there is no manual merge recovery. David must directly authorize any
record rebuild or deletion. Keep worker worktrees until `record_acceptance` has
finished. Before global synchronization, only the new pinned package writes and
reads acceptance records; publish before aligning, and do not run old-package
alignment in the same checkout because it may overwrite unpublished sidecars.
Secret checks use six known markers; secrets outside that list can still be copied
and pushed under the existing publication authorization.

## Schema 2 experience sharing (Strict 0.13.0 / Lite 1.5.0)

The coordinator is the single experience writer. Receivers must not initialize
local libraries: fetch/merge of published context can silently overwrite an
existing ignored `.prime/experience/` library. In a temporary test repository,
exercise `publish_context` -> receiver fetch/merge -> configure
`core.hooksPath=.githooks` -> `align_context`. Real publication requires David's
separate authorization.

Before global synchronization, never use the new package to `init` an experience
store in a real repository; use temporary stores for implementation and validation.
Old packages report `WORKSPACE_MISMATCH` for schema 2 bindings: check the loaded
version first. Forks and other projects with shared root commits are admitted;
no common history and relocated stores remain blocked. Orphan branches can lose
that intersection until restored. Unavailable Git metadata or shallow history
returns `PROJECT_IDENTITY_UNAVAILABLE`. Existing schema 1 stores remain unchanged;
no migration is provided. Source paths are relative on disk and absolute in
outputs/callbacks; `record_digest` must not be recomputed from restored output.
Rule execution keeps its absolute `store_root` restriction.

## 封印前影响面检查（A）

协调者在封印合同前，对计划改动的字面量、符号和文件运行
`scripts/contract_precheck.py`，将命中的测试逐项核对：要么列入合同 scope，
要么在合同里写明该测试为何不受影响。命中结果只是影响面线索，不能替代核对。

凡合同含数值阈值，须在每个要求的解释器上实测，并把各解释器的实测值写进
合同后再封印。设计要求须追到所有受影响的函数，将这些函数及其文件列入
scope，不能只列入口或最先发现的函数。

## 读盘功能的健壮性验收条（C）

凡读取任务库、报告或其他落盘记录的改动，合同须含一条健壮性验收：对类型
错误、缺键、不可读、嵌套过深等异常形状，返回 `unknown` 或明确错误码，
不得抛出未捕获异常。验收须实际覆盖这些失败路径并保留命令与输出，不能只凭
正常记录的成功读取判定通过。

## 并行派工与共用件归属（D）

owned paths 互不相交的任务，各用自己的工作树并发派工；同一工作树同一时间
只能有一个在途任务。协调者先核对所有任务的 owned paths 再派出独立任务。

共用件 `src/managing_long_task_context/__init__.py`、`pyproject.toml`、
`skill-package.json`、`tests/test_distribution.py` 以及 `skills/` 镜像，
同一轮只许一条线改。版本号与镜像同步由协调者在集成时统一做，避免并行分支
各自改写共用件；执行者不得因 owned paths 扩大而越过封印 scope。

## 验收深度与集成复跑（E）

执行者跑仓库全量（两个要求的解释器）与包内测试，并保留每次检查的实际输出。
审核者跑与改动相关的定向测试，并在 `python3` 上抽查一次仓库全量；
双解释器与包矩阵交给 CI。审核者仍须从原始合同、代码和输出核对执行者主张，
抽查不免除合同明确要求的检查。

协调者在集成提交上复跑合同命令，生成该提交的验收证据；CI 全绿才合并。
执行者自检、审核者报告、协调者复跑和 CI 结果分别记录，未运行的检查不得记为通过。

## 派工等待防休眠（G）

协调者等待派工结果时，用 `caffeinate -i` 包住等待命令，例如：

```sh
caffeinate -i orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
```

防休眠只持续到被包住的等待命令结束，等待结束即解除，不启动脱离等待命令的
常驻防休眠进程。等待结果仍按 Orca 的派工状态和消息处理规则判断。
