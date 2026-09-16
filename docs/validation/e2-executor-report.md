# E2 executor report

## Boundary and contract

Executed only the E2 complete-package connection scope under contract v1.1,
SHA-256 `0f4237d22db440b61c596a37c3fda3242ab7324f3263f696f9dcf53ba5295827`.
The earlier v1 contract hash remains
`f510980b08a35575c6c758421ea2d7b17fba6951aae8a44d86f9d79d88111983`.
No global installation, commit, push, deployment, remote CI, real host
adapter, production action, or paid model call was performed.

## Delivered local E2 connection

- Strict candidate version is `0.8.0` in root declaration, project metadata,
  and generated Strict declaration. `short-session-handoff/v1` declares all
  five public exports.
- `handoff.py` is in the import-time controlled baseline. Runtime identity
  remains lightweight (manifest/path/binding only); full doctor remains the
  content-hash proof.
- `BoundContext`, `run`, and `__all__` expose prepare, validate, activate,
  cancel, and status. Missing bound workspace/package returns
  `HANDOFF_BINDING_REQUIRED`; path overrides return
  `HANDOFF_BOUND_PATH_OVERRIDE` and do not guess paths.
- The strict copy list contains the module, reference, executable example,
  activation/protocol tests, and `handoff_test_authority.py`. It deliberately
  excludes the development-only `test_handoff_distribution.py`; a manifest
  assertion proved it is absent.
- The example runs full doctor before creating its temporary local state,
  then uses BoundContext for prepare/validate/status and async `run` for
  activate. Its fixed synthetic registry reads real temporary files and fixed
  registrations. It exits nonzero if identity or any required lifecycle
  result is not as expected. It reports one activation event and unchanged
  event bytes on idempotent replay.
- CI retains its existing clean `git:$GITHUB_SHA` package build. Its added
  step reuses that verified Strict package for full doctor and the example,
  then explicitly runs the five distribution tests and rejects a zero-test
  result. Remote CI itself is **NOT_RUN**.

## Validation evidence

The exact commands, exit codes, durations, baseline/assembly failures, and
candidate fingerprints are in [e2-executor-runs.json](e2-executor-runs.json).

The two captured failures were an absent BoundContext entry and an absent
distributed protocol test. Per the contract and controller clarification,
both are assembly/closure failures, **not** behavior TDD-red evidence. They
are retained verbatim and corrected by explicit public-package coverage; no
historical red-before-green claim is made. The pre-existing E1 handoff state
machine was not modified.

Focused runs passed: distribution/runtime identity/new package tests 29/29;
the v1.1 process-recovery compatibility suite 11/11; and the explicit frozen
0.7.0 migration analogy 6/6 with `MLTC_LEGACY_PACKAGE` set. The latter is a
local synthetic process comparison, not a real host migration claim. A
retrospective package comparison also observed old 0.7.0 rejecting the new
capability while the candidate accepts and seals it.

The first 52-file candidate is intentionally withdrawn because it carried a
development-only distribution test. The final controller-built candidate is
`/private/tmp/mltc-e2-controller.rGw7ow/context-strict`: 51 files, manifest
`51331cb7ea3edb2c120d1f1a5efa76dff32d79edd7644a1f0f98312ab0817165`,
source-tree hash
`5ecbef6bf1d08c7dd75e5e39d7efba3764bcd092475039c14ebb33fa32297d1a`,
and source revision `candidate:dirty-worktree-0.8.0`. This explicit dirty
candidate label does not claim the contents are the Git HEAD package.

## Open evidence boundaries

Final complete regression and controller probes are owned by the controller
and remain separate from this executor report. Model judgment, token/cost
benefit, real Codex/Claude host identity, remote CI, and production benefit
are **UNKNOWN/NOT_RUN**. A successful local package mechanism does not prove
any of those outcomes.
