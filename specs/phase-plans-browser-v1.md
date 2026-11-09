# Phase roadmap BROWSER v1: browser and UI visibility for review seats

> # ADVISORY — not runner-selected (2026-11-08)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. This status grants no live run, no `ai` access and
> no ruling authority.

## Context

Review seats cannot see a user interface. The executor closeout already requires a
screenshot for UI diffs (`visual_evidence_path`, captured with claude-in-chrome or
Playwright via PMCP). But that screenshot only feeds a warn-by-default gate: no seat is
given the image, and no seat can re-observe the change independently.

The jail rules out the obvious fix:

- The J14 seccomp filter refuses nested user namespaces, so Chromium's own sandbox cannot
  start in a seat.
- A seat's egress allowlist is exactly the provider's measured traffic. Rendering a real
  app there would widen the agent's own exfiltration channel.

A browser inside the seat is therefore not on this roadmap.

The repository already has most of the plumbing for the alternative:

- `SeatProfile.broker_socket` binds one checked unix socket into a sandbox-profile seat
  (`panel_invoker._seat_filesystem_view`, refusal `seat_broker_socket_unavailable`).
- `seat_uid.handoff` already hands a read-only subtree to a jailed seat without a new
  mount: the Gemini config goes to H-root:seat, with directories 0550 and files 0440.
- The planner vocabulary has `browser_automation`, reported as unavailable.
- The managed tooling releases ship a root-owned, version-pinned Playwright browser tree
  at `/opt/consiliency/browsers` (observed on dev0).
- v13 PLACECLI specifies a per-reservation bridge for remote runners: one 0700 directory
  and one 0600 socket per reservation.

Thesis:

- Keep every browser outside the seat, in a broker we own.
- Have the board drive that broker before seats launch.
- Later, give seats a small typed tool surface through a declared, requalified channel.
- Make every result a plain file that T3 and a standard Chrome can show.
- Start with no browser at all: deliver the executor's existing screenshots to the seats.

The contract (External Inputs) carries the detail.

## Architecture North Star

```
 executor (not jailed)                   board host, outside every jail
 claude-in-chrome | PMCP | T3 incognito  ┌───────────────────────────────────────┐
        │ visual_evidence_path           │ broker: own uid, own bwrap, no op home │
        ▼                                │  shim (tool allowlist, journal)        │
 phase-loop observation import           │   └─ stdio ─ Playwright MCP            │
        │ browser_observation.v1         │        └─ pipe CDP ─ headless shell    │
        ▼                                │  review-target egress proxy ──► app    │
 advisor-board --observation ─┐          └───────▲───────────────────▲───────────┘
                              │   board-driven render + frozen       │ declared,
                              │   replay before launch (VISRENDER)   │ requalified
                              ▼                    │                 │ slot (VISBROKER)
                stage (inert, digest-bound) ◄──────┘                 │
                 ├─ jailed: /seat/home/review-visual (H-root:seat, 0550/0440)
                 ├─ direct Claude: <review_dir>/visual (existing grant)
                 └─ native fill: native-fill/<id>/visual
 board result: absolute paths ──► owner's T3 thread (inline) or Chrome
```

The operator target policy (`preview_url` by default, `static_bundle`, or opt-in
`build_and_serve` in its own app-runner sandbox) decides what the broker may render. No
seat can choose or raise it.

## Assumptions

1. `build_seat_jail` creates the seat home fresh for each leg, and `seat_uid.handoff`
   owns it. So a read-only subtree under it can be re-owned to H-root:seat without a jail
   change, as the Gemini config already is (contract §4.3). If this is false, VISART stops
   and routes an amendment to a declared, requalified slot.
2. `/opt/consiliency/browsers` stays root-owned and read-only on every broker host, with
   the revision the tooling release's `playwright-core` pins. This was observed on dev0
   only; `ai` is unverified.
3. `@playwright/mcp` keeps a stdio transport and the tool names in contract §8.3.
   VISRENDER pins the version at planning.
4. Most review work needs observation (screenshot, accessibility tree, console errors), not
   live control. The phase order relies on this.

## External Inputs

| Input | Pin |
| --- | --- |
| BROWSER v1 contract | `plans/artifacts/browser-v1-contract.md`, sha256 `57aca5ee2a0c5b0389d80010fb0a7135c2b0de8a2569dc705e204726f127042a` |
| `browser_observation.v1` schema | `plans/artifacts/browser-v1-observation.schema.json`, sha256 `169c05daaa03788bdfe10fb3efa4a3fe31d3a58bbe1767826645ced4e3ec9a1d` |
| Research report (operator-held, not published) | `sandbox-browser-visibility-20261108/report.md`, sha256 `d6d0494f74d5df2c8dadc478fb5b5d60cacc2be6f0ff1794b8e97a99c8193fb3`. The contract restates every fact a phase relies on. |
| v13 placement contract | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, as pinned by `specs/phase-plans-v13.md` |
| Managed browser tree | `/opt/consiliency/browsers` with `playwright-core` 1.65.0 and `chromium_headless_shell-1254`, observed on dev0 2026-11-08; repinned at VISRENDER planning |

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

