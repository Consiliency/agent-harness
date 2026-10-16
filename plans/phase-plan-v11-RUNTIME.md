---
phase_loop_plan_version: 1
phase: RUNTIME
roadmap: specs/phase-plans-v11.md
roadmap_sha256: d294c3bab92c995bda8266a12340c78a9d73c12a18919a47b2154ceb4555aba4
automation:
  suite_command:
    - uv
    - run
    - --quiet
    - --project
    - phase-loop-runtime
    - --group
    - test
    - --extra
    - visual
    - --python
    - "3.14"
    - --locked
    - python
    - -m
    - pytest
    - phase-loop-runtime/tests
    - -q
---

# RUNTIME: Runtime Substrate

## Context

Implement only EC-RUNTIME-0 and EC-RUNTIME-2 carried by v11 Phase 6. Their
definitions remain in the V10 external input named by the roadmap. The frozen
input `plans/phase-plan-v10-RUNTIME.md` explains the existing runtime interfaces;
its historical execution sequence is not a new v11 requirement. Delivered goals
EC-RUNTIME-1, EC-RUNTIME-3, EC-RUNTIME-4 and EC-RUNTIME-5 remain closed.

The current `convergence/reconcile.py` consumes four callbacks, selects authority
and invalidates divergent observations; its tests supply in-memory observations.
No production `ExactStateProbes` construction supplies the four live sources.
EC-RUNTIME-2 therefore needs a usable read-only source construction and evidence
that actually enters it. Existing status is deliberately a replay projection.

EC-RUNTIME-0's historical receipt is missing. The roadmap explicitly calls
agent-harness#1000 unratified and requires a maintainer ruling with an explicit
retirement and replacement. Neither new green tests nor reconstructed chronology
closes that goal. Planning and independent reconciliation work may proceed;
phase completion must wait for the ruling and its accepted evidence.

Canonical `.phase-loop/` is authoritative. This checkout already registers
`v11-RUNTIME` as imported; `v10-RUNTIME` remains committed and the vergence row
orphaned. The plan-registration PR carries the v11 row, the minimal
roadmap-scoped frozen-test repair and the v10 `sl0_repairs` record together.
Legacy state cannot override canonical events, current Git state, or the roadmap
selection.

## Interface Freeze Gates

No new IF gate is produced: v11 Phase 6 declares `Produces: (none)`.
Consume these pre-existing contracts without claiming to re-produce them:

- IF-0-RUNTIME-1: `ExactStateProbes(git, github, provider, registry)`,
  `reconcile_train_state(state: RecoveredTrainState, probes: ExactStateProbes)
  -> ReconciliationVerdict`, `ReconciliationVerdict(binding, observations,
  blocker_reason, checked_at)`, `build_train_status` and `render_train_status`
  retain their public signatures. Status validity remains replay-derived.
- IF-0-FREEZE-5: `AuthoritySource`, `InvalidationTrigger` and
  `ReconciliationBinding` in `convergence/contracts.py` remain unchanged.
  Probe absence, failure, malformed results and unresolved authority fail closed;
  registry disagreement emits the appropriate authority and normative trigger,
  whereas a matching observation does not invalidate.
- IF-0-VC-2 and IF-0-GOVLEAN-1 are pre-existing verification/evidence contracts.
  New live evidence binds source identities, observed values, invocation time,
  production entry, verdict and controls; retain only bounded, non-secret metadata.

## Lane Index & Dependencies

SL-0 — Evidence policy and registration preamble
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no
SL-1 — Live reconciliation and registry controls
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no
SL-2 — Documentation and acceptance reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Evidence policy and registration preamble

