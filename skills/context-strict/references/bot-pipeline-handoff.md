# Multi-bot / assistant pipeline handoff

## Why

Multiple bots do not share one chat transcript. Without a shared sealed store, each
stage retells goals and acceptance criteria and silently drifts. Context Strict's
`.prime/context/<task-id>/` pack is the shared truth.

## Rule

1. Publisher (often plan / controller) creates or points to
   `<project>/.prime/context/<task-id>/` with a sealed `task-contract.json` (or the
   package's contract filename).
2. Every handoff message to another bot includes the **absolute** task-dir path and/or
   contract path.
3. Downstream reads the contract first, then acts (implement or review).
4. Reviewers judge primarily against the sealed acceptance / verification criteria.
5. Missing path or unreadable/unsealed contract → stop; feedback the upstream bot.

## Example path shapes

- `/Users/you/proj/.prime/context/NPI-PHASE1-01/`
- `/Users/you/proj/.prime/context/NPI-PHASE1-01/task-contract.json`

## Out of scope

This reference does not replace `brief()`, `gate()`, or `short-session-handoff/v1`.
It defines the minimum message-level requirement so Strict remains meaningful across
bots that only communicate by handoff packs.
