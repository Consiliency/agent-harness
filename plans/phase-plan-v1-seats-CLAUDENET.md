---
phase_loop_plan_version: 1
phase: CLAUDENET
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 785e5ada02bc80319d23f9f5cfb577aa5fdefcb425cca9bf4f779962a01c16f9
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--python", "/usr/bin/python3", "--python-preference", "only-system", "--locked", "python", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seat_egress_allowlist_claude.py", "phase-loop-runtime/tests/test_seat_claude_credential_scope.py", "phase-loop-runtime/tests/test_seat_profile_claude_egress.py", "phase-loop-runtime/tests/test_seat_claude_containment.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_seat_egress_allowlists_jailcore.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_route.py", "phase-loop-runtime/tests/test_panel_invoker.py", "phase-loop-runtime/tests/test_seat_claude_provider_free.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py"]
---

# CLAUDENET: Claude Seat Egress and Row Qualification

## Context

This plan covers roadmap Phase 5 (CLAUDENET) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Exit criteria are EC-CLAUDENET-1 to EC-CLAUDENET-4, cited by ID only. The
roadmap is advisory (OD-1), so lanes land as governed PRs under principle 2.

**Inputs.**

- `plans/seats-jailcore-route-contract.md`, sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`: §1 profile and vendor
  rule, §2 step L7, §3 code classes, §5 key, §7 egress. JAILCORE registers the Claude
  `JailProfile` with `allowlist_id=None` and `deferred_to="EC-CLAUDENET-3"`. This phase does
  what §1 allows a vendor and nothing more: it sets that profile's egress and containment
  fields, adds one allowlist file and one `claude_seat_*` code with one additive
  `OD10_CLASSES` entry, and adds the Claude window rows as data on the profile. No core
  builder, resolver or window-kit code changes.
- CLAUDE: IF-0-CLAUDE-1 (transport admission), IF-0-CLAUDE-2 (W0 records and their
  `request_set`), the OD-3b section of the print-route decision record, and
  `plans/seats-claude-sdk-worker-contract.md` as EC-CLAUDE-3 pins it (worker sandbox,
  continuous admission audit).
- TEAMHOST: IF-0-TEAMHOST-1, IF-0-TEAMHOST-3 (gate 1b covers Claude once it has an
  allowlist), IF-XR-1 and contract §6 item 5 (the idle bound applies before the splice only).
  These are consumed by ID, and no TEAMHOST digest is pinned.
- IF-0-FIRSTSEAT-1, IF-0-FIRSTSEAT-2 and IF-0-FIRSTSEAT-3.

**The change.** The jailed Claude CLI moves from the shared public-internet namespace to the
proxy-only namespace the Gemini seat uses, through one per-seat proxy bound to the Claude
allowlist. The same single digest change adds `DISABLE_UPDATES=1` (agent-harness#1804).

**Design decisions.**

- **Allowlist source.** Rows are derived mechanically from W0 records, by the IF-0-CLAUDENET-2
  rule. A developer-host turn (`VM`, principle 5) confirms them and measures two things W0
  does not: the token endpoint, and which W0 hosts a canonical review can do without. `VM`
  never adds an `allow` row.
- **Refresh.** The seat receives only an access token over the token pipe (`seat_credentials`
  never delivers a refresh token). No allow rule matches the token endpoint, and after launch
  a credential-file check detects any persisted login (IF-0-CLAUDENET-3). `proxy.mjs` is not
  edited.
- **Credential scope.** This phase measures and records the scope. It adds no precondition.
- **SDK worker.** It is unchanged: `--unshare-net`, with no proxy, no CA and no exception. Its
  boundary receipt binds `profile_digest` and the schema-defined shared proof regions changed by
  SL-2. If `sdk` is admitted on SL-2's landing base or head, SL-2 runs the worker contract's
  final-head `VB`/`VL`, renews the committed and packaged `receipt-v1.json` byte-identically, and
  passes the base-tree continuous admission audit. Missing or stale proof blocks the PR.
- **Release declaration (IF-XR-1).** This phase specifies Claude's declaration content as
  exactly what TEAMHOST SL-8 specifies. The CA bind and the environment are not release files,
  so nothing new goes to Consiliency/dotfiles.
- **Resource caps.** Seat launches keep their per-seat cgroup caps. No lane changes a cap or
  adds a resource control.
- **No-transport branch.** If the OD-3b section records no admitted transport, SL-1 to SL-3
  do not run, and SL-4 records OD-9 (`remote-pending`).

## Interface Freeze Gates

- [ ] IF-0-CLAUDENET-1 — The Claude profile change. Only these fields of the registered
  Claude `JailProfile` change. The transport argv, `variant`, `token_fd`, `projection`,
  `config_surface`, `preconditions`, `auth_probe` and `output_secret_code` keep their JAILCORE
  values.

  | Field | New value |
  |---|---|
  | `owner_binds` | adds `--ro-bind <egress-ca> /seat/egress-ca.pem`, in Gemini's form |
  | `env` | adds `HTTPS_PROXY=<proxy url>`, `NODE_EXTRA_CA_CERTS=/seat/egress-ca.pem` and `DISABLE_UPDATES=1`; no `NO_PROXY`, `HTTP_PROXY` or `ANTHROPIC_*` |
  | `digest_placeholders`, `mount_points` | cover `<egress-ca>` and `<egress-proxy>` as Gemini's do |
  | `allowlist_id` | `claude` |
  | `credential` | `CredentialDelivery("token_fd", "claude-credential-scope")` |
  | `containment` | `ContainmentEvidence("claude-credential-scope", "claude-refresh-detection", "claude-unlisted-endpoint", None)` |
  | `notice_codes` | adds `claude_seat_token_refreshed_in_jail` |
  | `window` | `CLAUDE_WINDOW_ROWS` |

  `CLAUDE_WINDOW_ROWS` is `WindowRows` data only (contract §1). Its record fields are
  `canonical_claude`, `claude_route` and `claude_transport`, and its route literal is
  `jailed`. Its tree rows are the profile's `config_surface.planted_paths`, unchanged. Its
  locations are `tree` (`/seat/tree`, also the workdir per `seat_cwd`), `home` (`/seat/home`)
  and `provider_config` (`/seat/home/.claude`).

  It is one digest change. `jail_profile_digest("claude")` changes once on each arch. The
  same PR regenerates the Claude entries of `tests/data/seat_profile_digests_jailcore.json`
  with `python -m phase_loop_runtime.seat_profiles digest-receipt`. Its CHANGELOG entry and the
  readiness Claude row name the window: "requalifies in the first Claude row window after the
  EC-CLAUDENET-3 receipts land" (EC-CLAUDENET-4).

  At launch, JAILCORE's call sites start one `start_proxy(allowlist_id="claude")` per seat and
  launch the seat in `isolated_network(..., proxy_socket=...)`, as for Gemini, for every
  admitted transport. The probe view (`qualify("claude")`) and the production view agree on
  env, binds and namespace.
- [ ] IF-0-CLAUDENET-2 — `seat_egress/claude-allowlist.json`. Schema
  `phase_loop_seat_egress_allowlist.v1`, `leg: "claude"`, id `claude`, loaded only through
  `allowlist_ref("claude")`. Its `measured` string names the CLI version and the W0
  `evidence_digest`.
  - **Source.** A record is a source when all of these hold: its `arm` is a transport
    admitted on SL-1's base (`print` or `sdk`; `tui` only through the CLAUDETUI amendment to
    EC-CLAUDENET-1), its `canonical_output` is `admitted`, and its `request_set.completeness`
    is `complete`. `t3-sdk-control` records are never a source. If an admitted transport has
    no source record, SL-1 stops.
  - **Mapping.** Each entry `(method, host, path_template)` gives one rule with `port` 443. A
    template without `{id}` gives `path`. A template with `{id}` gives a `path_prefix` that
    runs up to its first `{id}` segment. If that prefix would be `/`, SL-1 stops.
  - **Refused set.** Every source entry is either an `allow` rule or has its host in
    `measured_and_refused`. A host moves to refused only when `VM` completes a canonical
    review with that host refused. A host is never in both lists.
  - **Shape.** No `allow` host carries a wildcard, no `path_prefix` is `/`, and no `allow` host
    appears in any other `seat_egress/*-allowlist.json`.
  - **Token endpoint.** The token endpoint `VM` measures is recorded in
    `allowlist-probes.json`. It matches no `allow` rule, and its host is refused unless that
    host is an allowed host.
- [ ] IF-0-CLAUDENET-3 — Refresh detection and the new code.

  ```python
  # seat_claude_containment.py
  CLAUDE_CREDENTIAL_FILES: tuple[str, ...] = (".credentials.json",)  # under seat-home/.claude
  def refreshed_in_jail(seat_home_fd: int) -> bool
  ```

  It reads from the host side before teardown, without following links. It returns true when
  any listed entry exists, of any file type. SL-1's `VM` may add a path where the pinned CLI
  persists a renewed login, and no lane removes one. The post-launch order, the same for every
  transport, ends the leg at its first match:
  1. `claude_seat_token_in_output` (unchanged);
  2. `refreshed_in_jail` gives `claude_seat_token_refreshed_in_jail`;
  3. the transport's existing classification.

  | Code | Class | Raised | Fix (gist) |
  |---|---|---|---|
  | `claude_seat_token_refreshed_in_jail` | security | post-launch | report the outcome privately; the seat stays degraded |

  The code is terminal. It lives in `seat_jail.NOTICES` and has one additive `OD10_CLASSES`
  entry. No existing entry changes, and neither do `DESCEND_CODES`, `REMOTE_DESCEND_CODES`,
  `CAPACITY_CODES` or `claude_seat_transport.CODES`.

## Lane Index & Dependencies

SL-1 — Allowlist and credential scope (lane B, part 1)
  Depends on: (none)
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: yes

SL-2 — Claude profile change (lane A)
  Depends on: SL-1
  Blocks: SL-3, SL-4
  Parallel-safe: no

SL-3 — Containment receipts (lane B, part 2)
  Depends on: SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Row window and documentation reducer (SL-docs)
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Allowlist and credential scope (lane B, part 1)

- **Scope**: Derive and ship the Claude allowlist from W0, prove its refusals at the proxy, and record the credential scope.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_egress/claude-allowlist.json`, `phase-loop-runtime/tests/test_seat_egress_allowlist_claude.py`, `phase-loop-runtime/tests/test_seat_claude_credential_scope.py`, `plans/evidence/seat-claude/allowlist-probes.json`, `plans/evidence/seat-claude/credential-scope.json`
- **Interfaces provided**: IF-0-CLAUDENET-2; evidence id `claude-credential-scope`
- **Interfaces consumed**: IF-0-JAILCORE-2 `allowlist_ref` and `start_proxy(*, allowlist_id)` (pre-existing), IF-0-CLAUDE-2 records (pre-existing), `seat_credentials.resolve_claude_seat_credential` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seat_egress_allowlist_claude.py` | The IF-0-CLAUDENET-2 shape rules. The committed `allow` equals the mapping of the committed source records, less the refused hosts, and every source entry is allowed or refused. Fixture W0 records cover an `{id}` prefix, a `/` prefix stop, a control record that is ignored, and a `partial` set that is refused. The token-endpoint probe is path-entered through the real proxy and reaches no fixture upstream; adding one fixture rule that matches its exact method, host and path turns this case red by reaching the upstream. Every probe row is path-entered through the real `proxy.mjs` under `start_proxy(allowlist_id="claude")`: allowed rows reach a fixture upstream, while refused, unlisted, Gemini-listed and Codex-listed hosts do not. `gemini-allowlist.json` bytes are unchanged. Repo-only reads skip on an installed wheel. | `V1` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_egress/claude-allowlist.json` | — | — |
| SL-1.3 | test | SL-1.2 | `phase-loop-runtime/tests/test_seat_claude_credential_scope.py` | The record holds the source vocabulary, scope names, `refresh_token_delivered: false` and counts, and nothing token-shaped. Path-entered through `resolve_claude_seat_credential` with a synthetic store, the delivered `SeatCredential` carries no refresh token. | `V1` |
| SL-1.4 | verify | SL-1.3 | SL-1 files | `VM` runs one canonical review per admitted transport, with IF-0-CLAUDENET-1's proxy and CA variables, through the proxy with this allowlist and the refused hosts refused. It also measures the token endpoint and the persisted-login path. Then all SL-1 tests run. | `V1`, `VM` |

**STOP conditions.** SL-1 stops and reports the exact sentence to change in three cases. If a
canonical review cannot complete with only the W0-derived rows, or an admitted transport has
no source record, the sentence is in EC-CLAUDENET-1. If the pinned CLI does not trust the
seat CA through `NODE_EXTRA_CA_CERTS`, the sentence is in IF-0-CLAUDENET-1.

### SL-2 — Claude profile change (lane A)

- **Scope**: Land IF-0-CLAUDENET-1 and IF-0-CLAUDENET-3 as the phase's one Claude digest change.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_claude_containment.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/test_seat_profile_claude_egress.py`, `phase-loop-runtime/tests/test_seat_claude_containment.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json`, `phase-loop-runtime/src/phase_loop_runtime/data/claude_sdk/receipt-v1.json`
- **Interfaces provided**: IF-0-CLAUDENET-1, IF-0-CLAUDENET-3; evidence id `claude-refresh-detection` (named; SL-3 records it)
- **Interfaces consumed**: IF-0-CLAUDENET-2 (SL-1), IF-0-JAILCORE-1 Claude registration (pre-existing), IF-0-JAILCORE-2 (pre-existing), IF-0-CLAUDE-1 (pre-existing), the profile-sourced window kit `seat_window` (pre-existing), the SDK worker launcher and receipt verifier (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_seat_profile_claude_egress.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py` | Field values. A field-by-field comparison with the base profile, captured before any edit, shows only the IF-0-CLAUDENET-1 fields differ. The digest data file's Claude entries equal `digest-receipt`. Path-entered through `_default_spawn`, a `print` and an `sdk` launch each use the proxy-only namespace and one proxy per seat. Mutation control: with `allowlist_id` unset, L7 takes `open egress` before expiry and `seat_route_exception_expired` after it (injected clock). The probe and production views agree. `CLAUDE_WINDOW_ROWS` reach the kit with no kit-code edit. The SDK worker argv keeps `--unshare-net` and carries no proxy or CA variable. | `V2` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json` | — | — |
| SL-2.3 | test | SL-2.2 | `phase-loop-runtime/tests/test_seat_claude_containment.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_panel_invoker.py` | The code has a what/why/fix row, its class and one additive `OD10_CLASSES` entry. Removing it leaves `OD10_CLASSES` equal to its base. `refreshed_in_jail` is false when nothing exists, and true for a regular file, a link or a directory, read without following links. Path-entered through `_exec_jailed_claude_leg` with a fixture transport, for `print` and `sdk`: a token in output wins over a credential file, a credential file gives the refresh code, and neither gives the transport's classification. | `V3` |
| SL-2.4 | impl | SL-2.3 | `phase-loop-runtime/src/phase_loop_runtime/seat_claude_containment.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | — | — |
| SL-2.5 | verify | SL-2.4 | SL-2 files | All SL-2 tests, inventory checks and `audit-order` on the final head. If `claude_seat_sdk.ADMITTED` is true on the landing base or head, run the worker contract's `VB`/`VL`, renew both receipt copies byte-identically, verify their installed-package binding, and rerun the continuous base-tree audit. Missing, skipped, stale or zero-collection proof blocks landing. | `V2`, `V3`, `V4`, conditional `VB`, conditional `VL` |

**`panel_invoker.py` scope.** The Claude leg's post-launch call (IF-0-CLAUDENET-3). If the base
still selects the Claude network namespace by leg rather than from `allowlist_id`, SL-2 makes
that one selection profile-driven. Nothing else.

### SL-3 — Containment receipts (lane B, part 2)

- **Scope**: Record EC-CLAUDENET-3's containment evidence on the changed profile, provider-free.
- **Owned files**: `phase-loop-runtime/tests/test_seat_claude_provider_free.py`, `phase-loop-runtime/tests/fixtures/claude_probe_provider.py`, `plans/evidence/seat-claude/refresh-detection.json`, `plans/evidence/seat-claude/unlisted-endpoint.json`, `plans/evidence/seat-claude/planted-config.json`, `plans/evidence/seat-claude/sdk-worker-network.json`
- **Interfaces provided**: evidence ids `claude-refresh-detection`, `claude-unlisted-endpoint`
- **Interfaces consumed**: IF-0-CLAUDENET-1, IF-0-CLAUDENET-3 (SL-2), IF-0-CLAUDENET-2 (SL-1), JAILCORE SL-3.6's Claude planted-config harness (pre-existing), the worker contract's network falsifiers (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_seat_claude_provider_free.py`, `phase-loop-runtime/tests/fixtures/claude_probe_provider.py` | `live_jail` cases. The fixture provider is bound in place of the CLI and launched through the real Claude profile. Requests to each refused host, an unlisted host and a Gemini-listed host through `HTTPS_PROXY` are refused. Direct DNS and IP connections have no route. A written `.claude/.credentials.json` ends the leg on `claude_seat_token_refreshed_in_jail`. JAILCORE SL-3.6's Claude planted-config falsifier runs on this digest for each admitted transport, and no planted marker loads. When `sdk` is admitted, the worker's external and planted host-loopback connections are refused on the installed release. Mutation control: a fixture allowlist that lists the unlisted host turns its case red. | `VL` |
| SL-3.2 | verify | SL-3.1 | SL-3 files | `VL` on the designated seat host, from `main` after SL-2. Each record holds metadata only and binds its `key_digest`. | `VL` |

### SL-4 — Row window and documentation reducer (SL-docs)

- **Scope**: Single writer of shared docs and inventories, and of the Claude row's window record.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/manifest.json`, `plans/evidence/seat-qualification/claude-row-*.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-CLAUDENET-1, IF-0-CLAUDENET-2, IF-0-CLAUDENET-3, IF-0-FIRSTSEAT-1 (pre-existing), IF-0-FIRSTSEAT-2 (pre-existing)
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | per catalog | On each landing: inventory rows for any changed launch reference, and an `[Unreleased]` CHANGELOG entry. After SL-2, CONTRACTS.md and the card state that Claude egress is confined to its allowlist through a per-seat proxy, that `DISABLE_UPDATES=1` is set, and the new code. The card drops "runs on open egress until CLAUDENET exits". |
| SL-docs.3 | docs | SL-docs.2 | `docs/review-seats-readiness.md`, `plans/evidence/seat-qualification/claude-row-*.json` | After SL-2, the Claude row reads `candidate`, with its allowlist id and digest, its exception ended by this phase, and the requalification note. The first Claude row window then runs through the profile-sourced kit on the OD-3b default, on the designated seat host only (LA-2, LA-3). Its record takes the row to `done-local`, or OD-9 routes it to `remote-pending`, citing the failed falsifier. In the no-transport branch, OD-9 applies directly. Comment closure on agent-harness#1804. |
| SL-docs.4 | verify | SL-docs.3 | — | `V5` and the hosted docs-freshness audit. |

## Execution Notes

- **Critical path to the date.** W0 (LA-3) is the first gate. If W0 holds a complete source
  record for at least one admitted native transport, SL-1 starts immediately and runs in
  parallel with the OD-3b record/default landing; SL-2, SL-3 and the Claude row window follow.
  If W0 has no admitted transport, wait only for OD-3b's no-transport record and take the
  no-transport branch. Once SL-2 is on `main`, L7 finds the allowlist, so the open-egress
  exception's 2026-12-04 UTC expiry no longer routes the seat. If SL-2 is not on `main` by then,
  the jailed Claude seat resolves degraded unless an owner record renews the exception
  (principle 3).
- **Content gates.** A lane starts when its base holds what it consumes, not when a whole
  upstream phase exits:
  - SL-1 needs IF-0-JAILCORE-2, the landed W0 records, and current transport-admission facts;
    it does not need OD-3b when at least one transport is admitted.
  - SL-2 needs JAILCORE's Claude registration and SL-1.
  - SL-3 needs SL-2.
  - The row window needs CLAUDE, JAILCORE and TEAMHOST to have exited, TEAMHOST for its
    interfaces, and it needs SL-3's receipts.
  - SL-1, SL-2 and SL-3 tests may be authored against their frozen interfaces before their
    landing gates open.
- **Stale-base guidance.** Lane teammates working in isolated worktrees do not see
  sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream
  dependency's merge>, it MUST stop and report rather than committing; the orchestrator will
  re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Batching.** If TEAMHOST SL-8's switch-on also returns the Claude row to `candidate`, one
  row window requalifies both changes. Neither waits for the other.
- **Open with JAILCORE (GROK plan S-2).** `seat_window.readiness_rows()` still names Claude
  `open egress`, and only the kit's owner may change that. Until the kit omits `open egress`
  for a profile with an allowlist, SL-4 records the exception's end in the readiness doc only.
  The first window, before 2026-12-04, does not need this fix. A Claude requalification after
  that date does.
- **Single writers.** `seat_jail.py`, `seat_route_contract.py`, `seat_profiles.py` and
  `panel_invoker.py` are shared with CODEX, GROK, PI, TEAMHOST and v11 PANELSPLIT, and the
  first two take additive rows only. Whichever lands second rebases. In either landing order,
  SL-2 adds only the Claude profile fields, notice row and post-launch call, and keeps TEAMHOST
  contract §8's `_prepare_jailed_claude` managed-subject seam and its Gemini-only profile edits.
  In the digest data file, SL-2 edits Claude entries only. `claude-allowlist.json` and the Claude profile fields are
  qualification-pinned, and this phase owns their digests (principle 4).
- **Shared-host limits.** Check `uptime` and `/proc/pressure/io` before each test command. Run
  targeted files serially under `timeout 900` without `-n`, with system python3.14.4 for jail
  tests. The full suite runs only in hosted CI and Gate A.
- **OD-10.** A containment finding met while executing is reported privately under the
  operator's private state, never in a PR, commit or test name.
- **Skill deviations (planning).** Reconnaissance ran in-thread because the context was already
  gathered. `advisor()` is unavailable here, so the plan goes to the cross-vendor review round.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`
- evidence paths: `plans/evidence/seat-claude/allowlist-probes.json`, `plans/evidence/seat-claude/credential-scope.json`, `plans/evidence/seat-claude/refresh-detection.json`, `plans/evidence/seat-claude/unlisted-endpoint.json`, `plans/evidence/seat-claude/planted-config.json`, `plans/evidence/seat-claude/sdk-worker-network.json`, `plans/evidence/seat-qualification/`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-CLAUDENET-1 — proven by `V1`, `V2` and `VL` (`test_seat_egress_allowlist_claude.py`, `test_seat_profile_claude_egress.py`, `test_seat_claude_provider_free.py`). Falsified by any of these: a jailed Claude seat or a jailed command reaching an unlisted host or a Gemini- or Codex-listed host; an `allow` rule with no W0 source entry; an SDK worker launch carrying a proxy or CA variable. Path-entered control: requests enter through the real `proxy.mjs`, and through a jailed command launched by `_default_spawn` on the real profile.
- [ ] EC-CLAUDENET-2 — proven by `V2` (`test_seat_profile_claude_egress.py`) and `V5` (the CHANGELOG and readiness text naming the window). Falsified by a field outside IF-0-CLAUDENET-1 differing from the base, by `DISABLE_UPDATES=1` missing from the jail environment, or by digest-data Claude entries that differ from `digest-receipt`. Path-entered control: the digest comes from `jail_profile_digest("claude")` and the real launch's `actual_profile_digest`.
- [ ] EC-CLAUDENET-3 — proven by `V3`, `VL` and the `plans/evidence/seat-claude/` records. Falsified by any of these: a persisted login that does not end the leg typed; an unlisted request that is not refused; a planted marker that loads on any admitted transport; an SDK worker connection to host loopback or the external network that succeeds. Path-entered control: the leg enters through `_exec_jailed_claude_leg`, the planted tree through `stage_review_tree`, and the worker through its owned launcher on the installed release.
- [ ] EC-CLAUDENET-4 — proven by the Claude row-window record `plans/evidence/seat-qualification/claude-row-*.json`. Falsified by a `done-local` Claude row with no window record on its current qualification key. Path-entered control: the exported record goes through `seat_window.verify_records`.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= uv run --quiet --project phase-loop-runtime
--group test --python /usr/bin/python3 --python-preference only-system --locked python -m
pytest -p no:cacheprovider -q`, with repo-relative file paths under
`phase-loop-runtime/tests/`. Every jail-touching selector uses `P` directly; it is never
re-expanded to bare `python3 -m pytest`. On this plan-only checkout the new test files are
absent, so these are pending selectors, not receipts.

- `V1`: `P test_seat_egress_allowlist_claude.py test_seat_claude_credential_scope.py test_seat_egress_allowlists_jailcore.py`
- `V2`: `P test_seat_profile_claude_egress.py test_seat_profiles.py test_seat_jail.py test_seat_route.py`
- `V3`: `P test_seat_claude_containment.py test_seat_notices.py test_seat_route_contract.py`, then `P test_panel_invoker.py -k claude`
- `V4`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`, then `timeout 300 python3 -m phase_loop_runtime.claude_seat_transport audit-order --base <pr base> --head HEAD --pr <pr>`
- `V5`: `P test_seat_reference_inventory.py`, then `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_seat_claude_provider_free.py -k live_jail --junitxml=<private-receipt>`. It is provider-free and runs on a host class with jail prerequisites. A skip or a zero collection fails.
- `VM`: `PHASE_LOOP_CLAUDE_MEASURE=1 P test_seat_egress_allowlist_claude.py -k measured_turn --junitxml=<private-receipt>`. It runs on a developer host with the developer's own login (principle 5) and is not a window.
- Full suite: hosted CI and Gate A only.
