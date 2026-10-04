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
with tools, or else is degraded and not run. The one exception is the temporary president
last resort (P-LR). Harness-specific code is kept to thin adapters
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
   order configured by agent-harness#1246's `[sandbox] roots.<name>` and `[sandbox] order`
   in the user `advisor-boards.toml` (R1). `PHASE_LOOP_SANDBOX_ROOT` is the alias for a
   single root. The self-hosted backend must meet the
   requirements in agent-harness#896 issuecomment-5983731656. E2B follows plan 4, which keeps
   its key custody and adds no runtime caps (R2).
3. **Host-native fill.** The host harness's own sub-agent fills the seat as a labelled
   stand-in, which counts as its own vendor (D3). The host must have an adapter. This step
   is taken only when the monitoring policy admits a native fill. Under `heartbeat_only` it
   is skipped with a typed reason until PR-A2 lifts the refusal (D2).
4. **Degraded, not run.** The seat gets a typed notice with its fix, shown in the pre-launch
   mode line. For the president, P-LR (the sealed last resort) applies first, where main had
   a president. Only when that cannot run either (for example on non-Linux, as on main) does
   the landing gate report "no president" (`president_no_tooled_route`).

**Sealed** (inlined and toolless) is never a step:
- For a **seat**, it runs only when `PHASE_LOOP_SEAT_ALLOW_SEALED=1` is set (D4), and then
  only after steps 1–3 have all failed. It is announced loudly.
