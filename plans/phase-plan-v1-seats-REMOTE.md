---
phase_loop_plan_version: 1
phase: REMOTE
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seat_remote_contract.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_remote_vectors.py", "phase-loop-runtime/tests/test_seat_remote_credentials.py", "phase-loop-runtime/tests/test_seat_remote_link.py", "phase-loop-runtime/tests/test_seat_remote_activation.py", "phase-loop-runtime/tests/test_seat_remote_invocation.py", "phase-loop-runtime/tests/test_seat_remote_rung.py", "phase-loop-runtime/tests/test_seat_remote_cli.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py"]
---

# REMOTE: Remote Review-Runner with Provider Egress

## Context

This plan covers roadmap Phase 10 (REMOTE) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. The exit criteria are EC-REMOTE-1 to EC-REMOTE-6, cited by ID only. The
roadmap is advisory (OD-1), so lanes land as governed PRs under principle 2. Nothing else in the
roadmap depends on REMOTE.

**Frozen artifact.** `plans/seats-remote-contract.md` is normative for the vectors, the map, the
probe set, the credential table, the proxy and link, the codes, the rung, the invocation, the
receipt and the window record. Its sha256 is
`1cea960ddd28ef5e1c4bf79083fa9f9938b2c99c2e29dbd937864944ca76d7e8`.
This plan points at its sections (§0–§8) and does not repeat them.

**Consumed, not rebuilt.** REMOTE adds only the review-seat layer.

- **JAILCORE.** The resolver walk, the remote-rung protocol, the capacity gate and the receipt
  schema come from `plans/seats-jailcore-route-contract.md` §2, §3 and §6, at sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`.
- **v13 placement.** The advisory v13 roadmap (agent-harness#1853) supplies the placement
  lifecycle:
  - IF-0-PLACECLI-1, which provides `agent-harness-placement --client agent-harness
    reserve|release|reap|version`;
  - IF-0-PLACECLI-2, which provides the reservation, `egress_sha256` and the bridge;
  - IF-0-LANEEXEC-1, the one generic launch.

  The rules REMOTE relies on are:
  - providers are named and allowlisted, and the egress digest binds the launch (EC-PLACECLI-1,
    EC-PLACECLI-2, EC-LANEEXEC-2);
  - credentials go only through the requester's credential proxy (EC-PLACECLI-4, EC-LANEEXEC-3);
  - seat workloads take the one target the SEATS route chose and never enter the agent order
    (EC-PLACECLI-2);
  - local headroom is pressure-gated with per-sandbox caps (EC-PLACECLI-5,
    XREQ-SEATS-LOCAL-CGROUP-1), which is off REMOTE's path because REMOTE requests only
    `openshell` targets;
  - LANEEXEC owns snapshot, envelope, exec and return (EC-LANEEXEC-1, EC-LANEEXEC-2).

  The inputs are consumed at these content digests:
  - roadmap `specs/phase-plans-v13.md`, sha256
    `78d0f987f7e5754ed1603291838c8aef8e5bb0ddb70fc32b38400d746d8c134f`;
  - artifact `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256
    `ddf3649953bc6ee28fc90466cd825a85e7c282188d84eb97aef107a77234fd57`
    (PLACECLI-v1-errata-1).

  If different bytes land, the plan is repinned before execution.
