---
status: planned
issue: agent-harness#1244
lands_after: agent-harness#1222, agent-harness#1166 (with its D1 change)
builds_on: plans/detailed-remote-sandbox-placement-896-20260929.md, plans/detailed-e2b-cloud-backend-896-20260929.md
evidence: plans/detailed-1244-sandbox-selection-20261004.md
---

# Detailed plan: review seats and the president never run toolless (agent-harness#1244)

## Task

This plan implements agent-harness#1244. The maintainer's rulings of 2026-10-04 are listed
once, under "Rulings", and every other section points to them by ID.

The goal is that every review seat, **and the president**, of every harness, gets a route
with tools, or else is degraded and not run. Harness-specific code is kept to thin adapters
for credentials, CLI argv and host sub-agent mechanisms.

**Split (round-1 board).** The work is more than one bounded change, so it is split into three
PRs:
- **PR-A1** (detailed below): the resolver, the policy, the president, the sealed guard, the
  D5 gates and the step-2 shim that respects agent-harness#896's execution gate.
- **PR-A2**: generic host-native fill, meaning per-host adapters, a runtime-held mint record,
  the D2 lift for seats and the president, and D3 effective-vendor governance.
- **PR-A3**: the remote fall-through, once agent-harness#896 has delivered the additions
  listed in that section.

A separate plan, **PR-B**, adopts srt as the local sandbox. Its inputs are the ruled S1–S4,
recorded in the evidence file named in the front matter.

## The chain

The resolver tries these steps in order for every seat and for every president rung,
whatever the harness:
1. **Local sandbox.** On Linux this is agent-harness#1166's jail (S1), or agent-harness#1222's
   staged tool-enabled route for codex and grok (D6). A claude seat **under Claude Code**
   also takes step 1 first (the jail). Native fill is only step 3. On macOS it is srt, once PR-B lands
   (S1). Windows has no local sandbox (S2).
2. **Remote sandbox.** The backends behind agent-harness#896's seam, in
   `[seat_route] remote_backends` order (R1). The self-hosted backend must meet the
   requirements in agent-harness#896 issuecomment-5983731656. E2B follows plan 4, which keeps
   its key custody and adds no runtime caps (R2).
3. **Host-native fill.** The host harness's own sub-agent fills the seat as a labelled
   stand-in, which counts as its own vendor (D3). The host must have an adapter. This step
   is taken only when the monitoring policy admits a native fill. Under `heartbeat_only` it
   is skipped with a typed reason until PR-A2 lifts the refusal (D2).
4. **Degraded, not run.** The seat gets a typed notice with its fix, shown in the pre-launch
   mode line. For the president, the landing gate reports "no president".

**Sealed** (inlined and toolless) is never a step:
- For a **seat**, it runs only when `PHASE_LOOP_SEAT_ALLOW_SEALED=1` is set (D4), and then
  only after steps 1–3 have all failed. It is announced loudly.
- The **president** is never sealed, whether or not the opt-in is set.
- The agy qualification board is the one internal exemption. The guard enforces it
  structurally (see "Sealed guard").

**The resolver's domain** is the governed review launches: `mode == "review"` with a
review authorization, the same launches #1166's `_seat_route_for_spawn` considers.
- Research, capture, non-review modes and injected test seams are outside it. They keep
  their current launches, which are tooled. Their mode label is corrected from #1166's
  `sealed` to `unconfined`, because they are tooled, not sealed. CHANGELOG records the
  relabel.

On non-Linux hosts the chain runs per seat, never as a refusal of the whole board (D5).

## Rulings (maintainer, 2026-10-04)