The owner decided the former open decisions on 2026-11-08, after the plan-tier board's
review. Contract §8.6 freezes their rules.

- **OR-6 (target source, formerly OD-1).** The target mode is operator-selectable and
  digest-bound. Its values are `preview_url` (the default), `static_bundle` and
  `build_and_serve`.
  - `preview_url` allows public or allowlisted preview origins only. Loopback, private
    ranges and the tailnet stay denied.
  - In `static_bundle`, the executor builds a static directory before the seat launches,
    and the broker serves it read-only.
  - `build_and_serve` is opt-in and off by default, and lands in its own later phase
    (VISBUILD) with its own sandbox and threat model. Untrusted PR code and install
    scripts never share the broker's or a seat's sandbox. VISBUILD does not block v1.
  - A seat can never choose or raise the mode.
  - *Board trade-off:* under `preview_url`, changes with no reachable allowlisted preview
    get executor screenshots only, and loopback, private and tailnet-only dev servers get
    nothing independent. `static_bundle` covers many of those without running PR code;
    `build_and_serve` covers the rest at the cost of a new sandbox and threat model.
- **OR-7 (interactive control, formerly OD-2).** v1 is observe plus frozen replay only.
  - `interactive` stays refused in v1. Replay steps are authored before the seat
    launches, and a seat-authored step counts as `interactive`.
  - A later phase (VISINTERACT) adds `interactive`, allowed only against disposable,
    per-review environments with throwaway test data and least-privilege accounts, and
    never against shared or persistent staging. It is gated on the disposable-environment
    mechanism (EXT-DISPOSABLE).
  - *Board trade-off:* v1 loses exploratory clicking, auth-flow probing and bug
    reproduction. In return, page-text prompt injection has no path to mutate shared
    state. Replay already needs disposable test state and least-privilege accounts.
  - *Placement:* the owner placed VISINTERACT "after VISHARDEN". Revision 2 merged
    VISHARDEN's hardening into VISRENDER and its session isolation and profile field into
    VISBROKER. VISINTERACT therefore follows VISBROKER, the last phase holding former
    VISHARDEN work, and it also needs VISBROKER's seat channel. The 2026-11-08 delta board
    reached the same equivalence independently, and the owner has not objected, so the
    placement stands.

Open questions (not blocking any phase):

- Which mechanism provides disposable per-review environments (EXT-DISPOSABLE)? VISBUILD's
  per-review app instances are one candidate.
- On `ai`, does the board run as the same uid as the linked T3 environment's user? If
  not, OR-4's copy fallback is the normal path there.

## External Readiness Gates

- **EXT-SEATSCODEX — satisfied.** agent-harness#1916 merged on 2026-11-08. It edited
  `panel_invoker.py`, `seat_jail.py`, `seat_profiles.py` and `sandbox_egress.py`, the docs
  and launch-reference inventory that VISART's SL-4 edits, and tests that SL-1 and SL-2
  run. VISART lanes branch from a main that includes it, and no lane is gated on it.
- **EXT-BUILDTM.** A reviewed, maintainer-approved threat model for building and running
  untrusted PR code and install scripts in the app-runner sandbox. It gates VISBUILD's
  planning.
- **EXT-DISPOSABLE.** A disposable-environment mechanism gives each review its own
  environment, with throwaway test data and least-privilege accounts. The environment is
  destroyed after the review and carries an attestation the broker can verify. This gates
  VISINTERACT's planning. VISBUILD's per-review instances are one candidate provider, and
  VISINTERACT's plan pins whichever interface is used.
- **EXT-BROWSERTREE.** Assumption 2 holds on the broker host. Gates VISRENDER's live
  evidence and VISREMOTE.
- **EXT-PLACECLI.** v13 IF-0-PLACECLI-1 and IF-0-PLACECLI-2 are implemented and landed.
- **EXT-LANEEXEC.** v13 IF-0-LANEEXEC-1 is implemented and landed.
- **EXT-WORKER.** v12 IF-0-JOURNAL-1 and IF-0-WORKER-1 are implemented and landed. The
  JOURNAL plan merged in agent-harness#1925; the WORKER plan is in review in
  agent-harness#1926.

## Non-Goals

- Any browser inside a seat or a runner image, including the research's in-seat
  loopback-only headless shell.
- T3 preview or T3's `/mcp` as a seat backend, any seat path to the T3 server, T3
  delegation inside seats, and changes to T3 sandboxing (OR-1, OR-5).
- Raw CDP, Playwright `launchServer`/`run-server` endpoints, browserless or any other CDP
  service for seats.
- Routing seats to the PMCP gateway or to any host browser that holds operator logins.
- Any mount projection or digest-stripping path into the jail (contract §8.1).
- Firefox and WebKit engines.
- Native desktop and mobile UI (see Later Work).
- `build_and_serve` and `interactive` in v1. They land in VISBUILD and VISINTERACT, off
  the v1 path (OR-6, OR-7).
