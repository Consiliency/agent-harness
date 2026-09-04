---
phase_loop_plan_version: 1
phase: REVIEWTRUTH
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command: 'PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py phase-loop-runtime/tests/test_phase_worktree_executor.py phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_advisor_board_research.py phase-loop-runtime/tests/test_panel_invoker_spawn.py phase-loop-runtime/tests/test_panel_native_fill_183.py phase-loop-runtime/tests/test_train_merge.py'
---

# REVIEWTRUTH: Board Reports Its Own Degradation

## Context

REVIEWTRUTH begins only after CONFORM, HARDEN, and SCHED have completed on the
canonical roadmap path. It replaces text-derived seat usability with typed outcomes,
distinguishes FULL, FLOOR-ONLY, and BELOW-FLOOR boards, makes prompt-lens and artifact
grounding load-bearing, persists seat and verdict facts, wires the governed repair
round, and applies the ratified prover policy. It consumes SCHED's worktree lifecycle
for the bounded early-prover path; it does not implement LEGLIFE timeout enforcement
or per-repo custom seats.

The three human decisions referenced by EC-REVIEWTRUTH-15 through
EC-REVIEWTRUTH-17 already exist. SL-0 turns them into the roadmap-required durable,
content-bound repository record. SL-1 then authors and runs the durable verifier over
that landed record and current protection and ancestry facts before any production lane.
No lane may substitute historical panel output, mutable issue text, or a planned identity
for current evidence. The tests-only boundary precedes every production lane, and its
test files become immutable for the implementation work.

## Interface Freeze Gates

- [ ] IF-0-REVIEWTRUTH-1 — `PanelLegOutcome` is the closed vocabulary
  `reviewed | unavailable | errored | timed_out | refused | capped | empty` on
  `PanelLegResult`, independent of `text`. `required` and `degraded` remain orthogonal
  fields. SL-2 adds aggregate `PanelResult.reviewed_seat_count`, owned in
  `panel_invoker.py`, as the raw count of seats whose outcome is `reviewed` so consumers
  can classify delivery without treating grounding or material completeness as outcome
  variants. Governed ratification separately filters that count by grounding and
  material completeness. REVIEWTRUTH consumes a synthesized `timed_out`; LEGLIFE owns
  the enforcement that produces it.
- [ ] IF-0-REVIEWTRUTH-2 — `RatificationPolicy.required_prover: bool = True` is an
  additive trailing field, and `BoardFacts` retains `reviewed_sha` in its current
  positional slot before additive `prover_usable: bool = False`. Typed per-repo
  resolution accepts `required_prover=false` without changing other policy fields.
  `RatificationPolicy` and `BoardFacts` both remain owned by
  `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py` in SL-4;
  `advisor_board/schema.py` does not own either type.
  The four shipped defaults require three vendors, three grounded lenses, and one
  usable prover; missing an effectively required prover escalates regardless of the
  ordinary shortfall action.
- [ ] IF-0-REVIEWTRUTH-3 — the additive review-wave contract leaves `PANEL_LEGS`
  unchanged. Plan/design may collect critics first but must stage one serial early
  prover's evidence before Fable; pre-merge/release requires that evidence before
  critics. Codex is the primary `can_probe` holder in a coordinator-created isolated
  worktree with closed external-tool state, no network or extra writable roots, exact
  input/evidence binding, and external reaping. A typed Codex preflight failure may use
  Grok only with positive OS confinement; otherwise the wave records zero launches.
  Gemini is ineligible, and only a usable grounded artifact-bound Fable result can be
  `binding_prover`. Contradicting evidence invalidates affected prior agreements. SL-2
  owns transport and receipts, SL-3 owns grounding, SL-4 owns prover usability, and
  SL-5 integrates those parts; only the SL-6 reducer may record this gate complete.

## Cross-Lane Contract Freeze

- `REVIEWTRUTH_CAPABILITY_DECISION` is `reviewtruth_capability_decision.v1` with the
  three maintainer-comment identities and body SHA-256 values, the ratified posture,
  the non-authorizing `agent-harness#405` reference, and branch-protection/ancestry
  requirements. Mutable comment text is never consumed after the record is landed.
