# Phase roadmap BROWSER v1: browser and UI visibility for review seats

> # ADVISORY — not runner-selected (2026-11-08)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. This status grants no live run, no `ai` access and
> no ruling authority.

## Context

Review seats cannot see a user interface. The executor closeout already requires a
screenshot for UI diffs (`visual_evidence_path`, captured with claude-in-chrome or
Playwright via PMCP), but it only feeds a warn-by-default gate: no seat is given those
images, and no seat can re-observe the change independently.

The jail rules out the obvious fix. The J14 seccomp filter refuses nested user namespaces,
so Chromium's own sandbox cannot start in a seat. A seat's egress allowlist is exactly the
provider's measured traffic, so rendering a real app would mean widening the agent's own
exfiltration channel. A browser inside the seat is therefore not on this roadmap.

The repository already has most of the plumbing for the alternative:

- `SeatProfile.broker_socket` binds one checked unix socket into a sandbox-profile seat
  (`panel_invoker._seat_filesystem_view`, refusal `seat_broker_socket_unavailable`).
- The jail already strips separately checked, digest-bound dependency mounts before the
  profile comparison. That is the precedent for giving a jailed seat read-only inputs
  without requalification (Assumption 1).
- The planner vocabulary has `browser_automation`, reported as unavailable.
- The managed tooling releases ship a root-owned, version-pinned Playwright browser tree
  at `/opt/consiliency/browsers` (observed on dev0).
- v13 PLACECLI specifies a per-reservation 0700-directory, 0600-socket bridge for remote
  runners.

Thesis: keep every browser outside the seat in a broker we own, give the seat a small
typed tool surface over its socket, and make every result a plain file that T3 and a
standard Chrome can show. Start with no browser at all: deliver the executor's existing
screenshots to the seats. The contract (External Inputs) carries the detail.

## Architecture North Star

```
 executor (not jailed)                    host or ai, outside the jail
 claude-in-chrome | PMCP | T3 incognito   ┌──────────────────────────────────────┐
        │ visual_evidence_path            │ broker bwrap, own uid, own netns      │
        ▼                                 │  shim (tool allowlist, journal)       │
 phase-loop observation import            │   └─ stdio ─ Playwright MCP           │
        │ browser_observation.v1          │        └─ pipe CDP ─ headless shell   │
        ▼                                 │           (/opt/consiliency/browsers) │
 advisor-board --observation ──stage──┐   │  review-target egress proxy ──► app   │
                                      │   └──────────────▲───────────────────────┘
 jailed seat: /seat/review/visual ◄───┘                  │ 0600 socket, one per seat
 sandbox seat: <review>/visual                           │ (VISBROKER)
        └────────── /seat/out: browser_observation.v1 ◄──┘
                                      │
 board report: absolute paths ──► owner's T3 thread (inline) or Chrome
```

## Assumptions

1. The dependency-projection precedent extends to a read-only `/seat/review/visual/`
   projection without changing `jail_profile_digest` for any leg (contract §4.3). If this
   is false, VISART stops and routes a requalification amendment.
2. `/opt/consiliency/browsers` stays root-owned and read-only on every broker host, with
   the revision the tooling release's `playwright-core` pins. This was observed on dev0
   only; `ai` is unverified.
3. `@playwright/mcp` keeps a stdio transport and the tool names in contract §8.1. VISBROKER
   pins the version at planning.
4. Most review work needs observation (screenshot, accessibility tree, console errors), not
   live control. The phase order relies on this.

## External Inputs

| Input | Pin |
| --- | --- |
| BROWSER v1 contract | `plans/artifacts/browser-v1-contract.md`, sha256 `cd8cbb9c4140216dc07dbae910f63d5810d9cc238bceddb30d16a13ae5856a4e` |
| `browser_observation.v1` schema | `plans/artifacts/browser-v1-observation.schema.json`, sha256 `c5508465b49b87de775eda3e711ee5ef4727c6d5965ae4256a456575f2995080` |
| Research report (operator-held, not published) | `sandbox-browser-visibility-20261108/report.md`, sha256 `d6d0494f74d5df2c8dadc478fb5b5d60cacc2be6f0ff1794b8e97a99c8193fb3`. The contract restates every fact a phase relies on. |
| v13 placement contract | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, as pinned by `specs/phase-plans-v13.md` |
| Managed browser tree | `/opt/consiliency/browsers` with `playwright-core` 1.65.0 and `chromium_headless_shell-1254`, observed on dev0 2026-11-08; repinned at VISBROKER planning |

