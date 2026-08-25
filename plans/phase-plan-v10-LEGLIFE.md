---
phase_loop_plan_version: 1
phase: LEGLIFE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_panel_invoker_spawn.py phase-loop-runtime/tests/test_panel_invoker_timeout_argv.py phase-loop-runtime/tests/test_advisor_board_concurrency.py phase-loop-runtime/tests/test_advisor_board_integration.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_resolver.py phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py phase-loop-runtime/tests/test_advisor_board_observability.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py'
---

# LEGLIFE: Board Leg Lifecycle and Production Reachability

## Context

LEGLIFE makes every Advisor Board leg terminal, reaped, and materially accountable,
then connects the existing configurable board, Omnigent backing, and observability
surfaces to the supported `advisor-board` phase-loop CLI entrypoint. The source already
has bounded orchestration, process-group termination, `load_boards()`,
`BoardResolver`, `OmnigentBacking.from_env()`, and `AsyncForwardingSink`; the live
CLI still hardcodes `compose_review_board()`, supplies neither Omnigent nor a ledger
sink, and exposes none of the documented named-board or ad-hoc-seat flags. There is
also no supported public single-leg entrypoint.

Implementation is blocked on REVIEWTRUTH. The `plans/manifest.json` lifecycle ledger
must record REVIEWTRUTH `completed` and the execution base must contain
`IF-0-REVIEWTRUTH-1`, including the production marker, typed `PanelLegOutcome`,
`PanelLegResult.outcome`, and load-bearing lens carrier. Worktree-local
`.phase-loop/` is runner telemetry and legacy `.codex/phase-loop/` is compatibility
data; neither can satisfy this gate.

`SL-0` freezes the HARDEN-style activation contract before production. It declares
sorted, unique, disjoint literal `SL1_NODEIDS` and `SL2_NODEIDS` tuples plus
`LEGLIFE_NODEIDS == tuple(sorted((*SL1_NODEIDS, *SL2_NODEIDS)))`. `SL-1` installs
`LEGLIFE_SL1_CAPABILITY_MARKER = "leglife-sl1@1"` and only its partition may
activate from that marker. `SL-2` installs
`LEGLIFE_SL2_CAPABILITY_MARKER = "leglife-sl2@1"` and only its partition may
activate from that marker. With activation variables absent, a missing lane marker
skips only that lane's new nodes; marker presence runs them. Setting the matching
`PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1` or
`PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1` forces only that partition to run regardless
of marker, producing retained RED on the tests-only base and GREEN after its lawful
writer. Unknown activation values fail loud. The default `automation.suite_command`
is therefore green at `SL-0`, incrementally complete after each marker, and complete
after `SL-2`; final joined verification explicitly runs both partitions' union.

The binding source/roadmap authority is `Consiliency/agent-harness#375` and the
current plan bytes are selected by the appended `plan_current_authority.v1` digest
record in `plans/manifest.json`. Live Git inspection establishes that the reviewed
capsule parent descends from the manifest's historical planning base, while the
telemetry-recorded head is a stale sibling child of that planning base and is not
an ancestor of the reviewed candidate. Telemetry's `current_phase=LEGIBLE` also
conflicts with its LEGLIFE closeout summary. These named roles and relationships
are ancestry/provenance facts to recompute at dispatch, never lifecycle or plan
authority and never pinned commit identities or future outputs.

## Interface Freeze Gates

- None. The roadmap declares `Produces: (none)`. The contracts below are
  phase-internal boundaries; LEGLIFE consumes `IF-0-REVIEWTRUTH-1` without
  redefining it.

## Lane Index & Dependencies

SL-0 — Immutable tests-only lifecycle contract
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Leg termination, single-leg API, and material parity
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Production board, Omnigent, and state-ledger activation
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation and LEGLIFE evidence reduction
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable tests-only lifecycle contract

- **Scope**: Land the complete default-green, partition-activated LEGLIFE falsifier
  inventory before any production edit.
