# OSCOORD2: OpenShell coordinator Stage 2 execution plan

## Context

Draft for lead review; no implementation or activation authorization. Replace the
patched cancellation-lease transport with stock NVIDIA OpenShell **v0.1.4** and
the ai-stack coordinator. The authoritative input is
[agent-harness#1795](https://github.com/Consiliency/agent-harness/issues/1795),
revisions 2–13 and addenda, including comments; later revisions override earlier
examples. agent-harness#1793 is superseded, not a second lease-service interface.

Input baseline: freshly fetched origin/main on 2026-11-02 (recorded in Git ancestry).
Input contract body SHA-256 (gh JSON body, trailing newline):
`e0d504a3235ca58aba0af6ad89ff952649c8ea313c00562b095fdcd5f9291b1d`.
Input `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/coordinator-v1.schema.json`
SHA-256: `6c7acf29315116a9efd2c111bace45121c811d04976ffed9cadbf33d9d0c6b89`.
The adjacent README, `vectors/`, BAML source and `placement_contract.py` carry
wire detail; stock `proto/sandbox.proto` at v0.1.4 carries policy detail. Schema
acceptance of an arbitrary policy object does not establish stock policy validity.
Preserve these input versions in review evidence; do not pin future output history.

This is an issue-led detailed plan, like the placement-hardening amendments. No
roadmap phase or EC goal IDs for this stage were found; do not invent them or bind
the draft to an unrelated roadmap. Formal phase registration is a lead question.

Scope: transport, channel, backend, journal adaptation, worker envelope, tests,
stock provenance and the disabled ranked-target ladder. This stage does not dispatch a
release or publish a package; provenance retirement is source maintenance. Keep
`_NONLOCAL_EXECUTION_DRIVER` false and backend registration closed throughout.
No deployment, endpoint enrollment, provider use, launch-site activation, cloud
backend implementation, OpenShell upgrade, streaming proxy or upstream patch.

**Scope conflict requiring lead resolution:** the task's removal bullet names
`placement_lease`, `lease_store` and `lease_supervisor`, while its read-first
instructions and agent-harness#1795 explicitly keep them. This draft preserves
all three: placement journals protect local dispatch/reaping; path-set leases
and process supervision have separate responsibilities. Only the patched SDK
pin, private RPC adapters and fork qualification are removed. Deleting retained
modules needs an explicit scope amendment, not an inferred coordinator migration.

## Interface Freeze Gates

- IF-0: Consume coordinator v1 exactly as revised through 13: HTTPS JSON `/v1`,
  `X-Deadline-Ms` relative milliseconds on every request, one `LeaseStatus` success
  shape, closed errors/reasons, owner CN plus client OU identity. Reserve sends
  only workload, TTL and digests; never owner/client text. Create sends full
  policy, image by allowlisted digest, matching JCS policy digest,
  `restart_policy: never`, `providers: []`, `service_exposures: []`.
- IF-1: Preserve `ExecutingBackend` bounds and C3/C4/C6/C9 obligations. Amend C7
  only through agent-harness#1791 below. A release requires coordinator kill's
  barrier plus a complete inventory proving absence or terminality; local stream
  cancellation, HTTP success and terminal display state alone prove nothing.
- IF-2: One stock `ExecSandbox` request per lease, field 11 `request_id` derived
  deterministically from lease and attempt. No retry, reconnect, replay, start,
  stop, suspend or resume. Coordinator owns create/delete; clients never call
  stock lifecycle RPCs. Stock streaming exec is not intercepted; destruction is
  its fence. A kill race invalidates results until the barrier and never permits
  importing the racing result. `exec_claimed` is client evidence, not a fence.

## Lane Index & Dependencies

SL-0 — Ranked ladder prerequisite within Stage 2
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no
SL-1 — Coordinator transport and certificate channel
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no
SL-2 — Backend and journal lifecycle
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no
SL-3 — Worker policy and projections
  Depends on: SL-2
  Blocks: SL-4
  Parallel-safe: no
SL-4 — Documentation sweep and provenance retirement
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

Paths below are repository-relative. Each lane is a reviewable PR boundary;
split further if needed without prescribing commit counts or topology. Freeze
proofs before accepting implementation, and land changes with their tests.

### SL-0 — Ranked ladder prerequisite within Stage 2

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`
- **Interfaces consumed**: `PlacementTarget`, `CapacityReading`, `AdmissionOutcome`, `TrailEntry` (pre-existing)
- **Interfaces provided**: ranked C7 ladder
- **Tasks**: test then amend C7/LADDER_TABLE per agent-harness#1791: remove
  `last_local_barred`/the capacity bar; local is an ordinary ranked target,
  admitted only with local memory, CPU-relative load and live-sandbox headroom.
  Thresholds have packaged defaults and governed overrides. Advisory capacity
  may order/skip targets; only authoritative admission reserves capacity. Unknown
  readings never imply free capacity. Preserve release-before-overflow.
- **Verification**: ladder/settings/policy suites, local equivalence, stale/unknown
  telemetry, read/admit races, capacity→local-with-headroom→overflow and local
  refusal controls. Mutation: restore the capacity bar and watch the new case
  fail. No new cloud execution route.

This lane includes the planned amendment of agent-harness#1502 obligation 1:
ranked local replaces the last-only source rule. Preserve its remaining
obligations: named no-rung outcome; cancellation winning coincident failed exec;
trusted-base settings and malformed-config precedence before remote effects;
one admission-plus-transfer budget, and execute bound from the post-seal clock
read. Issue updates belong to future authorized execution, not this drafting task.

### SL-1 — Coordinator transport and certificate channel

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py`, `phase-loop-runtime/tests/test_openshell_transport.py`, `phase-loop-runtime/tests/test_openshell_transport_grpc.py`, `phase-loop-runtime/tests/test_openshell_channel.py`, `phase-loop-runtime/tests/_openshell_channel_server.py`
- **Interfaces provided**: bounded coordinator client and stock exec stream
- **Tasks**: establish fake HTTPS/JSON lifecycle and stock gRPC tests, then replace
  `ControlCancellationLease`, `ExecCancellationLease` and source RPC dependence.
  Explicit CA, client certificate/private key, CN owner and `OU=agent-harness`
  replace OIDC bearer/workspace authority. Verify server SAN at coordinator
  `:17672` and proxy `:17670`; explicit credentials, no ambient discovery, TLS
  overrides or application retries. Owner IDs in local journals are not
  certificate CNs; bind them explicitly without rewriting local ownership.
- **Verification**: wire vectors drive request/response cases, with schema format
  checks and semantic fault injection; stock generated protobuf fixtures verify
  request_id, finite stream deadlines, cancellation, silence, byte/message caps
  and dropped streams. Test wrong CA/SAN/OU, failed client authentication,
  secret-free errors, bounded close and single dispatch with hostile retry config.
  TLS readiness alone is not authorization or live shutdown qualification.

All operations share remaining caller allowance, including bounded polling and
pagination; responses cannot reset it. Unknown errors, malformed responses,
wrong lease echoes, regressed flags or changed sandbox UUIDs fail closed and
retain cleanup obligations. No prose parsing or interpreting an untyped 5xx as
nothing held.

### SL-2 — Backend and journal lifecycle

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py`, `phase-loop-runtime/tests/test_openshell_backend.py`, `phase-loop-runtime/tests/test_openshell_journal.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- **Interfaces consumed**: `ExecutingBackend`, `Lease`, coordinator client (pre-existing)
- **Interfaces provided**: coordinator-backed disabled backend and cleanup adapter
- **Tasks**: journal client UUID before reserve; use canonical UUID spelling of
  the existing journal lease identity rather than allocate an unjournaled second
  identifier. Persist reserve/create/exec attempt markers before effects. `admit`
  reserves then creates once and observes readiness. Lost replies reconcile by
  status, then release; disk recovery grants cleanup authority only. Preserve
  journal locking, fixed ends and no dispatch after recovery. Old fork obligations
  must remain identifiable and cleanup-only; never send them to the coordinator
  or clear them as unknown. Refuse ambiguous legacy recovery pending lead policy.
- **Tasks**: `renew` requests 1–3600 seconds with remaining bounds, around half TTL,
  tracks expiry and the 24-hour cap; never fabricates success. Rename cleanup-only
  `OpenShellBackend` to distinguish it from execution. Map reaper context
  `ValueError` to typed refusal while continuing other scheme groups.
- **Verification**: journal/backend/reap CLI tests: crashes at each durable marker,
  lost reserve/create replies, unseen kill tombstones, duplicates, coordinator
  restart, immutable bindings, cancellation and expiry. Kill destroys all label
  matches; retain charges/journals until barrier plus complete listing evidence.
  Mutations removing either proof must fail. No result can clear a cleanup debt.

`list_owned` reads every page under one snapshot, scoped to certificate
(owner, client); request page_size ≤200. Restart from page 1 on
`snapshot_expired`, snapshot change or stale token, within the original bound
and 60-second validity. Never return partial success. Keep reservations and
nonterminal tombstones/killing obligations represented with stable reservation
references. Retain validated terminal entries as evidence while filtering them
from the driver's outstanding pairs only after barrier proof; merely listing a
lease is not proof it is live or released. Record duplicate/reclaim details.

### SL-3 — Worker policy and projections

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`, `phase-loop-runtime/tests/test_openshell_worker.py`, `phase-loop-runtime/tests/test_openshell_source_rpc.py`
- **Interfaces provided**: one-shot load/restrict/exec envelope
- **Tasks**: replace private source publication with a bounded load manifest and
  verified content carried in the single stock ExecSandbox worker stdin envelope,
  alongside existing sealed request metadata and credential handling. Enforce
  stock stdin/message limits before dispatch; oversize input refuses, never
  spills secrets or opens another exec. Remove obsolete source-RPC tests after
  equivalent manifest, digest, transfer-failure and cancellation cases exist.
- **Tasks**: policy is strictly stock `SandboxPolicy`, snake_case proto3 JSON,
  unknown/camelCase fields refused, digest over exact RFC 8785 JCS document.
  Do not treat `{}` or candidate `{"version":1}` as qualified no-egress policy.
  Use immutable image-baked, uid-10001-owned stable load parents in outer
  `read_write`; explicit guest mappings create per-run leaves below them.
  Never list nonexistent per-run leaves in outer policy: stock skips them.
- **Tasks**: worker verifies/loads review source and dependency projections,
  probes **guest** Landlock ABI, constructs the handled-access mask and calls
  `restrict_self` before agent exec. Unsupported rights/ABI, missing roots or
  restriction failure abort before agent launch. Every agent descendant inherits
  the layer. No later exec, upload or SSH session for agent work. Review inputs
  and projections become read-only; implementation's separate edit tree and
  necessary result/scratch roots remain writable under their declared scope.
- **Verification**: supported/unsupported ABI and load failure fakes prove order
  and zero unrestricted launches; tamper/write/unlink/rename and descendant
  controls prove restricted input roots while allowed output remains writable.
  Hashes bind guest mappings and projection manifests. Record
  `read_only_enforced_by: client-landlock`, outer `policy_digest`, restricted
  roots, client-reported exec claim and coordinator reclaims; never claim stock
  enforces the inner layer. Actual guest enforcement remains a live gate.

For agent-harness#1787, wire authenticated dependency projections into this
manifest or call `refuse_unwired_dependency_route(...)` before remote effects
for required dependency sessions. Offline refusal coverage is mandatory even
where a real projection adapter remains unqualified. Preserve credential-free
artifact identity, output quarantine, native validation and isolated same-base
client retest/owner acceptance; a worker echo is not runtime attestation.

### SL-4 — Documentation sweep and provenance retirement

- **Owned files**: `phase-loop-runtime/openshell-private-transport.md`, `phase-loop-runtime/scripts/qualify_openshell_sdk.py`, `phase-loop-runtime/scripts/openshell-sdk-manifest.json`, `phase-loop-runtime/tests/test_openshell_sdk_qualification.py`, `phase-loop-runtime/tests/_openshell_qualification.py`, `plans/evidence/openshell-cancellation/CONFORMANCE.md`, `CHANGELOG.md`
- **Tasks**: retire patched SDK pin/qualification and private source RPC recipe;
  document stock v0.1.4 proto/generator/dependency provenance and offline test
  recipe without claiming qualification. Preserve historical receipts as history.
  Replace fork-era contract claims with explicit coordinator/client/stock
  responsibility and remaining activation evidence. Update affected package
  inclusion/import guards in a separately scoped follow-up if discovered.
- **Verification**: provenance/import and packaging checks, docs audit, retained
  regression suites and clean-wheel Gate A. Search remaining private API imports
  and fork pins; history may remain, executable dependency may not. This lane
  cannot retire a guard before its stock replacement proof exists.

## Execution Notes

Use `placement_contract.py` mappings with operation context, never blind lookup
as a ladder action. The table uses the `sandbox_placement_` prefix for code suffixes.

| Coordinator answer | Code suffix and action |
|---|---|
| `at_capacity` | `at_capacity`; keep closed reason, next ranked target |
| `unavailable` | `unreachable` only on typed pre-reservation refusal; preserve reason |
| `not_enrolled`, `owner_mismatch`, `workload_unsupported` | matching `not_enrolled`, `identity_mismatch`, `workload_unsupported`; refusal only where nothing held |
| `deadline_exceeded`, no answer, untyped 5xx | `operation_timeout`; status then kill and confirm; never overflow while uncertain |
| `fenced`, `expired` | after launch `lost_after_launch`, no replay; before launch release any obligation first |
| `unknown_lease` | no successful/empty interpretation; recovery kill-to-tombstone then confirm |
| `duplicate_binding` | `release_unconfirmed` until kill destroys every match, affecting this lease only |
| `invalid_request` | reserve: nothing held, typed refusal; create/renew: reservation remains, release before ladder movement |
| `digest_mismatch` | create-only, no direct ladder code; kill reserved lease and confirm |
| `lifetime_exceeded` | renew-only, no ladder code; end before current expiry, kill/confirm |
| `snapshot_expired` | inventory-only, restart complete listing; exhausted bound means `release_unconfirmed` |
| kill without barrier or incomplete inventory | `release_unconfirmed`; keep journal for reaper |

A reserve `invalid_request` collision can use a fresh journaled UUID only when
nothing was held; no create/exec replay. Gateway `INVALID_ARGUMENT` during
create is coordinator `deadline_exceeded`, not a safe refusal. Bare gRPC
`UNAVAILABLE`/`DEADLINE_EXCEEDED` after dispatch remains uncertain. Only proven
pre-send connection failure is unreachable. Reasons remain verbatim in trail.

Governance: obtain plan review before execution, then panel CR, independent
actual-source approval and qualified president ruling on each source boundary,
per CONTRIBUTING.md and the placement-hardening owner amendment. Use the
cross-vendor advisor board for the overall change and final integration. Freeze
a review round cap of two; delta-review dissenting seats, let all seats finish,
and descope/escalate rather than loop past the cap. File ruled deferrals through
`docs/registers/deferred-findings.md` before decision dispatch. Stop and diagnose
if plan amendments outnumber implementation. This draft dispatches no board,
files no issue, and authorizes no GitHub mutation.

## Acceptance Criteria

These are future acceptance obligations, not claims about this drafting run.

- [ ] AC-1 — Coordinator lifecycle and recovery: proven by `pytest -q phase-loop-runtime/tests/test_openshell_transport.py phase-loop-runtime/tests/test_openshell_journal.py phase-loop-runtime/tests/test_openshell_backend.py`; falsified by the path-entered control with a dropped-create-reply case moving to the next target before kill/barrier and complete inventory, or a duplicate-binding case clearing its journal while a match remains.
- [ ] AC-2 — Single stock dispatch and bounded channel: proven by `pytest -q phase-loop-runtime/tests/test_openshell_transport_grpc.py phase-loop-runtime/tests/test_openshell_channel.py`; falsified by the path-entered control with a stream-drop case observing a second ExecSandbox, a wrong-SAN handshake succeeding, or hostile retry configuration producing repeated dispatch.
- [ ] AC-3 — Worker restriction and projection refusal: proven by `pytest -q phase-loop-runtime/tests/test_openshell_worker.py`; falsified by the path-entered control reaching the worker with an unsupported guest ABI and launching the provider, or a restricted descendant modifying a loaded input root.
- [ ] AC-4 — Ranked local placement and disabled activation: proven by `pytest -q phase-loop-runtime/tests/test_sandbox_placement.py`; falsified by the path-entered control restoring the capacity bar and still passing the capacity-to-local-headroom case, or the disabled-driver control reaching remote execution.

Disabled source has coordinator-only lifecycle, one stock exec, no private fork
runtime dependency, phase-aware recovery and ranked C7 tests. Existing placement
lease, lease-store/conformance and supervisor suites remain; their modules stay.
Artifact/worker security tests stay, adjusted only for the documented boundary.
The issue's approximately 3.5k OpenShell test lines are a migration estimate:
current `test_openshell*.py` totals 4,750 including artifacts and worker tests.
Rewrite transport/gRPC/channel/backend/journal/source cases by invariant, not
line-for-line; retire SDK tests only with stock provenance replacement. Retain `test_launcher_exec_supervisor.py` and
the agent-harness#1147 scratch/inventory suites as independent regressions.

Stage 2 delivers offline projection wiring-or-refusal for agent-harness#1787,
worker launch inventory/scratch requirements for agent-harness#1788 in review
artifacts, typed reap refusal for agent-harness#1789, and distinct backend names
for agent-harness#1790. It does not close those activation gates on fake evidence:
real projection routes, production adapter inventory/scratch decisions and live
acceptance still need source-bound approval before registration or flag changes.

Activation additionally requires ai-stack **Unit 7 deployment**, owner's live
qualification, exact minimal/full stock policy vectors proving no egress/providers,
client/proxy/coordinator certificates and routing, credential split and method
denials, renewal/expiry, retention ≥longest journal life (default 90 days, minimum
30), and exact-sandbox destruction proofs for late create/exec, lost reply,
restart and open streams. Keep the reconciler/MemoryMax backstop. Reconcile
previously failed full/native-ai acceptance including D8 jailed-Claude under the
2026-10-31 owner decision; disabled merge is not qualification. Remaining C5,
provenance, bounded production shutdown and launch-site obligations are not waived.

## Verification

For each future lane run `make check` and its named suites, with absolute source
PYTHONPATH as CONTRIBUTING.md requires. Record negative controls with source
identity and test output. Wire-vector fakes establish protocol behavior, not
live capacity, destructive fencing or guest isolation. Preserve shared contract
schema/digest/emitter drift checks; arbitrary JSON-policy vectors remain schema
examples until strict stock-policy vectors are added through contract governance.

Before future merges require hosted suite gate, lint, chronology retention guard,
docs-freshness audit, gitleaks and release-consistency check. Dispatch exact-head
clean-wheel Gate A for packaging/tests-read docs/workflow changes; Gate A does
not run on PRs automatically. Verify stock fixtures work without a private SDK
or optional qualification environment. Collect postmerge-main proof separately.
For this local plan-only task run `validate_plan_doc.py`; no CI dispatch or live
qualification is authorized. Report formal-metadata limitations honestly.

Draft validation: run the repository validator in the locked runtime environment.
The draft intentionally lacks formal phase frontmatter pending open question 2;
that prevents a clean formal-validator verdict. Its SDK-manifest retirement also
triggers the release-shaped heuristic warning despite no release dispatch. Do not
claim phase-dispatch readiness from a within-budget draft.

## Spec Closeout Plan

- decision: canonical_spec_update
- `spec_delta_closeout.v1`: target surfaces are C7 and agent-harness#1502's
  obligation amendment, transport design and activation evidence matrix;
  evidence paths are source-bound lane review packets and test receipts.
- `metadata_only`: false for future implementation; this draft changes prose only.
  No shared wire change is intended. A new code/schema revision returns to the
  lead and shared-contract governance rather than being silently implemented.

## Open questions for the lead

1. Confirm preserving `placement_lease`, `lease_store`, `lease_supervisor` resolves
   the contradictory removal bullet, or explicitly authorize a different scope.
2. Which roadmap/phase and existing goal IDs, if any, should bind this issue-led
   draft for formal phase dispatch? None are fabricated here.
3. Name the agent-harness immutable workload image, stable load parents, guest
   mappings, trusted Landlock wrapper and qualified minimal/full policy. These
   depend on the owner's live run; candidate policy is not acceptance.
4. Who owns Unit 7 deployment and the live qualification receipts, and who may
   approve launch-site activation after all outstanding gates are met?
5. What is the retention and cleanup authority for any surviving fork-era journal
   obligations? Coordinator `unknown_lease` cannot erase a legacy sandbox debt.