These are immutable planning inputs. A changed input needs a reviewed repin. No plan pins
a future implementation commit, commit count or landing topology.

## Owner Rulings (2026-11-08)

- **OR-1.** The seats' browser is our own broker, outside the jail. T3's preview is never
  the seats' backend, and no browser is ever put inside a seat.
- **OR-2.** The human viewer is T3 or a standard desktop or mobile Chrome. Broker output is
  plain, viewable files that T3 can also show inline.
- **OR-3.** Executors (non-sandboxed agents) may take screenshot evidence with T3 preview,
  on the `incognito` profile only.
- **OR-4.** Seat artifacts on `ai` are viewed through the linked `ai` T3 environment;
  copying them is the fallback.
- **OR-5.** No T3 delegation inside seats. T3 sandboxing is left alone.

## Open Owner Decisions

| ID | Decision | Default until ruled | Effect of the ruling |
| --- | --- | --- | --- |
| OD-1 | Will reviews always have a preview URL, or must the broker build and serve the reviewed tree? | VISBROKER accepts `review_target.kind: url` only; any other kind refuses `browser_target_kind_unsupported`. | "Build and serve" adds an app-runner phase after VISBROKER, in parallel with VISHARDEN, by roadmap amendment. "Always a URL" needs no change. |
| OD-2 | Is live interactive control against staging apps ever allowed, or only observe and scripted replay? | VISHARDEN ships `none`, `observe` and `replay`; `interactive` refuses `browser_policy_tier_unavailable`. | "Allowed" adds the interactive tools, a session time cap and the action-journal rules to VISHARDEN or a follow-on phase, by amendment. "Never" removes `interactive` from the vocabulary by amendment. |

Open questions (not blocking any phase):

- When a test account for the app under review is needed, is it injected broker-side on
  the credential-proxy pattern? This depends on OD-1 and OD-2.
- On `ai`, does the board run as the same uid as the linked T3 environment's user? If not,
  OR-4's copy fallback is the normal path there.

## External Readiness Gates

- **EXT-SEATSCODEX.** agent-harness#1916 (SEATS CODEX) has merged or been closed before
  VISART's jail and board lanes start implementation. It edits `panel_invoker.py`,
  `seat_jail.py`, `seat_profiles.py` and `sandbox_egress.py`. Planning is not gated.
- **EXT-OD.** OD-1 before any target kind other than `url`; OD-2 before `interactive`.
- **EXT-BROWSERTREE.** Assumption 2 holds on the broker host. Gates VISBROKER's live
  evidence and VISREMOTE.
- **EXT-PLACECLI.** v13 IF-0-PLACECLI-1 and IF-0-PLACECLI-2 are implemented and landed.
- **EXT-LANEEXEC.** v13 IF-0-LANEEXEC-1 is implemented and landed.
- **EXT-WORKER.** v12 IF-0-JOURNAL-1 and IF-0-WORKER-1 are implemented and landed. Their
  plans are in review in agent-harness#1925 and agent-harness#1926.

## Non-Goals

- Any browser inside a seat or a runner image, including the research's in-seat
  loopback-only headless shell.
- T3 preview or T3's `/mcp` as a seat backend, any seat path to the T3 server, T3
  delegation inside seats, and changes to T3 sandboxing (OR-1, OR-5).
- Raw CDP, Playwright `launchServer`/`run-server` endpoints, browserless or any other CDP
  service for seats.
- Routing seats to the PMCP gateway or to any host browser that holds operator logins.
- Firefox and WebKit engines.
- Native desktop and mobile UI (see Later Work).
- Broker-built targets and live interactive control until OD-1 and OD-2 are ruled.
- Planning around v13 or v12 before their interfaces land. VISREMOTE consumes them.

