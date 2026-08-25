---
phase_loop_plan_version: 1
phase: RESIDUAL
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_RESIDUAL=1
    - PYTHONPATH=phase-loop-runtime/src
    - python3
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests/test_train_invariants.py
    - phase-loop-runtime/tests/test_convergence_broker_admission.py
    - phase-loop-runtime/tests/test_convergence_broker_verbs.py
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py
    - phase-loop-runtime/tests/test_train_runner.py
    - phase-loop-runtime/tests/test_train_merge.py
    - phase-loop-runtime/tests/test_fab_activation_promotion.py
    - phase-loop-runtime/tests/test_hotfix_lane.py
    - phase-loop-runtime/tests/test_phase_loop_runner.py
    - phase-loop-runtime/tests/test_phase_loop_repair_precondition_planned_closeout.py
    - phase-loop-runtime/tests/test_model_tier_taxonomy.py
    - phase-loop-runtime/tests/test_phase_loop_claude_channel_sidecar.py
    - phase-loop-runtime/tests/test_phase_loop_launcher.py
    - phase-loop-runtime/tests/test_phase_loop_models.py
    - phase-loop-runtime/tests/test_phase_loop_metrics.py
    - phase-loop-runtime/tests/test_phase_loop_handoff.py
    - phase-loop-runtime/tests/test_phase_loop_state.py
---

# RESIDUAL: Broker, Train, and Channel Residuals

## Context

The canonical manifest registers this RESIDUAL candidate as `committed`; legacy
`.codex/phase-loop/` files are non-authoritative compatibility artifacts. The
roadmap bytes match the frontmatter digest. Implementation eligibility begins
only after FABREADMIT is completed in the manifest.

Live issues agent-harness#289, agent-harness#296, agent-harness#298,
agent-harness#341, agent-harness#344, and agent-harness#360 ground the six
scheduled defects. The maintainer ruling on agent-harness#368 resolves
EC-RESIDUAL-1: publish identity and evidence include `base`, without a migration
shim while the recordless premise holds. SL-1 rechecks that premise and fails
closed if it changed.

The planning snapshot from `ruff 0.15.5` reports 38 F841 diagnostics across 28
files, while the roadmap and agent-harness#341 say “28 findings.” SL-0 re-derives
the exact execution-base inventory; the planning count is evidence, not a gate.

## Interface Freeze Gates

- [ ] IF-0-RESIDUAL-1 — Broker and train closure. The completed-effect identity
  is `publish_committed_branch_idempotency_key(repo, branch, base, head_sha)`;
  every producer, replay lookup, admission check, and `EvidenceRecord` binds the
  same normalized `base`. A faithful same-base retry deduplicates, a different
  base does not. No base-blind dual-read, backfill, or compatibility shim is
  permitted while the agent-harness#368 recordless premise remains true; finding
  any durable pre-change evidence record blocks the lane for re-design. On a
  `pr_open` resume, an exception or unavailable live head becomes one durable
  typed blocked result and never falls back to the ledger head or escapes
  `run_train`. A successful non-FAB `gh pr merge` with a null immediate merge
  OID enters the existing queue membership, bounded terminal poll, dequeue, and
  loud-unreconciled machinery before the coordinator records a terminal result.

- [ ] IF-0-RESIDUAL-2 — Hotfix and repair closure. A scalar or list-item
  `verification_command` is an argv command, never an implicit shell program;
  unquoted control operators and redirections (`;`, `&&`, `||`, `|`, `<`, `>`,
  and newline chaining) are rejected before verification artifacts or a passing
  closeout can be produced. Repair dispatch owns one runner-written
  `repair_lineage.v1` lease under `.phase-loop/`, bound to repository, roadmap
  digest, phase, root work-unit identity, owner process, and depth one. A live
  same-lineage lease refuses nested repair, while a stale lease is recoverable.
  Interruption of a repair coordinator that made no repository change cannot
  supersede a previously trusted `awaiting_phase_closeout`/`passed` terminal;
  top-level repair remains available.