- `interactive` against shared or persistent staging, in any phase.
- Planning around v13 or v12 before their interfaces land. VISREMOTE consumes them.

## Cross-Cutting Principles

1. **Browser outside, tools inside.** No seat ever holds CDP. A seat reaches a browser
   only through a declared channel (contract §8.1) and a fixed, typed, argument-checked
   tool list.
2. **Plain files are the product.** Every artifact is a `browser_observation.v1` directory
   of plain files and a script-free `index.html`, viewable in T3 and in standard Chrome.
3. **Two egress policies, never merged.** A seat's provider allowlist digest never
   changes. The browser has its own review-target allowlist, whose digest every broker
   observation records.
4. **Seat-channel rule (contract §8.1).**
   - Inert, sealed, digest-bound data may reach a seat through a view it already has,
     without requalification.
   - Any live channel (socket, FIFO, device, inherited fd), writable bind or new mount
     class is a declared, digest-covered, probe-attested slot, requalified for every leg.
   - No channel this roadmap adds is stripped from the profile digest. The existing
     stripping of qualified dependency mounts is outside this roadmap.
5. **No logged-in browser.** Broker profiles are ephemeral. The broker's bwrap holds no
   operator home and no credentials. Executors use T3 preview on `incognito` only.
   - **Operator chooses, seat cannot raise.** The target mode comes from digest-bound
     operator policy, and the tier from the review profile. Both are fixed before the
     seat launches. No seat-facing surface names either (contract §8.6).
6. **Page content is untrusted.** Pixels, accessibility YAML, console text and URLs are
   data, never instructions. Every seat route's trusted text says so, and says not to
   follow those URLs (contract §4.6).
7. **Executor evidence is a claim.** Staged executor screenshots are labelled as claims.
   Independent observation starts with VISRENDER.
8. **Fail closed, typed.** Every refusal is a closed code from the contract or the phase's
   frozen gate, before any seat is spent where possible.
9. **Offline before live.** Fakes and fixtures establish behaviour; live evidence is
   runner-stamped later. Proxy evidence requires a roadmap amendment before any plan
   treats it as a gate verdict.
10. **Machine-checkable plans.** Each phase plan has an effective
    `automation.suite_command` and validates through IF-0-VC-2.
11. **Shared-host test limits.** Targeted serial pytest (never more than `-n 2`) under
    `timeout`. Full suites and live runs go to CI, Gate A or a phase's live evidence step.
    Tests leave no browser running.

## Top Interface-Freeze Gates

- IF-0-VISART-1 — `browser_observation.v1`: the pinned schema, the file rules, executor-only
  ingress, the deterministic `index.html` and the closed refusal codes (contract §2, §3, §7).
- IF-0-VISART-2 — Staging: the seat subset and budget, `visual_stage_sha256`, per-route
  delivery including the jailed seat-home handoff, the route-neutral appendix and the
  untrusted-content notice (contract §4).
- IF-0-VISART-3 — `phase-loop observation validate|import`, `advisor-board --observation`,
  the native-fill identity rule, the board result's `visual_evidence` block and the
  `seat_visual_stage_changed` notice (contract §4.5, §5, §7).
- IF-0-VISRENDER-1 — Broker launch posture: dedicated uid, bwrap without operator home,
  Chromium sandbox, browser tree, Playwright MCP flags, pipe CDP, ephemeral profile, caps
  and teardown.
- IF-0-VISRENDER-2 — Review-target egress allowlist kind and digest, with
  connect-to-checked-address, redirect recheck and non-proxied-UDP rules.
- IF-0-VISRENDER-3 — Filtering shim: observe tool allowlist, the board-facing replay
  execution path, argument rules, journal line and refusal codes.
- IF-0-VISRENDER-4 — Render list, frozen replay script (`replay_sha256` binding, step
  vocabulary and result), and the board-to-staging handoff of broker observations.
- IF-0-VISRENDER-5 — Operator target policy (`browser_target_policy.v1`): location,
  closed fields, default, `policy_sha256`, the `preview_url` and `static_bundle` modes, and
  the `build_and_serve` refusal (contract §8.6).
- IF-0-VISBROKER-3 — Seat channel: per-seat socket lifecycle on sandbox-profile seats, and
  the jailed declared socket slot with its requalification.
- IF-0-VISBROKER-4 — Review-profile `browser` field, its `browser_automation` mapping and
  per-session process isolation.
- IF-0-VISREMOTE-1 — Remote broker channel over the per-reservation bridge, with pool
  capacity accounting.
- IF-0-VISBUILD-1 — App-runner sandbox and per-review instance lifecycle for
  `build_and_serve`, with its serving channel to the broker.
- IF-0-VISINTERACT-1 — Interactive tool set, disposable-environment attestation check,
  session cap and input-action journal.

