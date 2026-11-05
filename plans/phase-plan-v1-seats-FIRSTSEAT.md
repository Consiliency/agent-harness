---
phase_loop_plan_version: 1
phase: FIRSTSEAT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 82efbc23a19b62044e2e8252d90a0124a1c0b5d2cc6ae2180259f63dd2941ca3
automation:
  suite_command:
    - 'timeout'
    - '600'
    - 'env'
    - 'PYTEST_ADDOPTS='
    - 'python3'
    - '-m'
    - 'pytest'
    - '-n'
    - '0'
    - '-p'
    - 'no:cacheprovider'
    - '-q'
    - 'phase-loop-runtime/tests/test_seat_jail.py'
    - 'phase-loop-runtime/tests/test_sandbox_egress.py'
    - 'phase-loop-runtime/tests/test_advisor_board_composition.py'
    - 'phase-loop-runtime/tests/test_president_heartbeat_1001.py'
    - 'phase-loop-runtime/tests/test_panel_invoker.py'
    - 'phase-loop-runtime/tests/test_grok_sandbox_seat_approval.py'
    - 'phase-loop-runtime/tests/test_seat_jail_qualification_entry.py'
    - 'phase-loop-runtime/tests/test_seat_qualification_host_context.py'
    - '-k'
    - 'seats_firstseat_'
---

# FIRSTSEAT: First Live Seat and a Terminating Board

## Context

Root phase of Consiliency/agent-harness#1820; acceptance is exclusively
EC-FIRSTSEAT-1 through EC-FIRSTSEAT-7. No other SEATS phase gates its start.
This plan owns agent-harness#1729, agent-harness#1821, agent-harness#1822 and
agent-harness#1823 through their roadmap ECs. Close them when those ECs hold.
TEAMHOST retains ownership of shared host issues whose reproduced portions lane A fixes.

OD-11 is decided: preserve `heartbeat_only` without a silence kill. Only `bounded`
receives the no-output bound. W1 uses `bounded`. All other roadmap non-goals,
principles and owner decisions remain binding.

This is a governed-PR execution plan, not permission to dispatch the phase-loop
runner. The interim `superseded` registration remains until agent-harness#1824;
v11 stays selected. That repair changes roadmap bytes and requires re-pinning
live plans. Coordinate shared modules with v11 PANELSPLIT and REVIEWTRUTH and
with CLAUDE before editing; if paths move, amend ownership before execution.
No future commit identity, count or topology is prescribed.

## External Inputs

- `specs/phase-plans-seats-v1.md`, pinned above, including its External Inputs,
  principles 1–8, OD-10, OD-11 and LA-1 through LA-3.
- Implementation refreshes against current main and rechecks the pinned input contracts.
- The Grok tool-surface probe (EC-FIRSTSEAT-4) follows OD-10 and CONTRIBUTING.md's
  private reporting route.
- Existing `review_policy_for_tier`, `_validate_review_board_policy`,
  `compose_review_board_report`, `PresidentInvoke`, `stage_review_tree`,
  `seat-sandbox qualify` and `seat-egress install` are the construction sites.

## Interface Freeze Gates

- [ ] IF-0-FIRSTSEAT-1 — Freeze the roadmap-defined schema in
  `docs/review-seats-readiness.md`; lane E owns its publication and final reduction.
- [ ] IF-0-FIRSTSEAT-2 — Freeze the roadmap-defined window record in
  `plans/evidence/seat-qualification/README.md`. Proposed entrypoint:
  `phase-loop seat-window qualify --window W1 --monitoring-policy bounded`;
  `phase-loop seat-window verify --window W1` validates retained metadata offline;
  `phase-loop seat-window export --window W1` is the only public writer.
  All three use the same versioned record, and qualify selects all candidate
  rows on the host, not a vendor-specific procedure. Each host/account record
  requires `containment` (credential scope, refresh detection, planted-config
  outcomes) and observed `egress` (allowed/refused proxy requests, direct DNS/IP
  controls), with evidence digests. Static `egress_evidence()` is insufficient.
