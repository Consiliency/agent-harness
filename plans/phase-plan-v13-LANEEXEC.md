---
phase_loop_plan_version: 1
phase: LANEEXEC
roadmap: specs/phase-plans-v13.md
roadmap_sha256: 78d0f987f7e5754ed1603291838c8aef8e5bb0ddb70fc32b38400d746d8c134f
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py tests/test_launch_snapshot.py tests/test_launch_return.py tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_laneexec_receipt.py"]
---

# LANEEXEC: Generic placement launch service

## Context

This is Phase 2 of the advisory v13 roadmap. PLACECLI is planned. Its plan
landed as agent-harness#1853, and it stops at reservation, release/reap and the
bridge. LANEEXEC adds the one launch service that every approved client uses
after a reservation. agent-toolkit#54 already reserves through PLACECLI, but it
cannot run a remote Pi end to end until these launch inputs exist.

**Frozen artifact.** `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
sha256 `41db02e67cb37c5c7fc5d70e152e882495bc7f1548a0d7898384eb7ef0f3f36b`,
holds IF-0-LANEEXEC-1. It covers:

- the process entry `agent-harness-launch --client … launch|status|cancel|version`
  and its exit classes;
- the closed request and response records, which reuse the PLACECLI
  `Reservation` by `$id`;
- client routes and launch inputs;
- operator argv templates;
- snapshot construction and upload;
- the derivation of every admitted launch envelope v2 field;
- one exec, the per-reservation local cgroup, lifetime, bridge, status/cancel,
  release/reap interplay, return and evidence;
- activation defaults, the code vocabulary, in-process signatures and test
  obligations C1–C9.

This plan points at sections of the artifact and does not repeat them. The
artifact is read-only during execution. A needed change is an artifact
amendment, not a lane decision.

**Resolved toolkit gaps** (artifact `x-placecli-clarifications`):

1. *`TrailEntry.code` for `admitted`.* This is erratum PLACECLI-v1-errata-1,
   class a, applied to the PLACECLI artifact in this PR: `code` is null if and
   only if `outcome` is `admitted`. It is an erratum, not v2. The artifact's new
   `x-errata.version_rule` allows an erratum to correct a placeholder-only
   conditional or to specify unspecified behaviour. It allows no constant,
   member, verb, exit-class, code or policy-name change. The wire identity is
   `protocol_schema_sha256`, so a client pinned to the old bytes refuses
   cleanly. The roadmap, PLACECLI plan, SEATS REMOTE plan and manifest are
   re-pinned to the new bytes.
2. *Reserve replay after a timeout.* This is the same erratum, class b, as
   `x-placement-semantics.reserve_replay`:
   - While the attempt is unsettled, a replay returns `timeout`, code
     `sandbox_placement_operation_timeout`, exit 20, and creates nothing.
   - Once the attempt settles, every replay returns the settled response
     byte for byte.
   - The settle bound is the journaled start plus the original `deadline_ms`
     plus `replay_settle_allowance_ms` (300000, the pinned transfer allowance).
     Past the bound, the attempt settles terminally as `timeout` with code
     `sandbox_placement_end_reached`, and the `uncertain_cleanup` barrier is
     armed.
   - Reap is still not the retry path.

   The erratum's obligations R1–R3 (and T1) are executed by PLACECLI's lifecycle
   lane. The PLACECLI plan's SL-0 and SL-1 test tasks now name them.
3. *Lifetime past `ttl_s` = 3600.* There is no `renew` verb. The pinned envelope
   v2 caps `launch.stop.timeout_seconds` at 3600 and forbids any deadline change
   after admission. PLACECLI v1 forbids deadline fallback after admission, and
   the roadmap makes every attempt bounded and one-shot, so a renew could never
   lengthen an admitted attempt. The real failure, a lease lapsing while an
   attempt is live, is fixed inside the service. The detached attempt supervisor
   holds the lease lock and renews internally, using the existing heartbeat
   pattern, without touching the stored `Reservation` or the deadline. `ttl_s`
   becomes the window without a heartbeat (`x-lifetime`).
4. *Local `pi-runner`.* `x-activation.local_pi_runner_launcher` ships as
   `toolkit_interim`. The toolkit's capped bwrap route stays the default until
   ACTIVATE (EC-LANEEXEC-5), and LaneExec refuses
   `sandbox_launch_local_route_interim` for that reservation. LaneExec-owned
   local launch (EC-LANEEXEC-3) is built and proven offline here. The switch is
   one config value, bound by `config_sha256` and reported by `version`. It flips
   only under the ACTIVATE three-part condition, and flipping back is the
   rollback.

agent-toolkit#54 also raised these, and the artifact settles them:

- launch inputs (`x-launch-inputs`);
- the caps schema (pinned below);
- the exit class for schema-invalid input: exit 70, already the reading of
  PLACECLI v1 and stated explicitly here.

**Caps.** `seat_resource_caps.v1` from the pinned caps contract is the single
cap schema. LaneExec applies the whole effective record to one capped parent per
`(client, reservation_id)`, and child-side readback is the only proof. The v13
subset (`memory.max`, `cpu.weight`, `io.weight` and `io.max`) is documented in
the caps contract §6, and `seat_caps_sha256` sits inside `config_sha256`. A
missing delegation or controller maps to `sandbox_placement_capability_unmet`,
and nothing runs (`x-local-cgroup`).

**Owner rulings in force.**

- `ai` is the only sandboxed-agent host. dev0 is not a host: no shipped
  configuration names it as a target, and local-launch proofs use fake
  cgroupfs/sysfs trees.
- Pressure gates stay EC-PLACECLI-5. LaneExec adds no pressure check.
- Remote writers carry `provider_readonly_patch_return_audit`. E2B stays parked.

**Other consumers.**

- SEATS REMOTE (`plans/phase-plan-v1-seats-REMOTE.md`) consumes this phase for
  `leg` seats. XR-3 is closed by `x-argv-templates.per_vendor_seat_templates`,
  `x-snapshot.full_mode` and `x-return.result`, and the REMOTE plan now records
  that.
- `leg` on `openshell` keeps the PLACECLI bridge (XR-1) through
  `x-bridge.attach`.

## External Inputs

The artifact's `x-contract-pins` carries every full digest and source revision.

- LaneExec launch protocol v1: the artifact named in Context.
- Placement process protocol v1 with PLACECLI-v1-errata-1:
  `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256
  `ddf3649953bc6ee28fc90466cd825a85e7c282188d84eb97aef107a77234fd57`.
