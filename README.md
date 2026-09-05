# Context Skills

Choose manually; this MVP does not auto-classify a task or transfer a task between
the two skills.

## Versioned packages

Each distributable skill has a `skill-package.json`. Build a complete copy and
verify its generated manifest before installation or evaluation:

```sh
python3 scripts/skill_package.py build \
  --source skills/context-strict \
  --destination /tmp/context-strict-package \
  --source-revision git:<exact-commit>
python3 scripts/skill_package.py verify --package /tmp/context-strict-package
```

The build receipt includes the manifest SHA-256. Freeze that hash with the eval or
installation receipt; copying only `SKILL.md` is not a valid package.

## Executable evidence contracts

New Strict contracts should enable `evidence-handlers/v1`. The sealed
`evidence_handlers.types` mapping binds every required evidence kind to stable resolver
and verifier capability IDs. `publish_contract()` rejects an incomplete mapping before
writing the contract; release and later gates require matching runtime handlers.

The built-in resolver kinds are `file`, `git-commit`, `test-report`, and `url`. A test
category such as “integration test” normally uses `test-report`; truly custom kinds remain
supported when both custom capabilities and callable handlers are supplied. See
[`assets/task-contract.example.json`](assets/task-contract.example.json) and the complete
[`examples/strict_completion.py`](examples/strict_completion.py) flow.

## Production context controls

Context Strict 0.5 defaults new contracts to an atomically published read-only file
guard, blocks release/resume/handoff when mandatory brief content cannot fit, and
reports every omitted mandatory item. The file mode is an error-prevention layer; the
sealed digest and gate remain authoritative.

Bind long-running tools to an absolute store before changing directories:

```python
ctx = context.bind("/absolute/project/.prime/context")
```

Use `externalize_item()` to shorten an unchanged fact without replacing its ID,
controls, evidence, or verification time. For a causal chain that one execution must
prove, opt into `required_hops_mode: "single-evidence-ordered"`; legacy contracts keep
aggregate hop coverage. Detailed failure modes and boundaries live in
[`references/production-failure-patterns.md`](references/production-failure-patterns.md).

## Runtime identity and diagnostics

Strict 0.6 and Lite 1.2 add `scripts/context_doctor.py` to complete packages. Use
`check --mode full --package-root <absolute-package>` after installation/update;
use identity-only checks and checked recovery during tasks. Strict callers must
explicitly select their Python module path (`PYTHONPATH=<package>/src`); diagnostics
do not silently repair a wrong import. Unknown or conflicting identities return
no recovery content, and legacy APIs keep their existing behavior.

See [runtime identity](references/runtime-identity.md) for binding initialization,
CLI/Python examples, limitations and upgrade handling. These checks do not prove
completion or replace existing evidence gates. [Issue 9 specification](docs/specs/runtime-identity-doctor.md)
defines the acceptance matrix.

## Manual routing

`scripts/context_skill_router.py` accepts explicit task characteristics and returns
`NO_SKILL`, `LITE_RECOMMENDED`, or `STRICT_REQUIRED`. It never injects a skill or
authorizes an external action. Lite/Strict selection remains a user decision, and
the route must be recomputed when scope or risk changes.

```json
{
  "risk_facts_complete": true,
  "multi_turn": true,
  "single_primary_agent": true,
  "high_risk": false,
  "auditability_required": false,
  "frozen_acceptance": false,
  "independent_validation": false,
  "external_side_effects": false,
  "multiple_state_writers": false
}
```

```sh
python3 scripts/context_skill_router.py --input task-characteristics.json
```

| Choose | Use it for | Local copy path |
| --- | --- | --- |
| Lite | One primary agent, low-risk multi-turn recovery, and a compact Markdown checkpoint. | `skills/context-lite/` |
| Strict | Multi-agent work, external side effects, auditability, frozen acceptance, or independent validation. | `skills/context-strict/` |

Read the [v1.1 design specification](docs/specs/context-skills-v1.1.md) for the
full boundary. Both skills are independently installable. The root Strict sources
remain the compatibility and development source during migration; run
`python3 scripts/sync_context_strict_skill.py` before validating or publishing the
`skills/context-strict/` distribution. Transfer is not implemented in this MVP.

## Context Strict truth sources

Truth sources are optional controls for local originals whose current bytes matter to a
task decision. Start with
[`assets/truth-source-contract.example.json`](assets/truth-source-contract.example.json),
then use the public lifecycle demonstrated by
[`examples/truth_source_contract.py`](examples/truth_source_contract.py):

```bash
python3 examples/truth_source_contract.py
```

The lifecycle is publish → observe every declared source → release. A declared change
must be marked dirty, then re-read and observed by its owner before handoff can pass.
Briefs carry paths and control metadata only; executors read originals themselves.
Unknown or failed truth observations block the gate, but do not substitute for completion
evidence. The runtime does not retain raw bytes, infer changes automatically, authenticate
actors, or provide an event hash chain. Upgrade every participating runtime before
declaring `truth-sources/v1`; without the declaration, no truth-source scan or prompt block
is added.
