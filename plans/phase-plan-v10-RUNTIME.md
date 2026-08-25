---
phase_loop_plan_version: 1
phase: RUNTIME
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_convergence_event_log.py
      phase-loop-runtime/tests/test_convergence_reconcile.py
      phase-loop-runtime/tests/test_convergence_adapters.py
      phase-loop-runtime/tests/test_convergence_status.py
      phase-loop-runtime/tests/test_convergence_runtime_imports.py
      phase-loop-runtime/tests/test_cli_train_status_45.py
      phase-loop-runtime/tests/test_convergence_event_contracts.py
      phase-loop-runtime/tests/test_convergence_coordination_contracts.py
      phase-loop-runtime/tests/test_convergence_provider_contracts.py
      phase-loop-runtime/tests/test_convergence_fixture_contracts.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration";
      ruff check phase-loop-runtime/src/phase_loop_runtime/
---

# RUNTIME: Runtime Substrate

## Context

RUNTIME completes the non-broker convergence substrate already present as a thin skeleton on
the current `origin/main` input recorded by
`v10-RUNTIME.lifecycle[0].metadata.planning_base` in `plans/manifest.json`. The roadmap bytes are
exactly SHA-256 `9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0`.
The authoritative phase ledger in `plans/manifest.json` records LEGIBLE and PROOFGATE as
`completed` and RUNTIME as `committed`, so RUNTIME's roadmap dependency is satisfied. A missing or
stale worktree-local `.phase-loop/state.json` does not override that ledger. Legacy
`.codex/phase-loop/` compatibility state is not an authority and is not consulted.

The 2026-07-13 `plans/phase-plan-vergence-v1-RUNTIME.md` is retained as provenance-only input. Its
manifest row is `orphaned`, and this v10 plan explicitly supersedes it for execution. Main already
contains the initial implementation from Consiliency/agent-harness#197: `event_log.py`,
`reconcile.py`, bounded adapter modules, status projection, `train-status --event-log`, exports,
and a short public document. The existing focused tests establish only smoke behavior; they do not
prove crash-safe short writes and cross-process appends, fresh four-domain reconciliation and every
frozen authority verdict, strict adapter fencing, or full transcript-free reconstruction. RUNTIME
therefore lands new falsifiers against this current baseline before repairing production.

The roadmap now assigns advisor-seat lifecycle persistence to REVIEWTRUTH. RUNTIME may consume the
pre-existing `CoordinatorEvent.seat_outcomes` field when reconstructing approval state, but it does
not edit `panel_invoker.py`, create seat outcomes, or claim EC-REVIEWTRUTH-11. DAG dispatch,
coordinator wiring, downstream refresh, merge/release publication, and credential-bearing broker
operations remain owned by INTEG, FABPUB/FABREADMIT, or RELEASE. The roadmap's named
`train_runner.py`, `runner.py`, and `injection.py` surfaces were inspected; none requires a RUNTIME
write under that boundary.

## Interface Freeze Gates

