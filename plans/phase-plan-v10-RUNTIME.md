---
phase_loop_plan_version: 1
phase: RUNTIME
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 09c6544ec85558bcbd16589c01ac2fd5d01ff2ef2faf5864a77045ba0fd1f40e
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
      phase-loop-runtime/tests/test_convergence_fixture_contracts.py
      phase-loop-runtime/tests/test_runtime_current_acceptance.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration";
      ruff check phase-loop-runtime/src/phase_loop_runtime/
---

# RUNTIME: Runtime Substrate

## Context

RUNTIME completes the non-broker convergence skeleton on its recorded ancestral planning input.
The manifest records LEGIBLE and PROOFGATE `completed` and RUNTIME `committed`; worktree-local
state cannot override it.

The superseded 2026-07-13 `plans/phase-plan-vergence-v1-RUNTIME.md` remains provenance. Main's
Consiliency/agent-harness#197 skeleton lacks proof of crash-safe writes, fresh four-domain authority,
strict adapter fencing, and transcript-free reconstruction. RUNTIME lands falsifiers before repair.

REVIEWTRUTH owns advisor-seat lifecycle persistence. RUNTIME may replay existing seat outcomes but
does not create them or claim EC-REVIEWTRUTH-11. INTEG, FABPUB/FABREADMIT, and RELEASE retain DAG
coordination, downstream refresh, publication, and credential-bearing broker effects.

## Interface Freeze Gates

- [ ] IF-0-RUNTIME-1 — INTEG consumes the existing public runtime API without a second coordinator
  or broker: `default_convergence_event_log_path(coordinator_root: Path, train_id: str) -> Path`;
  `record_intent(path: Path, event: CoordinatorEvent) -> None`; `record_outcome(path: Path, event:
  CoordinatorEvent) -> None`; `read_convergence_events(path: Path) -> tuple[CoordinatorEvent, ...]`;
  `recover_train_state(events: Iterable[CoordinatorEvent]) -> RecoveredTrainState`;
  `reconcile_train_state(state: RecoveredTrainState, probes: ExactStateProbes) ->
  ReconciliationVerdict`; `build_train_status(state: RecoveredTrainState, event_log_path: Path | str
  = "") -> TrainStatusSnapshot`; and `render_train_status(snapshot: TrainStatusSnapshot, *, as_json:
  bool = False) -> str`. `RecoveredTrainState` retains `train_id`, unmatched intents, latest epoch,
  validity, ambiguities, and `node_states`; its `last_event_offset` is the zero-based durable-record
  index (`-1` when empty). Replay order deterministically retains the last durable event of either
  kind per `node_id`; exact `(train_id, node_id, attempt_id, epoch)` keys govern intent/outcome and
  pending-attempt folds. `ReconciliationVerdict` retains one versioned `ReconciliationBinding`,
  fresh metadata-only observations, a non-secret blocker reason, and `checked_at`.
  `TrainStatusSnapshot` projects only `RecoveredTrainState` plus event-log path. Its
  `verification_valid` and `approval_valid` are replay-derived ledger facts, never fresh authority;
  SL-2's live `ReconciliationVerdict` alone carries authority, observations, blocker reason,
  `checked_at`, and invalidation triggers for INTEG. No `CoordinatorEvent` or status signature
  changes. Intent is durable before return; outcomes require a prior exact-key intent; identical
  replay is idempotent; conflicting duplicates, mixed versions, epoch regression, corrupt committed
  records, missing authority, and ambiguous provider outcomes fail closed. Reconciliation freshly
  probes Git, GitHub, provider, and registry, selects only IF-0-FREEZE-5 authority values, and emits
  exact `InvalidationTrigger` values. Transcripts and `.phase-loop/` are recovery evidence only.
  `AdapterExecutionRequest` preserves the seven-field `AdmissionRequest` and nonempty exact-version
  predicate; Codex, Claude, and outside-agent adapters perform one bounded non-coordinating action
  and return only `ConvergenceResultEnvelope`. The terminal reducer alone exports
  `RUNTIME_CAPABILITY_VERSION = 1` after all functional writers integrate.

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

