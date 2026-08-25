---
phase_loop_plan_version: 1
phase: LEGLIFE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command: 'PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_panel_invoker_spawn.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_resolver.py phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py phase-loop-runtime/tests/test_advisor_board_observability.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py'
---

# LEGLIFE: Board Leg Lifecycle and Production Reachability

## Context

LEGLIFE makes every Advisor Board leg terminal, reaped, and materially accountable,
then connects the already-built configurable board, Omnigent backing, and observability
surfaces to the supported `advisor-board` phase-loop CLI entrypoint. The current source
already has bounded concurrent orchestration, process-group termination helpers,
`load_boards()` / `resolve_board()`, `OmnigentBacking.from_env()`, and
`AsyncForwardingSink`; however, the live CLI still always calls
`compose_review_board()`, supplies neither Omnigent nor a ledger sink, and exposes none
of the documented named-board or ad-hoc-seat flags. `invoke_panel()` can be narrowed to
one leg internally, but no supported single-leg public entrypoint exists.

The execution prerequisite is REVIEWTRUTH and its `IF-0-REVIEWTRUTH-1` outcome/lens
contract. The authoritative phase lifecycle ledger in `plans/manifest.json` records
REVIEWTRUTH as `committed`, so LEGLIFE may be planned now but no implementation lane may
dispatch until that ledger records REVIEWTRUTH `completed` and the production marker,
typed `PanelLegOutcome`, `PanelLegResult.outcome`, and load-bearing lens carrier exist on
the execution base. Worktree-local `.phase-loop/` runner telemetry does not satisfy that
completion gate, and legacy `.codex/phase-loop/` state is not an authority or blocker.

The roadmap requires an immutable tests-only landing before production work. `SL-0`
therefore freezes a dual-mode LEGLIFE suite: default mode stays green on the tests-only
base, while `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1` requires anchored RED failures until the
production marker `LEGLIFE_CAPABILITY_MARKER = "leglife@1"` appears. After that landing,
`SL-1` and `SL-2` are disjoint production writers corresponding to the roadmap's two
functional lanes and may run in parallel. `SL-3` is the terminal documentation and
evidence reducer and depends on every producer.

## Interface Freeze Gates

- None. The roadmap declares `Produces: (none)` for LEGLIFE. The phase-internal
  contracts below are implementation boundaries and are not promoted to cross-phase IF
  gates. LEGLIFE consumes `IF-0-REVIEWTRUTH-1` without redefining it.

## Lane Index & Dependencies

SL-0 — Immutable tests-only lifecycle contract
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Leg termination, single-leg API, and material parity
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Production board, Omnigent, and state-ledger activation
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Documentation and LEGLIFE evidence reduction
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable tests-only lifecycle contract

- **Scope**: Land the complete LEGLIFE falsifier inventory before any production edit,
  preserving default CI while proving the activated suite is RED for the intended source
  anchors.
