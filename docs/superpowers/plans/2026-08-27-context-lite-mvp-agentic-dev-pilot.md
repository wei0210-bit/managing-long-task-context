# Context Lite MVP and Agentic-Dev Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone, Markdown-first `context-lite` skill and prove in a real Agentic-Dev recovery task that a fresh session can recover the current state and avoid re-running completed work.

**Architecture:** Keep `context-lite` independent from the existing Python-backed Strict implementation. The production artifact is prose plus one fixed `NOW.md` template under `skills/context-lite/`; deterministic contract tests protect the documented action semantics, while a read-only Agentic-Dev pilot supplies behavioral evidence from a fresh-context resume. Pilot state lives only in this repository's ignored `.context-lite/` runtime directory, and Agentic-Dev is observed but never modified.

**Tech Stack:** Markdown, Python 3.10+ standard-library `unittest` for contract tests, Git and POSIX shell commands for read-only pilot observations.

**Spec:** `docs/specs/context-skills-v1.1.md`

## Global Constraints

- `context-lite` is a separate manually selected skill; do not add an automatic router or a runtime dependency on `managing_long_task_context`.
- The regular path uses Markdown and live project observations only; it does not require a Python package, database, event ledger, queue, or Agent runtime checkpoint.
- Expose exactly four user actions: `start`, `checkpoint`, `resume`, and `finish`.
- Task IDs must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and must reject path separators and `..`.
- `NOW.md` limits are exactly 80 lines, 8000 Unicode characters, 500 characters per line, and at most three `Next` entries with one explicitly marked first action.
- `checkpoint` must normalize relative time to UTC RFC3339, replace deictic references with stable locators, validate before replacing, and atomically rename a same-directory temporary file over `NOW.md`.
- `resume` refreshes each mutable `STATE-*` and each `RUN-*` only from its own stable read-only reference; failed or ambiguous refresh becomes `unknown` and never authorizes an automatic retry.
- `finish` defaults to archive. Deletion is available only after an explicit user choice and a second confirmation that names the exact task directory.
- Do not implement `context-transfer/v1`, Strict handoff, concurrency, repair, migration, network access, long-term memory, or automatic Lite/Strict selection in this plan.
- The pilot may read `/Users/zhaowei/Desktop/David/project/Agentic-Dev` but must not write there or invoke tests, builds, deployments, dispatchers, session export, cleanup, network tools, or external systems.
- Pilot state is stored below this worktree's ignored `.context-lite/`; the committed pilot report must contain no credentials, machine secrets, raw long logs, or inferred session IDs.
- Work only in `/Users/zhaowei/Desktop/David/project/managing-long-task-context/.worktrees/context-lite-mvp` on `codex/context-lite-mvp`; do not merge, push, or modify `main`.

## File Structure

- `skills/context-lite/SKILL.md`: standalone agent workflow, safety boundaries, exact action protocols, validation rules, and user-facing outcomes.
- `skills/context-lite/assets/NOW.template.md`: the only persistent active-state template; short fixed headings and stable `STATE-*` / `RUN-*` examples.
- `README.md`: 30-second manual Lite-versus-Strict selection and local installation/use paths.
- `tests/test_context_lite_skill.py`: executable contract tests for metadata, action count, hard limits, refresh/retry boundaries, template shape, and README selection guidance.
- `tests/test_context_lite_pilot_report.py`: executable evidence-shape checks for the real-task report.
- `docs/validation/2026-08-27-context-lite-agentic-dev-r56-pilot.md`: concise pilot record with exact read-only commands, observed results, fresh-resume verdict, measurements, and safety accounting.

---

### Task 1: Build the standalone Context Lite skill

**Files:**
- Create: `skills/context-lite/SKILL.md`
- Create: `skills/context-lite/assets/NOW.template.md`
- Create: `README.md`
- Create: `tests/test_context_lite_skill.py`