- [ ] IF-0-RESIDUAL-3 — Channel model provenance closure.
  `SessionRegistryRecord` carries a metadata-only normalized actual session
  model. `ChannelSidecarClient.preflight(expected_model=...)` refuses an absent
  actual model as `session_model_unbound` and an unequal model as
  `session_model_mismatch` before message delivery. Launch metadata and
  `WorkUnitMetric` preserve intended model, actual model when verified, binding
  state, and caveat; `summarize_work_unit_metrics`, TUI handoff, and status
  rendering never place an intended unbound model in `by_model` without the
  caveat. A command-adapter template without `{model}` receives the same
  unbound provenance rather than a false launch-bound claim.

- [ ] IF-0-RESIDUAL-4 — F841 closure. The baseline is the exact Ruff JSON
  inventory re-derived from the post-FABREADMIT SL-0 execution base. The triage
  artifact has
  one row per diagnostic, keyed by path, symbol, and baseline location, with a
  disposition of fixed or individually justified. The behavioral
  `governed_premerge.py` `seen_block` finding is fixed with a frozen attribution
  test rather than mechanically deleted. Canonical skill source is edited once
  and both generated bundle layers are regenerated. Final `ruff check . --select
  F841` is empty, `ruff.toml` no longer ignores F841, and the config-driven CI
  lint command enforces it.

## Lane Index & Dependencies

SL-0 — Immutable tests-only RED boundary
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Broker identity, train resume, and general merge queue
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-2 — Hotfix command and repair-lineage safety
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Channel provenance and F841 retirement
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Documentation and exact-head closeout reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

The writer lanes are disjoint: SL-1 owns train F841 edits, SL-2 runner F841
edits, and SL-3 the remainder. Runtime schedulers stay off; the coordinator may
fan out same-vendor native workers only into ownership-validated worktrees.

## Lanes

### SL-0 — Immutable tests-only RED boundary

- **Scope**: Freeze every RESIDUAL falsifier, positive control, mutation anchor,
  F841 inventory expectation, and tests-first receipt before production edits.
- **Owned files**: `phase-loop-runtime/tests/test_train_invariants.py`
- **Interfaces provided**: `RESIDUAL_RED_SUITE`, exact mutation-anchor inventory,
  activated-RED/default-GREEN receipt contract
