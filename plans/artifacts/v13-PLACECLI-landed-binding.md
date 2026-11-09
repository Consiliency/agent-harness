# v13 PLACECLI: landed binding and STOP decisions (re-plan, 2026-11-09)

Frozen artifact for `plans/phase-plan-v13-PLACECLI.md` (re-plan). It has no word
cap. The wire contract stays `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`
with erratum PLACECLI-v1-errata-1, byte-identical at its roadmap pin; this
artifact does not change one byte of it. It records the landed baseline the
plan builds on, the decision for each STOP item in the pre-build sweep, and the
cross-phase interfaces LANEEXEC consumes.

## 0. Inputs (pins of existing bytes only)

| Input | Identity |
| --- | --- |
| Roadmap | `specs/phase-plans-v13.md`, sha256 `a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d` |
| Placement process protocol v1 (unchanged) | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256 `130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea` |
| Landed baseline inspected | `origin/main` at `a493c46ccf979231b1a3ae5b23ae678a801f0603`. Every `file:line` below refers to this tree. |
| Pre-build sweep | Consiliency/agent-harness#1962 head `8c38caf778ed4455e02158584053cfe5e0f4247b`, `plans/artifacts/v13-PLACECLI-landed-sweep.md` |
| Caps contract | `plans/seats-jailcore-caps-contract.md`, sha256 `e614d3855320fe4c8a1d8b9a335181b2c493da45510062d2f8432ee30c362445` |
| Cross-phase ownership | `plans/artifacts/v12-v13-replan-ownership.md` |

The sweep re-verified the four local input pins inside the protocol artifact
(placement BAML, `sandbox_placement.py`, `policies.json`, driver defaults)
against the baseline; all match. `sandbox_placement.py` and the driver defaults
keep `runtime_equality: false` (planning baselines SL-1 may edit).

## 1. What PLACECLI must still deliver

Nothing of PLACECLI has landed: no `placement_process_contract.py`,
`placement_cli.py`, `placement_bridge.py`, packaged `process-v1.schema.json` or
`agent-harness-placement` console script exists at the baseline. All five goals,
EC-PLACECLI-1 to EC-PLACECLI-5, remain open.

Dropped from the old plan because it is done: the work-start gate on v12
IF-0-WORKER-1 and IF-0-JOURNAL-1 (roadmap gate EXT-WORKER), which landed with
receipts. PLACECLI calls neither the worker nor the journal; the gate was a
sequencing edge only.

## 2. Landed-interface table

"Use": **consume** (call unchanged), **extend** (the owning lane edits it),
**do not touch**.

