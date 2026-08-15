---
phase_loop_plan_version: 1
phase: PROOFGATE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: c66949236043e46e956caec1c09d0c19d0e8751e4ce2891de1fe2edf24e9fea1
automation:
  suite_command: [bash, -lc, 'cd phase-loop-runtime && PYTHONPATH=src python -m pytest -m "not dotfiles_integration" -q && bash scripts/gate_a_cleanroom.sh']
---

# PROOFGATE: Falsifier Gate

## Context

PROOFGATE consumes landed `IF-0-GOVLEAN-1` content-bound TDD receipts and declared commit identities, plus LEGIBLE’s generic verification-evidence v3 registry, reader, and seal/reseal protocol. It adds no replacement receipt API and no bootstrap, workflow, provider-session, or external-head mechanism.

The phase has three implementation lanes and one writer-free coordinator gate. Test/support work lands first; production then executes strictly as `TG-PROOFGATE-0 → SL-1 → SL-0 → SL-2`. Owned-file sets are complete and disjoint. Shared and generated surfaces have one writer.

The grammar rejects missing falsifiers, vacuous falsifiers, and negative claims lacking path-entered controls unconditionally at validator, execution intake, and closeout. Exact same-ID complete raw bytes proven at the trusted cutoff are the sole warning-level grandfather case. Other unrelated Check P findings remain advisory.

Scope is this repository’s PROOFGATE surfaces only. Do not edit the roadmap, sibling repositories, canon, Governed Pipeline, or `tdd_receipts.py`. The sole write-capable review role is the isolated Opus early prover; critic and president roles are read-only.

## Interface Freeze Gates

- [ ] **IF-0-PROOFGATE-1 — Acceptance grammar and mutation evidence.**
  - `goal_coverage.extract_acceptance_contracts(...)` preserves each complete raw acceptance-item byte sequence and identifies its criterion ID, proof command, falsifier, negative-claim posture, and path-entered control.
  - `goal_coverage.check_acceptance_falsifiers(...)` returns typed dispositions. `missing_falsifier`, `vacuous_falsifier`, and `missing_path_entered_control` are invalid hard errors. Exact-byte cutoff proof returns `grandfathered` with the server-attested pre-grammar date. Non-invalid Check P advice remains warning-level.
  - The canonical Claude validator invokes that authoritative runtime contract. `runner.py` invokes the same contract through its shared intake and closeout paths without depending on `PHASE_LOOP_ACCEPTANCE_ENFORCE`.
  - The only extension namespace added by this phase is `phase_loop_runtime.proofgate_evidence`, schema `proofgate_evidence.v1`. Its mutation rows bind parameter ID, candidate/tree, target path/blob, unique injection anchor, command/argv/environment, selected node, expected rejection class, expected typed observable, baseline result, mutation result, and status.
  - Mutation statuses distinguish `killed`, `survived`, `mutation_not_applied`, and typed execution/evidence failures. Aggregate success requires every declared parameter to be present exactly once and `killed`.
- [ ] **TG-PROOFGATE-0 — Writer-free tests-only freeze gate.** Gemini 3.6 Flash authors all lane test/support changes before production work. A new bounded `proofgate_content_tdd_adapter.py` leaves the load-bearing legacy `proofgate_tdd_guard.py` API and consumers unchanged, imports `RED_ANCHOR_MARKER` from landed `tdd_receipts.py`, invokes the receipt recorder with a RED command prefixed by `env PHASE_LOOP_TDD_EXPECT_PROOFGATE=1`, asserts every injection anchor exactly once, and requires both the imported receipt marker and distinct `PROOFGATE_RED::<case-id>` markers. Default tests remain green; the activated pre-implementation run fails only at the intended assertions. The coordinator lands the frozen set with `Phase-Loop-Identity: proofgate-tests-freeze`, resolves it uniquely through `select_declared_commit`, and records/verifies a `ContentTddReceipt`. The gate authors no files and permits no later test/support edits.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `dotfiles_skill_source_update`
- documentation decision: `no_doc_delta` for README, CHANGELOG, and release-note surfaces; this phase changes only owned plan-phase skill guidance
- target surfaces: `skills-src/{claude,codex,gemini,opencode}/*-plan-phase/SKILL.md`, `phase-loop-skills/plan-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**`
- evidence paths: `.phase-loop/evidence/PROOFGATE/spec-delta-closeout.json`
- redaction posture: `metadata_only`
- malformed or missing evidence: non-human `blocker_class=contract_bug`
- downstream handling: `none`; record metadata-only references to the amended grammar and write neither sibling repositories, canon, nor Governed Pipeline

