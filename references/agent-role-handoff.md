# Agent role handoff packets

## Why

`bot-pipeline-handoff.md` requires every handoff to carry the task-store path. It does
not say what each role should receive. Without a whitelist, orchestrators tend to pass
full session history or retold acceptance criteria, which is expensive and drifts from
the sealed contract.

This reference defines **what context each role receives**. Who acts when (routing,
repair loops, escalation) belongs to the orchestration skill (for example
`coding-orchestrator`), not to Context Strict.

## Rules

1. Handoff messages carry paths and hashes, never session history or a retelling of the
   acceptance criteria.
2. The receiver reads the original contract first. A missing, unsealed, or
   hash-mismatched contract stops the handoff and returns to the publisher.
3. Any agent's natural-language summary is a lead, not evidence. Load-bearing
   conclusions are re-checked against originals: Git state, test logs, code.

## Role packets (whitelist)

| Role | Receives | Does not receive |
|---|---|---|
| Executor, first round | Contract path and hash, verification script path, project convention paths, pointers to the relevant code | The orchestrator's investigation transcript; other tasks' history |
| Executor, repair round | The same, plus the previous review result path; resumes its own executor session | The reviewer's full reasoning |
| Independent reviewer | Contract, base commit, diff, the orchestrator's own verification log, scope report, previous review result | The executor's session; the executor's self-report is attached only as a lead |
| Orchestrator recovery | Orchestration state file, latest round directory, contract | Any agent's full conversation |

## Long-lived decisions

Record contract revisions with their reason in the orchestration state history. Record
decisions that stay valid beyond the task with `record(item_type="decision")` in the
same task store.

## Coexisting files

Orchestration files (for example `contract.md`, `verify.sh`, `orch-state.json`,
`rounds/`) and Strict files (`task-contract.json`, `events.jsonl`, `snapshot.json`) may
share one `.prime/context/<task-id>/` directory; the names do not collide. When both
are active, the Strict-sealed `task-contract.json` is authoritative and `contract.md`
must match it; say so in the contract.

## Out of scope

This reference does not replace `brief()`, `gate()`, or `short-session-handoff/v1`, and
it does not define routing, retry limits, or escalation.