## Cross-Cutting Principles

1. **Browser outside, tools inside.** A seat reaches a browser only through its own socket
   and a fixed, typed, argument-checked tool list. It never holds CDP.
2. **Plain files are the product.** Every artifact is a `browser_observation.v1` directory
   of plain files and a script-free `index.html`, viewable in T3 and in standard Chrome.
3. **Two egress policies, never merged.** A seat's provider allowlist digest never
   changes. The browser has its own review-target allowlist, whose digest every broker
   observation records.
4. **The jail profile is not edited silently.** Any visibility feature that would change
   `jail_profile_digest` stops and routes a requalification amendment.
5. **No logged-in browser.** Broker profiles are ephemeral. Executors use T3 preview on
   `incognito` only. No seat reaches a browser or gateway that holds operator identity.
6. **Executor evidence is a claim.** Staged executor screenshots are labelled claims.
   Independent observation starts with VISBROKER.
7. **Fail closed, typed.** Every refusal is a closed code from the contract or the phase's
   frozen gate, before any seat is spent where possible.
8. **Offline before live.** Fakes and fixtures establish behaviour; live evidence is
   runner-stamped later. Proxy evidence requires a roadmap amendment before any plan
   treats it as a gate verdict.
9. **Machine-checkable plans.** Each phase plan has an effective `automation.suite_command`
   and validates through IF-0-VC-2.
10. **Shared-host test limits.** Targeted serial pytest (never more than `-n 2`) under
    `timeout`. Full suites and live runs go to CI, Gate A or a phase's live evidence step.
    Tests leave no browser running.

## Top Interface-Freeze Gates

- IF-0-VISART-1 — `browser_observation.v1`: the pinned schema, the file rules, the
  deterministic `index.html` and the closed refusal codes (contract §2, §3, §7).
- IF-0-VISART-2 — Review-input staging: stage layout, `visual_stage_sha256`, per-route
  delivery, the jail projection under `/seat/review/visual/` and the bundle appendix
  (contract §4).
- IF-0-VISART-3 — `phase-loop observation validate|import`, `advisor-board --observation`
  and the board report's `visual_evidence` block (contract §5).
- IF-0-VISBROKER-1 — Broker seat protocol: the observe tool allowlist, argument rules,
  socket lifecycle, journal line and refusal codes.
- IF-0-VISBROKER-2 — Broker launch posture: browser tree, Playwright MCP flags, pipe CDP,
  ephemeral profile, review-target allowlist kind and digest, caps and teardown.
- IF-0-VISHARDEN-1 — Review-profile `browser` field and its `browser_automation` mapping.
- IF-0-VISHARDEN-2 — Replay step vocabulary and replay result.
- IF-0-VISHARDEN-3 — Broker identity and sandbox posture: uid, bwrap, AppArmor and one
  browser process per seat session.
- IF-0-VISREMOTE-1 — Remote broker channel over the per-reservation bridge, with pool
  capacity accounting.

## Phases

### Phase 1 — Observation artifacts and seat staging (VISART)

**Objective**

Define `browser_observation.v1` and deliver executor-captured observations read-only to
every local review seat and to the owner's T3 view. No browser runs anywhere in this phase.

**Exit criteria**

- [ ] EC-VISART-1 — `phase-loop observation validate` accepts a directory exactly when it conforms to the pinned schema and contract §2–§3; every refusal is one closed code from contract §7, proven by positive fixtures and one negative fixture per code.
- [ ] EC-VISART-2 — `phase-loop observation import` turns `visual_evidence_path` images into a valid executor observation with a deterministic `index.html`; `--tool t3_preview` without `--profile incognito` refuses `observation_profile_forbidden`, and no browser is launched or contacted.
- [ ] EC-VISART-3 — `phase-loop advisor-board --observation DIR` stages a copy per contract §4.1. Each local seat route in contract §4.2 receives it read-only at its review-input root's `visual/`, and jailed seats at `/seat/review/visual/`. The bundle carries the §4.4 appendix. An invalid observation exits 2 before any seat launch.
- [ ] EC-VISART-4 — `jail_profile_digest(leg)` and every seat egress allowlist digest are unchanged for every leg. A jailed launch with visuals has the same `actual_profile_digest` as without. A destination outside `/seat/review/visual/`, an unsealed memfd or a stage that changed after staging refuses.
- [ ] EC-VISART-5 — The `advisor-board` result's `visual_evidence` block lists each observation's host label, absolute directory and `index.html` paths, manifest sha256 and `visual_stage_sha256`, and every leg records `visual_delivered`. The remote route records `visual_delivered: false`.
- [ ] EC-VISART-6 — The execute skills name T3 preview on `profileId: "incognito"` as a capture source beside claude-in-chrome and Playwright via PMCP, and direct `observation import` plus `--observation`. Regenerated bundles and launch-spec goldens match their sources.

