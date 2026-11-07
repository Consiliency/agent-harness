---
phase_loop_plan_version: 1
phase: PLACECLI
roadmap: specs/phase-plans-v13.md
roadmap_sha256: 1b33da8ce3b43bf109e2a55aa3fece806aa9e0a4966eac64f23fad98ba0e05e0
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_placement_process_contract.py tests/test_placement_lifecycle_process.py tests/test_placement_bridge.py tests/test_placement_cli.py tests/test_sandbox_placement.py tests/test_placement_driver.py tests/test_placement_ladder_model.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_openshell_channel.py tests/test_openshell_journal.py tests/test_openshell_transport.py tests/test_openshell_worker.py tests/test_advisor_board_config.py tests/test_sandbox_policy.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_gate_a_wheel_isolation.py"]
---

# PLACECLI: Placement process boundary and lifecycle

## Context

This is the first phase of the owner-priority v13 placement consolidation. It
implements the process boundary that agent-toolkit can consume without importing
agent-harness Python. The frozen input is
`plans/artifacts/v13-PLACECLI-contract-v1.schema.json` with erratum
PLACECLI-v1-errata-1 (its `x-errata` member), sha256
`8b6fe858fc95894c39af8d8e091090074effb38e38acec95e71bd7b1d69576a1`.
The artifact fixes the stable console entry, required client/config flag,
version response, exact message shapes, code vocabularies, target-bound policy
and provider names, reservation egress digest, two isolated identities/inventories,
per-host local-headroom configuration and defaults, bridge descriptor and
lifecycle semantics. It is read-only during
execution; a needed contract change routes back through a roadmap/artifact
amendment.

Implementation has a non-human work-start gate: v12 IF-0-WORKER-1 and
IF-0-JOURNAL-1 must be implemented and landed, and their final APIs must be
reconciled with this plan. Until then PLACECLI is planned but blocked with
`blocker_class=upstream_phase_unmet`, `human_required=false`. This is not a live
activation gate and does not prevent black-box fixture preparation in a later
authorized execution; the phase still lands as one coherent disabled feature.

The process boundary is `agent-harness-placement --client
agent-toolkit|agent-harness reserve|release|reap|version`. The flag is required,
selects exactly one per-client operator config/certificate/inventory and is never
derived from the environment. Placement verbs read one bounded JSON object and
write one response object; `version` reads empty stdin and writes the protocol
schema SHA-256, selected config SHA-256 and effective local-headroom thresholds.
The human-facing `phase-loop
placement reap` delegates with an explicit client rather than keeping a second
reaper. Reserve requests carry a required non-empty, duplicate-free list of
provider names resolved through selected operator config; they never carry model
names, endpoints or inline egress. Requests do not carry owner, client, target
lists, certificate selection or inline policy.

PLACECLI stops at reservation, release/reap and bridge construction. LANEEXEC
owns the generic launch service for every approved client—the Pi shim,
phase-loop lanes, OpenCode, Claude and Codex—including default git-visible-plus-`.git`
masked snapshot construction/upload, policy-selected size-capped `full` mode,
admitted envelope, one restricted exec of a client-supplied fixed command,
optional bridge, status/cancel/release, caller-scoped reap and patch return.
Clients supply only an allowlisted `image_digest`, a fixed argv template per
workload or policy, a named `policy_vector`, required provider names, the snapshot
root and masks, and `caller_context`. LANEEXEC binds the reservation's
`egress_sha256` as the envelope's RFC-8785 `egress_policy_sha256` grant; model
choice remains inside the client harness.
agent-toolkit keeps only its `pi-runner` image recipe, `remote-inner` and shim;
the legacy client tracked by agent-toolkit#35 retires under the switch condition.
LANEEXEC applies the host-configured `memory.max`, `cpu.weight` and `io.weight` or
`io.max` cap in a distinct delegated cgroup for every placed LOCAL workload.
PLACECLI only proves the local target can be confined and refuses
`sandbox_placement_capability_unmet` before reservation if delegation or a
required controller is absent. The SEATS launcher owns equivalent cap application
for seat launches under roadmap requirement XREQ-SEATS-LOCAL-CGROUP-1.
Every model connection uses the requester's credential proxy. Remote Pi carries
those bytes over the reservation bridge following the roadmap-pinned
agent-toolkit `cred-proxy.mjs` reference; local placement uses the same
requester-owned proxy boundary in
process while retaining `bridge: null`. Provider keys never enter the placement
service or sandbox.