- `seat_resource_caps.v1`: `plans/seats-jailcore-caps-contract.md`, sha256
  `a2fe08ef0e3a6b7d888e948a10e22f7c70c11258db355a551063cf69c2c2a1f2`.
- SEATS REMOTE: `plans/seats-remote-contract.md`, sha256
  `1cea960ddd28ef5e1c4bf79083fa9f9938b2c99c2e29dbd937864944ca76d7e8`.
- Admitted launch envelope v2 and run status at the roadmap-pinned
  consiliency-contract revision (`x-contract-pins.admitted_launch_envelope_v2`,
  `x-contract-pins.run_status`).
- agent-toolkit `writer-snapshot.mjs`, `policy.json`, `cred-proxy.mjs` and
  `docs/remote-placement.md` at the roadmap-pinned revision. These are design
  inputs, read and never copied.

No future implementation SHA, commit count or landing topology is pinned.

## Interface Freeze Gates

- [ ] IF-0-LANEEXEC-1 — The artifact above, byte-equal in source-tree checks to
  the packaged copy. It covers the closed messages and the CLI; the client
  routes, the writer-route rule and executor resolution before reserve;
  template registration and slots; git/full snapshot construction, masks,
  limits and upload; envelope field derivation, including the egress grant from
  `Reservation.egress_sha256`; one exec claim and route entries; the
  per-reservation capped parent; the fixed deadline with internal lease
  liveness; bridge attach and loss; status, cancel, release and reap
  interplay; patch, result and none return with bounded descriptors; and
  disabled activation defaults.

Production signatures freeze as listed in the artifact's `x-in-process-api`:
`decode_launch_request`, `encode_launch_response`, `build_launch_service`,
`LaunchService.launch|status|cancel`, `build_snapshot`, `lane_launch.place_lane`,
`launch_cli.main` and `launch_cli.version_response`. Record fields come only from
the schema. Exceptions translate to closed codes `from None`. Input values,
returned bytes, policy bodies and credential material never enter messages,
diagnostics or evidence.

