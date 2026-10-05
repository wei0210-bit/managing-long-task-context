# Orca dispatch and handoff

## Why

Orca records who owns work and when a worker has settled. It does not know the task's
acceptance criteria, and its lifecycle messages do not prove them. Context Strict holds
the sealed contract, facts, and evidence. This reference connects the two at the two
points where work changes hands: a supervised dispatch and an unsupervised handoff.

Orca commands and flags are defined by the Orca binary, not here. Load them with
`orca skills get orchestration` (supervised work) or the `orca-cli` skill (handoffs).

## Boundary

| Question | Authority |
|---|---|
| Which attempt is active, has the worker settled, who owns the terminal | Orca Run / Task / Dispatch |
| Objective, scope, constraints, acceptance criteria | Sealed contract in `.prime/context/<task-id>/` |
| Whether a criterion is met | Strict completion gate over resolved evidence |

Neither side substitutes for the other. An Orca `worker_done` with
`--outcome succeeded` is a lifecycle fact and a lead; it is not acceptance.

## Supervised dispatch (Orca orchestration)

Coordinator, before starting a worker:

1. Publish the contract and pass the release gate. Do not start a worker against an
   unsealed or missing contract.
2. Put the handoff pack from `SKILL.md` ("Recommended handoff pack") in the worker's
   task spec. The absolute path to `.prime/context/<task-id>/` or to the sealed contract
   is mandatory; the worker may run in another worktree or on another host, so a
   relative path is not enough.
3. Carry paths and hashes, not a retelling of the acceptance criteria. Choose what the
   worker receives from the role whitelist in `agent-role-handoff.md`.

Worker, on receiving the dispatch:

1. Open and read the sealed contract before implementing or reviewing.
2. If the path is missing or unreadable, or the contract is unsealed or stale, ask the
   coordinator through the blocking question command in the Orca preamble. Do not
   invent or infer acceptance criteria, and do not report success.
3. When reporting completion, point the report path at the evidence the contract
   requires. The executive summary stays a summary.

Coordinator, on each completion message:

1. Treat the worker's summary and outcome as leads. Re-check load-bearing claims
   against originals: Git state, test logs, the files at the report path.
2. Run the completion gate against the sealed criteria. Settle the Orca Task as accepted
   only after the gate passes; a failed or `unknown` gate is reported as such, whatever
   outcome the worker sent.

## Unsupervised handoff (orca-cli)

A handoff to another agent or worktree creates no Run, Task, or Dispatch, so Orca
reports nothing about completion. The handoff message is the only carrier:

1. It must include the same handoff pack, with the absolute Strict path.
2. Pass the handoff gate and produce a usable `brief()` first when the runtime is
   available.
3. A delivered prompt, a new terminal, or a visible session does not prove the receiver
   read or accepted the work. Under the session-migration rules in `SKILL.md`,
   `control_transfer` stays `unknown` until it is proven by readback, and the source
   session is kept.

## Out of scope

This reference does not define Orca commands, worktree placement, parallel-writer rules,
routing, retries, or escalation, and it does not replace `brief()`, `gate()`, or
`short-session-handoff/v1`. Keep these rules in this package; do not write them into
Orca's own skill directories.