## Phases

### Phase 1 — Observation artifacts and seat staging (VISART)

**Objective**

Define `browser_observation.v1` and deliver executor-captured observations read-only to
every local review seat and to the owner's T3 view, with no change to any jail. No browser
runs anywhere in this phase.

**Exit criteria**

- [ ] EC-VISART-1 — `phase-loop observation validate` accepts a directory exactly when it conforms to the pinned schema and contract §2–§3; every refusal is one closed code from contract §7, proven by positive fixtures and one negative fixture per code, including the maximum-size fixture.
- [ ] EC-VISART-2 — `phase-loop observation import` turns `visual_evidence_path` images into a valid executor observation whose `index.html` is byte-identical across two renderings of one manifest. A broker tool, `t3_preview` without `incognito`, and GIF or BMP input refuse with their §7 codes. No browser is launched or contacted.
- [ ] EC-VISART-3 — `advisor-board --observation` accepts executor observations only, stages the seat subset under the §4.1 budget, and delivers it per contract §4.2 with no new grant on any route. Jailed seats find it read-only at `/seat/home/review-visual`, and with no `--observation` no route's instructions, argv or bundle change. Every route's trusted instructions carry the §4.6 notice, and the bundle carries the route-neutral §4.4 appendix within its cap. An invalid or broker observation exits 2 before any seat launch.
- [ ] EC-VISART-4 — Across `seat_profiles.registered_legs()`, a jail built in-process with a staged visual copy has the same owner argv, `jail_profile_digest` and `actual_profile_digest` as one built without it. Every seat egress allowlist digest is unchanged. A hard-linked or non-regular staged entry refuses at handoff. A stage changed before launch records `seat_visual_stage_changed`. So does a copy that the in-H post-run rehash (contract §4.3) cannot confirm intact, which is never judged from outside H.
- [ ] EC-VISART-5 — The board result's `visual_evidence` block lists each observation's host label, absolute source, staged and `index.html` paths, manifest sha256, `visual_stage_sha256` and unstaged video. Every leg records `visual_delivered`, false for every launch path contract §4.2 marks false (sandbox-profile, brokered, sealed and remote), and jailed legs record `visual_post_run_intact`.
- [ ] EC-VISART-6 — The execute skills name T3 preview on `profileId: "incognito"` as a capture source beside claude-in-chrome and Playwright via PMCP. They direct moving the screenshot into the worktree, then `observation import` and `--observation`. Regenerated bundles and launch-spec goldens match their sources.
- [ ] EC-VISART-7 — A `--native-leg` run with a different observation set or stage digest from its `--emit-native-request` run refuses `observation_set_mismatch` before any seat runs; the same set is accepted.

**Scope notes**

- Decompose into 5 lanes: an observation-contract preamble; staging, the jailed handoff and
  the notice row; board delivery, CLI and result; executor guidance and skill regeneration;
  and a dependent documentation reducer. The lanes own disjoint files.
- Single-writer files: `seat_uid.py` and `seat_route_contract.py` (staging lane);
  `panel_invoker.py` and `cli.py` (board lane).
- `seat_jail.py` is not edited. No lane edits an `agy_qualification.ROUTE_CORE` file.
- All lanes may start now; EXT-SEATSCODEX is satisfied.

**Non-goals**

- Any browser process.
- Broker observations at ingress.
- Delivery to the sealed and remote routes, and to the masked seats: the non-brokered
  sandbox-profile seats and the brokered codex, Claude and grok seats. v1 makes no grant
  relaxation. Delivering to masked seats would be a later, deliberate grant relaxation
  that needs an owner decision, its own contract repin and its own tests.
- Video in seats.
- Runner wiring that passes a closeout's `visual_evidence_path` to the board
  automatically.

**Key files**

- `plans/artifacts/browser-v1-contract.md`
- `plans/artifacts/browser-v1-observation.schema.json`
- `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`
- `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json`
- `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `skills-src/codex/codex-execute-phase/SKILL.md`
- `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`
- `docs/browser-observation.md`

**Depends on**

- (none)

**Produces**

- IF-0-VISART-1 — `browser_observation.v1`, executor-only ingress, `index.html` and refusal codes.
- IF-0-VISART-2 — Staging, jailed seat-home handoff, appendix and untrusted-content notice.
- IF-0-VISART-3 — Observation CLI, board flag, native-fill identity, result block and notice.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
(seat view), `docs/browser-observation.md`; evidence paths:
`plans/evidence/browser/VISART.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 2 — Board-driven render and frozen replay (VISRENDER)

**Objective**

Before any seat launches, the board drives a hardened, host-side broker. It renders the
declared review targets and runs frozen replay steps, then stages the resulting broker
observations to every route through VISART. This gives seats an independent observation
with no seat channel and no jail change.

**Exit criteria**

