# Regression checklist

## Rule: append only (只增不删)

- Entries are never deleted, weakened, or rewritten to make a failing result pass.
- Each fix round adds its own entries at the end, with the next free ID and the issue
  that introduced them. An obsolete entry stays and is marked `Retired (#issue, reason)`;
  retiring one needs the same approval as relaxing a quality bar.
- Every entry has a command or walkthrough step and an explicit pass criterion.
- Run every non-retired entry from the repository root. A round passes only when all of
  them pass; report each entry's result separately.
  Run the checklist with `python3 scripts/regression_checklist.py`.

## Entries

### R-001 `references/orca.md` never settles an Orca Task as accepted

Added: #39. Orca settles a Task as soon as a valid `worker_done` arrives and has no
accepted state.

```sh
grep -n -i -E "settle[^.]*accepted|as accepted|accepted state" \
  references/orca.md skills/context-strict/references/orca.md
```

Pass: no output (exit code 1). Then read every remaining line from
`grep -n -i accepted references/orca.md`; pass only if none of them describes Orca
marking, settling, or storing a Task as accepted.

### R-002 The three "copy acceptance criteria verbatim" rules agree
Retired (#42, superseded by R-008: section renamed)

Added: #39.

Walkthrough:

1. Read item 5 of "Recommended handoff pack" in `SKILL.md`
   (`grep -n -A9 "Recommended handoff pack" SKILL.md`).
2. Read rule 1 under "Rules" in `references/agent-role-handoff.md`.
3. Read the dispatch instructions in `references/orca.md`
   ("Supervised dispatch", coordinator step 3).

Pass: all three say the same thing: the acceptance criteria are copied verbatim from
the sealed contract, together with the contract path and seal digest, and the contract
remains authoritative. Fail if any one of them forbids copying the criteria, allows a
paraphrase or summary, or omits the path or digest.

### R-003 `SKILL.md` deletes no lines relative to `main`

Added: #39.

```sh
git fetch origin main
git diff --numstat origin/main -- SKILL.md
```

Pass: the second column (deleted lines) is `0`, or there is no output.

### R-004 Full test suite passes

Added: #39.

```sh
python3 -m unittest discover -s tests
```

Pass: the run ends with `OK`, and the test count is at least the count recorded by the
previous round (704 at #39).

### R-005 The generated Strict package has no drift
Retired (#52, superseded by R-011: untracked task-store design artifacts cause false failures)

Added: #39.

```sh
python3 scripts/sync_context_strict_skill.py && git status --short
```

Pass: after the round's commit, `git status --short` prints nothing.

### R-006 Worker report directory is ignored by Git

Added: #39.

```sh
git check-ignore -v .context-reports/issue-0/example.json
```

Pass: exit code 0 and the matching rule is `.context-reports/` in `.gitignore`.

### R-007 Entry files point to the maintained root sources

Added: #39.

```sh
grep -n "skills/context-strict/SKILL.md\|skills/context-strict/references/orca.md" CLAUDE.md AGENTS.md
grep -c "repository-root \`SKILL.md\`" CLAUDE.md AGENTS.md
grep -c "repository-root \`references/orca.md\`" CLAUDE.md AGENTS.md
grep -c "generated installable package" CLAUDE.md AGENTS.md
```

Pass: the first command prints nothing (exit code 1), and each of the other three
reports a count of at least 1 for both files.

### R-008 The three "copy acceptance criteria verbatim" rules agree

Added: PILOT-A.

Walkthrough:

1. Read item 5 of "Recommended handoff pack" in `SKILL.md`
   (`grep -n -A9 "Recommended handoff pack" SKILL.md`).
2. Read rule 1 under "Rules" in `references/agent-role-handoff.md`.
3. Read the dispatch instructions in `references/orca.md`
   ("Dispatch spec", item 3).

Pass: all three say the same thing: the acceptance criteria are copied verbatim from
the sealed contract, together with the contract path and seal digest, and the contract
remains authoritative. Fail if any one of them forbids copying the criteria, allows a
paraphrase or summary, or omits the path or digest.

### R-009 `update_item` keeps verification provenance

Added: #43.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_update_item_verified_at
```

Pass: `OK`. The suite asserts that a metadata-only or status-only update of a
`verified-fact` keeps `verified_at` and the item's original `actor`, that only a new
`evidence` or `verification_method` refreshes `verified_at`, and that the `item-updated`
event envelope records the modifier as `actor`.

### R-010 `brief()` renders stale items, omission count, and `blocking` ordering

Added: #44.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_brief_rendering
```

Pass: `OK`. The suite asserts that an expired mutable `verified-fact` appears in a
"needs re-observation" section of the brief markdown, that the number of non-mandatory
items dropped for budget is shown and equals `brief_diagnostics().omitted_ids`, and that
`metadata.blocking` sorts like `metadata.blocker`. Packets with no stale or omitted
items keep their previous shape byte for byte.

### R-011 The generated Strict package has no tracked-file drift

Added: #52.

```sh
python3 scripts/sync_context_strict_skill.py && git status --short --untracked-files=no
```

Pass: after the round's commit, `git status` prints nothing; the sync script's
`Synchronized Context Strict` success message does not count. Untracked design artifacts
`.gitattributes`, `.githooks/`, and `.prime/` do not count.

### R-012 Dispatch spec generator reproduces the sealed contract

Added: #58.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_dispatch_spec
```

Pass: `OK`. The suite asserts that `scripts/dispatch_spec.py` copies every acceptance
criterion byte for byte, attaches the contract path and seal digest, keeps the literal
`<dispatch-id>` and `<worker-workspace-root>` placeholders, and emits a version-proof
command that runs against the given package root.

### R-013 恢复门禁不通过时仍返回 context 且总状态非 pass

Added: #45.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_resume_gate.ResumeGateTests
```

Pass: `OK`.

### R-014 只读入口不写任务库

Added: #45.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_resume_gate.ReadOnlyEntryTests
```

Pass: `OK`.

### R-015 SKILL.md 发布流程含 init-binding

Added: #45 (absorbs #55).

```sh
sed -n '/### 1. Bind storage/,/### 2\./p' SKILL.md | grep -c init-binding
```

Pass: output ≥ 1.

### R-017 合同改版保留旧版全文

Added: #54 (absorbed by #46), approved design section 14.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_contract_history
```

Pass: `OK`.

### R-018 `worker-report` 只依据封印命令与协调者复跑报告

Added: #53 (absorbed by #46), approved design section 14.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_worker_report
```

Pass: `OK`.

### R-019 验收记录不进账本、旧版本可读、对齐不丢记录、不改 `.gitattributes`

Added: #46, approved design section 14.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_acceptance_records.RecordStorageTests
```

Pass: `OK`.

### R-020 「需重新验收」不因无关提交、发布提交、压缩合并而为真

Added: #46, approved design section 14.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_acceptance_records.ReacceptanceTests
```

Pass: `OK`.

### R-021 经验库跨检出可读且误用保护不变

Added: #47, approved design r4.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_experience_cross_checkout
```

Pass: `OK`. Schema 2 publication to a second checkout preserves approval and the
stored-form digest, restores current absolute paths, and checks source drift.
Shared-root forks are admitted; receiver overwrite is a preservation test.

### R-022 旧格式经验库与规则执行行为不变

Added: #47, approved design r4.

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_context_experience_cli tests.test_experience_rule_gate
```

Pass: `OK`. Existing assertions remain unchanged; schema 1 keeps byte-identical
binding/storage, repeated init, and rule execution blocks relative `store_root`.
Schema 2 rejects moved stores, unrelated projects, unavailable identity, and mixed
reference forms without relaxing the previous source validity checks.

### R-023 状态命令第 4 段不把普通条目计为派单跳过

Added: closing validation CLOSE-A (#45 review M-001).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_resume_gate
```

Pass: `OK`. Items whose metadata is a dict without an `orca_dispatch_id` key are not
counted as skipped and leave the dispatch section available; malformed metadata and
invalid dispatch ids are still counted as skipped, and the valid dispatch list is unchanged.

### R-024 publish_contract 只接受正整数 version，已封印的旧合同照常可读

Added: closing validation CLOSE-B (contract v2, David authorized the fixture change on 2026-10-07).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_context tests.test_contract_history tests.test_truth_sources
```

Pass: `OK`. publish_contract rejects string, float, bool, zero and negative versions
and writes nothing; directly sealed legacy contracts with non-integer versions still
load for brief, audit and gate; the fixtures that need such contracts build them by
writing and sealing directly, with every original assertion kept.

### R-025 PERF-04 按相对空载基线判定，过期用例不依赖真实时间

Added: STEP8-TESTFIX (contract v3, David authorized the quality-floor change on 2026-10-07).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_handoff_preflight.PreflightPerformanceTests tests.test_experience_rule_gate
```

Pass: `OK` under both `python3` and `/opt/homebrew/bin/python3.12`. PERF-04 checks the
preflight peak memory against an import-only baseline measured in the same run (delta at
most 32 MiB for small and grown inputs, growth at most 8 MiB); its git-call and CPU
assertions are unchanged. The expired-rule case controls the clock with a mock and does
not sleep.

### R-026 分发测试从 pyproject.toml 读取 Strict 版本号

Added: IMP-B (contract v1, David confirmed the seal on 2026-10-08).

```sh
grep -c '0\.13\.' tests/test_distribution.py; python3 -m unittest tests.test_distribution
```

Pass: the `grep -c` count is `0` (no hard-coded Strict version remains in the file) and the
unittest run is `OK`. The worker-report and acceptance registration tests read the
version from `pyproject.toml`, so a version bump changes only `pyproject.toml`,
`skill-package.json` and their synchronized copies.

### R-027 协调者入账、检查点与验收一条命令且去重

Added: IMP-OPS (contract v1).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_coordinator_ops
```

Pass: `OK`. Running `ingest` twice leaves one main item and exactly the report's number of
deferred items; `checkpoint` without evidence exits 2; `accept` never records `pass`
when a check exits non-zero or the workspace is dirty.

### R-028 Orca 规程含封印前检查与验收深度，审核者说明含验收深度

Added: IMP-DOC (contract v1, David confirmed the seal on 2026-10-08).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_dispatch_spec
grep -c -E '^## .*（[ACDEG]）$' references/orca.md
cmp references/orca.md skills/context-strict/references/orca.md
```

Pass: the unittest run is `OK`, the `grep -c` count is `5` (sections A, C, D, E and G are
present), and `cmp` prints nothing. The reviewer dispatch text states the acceptance depth (targeted tests plus one
sampled `python3` full suite; interpreter and package matrix left to CI), and
`references/orca.md` keeps every pre-existing paragraph while carrying sections A, C, D,
E and G.
Known gap: section A names `scripts/contract_precheck.py`, which is not in this release
(IMP-PRECHECK was parked after its fourth review); until it lands, run the impact check
with `grep -rn` over `tests/` by hand.

### R-029 封印前检查规范是单一来源，健壮性验收为强制项

Added: W1-S (contract v1, coordinator-sealed with DAVID_AUTH lines from 2026-10-08).

```sh
python3 -c "import sys;t=open('references/preseal-checks.md',encoding='utf-8').read();ks=['verify.sh','预审','影响面','解释器','调用方','locale','3.12','task-contract.json','unittest','重入','DAVID_AUTH','STANDING_AUTH','凡读取任务库、报告或其他落盘记录的改动，合同须含一条健壮性验收'];m=[k for k in ks if k not in t];print('missing',m);sys.exit(1 if m else 0)"
for f in references/*.md; do cmp "$f" "skills/context-strict/$f" || exit 1; done
python3 -c "import json,sys;d=json.load(open('docs/agents/standing-authorizations.json',encoding='utf-8'));it={i['id']:i for i in d['items']};sys.exit(0 if {'SA-PUSH-PR','SA-CI-TIMEOUT','SA-THRESHOLD'}<=set(it) and 'main' in it['SA-PUSH-PR']['deny_refs'] and it['SA-CI-TIMEOUT']['max']==20 and it['SA-THRESHOLD']['max_ratio']==1.5 and (d['merge_authorized'] is not True or ('SA-MERGE-PR' in it and '--auto' in it['SA-MERGE-PR']['deny'])) else 1)"
```

Pass: every command exits 0. `references/preseal-checks.md` carries every preseal check, including the mandatory
robustness acceptance for changes that read persisted records (restored after review F-01); every reference file is
mirrored byte for byte; merge is authorized only through SA-MERGE-PR and its gates (David 2026-10-10), and the standing authorizations keep their numeric bounds.

### R-030 Orca 等待脚本一次调用确认并等待，验收的工作区判定与校验器一致

Added: W1-O (contract v2).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_orca_wait tests.test_coordinator_ops
test -f scripts/orca_wait.py && ! grep -n -- '--types' scripts/orca_wait.py
```

Pass: `OK` and no `--types` in the script. `scripts/orca_wait.py` never sends a separate acknowledgement and never filters
by type (the gap that let Orca inject prompts into the coordinator input); `coordinator_ops accept` judges a dirty
workspace with the worker-report verifier's own exclusions.

### R-031 封印前影响面预检脚本按 unittest 真实行为选择与运行测试，日志只写 --out-dir

Added: W1-P1 (contract v2, frozen tests sha256 5767100e…) and W1-P2 (contract v3).

```sh
test "$(shasum -a 256 tests/test_contract_precheck.py | cut -d' ' -f1)" = 5767100e9ec84e84cbf7d69949f89a1b1bb59e94dddaee5686b66254d4d55a0a
PYTHONPATH=src:tests python3 -m unittest tests.test_contract_precheck tests.test_contract_precheck_outdir
PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest tests.test_contract_precheck tests.test_contract_precheck_outdir
```

Pass: the frozen acceptance tests are byte-identical and both modules are `OK` on both interpreters (at most one skip,
prefixed `ENV-SKIP:`). `scripts/contract_precheck.py` selects and runs tests the way `python3 -m unittest discover -s
tests` loads them (F-01..F-06, P-07..P-12), fails closed with one stderr line, and refuses a symbolic link, dangling link,
directory or hard link named like a log file inside `--out-dir` before any test runs (R-P2-01).

### R-032 授权与封印前检查只有一处原文，协调者工具随 Strict 包分发，回归清单只增不删有守卫

Added: W2-A (contract v2).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_regression_checklist_guard
! grep -q 'orca.md#david' references/preseal-checks.md && grep -q 'preseal-checks.md' references/orca.md
for f in contract_precheck coordinator_ops orca_wait context_skill_router; do test -f "skills/context-strict/scripts/$f.py" || exit 1; done
```

Pass: the guard test is `OK`; `preseal-checks.md` holds the only original text of `DAVID_AUTH`/`STANDING_AUTH` and does not
link back to `orca.md`, which points to it; the four coordinator scripts are in the generated Strict copy. The guard keeps every
id that existed at 3a7acba (R-016 is a historical gap; R-002 and R-008 are walkthrough entries without `sh` blocks) and requires
new ids to continue from R-032 with an `sh` block.

### R-033 本项目常设授权清单的合并条目带质量门槛，自动合并永不授权

Added: W3-SA (David 2026-10-10: 「授权合并 PR、推送默认分支、生产部署、凭据与密钥操作」→ 仅本项目常设，带质量门槛).

```sh
python3 -c "import json,sys;d=json.load(open('docs/agents/standing-authorizations.json',encoding='utf-8'));i={x['id']:x for x in d['items']};m=i['SA-MERGE-PR'];c=' '.join(m['conditions']);p=i['SA-PUSH-DEFAULT'];dp=i['SA-PROD-DEPLOY'];cr=' '.join(i['SA-CREDENTIALS']['conditions']);ok=d['merge_authorized'] is True and any('--match-head-commit' in x for x in m['allow']) and '--auto' in m['deny'] and '--admin' in m['deny'] and all(k in c for k in ('CI 全绿','独立审核','decision=pass','reproducible','回归清单全过','通知','David')) and '直接推送默认分支' in p['deny'] and '强推任何分支' in p['deny'] and dp['applicable'] is False and '预发' in ' '.join(dp['conditions']) and '回滚' in ' '.join(dp['conditions']) and '密钥不出现在输出、日志或提交中' in cr;sys.exit(0 if ok else 1)"
! grep -q '永不含合并' references/preseal-checks.md && grep -q -- '--auto' references/preseal-checks.md
```

Pass: both commands exit 0. The merge entry requires green CI on the PR head, an independent review PASS, a reproducible
pass acceptance record and a passing regression checklist, merges with `--match-head-commit`, and never allows `--auto`,
`--admin` or a direct push to the default branch.


### R-034 一个任务库同一时间只有一个协调者（协调者租约）

Added: W3-LEASE (David 2026-10-10: 一个工作树只有一个协调者；租约 2 小时无心跳过期、无租约时自动取得、只在过期或 David 指示并写记录时接手).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_coordinator_lease && grep -q 'LEASE_TTL_SECONDS = 7200' scripts/coordinator_ops.py && grep -q 'check_coordinator_lease' scripts/dispatch_spec.py && grep -q 'mutate_coordinator_lease' scripts/orca_wait.py
```

Pass: the command exits 0. A second session, or the same session in another terminal, is refused with exit 3 by
`coordinator_ops` write subcommands, `orca_wait` and `dispatch_spec` without writing the task store; an expired lease
changes hands only through `lease takeover --reason`, which appends a takeover record; a malformed lease file fails closed.

### R-035 残留协调者租约锁只在 David 指示下清除，且绝不删除被替换的新锁

Added: W3-FOLLOW (W3-LEASE review finding F01; W3-FOLLOW review finding F01; David 2026-10-10: 「要你把三项都做完（推荐）」).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_coordinator_lease.StaleLockRecoveryTests tests.test_coordinator_lease.StaleLockRaceTests && grep -q 'clear-lock-aborted' scripts/coordinator_ops.py
```

Pass: the command exits 0. `lease clear-lock` needs a reason and David's exact words, refuses a live local holder,
fsyncs an audit row before removing the lock, and when the lock bytes changed after the audit it leaves the newer lock in
place (or keeps a named quarantine file), appends `clear-lock-aborted` and exits 3. No path removes a lock by age or expiry.

### R-036 回归清单执行器逐条判定，前序失败不被后序成功掩盖

Added: W3-FOLLOW (W3-LEASE review deferred item; W3-FOLLOW review finding F02).

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_regression_checklist_runner
```

Pass: `OK`. `scripts/regression_checklist.py` runs ordinary entries with `bash -e`, keeps R-001 as one `bash -c` block,
judges R-007 and R-026 command by command, skips retired entries and reports every entry separately. This entry runs only
the runner's own tests; it must never call the runner on this checklist, which would run this entry again.

### R-037 生成的 Strict 包没有已跟踪文件漂移（按退出码判定）

Added: W3-FOLLOW (R-011 judges drift by reading `git status` output; this entry fails by exit code).

```sh
python3 scripts/sync_context_strict_skill.py >/dev/null && test -z "$(git status --short --untracked-files=no)"
```

Pass: the command exits 0 after the round's commit.