**Interfaces:**
- Consumes: the Lite workflow and success criteria in `docs/specs/context-skills-v1.1.md`.
- Produces: a copyable `skills/context-lite/` directory whose frontmatter name is `context-lite`; action sections named exactly `start`, `checkpoint`, `resume`, and `finish`; a fixed `NOW.md` template; a manual selection table in `README.md`.
- Preserves: the existing root `SKILL.md`, Python import package, Strict tests, and all Strict runtime behavior.

**Acceptance criteria:**

- The skill frontmatter has `name: context-lite` and a description that clearly says it is for one primary Agent, multi-turn or cross-day work, and low-risk recovery rather than audit.
- A user can identify the four actions and their success/failure outcomes without reading the design spec.
- Repeating `start` with the same task ID and same goal returns the existing task without overwriting it; a different goal fails and asks for a new task ID.
- `checkpoint` names validation-before-replace and same-directory atomic rename; failure preserves the old `NOW.md` and temporary files are not valid resume state.
- Over-limit handling reports the exact offending limit and offers exactly these deterministic remedies: external artifact plus reference, remove resolved state, or split the task ID. It never truncates Acceptance, Blockers, or the unique first action.
- `resume` treats stored state as a lead, refreshes mutable states and in-flight actions independently, records `unknown` on ambiguity, and does not continue a prior turn or automatically retry.
- `finish` archives by default and requires explicit choice plus exact-target confirmation before deletion.
- The template headings are ordered exactly: Acceptance, Current State, Decisions, In Flight, Blockers, Next, Refresh On Resume.
- `README.md` lets a user choose Lite versus Strict in under 30 seconds and points to both the standalone Lite directory and the existing Strict root skill.
- All pre-existing 102 tests remain green.

**Failure conditions:**

- The implementation imports the Strict Python package, introduces an event ledger/database, or adds a fifth public action.
- The skill implies that `resume` restores hidden reasoning, messages, credentials, tool processes, network connections, or executor state.
- Any `RUN-*` reference can update a different run, or an ambiguous status remains `pending`/`running` instead of becoming `unknown`.
- `checkpoint` silently truncates content, overwrites a valid record before validation, or accepts relative dates/deictic references as stable context.
- The template includes chat history, long-log sections, automatic memory, or more than three example `Next` entries.
- Tests only search for the word “resume” without checking the safety semantics and fixed numeric limits.
- Root Strict files are renamed, moved, or behaviorally modified.

- [ ] **Step 1: Add RED contract tests**

Create `tests/test_context_lite_skill.py` with these exact helpers and test cases:

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills" / "context-lite" / "SKILL.md"
TEMPLATE_PATH = ROOT / "skills" / "context-lite" / "assets" / "NOW.template.md"
README_PATH = ROOT / "README.md"


def section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^##+ {re.escape(heading)}\s*$\n(.*?)(?=^##+ |\Z)",
        markdown,
    )
    if match is None:
        raise AssertionError(f"missing section: {heading}")
    return match.group(1)


class ContextLiteSkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.template = TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_metadata_names_a_low_risk_single_agent_skill(self):
        self.assertRegex(self.skill, r"(?m)^name: context-lite$")
        description = re.search(r"(?m)^description: (.+)$", self.skill).group(1)
        self.assertIn("single", description.lower())
        self.assertIn("low-risk", description.lower())

    def test_exactly_four_action_sections_exist(self):
        actions = re.findall(r"(?m)^## Action: (start|checkpoint|resume|finish)$", self.skill)
        self.assertEqual(actions, ["start", "checkpoint", "resume", "finish"])

    def test_fixed_limits_and_task_id_pattern_are_machine_readable(self):
        expected = {
            "TASK_ID_PATTERN": r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
            "MAX_LINES": "80",
            "MAX_CHARS": "8000",
            "MAX_LINE_CHARS": "500",
            "MAX_NEXT_ITEMS": "3",
        }
        for key, value in expected.items():
            self.assertIn(f"{key} = {value}", self.skill)

    def test_start_is_idempotent_without_cross_goal_overwrite(self):
        start = section(self.skill, "Action: start")
        for phrase in ("same task ID", "same goal", "return the existing", "different goal", "new task ID"):
            self.assertIn(phrase, start)
        self.assertIn("reject", start)

    def test_checkpoint_is_validate_then_atomic_replace(self):
        checkpoint = section(self.skill, "Action: checkpoint")
        for phrase in ("UTC RFC3339", "stable locator", "same directory", "atomic rename", "preserve the previous NOW.md"):
            self.assertIn(phrase, checkpoint)
        for remedy in ("external artifact", "remove resolved state", "split the task ID"):
            self.assertIn(remedy, checkpoint)
        self.assertIn("must not silently truncate", checkpoint)

    def test_resume_refreshes_independently_and_never_auto_retries(self):
        resume = section(self.skill, "Action: resume")
        for phrase in ("task-level context", "does not resume", "read-only", "matching STATE", "matching RUN", "unknown", "must not automatically retry"):
            self.assertIn(phrase, resume)

    def test_finish_archives_by_default_and_guards_delete(self):
        finish = section(self.skill, "Action: finish")
        for phrase in ("default", "archive", "explicit", "exact task directory", "confirmation", "unrecoverable"):
            self.assertIn(phrase, finish)

    def test_template_has_exact_ordered_sections_and_stable_ids(self):
        headings = re.findall(r"(?m)^## (.+)$", self.template)
        self.assertEqual(headings, [
            "Acceptance", "Current State", "Decisions", "In Flight",
            "Blockers", "Next", "Refresh On Resume",
        ])
        self.assertIn("STATE-01", self.template)
        self.assertIn("RUN-01", self.template)
        self.assertIn("First:", self.template)

    def test_readme_supports_manual_choice_without_router(self):
        for phrase in ("context-lite", "context-strict", "单 Agent", "多 Agent", "手动选择"):
            self.assertIn(phrase, self.readme)
        self.assertNotIn("自动路由", self.readme)
```

- [ ] **Step 2: Run the new tests and confirm the intended RED**

Run:

```bash
python3 -m unittest tests.test_context_lite_skill -v
```

Expected: error or failure because `skills/context-lite/SKILL.md`, `NOW.template.md`, and `README.md` do not exist. A syntax error in the test is not an acceptable RED; fix the test until absence of the production artifacts is the cause.

- [ ] **Step 3: Write the standalone skill**

Create `skills/context-lite/SKILL.md` with:

- YAML frontmatter matching the metadata acceptance criterion.
- A short “Use When / Do Not Use When” decision boundary.
- A machine-readable `Protocol Constants` block containing the five exact constants from the test.
- One section for each exact `## Action: ...` heading, in order.
- Under every action: required observations, validation order, success output, and hard-stop output.
- A “Stable Reference Rules” section that accepts absolute paths, repository plus revision, symbol, issue/PR, URL, tool/job/message ID, and exact read-only commands; it rejects “刚才”“这里”“那个任务” and inferred session IDs.
- A “No Runtime Resurrection” section stating that saved context does not restore hidden reasoning, messages, permissions, credentials, processes, connections, or the former Agent turn.
- A “Response Contract” that always reports task ID, phase, refreshed/unknown counts, blockers, and the single first action.

Use concise imperative prose. Do not copy the full design spec into the skill.

- [ ] **Step 4: Write the fixed NOW template**

Create `skills/context-lite/assets/NOW.template.md` with the exact seven ordered headings and these field shapes:

