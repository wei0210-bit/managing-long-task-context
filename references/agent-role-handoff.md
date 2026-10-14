# Shared ledger information

Orca owns role assignment, session transfer, dispatch, waiting, execution and review.
Carry an absolute task-store or `task-contract.json` path so every participant reads the
same original agreement. Include task id, original evidence/report pointers, current
checkpoint and next action when available. The sealed contract is a record of the
agreement; its acceptance criteria are read verbatim rather than reconstructed from chat.

`brief` and `brief_diagnostics` summarize that ledger, including omissions, stale facts
and uncertainty. These reports impose no execution or session-transfer conditions.
Record results with their sources and timestamps; distinguish observed results from
claims and unverified assumptions. A worker report records its command logs and outcomes;
Orca handles its lifecycle messages. Strict does not rerun acceptance commands.
