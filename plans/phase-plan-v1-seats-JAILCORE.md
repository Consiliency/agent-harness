---
phase_loop_plan_version: 1
phase: JAILCORE
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_egress_allowlists_jailcore.py", "phase-loop-runtime/tests/test_seat_qualification_key.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_route.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_qualification_host_context.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_seat_jail_autoqualify.py", "phase-loop-runtime/tests/test_gemini_seat_egress_1170.py", "phase-loop-runtime/tests/test_sealed_seat_never_counts.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_seat_resource_caps.py"]
---

# JAILCORE: Jail Profile Registry and Route Resolver

## Context

This plan covers roadmap Phase 3 (JAILCORE) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Exit criteria are EC-JAILCORE-1 to EC-JAILCORE-6, cited by ID only. The
roadmap is advisory (OD-1) and the runner refuses it, so lanes land as governed PRs under
principle 2. The file name follows the canonical manifest form used by the landed FIRSTSEAT,
INVENTORY and CLAUDE plans.

**Frozen artifact.** `plans/seats-jailcore-route-contract.md` is normative for the profile
fields, the resolver walk, the descend list, route codes, the qualification key, the route
policy and per-provider egress, at sha256
`235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`. This plan points at its
sections (§1–§8) and does not repeat them. CODEX, GROK, PI, CLAUDENET and REMOTE plan against that file in parallel straight away.

**Base (current main).** FIRSTSEAT L1–L5 and the CLAUDE lanes have landed. FIRSTSEAT lanes A,
D and E are finishing. The construction sites are:

- `seat_jail.decide_seat_route`, J7 steps 0–4, with `leg ==` branches;
- `seat_jail._owner_argv`, `seat_env`, `jail_profile_digest`, `actual_profile_digest` and
  `build_seat_jail`, each with Claude or Gemini branches;
- `seat_jail.SEALED_FALLBACK_CODES` and `JAIL_NOT_RUN_CODES`;
- `seat_jail.pass_record_verdict`, a v1 record keyed by profile digest, host and falsifier
  layout, written by `seat_jail_qualification`;
- `panel_invoker._seat_route_for_spawn`, plus the seat-mode builder that gives codex and grok
  `MODE_UNCONFINED` with `seat_filesystem_unconfined`;
- `seat_egress_proxy.start_proxy`, which takes one hard-wired Gemini allowlist and returns
  `unavailable_reason()` as free text;
- `seat_uid.seat_uid_available`, which conflates missing prerequisites with no free seat id;
- `claude_seat_transport.CODES`, the CLAUDE handoff: its OD-10 classes are JAILCORE input;
- `seat_window.readiness_rows()`, the named exceptions with expiry (FIRSTSEAT lane E);
- `leg_exec_record`, with its `auth_state` (IF-0-FIRSTSEAT-3).

**Execution gate.** Plan now; execute after FIRSTSEAT exits (roadmap scope note). Gemini's
profile is consumed as W1 left it. JAILCORE changes no profile digest and no allowlist bytes
(principle 4).

**Owner ruling (capacity, 2026-11-06).** Capacity offload is a policy input whose packaged
default is empty. An owner-controlled target may take a review seat only after L0-L8 pass,
`seat_local_capacity_exhausted` occurs, an explicit private host grant matches vendor and host
class, and one current generic egress-and-credential probe receipt binds the target. A
third-party target additionally requires that vendor's OD-7 activation. The ruling is folded
into this PR's roadmap amendment; no later plan or code amendment enables it.