- [ ] IF-0-FIRSTSEAT-3 — Freeze the roadmap-defined exec record in
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`.
  Lane D supplies the day-one contract; lane E publishes it before implementation.
  Freeze each leg's parent-observed auth probe and structured turn/verdict signals;
  absent signals are unavailable, never inferred from review text. For Grok's plain
  output, require independent host auth corroboration; text alone cannot classify auth.
  D freezes the per-leg sources: Claude's subscription-auth probe, Codex's login-status
  probe, and new parent-side Gemini/Grok auth-state adapters outside the staged tree.
  Each yields signed-out, healthy or unavailable; missing/ambiguous observations
  yield unavailable. Freeze their invocation/result contracts before implementation.
  Agree typed outcome mapping with v11 IF-0-REVIEWTRUTH-1 before freezing;
  that pending interface is coordination, not a dependency on v11 completion.
- [ ] IF-0-FIRSTSEAT-4 — Freeze composition refusal and president start/terminal
  event shapes at the existing construction sites. Use unchanged landing-policy
  requirements; persist start before waiting, with attempt identity joining its
  terminal record. Declare a finite no-output setting for `bounded` within the
  existing 1800-second ceiling; reject unset, non-finite, non-positive or larger
  bounds. Keep `heartbeat_only` semantics under OD-11. President records inherit
  IF-0-FIRSTSEAT-3 storage, scanning and closed-field rules; raw detail/exception
  text stays only in private logs.
- [ ] IF-0-FIRSTSEAT-5 — Lane A's containment-supplier contract (amendment
  2026-11-04, agent-harness#1829). Pinned method inputs, under
  `plans/evidence/seat-jail-1132/`: `probe_p3_agy_tools.py`
  (`51eced4937fe5a1c6f4b6dd72aad72daed60fd486adcff958f9f374bc624c552`), its record
  `p3-agy-tools-workspace.json`
  (`24c9bc9169b27cbfa452fca6734341f1cec974ed9c03e906e4554e0af1a54d4d`), `probe_p4.py`
  (`68002edcefb9d66fe1eefb1c03cbd8ec61497a83af2756405d1dc07f5cb84ceb`) and
  `probe_p4_containment_egress.py`
  (`4f866e4f6cea84823a1a14d341a3cca1f9bebb3ddf77285e220d34c655c53910`), with records
  `p4-agy-d7-credential.json`
  (`121ef9386e1412d30d4d5b202a7b73b59e07dbd8679b1c4ac2425f25ab97b035`) and
  `p4-containment-egress.json`
  (`997844005a24e7c35d93943e91f45efe52ce81562e159b27e4274dce032799e0`). They fix
  the method only. Their results belong to earlier images and are never W1 evidence.
  - Plants: one committed qualification input, staged through the approved-stage path,
    plants every loader path in P3's `PLANT` set and its recorded control `tree_opened`
    list, plus the current `WINDOW_PLANT_PATHS`. Workspace/VCS markers and P3's read
    marker are excluded, and a directory entry gets one file inside it. Each plant is a
    valid instance of its role with a unique nonce. A command it names is an inert
    executable plant, and an MCP plant also names an unlisted canary URL. Roles:
    settings/config files are `project_settings`; `hooks.json` is `hooks`; MCP
    configuration is `mcp_servers`; every other loader entry (context, rules,
    workflows, skills, agents, plugins) is `provider_overrides`, which covers agy's
    customization discovery. When the admitted image's measured help lists `plugin`,
    a plugin plant must first pass that image's `plugin validate <copy> --strict --json`.
    It runs from the sealed image, on a separate copy, before observation starts, and
    needs zero error or warning findings and nonzero hooks, mcpServers, rules and skills
    counts. This report is the only CLI self-report used; it proves format, never loading.
  - Definition (the `definition_probe` result): a surface is defined only when a
    control launch observes at least one of its plants opened. The control uses the
    same sealed image digest, the same jail shape, a stage with an equal manifest
    digest, and P3's control argv, which makes the tree the workspace. It runs first
    credential-free, with no route off the host. Any surface still undefined gets one
    credentialed control in W1. A constant, a fixture or documentation never defines a
    production surface.
  - Load result: each W1 context's measured jailed leg runs the same input on the
    unchanged production argv. A defined surface is `not_loaded` only if the complete
    watch sees no open of any of its plants during the whole leg, and no proxy
    observation names its canary host. Any such open or canary request is `loaded`
    (OD-10), including an open caused by a tool step. An undefined surface, an incomplete
    watch, a digest mismatch, an error or a timeout is `unavailable`.
  - Credential scope and refresh (W1 only): `credential_scope` comes from a
    parent-side issuer measurement of the exact delivered copy. It must be a subset of
    the set measured in the pinned P4 record; anything else is
    `gemini_seat_token_scope_excess`. The in-jail projection check stays a shape check.
    The trusted probe's unlisted control request targets the provider token endpoint
    and must appear refused in complete proxy observations. Any other token-endpoint
    request is `gemini_seat_token_refreshed_in_jail`. `refresh_detection` also needs no
    credential events, an unchanged copy digest and P4's expired-copy control. Any
    missing channel makes the field `unavailable`.
  - Binding: results bind the image, admission-class and help digests, the manifest
    and plant-layout digests, both argv digests, and the watch, proxy and validator
    digests. A non-admitted image makes every field `unavailable`.
  - Offline proof (V-A): a fixture image opens a surface's plants only under the
    control argv. Five mutants must each fail the field they target: a constant
    definition, a control argv equal to production, a missing surface plant, a watch
    armed after launch, and a scope derived inside the jail.
  - Split: lane A completes on code and these controls. The credential-free control is
    the only real-image offline step; it is a provider-free E host step and gates no
    lane. Load results, credentialed controls, scope and refresh are EC-FIRSTSEAT-7
    containment fields in IF-0-FIRSTSEAT-2 records, not EC-FIRSTSEAT-5 sub-claims. An
    `unavailable` field keeps the row `candidate`; only EC-FIRSTSEAT-7's OD-9 route
    applies.
- [ ] IF-0-VC-2 — Validate command argv with
  `phase_loop_runtime.verification_evidence.validate_verification_commands`.
  Run again after implementation for the new CLI forms; an unresolved executable,
  import error, empty test selection or timed-out check is not success.

Publish the first three interface agreements on day one, before implementation,
using these roadmap contracts as pre-existing inputs. This does not mark lanes
complete or assert live evidence. D/E's first tasks are this pre-implementation
freeze preamble, outside the lane-completion dependencies below. E publishes
schema/kit instructions immediately; its final evidence reduction waits for producers.
A/B/C lane completion requires code and offline checks only. D depends on their
code interfaces, never LA-1 or host evidence. E alone schedules live qualification.

## Lane Index & Dependencies

SL-0 — A: Gemini team-host path
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-1 — B: Composition outcomes
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-2 — C: President attempt lifecycle
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-3 — D: Leg evidence and integration
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — E: Window kit, matrix and documentation reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — A: Gemini team-host path

- **Scope**: Implement EC-FIRSTSEAT-5 at the existing Gemini jail and staging boundaries, and supply IF-0-FIRSTSEAT-5 for EC-FIRSTSEAT-7's W1 containment fields.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`, `phase-loop-runtime/tests/test_sandbox_egress.py`, `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_review_stage_binding.py`
- **Ownership amendment (2026-11-04):** `seat_egress/proxy.mjs` is owned only to emit metadata-only request-observation events (method, host, templated path, decision) to its Python wrapper. Its allow/deny decisions, allowlist and readiness protocol stay byte-for-byte unchanged in behaviour, and existing egress tests must pass unmodified.
- **Interfaces provided**: `gemini_teamhost_route`, IF-0-FIRSTSEAT-5.
- **Interfaces consumed**: IF-0-FIRSTSEAT-1 (pre-existing roadmap contract), IF-0-FIRSTSEAT-2 (pre-existing roadmap contract), `stage_review_tree` (pre-existing), `seat-sandbox qualify` (pre-existing).
- **Parallel-safe**: yes.
- **Tasks**:
  - test: Add `seats_firstseat_teamhost` cases in `test_seat_jail.py` entering
    actual jail construction and staging with a promisor checkout and private
    umask. Assert staging stays offline, refuses missing blobs unless previously
    materialized by the trusted host, strips remote/promisor configuration and
    binds the reviewed head. Perturb the bind/route after proving entry.
  - test: Add `seats_firstseat_resolver` in `test_sandbox_egress.py`, entering
    actual resolver creation/bind under private umask in the uplink namespace;
    prove seat-uid readability and fail with the unreadable-mode mutation.
    Separately prove Gemini's proxy namespace denies direct DNS and raw public IP
    while allowlisted proxied requests succeed. Never add an uplink or DNS forwarder;
    this route's DNS falsifier means failure of the proxied provider request.
  - test: Add `seats_firstseat_teamhost_containment` (selected by V-A), entering the
    measurement code with fixture providers that load each planted surface, or show
    excess scope, a refresh, an unlisted request or no proxy traffic. Each must fail
    its own field; a clean fixture is the path-entered control. A constant-pass
    measurement must fail these cases, which run without a user namespace.
  - impl: Extend `seat_jail_qualification.py` to produce the per-context W1
    measurements: staged planted project settings, hooks, MCP servers and provider
    overrides must not load; remeasure credential scope, in-jail refresh detection,
    unlisted-endpoint refusal and observed proxy traffic, per IF-0-FIRSTSEAT-5.
    E runs these on live hosts.
  - impl: Salvage only reproduced host fixes, including the resolver portion of
    agent-harness#1623. Supply panel call-site requirements to lane D. Track any
    qualification-key change as `candidate` for W1; do not use a heartbeat route
    to conceal a failed jail. Preserve profile-digest ownership until handoff to TEAMHOST.
    D hands the notice vocabulary to A during the freeze preamble; A alone edits
    `seat_jail.NOTICES`. D's preamble first lands the new codes' literals in
    `panel_invoker._HARNESS_DETAIL_CODES`: `test_seat_notices.py` requires every
    notice code there, so A's rows cannot land first. Add nothing to
    `SEALED_FALLBACK_CODES` or the descend list.
    V-A and V-D prove new notices launch no later route.
  - verify: Run V-A and V-R offline; hand the qualification implementation to E.
    Host administration, managed release, provider-free host proofs and W1 do not
    gate A's code completion or D's board repair.