```markdown
# <task-id>: <goal>

Updated: <UTC RFC3339 timestamp>
Phase: <current phase>

## Acceptance
- <current completion condition>

## Current State
- [STATE-01] <statement> | mutable: true | source: <stable source> | refreshed_at: <UTC RFC3339> | refresh_ref: <read-only observation>

## Decisions
- <decision> | why: <reason> | evidence: <stable reference>

## In Flight
- [RUN-01] <action> | owner: <user/agent> | status: pending/blocked/unknown | started_at: <UTC RFC3339> | correlation_ref: <stable run locator> | recovery_ref: <read-only observation>

## Blockers
- none

## Next
1. First: <the one next action>

## Refresh On Resume
- STATE-01 -> <read-only refresh source>
- RUN-01 -> <read-only recovery source>
```

Explain in an HTML comment that unused `In Flight` is written as `- none`; do not add optional headings.

- [ ] **Step 5: Add the 30-second manual selection README**

Create `README.md` with:

- A two-row table: Lite for one primary Agent and low-risk recovery; Strict for multiple actors, external side effects, frozen acceptance, audit, or evidence-backed completion.
- An explicit sentence that the user manually selects the skill.
- Copy/install examples from `skills/context-lite/` to `~/.agents/skills/context-lite/` and the existing repository root to `~/.agents/skills/context-strict/`, labeled as local installation paths rather than commands executed by tests.
- A link to `docs/specs/context-skills-v1.1.md` and a note that `context-transfer/v1` is not implemented in this MVP.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
python3 -m unittest tests.test_context_lite_skill -v
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: focused contract tests pass; full suite reports 111 tests with zero failures/errors; `git diff --check` is silent.

- [ ] **Step 7: Commit Task 1**

```bash
git add README.md skills/context-lite/SKILL.md skills/context-lite/assets/NOW.template.md tests/test_context_lite_skill.py
git commit -m "feat: add context lite skill"
```

Record the RED and GREEN command outputs in the SDD task report; a self-reported summary without command evidence is insufficient.

---

### Task 2: Prove fresh-session recovery on Agentic-Dev R56

**Files:**
- Create: `tests/test_context_lite_pilot_report.py`
- Create: `docs/validation/2026-08-27-context-lite-agentic-dev-r56-pilot.md`
- Runtime only, ignored and never committed: `.context-lite/ctxlite-pilot-agentic-dev-r56-resume-audit/NOW.md`
- Read only: `/Users/zhaowei/Desktop/David/project/Agentic-Dev/bin/session-orient.sh`
- Read only: `/Users/zhaowei/Desktop/David/project/Agentic-Dev/.scratch/w2r/issues/R56-ticket.md`
- Read only: `/Users/zhaowei/Desktop/David/project/Agentic-Dev/.scratch/w2r/R56-verify-wiring.sh`
- Read only: Agentic-Dev Git commits `9a8e32e` and `cf91814`

**Interfaces:**
- Consumes: Task 1's `context-lite` action protocol and template; Agentic-Dev's live Git/file observations.
- Produces: a real-task pilot report and a fresh-context resume verdict of either `R56 已完成，无恢复动作` or `需人工升级`; no other verdict is allowed.
- Safety boundary: the pilot writes only below this worktree's `.context-lite/` plus the two committed test/report files. Agentic-Dev is read-only.

**Acceptance criteria:**

- The pilot task ID is exactly `ctxlite-pilot-agentic-dev-r56-resume-audit` and the goal is to decide whether R56 needs recovery after an intentional interruption.
- `start` records absolute Agentic-Dev paths and exact read-only commands; it does not use an inferred Codex/Claude session ID.
- Checkpoint 1 records the R56 close decision at `cf91814` and implementation anchor `9a8e32e`, then intentionally stops before the final live-state conclusion.
- A fresh no-history Agent reads only the new Lite skill, `NOW.md`, and listed read-only sources, refreshes the state, and does not inspect the prior conversation or dispatch another Agent.
- If `9a8e32e` is an ancestor of local `HEAD`, `src` and `acceptance` have no later diff relative to that anchor, and the close decision exists, the verdict is `R56 已完成，无恢复动作`; any ambiguous or failed observation becomes `需人工升级` without a retry.
- The pilot records the local branch/tracking state as observed. Being behind `origin/main` is a current-state fact, not evidence that R56 must be rerun.
- The final active `NOW.md` is archived using the skill's default finish path; no delete path is exercised.
- The report records line count, Unicode character count, longest line, number of refreshed states, number of unknown states, and `auto_retry_count=0`.
- Agentic-Dev Git status before and after the pilot is byte-for-byte identical.

