---
phase_loop_plan_version: 1
phase: LANEEXEC
roadmap: specs/phase-plans-v13.md
roadmap_sha256: a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest tests/test_launch_snapshot.py tests/test_launch_return.py tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_laneexec_receipt.py"]
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
Nothing of it has landed. The landed WORKER is a local fixture seam whose
production CLI still refuses `codec_unavailable`, so LANEEXEC builds on the
CLOSEOUT and PLACECLI re-plans, not on WORKER directly.

Frozen inputs, read before building:

- `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, unchanged and still
  vendored by agent-toolkit at its digest. It carries IF-0-LANEEXEC-1: messages,
  CLI, routes, templates, snapshot, seed, prepare, envelope derivation, exec,
  caps, lifetime, bridge, status/cancel, return, evidence, activation defaults
  and obligations C1–C11.
- `plans/artifacts/v13-LANEEXEC-landed-binding.md`: work-start gates and what is
  dropped (§1), the landed-interface table at `file:line` (§2), the STOP
  decisions with the wire sentences they bind (§3), cross-repo consequences (§4)
  and verification groups (§5).
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
| L-S1 | Depend on CLOSEOUT: pre-claim `prepare_launch_v2` in process, disposed through `discard_admission`, then one `supervised_worker_cli launch --envelope --result` chain root that reads the CLOSEOUT §4.2 controller document and re-admits authoritatively. No admission code here. Adopted. |
| L-S2 | The JOURNAL reservation stays worker-owned. The claim is one durable write in the placement journal; every rollback precedes the first chain process, so no permanent reservation is ever orphaned and the prepared `attempt_id` stays valid. |
| L-S3 | Block-backed route: local attempt directories live under the client's LaneExec state directory and share `staging_root()`'s filesystem; tmpfs refuses `capability_unmet`; no carve-out and no caps API change; `capped_popen` failures keep the claim; the missing SEATS caps APIs gate activation. Deviates from the sweep (keep blocked) to remove the tmpfs prerequisite. |
| L-S4 | A total mapping onto the existing wire states, with LaneExec's own terminal record first; every failure after the first chain process is `finished`/`failed_to_start`; zero-signal cancels return `cancel_pending`, never success. Adopted. |
| L-S5 | `patch` reuses WORKER's fail-closed withholding; `result` and `none` are specified separately; no private WORKER helper is used. Adopted. |
| L-S6 | Zero-effect assertions scoped by stage. Adopted. |
| L-S7 | Per-action route mapping defined; no qualification record shipped; local review seats never launch through LaneExec. Adopted. |
| L-S8 | No repin: both v13 wire artifacts keep their bytes; this artifact's existing bare-hex grant rule governs. Deviates from the sweep (hold) as in PLACECLI P-S2. |

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

- [ ] IF-XR-1 (agent-toolkit, consumer) — unchanged wire and digest; the toolkit
  keeps its capped bwrap launcher while `local_pi_runner_launcher` is
  `toolkit_interim` and switches only under the ACTIVATE condition. It can
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
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no

SL-1 — Snapshot and seed construction
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Return, status and cancel mapping
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Launch service, exec claim, local caps, lifetime and lifecycle interplay
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4, SL-5
  Parallel-safe: no

SL-4 — Phase-loop lane placement site
  Depends on: SL-0, SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-5 — Launch process CLI and launch inventories
  Depends on: SL-0, SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-6 — Documentation, receipt and spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

The roadmap's four lane concerns map onto these: dispatch, admission and
snapshot (SL-0, SL-1, SL-3); workload, command and bridge (SL-3, SL-4, SL-5);
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
| SL-0.1 | test | — | `tests/test_launch_process_contract.py`, `tests/test_gate_a_wheel_isolation.py` | obligation C1 and the schema cases of C10 and C11 as the wire artifact lists them; both crossed Pi policy/target pairs decode and are left to SL-3's binding refusal; `patch` with `pi-runner` refused; packaged bytes equal the artifact; Reservation resolves through the PLACECLI `$id`; installed-wheel load; additions to `tests/test_gate_a_wheel_isolation.py` go in `GateAConformEvidenceScopeTest` | `V0` |
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

- **Scope**: Turn a terminated attempt into one bounded return plus metadata-only evidence, and map local status and cancel outcomes onto the wire as decided in L-S4 and L-S5.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_return.py`, `phase-loop-runtime/tests/test_launch_return.py`
- **Interfaces provided**: `collect_return`, `ReturnOutcome`, `map_status`, `map_cancel`, `LaunchEvidence` builder; signature `collect_return(attempt, kind, *, policy, withhold, bound) -> ReturnOutcome`
- **Interfaces consumed**: launch records (SL-0), `WorkerResult` (pre-existing), `ProposalReturn` (pre-existing), `CancelOutcome` (pre-existing), `attempt_status` (pre-existing), CLOSEOUT `v2_status_mapping`, `openshell_artifacts.check_binary_literals` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_launch_return.py` | obligation C8 as narrowed by L-S5: every proposal status row of the L-S5 table, including cancelled and timed-out `withheld_incomplete` returning null; a masked baseline path; digest mismatch at the locator; `result.json` bounds, duplicate keys, trailing data and `truncated: true`; `withhold` deleting bytes; 0700/0600 descriptors; a raw-output sentinel never in a record or evidence; the L-S4 status and cancel tables as closed exhaustive tables, with zero-signal outcomes never mapping to `cancelled` or `already_terminal` | `V2` |
| SL-2.2 | impl | SL-2.1 | `launch_return.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests | `V2` |

