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

Generate the spec from the sealed contract with `scripts/dispatch_spec.py`;
add only role-whitelisted context and the live Orca preamble:

Before dispatching, check the coordinator lease with `scripts/coordinator_ops.py lease status --store <absolute-context-store>` and acquire or renew it with `lease acquire`; a foreign holder, including another terminal in the same session, requires an explicit recorded `lease takeover --reason` after expiration or with `--david-instruction "<David's exact words>"`.

```sh
python3 scripts/dispatch_spec.py --store /absolute/project/.prime/context --task-id TASK-001 --coordinator-workspace /absolute/project --package-root /absolute/pinned-package --role executor --expected-manifest <retained-manifest-sha256> --baseline-commit <baseline-commit> --owned-paths references/orca.md
```

The generated dispatch spec is self-contained and contains:

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

Only the coordinator uses `scripts/coordinator_ops.py ingest` after checking the
report against originals. It deduplicates the main `report-ingest` observation by
`orca_dispatch_id`, then appends each deferred suggestion in report order with its
`report_item` sequence number. A repeat invocation writes only missing items:

Use each subcommand’s `--help` for its required arguments.

After resolving report blockers, use `scripts/coordinator_ops.py settle` to clear
only blocking `report-ingest` metadata and record `resolved_by`; this does not
clear other blockers or prove acceptance. Record completed work, evidence, blockers
and the next action with `scripts/coordinator_ops.py checkpoint`:


When a review report covers multiple tasks, record each suggestion under the
`task_id` marked for that entry in the report. If an entry has no `task_id`, record
it under the coordinator's current task and add `{"report_task_unspecified": true}`
to its metadata.

Pass condition: each dispatch id has exactly one main item, and its number of
suggestion items equals the number in the report.

Re-check every load-bearing claim in a report against originals (Git state, test logs,
the output files) before relying on it, then run the completion gate.

## Coordinator takeover

Before rebinding the Run or writing the task store, check `scripts/coordinator_ops.py lease status --store <absolute-context-store>` and use `lease takeover --reason` only after expiration or with `--david-instruction "<David's exact words>"`, retaining the append-only coordinator takeover record.

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
   the sealed commands in the coordinator workspace and retain each check's
   `<name>.log` and `<name>.exit` under that workspace; a worker report is only
   a review lead. Before `accept`, satisfy section E’s final-commit and upstream checks.
2. Use `scripts/coordinator_ops.py accept` in that workspace with the pinned
   package, each sealed command's retained log, `recorded_by`, and repeated
   `--watched-path` values from the dispatch's `owned_paths`. Natural-language
   scope text is not a path list. The tool builds the host-bound handlers,
   writes a fresh report with output hashes, calls `record_acceptance`, and
   records an acceptance checkpoint. It consumes prior outputs; it does not
   run the commands or push the branch:

   Repeat `--check 'name=command'` for every sealed command and pass its exact
   text. Completion runs inside the recorder before its writer lock, then it
   checks contract, ledger, HEAD, dirty state and watched content again;
   `RECORD_RACE` or `EVIDENCE_CHANGED` means no record was appended.
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

见 [统一封印前检查](preseal-checks.md)。

## 读盘功能的健壮性验收条（C）

见 [统一封印前检查](preseal-checks.md)。

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

合同中相对基线的范围检查命令，须在执行者工作树的最终提交上复跑并保留输出；
集成工作树的差异不能代替这项检查。协调者在集成提交上复跑合同命令，生成
该提交的验收证据；运行 `scripts/coordinator_ops.py accept` 前，该分支须已
推送并设置上游（upstream），推送遵循适用授权；CI 全绿才合并。
执行者自检、审核者报告、协调者复跑和 CI 结果分别记录，未运行的检查不得记为通过。

## 派工等待防休眠（G）

派工与等待须接电源、不合盖。`caffeinate -i -s` 中，`-s` 只在接交流电时
有效，`-i` 只防空闲休眠；二者都挡不住合盖与低电量休眠。

派工前用 `scripts/orca_wait.py power-check` 检查电源；处理完本批消息后，
用 `scripts/orca_wait.py` 把确认与等待放在一次调用中（不带 `--types`）：

```sh
python3 scripts/orca_wait.py power-check
python3 scripts/orca_wait.py --orca <orca> --run <run-id> --ack <delivery> --timeout-ms 900000 --max-minutes 60 --log /absolute/retained/orca-wait.jsonl
```

`<delivery>` 必须来自当前会话本次 `check` 返回的 delivery id。脚本调用一次
`check --ack <delivery> --wait`，不按类型过滤，并自动在下一次等待中确认仅含
心跳或状态的批次；有可操作消息时输出完整批次，协调者处理后再传入本次 id。
确认与等待分两次调用或带 `--types` 时，心跳与状态消息可能被注入输入框。
脚本负责电源检查、有界重试和随等待结束退出的 `caffeinate`，读回消息后仍须
按实际派工状态处理；防休眠不启动脱离等待命令的常驻进程。

## David 授权与阻塞提醒（H）

David 点选授权、项目常设授权及其字段、原件与封印核对规则，统一见 [封印前检查](preseal-checks.md#授权前置与封印读回)。

流水线因待答问题、登录失效、usage limit 或需人按键而阻塞，协调者按全局
规则「阻塞提醒」在停下前向 David 手机推送项目、任务号和需要他做的事；
同一原因只推一次，宿主已自动推送的待答卡片不重复推。工具不可用或手机未
连接时不假装已推，回复首行写 `推送：UNKNOWN（原因）`。遇到 usage limit
立即停止、不重试，并按全局用量纪律首行报告。
