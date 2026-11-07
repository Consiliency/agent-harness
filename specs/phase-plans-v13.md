# Phase roadmap v13 — Placement lifecycle consolidation

> # ADVISORY — not runner-selected (2026-11-06)
>
> This owner-priority roadmap is manually planned and landed while
> `specs/phase-plans-v11.md` remains the sole active runner-selected roadmap.
> This status grants no live placement or external activation authority.

## Context

agent-harness owns the shared placement contract and reservation lifecycle used
by both agent-harness and agent-toolkit. The current placement seam, OpenShell
coordinator client and ranked capacity walk are in agent-harness, but there is no
stable process boundary for the toolkit, no ForwardTcp-to-Unix bridge, and no
phase-loop lane-executor placement site. The planned v12 supervised worker is a
separate prerequisite and remains local-only; the SEATS roadmap owns review-seat
route policy; agent-harness#1704 owns extraction; and agent-harness#1791 owns the
capacity order. None of those homes can absorb this cross-client lifecycle without
changing its declared ownership.

This new roadmap consumes those decisions instead. Phase 1 freezes and
implements the process contract after the supervised-worker seam is available.
Phase 2 adds the generic approved-client launch service and connects phase-loop
LANE executors, where Pi is already the default. Phase 3 is the separately
authorized live activation and agent-toolkit cutover. All design, schema,
fake-coordinator and refusal-path work is plannable offline now.

## Architecture North Star

```text
agent-toolkit shim ─┐
phase-loop LANE ────┼─► agent-harness-placement --client … reserve
Claude / Codex ─────┤             │                 │
review-seat route ──┘             │                 └─► one reservation / one target
                                  ├─► generic snapshot/upload/exec/bridge lifecycle
                                  ├─► supervised_worker_cli launch|status|cancel
                                  └─► release|reap ─► selected client's inventory only
```

The required `--client` flag selects one per-client trusted placement
configuration, certificate and inventory; the environment never selects them.
That configuration owns target ranks, identity selection, policy-vector lookup
and the provider-name-to-endpoint allowlist. Requests supply a required non-empty
set of provider names, never endpoints or model names, and never supply a target
list, inline policy, owner, client or certificate. `pi-runner` admissions rank `ai`, then local when all published
headroom thresholds admit, then a disabled E2B rung. Seat workloads consume one
target already selected by SEATS JAILCORE and never enter that ladder.

## Assumptions

- v12 IF-0-WORKER-1 and IF-0-JOURNAL-1 are prerequisites for process CLI
  implementation and lifecycle integration, not claims about the current tree.
- The published admitted launch envelope v2 remains the authority for launch
  admission and its no-fallback-after-admission rule. Its
  `launch.grants.egress_policy_sha256` binds the reservation's effective egress.
- The OpenShell coordinator remains the authoritative remote capacity and lease
  service; local telemetry is informational until a local slot is actually reserved.
- agent-toolkit keeps only its `pi-runner` image recipe, `remote-inner` and thin
  shim. The shared service owns placement and launch lifecycle; the legacy
  OpenShell/coordinator client tracked by agent-toolkit#35 retires fully when the
  three-part switch condition passes.
- The SEATS JAILCORE planner owns any roadmap wording needed for owned-host review
  seats to offload for capacity. This roadmap consumes its landed interface only.

## External Inputs