- **The rest.** The guest wrapper is `landlock-exec` (agent-harness#1795 revision 14), the
  helper the review-runner Containerfile already pins at agent-toolkit revision d945fdd0. Link
  framing follows agent-toolkit `docs/remote-placement.md` at the v13-pinned revision 9304a5b9.

**Design in one paragraph.**

- The JAILCORE walk reaches step 2 for a row the matrix routes remote, or for a capacity offload
  its gate admits.
- `SeatRemoteRung` (contract §6) checks activation, the vector map, the credential row and the
  projection. It then reserves through the placement console entry with workload `leg`, policy
  `full-remote-pi-runner` and exactly one provider.
- It checks that the reservation binds the activated `openshell` target, the bridge and the
  expected `egress_sha256`.
- One IF-0-LANEEXEC-1 launch runs the vendor CLI under `landlock-exec`. The CLI's API base points
  at an in-guest relay, which carries model connections over the reservation bridge to a per-seat
  requester credential proxy on the launching host.
- The proxy swaps a short-lived placeholder for the host credential and forwards through the
  vendor's IF-0-JAILCORE-2 allowlist proxy.
- The guest never holds a credential. The bounded result returns a verdict and tool evidence.

**Owner rulings in force.**

- **Capacity (2026-11-06).** The roadmap capacity bullet and JAILCORE contract §6 and §8 apply:
  - owner-controlled targets may take review seats for capacity after one generic
    egress-and-credential probe set;
  - third-party targets need per-vendor OD-7 first;
  - capacity ships disabled and is enabled per host by a private grant plus a current probe
    receipt.

  REMOTE supplies that probe set and its evidence (contract §2) and changes nothing in the gate.
- **OD-5.** Pi's provider-scoped credential.
- **OD-7.** OD-7 is pending for the design packet (lane C).

## Interface Freeze Gates

- [ ] **IF-0-REMOTE-1** — the per-provider vectors: contract §1–§2. This covers
  `seat-provider-vectors.json` (`seat_provider_vectors.v1`), `seat-vector-map.json`
  (`seat_vector_map.v1`), `seat_remote_vectors.validate`, `remote-probe-set.json`
  (`seat_remote_probe_set.v1`, `probe_set_digest`), `seat_remote_probe_evidence.v1` and the C5
  amendment. `policies.json` and every existing vector digest stay unchanged. Lane A owns the
  semantics; the shapes ship in SL-0.
- [ ] **IF-0-REMOTE-2** — the per-vendor remote credential table, proxy and link: contract §3–§4.
  This covers `RemoteCredentialRow`, `CREDENTIAL_TABLE`, `open_session`, `ProxySession.revoke`,
  the closed delivery set `requester_proxy | unsupported` and the link frame subset with its
  bounds. Lane B owns the semantics; the shapes ship in SL-0.
- [ ] **IF-0-REMOTE-3 (plan-internal)** — the codes and remote descend: contract §5. This covers
  the additive `seat_route_contract.CODES` and `OD10_CLASSES` entries and `REMOTE_DESCEND_CODES =
  {seat_remote_at_capacity, seat_remote_unreachable}`. It is a security change reviewed by the
  lane C packet.
- [ ] **IF-0-REMOTE-4 (plan-internal)** — the rung, activation and invocation: contract §6–§8.
  This covers `SeatRemoteRung` with steps R0–R6, `held()` and `release_unused()`;
  `seat_remote_activation.v1`, `seat_remote_deactivation.v1` and `activation_digests`; `run_remote_seat`, `run_probe_set` and
  `seat_remote_result.v1`; `seat_remote_review_receipt.v1`; and `seat_remote_window.v1`.

## Cross-Repo Gates

These are non-human work-start gates unless marked live. None of them is an amendment to the
other roadmap.

- **XR-1 (v13, consumed).** The pinned PLACECLI artifact gives workload `leg` on `openshell` one
  reservation-scoped `ForwardTcpUnixBridge` (EC-PLACECLI-4); every other seat reservation has
  `bridge: null`. It leaves the `leg` policy vector unconstrained, and R6 binds
  `full-remote-pi-runner` (contract §6).
- **XR-2 (v13).** The agent-harness client configuration names one seat `openshell` target, and
  REMOTE's activation file names the same one. Its provider allowlist references
  `seat-provider-vectors.json`, and its owner-controlled clearance reads REMOTE's probe receipt.
  REMOTE writes the data, and PLACECLI reads it.
- **XR-3 (v13, frozen).** IF-0-LANEEXEC-1 accepts workload
  `leg` with the following inputs:
  - a fixed per-vendor argv template;
  - snapshot mode `full` under its size cap;
  - one bounded non-patch result, as a non-writer route (EC-LANEEXEC-1).

  Frozen by `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, sha256
  `41db02e67cb37c5c7fc5d70e152e882495bc7f1548a0d7898384eb7ef0f3f36b`
  (`x-argv-templates.per_vendor_seat_templates`, `x-snapshot.full_mode`, `x-return.result`, and the
  in-process `pre_exec` and `withhold` hooks). SL-4 and SL-5 still wait on the landed LANEEXEC
  implementation (Upstream implementation, below).
- **XR-4 (v13).** EC-ACTIVATE-2 consumes REMOTE's probe set; no second generic set is authored.
- **Upstream implementation.** The JAILCORE resolver (EC-JAILCORE-2), PLACECLI after
  EXT-WORKER, and LANEEXEC.
- **Live (LA-4, owner) gates.** These gate EC-REMOTE-5 only:
  - EXT-LAUNCHSITE (agent-harness#1787, agent-harness#1788, agent-harness#1789 and
    agent-harness#1790);
  - EXT-OPENSH: stock OpenShell v0.1.7, whose adoption is being prepared on the owner-controlled
    target. OpenShell qualification windows W1 and W5 re-run on it, and W2–W4 pass. These are
    agent-harness#1795's windows, distinct from SEATS W0 and W1;
  - ai-stack Unit 7, certificates and grants, and the image allowlist for each vendor image
    digest;
  - the Stage 2 proof amendment (SL-1.4) and the lane C packet approved under OD-7.

## Lane Index & Dependencies

SL-0 — Contract module and codes (preamble)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no

SL-1 — Vectors, validator, probe set and C5 (lane A)
  Depends on: SL-0, SL-3
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-2 — Credential table, proxy and link (lane B)
  Depends on: SL-0, SL-3
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-3 — Security-review packet and activation verifier (lane C)
  Depends on: SL-0
  Blocks: SL-1, SL-2, SL-5, SL-6
  Parallel-safe: yes

SL-4 — Remote review invocation and image targets (lane E)
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-5, SL-6
  Parallel-safe: yes

SL-5 — Rung integration, isolation and deactivation (lane D)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: SL-6
  Parallel-safe: no

SL-6 — Evidence, inventories and documentation reducer (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Contract module and codes (preamble)

- **Scope**: Publish the contract's pure types and the additive route codes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_remote_contract.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`
- **Interfaces provided**: `seat_remote_contract` record types for contract §1–§8; the IF-0-REMOTE-3 code entries
- **Interfaces consumed**: `seat_route_contract.CODES` (pre-existing), `OD10_CLASSES` (pre-existing), `REMOTE_DESCEND_CODES` (pre-existing); all three land with JAILCORE SL-0
- **Parallel-safe**: no

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-0.1 | test | — | Construct every record from valid and path-entered invalid data. Prove each §5 code has exactly one class, a fix line free of sealed, inline and key-based routes, and membership in `mode_line_codes()`. Prove `REMOTE_DESCEND_CODES` equals the two §5 members, and that `DESCEND_CODES`, `CAPACITY_CODES` and every pre-existing entry are byte-identical. | `V0` |
| SL-0.2 | impl | SL-0.1 | Add the frozen dataclasses and literals, plus additive entries only. | `V0` |

### SL-1 — Vectors, validator, probe set and C5 (lane A)

- **Scope**: Per-provider vectors, the vector map, the validator, the generic probe set, and both proof amendments.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_vectors.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/seat-provider-vectors.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/seat-vector-map.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/remote-probe-set.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/README.md`, `phase-loop-runtime/openshell-private-transport.md`, `phase-loop-runtime/tests/test_seat_remote_vectors.py`, `plans/evidence/seats-remote/request-sets/**`
- **Interfaces provided**: IF-0-REMOTE-1
- **Interfaces consumed**: `seat_remote_contract` (SL-0); `openshell_worker.stock_policy_digest` and the stock field inventory (pre-existing); `policies.json` (pre-existing); `PiRoutedIdentity` (pre-existing after PI)
- **Parallel-safe**: yes

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.1 | test | — | Path-enter the real files and assert no findings. Each mutation must yield a finding: a field outside `network_policies`, AUDIT, PASSTHROUGH, `allow_uninspected_credentials: true`, an extra L7 rule, `allow_uninspected_credentials` not false, an empty or multi-path `binaries`, each listed field set, a second provider's host in an entry, a duplicate provider, a stale digest, an edited baseline digest, and a map row naming a missing provider. Hash `policies.json`, `policy-digests.json` and `full-remote-pi-runner` before and after. | `V1` |
| SL-1.2 | evidence | — | For each vendor, measure the guest-direct request set with the CLI's API base on the relay and record metadata only. | request-set records |
| SL-1.3 | impl | SL-1.1, SL-1.2 | Author the vectors, the map and the probe set per contract §1–§2, and implement `validate`. | `V1` |
| SL-1.4 | docs | SL-1.3 | Amend C5 in the placement README. Amend the Stage 2 activation-proof text so that its no-egress and no-exposure claim covers Stage 2's own vectors only and names the reservation bridge for seat reservations. | `V1` |

### SL-2 — Credential table, proxy and link (lane B)

- **Scope**: The IF-0-REMOTE-2 table, the per-seat requester credential proxy, the link and revocation.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_credentials.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_remote_link.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_remote_relay.py`, `phase-loop-runtime/tests/test_seat_remote_credentials.py`, `phase-loop-runtime/tests/test_seat_remote_link.py`, `plans/evidence/seats-remote/credential-scope/**`
- **Interfaces provided**: IF-0-REMOTE-2
- **Interfaces consumed**: `seat_remote_contract` (SL-0); `start_proxy(*, allowlist_id)`, `allowlist_ref`, `contains_secret` and the host credential lanes (pre-existing); `ForwardTcpUnixBridge` (pre-existing after PLACECLI and XR-1)
- **Parallel-safe**: yes

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Use a socketpair standing in for the bridge and the real proxy and link code. Prove the placeholder is accepted through `deadline + 60s` and refused after that instant, plus these refusals: a non-placeholder bearer, a refresh-matcher request and a host credential in any downlink encoding, each ending typed. Prove a scope above evidence and an API key without an OD-7 reference are refused before reserve. Prove a missing allowlist yields `seat_egress_allowlist_missing`. Prove an unknown frame, an oversize frame and the per-connection and overall bounds. Prove `revoke()` is idempotent and invalidates the placeholder, and that no frame ever carries the renewal token. | `V2` |
| SL-2.2 | evidence | — | Measure each vendor's base-URL and placeholder behaviour and its credential scope, and record metadata only. A vendor with no record stays `unsupported`. | scope records |
| SL-2.3 | impl | SL-2.1, SL-2.2 | Implement the table, `open_session`, the proxy, link, relay and revocation. | `V2` |
| SL-2.4 | verify | SL-2.3 | Once XR-1 holds, rerun SL-2.1 against the real v13 bridge descriptor from a fake coordinator. | `V2` |

### SL-3 — Security-review packet and activation verifier (lane C)

- **Scope**: The private EC-REMOTE-3 packet, its public receipt, and the activation checks the rung calls.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_activation.py`, `phase-loop-runtime/tests/test_seat_remote_activation.py`, `plans/evidence/seats-remote/security-review-receipt.json`
- **Interfaces provided**: `load_activation`, `activation_digests`, `verify_owned(receipt, evidence, provider)`, `verify_third_party(record, digests)`, `seat_remote_review_receipt.v1`
- **Interfaces consumed**: `seat_remote_contract` (SL-0); the JAILCORE §6 receipt rules (pre-existing), the overlay file checks (pre-existing)
- **Parallel-safe**: yes

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | evidence | — | Write the EC-REMOTE-3 packet in the operator-private store. It covers every item EC-REMOTE-3 lists, records the proxy-held choice (contract §4), and reviews IF-0-REMOTE-3. Commit only its receipt. | receipt digest |
| SL-3.2 | test | — | Path-enter real files. Prove the following are refused: an unsafe or malformed activation file (ignored, not trusted), an expired receipt, a receipt bound to another target or class, a receipt or evidence whose probe-set digest differs from the installed probe set's, evidence that does not re-hash, evidence missing the provider or any probe id and origin row, and a third-party capacity entry without a current receipt. For third-party, prove that changing each bound digest or version flips the verdict; the digested files are temporary packaged copies. Prove an owner-controlled entry binds no digest list. | `V3` |
| SL-3.3 | impl | SL-3.2 | Implement the verifier per contract §6–§7. | `V3` |

### SL-4 — Remote review invocation and image targets (lane E)

- **Scope**: The trusted per-vendor invocation through IF-0-LANEEXEC-1, the probe runner and the per-vendor image targets.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_invocation.py`, `phase-loop-runtime/images/review-runner/Containerfile`, `phase-loop-runtime/tests/test_seat_remote_invocation.py`
- **Interfaces provided**: `run_remote_seat`, `run_probe_set`, `INVOCATIONS`, `seat_remote_result.v1`
- **Interfaces consumed**: `seat_remote_contract` (SL-0); IF-0-REMOTE-1; IF-0-REMOTE-2; IF-0-LANEEXEC-1, `JailProfile.argv` and `config_surface`, `seat_tool_evidence` and `leg_exec_record` (pre-existing)
- **Parallel-safe**: yes

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-4.1 | test | — | Run against the v13 fake coordinator and the real launch service, building the argv from the real profile builder. Prove the following: one launch per seat; the exact template under `landlock-exec`; placeholder-only home; upload masks equal to `planted_paths`; a result without a staged-tree read not admitted; output with a planted credential ending typed; a vendor deactivated between admit and exec yielding `seat_remote_deactivated` with nothing run; lost-after-launch and release-unconfirmed each calling `revoke()`; and release on every exit. The Containerfile test proves each vendor target adds only its CLI and the relay, and that the `landlock-exec` stage bytes are unchanged. | `V4` |
| SL-4.2 | impl | SL-4.1 | Implement the invocation, the probe runner and the image targets. Image pushes stay with the owner and ai-stack. | `V4` |

### SL-5 — Rung integration, isolation and deactivation (lane D)

- **Scope**: `SeatRemoteRung` at the JAILCORE construction site, per-seat isolation, the operator CLI and the tested deactivation path.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_remote_rung.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_seat_remote_rung.py`, `phase-loop-runtime/tests/test_seat_remote_cli.py`, `phase-loop-runtime/tests/test_panel_invoker.py`
- **Interfaces provided**: `SeatRemoteRung`, `phase-loop seat-remote status|deactivate|probe`
- **Interfaces consumed**: `seat_route.resolve` (pre-existing), `INACTIVE_REMOTE_RUNG` (pre-existing), both after JAILCORE; IF-0-PLACECLI-1 and IF-0-PLACECLI-2 (pre-existing after PLACECLI); IF-0-REMOTE-1, IF-0-REMOTE-2, `verify_owned`, `verify_third_party`, `run_remote_seat` and `run_probe_set`
- **Parallel-safe**: no

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-5.1 | test | — | Drive `seat_route.resolve` through the real construction site, the placement console entry and a fake coordinator, covering each of the following. Each R0–R6 failure yields its code, and nothing is reserved before R5. For each of `at_capacity` and `unreachable`, the walk descends to native fill, and each other R5 outcome resolves degraded. A wrong workload, target, kind, client, image digest, policy vector, policy digest, provider list, bridge or `egress_sha256` releases, then resolves degraded. The packaged default stays `INACTIVE_REMOTE_RUNG`-equivalent with no activation file. Two concurrent seats never share a reservation, sandbox, proxy session or bridge. `deactivate` turns the vendor off for the next admission. | `V5` |
| SL-5.2 | impl | SL-5.1 | Implement the rung. Make two narrow edits at the construction site: one rung per `resolve` call, and mode `remote` dispatching to `run_remote_seat`. Register the CLI group. | `V5` |
| SL-5.3 | verify | SL-5.2 | With XR-1 to XR-3 met, run SL-5.1 against the landed v13 entry, bridge and launch service. | `V5` |

### SL-6 — Evidence, inventories and documentation reducer (SL-docs)

- **Scope**: Docs, the matrix's remote rows, the inventories, and the activation-window record.
- **Owned files**: `docs/review-seats-readiness.md`, `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `plans/evidence/seats-remote/windows/**`
- **Interfaces provided**: the matrix's remote rows and the window record
- **Interfaces consumed**: IF-0-REMOTE-1, IF-0-REMOTE-2, IF-0-REMOTE-3, IF-0-REMOTE-4; `seat_remote_review_receipt.v1`
- **Parallel-safe**: no

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-6.1 | docs | SL-0, SL-1, SL-2, SL-3, SL-4, SL-5 | Document the remote rung, the codes, the activation file and the deactivation CLI. Update only `kind="remote"` and `remote-pending` rows in the matrix. Rescan the docs catalog. | `V6` |
| SL-6.2 | evidence | SL-6.1 | After LA-4, attach the owner's activation-window record. Only that PR flips a contract §1 entry or a matrix row to `done-remote`. | `VL1` |
| SL-6.3 | closeout | SL-6.2 | Emit `spec_delta_closeout.v1`. Missing or malformed evidence uses `terminal_status=blocked`, `verification_status=blocked` and `blocker_class=contract_bug`. | `V6` |

## Execution Notes

- **Order.** SL-0 starts once JAILCORE SL-0 has published `seat_route_contract.py`. SL-3.1 (the design packet) starts
  straight away from the frozen contract; SL-3.2–SL-3.3 follow SL-0. SL-1 and SL-2 start only
  after SL-3 lands with the owner-approved OD-7 receipt. SL-4 waits on LANEEXEC and XR-3. SL-5 waits on the JAILCORE
  resolver, PLACECLI and XR-1 to XR-3. Each of these is a non-human work-start gate
  (`blocker_class=upstream_phase_unmet`).
- **OD-7 order.** SL-1 and SL-2 land only after OD-7 approves the SL-3.1 packet and its receipt
  is committed (roadmap governance). That is why they depend on SL-3.
- **Inventories.** SL-6 owns the launch inventory and the scratch inventory entry by entry,
  following the FIRSTSEAT pattern. Each lane's change carries the entries for its own sites:
  - SL-2: the proxy and relay;
  - SL-4: the probe runner;
  - SL-5: the placement console entry.

  Those entries use existing roles, and no other entry changes. Each lane PR also runs DELEGATE
  steps 2–4.
- **Shared writers.**
  - `seat_route_contract.py` and its test take additive entries only, after JAILCORE, PI and
    CODEX; the second landing rebases.
  - The `panel_invoker.py` edits are limited to the two SL-5.2 sites. They rebase onto v11
    PANELSPLIT if it has moved them.
  - `cli.py` takes one subcommand group and shares the file with v13 PLACECLI SL-3; the second
    landing rebases.
  - REMOTE never edits `openshell_worker.py`, `sandbox_placement.py`, `policies.json`,
    `policy-digests.json` or any v13-owned file.
- **Disabled by default.** There is no activation file, no grant and no third-party target. No
  test enables a live route, and no fixture produces a receipt that a production path accepts.
- **OD-10.** The packet, probe evidence, receipts' private parts and any containment outcome stay
  in the operator-private store. Public text is limited to receipts, digests and codes.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/README.md`, `phase-loop-runtime/openshell-private-transport.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`
- evidence paths: `plans/evidence/seats-remote/security-review-receipt.json`, `plans/evidence/seats-remote/windows/**`
- redaction posture: `metadata_only`
- downstream handling: none

## Acceptance Criteria

- [ ] EC-REMOTE-1 — roadmap reference; proof: `V1` and IF-0-REMOTE-1.
  Falsifier: EC-REMOTE-1's roadmap falsifier, by reference, through the path-entered `V1` suite.
- [ ] EC-REMOTE-2 — roadmap reference; proof: `V2` and IF-0-REMOTE-2.
  Falsifier: EC-REMOTE-2's roadmap falsifier, by reference, through the path-entered `V2` suite.
- [ ] EC-REMOTE-3 — roadmap reference; proof: `V3` and `seat_remote_review_receipt.v1`.
  Falsifier: EC-REMOTE-3's roadmap falsifier, by reference, through the path-entered `V3` suite.
- [ ] EC-REMOTE-4 — roadmap reference; proof: `V5`.
  Falsifier: EC-REMOTE-4's roadmap falsifier, by reference, through the path-entered `V5` suite.
- [ ] EC-REMOTE-5 — roadmap reference; proof: `VL1` and `seat_remote_window.v1`.
  Falsifier: EC-REMOTE-5's roadmap falsifier, by reference, through the path-entered `VL1` suite.
- [ ] EC-REMOTE-6 — roadmap reference; proof: `V4`.
  Falsifier: EC-REMOTE-6's roadmap falsifier, by reference, through the path-entered `V4` suite.

## Verification

Run these serially, after the load and IO precheck, using `uv run --group test --python
/usr/bin/python3 -m pytest` or the managed runtime python:

```bash
P="timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q"
V0="$P phase-loop-runtime/tests/test_seat_remote_contract.py phase-loop-runtime/tests/test_seat_route_contract.py"
V1="$P phase-loop-runtime/tests/test_seat_remote_vectors.py"
V2="$P phase-loop-runtime/tests/test_seat_remote_credentials.py phase-loop-runtime/tests/test_seat_remote_link.py"
V3="$P phase-loop-runtime/tests/test_seat_remote_activation.py"
V4="$P phase-loop-runtime/tests/test_seat_remote_invocation.py"
V5="$P phase-loop-runtime/tests/test_seat_remote_rung.py phase-loop-runtime/tests/test_seat_remote_cli.py"
V6="$P phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py"
```

`VL1` is the owner's remote activation window (LA-4), which runs after every live gate:

- `phase-loop seat-remote probe` on each owner-controlled target produces evidence and a receipt;
- one admitted remote review per row the matrix routes remote;
- the window record lands through a reviewed PR (principle 5).

No full suite, `-n auto` or Gate A dispatch is part of this plan.