## Cross-Repo Gates

- [ ] IF-XR-1 (agent-toolkit, consumer) — The toolkit:
  - vendors this artifact by sha256 and refuses on a `version` mismatch;
  - launches `openshell` `pi-runner` reservations through `agent-harness-launch`;
  - keeps its capped bwrap launcher for local `pi-runner` while
    `local_pi_runner_launcher` is `toolkit_interim`. That route applies the full
    `seat_resource_caps.v1` record with readback, bounds the run by a non-null
    `expires_at` and releases on exit;
  - switches only under EC-ACTIVATE-4.
- [ ] IF-XR-2 (SEATS REMOTE XR-3, closed by this freeze) — Workload `leg` gets:
  - one registered template per vendor;
  - `full` snapshot under the size cap, masked by `planted_paths`;
  - action `review`, with one bounded `result` object and no patch;
  - in-process `pre_exec` (the vendor re-check) and `withhold` (the credential
    scan) hooks.
- [ ] IF-XR-3 (consumed) — The PLACECLI `ForwardTcpUnixBridge` for `pi-runner`
  and `leg` on `openshell`, unchanged.

Work-start gates (non-human, `blocker_class=upstream_phase_unmet`):

- PLACECLI implemented, including errata-1;
- EXT-WORKER (v12 IF-0-WORKER-1 and IF-0-JOURNAL-1);
- IF-0-JAILCORE-4 (`seat_resource_caps.py`) landed.

EXT-LAUNCHSITE and EXT-OPENSH are activation prerequisites; their offline
controls run here.

## Lane Index & Dependencies

SL-0 — Packaged launch contract and strict codec
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no

SL-1 — Snapshot construction
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Bounded return and evidence
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Launch service, exec, local caps, lifetime and lifecycle interplay
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

## Lanes

### SL-0 — Packaged launch contract and strict codec

- **Scope**: Package the frozen artifact and expose a side-effect-free strict codec and typed records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `phase-loop-runtime/tests/test_launch_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **Interfaces provided**: `decode_launch_request`, `encode_launch_response`, immutable launch records, packaged launch-v1 bytes
- **Interfaces consumed**: the frozen artifact; packaged PLACECLI process-v1 schema and records (PLACECLI SL-0); `jsonschema`, `referencing` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_launch_process_contract.py`, `tests/test_gate_a_wheel_isolation.py` | Obligation C1. Valid examples for all seven families. Path-entered negatives for every enum and conditional, including `RepoPath` grammar, the workload/action/result_kind pairs, refused→zero invocations and the snapshot_reason/admission_diagnostic pairing. Packaged bytes equal the artifact. Reservation resolves through the PLACECLI `$id`. Installed-wheel load. | `V0` |
| SL-0.2 | impl | SL-0.1 | `launch_process_contract.py`, `contracts/placement/launch-v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | SL-0 tests | `V0`; mutating the packaged bytes while updating only a test expectation must still fail. |

### SL-1 — Snapshot construction

- **Scope**: Build git and full snapshots of a hostile source exactly as `x-snapshot` states, with no network and no source-repository git execution.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_snapshot.py`, `phase-loop-runtime/tests/test_launch_snapshot.py`, `phase-loop-runtime/tests/fixtures/launch-snapshot/**`
- **Interfaces provided**: `build_snapshot`, `SnapshotHandle` (execution tree, descriptor bytes, `SnapshotEvidence`)
- **Interfaces consumed**: `Snapshot` record (SL-0); `openshell_artifacts.Bound`, `safe_path` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_launch_snapshot.py`, fixtures | Obligation C3 on generated temporary repositories: each inventory class; a self-contained `.git` with only B-reachable objects and none of the reference's excluded material; skip-worktree masks; the always-on secret matcher; full mode only where permitted; a non-work-tree root; each cap; a mid-copy mutation giving `source_changed`; each path rule; `untracked_input` for patch. A planted hostile `.git/config` (hooks, fsmonitor, filter) must leave a marker unexecuted. | `V1` |
| SL-1.2 | impl | SL-1.1 | `launch_snapshot.py` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 files | SL-1 tests | `V1` |

### SL-2 — Bounded return and evidence

- **Scope**: Turn a terminated attempt into one bounded patch, result or none return plus metadata-only `LaunchEvidence`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_return.py`, `phase-loop-runtime/tests/test_launch_return.py`
- **Interfaces provided**: `collect_return`, `ReturnOutcome`, `LaunchEvidence` builder; signature `collect_return(attempt, kind, *, policy, withhold, bound) -> ReturnOutcome`
- **Interfaces consumed**: records (SL-0); v12 IF-0-WORKER-1 proposal transport and post-run audit (pre-existing after EXT-WORKER); `output_retention.mark/prune` (pre-existing); `openshell_artifacts.check_binary_literals` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_launch_return.py` | Obligation C8: patch cap, a masked path in a proposal, audit error and unexplained change withholding; `result.json` bound, duplicate keys, trailing data and `truncated: true`; `withhold` deleting bytes; 0700/0600 descriptors; return on cancelled and timed-out terminations; a raw-output sentinel never reaching a record or evidence. | `V2` |
| SL-2.2 | impl | SL-2.1 | `launch_return.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 files | SL-2 tests | `V2` |