### SL-3 — Launch service, exec claim, local caps, lifetime and lifecycle interplay

- **Scope**: The one `LaunchService`: admission order, pre-claim v2 admission, exec claim, the CLOSEOUT controller hand-off and chain root, local and openshell route entries, the capped parent, the detached supervisor with lease liveness, bridge attach, status/cancel and release/reap hooks.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_service.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/tests/test_launch_service.py`, `phase-loop-runtime/tests/test_launch_local_caps.py`, `phase-loop-runtime/tests/test_launch_lifetime.py`, `phase-loop-runtime/tests/test_launch_release_reap.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`
- **Interfaces provided**: `build_launch_service`, `LaunchService`, release/reap attempt hooks in `PlacementLifecycle`
- **Interfaces consumed**: records (SL-0), `build_snapshot`, `build_seed` (SL-1), `collect_return`, `map_status`, `map_cancel` (SL-2), `PlacementLifecycle`, `ForwardTcpUnixBridge` (PLACECLI), `load_v2_binding`, `capture_launch_v2`, `prepare_launch_v2`, `discard_admission`, `AttemptBinding`, the §4.2 controller document and `supervised_worker_cli launch --envelope --result` (CLOSEOUT), `seat_resource_caps.capped_popen` (pre-existing), `seat_resource_caps.load_caps` (pre-existing), `seat_resource_caps.readiness_code` (pre-existing), `seat_uid.trusted_module_argv` (pre-existing), `sandbox_policy.staging_root` (pre-existing), `cancel_attempt` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | SL-3 test files | obligations C2 and C4–C7, C10 and C11 through `build_launch_service` with a fake coordinator and `capped_popen`, `load_caps` and `readiness_code` injected at `build_launch_service` (defaults are the landed functions; `seat_resource_caps` internals are never patched): stage-scoped zero-effect counters (L-S6); the bare-hex egress grant; pre-claim `prepare_launch_v2` refusal with no claim; claim order with a crash injected between each step, rollback only before the first chain process and relaunch of the prepared `attempt_id` under a new request_id, claims kept after it (L-S2); the chain root argv built by `trusted_module_argv` and started through `capped_popen` with key `laneexec:<client>:<reservation_id>`; the controller document at its envelope-digest path under `controller_root` only; the `PreparedLaunch` discarded on every path; local attempt directories outside the client's LaneExec state directory, on another filesystem than `staging_root()` or on tmpfs refusing `capability_unmet` before the claim; a caps digest change before chain start rolling back; any `capped_popen` exception keeping the claim as `finished`/`failed_to_start` (L-S3); an inner WORKER refusal after chain start reported `finished`/`failed_to_start` by launch and by `status` after restart (L-S4); a `launch` referent changed without its path refusing `sandbox_launch_input_mismatch`; lifetime renewal, fencing and `ttl_s` floor as frozen; bridge loss, cancel through the verified owner, release then `cleanup_pending`, reap of a dead supervisor in its own inventory reporting its capped parent `cleanup_pending`; with an unreadable caps record `prepare` and `launch` refusing `capability_unmet` for every target while `status` and `cancel` keep working (coordinator ruling 1); `route_disabled` under shipped defaults, `toolkit_interim` for local `pi-runner`, local `leg`/`qualification` always `route_disabled` (L-S7); crossed Pi pairs and template selection as frozen | `V3` |
| SL-3.2 | impl | SL-3.1 | SL-3 source files | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 owned files | all SL-3 tests | `V3`; mutations that drop the capped parent, skip the claim write, launch after `pre_exec` refuses, roll back after the first chain process, reach a coordinator under shipped defaults, swallow a renewal failure or accept a tmpfs attempt path each fail through a production path |

### SL-4 — Phase-loop lane placement site

- **Scope**: Wire writable `lane_execute` units through `lane_launch.place_lane`, disabled by default, with the executor resolved before reserve.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_phase_loop_lane_placement.py`, `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py`
- **Interfaces provided**: `lane_launch.place_lane`, `LaneLaunchOutcome`
- **Interfaces consumed**: `LaunchService` (SL-3), `PlacementLifecycle` (PLACECLI), `default_executor_for_work_unit` (pre-existing), `launch_harness_lane_work_unit` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | SL-4 test files | obligation C9 through `launch_harness_lane_work_unit`: disabled placement leaves the existing launch and argv byte-identical; enabled, a Pi lane selects the toolkit shim's endpoint and never reserves `pi-runner` itself, other executors reserve `agent-harness`/`implementation`; reducer, review, verify and closeout units never reach the site; an executor or provider change after reserve refuses; a typed refusal releases without fallback | `V4` |
| SL-4.2 | impl | SL-4.1 | `lane_launch.py`, `runner.py` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 owned files | all SL-4 tests | `V4` |