- **Owned files**: `phase-loop-runtime/tests/test_leglife_phase.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`
- **Interfaces provided**: `LEGLIFE_RED_SUITE`
- **Interfaces consumed**: `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: no.
- **Tasks**:
  - test: add the shared dual-mode guard, exact marker check, unique
    `LEGLIFE_RED::<criterion>` failure anchors, and tests for typed timeout outcome,
    process-tree quiescence before aggregation, bounded successful completion, a public
    single-leg entrypoint using the board spawn/staging path, custom config seat/lens
    prompt propagation, Gemini/agy material equivalence or typed asymmetry, CLI
    construction of Omnigent and real-ledger forwarding, and the zero-production-caller
    prohibitions. Amend only the sanctioned additive result fields in the existing
    golden inventory.
  - impl: land only the two owned test paths and record the observed tests-only base and
    landing relationship without prescribing a future commit identifier or count.
  - verify: run the two modules without the activation variable and require green; then
    run with `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1`, require the anchored RED inventory, and
    obtain the required tests-only review before either production lane dispatches.

### SL-1 — Leg termination, single-leg API, and material parity

- **Scope**: Make the provider lifecycle terminal and expose the supported single-leg
  seam while preserving the frozen legacy `invoke_panel()` call shape.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: `LEGLIFE_LEG_RUNTIME`, `invoke_leg`, `LEGLIFE_MATERIAL_ATTESTATION`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: yes; its sole writer is disjoint from SL-2.
- **Tasks**:
  - test: use only the immutable SL-0 assertions and mutation anchors; add no tests in
    this lane.
  - impl: install `LEGLIFE_CAPABILITY_MARKER = "leglife@1"`; map timeout/stall/deadline
    arms to `PanelLegOutcome.TIMED_OUT`; ensure normal, exceptional, and retry paths
    terminate and reap every owned process group before `_run_legs_ordered()` returns;
    retain the positive bounded-success path and ordered aggregate semantics.
  - impl: add public `invoke_leg()` as a one-seat specialization over the same artifact
    resolution, prompt rendering, environment, spawn/retry, timeout, callback, and cleanup
    machinery used by `invoke_board()`, rather than a second launcher.
  - impl: carry additive metadata-only `material_digest` and typed
    `material_asymmetry` on each result. All CLI-backed legs bind the same resolved staged
    material bytes. A Gemini/agy route either binds that same digest or records a nonempty
    enum-backed asymmetry reason; transcript inference and silent omission are forbidden.
  - verify: run the activated SL-0 lifecycle/material assertions, the legacy panel
    golden, spawn, timeout, concurrency, and board integration modules; mutate each
    timeout/reaper/material anchor and require the intended test to fail.

### SL-2 — Production board, Omnigent, and state-ledger activation

- **Scope**: Make existing configuration and integration seams reachable from the live
  `advisor-board` phase-loop command without changing board composition ownership.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py`
