# Codex CLI transport boundary

`CodexCliHost` is a narrow subprocess transport, not a scheduler, a ledger, or
a completion gate. It accepts only trusted `CodexCliConfig`; requests cannot
choose an executable, model, sandbox, approval setting, working directory, or
extra CLI option.

`start_child` and `resume_child` first request an atomic reservation from the
core-owned `HostTaskLedger`. Only its literal `status=pass`,
`launch_allowed=true`, non-empty reservation ID permits one subprocess. The
ledger repeats trusted host observation before committing the reservation.
The transport's preflight observation is request-bound and fail-closed, but it
does not replace that ledger check.

Commands are argv lists with `shell=False`, `stdin=DEVNULL`, an exact canonical
cwd, explicit `--json`, and `--` before the prompt. Output is bounded while
streaming. The trusted config accepts only the local CLI's supported sandbox
values (`read-only`, `workspace-write`, `danger-full-access`) and approval
policies (`untrusted`, `on-failure`, `on-request`, `never`); it rejects NUL,
non-UTF-8, and unknown values before forming a TOML override. Immediately
before `Popen`, it rechecks the program-prefix and workspace inode captured at
construction, so replacement after reservation leaves the durable reservation
in place but launches nothing.

The core-owned ledger archives UTF-8 stdout plus exit/timeout evidence in an
attempt-specific mode-0600 artifact and keeps only a reference/digests in the
event stream. Non-UTF-8 stdout retains its actual byte digest and size but is
not represented as a readable original; that execution is `unknown`. Stderr
is currently retained as bounded digest/byte metadata only. A stream limit,
timeout, conflicting/malformed thread event, or inherited pipe left open by a
descendant is likewise `execution_unknown`; the transport kills only its direct
child and never treats this as proof that related business work stopped.
Process exit and JSON thread events are observations, never business completion;
persistence uncertainty remains `execution_unknown` and is never retried.

The local fixture proves transport mechanics only. Actual Codex identity,
exclusive control, clean sessions, rollover, parent-exit effects, and business
outcomes remain `NOT_RUN`/`unknown` until a separate real-host validation.
