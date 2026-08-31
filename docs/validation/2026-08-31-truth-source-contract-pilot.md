# Truth Source Contract Validation — 2026-08-31

## Verdict boundary

Implementation revision under test: `bbd9d77988dce68d977670aea587e00d405d70f7`.

This controller-produced record covers the frozen specification section 12 checks and the real-workspace pilot. It does not yet claim AC-01 through AC-06 complete: independent acceptance and the Context Strict completion gate remain pending. The structured report is `docs/validation/2026-08-31-truth-source-contract-test-report.json`, digest `sha256:9f1b1c8784500ed1bd316124aacf309a82d36c1e3fc0e74626c4e704e6c0794e`.

## Dogfood contract transition

- Task `TRUTH-SOURCE-CONTRACT-001` moved from sealed v1 `sha256:7c6c496c7684be728fdfbefa3e4d95d17f8ded3cdc2320abdaae60148827b7b2` to sealed v2 `sha256:89ed0f23de7db90a9a72ea7a9d845d38f0dfd57ff83d77295ae7cf07e29ed5da` after user execution approval.
- Structural changes were exactly `version`, `workspace_root`, `required_capabilities`, `truth_sources`, and `seal`. The stable publisher-field digest remained `sha256:2401a461d5fc879f6bbeb11146f80e41abf75d151c775203251f3e92a86dd897`; the acceptance-criteria digest remained `sha256:ab94662c50b233aab4c48521b7bbeec2d13efaa2a6aaa3a21eb634fff5ed5288`; the actor-role digest remained `sha256:7284e01516b8b7c059cd7fb1f94f2d05d1e4bf405bc3778ce579de7a3d21fac3`.
- Unique v2 publish event: `EV-3006852a3b70`. `TS-DESIGN-SPEC` observation event: `EV-5b3f886f2cee`. Fresh public audit and release both passed.

## Specification 12.1 automated checks

| # | Required check | Direct evidence and result | Status |
|---:|---|---|---|
| 1 | Legacy golden compatibility | `LegacyTruthSourceCompatibilityTests` and `LegacyTruthSourceFastPathTests`; fixed contract/file/report hashes, zero truth resolver and workspace-source I/O; root full suite 216/216. | PASS |
| 2 | Schema/capability table | `TruthSourceSchemaTests`; capability pairing, exact fields/types, unique IDs, owner/age/change kind, workspace root, safe locator. | PASS |
| 3 | Event/rebuild/recovery | `TruthSourceReducerTests` and `TruthSourceRecoveryTests`; dirty/idempotence/selective invalidation, poison, snapshot rebuild, publish crash cuts, capability add/change/remove and same-version missing-event recovery. | PASS |
| 4 | Observation binding | `TruthSourceApiTests`; actor, contract digest, generation, fingerprint, trusted time and verification refs are bound; rejected writes preserve bytes/event counts. | PASS |
| 5 | Unmarked byte change | Automated evaluator/API tests reject observe with `TRUTH_SOURCE_UNDECLARED_CHANGE` and gate with `TRUTH_SOURCE_CHANGED`; natural pilot repeated the path. | PASS |
| 6 | Four-stage fail closed | `TruthSourceEvaluationTests` and `TruthSourceGateTests`; release/resume/handoff/completion cover unobserved, dirty, stale, changed, missing, unreadable and unknown. | PASS |
| 7 | Completion order/linearization | `TruthSourceGateTests`; entry-invalid callback counts and attempts are zero, tail barriers cover dirty/contract/file/freshness changes, and writer lock ordering is asserted without sleeps. | PASS |
| 8 | Secure file resolution | `SecureFileResolverTests`; absolute/escape/directory/glob/symlink/root swap/replacement/read-change/FD balance/nonblocking flags and 16 MiB boundary. | PASS |
| 9 | Non-leakage | Automated unique-canary tests plus natural dual-directory `rg` returned exit 1 with empty output; brief/events/snapshot/gate/errors retain only control metadata. | PASS |
| 10 | Distribution | Root 216/216; Strict 211/211; `ContextStrictDistributionTests` 5/5; 12 maintained files byte-identical; root/Strict examples exact; Python 3.12 wheel, isolated install and imports passed in TSC-07. | PASS |
| 11 | Crash injection | `TruthSourceRecoveryTests` injects contract temp write, atomic replace, event append and snapshot replace cuts; recovery or stable fail-closed result required. | PASS |
| 12 | Read-only side effects | `ReadOnlyLockingTests` plus read API write spies and task-tree byte maps; audit/brief/diagnostics/gate do not create task, lock, temp or probe files and preserve probe stats. | PASS |

Commands independently rerun by the controller at the implementation revision:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
=> exit 0; Ran 216 tests; OK

(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)
=> exit 0; Ran 211 tests; OK

