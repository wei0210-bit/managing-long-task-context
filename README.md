# Context ledger skills

Context Strict 1.0.0 gives multiple agents a shared factual ledger: typed facts,
provenance, evidence pointers, TTLs, checkpoints, agreement seals/history, worker
reports and acceptance records. Missing or stale information appears in read-only
reports. Orca owns sessions, plans, dispatch, waiting, code execution and review.

Read [SKILL.md](SKILL.md) for the ledger API and [CONTEXT.md](CONTEXT.md) for the
current project entry. [Context Lite](skills/context-lite/SKILL.md) automatically
serves a single low-risk primary agent needing multi-turn context recovery.

The maintained Strict sources are at the repository root. Run
`python3 scripts/sync_context_strict_skill.py` to regenerate `skills/context-strict`;
run `python3 scripts/sync_context_tools.py` for shared Lite tools. Full packages
are built/verified with `scripts/skill_package.py`, including their manifests.

Validation uses `python3 -m unittest discover -s tests`, Python 3.12, package tests
from outside the package, and `scripts/regression_checklist.py`. Historical controls
retired by STRICT-LEDGER remain labelled in [the regression checklist](docs/regression-checklist.md).