- **Interfaces provided**: `LEGLIFE_PRODUCTION_BOARD_ENTRY`, `LEGLIFE_STATE_LEDGER_BRIDGE`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `load_boards` (pre-existing), `resolve_board` (pre-existing), `OmnigentBacking.from_env` (pre-existing), `AsyncForwardingSink` (pre-existing), `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: yes; its writers are disjoint from SL-1.
- **Tasks**:
  - test: use only the immutable SL-0 assertions and existing config, resolver,
    Omnigent, observability, and CLI tests; add no tests in this lane.
  - impl: add mutually exclusive `--board NAME` and `--seats SPECS` plus optional
    `--board-config PATH` to the `advisor-board` parser. The command loads the existing
    strict TOML schema, resolves the named/default/ad-hoc board, and passes the resulting
    `Board` to `invoke_board()`. Do not duplicate config parsing or edit
    `composition.py`; REVIEWTRUTH makes the already-carried lens load-bearing.
  - impl: construct `OmnigentBacking.from_env(os.environ)` in the live command and pass
    it to `invoke_board()` so configured Omnigent seats are reachable. Preserve missing
    gateway URL as the existing typed unavailable result and never print gateway tokens.
  - impl: add a production `LedgerWriter` bridge whose child process owns the real
    omniagent-plus `AuditLedger.appendRuntimeEvent` call and assigns ledger record IDs and
    sequence. Activate it only through an explicit `--state-ledger-append-command`
    argument supplied as repeatable argv tokens, stream metadata-only runtime-event
    payloads over stdin with acknowledged success/failure, and do not reimplement ledger
    retention, replay, locking, compaction, record IDs, or sequence in Python. The live
    command constructs `StateLedgerSink`, wraps it in `AsyncForwardingSink`, passes the
    sink to `invoke_board()`, and closes/drains it after the board returns. A missing
    explicit command retains the current no-op sink; configured bridge failure remains
    best-effort observability and cannot alter a leg outcome.
  - impl: surface `outcome`, material digest/asymmetry, and ledger forwarding status in
    metadata-only JSON output without exposing raw secrets. Export new observability
    types lazily from `advisor_board.__init__` so optional production integration does not
    make bare package import eager or fragile.
  - verify: run the activated SL-0 production-reachability assertions and existing CLI,
    config, resolver, Omnigent, and observability modules. The integration control uses a
    local fake append command that acknowledges records and proves argv boundaries; a
    source-structure assertion proves the production bridge delegates to the configured
    real-ledger owner rather than `JsonlLedgerWriter`.

### SL-3 — Documentation and LEGLIFE evidence reduction

- **Scope**: Reconcile the public capability card and normative integration contract
  with the actual production surface, then reduce exact-head lifecycle evidence.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: `LEGLIFE_COMPLETION_EVIDENCE`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `LEGLIFE_LEG_RUNTIME`, `invoke_leg`, `LEGLIFE_MATERIAL_ATTESTATION`, `LEGLIFE_PRODUCTION_BOARD_ENTRY`, `LEGLIFE_STATE_LEDGER_BRIDGE`
- **Parallel-safe**: no; it runs only after both production writers are integrated.
- **Tasks**:
  - test: run the complete immutable SL-0 suite and all focused existing modules before
    changing documentation; a doc-only mutation must not stand in for runtime proof.
  - impl: replace aspirational invocation examples with the exact supported flags and
    config precedence; document `invoke_leg()`, typed timeout, aggregate quiescence,
    material parity/asymmetry, Omnigent reachability, and the external real-ledger bridge.
  - impl: retain the launcher-versus-observability boundary and state explicitly that
    Python never assigns real ledger IDs/sequences or owns retention/replay/compaction.
  - verify: rerun focused and broad verification on the exact candidate, check the
    immutable tests-only ancestry and production-only changed-path boundaries, record the
    exact plan and roadmap digests, and emit the two metadata-only evidence artifacts.

## Execution Policy

- work-unit defaults: `work-unit=lane_execute`, `fallback=inherit_default`, `policy-source=roadmap`, `inherit-default=true`
- SL-3: `work-unit=phase_reducer`, `fallback=inherit_default`, `policy-source=plan`, `inherit-default=true`, `override-reason=terminal documentation and evidence reduction`

Policy precedence is CLI/operator override, this phase-plan policy, roadmap policy,
`Dispatch Hints`, then registry defaults. An executor or effort downgrade is forbidden
unless the selected policy explicitly names a fallback or inherits the registry default.

## Verification

Run from the repository root. The tests-only lane records both modes before production:

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_leglife_phase.py \
  phase-loop-runtime/tests/test_advisor_board_golden.py
PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 \
  PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_leglife_phase.py \
  phase-loop-runtime/tests/test_advisor_board_golden.py
```

After SL-1 and SL-2, the activated focused gate is:

```bash
PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 \
  PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_leglife_phase.py \
  phase-loop-runtime/tests/test_advisor_board_golden.py \
  phase-loop-runtime/tests/test_panel_invoker.py \
  phase-loop-runtime/tests/test_panel_invoker_spawn.py \
  phase-loop-runtime/tests/test_panel_invoker_timeout_argv.py \
  phase-loop-runtime/tests/test_advisor_board_concurrency.py \
  phase-loop-runtime/tests/test_advisor_board_integration.py \
  phase-loop-runtime/tests/test_advisor_board_config.py \
  phase-loop-runtime/tests/test_advisor_board_resolver.py \
  phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py \
  phase-loop-runtime/tests/test_advisor_board_observability.py \
  phase-loop-runtime/tests/test_advisor_board_cli_legacy.py
```

Static and broad gates are:

```bash
cd phase-loop-runtime
uv run --locked ruff check .
uv lock --check
python3 scripts/check_model_id_sources.py
cd ..
git diff --check
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests -m "not dotfiles_integration"
```

The reducer must also prove the live CLI contains one production call that passes both an
`OmnigentBacking.from_env()` result and an `AsyncForwardingSink` to `invoke_board()`, and
that the configured production writer delegates to the external state-ledger owner while
`JsonlLedgerWriter` remains reference-only. This source reachability proof is paired with
`test_leglife_phase.py` behavioral assertions and is not accepted as grep-only evidence.

## Execution Notes

