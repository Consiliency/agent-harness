---
phase_loop_plan_version: 1
phase: INTEG
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_INTEG=1
    - PYTHONPATH=phase-loop-runtime/src
    - python3
    - -m
    - pytest
    - phase-loop-runtime/tests/test_integ_coordinator_contract.py
    - phase-loop-runtime/tests/test_integ_credential_isolation.py
    - phase-loop-runtime/tests/test_integ_fault_matrix.py
    - phase-loop-runtime/tests/test_integ_legacy_faults_reconciliation.py
    - -q
---

# INTEG: Coordinator Integration and Fault Suite

## Context

INTEG absorbs the superseded convergence-v1 INTEG and FAULTS work into the active v10 roadmap. The current repository contains the broker, event-log, reconciliation, dispatch, fencing, and refresh primitives, but the live `run_train` path still does not call `dispatch_ready_nodes`, `reconcile_before_action`, or `refresh_downstream_after_merge`. The existing credential boundary strips only `GH_TOKEN` and `GITHUB_TOKEN`, while the live broker is constructed in the coordinator process. This plan treats both as standing implementation findings, not accepted residuals.

Canonical `.phase-loop/events.jsonl` records this INTEG planning launch as `unplanned` on a clean worktree aligned with `origin/main`; legacy `.codex/phase-loop/` state has no authority. FABREADMIT is recorded complete in `plans/manifest.json`. INTEG execution remains gated on a completed RUNTIME closeout on the exact execution base; planning now does not waive that upstream dependency.

The roadmap's two work lanes are represented by SL-1 (coordinator integration) and SL-2 (fault certification). SL-0 is the mandatory immutable tests-first preamble, and SL-3 is the read-only whole-phase verifier. One production lane owns every potentially overlapping runtime file, so no write-capable fanout can bypass single-writer ownership.

## Interface Freeze Gates

- [ ] IF-0-INTEG-1 — `CoordinatorRuntime` carries metadata-only authority and a credential-free `BrokerProcessClient`, never an in-process credential-bearing provider adapter. A dedicated broker service process owns mutation credentials and accepts only typed broker requests over a bounded local IPC contract; the coordinator, executor children, and outside-agent children receive a `CredentialIsolationProfile` that removes token, gh-config, keyring/session-bus, SSH-agent, askpass, netrc, and git-credential-helper authentication channels while preserving a positive broker control. On the live `run_train` path, `reconcile_before_action` gates dispatch, resume, publish, review, merge, and release; unsupported event/transition/invalidation versions reject rather than coerce; intent is durable before broker admission and terminal outcome after it; a crash between admission and append replays the same idempotency identity exactly once. `dispatch_ready_nodes` admits an independent pair only after `evaluate_resource_isolation` proves distinct repositories, disjoint complete owned paths, and frozen interfaces, persists the decision, serializes predicate-false/unknown pairs, and always serializes topological merges and release publication. After an upstream merge, `refresh_downstream_after_merge` refreshes each affected branch to the exact merged SHA or records a typed conflict, invalidates prior verification/review, re-verifies, and broker-gates any republish. The phase certification binds the complete adversarial matrix and the recovered 2026-07-26 FAULTS evidence into runner-owned metadata artifacts whose digests are stamped into the INTEG closeout event.

## Lane Index & Dependencies

SL-0 — Immutable tests-only contract and RED receipt
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Live coordinator and process-isolated broker integration
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Adversarial fault certification and legacy reconciliation
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Whole-phase verification and documentation sweep
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable Tests-Only Contract and RED Receipt