### SL-1 — B: Composition outcomes

- **Scope**: Implement EC-FIRSTSEAT-1 without changing production policy requirements.
  Coordinate composition outcome/validation functions with v11 PANEL and ROUTE:
  no concurrent same-function edits; the second landing rebases, without waiting
  for either phase's completion.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`
- **Interfaces provided**: `composition_outcome`.
- **Interfaces consumed**: `compose_review_board_report` (pre-existing), `review_policy_for_tier` (pre-existing).
- **Parallel-safe**: yes.
- **Tasks**:
  - test: Add `seats_firstseat_composition` replay cases for the incident and each
    missing required seat; invoke production composition and landing validation.
    Include an admitted control proving the policy path was entered.
  - impl: Return the typed composition outcome and fix information; hand its
    panel integration to lane D. Keep the required seats, independence, floors
    and ladder invariant. Policy refusals remain distinct from board failures.
  - verify: Run V-B; export replay metadata and the policy-invariance comparison.

### SL-2 — C: President attempt lifecycle

- **Scope**: Implement EC-FIRSTSEAT-2 across the existing president routes.
  Coordinate `PresidentInvoke` lifecycle/supervision edits with v11 ROUTE:
  no concurrent same-function edits; the second landing rebases, with no phase gate.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/tests/test_president_heartbeat_1001.py`
- **Interfaces provided**: `president_attempt_lifecycle`, `president_rung_inventory`.
- **Interfaces consumed**: `PresidentInvoke` (pre-existing), IF-0-FIRSTSEAT-4 (pre-existing plan contract).
- **Parallel-safe**: yes.
- **Tasks**:
  - test: Add `seats_firstseat_president` cases with a controlled clock and silent
    transport, entering each real adapter route. Observe persisted start before
    release of the blocked transport, then bounded timeout/ladder advance. For
    `heartbeat_only`, advance beyond the bounded silence setting and release the
    healthy transport explicitly; assert no silence kill and a start entry.
    Check invalid bounds, planted tokens, process-group quiescence before ladder
    advance and rejection of late results joined to ended attempts.
  - impl: Add durable start/terminal attempt reporting and bounded no-output
    supervision, including brokered and native/sealed rungs already present.
    Supply shared monitor and call-site edits to lane D. Cancellation stays
    cancellation; add no route and remove no existing rung. Use the existing
    quiescence latch before advance and discard late results. Preserve the president's
    Grok delegation to `panel_invoker._exec_leg`; V-C proves that route is entered.
    D gates that shared launch path and proves the integrated gate with V-G;
    C's offline completion does not depend on D's implementation.
  - verify: Run V-C and the existing heartbeat regression file serially. Give lane
    E the runtime-named rung inventory, routes, tool modes, bounds and host scope.

### SL-3 — D: Leg evidence and integration

- **Scope**: Implement EC-FIRSTSEAT-3 and the Grok tool-surface probe (EC-FIRSTSEAT-4), integrating lanes A–C.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_grok_sandbox_seat_approval.py`
- **Interfaces provided**: `leg_exec_record`, `tool_probe_receipt`, `integrated_board_outcome`.
- **Interfaces consumed**: `gemini_teamhost_route`, `composition_outcome`, `president_attempt_lifecycle`, IF-0-FIRSTSEAT-3 (pre-existing roadmap contract).
- **Parallel-safe**: no.
- **Tasks**:
  - freeze: First, publish IF-0-FIRSTSEAT-3 through E, give A notice definitions and
    land their `_HARNESS_DETAIL_CODES` literals before implementation; no host action
    or producer completion gates this task.
  - test: Add `seats_firstseat_exec_record` at the real leg launch/return paths,
    including degraded and pre-launch paths, no-model-turn classification, host
    auth-state corroboration, hostile reviewed text, encoded planted tokens,
    size limits and operator-file permissions, for Claude, Gemini, Codex, Grok
    and pre-launch outcomes. Include unknown-secret and detector-error cases,
    tokens straddling truncation, tokens in prompts, planted symlinks, wide
    directories, foreign owners and staging exclusion. Auth-like text with nonzero
    exit, no turn/verdict and healthy host auth must produce a non-auth outcome.
    Fix lines must never recommend `XAI_API_KEY` or another API-key lane.
  - test: Add `seats_firstseat_tool_surface`: unprobed/inconclusive versions,
    timeout, empty/unparseable results, any probe diagnostic, changed binaries or
    argv, and non-passing tool sets launch nothing. A passing receipt launches
    through the actual gate. Cover brokered, non-brokered and president paths;
    fixtures use invented tool names. Verify every non-pass has identical public
    code/fix text and exposes no result-specific receipt or tool set.
  - impl: Integrate producer interfaces in the sole panel writer. Emit bounded
    records from closed fields only: argv flags are allowlisted and free-text
    values, including review prompts, omitted. Obtain credential scan inputs per leg;
    unknown secrets never mean clean. Scan before bounding, using credential-aware
    checks plus independent credential-pattern detection for legs without a known
    secret. On a hit, unavailable assurance or detector error, omit the field and
    retain a typed record. Never persist unscanned output.
    Store outside the repo in per-operator state: fstat-checked ownership and 0700
    directory, 0600 files, `O_EXCL|O_NOFOLLOW`; write failures are typed outcomes.
    Auth classification requires parent-probed signed-out host state outside the
    tree, nonzero exit and no turn/verdict. Forbid `_leg_failure_kind` as input;
    preserve canonical results and type unavailable evidence as non-auth.
  - impl: Place the Grok tool-surface probe (EC-FIRSTSEAT-4) outcome at the leg
    route, not composition: composition exclusion triggers backfill and can stop
    Gemini before launch. Follow OD-10 before any public record.
    One shared gate covers every Grok launch, including the president rung.
    Bind passing receipts to resolved binary digest and exact argv form; recheck
    immediately before launch. Provide a definition-only probe, run from an empty
    directory without a staged tree or tool execution. Every non-pass uses one
    public `grok_tool_surface_unverified` code/fix line; distinctions stay private.
    Offered tools appear in receipts only on a pass. Confirmed results take the
    private reporting route before any public record.
  - verify: Run V-D and V-G; replay B/C through the integrated native board and
    confirm the unchanged policy can admit W1 composition before any leg degrades.

