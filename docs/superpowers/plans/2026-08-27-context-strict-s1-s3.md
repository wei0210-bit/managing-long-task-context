# Context Strict S1-S3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the three approved Strict correctness defects around conflict preservation, controlled Markdown handoffs, and deterministic brief selection.

**Architecture:** Keep the existing standard-library event ledger and public import path. Add small pure helpers for Markdown serialization and priority selection inside the current module; each behavior is introduced through a failing public-API test before production code changes.

**Tech Stack:** Python 3.10+, Python standard library, `unittest`.

**Spec:** `docs/specs/context-skills-v1.1.md`

## Global Constraints

- `context-strict` remains independent from `context-lite`; this plan changes only the existing Strict implementation and tests.
- No production code may be written before the assigned test has been run and observed failing for the expected behavior.
- Keep `managing_long_task_context` as the import path and keep all nine baseline tests green.
- Use only the Python standard library; do not add package dependencies.
- A task dispatch must contain scope, owned files, deliverables, acceptance criteria, failure conditions, exact verification commands, and required evidence before work starts.
- Agent reports, runtime messages, and a green command from another agent are not controller verification; the controller inspects the diff and runs fresh verification before accepting each task.
- Do not push, merge, publish, or change GitHub issues from an implementer task.

---

### Task 1: Preserve explicit conflicted status

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:543`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: existing `update_item(task_id, item_id, *, actor, status, conflicts_with, conflict_reason, base_dir)`.
- Produces: the same public signature; verified facts retain an explicit `conflicted` status while still receiving `verified_at` when updated.

- [ ] **Step 1: Write the failing regression test**

Add this method to `ContextSkillTests`:

```python
def test_verified_fact_update_preserves_explicit_conflicted_status(self) -> None:
    self.publish()
    fact = context.record(
        "TASK-001",
        statement="Callback writes exactly once",
        item_type="verified-fact",
        actor="validator-01",
        source={"kind": "test-report", "ref": "artifacts/run-018.json"},
        evidence=["artifacts/run-018.json"],
        verification_method="integration test inspection",
        scope={"module": "payment-callback"},
        base_dir=self.base,
    )

    conflicted = context.update_item(
        "TASK-001",
        fact["id"],
        actor="validator-02",
        status="conflicted",
        conflicts_with=["EV-019"],
        conflict_reason="A second report observed two writes",
        base_dir=self.base,
    )

    self.assertEqual(conflicted["status"], "conflicted")
    self.assertEqual(conflicted["conflicts_with"], ["EV-019"])
    self.assertEqual(conflicted["conflict_reason"], "A second report observed two writes")
    self.assertIsNotNone(conflicted["verified_at"])
```

- [ ] **Step 2: Run the new test and capture RED evidence**

Run:

```bash
python3 -m unittest tests.test_context.ContextSkillTests.test_verified_fact_update_preserves_explicit_conflicted_status -v
```

Expected: FAIL because the returned status is `active`, proving the verified-fact normalization overwrites the explicit conflict.

- [ ] **Step 3: Implement the minimal state precedence fix**

Change the verified-fact normalization in `update_item` to preserve both terminal and control states:

```python
if updated.get("type") == "verified-fact":
    if updated.get("status") not in {"conflicted", "superseded"}:
        updated["status"] = "active"
    updated["verified_at"] = now
```

Do not change any other transition semantics in this task.

- [ ] **Step 4: Run focused and full GREEN verification**

Run:

```bash
python3 -m unittest tests.test_context.ContextSkillTests.test_verified_fact_update_preserves_explicit_conflicted_status -v
python3 -m unittest discover -s tests -v
```

Expected: focused test PASS; full suite reports 10 tests and 0 failures.

- [ ] **Step 5: Self-review and commit**

Inspect `git diff --check` and confirm production changes are limited to the status-precedence branch.

```bash
git add tests/test_context.py src/managing_long_task_context/__init__.py
git commit -m "fix: preserve explicit context conflicts"
```

Required report evidence: RED command and failure reason, GREEN commands and test counts, commit SHA, changed-file list, and any concern.

---

### Task 2: Preserve control fields in Markdown briefs

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:722`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: packet dictionaries produced by `brief()`.
- Produces: `_brief_item_to_markdown(item: Mapping[str, Any]) -> str`; `_brief_to_markdown()` renders contract scope and every context item's status, source, evidence, scope, verification time, and update time.

- [ ] **Step 1: Write the failing public-output tests**

Add these methods to `ContextSkillTests`:

