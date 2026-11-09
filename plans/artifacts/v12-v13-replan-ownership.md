# v12 CLOSEOUT / v13 PLACECLI / v13 LANEEXEC: cross-phase ownership and integration order

Owner decision 2026-11-09: the three phases are re-planned on the landed code,
keeping their roadmap goals. This artifact is the single file-ownership map for
the three re-plans and the record of STOP item X-S1. Each plan's lane `Owned
files` lines are copied from the tables below; if a plan and this map disagree,
this map governs and the plan is corrected by a reviewed plan-only change.

Inputs: the landed tree on `origin/main` that the three sweep reports inspected
(`a493c46cc`, the v12 WORKER merge), and the sweep reports themselves
(Consiliency/agent-harness#1961, #1962 and #1963). No output commit, count or
merge topology is prescribed here.

## X-S1 decision: serial integration order

Option chosen: **serial integration in the order CLOSEOUT → PLACECLI → LANEEXEC**,
with shared files merged additively. The sweep's recommendation (the coordinator
chooses an order, current main text is preserved and manifest rows are appended)
is adopted unchanged.

- **Work start.** CLOSEOUT and PLACECLI have no functional dependency on each
  other and may be built concurrently. LANEEXEC starts only after both have
  merged, because it consumes CLOSEOUT's v2 launch seam (STOP L-S1) and PLACECLI's
  lifecycle and bridge.
- **Merge order.** CLOSEOUT's implementation PR merges first, then PLACECLI's,
  then LANEEXEC's. A later phase rebases onto the earlier landing before it
  merges; it never force-overwrites an earlier phase's text in a shared file.
- **Why this order.** It is the dependency order the owner set for the
  re-plans, it keeps the v12 seam ahead of its only v13 consumer, and every
  CLOSEOUT/PLACECLI shared file is additive (rows, globs, console scripts), so
  the order costs PLACECLI a rebase, not a redesign.
- **Shared-file rule.** For the files in the shared table, the later phase keeps
  main's text verbatim and adds its own entries next to it, as the coordinator's
  delegate rules already require for `CHANGELOG.md`, `plans/manifest.json` and
  `tests/data` inventories. Any other conflict in a shared file is a STOP for the
  coordinator, not a lane decision.

## Shared files (serially owned across phases)

Within one phase each file has exactly one owning lane. Across phases the order
above serializes them.

| File | CLOSEOUT | PLACECLI | LANEEXEC | Rule |
| --- | --- | --- | --- | --- |
| `phase-loop-runtime/pyproject.toml` | SL-0 (package data for `schemas/supervised-worker-v2/**`) | SL-3 (console script `agent-harness-placement`) | SL-5 (console script `agent-harness-launch`) | Additive. No dependency or bound change in any phase. |
| `phase-loop-runtime/uv.lock` | SL-0 | SL-3 | SL-5 | Drift guard only: bytes stay identical in all three phases. |
| `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` | SL-0 | SL-0 | SL-0 | Additive assertions per packaged resource. |
| `phase-loop-runtime/tests/data/seat_launch_references.json` | SL-2 | SL-3 | SL-5 | Union of rows; landed WORKER rows preserved. |
| `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py` | SL-2 | SL-3 | SL-5 | Inventory decision per new launch site or dynamic import. |
| `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` | SL-2 | SL-3 | SL-5 | Helpers launch through `seat_uid.trusted_module_argv`, never `-m`. |
| `phase-loop-runtime/tests/test_seat_reference_inventory.py` | SL-2 | SL-3 | SL-5 | Union. |
| `CHANGELOG.md` | SL-3 | SL-3 | SL-6 | One Unreleased entry each; main text verbatim. |
| `plans/manifest.json` | SL-3 | SL-3 | SL-6 | Append-only lifecycle events and rows. |
| `phase-loop-runtime/README.md` | — | SL-3 | SL-6 | Additive sections. |
| `.doc-decisions.json` | — | SL-3 | SL-6 | Append decisions. |
| `docs/placement-process-cli.md` | — | SL-3 (creates) | SL-6 (adds the launch cross-reference) | LANEEXEC never rewrites PLACECLI's sections. |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` | — | SL-1 | SL-3 | Roadmap DAG PLACECLI → LANEEXEC already serializes these. |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` | — | SL-1 | SL-3 | As above. |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py` | — | SL-1 | SL-3 | As above. |
| `phase-loop-runtime/tests/test_sandbox_placement.py` | — | SL-1 | SL-3 | As above. |
| `phase-loop-runtime/tests/test_placement_lease.py` | — | SL-1 | SL-3 | As above. |
| `phase-loop-runtime/tests/test_openshell_backend.py` | — | SL-1 | SL-3 | As above. |

## Complete per-phase ownership

Every path owned by any lane of the three plans. Paths not listed are not owned
by these phases.

### v12 CLOSEOUT

- **SL-0**: `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v2/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/MANIFEST.in`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_supervised_contracts*.py`, `phase-loop-runtime/tests/historical_receipts.py`, `phase-loop-runtime/scripts/verify_supervised_contract_publication.py`, `phase-loop-runtime/scripts/verify_supervised_v2.sh`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`, `phase-loop-runtime/tests/test_ci_chronology_scope.py`, `phase-loop-runtime/tests/test_ci_offload_lock.py`, `.github/workflows/supervised-contract-intake.yml`, `.github/workflows/test.yml`, `.gitleaks.toml`
- **SL-1**: `phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py`, `phase-loop-runtime/tests/test_supervised_envelope_v2.py`, `phase-loop-runtime/tests/test_supervised_capture_v2.py`, `phase-loop-runtime/tests/test_supervised_launch*.py`, `phase-loop-runtime/tests/fixtures/supervised_launch_local/**`
- **SL-2**: `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_echo.py`, `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`, `phase-loop-runtime/tests/test_supervised_worker*.py`, `phase-loop-runtime/tests/test_run_status*.py`, `phase-loop-runtime/tests/_run_status_vectors.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_executable_dependency_startup.py`, `phase-loop-runtime/tests/fixtures/supervised_worker_local/**`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`
- **SL-3**: `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`, `docs/supervised-worker-readiness.md`, `plans/evidence/supervised-worker/CLOSEOUT.md`, `phase-loop-runtime/tests/test_supervised_v2_readiness.py`, `phase-loop-runtime/scripts/verify_supervised_v2_evidence.py`, `.github/workflows/supervised-v2-evidence.yml`, `CHANGELOG.md`, `plans/manifest.json`

### v13 PLACECLI

- **SL-0**: `phase-loop-runtime/src/phase_loop_runtime/placement_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `phase-loop-runtime/tests/test_placement_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **SL-1**: `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`, `phase-loop-runtime/tests/test_placement_lifecycle_process.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`, `phase-loop-runtime/tests/test_placement_driver.py`, `phase-loop-runtime/tests/test_placement_ladder_model.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`, `phase-loop-runtime/tests/test_openshell_channel.py`, `phase-loop-runtime/tests/test_openshell_journal.py`, `phase-loop-runtime/tests/test_openshell_transport.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`
- **SL-2**: `phase-loop-runtime/src/phase_loop_runtime/placement_bridge.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`, `phase-loop-runtime/tests/test_placement_bridge.py`, `phase-loop-runtime/tests/test_openshell_worker.py`, `phase-loop-runtime/tests/_openshell_channel_server.py`, `phase-loop-runtime/tests/fixtures/placement-cli/**`
- **SL-3**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_placement_cli.py`, `phase-loop-runtime/tests/test_placecli_receipt.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/README.md`, `docs/placement-process-cli.md`, `plans/evidence/placement/PLACECLI.md`, `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`

### v13 LANEEXEC

- **SL-0**: `phase-loop-runtime/src/phase_loop_runtime/launch_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `phase-loop-runtime/tests/test_launch_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **SL-1**: `phase-loop-runtime/src/phase_loop_runtime/launch_snapshot.py`, `phase-loop-runtime/tests/test_launch_snapshot.py`, `phase-loop-runtime/tests/fixtures/launch-snapshot/**`
- **SL-2**: `phase-loop-runtime/src/phase_loop_runtime/launch_return.py`, `phase-loop-runtime/tests/test_launch_return.py`
- **SL-3**: `phase-loop-runtime/src/phase_loop_runtime/launch_service.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/tests/test_launch_service.py`, `phase-loop-runtime/tests/test_launch_local_caps.py`, `phase-loop-runtime/tests/test_launch_lifetime.py`, `phase-loop-runtime/tests/test_launch_release_reap.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`
- **SL-4**: `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_phase_loop_lane_placement.py`, `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py`
- **SL-5**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py`, `phase-loop-runtime/tests/test_launch_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **SL-6**: `docs/placement-launch-service.md`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `plans/evidence/placement/LANEEXEC.md`, `phase-loop-runtime/tests/test_laneexec_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`

Ownership resolutions (coordinator ruling 2, 2026-11-09): CLOSEOUT SL-2 owns
`convergence/adapters/base.py` because it extends `run_bounded_capture` with the
v2 spawn capability; `convergence/adapters/codex.py` is consumed unchanged
(CLOSEOUT binding §2) and owned by no lane; LANEEXEC's `capability_registry.py`
is consumed unchanged (`default_executor_for_work_unit` is only called) and owned
by no lane.

## Regression inputs no lane of the three may edit

These landed surfaces are consumed unchanged. A needed change is a STOP to the
coordinator naming the exact plan sentence, never a silent widening.

- SEATS-owned confinement: `seat_resource_caps.py`, `seat_resource_caps_enter.py`,
  `seat_uid.py`, `seat_jail*.py`, the jailed Codex seat route in `panel_invoker.py`
  (including `_NONLOCAL_EXECUTION_DRIVER`, which stays false) and
  `plans/seats-jailcore-caps-contract.md`. Jail boundaries and disabled-by-default
  routes are preserved (owner rule).
- v12 inputs and history: `supervised_dependency.py`,
  `executable_dependency_startup.py`, `output_retention.py`,
  `phase-loop-runtime/scripts/stamp_evidence_receipt.py`, every receipt under
  `plans/evidence/supervised-worker/` (SCHEMA, ENVELOPE, JOURNAL, WORKER),
  `plans/artifacts/v12-*.md`, and both roadmaps.
- Placement inputs: `openshell_artifacts.py`, `contracts/placement/vectors/policies.json`
  (status stays `pending_qualification`), `baml_src/placement_contract.baml`, and
  both v13 schema artifacts under `plans/artifacts/` (their bytes stay at the
  roadmap and toolkit pins; see STOP P-S2/L-S8 in the PLACECLI and LANEEXEC
  landed-binding artifacts).
- agy qualification: `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
  and the RECBIND catalog. It is a separate qualification system, never a v2
  worker qualification receipt.

## Concurrent writers outside these phases

Open draft PRs that touch a shared file, observed 2026-11-09:
Consiliency/agent-harness#1883 (`pyproject.toml`), and #1781, #1770, #1744, #1740,
#1641 and #1582 (`tests/data/seat_launch_references.json`; #1744 also
`pyproject.toml`). Whichever lands first, the other side union-resolves under
the shared-file rule above. None of them touches a placement, worker or journal
source file.

## Receipt pins (owner rule, agent-harness#1955)

No receipt produced by these phases pins a shared or frequently changed file:
nothing in the shared table above, no `docs/*.md` file, and no file under
`.github/workflows/`. Each receipt pins only its own phase-exclusive sources,
tests and frozen artifacts.