- **Scope**: Land the complete RUNTIME falsifier set, tests-only adapter, default-green/activated-RED evidence, and content receipt before production edits.
- **Owned files**: `phase-loop-runtime/tests/runtime_content_tdd_adapter.py`, `phase-loop-runtime/tests/_runtime_tdd_guard.py`, `phase-loop-runtime/tests/test_convergence_event_log.py`, `phase-loop-runtime/tests/test_convergence_reconcile.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_convergence_status.py`, `phase-loop-runtime/tests/test_convergence_runtime_imports.py`, `phase-loop-runtime/tests/test_cli_train_status_45.py`
- **Interfaces provided**: `immutable RUNTIME tests`, `runtime_content_tdd_adapter.v1`, `exact per-case production-target/RED-anchor map`, `content-bound RUNTIME receipt`
- **Interfaces consumed**: `CoordinatorEvent`, `ConvergenceResultEnvelope`, `AdmissionRequest`, `AuthoritySource`, `InvalidationTrigger`, `ContentTddReceipt`, `RED_ANCHOR_MARKER`, `select_declared_commit` (pre-existing)
- **Parallel-safe**: no; this is the single pre-production tests-only boundary.
- **Tasks**:
  - test: Add `runtime_content_tdd_adapter.py` as a tests-only wrapper over unchanged `phase_loop_runtime.tdd_receipts`. Its closed inventory is exactly its own path, `_runtime_tdd_guard.py`, and the six focused test modules listed above. Its closed per-case map binds one `(lane, production path, symbol, anchor)` in the exact SL-1/SL-2/SL-3 production unions, rejects every test/helper/guard target, and proves the symbol's source was entered before its unique anchor.
  - test: Add `_runtime_tdd_guard.py` with activation `PHASE_LOOP_TDD_EXPECT_RUNTIME=1`, lazy probes, unique `RUNTIME-RED-ANCHOR::<case>` failures, and exact collected-node accounting. The import fence explicitly forbids `GitHubBrokerAdapter`, `BrokerEnvironmentBoundary`, `BrokerProviderAdapter`, `BrokerClient`, `BrokerService`, `build_github_broker_client`, `build_routing_broker_client`, and `publish_committed_branch_idempotency_key`; it permits the pure `credsep.strip_mutation_credentials` scrubber and its pure helper constants, so no module-prefix ban rejects that required import.
  - test: Expand the six focused test modules (including `test_cli_train_status_45.py`) for torn/short/cross-process appends, replay/version/epoch conflict, fresh four-domain authority/invalidation, adapter executable/environment/version/result/timeout fences, restart-only status, stable JSON/human output, legacy `--train`, and the public surface.
  - test: From the exact production-free base, require default GREEN (guarded new cases may skip only for missing capability) and activated exit 1 solely at the complete typed anchor inventory. After the reviewed tests-only landing declares `Phase-Loop-Identity: runtime-tests-freeze-v1`, run `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m runtime_content_tdd_adapter record --repo . --landing-remote origin --landing-branch main --identity runtime-tests-freeze-v1` from that base.
  - test: `record` calls `record_content_tdd_receipt`, supplies its frozen GOVLEAN marker only for generic-recorder compatibility, and writes a digest-bound `runtime_content_tdd_adapter.v1` companion. Default paths are this plan, its roadmap, `.phase-loop/evidence/RUNTIME/tdd/content-tdd-receipt.json`, and `.phase-loop/evidence/RUNTIME/tdd/runtime-content-tdd-binding.json`. The companion binds RUNTIME activation/typed markers, exact node/test/target inventories, default/RED JUnit and raw digests, base/landing identity and ancestry, plan/roadmap digests, and the declared tests landing as the expected first-production parent.
  - impl: Add only these test/support bytes; never edit production, public docs, metadata, lockfiles, env examples, or frozen contract tests.
  - verify: Before any producer starts, verify the generic receipt plus companion and panel/land the exact tests-only diff. At whole-phase closeout run `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m runtime_content_tdd_adapter verify --repo . --landing-remote origin --landing-branch main --identity runtime-tests-freeze-v1 --head HEAD`; it fails on receipt/digest/inventory drift, later SL-0 edits, any production change before the landing, or a first production commit whose parent is not the declared landing.

### SL-1 — Durable convergence event log