git diff --check
=> exit 0; no output
```

## Specification 12.2 natural pilot

The first run at revision `1e90a4b54eb7329a980b7a68457901abb30aa50f` stopped acceptance: although the eight-key command result and fixture restoration passed, the final durable observation fingerprinted the temporary mutation, so fresh release/handoff returned `TRUTH_SOURCE_CHANGED`. Its complete runtime was preserved at `.prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b` with event/snapshot/contract hashes `661aa96f…51c50`, `dacf3d41…207e`, and `da429351…46d1`. That failure caused TSC-07 Fix 1; it was not reclassified as a pass.

After the fix was independently accepted, the controller moved the failed directory aside without deletion and the fresh Terra-high worker ran the frozen public command exactly once at `bbd9d77`:

```text
PYTHONDONTWRITEBYTECODE=1 python3 examples/truth_source_contract.py --base-dir .prime/context --spec docs/superpowers/specs/2026-08-31-truth-source-contract-design.md --fixture tests/fixtures/truth_source_pilot.md
=> exit 0
=> {"canary_leaked": false, "changed_handoff_codes": ["TRUTH_SOURCE_CHANGED"], "dirty_handoff_codes": ["TRUTH_SOURCE_DIRTY"], "explicit_dirty_release_passed": true, "fixture_restored": true, "recovered_handoff_passed": true, "reobserved_handoff_passed": true, "undeclared_change_code": "TRUTH_SOURCE_UNDECLARED_CHANGE"}
```

Natural control evidence:

- Fixture before/after SHA-256: `dd6672e61b8af322db6acc2245e54127b9c562a3466ba91744bda6f11cce3947`; fixture Git diff empty.
- Fresh task event chain contains 10 events and snapshot `event_count=10`, generation 4. Initial publication/observations and checkpoint are followed by dirty/observe generation 2, undeclared change rejection and changed gate, dirty/observe generation 3, then restored-source reconciliation.
- Final reconciliation events are `EV-078910329f35` (`truth-source-dirtied`, generation 4) and `EV-d761108f7582` (`truth-source-observed`, generation 4).
- Final `TS-FIXTURE` fingerprint is the restored fixture digest above; required/observed generation is 4/4. Fresh public brief is current; release and handoff pass with two sources checked, two resolution attempts, 10 events checked, zero criteria/evidence attempts and probe pass.
- `rg -n` against both `.prime/context/TRUTH-SOURCE-PILOT` and the preserved failed directory for both source-only canaries exited exactly 1 with empty output.
- Current control-file hashes: events `141259e99ebc612d4eba8236d60253cfa5cc8c4b460a4187fc1c763cde911fe7`; snapshot `047a6ffb9d94417f79ce66b508a6abe192c002bc293e1910671cab46683a3c22`; contract `8415bd25d13209476a9b44e930a4b822d5de93de8c74b844c77defff85384994`.

## Scope, side effects, and residual risks

- Skipped checks: none in specification 12.1 or the approved round-2 natural pilot contract.
- Pending at this point: independent AC-01 through AC-06 acceptance object, its canonical embedding, and the completion gate. They are not silently treated as passed.
- No Context Lite change, URL/remote Git/network resolver, watcher, automatic dirty inference, raw source persistence, global installation, release, push or merge occurred. The failed and successful ignored pilot runtimes remain for audit.
- System `python3` is 3.9.6 and cannot build the package declared `requires-python >=3.10`; install smoke used `/opt/homebrew/bin/python3.12` 3.12.13 without lowering the requirement.
- Actor strings are not authenticated; there is no event hash chain/signature. File equality does not prove semantic truth. Old runtimes may ignore the capability, so every participant must upgrade before use. There is no watcher, and the resolver is designed for a cooperative local workspace rather than a malicious writer.

## Independent Acceptance

```json
{"ac_verdicts":{"AC-01":{"evidence_refs":["file:tests/test_truth_sources.py#LegacyTruthSourceCompatibilityTests","file:tests/test_truth_sources.py#LegacyTruthSourceFastPathTests","command:PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v"],"status":"pass"},"AC-02":{"evidence_refs":["file:src/managing_long_task_context/truth_sources.py#validate_truth_source_contract","file:tests/test_truth_sources.py#TruthSourceSchemaTests","command:PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v"],"status":"pass"},"AC-03":{"evidence_refs":["file:src/managing_long_task_context/__init__.py#mark_truth_sources_dirty","file:src/managing_long_task_context/__init__.py#observe_truth_source","file:tests/test_truth_sources.py#TruthSourceApiTests","file:tests/test_truth_sources.py#TruthSourceReducerTests","event:EV-078910329f35","event:EV-d761108f7582"],"status":"pass"},"AC-04":{"evidence_refs":["file:src/managing_long_task_context/__init__.py#gate","file:src/managing_long_task_context/__init__.py#_gate_truth_enabled","file:tests/test_truth_sources.py#TruthSourceGateTests","command:PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v"],"status":"pass"},"AC-05":{"evidence_refs":["file:src/managing_long_task_context/truth_sources.py#resolve_file_source","file:tests/test_truth_sources.py#SecureFileResolverTests","file:tests/test_truth_sources.py#TruthSourceBriefTests","command:rg -n 'TRUTH_SOURCE_PILOT_CANARY_|协调删除、截断事件并重建 snapshot 的行为不可检测' .prime/context/TRUTH-SOURCE-PILOT .prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b","hash:dd6672e61b8af322db6acc2245e54127b9c562a3466ba91744bda6f11cce3947"],"status":"pass"},"AC-06":{"evidence_refs":["file:tests/test_distribution.py#ContextStrictDistributionTests","command:PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v","command:(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)","gate:TRUTH-SOURCE-PILOT/release:pass","gate:TRUTH-SOURCE-PILOT/handoff:pass","event:TRUTH-SOURCE-PILOT/events=10/generation=4","hash:141259e99ebc612d4eba8236d60253cfa5cc8c4b460a4187fc1c763cde911fe7"],"status":"pass"}},"commands":["PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v","(cd skills/context-strict && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v)","PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_truth_sources.LegacyTruthSourceCompatibilityTests tests.test_truth_sources.LegacyTruthSourceFastPathTests tests.test_truth_sources.SecureFileResolverTests tests.test_truth_sources.ReadOnlyLockingTests tests.test_truth_sources.TruthSourceRecoveryTests tests.test_truth_sources.TruthSourceGateTests tests.test_distribution.ContextStrictDistributionTests","PYTHONDONTWRITEBYTECODE=1 python3 -c '<independent structured-report revision, UTC timestamp, and canonical SHA-256 verification>'","PYTHONDONTWRITEBYTECODE=1 python3 -c '<read-only dogfood audit/release and unique v2 publish/TS-DESIGN-SPEC observation verification>'","PYTHONDONTWRITEBYTECODE=1 python3 -c '<read-only fresh pilot event/snapshot/final fingerprint/release/handoff verification>'","rg -n 'TRUTH_SOURCE_PILOT_CANARY_|协调删除、截断事件并重建 snapshot 的行为不可检测' .prime/context/TRUTH-SOURCE-PILOT .prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b","cmp -s root/distribution truth-source implementation, tests, examples, and copied files","shasum -a 256 tests/fixtures/truth_source_pilot.md .prime/context/TRUTH-SOURCE-PILOT/events.jsonl .prime/context/TRUTH-SOURCE-PILOT/snapshot.json .prime/context/TRUTH-SOURCE-PILOT/task-contract.json .prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b/events.jsonl .prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b/snapshot.json .prime/context/TRUTH-SOURCE-PILOT-failed-1e90a4b/task-contract.json","git rev-parse HEAD","git diff --name-status bbd9d77988dce68d977670aea587e00d405d70f7..HEAD","git status --porcelain=v1"],"model":"gpt-5.6-terra","omissions":[],"reasoning_effort":"high","residual_risks":["Actor 字符串未认证，事件没有签名或哈希链。","安全解析器适用于协作式本地工作区；恶意原地写入者或文件在两次读取间恢复相同字节仍是设计边界。","旧运行时可能忽略 capability，参与任务的运行时仍须先升级。","两份 validation artifacts 当前未跟踪；controller 仍需嵌入本审核对象、运行 completion gate，并完成仅含这两份 artifacts 的证据提交后才可声称整体完成。"],"reviewed_repo_revision":"bbd9d77988dce68d977670aea587e00d405d70f7","reviewer_role":"independent-review-agent","schema":"truth-source-acceptance-review/v1","skipped_checks":[],"validated_at":"2026-08-31T11:40:05Z"}
```

## Completion Gate

The controller validated the review object's exact allowlists, role/model/reasoning, implementation revision, UTC freshness, six per-AC pass verdicts, required rerun commands, empty skipped/omission arrays, and canonical embedding. Reviewer digest: `sha256:7ee60d62b22e4fb03d5fa43d8547a920a268e727558b7e04720e7a512933b453`.

The public Context Strict completion gate for `TRUTH-SOURCE-CONTRACT-001` v2 returned `passed=true`. AC-01 through AC-06 each had one unique `EV-TSC-AC-*` test-report result; built-in resolve, integrity/freshness, and scope checks passed; the criterion-bound claim check passed; independent validation passed; there were no missing evidence/delivery/hop requirements. The report accounted for 6 criteria and 6 evidence attempts. Entry/tail truth checks passed for `TS-DESIGN-SPEC`.

Before and after the completion gate, task-contract/events/snapshot hashes were unchanged: `5a26cb855241e05a1d8e0312abe4cb443281dbcea8658a886e5c05b79f9560f6`, `778cb3e1e824b8d41d1cb8d96a88b38d6d49a3cce6aa9b3fd69be12676b73cc3`, and `ec197b91a8e978af351bee8319b8b1ce2ce8c0f1ee5f42d956e5557184763551`.