- **Owned files**: `phase-loop-runtime/tests/test_leglife_phase.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`
- **Interfaces provided**: `LEGLIFE_RED_SUITE`, `LEGLIFE_NODE_PARTITIONS`
- **Interfaces consumed**: `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: no.
- **Tasks**:
  - test: freeze the marker/activation rules and these exact new nodeids:
    `SL1_NODEIDS` owns `test_timeout_outcome_and_bound`,
    `test_aggregate_quiescence`, `test_supported_single_leg_entrypoint`, and
    `test_material_parity_or_typed_asymmetry`; `SL2_NODEIDS` owns
    `test_custom_seat_lens_prompt`, `test_configured_default_board_reaches_prompt`,
    `test_production_entry_preserves_harden_isolation_and_govlean_review_tier`,
    `test_omnigent_production_reachability`, and
    `test_real_ledger_production_reachability`. Keep
    `test_tests_first_chronology` as an always-on control outside both activated
    partitions. Assert exact tuple sorting, uniqueness, disjointness, and union.
  - test: cover typed timeout, process-tree quiescence, bounded success, shared-path
    `invoke_leg()`, custom/default config and lens propagation, material parity or
    typed asymmetry, active isolation/review-tier enforcement, Omnigent and ledger
    reachability, and zero-production-caller prohibitions. Amend only sanctioned
    additive result fields in the existing golden inventory.
  - impl: land only the two owned test paths. They become immutable; later lanes add
    no tests.
  - verify: run the complete default suite and require green. Then force `SL1_NODEIDS`
    and `SL2_NODEIDS` separately on the implementation-free base, require every
    exact node to reach its unique `LEGLIFE_RED::<criterion>` anchor and fail for
    the intended reason, retain evidence, and obtain tests-only review before `SL-1`.

### SL-1 — Leg termination, single-leg API, and material parity

- **Scope**: Make provider lifecycles terminal and expose the supported single-leg
  seam while preserving the frozen `invoke_panel()` call shape.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: `LEGLIFE_LEG_RUNTIME`, `invoke_leg`, `LEGLIFE_MATERIAL_ATTESTATION`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `LEGLIFE_NODE_PARTITIONS`, `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: no; `SL-2` consumes its material interface.
- **Tasks**:
  - test: use only immutable `SL1_NODEIDS` and existing panel modules.
  - impl: install only `LEGLIFE_SL1_CAPABILITY_MARKER`; map timeout/stall/deadline
    arms to `PanelLegOutcome.TIMED_OUT`; ensure normal, exceptional, and retry
    paths terminate and reap owned process groups before `_run_legs_ordered()`
    returns; preserve bounded success and ordered aggregation.
  - impl: add public `invoke_leg()` as a one-seat specialization over
    `invoke_board()` artifact resolution, prompt rendering, environment,
    spawn/retry, timeout, callback, and cleanup machinery, not a second launcher.
  - impl: carry additive metadata-only `material_digest` and typed
    `material_asymmetry` on every result. CLI-backed legs bind the same staged
    bytes; Gemini/agy either binds that digest or records a nonempty enum-backed
    reason. Transcript inference and silent omission are forbidden.
  - verify: force and run only exact `SL1_NODEIDS` on the `SL-0` base plus this
    writer, require GREEN, run legacy panel/spawn/timeout/concurrency/integration
    regressions, and mutation-kill each timeout/reaper/material anchor. Do not
    require or activate `SL2_NODEIDS`.

### SL-2 — Production board, Omnigent, and state-ledger activation