- **Scope**: Make the coordinator-owned JSONL log crash-safe, replay-safe, and reconstructable without widening into coordinator behavior.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`
- **Interfaces provided**: event log implementation
- **Interfaces consumed**: immutable RUNTIME tests, `CoordinatorEvent` (pre-existing), `CoordinatorEventKind` (pre-existing), IF-0-RUNTIME-1 (pre-existing)
- **Parallel-safe**: yes; after SL-0, this file is disjoint from SL-2 and SL-3 and may use a scheduler-owned isolated worktree under the single selected author vendor.
- **Tasks**:
  - test: Consume SL-0 unchanged and confirm the event-log RED anchors fail on the current short-write, torn-tail, and process-concurrency gaps before implementation.
  - impl: Preserve canonical metadata-only JSON lines and the 64-KiB bound; add a fully drained append, durable flush/fsync, parent-directory durability where creation requires it, cross-process single-writer serialization, and safe torn-final-record repair without accepting corruption before the final record.
  - impl: Enforce exact-key intent/outcome matching, replay idempotence, conflicts, mixed train/version ambiguity, monotonic epochs, pending recovery, zero-based durable-record offsets, and replay-order last-event-per-node folding. Never write below `.phase-loop/` or read transcripts.
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
- **Interfaces consumed**: immutable RUNTIME tests, `AdmissionRequest` (pre-existing), `ConvergenceResultEnvelope` (pre-existing), `ConvergenceResultStatus` (pre-existing), `RecoveredTrainState` (pre-existing), `validate_outside_agent_submission` (pre-existing), `scrub_subscription_env` (pre-existing), `strip_mutation_credentials` (pre-existing), IF-0-RUNTIME-1 (pre-existing)
- **Parallel-safe**: yes; after SL-0, this set is disjoint from SL-1 and SL-2; the coordinator separately serializes RUNTIME against RESIDUAL's `cli.py` writer.
- **Tasks**:
  - test: Consume SL-0 unchanged and prove all adapters return the same frozen envelope for success, verified, blocked, clarification, degraded, failure, malformed output, nonzero exit, timeout, and outside-agent conformance failure while preserving attempt and expected-version bindings.
  - test: Prove `train-status --event-log PATH [--json]` reconstructs intent-only, completed, verification/approval-invalid, mixed-version, epoch-regressed, and ambiguous-provider histories after restart with transcripts and repo-local runner state absent, while legacy `--train` bytes and read-only behavior remain unchanged.
  - impl: Require exact executable identity; apply only the pure `phase_loop_runtime.advisor_board.backing.scrub_subscription_env` and `phase_loop_runtime.convergence.broker.credsep.strip_mutation_credentials` helpers without editing them or importing any SL-0-forbidden broker symbol. Bound argv/cwd/time/output, reclaim timeout process groups, keep diagnostics metadata-only, use the outside-agent validator, preserve the admission predicate, and import no coordinator/publisher/merge/release/package path.
  - impl: Make status deterministic from recovered ledger state and log identity. Label human `verification_valid`/`approval_valid` as replay-derived; retain JSON field names but document the same semantics. Never synthesize/persist live `ReconciliationVerdict` authority. Keep `train-status --event-log` read-only, mutually exclusive with `--train`, and console-entrypoint compatible.
  - verify: `cd phase-loop-runtime && env PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=src python3 -m pytest -q tests/test_convergence_adapters.py tests/test_convergence_status.py tests/test_cli_train_status_45.py tests/test_convergence_fixture_contracts.py`.

### SL-4 — Runtime integration reducer

- **Scope**: Integrate the three functional writers and expose the completed public runtime gate after all producer behavior is known.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/__init__.py`
- **Interfaces provided**: RUNTIME integration output
- **Interfaces consumed**: immutable RUNTIME tests, event log implementation, reconciliation implementation, adapter and status implementation
- **Parallel-safe**: no; this synthesized public-surface writer depends on every functional producer.
- **Tasks**:
  - test: Consume the SL-0 import, integration, documentation, and chronology assertions without editing them.
  - impl: Additively export the exact IF-0-RUNTIME-1 surface and `RUNTIME_CAPABILITY_VERSION = 1` only after all three producer heads integrate; preserve every existing BROKER/INTEG export. Do not change frozen `CoordinatorEvent`, `ConvergenceResultEnvelope`, `AdmissionRequest`, `AuthoritySource`, or `InvalidationTrigger` shapes.
  - verify: Run all activated focused tests, import the public package in a fresh process, and confirm SL-0 has no diff from its tests-only landing.

### SL-5 — Documentation and whole-phase verification reducer