### SL-3 — Launch service, exec, local caps, lifetime and lifecycle interplay

- **Scope**: The one `LaunchService`, covering admission order, envelope construction and admission, exec claim, local and openshell route entries, the capped parent, the detached supervisor with internal lease liveness, bridge attach, status/cancel, and the release/reap hooks.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_service.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/tests/test_launch_service.py`, `phase-loop-runtime/tests/test_launch_local_caps.py`, `phase-loop-runtime/tests/test_launch_lifetime.py`, `phase-loop-runtime/tests/test_launch_release_reap.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`
- **Interfaces provided**: `build_launch_service`, `LaunchService`, `LaunchService.launch|status|cancel`, release/reap attempt hooks inside `PlacementLifecycle`
- **Interfaces consumed**: records (SL-0); `build_snapshot` (SL-1); `collect_return` (SL-2); `PlacementLifecycle`, `ForwardTcpUnixBridge`, the stored reservation journal (PLACECLI); `supervised_launch.prepare_launch`/`consume_admission`, `supervised_worker_cli launch|status|cancel`, journal API (v12); `seat_resource_caps.load_caps`, `caps_sha256`, `readiness_code`, `capped_popen` (IF-0-JAILCORE-4); `openshell_worker.landlock_manifest`, `panel_invoker._NONLOCAL_EXECUTION_DRIVER` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | SL-3 test files | Obligations C2, C4–C7 through `build_launch_service` with a fake coordinator, fake cgroupfs/sysfs and fake `systemd-run` (`real_seat_caps` marker). (1) Every refusal through `pre_exec` with zero snapshot, upload, envelope or invocation counters. (2) The egress grant equals the reservation digest's hex. (3) Exec claim survives concurrency and restart. (4) Missing controllers each refuse capability_unmet. (5) A readback mismatch gives finished/failed_to_start with no target marker. (6) An attempt longer than `ttl_s` stays live by renewal while the stored Reservation is byte-identical. (7) lifetime_exceeded ends the attempt timed_out. (8) Bridge loss ends it cancelled. (9) Cancel affects only the verified owner. (10) Release cancels a live attempt, then cleanup_pending. (11) Reap settles a dead supervisor in its own inventory only. (12) route_disabled is refused under the shipped defaults. (13) toolkit_interim refuses local `pi-runner`. | `V3` |
| SL-3.2 | impl | SL-3.1 | `launch_service.py`, `launch_routes.py`, `sandbox_placement.py`, `placement_lease.py`, `openshell_backend.py` | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 files | SL-3 tests | `V3`. Mutation controls, each failing through a production path: drop the capped parent, renew by rewriting the Reservation, skip the exec-claim journal, launch after `pre_exec` refuses, reach a coordinator under the shipped defaults. |

### SL-4 — Phase-loop lane placement site

- **Scope**: Wire writable `lane_execute` units through `lane_launch.place_lane`, which is disabled by default, with the executor resolved before reserve and the `x-client-routes` mapping.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/tests/test_phase_loop_lane_placement.py`, `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py`
- **Interfaces provided**: `lane_launch.place_lane`, `LaneLaunchOutcome` (route `interim_local` or a LaunchResponse)
- **Interfaces consumed**: `LaunchService` (SL-3); `PlacementLifecycle` (PLACECLI); `default_executor_for_work_unit` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | SL-4 test files | Obligation C9 through `launch_harness_lane_work_unit`. (1) `lane_placement` disabled leaves the existing launch and its argv byte-identical. (2) Enabled, a Pi lane reserves `agent-toolkit`/`pi-runner` and other executors reserve `agent-harness`/`implementation`. (3) Reducer, review, verify and closeout units never reach the site. (4) An executor or provider change after reserve refuses. (5) A typed refusal releases and does not fall back. | `V4` |
| SL-4.2 | impl | SL-4.1 | `lane_launch.py`, `runner.py`, `capability_registry.py` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 files | SL-4 tests | `V4` |