- [ ] IF-0-RUNTIME-1 — INTEG consumes the existing public runtime API, completed without a second
  coordinator or broker: `default_convergence_event_log_path(coordinator_root: Path, train_id: str)
  -> Path`; `record_intent(path: Path, event: CoordinatorEvent) -> None`;
  `record_outcome(path: Path, event: CoordinatorEvent) -> None`;
  `read_convergence_events(path: Path) -> tuple[CoordinatorEvent, ...]`;
  `recover_train_state(events: Iterable[CoordinatorEvent]) -> RecoveredTrainState`;
  `reconcile_train_state(state: RecoveredTrainState, probes: ExactStateProbes) ->
  ReconciliationVerdict`; `build_train_status(state: RecoveredTrainState,
  event_log_path: Path | str = "") -> TrainStatusSnapshot`; and
  `render_train_status(snapshot: TrainStatusSnapshot, as_json: bool = False) -> str`.
  `RecoveredTrainState` retains `train_id`, last outcome per node, unmatched intents, latest epoch,
  verification/approval validity, ambiguities, and last durable offset. `ReconciliationVerdict`
  retains one versioned `ReconciliationBinding`, fresh metadata-only observations, a non-secret
  blocker reason, and `checked_at`. Intent is durable before return; an outcome must match a prior
  intent by `(train_id, node_id, attempt_id, epoch)`; identical replay is idempotent; conflicting
  duplicates, mixed versions, epoch regression, corrupt committed records, missing authority, and
  ambiguous provider outcomes fail closed. Every reconciliation invokes fresh Git, GitHub,
  provider, and registry probes and selects only the frozen IF-0-FREEZE-5 authority enum while
  emitting the exact normative `InvalidationTrigger` values. Transcripts and `.phase-loop/` remain
  recovery evidence, never live-state authority. `AdapterExecutionRequest` continues to carry the
  seven-field `AdmissionRequest`, including its non-empty exact expected-version predicate; Codex,
  Claude, and outside-agent adapters execute one bounded non-coordinating action and return only
  the frozen `ConvergenceResultEnvelope`. `RUNTIME_CAPABILITY_VERSION = 1` is exported only by the
  terminal reducer after all three functional writers integrate.

## Lane Index & Dependencies

SL-0 — Immutable tests-only contract and RED evidence
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no
SL-1 — Durable convergence event log
  Depends on: SL-0
  Blocks: SL-4, SL-5
  Parallel-safe: yes
SL-2 — Exact-state reconciliation
  Depends on: SL-0
  Blocks: SL-4, SL-5
  Parallel-safe: yes
SL-3 — Adapter envelopes and transcript-free status
  Depends on: SL-0
  Blocks: SL-4, SL-5
  Parallel-safe: yes
SL-4 — Runtime integration reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: SL-5
  Parallel-safe: no
SL-5 — Documentation and whole-phase verification reducer
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable tests-only contract and RED evidence

- **Scope**: Land the complete v10 RUNTIME falsifier set, default-green/activated-RED guard, and chronology proof before any production edit.
- **Owned files**: `phase-loop-runtime/tests/_runtime_tdd_guard.py`, `phase-loop-runtime/tests/test_convergence_event_log.py`, `phase-loop-runtime/tests/test_convergence_reconcile.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_convergence_status.py`, `phase-loop-runtime/tests/test_convergence_runtime_imports.py`, `phase-loop-runtime/tests/test_cli_train_status_45.py`
- **Interfaces provided**: immutable RUNTIME tests, RUNTIME RED-anchor inventory, RUNTIME chronology receipt contract
- **Interfaces consumed**: `CoordinatorEvent` (pre-existing), `ConvergenceResultEnvelope` (pre-existing), `AdmissionRequest` (pre-existing), `AuthoritySource` (pre-existing), `InvalidationTrigger` (pre-existing), `test_lane_chronology.v1` (pre-existing)
- **Parallel-safe**: no; this is the single pre-production tests-only boundary.
- **Tasks**:
  - test: Add `_runtime_tdd_guard.py` with exact activation `PHASE_LOOP_TDD_EXPECT_RUNTIME=1`, lazy probes, unique `RUNTIME-RED-ANCHOR::<case>` failures, a collected-node inventory, injection-anchor assertions, and a chronology-receipt verifier without pinning future commits or commit counts in this plan.
  - test: Expand the six matching focused tests plus `test_cli_train_status_45.py` to cover torn/short/cross-process appends, replay conflicts, mixed versions and epochs, fresh four-domain probes and every authority/invalidation enum, strict executable and environment bounds, expected-version preservation, provider terminal mappings, process-tree timeout, event-log-only restart, stable JSON/human status, unchanged legacy `--train`, and the integrated public surface.
  - test: On the exact pre-production base, require the ordinary selector to pass or skip only the guarded new falsifiers, then require the activated selector to fail only at the complete unique RED-anchor inventory after every injection anchor was entered. Preserve JUnit, raw output digest, source-tree digest, reviewed plan/roadmap digests, and the tests-only landing identity in runner-owned `.phase-loop/evidence/RUNTIME/tdd/` receipts.
  - impl: Add test and guard code only. Do not modify production, public docs, package metadata, lockfiles, environment examples, or the existing frozen contract tests.
  - verify: Run the default and activated selectors in isolated processes, validate the RED-anchor inventory and `test_lane_chronology.v1` receipt, panel the exact tests-only diff under the authority active at dispatch, and land it before SL-1, SL-2, or SL-3 starts.