- `plans/manifest.json` is the phase lifecycle ledger; `.phase-loop/` is authoritative
  for current runner-process telemetry. They must reconcile before dispatch, and neither
  may silently erase a contradiction. Legacy `.codex/phase-loop/` artifacts are
  compatibility data and never supersede or block either canonical surface.
- Before SL-0, require REVIEWTRUTH complete on the execution base and validate the exact
  `IF-0-REVIEWTRUTH-1` marker/outcome/lens surface. If absent, stop before dispatch with
  `upstream_phase_unmet`; do not weaken or locally recreate REVIEWTRUTH.
- `plans/manifest.json`, `.phase-loop/**`, evidence artifacts, and closeout control are
  runner-owned and excluded from lane ownership. Lane closeouts record observed digests
  and ancestry after work exists; the plan pins no future SHA, commit count, or topology.
- The SL-0 paths are immutable after their tests-only landing. Any correction requires a
  separately reviewed tests-only successor before production resumes; SL-1 and SL-2 may
  not edit tests.
- SL-1 and SL-2 may execute in parallel only after the same reviewed SL-0 landing is an
  ancestor of both execution bases. SL-3 waits for both integrated production writers.
- No dependency, lockfile, migration, generated-client, fixture snapshot, or environment
  example change is expected. The existing Omnigent environment variable names remain
  authoritative; the ledger bridge is activated by explicit CLI argv.
- Public-doc no-doc-change decision: `README.md`, `CHANGELOG.md`, and release notes are
  already current because LEGLIFE does not change installation, packaging, or release
  identity. The capability card and normative Advisor Board contract are the only public
  documentation surfaces whose behavior changes.
- This phase is not a visible avatar or browser-media render deliverable, so no visual
  evidence artifact is required.

## Acceptance Criteria

- [ ] EC-LEGLIFE-0 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k tests_first_chronology`; falsified by `verification_evidence.v3` path-entered controls that observe an implementation source change in the tests-only landing or a production landing whose recorded base does not contain the immutable tests landing.
- [ ] EC-LEGLIFE-1 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k timeout_outcome_and_bound`; falsified by a `verification_evidence.v3` path-entered timeout mutation that observes a result other than `PanelLegOutcome.TIMED_OUT`, a surviving process group, or a breached bound before the restored positive control.
- [ ] EC-LEGLIFE-2 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k aggregate_quiescence`; falsified by a `verification_evidence.v3` path-entered reaper mutation that observes aggregate return while a provider descendant is still alive before the restored quiescent control.
- [ ] EC-LEGLIFE-3 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k supported_single_leg_entrypoint`; falsified by a `verification_evidence.v3` path-entered API mutation that observes the public entrypoint bypass artifact staging, prompt rendering, spawn, timeout, or cleanup machinery before the restored shared-path control.
- [ ] EC-LEGLIFE-4 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k custom_seat_lens_prompt`; falsified by a `verification_evidence.v3` path-entered resolver or prompt mutation that observes the configured seat or exact lens absent from the spawned prompt before the restored config control.
- [ ] EC-LEGLIFE-5 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k material_parity_or_typed_asymmetry`; falsified by a `verification_evidence.v3` path-entered material mutation that observes unequal Gemini/agy material digests without a nonempty typed asymmetry before the restored parity control.
- [ ] EC-LEGLIFE-6 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k omnigent_production_reachability`; falsified by a `verification_evidence.v3` path-entered CLI mutation that observes a configured Omnigent seat reach `invoke_board()` without the `OmnigentBacking.from_env()` result before the restored production control.
- [ ] EC-LEGLIFE-7 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k real_ledger_production_reachability`; falsified by a `verification_evidence.v3` path-entered CLI or bridge mutation that observes zero production sink callers, direct `JsonlLedgerWriter` use, Python-assigned real ledger identity, or an undrained sink before the restored external-ledger control.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none outside this repository
- evidence paths: `plans/evidence/v10-LEGLIFE-tests-first.json`, `plans/evidence/v10-LEGLIFE-verification.json`
- redaction posture: `metadata_only`
- downstream handling: no canonical spec, roadmap, mirror, or cross-repository update is expected; retain phase evidence locally and leave the roadmap bytes unchanged.