- **Interfaces consumed**: `IF-0-RESIDUAL-1`, `IF-0-RESIDUAL-2`, `IF-0-RESIDUAL-3`, `IF-0-RESIDUAL-4`, current post-FABPUB source (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add `PHASE_LOOP_TDD_EXPECT_RESIDUAL=1`-guarded tests for the four-argument
    publish identity and base-bearing evidence record, including same-base retry
    dedup and different-base separation. Assert the exact production call-site
    inventory so a base-blind replay lookup cannot survive elsewhere.
  - test: Add a `pr_open` resume test whose live-head seam raises and a second
    whose seam returns unavailable; both must assert a typed blocked return and
    durable blocked ledger row, while a successful read resumes normally.
  - test: Add a non-FAB merge-queue test in which `gh pr merge` succeeds, the
    immediate merge OID is null, and queue membership later terminalizes. Assert
    the enqueue argv omits `--delete-branch`; mutate either that omission or queue
    detection and require the production path to fail. Include removed,
    timeout/dequeue, and unreconciled controls using existing queue seams.
  - test: Add scalar and list-item hotfix cases for `;`, `&&`, `||`, `|`,
    redirection, and newline chaining. Each asserts no command or suite ran and
    no passing artifact was emitted; a quoted literal token and two separate
    shell-free list items remain valid controls.
  - test: Add channel-sidecar tests for matching, absent, and mismatched actual
    session model. Assert zero message delivery on refusal and assert that
    launch JSON, event metadata, work-unit metrics, JSON status, and TUI handoff
    either carry a verified actual model or the explicit unbound caveat.
  - test: Add an end-to-end repair-lineage test: a top-level repair may launch,
    its child cannot dispatch repair or `resume` into another repair, stale
    lineage is recoverable, and an interrupted no-diff repair preserves the
    byte-identical trusted terminal summary.
  - test: Add `residual_tdd_chronology` and a governed-premerge attribution
    regression proving an early block followed by structural hold resolves to
    `non_convergence`. Re-derive the execution-base Ruff JSON and freeze its exact
    diagnostic inventory; a diagnostic outside lane ownership forces re-planning.
    Insert one unused-local mutation and prove the final lint command fails.
  - verify: Run the unactivated selector and require GREEN, then run the activated
    selector and require RED only at the named new guarantees. For every test,
    assert its mutation anchor exists, apply the mutation, observe the named
    failure, restore source bytes, and retain raw plus JUnit evidence.
  - verify: Land and review this tests-only file before any production change.
    Later lanes may consume but never edit it; an implementation diff touching
    it is a blocking chronology violation.

### SL-1 — Broker identity, train resume, and general merge queue

- **Scope**: Apply the resolved publish-identity ruling and close the two general
  train-resume/merge defects without weakening FAB fencing.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/tests/test_convergence_broker_admission.py`, `phase-loop-runtime/tests/test_convergence_broker_verbs.py`, `phase-loop-runtime/tests/test_fab_activation_promotion.py`, `phase-loop-runtime/tests/test_fab_closeout_crash_safety.py`, `phase-loop-runtime/tests/test_fab_delta_consumer.py`, `phase-loop-runtime/tests/test_fabpub_shared_epoch.py`, `phase-loop-runtime/tests/test_fabreadmit_broker.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_train_order_only_deps_47.py`, `phase-loop-runtime/tests/test_train_roadmap.py`, `phase-loop-runtime/tests/test_train_runner.py`
- **Interfaces provided**: `RESIDUAL_BROKER_TRAIN_CLOSURE`, four-argument publish
  completed-effect identity, typed `pr_open` resume failure, general queue-bound
  terminal reconciliation
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, IF-0-FABPUB-1 (pre-existing),
  agent-harness#368 maintainer ruling (pre-existing), existing FAB queue
  membership/dequeue/re-gate primitives
- **Parallel-safe**: yes, only beside SL-2 and SL-3 after scheduler ownership and
  isolated-worktree assignment
- **Tasks**:
  - test: Make only `residual_publish_identity_includes_base`,
    `residual_pr_open_resume_live_head_failure`, and
    `residual_non_fab_merge_queue_null_oid` GREEN without editing SL-0.
  - impl: Before durable-key edits, inspect the canonical repository broker
    evidence root for any existing record. If any record exists, stop without a
    dual-read/backfill and report that agent-harness#368's recordless premise no
    longer holds.
  - impl: Change the key contract and every call site to `(repo, branch, base,
    head_sha)`. Add normalized `base` to `EvidenceRecord` serialization,
    validation, replay, and admission-key comparisons. Preserve epoch-free
    completed-effect identity and faithful same-base crash retry deduplication.
  - impl: Wrap both exceptions and unavailable results from the `pr_open` resume
    live-head read. Append one blocked ledger record and return the established
    train blocked shape with a stable non-secret reason; never inject or merge a
    ledger fallback head. Preserve successful resume and out-of-band-head
    detection.
  - impl: Generalize the existing FAB queue-bound post-merge path so queue
    detection and bounded terminal reconciliation apply to non-FAB nodes too.
    Omit `--delete-branch` whenever the merge enters a queue, before invoking `gh`.
    Preserve exact head/base checks, terminal-first race handling, GraphQL
    membership, dequeue confirmation, and loud unreconciled halt. FAB
    provenance/re-gate remains additive when a FAB run ID exists.
  - impl: Resolve this lane's F841 rows individually, including
    `train_runner.py`; do not remove a call merely to satisfy lint.
  - verify: Run activated `test_train_invariants.py -k 'residual_publish_identity_includes_base or residual_pr_open_resume_live_head_failure or residual_non_fab_merge_queue_null_oid'`.
  - verify: Run unactivated `pytest -q test_convergence_broker_admission.py test_convergence_broker_verbs.py test_fabpub_shared_epoch.py test_train_runner.py test_train_merge.py test_fab_activation_promotion.py` from `phase-loop-runtime/tests`.

### SL-2 — Hotfix command and repair-lineage safety

- **Scope**: Make hotfix verification parsing fail closed and prevent recursive
  repair or interruption from degrading a trusted closeout.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_hotfix_lane.py`, `phase-loop-runtime/tests/test_phase_loop_runner.py`, `phase-loop-runtime/tests/test_phase_loop_repair_precondition_planned_closeout.py`
- **Interfaces provided**: `RESIDUAL_HOTFIX_REPAIR_CLOSURE`, shell-operator
  refusal, `repair_lineage.v1`, trusted-terminal preservation rule
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, existing runner event and
  terminal-summary precedence, existing `.phase-loop/` path resolvers
- **Parallel-safe**: yes, only beside SL-1 and SL-3 after scheduler ownership and
  isolated-worktree assignment
- **Tasks**:
  - test: Make only `residual_hotfix_shell_operator` and
    `residual_repair_recursion_or_interrupt` GREEN without editing SL-0.
  - impl: Parse every hotfix scalar/list item with punctuation-aware shell
    tokenization and reject control operators/redirections before
    `run_verification`. Do not use `shell=True`. Retain the existing multi-item
    list as separate argv commands and preserve quoting of ordinary literal
    arguments.
  - impl: Add a runner-owned atomic `repair_lineage.v1` lease under canonical
    `.phase-loop/`. Acquire it before a repair child launch, refuse a live
    same-repo/roadmap/phase repair lineage at depth one, include the lineage in
    launch metadata and the repair prompt, and terminalize/recover stale leases
    without deleting evidence.
  - impl: Teach the repair prompt that it returns the shared closeout to its
    parent and must not invoke the phase-loop command. Enforcement remains the
    parent/child lineage gate, not prompt compliance.
  - impl: During failed-launch reduction, prefer a previously authenticated
    `awaiting_phase_closeout`/`passed` terminal when the interrupted work unit is
    only its repair coordinator and the repo/index/plan-owned bytes are
    unchanged. Do not preserve the terminal after a child write or for an
    ordinary execute failure.
  - impl: Remove or use the dead `prompt_profile` binding as its individual F841
    disposition; preserve dispatch behavior.
  - verify: Run activated `test_train_invariants.py -k 'residual_hotfix_shell_operator or residual_repair_recursion_or_interrupt'`.
  - verify: Run unactivated `pytest -q test_hotfix_lane.py test_phase_loop_runner.py test_phase_loop_repair_precondition_planned_closeout.py` from `phase-loop-runtime/tests`.

### SL-3 — Channel provenance and F841 retirement

- **Scope**: Bind/refuse channel session models, carry model caveats through every
  reporting surface, and retire the remaining exact F841 inventory.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/models.py`, `phase-loop-runtime/src/phase_loop_runtime/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/handoff.py`, `phase-loop-runtime/src/phase_loop_runtime/render.py`, `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/harness-capability-matrix.md`, `phase-loop-runtime/scripts/_gate_a_probe.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/tests/proofgate_bootstrap_verifier.py`, `phase-loop-runtime/tests/test_injection_skill_failloud.py`, `phase-loop-runtime/tests/test_legible_evidence.py`, `phase-loop-runtime/tests/test_phase_loop_launcher.py`, `phase-loop-runtime/tests/test_release_dispatch_operator_approval_145.py`, `phase-loop-runtime/tests/test_model_tier_taxonomy.py`, `phase-loop-runtime/tests/test_phase_loop_claude_channel_sidecar.py`, `phase-loop-runtime/tests/test_phase_loop_models.py`, `phase-loop-runtime/tests/test_phase_loop_metrics.py`, `phase-loop-runtime/tests/test_phase_loop_handoff.py`, `phase-loop-runtime/tests/test_phase_loop_state.py`, `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-skills/plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/codex-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/gemini-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/opencode-plan-phase/scripts/validate_plan_doc.py`, `ruff.toml`, `.github/workflows/test.yml`, `plans/evidence/v10-RESIDUAL-f841-triage.md`
- **Interfaces provided**: `RESIDUAL_CHANNEL_F841_CLOSURE`, verified/unbound
  model provenance in session, launch, metric, handoff, and status records;
  exact per-diagnostic F841 disposition table
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, current channel session registry
  and client preflight, current work-unit metric/status rendering, exact baseline
  F841 inventory
- **Parallel-safe**: yes, only beside SL-1 and SL-2 after scheduler ownership and
  isolated-worktree assignment
- **Tasks**:
  - test: Make only `residual_channel_session_model` and
    `residual_f841_triage` GREEN without editing SL-0.
  - impl: Add normalized actual-model metadata to the channel session registry
    and client preflight. Launcher passes the intended model into preflight and
    returns typed unbound/mismatch route results before `send_and_wait` creates a
    message. Matching sessions record both intended and verified actual model.
  - impl: Extend the additive `work_unit_metric.v1` record with model binding and
    caveat fields without reinterpreting old rows. Summaries render a bare model
    only when bound; unbound legacy/current rows render a stable explicit caveat.
    Apply the same rule to JSON status, text status, and TUI handoff.
  - impl: A command adapter lacking `{model}` remains identifiable as unbound and
    never produces a launch-bound model claim. Preserve existing template
    compatibility while refusing a known actual mismatch.
  - impl: Update the channel capability contract to require model metadata at
    session registration and document refusal/caveat behavior. Do not record raw
    auth or provider payloads.
  - impl: Build the exact F841 triage table from the frozen execution-base Ruff JSON. For each
    diagnostic, fix the binding or retain an explicit line-local justification;
    fix `seen_block` behavior with the frozen test. Edit only the canonical
    `skills-src` validator copy, then run both repository generators so the
    neutral and four packaged copies are byte-parity outputs.
  - impl: Remove `F841` from `ruff.toml`'s ignore list and update the CI comment so
    the existing config-driven pinned-Ruff job enforces the rule. Do not add a
    second lint job or override config with CLI `--select` in CI.
  - verify: Run activated `test_train_invariants.py -k 'residual_channel_session_model or residual_f841_triage'`.
  - verify: Run unactivated `pytest -q test_model_tier_taxonomy.py test_phase_loop_claude_channel_sidecar.py test_phase_loop_launcher.py test_phase_loop_models.py test_phase_loop_metrics.py test_phase_loop_handoff.py test_phase_loop_state.py` from `phase-loop-runtime/tests`.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_phase_loop_docs.py`

### SL-4 — Documentation and exact-head closeout reducer

- **Scope**: Reduce all producer evidence into one exact-head, issue-qualified,
  metadata-only completion record and release-note entry.
- **Owned files**: `CHANGELOG.md`, `plans/evidence/v10-RESIDUAL-closeout.json`
- **Interfaces provided**: `RESIDUAL_CLOSEOUT_EVIDENCE`
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`,
  `RESIDUAL_BROKER_TRAIN_CLOSURE`, `RESIDUAL_HOTFIX_REPAIR_CLOSURE`,
  `RESIDUAL_CHANNEL_F841_CLOSURE`, exact staged diff and exact-head verification
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume the frozen reducer assertions in SL-0; do not edit the tests.
  - impl: Add a concise CHANGELOG entry covering base-bound publish identity,
    typed train resume/queue handling, hotfix refusal, repair-lineage safety,
    channel model provenance, and F841 enforcement.
  - impl: Write `plans/evidence/v10-RESIDUAL-closeout.json` with schema,
    roadmap/plan digests, tests-only and implementation chronology references,
    exact test/lint commands and outcomes, the F841 triage artifact digest,
    produced gate list, and dispositions for agent-harness#289,
    agent-harness#296, agent-harness#298, agent-harness#341,
    agent-harness#344, agent-harness#360, and agent-harness#368. Record issues as
    closeable only after their exact criteria pass; do not close or mutate GitHub
    state from this reducer.
  - verify: Run the complete frontmatter suite, all Verification commands below,
    and `git diff --check` against the exact staged diff. A material reducer edit
    invalidates prior verification and requires the suite and exact-head review
    to run again.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`roadmap and coordinator rotation`
- SL-4: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`phase-plan reducer policy`

CLI/operator override has highest precedence, followed by this phase-plan policy,
roadmap policy, `Dispatch Hints`, and registry defaults. The coordinator must
select the phase's single author vendor under the roadmap rotation. Default
inheritance above is explicit; no executor or model may silently downgrade.

## Execution Notes

RESIDUAL implementation waits for manifest-recorded FABREADMIT completion. SL-0
then lands and receives its tests-only review: unactivated is GREEN and activated
is RED at the named guarantees. Runtime schedulers remain off; SL-1 through SL-3
may use same-vendor native workers in coordinator-assigned disjoint worktrees and
never edit SL-0. SL-4 runs only after all producers. Release, publication, issue
mutation, and external dispatch remain outside this plan.

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-RESIDUAL.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests -m not\ dotfiles_integration --deselect phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_phase_loop_docs.py`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.docs_freshness check-catalog --repo .`
- `ruff check . --no-cache`
- `ruff check . --select F841 --no-cache`
- `git diff --check`

IF-0-VC-2 is satisfied only when the plan validator resolves the pinned roadmap,
extracts every command above as executable argv, and resolves the exact
frontmatter `automation.suite_command`. Collection-only output, an unactivated
tests-only GREEN, skipped falsifiers, stale-head output, or a prose-only triage
table is not passing verification.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-v10.md`, `plans/manifest.json`
- evidence paths: `.phase-loop/evidence/RESIDUAL/spec-delta-closeout.json`, `plans/evidence/v10-RESIDUAL-f841-triage.md`, `plans/evidence/v10-RESIDUAL-closeout.json`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment`

The amendment route reconciles EC-RESIDUAL-1's agent-harness#368 design condition,
EC-FABPUB-4's base-blind identity text, and EC-RESIDUAL-7's historical count to
the frozen execution-base Ruff inventory. This is downstream routing, not
permission for a lane to edit the roadmap or manifest. The runner stamps it only
after exact-head evidence and rebinds later plans to the amended roadmap digest.

## Acceptance Criteria

- [ ] EC-RESIDUAL-0 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_tdd_chronology`; falsified by a `verification_evidence.v3` path-entered mutation that permits an implementation edit before the frozen tests-only landing and observes the chronology assertion reject it before the restored control passes.
- [ ] EC-RESIDUAL-1 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_publish_identity_includes_base`; falsified by a `verification_evidence.v3` path-entered mutation that removes `base` from one identity call site and observes cross-base aliasing before the restored control passes.
- [ ] EC-RESIDUAL-2 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_pr_open_resume_live_head_failure`; falsified by a `verification_evidence.v3` path-entered mutation that restores ledger-head fallback and observes the resume assertion reject it before the restored control passes.
- [ ] EC-RESIDUAL-3 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_non_fab_merge_queue_null_oid`; falsified by a `verification_evidence.v3` path-entered mutation that bypasses queue membership and observes the false-halt assertion before the restored control passes.
- [ ] EC-RESIDUAL-4 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_hotfix_shell_operator`; falsified by a `verification_evidence.v3` path-entered mutation that accepts one control operator and observes execution reach the sentinel before the restored refusal passes.
- [ ] EC-RESIDUAL-5 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_channel_session_model`; falsified by a `verification_evidence.v3` path-entered mutation that suppresses mismatch refusal and observes message delivery reach the sentinel before the restored control passes.
- [ ] EC-RESIDUAL-6 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_repair_recursion_or_interrupt`; falsified by a `verification_evidence.v3` path-entered mutation that ignores a live lineage lease and observes nested repair launch before the restored control passes.
- [ ] EC-RESIDUAL-7 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_f841_triage` and `ruff check . --select F841 --no-cache`; falsified by a `verification_evidence.v3` path-entered unused-local mutation that makes lint fail before the restored exact inventory passes.