### SL-1 — Durable convergence event log

- **Scope**: Make the coordinator-owned JSONL log crash-safe, replay-safe, and reconstructable without widening into coordinator behavior.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`
- **Interfaces provided**: event log implementation
- **Interfaces consumed**: immutable RUNTIME tests, `CoordinatorEvent` (pre-existing), `CoordinatorEventKind` (pre-existing), IF-0-RUNTIME-1 (pre-existing)
- **Parallel-safe**: yes; after SL-0, this file is disjoint from SL-2 and SL-3 and may use a scheduler-owned isolated worktree under the single selected author vendor.
- **Tasks**:
  - test: Consume SL-0 unchanged and confirm the event-log RED anchors fail on the current short-write, torn-tail, and process-concurrency gaps before implementation.
  - impl: Preserve canonical metadata-only JSON lines and the 64-KiB bound; add a fully drained append, durable flush/fsync, parent-directory durability where creation requires it, cross-process single-writer serialization, and safe torn-final-record repair without accepting corruption before the final record.
  - impl: Enforce exact intent/outcome key matching, identical replay idempotence, conflicting duplicate and mixed train/version ambiguity, monotonic epochs, deterministic last-outcome folding, pending-attempt recovery, and an event offset that identifies the last durable record. Never write below any `.phase-loop/` path or read transcripts.
  - verify: `cd phase-loop-runtime && env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=src python3 -m pytest -q tests/test_convergence_event_log.py tests/test_convergence_event_contracts.py`.

### SL-2 — Exact-state reconciliation

- **Scope**: Resolve every IF-0-FREEZE-5 authority from fresh read-only probes and invalidate approval/verification on the exact normative triggers.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py`
- **Interfaces provided**: reconciliation implementation
- **Interfaces consumed**: immutable RUNTIME tests, `RecoveredTrainState` (pre-existing), `AuthoritySource` (pre-existing), `InvalidationTrigger` (pre-existing), `ReconciliationBinding` (pre-existing), IF-0-RUNTIME-1 (pre-existing)
- **Parallel-safe**: yes; after SL-0, this file is disjoint from SL-1 and SL-3 and consumes only plan-frozen/pre-existing shapes.
- **Tasks**:
  - test: Consume SL-0 unchanged and confirm the current implementation misses the complete authority split, fresh-probe behavior, registry divergence arm, and one-for-one invalidation emission.
  - impl: Invoke Git, GitHub, provider, and registry probes afresh for every decision; keep observations metadata-only; fail closed on a missing, errored, malformed, stale, or ambiguous required probe; and never treat cached state, transcripts, or `.phase-loop/` as a substitute.
  - impl: Select ROADMAP for intent-only, EVENT_LOG for an active operation, GIT_HEAD for implementation/PR head, MERGED_SHA for observed merge, and REGISTRY_MANIFEST for observed release. Emit each changed-code/roadmap/base/dependency/verification-plan enum exactly once, bind supported authority/invalidation versions, and clear verification/approval validity whenever any trigger fires.
  - verify: `cd phase-loop-runtime && env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=src python3 -m pytest -q tests/test_convergence_reconcile.py tests/test_convergence_coordination_contracts.py tests/test_convergence_provider_contracts.py`.

### SL-3 — Adapter envelopes and transcript-free status