## Lane Index & Dependencies

SL-1 — Mutation evidence and namespace registration
  Depends on: (none)
  Blocks: SL-0, SL-2
  Parallel-safe: no

SL-0 — Grammar and runtime hard enforcement
  Depends on: SL-1
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Grandfathering, generated skill docs, and terminal reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Mutation evidence and namespace registration

- **Scope**: Freeze the mutation falsifiers, then implement exact-anchor mutation execution, per-parameter reduction, and the sole new v3 evidence namespace.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/tests/proofgate_content_tdd_adapter.py`, `phase-loop-runtime/tests/test_verification_evidence.py`, `phase-loop-runtime/tests/test_convergence_broker_revocation_race.py`, `phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json`
- **Interfaces provided**: `proofgate_tdd_adapter.v1`, `phase_loop_runtime.proofgate_evidence`, `proofgate_evidence.v1`, `mutation_not_applied`, `proofgate_parameter_reducer`
- **Interfaces consumed**: `ContentTddReceipt` (pre-existing), `RED_ANCHOR_MARKER` (pre-existing), `select_declared_commit` (pre-existing), `verification_evidence.v3` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `SL1-T0` | `test` | (none) | SL-1 test/support and mutation-manifest files | adapter activation, unique anchors, unmatched-anchor classification, genuine kill control, production-construction-site rows, and complete parameter reduction | `PHASE_LOOP_TDD_EXPECT_PROOFGATE=1 uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_verification_evidence.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py -k proofgate` |
| `SL1-I0` | `impl` | `TG-PROOFGATE-0` | `verification_evidence.py` only | frozen; edits forbidden | same focused command without forced RED must pass |
| `SL1-V0` | `verify` | `SL1-I0` | all SL-1 files | registry preservation, manifest execution, mutation state table, and v3 plan-aware validation | `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_verification_evidence.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py -k proofgate` |

### SL-0 — Grammar and runtime hard enforcement

- **Scope**: Implement the authoritative acceptance parser and enforce its invalid dispositions at the canonical validator, every shared execution-intake route, and both closeout reductions.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/tests/test_acceptance_falsifier_contract.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py`
- **Interfaces provided**: `extract_acceptance_contracts`, `check_acceptance_falsifiers`, `hard_acceptance_disposition`, `grandfathered_acceptance_disposition`
- **Interfaces consumed**: `proofgate_evidence.v1`, `proofgate_parameter_reducer`
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `SL0-T0` | `test` | (none) | SL-0 test files | grammar positives/negatives, advisory separation, validator exit status, direct/delegated/lane intake parity, and both closeout paths | `PHASE_LOOP_TDD_EXPECT_PROOFGATE=1 uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_acceptance_falsifier_contract.py phase-loop-runtime/tests/test_goal_coverage.py phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py -k proofgate` |
| `SL0-I0` | `impl` | `TG-PROOFGATE-0`, `SL1-V0` | three SL-0 production/source files | frozen; edits forbidden | focused tests pass with hard errors independent of warn-default environment |
| `SL0-V0` | `verify` | `SL0-I0` | all SL-0 files | validator/intake/closeout parity plus unrelated Check P advisory controls | `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_acceptance_falsifier_contract.py phase-loop-runtime/tests/test_goal_coverage.py phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py` |