## External Inputs

- Frozen process artifact and hashes: the exact v13 artifact named above.
- Existing production placement BAML, driver, policy vectors and driver defaults
  at the hashes embedded in that artifact.
- Consiliency/consiliency-contract admitted launch envelope v2 and run-status
  bytes at the immutable revision pinned in the frozen process artifact.
- The roadmap-pinned Consiliency/agent-toolkit revision of
  `harnesses/pi/sandbox/cred-proxy.mjs` and `docs/remote-placement.md` defines the
  requester-owned proxy reference. Those files
  are design inputs, not code to copy into agent-harness.
- agent-toolkit's L0–L9 fixture corpus, fake coordinator/CLI/TLS behavior and shim
  invocation are black-box inputs. Vendor only language-neutral request/response
  cases needed for repeatable offline tests; do not copy its production client.

No future implementation SHA, commit count, PR topology or live run identity is
pinned. Any changed external bytes require reviewed repinning before execution.

## Interface Freeze Gates

- [ ] IF-0-PLACECLI-1 — `placement_process_contract.py` loads the packaged v1
  schema, verifies byte equality with the frozen planning artifact in source-tree
  checks, and exposes strict parse/validate/encode functions plus immutable typed
  request/response records. The installed `agent-harness-placement` console
  script accepts only the artifact's required `--client` flag, four subcommands,
  stdin/stdout rules and exit classes. `version` returns the packaged artifact
  digest, selected config digest and effective local-headroom thresholds. It
  requires unique provider names and rejects endpoint/model syntax. Unknown or
  client/workload/policy-unpermitted providers return
  `sandbox_placement_provider_refused` before configuration, capacity or lease
  effects; other unknown input and client/workload mismatch fail at the same seam.
- [ ] IF-0-PLACECLI-2 — One lifecycle service resolves named policy vectors and
  operator-allowlisted provider endpoint sets plus trusted workload rank policy,
  maps every target to the correct OU/inventory,
  reserves/releases or reaps only the selected client's authoritative resources,
  loads the frozen defaults or effective per-host local thresholds, verifies local
  cgroup delegation/controllers before admission, records providers plus the
  canonical effective `egress_sha256`, and owns a reservation-scoped
  credential-proxy ForwardTcp-to-0600-Unix bridge for remote `pi-runner`. Exit-20 state is scoped
  to one reservation within one client and survives restart without blocking
  independent reservations.

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
placement_cli.version_response(client_config) -> VersionResponse
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

SL-1 — Reservation, identity and caller-scoped lifecycle
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
  - test: Add valid examples for all seven message families and path-entered negatives for every closed enum/conditional. Exercise required/non-empty/unique provider names, reject URL/hostname/model/endpoint-shaped values, and require reservation `providers` plus `egress_sha256`. Also exercise duplicate keys, trailing bytes, invalid UTF-8, the 64 KiB bound, non-finite/unsafe numbers, nested/oversized caller context, unknown fields, bridge permissions, identity/workload mismatch, admitted/non-admitted reservation conditionals and the errata-1 trail conditional (obligation T1). Compare packaged schema bytes with the frozen artifact and test the installed wheel path.
  - impl: Copy the reviewed artifact byte-for-byte into package data, load it through `importlib.resources`, and check byte equality only for pins that do not set `runtime_equality` to false. The BAML, `policies.json`, envelope v2 and run-status pins stay equality checks. The `sandbox_placement.py` and driver-defaults hashes are planning baselines; SL-1 may edit those files and must keep the published headroom numbers. Implement strict decode/encode without accepting already-parsed objects. Capture bytes once; validate and construct records from that same capture. Keep schema diagnostics closed and value-free.
  - verify: Run V0 and the installed-wheel portion of V4. A mutation that changes the packaged schema while updating only a test expectation must still fail the frozen-artifact byte comparison.

