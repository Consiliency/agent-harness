---
phase_loop_plan_version: 1
phase: LANEEXEC
roadmap: specs/phase-plans-v13.md
roadmap_sha256: a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest tests/test_launch_snapshot.py tests/test_launch_return.py tests/test_launch_prepare.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_launch_routes.py tests/test_launch_service.py tests/test_launch_admission.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_openshell.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_laneexec_receipt.py"]
---

# LANEEXEC: Generic placement launch service (re-plan on landed code)

## Context

Owner decision 2026-11-09: LANEEXEC is re-planned on the landed code and keeps
its roadmap goals, EC-LANEEXEC-1 to EC-LANEEXEC-5. This plan replaces the
previous LANEEXEC plan rather than amending it; the supersession is an appended
`replan` lifecycle event on the existing `plans/manifest.json` row
`v13-LANEEXEC`, which keeps every earlier field and seal.

LANEEXEC adds the one launch service every approved client uses after a
reservation: prepare, snapshot and seed, v2 envelope admission, one restricted
exec, optional bridge, status/cancel, release/reap interplay and bounded return.
SL-0, SL-1, SL-2, SL-7 and SL-3a have landed. Binding §9 defines the remaining handoffs to the CLOSEOUT v2 CLI and WORKER.

Frozen inputs, read before building:

- `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json` with erratum
  LANEEXEC-v1-errata-1 (`x-errata`) and the LANEEXEC-v1-errata-6 toolkit repin.
  Agent-toolkit vendors it at its digest. It carries IF-0-LANEEXEC-1: messages,
  CLI, routes, templates, snapshot, seed, prepare, envelope derivation, exec,
  caps, lifetime, bridge, status/cancel, return, evidence, activation defaults
  and obligations C1–C11.
- `plans/artifacts/v13-LANEEXEC-landed-binding.md`: work-start gates and what is
  dropped (§1), the landed-interface table at `file:line` (§2), the STOP
  decisions with the wire sentences they bind (§3), cross-repo consequences (§4),
  verification groups (§5), and errata LANEEXEC-v1-errata-2 (§6),
  LANEEXEC-v1-errata-3 (§7), LANEEXEC-v1-errata-4 (§8), LANEEXEC-v1-errata-5 (§9),
  LANEEXEC-v1-errata-6 (§10) and LANEEXEC-v1-errata-7 (§11).
- `plans/artifacts/v13-LANEEXEC-errata-5-resolutions.md`: SL-8 producer signatures, lock order, supervisor protocol, evidence gates and test ownership.
- `plans/artifacts/v13-PLACECLI-contract-v1.schema.json` (unchanged), the
  CLOSEOUT and PLACECLI landed-binding artifacts, and
  `plans/artifacts/v12-v13-replan-ownership.md`.

Work-start gates (non-human, `blocker_class=upstream_phase_unmet`): CLOSEOUT SL-1
and SL-2 merged (its v2 seam, not its acceptance), and PLACECLI merged. The old
gate on the caps contract §1a tmpfs carve-out is dropped (L-S3). EXT-LAUNCHSITE
and EXT-OPENSH remain activation prerequisites whose offline controls run here.

**STOP decisions** (each recorded with its reason in the binding artifact §3):

| Item | Decision |
| --- | --- |
| L-S1 | Depend on CLOSEOUT: pre-claim admission in one isolated helper (errata-3 E3-1), disposed through `discard_admission`, then one `supervised_worker_cli launch --envelope --result` chain root that reads the CLOSEOUT §4.2 controller document and re-admits authoritatively. No admission code here. Adopted. |
| L-S2 | The JOURNAL reservation stays worker-owned. The claim is one durable write in the placement journal; every rollback precedes the first chain process, so no permanent reservation is ever orphaned and the prepared `attempt_id` stays valid. |
| L-S3 | Block-backed route: local attempt directories live under the client's LaneExec state directory and share `staging_root()`'s filesystem; tmpfs refuses `capability_unmet`; no carve-out and no caps API change; `capped_popen` failures keep the claim; the missing SEATS caps APIs gate activation. Deviates from the sweep (keep blocked) to remove the tmpfs prerequisite. |
| L-S4 | A total mapping onto the existing wire states, with LaneExec's own terminal record first; every failure after the first chain process is `finished`/`failed_to_start`; zero-signal cancels return `cancel_pending`, never success. Adopted. |
| L-S5 | `patch` reuses WORKER's fail-closed withholding; `result` and `none` are specified separately; no private WORKER helper is used. Adopted. |
| L-S6 | Zero-effect assertions scoped by stage. Adopted. |
| L-S7 | Per-action route mapping defined; no qualification record shipped; local review seats never launch through LaneExec. Adopted. |
| L-S8 | No grant-rule repin: the PLACECLI bytes are unchanged and the LANEEXEC template erratum and toolkit repin leave the existing bare-hex grant rule intact. Deviates from the sweep (hold) as in PLACECLI P-S2. |

**Erratum LANEEXEC-v1-errata-2** (binding §6, 2026-11-23; plan and binding only, the
wire bytes and the toolkit pin are unchanged) re-anchors binding §2 to the v0.7.40 main
tree that binding §0 pins. Its items:

| Item | Ruling |
| --- | --- |
| E2-1 | `capped_popen` takes `before_spawn` (agent-harness#2033); LaneExec never passes it. Collection is the landed reap thread, and the supervisor outlives it or reports `cleanup_pending`. |
| E2-2 | SL-3 zero-egress amendment (owned by SL-8 since errata-3): every openshell launch goes through `sandbox_placement.openshell_launch_refusal` at the activation step, the host activation and egress check alongside the client opt-in (agent-harness#2003; owner egress ruling of 2026-11-19, quoted in binding §6). The ACTIVATE roadmap goal is agent-harness#2104. |
| E2-3 | `execute_lane_waves` (agent-harness#1978) launches writable lanes. SL-4 guards the runner's concurrent branch: placement enabled never enters it. |
| E2-4 | A RAM-backed `staging_root()`, or an override onto another device, refuses `capability_unmet` under the device rule (binding §11 E7-3). An exception from it, or from `readiness_code()`, is `capability_unmet`. |
| E2-5 | Panel verdict and gates recorded; manifest `review_status` updated. |
| E2-6 | The review-runner image pin is scoped. RR-1 is decided: a new parallel phase builds the pin record (binding §6 E2-6). |

**Erratum LANEEXEC-v1-errata-3** (binding §7, 2026-11-23; plan and binding only, the wire
bytes, the toolkit pin and every CLOSEOUT file are unchanged) answers the SL-3 implementer's
STOP. Its items:

| Item | Ruling |
| --- | --- |
| E3-1 | The L-S1 pre-claim check runs in one isolated helper, `trusted_module_argv("phase_loop_runtime.launch_admission")`: `load_v2_binding`, `reconcile_v2_binding` with the controller document held in memory, `activate_v2_binding`, the codec's `decode_v2` and `precheck_v2_admission` before capture, then `capture_launch_v2`, `prepare_launch_v2`, and `discard_admission` in a `finally`. The controller bytes are serialized once. They reach the helper over a stdin pipe, and the helper never writes them. After the claim the supervisor publishes the same bytes. A failed publication keeps the claim and starts nothing, ending `finished`/`failed_to_start` with zero worker invocations as crash-after-claim recovery. Diagnostics, counters and inventory rows are in binding §7 E3-1. |
| E3-2 | `ClientConfig` is the captured `PlacementClientConfig`. LaneExec settings live in its `launch` object, which `config_sha256` covers. SL-7 defines the shape and SL-6 documents it. |
| E3-3 | SL-3 is split: SL-3 (coordinator label SL-3a), SL-7 (SL-3b), SL-8 (SL-3c) and SL-9 (SL-3d), with numeric IDs because the validator requires them. Each former SL-3.1 obligation and SL-3.3 mutation has one owner in binding §7 E3-3, which also fixes the SL-8/SL-9 staging seam and the reduced dependency graph. |
| E3-4 | The E2-4 mount cases skip with a named reason without fixture mounts, and run in the new `laneexec-mounts` workflow on a loop-backed second device and the runner's tmpfs. The SL-6 receipt needs a same-head run whose JUnit artifact shows all five cases (M1–M5) passed. No required check runs them; the gap is stated in binding §7 E3-4. |

**Erratum LANEEXEC-v1-errata-7** (binding §11, 2026-11-24) records the five
binding SL-8 interpretations from agent-harness#2160 under the frozen wire.

## Interface Freeze Gates

- [ ] IF-0-LANEEXEC-1 — The frozen wire artifact, byte-equal in source-tree
  checks to the packaged copy, implemented with the bindings of the landed-binding
  artifact §3. Production signatures are those of the wire artifact's
  `x-in-process-api` (`decode_launch_request`, `encode_launch_response`,
  `build_launch_service`, `LaunchService.prepare|launch|status|cancel`,
  `build_snapshot`, `build_seed`, `lane_launch.place_lane`, `launch_cli.main`,
  `launch_cli.version_response`), plus the SL-2 mapping functions
  `map_status`, `map_cancel` and `collect_return`. Record fields come only from
  the schema; exceptions translate to closed codes `from None`; input values,
  returned bytes, policy bodies and credentials never enter messages,
  diagnostics or evidence.

## Cross-Repo Gates

- [ ] IF-XR-1 (agent-toolkit, consumer) — unchanged members and exit classes; the
  toolkit re-vendors the digest with the LANEEXEC-v1-errata-6 repin. It keeps
  its capped bwrap launcher while `local_pi_runner_launcher` is `toolkit_interim`
  and switches only under the ACTIVATE condition. It can
  observe the L-S4 cancel narrowing only.
- [ ] IF-XR-2 (SEATS REMOTE, consumer) — `leg` and `qualification` routes,
  templates, `full` snapshots, `result` return and the `pre_exec`/`withhold`
  hooks as frozen; they stay disabled until SEATS supplies qualification
  records (L-S7).
- [ ] IF-XR-3 (PLACECLI, consumed) — `ForwardTcpUnixBridge` unchanged.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `docs/placement-launch-service.md`, `docs/placement-process-cli.md`
- evidence paths: `plans/evidence/placement/LANEEXEC.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Lane Index & Dependencies

SL-0 — Packaged launch contract and strict codec
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-5, SL-6, SL-7
  Parallel-safe: no

SL-1 — Snapshot and seed construction
  Depends on: SL-0
  Blocks: SL-6, SL-8
  Parallel-safe: yes

SL-2 — Return, status and cancel mapping
  Depends on: SL-0
  Blocks: SL-3, SL-6, SL-8
  Parallel-safe: yes

SL-3 — Launch service: prepare, status, cancel and lifecycle hooks (SL-3a)
  Depends on: SL-2
  Blocks: SL-4, SL-5, SL-6, SL-8
  Parallel-safe: yes

SL-7 — Routes, templates, registration and launch settings (SL-3b)
  Depends on: SL-0
  Blocks: SL-4, SL-5, SL-6, SL-8
  Parallel-safe: yes

SL-8 — Launch order, exec claim, admission helper and local supervisor (SL-3c)
  Depends on: SL-1, SL-2, SL-3, SL-7
  Blocks: SL-5, SL-6, SL-9
  Parallel-safe: no

SL-9 — Openshell route, bridge and coordinator lifetime (SL-3d)
  Depends on: SL-8
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: no

SL-4 — Phase-loop lane placement site
  Depends on: SL-3, SL-7, SL-9
  Blocks: SL-6
  Parallel-safe: yes

SL-5 — Launch process CLI and launch inventories
  Depends on: SL-0, SL-3, SL-7, SL-8, SL-9
  Blocks: SL-6
  Parallel-safe: yes

SL-6 — Documentation, receipt and spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5, SL-7, SL-8, SL-9
  Blocks: (none)
  Parallel-safe: no

The roadmap's four lane concerns map onto these: dispatch, admission and
snapshot (SL-0, SL-1, SL-3, SL-7, SL-8); workload, command and bridge (SL-8, SL-9, SL-4, SL-5);
patch-return and run-status evidence (SL-2); the reducer (SL-6).

## Lanes

### SL-0 — Packaged launch contract and strict codec

- **Scope**: Package the frozen wire artifact and expose a side-effect-free strict codec and typed records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `phase-loop-runtime/tests/test_launch_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **Interfaces provided**: `decode_launch_request`, `encode_launch_response`, launch records, packaged launch-v1 bytes
- **Interfaces consumed**: `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, packaged process-v1 schema and records (PLACECLI SL-0), `jsonschema` (pre-existing), `referencing` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_launch_process_contract.py`, `tests/test_gate_a_wheel_isolation.py` | obligation C1 and the schema cases of C10 and C11 as the wire artifact lists them; both crossed Pi policy/target pairs decode and are left to SL-8's binding refusal; `patch` with `pi-runner` refused; packaged bytes equal the artifact; Reservation resolves through the PLACECLI `$id`; installed-wheel load; additions to `tests/test_gate_a_wheel_isolation.py` go in `GateAConformEvidenceScopeTest` | `V0` |
| SL-0.2 | impl | SL-0.1 | `launch_process_contract.py`, `contracts/placement/launch-v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 owned files | all SL-0 tests | `V0`; mutating the packaged bytes while updating only a test expectation still fails |

### SL-1 — Snapshot and seed construction

- **Scope**: Build git, git_overlay and full snapshots of a hostile source and capture the declared seed set exactly as frozen, with no network and no source-repository git execution.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_snapshot.py`, `phase-loop-runtime/tests/test_launch_snapshot.py`, `phase-loop-runtime/tests/fixtures/launch-snapshot/**`
- **Interfaces provided**: `build_snapshot`, `SnapshotHandle`, `build_seed`, `SeedHandle`
- **Interfaces consumed**: `Snapshot` record (SL-0), `openshell_artifacts.Bound` (pre-existing), `openshell_artifacts.safe_path` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_launch_snapshot.py`, fixtures | obligation C3 on generated temporary repositories, including linked worktrees, masks, the secret matcher, caps, mid-copy `source_changed`, the `git_overlay` cases and a planted hostile `.git/config` that must leave its marker unexecuted; the C10 source cases through `build_seed` with undeclared files never opened | `V1` |
| SL-1.2 | impl | SL-1.1 | `launch_snapshot.py` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | all SL-1 tests | `V1` |

### SL-2 — Return, status and cancel mapping

- **Scope**: Turn a terminated attempt into one bounded return plus metadata-only evidence, and map local status and cancel outcomes onto the wire as decided in L-S4 and L-S5. Extend ReturnPolicy and collection with the zero/lowered per-kind bounds of §9.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_return.py`, `phase-loop-runtime/tests/test_launch_return.py`
- **Interfaces provided**: `collect_return`, `ReturnOutcome`, `map_status`, `map_cancel`, `LaunchEvidence` builder; signature `collect_return(attempt, kind, *, policy, withhold, bound) -> ReturnOutcome`
- **Interfaces consumed**: launch records (SL-0), `WorkerResult` (pre-existing), `ProposalReturn` (pre-existing), `CancelOutcome` (pre-existing), `attempt_status` (pre-existing), CLOSEOUT `v2_status_mapping`, `openshell_artifacts.check_binary_literals` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_launch_return.py` | obligation C8 as narrowed by L-S5: every proposal status row of the L-S5 table, including cancelled and timed-out `withheld_incomplete` returning null; a masked baseline path; digest mismatch at the locator; `result.json` bounds, duplicate keys, trailing data and `truncated: true`; `withhold` deleting bytes; 0700/0600 descriptors; a raw-output sentinel never in a record or evidence; the L-S4 status and cancel tables as closed exhaustive tables, with zero-signal outcomes never mapping to `cancelled` or `already_terminal` | `V2` |
| SL-2.2 | impl | SL-2.1 | `launch_return.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests | `V2` |
| SL-2.4 | test | SL-2.3 | `tests/test_launch_return.py` | §9 precursor: zero and lowered per-kind caps, including verified absent, over-cap invalid and no retained bytes | `V2` |
| SL-2.5 | impl | SL-2.4 | `launch_return.py` | §9 producer interfaces | — |
| SL-2.6 | verify | SL-2.5 | SL-2 owned files | §9 precursor and landed regressions | `V2` |

### SL-3 — Launch service: prepare, status, cancel and lifecycle hooks (SL-3a)

- **Scope**: `build_launch_service` with every injection seam the SL-3 lanes use, and `LaunchService.prepare`, `status` and `cancel`. `launch` is one late-bound call to SL-8 (binding §7 E3-3). The `PlacementLifecycle` hooks: the prepare record, the claim compare-and-set and its rollback, the local heartbeat write, release and reap. Provide the §9 lifecycle transactions, bounded heartbeat, durable fence and verified supervisor cancel in the existing service and lifecycle files.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_service.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/tests/test_launch_prepare.py`, `phase-loop-runtime/tests/test_launch_release_reap.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`
- **Interfaces provided**: `build_launch_service` with its keyword-only `supervisor_runner` parameter, `LaunchService`, `LaunchService.launch_lane`, the immutable `LaneContext` record, the release, reap, claim, rollback and heartbeat hooks in `PlacementLifecycle`
- **Interfaces consumed**: records (SL-0), `map_status`, `map_cancel` (SL-2), `PlacementLifecycle` (PLACECLI), `seat_resource_caps.load_caps` (pre-existing), `sandbox_policy.placement_state_root` (pre-existing), `attempt_status` (pre-existing), `cancel_attempt` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | SL-3 test files | the SL-3 rows of binding §7 E3-3 ("Re-homing of SL-3.1"), through `build_launch_service` | `V3a` |
| SL-3.2 | impl | SL-3.1 | `launch_service.py`, `sandbox_placement.py` | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 owned files | all SL-3 tests | `V3a`; the SL-3 mutations of binding §7 E3-3 each fail |
| SL-3.4 | test | SL-3.3 | `tests/test_launch_release_reap.py` | §9 precursor: generation-checked hooks and record recovery, cancel framing and peer identity with a real bind/connect under a launch root longer than 107 bytes, lock order, rollback/release races and implicit prepare. Test launch_lane forwarding with explicit lane origin and supervisor_runner injection at the factory. Verify settings, environment and request cannot override the default detached runner | `V3a` |
| SL-3.5 | impl | SL-3.4 | `launch_service.py`, `sandbox_placement.py` | §9 producer interfaces | — |
| SL-3.6 | verify | SL-3.5 | SL-3 owned files | §9 precursor and landed regressions | `V3a` |

### SL-7 — Routes, templates, registration and launch settings (SL-3b)

- **Scope**: The L-S7 route mapping, template selection and argv expansion, toolkit-pin registration with image links, and the strict decoder of the `launch` settings object (binding §7 E3-2). Expose the static and activation route functions of §9 while preserving the composite API.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_settings.py`, `phase-loop-runtime/tests/test_launch_routes.py`
- **Interfaces provided**: `launch_routes.register_templates`, the route and template functions, `launch_settings` decoder
- **Interfaces consumed**: records (SL-0), `PlacementClientConfig` (pre-existing), `openshell_artifacts.safe_path` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-7.1 | test | — | `tests/test_launch_routes.py` | the SL-7 rows of binding §7 E3-3, including the full C2 registration matrix at `register_templates` and the local template's LANEEXEC-v1-errata-1 obligations E1 and E2 | `V3b` |
| SL-7.2 | impl | SL-7.1 | `launch_routes.py`, `launch_settings.py` | — | — |
| SL-7.3 | verify | SL-7.2 | SL-7 owned files | all SL-7 tests | `V3b` |
| SL-7.4 | test | SL-7.3 | `tests/test_launch_routes.py` | §9 precursor: static route refusal and separate activation with legacy composite parity | `V3b` |
| SL-7.5 | impl | SL-7.4 | `launch_routes.py` | §9 producer interfaces | — |
| SL-7.6 | verify | SL-7.5 | SL-7 owned files | §9 precursor and landed regressions | `V3b` |

### SL-8 — Launch order, exec claim, admission helper and local supervisor (SL-3c)

- **Scope**: The common `x-launch-inputs.order` through the claim on both routes, including pre-claim scratch staging, activation (zero-egress) and the lifetime gate. Also the isolated pre-claim admission helper (binding §7 E3-1), controller publication and the chain root, the detached supervisor with the capped parent, local lifetime and the local route, and the E2-4 mount workflow (binding §7 E3-4). SL-8 implements the §9 request and supervisor protocols after the SL-2, SL-3a and SL-7 precursor interfaces pass their owner tests. After claim it hands the staged capture and retained return path to SL-9. Real-chain, descendant-death and Pi-stream positives require the producer evidence specified in §9.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_exec.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_admission.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_supervisor.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_lifetime.py`, `phase-loop-runtime/tests/test_launch_service.py`, `phase-loop-runtime/tests/test_launch_admission.py`, `phase-loop-runtime/tests/test_launch_local_caps.py`, `phase-loop-runtime/tests/test_launch_lifetime.py`, `.github/workflows/laneexec-mounts.yml`
- **Interfaces provided**: `launch_exec.launch_attempt`, the `launch_admission` helper module, the private supervisor protocol (§9)
- **Interfaces consumed**: records (SL-0), `build_snapshot`, `build_seed` (SL-1), `collect_return`, `map_status` (SL-2), `build_launch_service` and the lifecycle hooks (SL-3), `register_templates` and `launch_settings` (SL-7), `read_binding_locator`, `load_v2_binding`, `reconcile_v2_binding`, `activate_v2_binding`, the activated codec's `decode_v2` and `precheck_v2_admission`, `capture_launch_v2`, `prepare_launch_v2`, `discard_admission`, `parse_v2`, `canonicalize_v2`, `AttemptBinding`, the §4.2 controller document and `supervised_worker_cli launch --envelope --result` (CLOSEOUT), `seat_resource_caps.capped_popen`, `load_caps`, `caps_sha256`, `readiness_code` (pre-existing), `seat_uid.trusted_module_argv` (pre-existing), `sandbox_policy.staging_root` (pre-existing), `sandbox_placement.openshell_launch_refusal` (pre-existing, agent-harness#2003), `ci/seat-caps-host.sh` (pre-existing, unchanged)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | SL-2.6, SL-3.6, SL-7.6 | SL-8 test files, the workflow | the SL-8 rows of binding §7 E3-3, through `build_launch_service` with `capped_popen`, `load_caps` and `readiness_code` injected there (`seat_resource_caps` internals are never patched), including the obligations of binding §6 E2-1, E2-2 and E2-4 and §7 E3-1, using the common supervisor core for callable-injection tests and a separate real detachment test per §9 | `V3c` |
| SL-8.2 | impl | SL-8.1 | SL-8 source files | — | — |
| SL-8.3 | verify | SL-8.2 | SL-8 owned files | all SL-8 tests and affected SL-2, SL-3a and SL-7 regressions | `V3c`, `V2`, `V3a`, `V3b` and the hosted mount workflow floor check; the SL-8 mutations of binding §7 E3-3 each fail through a production path |

### SL-9 — Openshell route, bridge and coordinator lifetime (SL-3d)

- **Scope**: The openshell route after the claim, against the fake coordinator: storage and provisioning of SL-8's staged payload and its results, the one coordinator exec with the landlock-exec helper from the image record (fixture until binding §6 E2-6 lands), bridge attach and loss, coordinator renewal, fencing and `lifetime_exceeded`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_openshell.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/tests/test_launch_openshell.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`
- **Interfaces provided**: `launch_openshell.run_staged(handoff: SupervisorHandoff, *, staged: StagedCapture, return_dir: Path, lifetime: LaunchLifetime) -> LaunchResponse` (§9)
- **Interfaces consumed**: `launch_exec.launch_attempt`, the supervisor and lifetime core (SL-8), the lifecycle hooks (SL-3), `ForwardTcpUnixBridge` (PLACECLI), `openshell_artifacts.Bound` (pre-existing), `openshell_worker.landlock_manifest` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-9.1 | test | — | SL-9 test files | the SL-9 rows of binding §7 E3-3, through `build_launch_service` with a fake coordinator | `V3d` |
| SL-9.2 | impl | SL-9.1 | SL-9 source files | — | — |
| SL-9.3 | verify | SL-9.2 | SL-9 owned files | all SL-9 tests | `V3d`; the SL-9 mutations of binding §7 E3-3 each fail through a production path |

### SL-4 — Phase-loop lane placement site

- **Scope**: Wire writable `lane_execute` units through `lane_launch.place_lane`, disabled by default, with the executor resolved before reserve; guard the concurrent wave path (binding §6 E2-3).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_phase_loop_lane_placement.py`, `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py`
- **Interfaces provided**: `lane_launch.place_lane`, `LaneLaunchOutcome`, `lane_launch.lane_context(unit: WorkUnitState) -> LaneContext` (§9)
- **Interfaces consumed**: `LaunchService` (SL-3, complete after SL-9), `launch_settings` (SL-7), `PlacementLifecycle` (PLACECLI), `default_executor_for_work_unit` (pre-existing), `launch_harness_lane_work_unit` (pre-existing), `lane_wave_executor.execute_lane_waves` (pre-existing, unchanged)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | SL-4 test files | obligation C9 through `launch_harness_lane_work_unit`: disabled placement leaves the existing launch and argv byte-identical; enabled, a Pi lane selects the toolkit shim's endpoint and never reserves `pi-runner` itself, other executors reserve `agent-harness`/`implementation`; reducer, review, verify and closeout units never reach the site; an executor or provider change after reserve refuses; a missing or mismatched scheduler context refuses admission, and verified context reaches the service through place_lane; a typed refusal releases without fallback; the falsifiers of binding §6 E2-3 for the concurrent wave path and the `jevdrill_adapter` call | `V4` |
| SL-4.2 | impl | SL-4.1 | `lane_launch.py`, `runner.py` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 owned files | all SL-4 tests | `V4` |

### SL-5 — Launch process CLI and launch inventories

- **Scope**: Register `agent-harness-launch`, assemble it from the shared service, and record every new launch site, helper and dynamic import.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py`, `phase-loop-runtime/tests/test_launch_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `agent-harness-launch`, `launch_cli.main`, `launch_cli.version_response`
- **Interfaces consumed**: `decode_launch_request`, `encode_launch_response` (SL-0), `build_launch_service` (SL-3, complete after SL-9), `launch_settings` (SL-7), the `launch_admission` helper (SL-8)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | SL-5 test files | installed entry and module path with isolated imports, controlled HOME and config and hostile selection variables; required `--client`; exit classes (70 for schema-invalid input with stdout absent; `prepare` 0, 10 and 20); one JSON line; no sentinel leakage; with an unreadable caps record `version` exits 0 with the sentinel `seat_caps_sha256` and empty stderr and `--help` names the caps state (coordinator ruling 1); `version` reports both protocol digests, `config_sha256`, `seat_caps_sha256`, `local_pi_runner_launcher`, `seed_root`, effective seed limits and templates, the local template's `template_sha256` being the erratum record's (LANEEXEC-v1-errata-1 E3); inventory rows for the supervisor and chain-root launches, both through `seat_uid.trusted_module_argv`, never `-m`; the admission-helper rows of binding §7 E3-1 | `V5` |
| SL-5.2 | impl | SL-5.1 | `launch_cli.py`, `pyproject.toml`, `uv.lock`, `tests/data/seat_launch_references.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 owned files | all SL-5 tests | `V5` |

### SL-6 — Documentation, receipt and spec reconciliation

- **Scope**: Publish the launch service, record evidence and reconcile specs only through amendments.
- **Owned files**: `docs/placement-launch-service.md`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `plans/evidence/placement/LANEEXEC.md`, `phase-loop-runtime/tests/test_laneexec_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: launch-service documentation, IF-0-LANEEXEC-1 receipt
- **Interfaces consumed**: `decode_launch_request` (SL-0), `build_snapshot` (SL-1), `collect_return` (SL-2), `LaunchService` (SL-3, SL-7, SL-8, SL-9), `lane_launch.place_lane` (SL-4), `agent-harness-launch` (SL-5)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `tests/test_laneexec_receipt.py` | the receipt parser refuses missing or skipped-only results, stale artifact hashes, a shared-file pin, an enabled live route, a shipped `laneexec` launcher default, a shipped qualification record, or a receipt without a `laneexec-mounts` run at the receipt's head whose JUnit artifact shows M1–M5 passed with mounts required, including a negative case where the artifact lacks the `PHASE_LOOP_TEST_REQUIRE_MOUNTS` testsuite property or carries a value other than `1` (binding §7 E3-4) | `V6` |
| SL-6.2 | docs | SL-6.1 | docs, README, catalog | messages, `prepare`, exit classes, routes and the L-S7 mapping, templates, the `launch` settings object (binding §7 E3-2), snapshot modes and masks, seeds and `scratch_path`, lifetime, caps on the block-backed route (L-S3), status and cancel mapping (L-S4), return rules (L-S5), the interim local route and switch; providers name egress only and credentials stay with the requester | — |
| SL-6.3 | docs | SL-6.2 | `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`, `plans/evidence/placement/LANEEXEC.md` | one Unreleased entry; actual V0–V7 outcomes; lifecycle event appended without editing frozen inputs | — |
| SL-6.4 | verify | SL-6.3 | SL-6 owned files | receipt test | `V6`, then `V7` |

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-1: effort=high, reason=hostile-source snapshot construction
- SL-3: effort=high, reason=claim compare-and-set, prepare replay and release/reap races on the placement journal
- SL-8: effort=high, reason=claim ordering across placement journal, isolated admission, worker journal and cgroup
- SL-9: effort=high, reason=coordinator lifetime, fencing and bridge loss
- SL-6: effort=low, reason=documentation and receipt reducer

## Execution Notes

- **Cross-phase order**: LANEEXEC starts after CLOSEOUT and PLACECLI have
  merged and merges last (`plans/artifacts/v12-v13-replan-ownership.md`).
  SL-3 edits `sandbox_placement.py`, and SL-9 edits `placement_lease.py` and
  `openshell_backend.py`, after PLACECLI; SL-0 and SL-5 extend files PLACECLI and
  CLOSEOUT also edited, additively.
- **Single-writer files**: `pyproject.toml`, `uv.lock` and the four inventory
  files (SL-5); `runner.py` (SL-4; `capability_registry.py` is consumed unchanged, coordinator ruling 2);
  `plans/manifest.json`, `CHANGELOG.md`, `.doc-decisions.json` and
  `.claude/docs-catalog.json` (SL-6); `test_gate_a_wheel_isolation.py` (SL-0).
  `uv.lock` stays byte-identical.
- **Late-bound seams** (binding §7 E3-3): `LaunchService.launch` (SL-3) calls SL-8, and the
  openshell route entry (SL-8) calls SL-9, each imported at call time. No earlier-lane test
  enters them, and SL-4 and SL-5 start only after SL-9. SL-2, SL-3a and SL-7 retain file ownership for the §9 precursor amendments. Their new obligations must pass before SL-8 dispatch.
- **No CLOSEOUT file is edited**: SL-8 implements the fail-closed path and offline controls in §9. Authoritative positive acceptance awaits the named upstream evidence.
- **Activation prerequisites recorded, not built**: the three SEATS caps APIs of binding §3 L-S3 (agent-harness#2098); no local LaneExec route is enabled before they land.
- **Known destructive changes**: none. Every lane is additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; nothing is exported from the package root.
- **Package data**: `contracts/placement/**` is already package data; V7 checks
  the installed wheel.
- **Shared host**: dev0 runs plan validators only. V0–V7 run on `ai` under the
  admission lock and PSI gates, serially, `timeout 900`, no xdist, no cache.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Validator (N)**: package and changelog ownership read as release-shaped;
  this phase dispatches no tag or release.
- **Not in this phase**: live `ai` use, a registered OpenShell backend, any
  change to `_NONLOCAL_EXECUTION_DRIVER` or `policies.json`, enabling
  `lane_placement`, flipping `local_pi_runner_launcher`, a shipped qualification
  record, E2B, toolkit changes, and edits to the seat jail, seat caps or CLOSEOUT
  files.

Next phase: LANEEXEC — dispatch SL-8 under separate execution authority after the §9 precursor checks pass. The advisor-board panel returned
AGREE-WITH-EDITS, its edits are applied, and the CLOSEOUT and PLACECLI work-start gates
are met (binding §6 E2-5). The §9 precursors and separate execution authority govern SL-8 dispatch.
Next command: `claude-execute-phase plans/phase-plan-v13-LANEEXEC.md` under separate execution authority.

## Deferred Items

Recorded, not built in this phase (coordinator ruling 4, 2026-11-09).

| Item | Owner | Effect on this phase |
| --- | --- | --- |
| Template and worker-policy adapter | Cross-plan owner decision (CLOSEOUT erratum or new phase), agent-harness#2148 | EC-LANEEXEC-1 and EC-LANEEXEC-2 authoritative execution positives pending real evidence against both policy commitments. |
| Bound worker-result handoff | Same cross-plan decision, agent-harness#2148 | EC-LANEEXEC-2 authoritative patch-return positive pending a verified, acknowledged worker terminal and proposal. |
| Managed per-attempt caller-context suitability records | Future managed authority producer for the route (§9) | EC-LANEEXEC-1 and EC-LANEEXEC-2 positives for nonempty context pending independent suitability evidence; SL-8 tests the real admission diagnostic. |
| SEATS public caps APIs: an expected-digest check inside `capped_popen`, typed evidence of whether a failure came before or after its helper started, and kill/collect of a capped parent by key | SEATS/JAILCORE; agent-harness#2098, scheduled against v13 ACTIVATE, cross-linked to agent-harness#1963 and agent-harness#1895 | Activation prerequisite: no local LaneExec route is enabled before they land (binding §3 L-S3). |
| Caps contract §1a tmpfs carve-out cleanup | SEATS; agent-harness#2099 | tmpfs attempt paths refuse until it lands; adopting it needs no wire change. |
| Garbage collection of orphaned content-addressed echoes (capped and secret-free) | v12 supervised-worker follow-up; agent-harness#2100, parked | None; LANEEXEC writes no echo. |
| Folding the reinterpreted sentences into the next protocol versions: the PLACECLI `launch_binding` sentence, the LANEEXEC narrowings and the wheel-shipped `x-*` prose | v13 placement protocol owner; agent-harness#2105, parked | The narrowings of `x-snapshot.upload`, `x-seed.provisioning`, `x-exec.claim_rollback`, `x-exec.after_start`, `x-local-cgroup.automatic_paths` and `x-lifetime.supervisor_death` and the L-S8 reading stay in the binding artifact. |
| The ACTIVATE roadmap goal for the owner zero-egress ruling (binding §6 E2-2) | v13 ACTIVATE roadmap amendment; agent-harness#2104 | None; SL-8 wires the launch check, and ACTIVATE supplies the live evidence. |
| The `/var/log` runtime check of the local template in its LANEEXEC-v1-errata-1 form: under the expanded argv, `/var/log` exists, lists empty and refuses a write, on Ubuntu 24.04 and 26.04 | v13 ACTIVATE local-launch qualification; owner-gated | None; the erratum is document-and-test only, and no local route is activated before this check is recorded. |
| Routing concurrent lane waves through `place_lane` while `lane_placement` is enabled (binding §6 E2-3) | v13 ACTIVATE; agent-harness#2103 | None; with placement enabled the wave path refuses `lane_placement_wave_unrouted`. |
| The pinned review-runner image record (binding §6 E2-6) | new review-runner image phase (RR-1 option c); tracking issue to come with its plan | None; SL-9 reads the helper path and digest only from that record, and tests use a fixture. |
| Reviewed, image-bound openshell runtime values (node path and digest, helper digest, launcher and tree paths) that the pinned toolkit runtime manifest lacks (binding §8 E4-2) | SL-9 and v13 ACTIVATE | None; production openshell registration stays closed (`runtime_unavailable`), and every openshell route is `route_disabled` under shipped defaults. |
| Production worker state root taken from trusted operator configuration | agent-harness#1960 | None; the CLI's state root is CLOSEOUT's. |
| A sanctioned `replan` lifecycle path in `plan_manifest.update_lifecycle` (the replan events here are hand-written and append-only) | coordinator follow-up (ruling 3) | The `v13-LANEEXEC` row carries one hand-written `replan` event. |

## Acceptance Criteria

SL-6 applies the evidence boundaries in binding §9. An outstanding authoritative producer or containment proof leaves its corresponding positive criterion open.

- [ ] EC-LANEEXEC-1 — proven by V3, V4 and V5 (`tests/test_launch_service.py`, `tests/test_phase_loop_lane_placement.py`, `tests/test_launch_cli.py`) through `build_launch_service`, `place_lane` and the installed entry for every `x-client-routes` row; falsified by a reducer or review unit reaching `place_lane`, a provider or executor change after reserve, a second launch for one reservation reaching the launch-chain counter, or a writable lane started through `execute_lane_waves` while `lane_placement` is enabled (binding §6 E2-3), each entered through the production construction site.
- [ ] EC-LANEEXEC-2 — proven by V1, V2 and V3 (`tests/test_launch_snapshot.py`, `tests/test_launch_return.py`, `tests/test_launch_service.py`) for snapshot, envelope derivation through `prepare_launch_v2`, one exec, local caps before exec and return bounds; falsified by an omitted or mismatched egress grant, an undeclared launch input in argv, an unverified seed file reaching `scratch/`, a target marker running before readback, a `not_armed` attempt, or a proposal over cap returned, each entered through `build_launch_service`.
- [ ] EC-LANEEXEC-3 — proven by V3 and V5 (`tests/test_launch_local_caps.py`, `tests/test_launch_release_reap.py`, `tests/test_seat_launch_helpers_trusted.py`) for `pi-runner` identity and inventory, bridge only on `openshell`, local `bridge: null`, `capability_unmet` with nothing run, caller-scoped reap and the inventory rows for agent-harness#1787 to agent-harness#1790 controls; falsified by a credential sentinel in sandbox, template, environment, record or evidence, a local bridge, cross-inventory reap, an uncapped local start or a tmpfs attempt path admitted.
- [ ] EC-LANEEXEC-4 — proven by V3 and V4 fake-coordinator, egress-digest, headroom-refusal, bridge-loss, cancel, timeout, crash/restart and return mutations at the production construction sites in `tests/test_launch_service.py`, `tests/test_launch_lifetime.py` and `tests/test_launch_openshell.py`; falsified by any coordinator connection under shipped configuration, a swallowed renewal failure, a target alive at `h + T`, or a test that replaces `build_launch_service` or `build_snapshot`.
- [ ] EC-LANEEXEC-5 — proven by V4 (`tests/test_phase_loop_lane_placement.py`: disabled placement leaves the existing launch byte-identical), V3 (`toolkit_interim` refuses local `pi-runner` with zero invocations) and the V6 receipt showing both shipped defaults; falsified by a shipped `laneexec` or `enabled` default, or removal of the existing local route.

## Verification

Execution-time commands, none run by this planning change; membership is
binding §5. Each group runs as `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider <group files>`.

- V0: `tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest`
- V1: `tests/test_launch_snapshot.py`
- V2: `tests/test_launch_return.py`
- V3a: `tests/test_launch_prepare.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py`
- V3b: `tests/test_launch_routes.py`
- V3c: `tests/test_launch_service.py tests/test_launch_admission.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py`; the M1–M5 mount nodes skip with a named reason without fixture mounts and run in `laneexec-mounts` (binding §7 E3-4)
- V3d: `tests/test_launch_openshell.py tests/test_placement_lease.py tests/test_openshell_backend.py`
- V3: V3a to V3d together
- V4: `tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py`
- V5: `tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V6: `tests/test_laneexec_receipt.py`
- V7: an installed wheel built the way `phase-loop-runtime/scripts/gate_a_cleanroom.sh` builds it, then V0 and V5 against it.

At execution preflight validate V0–V7 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple-failure reporting and flag any node over roughly five minutes. Live
operational evidence belongs to ACTIVATE and its runner-stamped amendment; proxy
evidence needs a roadmap amendment.