- **Scope**: Prepare the evidence-loss decision and verify the successor registration without asserting that the historical goal passed.
- **Owned files**: `plans/manifest.json`, `phase-loop-runtime/tests/test_convergence_runtime_imports.py`, `docs/phase-loop/runtime-evidence-loss.md`
- **Interfaces provided**: RUNTIME registration record; evidence-loss decision packet
- **Interfaces consumed**: IF-0-GOVLEAN-1 (pre-existing); v11 Phase 6 (pre-existing); plan_manifest.append_entry (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Verify the plan-registration PR's repair coverage: selection is unique within the selected roadmap, rejects a duplicate within v11, preserves v10 grounding/history and keeps vergence orphaned. Extend coverage where needed through production plan discovery/reconciliation, not only a local list helper.
  - impl: Verify the existing `v11-RUNTIME` registration, roadmap-scoped test repair and `v10-RUNTIME` `sl0_repairs` record landed together in the plan PR. Preserve v10 as committed and all its existing fields/history. Any further test repair appends to that record with reason, actual before/after test digests, review/evidence references and scope; do not invent historical RED evidence or future commit identities. Use the manifest API and serialize this single-writer file against other phases.
  - impl: Write a metadata-only decision packet documenting the unavailable receipt, agent-harness#720, the unratified agent-harness#1000 proposal, permissible replacement evidence and the exact decision still needed. Seek the maintainer ruling through the structured owner-decision channel after presenting that packet. Record an existing explicit ruling if available; do not interpret silence or a proposal as approval. SL-0 may finish with the decision pending so SL-1 can proceed; EC-RUNTIME-0 remains open.
  - verify: `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_convergence_runtime_imports.py -q`
  - verify: `uv run --quiet --with-editable ./phase-loop-runtime python -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import check; r=check(Path.cwd()); assert r.exit_code == 0, r'`

### SL-1 — Live reconciliation and registry controls

- **Scope**: Supply fresh read-only authority observations to the production reconciler and prove registry divergence through the real source path.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py`, `phase-loop-runtime/tests/test_convergence_live_reconcile.py`, `docs/evidence/runtime-v11-live-reconciliation.json`, `docs/evidence/runtime-v11-live-tdd.json`
- **Interfaces provided**: live reconciliation evidence; fresh four-domain probe construction
- **Interfaces consumed**: RUNTIME registration record; evidence-loss decision packet; IF-0-RUNTIME-1 (pre-existing); IF-0-FREEZE-5 (pre-existing); ProviderCompletionContract (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add the new test module, review it and capture content-bound RED evidence before production edits. Bind each failure to the entered production symbol. Keep the existing frozen `test_convergence_reconcile.py`, `runtime_content_tdd_adapter.py` and `_runtime_tdd_guard.py` unchanged. New evidence proves this repair only.
  - test: Cover real Git reads and bounded GitHub/provider/registry read transports, fresh reads on consecutive decisions, domain-by-domain divergence, unavailable/stale/malformed sources, ambiguous provider outcomes, metadata redaction, and exact repository/node/attempt identity. Include a multi-node control that prevents one node's observation from satisfying another node's expected identity.
  - impl: Add production probe construction in the existing reconciliation module, returning `ExactStateProbes`. Bind it to explicit repository/node identities and read-only source configuration, use bounded argv-based subprocess or existing transport utilities, and normalize into the existing observation allow-list. Git resolves the current worktree/ref; GitHub resolves exact PR/head/merge state; provider uses its declared status endpoint; registry resolves the exact release/package identity independently of GitHub merge state. Never fill a missing domain from cached state or a successful test fixture.
  - impl: Preserve frozen verdict/enumeration shapes. `_ledgered` currently returns the last non-empty value across all nodes (board N1); make comparison node-specific so one node is never compared against another's ledger identity. Compare live identities to the corresponding recovered node, propagate required divergence flags, and invalidate verification/approval through the existing reconciliation path. Keep credential-bearing broker mutations and coordinator action wiring outside this lane.
  - test: Name the opt-in operational test `test_runtime_live_four_domain_operational` (board N2) and run it against accessible live Git, GitHub, provider and registry sources through the production constructor. Use an existing real release identity and a deliberately mismatching ledger expectation for the negative arm, then the matching expectation for the positive arm; this requires no remote publication or deletion. Record all four source entries and the actual registry result, emitted authority, invalidation and matching control. Also falsify each live read with a path-entered stub to prove its absence/divergence is detected.
  - impl: Store only metadata and artifact digests in the two owned evidence files. The live test uses `PHASE_LOOP_RUNTIME_LIVE_EVIDENCE=1`; with that flag, missing configuration, any skipped domain or a fixture substitution fails rather than skipping. Unit transport fixtures alone cannot satisfy EC-RUNTIME-2.
  - verify: `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k 'convergence_live_reconcile or convergence_reconcile'`
  - verify: `env PHASE_LOOP_RUNTIME_LIVE_EVIDENCE=1 uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k runtime_live_four_domain_operational`

### SL-2 — Documentation and acceptance reducer

- **Scope**: Reduce both producer lanes into accurate documentation and the governed acceptance disposition.
- **Owned files**: `docs/phase-loop/convergence-runtime.md`, `docs/evidence/runtime-v11-closeout.json`, `specs/phase-plans-v11.md`
- **Interfaces provided**: RUNTIME acceptance disposition
- **Interfaces consumed**: RUNTIME registration record; evidence-loss decision packet; live reconciliation evidence; fresh four-domain probe construction; spec_delta_closeout.v1 (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Check the ruling's identity and explicit scope, all four live source witnesses, both registry controls, new RED receipt, frozen-test repair record, runner-stamped verification and the two carried EC references. Missing evidence must leave its goal open.
  - impl: Update the runtime documentation from SL-0 and SL-1 findings, distinguishing live authority from replay status and new evidence from the lost receipt. Record exact evidence references, unresolved decisions and acceptance outcomes in the closeout artifact.
  - impl: Only after an explicit maintainer ruling, amend the RUNTIME section of v11 with the authorized retirement/replacement and cite the ruling; never rewrite the original V10 criterion. A resulting roadmap hash change requires runner-stamped amendment/replanning and refreshed plan review before execution resumes. Do not silently reseal this plan, change dependencies or make a proxy count as acceptance.
  - verify: Run the Verification commands below, consume both producer outcomes, and emit `spec_delta_closeout.v1` with `roadmap_amendment`. Pending policy is `product_decision_missing` with human input required; repairable command/evidence failures remain non-human. Phase completion is unavailable until the ruling, amended criterion and required live verification are all satisfied.

## Execution Notes

The two roadmap work lanes are SL-0 and SL-1; SL-2 is their terminal reducer.
All execution is serialized. No prose authorizes worker fanout; any later
concurrent dispatch requires disjoint ownership and scheduler-owned worktrees.
The reducer depends explicitly on both producers.

Registration, the minimal roadmap-scoped frozen-test repair and the
`v10-RUNTIME` `sl0_repairs` entry land together in the plan-registration PR,
before SL-0 execution. That PR keeps `v11-RUNTIME.if_gates_produced` empty and
runs the repaired tests and whole suite; SL-0 verifies or extends this record.
No manifest lifecycle or evidence-loss policy is waived by writing this plan.

Preserve the four delivered goals. `convergence/status.py`,
`convergence/event_log.py`, their tests, top-level `reconcile.py`,
`convergence/__init__.py`, `train_runner.py`, `cli.py`, broker files,
dependency manifests and lockfiles stay untouched: the remaining slice needs
no public export, status rewrite, runner lifecycle change or dependency.
INTEG retains transition-version binding (agent-harness#720 items 4–5),
before-action coordinator wiring and broker effects. No visible render is a
deliverable. No doc change is needed for README, CHANGELOG or release notes:
this phase changes neither installation nor release behavior; the runtime guide
is the affected public documentation, and SL-2 confirms that decision after both
producer lanes.

Before operational access is declared unavailable, inspect repo configuration
and metadata-only CLI access (`gh`, `op` and the relevant provider/registry).
Never copy credentials, environment values or raw provider output into evidence.
A missing required live source blocks operational acceptance; it does not turn
unit fixtures into live evidence. Ratified plan/production review follows v11
Execution Notes, including independent cross-vendor evidence where required.

Use CLI/operator override, phase-plan policy, roadmap policy, Dispatch Hints,
then registry defaults in that order. This plan adds no model/executor override
and grants no silent downgrade.

## Execution Policy

- SL-2: work-unit=`phase_reducer`

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-v11.md`
- evidence paths: `docs/phase-loop/runtime-evidence-loss.md`, `docs/evidence/runtime-v11-live-reconciliation.json`, `docs/evidence/runtime-v11-live-tdd.json`, `docs/evidence/runtime-v11-closeout.json`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment`

## Verification

Run from the repository root, narrow checks before the whole suite. The frontmatter
is the effective automation.suite_command. The local validator is used because
this checkout does not yet have LOOPFIX's validate-plan command. Validate parsed
commands with IF-0-VC-2 before handoff. The plan-registration PR runs the
frozen-test repair checks and whole suite; live implementation verification
remains for SL-1.

- `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k 'convergence_live_reconcile or convergence_reconcile or convergence_runtime_imports'`
- `env PHASE_LOOP_RUNTIME_LIVE_EVIDENCE=1 uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k runtime_live_four_domain_operational`
- `uv run --quiet --with-editable ./phase-loop-runtime python -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import check; r=check(Path.cwd()); assert r.exit_code == 0, r'`
- `uv run --quiet --with-editable ./phase-loop-runtime python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v11-RUNTIME.md`
- `uv run --quiet --with-editable ./phase-loop-runtime phase-loop validate-roadmap specs/phase-plans-v11.md`
- `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q`
- `git diff --check`

The maintainer ruling is operational evidence in
`docs/phase-loop/runtime-evidence-loss.md`. The runner-stamped roadmap amendment
must bind the ruling and the accepted replacement criterion; machine checks or
an operator proposal cannot manufacture that authorization. Store verification
receipts through the canonical runner evidence mechanism and link them from
`docs/evidence/runtime-v11-closeout.json`.

## Acceptance Criteria

- [ ] EC-RUNTIME-0 — proven by the maintainer ruling and runner-stamped explicit retirement/replacement amendment referenced in `docs/phase-loop/runtime-evidence-loss.md`, plus the replacement's authorized verification command; falsified by an unratified proposal, missing historical receipt presented as recovered, absent `sl0_repairs` record or completion without the accepted replacement evidence. Path-entered control: production plan discovery/reconciliation resolves the selected v11 plan while preserving historical v10 grounding; the test command is `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_convergence_runtime_imports.py -q`. This command checks registration only and cannot by itself close EC-RUNTIME-0.
- [ ] EC-RUNTIME-2 — proven by `env PHASE_LOOP_RUNTIME_LIVE_EVIDENCE=1 uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k runtime_live_four_domain_operational` and `docs/evidence/runtime-v11-live-reconciliation.json`; falsified by any stubbed/skipped live domain, missed actual registry disagreement or blanket invalidation of the matching control. Path-entered control: enter the production probe constructor and `reconcile_train_state`, observe every live source and distinguish the divergent and matching registry arms.
