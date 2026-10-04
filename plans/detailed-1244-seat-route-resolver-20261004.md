---
status: planned
issue: agent-harness#1244
lands_after: agent-harness#1222, agent-harness#1166
---

# Detailed plan: review seats never run toolless — one seat-route resolver (agent-harness#1244, first PR)

## Task

agent-harness#1244, maintainer decision 2026-10-04 (the issue is the source of truth; not
restated here). This first PR adds one seat-route resolver that every board and panel path
calls, with the order **(1) local sandbox → (2) remote sandbox → (3) native fill with tools,
labelled a stand-in → (4) degraded, not run**, and removes the sealed (toolless) route as a
fallback. Sealed survives only as an explicit operator opt-in, off by default and named in the
mode line.

Out of scope, filed as follow-ups: the per-OS sandboxes (macOS Seatbelt/VM, Windows
AppContainer/WSL2), the remote backend itself (agent-harness#896), the Gemini egress proxy
(agent-harness#1170), and native fill under a non-Claude-Code host (a Codex-hosted "sol" fill).

## Sequencing (decided here)

**This PR lands after agent-harness#1222 and agent-harness#1166, and consumes #1166's
interface. #1166 does not adopt the resolver.** #1166 owns step (1) and the mode-line
surface. It has had more than ten board rounds, and adding scope to it would reset its
review. The resolver takes #1166's step-1 outcome as input, by symbol on its pushed head:
`seat_jail.decide_seat_route`, `SeatRoute`, `SEALED_FALLBACK_CODES`,
`panel_invoker._seat_route_for_spawn`, `panel_invoker._publish_seat_modes`, and
`seat_preflight.SeatMode` / `SEAT_MODES`. If any of these is renamed before #1166 lands, the
implementer re-reads them on main. This plan pins symbols, not SHAs.

**The brief's premise about #1166 A3 is wrong as of this plan.** The team-lead brief says
amendment A3 already makes #1166's own fallbacks degraded-not-run. A3 as written
(`plans/detailed-seat-sandbox-permissions-1132-20260928.md`, "Amendment A3", on #1166's
branch) says otherwise:
- A login-wait timeout runs the seat **sealed** with `claude_seat_login_token_expiring`.
- A store that stops yielding a login seals it with `claude_seat_token_missing`.
- A2's qualification failure still goes sealed with `seat_jail_qualification_failed`.

`SEALED_FALLBACK_CODES` therefore still exists. This PR converts every code in it into
"step 1 unavailable, reason=<code>" and continues the chain. Maintainer decision **D1**
(below) is whether #1166 should do this itself before landing.

## Research summary

There is no single route resolver on main. A seat's route comes from separate predicates in
`phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`:
- The board-wide gates in `invoke_board`: `native_host_deferral_only` and
  `exact_broker_routes`, with `harden_review_unsupported_route_refused` for anything else.
- `_SANDBOX_INCAPABLE_BROKERED_LEGS = {"claude","gemini"}` and `sandbox_usable_by`.
- The silent sealed fallback, at the brokered spawn's call to
  `_render_broker_inline_prompt(..., staged_tree=... if sandbox_usable_by(...) else None)`.
- The native-fill path: `native_agent_leg_request`, `preflight_native_leg_fills`, and
  `apply_native_leg_fills`. The last accepts only a same-model fill on an
  `UNAVAILABLE/under_claude_code` leg.

Native fill is refused under `heartbeat_only`. `advisor_board/backing.py`
`resolve_review_monitoring_policy` raises `review_monitoring_unsupported_route:native_fill`,
and boards have run heartbeat-only since 2026-09-24. **Step (3) is therefore dead for every
current board until D2 is decided.**

Remote placement (agent-harness#896) is only planned on main:
`plans/detailed-e2b-cloud-backend-896-20260929.md` and its placement plan name
`sandbox_placement.resolve_backend` / `PlacementBackend.available()` /
`PlacementUnavailable(code)`. `sandbox_policy.configured_root()` only records a location and
is not "configured and usable."

Governance on main:
- `ratification_policy.py:100-105` sets `required_vendors` per gate (3 for pre-merge-CR and
  release-dispatch, 2 for plan/design).
- `_effective_vendors` does not count an empty, timed-out or DEGRADED seat.
- `governed_premerge._MIN_USABLE_REVIEWERS = 2`, with the full 3-vendor quorum deferred to
  agent-harness#375.
- `advisor_board/composition.board_independence` marks any repeated vendor family `degraded`.
- The seat-count states are EC-REVIEWTRUTH-1 / EC-REVIEWTRUTH-4, and native-fill counting is
  EC-REVIEWTRUTH-14.
- No cross-vendor stand-in field exists. The closest are `_native_fill` metadata and
  `attach_provider_refusal_state(fallback_used=True)`.
- The stand-in practice so far (a native Opus filling a filtered codex seat) is an
  out-of-band operator ruling, not code.

## Frozen vocabulary

No new leg status:
- `LEG_STATUSES` (`panel_invoker.py:194-201`: OK, EMPTY, TIMEOUT, ERROR, DEGRADED,
  UNAVAILABLE) is unchanged. There is no `NOT_RUN`. "Degraded, not run" is status
  `DEGRADED` with zero launches.
- No new seat mode. The modes stay #1166's `jailed | unconfined | sealed | degraded | native`.
  Remote has no mode in this PR because step (2) never resolves until agent-harness#896,
  which adds `remote`.

Additions, each extending a closed list in the way that list already grows:
- Notice codes in `seat_preflight.NOTICE_TEXT`.
- One `_HARNESS_DETAIL_CODE_TEMPLATES` pattern, `seat_not_run:<reason>`, under
  `advisor_board/CONTRACTS.md` "Leg `detail` vocabulary" (lines 470-489).
- The additive `SeatMode.stand_in_for` field.

The sealed route is the HARDEN-era "CLI seats cannot read files" contract. Making it opt-in
is recorded as a CONTRACTS amendment entry, not a silent edit. See D4.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/seat_route.py` (create)

No existing home: #1166's `decide_seat_route` is jail-only (it returns `None` for
codex/grok, and `jailed | sealed` otherwise).

- `SeatRouteStep` — add — a closed enum-like set of literals: `local`, `remote`, `native`,
  `degraded`, `sealed_opt_in`, `unconfined`.
- `ResolvedSeatRoute` — add — a frozen dataclass with these fields:
  - `step`
  - `mode`: a #1166 `SEAT_MODES` literal
  - `code`: a notice code or None
  - `stand_in_for`: the vendor family or None
  - `filled_by_model`: str or None
  - `tried`: a tuple of `(step, code)` for each skipped step
- `resolve_seat_route(seat, *, local, remote_probe, native_capable, allow_sealed)` — add —
  a pure function. It does not probe, and takes every fact as an argument so tests cover the
  logic and a separate test covers the gathering:
  - codex and grok return `unconfined`.
  - claude: (1) a `local` jailed outcome returns `local`, and any `SEALED_FALLBACK_CODES`
    outcome or `None` records the code and continues. (2) The `remote_probe` result. (3) If
    `native_capable`: claude-on-Claude-Code is the existing same-model native fill
    (`stand_in_for=None`), and any other vendor gets `stand_in_for=<vendor>`. (4) Otherwise
    `degraded`, with the last skipped code as the reason.
  - gemini: step (1) is skipped with `gemini_seat_egress_unconfined` until
    agent-harness#1170, then (2)→(3)→(4).
  - `sealed_opt_in` is returned only when `allow_sealed` is true **and** steps (1)–(3) all
    failed.
- `remote_sandbox_probe(seat)` — add — the default step-2 fact. It returns unavailable with
  `seat_remote_sandbox_unconfigured` until agent-harness#896 lands
  `sandbox_placement.resolve_backend`. Its docstring names that seam as the plug-in point.
- `sealed_opt_in_enabled(env)` — add — reads `PHASE_LOOP_SEAT_ALLOW_SEALED=1`. Default off.

### `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py` (modify)

- `NOTICE_TEXT` — modify — add what/why/fix literals for these codes:
  - `seat_not_run_no_tooled_route`: fix "configure a remote sandbox, run the board under Claude
    Code, or qualify the jail on this host".
  - `seat_remote_sandbox_unconfigured`.
  - `seat_native_standin`: why "stands in for <vendor>"; fix "none: counts as the host
    vendor".
  - `seat_sealed_operator_opt_in`: fix "unset PHASE_LOOP_SEAT_ALLOW_SEALED".
- `SeatMode` — modify — add `stand_in_for: str | None = None` to `as_json`. `render` prints
  `native (stand-in for <vendor>)` or `sealed (operator opt-in)`.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- `_seat_route_for_spawn` (#1166) — modify — call `seat_route.resolve_seat_route` with
  #1166's `decide_seat_route` outcome as `local`. It returns the resolved route, not
  `SeatRoute`.
- The brokered spawn's `_render_broker_inline_prompt(..., staged_tree=None)` branch — modify —
  this is reachable only when the resolved step is `sealed_opt_in`. Every other path with
  `staged_tree=None` raises `seat_route_sealed_without_opt_in` (fail closed).
- `invoke_board`, around the per-seat launch loop — modify — a `degraded` route produces a
  `DEGRADED` `PanelLegResult` with detail `seat_not_run:<reason>` and **zero spawns**. A
  `native` route emits a `NativeAgentLegRequest` through the existing
  `native_agent_leg_request`.
- `_publish_seat_modes` (#1166) — modify — modes come from the resolver. Every seat's mode is
  published before any launch, so the pre-launch mode line shows the step, the stand-in label
  and the fix.
- `apply_native_leg_fills` / `preflight_native_leg_fills` — modify — accept a fill whose
  model differs from the seat's model only when the resolved route has `stand_in_for` set,
  and record `stand_in_for` and `filled_by_model` in `_native_fill`. A same-model fill is
  unchanged.
- `agy_qualification.py` (the Gemini heartbeat qualification board) — modify — it
  qualifies the sealed agy route itself, so it is the one sanctioned non-operator caller of
  the sealed route. It passes `allow_sealed=True` explicitly, and its mode line says
  `sealed (operator opt-in)`. The sealed guard exempts no other caller.
- `invoke_panel`, `invoke_panel_request` — modify — route through the same resolver. There
  are no other per-seat route predicates. `sandbox_usable_by` becomes an input to step (1)
  only.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify; conditional on D2)

- `resolve_review_monitoring_policy` — modify — only if D2 = (a). Allow a native fill under
  `heartbeat_only` when it is a resolver-produced stand-in, and keep the refusal for a
  caller-supplied fill. If D2 = (b), there is no change, and a native-route seat under
  heartbeat-only keeps today's `UNAVAILABLE` / `under_claude_code` detail. That way the
  out-of-band `--native-leg` fill still binds: `apply_native_leg_fills` accepts only that
  shape. `seat_not_run:<reason>` is reserved for seats that have no native option.
- `prepare_review_composition_authorization` and the review-isolation authorization (both
  `platform.system() != "Linux"` gates, around lines 949 and 996) — modify, only if D5 = (a).
  On non-Linux, the whole-board refusal becomes a per-seat step-1 fact,
  `seat_local_sandbox_unsupported_os`, so the seat continues to steps 2→3→4. Under D5 = (b),
  non-Linux boards stay refused whole (agent-harness#1098), and this PR does not close the
  issue's "hosts without the jail" box for macOS or Windows.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/president_adapter.py` (modify)

- `build_president_invoke` (around line 564) — modify — the president's brief carries each
  seat's resolved route: step, `stand_in_for`, `filled_by_model` and the not-run reason. This
  is how the president is told.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)

- The `advisor-board` parser — modify — add `--allow-sealed-seat`, which sets the same switch
  as the env var.
- The mode-line print (#1166's per-seat stderr line) — modify — no new printer. It renders
  the new `SeatMode` fields.

### `phase-loop-runtime/tests/test_seat_route.py` (create)

- A table test over host × seat × facts covering every order: Linux jail ok; no
  subuid/uidmap, macOS or Windows (step 1 unavailable); Gemini; remote configured (a fake
  probe); under or not under Claude Code; opt-in on or off.
- One falsifier per step: deleting a step from the resolver reds a named row.
- A guard that the sealed prompt branch raises without the opt-in.
- A gathering test that calls the real call sites (`invoke_board` through `cli.py`
  `advisor-board`, `runner.py` `invoke_board(CODE_REVIEW_BOARD, ...)`,
  `agy_qualification.py`, `invoke_panel`, `governed_review.py`) with fakes at the spawn seam.
  It asserts every seat's route came from `resolve_seat_route`, and that a degraded seat
  made zero spawns.

## Governance (describe, do not invent)

This PR changes **no** quorum rule:
- A `degraded` not-run seat is DEGRADED, so `_effective_vendors` already does not count it,
  and EC-REVIEWTRUTH-1/-4 classify the board FLOOR-ONLY or BELOW-FLOOR from the delivered
  count.
- A native stand-in reviews with tools and counts as a reviewing seat of its **host** vendor
  family. On a board that already seats Claude, an Opus stand-in for Gemini is therefore a
  repeated family: `board_independence` reports `degraded`, and the stand-in does not raise
  the `required_vendors` count.

Whether a labelled stand-in should count toward `required_vendors` is D3. It is not decided
here.

## Documentation impact

- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — add a
  "Seat route resolver (agent-harness#1244)" section: the order, sealed as opt-in only (the
  HARDEN amendment entry, D4), the new notice codes and the `seat_not_run:<reason>` detail
  pattern.
- `phase-loop-skills/advisor-board/SKILL.md` — modify — replace the sealed-fallback wording
  with the chain and the opt-in.
- `CHANGELOG.md` — modify — behaviour change: a seat with no tooled route is not run, where
  before it ran sealed.
- `docs/outside-agent-conformance.md` — modify, only if it describes the sealed route as a
  default (the implementer greps for "sealed").

## Dependencies & order

1. agent-harness#1222, then agent-harness#1166, land on main.
2. D1, D2, D4 and D5 are decided. D3 does not block this PR.
3. Within the PR: `seat_preflight` codes → `seat_route.py` and its test → panel_invoker
   wiring → cli/president → docs.

## Verification

```bash
cd phase-loop-runtime
uv run pytest tests/test_seat_route.py tests/test_seat_notices.py tests/test_seat_jail*.py -q
uv run pytest tests -q -k "native_fill or monitoring_policy or board_independence or premerge"
grep -n "staged_tree=None" src/phase_loop_runtime/panel_invoker.py   # only the opt-in branch
PHASE_LOOP_SEAT_ALLOW_SEALED= uv run python -m phase_loop_runtime.cli advisor-board --help | grep -- --allow-sealed-seat
```

Edge cases:
- A jail that becomes unqualified mid-board.
- A remote probe that raises, which is treated as unavailable with a typed code, never sealed.
- Opt-in set on a host where the jail works, which still runs jailed (opt-in is last resort).
- A Gemini seat on a Linux jail host.
- A board where every seat is degraded, which is BELOW-FLOOR and refused, never "converged".

Mutation receipts are required, one per resolver step and one for the sealed guard.

## Acceptance criteria

- [ ] `resolve_seat_route` returns `degraded` with `seat_not_run_no_tooled_route` for a Claude
  seat with no jail, no remote and no native capability, and the board makes **0** spawns
  for that seat. Proven by `tests/test_seat_route.py`.
- [ ] With `PHASE_LOOP_SEAT_ALLOW_SEALED` unset, no production path reaches
  `_render_broker_inline_prompt(..., staged_tree=None)`. The guard test reds when the raise
  is removed.
- [ ] A Gemini seat is never `sealed` by default. It resolves `native` with
  `stand_in_for="gemini"` under Claude Code (D2 permitting), otherwise `degraded`.
- [ ] Every board seat's mode, including step, stand-in label and fix, is in
  `seat-modes.json` and on stderr before the first spawn, and the president brief carries
  the same routes.
- [ ] No change to `LEG_STATUSES`, `SEAT_MODES`, `DEFAULT_RATIFICATION_POLICIES` or
  `board_independence` (diff check).

## Maintainer decisions needed

- **D1:** #1166 A3/A2 still fall back to sealed. Should #1166 convert them to degraded
  before landing, or does this PR do it? Recommended: this PR.
- **D2:** native fill is refused under `heartbeat_only`. (a) Allow resolver-produced
  stand-ins under heartbeat-only, or (b) keep the refusal, so step (3) means "degraded, fill
  out of band with `--native-leg`". Recommended: (a). The refusal came from the
  agent-harness#908 board r4 (d) finding.
- **D3:** does a labelled stand-in count toward `required_vendors` and toward independence?
  Current code says no. This PR keeps that.
- **D4:** demoting the HARDEN sealed route to opt-in needs a CONTRACTS/HARDEN amendment entry.
  Is the opt-in name `PHASE_LOOP_SEAT_ALLOW_SEALED` / `--allow-sealed-seat` approved?

- **D5:** today the board is refused whole on non-Linux (`backing.py` Linux gates;
  agent-harness#1098). (a) Make it a per-seat step-1 fact, so macOS and Windows go
  2→3→4 (recommended), or (b) keep the whole-board refusal until the per-OS sandboxes
  exist.

## Follow-ups (file as separate issues)

- macOS seat sandbox (Seatbelt `sandbox-exec` or a VM).
- Windows seat sandbox (AppContainer or a WSL2 jail).
- Remote backend: agent-harness#896 plugs into `remote_sandbox_probe` and adds mode `remote`.
- Gemini egress: agent-harness#1170 removes the Gemini step-1 skip.
- Native fill under a Codex host (a "sol" stand-in).
- Remove the sealed opt-in once steps 1–3 cover the supported hosts.

## Execution Policy

- execute: effort=high, reason=security-relevant route selection across every board path