- [ ] EC-VISRENDER-1 — The broker runs as a dedicated non-operator uid in its own bwrap with no operator home and no credentials. Chromium starts with its own sandbox, using an AppArmor profile where unprivileged user namespaces are restricted. A host where that sandbox cannot start refuses; nothing ever passes `--no-sandbox`.
- [ ] EC-VISRENDER-2 — Playwright MCP runs headless and isolated from `/opt/consiliency/browsers`, with pipe CDP, an ephemeral profile, downloads denied and no TCP listener. A writable or non-root-owned browser tree refuses.
- [ ] EC-VISRENDER-3 — All browser traffic crosses a broker-side proxy with a review-target allowlist kind. The proxy connects only to the address it just checked and rechecks every redirect hop. It denies private ranges, loopback, NAT64, 6to4 and the host's own addresses, and non-proxied UDP (QUIC, WebRTC) is disabled. Each observation records `egress_allowlist_sha256`.
- [ ] EC-VISRENDER-4 — The board renders a render list (URLs × viewports × colour schemes) authored before seat launch, writes broker observations and stages them through IF-0-VISART-2 to every route.
- [ ] EC-VISRENDER-5 — Frozen replay in VISRENDER is board-driven only. Before any seat launches, the board submits one replay script authored by the plan or the executor, from the contract §8.2 vocabulary, and bound by `replay_sha256`. The shim's board-facing replay execution path (contract §8.3) runs its steps in order, with no script execution, and returns pass/fail plus a broker observation, with `replay_sha256` in the journal and the board result. A script arriving after composition, or differing from its bound digest, refuses.
- [ ] EC-VISRENDER-6 — The broker runs under `seat_resource_caps` limits. After completion, crash or timeout, no broker or browser process, socket or profile directory remains.
- [ ] EC-VISRENDER-7 — Operational evidence: one board run on the review-seat host stages a broker observation of a preview URL to every local route, recorded as runner-stamped evidence.
- [ ] EC-VISRENDER-8 — The shim exposes exactly the contract §8.3 observation tools to the board driver. It accepts input actions only as the next step of the bound replay script on the board-facing replay execution path, and that path is never on a seat socket. Each of these refuses with a closed code before reaching Playwright MCP: a free-standing input tool call; an input action that is not the next bound step (`browser_input_not_in_replay`); and every denied tool, flag and target. Each call writes one journal line.
- [ ] EC-VISRENDER-9 — The target mode comes only from the operator target policy of contract §8.6. An absent policy yields `preview_url`, and an unsafe or malformed one is ignored with the default applied and the board result saying so. Every broker observation and the board result record `target.mode` and `target.policy_sha256`. `build_and_serve` refuses `browser_target_mode_unavailable`.
- [ ] EC-VISRENDER-10 — Under `preview_url`, only URLs whose origins match the policy's preview origins and the egress allowlist render. Loopback, private ranges and tailnet addresses are denied after resolution in every mode.
- [ ] EC-VISRENDER-11 — Under `static_bundle`, the board takes an executor-built directory before seat launch, validates it (regular single-link files, no symlinks, caps) and serves a read-only copy at a synthetic origin inside the broker sandbox, with no other code running. The observation records `target.bundle_sha256`.
- [ ] EC-VISRENDER-12 — No render input, bundle field or seat-reachable surface can choose or raise the mode. A render request outside the session's fixed origin set refuses.

**Scope notes**

- Decompose into 6 lanes plus docs: launcher and posture (uid, bwrap, AppArmor, browser
  tree); shim and tool filter; review-target allowlist kind in the srt proxy machinery;
  target policy and static-bundle serving; render and replay driver; board integration and
  staging.
- Single-writer: `panel_invoker.py` and `cli.py` (integration lane).
- VISRENDER's replay is board-driven only. The review-profile `replay` tier arrives with
  VISBROKER, so VISRENDER needs no tier.
- Plannable after VISART's plan freezes IF-0-VISART-2.

**Non-goals**

Seat channels, a review-profile `browser` field, input driven by a seat, remote runners and
`build_and_serve` (VISBUILD).

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_broker_shim.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_render.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `deploy/`
- `docs/browser-broker.md`

**Depends on**

- VISART

**Produces**

