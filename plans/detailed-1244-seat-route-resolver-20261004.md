---
status: planned
issue: agent-harness#1244
lands_after: agent-harness#1222, agent-harness#1166
builds_on: plans/detailed-remote-sandbox-placement-896-20260929.md, plans/detailed-e2b-cloud-backend-896-20260929.md
---

# Detailed plan: review seats never run toolless — adopt one open-source sandbox, one seat-route resolver (agent-harness#1244)

## Task

agent-harness#1244, maintainer decisions of 2026-10-04. The issue is the source of truth and
is not restated here.

This plan sets the **policy** and the **resolver**, and **adopts** an existing open-source
process sandbox rather than building per-OS isolation ("this should not be rocket science").
It is harness-agnostic: the resolver and the sandbox treat every seat and executor harness in
`advisor_board/registries.py` alike (claude, codex, gemini/agy, grok, opencode, pi, cursor).
Harness-specific code is limited to thin adapters for credential delivery and CLI argv.

The work splits into bounded PRs:
- **PR-A (this plan, in full):** the resolver and policy. Sealed is removed as a fallback,
  degraded-not-run is typed, and the generic host-native fill and credential-source
  interfaces are defined.
- **PR-B (its own detailed plan, listed under follow-ups):** the adopted sandbox as the
  local backend.

Remote is agent-harness#896's existing placement seam. It is referenced here, not
redesigned.

## The chain (policy)

For every seat, whatever its harness, the resolver tries these in order:

1. **Local sandbox:** the adopted process sandbox (see "Sandbox selection"), used as
   agent-harness#896's `local` placement backend.
2. **Remote sandbox:** an agent-harness#896 placement backend. The self-hosted backend
   (plan 3: authenticated HTTPS, for example a tailnet or LAN host such as `ai` that can
   sandbox locally) comes first, then cloud (agent-harness#1165, E2B).
3. **Host-native fill:** the **host** harness fills the seat with its own sub-agent
   mechanism, with tools, whatever that host is (a Claude Code `Task`, a Codex
   `spawn_agent`, and so on). The seat is labelled a stand-in for its vendor and the
   president is told. Hosts with no sub-agent mechanism skip this step.
4. **Degraded, not run:** a typed notice and a fix line in the pre-launch mode line.

The seat is **never** toolless. The sealed (inlined, toolless) route survives only as an
explicit operator opt-in (`PHASE_LOOP_SEAT_ALLOW_SEALED` / `--allow-sealed-seat`, default
off). It is tried only after steps 1–3 all fail, and the mode line says
`sealed (operator opt-in)`.

The resolver is the choice of an agent-harness#896 placement backend per seat (`local`, then
`self-hosted`, then `cloud`, each checked with `PlacementBackend.available()`, where a
`PlacementUnavailable(code)` becomes a skipped step), followed by host-native fill and then
degraded.

## Sandbox selection

Each claim below was checked against the project's own README, source or registry on
2026-10-04 by a research pass. Cells marked "unverified" were not confirmed against primary
docs.