- **Scope**: Complete the three non-coordinating adapters and the event-log-only status/CLI projection without touching train coordination or broker effects.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/claude.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/outside_agent.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/status.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- **Interfaces provided**: adapter and status implementation
- **Interfaces consumed**: immutable RUNTIME tests, `AdmissionRequest` (pre-existing), `ConvergenceResultEnvelope` (pre-existing), `ConvergenceResultStatus` (pre-existing), `RecoveredTrainState` (pre-existing), `validate_outside_agent_submission` (pre-existing), IF-0-RUNTIME-1 (pre-existing)
- **Parallel-safe**: yes; after SL-0, this file set is disjoint from SL-1 and SL-2, and `cli.py` has one RUNTIME writer.
- **Tasks**:
  - test: Consume SL-0 unchanged and prove all adapters return the same frozen envelope for success, verified, blocked, clarification, degraded, failure, malformed output, nonzero exit, timeout, and outside-agent conformance failure while preserving attempt and expected-version bindings.
  - test: Prove `train-status --event-log PATH [--json]` reconstructs intent-only, completed, invalidated, mixed-version, epoch-regressed, and ambiguous-provider histories after restart with transcripts and repo-local runner state absent, while legacy `--train` bytes and read-only behavior remain unchanged.
  - impl: Require exact provider executable identity rather than prefix matching; reuse the central subscription and mutation-credential scrubbers; use bounded argv/cwd/time/output, a fully reclaimed process group on timeout, metadata-only diagnostics, and the pre-existing outside-agent validator. Adapters execute exactly one permitted action, carry the admission predicate unchanged, and import no train coordinator, publisher, merge, release, package, or broker adapter.
  - impl: Make status output deterministic and explicit about log identity/offset, pending attempts, node outcomes, verification/approval validity, ambiguities, authority/invalidation facts, and non-secret next action. Keep `train-status --event-log` mutually exclusive with `--train`, read-only, and compatible with the existing Python console-script entrypoint.
  - verify: `cd phase-loop-runtime && env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=src python3 -m pytest -q tests/test_convergence_adapters.py tests/test_convergence_status.py tests/test_cli_train_status_45.py tests/test_convergence_fixture_contracts.py`.

### SL-4 — Runtime integration reducer

- **Scope**: Integrate the three functional writers and expose the completed public runtime gate after all producer behavior is known.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/__init__.py`
- **Interfaces provided**: RUNTIME integration output
- **Interfaces consumed**: immutable RUNTIME tests, event log implementation, reconciliation implementation, adapter and status implementation
- **Parallel-safe**: no; this synthesized public-surface writer depends on every functional producer.
- **Tasks**:
  - test: Consume the SL-0 import, integration, documentation, and chronology assertions without editing them.
  - impl: Export the exact IF-0-RUNTIME-1 surface and `RUNTIME_CAPABILITY_VERSION = 1` only after all three producer heads integrate. Do not change frozen `CoordinatorEvent`, `ConvergenceResultEnvelope`, `AdmissionRequest`, `AuthoritySource`, or `InvalidationTrigger` shapes.
  - verify: Run all activated focused tests, import the public package in a fresh process, and confirm SL-0 has no diff from its tests-only landing.

### SL-5 — Documentation and whole-phase verification reducer

- **Scope**: Reduce the final public documentation and prove every RUNTIME goal and gate on the integrated head without repairing producer-owned files.
- **Owned files**: `docs/phase-loop/convergence-runtime.md`
- **Interfaces provided**: RUNTIME documentation and verification evidence
- **Interfaces consumed**: immutable RUNTIME tests, event log implementation, reconciliation implementation, adapter and status implementation, RUNTIME integration output
- **Parallel-safe**: no; this terminal synthesized writer and verifier runs after every producer.
- **Tasks**:
  - test: Consume the SL-0 documentation assertions, then validate roadmap/plan contracts, the retained TDD chronology receipt, every activated focused test, the frozen convergence contracts, legacy train status, the complete non-dotfiles suite, and lint.
  - impl: Update `docs/phase-loop/convergence-runtime.md` with durability/corruption/replay semantics, live authority precedence and invalidation, adapter bounds and expected-version carriage, event-log-only status usage, metadata-only redaction, and the RUNTIME/REVIEWTRUTH/INTEG/BROKER ownership split. Record `no_doc_delta` for README.md, CHANGELOG.md, and release notes because RUNTIME changes no install, release, or package surface.
  - impl: Do not repair producer-owned files in this lane. Route any failure to the sole owning lane, require a new exact-head review after a material repair, and rerun the complete reducer.
  - verify: Run the exact commands in `## Verification`, retain runner-owned JUnit and verification evidence, and list IF-0-RUNTIME-1 in the phase closeout only after every command passes.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- plan: executor=`codex`, model=`gpt-5.6-sol`, effort=`max`, work-unit=`phase_plan`, unsupported=`block`, inherit-default=`false`, policy-source=`roadmap`, reason=`v10 planning policy; CLI/operator override remains higher precedence`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`, reason=`coordinator must supply the explicit whole-phase author executor at dispatch`