- IF-0-VISRENDER-1 — Broker launch posture, caps and teardown.
- IF-0-VISRENDER-2 — Review-target egress allowlist kind and digest.
- IF-0-VISRENDER-3 — Filtering shim tool allowlist, board-facing replay execution path, journal line and refusal codes.
- IF-0-VISRENDER-4 — Render list, bound replay script and result, and staging handoff.
- IF-0-VISRENDER-5 — Operator target policy, `preview_url` and `static_bundle` modes, and the `build_and_serve` refusal.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `plans/artifacts/browser-v1-contract.md` (repinned §8.2 and §8.3 freeze),
`docs/browser-broker.md`, `advisor_board/CONTRACTS.md`; evidence paths:
`plans/evidence/browser/VISRENDER.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 3 — Seat-driven observe channel (VISBROKER)

**Objective**

A review seat can make its own observations through the VISRENDER broker, over a channel
that follows the seat-channel rule, under review-profile policy.

**Exit criteria**

- [ ] EC-VISBROKER-4 — Each seat's channel follows contract §8.1. Sandbox-profile seats bind a per-seat 0600 socket in a 0700 directory through `SeatProfile.broker_socket`. Jailed seats get one declared socket slot that `jail_profile_digest` covers, `expected_mount_points` lists and the identity probe attests. Every leg has requalification evidence before the route enables. No seat's provider allowlist digest changes, and no route reaches the PMCP gateway.
- [ ] EC-VISBROKER-6 — Seat sessions run under `seat_resource_caps` limits. After seat exit, crash or timeout, no session process, socket or profile directory remains.
- [ ] EC-VISBROKER-7 — Operational evidence: one jailed and one sandbox-profile seat each record a seat-driven observation of a preview URL, as runner-stamped evidence.
- [ ] EC-VISBROKER-8 — Review profiles carry `browser: none|observe|replay|interactive`, defaulting to `none`. `browser_automation` is true only when a channel is attached, and unknown values refuse.
- [ ] EC-VISBROKER-9 — `replay` lets a seat re-run only a bound replay script authored before launch, named by its `replay_sha256`, through the contract §8.3 replay execution path. The seat cannot add, edit or reorder steps, and a seat-authored step is handled as `interactive`.
- [ ] EC-VISBROKER-10 — `interactive` refuses `browser_policy_tier_unavailable` (OR-7) until VISINTERACT lands.
- [ ] EC-VISBROKER-11 — Each seat session gets its own browser process. Contexts are shared only among seats of one review, and a cross-review share refuses.
- [ ] EC-VISBROKER-12 — No seat-facing tool or argument names a target mode or a tier. The session's origin set and tier are fixed from operator policy and the review profile before the seat launches. A seat request outside them refuses.

**Scope notes**

- Decompose into 4 lanes plus docs: sandbox-profile socket binding; jailed declared slot
  and its requalification; profile field and capability gate; session isolation.
- Single-writer files: `seat_jail.py` and `seat_profiles.py` (slot lane),
  `panel_invoker.py` (binding lane).
- The jailed slot needs maintainer review and per-leg requalification before it enables.

**Non-goals**

Interactive tools (VISINTERACT), `build_and_serve` (VISBUILD) and remote runners.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_broker_shim.py`
- `docs/browser-broker.md`

**Depends on**

- VISRENDER

**Produces**

- IF-0-VISBROKER-3 — Seat channel: sandbox-profile socket and jailed declared slot.
- IF-0-VISBROKER-4 — Review-profile `browser` field and session isolation.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `advisor_board/CONTRACTS.md`; evidence paths:
`plans/evidence/browser/VISBROKER.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 4 — Pooled remote broker on ai (VISREMOTE)

**Objective**

Seats on remote runners use a pooled broker on `ai`, reached through a PLACECLI-style
per-reservation bridge. Runner images stay browser-free.

**Exit criteria**

- [ ] EC-VISREMOTE-1 — The broker runs on `ai` as a pooled service with its own allowlisted image digest. Each reservation gets one browser channel through a 0700-directory, 0600-socket bridge scoped to it, with no public listener, torn down on release.
- [ ] EC-VISREMOTE-2 — Browser sessions count in PLACECLI headroom gates. At capacity the request refuses typed, with no fallback after admission.
- [ ] EC-VISREMOTE-3 — Broker session lifecycle and journal use the v12 JOURNAL and WORKER records; no second journal format exists.
- [ ] EC-VISREMOTE-4 — Remote seat observations reach a path the linked `ai` T3 environment can read, or the documented copy fallback, and the board result says which.
- [ ] EC-VISREMOTE-5 — The `pi-runner` image recipe is unchanged.
- [ ] EC-VISREMOTE-6 — Operational evidence: one remote seat records a broker observation on `ai`, as runner-stamped evidence.

**Scope notes**

- Decompose into 4 lanes plus docs: pooled service and image; bridge channel; capacity
  accounting; journal and result integration.
- Plan only after the EXT-PLACECLI, EXT-LANEEXEC and EXT-WORKER interfaces are frozen,
  and implement only after they land. Do not plan around them.

**Non-goals**

Changing PLACECLI, LANEEXEC, JOURNAL or WORKER contracts; E2B; native UI.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/`
- `docs/browser-broker.md`

**Depends on**

- VISBROKER

**Produces**