### SL-5 — Launch process CLI and launch inventories

- **Scope**: Register `agent-harness-launch`, assemble it from the shared service, and record every new launch site, helper and dynamic import.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py`, `phase-loop-runtime/tests/test_launch_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `agent-harness-launch`, `launch_cli.main`, `launch_cli.version_response`
- **Interfaces consumed**: `decode_launch_request`, `encode_launch_response` (SL-0), `build_launch_service` (SL-3)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | SL-5 test files | installed entry and module path with isolated imports, controlled HOME and config and hostile selection variables; required `--client`; exit classes (70 for schema-invalid input with stdout absent; `prepare` 0, 10 and 20); one JSON line; no sentinel leakage; with an unreadable caps record `version` exits 0 with the sentinel `seat_caps_sha256` and empty stderr and `--help` names the caps state (coordinator ruling 1); `version` reports both protocol digests, `config_sha256`, `seat_caps_sha256`, `local_pi_runner_launcher`, `seed_root`, effective seed limits and templates; inventory rows for the supervisor and chain-root launches, both through `seat_uid.trusted_module_argv`, never `-m` | `V5` |
| SL-5.2 | impl | SL-5.1 | `launch_cli.py`, `pyproject.toml`, `uv.lock`, `tests/data/seat_launch_references.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 owned files | all SL-5 tests | `V5` |

### SL-6 — Documentation, receipt and spec reconciliation

- **Scope**: Publish the launch service, record evidence and reconcile specs only through amendments.
- **Owned files**: `docs/placement-launch-service.md`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `plans/evidence/placement/LANEEXEC.md`, `phase-loop-runtime/tests/test_laneexec_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: launch-service documentation, IF-0-LANEEXEC-1 receipt
- **Interfaces consumed**: `decode_launch_request` (SL-0), `build_snapshot` (SL-1), `collect_return` (SL-2), `LaunchService` (SL-3), `lane_launch.place_lane` (SL-4), `agent-harness-launch` (SL-5)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `tests/test_laneexec_receipt.py` | the receipt parser refuses missing or skipped-only results, stale artifact hashes, a shared-file pin, an enabled live route, a shipped `laneexec` launcher default or a shipped qualification record | `V6` |
| SL-6.2 | docs | SL-6.1 | docs, README, catalog | messages, `prepare`, exit classes, routes and the L-S7 mapping, templates, snapshot modes and masks, seeds and `scratch_path`, lifetime, caps on the block-backed route (L-S3), status and cancel mapping (L-S4), return rules (L-S5), the interim local route and switch; providers name egress only and credentials stay with the requester | — |
| SL-6.3 | docs | SL-6.2 | `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`, `plans/evidence/placement/LANEEXEC.md` | one Unreleased entry; actual V0–V7 outcomes; lifecycle event appended without editing frozen inputs | — |
| SL-6.4 | verify | SL-6.3 | SL-6 owned files | receipt test | `V6`, then `V7` |

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-1: effort=high, reason=hostile-source snapshot construction
- SL-3: effort=high, reason=claim ordering across placement journal and worker journal and cgroup
- SL-6: effort=low, reason=documentation and receipt reducer

