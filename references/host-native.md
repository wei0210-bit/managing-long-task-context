# Native sub-agent host boundary

`host_codex_native` and `host_claude_native` are read-only capability
inventories.  Their evidence is a fixed 2026-09-15 snapshot of this call
environment only; it is not runtime probing or end-to-end host validation.
They do not start, resume, interrupt, archive, or otherwise control a task.
`request_control()` returns `unknown` for the four named control operations
until a trusted host bridge separately supplies identity, write-fencing,
clean-history, parent-survival, and cross-parent-continuation evidence.
Invalid values are rejected and never interpreted as commands.

The Codex inventory records only the currently exposed collaboration-tool
schema: a child is addressable within its live parent tree, and a fork setting
can request whether surrounding turns are passed.  Neither fact establishes a
clean host session, a trusted identity, exclusive control, or a durable
takeover.  The Claude inventory remains separate: no native Claude sub-agent
interface is exposed here, and it does not reuse CLI or Codex observations.

For manual handoff, retain the current task identity, complete handoff record,
and old session until a successor has independently verified the required
evidence.  Do not archive the only recovery entry or re-dispatch an unknown
in-flight action.  Automatic switching, real-host validation, model execution,
and token-benefit measurement remain `NOT_RUN`/`UNKNOWN`.
