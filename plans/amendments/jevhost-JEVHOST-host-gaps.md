---
phase_loop_plan_version: 1
phase: JEVHOST
roadmap: specs/phase-plans-jevhost-v1.md
roadmap_sha256: 55bae44da652dc537d33edf5eaaa685d21f7e9c2ab4515b98601e0d04a8b853a
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=$PWD/src:$PWD/tests timeout 1800 .venv/bin/python -m pytest -q -rA -p no:cacheprovider -m 'not dotfiles_integration' tests/test_host_integration.py tests/test_host_integration_runner.py tests/test_jevdrill_host_gaps.py tests/test_jevdrill_adapter.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_jevdrill_discovery.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_input.py tests/test_jevdrill_selection.py tests/test_jevdrill_companion_workflow.py tests/test_jevdrill_receipt.py tests/test_jevdrill_launch_merge.py tests/test_jevdrill_runner_lanes.py tests/test_launch_audit_inventory.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_resource_caps.py tests/test_seat_launch_helpers_trusted.py tests/test_gate_fail_open_visibility.py"]
---

# JEVHOST amendment: host gaps, generic seam first

## Context

This amends `plans/phase-plan-v1-jevhost-JEVHOST.md`, the phase that landed in
agent-harness#2086. JEV Drill's HOST verifier records nine clauses as `not_covered` at the
pinned host commit. The owner decided on 2026-11-23 to cover them with discriminating
producer tests, then narrowed the scope the same day: agent-harness builds only the
**GENERAL** items. EC-HOST-3 stays synthetic-only. Native-Windows import is
agent-harness#2123 and is outside this amendment.

**Revision 2 (2026-11-23).** This revision applies the plan review of agent-harness#2124
(REQUEST CHANGES, findings F1 to F5) and the coordinator's rulings on Q1 and Q2. Every
change is tagged in GAPS.

**Frozen input.** `plans/artifacts/jevhost-host-gaps-v1.md` (**GAPS**, sha256
`a3037ebaf63dd745c583cac6deff199ba175fc0da53ca4f69edaf6049def4db3`) holds:
- each item's coverage key, class, status and file:line evidence (§1);
- the generic seam (§2);
- per-item behaviour, ordering and tests, with each test's expected base outcome (§3);
- the JEV-owned items (§4);
- the rulings (§5);
- authority, key files, inventories and continuity evidence (§6).

This plan cites GAPS and does not restate it.

**Roadmap change.** The roadmap's Phase 1 **Key files** gain the four new paths of GAPS
§6, so `roadmap_sha256` is repinned here and in the JEVHOST plan. No exit criterion and no
JEVHOST contract text changes.

**Classification** (GAPS §1). GENERAL: items 1, 2, 4, 5, 6, 7 and 9. JEV-SPECIFIC and
JEV-owned: items 3 and 8 (GAPS §4). Only host-neutral parts go to `host_integration.py`
(GAPS §2 [P]):
- the retry budget arithmetic;
- the acceptance observer protocol;
- the deactivation vocabulary;
- the advice for each operation;
- the override guard.

The adapter keeps the ledger, the readiness ordering, the argv budget, the declaration
check and every JEV mapping.

**Not in scope (JEV-owned).** These are GAPS §4.
- Item 3 stays an open coverage gap. Its hook, one opaque run-bound enqueue capability,
  is deferred until JEV requests it.
- Item 8 needs no hook.

**Shared-host rule.** Only the files a lane lists, serially without `-n`, with
`-p no:cacheprovider`, under `timeout`, after a headroom check. No full suite runs
locally. No provider, model or live JEV call.

## Interface Freeze Gates

- [ ] IF-0-JEVHOST-5 — The generic seam of GAPS §2, frozen before SL-7 and SL-8 start:
  - `RetryBudget` and `ACCEPTANCE_FAILURE_CLASSES`;
  - the `AcceptanceObserver` protocol (`record_acceptance_outcome`) and `notify_acceptance`;
  - `DEACTIVATION_REASONS` and `deactivation_reason`;
  - `disconnect_advice` and `annotate_disconnect`;
  - `build_host_request` and `HostOverrideViolation`.

