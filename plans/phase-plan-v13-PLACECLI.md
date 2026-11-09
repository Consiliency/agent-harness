---
phase_loop_plan_version: 1
phase: PLACECLI
roadmap: specs/phase-plans-v13.md
roadmap_sha256: a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_placement_process_contract.py tests/test_placement_lifecycle_process.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_placement_driver.py tests/test_placement_ladder_model.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_openshell_channel.py tests/test_openshell_journal.py tests/test_openshell_transport.py tests/test_advisor_board_config.py tests/test_placement_bridge.py tests/test_openshell_worker.py tests/test_placement_cli.py tests/test_placecli_receipt.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_gate_a_wheel_isolation.py"]
---

# PLACECLI: Placement process boundary and lifecycle (re-plan on landed code)

## Context

Owner decision 2026-11-09: PLACECLI is re-planned on the landed code and keeps
its roadmap goals, EC-PLACECLI-1 to EC-PLACECLI-5. This plan replaces the
previous PLACECLI plan rather than amending it; the supersession is an appended
`replan` lifecycle event on the existing `plans/manifest.json` row
`v13-PLACECLI`, which keeps every earlier field and seal.

The roadmap's work-start gate EXT-WORKER (v12 IF-0-WORKER-1 and IF-0-JOURNAL-1)
has landed, and PLACECLI calls neither the worker nor the journal, so no gate
remains. Per-seat caps (agent-harness#1895) and the jailed Codex seat
(agent-harness#1916) landed in 0.7.31; PLACECLI consumes the caps readiness and
never touches the seat jail. Nothing of PLACECLI itself has landed.

Frozen inputs, read before building:

- `plans/artifacts/v13-PLACECLI-contract-v1.schema.json` with erratum
  PLACECLI-v1-errata-1, unchanged at its roadmap pin. It fixes the console
  entry, `--client` selection, version response, message shapes, code
  vocabularies, provider and egress rules, identities and inventories, headroom
  defaults, bridge descriptor and lifecycle semantics.
- `plans/artifacts/v13-PLACECLI-landed-binding.md`: the landed-interface table
  with every touchpoint at `file:line` (§2), the STOP decisions (§3), the
  cross-phase interfaces LANEEXEC consumes (§4), preserved boundaries (§5) and the
  verification groups (§6).
- `plans/artifacts/v12-v13-replan-ownership.md`: the ownership map shared with
  CLOSEOUT and LANEEXEC, and the integration order.

The process boundary is `agent-harness-placement --client
agent-toolkit|agent-harness reserve|release|reap|version`. PLACECLI stops at
reservation, release/reap and bridge construction; LANEEXEC owns launch. Model
choice stays inside each client harness and provider credentials never enter
placement or a sandbox.

**STOP decisions** (each recorded with its reason in the binding artifact §3):

| Item | Decision |
| --- | --- |
| P-S1 | Reuse the whole landed `seat_resource_caps.v1` record. `load_caps` and `readiness_code` run at reservation time and refuse `sandbox_placement_capability_unmet`; `seat_caps_sha256` enters `config_sha256`. Per-path readback is LANEEXEC's, at launch. Sweep recommendation adopted. |
| P-S2 | No byte change and no repin. The protocol artifact stays at its pin; the LANEEXEC artifact on main already spells the v2 egress grant as bare hex and governs it. This deviates from the sweep (hold and repin) because the defect is in a consumer instruction, not PLACECLI's wire, and a repin would cascade to the roadmap, SEATS REMOTE and agent-toolkit with no wire benefit. |
| X-S1 | Serial integration CLOSEOUT → PLACECLI → LANEEXEC. PLACECLI may build concurrently with CLOSEOUT and rebases its shared-file edits additively. Adopted. |

## Interface Freeze Gates

- [ ] IF-0-PLACECLI-1 — `placement_process_contract.py` loads the packaged copy
  of the frozen schema (byte-equal to the planning artifact in source-tree
  checks) and exposes strict decode/encode plus immutable typed records. The
  installed `agent-harness-placement` script accepts only the required
  `--client` flag, the four verbs, the stdin/stdout rules and the exit classes;
  `version` returns the packaged schema digest, the selected `config_sha256` and
  the effective headroom thresholds. Unknown or unpermitted providers refuse
  `sandbox_placement_provider_refused` before any configuration, capacity or
  lease effect.
- [ ] IF-0-PLACECLI-2 — One `PlacementLifecycle` resolves named policy vectors,
  operator-allowlisted provider endpoint sets and trusted workload rank policy;
  maps each target to its OU and inventory; reserves, releases or reaps only the
  selected client's resources; applies host headroom thresholds and the landed
  caps readiness before any local reservation (P-S1); records `providers` and the
  canonical `egress_sha256`; and owns the reservation-scoped credential-proxy
  ForwardTcp-to-0600-Unix bridge. Exit-20 state is scoped to one `(client,
  reservation)` and survives restart.

Production signatures, which execution may not rename without a plan change:

```text
decode_request(verb: str, raw: bytes) -> PlacementRequestMessage
encode_response(message: PlacementResponseMessage) -> bytes
PlacementLifecycle.reserve(request, *, cancelled) -> ReserveResponse
PlacementLifecycle.release(request, *, cancelled) -> ReleaseResponse
PlacementLifecycle.reap(request, *, cancelled) -> ReapResponse
ForwardTcpUnixBridge.open(reservation, exposure, *, cancelled) -> BridgeHandle
ForwardTcpUnixBridge.close(handle, *, cancelled) -> LeaseFlags
placement_cli.main(argv: Sequence[str] | None = None) -> int
placement_cli.version_response(client_config) -> VersionResponse
```

Record fields come only from the frozen schema. Exceptions translate to closed
codes `from None`; input values, policy bodies, credentials and paths other than
the bridge socket hand-off never enter messages or diagnostics. The whole-config
`config_sha256` rule, including the uninterpreted `launch` member, is frozen in
binding §4.1 for LANEEXEC.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`
- evidence paths: `plans/evidence/placement/PLACECLI.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Lane Index & Dependencies

SL-0 — Packaged process contract and strict codec
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Reservation, identity, caps readiness and caller-scoped lifecycle
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: no

SL-2 — ForwardTcp bridge and toolkit black-box fixtures
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Process CLI, inventories, documentation and evidence reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Packaged process contract and strict codec

- **Scope**: Install the frozen schema as package data and expose a side-effect-free strict JSON codec and typed records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `phase-loop-runtime/tests/test_placement_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **Interfaces provided**: `decode_request`, `encode_response`, `PlacementRequestMessage`, `PlacementResponseMessage`, packaged process-v1 bytes
- **Interfaces consumed**: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, `jsonschema` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_placement_process_contract.py`, `tests/test_gate_a_wheel_isolation.py` | valid examples for all seven message families; path-entered negatives for every enum and conditional; required, non-empty, unique provider names and refusal of URL, hostname, model or endpoint shapes; reservation `providers` and `egress_sha256`; duplicate keys, trailing bytes, invalid UTF-8, the 64 KiB bound, non-finite or unsafe numbers, nested or oversized caller context, unknown fields; errata-1 obligation T1; packaged bytes equal the frozen artifact; installed-wheel load | `V0` |
| SL-0.2 | impl | SL-0.1 | `placement_process_contract.py`, `contracts/placement/process-v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 owned files | all SL-0 tests | `V0`; mutating the packaged bytes while updating only a test expectation still fails |

SL-0.2 copies the artifact byte-for-byte (P-S2: no byte change), loads it through
`importlib.resources`, captures input bytes once and validates and constructs
records from that capture. Byte-equality checks apply only to pins without
`runtime_equality: false`.

### SL-1 — Reservation, identity, caps readiness and caller-scoped lifecycle

- **Scope**: Adapt the ranked Pi walk and the single-target SEATS route into one restart-safe, per-client lifecycle with fail-closed local admission.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`, `phase-loop-runtime/tests/test_placement_lifecycle_process.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`, `phase-loop-runtime/tests/test_placement_driver.py`, `phase-loop-runtime/tests/test_placement_ladder_model.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`, `phase-loop-runtime/tests/test_openshell_channel.py`, `phase-loop-runtime/tests/test_openshell_journal.py`, `phase-loop-runtime/tests/test_openshell_transport.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`
- **Interfaces provided**: `PlacementLifecycle`, effective-egress resolver, whole-config `config_sha256`, caps readiness admission, workload-to-client mapping, caller-scoped reap
- **Interfaces consumed**: `PlacementRequestMessage`, `PlacementResponseMessage`, `place` (pre-existing), `open_lease` (pre-existing), `seat_resource_caps.load_caps` (pre-existing), `seat_resource_caps.readiness_code` (pre-existing), `seat_resource_caps.caps_sha256` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | SL-1 test files | `pi-runner` through `ai` capacity, an actually reserved local slot and disabled E2B on the existing walk; `leg`, `qualification` and `implementation` only through one injected SEATS target, refusing before any probe when it is missing; provider refusal at exit 10 with zero capacity, coordinator and lease calls; effective egress exactly baseline plus declared endpoints, with order, duplicate, undeclared-endpoint and mapping mutations failing; generic probe receipt on owned hosts and per-provider OD-7 on third-party targets; default and overridden headroom thresholds with every exclusive boundary, stale or unknown dimensions and missing or malformed PSI as `at_capacity`; injected caps loader raising and readiness returning `seat_resource_caps_unavailable` each refuse `sandbox_placement_capability_unmet` before a local reservation; changing thresholds, provider mappings, the caps record or the `launch` member changes `config_sha256`; local Pi on `minimal-without-app` with `bridge: null` holding a live-sandbox slot; reserve budget, lost replies, late handles, restart, errata-1 replay R1–R3, release echo mismatch returning `rejected`, repeat release; OU and inventory per workload, `(client, reservation)` barriers and caller-scoped reap | `V1` |
| SL-1.2 | impl | SL-1.1 | SL-1 source files | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | all SL-1 tests | `V1`; mutations that add undeclared egress, bypass provider, OD-7, headroom or caps readiness checks, merge inventories, relabel timeout as unreachable or advance after an unconfirmed release each fail through a production path |

SL-1.2 implements binding §3 P-S1 and §4.1–§4.2 with the protocol artifact's
semantics. Loader and readiness callables are injected at the lifecycle
constructor with the landed functions as defaults. `_NONLOCAL_EXECUTION_DRIVER`
stays false, no production OpenShell backend is registered and `policies.json`
stays `pending_qualification`.

### SL-2 — ForwardTcp bridge and toolkit black-box fixtures

- **Scope**: Provide the reservation-scoped credential-proxy socket bridge and a language-neutral differential corpus for the toolkit shim.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_bridge.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`, `phase-loop-runtime/tests/test_placement_bridge.py`, `phase-loop-runtime/tests/test_openshell_worker.py`, `phase-loop-runtime/tests/_openshell_channel_server.py`, `phase-loop-runtime/tests/fixtures/placement-cli/**`
- **Interfaces provided**: `ForwardTcpUnixBridge`, `BridgeHandle`, toolkit black-box L0–L9 cases
- **Interfaces consumed**: `PlacementRequestMessage`, `PlacementResponseMessage`, `MTLSConfig` (pre-existing), `StockExecChannel` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | SL-2 test files and fixtures | request/response vectors for L0–L9, unavailable, deadline, lost reply, snapshot expiry and duplicate binding, driven through the real CLI as a subprocess against the fake coordinator; a language-neutral fake of the pinned `cred-proxy.mjs` shows model bytes crossing the bridge while placeholders stay guest-side and no key or token reaches sandbox input, config, environment, messages, logs or evidence; one 0700 directory and 0600 socket per remote Pi or `leg` reservation, no public listener, teardown on release and cancel, stale-socket refusal and `bridge: null` locally; a fake that branches on case ID is forbidden | `V2` |
| SL-2.2 | impl | SL-2.1 | `placement_bridge.py`, `openshell_worker.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests | `V2`; weakening modes, reusing a socket, swapping the service exposure and dropping teardown each fail |

### SL-3 — Process CLI, inventories, documentation and evidence reducer

- **Scope**: Wire the producers into the installed process entry, delegate the legacy reaper, record inventories and publish documentation and evidence.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_placement_cli.py`, `phase-loop-runtime/tests/test_placecli_receipt.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/README.md`, `docs/placement-process-cli.md`, `plans/evidence/placement/PLACECLI.md`, `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`
- **Interfaces provided**: `agent-harness-placement`, `placement_cli.main`, `placement_cli.version_response`, client-explicit `phase-loop placement reap`, IF-0-PLACECLI-1/2 receipt
- **Interfaces consumed**: `decode_request`, `encode_response`, `PlacementLifecycle`, `ForwardTcpUnixBridge`, toolkit black-box L0–L9 cases
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `tests/test_placement_cli.py`, `tests/test_placecli_receipt.py`, inventory tests | installed console script and module path with isolated imports, controlled HOME and config and hostile selection variables; required `--client`; client/workload mismatch refused before effects; exact exit classes, one JSON line per schema-valid outcome, exit 70 with stdout absent for schema-invalid input (T2), a client pinned to pre-erratum bytes refusing on `version` (T3); empty ordinary stderr and no sentinel leakage; `version` reads empty stdin and reports the schema digest, `config_sha256` and thresholds; the legacy reaper reaches the same service with an explicit client; inventory rows for every new subprocess, file and dynamic import, helpers via `seat_uid.trusted_module_argv`; the receipt parser refuses missing or skipped-only results, stale hashes, a shared-file pin or a live-activation claim | `V3` |
| SL-3.2 | impl | SL-3.1 | `placement_cli.py`, `cli.py`, `pyproject.toml`, `uv.lock`, `tests/data/seat_launch_references.json` | — | — |
| SL-3.3 | docs | SL-3.2 | `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `CHANGELOG.md`, `.doc-decisions.json`, `plans/evidence/placement/PLACECLI.md`, `plans/manifest.json` | — | `V3` |
| SL-3.4 | verify | SL-3.3 | SL-3 owned files | all SL-3 tests | `V3`, then `V4` and the effective suite |

SL-3.2 registers the console script (no dependency change; `uv.lock` stays
byte-identical) and assembles the CLI without reading client, config or target
from environment or request. SL-3.3 documents messages, exit and flag semantics,
provider refusal and the egress-digest rule including the v2 bare-hex spelling
(P-S2), barriers, caller-scoped reap, local and remote Pi policies, the
credential-proxy boundary, the per-host defaults and fail-closed PSI and caps
readiness. It states that live routes and E2B stay disabled and toolkit cutover
waits on all three switch conditions, adds one Unreleased changelog entry,
records actual outcomes in the evidence file and appends the lifecycle event.

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-1: effort=high, reason=restart-safe lifecycle across lease journal and per-client inventories

## Execution Notes

- **Sequencing**: SL-1 and SL-2 may run in parallel after SL-0; SL-3 reduces
  all producers. No subagents or writer fanout beyond these lanes.
- **Cross-phase order**: PLACECLI merges after CLOSEOUT and before LANEEXEC
  (`plans/artifacts/v12-v13-replan-ownership.md`). Shared files are rebased
  additively; any other conflict is a STOP.
- **Single-writer files**: SL-0 owns `test_gate_a_wheel_isolation.py`; SL-3 owns
  `pyproject.toml`, `uv.lock`, the four inventory files, `README.md`,
  `CHANGELOG.md`, `.doc-decisions.json` and `plans/manifest.json`. LANEEXEC
  later edits `sandbox_placement.py`, `placement_lease.py` and
  `openshell_backend.py` after this phase lands; SL-1 keeps `PlacementLifecycle`
  as the seam it extends (binding §4.2).
- **Package data**: `contracts/placement/**` is already package data, so
  `MANIFEST.in` is untouched; V4 checks the installed wheel.
- **Known destructive changes**: none. Every lane is additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; nothing is exported from the package root.
- **Shared host**: dev0 runs plan validators only. V0–V4 run on `ai` under the
  admission lock and PSI gates, serially, `timeout 900`, no xdist, no cache.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Validator (N)**: package and changelog ownership read as release-shaped;
  this phase dispatches no tag or release.
- **STOP rule**: an unclear interface or ownership gap stops the lane and
  reports the exact plan or artifact sentence to change.

Next phase: PLACECLI — blocked: advisor-board panel review of this re-plan.
Next command: none until the panel and president return; then
`claude-execute-phase plans/phase-plan-v13-PLACECLI.md` under separate execution authority.

## Acceptance Criteria

- [ ] EC-PLACECLI-1 — proven by V0 and V3 (`tests/test_placement_process_contract.py`, `tests/test_placement_cli.py`) against `decode_request`, the installed entry and `placement_cli.main`; falsified by a malformed or provider-unpermitted request, or a hostile environment variable, entered through the installed entry and reaching SL-1's injected capacity-effect counter.
- [ ] EC-PLACECLI-2 — proven by V1 (`tests/test_placement_lifecycle_process.py`) against the production lifecycle, provider resolution, effective-egress digest and reservation binding; falsified by an undeclared endpoint, post-admission target or provider substitution, or a request-supplied target policy entered through `PlacementLifecycle.reserve`.
- [ ] EC-PLACECLI-3 — proven by V1 restart, repeat-release, per-reservation barrier and caller-scoped reap cases in `tests/test_placement_lease.py` and `tests/test_placement_lifecycle_process.py`; falsified by cross-client inventory access, a host-wide barrier, a mutated release echo returning `unknown_reservation` or `released`, or a late handle advancing the walk before `barrier_confirmed`, each entered through the production lifecycle.
- [ ] EC-PLACECLI-4 — proven by V2 (`tests/test_placement_bridge.py`) credential-proxy and transport cases plus the unchanged black-box fixture driver in V3; falsified by a credential sentinel, a mode, listener or service-swap mutation in `placement_bridge.py`, or a shim importing agent-harness modules.
- [ ] EC-PLACECLI-5 — proven by V1 (`tests/test_placement_lifecycle_process.py`, `tests/test_placement_driver.py`) local-provider allowlist, threshold boundaries, PSI failure and caps-readiness refusal cases plus the V3 version and receipt checks (`tests/test_placement_cli.py`, `tests/test_placecli_receipt.py`); falsified by a local provider bypass, a threshold-source divergence, an omitted effective threshold, permissive PSI failure, an injected caps-unavailable host admitting a local reservation, or a live adapter reachable under shipped defaults.

## Verification

Execution-time commands, none run by this planning change; group membership is
binding §6. Each runs as `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider <group files>`.

- V0: `tests/test_placement_process_contract.py`
- V1: `tests/test_placement_lifecycle_process.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_placement_driver.py tests/test_placement_ladder_model.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_openshell_channel.py tests/test_openshell_journal.py tests/test_openshell_transport.py tests/test_advisor_board_config.py`
- V2: `tests/test_placement_bridge.py tests/test_openshell_worker.py`
- V3: `tests/test_placement_cli.py tests/test_placecli_receipt.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V4: an installed wheel built the way `phase-loop-runtime/scripts/gate_a_cleanroom.sh` builds it, then V0 and V3 against that wheel.

At execution preflight validate V0–V4 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple-failure reporting and flag any node over roughly five minutes. Full
suites and Gate A stay with hosted CI under the sprint policy.