**Failure conditions:**

- Any command writes inside Agentic-Dev, fetches from the network, starts a service, runs a build/test, dispatches work, exports sessions, removes worktrees, or touches `.env`, `src`, `acceptance`, hooks, deployment, Feishu, SSH, or GitHub.
- The fresh resume trusts the stored claim without rerunning its exact refresh/recovery references.
- A hand-written `CLAUDE.md` backlog count, tool success line, or inferred session ID is treated as proof that R56 is incomplete or running.
- The new Agent receives the parent conversation via full-history fork.
- The pilot report claims success without exact command outputs or omits unknown/auto-retry accounting.
- Runtime `.context-lite` files are staged or committed.

- [ ] **Step 1: Add a RED pilot-report contract test**

Create `tests/test_context_lite_pilot_report.py`:

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "validation" / "2026-08-27-context-lite-agentic-dev-r56-pilot.md"


class ContextLitePilotReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = REPORT.read_text(encoding="utf-8")

    def test_report_has_required_evidence_sections(self):
        headings = set(re.findall(r"(?m)^## (.+)$", self.report))
        self.assertTrue({
            "Scenario", "Safety Boundary", "Start", "Checkpoint",
            "Fresh Resume", "Finish", "Measurements", "Verdict",
        }.issubset(headings))

    def test_report_binds_the_real_task_and_read_only_sources(self):
        for value in (
            "ctxlite-pilot-agentic-dev-r56-resume-audit",
            "/Users/zhaowei/Desktop/David/project/Agentic-Dev",
            "bin/session-orient.sh", "R56-ticket.md", "R56-verify-wiring.sh",
            "9a8e32e", "cf91814",
        ):
            self.assertIn(value, self.report)
        self.assertIn("Agentic-Dev writes: 0", self.report)

    def test_report_records_limits_refresh_and_no_retry(self):
        for field in (
            "now_lines=", "now_chars=", "longest_line_chars=",
            "refreshed_state_count=", "unknown_state_count=",
        ):
            self.assertRegex(self.report, re.escape(field) + r"\d+")
        self.assertIn("auto_retry_count=0", self.report)

    def test_report_has_only_an_allowed_final_verdict(self):
        allowed = ("R56 已完成，无恢复动作", "需人工升级")
        matches = [value for value in allowed if value in self.report]
        self.assertEqual(len(matches), 1)