### SL-1 — Reservation, identity and caller-scoped lifecycle

- **Scope**: Adapt the ranked Pi walk and single-target SEATS route into one restart-safe, per-client lifecycle while preserving local reservation authority.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`, `phase-loop-runtime/tests/test_placement_lifecycle_process.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`, `phase-loop-runtime/tests/test_placement_driver.py`, `phase-loop-runtime/tests/test_placement_ladder_model.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`, `phase-loop-runtime/tests/test_openshell_channel.py`, `phase-loop-runtime/tests/test_openshell_journal.py`, `phase-loop-runtime/tests/test_openshell_transport.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`
- **Interfaces provided**: `PlacementLifecycle`, trusted workload rank/provider policy, canonical effective-egress resolver, local reservation adapter, fail-closed local pressure/cgroup-capability admission, workload-to-client mapping, caller-scoped reap
- **Interfaces consumed**: `PlacementRequestMessage`, `PlacementResponseMessage` (SL-0); `sandbox_placement` walk, coordinator wire, lease flags, operator configuration (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Drive `pi-runner` through `ai` capacity, an actually reserved local slot and disabled E2B using the existing walk. Drive `leg`, `qualification` and `implementation` only through one trusted SEATS target and show a missing decision refuses before any probe. Reject an unknown or client/workload/policy-unpermitted provider as `sandbox_placement_provider_refused` at exit 10 with zero capacity/coordinator/lease calls. Prove canonical resolution yields exactly vector-baseline union declared-provider endpoints, the reservation records names and RFC-8785 `egress_sha256`, local uses the same allowlist, owned `ai` needs the generic probe receipt, and disabled E2B refuses if any declared provider lacks OD-7. Mutate endpoint order/duplicates, add an undeclared endpoint and change a provider mapping; digest or admission assertions must fail. At default and overridden per-host settings, exercise MemAvailable at least max(4 GiB, 10% of total RAM), load per online CPU strictly below 70%, IO `full avg10` and memory `some avg10` strictly below 10%, fewer than four live sandboxes and observation age at most 5 s. Stale/unknown dimensions and missing, unreadable or malformed PSI are `at_capacity`; each exclusive boundary refuses. Prove `version` returns the effective values and changing them changes `config_sha256`. Prove missing cgroup delegation or a required cpu/memory/io controller refuses `sandbox_placement_capability_unmet` before a local reservation and cannot fall through to uncapped execution. Prove local Pi resolves `minimal-without-app`, returns `bridge: null` and holds a live-sandbox slot. Cover a 900000 ms reserve budget, capacity as a new pre-envelope admission, no post-admission fallback, lost replies, late handles, restart, same-request retry including the errata-1 replay obligations R1–R3 (`reserve_replay`), mutated release echo returning `rejected` at exit 10 with the lease held, and repeat release. Assert every Pi target uses OU/inventory `agent-toolkit`, seats use `agent-harness`, exit 20 blocks only its `(client, reservation)` and caller-scoped reap cannot observe the other inventory.
  - impl: Add `pi-runner` only through the lifecycle mapping. Keep one walk state machine and select trusted rank config from the frozen workload rule; seats consume one preselected target without ranking. Resolve provider names only through the selected operator config's allowlist, bind its mapping into `config_sha256`, form the exact baseline-plus-declared-provider grant and hash its sorted/deduplicated RFC-8785 form. Refuse provider failures before any admission effect; require generic owned-host probe coverage and per-provider OD-7 for a third-party attempt. Resolve effective thresholds from the selected host's operator configuration, default them from the frozen artifact and bind them into canonical `config_sha256`. Read one fresh observation from `/proc/pressure/io`, `/proc/pressure/memory`, load, memory and live-sandbox accounting; fail closed on every stale, unknown or unreadable dimension. Verify cgroup delegation and required controllers before local admission; LANEEXEC, not this phase, creates the per-reservation cgroup and applies caps. Resolve `valid` policy names while `pending_qualification` still refuses live coordinator, image-pull and E2B effects. Bind remote Pi to `full-remote-pi-runner` and local Pi to `minimal-without-app`; bind reservations to target, transport, config, image, policy, providers, egress digest and rank policy. Journal same-request responses and release tombstones so release repeats return `released` or `unknown_reservation` without blocking admission. Key uncertain barriers by selected client and reservation/request, never host. Reap only the `--client` inventory in deterministic journal order. Keep `_NONLOCAL_EXECUTION_DRIVER` false, register no production OpenShell backend and leave `policies.json` at `pending_qualification`. Treat a mismatched release echo as state `rejected`, code `sandbox_placement_refused`, exit 10, with the stored lease and flags unchanged and no barrier armed.
  - verify: Run V1. Mutation controls add undeclared egress, bypass provider/OD-7 or fresh-headroom checks, merge inventories, relabel timeout as unreachable and advance after unconfirmed release; each must fail through a production path.

### SL-2 — ForwardTcp bridge and toolkit black-box fixtures

- **Scope**: Provide the generic reservation-scoped credential-proxy socket bridge and a language-neutral differential corpus for the toolkit shim.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/placement_bridge.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`, `phase-loop-runtime/tests/test_placement_bridge.py`, `phase-loop-runtime/tests/test_openshell_worker.py`, `phase-loop-runtime/tests/_openshell_channel_server.py`, `phase-loop-runtime/tests/fixtures/placement-cli/**`
- **Interfaces provided**: `ForwardTcpUnixBridge`, bridge handle/evidence, toolkit black-box L0–L9 cases
- **Interfaces consumed**: reservation and bridge records (SL-0); OpenShell service exposure, channel seams, toolkit fixture behavior (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Port only request/response scenario vectors for L0–L9, unavailable/deadline/lost reply, snapshot expiry and duplicate binding. Start the real CLI as a subprocess against the fake coordinator; never import its internals into the shim test. Against a language-neutral fake of the roadmap-pinned agent-toolkit `cred-proxy.mjs`, prove declared-provider model bytes cross the remote bridge while placeholder credentials remain guest-side and no provider key/token appears in sandbox input, placement config, environment, messages, logs or evidence. Prove one 0700 directory and 0600 Unix socket per remote Pi reservation, no public listener, peer teardown on release/cancel, bounded setup, stale-socket refusal, cleanup-pending retention, and `bridge: null` for local Pi and local seats. Prove a `leg` reservation on `openshell` receives exactly one such bridge to the requester's credential proxy. A fake that branches on case ID is forbidden.
  - impl: Bridge exactly the admitted ForwardTcp service to one Unix socket and return the frozen descriptor. Use trusted service exposure, not request-supplied host/port. Carry opaque model connection bytes to the requester-owned credential proxy; never resolve or hold a provider credential in placement. Bind lifetime to reservation release/reap, scrub descriptors/env, and record metadata-only bridge evidence. Keep agent-toolkit's Pi-specific `cred-proxy.mjs`, `remote-inner` and shim outside this repository; OpenCode and other clients retain their own compatible credential proxy.
  - verify: Run V2. Negative controls weaken directory/socket mode, reuse a socket, swap service exposure and drop teardown; production-path tests must fail.

### SL-3 — Process CLI, documentation and evidence reducer

- **Scope**: Wire the producers into the isolated process module, delegate the legacy maintenance entry point, and publish thresholds/compatibility evidence.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_placement_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/README.md`, `docs/placement-process-cli.md`, `plans/evidence/placement/PLACECLI.md`, `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`
- **Interfaces provided**: `agent-harness-placement --client … reserve|release|reap|version`, delegated client-explicit `phase-loop placement reap`, public headroom table, IF-0-PLACECLI-1/2 receipt
- **Interfaces consumed**: `decode_request`, `encode_response` (SL-0); `PlacementLifecycle` (SL-1); `ForwardTcpUnixBridge`, toolkit fixture results (SL-2)
- **Parallel-safe**: no
- **Tasks**:
  - test: Spawn the installed console script and module path with an isolated import path, controlled HOME/config and hostile client-selection environment variables. Require `--client`, reject client/workload mismatch before effects, and compare both paths. Assert exact exit classes, one JSON line for every schema-valid outcome, exit 70 with stdout absent for schema-invalid input (errata-1 obligation T2), empty ordinary stderr, zero effects on invalid input and no secret/exception/path sentinel leakage. Verify `version` reads empty stdin and reports the packaged protocol schema SHA-256, selected config SHA-256 and effective local-headroom thresholds. Verify legacy reap reaches the same service with an explicit client and returns exactly that inventory. Update launch/scratch/reference inventories for every new subprocess, file and dynamic import; bind the receipt to actual V0–V4 results and artifact hashes.
  - impl: Register the stable `agent-harness-placement` console script and assemble the CLI without reading client/config/target settings from environment or request fields. Compute `version` from the installed schema bytes and canonical selected host config, including its effective headroom values. Publish JSON examples, exit/flag semantics, provider refusal and egress-digest rules, per-reservation barriers, caller-scoped reap, target-bound local/remote Pi policies, credential-proxy ForwardTcp boundary and exact per-host defaults/fail-closed PSI semantics. State that model selection stays with each harness, provider credentials never enter placement/sandbox, live routes/E2B remain disabled and toolkit cutover waits on all three conditions. Add one Unreleased changelog entry; record actual outcomes in the PLACECLI evidence artifact and append lifecycle metadata to the existing manifest entry without editing the frozen input.
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

- [ ] EC-PLACECLI-1 — proven by V0 and V3 against `decode_request`, the installed `agent-harness-placement` entry, `placement_cli.main`, provider syntax/refusal, version/client-selection cases and isolated subprocess controls; falsified by a path-entered malformed/provider-unpermitted request or hostile environment reaching SL-1's injected capacity-effect counter.
- [ ] EC-PLACECLI-2 — proven by `V1` against production lifecycle, provider resolution/effective-egress digest and reservation binding cases; falsified by a path-entered undeclared endpoint, post-admission target/provider substitution or request-supplied target-policy mutation.
- [ ] EC-PLACECLI-3 — proven by V1 restart, repeat-release, per-reservation barrier and caller-scoped reap cases; falsified by cross-client inventory access, host/client-wide blocking, a mutated release echo returning `unknown_reservation` or `released`, or a path-entered late-handle mutation advancing the same reserve walk before `barrier_confirmed`.
- [ ] EC-PLACECLI-4 — proven by `V2` credential-proxy secrecy/transport cases plus the unchanged black-box fixture driver in `V3`; falsified by a path-entered credential, mode/listener/service-swap mutation or a shim importing agent-harness modules.
- [ ] EC-PLACECLI-5 — proven by `V1` local-provider allowlist, default/override boundaries, PSI failure and cgroup-capability refusal cases plus `V3` version/documentation/disabled-config receipt; falsified by local provider bypass, a path-entered threshold-source divergence, omitted effective threshold, permissive PSI failure, uncapped local path or live adapter reachable under the shipped default.

## Execution Notes

Owned paths are disjoint. SL-3 is the only reducer and depends on all producers.
SL-0 owns the package-data construction site; existing package-data globs already
cover `contracts/placement/**`, so `MANIFEST.in` stays untouched unless V4
disproves that assumption. SL-3 owns `pyproject.toml` for the console entry;
console-script metadata should not change dependencies, so SL-3 owns `uv.lock` but
keeps it byte-identical when the lock check agrees; V4 checks the installed wheel.
No `__init__.py` export is required. No generated skill tree, policy vector or BAML
source changes in this phase. If landed v12
worker adds a shared CLI registry or companion snapshots, reconcile and amend the
complete ownership list before execution.

This phase is PLACECLI. Execution is blocked pending landed v12 IF-0-WORKER-1 and
IF-0-JOURNAL-1. Next command: none until those upstream gates are verified; then
`codex-execute-phase plans/phase-plan-v13-PLACECLI.md` under separate execution
authority. The following roadmap phase is LANEEXEC; this PR does not plan it.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json`, `docs/placement-process-cli.md`, placement contract documentation
- evidence paths: `plans/evidence/placement/PLACECLI.md`
- redaction posture: `metadata_only`
- downstream handling: `none`
