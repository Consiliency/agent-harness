---
phase_loop_plan_version: 1
phase: JEVHOST
roadmap: specs/phase-plans-jevhost-v1.md
roadmap_sha256: 79dae858f5b456625b4cb72e751fb91085d9280e7dfa87b6125d2d3b6dfc4ee7
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=$PWD/src:$PWD/tests timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider -m 'not dotfiles_integration' tests/test_host_integration.py tests/test_host_integration_runner.py tests/test_jevdrill_host_gaps.py tests/test_jevdrill_adapter.py tests/test_jevdrill_queue.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_selection.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_launch_audit_inventory.py"]
---

# JEVHOST amendment: host gaps, generic seam first

## Context

This amends `plans/phase-plan-v1-jevhost-JEVHOST.md`. The phase landed in agent-harness#2086.
JEV Drill's HOST verifier records nine clauses as not covered at the pinned host commit.
They are in EC-HOST-1, EC-HOST-2 and EC-HOST-4, and in the HOST scope notes of
`Consiliency/jevdrill` (pinned in GAPS §0). The owner decided on 2026-11-23 to cover them
with discriminating producer tests, and then narrowed the scope the same day:
agent-harness builds only the **GENERAL** items. JEV-specific behaviour lives in JEV's
repository, built against a generic host interface. EC-HOST-3 stays synthetic-only.

This amendment changes no roadmap text, no EC and no JEVHOST contract text. Native-Windows
import is agent-harness#2123 and is not covered here.

**Frozen input.** `plans/artifacts/jevhost-host-gaps-v1.md` (**GAPS**, sha256
`2b2e4d487a126f6cfb15968ed73f6bbcfc2804e937b09a2bb5e812ea173a6eff`) holds each item's
classification, status and file:line evidence (§1), the generic seam (§2), the behaviour
and discriminating test per item (§3), the JEV-owned items and their hooks (§4), the open
questions (§5) and the JEVHOST contract check (§6). This plan cites GAPS and does not
restate it.

**Classification** (GAPS §1). Seven items are GENERAL: 1, 2, 4, 5, 6, 7 and 9. Two are
JEV-SPECIFIC and owned by JEV: 3 and 8 (GAPS §4). Of the GENERAL items:
- 1, 2, 4 and 5 put their host-neutral part into a new generic module,
  `host_integration.py`;
- 6, 7 and 9 stay in the JEV adapter, because they are bound to JEV's decision, CLI flag
  and declaration formats (GAPS §2 table).

**Not in scope (JEV-owned).** These are GAPS §4.
- Item 3: JEV owns the explicit-report queue proof. It needs one hook from us, a
  post-launch run handle (`routing_decision_id`, the envelope scope and the next
  `source_sequence` beside `LaunchResult.jevdrill_execution_run`). We build it only on
  JEV's request.
- Item 8: JEV owns the ordinary-macOS control. It needs no hook, because
  `launcher.launch(..., lease_authority=None)` is public.

**Shared-host rule.** Only the files a lane lists, serially without `-n`, with
`-p no:cacheprovider`, under `timeout`, after a headroom check. No full suite runs
locally. No provider, model or live JEV call.

## Interface Freeze Gates

- [ ] IF-0-JEVHOST-5 — The generic host seam of GAPS §2: `host_integration.py` with
  - `build_retry_context` and `RETRY_FAILURE_CLASSES`;
  - `record_acceptance_failure`;
  - `DEACTIVATION_REASONS` and `deactivation_reason`;
  - `DISCONNECT_RESOLUTION_ADVICE` and `annotate_disconnect`;
  - `OVERRIDE_DEFAULT_SOURCES`, `build_host_request` and `HostOverrideViolation`;
  - the adapter method `JevDrillAdapter.record_acceptance_failure(execution_run, *, failure_class)`.

## Lane Index & Dependencies

SL-6 — GENERIC: the host-neutral seam and its unit tests
  Depends on: (none)
  Blocks: SL-7, SL-8
  Parallel-safe: yes

SL-7 — RUNNER: the acceptance-failure hook and the override guard at the three request sites
  Depends on: SL-6
  Blocks: SL-9
  Parallel-safe: yes