| Landed site | Shape | Use |
| --- | --- | --- |
| `sandbox_placement.py:264` | `PlacementRequest(leg, round_id, repo, snapshot_sha256, deadline_s, egress_needs, one_shot_secret=True, workload='leg', required_capabilities=frozenset(), root=None, owner_id='', lease_id='')` | extend (SL-1): workload `pi-runner` through the lifecycle mapping only |
| `sandbox_placement.py:445`, `:468` | `PlacementBackend`, `ExecutingBackend` protocols | consume |
| `sandbox_placement.py:563`, `:620`, `:635` | `register_backend`, `backend_for_scheme`, `resolve_backend` | consume; no production OpenShell backend is registered |
| `sandbox_placement.py:731` | `LegPlacement` | consume |
| `sandbox_placement.py:1002`, `:1015` | `lifetime_sufficient`, `lifetime_at_floor` | consume |
| `sandbox_placement.py:1021` | `PlacementDecision(outcome, trail, code=None, placement=None, ..., local_reservation=None, pending_local_reservation=None)` | extend (SL-1) to carry the reservation binding |
| `sandbox_placement.py:1220`, `:1250`, `:1260`, `:1294` | `LocalHeadroom.admits(settings)`, `LocalReservation`, `LocalReservationPending`, `LocalAdmission` | extend (SL-1): fresh-observation thresholds from host config |
| `sandbox_placement.py:1940` | `place(rungs, last_rung, prepared, request_for, open_lease, *, preflight, seal, driver_enabled, cancelled, settings=None, local_capacity=None, local_admit=None, local_release=None)` | consume as the one walk state machine; seats bypass ranking |
| `sandbox_placement.py:2026` | `run_placed(placement, *, on_progress, cancelled)` | consume (LANEEXEC uses it later) |
| `sandbox_policy.py:181`, `:474`, `:491` | `SandboxRootChoice`, `PlacementDriverSettings`, `placement_driver_settings(...)` | extend (SL-1) |
| `advisor_board/config.py:380` | `load_placement_driver_settings(...)` reading `fixtures/placement-driver.defaults.toml` | extend (SL-1) |
| `placement_lease.py:106` | `owner_id()` | extend (SL-1): per-client inventory owner |
| `placement_lease.py:287` | `Lease` (attach/mark/record/fence/heartbeat …) | consume |
| `placement_lease.py:504`, `:554`, `:576` | `open_lease(backend_name, root)`, `recover_lease(lease_id)`, `reap(backends, bound, *, on_refusal=None)` | extend (SL-1): caller-scoped, per-client inventory |
| `openshell_backend.py:36`–`:90` | `StageBinding`, `StageAdapter`, `WorkerAdapter`, `OpenShellBackend` | consume / extend (SL-1) |
| `openshell_channel.py:29` | `MTLSConfig(endpoint, owner_cn, local_owner_id, ca_pem, client_cert_pem, client_key_pem, receive_limit_bytes, connect_timeout_s)` | extend (SL-1): OU per client |
| `openshell_journal.py:249`, `:325` | `ReaperAdapter`, `OpenShellCleanupBackend.kill` | consume |
| `openshell_transport.py:131`, `:462` | `CoordinatorClient.validate_create`, `StockExecChannel` | consume |
| `openshell_worker.py:39`, `:71`, `:160` | `WorkerRequest`, `seal_request(...)`, `run_worker(...)` | extend (SL-2) only where the bridge needs it |
| `cli.py:1099`, `:2895` | `phase-loop placement reap` parser and `_placement_command` | extend (SL-3): delegate in process with an explicit client |
| `seat_resource_caps.py:21`–`:23` | `SCHEMA = "seat_resource_caps.v1"`, `CODE = "seat_resource_caps_unavailable"`, `REQUIRED_CONTROLLERS = {cpu, io, memory, pids}` | consume |
| `seat_resource_caps.py:52`, `:221`, `:242` | `SeatResourceCaps` (whole record), `load_caps()`, `caps_sha256(caps)` | consume (P-S1) |
| `seat_resource_caps.py:365` | `readiness_code() -> str \| None` (delegation, controllers, systemd-run, bus, and `io_devices` over the automatic paths) | consume (P-S1) |
| `panel_invoker.py:4440` | `_NONLOCAL_EXECUTION_DRIVER = False` | do not touch |
| `panel_invoker.py:13354` | jailed Codex seat route (0.7.31) | do not touch; placement never adopts a seat profile |
| `seat_uid.py:490` | `trusted_module_argv(module, *args)` | consume for any helper launch |
| `contracts/placement/vectors/policies.json:3` | `"status": "pending_qualification"` | do not touch |
| `tests/data/seat_launch_references.json:13` | landed WORKER rows (and CLOSEOUT rows after it merges) | extend (SL-3) by union |

## 3. STOP decisions

### P-S1 — caps record and readiness

**Chosen: reuse the complete landed `seat_resource_caps.v1` record and its
readiness check, and split reservation-time readiness from launch-time
readback (sweep recommendation, adopted).**

- **Reservation time (PLACECLI SL-1).** Before any local reservation effect the
  lifecycle calls `seat_resource_caps.load_caps()` and `readiness_code()`. A
  `CapsUnavailable` from the loader or a non-null readiness code maps to outcome
  `refused`, code `sandbox_placement_capability_unmet`, exit 10, with zero
  capacity, coordinator and lease effects. The whole record applies, including
  `cpu_max_percent`, `pids_max` and both IO settings; it is a superset of the
  artifact's "memory.max, cpu.weight and either io.weight or an io.max cap", so
  the protocol artifact is satisfied without change.
- **Binding.** `seat_caps_sha256 = caps_sha256(load_caps())` is part of the
  effective configuration that `config_sha256` hashes (§4.1), so a changed cap
  record changes `config_sha256` and `version` reports it.
- **Launch time (LANEEXEC).** Per-path device readback and cap application in a
  per-reservation parent belong to LANEEXEC (its STOP L-S3). PLACECLI performs no
  per-path check and starts no workload.
- Tests inject the loader and readiness callables at the lifecycle's construction
  site (defaults are the landed functions); they never patch module internals of
  `seat_resource_caps.py`.

### P-S2 — the egress grant spelling (same item as LANEEXEC L-S8)

**Chosen: no byte change and no repin. The protocol artifact keeps its pinned
bytes; the envelope derivation is governed by the LANEEXEC artifact that already
spells it correctly.** This deviates from the sweep recommendation (hold
execution and coordinate a repin set).

