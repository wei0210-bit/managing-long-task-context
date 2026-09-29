## Agent skills

### Issue tracker

Issues and specs are tracked in the private GitHub repository `wei0210-bit/managing-long-task-context`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels without aliases. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository using root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

### Task delegation and verification

Every delegated task must define its scope, owned files, expected deliverables, acceptance criteria, failure conditions, verification commands, and required evidence before implementation begins.

An agent must not claim completion unless it has run the assigned verification or explicitly reported why verification could not run. Runtime messages and self-reported completion are not verification evidence.