- IF-0-VISREMOTE-1 — Remote broker channel and pool capacity accounting.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `docs/placement-process-cli.md`; evidence paths:
`plans/evidence/browser/VISREMOTE.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 5 — Opt-in build-and-serve app runner (VISBUILD)

**Objective**

When the operator enables `build_and_serve` (OR-6), the reviewed tree is built and served
per review in a dedicated app-runner sandbox, and the VISRENDER broker renders it. This
phase is off the v1 path and blocks no other phase.

**Exit criteria**

- [ ] EC-VISBUILD-1 — `build_and_serve` is off by default and is enabled only by the operator target policy. Otherwise, and before this phase lands, it refuses `browser_target_mode_unavailable`. No seat-reachable surface can enable it.
- [ ] EC-VISBUILD-2 — Builds, install scripts and the running app execute only in the app-runner sandbox. It has its own uid, mount and network namespaces, and no operator home or credentials. It has no access to the broker's or any seat's filesystem, sockets, namespaces or credentials. Tests prove each separation from both sides.
- [ ] EC-VISBUILD-3 — Each review gets one instance, built from the staged reviewed tree after review authorization and destroyed when the review ends; no state survives into another review. Its observations record `target.mode: build_and_serve` and the reviewed `source_commit`.
- [ ] EC-VISBUILD-4 — Install traffic reaches only declared package registries. The running app has no egress beyond what the operator policy declares. The broker reaches the app only over its single private serving channel.
- [ ] EC-VISBUILD-5 — Every control the EXT-BUILDTM threat model requires has a test or a recorded evidence item.
- [ ] EC-VISBUILD-6 — Build and serve run under `seat_resource_caps` limits, and no instance process, network namespace or file survives teardown, crash or timeout.
- [ ] EC-VISBUILD-7 — Operational evidence: one opt-in review renders a served instance of its reviewed tree, as runner-stamped evidence.

**Scope notes**

- Decompose into 4 lanes plus docs: app-runner sandbox; per-review instance lifecycle;
  registry egress and serving channel; target-policy and board integration.
- Plan only after EXT-BUILDTM. Single-writer: `panel_invoker.py` (integration lane).

**Non-goals**

Running PR code anywhere but the app-runner sandbox; persistent or shared app instances;
interactive control.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_app_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_broker.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `docs/threat-models/browser-app-runner.md`
- `docs/browser-broker.md`

**Depends on**

- VISRENDER

**Produces**

- IF-0-VISBUILD-1 — App-runner sandbox, per-review instance lifecycle and serving channel.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `docs/threat-models/browser-app-runner.md`;
evidence paths: `plans/evidence/browser/VISBUILD.md`; `redaction_posture: metadata_only`;
missing or malformed evidence routes non-human `blocker_class=contract_bug`.

### Phase 6 — Interactive control on disposable environments (VISINTERACT)

**Objective**

A seat whose review profile says `interactive` can drive the browser, but only against a
disposable per-review environment with throwaway test data and least-privilege accounts
(OR-7). This phase is off the v1 path and blocks no other phase.

**Exit criteria**

- [ ] EC-VISINTERACT-1 — The contract §8.8 interactive tools are enabled only when the review profile says `interactive` and the target environment carries a valid EXT-DISPOSABLE attestation for this review. Otherwise they refuse `browser_environment_not_disposable`, and without the profile tier they refuse `browser_policy_tier_unavailable`.
- [ ] EC-VISINTERACT-2 — A shared or persistent environment, or one whose attestation is missing, expired, for another review or unverifiable, never gets interactive tools.
- [ ] EC-VISINTERACT-3 — Accounts are per-review and least-privilege, with credentials injected broker-side as placeholders in the seat. They are revoked at teardown, and test data is throwaway.
- [ ] EC-VISINTERACT-4 — An interactive session has a time cap, and every input action writes one journal line (tool, `aria-ref`, outcome, timing; no page content).
- [ ] EC-VISINTERACT-5 — The environment is destroyed after the review, with teardown evidence. A seat cannot choose or raise the tier, the target mode or the environment.
- [ ] EC-VISINTERACT-6 — Operational evidence: one interactive review against a disposable environment, as runner-stamped evidence.

**Scope notes**

- Decompose into 4 lanes plus docs: attestation check; interactive tool enablement and
  journal; per-review credentials; session cap and teardown.
- Plan only after EXT-DISPOSABLE. The owner's "after VISHARDEN" maps to after VISBROKER
  (see OR-7).

**Non-goals**

Interactive control against shared or persistent staging; seat-chosen environments; any
change to the seat-channel rule.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/browser_broker_shim.py`
- `phase-loop-runtime/src/phase_loop_runtime/browser_interactive.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`
- `docs/browser-broker.md`

**Depends on**

- VISBROKER

**Produces**

- IF-0-VISINTERACT-1 — Interactive tools, attestation check, session cap and input journal.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/browser-broker.md`, `advisor_board/CONTRACTS.md`; evidence paths:
`plans/evidence/browser/VISINTERACT.md`; `redaction_posture: metadata_only`; missing or
malformed evidence routes non-human `blocker_class=contract_bug`.

## Later Work (not phased in v1)

Native UI comes after v1, behind the same broker interface (contract §8.5): Electron
through Playwright's `_electron` first, then headless Wayland (`cage` or `sway`) with
screenshots and virtual input, then mobile through `agent-device` (Callstack, MIT) on device
hosts. Adding it needs a new roadmap or an append.

## Phase Dependency DAG

```
VISART ──> VISRENDER ──┬──> VISBROKER ──┬──> VISREMOTE   (EXT-PLACECLI, EXT-LANEEXEC, EXT-WORKER)
                       │                └──> VISINTERACT (EXT-DISPOSABLE; later, off v1)
                       └──> VISBUILD                      (EXT-BUILDTM; opt-in, later, off v1)