### SL-4 — E: Window kit, matrix and documentation reducer

- **Scope**: Implement EC-FIRSTSEAT-6 and EC-FIRSTSEAT-7 and reconcile all producer evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `docs/review-seats-readiness.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `plans/evidence/seat-qualification/*`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-FIRSTSEAT-1, IF-0-FIRSTSEAT-2, IF-0-FIRSTSEAT-3.
- **Interfaces consumed**: `gemini_teamhost_route`, IF-0-FIRSTSEAT-5, `composition_outcome`, `president_attempt_lifecycle`, `president_rung_inventory`, `leg_exec_record`, `tool_probe_receipt`, `integrated_board_outcome`.
- **Parallel-safe**: no.
- **Tasks**:
  - freeze: First, publish IF-0-FIRSTSEAT-1/2 and D's IF-0-FIRSTSEAT-3 with kit
    instructions before implementation or host readiness; final synthesis alone
    waits for the lane DAG.
  - test: Add `seats_firstseat_window` to `test_seat_jail_qualification_entry.py`
    entering the CLI and all-candidate selector, and `seats_firstseat_w1_receipt`
    to `test_seat_qualification_host_context.py` entering the evidence verifier.
    Include two-account isolation, missing/co-seat disclosures, stale digests,
    incomplete host coverage and exception expiry. Require one missing/failed
    negative control per containment/observed-egress field; refuse `done-local`.
    Containment failures produce no public file. Export refuses hostnames, absolute
    paths, usernames and tokens; only reviewed closed-field passing metadata passes.
    Valid native-board receipts are the path-entered controls; fixture receipts
    test validation only and never stand in for W1.
  - impl: Add the frozen commands and canonical docs. Preflight all four vendors'
    `is_available` and `auth_ok` under EACH operator account before launching the
    plan-tier board. A composition refusal blocks that window attempt and routes
    LA-2 remediation; it is not a jail falsifier and cannot trigger OD-9.
  - impl: Prepare W1 with LA-1 host administration and managed released runtime,
    LA-2 logins and LA-3 attended runs. E owns provider-free qualification/egress
    installation and every live measurement supplied by A. Qualify writes only to
    private per-operator storage; a reviewed export alone writes public passing
    metadata. All containment, output-secret, refresh, egress or install-integrity
    failures follow OD-10: private record and owner summary, neutral `candidate`
    status without public reason. OD-9 security citations refer privately to records.
    Public account labels are opaque, never username hashes. W1 checks that the
    two real accounts cannot read each other's records; state plainly that 0600
    does not isolate an unconfined co-seat using the same operator identity.
    Parent-computed digests are captured as each leg ends. Bind records to observed
    runtime/profile/allowlist digests, board identity, tool receipts and review
    admission; never invent host readiness or owner actions. Reconcile vendor,
    remote and president rows from every producer; name exceptions and expiries.
    A later EC-JAILCORE-6 failure returns Gemini to `candidate`.
  - verify: Run V-E and V-W, execute the window command sequentially on the
    required operator/host contexts, then `phase-loop seat-window verify --window W1`.
    Publish reviewed metadata and update status only from validated evidence.

## Execution Notes

The roadmap prescribes `phase-plan-seats-v1-<ALIAS>.md`, which manifest `PLAN_RE`
rejects. Use the manifest-accepted `phase-plan-v1-seats-<ALIAS>.md` here;
`phase-plan-v1-<ALIAS>.md` collides with v1. A later roadmap erratum must reconcile
its banner/execution notes and re-pin plans; this repair preserves the pinned input.

Ownership is disjoint. A/B/C may run together only after machine-verified lane
safety and scheduler-owned worktree assignments; no same-function external writer
may overlap. D/E freeze publication precedes those waves; reducer writes follow
all producers. Verification commands remain serial on shared hosts.
Existing unrelated companion tests, frozen goldens, skills, dependency/lockfiles
and package indexes remain untouched: no new export or dependency is required.
Any discovered additional touch path requires an ownership amendment first.

## Verification

Use the project test environment with pytest-xdist available for explicit `-n 0`.
Set `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests"`
in the environment and clear `PYTEST_ADDOPTS`. On shared hosts, **no full or parallel suite and no `-n auto`**. Run each
command below serially as:
`timeout 300 python3 -m pytest -n 0 -p no:cacheprovider -q FILE -k SELECTOR`.

| Command | FILE under `phase-loop-runtime/tests/` | SELECTOR (new; zero collection required before implementation) |
|---|---|---|
| V-A | `test_seat_jail.py` | `seats_firstseat_teamhost` |
| V-R | `test_sandbox_egress.py` | `seats_firstseat_resolver` |
| V-B | `test_advisor_board_composition.py` | `seats_firstseat_composition` |
| V-C | `test_president_heartbeat_1001.py` | `seats_firstseat_president` |
| V-D | `test_panel_invoker.py` | `seats_firstseat_exec_record` |
| V-G | `test_grok_sandbox_seat_approval.py` | `seats_firstseat_tool_surface` |
| V-E | `test_seat_jail_qualification_entry.py` | `seats_firstseat_window` |
| V-W | `test_seat_qualification_host_context.py` | `seats_firstseat_w1_receipt` |

Check `uptime` and `/proc/pressure/io` first; skip collection on a degraded host.
Otherwise collect each selector using the table argv unchanged plus `--collect-only`,
including `-n 0`, `-p no:cacheprovider` and cleared `PYTEST_ADDOPTS`, serially
(agent-harness#1825). Zero selected with exit 5 is expected before implementation;
collection errors or skipped collection are not zero-collection proof.
After adding tests, require nonzero collection and behavioral RED before fixes,
then GREEN. The combined new-test suite is the frontmatter command; its expected
pre-implementation selection is also zero. Existing regression checks use only these explicit files,
one at a time with `timeout 300` and `-n 0`: `test_president_heartbeat_1001.py`,
`test_advisor_board_composition.py`, `test_gemini_seat_egress_1170.py`,
`test_review_stage_binding.py`, `test_sandbox_egress.py`, `test_seat_notices.py`.
Hosted CI and hosted Gate A own full-suite
verification; do not run `make check-full` or unscoped pytest locally.

Provider-free host commands: `timeout 300 phase-loop seat-sandbox qualify` and
`timeout 300 phase-loop seat-egress install`. W1: execute the frozen qualify
command sequentially on team-host account 1, team-host account 2 and one standard
host, `timeout 7200` each. Run A's planted-config and containment/observed-egress
measurements (IF-0-FIRSTSEAT-5) in every context; outer timeout is failed evidence, never a typed-success
substitute. Offline W1 verify:
`timeout 300 phase-loop seat-window verify --window W1`.

V-G is offline gate coverage, not an installed-version probe. E adds the proposed
`timeout 300 phase-loop seat-window probe-tools --vendor grok` command to the kit;
D supplies its probe implementation. It records installed version, binary digest,
argv and observed definitions privately under the gate rules above; no frozen
version list substitutes for measurement. E owns the CLI wiring.

Only explicitly reviewed passing exports live under
`plans/evidence/seat-qualification/`; raw records and failure evidence stay private.
Attach validated metadata through the reviewed window PR and the
runner-stamped verification/closeout amendment mechanism if later runner-selected.
Proxy evidence requires a roadmap amendment; it cannot satisfy W1. Plan and
implementation reviews follow principle 2: native first, then the authorized T3
fallback, exact-head cross-vendor review, six required checks and hosted Gate A.
These reviews and all live actions are future gates, not performed by this planner.

## Acceptance Criteria

Each proof uses the referenced construction site with the lane's path-entered
control. The roadmap supplies the criteria and falsifiers; these are proof mappings.

- [ ] EC-FIRSTSEAT-1 — proven by `V-B` plus integrated replay, falsified by its path-entered negative replay at `compose_review_board_report` / `_validate_review_board_policy`.
- [ ] EC-FIRSTSEAT-2 — proven by `V-C`, falsified by its path-entered silent-transport control at `PresidentInvoke` under OD-11.
- [ ] EC-FIRSTSEAT-3 — proven by `V-D`, falsified by its path-entered hostile-input and record-boundary controls in `panel_invoker.py`.
- [ ] EC-FIRSTSEAT-4 — proven by `V-G`, `V-C` and the installed-version `seat-window probe-tools` command, falsified by its path-entered leg-route control; OD-10 governs private evidence.
- [ ] EC-FIRSTSEAT-5 — proven by `V-A`, `V-R` and E's provider-free host commands, falsified by path-entered host controls in `seat_jail.py` / `stage_review_tree`.
- [ ] EC-FIRSTSEAT-6 — proven by `V-E` and `phase-loop seat-window verify --window W1`, falsified by path-entered matrix/kit negative controls at the new CLI construction site.
- [ ] EC-FIRSTSEAT-7 — proven by `V-W` and W1's `phase-loop seat-window verify --window W1`, falsified by path-entered receipt controls and the roadmap's live falsifiers; offline GREEN alone cannot close this item.

The only alternative exit is the roadmap's EC-FIRSTSEAT-7 / principle 6 OD-9
mechanism. Lane A must land and LA-1 be done or recorded impossible; the owner
must cite a qualifying failed host falsifier and record the interim route.
Apply exactly the EC-FIRSTSEAT-7 waiver: EC-FIRSTSEAT-1 through EC-FIRSTSEAT-4
and EC-FIRSTSEAT-6 stay required; only Gemini `done-local` evidence is waived,
plus EC-FIRSTSEAT-5 when its own falsifier is cited. Shared artifacts remain required.
A stall count or failed composition preflight grants nothing. No live gate is assumed met.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/review-seats-readiness.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/seat-qualification/*`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing or malformed evidence is a non-human `contract_bug`, not a reason to
claim delivery. Carry owner/live gates explicitly until observed. No runtime
selection or registry change is included in this phase.