### SL-2 — Grandfathering, generated skill docs, and terminal reducer

- **Scope**: Validate the historical corpus and exact-byte grandfather exception, publish the grammar through all canonical and generated plan-phase surfaces, and reduce metadata-only closeout evidence.
- **Owned files**: `phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py`, `phase-loop-runtime/tests/test_skills_canon_parity.py`, `phase-loop-runtime/tests/test_skills_bundle_drift.py`, `skills-src/claude/claude-plan-phase/SKILL.md`, `skills-src/codex/codex-plan-phase/SKILL.md`, `skills-src/gemini/gemini-plan-phase/SKILL.md`, `skills-src/opencode/opencode-plan-phase/SKILL.md`, `phase-loop-skills/plan-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**`, `.phase-loop/evidence/PROOFGATE/spec-delta-closeout.json`
- **Interfaces provided**: `plan_phase_falsifier_guidance`, `plan_phase_generated_parity`, `PROOFGATE_spec_closeout`
- **Interfaces consumed**: `hard_acceptance_disposition`, `grandfathered_acceptance_disposition`, `proofgate_evidence.v1`
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `SL2-T0` | `test` | (none) | three SL-2 tests | known-bad historical criteria, exact-byte cutoff warning, changed/new-byte rejection, four-source guidance, and generated parity | `PHASE_LOOP_TDD_EXPECT_PROOFGATE=1 uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py -k proofgate` |
| `SL2-I0` | `impl` | `TG-PROOFGATE-0`, `SL0-V0`, `SL1-V0` | four canonical skill docs | frozen tests remain unchanged | update the grammar and hard/warn semantics in all four sources |
| `SL2-I1` | `impl` | `SL2-I0` | neutral and packaged plan-phase outputs | frozen parity tests | `uv run --project phase-loop-runtime python phase-loop-runtime/scripts/regenerate_skills_bundle.py && uv run --project phase-loop-runtime python phase-loop-runtime/scripts/sync_skills_bundle.py` |
| `SL2-R0` | `verify` | `SL2-I1` | all SL-2 files and metadata-only closeout evidence | historical, parity, and drift suites | run the whole verification block, assert no out-of-scope diff, then write `spec_delta_closeout.v1` evidence |

## Dispatch Hints

- plan preferred executors: `codex`
- execute allowed executors: `gemini`
- review allowed executors: `claude`, `codex`, `grok`, `gemini`
- required capabilities: `live_launch`, `structured_output`, `explicit_approval_controls`

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`block`, inherit-default=`false`
- plan: executor=`codex`, model=`gpt-5.6-sol`, effort=`max`, work-unit=`phase_plan`, reason=`coordinator-only PROOFGATE planning override`
- SL-1: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, unsupported=`block`
- SL-0: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, unsupported=`block`
- SL-2: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`phase_reducer`, unsupported=`block`

## Execution Notes