- **Scope**: Reduce the final public documentation and prove every RUNTIME goal and gate on the integrated head without repairing producer-owned files.
- **Owned files**: `docs/phase-loop/convergence-runtime.md`
- **Interfaces provided**: RUNTIME documentation and verification evidence
- **Interfaces consumed**: immutable RUNTIME tests, event log implementation, reconciliation implementation, adapter and status implementation, RUNTIME integration output
- **Parallel-safe**: no; this terminal synthesized writer and verifier runs after every producer.
- **Tasks**:
  - test: Consume SL-0 unchanged; validate roadmap/plan/manifest and extraction contracts, the retained content receipt, focused/frozen/legacy behavior, full non-dotfiles suite, and lint.
  - impl: Document durability/corruption/replay, adapter/version bounds, metadata-only redaction, ownership, and event-log status. Explicitly distinguish replay-derived snapshot validity from fresh live `ReconciliationVerdict` authority/invalidation. Record `no_doc_delta` for README, CHANGELOG, and release notes.
  - impl: Do not repair producer-owned files in this lane. Route any failure to the sole owning lane, require a new exact-head review after a material repair, and rerun the complete reducer.
  - verify: Run the exact commands in `## Verification`, retain runner-owned JUnit and verification evidence, and list IF-0-RUNTIME-1 in the phase closeout only after every command passes.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`, reason=`coordinator must supply the explicit whole-phase author executor at dispatch`
- SL-4: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-5: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- Policy precedence is operator/CLI, this plan, roadmap, `Dispatch Hints`, then defaults; unsupported policy blocks. The coordinator selects one whole-phase author vendor for SL-0 through SL-5. Runtime lane scheduling stays off; after machine-checked disjointness, only same-vendor workers in assigned worktrees may fan out SL-1/SL-2/SL-3. Reducers remain serial.
- At dispatch recheck PROOFGATE `completed` in the manifest ledger or stop `upstream_phase_unmet`; planning/local runner state is no substitute.
- EC-RUNTIME-0 remains literal, unchecked, and `unproven_evidence_loss`. Preserve the original eight-file snapshot, the legacy verifier, and its archived failure. The reviewed current `test_convergence_runtime_imports.py` byte is also authoritative for the current candidate and must not be reverted: its historical assertion uses the first authority while its current-byte assertion uses the latest authority. EC-RUNTIME-6 is a distinct current-candidate route under the roadmap's RUNTIME-only disposition; it neither satisfies EC-RUNTIME-0 nor opens another criterion or phase.
- An unexpectedly passing new falsifier, collection/import failure, skipped activated case, missing/duplicate marker, helper target, or unentered production symbol is not RED. Repair SL-0 before its landing.
- Phase ownership is the lane union. `train_runner.py`, `runner.py`, `injection.py`, `panel_invoker.py`, broker/publishing modules, frozen contracts/tests, `goal_coverage.py`, package/lock/env/migration files, README, and CHANGELOG stay out. The `is_production_construction_site` RUNTIME-helper classifier gap is a downstream repository follow-up; RUNTIME only rejects it in its adapter and never edits the classifier.
- Serialize RUNTIME and RESIDUAL until RUNTIME releases `cli.py`; they never execute concurrently.
- IF-0-VC-2 requires plan/roadmap/manifest and dispatch-literal validation, exactly twelve extracted commands with no operational fragments, and a resolved frontmatter suite. Prose, stale-head output, or collection-only evidence cannot pass.
- This phase is non-visual; closeout sets `visual_render_declared=false`.
- Carrier adds metadata only. The catalog is EC-RUNTIME-6's normative contract; EC-RUNTIME-6 remains red until reviewed code and closeout enforcement exist.
- Before review, stage the supported IF-0-REVIEWTRUTH-3 result before Opus. `DEGRADED_NO_LAUNCH` records failed strict preflight and zero processes; it is no vote or `can_probe` success, and no subagent substitutes.
- Sol authorship requires EC-GOVLEAN-7 non-author-vendor ablation before ratification. The active interim note requires exact-head 4/4, removes president, and post-GOVLEAN authority has no separate chair.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/**`, `plans/**`
- evidence paths: `.phase-loop/evidence/RUNTIME/spec-delta-closeout.json`, `.phase-loop/evidence/RUNTIME/tdd/`, `.phase-loop/runs/*/verification.json`, `plans/phase-plan-v10-RUNTIME.md`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment`

This metadata-only closeout routing preserves the roadmap's declared decision and does not grant
an implementation lane permission to edit the protected roadmap or this plan. The amendment must
record the re-grounding/supersession decision, exact RUNTIME evidence, and RUNTIME/RESIDUAL
`cli.py` serialization without future-history pins or raw transcripts, provider payloads,
credentials, environment values, or private paths.

## Retained Historical Failure

The legacy command remains `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m runtime_content_tdd_adapter verify --repo . --landing-remote origin --landing-branch main --identity runtime-tests-freeze-v1 --head HEAD`. Its archived exit is `1`, diagnosed as missing `content-tdd-receipt.json`; the retained record is `review-evidence/decision-review-r1-attempt2/bundle.md`, SHA256 `44ebdf11ce30b65a415bee51c8cfb9fb2f284c76cf72ac66083d9b61266fb1f3`. This is historical evidence, not a green admission command.

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-RUNTIME.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.plan_manifest check --repo .`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; p=Path("plans").joinpath("phase-plan-v10-RUNTIME.md"); f=validate_plan_dispatch_hints(p.read_text()); assert not f,f'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.discovery import verification_commands_from_plan; p=Path("plans").joinpath("phase-plan-v10-RUNTIME.md"); c,o=verification_commands_from_plan(p); assert len(c)==12 and all(c) and not o,(c,o); print(c)'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.runtime_current_acceptance audit-history --repo . --inventory plans/evidence/v10-RUNTIME-evidence-loss-reference-closure.v1.json`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.runtime_current_acceptance verify --repo . --receipt .phase-loop/evidence/RUNTIME/current/runtime-current-acceptance.json --custody-observation .phase-loop/evidence/RUNTIME/current/runtime-current-acceptance-custody.json --candidate HEAD`
- `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_event_log.py phase-loop-runtime/tests/test_convergence_reconcile.py phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_convergence_status.py phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_cli_train_status_45.py phase-loop-runtime/tests/test_convergence_event_contracts.py phase-loop-runtime/tests/test_convergence_coordination_contracts.py phase-loop-runtime/tests/test_convergence_provider_contracts.py phase-loop-runtime/tests/test_convergence_fixture_contracts.py phase-loop-runtime/tests/test_runtime_current_acceptance.py`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `python3 -c 'from pathlib import Path; p=Path("plans").joinpath("phase-plan-v10-RUNTIME.md"); n=len(p.read_text().split()); print(n); assert n<=3000'`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-RUNTIME-0 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m runtime_content_tdd_adapter verify --repo . --landing-remote origin --landing-branch main --identity runtime-tests-freeze-v1 --head HEAD`; falsified by receipt/binding drift, production preceding the tests landing, any later SL-0 byte change, a missing/duplicate/unentered typed RED anchor, a non-production target, or a first production parent other than the declared tests landing; path-entered control: every case records its exact resolved production symbol before its unique assertion and rejects every test/helper/guard target. **Historical disposition: `unproven_evidence_loss`; non-admitting; never check this box through EC-RUNTIME-6.**
- [ ] EC-RUNTIME-1 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_event_log.py`; falsified by accepting a dropped intent, partial/torn committed record, conflicting replay, concurrent write loss, mixed version, epoch regression, or restart mismatch; path-entered control: a complete intent/outcome pair survives restart and folds to the expected state.
- [ ] EC-RUNTIME-2 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_reconcile.py`; falsified by any changed Git/GitHub/provider/registry observation escaping its authority verdict or normative invalidation trigger; path-entered control: a fresh matching four-domain observation emits the expected authority with zero invalidations.
- [ ] EC-RUNTIME-3 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_adapters.py`; falsified by an adapter accepting a wrong executable, dropping the expected-version binding, leaking credentials, leaving a timed-out child, coordinating a train, or returning a non-frozen envelope; path-entered control: each provider adapter executes one bounded valid request and returns the expected frozen status and attempt identity.
- [ ] EC-RUNTIME-4 — proven by `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_status.py phase-loop-runtime/tests/test_cli_train_status_45.py phase-loop-runtime/tests/test_convergence_runtime_imports.py`; falsified by transcript/cache deletion changing the ledger-derived result, restart losing state, event-log mode mutating bytes, or legacy CLI drift; path-entered control: identical durable events render identical JSON and human output before and after restart.
- [ ] EC-RUNTIME-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_convergence_runtime_imports.py -k "runtime_v10_reground"`; the assertion consumes `v10-RUNTIME.lifecycle[0].metadata.planning_base`, the plan's verified roadmap seal, the committed `v10-RUNTIME` manifest row, and the retained orphaned `vergence-v1-RUNTIME` row; falsified by the old plan becoming selectable or the current re-grounding record becoming absent, malformed, or non-ancestral to the execution base; path-entered control: the new plan resolves uniquely while the provenance-only row remains queryable and orphaned.
- [ ] EC-RUNTIME-6 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.runtime_current_acceptance verify --repo . --receipt .phase-loop/evidence/RUNTIME/current/runtime-current-acceptance.json --custody-observation .phase-loop/evidence/RUNTIME/current/runtime-current-acceptance-custody.json --candidate HEAD`; the exact roadmap criterion governs; falsified by any catalog mutation passing; path-entered control: each row records candidate source and symbol entry.
- [ ] IF-0-RUNTIME-1 — proven by the frontmatter `automation.suite_command` plus `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`; falsified by any frozen public symbol, invariant, owned-path boundary, or closeout gate missing from the integrated plan/evidence; path-entered control: a valid intent/outcome/reconciliation/adapter/status flow imports through the public package and closeout lists `IF-0-RUNTIME-1` with no dirty path outside SL-0 through SL-5.