**Scope notes**

- Decompose into 5 lanes: an observation-contract preamble; jail projection and staging;
  board delivery, CLI and report; executor guidance and skill regeneration; and a
  dependent documentation reducer. The lanes own disjoint files.
- Single-writer files: `seat_jail.py` (projection lane); `panel_invoker.py` and `cli.py`
  (board lane).
- Implementation of the jail and board lanes waits for EXT-SEATSCODEX. The contract
  preamble and guidance lanes do not.
- Do not edit `agy_qualification.ROUTE_CORE` files.

**Non-goals**

Any browser process; seat-originated observations; delivery to remote seat routes; runner
wiring that passes a closeout's `visual_evidence_path` to the board automatically.

**Key files**

- `plans/artifacts/browser-v1-contract.md`
- `plans/artifacts/browser-v1-observation.schema.json`
- `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`
- `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json`
- `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `skills-src/codex/codex-execute-phase/SKILL.md`
- `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`
- `docs/browser-observation.md`

**Depends on**

- (none)

**Produces**

- IF-0-VISART-1 — `browser_observation.v1` schema, file rules, `index.html` and refusal codes.
- IF-0-VISART-2 — Review-input staging, jail projection and bundle appendix.
- IF-0-VISART-3 — Observation CLI, board flag and report block.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
(seat view), `docs/browser-observation.md`; evidence paths:
`plans/evidence/browser/VISART.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 2 — Local observe-only browser broker (VISBROKER)

**Objective**

A review seat gets an independent screenshot, accessibility snapshot and console summary of
an allowed review target from a host-side broker that it reaches only through its own
socket. The broker writes a broker `browser_observation.v1`.

**Exit criteria**

- [ ] EC-VISBROKER-1 — The shim exposes exactly the contract §8.1 allowed tools. Every other tool, every denied flag and every `file:`, `data:`, `javascript:` or `chrome:` target refuses with a closed code before reaching Playwright MCP. Each call writes one journal line.
- [ ] EC-VISBROKER-2 — The broker runs Playwright MCP headless and isolated from `/opt/consiliency/browsers`, with pipe CDP, an ephemeral profile, downloads denied and no TCP listener. A writable or non-root-owned browser tree refuses.
- [ ] EC-VISBROKER-3 — All browser traffic crosses a broker-side proxy with a review-target allowlist kind. Redirects and subresources to unlisted hosts fail at the proxy. Private ranges and host loopback are denied after resolution. The observation records `egress_allowlist_sha256`.
- [ ] EC-VISBROKER-4 — Each seat gets its own 0600 socket in a 0700 directory, bound only into that seat. The seat's provider allowlist digest is unchanged, and no seat route reaches the PMCP gateway.
- [ ] EC-VISBROKER-5 — `review_target.kind: url` is accepted; any other kind refuses `browser_target_kind_unsupported` while OD-1 is open.
- [ ] EC-VISBROKER-6 — The broker runs under `seat_resource_caps` limits. After seat exit, crash or timeout, no broker or browser process, socket or profile directory remains.
- [ ] EC-VISBROKER-7 — Operational evidence: one review seat records an independent observation of a preview URL, as runner-stamped evidence.

**Scope notes**

- Decompose into 5 lanes plus docs: shim and tool filter; launcher and process lifecycle;
  review-target allowlist kind in the srt proxy machinery; seat binding; observation
  writer and evidence.