- **Scope**: Freeze every INTEG falsifier, mutation anchor, path-entered control, credential channel, fault family, and evidence-reconciliation rule before production work.
- **Owned files**: `phase-loop-runtime/tests/_integ_tdd_guard.py`, `phase-loop-runtime/tests/test_integ_coordinator_contract.py`, `phase-loop-runtime/tests/test_integ_credential_isolation.py`, `phase-loop-runtime/tests/test_integ_fault_matrix.py`, `phase-loop-runtime/tests/test_integ_legacy_faults_reconciliation.py`
- **Interfaces provided**: `immutable INTEG test contract`, `content-bound TDD receipt`, `legacy FAULTS evidence schema`
- **Interfaces consumed**: IF-0-FABREADMIT-1 (pre-existing), current convergence contracts (pre-existing), GOVLEAN content-bound TDD receipt API (pre-existing), RUNTIME completion state (phase precondition)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add a guard whose default mode remains green only while IF-0-INTEG-1 capability is absent, whose activated mode requires every exact node and distinct RED anchor, and whose verify mode rejects skips, deselection, xfail, missing anchors, or a changed test byte.
  - test: Prove the real `run_train` seam records reconciliation before each of the six roadmap action kinds, blocks a stale/unsupported verdict, routes every mutation through the broker client, records intent before admission and outcome after it, and reaches the post-merge refresh seam on a two-node train.
  - test: Parameterize every credential channel named by EC-INTEG-5. Each coordinator/worker attempt invokes a fake `gh` or `git` mutation and must fail authentication; an otherwise identical broker-process control must authenticate through its injected fake channel. Assert the sanitized role and the broker role were both entered.
  - test: Inject the admission-to-ledger crash and prove resume observes one provider effect and one durable outcome. Add direct-mutation and production-call-site inventories so dead exports, permanent-false branches, or direct `gh`/`git` mutation paths cannot satisfy the positive run.
  - test: Exercise overlapping, unknown, same-repository, and disjoint concurrent pairs independently; require a persisted predicate-false serialization event and a genuinely overlapping positive concurrency control only for the disjoint pair. Topological merge and release cases remain serial.
  - test: Cover revocation mid-operation, ambiguous terminals, concurrent same-target requests, delayed provider commits, mixed versions, exact-head drift, forged completion evidence, malformed envelopes, capability overclaim, stale/delayed seat writes, and action-outside-bounds with deterministic clocks/barriers and typed fail-closed observables.
  - test: Freeze a metadata-only `legacy-faults-reconciliation.v1` record that requires the old FAULTS plan digest, exact historical command/node inventory and count, source identity, captured result artifact digest, and runner verification binding; prose-only, missing, fabricated, stale, raw-secret, or count-only evidence fails.
  - impl: Land only these test/support files under the current GOVLEAN tiered-review policy, retain default-green plus activated RED outputs, and record `.phase-loop/evidence/INTEG/content-tdd-receipt.json`. Every later lane treats all SL-0 bytes as read-only.
  - verify: `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py phase-loop-runtime/tests/test_integ_credential_isolation.py phase-loop-runtime/tests/test_integ_fault_matrix.py phase-loop-runtime/tests/test_integ_legacy_faults_reconciliation.py -q`

### SL-1 — Live Coordinator and Process-Isolated Broker Integration