## Execution Notes

- **Cross-phase order**: LANEEXEC starts after CLOSEOUT and PLACECLI have
  merged and merges last (`plans/artifacts/v12-v13-replan-ownership.md`).
  SL-3 edits `sandbox_placement.py`, `placement_lease.py` and
  `openshell_backend.py` after PLACECLI; SL-0 and SL-5 extend files PLACECLI and
  CLOSEOUT also edited, additively.
- **Single-writer files**: `pyproject.toml`, `uv.lock` and the four inventory
  files (SL-5); `runner.py` (SL-4; `capability_registry.py` is consumed unchanged, coordinator ruling 2);
  `plans/manifest.json`, `CHANGELOG.md`, `.doc-decisions.json` and
  `.claude/docs-catalog.json` (SL-6); `test_gate_a_wheel_isolation.py` (SL-0).
  `uv.lock` stays byte-identical.
- **No CLOSEOUT file is edited**: if the CLOSEOUT hand-off (the §4.2 controller document,
  `prepare_launch_v2`, `discard_admission`, the status mapping) is insufficient, the lane stops and
  reports the sentence to change.
- **Activation prerequisites recorded, not built**: the three SEATS caps APIs of binding §3 L-S3; no local LaneExec route is enabled before they land.
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

Next phase: LANEEXEC — blocked: advisor-board panel review of this re-plan, then
the CLOSEOUT and PLACECLI work-start gates.
Next command: none until those clear; then
`claude-execute-phase plans/phase-plan-v13-LANEEXEC.md` under separate execution authority.

## Deferred Items

Recorded, not built in this phase (coordinator ruling 4, 2026-11-09).