## Lane Index & Dependencies

SL-6 — GENERIC: the host-neutral seam and its unit tests
  Depends on: (none)
  Blocks: SL-7, SL-8, SL-9
  Parallel-safe: yes

SL-7 — RUNNER: acceptance verdicts to the observer, and the override guard at the three request sites
  Depends on: SL-6
  Blocks: SL-9
  Parallel-safe: yes

SL-8 — ADAPTER: the retry ledger, deactivation reasons, disconnect advice, readiness order, spawn reserve and declaration check
  Depends on: SL-6
  Blocks: SL-9
  Parallel-safe: yes

SL-9 — REDUCE: inventories, frozen-file regression, docs, changelog and disclosure
  Depends on: SL-6, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

SL-7 and SL-8 have disjoint files. SL-7 tests against the frozen observer protocol with a
fake, and never imports an unlanded adapter. Every adapter change is in SL-8, because the
adapter is one file.

## Lanes

Paths are under `phase-loop-runtime/` unless they start with `docs/` or `CHANGELOG`.
Verify from `phase-loop-runtime/` with `PYTHONPATH=$PWD/src:$PWD/tests` and
`PHASE_LOOP_TDD_EXPECT_SCHED=1`. Each lane first runs its new tests against the GAPS §0
base and records each outcome by node ID, as GAPS §3.0 requires. It then confirms that
every named test collects (`--collect-only -q`) and executes (`-rA`).

### SL-6 — GENERIC: the host-neutral seam and its unit tests

- **Scope**: `host_integration.py` exactly as in GAPS §2. It does no IO, spawn or `ctypes`, and imports nothing from `jevdrill_*`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/host_integration.py`, `phase-loop-runtime/tests/test_host_integration.py`
- **Interfaces provided**: IF-0-JEVHOST-5
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: GAPS §3.1 row 1a and the two §3.5 row 5a module tests. Add unit cases for the order of `deactivation_reason`, the exact advice for each operation, and `annotate_disconnect` returning the same object.
  - impl: the module.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -rA -p no:cacheprovider tests/test_host_integration.py`.

### SL-7 — RUNNER: acceptance verdicts to the observer, and the override guard at the three request sites

- **Scope**: The runner verdict table of GAPS §3.1, through one `_report_acceptance` helper. Route `runner.py:3388`, `:5509` and `:6221` through `build_host_request`. With no integration, behaviour is unchanged.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_host_integration_runner.py`
- **Interfaces provided**: the runner's `_report_acceptance` verdicts and its `build_host_request` call sites
- **Interfaces consumed**: IF-0-JEVHOST-5
- **Parallel-safe**: yes
- **Tasks**:
  - test: GAPS §3.1 row 1b and §3.5's runner row 5a (main, delegated and lane), with a host-neutral fake.
  - impl: the verdict helper and the three call sites. Record the `launch_contract_blocker` verdict with evidence. If it is ambiguous, stop.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -rA -p no:cacheprovider tests/test_host_integration_runner.py tests/test_jevdrill_runner_lanes.py`, then `timeout 900 .venv/bin/python -m pytest -q -rA -p no:cacheprovider tests/test_phase_loop_runner.py -k jevdrill`.

### SL-8 — ADAPTER: the retry ledger, deactivation reasons, disconnect advice, readiness order, spawn reserve and declaration check

