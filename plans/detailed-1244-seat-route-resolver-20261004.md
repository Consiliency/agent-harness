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
2. **Remote sandbox:** one of two backends behind agent-harness#896's placement seam:
   - **self-hosted** (#896 plan 3): authenticated HTTPS to a tailnet or LAN host, such as
     `ai`, that can sandbox locally;
   - **E2B cloud** (#896 plan 4 = agent-harness#1165).

   They are tried in the order of a harness-agnostic config list,
   `[seat_route] remote_backends`. The default is `["self-hosted", "e2b"]` (ruled R1): the fleet tailnet/LAN host first, then E2B.
3. **Host-native fill:** the **host** harness fills the seat with its own sub-agent
   mechanism, with tools, whatever that host is (a Claude Code `Task`, a Codex
   `spawn_agent`, and so on). The seat is labelled a stand-in for its vendor and the
   president is told. Hosts with no sub-agent mechanism skip this step.
4. **Degraded, not run:** a typed notice and a fix line in the pre-launch mode line.

The seat is **never** toolless. The sealed (inlined, toolless) route survives only as an
explicit operator opt-in (`PHASE_LOOP_SEAT_ALLOW_SEALED` / `--allow-sealed-seat`, default
off; ruled D4). It is tried only after steps 1–3 all fail. Its mode line is loud: a
`WARNING:` prefix, `sealed (operator opt-in, NO TOOLS)`, and the env var to unset.
The agy qualification board is the one internal exemption.

The resolver picks an agent-harness#896 placement backend for each seat:
- first `local`;
- then each name in `remote_backends`, through `sandbox_placement.resolve_backend`.

It checks each one with `PlacementBackend.available()`. A `PlacementUnavailable(code)`
becomes a skipped step whose code is recorded. After the backends come host-native fill,
then degraded.

These symbols come from #896 plan 1a, which is being implemented now in lane
impl-896-1a. PR-A references them by name only.

**Non-Linux hosts (ruled D5).** The chain runs per seat on every OS. A host that cannot
sandbox locally skips step 1 with a typed code, so its seats go to remote/tailnet, then
native, then not run. This replaces refusing the whole board (agent-harness#1098).

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

**Ruled (S1–S3, 2026-10-04): `srt` is the adopted local sandbox, introduced OS by OS.** It is
the only maintained, standalone and harness-neutral candidate that covers Linux, macOS and
Windows without a container or VM, and that has both a filesystem allowlist and a domain
egress allowlist. Codex's sandbox is equivalent, but it ships inside one vendor's CLI.
bubblewrap, nsjail, gVisor, Kata and Firecracker have no domain allowlist and run only on
Linux. Containers and VMs carry the most install friction.

| OS | Step 1, local sandbox | Rule |
|---|---|---|
| **macOS** | **srt first** (Seatbelt) | S1. Where srt is unusable, go to step 2. |
| **Linux** | **agent-harness#1166's jail stays** until srt passes the Linux conformance suite below; then srt replaces it | S1 |
| **Windows** | **none yet**: seats go to step 2 (tailnet/LAN via #896 plan 3, or E2B). There is no Windows-specific sandbox work. Revisit srt when its Windows support leaves alpha. | S2 |
| Linux without user namespaces (e.g. Ubuntu 24.04+ with `apparmor_restrict_unprivileged_userns=1`) | none: step 2, with the sysctl named as the fix | — |

**Linux conformance suite (S1, a gate in PR-B).** srt must pass this suite before it replaces
the jail. The suite runs the same probes against both #1166's jail and srt, and srt must
match the jail on every row:
- **Capability bounding.** CapBnd is 0 inside the seat, carrying over #1166's invariant and
  its codex exception unchanged.
- **Private home.** The seat sees a private `$HOME`, not the host's, and no host
  credential store is readable.
- **Egress allowlist.** Only the allowlisted hosts answer, measured with real replies.
- **fd hygiene.** No inherited host fds beyond stdio and the declared channels.
- **uid isolation.** The seat runs under its own uid or namespace mapping, and it cannot
  signal or ptrace host processes.
- **No host-path leaks.** Only the staged tree and declared paths are visible. Host paths
  are absent from the environment, `/proc/self/mounts` and error text.

Each row has a mutation that turns it red, such as removing a bind-mount restriction or
widening the allowlist.

**Egress: srt's proxy for every seat that needs network (ruled S3; supersedes
agent-harness#1170).** srt's proxy is deny-by-default, with a domain allowlist and a refusal of
loopback and metadata addresses. It is the egress layer for every networked seat, including
a tooled Gemini seat. agent-harness#1170 is superseded, and PR-B closes it with a link. srt's
proxy is checked against what #1170 required:
- **(a)** only a short-lived access token enters the sandbox. This holds already on
  #1166's evidence and is re-checked under srt.
- **(b)** a containment probe with real replies: the agy inference host is reachable, and
  every other Google API host on the same front-end addresses is refused. This includes a
  request that tunnels through an allowed host but names another host inside TLS (SNI or
  Host).
- A mutation that widens the allowlist, or allows direct egress, turns the probe red.
- The proxy runs outside the seat, holds no credentials, and the seat cannot reconfigure it.
- The allowlist is measured from agy's real traffic, pinned as config, and not specific to
  the fleet.

**Ruled S4:** suppose (b)'s inner-host row shows that srt's plain CONNECT proxy cannot
block a request that tunnels through an allowed host but names another host inside TLS. Then
the tooled Gemini seat uses **srt's TLS-terminating proxy**. It does not fall back to a
remote-only Gemini. The requirements:
- **Interception CA:**
  - generated per host and owner-only: the key file is 0600 and its directory 0700;
  - trusted **only inside the seat's sandbox**, through the sandbox's own trust bundle or
    env, and never added to the host trust store.
- **The CA private key never enters the sandbox.** Only the CA certificate is mounted.
- **Inner check:** the proxy verifies the inner Host and SNI against the allowlist, and
  refuses on a mismatch.
- **Probe (b) passes with inspection on:** the allowed host is reachable, and a different
  Google API host is refused, with real replies.
- **Evidence:** the seat's evidence records `egress.tls_inspection: true|false`.

Each requirement has a mutation that turns it red:
- trusting the CA in the host store;
- mounting the key;
- skipping the inner-host check;
- dropping the evidence field.

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
  interface by symbol: `seat_jail.decide_seat_route`, `SeatRoute`,
  `panel_invoker._seat_route_for_spawn`, `_publish_seat_modes`, and
  `seat_preflight.SeatMode` / `SEAT_MODES`.
- **Ruled D1:** #1166 makes **its own** fallbacks degraded and not run. These are:
  - A2 qualification failure;
  - the A3 login-wait timeout, or the stored login vanishing;
  - `jail_unqualified`.

  PR-A does not duplicate that. It covers every other path, and its guard test asserts that
  after #1166 lands, no sealed-fallback code remains: no member of any `SEALED_FALLBACK_CODES`
  set, and no production path to `staged_tree=None` except the opt-in and the agy exemption.
- **The remote build order** follows agent-harness#896's plans, which are referenced, not
  restated:

  ```
  1a (seam; impl-896-1a) → 1b (execution driver + lease journal) ─┬─ 3   self-hosted (tailnet/LAN)
                                                                  └─ 4a1 → 4a2 → 4b   E2B (agent-harness#1165)
  ```

  After 1b, the two backends are independent. Either one, once landed, gives "never
  toolless" on hosts that have no local sandbox.
  - Until 1a lands, PR-A's step 2 is a shim that returns `seat_remote_sandbox_unconfigured`.
  - Once 1a lands, the shim is replaced by `resolve_backend`.
  - Plan 4b states the condition under which a seat runs inside the E2B VM. Plan 3's
    jailed launch depends on the seat jail.
- **PR-B (srt) depends on 1a** only to register as the `local` backend kind.

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
boards today; ruled D2 lifts it for resolver stand-ins.

**Non-Linux boards are refused whole** by `backing.prepare_review_composition_authorization`
and the review-isolation authorization; ruled D5 makes this per seat.

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

Making the HARDEN sealed route opt-in is a CONTRACTS amendment entry (ruled D4).

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
  - **ruled D6:** codex and grok keep their current tool-enabled staged route
    (`unconfined`) as their step-1 outcome until srt covers them. agent-harness#1222's
    owner adds namespaces and private homes in the meantime. Nothing regresses to
    toolless.
  - Gemini skips step 1 with `gemini_seat_egress_unconfined` until srt's egress proxy
    passes the #1170 checks above (S3). Until then it goes to steps 2, 3 and 4.
  - On Windows, every seat skips step 1 with `seat_local_sandbox_unsupported_os` (S2).
  - On Linux, step 1 is #1166's jail until the conformance suite passes (S1).
- `remote_sandbox_probe(seat, backends)` — add — walks `[seat_route] remote_backends` in
  order. Each name goes through `sandbox_placement.resolve_backend` and then
  `PlacementBackend.available()`. A `PlacementUnavailable(code)` is recorded in `tried`.
  - Until #896 1a lands, it is a shim returning `seat_remote_sandbox_unconfigured`.
  - It is harness-agnostic. A backend's own eligibility (for example E2B's `eligible_legs`)
    is that backend's `available()` answer, not a branch in the resolver.
- `[seat_route] remote_backends` — add, in `advisor_board/config.py` — a closed-value list of
  names (`self-hosted`, `e2b`). The default is `["self-hosted", "e2b"]` (ruled R1).
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
  (<host> stand-in for <vendor>)` or `WARNING: sealed (operator opt-in, NO TOOLS)` with the env var to unset.

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
- Seat evidence — add `placement` to each remote-placed leg: `backend`, `sandbox_id`,
  `created_at`, `confirmed_killed_at` and `duration_s`, taken from the #896 `ExecResult` and
  lease. This makes E2B spend auditable (R2). It is metadata only, not a new status.

### `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py` (modify)

- The Gemini heartbeat qualification board — it qualifies the sealed agy route itself, so it
  is the one sanctioned non-operator caller. It passes `allow_sealed=True` explicitly, and
  its mode line says so.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify)

#### `resolve_review_monitoring_policy` (ruled D2: lift the heartbeat refusal for resolver stand-ins only)

**The refusal being lifted.** agent-harness#908 board r4 (d) added
`review_monitoring_unsupported_route:native_fill`. Its reason, in the docstring, is that a
supplied fill must never be "bound as a usable OK under a policy that excludes it".
CONTRACTS "Review monitoring policy v1" lists "no native host seat".

**Why that no longer applies to a stand-in.** The reason protects heartbeat evidence: a
minted leg, single-use admission, frame receipt, and quiescence under runtime ownership. A
host-native process is not owned by the runtime and cannot produce that evidence. A
resolver stand-in never claims to:
- it is not a heartbeat leg;
- it records `review_monitoring.v1` with effective policy `host_native` and terminal reason
  `host_native_fill`;
- it carries no heartbeat evidence fields.

So no fill can be passed off as heartbeat evidence.

**Guards that replace the blanket refusal:**
1. Only a fill answering a **resolver-minted** `NativeAgentLegRequest` is accepted. The
   request id is bound to this board's operation and its `stand_in_for` is set. A
   caller-supplied fill (`native_leg_fills` with no resolver request) is still refused with
   the existing code.
2. The fill must match the request's `artifact_sha256`, `brief_sha256` and
   `composition_sha256`, which is the existing `_native_fill` provenance.
3. It is labelled as a stand-in everywhere, and counts as its own vendor (D3).
4. It has no deadline, which is consistent with heartbeat-only's no-deadline rule. A fill that
   never arrives is typed EMPTY or TIMEOUT under EC-REVIEWTRUTH-7, never OK.

#### `prepare_review_composition_authorization` and the review-isolation authorization (ruled D5)

These are the `platform.system() != "Linux"` gates, around lines 949 and 996. They stop
refusing the whole board. Non-Linux becomes the per-seat step-1 fact
`seat_local_sandbox_unsupported_os`, and the seat continues to step 2, then 3, then 4.

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

## Governance (ruled D3: a stand-in counts as its own vendor)

PR-A changes no quorum rule:
- A degraded seat is DEGRADED, so it is not counted (`_effective_vendors`,
  EC-REVIEWTRUTH-1/-4).
- A host-native stand-in counts as a reviewing seat of **its own** (the host's) vendor
  family, never the vendor it stands in for. `board_independence` therefore reports a repeat
  family as degraded, honestly.
- The stand-in label (`stand_in_for`, `host_harness`, `filled_by_model`) is recorded on the
  seat mode, in `_native_fill` provenance and in the president brief.

## Documentation impact

- `docs/advisor-board-capabilities-card.md` — add a "Remote seats" entry (R2):
  - the `remote_backends` order;
  - that E2B costs money per sandbox-second and has no runtime cap;
  - that the operator's guard is the E2B dashboard's spending-limits page and prepaid
    credits;
  - where the per-sandbox duration is recorded in the evidence.

- `advisor_board/CONTRACTS.md`:
  - add the section "Seat route resolver (agent-harness#1244)": the chain, the notice codes,
    the detail template and `remote_backends`;
  - **a HARDEN amendment entry (D4):** the HARDEN-era sealed route ("CLI seats cannot read
    files") is no longer a default or a fallback. It runs only on
    `PHASE_LOOP_SEAT_ALLOW_SEALED=1`, with the loud mode line, or on the agy qualification
    board;
  - **an amendment to "Review monitoring policy v1" (D2):** "no native host seat" gains the
    exception "except a resolver-minted, labelled stand-in, which is never heartbeat
    evidence".
- `phase-loop-skills/advisor-board/SKILL.md` — replace the sealed-fallback wording with the
  chain.
- `CHANGELOG.md` — two behaviour changes: a seat with no tooled route is not run, where before
  it ran sealed; and non-Linux boards now resolve seat by seat rather than being refused.
- `docs/` operator page for the remote step (it extends #896's docs rather than duplicating
  them):
  - **E2B key custody** follows plan 4's design exactly. The key is read at call time from the
    owner-only file `$XDG_STATE_HOME/phase-loop/credentials/e2b` (file 0600, directory 0700,
    `O_NOFOLLOW` plus `fstat`), and never from the process environment.
  - **Provisioning that file is the operator's job** (fleet dotfiles, from whatever secret
    store they use). The product documents only the file contract. Product code contains no
    secret-manager specifics.

## Dependencies & order

1. agent-harness#1222, then agent-harness#1166, land.
2. Every decision is ruled (D1–D6, S1–S4, R1, R2 and E2B).
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

- [ ] For every registry harness (a table test), a seat with no local sandbox, no remote backend and no
  host sub-agent resolves to `degraded` / `seat_not_run_no_tooled_route` and makes 0
  spawns. Proven by `tests/test_seat_route.py`.
- [ ] With `PHASE_LOOP_SEAT_ALLOW_SEALED` unset, only `agy_qualification` reaches
  `_render_broker_inline_prompt(..., staged_tree=None)`, and no sealed-fallback code is
  reachable after #1166 lands. The guard test goes red when the raise is removed.
- [ ] Under `heartbeat_only`, a resolver-minted stand-in fill binds with
  `review_monitoring.v1` effective policy `host_native`. A caller-supplied fill is still
  refused with `review_monitoring_unsupported_route:native_fill`.
- [ ] On a non-Linux host fake, the board is not refused. Each seat resolves through steps
  2, 3 and 4 with `seat_local_sandbox_unsupported_os` in `tried`.
- [ ] A host-native fill is emitted under both a Claude Code host and a Codex host fake, and
  is labelled with `host_harness` and `stand_in_for`. A host without sub-agents skips the
  step.
- [ ] Every seat's mode is in `seat-modes.json` and on stderr before the first spawn, and the
  president brief carries the same routes.
- [ ] An E2B-placed seat's evidence carries its sandbox duration (created and
  confirmed-killed times, seconds). With no `[e2b]` cap keys set, E2B is still available.
  Both are proven with a fake E2B backend.
- [ ] `remote_backends` is walked in config order, and an unavailable backend's
  `PlacementUnavailable` code is recorded in `tried`. Proven with fake self-hosted and e2b
  backends.
- [ ] A diff check shows no change to `LEG_STATUSES`, `SEAT_MODES`,
  `DEFAULT_RATIFICATION_POLICIES` or `board_independence`.

## Maintainer decisions

**Ruled 2026-10-04:**
- **D1:** #1166 makes its own fallbacks (A2, A3, `jail_unqualified`) degraded and not run.
  PR-A covers the rest and asserts that no sealed fallback code remains.
- **D2:** the heartbeat-only refusal of native fill is lifted, for resolver stand-ins only,
  with the guards above.
- **D3:** a stand-in counts as its own vendor (the current behaviour).
- **D4:** sealed is opt-in only, `PHASE_LOOP_SEAT_ALLOW_SEALED=1`, off by default, with a loud
  mode line and a HARDEN/CONTRACTS amendment. The agy qualification board is the one
  exemption.
- **D5:** non-Linux hosts resolve per seat (agent-harness#1098).
- **E2B is in this plan:** it is the second remote backend, with plan 4's key custody.

- **S1:** keep agent-harness#1166's Linux jail until srt passes the Linux conformance suite.
  macOS adopts srt first.
- **S2:** Windows uses tailnet offload (#896 plan 3) or E2B for now. There is no
  Windows-specific sandbox work; revisit srt when it leaves alpha.
- **S3:** srt's egress proxy serves every networked seat, including tooled Gemini.
  agent-harness#1170 is superseded, and its requirements are the check.
- **D6:** codex and grok keep their tool-enabled staged route until srt covers them. Nothing
  regresses to toolless.
- **R1:** the default is `[seat_route] remote_backends = ["self-hosted", "e2b"]`: the fleet
  tailnet/LAN host first, then E2B.
- **R2:** E2B gets **no runtime spending caps** for now. The operator's guard is E2B's
  account-side controls: prepaid credits, monthly overage billing with a payment method on
  file, the dashboard "spending limits" budget page, and an account that is blocked once
  credits run out with no payment method. Consequences:
  - PR-A ships no default caps and does **not** keep E2B unavailable pending caps.
  - This amends agent-harness#896 plan 4a1. That plan lists the CD3 caps
    (`max_concurrent_per_run`, `max_seconds_per_run`, `max_seconds_per_day`) as required
    `[e2b]` keys. Under R2 they become optional, and unset means no runtime cap. The
    amendment is recorded on plan 4 when 4a1 is implemented, not restated here.
  - Plan 4's per-sandbox TTL (`tier_max_lifetime_s`, `lease_ttl_s`) stays, as a **liveness
    bound, not a budget**.
  - Every E2B seat records its sandbox duration in the evidence (backend, sandbox id, created
    and confirmed-killed times, seconds), so spend is auditable.
  - The account-side spending limit is documented as the operator's guard in
    `docs/advisor-board-capabilities-card.md`.

- **S4:** if probe (b)'s inner-host row fails with the plain CONNECT proxy, the tooled
  Gemini seat uses srt's TLS-terminating proxy. The CA is per host, owner-only, trusted only
  inside the sandbox, and its key never enters the sandbox. The proxy checks the inner Host
  and SNI, probe (b) must pass with inspection on, and inspection is recorded in the
  evidence.

**Open:** none.

## Follow-ups (separate issues or plans)

- **PR-B:** a detailed plan for the srt local backend: macOS first, then the Linux conformance suite (S1), then Gemini egress against the #1170 checks (S3). Close agent-harness#1170 as superseded. It covers config generation from the
  seat's staged tree and egress allowlist, the per-OS prerequisite checks (bwrap, socat,
  ripgrep and the userns sysctl; Seatbelt), and qualification. Windows is out until srt leaves alpha (S2).
- Credential-source adapters for codex, gemini/agy, grok and the omnigent harnesses.
- A native-subagent capability probe per harness for opencode, pi, cursor and gemini.
- agent-harness#896 plans 1a, 1b, then 3 and 4a1 → 4a2 → 4b (agent-harness#1165), in
  parallel after 1b.
- Fleet dotfiles: provision `$XDG_STATE_HOME/phase-loop/credentials/e2b` from the operator's
  secret store. This is outside product code.
- Removing the sealed opt-in once steps 1–3 cover the supported hosts.

## Execution Policy

- execute: effort=high, reason=security-relevant route selection across every board path