- **Scope**: Compose the existing convergence primitives on the live train path while making the broker service the only credential-bearing process and the only mutation boundary.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/dispatch.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/provider_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/refresh.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/outside_agent.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/process.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`
- **Interfaces provided**: `IF-0-INTEG-1`, `BrokerProcessClient`, `BrokerProcessServer`, `CredentialIsolationProfile`, `live action reconciliation`, `live isolation dispatch`, `exact downstream refresh`
- **Interfaces consumed**: `immutable INTEG test contract`, IF-0-FABREADMIT-1 (pre-existing), RUNTIME event/reconciliation surface (pre-existing on execution base), existing provider completion classifications (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume the frozen SL-0 files without editing them; use their failing node IDs as the repair checklist.
  - impl: Split live launch into a bounded credential-bearing broker service and a credential-free coordinator child. IPC accepts only typed broker execute/readmit requests and metadata-only results, binds train/repository/attempt identity, rejects arbitrary commands or unknown fields, and shuts down without leaking credentials or orphaning the repository generation lease.
  - impl: Extend `BrokerEnvironmentBoundary` and all coordinator-owned child launches with isolated home/config roots, empty credential helpers, no token/keyring/session-bus/SSH-agent/askpass/netrc access, and explicit role receipts. Preserve only the broker role's validated provider access; never serialize secret values into events, logs, IPC, or test artifacts.
  - impl: Make `run_train` recover the convergence event log, call reconciliation before dispatch/resume/publish/review/merge/release, reject unsupported versions, persist action/isolation decisions, and place intent/outcome records around broker admission. Remove or fail-close every direct mutation fallback; human-executed/unsupported broker classifications remain blocked and are not promoted in this phase.
  - impl: Drive ready-node work through `dispatch_ready_nodes` with complete roadmap-owned paths and frozen-interface evidence. Keep the repository lock for the entire work unit, serialize merges/releases, and make stale completion unable to release or satisfy a newer attempt.
  - impl: After each observed upstream merge, invoke exact-SHA downstream refresh, invalidate prior evidence, re-run bound verification, republish through the broker when classified, and require fresh review before merge. Persist typed conflict/blocked outcomes for deterministic resume.
  - impl: Preserve autonomous `drafts_open`, forward-only already-merged state, FABPUB/FABREADMIT repository authority, train-ledger compatibility projection, and current result vocabulary. Do not add dependencies, migrations, generated files, env examples, snapshots, or provider-capability promotions.
  - verify: `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py phase-loop-runtime/tests/test_integ_credential_isolation.py phase-loop-runtime/tests/test_integ_fault_matrix.py -q`

### SL-2 — Adversarial Fault Certification and Legacy Reconciliation

- **Scope**: Execute and reduce the immutable fault suite, bind the historical FAULTS run when authentic evidence exists, and make documentation/spec impact explicit without writing repository files.
- **Owned files**: none
- **Interfaces provided**: `INTEG fault certification`, `legacy FAULTS reconciliation`
- **Interfaces consumed**: `IF-0-INTEG-1`, `immutable INTEG test contract`, `legacy FAULTS evidence schema`, frozen historical FAULTS plan (pre-existing), runner-owned verification artifact (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Run every immutable fault parameter together with zero live network/provider calls and zero skipped family rows. Route any production failure back to SL-1, then rerun the entire suite without changing SL-0.
  - impl: Do not edit repository files. Reduce authentic archived 2026-07-26 FAULTS command, 138-node result, source identity, and artifact digests into `.phase-loop/evidence/INTEG/legacy-faults-reconciliation.json`; if any binding is unavailable or contradictory, fail closed with `verification_evidence_missing` rather than substituting the old plan prose or a new run.
  - impl: Record `no_spec_delta`: INTEG changes runtime behavior and tests only; no roadmap, canonical external spec, public provider classification, README, changelog, release note, or operator guide changes are authorized.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/_integ_tdd_guard.py verify-legacy-faults --record .phase-loop/evidence/INTEG/legacy-faults-reconciliation.json --verification .phase-loop/evidence/INTEG/verification.json`

### SL-3 — Whole-Phase Verification and Documentation Sweep