- **Scope**: Make configuration and integration seams reachable from the live
  `advisor-board` command while preserving upstream security and review authority.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py`
- **Interfaces provided**: `LEGLIFE_PRODUCTION_BOARD_ENTRY`, `LEGLIFE_STATE_LEDGER_BRIDGE`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `LEGLIFE_NODE_PARTITIONS`, `LEGLIFE_MATERIAL_ATTESTATION` (from SL-1), `load_boards` and `BoardResolver` (pre-existing), `OmnigentBacking.from_env` and `AsyncForwardingSink` (pre-existing), `EC-HARDEN-5` operation-bound isolation authorization (upstream constraint), active GOVLEAN `authority_switch` / `ReviewLandingTier` policy (pre-existing constraint), `IF-0-REVIEWTRUTH-1` (pre-existing)
- **Parallel-safe**: no; it starts from the green `SL-1` base.
- **Tasks**:
  - test: use only immutable `SL2_NODEIDS` and existing config, resolver,
    Omnigent, observability, and CLI modules.
  - impl: add mutually exclusive `--board NAME` and `--seats SPECS`, optional
    `--board-config PATH`, and the existing-policy landing-tier input required
    after the GOVLEAN switch. Obtain and revalidate the fresh operation-bound
    EC-HARDEN-5 authorization before the first config availability/auth/session/
    provider/broker/callback/spawn effect; custom flags cannot bypass it or the
    active review-tier seat policy.
  - impl: load the strict TOML once. Do not use one-shot `resolve_board()` for a
    bare invocation because it hardcodes `default_board="default"`. Construct
    `BoardResolver(cfg.boards, default_board=cfg.default_board)` and call
    `.resolve(name, seats=...)` so `BoardConfig.default_board` is authoritative.
    Pass the resulting `Board` and load-bearing lens through `invoke_board()`;
    do not duplicate parsing or edit `composition.py`.
  - impl: construct `OmnigentBacking.from_env(os.environ)` and thread it to
    `invoke_board()`. Preserve missing URL as typed unavailable and never print
    tokens.
  - impl: add a production `LedgerWriter` bridge whose child owns the real
    omniagent-plus `AuditLedger.appendRuntimeEvent` call and assigns IDs/sequence.
    Activate only through repeatable argv tokens for explicit
    `--state-ledger-append-command`, stream metadata-only records over stdin with
    acknowledgement, and leave retention/replay/locking/compaction/identity
    TS-side. Build `StateLedgerSink`, wrap `AsyncForwardingSink`, pass `sink=`,
    and close/drain after return. Missing command remains no-op; forwarding
    failure is best-effort and cannot alter outcomes.
  - impl: consume `LEGLIFE_MATERIAL_ATTESTATION` directly and serialize `outcome`,
    material digest/asymmetry, and forwarding status in metadata-only JSON. No
    `getattr`, absent-field fallback, or silent omission is permitted. Export new
    observability types lazily from `advisor_board.__init__`.
  - impl: install only `LEGLIFE_SL2_CAPABILITY_MARKER` after every `SL-2`
    production path is present.
  - verify: force exact `SL2_NODEIDS` on the lawful `SL-1` base plus this writer
    and require GREEN; rerun `SL1_NODEIDS` as a regression and the focused CLI,
    config, resolver, Omnigent, observability, timeout, concurrency, and integration
    modules. Use a local fake append command for argv/ack controls.

### SL-3 — Documentation and LEGLIFE evidence reduction

- **Scope**: Reconcile public documentation with the integrated production surface
  and reduce exact-head lifecycle evidence.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: `LEGLIFE_COMPLETION_EVIDENCE`
- **Interfaces consumed**: `LEGLIFE_RED_SUITE`, `LEGLIFE_NODE_PARTITIONS`, `LEGLIFE_LEG_RUNTIME`, `invoke_leg`, `LEGLIFE_MATERIAL_ATTESTATION`, `LEGLIFE_PRODUCTION_BOARD_ENTRY`, `LEGLIFE_STATE_LEDGER_BRIDGE`
- **Parallel-safe**: no; it consumes both production writers.
- **Tasks**:
  - test: run the joined partition union and focused modules before documentation;
    doc edits cannot substitute for runtime proof.
  - impl: replace aspirational examples with exact supported flags/config precedence;
    document `invoke_leg()`, timeout/quiescence, material parity/asymmetry, Omnigent,
    the external ledger boundary, EC-HARDEN-5 isolation, and GOVLEAN tier behavior.
    After reviewing installation, packaging, and release identity, record the
    explicit no-doc-change decision here: `README.md`, `CHANGELOG.md`, and
    release notes are already current and require no change.
  - verify: rerun extracted focused, broad, and static commands on the joined
    candidate; check immutable tests-first ancestry and owned-path boundaries;
    record observed plan/roadmap digests and metadata-only evidence.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: executor=`codex`, model=`gpt-5.6-terra`, effort=`high`, work-unit=`lane_execute`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`LEGLIFE whole-phase single-vendor authorship`
- SL-3: executor=`codex`, model=`gpt-5.6-terra`, effort=`high`, work-unit=`phase_reducer`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`same-vendor terminal documentation and evidence reduction`

One Codex vendor owns `SL-0` tests, both production lanes, and `SL-3`. Cross-vendor
implementation rotation and lane/phase scheduler fanout remain off. The lanes are
serial because of the material interface even though their write sets and activated
nodeid partitions are disjoint.

## Verification

These bullet-form commands are the final joined runner contract; fenced commands are
not authoritative. `SL-0` uses the default command as its green machine gate and
records each forced partition's expected RED separately. `SL-1` closes with the
forced SL-1 command only. `SL-2` closes with the forced SL-2 command on the `SL-1`
base. Only the joined candidate may run the forced union and the full extracted set.

- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_panel_invoker_spawn.py phase-loop-runtime/tests/test_panel_invoker_timeout_argv.py phase-loop-runtime/tests/test_advisor_board_concurrency.py phase-loop-runtime/tests/test_advisor_board_integration.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_resolver.py phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py phase-loop-runtime/tests/test_advisor_board_observability.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`
- `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py::test_timeout_outcome_and_bound phase-loop-runtime/tests/test_leglife_phase.py::test_aggregate_quiescence phase-loop-runtime/tests/test_leglife_phase.py::test_supported_single_leg_entrypoint phase-loop-runtime/tests/test_leglife_phase.py::test_material_parity_or_typed_asymmetry`
- `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py::test_custom_seat_lens_prompt phase-loop-runtime/tests/test_leglife_phase.py::test_configured_default_board_reaches_prompt phase-loop-runtime/tests/test_leglife_phase.py::test_production_entry_preserves_harden_isolation_and_govlean_review_tier phase-loop-runtime/tests/test_leglife_phase.py::test_omnigent_production_reachability phase-loop-runtime/tests/test_leglife_phase.py::test_real_ledger_production_reachability`
- `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py::test_timeout_outcome_and_bound phase-loop-runtime/tests/test_leglife_phase.py::test_aggregate_quiescence phase-loop-runtime/tests/test_leglife_phase.py::test_supported_single_leg_entrypoint phase-loop-runtime/tests/test_leglife_phase.py::test_material_parity_or_typed_asymmetry phase-loop-runtime/tests/test_leglife_phase.py::test_custom_seat_lens_prompt phase-loop-runtime/tests/test_leglife_phase.py::test_configured_default_board_reaches_prompt phase-loop-runtime/tests/test_leglife_phase.py::test_production_entry_preserves_harden_isolation_and_govlean_review_tier phase-loop-runtime/tests/test_leglife_phase.py::test_omnigent_production_reachability phase-loop-runtime/tests/test_leglife_phase.py::test_real_ledger_production_reachability`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"`
- `uv run --project phase-loop-runtime ruff check phase-loop-runtime`
- `uv --project phase-loop-runtime lock --check`
- `python3 phase-loop-runtime/scripts/check_model_id_sources.py`
- `git diff --check`