- `ExecutionCapabilityAttestation` binds the exact seat key, vendor, model, effort,
  lens, capability roles (`can_probe` and `binding_prover_capable`), posture, effective
  preflight digest, executable/config inventory digests, and candidate head/tree. A
  missing, unknown, mismatched, or failed field is unusable.
- `ReviewWaveEvidence` binds gate, ordering, candidate head/tree, plan, input, bundle,
  review-instruction, policy, preflight, launch/no-launch, output, and evidence-bundle
  digests; it also records critic verdict digests, the grounded Fable
  `binding_prover` digest, and every invalidated agreement digest. Required fields are
  never reconstructed from prose.
- `BoardDeliveryState` is exactly `FULL` when raw reviewed seats equal target,
  `FLOOR_ONLY` when floor is at most raw reviewed seats and less than target, and
  `BELOW_FLOOR` when raw reviewed seats are less than floor. Counts above target return
  a typed malformed result and the governed gate blocks; `floor > target` is the same
  typed malformed case. Grounded/material-complete
  reviewed count and prover usability are independent ratification facts and may block
  a delivery-classified board.
- REVIEWTRUTH extends the already-frozen `verification_evidence.v3` envelope only via
  registered namespace `phase_loop_runtime.reviewtruth_evidence`. Its payload binds
  phase, lane, criterion, mutation anchor, command/result digests, candidate head/tree,
  plan, bundle, and review-instruction digests plus referenced artifact digests. The
  runner is the sole writer of
  `.phase-loop/runs/**/verification.json`: lanes submit append-only payloads, existing
  sealed entries are immutable, and any head, tree, plan, bundle, instruction, or
  evidence digest mismatch invalidates the affected review and verification records.

## Lane Index & Dependencies

SL-0 — Durable capability decision record
Depends on: (none)
Blocks: SL-1, SL-2, SL-6
Parallel-safe: no

SL-1 — Tests-first falsifier boundary
Depends on: SL-0
Blocks: SL-2, SL-3, SL-4, SL-5, SL-6
Parallel-safe: no

SL-2 — Typed outcomes, prompt lens, native fill, and early-prover transport
Depends on: SL-0, SL-1
Blocks: SL-3, SL-4, SL-5, SL-6
Parallel-safe: no

SL-3 — Governed classification and grounding
Depends on: SL-1, SL-2
Blocks: SL-4, SL-5, SL-6
Parallel-safe: no

SL-4 — Ratification policy and delivery state
Depends on: SL-1, SL-2, SL-3
Blocks: SL-5, SL-6
Parallel-safe: no

SL-5 — Production gates, repair, and durable reporting
Depends on: SL-1, SL-2, SL-3, SL-4
Blocks: SL-6
Parallel-safe: no

SL-6 — Evidence and documentation reducer
Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
Blocks: (none)
Parallel-safe: no

## Lanes

### SL-0 — Durable capability decision record