| Candidate | Linux | macOS | Windows | Unprivileged | FS allowlist | Egress domain allowlist | Wraps any CLI | License | Health | Install |
|---|---|---|---|---|---|---|---|---|---|---|
| **sandbox-runtime `srt`** ([anthropics/sandbox-runtime](https://github.com/anthropics/sandbox-runtime)) | bubblewrap + seccomp | Seatbelt | **alpha**: a dedicated sandbox account, WFP filters and a restricted token | yes; Windows needs one elevated install | yes (allow/deny read and write) | **yes**: built-in HTTP and SOCKS5 proxies with allowed/denied domains, deny by default | yes (`srt <cmd>`) | Apache-2.0 | npm 0.0.78, 2026-09-30; active | `npm i -g`; Linux also needs bwrap, socat and ripgrep |
| Codex CLI sandbox ([openai/codex](https://github.com/openai/codex)) | bubblewrap | Seatbelt | native (sandbox users, WFP, restricted token) | Windows elevated mode needs admin | yes | yes (`network-proxy`) | `codex sandbox <cmd>` | Apache-2.0 | active | **ships inside one vendor's CLI** |
| bubblewrap | yes | no | no | yes | yes | **no** (no network or loopback only) | yes | LGPL-2.1 | v0.13.0 | distro package |
| nsjail / firejail | yes | no | no | nsjail unverified; firejail is SUID (**no**) | yes | no | yes | Apache-2.0 / GPL-2.0 | active | build or package |
| Podman / Docker rootless | yes | via a VM | via WSL2 or a VM | yes, rootless (unverified) | mounts | not built in (unverified) | inside an image | Apache-2.0 | active | **high** (images, plus a VM on macOS and Windows) |
| Apple `container`, Lima/colima | via the host | macOS 26 on Apple silicon / yes | no | unverified | mounts | unverified | inside a VM | Apache-2.0 / MIT | active | medium |
| gVisor, Kata, Firecracker | Linux; Kata and Firecracker need KVM | no | no | gVisor `--rootless`; others need `/dev/kvm` | yes | no | as an OCI image | Apache-2.0 | active | medium to high |
| microsandbox ([superradcompany/microsandbox](https://github.com/superradcompany/microsandbox)) | KVM | Apple silicon | yes (WHP) | unverified | VM | yes (`allowed_hosts`) | `msb run <image> -- <cmd>` | Apache-2.0 | active | medium (microVM plus image) |
| E2B runtime (self-host) | Linux + KVM | no | no | unverified | yes | yes (nftables plus SNI/Host) | yes | Apache-2.0 | active | high; already planned as agent-harness#896 cloud (agent-harness#1165) |
| Daytona | — | — | — | — | — | — | — | unclear | **repository archived 2026-10-03** | out |

**Recommendation: `srt` is the one local sandbox on every OS** (decision S1). It is the only
maintained, standalone and harness-neutral candidate that covers Linux, macOS and Windows
without a container or VM, and that has both a filesystem allowlist and a domain egress
allowlist.
- **Linux:** it is bubblewrap, the same primitive as our jail (agent-harness#1166 and
  agent-harness#1222), so it fits the launch owner rather than replacing it.
- **Egress:** its proxy is deny-by-default, with a domain allowlist and a refusal of
  loopback and metadata addresses. That is the agent-harness#1170 shape, so the Gemini
  seat's egress question becomes configuration (decision S3).
- **Rejected alternatives:**
  - Codex's sandbox is equivalent, but it ships inside one vendor's CLI.
  - bubblewrap, nsjail, gVisor, Kata and Firecracker have no domain allowlist and are
    Linux-only.
  - Containers and VMs carry the highest install friction.

**Fallbacks:**
- **Windows:** `srt` is **alpha** there. It needs one elevated install, and it cannot open
  CLIs installed per user (nvm, Scoop, `pip --user`). It is the one local option to try.
  Where it is unusable, the seat goes to step 2: a tailnet or LAN host via agent-harness#896
  plan 3. microsandbox, which needs a microVM, is the alternative if a VM is acceptable
  (decision S2).
- **macOS:** `srt` uses Seatbelt. Where that fails, the seat goes to step 2.
- **Linux without user namespaces** (for example Ubuntu 24.04+ with
  `apparmor_restrict_unprivileged_userns=1`): step 2, with the sysctl named as the fix.

**Credentials (generic):**
- A `SeatCredentialSource` interface: `harness`, `kind` (`short_lived_login_token`,
  `api_key` or `oauth_files`), `present()` and `deliver(into)`.
- Each harness is one adapter. The Claude adapter wraps agent-harness#1166's
  `seat_credentials` (`resolve_claude_seat_credential`). The others (codex, gemini/agy, grok
  and the omnigent harnesses) are follow-ups.
- A harness with no adapter cannot take step 1 or step 2. It is skipped with
  `seat_credential_source_missing`.
- The remote path uses agent-harness#896's `one_shot_secret` channel, unchanged.

## Sequencing

- **PR-A lands after agent-harness#1222 and agent-harness#1166.** It consumes #1166's
  interface by symbol: `seat_jail.decide_seat_route`, `SeatRoute`, `SEALED_FALLBACK_CODES`,
  `panel_invoker._seat_route_for_spawn`, `_publish_seat_modes`, and `seat_preflight.SeatMode`
  / `SEAT_MODES`. #1166 does not adopt the resolver: it has had more than ten board rounds.
  Until PR-B lands, #1166's jail is step 1 on Linux for the harnesses it covers.
- **A premise in the brief is wrong:** #1166's amendment A3 does **not** make its fallbacks
  degraded. As written, a login-wait timeout and a missing login store run the seat sealed
  (`claude_seat_login_token_expiring`, `claude_seat_token_missing`), and A2's qualification
  failure also runs sealed. PR-A turns every `SEALED_FALLBACK_CODES` member into "step 1
  unavailable, reason=<code>" and continues the chain (decision D1).
- **The critical path to "never toolless" on hosts without a local sandbox** is
  agent-harness#896 plan 1a → plan 1b → plan 3 (self-hosted). Cloud is 1a → 1b →
  agent-harness#1165.
  - Until 1a lands, PR-A's step 2 is a shim that returns
    `seat_remote_sandbox_unconfigured`.
  - Once 1a lands, the shim is replaced by `sandbox_placement.resolve_backend`.
  - Once plan 3 lands, a tailnet host such as `ai` takes the seats.
  - Plan 3 states its own dependency on the seat jail for jailed launches.
- PR-B (srt) depends on 1a only to register as the `local` backend kind. It can start
  before 1b.

## Research summary

**Route choice on main is scattered** across predicates in `panel_invoker.py`:
- the board gates in `invoke_board` (`native_host_deferral_only`, `exact_broker_routes`);
- `_SANDBOX_INCAPABLE_BROKERED_LEGS` / `sandbox_usable_by`;
- the silent sealed fallback at the brokered spawn's
  `_render_broker_inline_prompt(..., staged_tree=None)`;
- the native-fill trio `native_agent_leg_request`, `preflight_native_leg_fills` and
  `apply_native_leg_fills`. The last accepts a same-model fill only on an
  `UNAVAILABLE/under_claude_code` leg.

**Native fill is detected for Claude Code only.**
- `_under_claude_code` checks `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT`, and
  `president_adapter.py` makes the same check.
- Generic pieces exist but nothing constructs them: `schema.HostContext.host_harness`,
  `identify_host_leg`, and the `NativeAgentLegRequest` docstring, which names Codex
  `spawn_agent`.
- `harness_env_signatures.py` already recognises a Codex host (`CODEX_THREAD_ID`).

**Native fill is refused under `heartbeat_only`.** `backing.resolve_review_monitoring_policy`
raises `review_monitoring_unsupported_route:native_fill`, so step 3 cannot run on current
boards (decision D2).

**Non-Linux boards are refused whole** by `backing.prepare_review_composition_authorization`
and the review-isolation authorization (decision D5).

**Governance on main:**
- `ratification_policy.py:100-105` sets `required_vendors` per gate.
- `_effective_vendors` does not count DEGRADED legs.
- `governed_premerge._MIN_USABLE_REVIEWERS = 2`, and the full quorum is deferred to
  agent-harness#375.
- `composition.board_independence` marks any repeated vendor family as degraded.
- Seat-count states are EC-REVIEWTRUTH-1 and EC-REVIEWTRUTH-4, and native counting is
  EC-REVIEWTRUTH-14.
- No stand-in field exists. The closest are the `_native_fill` metadata and `fallback_used`.

## Frozen vocabulary

Nothing frozen changes:
- `LEG_STATUSES` (`panel_invoker.py:194-201`) is unchanged, with no `NOT_RUN`. Degraded,
  not run is `DEGRADED` with zero spawns.
- `SEAT_MODES` is unchanged. agent-harness#896 adds `remote` when step 2 can resolve.

Additions only, each made the way its closed list already grows:
- notice codes in `seat_preflight.NOTICE_TEXT`;
- one detail template, `seat_not_run:<reason>`, under `advisor_board/CONTRACTS.md`
  "Leg `detail` vocabulary" (lines 470-489);
- the additive `SeatMode.stand_in_for` and `SeatMode.host_harness`.

Making the HARDEN sealed route opt-in is a CONTRACTS amendment entry (decision D4).

## Changes (PR-A)

### `phase-loop-runtime/src/phase_loop_runtime/seat_route.py` (create)

No existing home: #1166's `decide_seat_route` handles only the jail.

- `ResolvedSeatRoute` — add — a frozen dataclass:
  - `step`, one of `local | remote | host_native | degraded | sealed_opt_in`;
  - `mode`, a `SEAT_MODES` literal;
  - `code`;
  - `backend`, the agent-harness#896 backend name or None;
  - `stand_in_for`;
  - `host_harness`;
  - `tried`, a tuple of `(step, code)`.
- `resolve_seat_route(seat, *, local, remote, host, credential, allow_sealed)` — add — a pure
  function with the same logic for every harness, where every fact is an argument:
  - `local`: the outcome of step 1. Today that is #1166's `decide_seat_route`; after PR-B it
    is the srt backend's `available()`.
  - `remote`: a callable over the configured agent-harness#896 backends.
  - `host`: a `HostContext`.
  - `credential`: a `SeatCredentialSource` or None.
- The interim routes of specific harnesses are kept as inputs, not as branches:
  - the codex and grok `unconfined` route (tools on the staged tree) counts as a step-1
    outcome until PR-B (decision D6);
  - gemini skips step 1 with `gemini_seat_egress_unconfined` until srt egress or
    agent-harness#1170 lands.
- `remote_sandbox_probe(seat)` — add — a shim that returns `seat_remote_sandbox_unconfigured`
  until agent-harness#896 plan 1a. Its docstring names `sandbox_placement.resolve_backend` as
  the replacement.
- `SeatCredentialSource` (a Protocol) and `ClaudeLoginCredentialSource` (an adapter over
  #1166's `seat_credentials`) — add.
- `detect_host_harness(env)` — add — returns a `HostContext` from the existing signatures.
  Claude Code is identified by `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT`, and Codex by
  `CODEX_THREAD_ID` via `harness_env_signatures`.
- The registry flag `native_subagent: bool` per harness — add, in `registries.py` — it is
  true for claude and codex, and false elsewhere until verified.
- `sealed_opt_in_enabled(env)` — add — default off.

### `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py` (modify)

- `NOTICE_TEXT` — add these codes, each with what, why and fix:
  - `seat_not_run_no_tooled_route` (fix: "qualify the local sandbox, configure an
    agent-harness#896 remote, or run the board under a harness with sub-agents");
  - `seat_remote_sandbox_unconfigured`;
  - `seat_credential_source_missing`;
  - `seat_host_native_standin`;
  - `seat_sealed_operator_opt_in`.
- `SeatMode` — add the fields `stand_in_for` and `host_harness`. `render` prints `native
  (<host> stand-in for <vendor>)` or `sealed (operator opt-in)`.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- `_seat_route_for_spawn` (#1166) — delegate to `resolve_seat_route`.
- The brokered spawn's `staged_tree=None` branch — this branch becomes reachable only for
  `sealed_opt_in`. Any other path raises `seat_route_sealed_without_opt_in`.
- `invoke_board` per-seat launch — a `degraded` route produces a `DEGRADED`
  `PanelLegResult`, `seat_not_run:<reason>`, with zero spawns. A `host_native` route emits
  `native_agent_leg_request` for **any** host whose registry entry has `native_subagent`.
- `_under_claude_code` call sites — replace with `detect_host_harness(env).host_harness` plus
  the registry flag.
- `apply_native_leg_fills` / `preflight_native_leg_fills` — accept a model that differs from
  the seat only when `stand_in_for` is set. Record `stand_in_for`, `host_harness` and
  `filled_by_model` in `_native_fill`.
- `_publish_seat_modes` (#1166) — build the modes from the resolver, so every seat's step,
  stand-in label and fix print before the first spawn.
- `invoke_panel` / `invoke_panel_request` — use the same resolver.

### `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py` (modify)

- The Gemini heartbeat qualification board — it qualifies the sealed agy route itself, so it
  is the one sanctioned non-operator caller. It passes `allow_sealed=True` explicitly, and
  its mode line says so.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify; conditional)

- `resolve_review_monitoring_policy` — under D2 = (a), allow a resolver-produced host-native
  stand-in under `heartbeat_only`. Under (b), the seat keeps `UNAVAILABLE` /
  `under_claude_code`, so an out-of-band `--native-leg` fill still binds.
- The Linux-only gates (around lines 949 and 996) — under D5 = (a), make them a per-seat
  step-1 fact (`seat_local_sandbox_unsupported_os`) rather than a refusal of the whole board.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/president_adapter.py` (modify)

- `build_president_invoke` — the president's brief carries each seat's resolved route:
  step, backend, host, `stand_in_for` and the not-run reason. Its `_under_claude_code` check
  becomes `detect_host_harness`.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)

- `advisor-board` — add `--allow-sealed-seat`. The per-seat stderr mode line renders the new
  fields.

### `phase-loop-runtime/tests/test_seat_route.py` (create)

- A table over harness × host × facts:
  - every registry harness;
  - Linux with the jail, Linux without user namespaces, macOS, Windows;
  - a remote fake that is configured or absent;
  - Claude Code, Codex and no-sub-agent hosts;
  - the opt-in on and off.
- One falsifier per step.
- The sealed guard.
- A gathering test that drives the real call sites (`cli.py advisor-board`,
  `runner.py invoke_board(CODE_REVIEW_BOARD, …)`, `agy_qualification.py`, `invoke_panel`,
  `governed_review.py`) with fakes at the spawn seam.

## Governance (describe, do not invent)

PR-A changes no quorum rule:
- A degraded seat is DEGRADED, so it is not counted (`_effective_vendors`, and
  EC-REVIEWTRUTH-1 and -4 apply).
- A host-native stand-in counts as a seat of its **host's** vendor family. On a board that
  already seats that vendor, it is a repeat, and `board_independence` reports degraded.

Whether a labelled stand-in should count toward `required_vendors` is decision D3.

## Documentation impact

- `advisor_board/CONTRACTS.md` — add the section "Seat route resolver (agent-harness#1244)":
  the chain, sealed as opt-in only (D4), the notice codes and the detail template.
- `phase-loop-skills/advisor-board/SKILL.md` — replace the sealed-fallback wording with the
  chain.
- `CHANGELOG.md` — a behaviour change: a seat with no tooled route is not run, where before
  it ran sealed.
- `docs/outside-agent-conformance.md` — only if it describes sealed as a default (grep for
  "sealed").

## Dependencies & order

1. agent-harness#1222, then agent-harness#1166, land.
2. Decisions D1, D2, D4, D5 and D6 are settled. S1 to S3 gate only PR-B.
3. Within PR-A: notice codes → `seat_route.py` and its test → panel_invoker wiring →
   cli/president → docs.

## Verification

```bash
cd phase-loop-runtime
uv run pytest tests/test_seat_route.py tests/test_seat_notices.py tests/test_seat_jail*.py -q
uv run pytest tests -q -k "native_fill or monitoring_policy or board_independence or premerge"
grep -n "staged_tree=None" src/phase_loop_runtime/panel_invoker.py   # only the opt-in branch
grep -n "_under_claude_code" src/phase_loop_runtime/*.py src/phase_loop_runtime/advisor_board/*.py  # no route decision left on it
```

Edge cases:
- the jail becomes unqualified mid-board;
- the remote probe raises (typed, never sealed);
- the opt-in is set on a host whose sandbox works (it still runs sandboxed);
- every seat is degraded (BELOW-FLOOR, so the board never converges);
- the host is Codex (the stand-in is labelled `codex`).

Mutation receipts: one per step, one for the sealed guard, and one for host detection.

## Acceptance criteria

- [ ] For every registry harness, a seat with no local sandbox, no remote backend and no
  host sub-agent resolves to `degraded` / `seat_not_run_no_tooled_route` and makes 0
  spawns. Proven by `tests/test_seat_route.py`.
- [ ] With `PHASE_LOOP_SEAT_ALLOW_SEALED` unset, only `agy_qualification` reaches
  `_render_broker_inline_prompt(..., staged_tree=None)`. The guard test goes red when the
  raise is removed.
- [ ] A host-native fill is emitted under both a Claude Code host and a Codex host fake, and
  is labelled with `host_harness` and `stand_in_for`. A host without sub-agents skips the
  step.
- [ ] Every seat's mode is in `seat-modes.json` and on stderr before the first spawn, and the
  president brief carries the same routes.
- [ ] A diff check shows no change to `LEG_STATUSES`, `SEAT_MODES`,
  `DEFAULT_RATIFICATION_POLICIES` or `board_independence`.

## Maintainer decisions needed

- **S1:** adopt `srt` (sandbox-runtime, Apache-2.0) as the one local sandbox on every OS, as
  agent-harness#896's `local` backend wrapped at the agent-harness#1222 launch owner.
  Recommended. On Linux, does srt replace #1166's hand-built bwrap jail, or does the jail stay
  as the Linux backend until a parity check?
- **S2:** Windows: try srt (alpha, one elevated install, cannot open per-user-installed CLIs),
  then a tailnet host via plan 3; or adopt microsandbox (a microVM) on Windows.
- **S3:** use srt's egress proxy for the Gemini seat, in place of building the
  agent-harness#1170 proxy.
- **D1:** PR-A, not #1166, converts #1166's sealed fallbacks (A2 and A3) to degraded.
  Recommended.
- **D2:** host-native fill is refused under `heartbeat_only` (agent-harness#908 r4 (d)).
  (a) Allow resolver stand-ins (recommended), or (b) keep the refusal and fill out of band.
- **D3:** should a labelled stand-in count toward `required_vendors` and independence?
  Today it does not.
- **D4:** a HARDEN/CONTRACTS amendment to make sealed opt-in, and the opt-in's name.
- **D5:** non-Linux boards are refused whole today (agent-harness#1098). Make that a
  per-seat step-1 fact (recommended)?
- **D6:** may the codex and grok "unconfined" route (tools on the staged tree, no isolation)
  remain step 1 until srt covers them, or do they go to steps 2 → 3 → 4 now?

## Follow-ups (separate issues or plans)

- **PR-B:** a detailed plan for the srt local backend. It covers config generation from the
  seat's staged tree and egress allowlist, the per-OS prerequisite checks (bwrap, socat,
  ripgrep and the userns sysctl; Seatbelt; the Windows install), and qualification.
- Credential-source adapters for codex, gemini/agy, grok and the omnigent harnesses.
- A native-subagent capability probe per harness for opencode, pi, cursor and gemini.
- agent-harness#896 plans 1a, 1b and 3, which are the critical path, and agent-harness#1165
  (cloud).
- Removing the sealed opt-in once steps 1–3 cover the supported hosts.

## Execution Policy

- execute: effort=high, reason=security-relevant route selection across every board path