- The **president** is never sealed by the opt-in. Its only sealed path is the ruled
  **president last resort** (P-LR): it applies after every president rung has failed to find
  a tooled route, it is announced loudly, and it is temporary.
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
| D4 | For seats only, sealed is opt-in (`PHASE_LOOP_SEAT_ALLOW_SEALED=1`) with a loud mode line. This needs a HARDEN/CONTRACTS amendment. agy qualification is the only exemption. The president is never sealed by the opt-in; see P-LR. |
| D5 | Non-Linux hosts are resolved per seat (agent-harness#1098). |
| D6 | codex and grok keep their current tool-enabled staged route until srt covers them. |
| President | The president goes through the same chain as seats. Every tooled rung is tried first: the local jail or D6, then remote, then native when admitted. A host never gets "no president" where main had a president. |
| P-LR | **"Number 2 until the sandboxes are available for all harnesses."** This is a temporary exception for the **president only**; seats remain never-toolless. When no president rung has a tooled route, the existing toolless (sealed) president runs as the **last resort**. The mode line and the evidence carry `president_sealed_last_resort`, the per-rung reasons, and the fix "make a sandbox available: …". **Sunset:** the exception is removed when sandboxes cover every harness, which is agent-harness#1244's end goal. The removal is tracked in agent-harness#1250. A host where the president has a tooled route never gets the last resort. |
| S1–S4 | srt adoption: macOS first; the Linux jail stays until srt passes the conformance suite; Windows goes to remote; srt egress supersedes agent-harness#1170; srt TLS inspection is used for Gemini if needed. Detail is in the evidence file. |
| R1 | The remote order defaults to `["self-hosted", "e2b"]`. The key is agent-harness#1246's `[sandbox] order`, over `[sandbox] roots.<name>`, read through `sandbox_policy.configured_roots()`. It is not a new key. |
| M1 | With `PHASE_LOOP_SANDBOX_DISABLE=1`, or after a `git rev-parse` failure or timeout, the president is refused with `president_ruling_missing:president_snapshot_missing`. The fix line is "unset PHASE_LOOP_SANDBOX_DISABLE, or retry". P-LR does **not** extend to these cases. |
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
    the D6 staged route, which counts as step 1, passes no adapter gate, and is always
    tooled; it has no separate host qualification. For gemini, a skip with
    `gemini_seat_egress_unconfined` until PR-B (S3/S4). **On the agy qualification board**
    (see case (d)), the gemini seat instead resolves to step `qualification_sealed` with
    mode `sealed`, because that board exists to qualify the sealed agy route. For a non-Linux host, a
    skip with `seat_local_sandbox_unsupported_os`.
  - **Step 2, `remote`:** the step-2 shim below.
  - **Step 3, `host`:** taken only when all of these hold:
    - the host-native adapter registry (PR-A2) has an adapter for the host;
    - that adapter can fill this target;
    - the new resolver input `native_admitted` is true. It is false under `heartbeat_only`
      until PR-A2, and the step is skipped with `seat_host_native_heartbeat_refused`.

    If the host has no adapter, or the adapter cannot fill this target, the step is skipped
    with `seat_host_native_unavailable`. That covers a plain terminal, and every codex,
    grok or gemini target in PR-A1.

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
- **Sealed guard at the argv level.** `_require_tooled_or_permitted(*, capability)` is
  called inside every **launch** builder that can produce a tools-off launch:
  - `_render_broker_inline_prompt` with `staged_tree=None`;
  - `_broker_claude_tui_command` with `sandboxed=None`;
  - `_brokered_gemini_command` with `staged_tree=None`;
  - the brokered codex `read-only` argv builder;
  - the grok `--tools ""` argv builder.

  `_broker_tool_controls` only derives evidence and carries no guard.

  **Capability threading (modified sites).** Each of the five builders gains a keyword-only
  `capability=None` parameter, the leg authorization of the launch it builds. The callers
  pass it:
  - `_default_spawn` passes its `leg_authorization` into `_exec_leg(capability=)` (codex,
    gemini and grok builders) and `_exec_claude_tui_leg(capability=)` (the claude TUI
    builder). Both are modified sites;
  - the president's `_launch_brokered` passes its `leg` down through
    `_transport(..., leg=)` into `_launch_claude` and the gemini launch, and through
    `_exec_leg(capability=)` into the codex and grok launches (president_adapter.py around
    :262).

  **The bounded injected-seam branch of `__call__`** (around president_adapter.py:217-226)
  has no leg, because `derive` runs only in `_launch_brokered`. It passes
  `capability=None`. Any real tools-off builder it reaches is therefore refused. The seam
  is never evidence. A frozen-corpus president test that drives the seam into a real
  tools-off builder must stub at or below the builder; the implementer lists any such test
  with its disposition.

  The guard is called directly in each builder's body, never through a decorator or helper,
  so the depth-2 frame below is exact.

  `agy_qualification.py`'s two preparatory renders pass nothing. They have no signature
  change and are admitted by case (c). Its worker launch is admitted by case (d).

  **Target kind is positive.** The kind is read from the capability:
  - a **seat** is a capability whose operation is the review operation
    (`public_board_review.v1`);
  - a **president** is a capability whose operation is `PRESIDENT_OPERATION_V1`;
  - **no capability** is neither of these, and is refused unless case (c) holds.

  The guard passes in exactly four cases:
  - **(a) Seat opt-in.** A seat capability is present, and the guard itself reads
    `sealed_opt_in_enabled(base_env)` and finds it set. `base_env` is the `invoke_board`
    env, which defaults to `os.environ` and is set by `--allow-sealed-seat`. The guard
    never trusts a caller-built `ResolvedSeatRoute`.
  - **(b) President last resort.** A president capability carries
    `sealed_last_resort=True`. Only `derive_president_leg_authorization` sets it, and only
    after it has **recomputed P-LR eligibility itself** (see "Last resort").
  - **(c) agy qualification.** The capability is `None`, and the **builder's caller**
    frame, `sys._getframe(2)` (exactly that frame, not any ancestor), satisfies both of
    these:
    - `f_code is` `agy_qualification.validate_directory.__code__` or `run_operation.__code__`;
    - `f_globals is vars(agy_qualification)`.

    A `types.FunctionType` rebuilt over that code object with foreign globals therefore
    fails. The remaining residue is monkeypatching `agy_qualification`'s own globals; the
    tripwire covers it, not the boundary. It is bounded in any case, because the two exempt
    sites render fixed text or render only to hash recorded inputs.

  - **(d) The agy qualification worker launch** (codex r5 F001). `agy_qualification.worker`
    runs `invoke_board(mode="review", monitoring_policy="heartbeat_only")` over a
    gemini-only board. Its renderer caller is `_default_spawn`, which carries a genuine
    `public_board_review.v1` leg, so cases (a) and (c) cannot admit it. Instead, the
    **review authorization records qualification provenance at mint**:
    - `prepare_review_isolation_authorization` sets `qualification_board=True` on the
      sealed `ReviewIsolationAuthorization` only after checking the **exact** call chain
      from its own frame: `prepare` ← `invoke_board` (code identity), with any number of
      `invoke_board` pin re-entries (`_INVOKE_BOARD(**call)`, code identity), ←
      `agy_qualification.worker`. The worker is checked by `f_code is worker.__code__` and
      `f_globals is vars(agy_qualification)`.
    - The chain must also show a gemini-only board.
    - There is no parameter for the flag, so no caller can request it.
    - The check runs **at mint, not at render**, because seat spawns run on pool threads
      where `invoke_board` is not on the stack. A render-time stack walk finds no
      `invoke_board` frame; this was verified on the real worker path.
    - `derive_review_leg_authorization` copies the flag onto each leg. The guard admits a
      **seat** capability with `qualification_board=True`, with the opt-in unset.
    - The resolver resolves that board's gemini seat to `qualification_sealed` (above).

    Every other board, including a board that some other function builds and passes into
    `invoke_board`, mints `qualification_board=False`. A `FunctionType` rebuild of `worker`
    with foreign globals fails the globals check. The residue, monkeypatching
    `agy_qualification`'s globals, is the same as case (c), and the tripwire covers it.

  Otherwise the guard raises `seat_route_sealed_without_opt_in`.

  The static **tripwire**, which is not the boundary, scans the package and the
  phase-loop-skills scripts and flags:
  - string constants that name the agy functions;
  - non-literal `getattr`, `vars` or `__dict__` on `panel_invoker` or `agy_qualification`;
  - `.__code__`, `FunctionType` / `CodeType`, or `f_code` outside the guard.
- **Claude under Claude Code: jailed first** (#1166 sites). The
  `not (leg == "claude" and _under_claude_code(env))` clause in `_seat_route_for_spawn`'s
  eligibility (around :10088) is removed. The `under_claude_code` deferral in
  `_exec_claude_tui_leg` (around :8382) then applies only when the resolved route is
  `host_native`. The `MODE_NATIVE` publish (around :1662) comes from the resolver.

  A jailed TUI runs with the jail's own env and home, not the host session's. #1166 notes
  that the nested self-PTY adapter is unavailable inside Claude Code, so jailed-first under
  Claude Code is gated on a **pre-resolution fact**, `nested_tui_qualified`. It is recorded
  by running the jail qualification once from a Claude Code session. It is stored with the
  jail qualification records, keyed by the Claude CLI version, the kernel and the jail
  digest, and it expires with the jail pass. A stale or missing fact means the step is
  skipped.

  Until that fact is recorded, step 1 skips **before resolution** with
  `claude_seat_nested_tui_unavailable`, never at launch. A **bounded** Claude Code board then
  fills the claude seat and the claude president natively at step 3, exactly as main does.
  So PR-A1 is never worse there.
- `invoke_board` — modify — a `degraded` route returns `DEGRADED`, `seat_not_run:<reason>`,
  with **zero** spawns.
- `_under_claude_code` route decisions — modify — use `detect_host_harness(env)` together
  with the adapter registry.

### Tooled president (`president_adapter.py`, `panel_invoker.py`, `advisor_board/backing.py`)

**The tree: retained, threaded, and re-hashed.**
1. **Retained snapshot.** `invoke_board` stages **one** pristine reviewed tree with
   `stage_review_tree(canonical_repo, board_dir)`, at the same time as it mints the review
   authorization. The snapshot is the source of that authorization's `staged_tree_sha256`.
   `prepare_review_isolation_authorization` changes too. It digests the **snapshot**,
   where today it digests the live repo (around #1166 `backing.py:1027`), and it asserts
   that `digest(snapshot)` equals the minted digest.

   The snapshot is made read-only and kept under the runtime's 0700 state directory,
   outside every review and seat directory, until the president returns. It is removed in
   `invoke_board`'s `finally`. Seats keep their own writable clones as today.

   The unconfined D6 seats run as the same uid, so a seat could still `chmod` the snapshot
   and edit it. The re-hash catches that and fails closed. The plan accepts this as a
   denial, not a bypass.

   Because the snapshot is retained, the president never re-stages from the live repo, and a
   working tree edited after the seats ran cannot reach it.
2. **Threading.** After minting, `invoke_board` calls
   `president_invoke.bind_review_tree(digest, snapshot_path)`. It does this for the
   auto-wired invoke and for the invokes built earlier by `runner.py` (around :8580) and
   `cli.py` (around :2317).

   **The president fails closed** with `president_ruling_missing:<code>`, and never
   reaches P-LR, in each of these cases:
   - an unbound `PresidentInvoke`, including `run_president_operation` walks that never pass
     through `invoke_board` (`president_tree_unbound`);
   - no snapshot because of a `git rev-parse` failure or timeout
     (`president_snapshot_missing`);
   - `PHASE_LOOP_SANDBOX_DISABLE=1` (`president_snapshot_missing`).

   Under `PHASE_LOOP_SANDBOX_DISABLE=1`, seats skip step 1 with `seat_sandbox_disabled`,
   whose fix is "unset PHASE_LOOP_SANDBOX_DISABLE", and degrade under D4. On main the
   president runs sealed there; ruled M1 refuses it. The fix line is "unset
   PHASE_LOOP_SANDBOX_DISABLE, or retry".
3. **Per-rung copy at the readers' path.** Each rung's stage receives a fresh writable copy
   of the snapshot at **`<stage>/reviewed-tree`**, with its
   `.git/phase-loop-source-commit` marker kept. That is the path `_sandbox_in` and the jail
   (`HOST_TREE_DIRNAME`) read.
4. **Re-hash before every launch.** Immediately before each rung launches,
   `review_tree_manifest_sha256(<stage>/reviewed-tree)` must equal the bound digest. In
   addition:
   - the president leg capability (`derive_president_leg_authorization`) gains
     `staged_tree_sha256`;
   - `ParentUnixBroker` re-hashes `reviewed-tree` against it at init, which covers the D6
     codex and grok rungs;
   - the jail re-hashes as it already does;
   - `revalidate_president_isolation_authorization` gains `staged_dir`;
   - the claude rung's `staged_tree_approved` comes from this check, never a literal.

   A mismatch fails the president **closed** with
   `president_ruling_missing:president_stage_changed`. Tampering is not descended past.
   `president_stage_changed`, `president_tree_unbound` and `president_snapshot_missing`
   join `_PRESIDENT_REFUSAL_CODES`, so each one surfaces as a typed refusal, not an
   exception.

   The per-rung copy is a real copy, or a reflink where the filesystem supports one. It is
   never a hard link, because rung writes would then mutate the snapshot.
5. **`PresidentIsolationAuthorization`** gains `staged_tree_sha256`. Prepare, derive,
   activate and revalidate each bind it. `_president_repo_digest`'s "reads no tree" contract
   is amended.

**Rungs:**
- **claude:** the jail, or step 3 native (a claude **president** too) when admitted.
- **codex and grok:** D6 over `_sandbox_in(stage)`. These rungs are always tooled. There is no separate D6
  qualification, and a missing tree is an M1 case, not a capability skip.
- **gemini:** skips until PR-B.

**Descent (the actual mechanism).** `invoke_president` (around `panel_invoker.py:731`)
descends only on `{"status": "unavailable", "code": "president_unavailable"}`. So:
- **`PresidentInvoke.__call__`** (around `president_adapter.py:169-170`) no longer sends the
  claude rung native ahead of the resolver. Every rung is resolved first in `__call__`, with
  the jail first.
- **A step-3 skip, or a `degraded` route,** returns `unavailable` / `president_unavailable`,
  so the walk descends.
- **`president_fill_heartbeat_refused`** is added to `_PRESIDENT_REFUSAL_CODES` only as a
  typed backstop.
- **A rung whose tooled launch fails before any provider process starts** (jail build,
  broker re-hash, copy) returns `president_unavailable`, so the walk descends. No model ran,
  so descending is safe. Such a failure is not a host-capability code, so it can never make
  P-LR eligible. A failure **after** spawn stays `president_invocation_failed` with no
  descent, which is parity with main.

**Last resort (P-LR).**
- **Eligibility.** P-LR is eligible only when **every** seated rung, at every step that
  applies to it, was skipped with a code in the frozen literal set below. A module constant
  holds it, and an equality test pins it:

  ```python
  PLR_HOST_CAPABILITY_CODES = frozenset({
      # step 1, jail prerequisites (#1166 seat_jail.NOTICES); a root operator surfaces as
      # seat_sandbox_unavailable_seat_uid (seat_uid.seat_uid_available returns False for uid 0)
      "seat_sandbox_unavailable_host",
      "seat_sandbox_unavailable_seat_uid",
      "seat_sandbox_unavailable_tiocsti",
      # step 1, Claude under Claude Code before the nested-TUI fact exists
      "claude_seat_nested_tui_unavailable",
      # step 1, gemini until PR-B (the only gemini step-1 code this resolver emits)
      "gemini_seat_egress_unconfined",
      # step 2, PR-A1 shim
      "seat_remote_sandbox_unconfigured",
      "sandbox_placement_driver_unavailable",
      # step 3
      "seat_host_native_unavailable",
      "seat_host_native_heartbeat_refused",
  })
  ```

  - There is **no D6 entry**. D6 rungs are always tooled, and the M1 cases are not host
    capability.
  - #1166's other gemini sealed codes (credential, scope, stream-split, profile) are not
    emitted by this resolver: it skips gemini on `gemini_seat_egress_unconfined` before
    #1166's gemini decision runs. They are therefore excluded.
  - PR-A3 extends the set with the remote admission codes that describe a host or account
    without a usable remote sandbox: `seat_remote_no_principal_token`,
    `seat_remote_source_not_allowed`, and E2B key-file missing. `seat_remote_principal_cap_exceeded`
    is excluded because it is transient, and PR-A3 states its disposition.
- **Excluded.** Any other code fails the president closed, and never reaches P-LR. That
  includes:
  - wiring faults: `president_tree_unbound`, `president_snapshot_missing`,
    `president_stage_changed`;
  - a pre-spawn launch failure;
  - an unknown code.
- **Recomputed, never trusted.** `derive_president_leg_authorization` accepts no walk
  records. It also requires the president authorization's `staged_tree_sha256` and a
  bound, present snapshot (M1) before it will set the flag. To set `sealed_last_resort`, it re-runs the resolver over the authorized ladder
  and the board's seats from host facts it gathers itself: the platform, the jail
  prerequisites, the D6 qualification, the monitoring policy, the host harness and the
  remote config. It sets the flag only if that recomputation is P-LR-eligible. A caller that
  passes fabricated all-skip resolutions gains nothing.
- **Which rung: main's walk, exactly, including where main stops.** Walk the seated,
  routed rungs in ladder order, the way main's walk does. Rungs with no seat are skipped,
  as main skips them with `president_unavailable`.
  - If the walk reaches a rung where **main raises**, there is no P-LR rung, and the result
    is `president_no_tooled_route`. That rung is a claude rung under Claude Code with
    `heartbeat_only`, where main's `_native_fill` raises `president_fill_heartbeat_refused`.
  - Otherwise, the first seated rung is the P-LR rung.
  - Under Claude Code with bounded monitoring, the claude rung resolves to step 3 (native),
    so P-LR is never reached there.
  - The P-LR launch site is `invoke_president`'s walk, after the last rung. It re-derives
    the leg for the chosen rung and runs the existing sealed president for it.
- **Terminal code when P-LR is ineligible.** The walk returns
  `president_ruling_missing:<first excluded code>` when any rung's skip was excluded: a
  wiring fault, a pre-spawn failure, or an unknown code. It returns
  `president_ruling_missing:president_no_tooled_route` only when every skip was
  allowlisted but no P-LR rung exists. A pre-spawn failure is recorded in `tried` with its
  real cause (for example `seat_sandbox_refused:jail_build`), not as the bare
  `president_unavailable`.
- **Loudness.**
  - Mode line: `WARNING: president sealed (LAST RESORT, NO TOOLS) -- <per-rung reasons>;
    fix: make a sandbox available: …`.
  - Evidence: `president_sealed_last_resort: true`, the per-rung `tried` codes, and the
    sunset issue agent-harness#1250.

The guard admits that launch through case (b) only. The opt-in plays no part.

**Main-supported host classes** (the parity table):

| Host class | Main | PR-A1 |
|---|---|---|
| Linux, jail-capable, outside Claude Code | brokered sealed president | tooled president (jail / D6) |
| Linux, jail-incapable (kernel before 6.2, i.e. no `dev.tty.legacy_tiocsti`; root; no subuid or `newuidmap`), codex/grok rungs usable | brokered sealed | tooled president on D6 |
| Linux, jail-incapable, only a claude rung (or a gemini-only ladder) | brokered sealed | **P-LR sealed last resort** with the warning |
| Claude Code, bounded, nested TUI not qualified | native claude president | the same native president (step 3) |
| Claude Code, `heartbeat_only`, claude is the first seated rung (e.g. `["fable","gemini"]`, or the default ladder, which ends in gemini) | **raises** `president_fill_heartbeat_refused`: not in main's `_PRESIDENT_REFUSAL_CODES`, so `invoke_board` re-raises it. **No president.** | descends to a **tooled** codex or grok rung, which is an improvement. Otherwise typed `president_no_tooled_route`. **Never a sealed president**, gemini included, because main had none. |
| Claude Code, `heartbeat_only`, a non-claude rung seated before claude (e.g. `["gemini","fable"]`) | runs the earlier rung sealed | tooled if that rung has a tooled route; else P-LR on it, which is legitimate because main reached it |
| top ladder rung has no seat on the board | the walk skips it (`president_unavailable`) and runs the first seated rung | the same: skipped. P-LR, when eligible, uses the first seated rung. |
| non-Linux, `invoke_board` path | the board is refused whole (backing ~949), so there is no president walk | the board now runs per seat (D5). Under Claude Code bounded, the president is native at step 3; otherwise typed `president_no_tooled_route`. `seat_local_sandbox_unsupported_os` is outside the allowlist, so P-LR never runs. |
| non-Linux, standalone walk (`invoke_president` / `run_president_operation`), Claude Code bounded | native claude president (the `__call__` pre-check runs before the Linux gate) | native president at step 3, given a bound snapshot. Unbound means `president_tree_unbound`. |

- **`build_president_invoke`** — the brief carries each seat's resolved route.

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
  - `claude_seat_nested_tui_unavailable`;
  - `president_sealed_last_resort`;
  - `president_stage_changed`;
  - `president_tree_unbound`;
  - `president_snapshot_missing`;
  - `seat_sandbox_disabled`;
  - `seat_host_native_unavailable`.
- `SEAT_MODES` — add `remote`.
- `SeatMode` — add the new fields. `render` prints `WARNING: sealed (operator opt-in, NO
  TOOLS) -- unset PHASE_LOOP_SEAT_ALLOW_SEALED`.

### `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `cli.py` (modify)

- `agy_qualification.py` — no signature change. Its two renderer calls (around lines 301
  and 559) are admitted by the guard's code-object check. Its mode line says so.
- `cli.py` `advisor-board` — add `--allow-sealed-seat`.

### `phase-loop-runtime/tests/test_seat_route.py`, `tests/test_president_route.py`, `tests/test_sealed_guard.py` (create)

- **The table.** Every registry harness, crossed with:
  - host OS: Linux with the jail, Linux without the jail, macOS, Windows;
  - a remote root configured or not;
  - monitoring policy: bounded or `heartbeat_only`;
  - host: Claude Code, with and without `nested_tui_qualified`, or none;
  - the opt-in on or off.
- **Guard.**
  - Every launch builder, from every production caller, the president included, with the
    opt-in unset and set.
  - A hand-built `sealed_opt_in` route.
  - A caller that reaches the agy functions' `__code__` objects, or the guard, through
    `getattr`, `vars` or a re-export. It is refused, because its frame is not the
    qualification frame.
  - A president capability presented from inside an agy frame is refused.
  - A president target dressed as a seat is refused. The kind comes from the capability.
  - The tripwire scan.
- **President tree.**
  - Positive: the claude rung, jailed, and the codex rung, on D6, each receive
    `<stage>/reviewed-tree` matching the board digest, launch with tools, and return a
    ruling.
  - Substituted tree: one byte changed in the rung's copy, or in the snapshot, gives
    `president_stage_changed`, and no rung launches.
  - Unbound invoke: `president_tree_unbound`.
- **Descent.** On a **Claude Code host fake** under `heartbeat_only`, the claude rung
  returns `president_unavailable` and the walk reaches the codex rung.
- **Guard additions.**
  - A president builder call with **no capability** and the opt-in set is refused.
  - agy qualification's two real calls pass. **(This is the positive case.)** It adopts
    codex's r4 F001 probe with the frame-2 + `f_globals` check.
  - A `FunctionType` rebuilt over the qualification code with foreign globals is refused.
  - The r5 models are at `/mnt/workspace/board-tools/plan1244-work/r5`. Codex's r5 F001
    probe is red against the eb9737a2 spec. Against this spec, the case-(d) positive and
    negative models (mint-time chain check) are green, and so are the stop-rule models and
    the claude r5 probe.
  - **The worker path (codex r5 F001 probe, positive):** `agy_qualification.worker` → the
    real `invoke_board` → `_default_spawn` → the renderer is admitted through case (d),
    with the opt-in unset.
  - **The worker path, negative:** the same gemini-only board passed to `invoke_board` from
    a different function mints `qualification_board=False` and is refused. A `worker`
    rebuilt with foreign globals is refused.
  - Positive admissions for case (a) through `_exec_leg` and `_exec_claude_tui_leg`, and
    for case (b) through a P-LR codex or grok rung.
- **P-LR exclusions.** On a capable host fake, none of these gives a sealed launch:
  - an unbound invoke;
  - a missing snapshot;
  - `PHASE_LOOP_SANDBOX_DISABLE=1`;
  - a caller passing fabricated all-skip resolutions to `derive`;
  - a pre-spawn launch failure.

  codex's r4 F002 probe (`ladder=["gemini","fable"]` on a claude-only board) yields the
  `fable` rung.

  **The R1/H1 shape:** a claude+gemini board, `ladder=["fable","gemini"]`, `CLAUDECODE=1`,
  `heartbeat_only` gives `president_no_tooled_route` with **zero** sealed launches. This is
  the r5 probe `test_r5_cc_hb_claude_first_gemini.py`. The converse, `["gemini","fable"]`,
  gives P-LR on gemini on a jail-incapable host. On a plain terminal that is jail-incapable
  with a claude-only ladder, P-LR runs with the warning, and the step-3 code is not stubbed
  away.

  On Claude Code with `heartbeat_only` and a claude-only ladder, the result is
  `president_no_tooled_route` with no sealed launch. With a seatless top rung, P-LR uses
  the first seated rung.
- **P-LR.**
  - On a jail-incapable host fake with only a claude rung: a sealed last-resort president,
    with the warning and the evidence.
  - On a capable host: never.
  - With a gemini-only ladder (codex r3 F002): last resort.
- **Parity.** One row per main-supported host class in the table above.
- **Driver gate, non-Linux and D1 entry:** as before. A spy backend sees zero calls. The
  revalidation test uses an injected non-local route. No `SEALED_FALLBACK_CODES` member
  reaches sealed, except through P-LR for the president.

### PR-A1 acceptance

- [ ] For every registry harness, a seat with no tooled route resolves to `degraded`, with
  `seat_not_run_no_tooled_route` and **0** spawns. That includes a claude seat under
  `heartbeat_only` on a Claude Code host fake with no jail. **Seats are never sealed
  without the env opt-in.**
- [ ] **Positive president:** the claude rung, jailed, and the codex rung, on D6, launch
  with tools over a `reviewed-tree` that matches the board digest, and return a ruling. A
  substituted tree gives `president_stage_changed`, and no rung launches.
- [ ] On a **Claude Code host fake** under `heartbeat_only`, the president descends past
  the claude rung via `president_unavailable`, and does not raise.
- [ ] **P-LR:** on a jail-incapable host with only a claude rung, the president runs
  sealed as the last resort, with `president_sealed_last_resort`, the per-rung reasons and
  the fix, in both the mode line and the evidence. On a host with a tooled rung, the last
  resort is **never** used.
- [ ] Every main-supported host class in the parity table has a president in PR-A1. Where
  main had none (non-Linux; Claude Code with `heartbeat_only` and claude first), PR-A1
  adds no sealed president.
- [ ] P-LR engages only through the host-capability allowlist, recomputed by `derive`.
  Wiring faults, a missing snapshot, the sandbox-disable knob, fabricated resolutions and
  pre-spawn failures all fail closed on a capable host.
- [ ] A builder call with no capability is refused unless it comes from the real agy
  qualification frames. Those two calls pass. The agy qualification **worker** launch
  passes through case (d), and the same board launched from any other function is
  refused.
- [ ] Under Claude Code with `heartbeat_only` and `ladder=["fable","gemini"]`, there is no
  sealed launch, and the result is `president_no_tooled_route`.
- [ ] `PLR_HOST_CAPABILITY_CODES` equals the literal set in this plan.
- [ ] The guard admits a tools-off launch only through cases (a), (b), (c) and (d). The opt-in
  never admits a president, and reflective access never admits the agy case.
- [ ] On a non-Linux host, the board is not refused. Seats resolve per seat, and a `local`
  route is refused at launch.
- [ ] codex and grok seats keep their D6 route with tools. The credential gate never
  excludes them.
- [ ] With a remote root configured and no driver, step 2 is
  `sandbox_placement_driver_unavailable`, with zero backend calls.
- [ ] Every target's mode is published before the first spawn. A diff check shows
  `LEG_STATUSES` and `DEFAULT_RATIFICATION_POLICIES` unchanged, and `SEAT_MODES` changed
  only by the addition of `remote`.

**Named mutations**, each of which must turn its item red:
- spawn a degraded seat;
- force every president rung's step 1 to skip with a **non-allowlisted** code on a capable
  host: P-LR must not engage, so the positive item goes red;
- let `president_tree_unbound` count toward P-LR;
- `derive` trusts caller-supplied resolutions;
- P-LR picks ladder[0] instead of main's first launched rung;
- engage P-LR under Claude Code with `heartbeat_only` where main had no president, using
  the `["fable","gemini"]` ladder;
- skip past a stopping claude rung instead of stopping;
- add a code to `PLR_HOST_CAPABILITY_CODES`, or let `derive` set the flag with no bound
  snapshot;
- drop case (d), or admit a non-worker caller through it;
- classify a missing capability as a seat;
- check `sys._getframe(1)`, or skip the `f_globals` check;
- skip the president tree re-hash;
- stage the president from the live repo instead of the snapshot;
- **restore `__call__`'s native pre-check under `heartbeat_only`**;
- engage P-LR while a tooled rung exists;
- let the opt-in admit a president;
- admit the agy case by symbol instead of by frame;
- trust a caller-asserted target kind;
- restore a whole-board platform gate;
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
| Named remote roots and their order: `[sandbox] roots.<name>` and `[sandbox] order` (default `["self-hosted","e2b"]`), read by `sandbox_policy.configured_roots()` | 1a supported only a single configured root | **delivered** by agent-harness#1246 |
| A **pre-launch admission** call, `ExecutingBackend.admit(request)`. It may contact the server and raises `PlacementUnavailable(code)`. It runs only when `_NONLOCAL_EXECUTION_DRIVER` is true. | `available()` is a bool with no network access, and "launch is final" forbids falling through after `execute` | #896 plan 1b (the driver) |
| Typed admission codes for self-hosted: no principal token, source not allowed, principal cap exceeded (from the #896 plan-3 requirements) | the mode line and its fix | #896 plan 3 |
| E2B admission codes: key file missing or unsafe, already in plan 4a1's refusal codes | the same | #896 plan 4a1 |
| `created_at` and `confirmed_killed_at` from the lease journal | the R2 duration evidence | #896 plan 1b |
| Lifetime and renewal for a leg **with no deadline** (heartbeat-only seats and the president). 1b refuses a leg whose deadline exceeds `max_lifetime_s`, and never renews past the deadline. | Without it, every remote leg under the standing heartbeat-only mode is refused or undefined. Under R2 the TTL is a liveness bound. | #896 plan 1b, as an open question |

**PR-A3 changes:**
- extend `PLR_HOST_CAPABILITY_CODES` with the remote admission codes listed under "Last resort", and state the disposition of each excluded code;
- replace the step-2 shim with an ordered `admit()` walk over `sandbox_policy.configured_roots()`;
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
  - the **HARDEN amendment (D4 and P-LR)**:
    - for seats, sealed runs only on the env opt-in, or from the agy qualification frames;
    - the president is never sealed by the opt-in;
    - the president runs sealed only as the P-LR last resort, with its sunset condition;
  - the president's tree contract: the president reads the staged reviewed tree.
    `PresidentInvoke.bind_review_tree` is now part of the public president API. An unbound
    `run_president_operation` walk fails closed with `president_tree_unbound`, and the fix
    is to bind the board's snapshot;
  - the agy qualification provenance (case (d)) and the `qualification_sealed` step;
  - the new codes and the `remote` mode.

  PR-A2 adds the "Review monitoring policy v1" exception for minted stand-ins (D2).
- **`phase-loop-skills/advisor-board/SKILL.md`** — PR-A1 adds the chain. The host consumer
  skills come with PR-A2.
- **`CHANGELOG.md`** — PR-A1 records these behaviour changes:
  - no sealed fallback;
  - a tooled president with the retained reviewed tree;
  - the president last resort (P-LR), with its warning;
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
- **Removing the sealed opt-in and P-LR** once sandboxes cover every harness (the P-LR sunset).

## Execution Policy

- execute: effort=high, reason=security-relevant route selection across every board and president path