SL-8 — ADAPTER: the JEV mapping of items 1, 2 and 4, plus items 6, 7 and 9
  Depends on: SL-6
  Blocks: SL-9
  Parallel-safe: yes

SL-9 — DOCS: the integration page, the changelog and the PR disclosure (reducer)
  Depends on: SL-6, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

Once SL-6 lands, SL-7 and SL-8 run in parallel: their owned files are disjoint. Every item
that touches the adapter is in SL-8, because the adapter is a single file. That is why there
are three code lanes and not more.

## Lanes

Paths are under `phase-loop-runtime/` unless they start with `docs/` or `CHANGELOG`.
Verify from `phase-loop-runtime/` with `PYTHONPATH=$PWD/src:$PWD/tests` and
`PHASE_LOOP_TDD_EXPECT_SCHED=1`.

### SL-6 — GENERIC: the host-neutral seam and its unit tests

- **Scope**: Create `host_integration.py` exactly as in GAPS §2. It does no IO, spawn or `ctypes`, and imports nothing from `jevdrill_*`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/host_integration.py`, `phase-loop-runtime/tests/test_host_integration.py`
- **Interfaces provided**: IF-0-JEVHOST-5 (module half)
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: the GAPS §3 rows 1a and 5a (`test_override_replacing_integration_is_refused`). Also unit cases for `deactivation_reason`'s order, the exact advice tuple, and `annotate_disconnect` returning the same object.
  - impl: the module.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_host_integration.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py`. A moved inventory is a stop (GAPS §6).

### SL-7 — RUNNER: the acceptance-failure hook and the override guard at the three request sites

- **Scope**: GAPS §3 rows 1b and 5a (runner half). Route the three `build_jevdrill_request` calls through `build_host_request`. Call `record_acceptance_failure` from `_finalize_phase_launch`. With no integration, behaviour is unchanged (EC-JEVHOST-3).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_host_integration_runner.py`
- **Interfaces provided**: the runner's `build_host_request` call sites and its `record_acceptance_failure` call
- **Interfaces consumed**: IF-0-JEVHOST-5
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_failed_acceptance_is_recorded_on_the_integration` and `test_runner_refuses_an_integration_that_replaces_an_override`, both with a host-neutral recording fake. They do not use the JEV adapter.
  - impl: the two runner changes.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_host_integration_runner.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_adapter.py -k "runner or lane"`, then the same with `tests/test_phase_loop_runner.py -k jevdrill`.

### SL-8 — ADAPTER: the JEV mapping of items 1, 2 and 4, plus items 6, 7 and 9

- **Scope**: GAPS §3 rows 1c, 2, 4, 5b, 6, 7 and 9, in `jevdrill_adapter.py` only. Existing tests in the twelve files are not edited (GAPS §6). If one breaks, stop and report.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/jevdrill_adapter.py`, `phase-loop-runtime/tests/test_jevdrill_host_gaps.py`
- **Interfaces provided**: IF-0-JEVHOST-5 (`JevDrillAdapter.record_acceptance_failure`)
- **Interfaces consumed**: IF-0-JEVHOST-5 (module half)
- **Parallel-safe**: yes
- **Tasks**:
  - test: the seven `test_jevdrill_host_gaps.py` tests of GAPS §3. Each must fail first on the §0 base, and the lane records each failure message.
  - impl: the adapter changes in GAPS §3 order. The `_launch` reorder (item 6) goes before the reason mapping (item 2), because both touch `_launch`.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_host_gaps.py tests/test_jevdrill_adapter.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_jevdrill_discovery.py tests/test_jevdrill_selection.py tests/test_seat_reference_inventory.py`.

### SL-9 — DOCS: the integration page, the changelog and the PR disclosure (reducer)

- **Scope**: Document the generic seam and the seven behaviours. State the JEV-owned items and the run-handle hook (GAPS §4).
- **Owned files**: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- **Interfaces provided**: the PR body's item-to-node-ID map
- **Interfaces consumed**: IF-0-JEVHOST-5
- **Parallel-safe**: no
- **Tasks**:
  - impl: add a "Host gaps" section to `docs/jevdrill-integration.md`. Add a `CHANGELOG.md` entry under `## [Unreleased]`.
  - impl: the PR body maps each item to its test node ID, so JEV can pin its own controls. It also states:
    - that JEV's handoff must repin, because adapter and runner digests move;
    - the GAPS §5 defaults.
  - verify: `timeout 120 .venv/bin/python -m phase_loop_runtime.entry_doc_check --repo ..` and `timeout 120 .venv/bin/python -m phase_loop_runtime.cli docs-audit --repo .. --base origin/main --json`.

