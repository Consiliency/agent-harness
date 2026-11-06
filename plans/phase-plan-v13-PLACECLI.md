---
phase_loop_plan_version: 1
phase: PLACECLI
roadmap: specs/phase-plans-v13.md
roadmap_sha256: eb15634609183e5d16d098892f5be8c236123cc1b3d955205b920a262bb7acfd
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_process_contract.py tests/test_placement_lifecycle_process.py tests/test_placement_bridge.py tests/test_placement_cli.py tests/test_sandbox_placement.py tests/test_placement_driver.py tests/test_placement_ladder_model.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_openshell_journal.py tests/test_openshell_transport.py tests/test_openshell_worker.py tests/test_advisor_board_config.py tests/test_sandbox_policy.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_gate_a_wheel_isolation.py"]
---

# PLACECLI: Placement process boundary and lifecycle

## Context

This is the first phase of the owner-priority v13 placement consolidation. It
implements the process boundary that agent-toolkit can consume without importing
agent-harness Python. The frozen input is
`plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256
`cb5870a71ef607345cc28262d77b40f7209a8c770eab22b55917afd3aa29566c`.
The artifact fixes command transport, exact message shapes, code vocabularies,
policy names, two identities/inventories, local-headroom defaults, bridge
descriptor and lifecycle semantics. It is read-only during execution; a needed
contract change routes back through a roadmap/artifact amendment.

Implementation has a non-human work-start gate: v12 IF-0-WORKER-1 and
IF-0-JOURNAL-1 must be implemented and landed, and their final APIs must be
reconciled with this plan. Until then PLACECLI is planned but blocked with
`blocker_class=upstream_phase_unmet`, `human_required=false`. This is not a live
activation gate and does not prevent black-box fixture preparation in a later
authorized execution; the phase still lands as one coherent disabled feature.

The process module is `python -I -m phase_loop_runtime.placement_cli
reserve|release|reap`. It reads one bounded JSON object from stdin and writes one
response object to stdout. The existing human-facing `phase-loop placement reap`
delegates to the same lifecycle rather than keeping a second reaper. Requests do
not carry owner, client, target lists, certificate selection or policy JSON.

## External Inputs

- Frozen process artifact and hashes: the exact v13 artifact named above.
- Existing production placement BAML, driver, policy vectors and driver defaults
  at the hashes embedded in that artifact.
- Consiliency/consiliency-contract admitted launch envelope v2 and run-status
  bytes at the immutable revision pinned in the frozen process artifact.
- agent-toolkit's L0–L9 fixture corpus, fake coordinator/CLI/TLS behavior and shim
  invocation are black-box inputs. Vendor only language-neutral request/response
  cases needed for repeatable offline tests; do not copy its production client.

No future implementation SHA, commit count, PR topology or live run identity is
pinned. Any changed external bytes require reviewed repinning before execution.

## Interface Freeze Gates

- [ ] IF-0-PLACECLI-1 — `placement_process_contract.py` loads the packaged v1
  schema, verifies byte equality with the frozen planning artifact in source-tree
  checks, and exposes strict parse/validate/encode functions plus immutable typed
  request/response records. `placement_cli.py` accepts only the artifact's three
  verbs, stdin/stdout rules and exit classes. Unknown input refuses before any
  configuration, capacity or lease effect.
- [ ] IF-0-PLACECLI-2 — One lifecycle service resolves named policy vectors and
  trusted ranks, maps workload to the correct OU/inventory, reserves/releases or
  reaps authoritative resources, publishes the frozen local thresholds, and owns
  a reservation-scoped ForwardTcp-to-0600-Unix bridge for remote `pi-runner`.
  Uncertain cleanup blocks overflow and survives restart.

Production signatures freeze at implementation review as:

```text
decode_request(verb: str, raw: bytes) -> PlacementRequestMessage
encode_response(message: PlacementResponseMessage) -> bytes
PlacementLifecycle.reserve(request, *, cancelled) -> ReserveResponse
PlacementLifecycle.release(request, *, cancelled) -> ReleaseResponse
PlacementLifecycle.reap(request, *, cancelled) -> ReapResponse
ForwardTcpUnixBridge.open(reservation, exposure, *, cancelled) -> BridgeHandle
ForwardTcpUnixBridge.close(handle, *, cancelled) -> LeaseFlags
placement_cli.main(argv: Sequence[str] | None = None) -> int
```

Names may not be changed in execution without amending this plan. Concrete record
fields come only from the frozen JSON schema. Underlying exceptions translate to
closed codes `from None`; input values, paths other than the bridge socket handoff,
policy bodies and credential material never enter messages or diagnostics.

## Lane Index & Dependencies

SL-0 — Packaged process contract and strict codec
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Reservation, identity and two-inventory lifecycle
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: no

SL-2 — ForwardTcp bridge and toolkit black-box fixtures
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Process CLI, documentation and evidence reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Packaged process contract and strict codec

- **Scope**: Install the frozen schema as package data and expose a side-effect-free strict JSON codec/type boundary.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `phase-loop-runtime/tests/test_placement_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **Interfaces provided**: `decode_request`, `encode_response`, immutable request/response records, packaged process-v1 bytes
- **Interfaces consumed**: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, Python JSON, `jsonschema` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add valid examples for all six message families and path-entered negatives for every closed enum/conditional. Exercise duplicate keys, trailing bytes, invalid UTF-8, the 64 KiB bound, non-finite/unsafe numbers, nested/oversized caller context, unknown fields, bridge permissions, identity/workload mismatch and admitted/non-admitted reservation conditionals. Compare the packaged schema bytes with the frozen artifact and test the installed wheel path.
  - impl: Copy the reviewed artifact byte-for-byte into package data, load it through `importlib.resources`, check its built-in pins, and implement strict decode/encode without accepting already-parsed objects. Capture bytes once; validate and construct records from that same capture. Keep schema diagnostics closed and value-free.
  - verify: Run V0 and the installed-wheel portion of V4. A mutation that changes the packaged schema while updating only a test expectation must still fail the frozen-artifact byte comparison.