- SL-4: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-5: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- Policy precedence is CLI/operator override, this phase-plan policy, roadmap policy, `Dispatch Hints`, then registry defaults. No unsupported executor/model/effort may silently downgrade; this plan blocks rather than falling back. The coordinator selects one explicit author executor from the rotation active at dispatch and keeps that vendor for SL-1 through SL-4. Runtime lane schedulers remain off; SL-1, SL-2, and SL-3 may fan out only through same-vendor workers in scheduler-owned isolated worktrees after machine verification of the disjoint path sets. SL-0, SL-4, and SL-5 are serial reducers.
- PROOFGATE is complete on this planning base. Before execution, recheck that the exact dispatch base still records PROOFGATE completed in the phase ledger; otherwise stop with `upstream_phase_unmet`. Planning or worktree-local runner state does not substitute for that completed lifecycle record.
- EC-RUNTIME-0 is literal. SL-0 lands and receives the required governed review before any production change. SL-1 through SL-4 may never edit an SL-0 path. The runner-stamped chronology receipt binds the exact base, tests-only head/landing, plan and roadmap digests, collected node IDs, injection anchors, default-green and activated-RED results, and the first production parent without prescribing future SHA values or commit counts in this plan.
- The existing skeleton is baseline code, not acceptance evidence. A new falsifier that unexpectedly passes on the exact pre-production base is not RED and must be repaired in SL-0 before landing; a collection/import failure is not an accepted RED result.
- The complete phase-owned write set is the union of SL-0 through SL-4. `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `runner.py`, `injection.py`, `panel_invoker.py`, all broker/publishing modules, frozen convergence contract files/tests, `pyproject.toml`, lockfiles, environment examples, migrations, README, and CHANGELOG remain out of scope.
- IF-0-VC-2 command preflight is satisfied only when `validate_plan_doc.py` resolves the anchored roadmap and complete goal coverage, `verification_commands_from_plan` extracts the commands below, and `resolve_suite_command_doc` resolves the frontmatter `automation.suite_command` without a finding. Collection-only, skipped activated falsifiers, stale-head output, or prose-only claims are not passing evidence.
- The RUNTIME deliverable is non-visual. No avatar, browser-media, or visible-render evidence is required; execution closeout sets `visual_render_declared=false`.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/**`, `plans/**`
- evidence paths: `.phase-loop/evidence/RUNTIME/spec-delta-closeout.json`, `.phase-loop/evidence/RUNTIME/tdd/`, `.phase-loop/runs/*/verification.json`, `plans/phase-plan-v10-RUNTIME.md`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment`

This metadata-only closeout routing preserves the roadmap's declared decision and does not grant
an implementation lane permission to edit the protected roadmap or this plan. The amendment must
record the re-grounding/supersession decision and exact RUNTIME evidence without future-history
pins or raw transcripts, provider payloads, credentials, environment values, or private paths.

## Verification

```bash
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md
PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-RUNTIME.md