### SL-5 — Launch process CLI and launch inventories

- **Scope**: Register `agent-harness-launch`, assemble it from the shared service, and record every new launch site, helper and dynamic import.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py`, `phase-loop-runtime/tests/test_launch_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `agent-harness-launch`, `launch_cli.main`, `launch_cli.version_response`; argv `agent-harness-launch --client … launch|status|cancel|version`
- **Interfaces consumed**: codec (SL-0); `build_launch_service` (SL-3)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | SL-5 test files | Spawn the installed entry and module path with isolated imports, controlled HOME/config and hostile selection variables. Assert the required `--client`, the exit classes (70 for schema-invalid input with stdout absent), one JSON line, empty ordinary stderr and no sentinel leakage. Assert `version` reports both protocol digests, `config_sha256`, `seat_caps_sha256`, `local_pi_runner_launcher` and templates. Classify new rows: helpers launch via `seat_uid.trusted_module_argv`, never `-m`. | `V5` |
| SL-5.2 | impl | SL-5.1 | `launch_cli.py`, `pyproject.toml`, `uv.lock`, `seat_launch_references.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 files | SL-5 tests | `V5` |

### SL-6 — Documentation, receipt and spec reconciliation (docs sweep)

- **Scope**: Publish the launch service and record evidence. Reconcile specs only through amendments.
- **Owned files**: `docs/placement-launch-service.md`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `plans/evidence/placement/LANEEXEC.md`, `phase-loop-runtime/tests/test_laneexec_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: the public launch-service documentation and the IF-0-LANEEXEC-1 receipt
- **Interfaces consumed**: `decode_launch_request` (SL-0), `build_snapshot` (SL-1), `collect_return` (SL-2), `LaunchService` (SL-3), `lane_launch.place_lane` (SL-4), `agent-harness-launch` (SL-5)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `tests/test_laneexec_receipt.py` | The closed receipt parser refuses missing or skipped-only results, stale artifact hashes, an enabled live route or a `laneexec` launcher default. | `V6` |
| SL-6.2 | docs | SL-6.1 | docs, README, catalog | Document messages, exit classes, routes, templates, snapshot modes and masks, lifetime (no renew), caps, the interim local route and switch, and return. Also state that providers name egress only and credentials stay with the requester. Rescan the catalog. | — |
| SL-6.3 | docs | SL-6.2 | `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`, evidence | Add one Unreleased entry. Write actual V0–V7 outcomes and hashes to the receipt. Append manifest lifecycle without editing frozen inputs. Record any freeze correction as a dated amendment request, never as an in-place edit. | — |
| SL-6.4 | verify | SL-6.3 | SL-6 files | receipt test | `V6`, then `V7` |

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-1: effort=high, reason=hostile-source snapshot construction
- SL-3: effort=high, reason=lifecycle ordering across lease and cgroup and journal
- SL-6: effort=low, reason=documentation and receipt reducer

## Execution Notes

- **Work-start gates**: PLACECLI (with errata-1), EXT-WORKER and
  IF-0-JAILCORE-4 must be landed, and their final APIs reconciled with the
  consumed names above. Until then the phase is planned but blocked with
  `blocker_class=upstream_phase_unmet` and `human_required=false`.
- **Cross-phase files**: SL-3 edits `sandbox_placement.py`, `placement_lease.py`
  and `openshell_backend.py`, which PLACECLI SL-1 owns. That is a serial edge,
  because LANEEXEC starts only after PLACECLI lands. SL-0 extends PLACECLI's
  `test_gate_a_wheel_isolation.py`, and SL-5 extends its CLI-adjacent
  inventories. If landed PLACECLI or v12 moves `PlacementLifecycle` or adds a
  shared CLI registry, amend ownership before execution.