| Item | Owner | Effect on this phase |
| --- | --- | --- |
| SEATS public caps APIs: an expected-digest check inside `capped_popen`, typed evidence of whether a failure came before or after its helper started, and kill/collect of a capped parent by key | SEATS/JAILCORE; new issue scheduled against v13 ACTIVATE, cross-linked to agent-harness#1963 and agent-harness#1895 | Activation prerequisite: no local LaneExec route is enabled before they land (binding §3 L-S3). |
| Caps contract §1a tmpfs carve-out cleanup | SEATS | tmpfs attempt paths refuse until it lands; adopting it needs no wire change. |
| Garbage collection of orphaned content-addressed echoes (capped and secret-free) | v12 supervised-worker follow-up; new parked issue | None; LANEEXEC writes no echo. |
| Folding the reinterpreted sentences into the next protocol versions: the PLACECLI `launch_binding` sentence, the LANEEXEC narrowings and the wheel-shipped `x-*` prose | v13 placement protocol owner; new parked issue | The narrowings at wire lines 471, 482, 519, 525, 529 and 540 and the L-S8 reading stay in the binding artifact. |
| Production worker state root taken from trusted operator configuration | agent-harness#1960 | None; the CLI's state root is CLOSEOUT's. |
| A sanctioned `replan` lifecycle path in `plan_manifest.update_lifecycle` (the replan events here are hand-written and append-only) | coordinator follow-up (ruling 3) | The `v13-LANEEXEC` row carries one hand-written `replan` event. |

## Acceptance Criteria

- [ ] EC-LANEEXEC-1 — proven by V3, V4 and V5 (`tests/test_launch_service.py`, `tests/test_phase_loop_lane_placement.py`, `tests/test_launch_cli.py`) through `build_launch_service`, `place_lane` and the installed entry for every `x-client-routes` row; falsified by a reducer or review unit reaching `place_lane`, a provider or executor change after reserve, or a second launch for one reservation reaching the launch-chain counter, each entered through the production construction site.
- [ ] EC-LANEEXEC-2 — proven by V1, V2 and V3 (`tests/test_launch_snapshot.py`, `tests/test_launch_return.py`, `tests/test_launch_service.py`) for snapshot, envelope derivation through `prepare_launch_v2`, one exec, local caps before exec and return bounds; falsified by an omitted or mismatched egress grant, an undeclared launch input in argv, an unverified seed file reaching `scratch/`, a target marker running before readback, a `not_armed` attempt, or a proposal over cap returned, each entered through `build_launch_service`.
- [ ] EC-LANEEXEC-3 — proven by V3 and V5 (`tests/test_launch_local_caps.py`, `tests/test_launch_release_reap.py`, `tests/test_seat_launch_helpers_trusted.py`) for `pi-runner` identity and inventory, bridge only on `openshell`, local `bridge: null`, `capability_unmet` with nothing run, caller-scoped reap and the inventory rows for agent-harness#1787 to agent-harness#1790 controls; falsified by a credential sentinel in sandbox, template, environment, record or evidence, a local bridge, cross-inventory reap, an uncapped local start or a tmpfs attempt path admitted.
- [ ] EC-LANEEXEC-4 — proven by V3 and V4 fake-coordinator, egress-digest, headroom-refusal, bridge-loss, cancel, timeout, crash/restart and return mutations at the production construction sites in `tests/test_launch_service.py` and `tests/test_launch_lifetime.py`; falsified by any coordinator connection under shipped configuration, a swallowed renewal failure, a target alive at `h + T`, or a test that replaces `build_launch_service` or `build_snapshot`.
- [ ] EC-LANEEXEC-5 — proven by V4 (`tests/test_phase_loop_lane_placement.py`: disabled placement leaves the existing launch byte-identical), V3 (`toolkit_interim` refuses local `pi-runner` with zero invocations) and the V6 receipt showing both shipped defaults; falsified by a shipped `laneexec` or `enabled` default, or removal of the existing local route.

## Verification

Execution-time commands, none run by this planning change; membership is
binding §5. Each group runs as `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider <group files>`.

- V0: `tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest`
- V1: `tests/test_launch_snapshot.py`
- V2: `tests/test_launch_return.py`
- V3: `tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py`
- V4: `tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py`
- V5: `tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V6: `tests/test_laneexec_receipt.py`
- V7: an installed wheel built the way `phase-loop-runtime/scripts/gate_a_cleanroom.sh` builds it, then V0 and V5 against it.

At execution preflight validate V0–V7 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple-failure reporting and flag any node over roughly five minutes. Live
operational evidence belongs to ACTIVATE and its runner-stamped amendment; proxy
evidence needs a roadmap amendment.