### SL-1 — Reservation, identity and two-inventory lifecycle

- **Scope**: Adapt the existing ranked walk and OpenShell lease machinery into one restart-safe process lifecycle while preserving local reservation authority.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`, `phase-loop-runtime/tests/test_placement_lifecycle_process.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`, `phase-loop-runtime/tests/test_placement_driver.py`, `phase-loop-runtime/tests/test_placement_ladder_model.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`, `phase-loop-runtime/tests/test_openshell_channel.py`, `phase-loop-runtime/tests/test_openshell_journal.py`, `phase-loop-runtime/tests/test_openshell_transport.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`
- **Interfaces provided**: `PlacementLifecycle`, trusted target policy, local reservation adapter, workload-to-client mapping, two-inventory reap
- **Interfaces consumed**: `PlacementRequestMessage`, `PlacementResponseMessage` (SL-0); `sandbox_placement` walk, coordinator wire, lease flags, operator configuration (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Drive `ai` capacity, local authoritative admission and disabled E2B through production constructors. Pin 1 GiB/100%/4/5 s threshold semantics and stale/unknown=`at_capacity`. Cover a capacity response as a new pre-envelope admission, then forbid any post-admission fallback. Exercise lost replies before/after send, late local handles, release barriers, duplicate binding, restart recovery, idempotent release/reap and cross-inventory isolation. Assert `pi-runner` selects OU/inventory `agent-toolkit`; other workloads select `agent-harness`; request data cannot override either.
  - impl: Add `pi-runner` to the closed placement workload only through the lifecycle mapping. Resolve policy names to the exact pinned vector and digest. Bind reservations to target/transport/config/image/policy. Store enough metadata to release after caller death without storing credentials or caller-context authority. Reuse the existing answer bound and fail-closed release semantics; do not fork a second walk.
  - verify: Run V1. Mutation controls bypass the fresh-headroom recheck, merge inventories, relabel timeout as unreachable and advance after unconfirmed release; each must fail through a production path.

### SL-2 — ForwardTcp bridge and toolkit black-box fixtures

- **Scope**: Provide the generic reservation-scoped socket bridge and a language-neutral differential corpus for the toolkit shim.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_bridge.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`, `phase-loop-runtime/tests/test_placement_bridge.py`, `phase-loop-runtime/tests/test_openshell_worker.py`, `phase-loop-runtime/tests/_openshell_channel_server.py`, `phase-loop-runtime/tests/fixtures/placement-cli/**`
- **Interfaces provided**: `ForwardTcpUnixBridge`, bridge handle/evidence, toolkit black-box L0–L9 cases
- **Interfaces consumed**: reservation and bridge records (SL-0); OpenShell service exposure, channel seams, toolkit fixture behavior (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Port only request/response scenario vectors for L0–L9, unavailable/deadline/lost reply, snapshot expiry and duplicate binding. Start the real CLI as a subprocess against the fake coordinator; never import its internals into the shim test. Prove one 0700 directory and 0600 Unix socket per reservation, no public listener, peer teardown on release/cancel, bounded setup, stale-socket refusal, and cleanup-pending retention. A fake that branches on case ID is forbidden.
  - impl: Bridge exactly the admitted ForwardTcp service to one Unix socket and return the frozen descriptor. Use trusted service exposure, not request-supplied host/port. Bind lifetime to reservation release/reap, scrub descriptors/env, and record metadata-only bridge evidence. Keep toolkit link framing, relay and credentials outside this repository.
  - verify: Run V2. Negative controls weaken directory/socket mode, reuse a socket, swap service exposure and drop teardown; production-path tests must fail.

### SL-3 — Process CLI, documentation and evidence reducer

- **Scope**: Wire the producers into the isolated process module, delegate the legacy maintenance entry point, and publish thresholds/compatibility evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_placement_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/README.md`, `docs/placement-process-cli.md`, `plans/evidence/placement/PLACECLI.md`, `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`
- **Interfaces provided**: `python -I -m phase_loop_runtime.placement_cli`, delegated `phase-loop placement reap`, public headroom table, IF-0-PLACECLI-1/2 receipt
- **Interfaces consumed**: `decode_request`, `encode_response` (SL-0); `PlacementLifecycle` (SL-1); `ForwardTcpUnixBridge`, toolkit fixture results (SL-2)
- **Parallel-safe**: no
- **Tasks**:
  - test: Spawn all verbs with an isolated import path, controlled HOME/config and bounded stdin/stdout. Assert exact exit classes, one JSON line, empty ordinary stderr, zero effects on invalid input and no secret/exception/path sentinel leakage. Verify old reap reaches the same service. Update launch/scratch/reference inventories for every new subprocess, file and dynamic import; helpers use trusted module argv. Bind the receipt to actual V0–V4 runner results and artifact hashes.
  - impl: Assemble the CLI without reading ambient owner/client/target settings from request fields. Publish JSON examples, code-stage separation, two inventories, ForwardTcp boundary and exact local thresholds. State that live routes/E2B remain disabled and toolkit cutover waits on all three conditions. Add one Unreleased changelog entry; use `.doc-decisions.json` only if the docs audit requires an explicit no-change decision for another release surface. Record actual outcomes in the PLACECLI evidence artifact and append lifecycle metadata to the existing manifest entry; do not hand-edit the frozen input.
  - verify: Run V3, then V4 and the effective suite. The reducer depends on all producers and refuses missing/skipped-only results, stale hashes, unqualified policy status or any live-activation claim.

## Verification

Before each command, check `uptime` and `/proc/pressure/io`; stop if the one-minute
load is above 16 or IO full avg60 is above 10%. Run serially with no cache and no
xdist workers. V0–V4 are execution-time commands, not run by this planning PR.

- V0: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_process_contract.py`
- V1: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_lifecycle_process.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_placement_driver.py tests/test_placement_ladder_model.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_openshell_channel.py tests/test_openshell_journal.py tests/test_openshell_transport.py tests/test_advisor_board_config.py`
- V2: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_bridge.py tests/test_openshell_worker.py`
- V3: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V4: build an installed wheel in Gate-A shape, run V0 and V3 against that wheel, then run `python -m json.tool plans/evidence/placement/PLACECLI.md` only if the receipt is JSON; otherwise validate its closed receipt parser. The phase plan must be amended with the exact installed command before execution if the landed worker packaging changes this shape.

At execution preflight, validate V0–V4 and the frontmatter suite through
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple failure reporting and flag proof cost when one node exceeds roughly five
minutes. Full-suite and Gate A execution stay with hosted CI under sprint policy.

## Acceptance Criteria

- [ ] EC-PLACECLI-1 — proven by V0 and V3 against `decode_request`, `placement_cli.main` and isolated subprocess controls; falsified by a path-entered malformed request reaching SL-1's injected capacity-effect counter.
- [ ] EC-PLACECLI-2 — proven by `V1` against production lifecycle and reservation binding cases; falsified by a path-entered post-admission target substitution or request-supplied target-policy mutation.
- [ ] EC-PLACECLI-3 — proven by V1 restart, uncertain cleanup and cross-inventory cases; falsified by a path-entered late-handle/lost-reply mutation allowing another admission before `barrier_confirmed`.
- [ ] EC-PLACECLI-4 — proven by `V2` plus the unchanged black-box fixture driver in `V3`; falsified by a path-entered mode/listener/service-swap mutation or a shim importing agent-harness modules.
- [ ] EC-PLACECLI-5 — proven by `V1` threshold boundaries and `V3` documentation/disabled-config receipt; falsified by a path-entered threshold-source divergence or live adapter reachable under the shipped default.

## Execution Notes

Owned paths are disjoint. SL-3 is the only reducer and depends on all producers.
SL-0 owns the package-data construction site; existing package-data globs already
cover `contracts/placement/**`, so `pyproject.toml` and `MANIFEST.in` stay untouched
unless V4 disproves that assumption, in which case amend ownership before editing.
No `__init__.py` export is required for module invocation. No generated skill tree,
lockfile, policy vector or BAML source changes in this phase. If the landed v12
worker adds a shared CLI registry or companion snapshots, reconcile and amend the
complete ownership list before execution.

Next phase: PLACECLI — blocked pending landed v12 IF-0-WORKER-1 and
IF-0-JOURNAL-1. Next command: none until those upstream gates are verified; then
`codex-execute-phase plans/phase-plan-v13-PLACECLI.md` under separate execution
authority.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `docs/placement-process-cli.md`, placement contract documentation
- evidence paths: `plans/evidence/placement/PLACECLI.md`
- redaction posture: `metadata_only`
- downstream handling: `none`