env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 \
  PYTHONPATH=phase-loop-runtime/src \
  python3 -m pytest -q \
  phase-loop-runtime/tests/test_convergence_event_log.py \
  phase-loop-runtime/tests/test_convergence_reconcile.py \
  phase-loop-runtime/tests/test_convergence_adapters.py \
  phase-loop-runtime/tests/test_convergence_status.py \
  phase-loop-runtime/tests/test_convergence_runtime_imports.py \
  phase-loop-runtime/tests/test_cli_train_status_45.py \
  phase-loop-runtime/tests/test_convergence_event_contracts.py \
  phase-loop-runtime/tests/test_convergence_coordination_contracts.py \
  phase-loop-runtime/tests/test_convergence_provider_contracts.py \
  phase-loop-runtime/tests/test_convergence_fixture_contracts.py

PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"
ruff check phase-loop-runtime/src/phase_loop_runtime/
git diff --check
```

## Acceptance Criteria

- [ ] EC-RUNTIME-0 — proven by `PHASE_LOOP_RUNTIME_TDD_RECEIPT=.phase-loop/evidence/RUNTIME/tdd/chronology.json PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_convergence_runtime_imports.py -k "runtime_tdd_chronology"`; falsified by a production change preceding the tests-only landing, any later SL-0 diff, or an activated case missing its unique RED anchor; path-entered control: the receipt records every injection anchor before the expected assertion and also records the ordinary default-green run.
- [ ] EC-RUNTIME-1 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_event_log.py`; falsified by accepting a dropped intent, partial/torn committed record, conflicting replay, concurrent write loss, mixed version, epoch regression, or restart mismatch; path-entered control: a complete intent/outcome pair survives restart and folds to the expected state.
- [ ] EC-RUNTIME-2 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_reconcile.py`; falsified by any changed Git/GitHub/provider/registry observation escaping its authority verdict or normative invalidation trigger; path-entered control: a fresh matching four-domain observation emits the expected authority with zero invalidations.
- [ ] EC-RUNTIME-3 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_adapters.py`; falsified by an adapter accepting a wrong executable, dropping the expected-version binding, leaking credentials, leaving a timed-out child, coordinating a train, or returning a non-frozen envelope; path-entered control: each provider adapter executes one bounded valid request and returns the expected frozen status and attempt identity.
- [ ] EC-RUNTIME-4 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_status.py phase-loop-runtime/tests/test_cli_train_status_45.py phase-loop-runtime/tests/test_convergence_runtime_imports.py`; falsified by transcript/cache deletion changing the ledger-derived result, restart losing state, event-log mode mutating bytes, or legacy CLI drift; path-entered control: identical durable events render identical JSON and human output before and after restart.
- [ ] EC-RUNTIME-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_runtime_imports.py -k "runtime_v10_reground"`; the assertion consumes `v10-RUNTIME.lifecycle[0].metadata.planning_base`, the plan's verified roadmap seal, the committed `v10-RUNTIME` manifest row, and the retained orphaned `vergence-v1-RUNTIME` row; falsified by the old plan becoming selectable or the current re-grounding record becoming absent, malformed, or non-ancestral to the execution base; path-entered control: the new plan resolves uniquely while the provenance-only row remains queryable and orphaned.
- [ ] IF-0-RUNTIME-1 — proven by the frontmatter `automation.suite_command` plus `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`; falsified by any frozen public symbol, invariant, owned-path boundary, or closeout gate missing from the integrated plan/evidence; path-entered control: a valid intent/outcome/reconciliation/adapter/status flow imports through the public package and closeout lists `IF-0-RUNTIME-1` with no dirty path outside SL-0 through SL-5.
