## Agent skills

### Issue tracker

Issues and specs are tracked in the private GitHub repository `wei0210-bit/managing-long-task-context`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels without aliases. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository using root `CONTEXT.md`. See `docs/agents/domain.md`.

### Task delegation and verification

Every delegated task must define its scope, owned files, expected deliverables, acceptance criteria, failure conditions, verification commands, and required evidence before implementation begins.

An agent must not claim completion unless it has run the assigned verification or explicitly reported why verification could not run. Runtime messages and self-reported completion are not verification evidence.

### Context management skills

When work spans sessions, involves multiple agents, or is handed off, read `skills/context-strict/SKILL.md` and follow it. For low-risk, multi-turn work by a single primary agent, read `skills/context-lite/SKILL.md` instead. These paths in this repository are the maintained source; do not copy the skill text into this file. When coordinating work in Orca, also read `skills/context-strict/references/orca.md`.