```

- **v1** is VISART → VISRENDER → VISBROKER, plus VISREMOTE once its gates land.
  VISBUILD and VISINTERACT are planned now, so their gating is explicit. No v1 phase
  depends on either.
- The v1 chain is serial because each phase freezes what the next one consumes: the
  artifact and staging, then the hardened broker, shim and target policy, then the seat
  channel that remote reservations bridge.
- Board-driven render comes before any seat channel. Every route gets an independent
  observation before any jail change is considered.
- VISBUILD can be planned in parallel with VISBROKER once its threat model is approved.
  The two land serially, because both edit `panel_invoker.py`.
- Critical path for v1: VISART → VISRENDER → VISBROKER → VISREMOTE.

## Execution Notes

- **Planning commands:** `/claude-plan-phase specs/phase-plans-browser-v1.md <ALIAS> --output plans/phase-plan-v1-browser-<ALIAS>.md`.
- **Concurrency:** VISRENDER can be planned once VISART's plan is approved, in parallel
  with VISART's execution. VISBROKER is planned after VISRENDER's plan freezes
  IF-0-VISRENDER-1 to IF-0-VISRENDER-3 and IF-0-VISRENDER-5. VISREMOTE waits for its
  external gates. VISBUILD is planned after EXT-BUILDTM, and VISINTERACT after
  EXT-DISPOSABLE.
- **Retired IDs.** The 2026-11-08 revision merged the former VISHARDEN phase into
  VISRENDER and VISBROKER. It retired EC-VISBROKER-1, -2, -3 and -5, IF-0-VISBROKER-1 and
  -2, and every VISHARDEN ID. None is reused.
- **Single-writer files across phases and roadmaps:**
  - `panel_invoker.py`: VISART, then VISRENDER, then VISBROKER, then VISBUILD. AGYROLL's REQUAL and
    EXECADMIT phases (planned in agent-harness#1927) will also edit it; serialize by
    landing order.
  - `seat_uid.py` and `seat_route_contract.py`: VISART.
  - `seat_jail.py`: VISBROKER only (the declared slot).
  - `seat_profiles.py`: VISBROKER, then VISINTERACT.
  - `browser_broker_shim.py`: VISRENDER, then VISBROKER, then VISINTERACT.
  - VISBUILD and VISBROKER may be planned in parallel, but they land serially because
    both edit `panel_invoker.py`.
  - `cli.py`: VISART, then VISRENDER.
  - `plans/manifest.json` and `specs/roadmap-status.json`: every planning PR, including
    agent-harness#1926 and agent-harness#1927. Each keeps main's rows and appends its
    own.

## Acceptance Criteria

- [ ] A UI change's executor screenshots reach every local review seat read-only and the owner's T3 thread, with no change to any jail profile digest or seat egress digest.
- [ ] Every local route receives an independent broker observation of an allowed preview URL before seats launch, with no browser in any seat and no path to CDP, T3 or the PMCP gateway.
- [ ] A seat-driven channel exists only as a declared, requalified slot or a sandbox-profile broker socket.
- [ ] The target mode is operator-selected and digest-bound, `preview_url` by default. No seat can choose or raise the mode or its tier.
- [ ] `build_and_serve` runs only when the operator opts in, in its own sandbox. `interactive` runs only against a disposable per-review environment, never against shared or persistent staging.
- [ ] Every artifact opens in T3 and in standard desktop and mobile Chrome without a viewer service.

## Verification

The installed managed `phase-loop` (0.7.27) does not accept this roadmap's registry
status, so validate with the in-tree runtime, from the repository root:

```bash
PYTHONPATH=phase-loop-runtime/src timeout 120 python3 -m phase_loop_runtime.cli \
  validate-roadmap --repo . --roadmap specs/phase-plans-browser-v1.md
PYTHONPATH=phase-loop-runtime/src timeout 120 python3 \
  phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-browser-VISART.md
cd phase-loop-runtime
timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -q -p no:cacheprovider \
  tests/test_browser_observation_contract.py tests/test_seat_visual_staging.py \
  tests/test_seat_visual_profile_neutrality.py tests/test_seat_visual_rehash_in_h.py \
  tests/test_board_visual_delivery.py tests/test_advisor_board_golden.py \
  tests/test_cli_observation.py tests/test_seat_route_contract.py tests/test_seat_notices.py
```

Later phases add their own targeted tests. Operational evidence comes from
EC-VISRENDER-7, EC-VISBROKER-7 and EC-VISREMOTE-6, in `plans/evidence/browser/`,
runner-stamped.