| ID | Ruling |
|---|---|
| D1 | agent-harness#1166 changes its **own** fallbacks to degraded: the A2 qualification failure, the A3 login-wait timeout and vanished login, and `jail_unqualified`. These plans do not change them. PR-A1 has an entry check and a guard. |
| D2 | The `heartbeat_only` refusal of native fill is lifted, for resolver stand-ins only, for both seats and the president, under the PR-A2 guard. |
| D3 | A stand-in counts as its own vendor. Independence is accounted for honestly. |
| D4 | For seats only, sealed is opt-in (`PHASE_LOOP_SEAT_ALLOW_SEALED=1`) with a loud mode line. This needs a HARDEN/CONTRACTS amendment. agy qualification is the only exemption. The president is never sealed. |
| D5 | Non-Linux hosts are resolved per seat (agent-harness#1098). |
| D6 | codex and grok keep their current tool-enabled staged route until srt covers them. |
| President | The president goes through the same chain and is never sealed, even with the opt-in set. If no rung has a tooled route, it is degraded and not run, and the landing gate reports "no president". The PR that removes the president's sealed route must also deliver a working tooled president route. A host never gets "no president" where main had a president. |
| S1–S4 | srt adoption: macOS first; the Linux jail stays until srt passes the conformance suite; Windows goes to remote; srt egress supersedes agent-harness#1170; srt TLS inspection is used for Gemini if needed. Detail is in the evidence file. |
| R1 | `remote_backends` defaults to `["self-hosted", "e2b"]`. |
| R2 | E2B has no runtime spending caps. The account-side spending limit is documented as the operator's guard. Each sandbox's duration is recorded in the evidence. Plan 4's time-to-live is a liveness bound, not a budget. |
| E2B | E2B is the second remote backend (plan 4 = agent-harness#1165). Its key comes from the owner-only file `$XDG_STATE_HOME/phase-loop/credentials/e2b`, which the operator provisions. |

## Research summary

**How routes are chosen today:**
- Seat routes are scattered across predicates in `panel_invoker.py`:
  - the `invoke_board` gates;
  - `sandbox_usable_by`;
  - the sealed renderer `_render_broker_inline_prompt`;
  - the native-fill functions `_native_fillable_seats`, `native_fill_request_payload`,
    `load_native_leg_fill(s)`, `preflight_native_leg_fills` and `apply_native_leg_fills`.
    All of them are Claude-only:
    - they check `_under_claude_code`;
    - they accept only `harness == "claude"` seats;
    - they default to `filled_by="claude-code-native-agent"`;
    - the only consumer of native requests is
      `phase-loop-skills/advisor-board/_overrides/claude/SKILL.md`.
- The president launches without tools on every brokered rung:
  - `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py` `_transport` and
    `_launch_claude` produce the tools-off argv.
  - The Gemini rung passes `staged_tree=None` (around line 396).
  - `PRESIDENT_FILL_HEARTBEAT_REFUSED` (around lines 193–197) refuses a native president
    under heartbeat.
- `agy_qualification.py` calls `_render_broker_inline_prompt` directly (around lines 301 and
  559).

**Linux-only gates in `advisor_board/backing.py`** are at about lines 659, 949, 996, 1054,
1153, 1235 and 1602.

**Governance:**
- `ratification_policy.board_facts_from` and `composition.board_independence` read the
  requested board's seat models.
- `governed_review.py` (around line 649) drops author vendors before the routes are resolved.

**agent-harness#896 plan 1a**, as implemented on `claude/896-placement-1a`, provides:
- `PlacementBackend.available(request) -> bool`, which returns no reason code and makes no
  network call;
- `resolve_backend(choice: SandboxRootChoice)` and `backend_for_scheme(scheme)`, keyed by
  the URL scheme of the single configured root;
- `PlacementUnavailable(code, reason)`;
- `panel_invoker._NONLOCAL_EXECUTION_DRIVER = False`. Until plan 1b lands, this refuses every
  non-local backend with `sandbox_placement_driver_unavailable`, and no backend method,
  `available` included, may run;
- the rule "launch is final".

`ExecResult` holds `sandbox_ref, exit, stdout, stderr, truncated`. Lifetimes live in 1b's
lease journal.

**agent-harness#1166 (A3b)** sends its D1 cases to `seat_jail.JAIL_NOT_RUN_CODES`, which
means not run:
- `claude_seat_token_missing`;
- `seat_jail_qualification_failed`;
- `claude_seat_login_token_expiring`;
- the `seat_sandbox_refused:jail_unqualified` refusal.

It still seals the cases it leaves to agent-harness#1244, through `SEALED_FALLBACK_CODES`:
`seat_sandbox_not_staged`, the `gemini_seat_*` codes, and `seat_sandbox_unavailable_*`.

There are two further sites:
- A claude seat under Claude Code is excluded from the jail at `_seat_route_for_spawn`'s
  eligibility (around #1166 `panel_invoker.py:10088`). It is deferred as `under_claude_code`
  in `_exec_claude_tui_leg` (around :8382).
- The president reads no tree. `PresidentIsolationAuthorization` (around #1166
  `backing.py:1531`) has no staged-tree digest. The president's stage holds only the bundle
  and the instructions (around `president_adapter.py:318-325`).
  `president_fill_heartbeat_refused` is not in `_PRESIDENT_REFUSAL_CODES` (around
  `panel_invoker.py:802`), so it raises instead of descending.

## Frozen vocabulary

**Unchanged:**
- `LEG_STATUSES` (`panel_invoker.py:194-201`); there is no `NOT_RUN`. Degraded, not run is
  `DEGRADED` with zero spawns.
- `DEFAULT_RATIFICATION_POLICIES`.

**Additions only**, each made the way its closed list already grows:
- `SEAT_MODES` gains **`remote`**. PR-A1 owns this literal. PR-A3 is the first producer.
- notice codes in `seat_preflight.NOTICE_TEXT`;
- harness detail codes `seat_not_run:<reason>` and `host_native_fill_abandoned`, added under
  the CONTRACTS "Leg `detail` vocabulary" (lines 470–489);
- the president code `president_ruling_missing:president_no_tooled_route`, inside the
  existing `president_ruling_missing:<code>` template;
- `SeatMode` fields `stand_in_for`, `host_harness` and `placement`.

## PR-A1 — resolver, policy, tooled president, sealed guard, D5 (in full)

### Entry check (D1, scoped to what #1166 owns)

Before implementation, confirm on main with #1166 merged that each D1 case is **not run**,
never sealed:
- the A2 qualification failure;
- the A3 login-wait timeout or vanished login;
- `jail_unqualified`.

The check is that `JAIL_NOT_RUN_CODES` holds those codes, and that the refusal path covers
`jail_unqualified`. If either fails, stop and report on #1166.

The remaining automatic sealed routes are **PR-A1's to remove**, after its resolver is
integrated. These are the `SEALED_FALLBACK_CODES` cases: no jail prerequisites, unstaged,
and Gemini. PR-A1 treats every member of that set as a step-1 skip code. Its acceptance
asserts that none of them reaches `MODE_SEALED` or a tools-off argv.

### `phase-loop-runtime/src/phase_loop_runtime/seat_route.py` (create)

- **`ResolvedSeatRoute`** — a frozen dataclass:
  - `step`, one of `local | remote | host_native | degraded | sealed_opt_in`;
  - `mode`, a `SEAT_MODES` value;
  - `code`, `backend`, `stand_in_for`, `host_harness`;
  - `tried`, a tuple of `(step, code)` pairs.
- **`resolve_seat_route(target, *, local, remote, host, allow_sealed)`** — pure. The
  `target` is a seat or a president rung, and every fact is an argument.
  - **Step 1, `local`:** #1166's `decide_seat_route` outcome for claude. For codex and grok,
    the D6 staged route, which counts as step 1 and passes no adapter gate. For gemini, a
    skip with `gemini_seat_egress_unconfined` until PR-B (S3/S4). For a non-Linux host, a
    skip with `seat_local_sandbox_unsupported_os`.
  - **Step 2, `remote`:** the step-2 shim below.
  - **Step 3, `host`:** taken only when all of these hold:
    - the host-native adapter registry (PR-A2) has an adapter for the host;
    - that adapter can fill this target;
    - the new resolver input `native_admitted` is true. It is false under `heartbeat_only`
      until PR-A2, and the step is skipped with `seat_host_native_heartbeat_refused`.

    In PR-A1 the registry holds today's Claude Code behaviour only: a same-model fill of a
    claude seat. In practice, then, step 3 runs in PR-A1 only on bounded boards.
  - **Step 4:** `degraded`.
- **The step-2 shim** (`remote_step(target, choice)`). It never calls a backend method while
  `_NONLOCAL_EXECUTION_DRIVER` is false:
  - no remote root configured → `seat_remote_sandbox_unconfigured`;
  - a root configured but no driver → `sandbox_placement_driver_unavailable`.

  PR-A3 replaces it.
- **The credential gate (D6-aligned).** `SeatCredentialSource` is required only by routes
  that PR-A1 and later PRs introduce: srt local in PR-B, and remote in PR-A3. #1166's jail
  and the D6 staged routes keep their existing credential paths and are never excluded by
  the gate.
- **`sealed_opt_in_enabled(env)`** — off by default.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- `_seat_route_for_spawn` and `_publish_seat_modes` (#1166) — modify — build both from
  `resolve_seat_route`. Every seat's mode is published before the first spawn.
- **Sealed guard at the argv level.** `_require_tooled_or_opted_in(target, *, env,
  exemption=None)` is called inside every builder that can produce a tools-off launch:
  - `_render_broker_inline_prompt`;
  - `_broker_tool_controls`;
  - `_broker_claude_tui_command` with `sandboxed=None`;
  - `_brokered_gemini_command` with `staged_tree=None`;
  - the brokered codex `read-only` argv;
  - the grok `--tools ""` argv.

  It passes in only two cases:
  - **(a)** the target is a **seat**, *and* the guard itself re-reads
    `sealed_opt_in_enabled(env)` at build time, *and* that read is true. It never trusts a
    caller-built `ResolvedSeatRoute(step="sealed_opt_in")`.
  - **(b)** `exemption is panel_invoker._AGY_QUALIFICATION_EXEMPTION`, a module-level
    sentinel object compared by identity.

  A **president** target never passes (a), whatever the env. Otherwise the guard raises
  `seat_route_sealed_without_opt_in`. There is no caller string.

  The sentinel is structural. A static (AST) test asserts that
  `_AGY_QUALIFICATION_EXEMPTION` is referenced only at its definition and in
  `agy_qualification.py`. A reference anywhere else turns the test red.
- **Claude under Claude Code: jailed first** (#1166 sites). The
  `not (leg == "claude" and _under_claude_code(env))` clause in `_seat_route_for_spawn`'s
  eligibility (around :10088) is removed. The `under_claude_code` deferral in
  `_exec_claude_tui_leg` (around :8382) then applies only when the resolved route is
  `host_native`. The `MODE_NATIVE` publish (around :1662) comes from the resolver.

  A jailed TUI runs with the jail's own env and home, not the host session's. If a nested
  self-PTY TUI cannot start in practice, the seat skips step 1 with
  `claude_seat_nested_tui_unavailable` and the chain continues.
- `invoke_board` — modify — a `degraded` route returns `DEGRADED`, `seat_not_run:<reason>`,
  with **zero** spawns.
- `_under_claude_code` route decisions — modify — use `detect_host_harness(env)` together
  with the adapter registry.

### Tooled president (`president_adapter.py`, `advisor_board/backing.py`) — delivered with the sealed removal

The president gets the **reviewed tree** together with its findings bundle:
- **Tree source.** The board's staged review tree, the one whose digest is in the review
  authorization's `staged_tree_sha256`, is copied into the president's stage under
  `sandbox/`, next to `review-bundle.md` and `review-instructions.md`.
- **`PresidentIsolationAuthorization`** — add `staged_tree_sha256`. Three functions bind it,
  and each verifies it equals the board's digest:
  - `prepare_president_isolation_authorization`;
  - `derive_president_leg_authorization`;
  - `activate_president_isolation_authorization`.

  `_president_repo_digest`'s "reads no tree" contract is amended.
- **`_launch_brokered`** — `ParentUnixBroker(staged_dir=stage)` now exposes `sandbox/`. Each
  rung reaches step 1 through the same launchers as a seat:
  - **claude** gets `decide_seat_route(leg, staged_tree_approved=True)` from the president
    authorization, so it runs jailed with tools;
  - **codex** and **grok** get the D6 staged route over `_sandbox_in(stage)`;
  - **gemini** skips by design until PR-B.
- **`_transport`** — routes each rung through `resolve_seat_route`, with these results:
  - **`degraded`:** the rung records `president_unavailable`, and the ladder descends.
  - **Every rung degraded:** `president_ruling_missing:president_no_tooled_route`, and the
    landing fails closed.
  - **Sealed:** never. The `_launch_claude` tools-off argv is unreachable for the president,
    even with the opt-in set.
- **`PRESIDENT_FILL_HEARTBEAT_REFUSED`** — added to `_PRESIDENT_REFUSAL_CODES`, so the
  ladder descends instead of raising. The resolver already skips step 3 under
  `heartbeat_only`. PR-A2 lifts the refusal under the mint guard.
- **`build_president_invoke`** — the brief carries each seat's resolved route.
- **Sequencing rule.** If the tooled president slice is cut from PR-A1, the removal of the
  president's sealed route moves with it to the PR that adds the tooled route. A host never
  gets "no president" where main has one. On main the president is Linux-only (backing gate
  around line 1602), so non-Linux hosts have no president there either.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify; D5)

Every Linux gate, with its disposition:

| Line (about) | Gate | Disposition |
|---|---|---|
| 949 | `prepare_review_composition_authorization` | becomes per seat: no refusal; non-Linux is the step-1 fact |
| 996 | review-isolation preparation | becomes per seat. The authorization records each seat's resolved route. |
| 1054 | `_expected_review_fields` | per seat: checked only for seats whose route is `local` |
| 1153 | launch revalidation | **revalidated at launch**: the platform, and that the route resolved at mint equals the route at launch. A non-Linux `local` route is refused at launch, and a route that changes refuses the seat. |
| 659 | `ParentUnixBroker` (bwrap) | stays Linux-only. Only `local` Linux launches reach it. |
| 1235 | falsifier authorization | stays Linux-only. It is qualification tooling, not a review launch. |
| 1602 | president isolation | becomes per rung, the same as seats |

### `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py` (modify)

- `NOTICE_TEXT` — add these codes, each with its what, why and fix:
  - `seat_not_run_no_tooled_route`;
  - `seat_remote_sandbox_unconfigured`;
  - `sandbox_placement_driver_unavailable`;
  - `seat_local_sandbox_unsupported_os`;
  - `seat_sealed_operator_opt_in`;
  - `president_no_tooled_route`;
  - `seat_host_native_heartbeat_refused`;
  - `claude_seat_nested_tui_unavailable`.
- `SEAT_MODES` — add `remote`.
- `SeatMode` — add the new fields. `render` prints `WARNING: sealed (operator opt-in, NO
  TOOLS) -- unset PHASE_LOOP_SEAT_ALLOW_SEALED`.

### `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `cli.py` (modify)

- `agy_qualification.py` — its direct renderer calls (around lines 301 and 559) pass
  `exemption=_AGY_QUALIFICATION_EXEMPTION`, and its mode line says so.
- `cli.py` `advisor-board` — add `--allow-sealed-seat`.

### `phase-loop-runtime/tests/test_seat_route.py`, `tests/test_president_route.py`, `tests/test_sealed_guard.py` (create)

- **The table.** Every registry harness, crossed with:
  - hosts: Linux with the jail, Linux without user namespaces, macOS, Windows;
  - a remote root configured or not;
  - monitoring policy: bounded or `heartbeat_only`;
  - host: Claude Code or none;
  - the opt-in on or off.
- **Guard.**
  - Every builder, called from every production caller, the president included, with the
    opt-in **both unset and set**.
  - A hand-built `sealed_opt_in` route with the env unset.
  - The AST check on the sentinel.
- **Positive president.**
  - With a qualified jail (faked jail runner, real argv and authorization), the claude rung
    launches **with tools** over the staged tree and returns a ruling.
  - With the jail absent, the codex rung launches on the D6 route with tools and returns a
    ruling.
- **Driver gate.** With a remote root configured and no driver, a spy backend records zero
  calls.
- **Non-Linux.** On a Darwin fake, the board mints and each seat resolves per seat. Launch
  revalidation (the codex r1 F002 falsifier) is exercised with an **injected** non-local
  route, because PR-A1 produces no launched non-local route. A `local` route is refused at
  launch.
- **D1 entry.** The check above, plus: no `SEALED_FALLBACK_CODES` member reaches
  `MODE_SEALED` or a tools-off argv.

### PR-A1 acceptance

- [ ] For every registry harness, a seat target with no tooled route resolves to
  `degraded`, with `seat_not_run_no_tooled_route` and **0** spawns. This includes a claude
  seat under `heartbeat_only` on a Claude Code host fake with no jail.
- [ ] **Positive:** a president claude rung with a qualified jail launches with tools over
  the staged tree and returns a ruling. A codex rung on the D6 route does the same.
- [ ] Under `heartbeat_only` with no jail, the president descends past the claude rung and
  does not raise.
- [ ] A president with every rung degraded yields
  `president_ruling_missing:president_no_tooled_route`, and the landing fails closed.
- [ ] No production caller builds a tools-off argv for the president, whether
  `PHASE_LOOP_SEAT_ALLOW_SEALED` is **unset or set**. The codex r1 F003 and r2 F002
  falsifiers both pass.
- [ ] A seat gets a tools-off argv only with the env opt-in, as read by the guard, or with
  the agy sentinel.
- [ ] On a non-Linux host, the board is not refused, each seat resolves per seat, and a
  `local` route is refused at launch.
- [ ] codex and grok seats keep their D6 staged route, with tools. The credential gate
  never excludes them.
- [ ] With a remote root configured and no driver, step 2 is
  `sandbox_placement_driver_unavailable`, with zero backend calls.
- [ ] Every target's mode is published before the first spawn. A diff check shows
  `LEG_STATUSES` and `DEFAULT_RATIFICATION_POLICIES` unchanged, and `SEAT_MODES` changed
  only by the addition of `remote`.

**Named mutations:**
- spawn a degraded seat;
- **force every president rung's step 1 to skip** (the positive item goes red);
- allow step 3 under `heartbeat_only`;
- drop `president_fill_heartbeat_refused` from the refusal set;
- let the opt-in authorize a president;
- trust `route.step` without re-reading the env;
- reference the agy sentinel from a seat or president call site (AST red);
- restore a whole-board platform gate, or skip launch revalidation;
- make the credential gate exclude codex or grok;
- call `available()` without the driver;
- publish a mode after launch;
- touch a frozen surface.

## PR-A2 — generic host-native fill, mint record, D2 lift, D3 accounting (specified; own detailed plan)

- **Host adapters** — a new `host_native.py` defines the `HostNativeAdapter` protocol:
  - `host_harness`;
  - `detect(env)`;
  - `surface(request)`, which tells the host's sub-agent how to receive the request;
  - `consumer_skill`;
  - `load(fill) -> NativeLegFill`.

  `ClaudeCodeAdapter` is the first adapter, extracted from today's code. A host gets
  `native_subagent=True` in the registry **only** when it has an adapter and a consumer
  skill. Codex stays `False` until both exist, which is a follow-up.
- **Generalised consumers:**
  - `_native_fillable_seats`: any target whose route is `host_native`.
  - `native_fill_request_payload`: the runtime mints the request id; a caller-chosen id is
    refused.
  - `load_native_leg_fill(s)` and `--native-leg`: accept any seat. `filled_by` comes from the
    adapter.
  - The president's native branch: any adapter.
- **Frontier rule.** A stand-in must be a frontier-slot model (the issue's stand-in rule),
  otherwise the target is `degraded`.
- **Mint record (the D2 guard).** When the resolver mints a request, it persists
  `native-mints/<request_id>.json` in the run state:
  - the location is 0600 under a 0700 directory, outside the review tree and outside every
    sandbox;
  - the record holds the operation id, target, `stand_in_for`, `host_harness`, the three
    digests, `minted_at` and `consumed`.

  A fill binds only if a matching, unconsumed record exists. Consumption is atomic and
  happens once, under a lock. A forged `request.json` with no record, even with valid
  digests, is refused with `review_monitoring_unsupported_route:native_fill`, and so is a
  replay.

  **Threat model.** The record guards against a **caller composing fills**, meaning an
  agent writing `request.json`. It does **not** guard against a same-account process that
  edits runtime state.
  - Until PR-B and agent-harness#1222's private homes and namespaces, the D6 codex and grok
    routes are tooled and unconfined, running as the same uid. A prompt-injected seat on
    those routes is such a process, so "outside every sandbox" gives no protection against
    it yet. The plan states this plainly.
  - Once #1222 lands, the mint store moves outside every view those routes have.
  - Each record is also bound to the live operation's **owner** (the invocation and lease
    id), so a record minted by a dead run cannot be consumed by a resumed one.
- **D2 lift.** `resolve_review_monitoring_policy` and `PRESIDENT_FILL_HEARTBEAT_REFUSED`
  allow a minted stand-in under `heartbeat_only`. Such a stand-in records
  `review_monitoring.v1` effective policy `host_native`, never heartbeat evidence.

  **Why agent-harness#908 r4 (d)'s reason no longer applies:** the refusal stopped a fill
  being bound as heartbeat-OK. A minted stand-in is never heartbeat evidence, and an unminted
  fill stays refused.

  **A fill that never arrives** has no deadline. It ends only by cancellation or owner loss,
  and is then `ERROR` with `host_native_fill_abandoned`. It is never counted.
- **D3 effective-vendor accounting:**
  - `board_facts_from` and `board_independence` compute over **effective reviewer
    identities**, meaning the vendor of the model that actually reviewed (taken from
    `_native_fill`). The requested composition digest stays as provenance.
  - `governed_review.py`'s author-disjointness check runs again after resolution. A stand-in
    whose effective vendor is an author is refused, and the target becomes `degraded`.
- **PR-A2 acceptance** covers these cases:
  - **End-to-end fill.** A gemini seat, under a Claude Code host fake, goes through emit →
    mint → fill → load → bind. It counts as a claude-vendor reviewer, and independence
    reports the repeat.
  - **Forged and replayed fills** are refused.
  - **A native president under `heartbeat_only`** binds as `host_native`.
  - **An author-vendor stand-in** is refused.
  - **A non-frontier stand-in** is degraded.
  - **Mutations**, each named:
    - skip the mint check;
    - allow a second consume;
    - count the requested vendor instead of the effective one;
    - skip the author re-check.

## PR-A3 — remote fall-through (after the agent-harness#896 additions)

PR-A3 needs these additions from agent-harness#896. Each names its owner. All of them are
filed on agent-harness#896 (issuecomment-5984291729) and cross-referenced on the 1a
implementation PR agent-harness#1246 (issuecomment-5984291935):

| Addition | Why the resolver needs it | Owner |
|---|---|---|
| A config for **named** remote backends, each with its own root (`self-hosted` → `https://…`, `e2b` → `e2b://…`), resolved through `backend_for_scheme` | 1a supports only a single configured root | an amendment to #896 plan 1a's config |
| A **pre-launch admission** call, `ExecutingBackend.admit(request)`. It may contact the server and raises `PlacementUnavailable(code)`. It runs only when `_NONLOCAL_EXECUTION_DRIVER` is true. | `available()` is a bool with no network access, and "launch is final" forbids falling through after `execute` | #896 plan 1b (the driver) |
| Typed admission codes for self-hosted: no principal token, source not allowed, principal cap exceeded (from the #896 plan-3 requirements) | the mode line and its fix | #896 plan 3 |
| E2B admission codes: key file missing or unsafe, already in plan 4a1's refusal codes | the same | #896 plan 4a1 |
| `created_at` and `confirmed_killed_at` from the lease journal | the R2 duration evidence | #896 plan 1b |
| Lifetime and renewal for a leg **with no deadline** (heartbeat-only seats and the president). 1b refuses a leg whose deadline exceeds `max_lifetime_s`, and never renews past the deadline. | Without it, every remote leg under the standing heartbeat-only mode is refused or undefined. Under R2 the TTL is a liveness bound. | #896 plan 1b, as an open question |

**PR-A3 changes:**
- replace the step-2 shim with an ordered `admit()` walk over `remote_backends`;
- map each admission code to a `seat_remote_*` notice and fix;
- produce mode `remote` with `placement.{backend, sandbox_id, created_at,
  confirmed_killed_at, duration_s}`;
- add the capabilities card entry for R2.

**PR-A3 acceptance** uses only codes those plans define. Fakes stand in for transport only,
never for behaviour that no plan produces.

## Governance

- A degraded target is not counted (`_effective_vendors`, EC-REVIEWTRUTH-1 and -4).
- PR-A1 produces no cross-vendor stand-in, because its only adapter fills a claude seat with
  the same model.
- PR-A2 adds D3 effective-vendor accounting before any cross-vendor stand-in can exist.
- The quorum rules are unchanged.

## Documentation impact

- **`advisor_board/CONTRACTS.md`** (PR-A1):
  - a "Seat route resolver (agent-harness#1244)" section;
  - the **HARDEN amendment (D4)**: for seats, sealed only on the env opt-in or for the agy
    qualification sentinel; the **president** is never sealed;
  - the president's tree contract: the president reads the staged reviewed tree;
  - the new codes and the `remote` mode.

  PR-A2 adds the "Review monitoring policy v1" exception for minted stand-ins (D2).
- **`phase-loop-skills/advisor-board/SKILL.md`** — PR-A1 adds the chain. The host consumer
  skills come with PR-A2.
- **`CHANGELOG.md`** — PR-A1 records these behaviour changes:
  - no sealed fallback;
  - a tooled president with the reviewed tree;
  - non-Linux boards resolved per seat;
  - a claude seat under Claude Code is jailed first;
  - non-governed tooled legs are relabelled from `sealed` to `unconfined`. PR-A2 and PR-A3 each add their own entry.
- **`docs/advisor-board-capabilities-card.md`** — PR-A3 adds:
  - the remote order;
  - E2B's per-sandbox-second cost, with no runtime cap;
  - the account-side spending limit as the operator's guard;
  - where duration evidence is recorded;
  - the key-file contract.

## Dependencies & order

1. PR-A1 depends on agent-harness#1222, and on agent-harness#1166 merged with its D1 change
   (the entry check above).
2. PR-A2 depends on PR-A1.
3. PR-A3 depends on PR-A1 and on #896 1a + 1b, plus the additions above. Real backends then
   arrive with plan 3 and with plan 4a1 → 4a2 → 4b (agent-harness#1165), which run in
   parallel after 1b.
4. PR-B depends on PR-A1, and on #896 1a for the `local` backend kind.

## Verification (PR-A1)

```bash
cd phase-loop-runtime
uv run pytest tests/test_seat_route.py tests/test_president_route.py tests/test_seat_notices.py tests/test_seat_jail*.py -q
uv run pytest tests -q -k "president or native_fill or monitoring_policy or review_isolation or premerge"
```

There is no grep check. The argv-level guard test and the president test are the checks.

## Follow-ups

- **PR-A2 and PR-A3**, as specified above, each with its own detailed plan.
- **PR-B**: the srt local backend, built from the evidence file. It covers macOS first, then
  the Linux conformance suite, then Gemini egress with optional TLS inspection. It closes
  agent-harness#1170 as superseded.
- **Codex host adapter and consumer skill.** Then `native_subagent=True` for codex.
- **Credential adapters** for the srt and remote routes: codex, gemini/agy, grok and the
  omnigent harnesses.
- **Executor sandboxing.** Executors run with tools today but without a sandbox. That is
  outside these PRs; the end goal of agent-harness#1244 covers it.
- **Fleet dotfiles**: provision the E2B key file.
- **Removing the sealed opt-in** once steps 1–3 cover the supported hosts.

## Execution Policy

- execute: effort=high, reason=security-relevant route selection across every board and president path