Production-reachability invariant: the exact `SL2_NODEIDS` behavioral controls and
source-structure assertions together must prove the live CLI supplies both
`OmnigentBacking.from_env()` and an `AsyncForwardingSink` to `invoke_board()`,
and that the production writer delegates to the external state-ledger owner while
`JsonlLedgerWriter` remains reference-only. Grep alone, a test-injected caller, or a
source assertion without the path-entered behavioral control is insufficient.

## Execution Notes

- Before `SL-0`, reconcile the manifest ledger with live Git and `.phase-loop/`
  telemetry using the ancestry/provenance classification above. Recompute rather
  than copying stale heads. If REVIEWTRUTH or its consumed surface is absent, stop
  with `upstream_phase_unmet`.
- `plans/manifest.json`, `.phase-loop/**`, evidence, and closeout control are
  runner-owned and excluded from lane ownership. The plan pins no future SHA,
  commit count, PR, or topology.
- `SL-0` paths are immutable after their tests-only landing. A correction requires
  a separately reviewed tests-only successor before production resumes.
- No dependency, lockfile, migration, generated client, fixture snapshot, or
  environment-example change is expected. Existing Omnigent environment names
  remain authoritative; the ledger bridge uses explicit CLI argv.

## Acceptance Criteria

- [ ] EC-LEGLIFE-0 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k tests_first_chronology`; falsified by path-entered `verification_evidence.v3` controls observing implementation in the tests-only landing or production without the immutable tests ancestor.
- [ ] EC-LEGLIFE-1 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k timeout_outcome_and_bound`; falsified by a path-entered timeout mutation observing a non-`TIMED_OUT` result, live process group, or breached bound before the restored positive control.
- [ ] EC-LEGLIFE-2 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k aggregate_quiescence`; falsified by a path-entered reaper mutation observing aggregate return with a live descendant before the restored control.
- [ ] EC-LEGLIFE-3 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k supported_single_leg_entrypoint`; falsified by a path-entered mutation observing bypass of shared staging, prompt, spawn, timeout, or cleanup machinery.
- [ ] EC-LEGLIFE-4 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k custom_seat_lens_prompt`; falsified by a path-entered resolver/prompt mutation observing the configured seat or exact lens absent.
- [ ] EC-LEGLIFE-5 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL1=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k material_parity_or_typed_asymmetry`; falsified by a path-entered material mutation observing unequal digests without nonempty typed asymmetry.
- [ ] EC-LEGLIFE-6 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k omnigent_production_reachability` under the production-reachability invariant above; falsified by its path-entered CLI mutation before the restored control.
- [ ] EC-LEGLIFE-7 — proven by `PHASE_LOOP_TDD_EXPECT_LEGLIFE_SL2=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_leglife_phase.py -k real_ledger_production_reachability` under the production-reachability invariant above; falsified by its path-entered CLI/bridge mutation before the restored control.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none outside this repository
- evidence paths: `plans/evidence/v10-LEGLIFE-tests-first.json`, `plans/evidence/v10-LEGLIFE-verification.json`
- redaction posture: `metadata_only`
- downstream handling: no canonical spec, roadmap, mirror, or cross-repository update; retain metadata-only phase evidence and preserve roadmap bytes.