- Seat binding: the sandbox-profile route uses `SeatProfile.broker_socket`. The
  `seat_jail_v1` owner argv has no socket slot, so the plan chooses a digest-bound
  projection (VISART precedent) or a requalified profile, under maintainer review.
- The broker runs as the operator in its own bwrap. It is not used on shared hosts until
  VISHARDEN.
- Plannable now. Single-writer: `panel_invoker.py` (seat-binding lane).

**Non-goals**

Input tools, replay, the dedicated uid, remote runners, app runners.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_broker_shim.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `docs/browser-broker.md`

**Depends on**

- VISART

**Produces**

- IF-0-VISBROKER-1 — Broker seat protocol, tool allowlist, journal line and refusal codes.
- IF-0-VISBROKER-2 — Broker launch posture, review-target allowlist kind, caps and teardown.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `plans/artifacts/browser-v1-contract.md` (repinned §8.1 freeze),
`docs/browser-broker.md`, `advisor_board/CONTRACTS.md`; evidence paths:
`plans/evidence/browser/VISBROKER.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 3 — Broker hardening and browser policy tiers (VISHARDEN)

**Objective**

Make the broker safe for shared hosts and put browser access under review-profile policy.

**Exit criteria**

- [ ] EC-VISHARDEN-1 — The broker runs as a dedicated non-operator uid in its own bwrap. Chromium starts with its own sandbox, using an AppArmor profile where unprivileged user namespaces are restricted. A host where that sandbox cannot start refuses; nothing falls back to `--no-sandbox`.
- [ ] EC-VISHARDEN-2 — Every seat session gets its own browser process. Contexts are shared only among seats of one review, and a cross-review share refuses.
- [ ] EC-VISHARDEN-3 — Review profiles carry `browser: none|observe|replay|interactive`, defaulting to `none`. `browser_automation` is true only when a broker is attached, and unknown values refuse.
- [ ] EC-VISHARDEN-4 — `replay` runs a declarative step list from contract §8.2 with no seat in the loop and no script execution, and returns a pass/fail result plus a broker observation.
- [ ] EC-VISHARDEN-5 — `interactive` refuses `browser_policy_tier_unavailable` while OD-2 is open.

**Scope notes**

- Decompose into 4 lanes plus docs: uid, bwrap and AppArmor; session isolation; profile
  field and capability gate; replay runner. The replay lane consumes the profile lane's
  vocabulary as a day-1 intra-phase freeze.
- Single-writer: `seat_profiles.py` (profile lane).

**Non-goals**

Interactive tools; running Playwright specs from the reviewed tree (that is code execution
and belongs with an OD-1 app runner); remote runners.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_replay.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_host_admin.py`
- `deploy/`
- `docs/browser-broker.md`

**Depends on**

- VISBROKER

**Produces**

- IF-0-VISHARDEN-1 — Review-profile `browser` field and `browser_automation` mapping.
- IF-0-VISHARDEN-2 — Replay step vocabulary and replay result.
- IF-0-VISHARDEN-3 — Broker identity and sandbox posture.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `advisor_board/CONTRACTS.md`; evidence paths:
`plans/evidence/browser/VISHARDEN.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 4 — Pooled remote broker on ai (VISREMOTE)

**Objective**

Seats on remote runners use a pooled broker on `ai`, reached through a PLACECLI-style
per-reservation bridge. Runner images stay browser-free.

**Exit criteria**

- [ ] EC-VISREMOTE-1 — The broker runs on `ai` as a pooled service with its own allowlisted image digest. Each reservation gets one browser channel through a 0700-directory, 0600-socket bridge scoped to it, with no public listener, torn down on release.
- [ ] EC-VISREMOTE-2 — Browser sessions count in PLACECLI headroom gates. At capacity the request refuses typed, with no fallback after admission.
- [ ] EC-VISREMOTE-3 — Broker session lifecycle and journal use the v12 JOURNAL and WORKER records; no second journal format exists.
- [ ] EC-VISREMOTE-4 — Remote seat observations reach a path the linked `ai` T3 environment can read, or the documented copy fallback, and the board report says which.
- [ ] EC-VISREMOTE-5 — The `pi-runner` image recipe is unchanged.
- [ ] EC-VISREMOTE-6 — Operational evidence: one remote seat records a broker observation on `ai`, as runner-stamped evidence.

**Scope notes**

- Decompose into 4 lanes plus docs: pooled service and image; bridge channel; capacity
  accounting; journal and report integration.
- Plan only after EXT-PLACECLI, EXT-LANEEXEC and EXT-WORKER interfaces are frozen;
  implement only after they land. Do not plan around them.

**Non-goals**

Changing PLACECLI, LANEEXEC, JOURNAL or WORKER contracts; E2B; native UI.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/`
- `docs/browser-broker.md`