- **Scope**: GAPS §3.1 (ledger, construction, supplied-context check), §3.2, §3.4, §3.5 row 5b, §3.6, §3.7 and §3.8, in `jevdrill_adapter.py` only. The frozen twelve files are read-only (GAPS §6). If one breaks, stop.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/jevdrill_adapter.py`, `phase-loop-runtime/tests/test_jevdrill_host_gaps.py`
- **Interfaces provided**: `JevDrillAdapter.record_acceptance_outcome`, which implements the IF-0-JEVHOST-5 observer
- **Interfaces consumed**: IF-0-JEVHOST-5
- **Parallel-safe**: yes
- **Tasks**:
  - test: every `test_jevdrill_host_gaps.py` test of GAPS §3, with its expected base outcome:
    - each probe fails with its named assertion;
    - the controls pass;
    - 5b passes on the base and fails under the recorded provenance mutation.
  - impl: in this order:
    1. the declaration check (§3.8);
    2. the retry ledger (§3.1);
    3. the `_launch` reorder (§3.6);
    4. the deactivation reasons (§3.2);
    5. the disconnect advice (§3.4);
    6. the spawn reserve (§3.7).
  - verify: `timeout 900 .venv/bin/python -m pytest -q -rA -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_host_gaps.py tests/test_jevdrill_adapter.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_jevdrill_discovery.py`.

### SL-9 — REDUCE: inventories, frozen-file regression, docs, changelog and disclosure

- **Scope**: The GAPS §6 reducer duties on the combined tree:
  - all five §13 inventories;
  - the frozen twelve files, with selection, companion-workflow and receipt;
  - the continuity reruns.

  Also the docs, the changelog, and the PR disclosure.
- **Owned files**: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- **Interfaces provided**: the PR body's map from each coverage key to its test node IDs
- **Interfaces consumed**: IF-0-JEVHOST-5
- **Parallel-safe**: no
- **Tasks**:
  - test: the frontmatter `suite_command`. A moved inventory is a stop, followed by a GAPS repin, and no lane edits an inventory file (GAPS §6).
  - impl: add a "Host gaps" section to `docs/jevdrill-integration.md`, and a `CHANGELOG.md` entry under `## [Unreleased]`.
  - impl: the PR body states:
    - the coverage-key-to-node-ID map;
    - the item-3 gap left open, and the deferred hook;
    - that the reserve guarantee is limited to pre-spawn plus parent enforcement (GAPS §3.7), and the changed path of the frozen deadline test;
    - that the retry ledger is lost on restart;
    - that JEV's handoff must repin its module digests;
    - any Gate A or companion dispatch, recorded after it runs, with the head's tree hash.
  - verify: `timeout 120 .venv/bin/python -m phase_loop_runtime.entry_doc_check --repo ..`, `timeout 120 .venv/bin/python -m phase_loop_runtime.cli docs-audit --repo .. --base origin/main --json`, and the disclosure grep over the diff.

## Execution Notes

- One implementation PR after this plan merges. Each lane commits only its own files. No
  commit, count or topology is pinned.
- **Single-writer files.** `jevdrill_adapter.py` belongs to SL-8, `runner.py` to SL-7, and
  `CHANGELOG.md` to SL-9. No lane writes the twelve frozen test files,
  `tests/data/jevdrill_test_names.json`, an inventory file, a workflow or the JEVHOST
  contract.
