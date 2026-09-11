# Context Strict independent validation — frozen local slice

Status: approved direction; acceptance frozen before implementation, 2026-09-11.
Principle: effective first, economical and refined. Reuse publish/bind/gate/evidence;
do not create a scheduler, identity service, crypto protocol, or generic workflow.

## Scope and trust boundary

Only independent-validation enforcement at public `publish_contract`, `bind`, and
`gate(stage="completion")`; retain existing content, freshness, scope, contract,
approval, rule and post-check file checks. Completion remains read-only.
Host code owns policy and a receipt resolver; model JSON owns neither. A trusted
resolver must obtain actual assignment identities and actual check results from its
host, not echo model input. The library cannot authenticate arbitrary Python callers
or protect against an actor who can replace its code/host. There is no verified
Codex/Claude adapter in scope. Local fixture results are mechanism evidence only.

## Minimal public interface

Add optional keyword-only `independent_validation_required: bool | None = None` and
`validation_resolver: callable | None = None` to `bind` and corresponding publish/gate
entry points as needed. Bind captures policy/resolver once; per-call override of a
captured policy/resolver is rejected, never silently substituted. Non-boolean policy
and non-callable supplied resolver are rejected. No callable is loaded from JSON.

Host policy `True` requires every sealed acceptance criterion to explicitly set
`independent_validation_required: true`; do not silently change publisher criteria.
Check before publish writes, at release, and at completion. Host policy `False` is
an explicit publisher-controlled permission to remove a previous independence
requirement, not a default: normal greater-version and authorized confirmation checks
still apply. None is not permission to downgrade. Existing true criteria cannot be
changed to false/omitted/deleted on version update without explicit host policy False.
Do not authenticate the publisher by merely checking the confirmed_by string; keep
the documented trusted-host boundary and existing publisher controls.

Any sealed criterion requiring independent validation must require host evidence on
completion, including existing contracts: different actor labels alone can no longer
pass. No implicit legacy bypass. Low-risk false/omitted contracts retain behavior.
Model entry carries only `validation_ref` as a lookup reference (other existing
fields may remain). Resolver called once per required criterion with that reference;
it does not receive model-supplied receipt fields to launder into proof.

Trusted resolver result is a mapping containing:
- `validation_ref`, `task_id`, `criterion_id`, `contract_digest` (current sealed
  seal.integrity_digest), `workspace_root` (canonical absolute contract workspace);
- `executor_principals` (nonempty unique strings), `validator_principal` (nonempty
  string), `run_id`, `checker_id` (nonempty actual host references);
- `validated_at`, `expires_at` (explicit UTC; current and not future/out of order);
- `evidence_digests` (exact evidence ID -> artifact_digest mapping for every primary
  evidence and delivery receipt relied upon by this criterion; missing digest blocks);
- `repo_revision` matching required_revision when that criterion requires one;
- `check_result`: `pass`, `fail`, or `unknown` from actual independent checker.

The library checks this receipt against frozen current task/criterion/contract,
workspace, evidence and revision. Unknown/missing/unreadable/wrong binding/expired
receipt -> unknown. Same canonical principal, including different display aliases,
or actual check_result fail -> fail. Both block. Missing run/checker, malformed output,
resolver exception, self-filled JSON or status -> unknown. Existing role/name/time
checks remain and cannot be weakened. Proof is no substitute for existing semantic
evidence verifiers. Independent callback runs before the existing final file/contract
recheck, so mutation from any callback cannot produce completion pass.

Report independent assurance separately (`not_required`, `verified`, `unknown`,
`failed`), concrete codes, and verified host reference/principal/run bindings. Do not
label disabled checking as independently verified. Preserve exact historical v0.5
non-independent report shape if needed; modern evidence-handlers reports expose the
new assurance. Do not change old gold hashes to conceal regressions.

## Frozen acceptance (synthetic unless later explicitly labelled otherwise)

| ID | Public input/change | Expected |
|---|---|---|
| IV01 | Valid distinct trusted principals, current receipt + actual content pass | pass / verified |
| IV02 | Same principal self-review | fail |
| IV03 | Different display names, resolver identifies same principal | fail |
| IV04 | Missing host identity or actual validation time | unknown |
| IV05 | Old contract digest or wrong task/criterion | unknown |
| IV06 | Wrong revision/workspace/evidence digest | unknown |
| IV07 | Expired or future receipt | unknown |
| IV08 | Only executor claims complete/pass, no reference/resolver | unknown |
| IV09 | JSON receipt/status supplied by model, resolver missing | unknown |
| IV10 | Resolver raises, missing run/checker, or returns malformed result | unknown |
| IV11 | Trusted checker fail versus model pass | fail |
| IV12 | Trusted checker unknown/not run | unknown |
| IV13 | Host policy true, initial contract false/omitted or no true criteria | reject publish; no contract/event written |
| IV14 | Existing required criterion downgraded or removed with policy None | reject publish; previous state unchanged |
| IV15 | Authorized higher version with explicit host policy False | publish succeeds; not_required, no resolver I/O |
| IV16 | Bound call tries overriding host policy/resolver | reject |
| IV17 | Gate host policy true, stored contract false/omitted | release/completion blocked |
| IV18 | No requirement, no host policy | legacy result preserved; modern assurance not_required |
| IV19 | Resolver changes relevant file or contract during checking | unknown; never completion pass |
| IV20 | Same completion requested twice | identical decision, no state/business writes or automatic retries |
| IV21 | Trusted receipt passes, actual semantic evidence checker fails | fail |
| IV22 | Explicit host policy False but unauthorized publisher/lower version | reject |

Variants in each row are required subcases, not a request to build extra APIs.
Freeze expected outcomes in tests before each vertical red/green implementation.
Tests use public interfaces and a clearly synthetic host-boundary fixture; never mock
the internal gate. Include a dynamic pass -> changed artifact -> blocked -> renewed
valid evidence/receipt -> pass scenario. No business side effects or real paid calls.

## Local acceptance and reporting

Preserve complete dirty-source package baseline; test baseline/candidate with the same
fixtures and explain API-unavailable baseline cases separately. Run focused regression,
source/package consistency and actual packaged tests. Record commands, return codes,
per-case expected/actual, omitted checks, local gate timing, resolver calls and retry
count. Token, real model stability, real host authenticity and natural effectiveness
remain unknown. Any open load-bearing finding prevents completion/integration.
Do not install globally, edit production projects, commit, merge, push or deploy.

## Deferred

Real host adapter (requires an authenticated host source); lifecycle redesign;
templates/catalog; unified CLI; automatic scheduling; dedupe; real model comparisons.