**Owner ruling (resource caps, 2026-11-06).** Local sandboxes must not swamp a shared machine,
in CPU or in disk bandwidth ("Pressure gates + per-sandbox caps"). SL-5 owns the per-seat caps
half as an additive lane after SL-3. No other lane's scope, shape or test changes.
`plans/seats-jailcore-caps-contract.md` is normative for SL-5, at sha256
`b8278120e408786bdd3ad120ae51a9f3b70a28736ee2926220156098c875151c`. The route contract and its digest above are unchanged, and the roadmap is not edited, so
every pin of either stands. AC-7 is therefore a plan-local criterion. Pressure gates stay with
v13 (EC-PLACECLI-5 on agent-harness#1853). The owner accepted the caps contract §1 default caps
as written (2026-11-06).

## Interface Freeze Gates

- [ ] IF-0-JAILCORE-1 — the leg-profile contract, frozen in contract §1–§4 and published as
  `phase_loop_runtime/seat_route_contract.py` by SL-0. It covers:
  - `JailProfile` and its supporting shapes;
  - the registry API (`seat_profiles.register`, `profile_for`, `registered_legs`);
  - `seat_route.resolve(RouteRequest, *, policy, remote, native, capacity) -> RouteDecision`,
    with the `SeatCapacity`/`SeatLease` protocols; the decision owns the optional lease;
  - walk rules W1–W6;
  - the closed descend list: `seat_sandbox_unavailable_host`,
    `seat_sandbox_unavailable_tiocsti`, `seat_sandbox_unavailable_seat_uid` and
    `seat_egress_not_installed`;
  - `REMOTE_DESCEND_CODES = frozenset()` and `CAPACITY_CODES`;
  - the OD-10 security set;
  - the route-code table `seat_route_contract.CODES`;
  - `MODE_REMOTE`.

  Adding to either descend set is a security change and needs a security review.
- [ ] IF-0-JAILCORE-2 — per-provider egress, frozen in contract §7. It covers:
  - `allowlist_ref(id) -> AllowlistRef(id, content_digest, request_set, probe_rows)`;
  - `start_proxy(*, allowlist_id)`, one process and token per call. The review-seat entry point always enables and attests the fail-closed front, TLS termination and inner-SNI check. None is caller-disableable. A test-only helper may inject failed attestations but is not exported or used by a profile.
  - `EgressLayerUnavailable.code`;
  - `unavailable_code()`.

  Lane B owns the semantics. Its shapes ship in SL-0.
- [ ] IF-0-JAILCORE-3 (plan-internal) — the qualification key and route policy, frozen in
  contract §5 and §6. It covers `QualificationKey`, `key_digest`, `record_binding`, pass-record
  schema `seat_jail_pass.v2`, `RoutePolicy`, `NamedException`, `CapacityGrant`, the host overlay
  path and validation, and receipt schema `seat_remote_probe_receipt.v1`. Lane C owns the key's
  semantics. Its shape ships in SL-0.
- [ ] IF-0-JAILCORE-4 (plan-internal) — per-seat resource caps, frozen in
  `plans/seats-jailcore-caps-contract.md`. It covers the `seat_resource_caps.v1` record and its
  host sources (§1, §2), `readiness_code`, the route precondition (§3), `capped_popen`, the
  seat-start classification (§4), the refusal code (§5) and the v13 subset mapping (§6). SL-5
  owns it and ships it; the lanes in flight need none of it.

## Lane Index & Dependencies

SL-0 — Route contract module (lane A, day one)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no

SL-1 — Per-provider egress (lane B)
  Depends on: SL-0
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-2 — Qualification key and projection (lane C)
  Depends on: SL-0
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-3 — Registry, resolver and integration (lane A)
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4, SL-5
  Parallel-safe: no

SL-4 — Documentation and inventory reducer (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

SL-5 — Per-seat resource caps
  Depends on: SL-0, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Route contract module (lane A, day one)

- **Scope**: Publish IF-0-JAILCORE-1, IF-0-JAILCORE-2's shapes and IF-0-JAILCORE-3 as pure types and pure functions, with no behaviour change.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`
- **Interfaces provided**: IF-0-JAILCORE-1, IF-0-JAILCORE-2 (shapes), IF-0-JAILCORE-3; symbols `JailProfile`, `RouteDecision`, `RoutePolicy`, `SeatCapacity`, `SeatLease`, `OD10_CLASSES`, `QualificationKey`, `key_digest`, `record_binding`, `AllowlistRef`, `DESCEND_CODES`, `route codes`
- **Interfaces consumed**: `claude_seat_transport.CODES` (pre-existing), `seat_jail.NOTICE_CODES` (pre-existing)
- **Parallel-safe**: no (preamble)

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_seat_route_contract.py` | Literal equality of `DESCEND_CODES`, `REMOTE_DESCEND_CODES`, `CAPACITY_CODES` and the security set, against constants in the test. Every `CODES` entry has a class, non-empty what/why/fix and no fix line naming a sealed, inline or key route. `OD10_CLASSES` security members include the frozen §3 set and every security entry of `claude_seat_transport.CODES`. A `seat_route_contract.CODES` entry missing from `OD10_CLASSES` fails that module's import and this test. Equality of `OD10_CLASSES` with `mode_line_codes()` fails `seat_route` import, which SL-3.3 covers, because SL-0's module imports no `seat_jail`. `key_digest` changes when any `QualificationKey` field changes. `validate_route_policy` rejects an overlay that sets anything but `capacity_offload`, and rejects a wildcard vendor. The module imports no I/O module. | `V0` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | all SL-0 tests | `V0` |

### SL-1 — Per-provider egress (lane B)

- **Scope**: Generalise the host proxy to one process, one token and one allowlist per seat, split the egress-unavailable cause into typed codes, and refuse a non-terminating mode. Additive only: existing callers keep working until SL-3 switches them.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`, `phase-loop-runtime/tests/test_seat_egress_allowlists_jailcore.py`, `phase-loop-runtime/tests/test_sandbox_egress.py`, `phase-loop-runtime/tests/test_seat_egress_rules.py`
- **Interfaces provided**: IF-0-JAILCORE-2 implementation: `allowlist_ref`, `start_proxy(*, allowlist_id)`, `EgressLayerUnavailable.code`, `unavailable_code`, and `egress_evidence` with `allowlist_id` and `allowlist_digest`. The review-seat entry point always enables and attests the fail-closed front, TLS termination and inner-SNI check. None is caller-disableable. A test-only helper may inject failed attestations but is not exported or used by a profile.
- **Interfaces consumed**: `AllowlistRef` (SL-0), the egress code literals (SL-0)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seat_egress_allowlists_jailcore.py` | (a) `gemini-allowlist.json` bytes and content digest are unchanged from the base. Changing only `measured_and_refused` changes `content_digest` and the derived probe rows. (b) Two `start_proxy` calls give distinct processes and tokens. (c) A proxy started for a fixture allowlist A refuses a host listed only in fixture allowlist B, and an unlisted host, path-entered through the real `proxy.mjs`. (d) Every pre-launch `EgressLayerUnavailable` raise site, including `_node`, `verify_install`, `ensure_ca`, process spawn and readiness parsing/timeout, is path-entered and returns exactly the §3 code assigned above; no test classifies by exception text. (e) False or missing fail-closed-front, TLS-termination or inner-SNI attestation returns `seat_egress_tls_unterminated`, and the public review-seat API has no argument that disables any of the three. | `V1` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs` | — | — |
| SL-1.3 | impl | SL-1.2 | `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py` | — | — |
| SL-1.4 | verify | SL-1.3 | SL-1 files | all SL-1 tests | `V1` |

SL-1.3 adds no new behaviour. It only exposes the operator egress opt-out as a predicate SL-3
can refuse on. If one already exists, SL-1.3 records "no change". `proxy.mjs` changes only if
binding a token to one allowlist needs it.

### SL-2 — Qualification key and projection (lane C)

- **Scope**: Build the contract §5 key from live inputs, and admit a dependency projection for any profile by its declared requirement.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_qualification_key.py`, `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py`, `phase-loop-runtime/tests/test_seat_qualification_key.py`, `phase-loop-runtime/tests/test_executable_dependency.py`
- **Interfaces provided**: `key_for_launch`, `admit_profile_projection` (signatures: `key_for_launch(profile, *, variant, allowlist_digest, projection) -> QualificationKey`; `admit_profile_projection(profile, requirement) -> AdmittedExecutableDependency | None`)
- **Interfaces consumed**: `JailProfile`, `QualificationKey`, `key_digest`, `record_binding` (SL-0); `seat_jail.jail_profile_digest` (pre-existing), `falsifier_layout_identity` (pre-existing), `host_identity` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_seat_qualification_key.py` | For each key part (profile digest, allowlist digest, falsifier layout, projection digest, variant, host), two keys differing only there have different `key_digest` and different `record_binding`. A widened fixture allowlist changes the key. A switched Claude transport changes the key. Projection: `projection="none"` with a requirement is refused; `"required"` without one is refused; `"optional"` admits through the real `admit_executable_dependency` for a synthetic non-Claude leg. A key built from that changed refusal/probe layout refuses the old pass. | `V2` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_qualification_key.py`, `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 files | all SL-2 tests | `V2` |

`executable_dependency.py` changes only if the subject-generic path is missing for a non-Claude
subject, and it stays inside the agent-harness#1782 selected-subject contract.

### SL-3 — Registry, resolver and integration (lane A)

- **Scope**: Register the Claude and Gemini profiles digest-invariantly, replace J7 with the contract §2 walk, bind the v2 pass store, enforce the named exceptions, and wire every seat-route call site.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_autoqualify.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_route.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_jail_autoqualify.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_sealed_seat_never_counts.py`, `phase-loop-runtime/tests/test_seat_preflight_1204.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_codex_seat_tool_sandbox_1335.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/data/seat_jail_1132_sealed_golden.json`, `phase-loop-runtime/tests/data/seat_jail_1132_sealed_tui_session_golden.json`, `plans/evidence/seat-jailcore/**`, `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`
- **Interfaces provided**: `seat_profiles` registry, `seat_route.resolve`, `seat_route.load_route_policy`, `seat_route.mode_line_codes`, `INACTIVE_REMOTE_RUNG`, the native-fill rung adapter, the production `SeatCapacity` adapter, the profile-sourced window kit (`seat_window`), `MODE_REMOTE`, the v2 pass store, `python -m phase_loop_runtime.seat_profiles digest-receipt`
- **Interfaces consumed**: everything SL-0 provides; SL-1's `allowlist_ref`, `start_proxy(*, allowlist_id)`, `unavailable_code`, opt-out predicate; SL-2's `key_for_launch`, `admit_profile_projection`; `seat_window.readiness_rows()` (pre-existing); `claude_seat_transport.resolve_jailed_claude_transport` (pre-existing), `claude_seat_transport.CODES` (pre-existing); `leg_exec_record` (pre-existing, IF-0-FIRSTSEAT-3)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json` | On the unmodified base, capture `jail_profile_digest` for `claude` and `gemini` on x86_64 and aarch64, with `_system_mounts` pinned to a fixed list, into the data file. These are base outputs, recorded before any edit. After the refactor the same calls reproduce them. Mutation control: one changed bind breaks equality. No-branch check: an AST scan of `seat_route.py` and the core builders in `seat_jail.py` finds no comparison of a leg value to a string literal, paired with a synthetic third profile registered in a fixture that builds, digests and resolves with no core edit. EC-JAILCORE-6 declarations: every registered profile has `config_surface.closed`, a security `output_secret_code`, an `auth_probe` and containment fields (Claude: `deferred_to="EC-CLAUDENET-3"`). | `V3` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py` | — | — |
| SL-3.3 | test | SL-3.2 | `phase-loop-runtime/tests/test_seat_route.py` | See "SL-3.3 cases" below. | `V4` |
| SL-3.4 | impl | SL-3.3 | `phase-loop-runtime/src/phase_loop_runtime/seat_route.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_autoqualify.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | — | — |
| SL-3.5 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py` | Window kit made vendor-neutral: `seat_window`'s vendor gate and its per-vendor path rows are read from the registered `JailProfile.window`, not `vendor == "gemini"` literals. Gemini's records, matrix rows and exports are byte-identical on the FIRSTSEAT lane E base, against a golden captured before the edit. A synthetic profile's rows reach the kit with no kit-code edit. | `V3` |
| SL-3.6 | verify | SL-3.5 | SL-3 files, `plans/evidence/seat-jailcore/digest-equality.json`, `plans/evidence/seat-jailcore/terminal-codes.json` | all SL-3 tests; the digest receipt; `VL` on a jail-capable host | `V3`, `V4`, `V5`, `VL` |

**SL-3.3 cases.** Each is path-entered through `panel_invoker._seat_route_for_spawn` and the
seat-mode builder, with recording fakes for the remote and native rungs.

- (a) Every code in `mode_line_codes() - DESCEND_CODES` is injected at its step: no later rung
  is entered, the mode is `degraded` and the code is exact.
- (b) Each descend code walks R (`seat_remote_rung_inactive`), then N, then D.
- (c) Each `SEALED_FALLBACK_CODES` member on a review seat yields no `sealed` mode and builds
  no sealed argv (the agent-harness#1282 falsifier).
- (d) A post-launch terminal code never launches a second rung.
- (e) Exceptions: codex and grok are `unconfined` before expiry and degraded with
  `seat_route_exception_expired` after it (injected clock). Pi, opencode and cursor give
  `seat_profile_unregistered`. Claude with no allowlist runs under `open egress` before expiry
  and is degraded after it.
- (f) The egress split appears in the mode line.
- (g) No free seat id gives `seat_local_capacity_exhausted`, not a descend code.
- (h) Capacity gate: off by default. An unsafe overlay is ignored with
  `seat_route_policy_ignored`. A valid owner-controlled grant with a current receipt reaches
  the fake rung. A third-party grant reaches it only with that vendor's OD-7
  `activation_refs` (allowed after OD-7, ruling 2026-11-06), and without them it does not. An
  expired receipt does not.
- Hold every seat-id lease, resolve one more review, and prove it takes the capacity gate;
  release one lease and prove the next local decision holds that exact lease until teardown.
  Mutation control: an acquire/release availability probe before the real acquire fails.
- The current matrix's remote inventory rows do not route any candidate local vendor row
  remote. One vendor can be local on one host class and remote on another.
- A request/profile/readiness-row vendor mismatch, or a registered profile with no unique
  `kind="vendor"` row, is terminal `seat_route_identity_invalid`; no remote, native or
  exception path is entered. A leg with no vendor row and no profile, including opencode
  and cursor, stays `seat_profile_unregistered`.
- Importing `seat_route` fails when `OD10_CLASSES` keys differ from `mode_line_codes()`.
- (i) Store: a v2 pass under key K is refused under K′ for each part. A v1 record is not
  honoured.
- (j) `advisory_document`, `qualification_candidate` and `under_claude_code` keep their
  current routes.

**SL-3.4 implementation order.** Perform the steps below in this order. Commit boundaries are
executor-owned and may change under review, rebase or squash:

1. resolver and policy loader;
2. the `seat_uid` split and the v2 store reader and writer together;
3. auto-qualify keyed by `key_digest`;
4. `panel_invoker` call sites: route, mode line, launch gate, per-seat `start_proxy`, profile
   projection, and `seat_route_contract.CODES` added to `_HARNESS_DETAIL_CODES`;
5. the fix-line sweep of `seat_jail.NOTICES`, retiring "inline fallback" and "sealed route"
   wording and any fix that names those routes, without editing digests;
6. `JAILED_LEGS` derived from the registry.

**SL-3.6 VL.** VL runs the real CLIs provider-free on a host class with jail prerequisites:

- Gemini planted-config and planted-output falsifiers;
- Claude's planted-config falsifier per admitted transport;
- one jailed tool command refused for an unlisted host and for a fixture second provider's
  listed host.

If a planted config loads for Claude, SL-3 STOPs and reports the exact sentence to change.
The fix belongs to CLAUDENET (digest) or CLAUDE (transport argv), not here.

### SL-4 — Documentation and inventory reducer (SL-docs)

- **Scope**: Single writer of shared docs and inventories. Its tasks ride in each producer's landing PR; a final sweep runs after SL-3.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/manifest.json`, `plans/seats-jailcore-route-contract.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-JAILCORE-1, IF-0-JAILCORE-2, IF-0-JAILCORE-3, `route codes` (SL-0), `MODE_REMOTE` (SL-3)
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | per catalog | Per landing: inventory rows for any changed launch reference and an `[Unreleased]` CHANGELOG entry. After SL-3: CONTRACTS.md and the card describe the four rungs, the descend list, `MODE_REMOTE` (inactive), the route codes, the named exceptions and the capacity gate (shipped off). |
| SL-docs.3 | docs | SL-docs.2 | `plans/seats-jailcore-route-contract.md` | Append `### Post-execution amendments` only if a freeze proved wrong, by section and date. The roadmap is not edited here (see §8). |
| SL-docs.4 | verify | SL-docs.3 | — | `V6` and the hosted docs-freshness audit. |

### SL-5 — Per-seat resource caps

- **Scope**: Run every local seat launch in a per-seat transient cgroup carrying the host record's caps, and refuse typed when that cannot be proven. Seats never run uncapped, and there is no fallback.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps_enter.py`, `phase-loop-runtime/tests/test_seat_resource_caps.py`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `docs/seat-resource-caps.md`, `docs/TEAM-ONBOARDING.md`, `plans/seats-jailcore-caps-contract.md`
- **Interfaces provided**: IF-0-JAILCORE-4 implementation: `SeatResourceCaps`, `load_caps`, `caps_sha256`, `readiness_code`, `capped_popen`, and the additive code `seat_resource_caps_unavailable`
- **Interfaces consumed**: `OD10_CLASSES` (SL-0), `seat_profiles` registry (SL-3), `seat_route.resolve` (SL-3); `seat_uid.trusted_module_argv` (pre-existing), `seat_jail.pass_store_dir_problem` (pre-existing), `seat_jail.SeatSandboxRefused` (pre-existing), `sandbox_policy.staging_root` (pre-existing), `launch_provider` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | `phase-loop-runtime/tests/test_seat_resource_caps.py`, `phase-loop-runtime/tests/conftest.py` | Caps contract §7 cases (a)–(j), including the §1a tmpfs carve-out, on a fake cgroupfs, plus the opt-in host probe, which skips when delegation is absent. | `V7` |
| SL-5.2 | impl | SL-5.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps_enter.py` | — | — |
| SL-5.3 | impl | SL-5.2 | the named edits below; `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` | — | — |
| SL-5.4 | impl | SL-5.3 | `docs/seat-resource-caps.md`, `docs/TEAM-ONBOARDING.md` | — | — |
| SL-5.5 | verify | SL-5.4 | SL-5 files, the named edits | all SL-5 tests; `VC` on each host in the host gate | `V7`, `V4`, `V5`, `VC` |

Before SL-5.1, re-read the v13 IDs in caps contract §6. If one changed meaning, STOP and report
the exact sentence. `docs/seat-resource-caps.md` documents the record, its defaults, the sources,
the host prerequisite and the probe. `docs/TEAM-ONBOARDING.md` gains one pointer to it.

## Execution Notes

- **Critical path.** SL-0 lands first, on day one. SL-1 and SL-2 then run in parallel. SL-3
  starts SL-3.1–SL-3.2 on its branch at once, since they need only SL-0. It rebases onto SL-1
  and SL-2 before SL-3.3, and opens its PR after both merge. Downstream phases need only the
  contract file to plan, and it lands with this plan.
- **Single-writer files.** `seat_jail.py`, `panel_invoker.py`, `seat_preflight.py`,
  `seat_uid.py` and the qualification store modules belong to SL-3. `seat_egress_proxy.py`
  belongs to SL-1. `seat_route_contract.py` belongs to SL-0; later phases change it only by
  plan amendment, except the additive `OD10_CLASSES` entries for their own codes (below). `panel_invoker.py` is also written by TEAMHOST lane A and v11 PANELSPLIT;
  whichever lands second rebases. If PANELSPLIT has moved the seat-launch code, SL-3 edits
  the named successor modules and records the path change in its PR.
  `docs/review-seats-readiness.md` is read-only here. `seat_window.py` joins SL-3 for SL-3.5
  only; FIRSTSEAT lane E's landed code is its base.
- **TEAMHOST shared edits (agent-harness#1859, its contract §8).** TEAMHOST may edit only
  these named parts of JAILCORE-owned files, and nothing else in them:
  - `seat_uid.py`: `seat_runtime_dir`, plus one range-disjointness check in the L3
    prerequisite that JAILCORE splits from `seat_uid_available`;
  - `seat_jail_autoqualify.py`: `fix_for` only;
  - `seat_egress/proxy.mjs`: `clientHelloSNI`, `MAX_FIRST_RECORD`, the `front` connection
    handler with its `inspect` closure, and one config read for the idle bound;
  - the Gemini overlay: `GEMINI_WRITABLE_DOTDIR_DIRS` or its successor in the registered
    profile, plus `_gemini_binds` only where needed;
  - `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`: Gemini entries only.

  Whichever of JAILCORE and TEAMHOST lands second rebases.
- **SL-5 named edits (caps contract §3–§5).** Check (D) forbids shared ownership even across a
  dependency, so these files stay with SL-0 and SL-3. After SL-3 merges, SL-5 may edit only these
  named parts of them, and nothing else:
  - `seat_route_contract.py`: one `OD10_CLASSES` entry (class `ordinary`);
  - `seat_jail.py`: one `NOTICES` entry, plus one `JAIL_NOT_RUN_CODES` member if `SeatRoute`
    survives SL-3;
  - `seat_profiles.py`: `register` only;
  - `panel_invoker.py`: the `seat_caps` keyword on `launch_owned` and `launch_provider`, the
    jailed and owned `Popen` calls in `launch_provider`, the Capped sites in caps contract §4,
    and the code in `_HARNESS_DETAIL_CODES` only if SL-3's derivation does not already cover it;
  - the Claude SDK proof binding, coordinated with CLAUDE, which owns both `launch-v1.json`
    copies and `plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json`. When SL-5
    changes the capped SDK worker launcher (`_launch_claude_sdk_worker`), the same PR runs
    `test_seats_claude_sdk.py`, including byte identity and owned capture, and refreshes the SDK
    receipt's `proof_inputs_sha256` binding through CLAUDE's capture procedure. SL-5 edits no
    fixture byte and no `SDK_PROOF_REGIONS` name; a needed change there STOPs and is reported
    to CLAUDE.

  If PANELSPLIT has moved the seat-launch code, SL-5 edits the named successors, as SL-3 does.
  Its inventory, CHANGELOG and capability-doc rows ride its landing PR through SL-docs.2 (SL-4's
  per-landing rule), so SL-4's final sweep does not wait for SL-5. Check (M)'s warning on this is
  accepted: a `Depends on` edge would hold JAILCORE's closeout on the host gate below.
- **Host gate (SL-5).** Owner ruling, 2026-11-06: roll out by drop-in first, then enforce. SL-5
  merges only after the first host's `VC` passes and the caps contract §8 drop-in has been
  requested from `Consiliency/dotfiles`. Once SL-5 lands, a host lacking that prerequisite degrades
  every local seat. Mark SL-5 ready only after `VC` passes, not skips, on every host that runs
  review seats. This is an owner action outside this repository.
- **Interfaces downstream phases add.** Each later phase adds exactly the following, with no
  core edit:
  - CODEX, GROK and PI each add one `JailProfile` in `seat_profiles.py` and one
    `seat_egress/<id>-allowlist.json`, and its own `<leg>_seat_*` codes in `seat_jail.NOTICES`, each with one additive `OD10_CLASSES` entry; no existing entry or descend set changes.
  - CLAUDENET sets Claude's `allowlist_id` and containment fields.
  - CODEX, GROK, PI and CLAUDENET each add their profile's window rows as data only, under
    the same additive rule as their codes; the window kit's code does not change.
  - REMOTE replaces `INACTIVE_REMOTE_RUNG`, and fills `REMOTE_DESCEND_CODES` only under
    security review.
- **Known destructive changes**: none. Every lane is additive or an in-place refactor, and no
  file is deleted.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none. Consumers import `seat_route_contract` directly. No `__init__.py`
  changes, so no `__getattr__` lazy pattern is needed.
- **Worktree naming**: allocated by the executor; this plan names none.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see
  sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream
  dependency's merge>, it MUST stop and report rather than committing — the orchestrator will
  re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Shared-host limits.** Before each test command, check `uptime` and `/proc/pressure/io`.
  Run targeted files serially, with no `-n`, under `timeout 900`, using system python3.14.4
  for jail tests. The full suite runs only in hosted CI and Gate A.
- **Before Gate A, per lane.** Run:
  - the lane's own tests;
  - `test_agent_cli_scratch_inventory_1147.py`, `test_seat_launch_helpers_trusted.py` and
    `test_seat_reference_inventory.py`;
  - a clean-room tree check from the installed wheel, where repo-only tests skip.

  Then union-resolve `CHANGELOG.md`, `plans/manifest.json` and `tests/data` inventories, and
  dispatch Gate A.
- **OD-10.** Any containment or security finding found while executing is reported privately
  under the operator's private state, never in a PR, commit or test name.
- **Skill deviations (planning).** Reconnaissance and architecture ran in-thread rather than
  through Explore and Plan teammates, because the context was already gathered. The
  `advisor()` step is unavailable in this harness, so the plan goes to the cross-vendor
  review round instead. The SL-5 amendment ran the same way.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `plans/seats-jailcore-route-contract.md`, `plans/seats-jailcore-caps-contract.md`, `docs/seat-resource-caps.md`
- evidence paths: `plans/evidence/seat-jailcore/digest-equality.json`, `plans/evidence/seat-jailcore/terminal-codes.json`
- redaction posture: `metadata_only`
- downstream handling: `none` (the binding capacity ruling and its roadmap reconciliation land with this plan; packaged grants remain empty)

## Acceptance Criteria

- [ ] EC-JAILCORE-1 — proven by `V3` (`test_seat_profiles.py -k digest`) and by `plans/evidence/seat-jailcore/digest-equality.json` from `python -m phase_loop_runtime.seat_profiles digest-receipt` run on base and head on one host. Falsified by the one-bind mutation control passing, or by the synthetic third profile needing a core edit. Path-entered control: the mutation enters through the real `build_seat_jail` and `actual_profile_digest`.
- [ ] EC-JAILCORE-2 — proven by `V4` (`test_seat_route.py` cases a–d, f–h, the lease, matrix-reduction and identity cases after (h), and j). Falsified by any non-descend code entering a recording rung, or by a sealed mode for a review seat. Path-entered control: each code enters at its step through `_seat_route_for_spawn`.
- [ ] EC-JAILCORE-3 — proven by `V1` (`test_seat_egress_allowlists_jailcore.py`) and `VL`. Falsified by fixture allowlist A's proxy admitting B's host or an unlisted host, or by a profile with no allowlist launching outside its exception. Path-entered control: requests enter through the real `proxy.mjs` and the jailed tool command.
- [ ] EC-JAILCORE-4 — proven by `V2` (`test_seat_qualification_key.py`) and `V4` case i. Falsified by a pass honoured across any changed key part. Path-entered control: through `pass_record_verdict` on a private fixture store.
- [ ] EC-JAILCORE-5 — proven by `V4` case e. Falsified by Pi or any profile-less leg reaching `unconfined` outside an unexpired exception. Path-entered control: through the seat-mode builder and `_default_spawn` with an injected clock.
- [ ] EC-JAILCORE-6 — proven by `V3` (declarations), `V4` (output secret refusal through the real output read) and `VL` (planted config, real CLI). Falsified by a planted config marker appearing, or a planted credential in any `contains_secret` encoding not ending the leg typed. Path-entered control: the planted tree enters through `stage_review_tree`.
- [ ] AC-7 — proven by `V7` (`test_seat_resource_caps.py`, caps contract §7) and a passing `VC` on each host in the host gate. Falsified by a Capped site reaching raw `subprocess.Popen`, by a provider starting when a readback file is absent or differs, or by a record expressing no limit being accepted. Path-entered control: a fake cgroupfs and fake `systemd-run` enter through the real `launch_provider` and `_seat_route_for_spawn`.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, with
system python3.14.4 and file paths under `phase-loop-runtime/tests/`. On this plan-only
checkout the six new test files are absent, so these are pending selectors, not receipts.

- `V0`: `P test_seat_route_contract.py`
- `V1`: `P test_seat_egress_allowlists_jailcore.py test_sandbox_egress.py test_seat_egress_rules.py`
- `V2`: `P test_seat_qualification_key.py test_executable_dependency.py`
- `V3`: `P test_seat_profiles.py test_seat_jail.py test_seat_qualification_host_context.py`
- `V4`: `P test_seat_route.py test_seat_notices.py test_seat_jail_autoqualify.py test_seat_jail_qualification_entry.py test_gemini_seat_egress_1170.py test_sealed_seat_never_counts.py test_seat_preflight_1204.py test_codex_seat_tool_sandbox_1335.py`
- `V5`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`
- `V6`: `P test_seat_reference_inventory.py`, then `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_seat_profiles.py test_seat_route.py -k live_jail --junitxml=<private-receipt>`, provider-free, on a host class with jail prerequisites. A skip or zero collection fails.
- `V7`: `P test_seat_resource_caps.py`
- `VC`: `PHASE_LOOP_SEAT_CAPS_PROBE=1 P test_seat_resource_caps.py -k host_probe`, on a host that meets caps contract §8. It skips where delegation is absent; the host gate requires a pass.
- Full suite: hosted CI and dispatched Gate A only.