Reason: the only defect is the `x-provider-egress.launch_binding` sentence, which
tells LANEEXEC to copy `Reservation.egress_sha256` (`sha256:` plus 64 hex) into
the v2 envelope, whose `$defs.sha256` is bare hex. PLACECLI's own wire
(`Reservation.egress_sha256` with the `sha256:` prefix) is self-consistent and
PLACECLI never builds an envelope. The consumer that does,
`plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`
`x-envelope-construction.fields["launch.grants.egress_policy_sha256"]`, already
says "the 64 hex digits of Reservation.egress_sha256 after the sha256: prefix" on
main. Correcting the PLACECLI sentence would change a digest pinned by the v13
roadmap, the LANEEXEC artifact and plan, SEATS REMOTE and the agent-toolkit
vendoring, for no wire benefit. So:

- the PLACECLI `launch_binding` sentence is read as non-normative where it names
  the digest spelling; the LANEEXEC field rule governs;
- SL-3 documents the spelling rule in `docs/placement-process-cli.md`;
- the next protocol version, if one is ever cut, folds the corrected sentence in.

### X-S1 — CLOSEOUT/PLACECLI shared files

**Chosen: serial integration CLOSEOUT → PLACECLI → LANEEXEC.** PLACECLI may be
built while CLOSEOUT is being built; it merges after CLOSEOUT's implementation
PR and rebases its shared-file edits additively. Full map:
`plans/artifacts/v12-v13-replan-ownership.md`.

## 4. Cross-phase interfaces frozen here

### 4.1 `config_sha256` covers the whole per-client configuration

`config_sha256` is the SHA-256 of the UTF-8 RFC 8785 serialization of the
selected client's effective operator configuration with every referenced
artifact resolved and `seat_caps_sha256` included. PLACECLI validates and
interprets its placement sections. A top-level `launch` member, if present,
must be a JSON object; PLACECLI v1 includes it verbatim in the canonical bytes
and does not interpret it. LANEEXEC validates and interprets that member
(template registry, image allowlist, snapshot and seed limits, `seed_root`,
activation values). This makes the digest LANEEXEC's
`x-launch-inputs.config_binding` requires, without PLACECLI changing when
LANEEXEC lands. Any other unknown top-level member refuses at load.

### 4.2 Reservation journal and lifecycle hooks

SL-1 journals every reservation, same-request response, release tombstone and
`(client, reservation_id)` barrier in the selected client's inventory. LANEEXEC
reads the stored `Reservation` by `reservation_id` for its echo comparison and
adds its exec-claim record and release/reap hooks there. SL-1 keeps one module
seam for that, `PlacementLifecycle`, so LANEEXEC extends rather than forks it.

### 4.3 Bridge

`ForwardTcpUnixBridge.open(reservation, exposure, *, cancelled) -> BridgeHandle`
and `close(handle, *, cancelled) -> LeaseFlags` are consumed unchanged by
LANEEXEC's `x-bridge.attach` (its consumed gate IF-XR-3).

## 5. Preserved boundaries

- Live routes stay disabled: `_NONLOCAL_EXECUTION_DRIVER` stays false, no
  production OpenShell backend is registered, `policies.json` stays
  `pending_qualification`, E2B stays disabled.
- No seat jail, seat caps, `seat_uid` or jailed Codex code is edited. `leg`,
  `qualification` and `implementation` admit only the injected trusted SEATS
  route target.
- Every helper the phase launches uses `seat_uid.trusted_module_argv`; the
  `agent-harness-placement` console script is an installed entry, and the legacy
  `phase-loop placement reap` delegates in process.
- PLACECLI's receipt pins no shared or frequently changed file (agent-harness#1955;
  ownership map receipt rule).
- The agy catalog is unrelated to placement and is not consumed.

## 6. Verification groups

Paths are relative to `phase-loop-runtime/`. Groups run on `ai` under the
admission lock and PSI gates, serially, `timeout 900`, no xdist, no cache
provider; dev0 runs plan validators only.

- V0: `tests/test_placement_process_contract.py`
- V1: `tests/test_placement_lifecycle_process.py`, `tests/test_sandbox_placement.py`, `tests/test_sandbox_policy.py`, `tests/test_placement_driver.py`, `tests/test_placement_ladder_model.py`, `tests/test_placement_lease.py`, `tests/test_openshell_backend.py`, `tests/test_openshell_channel.py`, `tests/test_openshell_journal.py`, `tests/test_openshell_transport.py`, `tests/test_advisor_board_config.py`
- V2: `tests/test_placement_bridge.py`, `tests/test_openshell_worker.py`
- V3: `tests/test_placement_cli.py`, `tests/test_placecli_receipt.py`, `tests/test_agent_cli_scratch_inventory_1147.py`, `tests/test_seat_launch_helpers_trusted.py`, `tests/test_seat_reference_inventory.py`
- V4: build an installed wheel the way `scripts/gate_a_cleanroom.sh` does, then run V0 and V3 against it; tests that read repo-only files skip when those files are absent.