```python
def test_markdown_brief_keeps_item_control_fields(self) -> None:
    self.publish()
    fact = context.record(
        "TASK-001",
        statement="Unique index exists",
        item_type="verified-fact",
        actor="validator-01",
        source={"kind": "tool", "ref": "schema-query-02"},
        evidence=["db:schema-query-02"],
        verification_method="direct schema inspection",
        scope={"database": "payments"},
        base_dir=self.base,
    )

    prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

    self.assertIn(f"- {fact['id']}: Unique index exists", prompt)
    self.assertIn("status=active", prompt)
    self.assertIn('source={"kind":"tool","ref":"schema-query-02"}', prompt)
    self.assertIn('evidence=["db:schema-query-02"]', prompt)
    self.assertIn('scope={"database":"payments"}', prompt)
    self.assertIn(f"verified_at={fact['verified_at']}", prompt)
    self.assertIn(f"updated_at={fact['updated_at']}", prompt)

def test_markdown_brief_keeps_contract_scope_and_constraints(self) -> None:
    self.publish()

    prompt = context.brief("TASK-001", base_dir=self.base)["prompt"]

    self.assertIn("## Scope", prompt)
    self.assertIn("- payment callback", prompt)
    self.assertIn("## Out of Scope", prompt)
    self.assertIn("## Constraints", prompt)
    self.assertIn("- keep public API", prompt)
```

- [ ] **Step 2: Run both tests and capture RED evidence**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_markdown_brief_keeps_item_control_fields \
  tests.test_context.ContextSkillTests.test_markdown_brief_keeps_contract_scope_and_constraints -v
```

Expected: FAIL because the current prompt renders only item ID and statement and omits the three contract control sections.

- [ ] **Step 3: Add deterministic compact serialization**

Add the helper immediately before `_brief_to_markdown`:

```python
def _brief_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _brief_item_to_markdown(item: Mapping[str, Any]) -> str:
    statement = item.get("criterion") or item.get("statement") or _brief_json(dict(item))
    fields = (
        f"status={item.get('status')}",
        f"source={_brief_json(item.get('source'))}",
        f"evidence={_brief_json(item.get('evidence') or [])}",
        f"scope={_brief_json(item.get('scope') or {})}",
        f"verified_at={item.get('verified_at')}",
        f"updated_at={item.get('updated_at')}",
    )
    return f"- {item.get('id', '')}: {statement} | " + " | ".join(fields)
```

Use `_brief_item_to_markdown` for dictionary context items. Before `Acceptance Criteria`, render `Scope`, `Out of Scope`, and `Constraints` from the packet with `- None` for empty lists. Acceptance criteria remain human-readable and are not passed through the context-item serializer.

- [ ] **Step 4: Run focused and full GREEN verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_markdown_brief_keeps_item_control_fields \
  tests.test_context.ContextSkillTests.test_markdown_brief_keeps_contract_scope_and_constraints -v
python3 -m unittest discover -s tests -v
```

Expected: both focused tests PASS; full suite reports 12 tests and 0 failures.

- [ ] **Step 5: Self-review and commit**

Confirm JSON fragments use compact sorted-key serialization and that no item source, evidence, scope, or timestamps are fabricated.

```bash
git add tests/test_context.py src/managing_long_task_context/__init__.py
git commit -m "fix: retain controls in handoff briefs"
```

Required report evidence: RED failures, GREEN commands and counts, one sample rendered item line, commit SHA, changed-file list, and concerns.

---

### Task 3: Select brief items by deterministic character budget

**Files:**
- Modify: `src/managing_long_task_context/__init__.py:654-720`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: context items with optional `metadata.required`, `metadata.blocker`, and `metadata.severity` fields.
- Produces: `brief(..., max_items: int | None = None, max_chars: int = 8000)`; compatibility callers may still pass `max_items`, but default selection is governed by `max_chars`.
- Produces private helpers `_brief_priority(item)`, `_brief_sort_key(item)`, and `_select_brief_items(items, *, max_chars, max_items)`.

- [ ] **Step 1: Write failing behavior tests**

Add these methods to `ContextSkillTests`:

```python
def test_brief_budget_prefers_required_conflict_and_decision(self) -> None:
    self.publish()
    assumption = context.record(
        "TASK-001",
        statement="A" * 900,
        item_type="assumption",
        actor="executor",
        source={"kind": "agent-inference", "ref": "review-01"},
        base_dir=self.base,
    )
    decision = context.record(
        "TASK-001",
        statement="D" * 900,
        item_type="decision",
        actor="publisher",
        source={"kind": "task-contract", "ref": "decision-01"},
        metadata={"severity": "high"},
        base_dir=self.base,
    )
    required = context.record(
        "TASK-001",
        statement="R" * 900,
        item_type="observation",
        actor="executor",
        source={"kind": "tool", "ref": "probe-01"},
        metadata={"required": True, "severity": "critical"},
        base_dir=self.base,
    )
    conflict_candidate = context.record(
        "TASK-001",
        statement="C" * 900,
        item_type="observation",
        actor="executor",
        source={"kind": "tool", "ref": "probe-02"},
        base_dir=self.base,
    )
    conflicted = context.update_item(
        "TASK-001",
        conflict_candidate["id"],
        actor="validator-01",
        status="conflicted",
        conflicts_with=[required["id"]],
        conflict_reason="Probe results disagree",
        base_dir=self.base,
    )

    packet = context.brief("TASK-001", max_chars=5000, base_dir=self.base)
    selected_ids = {
        item["id"]
        for key in ("facts", "observations", "assumptions", "decisions", "questions")
        for item in packet[key]
    }

    self.assertIn(required["id"], selected_ids)
    self.assertIn(conflicted["id"], selected_ids)
    self.assertIn(decision["id"], selected_ids)
    self.assertNotIn(assumption["id"], selected_ids)
    self.assertLessEqual(len(packet["prompt"]), 5000)

def test_brief_rejects_required_items_that_exceed_budget(self) -> None:
    self.publish()
    context.record(
        "TASK-001",
        statement="R" * 9000,
        item_type="observation",
        actor="executor",
        source={"kind": "tool", "ref": "probe-oversized"},
        metadata={"required": True},
        base_dir=self.base,
    )

    with self.assertRaisesRegex(context.ContextError, "BRIEF_REQUIRED_OVERFLOW"):
        context.brief("TASK-001", max_chars=8000, base_dir=self.base)

def test_brief_rejects_non_positive_character_budget(self) -> None:
    self.publish()
    with self.assertRaisesRegex(ValueError, "max_chars must be positive"):
        context.brief("TASK-001", max_chars=0, base_dir=self.base)
```

- [ ] **Step 2: Run the three tests and capture RED evidence**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_brief_budget_prefers_required_conflict_and_decision \
  tests.test_context.ContextSkillTests.test_brief_rejects_required_items_that_exceed_budget \
  tests.test_context.ContextSkillTests.test_brief_rejects_non_positive_character_budget -v
```

Expected: ERROR because `brief()` does not accept `max_chars`; this is the missing public behavior, not an import or fixture error.

- [ ] **Step 3: Implement deterministic ranking and budgeting**

Use these exact priority ranks:

```python
_BRIEF_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _brief_priority(item: Mapping[str, Any]) -> int:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if metadata.get("required") is True:
        return 0
    if item.get("status") == "conflicted":
        return 1
    if metadata.get("blocker") is True:
        return 2
    return {
        "decision": 3,
        "verified-fact": 4,
        "assumption": 5,
        "observation": 6,
        "question": 7,
    }.get(str(item.get("type")), 8)
```

Within one rank sort by severity, then parsed `updated_at` descending, then item ID ascending. Missing or invalid timestamps sort last. Build candidates in that order, render the whole candidate packet through `_brief_to_markdown`, and accept a candidate only when the resulting prompt stays within `max_chars`. Required and conflicted candidates are mandatory: if the packet containing all mandatory candidates exceeds the budget, raise `ContextError` with code `BRIEF_REQUIRED_OVERFLOW` and do not return a prompt. Apply a non-`None` `max_items` only as a compatibility cap after ordering; if it would omit a mandatory item, raise the same overflow code.

- [ ] **Step 4: Run focused and full GREEN verification**

Run:

```bash
python3 -m unittest \
  tests.test_context.ContextSkillTests.test_brief_budget_prefers_required_conflict_and_decision \
  tests.test_context.ContextSkillTests.test_brief_rejects_required_items_that_exceed_budget \
  tests.test_context.ContextSkillTests.test_brief_rejects_non_positive_character_budget -v
python3 -m unittest discover -s tests -v
```

Expected: all three focused tests PASS; full suite reports 15 tests and 0 failures; every returned prompt has `len(prompt) <= max_chars`.

- [ ] **Step 5: Self-review and commit**

Check the mutation cases: swapping decision and assumption ranks must fail the budget test; allowing required truncation must fail the overflow test; removing the positive-budget validation must fail its test.

```bash
git add tests/test_context.py src/managing_long_task_context/__init__.py
git commit -m "feat: budget strict context briefs"
```

Required report evidence: RED output, GREEN commands and counts, prompt length from the budget fixture, selected item IDs, commit SHA, changed-file list, and concerns.
