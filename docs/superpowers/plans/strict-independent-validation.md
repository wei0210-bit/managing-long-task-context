# Strict independent-validation local repair

Spec: docs/specs/strict-independent-validation.md (frozen local scope).

## Global Constraints

Effective first; economical and refined. No global install, production state changes,
Git commit/merge/push/deploy, paid model calls, automatic business retries, or subagents
spawned by workers. Keep all previous dirty changes. Use apply_patch for edits.
Only local mechanism verification is in scope; do not claim real host authentication,
model stability, token savings, or natural project reliability. Missing proof blocks.
Independent review and controller integration verification are required; self-report
alone never completes a task.

## Task 1: Independent validation public-boundary repair

Work only in /Users/zhaowei/Desktop/David/project/managing-long-task-context/.scratch/strict-independent-validation-20260911/work.
Read the frozen spec at /Users/zhaowei/Desktop/David/project/managing-long-task-context/docs/specs/strict-independent-validation.md.
Follow /Users/zhaowei/.codex/skills/tdd/SKILL.md and its tests/mocking references.
The public seams publish_contract/bind/gate are the user-approved completion and
contract boundary. Do not test private methods. Implement vertical red -> green slices,
not a mock-only framework. Never dispatch subagents or commit.

Allowed production edits: src/managing_long_task_context/__init__.py; at most one small
focused src/managing_long_task_context/independent_validation.py helper if needed.
Allowed test addition: tests/test_independent_validation.py. Tests may adjust old
independence success expectations in tests/test_context.py to reflect deliberately
stronger behavior, with precise evidence, but never weaken unrelated checks or update
legacy hash gold. Do not touch source distribution, examples, docs or declarations.

Implement the frozen spec IV01-IV22, including all listed variants and dynamic recovery.
Reuse current file/content/freshness/revision checks, bound API and existing role/time
checks. Keep the helper focused; no services, custom crypto, generic policy registry,
new storage log or background engine. Raise NEEDS_CONTEXT before significant interface
deviation; send a concrete smaller alternative if scope proves too large.

Validation before reporting:
- Record failing public-gate baseline tests BEFORE each production repair; preserve RED
  command/output. Model aliases must be demonstrably ineffective with trusted principals.
- Run new tests and context/completion/evidence/production-feedback/rule-gate regressions.
- Cover no-writing rejection and repeat semantics using isolated temporary storage.
- Save per-case results and measured local timing/calls if available without expanding
  production instrumentation. Tokens and real-host integration remain unknown.
- Report exact changed files, RED/GREEN commands and results, unverified cases and
  compatibility impact to the task report path given by the controller. Return only
  DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT, test summary, concerns and report path.

## Task 2: Minimal documentation and complete-package consistency

Dependency: Task 1 reviewed and accepted; no concurrent implementation.
Work only in /Users/zhaowei/Desktop/David/project/managing-long-task-context/.scratch/strict-independent-validation-20260911/work.
Read frozen spec /Users/zhaowei/Desktop/David/project/managing-long-task-context/docs/specs/strict-independent-validation.md and Task 1 report path supplied at dispatch.
Never dispatch subagents, install, commit, merge, push or edit any production project.
Use apply_patch. No runtime behavior changes in this task.

Allowed edits: SKILL.md, references/independent-validation.md (new concise reference),
examples/independent_validation.py (synthetic runnable example), skill-package.json,
scripts/sync_context_strict_skill.py, tests/test_distribution.py and focused tests for
the new example/declaration if necessary. Generated Strict distribution files may be
synced inside the isolated copy. Never modify Lite source or installed packages.

Keep SKILL main-body net growth <= 120 English words; replace misleading old independence
wording instead of appending a tutorial. Put actual host API contract/limitations and
one clear example in the on-demand reference. Explicitly say no verified Codex/Claude
adapter, same process Python code is trusted, host policy cannot be supplied by model,
old true contracts without trusted resolver now block, false low-risk contracts do not.
Receipt fixture is synthetic; no production credentials, forged-host-success example,
or claim that different thread IDs establish authentication.

Register a precise capability for local independent-validation gate; declare and copy
new source/test/reference/example files. Keep version unreleased 0.7.0; generated full
manifest hashes identify the candidate. Reuse existing build/verify tools. No new CLI.

Validation: compile/run example for valid and blocked cases; source checker validates
all documented paths/API exports; build/verify whole Strict package; run new public
tests from the built package in a process outside source root; prove expected copied
file set and byte equality and no Lite changes. Supply exact commands/results in task
report. Controller performs final regression/integration review separately.