- **Single-writer files**: `pyproject.toml`, `uv.lock` and
  `seat_launch_references.json` (SL-5); `runner.py` and
  `capability_registry.py` (SL-4); `plans/manifest.json`, `CHANGELOG.md` and
  `.doc-decisions.json` (SL-6). `uv.lock` stays byte-identical when the lock
  check agrees.
- **Known destructive changes**: none. Every lane is purely additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none. Nothing is exported from the package root, so no lazy `__getattr__` pattern is needed.
- **Package data**: `contracts/placement/**` is already package data. V7 checks
  the installed wheel.
- **Shared host**: before each command, check `uptime` and `/proc/pressure/io`.
  Wait if the 1-minute load is above 16 or IO full avg60 is above 10%. Run only
  targeted files, serially, with no xdist and no cache. Full suites and Gate A
  belong to hosted CI.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Not in this phase**:
  - live `ai` use, a registered OpenShell backend, any change to
    `_NONLOCAL_EXECUTION_DRIVER` or `policies.json`, enabling `lane_placement`,
    flipping `local_pi_runner_launcher`, E2B, and any toolkit change;
  - a new `--client` value for a standalone OpenCode/Claude/Codex harness
    (a PLACECLI protocol version).
- **Next command**: none until the work-start gates are verified. Then run
  `claude-execute-phase plans/phase-plan-v13-LANEEXEC.md` under separate
  execution authority.

## Acceptance Criteria

- [ ] EC-LANEEXEC-1 — proven by `V3`, `V4` and `V5` through `build_launch_service`, `place_lane` and the installed entry for every `x-client-routes` row; falsified by a path-entered reducer or review unit reaching `place_lane`, a provider or executor change after reserve, or a second launch for one reservation reaching the launch-chain counter.
- [ ] EC-LANEEXEC-2 — proven by `V1`, `V2` and `V3` (snapshot, envelope derivation, one exec, local caps before exec, return bounds); falsified by a path-entered omitted or mismatched egress grant, an undeclared launch input entering argv, a target marker running before readback, a `not_armed` placed attempt, or a proposal over cap returned.
- [ ] EC-LANEEXEC-3 — proven by `V3` and `V5` (`pi-runner` identity and inventory, bridge only on `openshell`, local `bridge: null`, capability_unmet with nothing run, caller-scoped reap, inventory rows for agent-harness#1787 to agent-harness#1790 controls); falsified by a path-entered credential sentinel in the sandbox, template, environment, record or evidence, a local bridge, cross-inventory reap or an uncapped local start.
- [ ] EC-LANEEXEC-4 — proven by `V3` and `V4` fake-coordinator, egress-digest, headroom-refusal, bridge-loss, cancel, timeout, crash/restart and return mutations at the production construction sites; falsified by any coordinator connection under shipped configuration, or by a test that replaces `build_launch_service` or `build_snapshot`.
- [ ] EC-LANEEXEC-5 — proven by `V4` (lane_placement disabled leaves the existing launch byte-identical) and `V3` (toolkit_interim refuses local `pi-runner` with zero invocations), plus the `V6` receipt showing both shipped defaults; falsified by a shipped `laneexec` or `enabled` default, or by the existing local route being removed.

## Verification

V0–V7 are execution-time commands, not run by this planning PR.

- V0: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py`
- V1: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_snapshot.py`
- V2: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_return.py`
- V3: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py`
- V4: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py`
- V5: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V6: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_laneexec_receipt.py`
- V7: build an installed wheel in the Gate-A shape of `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, then run V0 and V5 against it. Tests that read repo-only files skip when those files are absent. If landed packaging changes this shape, amend the exact command before execution.

At execution preflight, validate V0–V7 and the frontmatter suite through
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple-failure reporting, and flag proof cost when one node exceeds roughly
five minutes. Operational evidence (a live run) belongs to ACTIVATE and its
runner-stamped amendment. Proxy evidence needs a roadmap amendment.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `docs/placement-launch-service.md`, `docs/placement-process-cli.md`
- evidence paths: `plans/evidence/placement/LANEEXEC.md`
- redaction posture: `metadata_only`
- downstream handling: `none`