```

- [ ] **Step 2: Run the report test and confirm RED**

Run:

```bash
python3 -m unittest tests.test_context_lite_pilot_report -v
```

Expected: error because the pilot report does not exist. Fix test syntax if necessary; do not create a placeholder report to force GREEN.

- [ ] **Step 3: Execute Lite start and checkpoint in ignored runtime state**

Before any write, capture:

```bash
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev status --porcelain=v1 -uall
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev branch --show-current
bash /Users/zhaowei/Desktop/David/project/Agentic-Dev/bin/session-orient.sh
```

Expected current observation: no local file changes, branch `main`, and a live orientation payload. Record the actual tracking state rather than copying an earlier expectation.

Create `.context-lite/ctxlite-pilot-agentic-dev-r56-resume-audit/NOW.md` by filling the fixed template. Use current UTC RFC3339. Acceptance must require a fresh session to determine the R56 verdict solely from listed read-only sources and perform zero retry. Record these stable references:

```text
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev show --no-patch --format='%H%n%s%n%b' cf91814
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev show --stat --oneline 9a8e32e
sed -n '1,260p' /Users/zhaowei/Desktop/David/project/Agentic-Dev/.scratch/w2r/issues/R56-ticket.md
sed -n '1,240p' /Users/zhaowei/Desktop/David/project/Agentic-Dev/.scratch/w2r/R56-verify-wiring.sh
```

For checkpoint, write a same-directory temporary file, validate all limits, then atomically rename it over `NOW.md`. Stop intentionally after recording the close and implementation anchors; do not write the final verdict before the fresh resume.

- [ ] **Step 4: Dispatch one fresh-context resume verifier**

Dispatch with `fork_turns="none"`, a mid-tier model at high reasoning, and this bounded brief:

```text
Read only these inputs: skills/context-lite/SKILL.md, the active pilot NOW.md,
and the read-only Agentic-Dev sources named inside NOW.md. Perform Action: resume.
Do not read the parent conversation, spawn agents, write files, use network,
run tests/builds/services, or retry any operation. Re-run every matching
STATE/RUN refresh_ref. Report goal, phase, refreshed/unknown counts, blockers,
the unique first action, exact commands and compact outputs, and exactly one
verdict: "R56 已完成，无恢复动作" or "需人工升级".
```

The dispatch brief must also include scope, owned files (`none`), deliverable, acceptance criteria, failure conditions, verification commands, and required evidence as required by `CLAUDE.md`.

- [ ] **Step 5: Independently verify the fresh resume**

The controller must re-run:

```bash
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev merge-base --is-ancestor 9a8e32e HEAD
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev diff --name-only 9a8e32e..HEAD -- src acceptance
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev show --no-patch --format='%H%n%s%n%b' cf91814
git -C /Users/zhaowei/Desktop/David/project/Agentic-Dev status --porcelain=v1 -uall
```

Expected for a positive verdict: ancestor exits 0; the scoped diff is empty; the close decision resolves; final status exactly matches the captured pre-pilot status. If any observation differs or is ambiguous, record `需人工升级` and stop without retrying R56.

- [ ] **Step 6: Finish by archive and write the evidence report**

Update `NOW.md` through a validated same-directory temporary file and atomic rename, recording the fresh result and measurements. Then move the task directory to:

```text
.context-lite/archive/ctxlite-pilot-agentic-dev-r56-resume-audit-<UTC-basic-timestamp>/
```

Create `docs/validation/2026-08-27-context-lite-agentic-dev-r56-pilot.md` with the eight required headings. Include compact command outputs, the fresh Agent report, controller cross-check, exact measurements, before/after status digests, `Agentic-Dev writes: 0`, and one allowed verdict. Do not paste full ticket/script contents.

- [ ] **Step 7: Run focused and full verification**

Run:

```bash
python3 -m unittest tests.test_context_lite_pilot_report -v
python3 -m unittest tests.test_context_lite_skill tests.test_context_lite_pilot_report -v
python3 -m unittest discover -s tests -v
git diff --check
git status --short --branch
```

Expected: report test passes; both Lite test modules pass; full suite reports 115 tests with zero failures/errors; `git diff --check` is silent; only Task 2's report/test files are uncommitted and runtime `.context-lite` remains ignored.

- [ ] **Step 8: Commit Task 2**

```bash
git add tests/test_context_lite_pilot_report.py docs/validation/2026-08-27-context-lite-agentic-dev-r56-pilot.md
git commit -m "test: validate context lite recovery"
```

After the commit, run `git status --short --branch` and require a clean branch before task review.

---

## Whole-Plan Review and Verification

- Review each task first for spec compliance, then for code/skill quality. Important or Critical findings return to the original implementer with focused verification.
- Run one final whole-plan review against this plan and `docs/specs/context-skills-v1.1.md`.
- Controller verification commands:

```bash
python3 -m unittest discover -s tests -v
git diff --check main..HEAD
git status --short --branch
```

- Require 115/115 tests, a silent diff check, a clean worktree, a preserved Agentic-Dev status, and no tracked `.context-lite` runtime files.
- Do not merge or push without a separate user integration choice.