- **Stops.** The JEVHOST §10 rules apply, over the amended Key files (GAPS §6).
- **Requalification.** Package edits move `runtime_digest()`.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`. Each item names its exact pinned coverage
key (GAPS §1). This amendment adds no EC.

- [ ] Item 1, coverage key `EC-HOST-1 / Acceptance failures supply bounded rerouting context: the host half` — proven by `test_host_integration.py::test_retry_budget_arithmetic_and_exhaustion`, `test_host_integration_runner.py::test_acceptance_verdicts_reach_the_observer`, `test_jevdrill_host_gaps.py::test_acceptance_failure_builds_bounded_retry_context` and `::test_supplied_retry_context_cannot_widen_or_bypass`; falsified by a retry route with no context, a context naming another task's run or decision, a widened or exhausted budget that still routes, or an unrelated blocker reported as a failure.
- [ ] Item 2, coverage key `EC-HOST-1 / Deactivates at task end, reporting host limitations` — proven by `test_jevdrill_host_gaps.py::test_deactivation_reports_the_host_limitation`; falsified by a `None` or free-text reason on `guidance_deactivated`, or a reason kept on any other lifecycle event.
- [ ] Item 4, coverage key `EC-HOST-2 / Disconnects include supported resolution advice` — proven by `test_jevdrill_host_gaps.py::test_route_disconnect_carries_advice`, `::test_report_disconnect_keeps_backoff_and_advises` and `::test_non_transport_delivery_errors_stay_distinct`; falsified by a disconnect with no or mismatched advice, a changed exception object, lost queue backoff, or advice on a non-transport error.
- [ ] Item 5, coverage key `EC-HOST-4 / The harness may retain its current model: a launch that keeps it` — proven by `test_host_integration.py::test_build_host_request_refuses_override_changes`, `::test_build_host_request_passes_preserved_override_and_default_routing`, `test_host_integration_runner.py::test_runner_refuses_an_integration_that_replaces_an_override` and `test_jevdrill_host_gaps.py::test_operator_model_is_kept_through_launch`; falsified by a launch with any override field replaced.
- [ ] Item 6, coverage key `scope / Scope note: the readiness recheck before launch` — proven by `test_jevdrill_host_gaps.py::test_readiness_expiring_in_a_final_callback_refuses_launch`, `::test_readiness_expiring_during_the_started_write_refuses_launch` and `::test_fresh_launch_reports_started_before_dispatch`; falsified by a launch after readiness expired at any point before dispatch.
- [ ] Item 7, coverage key `scope / Scope note: the budget passed after host spawn time` — proven by `test_jevdrill_host_gaps.py::test_budget_reserves_spawn_time`, `::test_near_zero_budget_never_spawns`, `::test_over_reserve_spawn_is_bounded_by_the_parent_deadline` and `::test_delete_argv_has_no_budget_flag`; falsified by an argv budget without the pinned pre-spawn reserve, a spawn with no budget left, or a child outliving the parent deadline. The guarantee is pre-spawn reserve plus parent-side enforcement (GAPS §3.7).
- [ ] Item 9, coverage key `scope / Scope note: the absence of silent forwarding` — proven by `test_jevdrill_host_gaps.py::test_undeclared_identity_makes_no_cli_request` and `::test_declared_identity_and_absent_file_still_route`; falsified by any CLI request for an identity that a present declaration omits.
- [ ] EC-JEVHOST-3 — continuity per GAPS §6: proven by rerunning `test_jevdrill_launch_merge.py`, `test_jevdrill_runner_lanes.py` and `test_launch_audit_inventory.py` on the combined tree, with S1 to S6 provenance from the landed evidence of agent-harness#2086; falsified by any behaviour change with no integration. Path-entered control: `run_loop` with production constructors and no integration.
- [ ] EC-JEVHOST-1, EC-JEVHOST-2, EC-JEVHOST-4, EC-JEVHOST-5, EC-JEVHOST-6, EC-JEVHOST-7, EC-JEVHOST-8 — continuity per GAPS §6: proven by the landed evidence of agent-harness#2086 plus the reruns named there; falsified by any rerun failing or any frozen file, inventory or workflow edited. Path-entered control: SL-9's `suite_command` on the combined tree.

## Verification

Per lane: the commands above. Whole amendment, serially after a headroom check: the
frontmatter `suite_command` (SL-9). Hosted: the required checks, plus the companion
receipt leg that the path filter triggers on the implementation PR. Gate A is the
coordinator's decision, and SL-9 records it if it runs. No step makes a provider call or
runs on a non-hosted machine.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- evidence paths: `phase-loop-runtime/tests/test_host_integration.py`, `phase-loop-runtime/tests/test_host_integration_runner.py`, `phase-loop-runtime/tests/test_jevdrill_host_gaps.py`
- redaction posture: `metadata_only`
- downstream handling: the coverage-key-to-node-ID map goes to the JEV Drill executive through Root, so JEV can pin its own controls