## Execution Notes

- One implementation PR after this plan merges. Each lane commits only its own files. No
  commit, count or topology is pinned.
- **Single-writer files.** `jevdrill_adapter.py` belongs to SL-8, `runner.py` to SL-7 and
  `CHANGELOG.md` to SL-9. No lane writes the twelve JEVHOST test files,
  `tests/data/jevdrill_test_names.json`, a workflow or the JEVHOST contract.
- **Stops.** The JEVHOST §10 rules apply. Each lane's owned files stand in for the key
  files (GAPS §6).
- **Requalification.** Package edits move `runtime_digest()`.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`. The JEV criteria named below are external and
are cited by ID in GAPS §0 and §1. This amendment adds no EC.

- [ ] Item 1 (JEV HOST criterion 1, retry context) — proven by `test_host_integration.py::test_retry_context_is_bounded_and_closed`, `test_host_integration_runner.py::test_failed_acceptance_is_recorded_on_the_integration` and `test_jevdrill_host_gaps.py::test_acceptance_failure_builds_bounded_retry_context`; falsified by a retry route whose `retry_context` is `None`, or one that exceeds the attempt budget.
- [ ] Item 2 (JEV HOST criterion 1, deactivation reason) — proven by `test_jevdrill_host_gaps.py::test_deactivation_reports_the_host_limitation`; falsified by a `None` or free-text reason.
- [ ] Item 4 (JEV HOST criterion 2, disconnect advice) — proven by `test_jevdrill_host_gaps.py::test_disconnect_carries_supported_resolution_advice`; falsified by an outage with no advice, or a changed exception type.
- [ ] Item 5 (JEV HOST criterion 4, retained model) — proven by `test_host_integration.py::test_override_replacing_integration_is_refused`, `test_host_integration_runner.py::test_runner_refuses_an_integration_that_replaces_an_override` and `test_jevdrill_host_gaps.py::test_operator_model_is_kept_through_launch`; falsified by a launch with a replaced override.
- [ ] Item 6 (JEV HOST scope note, readiness recheck) — proven by `test_jevdrill_host_gaps.py::test_readiness_is_rechecked_after_the_final_callbacks`; falsified by a launch after readiness expired during the final callbacks.
- [ ] Item 7 (JEV HOST scope note, spawn budget) — proven by `test_jevdrill_host_gaps.py::test_budget_accounts_for_spawn_time`; falsified by an argv budget that outlasts the host deadline after spawn.
- [ ] Item 9 (JEV HOST scope note, no undeclared forwarding) — proven by `test_jevdrill_host_gaps.py::test_undeclared_harness_identity_is_never_forwarded`; falsified by a `route` call for an undeclared identity.
- [ ] EC-JEVHOST-3 — proven by `test_jevdrill_runner_lanes.py::test_no_adapter_keeps_the_lane_wave_path` and SL-7's verify, with no integration set; falsified by any `run_loop`, `launch_delegated_child` or lane work-unit behaviour change when `jevdrill_adapter` is `None`. Path-entered control: `run_loop` with production constructors and no integration.
- [ ] EC-JEVHOST-6 — proven by `test_jevdrill_selection.py::test_every_r5_name_imports`; falsified by removing or renaming any R5 name. Path-entered control: import from the checkout.

## Verification

Per lane: the commands above. Whole amendment, serially after a headroom check: the
frontmatter `suite_command`. Hosted: the required checks on the implementation PR. Gate A
is the coordinator's decision. No step makes a provider call or runs on a non-hosted
machine.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- evidence paths: `phase-loop-runtime/tests/test_host_integration.py`, `phase-loop-runtime/tests/test_host_integration_runner.py`, `phase-loop-runtime/tests/test_jevdrill_host_gaps.py`
- redaction posture: `metadata_only`
- downstream handling: the PR's item-to-node-ID map goes to the JEV Drill executive through Root, so JEV can pin its own controls