**Depends on**

- VISHARDEN

**Produces**

- IF-0-VISREMOTE-1 — Remote broker channel and pool capacity accounting.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `docs/placement-process-cli.md`; evidence paths:
`plans/evidence/browser/VISREMOTE.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

## Later Work (not phased in v1)

Native UI comes after v1, behind the same broker interface (contract §8.4): Electron
through Playwright's `_electron` first, then headless Wayland (`cage` or `sway`) with
screenshots and virtual input, then mobile through `agent-device` (Callstack, MIT) on device
hosts. Adding it needs a new roadmap or an append.

## Phase Dependency DAG

```
VISART ──> VISBROKER ──> VISHARDEN ──> VISREMOTE
                                         ^
         EXT-PLACECLI, EXT-LANEEXEC, EXT-WORKER
```

- The chain is serial because each phase freezes what the next one hardens: the artifact,
  then the broker protocol, then the identity and policy posture remote use needs.
- An OD-1 "build and serve" ruling adds an app-runner phase after VISBROKER, parallel with
  VISHARDEN.
- Critical path: VISART → VISBROKER → VISHARDEN → VISREMOTE.

## Execution Notes

- **Planning commands:** `/claude-plan-phase specs/phase-plans-browser-v1.md <ALIAS> --output plans/phase-plan-v1-browser-<ALIAS>.md`.
- **Concurrency:** VISBROKER can be planned now, in parallel with VISART's execution; its
  §8.1 design freezes at its planning. VISHARDEN is planned after the VISBROKER plan
  freezes IF-0-VISBROKER-1 and -2. VISREMOTE waits for its external gates.
- **Single-writer files across phases and roadmaps:**
  - `panel_invoker.py`: VISART, then VISBROKER, then VISHARDEN. SEATS CODEX
    (agent-harness#1916) and AGYROLL REQUAL and EXECADMIT (agent-harness#1927) also edit it;
    serialize by landing order.
  - `seat_jail.py`: VISART, then VISBROKER if it chooses a projection. agent-harness#1916
    also edits it.
  - `seat_profiles.py`: VISHARDEN only. agent-harness#1916 also edits it.
  - `cli.py`: VISART, then any phase adding a command.
  - `plans/manifest.json` and `specs/roadmap-status.json`: every planning PR, including
    agent-harness#1925, agent-harness#1926 and agent-harness#1927. Conflicts are
    mechanical rebases.

## Acceptance Criteria

- [ ] A UI change's executor screenshots reach every local review seat read-only and the owner's T3 thread, with no change to any jail profile digest or seat egress digest.
- [ ] A review seat can independently observe an allowed preview URL through the broker, with no browser in the seat and no path to CDP, T3 or the PMCP gateway.
- [ ] Every artifact opens in T3 and in standard desktop and mobile Chrome without a viewer service.

## Verification

```bash
cd phase-loop-runtime
timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_browser_observation_contract.py tests/test_seat_visual_staging.py \
  tests/test_seat_jail_visual_projection.py tests/test_board_visual_delivery.py \
  tests/test_cli_observation.py
phase-loop validate-roadmap ../specs/phase-plans-browser-v1.md
```

Later phases add their own targeted tests. Operational evidence comes from
EC-VISBROKER-7 and EC-VISREMOTE-6, in `plans/evidence/browser/`, runner-stamped.