1. Register this plan, perform the required cross-vendor ablation for its Sol authorship, and ratify its exact digest before `SL1-T0`, `SL0-T0`, or `SL2-T0`.
2. The operator directive for this coordinated run substitutes Grok 4.6 for Fable without changing shipped defaults. Hand-enforce the ratified topology through canonical `invoke_board`: the Opus 5 board seat runs first as the sole write-capable early prover in a coordinator-created disposable worktree and stages digest-bound evidence; Sol, Grok 4.5, and Gemini 3.6 Flash then review that immutable evidence as read-only critics. A separate read-only Grok 4.6 president rules on the completed four-seat record. Record the override in the phase ledger. Opus or Grok 4.6 unavailability blocks this run; do not descend the default ladder or edit runtime defaults.
3. Before tests, freeze `LEGIBLE_PREDECESSOR_INTERFACE_ANCHOR_V1` against the completion-ledger LEGIBLE landing and its recorded integration evidence: v3 support, generic registry/reader/seal-reseal, LEGIBLE namespace present, and PROOFGATE namespace absent. Gemini 3.6 Flash then authors the complete test/support set, using same-vendor workers for parallelism. Sol performs the grounded tests-only review. Retain default-green and activated-RED outputs, land the unchanged set with the declared identity, then have `proofgate_content_tdd_adapter.py` resolve that landing and record the content receipt. Every later task verifies the receipt before writing.
4. Keep PROOFGATE single-author-vendor: Gemini 3.6 Flash completes SL-1, SL-0, and SL-2 serially, with same-vendor workers allowed only inside a lane. No lane scheduler or reviewer may alter frozen tests. Re-run the exact-digest board and Grok 4.6 president after any material production fix; rotate the next roadmap phase to a different author vendor.
5. SL-0 must preserve advisory behavior for unrelated Check P findings while making the three invalid dispositions unconditional. Tests must exercise the shared runner helpers so direct, delegated, and lane-scheduled intake cannot diverge, cover both child reduction and final phase closeout, and target the canonical skills-src validator until SL-2 regenerates derived copies.
6. SL-2 regenerates rather than hand-edits neutral or packaged outputs. Its reducer verifies all producer interfaces, generated parity, receipt integrity, plan size, and scope before emitting metadata-only closeout evidence. Any roadmap, sibling-repository, canon, Governed Pipeline, or unowned-file diff blocks completion.

## Verification

- `uv run --project phase-loop-runtime python phase-loop-runtime/tests/proofgate_content_tdd_adapter.py verify --repo . --landing-ref origin/main --identity proofgate-tests-freeze --receipt .phase-loop/evidence/PROOFGATE/content-tdd-receipt.json`, evidence: operational
- `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_verification_evidence.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py -k proofgate`
- `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_acceptance_falsifier_contract.py phase-loop-runtime/tests/test_goal_coverage.py phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py`
- `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py -k proofgate`
- `uv run --project phase-loop-runtime python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-PROOFGATE.md`
- `uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"`
- `git diff --exit-code -- specs/phase-plans-v10.md`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-PROOFGATE-0 — proven by `uv run --project phase-loop-runtime python phase-loop-runtime/tests/proofgate_content_tdd_adapter.py verify --repo . --landing-ref origin/main --identity proofgate-tests-freeze --receipt .phase-loop/evidence/PROOFGATE/content-tdd-receipt.json`; falsified by receipt drift, a non-unique declared landing, a production change to a frozen test/support byte, or retained RED evidence lacking an asserted anchor and its typed marker.
- [ ] EC-PROOFGATE-1 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_acceptance_falsifier_contract.py -k missing_falsifier`; falsified by removing the clause check and observing that command accept the invalid fixture at validator, intake, or closeout.
- [ ] EC-PROOFGATE-2 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_verification_evidence.py -k unmatched_anchor`; falsified by changing the unmatched anchor fixture and observing a `killed` or passing disposition instead of `mutation_not_applied`.
- [ ] EC-PROOFGATE-3 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py -k '358_original or 288_ac1_and_ac4'`; falsified by either unchanged historical corpus fixture producing validator exit zero or a warning-only result.
- [ ] EC-PROOFGATE-4 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_convergence_broker_revocation_race.py -k 'github_broker_admission_store_is_wired or routing_broker_admission_store_is_wired'`; falsified by either corresponding production-site mutation surviving or by a helper-only mutation being credited as a kill.
- [ ] EC-PROOFGATE-5 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_verification_evidence.py -k 'parameter and proofgate'`; falsified by a missing, duplicate, substituted, blocked, or surviving parameter reducing to complete all-killed coverage.
- [ ] EC-PROOFGATE-6 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_acceptance_falsifier_contract.py -k negative_assertion_requires_path_entered_control`; falsified by removing the positive control and observing validator, intake, or closeout acceptance.
- [ ] EC-PROOFGATE-7 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py -k 'grandfathering or changed_or_new'`; falsified by hard-failing cutoff-proven exact bytes without the dated record, grandfathering changed/new bytes, or demoting any invalid non-grandfathered item to a warning.