| Input | Pin |
| --- | --- |
| Placement process protocol v1 | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json` with erratum PLACECLI-v1-errata-1, sha256 `ddf3649953bc6ee28fc90466cd825a85e7c282188d84eb97aef107a77234fd57` |
| Shared placement BAML | `phase-loop-runtime/src/phase_loop_runtime/baml_src/placement_contract.baml`, sha256 `f662ea044dbe37a65c8bd782aeb7a5b2dd75b5851944c05b4f055061fcd27ace` |
| Placement policy vectors | `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json`, sha256 `5b3bc7f515bd2a4cbc10a18d98465d511f65e8089213ceb8c21f9cce2409020f` |
| Credential-proxy reference | Consiliency/agent-toolkit commit `9304a5b92c8c409473ca3d2182557b8592697476`, `harnesses/pi/sandbox/cred-proxy.mjs` and `docs/remote-placement.md` |
| Admitted launch envelope v2 | Consiliency/consiliency-contract commit `2b91ef85bfdc76239ae52806b3318513951543ab`, schema sha256 `6d6b2f89c55d160c2c132c29b3aa330a0a91c40ab017707040478a60b469194f` |
| Run-status contract | Same commit, schema sha256 `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30` |

These are immutable planning inputs. A changed input requires reviewed repinning;
no plan pins a future implementation commit, commit count or landing topology.

## Non-Goals

- Activating OpenShell, a review seat, a Pi executor or a toolkit cutover in the
  PLACECLI or LANEEXEC phases.
- Implementing or funding E2B. It stays represented but disabled until `ai` is
  live and the owner supplies an account and spend cap; that needs an amendment.
- Rewriting the SEATS REMOTE/JAILCORE roadmap, agent-harness#1704 extraction or
  agent-harness#1791 ranking plan.
- Reimplementing agent-toolkit's `pi-runner` image recipe, `remote-inner` or shim.
- Claiming an OS-enforced contract tier. Remote writers use the conservative
  `provider_readonly_patch_return_audit` tier label and record extra evidence.
- Interactive or steerable admitted workers. Each admitted attempt is bounded,
  one-shot and returns proposal bytes; a longer job uses a fresh attempt.
- Selecting a model within a declared provider. Pi, OpenCode and other harnesses
  keep model selection behind their own fixed launch command.

## Cross-Cutting Principles

1. **One target per envelope.** Placement finishes before envelope construction.
   `at_capacity` starts a new admission; after admission no fallback is allowed.
2. **Closed JSON boundary.** Placement verbs accept one bounded JSON object;
   `version` accepts empty stdin; every command emits one bounded JSON object.
   Unknown members, values, codes and policy names fail closed.
3. **Named policy only.** Every resolved `policy_vector` is a name from the
   pinned policies file; neither the request nor caller context can carry inline
   policy or authority. Local Pi uses `minimal-without-app`; remote Pi uses
   `full-remote-pi-runner`.
4. **Identity follows the workload.** Every Pi target uses the operator-configured
   OU=`agent-toolkit` certificate and inventory. agent-harness manages that key
   and inventory separately from OU=`agent-harness`.
5. **Cleanup is reservation-scoped.** An uncertain create, lost reply or
   unconfirmed release blocks later targets only for that reservation in the
   selected client inventory. Other reservations and the other client continue;
   reap can inspect only its caller's inventory.
6. **Honest records.** Placement outcomes, v2 admission diagnostics and run-status
   termination remain separate closed vocabularies; raw output and secrets never
   become placement evidence.
7. **Offline before live.** Fakes, mutations and black-box fixtures establish
   behavior, never live readiness. Operational evidence is runner-stamped later.
8. **Machine-checkable plans.** Each phase plan has an effective
   `automation.suite_command`, validates through IF-0-VC-2 and names any later
   operational evidence plus its amendment mechanism.
9. **Local admission and confinement fail closed.** Every host reads its effective
   pressure thresholds and per-reservation cgroup caps from operator configuration;
   the host `config_sha256` binds both. Every local reservation runs in its own
   delegated cgroup with `memory.max`, `cpu.weight` and either `io.weight` or an
   `io.max` bandwidth cap. Missing delegation or a required controller refuses
   `sandbox_placement_capability_unmet`; no local workload runs uncapped.
10. **Provider names bind egress, never credentials.** Every reserve request names
    one or more unique operator-allowlisted providers. The effective grant is
    exactly the policy-vector baseline plus those providers' resolved endpoints,
    recorded as `providers` and `egress_sha256` in the reservation and bound into
    the launch envelope. Model bytes traverse the requester's credential proxy;
    provider keys never enter the placement service or sandbox.

## Owner Rulings (2026-11-06)

- agent-harness owns the generic placement and launch lifecycle; agent-toolkit
  keeps only its `pi-runner` image recipe, `remote-inner` and thin shim.
- Agent and executor order is `ai`, local with headroom, then E2B. Review seats on
  owned hosts may use remote capacity after one generic egress-and-credential probe
  set; per-vendor OD-7 applies only to third-party clouds.
- Pi uses OU=`agent-toolkit`; agent-harness manages two keys and inventories.
- `--client agent-toolkit|agent-harness` is required and selects operator config;
  no environment variable may select identity or configuration.
- Remote writers carry `provider_readonly_patch_return_audit`.
- E2B is parked as stated in Non-Goals.
- The toolkit switches only when all three are true: L0–L9 evidence parity, its
  fixtures pass as black-box tests, and one end-to-end Pi run on `ai` succeeds
  through the toolkit shim.
- Local headroom thresholds are per-host operator configuration. The published
  defaults are MemAvailable at least max(4 GiB, 10% of total RAM), one-minute load
  per online CPU below 70%, `/proc/pressure/io` `full avg10` below 10%,
  `/proc/pressure/memory` `some avg10` below 10%, fewer than four live sandboxes
  and observations no older than five seconds. Unknown or stale dimensions and
  missing, unreadable or malformed PSI are `at_capacity`.
- `ReserveRequest.providers` is required, non-empty, unique and names only
  operator-allowlisted providers. Unknown or unpermitted names refuse
  `sandbox_placement_provider_refused` before admission. The same allowlist applies
  locally; owned hosts need the generic probe receipt, while a third-party target
  needs a current OD-7 clearance for every declared provider.

## External Readiness Gates

- **EXT-WORKER** — v12 IF-0-WORKER-1 and IF-0-JOURNAL-1 are implemented and
  landed; the CLI and status contracts are available to consume.
- **EXT-LAUNCHSITE** — agent-harness#1787, agent-harness#1788,
  agent-harness#1789 and agent-harness#1790 are satisfied for each new launch
  site, including dependency projection, inventory/scratch, reap and backend names.
- **EXT-OPENSH** — OpenShell qualification windows W2–W4 pass; `ai`-stack Unit 7,
  certificates/grants and the required image allowlist are complete.
- **EXT-SEATS** — the SEATS JAILCORE planner's owner-approved capacity-offload
  outcome is landed before the review-seat policy consumes it.
- **XREQ-SEATS-LOCAL-CGROUP-1** — before the coordinator routes a local SEATS
  launch, the SEATS seat launcher applies the selected host's `memory.max`,
  `cpu.weight` and `io.weight` or `io.max` cap in a per-reservation delegated
  cgroup. Missing delegation or a required controller refuses
  `sandbox_placement_capability_unmet` and launches nothing. This roadmap records
  the cross-roadmap requirement for coordinator routing; it does not amend SEATS.

## Top Interface-Freeze Gates

- IF-0-PLACECLI-1 — Frozen placement process messages, stable console entry,
  version response, closed code vocabularies, named-policy/provider lookup,
  explicit client/config selection, target/egress binding and exit classes.
- IF-0-PLACECLI-2 — Reservation lifecycle, caller-scoped reap, per-host local
  headroom configuration and published defaults, effective-egress digest,
  credential-proxy ForwardTcp bridge and black-box parity evidence.
- IF-0-LANEEXEC-1 — Generic approved-client reservation, snapshot/upload,
  egress-grant-bound restricted exec, optional credential-proxy bridge,
  release/reap and patch-return evidence with fail-closed disabled activation.
- IF-0-ACTIVATE-1 — Live readiness, one `ai` Pi shim run and three-part toolkit
  switch evidence, with independent cleanup and rollback proof.

## Phases

### Phase 1 — Placement process boundary and lifecycle (PLACECLI)

**Objective**

Implement the frozen JSON process boundary, authoritative reservation lifecycle,
two identities/inventories and the generic ForwardTcp-to-Unix bridge, entirely
disabled for live routes until later activation.

**Exit criteria**

- [ ] EC-PLACECLI-1 — The stable `agent-harness-placement --client agent-toolkit|agent-harness reserve|release|reap|version` entry validates every process message through the pinned artifact. The required flag alone selects per-client operator config; `version` emits the protocol schema and config SHA-256 values. Reserve requires a non-empty, duplicate-free `providers` list of provider names only. Unknown or client/workload/policy-unpermitted names refuse `sandbox_placement_provider_refused` before a capacity probe or lease effect. Unknown fields, duplicate keys, trailing data, oversized input, invalid UTF-8, non-finite/unsafe numbers, unknown policies/codes and client/workload mismatch also refuse before effects. Falsified by an endpoint or model entering `providers`, environment-selected config, a malformed request reaching a probe, or an installed entry point differing from module behavior.
- [ ] EC-PLACECLI-2 — Reserve finishes before envelope construction. `pi-runner` tries `ai` by authoritative capacity, then an actually reserved local slot only when every published headroom threshold admits, then disabled E2B. `leg`, `qualification` and `implementation` do not rank: each admits only the single trusted SEATS route target, or refuses `sandbox_placement_workload_unsupported` before any probe. Pending-qualification policy and provider names resolve for offline work but no live endpoint is reachable. Each attempt has a `TrailEntry`; one admitted reservation binds one target, transport, image, policy digest, declared provider names, effective `egress_sha256`, rank policy and trusted configuration digest. Effective egress is exactly the vector baseline plus resolved declared-provider endpoints. Falsified by a seat workload entering the agent order, request-supplied endpoint/routing, extra egress, informational local telemetry treated as a reservation, or fallback after admission.
- [ ] EC-PLACECLI-3 — Release and reap reconcile definite and uncertain effects in the inventory selected by `--client`. Exit 20 creates only a `(client, reservation_id)` barrier, using request ID until reservation ID is known; independent reservations continue. Reap returns exactly the caller's inventory and cannot inspect the other client. Release is idempotent for a journaled reservation and a repeat returns `released` or `unknown_reservation` without blocking admission. A mismatched echo returns `rejected` and leaves the lease held. Falsified by a host/client-wide barrier, cross-client reap, a mismatched echo returning `unknown_reservation` or `released`, or crash/restart losing a held local slot, lease or bridge.
- [ ] EC-PLACECLI-4 — `pi-runner` and seat (`leg`) reservations on OpenShell each receive one ForwardTcp-to-Unix bridge in a 0700 directory with a 0600 socket, scoped to that reservation. Model connections traverse that link to the requester's `cred-proxy.mjs`-compatible credential proxy; the sandbox holds placeholders and the placement service holds no provider keys. The toolkit's L0–L9 fixture set and fake coordinator/TLS cases run unchanged as black-box process tests and preserve closed outcomes. Falsified by a credential entering the sandbox/service, the shim needing an agent-harness import, a public listener, a shared socket, or fixture-specific production branching.
- [ ] EC-PLACECLI-5 — Local-headroom thresholds come from the selected host's operator configuration, whose `config_sha256` binds the effective values; `version` reports them. Defaults are MemAvailable at least max(4 GiB, 10% of total RAM), one-minute load per online CPU below 70%, `/proc/pressure/io` `full avg10` below 10%, `/proc/pressure/memory` `some avg10` below 10%, fewer than four live sandboxes and one observation no older than five seconds. Any unknown or stale dimension, or missing, unreadable or malformed PSI, is `at_capacity`. A local Pi reservation resolves `minimal-without-app`, has `bridge: null`, uses the same declared-provider allowlist through its requester-owned proxy and counts toward `live_sandboxes`. Live activation and E2B remain disabled. Falsified by a threshold not coming from host config, a local provider bypassing the allowlist, a version response omitting effective thresholds, permissive PSI failure, a local Pi escaping the shared gate, or any offline test enabling a live route.

**Scope notes**

Decompose into 4 lanes: a schema/codec and CLI preamble; reservation, identity and
reap lifecycle; bridge plus black-box fixtures; and a dependent documentation and
evidence reducer. All production entry-point writes are serially owned. The plan
may be written now; implementation starts only after EXT-WORKER. Consume the
SEATS policy as an injected named route decision, never by editing that roadmap.

**Non-goals**

LANE integration, live target activation, E2B backend implementation, toolkit
controller changes or a new enforcement tier. `_NONLOCAL_EXECUTION_DRIVER` stays
false. No production OpenShell backend is registered, and `policies.json` status
stays `pending_qualification`.

**Key files**

- `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`
- `phase-loop-runtime/pyproject.toml`
- `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`
- `phase-loop-runtime/src/phase_loop_runtime/openshell_*.py`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/**`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`
- `phase-loop-runtime/tests/test_placement_cli*.py`
- `phase-loop-runtime/tests/fixtures/placement-cli/**`
- `docs/placement-process-cli.md`
- `plans/evidence/placement/PLACECLI.md`

**Depends on**

- (none)

**Produces**

- IF-0-PLACECLI-1 — Frozen placement process messages, stable console entry, version response, closed code vocabularies, named-policy/provider lookup, explicit client/config selection, target/egress binding and exit classes.
- IF-0-PLACECLI-2 — Reservation lifecycle, caller-scoped reap, per-host local headroom configuration and published defaults, effective-egress digest, credential-proxy ForwardTcp bridge and black-box parity evidence.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`,
`docs/placement-process-cli.md`, placement BAML/README; evidence paths:
`plans/evidence/placement/PLACECLI.md`; `redaction_posture: metadata_only`;
missing or malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 2 — Generic placement launch service (LANEEXEC)

**Objective**

Add the generic launch capability used by every approved client, including the Pi
shim, phase-loop lanes, OpenCode, Claude and Codex, with Pi remaining the default lane
executor. It lands after the worker CLI and before any OpenShell activation.

**Exit criteria**

- [ ] EC-LANEEXEC-1 — Every approved client—the Pi shim, a phase-loop lane, OpenCode, Claude or Codex—uses the same shared lifecycle: reserve with declared providers; snapshot upload; one restricted exec of a client-supplied command; optional bridge; release and caller-scoped reap. A writable phase-loop LANE resolves its existing Pi default before envelope admission and launches exactly that reservation or refuses typed. Falsified by any client bypassing the lifecycle, a second provider/route decision after admission, or a reducer/review unit entering the writer route.
- [ ] EC-LANEEXEC-2 — The shared service owns snapshot construction and upload using git-visible files plus `.git` with masks by default, following Consiliency/agent-toolkit commit `9304a5b92c8c409473ca3d2182557b8592697476` `writer-snapshot.mjs`; a workload policy may select optional `full` mode only under a size cap. It owns admitted launch envelope v2 naming the reserved transport ID and binding `Reservation.egress_sha256` as the RFC-8785 `launch.grants.egress_policy_sha256`, exactly one restricted `supervised_worker_cli launch`, bridge attachment, status/cancel/release and bounded patch/audit return. For every LOCAL reservation it creates a distinct delegated cgroup and applies the selected host's `memory.max`, `cpu.weight` and `io.weight` or `io.max` cap before exec. Clients supply only an allowlisted `image_digest`, a fixed argv template per workload or policy, a named `policy_vector`, required provider names, snapshot root and masks, and `caller_context`; model choice remains inside the client harness. Falsified by a client owning snapshot upload or worker launch, mismatched/omitted egress grant, undeclared launch input, a local workload executing before all caps apply, steering after output, an unbounded attempt, direct protected-tree apply or an OS-enforced claim.
- [ ] EC-LANEEXEC-3 — Every `pi-runner` target uses the OU=`agent-toolkit` key/inventory. OpenShell alone receives the ForwardTcp bridge; local Pi uses `minimal-without-app`, `bridge: null` and shared headroom accounting. Every model connection uses the requester's credential proxy, following agent-toolkit `9304a5b92c8c409473ca3d2182557b8592697476` `cred-proxy.mjs`; no provider key enters the placement service or sandbox. A local target without cgroup delegation or a required cpu, memory or io controller refuses `sandbox_placement_capability_unmet` and runs nothing. Dependency projection, executable/image/policy/egress chain, scratch ownership and caller-scoped release/reap satisfy agent-harness#1787, agent-harness#1788, agent-harness#1789 and agent-harness#1790 offline controls. Falsified by a sandbox/service credential, review-seat identity, cross-client reap, a local bridge, shared inventory, uncapped local execution or an unwired dependency route.
- [ ] EC-LANEEXEC-4 — Fake coordinator, provider registry/egress digest, credential proxy, local-headroom, bridge loss, cancel, timeout, crash/restart and patch-return mutations exercise the production construction sites. No fixture or proxy evidence enables the live route. Falsified by any live adapter being reachable before ACTIVATE or by tests replacing the route constructor under test.
- [ ] EC-LANEEXEC-5 — The phase lands after PLACECLI and EXT-WORKER, but before OpenShell activation; existing local Pi execution remains the typed interim route until activation. Falsified by reversing either ordering edge or removing local fallback before live authority.

**Scope notes**

Decompose into 4 lanes: generic dispatch/admission and snapshot integration;
workload/command/bridge integration; patch-return/run-status evidence; and a
dependent docs/readiness reducer. Keep lane file ownership disjoint. The phase
consumes IF-0-PLACECLI-1 and IF-0-PLACECLI-2 and treats EXT-LAUNCHSITE as an
activation prerequisite, with all available offline refusal work completed here.

LANEEXEC owns the shared launch service for every approved client: reserve;
git-visible-plus-`.git` masked snapshot construction and upload by default, or
policy-selected size-capped `full` mode; envelope admission; one restricted exec
of the client's fixed command template; optional bridge; status/cancel; release;
caller-scoped reap; and bounded patch-return evidence. Clients supply only the
declared image, argv-template, policy, provider names, snapshot-root/masks and caller-context
inputs. agent-toolkit keeps only its `pi-runner` image recipe, `remote-inner` and
thin shim. The legacy OpenShell/coordinator client tracked by agent-toolkit#35 is
the L0–L9 oracle until the switch condition and retires fully when it passes.
LANEEXEC owns per-reservation cgroup creation and cap application for every placed
LOCAL workload. The SEATS seat launcher owns the equivalent work for seat launches;
the coordinator must satisfy XREQ-SEATS-LOCAL-CGROUP-1 before routing them locally.

**Non-goals**

Live `ai` use, toolkit client retirement, review-seat route changes, E2B or remote
application of a proposal. `_NONLOCAL_EXECUTION_DRIVER` stays false. No production
OpenShell backend is registered, and `policies.json` status stays
`pending_qualification`.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`
- `phase-loop-runtime/tests/test_phase_loop_*placement*.py`
- `phase-loop-runtime/tests/test_supervised_worker*.py`
- `docs/placement-process-cli.md`
- `plans/evidence/placement/LANEEXEC.md`

**Depends on**

- PLACECLI

**Produces**

- IF-0-LANEEXEC-1 — Generic approved-client reservation, snapshot/upload, restricted exec, optional bridge, release/reap and patch-return evidence with fail-closed disabled activation.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: phase-loop dispatch/runtime contracts, `docs/placement-process-cli.md`;
evidence paths: `plans/evidence/placement/LANEEXEC.md`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 3 — Live qualification and toolkit cutover (ACTIVATE)

**Objective**

After every external readiness gate, qualify the owned-host routes, run one Pi
LANE end to end on `ai` through the toolkit shim, and authorize cutover only on
the complete three-part parity condition.

**Exit criteria**

- [ ] EC-ACTIVATE-1 — EXT-WORKER, EXT-LAUNCHSITE, EXT-OPENSH and EXT-SEATS are all backed by current, independently resolved evidence; the image, policy, executable chain, certificates, grants and generic probe set match the reservation configuration. Falsified by any stale/missing gate, digest drift or activation inferred from offline fixtures.
- [ ] EC-ACTIVATE-2 — One generic egress-and-credential probe set qualifies each effective declared-provider set for owned-host remote capacity use. Review seats consume the SEATS route outcome; per-vendor OD-7 remains required only for third-party cloud routes and must cover every declared provider. Falsified by an owned-host route using a provider set outside its generic probe receipt, or a third-party target admitting one declared provider without current OD-7 clearance.
- [ ] EC-ACTIVATE-3 — One end-to-end Pi LANE run on `ai` through agent-toolkit's shim reserves, launches, returns a bounded patch proposal, records run status and confirms release. Its reservation uses OU=`agent-toolkit`, records the declared providers/effective egress digest, binds that digest into the launch envelope and uses the exact credential-proxy bridge/process protocol. Falsified by a direct harness-only route, provider/egress drift, a credential entering the sandbox/service, an unconfirmed release, a missing proposal/audit binding or a different client identity.
- [ ] EC-ACTIVATE-4 — agent-toolkit switches only when the same assessed content proves all three conditions: agent-harness reproduces L0–L9 evidence, its fixtures pass unchanged as black-box tests, and EC-ACTIVATE-3 passes. Until then the toolkit client remains a differential oracle. Falsified by retirement or default flip on any subset.
- [ ] EC-ACTIVATE-5 — Deactivation is tested and leaves local typed fallback intact. E2B stays disabled unless a later owner decision supplies the account/spend cap and a roadmap amendment. Falsified by a vector flip without rollback, local-route removal, or an E2B call without that amendment.

**Scope notes**

Decompose into 3 lanes, executed sequentially: readiness and generic probes; live
Pi canary; then a cutover/deactivation evidence reducer. This phase performs external effects
only under separate owner authority. Operational evidence is runner-stamped and
bound by actual run/image/policy identities; proxy evidence requires amendment.

**Non-goals**

Third-party cloud activation, E2B implementation, deleting toolkit controller
code, or changing the shared enforcement-tier contract.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policy-digests.json`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`
- `plans/evidence/placement/ACTIVATE.md`
- `docs/placement-process-cli.md`
- `CHANGELOG.md`

**Depends on**

- LANEEXEC

**Produces**

- IF-0-ACTIVATE-1 — Live readiness, one `ai` Pi shim run and three-part toolkit switch evidence, with independent cleanup and rollback proof.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/placement-process-cli.md`, placement readiness and capability
surfaces; evidence paths: `plans/evidence/placement/ACTIVATE.md`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```text
PLACECLI → LANEEXEC → ACTIVATE
   │           │          └─ EXT-LAUNCHSITE + EXT-OPENSH + EXT-SEATS
   │           └─ EXT-WORKER
   └─ frozen process artifact
```

## Execution Notes

- Plan PLACECLI now. Its implementation waits on EXT-WORKER; that upstream edge
  is a work-start gate, not a reason to leave the design unplanned.
- Plan LANEEXEC after IF-0-PLACECLI-1/2 freeze. It lands after the worker CLI and
  before any OpenShell activation.
- ACTIVATE is never inferred from offline success. It starts only under separate
  owner authority after every external gate is current.
- E2B has no phase in v13. Once `ai` is live and account/spend are decided, amend
  the roadmap rather than reviving the 2026-09 E2B plan unchanged.
- No phase authorizes subagents. Execution plans must list complete and disjoint
  file ownership, with reducers depending on every producer they consume.

## Verification

Planning-artifact validation:

```bash
python -m json.tool plans/artifacts/v13-PLACECLI-contract-v1.schema.json
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.roadmap_lint specs/phase-plans-v13.md
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .
python phase-loop-runtime/src/phase_loop_runtime/skills_bundle/codex-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v13-PLACECLI.md
```

Downstream phase plans add targeted serial suites for the production codec/CLI,
placement lifecycle, bridge, toolkit fixtures, LANE dispatch, supervised worker
and activation evidence. No full local suite or live provider call is part of
this roadmap-planning change.
