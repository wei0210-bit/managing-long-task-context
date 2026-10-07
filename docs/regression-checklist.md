# Regression checklist

## Rule: append only (只增不删)

- Entries are never deleted, weakened, or rewritten to make a failing result pass.
- Each fix round adds its own entries at the end, with the next free ID and the issue
  that introduced them. An obsolete entry stays and is marked `Retired (#issue, reason)`;
  retiring one needs the same approval as relaxing a quality bar.
- Every entry has a command or walkthrough step and an explicit pass criterion.
- Run every non-retired entry from the repository root. A round passes only when all of
  them pass; report each entry's result separately.

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

Pass: after the round's commit, the command prints nothing. Untracked design artifacts
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