- **Scope**: Bind the already-issued capability, prover, and ordering decisions into the durable record required by EC-REVIEWTRUTH-15.
- **Owned files**: `docs/research/reviewtruth-leg-capability-ratification.md`
- **Interfaces provided**: `REVIEWTRUTH_CAPABILITY_DECISION`.
- **Interfaces consumed**: roadmap directives (pre-existing), the maintainer-comment identities and captured body bytes/digests enumerated under EC-REVIEWTRUTH-15 through EC-REVIEWTRUTH-17 (pre-existing), live repository protection/ancestry metadata (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: enumerate the exact record fields and rejection conditions consumed by SL-1; SL-0 does not author the verifier.
  - impl: write the metadata-only disposition record without secrets or mutable evidence blobs.
  - verify: obtain exact-head review of the record-only diff and land it before SL-1; SL-1 performs the durable executable verification before SL-2.

### SL-1 — Tests-first falsifier boundary

- **Scope**: Author, review, and run every REVIEWTRUTH falsifier RED before any production edit, retaining one `verification_evidence.v3` record per injected failure.
- **Owned files**: `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, `docs/research/reviewtruth-red-baseline.md`
- **Interfaces provided**: `REVIEWTRUTH_RED_SUITE`, `REVIEWTRUTH_TESTS_FIRST_EVIDENCE`.
- **Interfaces consumed**: `REVIEWTRUTH_CAPABILITY_DECISION`, IF-0-REVIEWTRUTH-1 through IF-0-REVIEWTRUTH-3.
- **Parallel-safe**: no.
- **Tasks**:
  - test: cover EC-REVIEWTRUTH-1 through `-17`, consuming the literal sixteen-node and
    anchor lists plus their sorted-LF digests from the roadmap's EC-REVIEWTRUTH-17
    section, and pair each mutation anchor with a positive control that enters the
    production construction path. Include closeout-evidence rejection cases for
    missing lane evidence, proxy-only smoke, altered tests, incomplete IF inventory,
    and raw secret/model output.
  - impl: add only tests, the chronology verifier, and RED evidence; activate new
    expectations with `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` until the production
    capability marker exists. The runner invokes the SL-1 verifier, which uses the
    pre-existing LEGIBLE `run_verification`, `register_extension_namespace`, and
    keyword-only `_bind_sidecar_extension` APIs to emit sealed v3 RED records under the
    frozen REVIEWTRUTH namespace; it accepts no executor-authored evidence. SL-5 later
    installs the identical namespace/schema in production.
  - verify: run the chronology verifier in `capability-record` mode against the landed
    SL-0 record and current hosting metadata, then prove the unactivated compatibility
    suite remains green and every activated test fails only at its named anchor. Capture
    a sorted path/blob digest for all `phase-loop-runtime/tests/**` dependencies
    (including `conftest.py`, helpers, fixtures, and goldens) and reject any later
    change. Define forbidden pre-RED production paths as
    `phase-loop-runtime/src/**`, `.github/workflows/test.yml`,
    `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, and
    `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`; the SL-1 verifier and
    docs are explicitly non-production. Require zero forbidden-path changes before the
    RED seal and satisfy EC-REVIEWTRUTH-0 before SL-2.

### SL-2 — Typed outcomes, prompt lens, native fill, and early-prover transport

- **Scope**: Publish the seat-level contracts, lossless durable-seat reconstruction, and the isolated early-prover/native-fill transport without changing frozen tests.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_gate.py`, `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- **Interfaces provided**: IF-0-REVIEWTRUTH-1, IF-0-REVIEWTRUTH-3 transport/receipt portion, `ExecutionCapabilityAttestation`, `NativeAgentLegRequest`, `ReviewWaveEvidence`.
- **Interfaces consumed**: `REVIEWTRUTH_RED_SUITE`, `REVIEWTRUTH_CAPABILITY_DECISION`, SCHED worktree authority.
- **Parallel-safe**: no; `panel_invoker.py` is single-writer.
- **Tasks**:
  - test: make only outcome, retry, lens propagation, native-fill, attestation, isolation, confinement, reaping, and review-wave tests green.
  - impl: add typed outcome/identity fields, lossless strict-reader reconstruction of
    `required` and `degraded`, prompt-lens binding, exact native request binding, strict
    capability preflight, serial worktree holder, external-tool closure, and
    digest-bound evidence receipts. Publish the final call-ready
    `PanelResult.reviewed_seat_count` and `ReviewWaveEvidence` APIs in SL-2-owned files;
    SL-5 integrates them without reopening `fab_gate.py` or another SL-2 path.
  - verify: run only SL-2-owned selectors: typed outcome, retry-not-count, prompt-lens
    transport, native fill, capability preflight, worktree isolation, reaping, and
    receipt binding, plus full `test_panel_invoker_spawn.py`, launcher, and board-golden
    regressions. Defer spawn-error
    classification, grounding/material checks, policy, and production persistence or
    gate wiring to their owning lanes; make no frozen-test edits.

### SL-3 — Governed classification and grounding

- **Scope**: Convert typed leg results into trustworthy findings and fail closed on ungrounded or incomplete review material.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`
- **Interfaces provided**: `ReviewGrounding`, `GovernedBoardEvidence`, `GroundedBindingProverCandidate`, `review_material_issue()`.
- **Interfaces consumed**: IF-0-REVIEWTRUTH-1, `ExecutionCapabilityAttestation`, `ReviewWaveEvidence`, `REVIEWTRUTH_RED_SUITE`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: make spawn-error, refused-artifact, grounded-review, exception-traceback, and empty/elided-material controls green.
  - impl: classify by typed outcome rather than response text and preserve genuine BLOCK
    findings. Preserve the raw delivery count unchanged; exclude ungrounded or
    incomplete material only from the separate governed-ratification reviewing count.
  - verify: run the EC-REVIEWTRUTH-3 spawn-error path and EC-REVIEWTRUTH-12/`-13`
    grounding/material selectors plus governed-review and research regressions,
    including positive reviewed-with-no-findings controls.

### SL-4 — Ratification policy and delivery state

- **Scope**: Implement the additive prover policy and the shared FULL/FLOOR-ONLY/BELOW-FLOOR decision.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- **Interfaces provided**: IF-0-REVIEWTRUTH-2, `BoardDeliveryState`, `classify_board_delivery()`.
- **Interfaces consumed**: IF-0-REVIEWTRUTH-1, `GovernedBoardEvidence`, `GroundedBindingProverCandidate`, `ExecutionCapabilityAttestation`, `REVIEWTRUTH_RED_SUITE`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: make the SL-1-owned positional compatibility, typed override, default floor,
    lens coverage, delivery-state, and hard-prover-block controls green; policy and
    gate-posture files outside SL-1 are run-only regressions.
  - impl: resolve policy without hardcoded gate branches and derive `prover_usable` only
    from the exact grounded artifact-bound attested seat. Publish final call-ready
    `classify_board_delivery()` and `evaluate_ratification()` APIs in SL-4-owned files;
    SL-5 calls them without reopening `gate_posture.py`.
  - verify: run the EC-REVIEWTRUTH-1/`-4` delivery-state and EC-REVIEWTRUTH-16 prover
    selectors plus policy and gate-posture regressions with frozen tests unchanged.

### SL-5 — Production gates, repair, and durable reporting

- **Scope**: Wire all REVIEWTRUTH contracts into the live governed planning, pre-merge, train, resume, and run-summary paths.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/review_summary.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py`, `phase-loop-runtime/src/phase_loop_runtime/reviewtruth_capability.py`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`, `.github/workflows/test.yml`
- **Interfaces provided**: integrated IF-0-REVIEWTRUTH-3, `REVIEWTRUTH_PRODUCTION_GATES`, `REVIEWTRUTH_APPLY_FIX`, `REVIEWTRUTH_SEAT_LEDGER`, `REVIEWTRUTH_PANEL_VERDICT_LEDGER`.
- **Interfaces consumed**: IF-0-REVIEWTRUTH-1 through IF-0-REVIEWTRUTH-3, `BoardDeliveryState`, `GovernedBoardEvidence`, `ReviewGrounding`, `review_material_issue()`, `NativeAgentLegRequest`, `ReviewWaveEvidence`, `REVIEWTRUTH_RED_SUITE`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: drive production gates for pass, degraded, block-then-pass repair,
    nonconvergence, resume, material failure, per-seat persistence, run-summary verdict
    emission, and the SL-1 closeout-evidence rejection cases.
  - impl: pass a real repair closure, rerender after repair, apply delivery/prover
    decisions, persist every seat and aggregate verdict, and surface degradation in the
    terminal summary. Install
    `phase_loop_runtime.reviewtruth_capability:REVIEWTRUTH_CAPABILITY_VERSION="reviewtruth.v1"`
    only after all SL-2 through SL-5 production paths are complete. Intermediate CI
    remains on the unactivated compatibility suite; SL-1 RED runs force the flag only in
    runner-owned evidence commands. In the terminal SL-5 change, CI runs the now-marker-
    activated suite without forcing the environment flag.
  - verify: run `automation.suite_command`, full `test_train_merge.py`, clean-room Gate
    A, locked Ruff/lock checks, and the full non-integration regression suite before
    reduction. `test_governed_planning_gate.py` exercises its production wrapper in
    SL-5-owned `runner.py`; it is run-only and creates no additional source owner.

### SL-6 — Evidence and documentation reducer

- **Scope**: Reduce all producer results into durable verification and operator-facing contract documentation.
- **Owned files**: `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- **Interfaces provided**: `REVIEWTRUTH_CLOSEOUT_EVIDENCE` and the sole completion
  record for IF-0-REVIEWTRUTH-1 through IF-0-REVIEWTRUTH-3.
- **Interfaces consumed**: `REVIEWTRUTH_CAPABILITY_DECISION`, `REVIEWTRUTH_TESTS_FIRST_EVIDENCE`, `REVIEWTRUTH_PRODUCTION_GATES`, `REVIEWTRUTH_APPLY_FIX`, `REVIEWTRUTH_SEAT_LEDGER`, `REVIEWTRUTH_PANEL_VERDICT_LEDGER`, IF-0-REVIEWTRUTH-1 through IF-0-REVIEWTRUTH-3.
- **Parallel-safe**: no; terminal reducer.
- **Tasks**:
  - test: run the immutable SL-1 rejection cases against the SL-5 verifier; SL-6 does
    not author or modify an executable.
  - impl: record metadata-only suite/JUnit, clean-room, live-panel inspection, policy, ledger, summary, and interface evidence; document only sanctioned contract deltas. Record `no_doc_delta` for `README.md`, `CHANGELOG.md`, and release notes because this phase changes no public release surface.
  - verify: from the final clean candidate, rerun the EC-REVIEWTRUTH-0 tests-first
    chronology check, the EC-REVIEWTRUTH-15 capability/protection/conformance/ancestry
    check, and evidence verification. Require the landed SL-0 record commit to remain
    an ancestor of the candidate's pre-landing base, bind the final candidate head/tree
    and plan digest, and require all three IF gates before closeout.

## Execution Notes

- The coordinator enforces CONFORM, HARDEN, and SCHED completion before SL-0 and
  prevents any external writer from overlapping a lane-owned path.
- SL-0 completion must satisfy EC-REVIEWTRUTH-15 exactly. Before SL-1 starts, the
  verifier requires the record to be present on current `main` and to satisfy that
  goal's ancestry and landing-shape checks; a record present only on the implementation
  branch is insufficient.
- One implementation author owns SL-2 through SL-5. Reviewers do not edit the
  candidate. Every review/evidence record binds candidate head/tree and plan digest;
  any candidate or plan mismatch invalidates it, regardless of perceived materiality.
- `.phase-loop/runs/**/verification.json` is runner-owned generated evidence, not a
  lane-editable source path. Each lane may supply only its typed namespaced payload;
  the runner appends and reseals it, and no lane may overwrite or mutate an earlier
  sealed entry.
- SL-1 is tests-only and immutable after acceptance. SL-2 through SL-5 may not
  modify an SL-1-owned path; a required test correction creates a new tests-only
  boundary before implementation resumes.
- External model work uses subscription-authenticated CLI or native harness routes.
  Provider API-key fallback, release publication, tagging, and dispatch are out of
  scope.
- Closeout records `visual_render_declared=false`; REVIEWTRUTH has no visible-render
  deliverable.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-6: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`terminal evidence and documentation reducer`

Policy precedence is CLI/operator override, this phase-plan policy, roadmap policy,
`Dispatch Hints`, then registry defaults. Silent downgrade is forbidden without an
explicit fallback or inherited default.

## Verification

Run the tests-only boundary first without activation, then activate it only to capture
RED evidence. After SL-5, the primary focused command is the frontmatter
`automation.suite_command`. Also run:

```bash
cd phase-loop-runtime
PYTHONPATH=src python3 -m pytest -q tests/test_ratification_policy.py tests/test_gate_posture.py tests/test_governed_planning_gate.py tests/test_governed_premerge_live.py tests/test_panel_verdict_summary.py tests/test_convergence_seat_lifecycle.py
uv run --locked ruff check .
uv lock --check
PYTHONPATH=src python3 -m pytest -q -m "not dotfiles_integration"
bash scripts/gate_a_cleanroom.sh
```

The live board smoke is produced during SL-6 by the runner-mediated phase-loop command:

```bash
codex-phase-loop reviewtruth-smoke --artifact plans/phase-plan-v10-REVIEWTRUTH.md --require-head HEAD --require-plan-authority plans/manifest.json --output docs/research/reviewtruth-real-panel-smoke.md
```

SL-5 adds this narrow CLI entrypoint and runner implementation. The runner pins the
clean repository head/tree, resolves the current plan authority, materializes the
canonical review instructions, computes plan/bundle/instruction digests, launches the
live board, and exclusively writes the redacted record; caller-supplied digest values or
script-self-authored evidence are refused. SL-6 owns the record contract and reduction,
but no lane or external writer may modify the runner output. Command-construction tests
are not a substitute. `verify_reviewtruth_evidence.py --smoke` validates that record and
requests its runner-stamped v3 binding before SL-6 closes. These identities live in
immutable evidence rather than self-pinning the plan to a future commit. The additional
tests in the verification block are read-only regressions; running them does not
authorize editing their files.

## Acceptance Criteria

- [ ] EC-REVIEWTRUTH-0 — proven by `python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py --mode tests-first`; falsified by path-entered control: the verifier accepts a production change before the RED evidence or a frozen test change afterward; evidence uses `verification_evidence.v3`.
- [ ] EC-REVIEWTRUTH-1, EC-REVIEWTRUTH-4 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k board_delivery_state`; falsified by path-entered control: a three-seat result with target four is classified FULL or a below-floor result converges.
- [ ] EC-REVIEWTRUTH-2, EC-REVIEWTRUTH-3 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k 'typed_outcome or spawn_error'`; falsified by path-entered control: response text restores usability or an exception traceback becomes a governed BLOCK.
- [ ] EC-REVIEWTRUTH-5 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k prompt_lens`; falsified by path-entered control: lens removal leaves prompt and credited coverage unchanged.
- [ ] EC-REVIEWTRUTH-6 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_golden.py`; falsified by path-entered control: an unsanctioned serialized result or launch delta is accepted.
- [ ] EC-REVIEWTRUTH-7 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k retry_not_count`; falsified by path-entered control: capped, empty, or synthesized timed-out outcomes increment the reviewed-seat count.
- [ ] EC-REVIEWTRUTH-8 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k production_apply_fix`; falsified by path-entered control: the governed block-then-pass case becomes mergeable without entering the production repair closure.
- [ ] EC-REVIEWTRUTH-9 — proven by first running the SL-6 runner-mediated `codex-phase-loop reviewtruth-smoke` command, then `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py --smoke docs/research/reviewtruth-real-panel-smoke.md`; falsified by path-entered control: a verdict whose seat did not inspect a staged file is accepted as live-panel evidence.
- [ ] EC-REVIEWTRUTH-10 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k production_panel_verdict_summary`; falsified by path-entered control: a production pass, block, or degraded outcome reaches run end without a durable verdict record.
- [ ] EC-REVIEWTRUTH-11 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k production_seat_lifecycle_ledger`; falsified by path-entered control: the live non-FAB path omits required, outcome, or degraded seat facts.
- [ ] EC-REVIEWTRUTH-12 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k grounding_refused`; falsified by path-entered control: ungrounded or artifact-mismatched agreement contributes to ratification.
- [ ] EC-REVIEWTRUTH-13 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k material_guard`; falsified by path-entered control: the production governed gate accepts empty or elided review material.
- [ ] EC-REVIEWTRUTH-14 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_native_fill_183.py` followed by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k native_fill`; falsified by path-entered control: a natively fillable Claude/Fable seat is silently dropped or sent through its local adapter.
- [ ] EC-REVIEWTRUTH-15 — proven before SL-2 and again at final closeout by `python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py --mode capability-record --candidate-head HEAD --require-record-ancestor-of-base`; falsified by path-entered control: posture-assuming production is admitted without the durable ratification, protection, conformance, and ancestry checks, or final-head revalidation accepts a stale/non-ancestor record.
- [ ] EC-REVIEWTRUTH-16 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py -k required_prover`; falsified by path-entered control: an unattested seat satisfies the prover requirement or `required_prover=false` changes an unrelated policy field.
- [ ] EC-REVIEWTRUTH-17 — proven by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_reviewtruth_phase.py phase-loop-runtime/tests/test_phase_worktree_executor.py -k 'review_wave or early_prover'`; falsified by path-entered control: ordering, role separation, external-tool closure, worktree isolation, reaping, receipt binding, fallback confinement, or contradiction re-review is bypassed; evidence uses `verification_evidence.v3`.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- rationale: REVIEWTRUTH changes repository-internal runtime and evidence contracts
  already mandated by this roadmap, not an external product, protocol, or consumer
  specification
- target surfaces: REVIEWTRUTH-owned runtime, tests, workflow, scripts, evidence, and contract documentation
- evidence paths: `docs/research/reviewtruth-leg-capability-ratification.md`, `docs/research/reviewtruth-red-baseline.md`, `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `.phase-loop/runs/**/verification.json`
- redaction posture: `metadata_only`
- downstream handling: none; LEGLIFE consumes IF-0-REVIEWTRUTH-1 and the roadmap remains authoritative