- **Scope**: Validate the plan and roadmap, execute the exact automation suite and broad regressions on final HEAD, record the terminal no-doc-change decision, and emit the sole completion evidence for IF-0-INTEG-1.
- **Owned files**: none
- **Interfaces provided**: `runner-bound INTEG verification evidence`, `IF-0-INTEG-1 closeout eligibility`, `documentation decision`
- **Interfaces consumed**: `IF-0-INTEG-1`, `INTEG fault certification`, `legacy FAULTS reconciliation`, `content-bound TDD receipt`
- **Parallel-safe**: no
- **Tasks**:
  - test: Run roadmap/plan validation, the content-bound TDD verifier, the exact `automation.suite_command`, focused convergence/broker/train/outside-agent regressions, the whole runtime suite, Ruff, and `git diff --check`.
  - impl: Do not edit files. Record `no_doc_delta` for README, CHANGELOG, release notes, and operator guides because INTEG implements the already-frozen roadmap contract without changing a public provider classification or release surface. A failure returns to the sole owning lane and forces the complete reducer to rerun. Withhold IF-0-INTEG-1 unless every command passes and both runner-owned evidence artifacts bind the final HEAD and roadmap digest.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md && python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-INTEG.md`

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-2: effort=`high`, work-unit=`phase_reducer`, unsupported=`inherit_default`, inherit-default=`true`, reason=`fault and historical-evidence reduction after the sole production writer`
- SL-3: effort=`high`, work-unit=`phase_verify`, unsupported=`inherit_default`, inherit-default=`true`, reason=`whole-phase exact-head verification`

## Execution Notes

- Do not dispatch SL-0 until canonical runner/manifest state records both FABREADMIT and RUNTIME complete on the execution base. An unmet predecessor is `upstream_phase_unmet`; it does not authorize a stale-plan or legacy-roadmap bypass.
- SL-0 is a preamble, SL-1 is roadmap lane A, SL-2 is roadmap lane B, and SL-3 is the verifier. No write-capable lanes run concurrently. Reducers are excluded from writer waves.
- The complete phase-owned repository write set is the union of SL-0 and SL-1. `.phase-loop/**` evidence is runner-owned and must be emitted through the runner evidence/closeout path, never edited as executor-owned output. Legacy `.codex/phase-loop/**` remains off-limits.
- All SL-0 tests and support files are immutable after their reviewed tests-only landing. The content-bound receipt, activated RED output, default-green output, exact node inventory, and anchor inventory are mandatory EC-INTEG-0 evidence.
- Existing provider classifications remain fail-closed. INTEG may route merge/release/package requests through the broker and observe their typed human-executed/unsupported result, but it may not make those verbs automated; RELEASE owns real pilots and release dispatch.
- Fault timing uses injected clocks, barriers, fake channels, and call logs. No sleep-based proof, live credential, real mutation, transcript authority, secret-bearing fixture, or raw provider payload is allowed.
- Documentation impact is consciously `no_doc_delta` and spec impact is `no_spec_delta`: behavior is already specified by the v10 roadmap and absorbed contracts. If implementation discovers a required contract or public-surface change, stop for a roadmap amendment instead of widening this plan.
- Policy precedence is CLI/operator override, this plan, roadmap policy, then registry defaults. Silent downgrade is forbidden; the declared `inherit_default` behavior is the only default inheritance.
- Closeout is complete only when verification passes and `produced_if_gates` contains exactly `IF-0-INTEG-1`. This phase is not a visible render deliverable, so `visual_render_declared=false` and no visual evidence is required.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `none outside this repository`
- evidence paths: `.phase-loop/evidence/INTEG/spec-delta-closeout.json`, `.phase-loop/evidence/INTEG/content-tdd-receipt.json`, `.phase-loop/evidence/INTEG/legacy-faults-reconciliation.json`, `.phase-loop/evidence/INTEG/verification.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-INTEG.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/INTEG/content-tdd-receipt.json --repo .`
- `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py phase-loop-runtime/tests/test_integ_credential_isolation.py phase-loop-runtime/tests/test_integ_fault_matrix.py phase-loop-runtime/tests/test_integ_legacy_faults_reconciliation.py -q`
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/_integ_tdd_guard.py verify-legacy-faults --record .phase-loop/evidence/INTEG/legacy-faults-reconciliation.json --verification .phase-loop/evidence/INTEG/verification.json`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_convergence_broker_admission.py phase-loop-runtime/tests/test_convergence_broker_api.py phase-loop-runtime/tests/test_convergence_broker_credsep.py phase-loop-runtime/tests/test_convergence_broker_evidence.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py phase-loop-runtime/tests/test_convergence_broker_verbs.py phase-loop-runtime/tests/test_convergence_cli_integration.py phase-loop-runtime/tests/test_convergence_coordination_contracts.py phase-loop-runtime/tests/test_convergence_dispatch.py phase-loop-runtime/tests/test_convergence_event_contracts.py phase-loop-runtime/tests/test_convergence_event_log.py phase-loop-runtime/tests/test_convergence_fencing.py phase-loop-runtime/tests/test_convergence_fixture_contracts.py phase-loop-runtime/tests/test_convergence_invalidation.py phase-loop-runtime/tests/test_convergence_live_enable.py phase-loop-runtime/tests/test_convergence_provider_contracts.py phase-loop-runtime/tests/test_convergence_reconcile.py phase-loop-runtime/tests/test_convergence_refresh.py phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_convergence_seat_lifecycle.py phase-loop-runtime/tests/test_convergence_status.py phase-loop-runtime/tests/test_convergence_train_integration.py phase-loop-runtime/tests/test_fab_activation_promotion.py phase-loop-runtime/tests/test_fab_canonical_b.py phase-loop-runtime/tests/test_fab_closeout_crash_safety.py phase-loop-runtime/tests/test_fab_closeout_wiring.py phase-loop-runtime/tests/test_fab_delta_c.py phase-loop-runtime/tests/test_fab_delta_consumer.py phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py phase-loop-runtime/tests/test_fab_gate_d.py phase-loop-runtime/tests/test_fab_producer.py phase-loop-runtime/tests/test_fab_provenance_a.py phase-loop-runtime/tests/test_fabpub_shared_epoch.py phase-loop-runtime/tests/test_fabreadmit_broker.py phase-loop-runtime/tests/test_outside_agent_advisory.py phase-loop-runtime/tests/test_outside_agent_advisory_cli.py phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py phase-loop-runtime/tests/test_outside_agent_authority_boundary.py phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py phase-loop-runtime/tests/test_outside_agent_conform_evidence.py phase-loop-runtime/tests/test_outside_agent_contract_drift.py phase-loop-runtime/tests/test_outside_agent_contract_imports.py phase-loop-runtime/tests/test_outside_agent_contract_pin.py phase-loop-runtime/tests/test_outside_agent_core_api.py phase-loop-runtime/tests/test_outside_agent_provenance.py phase-loop-runtime/tests/test_outside_agent_real_ci.py phase-loop-runtime/tests/test_outside_agent_real_cli.py phase-loop-runtime/tests/test_outside_agent_real_output.py phase-loop-runtime/tests/test_outside_agent_real_runtime.py phase-loop-runtime/tests/test_outside_agent_redaction.py phase-loop-runtime/tests/test_outside_agent_redaction_separation.py phase-loop-runtime/tests/test_outside_agent_release_surface.py phase-loop-runtime/tests/test_outside_agent_schema_validation.py phase-loop-runtime/tests/test_outside_agent_vectors.py phase-loop-runtime/tests/test_train_e2e.py phase-loop-runtime/tests/test_train_invariants.py phase-loop-runtime/tests/test_train_merge.py phase-loop-runtime/tests/test_train_order_only_deps_47.py phase-loop-runtime/tests/test_train_prebuilt.py phase-loop-runtime/tests/test_train_roadmap.py phase-loop-runtime/tests/test_train_runner.py -q`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-INTEG-0 — proven by `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/_integ_tdd_guard.py verify --repo . --receipt .phase-loop/evidence/INTEG/content-tdd-receipt.json`; falsified by receipt/test-byte drift, a missing exact node, or retained RED evidence without its asserted anchor.
- [ ] EC-INTEG-1 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py -q -k broker_only`; falsified by the selector's direct-mutation restoration case, with the live action path asserted entered.
- [ ] EC-INTEG-5 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_credential_isolation.py -q`; falsified by each frozen credential-channel mutation independently, with matching broker-positive and coordinator-negative path-entered controls.
- [ ] EC-INTEG-6 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py -q -k live_action_matrix`; falsified by each selector mutation, with the two-node live seam and all six action events asserted entered.
- [ ] EC-INTEG-2 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_fault_matrix.py -q -k admission_append_crash`; falsified by the idempotency-guard mutation, with admission and resume both asserted entered.
- [ ] EC-INTEG-3 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_fault_matrix.py -q`; falsified by each frozen fault-family mutation independently, each with a positive path-entered control.
- [ ] EC-INTEG-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/_integ_tdd_guard.py verify-legacy-faults --record .phase-loop/evidence/INTEG/legacy-faults-reconciliation.json --verification .phase-loop/evidence/INTEG/verification.json`; falsified by removing or changing any historical run binding and observing the reducer reject the record.
- [ ] EC-INTEG-7 — proven by `env PHASE_LOOP_TDD_EXPECT_INTEG=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_integ_coordinator_contract.py -q -k concurrent_admission`; falsified by the predicate-false serialization and predicate-true concurrency mutations separately, with both path-entered controls and persisted decisions asserted.
